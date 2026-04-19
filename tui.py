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
import os
import shlex
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

from agents.base import invoke_chat_model

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_QUESTIONNAIRE = REPO_ROOT / "sample_vendor_q.txt"
DEFAULT_DOCS = [
    REPO_ROOT / "sample_soc2_report.txt",
    REPO_ROOT / "sample_iso_certificate.txt",
    REPO_ROOT / "sample_dora_questionnaire.txt",
]

CHAT_SYSTEM_PROMPT = """You are the Vendor Guard audit assistant. You help an auditor triage a vendor risk packet against EU/NL regulatory frameworks (ISO 27001, NIS2, DORA, BIO2, EU AI Act, ALTAI, EC Ethics).

Rules:
- Be concise. Bullet points over prose.
- When asked about findings you haven't seen, say so; do not speculate.
- If the user asks you to audit a file, remind them to run /audit on the queued files.
- Cite framework article numbers only if you are certain they exist.
- Never return a pass/fail verdict on the whole vendor — findings are for human review.
"""

CHAT_MODEL = "claude-opus-4-6"


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
    table.add_row("/audit", "Run the full pipeline on queued files")
    table.add_row("/output", "Where audit outputs land (scorecard, memo, …)")
    table.add_row("/reset", "Clear chat history")
    table.add_row("/quit  /exit", "Leave")
    table.add_row("<any other text>", "Chat with the audit assistant")
    table.add_row("<drag a file in>", "Path is auto-queued; no chat turn sent")
    console.print(table)


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


def _cmd_chat(session: Session, user_text: str) -> None:
    """Send the user's line to Claude with current session context."""
    session.chat_history.append(("user", user_text))

    context_bits = []
    if session.queued_files:
        context_bits.append(
            "Currently queued files (user can /audit to run them): "
            + ", ".join(p.name for p in session.queued_files)
        )
    if session.last_audit_summary:
        context_bits.append("Last audit: " + session.last_audit_summary)
    context = "\n".join(context_bits)

    prompt_text = (
        f"{context}\n\nUser: {user_text}" if context else f"User: {user_text}"
    )

    try:
        with session.console.status("[dim]thinking…[/dim]", spinner="dots"):
            reply = invoke_chat_model(
                model=CHAT_MODEL,
                max_tokens=1024,
                system=CHAT_SYSTEM_PROMPT,
                user_prompt=prompt_text,
            )
    except RuntimeError as exc:
        session.console.print(f"[red]chat error:[/red] {exc}")
        return
    except Exception as exc:
        session.console.print(f"[red]chat error:[/red] {exc}")
        return

    session.chat_history.append(("assistant", reply))
    session.console.print()
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
            _cmd_audit(session)
            return True
        if cmd == "output":
            session.console.print(f"[dim]output dir:[/dim] {session.output_dir}")
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
