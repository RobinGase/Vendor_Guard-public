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

## Useful artifact

- `debug_http_probe.py` is kept here as a lightweight exact prompt probe for the profile extraction request.
