# SAAF Vendor Risk Agent

## Overview
CLI tool that audits vendor risk against EU/NL regulatory frameworks (ISO 27001, NIS2, DORA, BIO2, EU AI Act, ALTAI, EC Ethics). Parses vendor documents, routes to specialized agents, synthesizes findings into a RAG scorecard, gap register, and audit memo.

## Project Structure
```
main.py              — CLI entrypoint & pipeline orchestration
agents/              — Framework-specific audit agents
  orchestrator.py    — Vendor profiling & agent routing
  security_agent.py  — ISO 27001 / NIS2
  resilience_agent.py — DORA
  gov_baseline_agent.py — BIO2
  ai_trust_agent.py  — EU AI Act / ALTAI / EC Ethics
  base.py            — Shared agent base
synthesizer/         — Aggregation & output generation
  synthesizer.py     — Finding aggregation & RAG scoring
  scorecard.py       — Excel scorecard & gap register
  memo.py            — DOCX audit memo
  google_output.py   — CSV/HTML for Google Workspace
models/finding.py    — Pydantic Finding model
utils/document_parser.py — PDF/DOCX/XLSX/TXT parser
prompts/             — Framework requirement markdown files
tests/               — pytest test suite
```

## Tech Stack
- Python 3.12+
- Anthropic Claude API (`anthropic` SDK)
- Pydantic v2 for data models
- pypdf, python-docx, openpyxl for document I/O
- pytest + pytest-mock for testing

## Commands
```bash
# Install
pip install -r requirements.txt

# Run
python main.py --questionnaire sample_vendor_q.txt --docs sample_soc2_report.txt sample_iso_certificate.txt sample_dora_questionnaire.txt --output-dir output

# Test
pytest tests/ -v
```

## Conventions
- Agents return `list[Finding]` via `run_<name>_agent(vendor_docs)` functions
- All framework requirements live as markdown in `prompts/`
- Output goes to `output/` directory (both Office and Google Workspace formats)
- Use concurrent.futures for parallel agent execution
- Environment variable `ANTHROPIC_API_KEY` must be set
