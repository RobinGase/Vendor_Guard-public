# Security Audit — Vendor_Guard (public)

**Scope:** code read-only review of main.py, agents/, synthesizer/, utils/, saaf_entrypoint.py, saaf_run.sh, saaf-manifest.yaml, requirements.txt.
**Status:** Draft for review. Not committed to history — intended to guide follow-up PRs.

## Summary

No critical findings. Vendor_Guard is a CLI workload with a small attack surface: file parsing, one outbound HTTP call to an LLM, and file output. API key handling is clean. Findings below are hardening items.

## Findings

### 1. INFERENCE_URL is used without scheme/host validation (low)
`agents/base.py:_post_inference` passes `os.getenv("INFERENCE_URL")` straight to `urllib.request.urlopen`. In the shell VM path this is constrained to `http://172.16.0.1:8088` by the manifest; outside the shell, a malicious operator env could point it at anything (SSRF within the host).
**Risk:** low — operator is the trust boundary.
**Fix:** validate scheme in (`http`, `https`) and log the resolved URL on first use.

### 2. `disable_pydantic_plugin_discovery` monkeypatches importlib (accepted)
`saaf_entrypoint.py` replaces `importlib.metadata.distributions` with an empty-list lambda to avoid NFS readdir races. Confirmed intentional and scoped to the entrypoint process only.

### 3. `saaf_run.sh` clears /tmp paths unconditionally (accepted)
`rm -rf /tmp/vendor_guard_runtime` and `/tmp/vendor-guard-venv` run at start. Inside the VM these paths are owned by the workload — safe. On a host this would be a footgun. The script is not intended to be run on the host.
**Fix:** add a guard `[ -f /opt/vendor-guard-venv.tar ] || exit 1` to fail fast if run in the wrong place.

### 4. Document parser trusts file suffix (low)
`utils/document_parser.py` dispatches by extension. A malicious `.pdf` containing a JS exploit or a malformed `.xlsx` with XXE could reach pypdf / openpyxl. Both libraries are reasonably hardened; openpyxl disables XML external entities by default.
**Risk:** low — inputs are provided by the operator.
**Fix:** add an upper file-size cap (say 50MB) before opening.

### 5. `extract_json` + `_salvage_truncated_array` do brace counting on raw strings (accepted)
Naive depth tracker does not handle braces inside string literals. A crafted model response `{"note": "}"}"` could confuse the parser.
**Risk:** low — the model is a downstream component, not attacker-controlled; worst case is a parse failure we already catch.
**Fix:** optional — switch to a streaming JSON decoder if the current approach ever fails in prod.

### 6. Requirements pin only lower bounds (low)
`requirements.txt` uses `>=` — no upper pin, no lock file. A future `pypdf` or `anthropic` release could introduce breaking or vulnerable behavior on `pip install`.
**Fix:** produce `requirements.lock` via `pip-compile`; add `pip-audit` to CI.

### 7. Sample files contain realistic-looking PII (intentional, flag for reviewers)
`sample_vendor_q.txt`, `sample_soc2_report.txt`, etc. include realistic names, emails, and company details. Confirm these are synthetic before the repo is made public.
**Fix:** add a note at the top of each sample file declaring "Synthetic data for testing. No real entities."

## Clean items
- No `shell=True`, `eval`, `exec`, `pickle`, or unsafe `yaml.load` anywhere in Python code.
- No `subprocess` use in Python code (only in `saaf_run.sh`, which is a wrapper, not user input).
- `require_anthropic_api_key` fails loudly on missing key; no silent fallback.
- `ThreadPoolExecutor` isolates agent failures via `future.result()` try/except; one agent failure does not break the run.
- Manifest `saaf-manifest.yaml` complies with the shell's v1 policy: one network rule (gateway:8088), single r/w root (/audit_workspace), PII entities declared, retention set.
- No hardcoded secrets, URLs, or Tailscale IPs in Python code.

## Recommended follow-ups (ordered)
1. INFERENCE_URL scheme validation + startup log (finding 1).
2. saaf_run.sh preflight guard (finding 3).
3. File-size cap in document_parser (finding 4).
4. Add `pip-audit` + `requirements.lock` to CI.
5. Confirm sample-data synthetic status in file headers (finding 7).
