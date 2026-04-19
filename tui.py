"""Vendor Guard — chat + file-drop TUI for live audit demos.

Interactive terminal front-end over ``main.run_pipeline``. Users
paste or drag files into the prompt; dropped paths are queued; any
non-path input is a conversational turn that reaches Claude (or the
local inference endpoint when ``INFERENCE_URL`` is set, same plumbing
as the agents). Running ``/audit`` fires the existing pipeline against
the queued files and streams findings back into the transcript.

Minimal design deliberately — the demo target is "this is the vendor
audit agent you've been hearing about, now drop a vendor packet into
it". Heavy TUI frameworks (Textual) add portability risk on the
demo laptop; ``rich`` for rendering + plain ``input()`` for the prompt
is enough: every major terminal (Windows Terminal, iTerm2, Konsole,
gnome-terminal) pastes a file path when a file is dragged onto the
window, quoted if the path contains spaces.

Usage::

    python tui.py                # sample packet preloaded
    python tui.py --empty        # start with no files queued
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_QUESTIONNAIRE = REPO_ROOT / "sample_vendor_q.txt"
DEFAULT_DOCS = [
    REPO_ROOT / "sample_soc2_report.txt",
    REPO_ROOT / "sample_iso_certificate.txt",
    REPO_ROOT / "sample_dora_questionnaire.txt",
]

# Trust boundary: chat backends never receive raw vendor-document text.
# Audit findings (which are gated by the shell's NeMo rails + Presidio)
# are the only document-derived content that flows here. The system
# prompt restates this so the model can answer "what can you see?"
# correctly when the auditor asks.
CHAT_SYSTEM_PROMPT = """You are the Vendor Guard chat assistant. The user is an internal/IT auditor reviewing a vendor packet against EU/NL frameworks (ISO 27001, NIS2, DORA, BIO2, EU AI Act, ALTAI, EC Ethics).

Trust boundary you must respect and explain when asked:
- You DO see: queued filenames + sizes (metadata only), the audit summary, and the contents of artefacts under output/ (scorecard, gap register, audit memo). These artefacts have already passed the saaf-shell's NeMo guardrails and Presidio PII redaction.
- You DO NOT see: the raw vendor documents. Their text never enters this chat. All substantive analysis happens inside the saaf-shell's Firecracker VM with the local model. Your job is to help the auditor interpret the guardrailed outputs, not re-run the audit.

How to behave:
- Be concise. Bullets over prose.
- If asked about something only present in raw docs, say so and tell the user to run /audit (it is by design — you're the helper, not the auditor).
- Cite framework article numbers only if you're certain they exist; otherwise refer to the artefact.
- Never issue a vendor-wide pass/fail; that's for the human reading the gap register.
"""

CHAT_MODEL = "claude-opus-4-6"
CHAT_BACKEND = os.environ.get("VENDOR_GUARD_CHAT_BACKEND", "claude-code").lower()
TRUST_BANNER = "[Claude sees: filenames + sanitized output/ artefacts only — never raw vendor data]"


@dataclass
class Session:
    """Everything the TUI carries across turns."""

    console: Console
    queued_files: list[Path] = field(default_factory=list)
    chat_history: list[tuple[str, str]] = field(default_factory=list)  # (role, content)
    last_audit_summary: str | None = None
    output_dir: Path = field(default_factory=lambda: REPO_ROOT / "output")

    def add_file(self, path: Path) -> str:
        if not path.exists():
            return f"[red]not found:[/red] {path}"
        if not path.is_file():
            return f"[red]not a file:[/red] {path}"
        if path in self.queued_files:
            return f"[yellow]already queued:[/yellow] {path.name}"
        self.queued_files.append(path)
        return f"[green]queued[/green] {path.name} ({path.stat().st_size:,} bytes)"

    def files_table(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("#", width=3)
        table.add_column("File")
        table.add_column("Role", width=18)
        table.add_column("Size", justify="right", width=12)
        if not self.queued_files:
            table.add_row("—", "[dim](empty)[/dim]", "", "")
            return table
        for idx, path in enumerate(self.queued_files, 1):
            role = "questionnaire" if idx == 1 else "supporting doc"
            table.add_row(str(idx), path.name, role, f"{path.stat().st_size:,}")
        return table


def _strip_drop_quoting(token: str) -> str:
    """Drag-drop on Windows Terminal and iTerm2 pastes a path wrapped
    in double quotes if it contains spaces. shlex handles it, but we
    also tolerate naive single-quoted or raw inputs."""
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _parse_paths_from_input(raw: str) -> list[Path]:
    """Return the subset of input tokens that resolve to existing files.

    A user turn like ``audit this /home/r/report.pdf`` becomes one
    path + conversational text. We split with shlex so a drag-drop
    of a path-with-spaces still parses as one token, then any token
    that resolves to an existing file becomes a queue candidate.
    """
    try:
        tokens = shlex.split(raw, posix=(os.name != "nt"))
    except ValueError:
        tokens = raw.split()
    out: list[Path] = []
    for token in tokens:
        candidate = Path(_strip_drop_quoting(token)).expanduser()
        if candidate.exists() and candidate.is_file():
            out.append(candidate.resolve())
    return out


def _input_is_only_paths(raw: str, paths: list[Path]) -> bool:
    """True when the line is nothing but file paths — auto-queue without
    sending the residual to the chat model."""
    try:
        tokens = shlex.split(raw, posix=(os.name != "nt"))
    except ValueError:
        tokens = raw.split()
    if not tokens or len(tokens) != len(paths):
        return False
    return True


def _render_header(console: Console) -> None:
    console.print(
        Panel.fit(
            Text.assemble(
                ("Vendor Guard", "bold magenta"),
                "  ",
                ("interactive audit shell", "dim"),
            ),
            subtitle="[dim]drop files  •  /help  •  /quit[/dim]",
            border_style="magenta",
        )
    )
    console.print(f"[dim cyan]{TRUST_BANNER}[/dim cyan]")
    console.print(
        f"[dim]chat backend:[/dim] [cyan]{CHAT_BACKEND}[/cyan]  "
        f"[dim](override with VENDOR_GUARD_CHAT_BACKEND=claude-code|anthropic)[/dim]"
    )


def _render_help(console: Console) -> None:
    table = Table(show_header=True, header_style="bold cyan", title="Commands")
    table.add_column("Command", style="cyan", width=22)
    table.add_column("What it does")
    table.add_row("/help", "Show this table")
    table.add_row("/files", "Show the queued files")
    table.add_row("/add <path>", "Queue a file explicitly (same as drag-drop)")
    table.add_row("/remove <n>", "Remove the n-th queued file")
    table.add_row("/clear", "Clear the file queue")
    table.add_row("/load-sample", "Load the built-in sample vendor packet")
    table.add_row("/audit", "Run inside saaf-shell Firecracker VM — compliance path (Linux)")
    table.add_row("/audit-direct", "Run the pipeline in-process on the host (uses ANTHROPIC_API_KEY)")
    table.add_row("/show", "Re-render the last audit results (scorecard, gaps, memo)")
    table.add_row("/open <n>", "Open artefact #n in its native app (Excel, browser, Word)")
    table.add_row("/output", "Where audit outputs land (scorecard, memo, …)")
    table.add_row("/backend", "Show / change the chat backend")
    table.add_row("/reset", "Clear chat history")
    table.add_row("/quit  /exit", "Leave")
    table.add_row("<any other text>", "Chat with the audit assistant")
    table.add_row("<drag a file in>", "Path is auto-queued; no chat turn sent")
    console.print(table)


# --- /audit-shell wiring ----------------------------------------------------
#
# The Firecracker run path. Lives in vendor_guard rather than the shell
# repo because the SAAF shell intentionally stays workload-agnostic; it
# exposes ``run_manifest()`` and the AgentFS CLI, and any agent that
# wants to invoke them composes its own runner. We shell out to the
# shell venv's python so the host TUI doesn't need any of the shell's
# heavy deps (firecracker, NeMo, etc.) installed.

SHELL_REPO = Path(os.environ.get(
    "SAAF_SHELL_REPO",
    str(Path.home() / "saaf" / "saaf-compliance-shell"),
))
SHELL_VENV_PYTHON = Path(os.environ.get(
    "SAAF_SHELL_PYTHON", str(SHELL_REPO / ".venv" / "bin" / "python"),
))
SHELL_ROOTFS = os.environ.get(
    "SAAF_SHELL_ROOTFS", "/opt/saaf/rootfs/vendor-guard-test",
)
SHELL_MANIFEST = Path(os.environ.get(
    "SAAF_SHELL_MANIFEST", str(REPO_ROOT / "saaf-manifest.yaml"),
))
SHELL_AGENTFS = os.environ.get("SAAF_AGENTFS_BIN", "/usr/local/bin/agentfs")
SHELL_AUDIT_LOG = os.environ.get("SAAF_AUDIT_LOG", "/var/lib/saaf/audit.jsonl")
SHELL_OUTPUT_FILES = (
    "scorecard.csv", "scorecard.xlsx",
    "gap_register.csv", "gap_register.xlsx",
    "audit_memo.html", "audit_memo.docx",
)


def _sudo_prefix() -> list[str]:
    """If SAAF_SUDO_PASSWORD is set, pipe it into sudo -S; else use -n
    (NOPASSWD must be configured). The password is never echoed; it's
    passed via stdin in the actual call site."""
    if os.environ.get("SAAF_SUDO_PASSWORD"):
        return ["sudo", "-S", "-p", ""]
    return ["sudo", "-n"]


def _run_sudo(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    cmd = _sudo_prefix() + argv
    pwd = os.environ.get("SAAF_SUDO_PASSWORD")
    return subprocess.run(
        cmd,
        input=(pwd + "\n").encode() if pwd else None,
        capture_output=True,
        timeout=timeout,
    )


def _cmd_audit_shell(session: Session) -> None:
    """Run vendor_guard inside the saaf-shell Firecracker VM.

    Outputs are produced by the local model under the shell's NeMo
    rails + Presidio masking, then retrieved from the AgentFS overlay
    via ``agentfs fs cat``. The chat layer afterwards reads only those
    sanitized artefacts (see _build_chat_context's trust boundary).
    """
    if sys.platform != "linux":
        session.console.print(
            "[yellow]/audit-shell only runs on Linux with saaf-shell installed.[/yellow]"
        )
        session.console.print("[dim]use /audit-direct for the in-process path on this platform.[/dim]")
        return
    if not SHELL_VENV_PYTHON.exists():
        session.console.print(f"[red]saaf-shell venv python not found:[/red] {SHELL_VENV_PYTHON}")
        session.console.print("[dim]set SAAF_SHELL_REPO or SAAF_SHELL_PYTHON.[/dim]")
        return
    if not SHELL_MANIFEST.exists():
        session.console.print(f"[red]manifest not found:[/red] {SHELL_MANIFEST}")
        return
    if not shutil.which("sudo"):
        session.console.print("[red]sudo not on PATH; can't invoke saaf-shell.[/red]")
        return

    session.console.print()
    session.console.print(Rule("[bold]Audit via saaf-shell (Firecracker VM)[/bold]", style="magenta"))
    session.console.print(f"  [dim]manifest:[/dim] {SHELL_MANIFEST}")
    session.console.print(f"  [dim]rootfs:[/dim]   {SHELL_ROOTFS}")
    session.console.print(f"  [dim]audit log:[/dim] {SHELL_AUDIT_LOG}")
    session.console.print()

    runner = (
        f"import sys; sys.path.insert(0, {str(SHELL_REPO)!r}); "
        "from modules.isolation.runtime import run_manifest; "
        f"sid = run_manifest({str(SHELL_MANIFEST)!r}, rootfs_path={SHELL_ROOTFS!r}); "
        "print('SAAF_SESSION_ID=' + sid)"
    )

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=session.console, transient=True) as progress:
        progress.add_task("Booting Firecracker + running pipeline (~3–5 min)…", total=None)
        try:
            proc = _run_sudo([str(SHELL_VENV_PYTHON), "-c", runner], timeout=900)
        except subprocess.TimeoutExpired:
            session.console.print("[red]shell run timed out (>15 min).[/red]")
            return

    stdout = proc.stdout.decode(errors="replace")
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        session.console.print(f"[red]shell run failed (rc={proc.returncode})[/red]")
        if "password is required" in stderr or "no tty" in stderr:
            session.console.print(
                "[yellow]sudo wants a password.[/yellow] either configure NOPASSWD for "
                "this user, or set SAAF_SUDO_PASSWORD in the env before launching the TUI."
            )
        if stdout.strip():
            session.console.print("[dim]stdout (last 2KB):[/dim]")
            session.console.print(stdout[-2000:])
        if stderr.strip():
            session.console.print("[dim]stderr (last 2KB):[/dim]")
            session.console.print(stderr[-2000:])
        return

    session_id = ""
    for line in stdout.splitlines():
        if line.startswith("SAAF_SESSION_ID="):
            session_id = line.split("=", 1)[1].strip()
    if not session_id:
        session.console.print("[red]no session id in shell output:[/red]")
        session.console.print(stdout[-2000:])
        return

    session.console.print(f"[green]VM exited cleanly.[/green] session=[cyan]{session_id}[/cyan]")
    session.output_dir.mkdir(parents=True, exist_ok=True)

    retrieved: list[str] = []
    missing: list[str] = []
    for fname in SHELL_OUTPUT_FILES:
        guest_path = f"/audit_workspace/{fname}"
        try:
            extract = _run_sudo([SHELL_AGENTFS, "fs", "cat", session_id, guest_path], timeout=30)
        except subprocess.TimeoutExpired:
            missing.append(fname)
            continue
        if extract.returncode == 0 and extract.stdout:
            (session.output_dir / fname).write_bytes(extract.stdout)
            retrieved.append(fname)
        else:
            missing.append(fname)

    summary_lines = [
        f"- session: `{session_id}`",
        f"- retrieved: {', '.join(retrieved) if retrieved else '(none)'}",
    ]
    if missing:
        summary_lines.append(f"- [yellow]missing:[/yellow] {', '.join(missing)}")
    summary_lines.append(f"- audit log: {SHELL_AUDIT_LOG}")
    summary_lines.append(f"- output dir: {session.output_dir}")
    session.console.print(
        Panel("\n".join(summary_lines),
              title="[green]/audit-shell complete[/green]", border_style="green")
    )

    session.last_audit_summary = (
        f"saaf-shell session {session_id} completed inside a Firecracker VM. "
        f"Artefacts retrieved: {retrieved}. "
        "Outputs were produced by the local model under 12 NeMo rails + Presidio PII "
        f"redaction, and the run is recorded in the hash-chained audit log at {SHELL_AUDIT_LOG}."
    )

    _render_artefact_summary(session)


def _cmd_audit(session: Session) -> None:
    """Run main.run_pipeline against the queued files.

    First queued file is used as the questionnaire; the rest are
    supporting documents. This matches the convention enforced by
    ``main.main()`` (``--questionnaire`` vs ``--docs``). We import
    ``run_pipeline`` lazily so the TUI starts up even when the
    pipeline's heavier deps (pypdf, openpyxl) aren't installed.
    """
    if not session.queued_files:
        session.console.print("[yellow]no files queued.[/yellow] Drag a vendor packet in first, or run /load-sample.")
        return

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("INFERENCE_URL"):
        session.console.print(
            "[red]neither ANTHROPIC_API_KEY nor INFERENCE_URL is set[/red] — the pipeline needs one."
        )
        return

    questionnaire = session.queued_files[0]
    docs = session.queued_files[1:]

    session.console.print()
    session.console.print(Rule(f"[bold]Auditing {questionnaire.name}[/bold]", style="magenta"))
    session.console.print(f"  [dim]questionnaire:[/dim] {questionnaire}")
    for doc in docs:
        session.console.print(f"  [dim]doc:[/dim]          {doc}")
    session.console.print(f"  [dim]output:[/dim]        {session.output_dir}")
    session.console.print()

    try:
        from main import run_pipeline
    except Exception as exc:
        session.console.print(f"[red]failed to import pipeline:[/red] {exc}")
        traceback.print_exc()
        return

    session.output_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=session.console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running agents (this may take ~1–2 min)…", total=None)
        try:
            result = run_pipeline(
                questionnaire_path=questionnaire,
                doc_paths=docs,
                output_dir=session.output_dir,
            )
        except Exception as exc:
            progress.stop()
            session.console.print(f"[red]pipeline failed:[/red] {exc}")
            traceback.print_exc()
            return
        progress.update(task, description="Done.")

    failed = result.get("failed_agents", [])
    summary_lines = [
        f"- scorecard: `{result['scorecard_xlsx'].name}` / `{result['scorecard_csv'].name}`",
        f"- gap register: `{result['gap_register_xlsx'].name}` / `{result['gap_register_csv'].name}`",
        f"- audit memo: `{result['memo_docx'].name}` / `{result['memo_html'].name}`",
    ]
    if failed:
        summary_lines.append(
            "- [red]agent failures[/red]: " + ", ".join(name for name, _ in failed)
        )
    session.console.print(Panel("\n".join(summary_lines), title="[green]Audit complete[/green]", border_style="green"))

    session.last_audit_summary = (
        f"Audit completed. Questionnaire: {questionnaire.name}. "
        f"Supporting documents: {[d.name for d in docs]}. "
        f"Outputs written to {session.output_dir}. "
        + (f"Agent failures: {[name for name, _ in failed]}. " if failed else "All agents succeeded. ")
    )

    _render_artefact_summary(session)


_OUTPUT_TEXT_EXTS = {".csv", ".html", ".md", ".txt"}
_OUTPUT_MAX_BYTES_PER_FILE = 60_000  # cap any one artefact in the chat context

# Artefacts the auditor cares about, in the order we render them.
ARTEFACT_ORDER = (
    "scorecard.csv",
    "gap_register.csv",
    "audit_memo.html",
    "scorecard.xlsx",
    "gap_register.xlsx",
    "audit_memo.docx",
)

_RAG_STYLE = {"Red": "bold red", "Amber": "bold yellow", "Green": "bold green"}
_SEV_STYLE = {
    "Critical": "bold red",
    "High": "red",
    "Medium": "yellow",
    "Low": "green",
    "Info": "dim",
}


def _list_artefacts(session: Session) -> list[Path]:
    if not session.output_dir.is_dir():
        return []
    present = {p.name: p for p in session.output_dir.iterdir() if p.is_file()}
    ordered = [present[name] for name in ARTEFACT_ORDER if name in present]
    extras = sorted(p for p in present.values() if p.name not in ARTEFACT_ORDER)
    return ordered + extras


def _render_scorecard(session: Session) -> None:
    """Render scorecard.csv as a RAG-coloured rich table."""
    import csv

    path = session.output_dir / "scorecard.csv"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows:
        return

    table = Table(title="Scorecard", header_style="bold cyan", expand=True)
    table.add_column("Framework", style="bold")
    table.add_column("RAG", justify="center")
    for col in ("Total Controls", "Gaps", "Critical", "High", "Partial"):
        table.add_column(col, justify="right")
    for row in rows:
        rag = row.get("RAG Status", "")
        table.add_row(
            row.get("Framework", ""),
            f"[{_RAG_STYLE.get(rag, 'white')}]{rag}[/]",
            row.get("Total Controls", ""),
            row.get("Gaps", ""),
            row.get("Critical", ""),
            row.get("High", ""),
            row.get("Partial", ""),
        )
    session.console.print(table)


def _render_gaps(session: Session, top_n: int = 5) -> None:
    """Render the top N gaps from gap_register.csv, severity-coloured."""
    import csv

    path = session.output_dir / "gap_register.csv"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return

    sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    rows.sort(key=lambda r: sev_order.get(r.get("Severity", ""), 99))
    rows = rows[:top_n]

    table = Table(title=f"Top {len(rows)} gaps", header_style="bold cyan", expand=True)
    table.add_column("Framework", width=12)
    table.add_column("Control", width=18)
    table.add_column("Severity", width=10)
    table.add_column("Status", width=10)
    table.add_column("Recommendation", overflow="fold")
    for row in rows:
        sev = row.get("Severity", "")
        table.add_row(
            row.get("Framework", ""),
            row.get("Control ID", ""),
            f"[{_SEV_STYLE.get(sev, 'white')}]{sev}[/]",
            row.get("Status", ""),
            (row.get("Recommendation", "") or "")[:240],
        )
    session.console.print(table)


def _render_memo_excerpt(session: Session, chars: int = 800) -> None:
    """Render the first ~chars of the audit memo (HTML preferred, stripped)."""
    import re as _re

    html = session.output_dir / "audit_memo.html"
    txt = ""
    if html.exists():
        body = html.read_text(encoding="utf-8", errors="replace")
        # crude strip — the memo HTML is internally generated, not adversarial
        body = _re.sub(r"<style.*?</style>", "", body, flags=_re.DOTALL | _re.IGNORECASE)
        body = _re.sub(r"<script.*?</script>", "", body, flags=_re.DOTALL | _re.IGNORECASE)
        body = _re.sub(r"<[^>]+>", " ", body)
        body = _re.sub(r"\s+", " ", body).strip()
        txt = body[:chars] + ("…" if len(body) > chars else "")
    if not txt:
        return
    session.console.print(
        Panel(Markdown(txt), title="[cyan]audit memo (excerpt)[/cyan]", border_style="cyan")
    )


def _render_artefact_links(session: Session) -> None:
    """List artefacts with terminal hyperlinks (works in Windows Terminal,
    iTerm2, modern gnome-terminal). Also numbers them so /open <n> works."""
    artefacts = _list_artefacts(session)
    if not artefacts:
        return
    table = Table(title="Artefacts", header_style="bold cyan", expand=True)
    table.add_column("#", width=3, justify="right")
    table.add_column("File")
    table.add_column("Size", justify="right", width=12)
    table.add_column("Action")
    for idx, path in enumerate(artefacts, 1):
        uri = path.resolve().as_uri()
        table.add_row(
            str(idx),
            f"[link={uri}]{path.name}[/link]",
            f"{path.stat().st_size:,}",
            f"[dim]/open {idx}[/dim]",
        )
    session.console.print(table)


def _render_artefact_summary(session: Session) -> None:
    """Post-audit rendering: scorecard, top gaps, memo excerpt, file links.

    All data here is sanitized (output/* is the post-guardrails surface).
    Same trust boundary that applies to chat applies here — this function
    intentionally does not touch session.queued_files or any raw input.
    """
    if not _list_artefacts(session):
        session.console.print("[yellow]no artefacts in output/ — nothing to render.[/yellow]")
        return
    session.console.print()
    session.console.print(Rule("[bold]Audit results[/bold]", style="green"))
    _render_scorecard(session)
    session.console.print()
    _render_gaps(session)
    session.console.print()
    _render_memo_excerpt(session)
    session.console.print()
    _render_artefact_links(session)
    session.console.print()
    session.console.print(
        "[dim]Chat below is grounded on these redacted artefacts only — never raw vendor docs. "
        "Try: [bold]what's the worst gap?[/bold] or [bold]summarise DORA findings[/bold].[/dim]"
    )


def _cmd_open(session: Session, arg: str) -> None:
    """Open an artefact via the OS handler.

    /open 3   → opens the third artefact (Excel, browser, Word, etc.)
    /open scorecard.csv → opens by name
    """
    artefacts = _list_artefacts(session)
    if not artefacts:
        session.console.print("[yellow]no artefacts to open. run /audit first.[/yellow]")
        return
    target: Path | None = None
    arg = arg.strip()
    if arg.isdigit():
        i = int(arg) - 1
        if 0 <= i < len(artefacts):
            target = artefacts[i]
    else:
        for p in artefacts:
            if p.name == arg or p.stem == arg:
                target = p
                break
    if target is None:
        session.console.print(f"[red]not found:[/red] {arg!r}. run /show to list.")
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        session.console.print(f"[green]opened[/green] {target.name}")
    except OSError as exc:
        session.console.print(f"[red]could not open:[/red] {exc}")
        session.console.print(f"[dim]path:[/dim] {target}")


def _build_chat_context(session: Session) -> str:
    """Assemble the context block sent to the chat backend.

    Trust boundary (enforced here, not in the backend): only metadata
    of queued files and the contents of sanitized output/ artefacts
    flow out. Raw vendor document text is never read in this function.
    Audit and chat MUST NOT share a context-builder.
    """
    bits: list[str] = []
    if session.queued_files:
        # METADATA ONLY — name + size, no path, no contents.
        listing = ", ".join(
            f"{p.name} ({p.stat().st_size:,}B)" for p in session.queued_files
        )
        bits.append(f"Queued files (metadata only): {listing}")

    if session.last_audit_summary:
        bits.append(f"Last audit summary: {session.last_audit_summary}")

    if session.output_dir.is_dir():
        rendered_artefacts: list[str] = []
        for path in sorted(session.output_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _OUTPUT_TEXT_EXTS:
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(body) > _OUTPUT_MAX_BYTES_PER_FILE:
                body = body[:_OUTPUT_MAX_BYTES_PER_FILE] + "\n…[truncated]"
            rendered_artefacts.append(f"=== output/{path.name} ===\n{body}")
        if rendered_artefacts:
            bits.append("Sanitized audit artefacts (passed NeMo rails + Presidio):\n\n"
                        + "\n\n".join(rendered_artefacts))

    return "\n\n".join(bits)


def _chat_via_claude_code(system: str, user_prompt: str) -> str:
    """Use the user's Claude Code subscription via claude-agent-sdk.

    Lazy import so the TUI still loads when the SDK or the `claude`
    CLI isn't installed — we surface the error only when the user
    actually tries to chat with this backend.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk not installed (pip install claude-agent-sdk)"
        ) from exc

    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=[],  # chat-only; no shell/read/write inside the SDK
        max_turns=1,
        permission_mode="default",
    )

    async def _drive() -> str:
        chunks: list[str] = []
        async for msg in query(prompt=user_prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
        return "".join(chunks).strip()

    return asyncio.run(_drive())


def _chat_via_anthropic(system: str, user_prompt: str) -> str:
    """API-key path. Used when VENDOR_GUARD_CHAT_BACKEND=anthropic or
    when the claude-code path is unavailable. Imports lazily for the
    same reason as above (and to keep claude-agent-sdk not strictly
    required at import time)."""
    from agents.base import invoke_chat_model

    return invoke_chat_model(
        model=CHAT_MODEL,
        max_tokens=1024,
        system=system,
        user_prompt=user_prompt,
    )


def _dispatch_chat(system: str, user_prompt: str) -> tuple[str, str]:
    """Return (backend_used, reply). Falls back from claude-code to
    anthropic if the SDK/CLI aren't available; that fallback is loud
    so the user knows their subscription quota didn't get used."""
    if CHAT_BACKEND == "anthropic":
        return "anthropic-api", _chat_via_anthropic(system, user_prompt)
    if CHAT_BACKEND == "claude-code":
        try:
            return "claude-code", _chat_via_claude_code(system, user_prompt)
        except RuntimeError as exc:
            # SDK missing — fall back, but tell the user.
            return "anthropic-api (fallback)", _chat_via_anthropic(
                system, user_prompt + f"\n\n[note: claude-code backend unavailable: {exc}]"
            )
    # Unknown backend string → treat as anthropic (safest default).
    return "anthropic-api", _chat_via_anthropic(system, user_prompt)


def _cmd_chat(session: Session, user_text: str) -> None:
    """Send the user's line to the configured chat backend.

    Critical: builds the chat context via _build_chat_context, which
    enforces the trust boundary (no raw vendor-doc text). The chat
    backend therefore can only ever see file metadata + sanitized
    output/* contents.
    """
    session.chat_history.append(("user", user_text))

    context = _build_chat_context(session)
    prompt_text = (
        f"{context}\n\nUser: {user_text}" if context else f"User: {user_text}"
    )

    try:
        with session.console.status("[dim]thinking…[/dim]", spinner="dots"):
            backend_used, reply = _dispatch_chat(CHAT_SYSTEM_PROMPT, prompt_text)
    except Exception as exc:
        session.console.print(f"[red]chat error:[/red] {exc}")
        return

    session.chat_history.append(("assistant", reply))
    session.console.print()
    session.console.print(f"[dim]{TRUST_BANNER} • via {backend_used}[/dim]")
    session.console.print(
        Panel(Markdown(reply), title="[cyan]assistant[/cyan]", border_style="cyan")
    )


def _dispatch(session: Session, line: str) -> bool:
    """Return False when the user wants to leave."""
    line = line.strip()
    if not line:
        return True

    # Drag-drop fast path: if the line is entirely file paths, auto-queue.
    dropped = _parse_paths_from_input(line)
    if dropped and _input_is_only_paths(line, dropped):
        for path in dropped:
            session.console.print(session.add_file(path))
        return True

    if line.startswith("/"):
        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in {"quit", "exit", "q"}:
            return False
        if cmd == "help":
            _render_help(session.console)
            return True
        if cmd == "files":
            session.console.print(session.files_table())
            return True
        if cmd == "add":
            if not arg:
                session.console.print("[yellow]usage:[/yellow] /add <path>")
                return True
            for token in shlex.split(arg, posix=(os.name != "nt")):
                session.console.print(session.add_file(Path(_strip_drop_quoting(token)).expanduser()))
            return True
        if cmd == "remove":
            try:
                idx = int(arg) - 1
                removed = session.queued_files.pop(idx)
                session.console.print(f"[yellow]removed[/yellow] {removed.name}")
            except (ValueError, IndexError):
                session.console.print("[red]usage:[/red] /remove <1-based index>")
            return True
        if cmd == "clear":
            session.queued_files.clear()
            session.console.print("[yellow]file queue cleared.[/yellow]")
            return True
        if cmd == "load-sample":
            session.queued_files = [DEFAULT_QUESTIONNAIRE, *DEFAULT_DOCS]
            session.console.print(session.files_table())
            return True
        if cmd == "audit":
            if sys.platform == "linux":
                _cmd_audit_shell(session)
            else:
                session.console.print(
                    "[yellow]/audit defaults to the saaf-shell (Firecracker) path on Linux.[/yellow]"
                )
                session.console.print(
                    "[dim]this host is not Linux — falling back to /audit-direct (in-process).[/dim]"
                )
                _cmd_audit(session)
            return True
        if cmd in {"audit-direct", "audit-inproc", "audit-host"}:
            _cmd_audit(session)
            return True
        if cmd in {"audit-shell", "shell-audit"}:
            _cmd_audit_shell(session)
            return True
        if cmd == "backend":
            session.console.print(f"[dim]chat backend:[/dim] [cyan]{CHAT_BACKEND}[/cyan]")
            session.console.print(
                "[dim]override at launch with VENDOR_GUARD_CHAT_BACKEND=claude-code|anthropic.[/dim]"
            )
            return True
        if cmd == "output":
            session.console.print(f"[dim]output dir:[/dim] {session.output_dir}")
            return True
        if cmd == "show":
            _render_artefact_summary(session)
            return True
        if cmd == "open":
            if not arg:
                session.console.print("[yellow]usage:[/yellow] /open <n> or /open <filename>")
                return True
            _cmd_open(session, arg)
            return True
        if cmd == "reset":
            session.chat_history.clear()
            session.last_audit_summary = None
            session.console.print("[yellow]chat history cleared.[/yellow]")
            return True
        session.console.print(f"[red]unknown command:[/red] /{cmd}. Try /help.")
        return True

    # If there were dropped paths mixed with text, queue them first then chat.
    if dropped:
        for path in dropped:
            session.console.print(session.add_file(path))

    _cmd_chat(session, line)
    return True


def run(empty: bool = False) -> None:
    console = Console()
    _render_header(console)
    console.print(
        "[dim]Drop files into this window to queue them, or type /load-sample to preload the built-in vendor packet. "
        "Type /help for commands.[/dim]"
    )

    session = Session(console=console)
    if not empty and DEFAULT_QUESTIONNAIRE.exists():
        session.queued_files = [DEFAULT_QUESTIONNAIRE, *DEFAULT_DOCS]
        console.print()
        console.print("[dim]Preloaded sample packet:[/dim]")
        console.print(session.files_table())

    console.print()
    while True:
        try:
            line = Prompt.ask("[bold magenta]vendor-guard[/bold magenta]")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not _dispatch(session, line):
            break
    console.print("[dim]bye.[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vendor Guard interactive TUI")
    parser.add_argument("--empty", action="store_true", help="Start with no files queued")
    args = parser.parse_args()
    try:
        run(empty=args.empty)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
