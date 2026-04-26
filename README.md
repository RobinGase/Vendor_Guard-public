# SAAF Vendor Risk Audit Agent

Automatically audit your third-party vendors against 8 EU and Dutch regulatory frameworks. Give it a vendor questionnaire and supporting documents; get back a risk scorecard, gap register, and management-ready audit memo.

This repo ships two things:

1. **Vendor_Guard** — the audit agent itself (orchestrator, specialist agents per framework, synthesizer, report generators).
2. **Integration artefacts** for running Vendor_Guard inside **[saaf-compliance-shell](https://github.com/RobinGase/saaf-compliance-shell)** — a modular compliance wrapper (Firecracker microVM + NeMo Guardrails + Presidio + privacy router + tamper-evident audit log) that turns Vendor_Guard into a workload isolatable to regulated-data standards.

Built as part of the [SAAF Project](https://saafproject.com) (Shared Audit Agents Framework), a co-creative initiative where IT and internal auditors from 45+ organizations build AI audit agents together through 2026 hackathons.

---

## ⚠ Platform requirement — Linux only for the compliance path

**The saaf-compliance-shell path requires a Linux host with KVM.** Firecracker is a KVM-based microVM; there is no macOS equivalent, and Windows/WSL2 cannot nest KVM reliably. If you are not on Linux, you can still run Vendor_Guard in cloud-standalone mode (Anthropic API, no shell, no VM, no compliance rails) — see **Path B** below.

Tested on Fedora Workstation and Ubuntu 24.04. Assumes CLI familiarity: you know what `sudo`, `pip`, and an SSH key are.

---

## What it does

You give it vendor documents (questionnaires, SOC 2 reports, ISO certificates, DORA self-assessments). It reads them, determines what kind of vendor this is, runs the right compliance checks in parallel, and produces three deliverables:

1. **Risk Scorecard** — Red/Amber/Green overview per framework.
2. **Gap Register** — every finding with control ID, status, severity, evidence, recommendation.
3. **Audit Memo** — formal narrative report, ready to hand to management.

Outputs in both Microsoft Office (xlsx, docx) and Google Workspace (csv, html) formats.

## Frameworks covered

| Cluster | Frameworks | When it runs |
|---|---|---|
| Security & Compliance | ISO 27001, NIS2, CBW | Always |
| Resilience | DORA | Only if vendor sector matches financial keywords (banking, insurance, payments, fintech, credit, asset management) |
| Government Baseline | BIO2 | Only if vendor serves Dutch government |
| AI Trustworthiness | EU AI Act, ALTAI, EC Ethical Guidelines | Only if vendor is an AI system |

**CBW** = Cyberbeveiligingswet (Dutch NIS2 transposition). **BIO2** = Baseline Informatiebeveiliging Overheid (mandatory for Dutch government organisations).

---

## Two paths to run it

### Path A — saaf-compliance-shell (Linux, compliance-first)

The reason the shell exists. Vendor_Guard runs inside a Firecracker VM; all model I/O flows through NeMo Guardrails + Presidio; every tool call lands in a SHA-256 hash-chained audit log; the privacy router refuses cloud fallback. Local inference on an Ollama endpoint (CPU or GPU).

```
  TUI on workstation                        Linux host (Firecracker VM host)
  ─────────────────                         ──────────────────────────────────
                                            ┌──────────────────────────┐
  queue files  ─────────▶  /audit  ────────▶│ saaf-compliance-shell    │
                                            │ ┌──────────────────────┐ │
                                            │ │ Firecracker microVM  │ │
                                            │ │  ┌────────────────┐  │ │
                                            │ │  │  Vendor_Guard  │  │ │
                                            │ │  │  orchestrator  │  │ │
                                            │ │  │  + agents      │  │ │
                                            │ │  └──────┬─────────┘  │ │
                                            │ │         │            │ │
                                            │ │   INFERENCE_URL      │ │
                                            │ │   ↓                  │ │
                                            │ │  ┌────────────────┐  │ │
                                            │ │  │ NeMo Guardrails│  │ │
                                            │ │  │ + Presidio PII │  │ │
                                            │ │  └──────┬─────────┘  │ │
                                            │ │         │            │ │
                                            │ │   Privacy Router ───────▶  Ollama
                                            │ │   (loopback-bound)   │ │    (local model)
                                            │ └──────────────────────┘ │
                                            │          │               │
                                            │          ▼               │
                                            │   tamper-evident         │
                                            │   audit.jsonl            │
                                            └──────────────────────────┘
                                                       │
                     output artefacts on AgentFS overlay → scorecard + gap_register + audit_memo
```

The `saaf-manifest.yaml` in this repo declares Vendor_Guard as a shell workload: entrypoint, network policy (single allow rule to the guardrails gateway), data classification, resource limits. `saaf_run.sh` is the guest-side wrapper; `saaf_entrypoint.py` bridges to `main.run_pipeline`.

### Path B — Cloud standalone (any OS, no compliance rails)

For quick evaluation, non-Linux workstations, or testing the agent logic in isolation. Vendor_Guard calls Anthropic directly: Claude Opus as orchestrator + audit memo, Claude Sonnet as specialist agents. No VM, no guardrails, no audit log, no PII redaction. **Do not run real vendor data through this path.**

---

## How it works

1. **Document ingestion** — PDF, DOCX, XLSX, TXT. Content combined with filename labels so agents know the provenance of every quote.
2. **Vendor profiling** — the orchestrator extracts a structured profile (name, sector, services, personal-data processing, AI system, Dutch-government). This determines which specialist agents are needed.
3. **Parallel assessment** — specialist agents run simultaneously. Each has the full text of its regulatory framework embedded in its system prompt. Agents cite only evidence explicitly present in the documents.
4. **Findings normalisation** — every agent returns structured findings: framework, control ID, status (Compliant/Gap/Partial/Not Applicable), severity (Critical/High/Medium/Low/Info), evidence quote, recommendation.
5. **Synthesis** — findings aggregated into a RAG scorecard. Red = any Critical or High gap. Amber = Medium/Low gaps or Partial. Green = fully compliant.
6. **Report generation** — formal audit memo drafted; scorecard, gap register, memo written to both Excel/Word and CSV/HTML.

On **Path A**, steps 2–6 all happen inside the Firecracker VM, gated by the shell. On **Path B**, they run in-process on the host.

---

## Setup

### Path A — Linux + saaf-compliance-shell

Prerequisites on the Linux host:
- KVM enabled (`ls /dev/kvm` → exists)
- Python 3.11 or 3.12 (3.14 not supported — NeMo Guardrails compatibility)
- An Ollama endpoint reachable from the host (local GPU machine or the host itself)
- saaf-compliance-shell installed — follow its [QUICKSTART](https://github.com/RobinGase/saaf-compliance-shell/blob/main/docs/QUICKSTART.md), pinned at **v0.9.1**

Clone Vendor_Guard into the shell's workspace and drop the manifest into place:

```bash
git clone https://github.com/RobinGase/Vendor_Guard.git vendor_guard
cd vendor_guard
pip install -r requirements.txt
```

Then run through the shell (see **Usage** below). Full walkthrough: [`docs/SHELL_INTEGRATION.md`](docs/SHELL_INTEGRATION.md).

### Path B — Cloud standalone

```bash
git clone https://github.com/RobinGase/Vendor_Guard.git
cd Vendor_Guard
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Windows: `set ANTHROPIC_API_KEY=sk-ant-your-key-here` (or `setx` for persistence).

---

## Usage

### Interactive TUI — the demo front end

```bash
python tui.py            # sample vendor packet preloaded
python tui.py --empty    # start with nothing queued
```

Drag a vendor packet (questionnaire + SOC 2 / ISO / DORA docs) directly into the terminal window — paths are auto-queued, quotes handled. Type `/audit` to run. Any non-path input is a conversational turn that reaches the chat backend (Claude Code SDK, or Anthropic API as fallback).

| Command | Effect |
|---|---|
| `/audit` | Run through saaf-shell Firecracker VM — **Path A** (Linux only) |
| `/audit-direct` | Run the pipeline in-process on the host — **Path B** (needs `ANTHROPIC_API_KEY`) |
| `/files` / `/add` / `/remove` / `/clear` | Manage the file queue |
| `/load-sample` | Load the built-in CloudSafe Solutions B.V. packet |
| `/show` | Re-render the last audit results |
| `/open <n>` | Open artefact #n in its native app |
| `/output` | Show where audit outputs land |
| `/backend` | Show / change the chat backend |

**Trust boundary:** the TUI chat never sees raw vendor documents — only queued filenames/sizes, the audit summary, and the guardrailed artefacts under `output/`. Raw doc text stays inside the shell's VM boundary. Ask the assistant "what can you see?" for the verbatim rules.

### CLI — scripted / batch mode

Path B (in-process, cloud):

```bash
python main.py --questionnaire sample_vendor_q.txt \
               --docs sample_soc2_report.txt sample_iso_certificate.txt sample_dora_questionnaire.txt
```

Path A (through shell) uses the manifest — refer to the shell's `run` subcommand:

```bash
saaf-shell run path/to/vendor_guard/saaf-manifest.yaml
```

Custom output dir: `--output-dir results/acme-bv`. Supported input formats: PDF, DOCX, XLSX, TXT.

### Multi-device dispatch (advanced)

For a workstation → remote-host split (e.g. Mac/Windows laptop driving the TUI, Linux server running the shell), set `VENDOR_GUARD_AUDIT_DISPATCH` to an SSH-capable dispatcher script. `/audit` will stage files to the remote, run there, and stream results back. Used in the demo setup; scripting is out of scope here.

---

## Output files

After a run, `output/` (host) or `/audit_workspace/` (VM overlay, synced out) contains:

| File | Format | Audience | Open with |
|---|---|---|---|
| `scorecard.csv` | CSV | Management | Google Sheets |
| `scorecard.xlsx` | Excel | Management | Microsoft Excel |
| `gap_register.csv` | CSV | Audit team | Google Sheets |
| `gap_register.xlsx` | Excel | Audit team | Microsoft Excel |
| `audit_memo.html` | HTML | Management | Browser / Google Docs import |
| `audit_memo.docx` | Word | Management | Microsoft Word |

The HTML memo includes scorecard table, narrative, and gap register in one styled page.

---

## Project structure

```
Vendor_Guard/
├── main.py                     # CLI entrypoint and pipeline orchestration
├── tui.py                      # Interactive terminal front-end (file-drop + chat)
├── saaf-manifest.yaml          # Shell workload contract (Path A)
├── saaf_run.sh                 # Guest-side wrapper run inside the VM
├── saaf_entrypoint.py          # Python entrypoint bridging to main.run_pipeline
├── requirements.txt
├── agents/
│   ├── base.py                 # Model dispatch (INFERENCE_URL vs Anthropic), JSON extraction
│   ├── orchestrator.py         # Vendor profiling + agent routing
│   ├── security_agent.py       # ISO 27001 / NIS2 / CBW
│   ├── resilience_agent.py     # DORA
│   ├── gov_baseline_agent.py   # BIO2
│   └── ai_trust_agent.py       # EU AI Act / ALTAI / EC Ethics
├── synthesizer/
│   ├── synthesizer.py          # Finding aggregation + RAG scorecard logic
│   ├── scorecard.py            # Excel output
│   ├── memo.py                 # Word output
│   └── google_output.py        # CSV + HTML output
├── models/finding.py           # Finding + VendorProfile models
├── utils/document_parser.py    # PDF / DOCX / XLSX / TXT reader
├── prompts/                    # Regulatory framework knowledge (markdown per framework)
├── docs/
│   └── SHELL_INTEGRATION.md    # Path A walkthrough — pinned at shell v0.9.1
├── tests/                      # 65 test functions across 14 files
└── sample_*.txt                # Sample CloudSafe Solutions B.V. packet
```

---

## Extending for your organisation

**Add a new framework:**
1. Create `prompts/your_framework.md` with the control requirements.
2. Copy an existing agent (e.g. `agents/resilience_agent.py`) and adapt the system prompt.
3. Add the agent to `AGENT_MAP` in `main.py`.
4. Add routing logic in `orchestrator.py` if it runs conditionally.

**Customise existing frameworks:** edit the markdown files in `prompts/` to match your interpretation or add sector-specific controls.

**Use a single agent standalone:**

```python
from agents.security_agent import run_security_agent

findings = run_security_agent("Your vendor document text here...")
for f in findings:
    print(f"{f.framework} | {f.control_id} | {f.status} | {f.severity}")
```

---

## Running tests

```bash
python -m pytest tests/ -v
```

65 test functions across 14 files covering models, document parser, every agent, synthesizer, output generators, and full pipeline integration. Tests mock the model backend — no API key or Ollama endpoint needed to run them.

## Sample files included

Fictional company CloudSafe Solutions B.V. All names, addresses, dates, identifiers, and findings in these files are synthetic — no real entities or personal data.

- `sample_vendor_q.txt` — main vendor risk questionnaire
- `sample_soc2_report.txt` — SOC 2 Type II report with control test results
- `sample_iso_certificate.txt` — ISO 27001:2022 certificate
- `sample_dora_questionnaire.txt` — DORA self-assessment with known gaps

## Cost estimate

- **Path A (local Ollama):** $0 API cost per run. Inference runs on your own hardware.
- **Path B (cloud):** typical 3-4 document packet → 1 Opus profiling call + 2-4 Sonnet agent calls + 1 Opus memo call.

---

## SAAF Project

Designed for the [SAAF Project](https://saafproject.com) — a vendor-agnostic, open-source initiative where IT and internal auditors from 45+ organisations co-build AI audit agents through 2026 hackathons. The SAAF framework has four components: prompts, tools, guardrails, output formats. This agent follows that structure; the saaf-compliance-shell integration is how it earns the "guardrails" piece at production grade.
