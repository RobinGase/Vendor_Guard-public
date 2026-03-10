# SAAF Vendor Risk Audit Agent

A multi-agent Claude pipeline for vendor third-party risk assessment. Ingests vendor questionnaires and supporting documents; outputs a risk scorecard, gap register, and audit memo across 8 EU/NL regulatory frameworks.

## Frameworks covered

| Cluster | Frameworks |
|---|---|
| Security & Compliance | ISO 27001, NIS2, CBW |
| Resilience | DORA |
| Government Baseline | BIO2 (Dutch government only) |
| AI Trustworthiness | EU AI Act, ALTAI, EC Ethics |

## Requirements

- Python 3.11+
- Anthropic API key (`ANTHROPIC_API_KEY` env var)

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py --questionnaire vendor_q.xlsx --docs soc2.pdf iso_cert.pdf
```

Outputs are written to `./output/` by default:
- `scorecard.xlsx` — RAG-colored scorecard per framework
- `gap_register.xlsx` — all findings with severity and recommendations
- `audit_memo.docx` — narrative audit memo for management

## Architecture

```
Orchestrator -> [Security, Resilience, Gov Baseline*, AI Trust*] -> Synthesizer -> Outputs
```

*Gov Baseline only for Dutch government vendors. AI Trust only for AI systems.

## How it works

1. **Orchestrator** reads all vendor documents and extracts a vendor profile (sector, services, AI system flag, government vendor flag)
2. **Specialist agents** run in parallel, each assessing the vendor against their framework cluster
3. **Synthesizer** aggregates all findings into a RAG scorecard, gap register, and Claude-drafted audit memo

## Extending for your organization

- Add a new framework: create `prompts/<framework>.md` and a new agent in `agents/`
- Fork an existing specialist agent and adapt the system prompt for your org's specific variant
- Each agent is fully independent and can be used standalone

## Running tests

```bash
pytest tests/ -v
```

32 tests covering models, document parser, all agents, synthesizer, outputs, and full pipeline integration.

## SAAF Project

Built as part of the [SAAF Project](https://saafproject.com) — a co-creative initiative where IT and internal auditors from 28+ organizations build AI audit agents together through hackathons across 2026.
