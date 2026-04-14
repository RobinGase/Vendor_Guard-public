# SAAF Shell Integration

Vendor_Guard can run as an ordinary CLI on a developer laptop, and it can also run inside `saaf-compliance-shell` as a constrained workload. This document describes the shell path: which files make it work, why they are shaped the way they are, and how to run it.

## What the shell adds

Nothing about Vendor_Guard's logic changes under the shell. The shell wraps the same `main.py` pipeline in four additional layers:

1. A Firecracker microVM isolates the process from the host.
2. AgentFS captures every file the workload writes.
3. NeMo Guardrails intercepts all model traffic for PII masking and injection defence.
4. A SHA-256 chained audit log records session events on the host.

From Vendor_Guard's point of view, the only visible difference is that inference goes to `$INFERENCE_URL` (injected by the shell) instead of the Anthropic API.

## The three files that make it work

### `saaf-manifest.yaml`

The compliance contract. The shell reads this once at session start and refuses to boot if anything is missing or malformed.

Key declarations:

- `agent.entrypoint: /audit_workspace/vendor_guard/saaf_run.sh` — what the guest runs.
- `filesystem.read_write: [/audit_workspace]` — the only writable path.
- `network.allow: [{host: gateway, port: 8088}]` — the only reachable endpoint.
- `resources: {vcpu_count: 2, mem_size_mib: 2048}` — VM sizing.
- `pii.entities: [PERSON, EMAIL_ADDRESS, BSN_NL]` — which Presidio recognisers apply.

### `saaf_run.sh`

The guest-side wrapper. Runs inside the VM, not on the host. It does three things in order:

1. Copies the workload from NFS (`/audit_workspace/vendor_guard`) to tmpfs (`/tmp/vendor_guard_runtime`).
2. Extracts a prebuilt Python venv tarball (`/opt/vendor-guard-venv.tar`) into `/tmp/vendor-guard-venv`.
3. Execs `saaf_entrypoint.py` under the venv's Python, with stdout/stderr redirected to `/audit_workspace` for AgentFS capture.

**Why tmpfs + prebuilt venv:** running the workload directly from NFS-mounted site-packages caused `readdir` races on subdirectories like `docx/parts`. Prebuilding the venv as a single tar file and extracting into tmpfs avoids that entire class of issue and happens to be much faster.

### `saaf_entrypoint.py`

The Python entrypoint. Runs inside the VM. Handles:

- `disable_pydantic_plugin_discovery()` — monkeypatches `importlib.metadata.distributions` to return an empty list. Pydantic otherwise scans every site-packages dist at import time, and that scan walks over NFS even after the venv has been copied to tmpfs. Disabling it prevents a noticeable cold-start hang.
- `resolve_inputs()` — picks up `VENDOR_QUESTIONNAIRE`, `VENDOR_DOCS`, and `VENDOR_OUTPUT_DIR` from env, with sensible fallbacks to the sample files.
- `wait_for_inference_ready()` — polls `$INFERENCE_URL`'s `/health` endpoint before running the pipeline, so transient cold-start errors at guardrails do not kill the session.
- Calls `run_pipeline()` from `main.py`.

Writes a line-oriented status log to `/audit_workspace/saaf_entrypoint.log` so the host can observe progress without reading the VM console.

## What gets produced

After a successful run, the AgentFS overlay for the session contains these paths under `/audit_workspace/`:

| File | Source |
|---|---|
| `scorecard.xlsx`, `scorecard.csv` | Synthesizer |
| `gap_register.xlsx`, `gap_register.csv` | Synthesizer |
| `audit_memo.docx`, `audit_memo.html` | Memo writer |
| `saaf_wrapper.log` | `saaf_run.sh` progress markers |
| `saaf_entrypoint.log` | Python-side status |
| `saaf_entrypoint.stdout`, `.stderr` | Redirected streams |
| `vendor_profile_raw.txt` | Orchestrator's raw model response, preserved for audit |

Inspect the overlay from the host with `saaf-shell diff --agent-id <session-id>`.

## Running it

From the saaf-compliance-shell repo on the Linux host, with the support services already up:

```bash
saaf-shell run --manifest /path/to/vendor_guard/saaf-manifest.yaml
```

The shell generates the VM config from the manifest, boots Firecracker, waits for the VM to exit, tears down the TAP device and iptables rules, and writes a `session_end` record to the audit log.

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Pipeline never starts | `saaf_entrypoint.log` should show `inference_ready=ok`. If it shows `timeout`, guardrails is not reachable from the VM. |
| Specific agent fails | `saaf_entrypoint.stderr` carries tracebacks. |
| No files in overlay | Check VM console log (`<session-id>.console.log` on the host) — the VM may have exited before the pipeline ran. |
| Scorecard missing but logs show success | Check AgentFS overlay directly via `saaf-shell diff`; the output dir default is `/audit_workspace/`. |

## Reference

The host side of this integration is documented in the saaf-compliance-shell repo. See `docs/ARCHITECTURE.md` there for the full request path and `docs/QUICKSTART.md` for bringing up the shell on a fresh host.
