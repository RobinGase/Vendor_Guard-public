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
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import traceback

# Enabling GNU readline line editing for input() globally. Without this
# the arrow keys emit raw escape sequences (^[[D etc.) instead of
# moving the cursor. Import-for-side-effect; no symbols used directly.
try:
    import readline  # noqa: F401
except ImportError:
    # readline isn't available on stock Windows Python; the Windows
    # build-in cmd.exe handling covers line editing there, so the
    # import failure is safe to ignore.
    pass
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

# Extensions utils.document_parser can actually read. Used to expand a
# dropped folder into its queueable children and skip README/images/etc.
_QUEUEABLE_EXTS = {".pdf", ".docx", ".xlsx", ".txt"}

# Trust boundary: chat backends never receive raw vendor-document text.
# Audit findings (which are gated by the shell's NeMo rails + Presidio)
# are the only document-derived content that flows here. The system
# prompt restates this so the model can answer "what can you see?"
# correctly when the auditor asks.
_CHAT_TRUST_RULES = """Trust boundary you must respect and explain when asked:
- You DO see: queued filenames + sizes (metadata only), the audit summary, and the contents of artefacts under output/ (scorecard, gap register, audit memo). These artefacts have already passed the saaf-shell's NeMo guardrails and Presidio PII redaction.
- You DO NOT see: the raw vendor documents. Their text never enters this chat. All substantive analysis happens inside the saaf-shell's Firecracker VM with the local model. Your job is to help the auditor interpret the guardrailed outputs, not re-run the audit.

How to behave:
- Be concise. Bullets over prose.
- If asked about something only present in raw docs, trigger <action name="audit"/> rather than refusing — the action runs the audit pipeline, which is how the content becomes available.
- Cite framework article numbers only if you're certain they exist; otherwise refer to the artefact.
- Never issue a vendor-wide pass/fail; that's for the human reading the gap register."""

CHAT_SYSTEM_PROMPT = f"""You are the Vendor Guard chat assistant. The user is an internal/IT auditor (often non-technical) reviewing a vendor packet against EU/NL frameworks (ISO 27001, NIS2, DORA, BIO2, EU AI Act, ALTAI, EC Ethics).

{_CHAT_TRUST_RULES}

Actions you can trigger:
When the user expresses intent to perform an operation, emit ONE action tag at the very start of your reply, on its own line, then a one-sentence confirmation of what you're doing. The TUI will execute the action and come back to you for reasoning.

Supported tags (use exactly this grammar):
  <action name="audit"/>              — run the audit pipeline on the currently queued files
  <action name="clear"/>               — clear the file queue
  <action name="show"/>                — print the artefact summary panel
  <action name="open" file="NAME"/>    — open a named artefact (e.g. scorecard.csv, gap_register.xlsx, audit_memo.html)
  <action name="reveal_reasoning"/>    — open the agent reasoning folder in the operator's file manager. You cannot read its contents; this is for the human reviewer.

Rules for actions:
- At most ONE tag per reply. Never fabricate filenames — only use files visible in the context.
- If no action is warranted, do not emit a tag; just answer.
- If the user dropped files and asks you to audit+reason, emit <action name="audit"/> — after it finishes, the TUI will ask you to reason about the output."""

_CHAT_SYSTEM_PROMPT_REASONING = f"""You are the Vendor Guard chat assistant, now in reasoning mode after an action just completed.

{_CHAT_TRUST_RULES}

Do NOT emit any <action .../> tag in this turn. Focus on interpreting the artefacts the user can now see."""

_ACTION_RE = re.compile(
    r'<action\s+name="(?P<name>[a-z_-]+)"(?:\s+file="(?P<file>[^"]+)")?\s*/?>',
    re.IGNORECASE,
)

CHAT_MODEL = "claude-opus-4-6"
CHAT_BACKEND = os.environ.get("VENDOR_GUARD_CHAT_BACKEND", "claude-code").lower()
TRUST_BANNER = "[Claude sees: filenames + sanitized output/ artefacts only — never raw vendor data]"


@dataclass
class Session:
    """Everything the TUI carries across turns."""

    console: Console
    queued_files: list[Path] = field(default_factory=list)
    # Suffixes that the document_parser can actually ingest — used to
    # expand dropped folders without queueing unrelated assets.
    chat_history: list[tuple[str, str]] = field(default_factory=list)  # (role, content)
    last_audit_summary: str | None = None
    output_dir: Path = field(default_factory=lambda: REPO_ROOT / "output")
    # Populated when a dispatched audit pulls the remote debug/ folder
    # back as reasoning. The chat backend's `reveal_reasoning` tool
    # opens this path in the operator's file manager — the tool
    # deliberately returns only a boolean status so the chat model
    # never ingests raw agent reasoning (trust boundary: Claude sees
    # sanitized output/ artefacts and filenames, never raw prompts).
    reasoning_path: Path | None = None

    def add_file(self, path: Path) -> str:
        if not path.exists():
            return f"[red]not found:[/red] {path}"
        if path.is_dir():
            added = []
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in _QUEUEABLE_EXTS:
                    if child.resolve() in self.queued_files:
                        continue
                    self.queued_files.append(child.resolve())
                    added.append(child.name)
            if not added:
                return f"[yellow]no queueable files in[/yellow] {path.name}"
            return f"[green]queued[/green] {len(added)} file(s) from {path.name}: {', '.join(added)}"
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


_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_path(raw_token: str, stripped: str) -> bool:
    """Heuristic: only treat a token as a path candidate when it
    visibly looks like one. Prevents bare words ("audit", "output",
    "this") from matching relative paths that happen to exist in the
    current working directory."""
    if raw_token.startswith(('"', "'")):
        return True
    if "/" in stripped or "\\" in stripped:
        return True
    if stripped.startswith("~"):
        return True
    if _DRIVE_RE.match(stripped):
        return True
    if "." in stripped:
        suffix = Path(stripped).suffix.lower()
        if suffix in _QUEUEABLE_EXTS:
            return True
    return False


def _parse_paths_from_input(raw: str) -> list[Path]:
    """Return the subset of input tokens that resolve to existing files.

    Splits with shlex so drag-dropped paths with spaces parse as one
    token, then filters to tokens that *look* like paths (contain a
    separator, drive letter, tilde, or queueable extension) before
    checking the filesystem. A bare word that coincidentally matches
    a file in CWD is NOT treated as a path — that would mis-queue
    natural-language tokens.
    """
    try:
        tokens = shlex.split(raw, posix=(os.name != "nt"))
    except ValueError:
        tokens = raw.split()
    out: list[Path] = []
    for token in tokens:
        stripped = _strip_drop_quoting(token)
        if not _looks_like_path(token, stripped):
            continue
        candidate = Path(stripped).expanduser()
        if candidate.exists() and (candidate.is_file() or candidate.is_dir()):
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
SHELL_AGENTFS_WORKDIR = os.environ.get("SAAF_AGENTFS_WORKDIR", "/opt/saaf")
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


def _run_sudo(argv: list[str], *, timeout: int, cwd: str | None = None) -> subprocess.CompletedProcess[bytes]:
    cmd = _sudo_prefix() + argv
    pwd = os.environ.get("SAAF_SUDO_PASSWORD")
    return subprocess.run(
        cmd,
        input=(pwd + "\n").encode() if pwd else None,
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
    )


def _stage_queued_inputs(session: Session) -> bool:
    """Copy session.queued_files into the rootfs and write queued.env.

    saaf_run.sh (inside the VM) sources /audit_workspace/queued.env to
    pick up VENDOR_QUESTIONNAIRE / VENDOR_DOCS. That's how per-run
    inputs flow in without rewriting the manifest each time.

    Also clears any leftover outputs from prior runs so the AgentFS
    overlay diff only contains this run's artefacts.
    """
    workspace = f"{SHELL_ROOTFS}/audit_workspace"
    queued_dir = f"{workspace}/vendor_guard/queued"
    env_file = f"{workspace}/queued.env"

    # Prep staging dir without a shell context. Previous `sh -c` form
    # interpolated SHELL_ROOTFS (env-var controlled) directly into a
    # command string, so a crafted SAAF_SHELL_ROOTFS could inject
    # commands that run via sudo. Each rm/mkdir goes through sudo's
    # argv path instead, which bypasses shell parsing entirely and
    # makes path values inert regardless of the characters they contain.
    stale_paths = [f"{workspace}/{f}" for f in SHELL_OUTPUT_FILES]
    cleanup_argv = ["rm", "-rf", "--", queued_dir, env_file, *stale_paths]
    prep = _run_sudo(cleanup_argv, timeout=30)
    if prep.returncode != 0:
        session.console.print("[red]failed to prep staging dir (rm):[/red]")
        session.console.print(prep.stderr.decode(errors="replace")[-500:])
        return False
    mk = _run_sudo(["mkdir", "-p", "--", queued_dir], timeout=30)
    if mk.returncode != 0:
        session.console.print("[red]failed to prep staging dir (mkdir):[/red]")
        session.console.print(mk.stderr.decode(errors="replace")[-500:])
        return False

    for src in session.queued_files:
        cp = _run_sudo(["cp", "--", str(src), f"{queued_dir}/{src.name}"], timeout=30)
        if cp.returncode != 0:
            session.console.print(f"[red]failed to stage {src.name}:[/red]")
            session.console.print(cp.stderr.decode(errors="replace")[-500:])
            return False

    q_candidates = [p for p in session.queued_files if "questionnaire" in p.name.lower()]
    questionnaire = q_candidates[0] if q_candidates else session.queued_files[0]
    docs = [p for p in session.queued_files if p != questionnaire]

    guest_queued = "/audit_workspace/vendor_guard/queued"
    # Values are double-quoted because the file is sourced by /bin/sh
    # inside the VM — unquoted semicolons in VENDOR_DOCS would be
    # parsed as command separators. Filenames come from the user's
    # Filenames from the queue flow into VENDOR_DOCS/VENDOR_QUESTIONNAIRE
    # that saaf_run.sh parses inside the VM. Any character the shell
    # would treat specially when reading the env file must be rejected:
    # backslash and `$`/backtick (expansion), `"` (closes the quoted
    # value), single quote (same problem if the quoting style changes),
    # and newline / CR / tab (line injection — an attacker-controlled
    # filename with \n could inject a whole extra VAR=value line).
    # `;` is the separator joining doc paths into VENDOR_DOCS — a
    # filename containing `;` would split into bogus path fragments at
    # the VM-side parser (saaf_entrypoint.resolve_inputs splits on `;`),
    # crashing run_pipeline with FileNotFoundError. `=` is the KEY=VALUE
    # delimiter in queued.env; a filename with `=` would corrupt the
    # parse. Reject both upstream — the VM-side denylist can't catch
    # them without breaking the legitimate VENDOR_DOCS separator.
    _unsafe_chars = ('"', "\\", "$", "`", "'", "\n", "\r", "\t", ";", "=")
    for p in session.queued_files:
        bad = [repr(c) for c in _unsafe_chars if c in p.name]
        if bad:
            session.console.print(
                f"[red]refusing to stage file with shell-unsafe name "
                f"(contains {', '.join(bad)}):[/red] {p.name!r}"
            )
            return False
    env_body = (
        f'VENDOR_QUESTIONNAIRE="{guest_queued}/{questionnaire.name}"\n'
        f'VENDOR_DOCS="{";".join(f"{guest_queued}/{d.name}" for d in docs)}"\n'
    )
    # Write to a tmpfile we own, then sudo-mv into place. Piping the
    # body through sudo -S stdin races with sudo's credential cache
    # (when cached, -S doesn't consume the password line and it leaks
    # into tee's stdout).
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as tf:
        tf.write(env_body)
        tmp_env_path = tf.name
    mv = _run_sudo(["install", "-m", "644", "--", tmp_env_path, env_file], timeout=10)
    try:
        os.unlink(tmp_env_path)
    except OSError:
        pass
    if mv.returncode != 0:
        session.console.print("[red]failed to write queued.env:[/red]")
        session.console.print(mv.stderr.decode(errors="replace")[-500:])
        return False

    session.console.print(
        f"  [dim]staged:[/dim] {len(session.queued_files)} file(s) → "
        f"questionnaire=[cyan]{questionnaire.name}[/cyan], docs={len(docs)}"
    )
    return True


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

    if session.queued_files:
        if not _stage_queued_inputs(session):
            return
    else:
        session.console.print(
            "  [yellow]no queued files — audit will use baked-in sample inputs.[/yellow]"
        )
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
            extract = _run_sudo([SHELL_AGENTFS, "fs", session_id, "cat", guest_path], timeout=30, cwd=SHELL_AGENTFS_WORKDIR)
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
    session.queued_files.clear()

    _render_artefact_summary(session)


_DISPATCH_STATUS_AGENT_RE = re.compile(
    r"^\s+(security|resilience|gov_baseline|ai_trust)\s*:"
)

# "dispatch: reasoning saved to /path/to/reasoning/<session-id> (N files)"
# — one emission per successful audit; captures the concrete per-session
# path so the chat backend can open it later without hardcoding layout.
_DISPATCH_REASONING_RE = re.compile(
    r"^dispatch: reasoning saved to (.+?) \(\d+ files?\)$"
)


def _dispatch_status_for_line(line: str) -> str | None:
    """Map a dispatcher/main.py stdout line to a spinner caption.

    Returns None when the line carries no stage transition and the
    caption should stay as-is. Captions use present-continuous ("…ing")
    so the spinner reads as an active state rather than a completed
    one. We match on the exact prose printed by main.py + the dispatch
    script — keep these in sync if those print statements change.
    """
    if line.startswith("dispatch: session "):
        return "[cyan]staging files on fedora…[/cyan]"
    if line.startswith("dispatch: remote "):
        return "[cyan]cooking on nemotron-nano-vg (via privacy router)…[/cyan]"
    if "Extracting vendor profile" in line:
        return "[cyan]profiling vendor…[/cyan]"
    if line.startswith("Running agents:"):
        return "[cyan]running framework agents…[/cyan]"
    m = _DISPATCH_STATUS_AGENT_RE.match(line)
    if m:
        return f"[cyan]{m.group(1)} agent finished — next up…[/cyan]"
    if "Writing outputs" in line:
        return "[cyan]writing artefacts…[/cyan]"
    if line.startswith("dispatch:") and "artefacts in" in line:
        return "[cyan]retrieving artefacts…[/cyan]"
    if line.startswith("dispatch: reasoning saved to"):
        return "[cyan]retrieving agent reasoning…[/cyan]"
    return None


def _cmd_audit_dispatch(session: Session) -> bool:
    """Hand the audit to an external dispatcher.

    When the TUI runs on a host where saaf-shell cannot execute
    locally (Windows, macOS, a Linux laptop without Firecracker),
    the operator can export ``VENDOR_GUARD_AUDIT_DISPATCH`` pointing
    at an executable that knows how to run the shell path somewhere
    else (a remote Linux host, a container, a CI job). The TUI does
    not care how — it only enforces:

    - the queued files are passed as CLI args exactly once
    - the child's exit code decides success/failure
    - artefacts must land in ``session.output_dir`` for the post-run
      dashboard to render

    The dispatcher is passed as argv:

        <VENDOR_GUARD_AUDIT_DISPATCH> \\
            --questionnaire <first queued file> \\
            --doc <second> [--doc <third> ...] \\
            --output-dir <session output dir>

    Everything host / network / credential specific lives in the
    dispatcher, outside the public vendor_guard tree. Personal
    multi-device glue belongs in a private dev repo; this hook is
    the contract between the two.
    """
    if not session.queued_files:
        session.console.print("[yellow]no files queued.[/yellow] Drag a vendor packet in first, or run /load-sample.")
        return False

    dispatcher = os.environ["VENDOR_GUARD_AUDIT_DISPATCH"]
    q_candidates = [p for p in session.queued_files if "questionnaire" in p.name.lower()]
    questionnaire = q_candidates[0] if q_candidates else session.queued_files[0]
    docs = [p for p in session.queued_files if p != questionnaire]

    session.console.print()
    session.console.print(Rule("[bold]Audit via dispatcher[/bold]", style="magenta"))
    session.console.print(f"  [dim]dispatcher:[/dim]    {dispatcher}")
    session.console.print(f"  [dim]questionnaire:[/dim] {questionnaire}")
    for doc in docs:
        session.console.print(f"  [dim]doc:[/dim]          {doc}")
    session.console.print(f"  [dim]output:[/dim]        {session.output_dir}")
    session.console.print()

    # Reasoning lands in a sibling of output/, not inside it, so that
    # the chat backend (which scans output/) never ingests raw agent
    # reasoning. The dispatcher mkdirs <reasoning-dir>/<session-id>/
    # and scp's the remote debug/ tree into it.
    reasoning_root = session.output_dir.parent / "reasoning"

    argv: list[str] = [
        dispatcher,
        "--questionnaire", str(questionnaire),
        "--output-dir", str(session.output_dir),
        "--reasoning-dir", str(reasoning_root),
    ]
    for doc in docs:
        argv.extend(["--doc", str(doc)])

    session.output_dir.mkdir(parents=True, exist_ok=True)
    reasoning_root.mkdir(parents=True, exist_ok=True)

    # Stream the dispatcher's stdout line-by-line so the operator gets
    # live feedback instead of staring at a silent terminal for the
    # 3-10 minute remote run. A rich Status spinner under the log
    # rolls its caption forward as we spot known markers from the
    # dispatch script + remote main.py output. Unknown lines still
    # print, the spinner just doesn't change caption for them.
    returncode: int | None = None
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        session.console.print(f"[red]dispatcher not found:[/red] {dispatcher}")
        return False
    except Exception as exc:
        session.console.print(f"[red]dispatcher crashed:[/red] {exc}")
        return False

    reasoning_path_from_run: Path | None = None
    with session.console.status(
        "[cyan]starting dispatcher…[/cyan]", spinner="dots"
    ) as status:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            session.console.print(f"  [dim]{line}[/dim]")
            new_caption = _dispatch_status_for_line(line)
            if new_caption:
                status.update(new_caption)
            # The dispatcher prints exactly one "reasoning saved to PATH (N files)"
            # line after scp'ing debug/ back. Capture the path so the chat
            # backend's reveal_reasoning tool can open it later.
            match = _DISPATCH_REASONING_RE.match(line)
            if match:
                reasoning_path_from_run = Path(match.group(1))
        returncode = proc.wait()

    if returncode != 0:
        session.console.print(
            f"[red]dispatcher exited with code {returncode}.[/red] "
            "No artefacts retrieved."
        )
        return False

    session.console.print(
        Panel(
            f"Dispatcher completed. Artefacts in {session.output_dir}.",
            title="[green]/audit (dispatched) complete[/green]",
            border_style="green",
        )
    )
    session.last_audit_summary = (
        f"Audit dispatched via {dispatcher}. "
        f"Questionnaire: {questionnaire.name}. Docs: {[d.name for d in docs]}. "
        f"Artefacts retrieved to {session.output_dir}."
    )
    if reasoning_path_from_run and reasoning_path_from_run.is_dir():
        session.reasoning_path = reasoning_path_from_run
        session.console.print(
            f"  [dim]reasoning:[/dim]    {reasoning_path_from_run} "
            "[dim](ask me to 'open the reasoning folder' for human review)[/dim]"
        )
    session.queued_files.clear()
    _render_artefact_summary(session)
    return True


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

    q_candidates = [p for p in session.queued_files if "questionnaire" in p.name.lower()]
    questionnaire = q_candidates[0] if q_candidates else session.queued_files[0]
    docs = [p for p in session.queued_files if p != questionnaire]

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
    session.queued_files.clear()

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


def _render_memo_excerpt(session: Session, chars: int = 2000) -> None:
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

    if session.reasoning_path is not None and session.reasoning_path.is_dir():
        # Advertise that a reasoning folder exists WITHOUT leaking any
        # content. Claude can trigger <action name="reveal_reasoning"/>
        # if the user asks, but never reads the folder itself.
        bits.append(
            "Agent reasoning folder available for this session. "
            "If the user asks to see, review, or open the reasoning / "
            "chain-of-thought / debug output, emit "
            "<action name=\"reveal_reasoning\"/> and the TUI will open it "
            "in their file manager. You cannot read its contents — it is "
            "for the human reviewer only."
        )

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


class ClaudeCodeCLIError(Exception):
    """Real claude CLI subprocess failure — not an SDK-missing condition.
    Kept distinct from RuntimeError so _dispatch_chat doesn't mistake a
    CLI crash for a missing install and silently fall back to the API path."""


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

    # Capture claude CLI debug output to a tempfile. Can't use the
    # stderr= callback reliably: the SDK cancels its async reader task
    # on close(), dropping any lines still buffered when the process
    # exits non-zero — exactly the failure case we need to diagnose.
    # debug_stderr= writes with flush() per line, so lines that were
    # processed before cancellation survive on disk.
    stderr_log = tempfile.NamedTemporaryFile(
        mode="w", suffix=".log", prefix="vg_claude_stderr_", delete=False
    )
    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=[],  # chat-only; no shell/read/write inside the SDK
        max_turns=1,
        permission_mode="default",
        debug_stderr=stderr_log,
        extra_args={"debug-to-stderr": None},
    )

    # Hold chunks in an outer list so we can still return whatever the
    # model produced if the SDK raises *after* the reply arrived. This is
    # the generate_session_title race: CLI has a background title task
    # that streams in parallel to the reply; when max_turns=1 completes
    # the SDK closes stdin, the title task hits EPIPE, and the CLI exits
    # 1 — even though the user-visible reply was already delivered.
    chunks: list[str] = []

    async def _drive() -> str:
        async for msg in query(prompt=user_prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
        return "".join(chunks).strip()

    try:
        try:
            result = asyncio.run(_drive())
        finally:
            stderr_log.close()
        # Success: stderr capture is no longer needed; clean it up so
        # we don't leak a vg_claude_stderr_*.log file under %TEMP% (or
        # /tmp) on every chat turn. Only the no-chunks failure branch
        # below keeps the file — that path embeds its name in the
        # error message for diagnosis.
        try:
            os.unlink(stderr_log.name)
        except OSError:
            pass
        return result
    except RuntimeError:
        # SDK-missing path; leave to caller for fallback.
        raise
    except Exception as exc:
        # If we already got a reply, swallow the post-reply exit-1 from
        # the session-title background-task race. The user got their
        # answer; the CLI just couldn't cleanly finish its bookkeeping.
        if chunks:
            try:
                os.unlink(stderr_log.name)
            except OSError:
                pass
            return "".join(chunks).strip()
        # No reply at all → this is a real failure. Surface stderr tail
        # via a distinct class so _dispatch_chat doesn't mistake a CLI
        # crash for a missing install and silently fall back to the API.
        try:
            with open(stderr_log.name, "r", errors="replace") as fh:
                captured = fh.read().splitlines()
        except OSError:
            captured = []
        if captured:
            tail = "\n".join(captured[-25:])
            raise ClaudeCodeCLIError(
                f"{exc}\n--- claude stderr ({stderr_log.name}, last 25 lines) ---\n{tail}"
            ) from exc
        raise ClaudeCodeCLIError(f"{exc} (no stderr captured at {stderr_log.name})") from exc


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


def _execute_action(session: Session, name: str, file: str | None) -> tuple[bool, str]:
    """Run an intent-dispatched action. Returns (ok, status_msg).

    The set here mirrors a subset of slash-commands — intentionally
    small so Claude cannot take surprising actions. Expand deliberately.
    """
    name = name.lower()
    if name == "audit":
        if not session.queued_files:
            return False, "no files queued — drop a vendor packet first"
        if sys.platform == "linux":
            _cmd_audit_shell(session)
            return True, "audit (shell) completed"
        if os.environ.get("VENDOR_GUARD_AUDIT_DISPATCH"):
            ok = _cmd_audit_dispatch(session)
            if ok:
                return True, "audit (dispatched) completed"
            return False, "dispatcher failed — see errors above"
        return False, "/audit requires Linux + saaf-shell or VENDOR_GUARD_AUDIT_DISPATCH"
    if name == "clear":
        session.queued_files.clear()
        session.console.print("[yellow]file queue cleared.[/yellow]")
        return True, "queue cleared"
    if name == "show":
        _render_artefact_summary(session)
        return True, "artefacts listed"
    if name == "open":
        if not file:
            return False, "open action missing file="
        _cmd_open(session, file)
        return True, f"opened {file}"
    if name == "reveal_reasoning":
        return _cmd_reveal_reasoning(session)
    return False, f"unknown action: {name}"


def _cmd_reveal_reasoning(session: Session) -> tuple[bool, str]:
    """Open the current session's reasoning folder in the OS file manager.

    The chat backend can trigger this via <action name="reveal_reasoning"/>
    but receives back only a one-line status — never a listing, never a
    byte of content. The reasoning folder holds raw per-agent prompts and
    responses; the trust boundary keeps those out of the chat model's
    context even when the human wants to review them.
    """
    path = session.reasoning_path
    if path is None:
        return False, (
            "no reasoning folder for this session — reasoning is only "
            "retrieved after a dispatched /audit completes"
        )
    if not path.is_dir():
        return False, f"reasoning path no longer exists: {path}"
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        return False, f"failed to open reasoning folder: {exc}"
    session.console.print(
        f"[green]opened reasoning folder:[/green] {path}"
    )
    return True, f"reasoning folder opened for the human reviewer at {path}"


def _cmd_chat(session: Session, user_text: str) -> None:
    """Send the user's line to the configured chat backend.

    Critical: builds the chat context via _build_chat_context, which
    enforces the trust boundary (no raw vendor-doc text). The chat
    backend therefore can only ever see file metadata + sanitized
    output/* contents.

    Intent layer: if the reply contains a single <action .../> tag,
    execute the action, then do a second reasoning-only turn over the
    post-action state. Action grammar is pinned; Claude cannot invent
    filenames or chain actions.
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

    action_match = _ACTION_RE.search(reply)
    visible_reply = _ACTION_RE.sub("", reply).strip() if action_match else reply

    session.chat_history.append(("assistant", reply))
    session.console.print()
    session.console.print(f"[dim]{TRUST_BANNER} • via {backend_used}[/dim]")
    if visible_reply:
        session.console.print(
            Panel(Markdown(visible_reply), title="[cyan]assistant[/cyan]", border_style="cyan")
        )

    if not action_match:
        return

    name = action_match.group("name")
    file = action_match.group("file")
    session.console.print()
    session.console.print(Rule(f"[magenta]action: {name}[/magenta]", style="magenta"))
    ok, status = _execute_action(session, name, file)
    if not ok:
        session.console.print(f"[red]action failed:[/red] {status}")
        return

    followup_context = _build_chat_context(session)
    followup_prompt = (
        f"{followup_context}\n\n"
        f"User originally asked: {user_text}\n\n"
        f"The '{name}' action just completed ({status}). "
        "Answer the user's question using the artefacts above. Be concise."
    )
    try:
        with session.console.status("[dim]reasoning over results…[/dim]", spinner="dots"):
            backend_used2, reply2 = _dispatch_chat(_CHAT_SYSTEM_PROMPT_REASONING, followup_prompt)
    except Exception as exc:
        session.console.print(f"[red]follow-up chat error:[/red] {exc}")
        return

    session.chat_history.append(("assistant", reply2))
    session.console.print()
    session.console.print(f"[dim]{TRUST_BANNER} • via {backend_used2}[/dim]")
    session.console.print(
        Panel(Markdown(reply2), title="[cyan]assistant (post-action)[/cyan]", border_style="cyan")
    )


# Box-drawing chars that leak in when auditors copy-paste bullets out of a
# rich panel. Strip leading/trailing runs so `│  1 DORA Art. 19 …  │` reads
# cleanly as `1 DORA Art. 19 …`.
_PANEL_CHARS = "│─┃━╭╮╰╯┌┐└┘├┤┬┴┼┏┓┗┛┳┻┣┫╋╔╗╚╝║═╠╣╦╩╬"


def _strip_panel_borders(line: str) -> str:
    return line.strip().strip(_PANEL_CHARS + " \t").strip()


def _dispatch(session: Session, line: str) -> bool:
    """Return False when the user wants to leave."""
    line = _strip_panel_borders(line)
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
            elif os.environ.get("VENDOR_GUARD_AUDIT_DISPATCH"):
                _cmd_audit_dispatch(session)
            else:
                session.console.print(
                    "[yellow]/audit requires Linux + saaf-shell or a configured dispatch hook.[/yellow]"
                )
                session.console.print(
                    "[dim]this host is not Linux and VENDOR_GUARD_AUDIT_DISPATCH is not set.[/dim]"
                )
                session.console.print()
                session.console.print("Options:")
                session.console.print("  • run the TUI on a Linux host that has saaf-shell installed")
                session.console.print("  • set VENDOR_GUARD_AUDIT_DISPATCH to an executable that runs the shell path remotely")
                session.console.print("  • use [cyan]/audit-direct[/cyan] to run in-process on this host (ANTHROPIC_API_KEY, bypasses saaf-shell)")
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


def run(with_sample: bool = False) -> None:
    console = Console()
    _render_header(console)
    console.print(
        "[dim]Drop files into this window to queue them, or type /load-sample to preload the built-in vendor packet. "
        "Type /help for commands.[/dim]"
    )

    session = Session(console=console)
    if with_sample and DEFAULT_QUESTIONNAIRE.exists():
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
    parser.add_argument("--with-sample", action="store_true",
                        help="Preload the built-in sample vendor packet (equivalent to /load-sample).")
    # --empty kept as a tolerated no-op since the default is now empty.
    parser.add_argument("--empty", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        run(with_sample=args.with_sample)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
