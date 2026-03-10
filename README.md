# SAAF Vendor Risk Audit Agent

Automatically audit your third-party vendors against 8 EU and Dutch regulatory frameworks. Upload a vendor questionnaire and supporting documents, and get a risk scorecard, gap register, and management-ready audit memo in seconds.

Built as part of the [SAAF Project](https://saafproject.com) (Shared Audit Agents Framework), a co-creative initiative where IT and internal auditors from 45+ organizations build AI audit agents together through hackathons across 2026.

## What it does

You give it vendor documents (questionnaires, SOC 2 reports, ISO certificates, DORA self-assessments). It reads them, determines what kind of vendor this is, runs the right compliance checks in parallel, and produces three deliverables:

1. **Risk Scorecard** - a Red/Amber/Green overview per framework, showing where the vendor stands at a glance
2. **Gap Register** - every finding listed with control ID, status, severity, evidence, and a recommendation
3. **Audit Memo** - a narrative report written in formal audit language, ready to hand to management

All outputs are generated in both Microsoft Office (xlsx, docx) and Google Workspace (csv, html) formats.

## Frameworks covered

| Cluster | Frameworks | When it runs |
|---|---|---|
| Security & Compliance | ISO 27001, NIS2, CBW | Always |
| Resilience | DORA | Always |
| Government Baseline | BIO2 | Only if vendor serves Dutch government |
| AI Trustworthiness | EU AI Act, ALTAI, EC Ethical Guidelines | Only if vendor is an AI system |

**CBW** is the Cyberbeveiligingswet, the Dutch implementation of NIS2. **BIO2** is the Baseline Informatiebeveiliging Overheid, mandatory for Dutch government organizations.

## How it works

```
                         Your Documents
                    (questionnaire + certs + reports)
                              |
                              v
                    +-------------------+
                    |   Orchestrator    |
                    |  (Claude Opus)    |
                    |                   |
                    | Reads all docs,   |
                    | extracts vendor   |
                    | profile: sector,  |
                    | services, AI?,    |
                    | government?       |
                    +-------------------+
                              |
               Decides which agents to run
                              |
            +-----------------+-----------------+
            |                 |                 |
            v                 v                 v
   +----------------+ +---------------+ +---------------+
   | Security Agent | | Resilience    | | AI Trust      |
   | (Sonnet)       | | Agent (Sonnet)| | Agent (Sonnet)|
   |                | |               | |               |
   | ISO 27001      | | DORA          | | EU AI Act     |
   | NIS2           | |               | | ALTAI         |
   | CBW            | |               | | EC Ethics     |
   +----------------+ +---------------+ +---------------+
            |                 |                 |
            +--------+--------+---------+-------+
                     |                  |
                     v                  v
          +------------------+ +------------------+
          |   Synthesizer    | |   Memo Writer    |
          |                  | |   (Claude Opus)  |
          | Aggregates all   | |                  |
          | findings, scores | | Drafts narrative |
          | RAG per framework| | audit memo       |
          +------------------+ +------------------+
                     |                  |
                     v                  v
           +--------------------------------------------+
           |              Output Files                  |
           |                                            |
           |  Google Workspace:     Microsoft Office:    |
           |   scorecard.csv        scorecard.xlsx      |
           |   gap_register.csv     gap_register.xlsx   |
           |   audit_memo.html      audit_memo.docx     |
           +--------------------------------------------+
```

**Step by step:**

1. **Document ingestion** - reads PDF, DOCX, XLSX, and TXT files. All content is combined with filename labels so agents know which document each piece of evidence came from.

2. **Vendor profiling** - the orchestrator (Claude Opus) analyzes all documents and extracts a structured profile: vendor name, sector, services, whether they process personal data, whether they are an AI system, and whether they serve Dutch government entities. This determines which specialist agents are needed.

3. **Parallel assessment** - specialist agents run simultaneously. Each agent has the full text of its regulatory framework embedded in its system prompt, so it assesses the vendor against specific control requirements. Agents only cite evidence that is explicitly present in the documents; they never invent findings.

4. **Findings normalization** - every agent returns structured findings with framework, control ID, status (Compliant/Gap/Partial/Not Applicable), severity (Critical/High/Medium/Low/Info), evidence quote, and recommendation. The system handles variations in Claude's output (e.g. "Informational" maps to "Info", "Non-Compliant" maps to "Gap").

5. **Synthesis** - all findings are aggregated into a RAG scorecard. Red means any Critical or High gap. Amber means Medium/Low gaps or Partial compliance. Green means fully compliant.

6. **Report generation** - Claude Opus drafts a formal audit memo with executive summary, scope, key findings, recommendations, and conclusion. The scorecard, gap register, and memo are written to both Excel/Word and CSV/HTML formats.

## Requirements

- Python 3.11+
- An Anthropic API key with access to Claude Sonnet and Claude Opus

## Setup

```bash
git clone <this-repo>
cd saaf-vendor-risk-agent
pip install -r requirements.txt
```

Set your API key (Windows):
```bash
set ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Set your API key (Mac/Linux):
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

To make the key permanent on Windows, run once as administrator:
```bash
setx ANTHROPIC_API_KEY "sk-ant-your-key-here"
```

## Usage

Basic usage with the included sample files:
```bash
python main.py --questionnaire sample_vendor_q.txt --docs sample_soc2_report.txt sample_iso_certificate.txt sample_dora_questionnaire.txt
```

With your own files:
```bash
python main.py --questionnaire vendor_questionnaire.xlsx --docs soc2_report.pdf iso_certificate.pdf contract.docx
```

Custom output directory:
```bash
python main.py --questionnaire vendor_q.xlsx --output-dir results/acme-bv
```

Supported input formats: PDF, DOCX, XLSX, TXT

## Output files

After running, the `output/` folder contains:

| File | Format | Audience | Open with |
|---|---|---|---|
| `scorecard.csv` | CSV | Management | Google Sheets (drag & drop) |
| `scorecard.xlsx` | Excel | Management | Microsoft Excel |
| `gap_register.csv` | CSV | Audit team | Google Sheets |
| `gap_register.xlsx` | Excel | Audit team | Microsoft Excel |
| `audit_memo.html` | HTML | Management | Browser, or import into Google Docs |
| `audit_memo.docx` | Word | Management | Microsoft Word |

The HTML memo includes the scorecard table, narrative, and gap register all in one styled page.

## Project structure

```
saaf-vendor-risk-agent/
├── main.py                         # CLI entrypoint and pipeline orchestration
├── requirements.txt
├── agents/
│   ├── base.py                     # Prompt loader + JSON extraction helper
│   ├── orchestrator.py             # Vendor profiling + agent routing
│   ├── security_agent.py           # ISO 27001, NIS2, CBW assessment
│   ├── resilience_agent.py         # DORA assessment
│   ├── gov_baseline_agent.py       # BIO2 assessment (Dutch government)
│   └── ai_trust_agent.py           # EU AI Act, ALTAI, EC Ethics assessment
├── synthesizer/
│   ├── synthesizer.py              # Finding aggregation + RAG scorecard logic
│   ├── scorecard.py                # Excel output (scorecard + gap register)
│   ├── memo.py                     # Word output (audit memo via Claude)
│   └── google_output.py            # CSV + HTML output (Google Workspace)
├── models/
│   └── finding.py                  # Finding + VendorProfile data models
├── utils/
│   └── document_parser.py          # PDF, DOCX, XLSX, TXT reader
├── prompts/                        # Regulatory framework knowledge files
│   ├── iso27001_controls.md
│   ├── nis2_measures.md
│   ├── cbw_requirements.md
│   ├── dora_requirements.md
│   ├── bio2_controls.md
│   ├── ai_act_requirements.md
│   ├── altai_requirements.md
│   └── ec_ethics_guidelines.md
├── tests/                          # 34 tests covering all components
└── sample_*.txt                    # Sample vendor documents for testing
```

## Extending for your organization

**Add a new framework:**
1. Create `prompts/your_framework.md` with the control requirements
2. Copy an existing agent (e.g. `agents/resilience_agent.py`) and adapt the system prompt
3. Add the new agent to `AGENT_MAP` in `main.py`
4. Add routing logic in `orchestrator.py` if it should only run conditionally

**Customize existing frameworks:**
Each prompt file in `prompts/` contains the control requirements in plain markdown. Edit these to match your organization's interpretation or add controls specific to your sector.

**Use a single agent standalone:**
Each specialist agent is independent. You can import and call any agent directly:
```python
from agents.security_agent import run_security_agent

findings = run_security_agent("Your vendor document text here...")
for f in findings:
    print(f"{f.framework} | {f.control_id} | {f.status} | {f.severity}")
```

## Running tests

```bash
python -m pytest tests/ -v
```

34 tests covering models, document parser, all agents, synthesizer, outputs, and full pipeline integration. Tests use mocked API calls, so no API key is needed to run them.

## Sample files included

The repo includes sample vendor documents for a fictional company (CloudSafe Solutions B.V.) so you can test immediately:

- `sample_vendor_q.txt` - main vendor risk questionnaire
- `sample_soc2_report.txt` - SOC 2 Type II report with control test results
- `sample_iso_certificate.txt` - ISO 27001:2022 certificate
- `sample_dora_questionnaire.txt` - DORA self-assessment with known gaps

## Cost estimate

A typical run with 3-4 vendor documents uses approximately:
- 1 Opus call for vendor profiling
- 2-4 Sonnet calls for specialist agents (depends on vendor type)
- 1 Opus call for the audit memo

## SAAF Project

This agent was designed for the [SAAF Project](https://saafproject.com) (Shared Audit Agents Framework), a vendor-agnostic, open-source initiative where IT and internal auditors from 45+ organizations co-build AI audit agents through a series of hackathons in 2026. The SAAF framework has four components: prompts, tools, guardrails, and output formats. This agent follows that structure.
