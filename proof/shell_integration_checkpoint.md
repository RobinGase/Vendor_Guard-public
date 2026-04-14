# Vendor_Guard Shell Checkpoint

## Proven (2026-04-13)

- `saaf-manifest.yaml`, `saaf_entrypoint.py`, `saaf_run.sh` drive an end-to-end Firecracker run on Fedora.
- Guest wrapper log records `wrapper_start → wrapper_runtime_copied → wrapper_venv_extracted → wrapper_python_exec`.
- `saaf_entrypoint.log` records `inference_ready=ok` and `pipeline=ok`.
- AgentFS session diff for `vendor-guard-a646e7cf` includes real output artifacts under `/audit_workspace/`:
  - `scorecard.xlsx`, `scorecard.csv`
  - `gap_register.xlsx`, `gap_register.csv`
  - `audit_memo.docx`, `audit_memo.html`
  - `vendor_profile_raw.txt`
- CSV scorecard contains per-framework RAG rows (DORA, ISO 27001, etc).

## Key fixes that unblocked the run

- `saaf_run.sh` no longer does per-package `cp` of site-packages over NFS (the readdir races on subdirs like `docx/parts` were the root cause of the earlier "6-second vm_exit=ok" illusion). It now copies the workload to tmpfs and extracts a prebuilt `/opt/vendor-guard-venv.tar` into `/tmp/vendor-guard-venv` in one sequential NFS read.
- `wrapper_start` breadcrumb is written before the first `cp`, so any future `set -e` abort still leaves proof that the wrapper at least started.
- `saaf_entrypoint.py` defers `from main import run_pipeline` until after `disable_pydantic_plugin_discovery()` clears `importlib.metadata.distributions`, dodging pydantic plugin discovery scans over NFS.

## Proven again (2026-04-14) — session `vendor-guard-5e3aae84`

Second full end-to-end run from a fresh Fedora boot. Same clean wrapper sequence and all 6 output
artifacts present in AgentFS with real content:

- `scorecard.xlsx` — 5 167 bytes
- `gap_register.xlsx` — 7 792 bytes
- `audit_memo.docx` — 38 456 bytes
- `scorecard.csv` — 113 bytes
- `gap_register.csv` — 9 433 bytes
- `audit_memo.html` — 17 524 bytes

`scorecard.csv` content:
```
Framework,RAG Status,Total Controls,Gaps,Critical,High,Partial
DORA,Amber,1,0,0,0,1
ISO 27001,Amber,1,0,0,0,1
```

**Output generation is repeatable. The VM path is stable.**

## Useful artifact

- `debug_http_probe.py` is kept here as a lightweight exact prompt probe for the profile extraction request.
