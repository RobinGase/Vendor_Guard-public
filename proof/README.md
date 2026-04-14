# Proof Folder

Durable checkpoints and diagnostic helpers worth keeping between sessions. This is not a log dump — each file should stay short and useful.

## What belongs here

- **Integration checkpoints.** A dated note of what was proven to work end-to-end, with enough detail that the next session can re-verify it.
- **Fresh-boot runbooks.** Exact steps to get from a cold host back to a working state — not tutorial material, just the minimum command sequence.
- **Diagnostic probes.** Short scripts that exercise a narrow slice of the system when something is behaving oddly.

## What does not belong here

- Full run logs. Attach evidence by file size and session ID, not by pasting the whole stdout.
- Experimental drafts. Promote things here once they are proven, not while figuring them out.
- Secrets or personal machine details. This folder is version-controlled.

## Current contents

- [`shell_integration_checkpoint.md`](shell_integration_checkpoint.md) — last proven state of the shell-wrapped path, with session IDs, output sizes, and the fixes that unblocked it.
- [`fresh_boot_runbook.md`](fresh_boot_runbook.md) — exact procedure to re-establish the shell services and re-run the pipeline after a Fedora reboot.
- [`debug_http_probe.py`](debug_http_probe.py) — minimal exact-prompt probe for the profile extraction request, useful when the orchestrator's first call behaves oddly.

## Rule of thumb

If a file in this folder is older than one month and you have not re-verified that it still holds, annotate it with a "last confirmed" date or move it out. Stale proof is worse than no proof.
