# SAAF Vendor Risk Audit Agent

## Overview
CLI + TUI tool that audits vendor risk against EU/NL regulatory frameworks (ISO 27001, NIS2, CBW, DORA, BIO2, EU AI Act, ALTAI, EC Ethics). Parses vendor documents, profiles the vendor, routes to specialised agents in parallel, synthesizes findings into a RAG scorecard, gap register, and audit memo.

**Two run paths:**
- **Path A — saaf-compliance-shell (Linux + KVM):** Vendor_Guard runs inside a Firecracker microVM with NeMo Guardrails + Presidio PII + privacy router + hash-chained audit log. Local inference via Ollama. This is the compliance-grade path.
- **Path B — Cloud standalone (any OS):** `anthropic` SDK direct. No VM, no guardrails. Dev/demo only.

Model dispatch lives in `agents/base.py::invoke_chat_model` — `INFERENCE_URL` set → Path A local endpoint (Ollama-compatible, model via `SAAF_MODEL`, default `Randomblock1/nemotron-nano:8b`). Unset → Path B Anthropic API.

Shell integration pinned at **saaf-compliance-shell v0.9.1**.

## Project Structure
```
main.py              — CLI entrypoint & pipeline orchestration
tui.py               — Interactive terminal front-end (file-drop + chat)
saaf-manifest.yaml   — Shell workload contract (Path A)
saaf_run.sh          — Guest-side wrapper inside the VM
saaf_entrypoint.py   — Python entrypoint bridging to main.run_pipeline
agents/              — Framework-specific audit agents
  base.py            — Model dispatch (INFERENCE_URL vs Anthropic), JSON extraction
  orchestrator.py    — Vendor profiling & agent routing
  security_agent.py  — ISO 27001 / NIS2 / CBW
  resilience_agent.py — DORA
  gov_baseline_agent.py — BIO2
  ai_trust_agent.py  — EU AI Act / ALTAI / EC Ethics
synthesizer/
  synthesizer.py     — Finding aggregation & RAG scoring
  scorecard.py       — Excel scorecard & gap register
  memo.py            — DOCX audit memo
  google_output.py   — CSV/HTML for Google Workspace
models/finding.py    — Pydantic Finding + VendorProfile models
utils/document_parser.py — PDF/DOCX/XLSX/TXT parser
prompts/             — Framework requirement markdown files
docs/SHELL_INTEGRATION.md — Path A walkthrough
tests/               — pytest test suite (65 tests across 14 files)
```

## Tech Stack
- Python 3.11 or 3.12 (3.14 intentionally excluded — NeMo/LangChain compatibility via the shell)
- `anthropic` SDK (Path B) or Ollama-compatible HTTP endpoint (Path A)
- Pydantic v2 for data models
- `pypdf`, `python-docx`, `openpyxl` for document I/O
- `rich` for TUI rendering; `readline` for line editing
- `pytest` + `pytest-mock` for testing

## Commands

### Install
```bash
pip install -r requirements.txt
```

### Run — Path A (saaf-shell)
Shell must be installed and running (v0.9.1). Invoke via the shell CLI with the manifest:
```bash
saaf-shell run /path/to/vendor_guard/saaf-manifest.yaml
```
Or through the TUI's `/audit` command (same path, friendlier).

### Run — Path B (cloud)
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python main.py --questionnaire sample_vendor_q.txt --docs sample_soc2_report.txt sample_iso_certificate.txt sample_dora_questionnaire.txt --output-dir output
```
Or TUI `/audit-direct`.

### Test
```bash
pytest tests/ -v
```
Tests mock the model backend — no API key or Ollama endpoint needed.

## Conventions
- Agents return `list[Finding]` via `run_<name>_agent(vendor_docs)` functions.
- All framework requirements live as markdown in `prompts/`.
- Output goes to `output/` (host, Path B) or `/audit_workspace/` (VM overlay, Path A). Both Office (xlsx/docx) and Google Workspace (csv/html) formats are emitted.
- Parallel agent execution via `concurrent.futures`.
- Model endpoint selection is env-driven: set `INFERENCE_URL` (Path A) or `ANTHROPIC_API_KEY` (Path B). Setting both → Path A wins.
- TUI chat system prompt enforces a trust boundary: raw vendor doc text never reaches the chat backend; only queued filenames/sizes + guardrailed artefacts do.

## Platform note
Path A requires Linux with KVM. macOS and Windows (including WSL2) cannot run the shell path reliably. Path B runs anywhere Python runs.
