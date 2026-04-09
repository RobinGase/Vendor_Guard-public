# Vendor Guard Codebase Analysis

## Purpose

`vendor_guard` is a Python CLI agent that performs a vendor risk assessment against a set of EU and Dutch regulatory frameworks. It takes a vendor questionnaire plus supporting evidence documents, uses Claude to classify the vendor and assess compliance, then produces management-facing outputs.

The repository is solving a real audit workflow problem:

- ingest vendor evidence
- decide which regulatory lenses apply
- run specialist assessment agents
- normalize findings into a common structure
- summarize risk into a RAG scorecard
- generate deliverables for both Microsoft Office and Google Workspace users

This is not just a prompt collection. It is an end-to-end assessment pipeline with a clear operational output.

## What The System Does

At a high level, the pipeline works like this:

1. `main.py` accepts a questionnaire, optional supporting docs, and an output directory.
2. `utils/document_parser.py` reads each file and concatenates the extracted text into a single string with file markers.
3. `agents/orchestrator.py` asks Claude Opus to infer a `VendorProfile` from the combined documents.
4. `determine_frameworks()` maps that profile to the specialist agents that should run.
5. `main.py` runs those agents in parallel with `ThreadPoolExecutor`.
6. Each specialist agent returns `Finding` objects.
7. `synthesizer/synthesizer.py` computes a per-framework RAG summary.
8. `synthesizer/scorecard.py`, `synthesizer/memo.py`, and `synthesizer/google_output.py` write final deliverables.

Outputs currently include:

- `scorecard.xlsx`
- `gap_register.xlsx`
- `audit_memo.docx`
- `scorecard.csv`
- `gap_register.csv`
- `audit_memo.html`

## Architecture Overview

### Entry Point

`main.py` is intentionally simple and readable. It acts as the pipeline orchestrator and keeps the overall control flow in one place.

Key responsibilities:

- parse CLI arguments
- create the output directory
- ingest documents
- build the vendor profile
- select and run agents
- aggregate findings
- write outputs

This is a good fit for the current project size. The file is short enough to understand quickly, and the top-level execution path is easy to follow.

### Agents Layer

The `agents/` package contains:

- `orchestrator.py`: infers vendor profile and routes work
- `security_agent.py`: ISO 27001, NIS2, CBW
- `resilience_agent.py`: DORA
- `gov_baseline_agent.py`: BIO2
- `ai_trust_agent.py`: EU AI Act, ALTAI, EC Ethics
- `base.py`: prompt loading and JSON extraction helpers

This is the core domain layer. The design is straightforward: each agent is a thin wrapper around a framework-specific system prompt plus response parsing.

The main architectural pattern is:

- load framework markdown from `prompts/`
- embed it into a system prompt
- send vendor docs to Claude
- parse returned JSON
- validate into `Finding` models

This pattern is consistent and easy to extend. That is one of the codebase's best traits.

### Models Layer

`models/finding.py` defines the shared contract for the rest of the application:

- `Finding`
- `VendorProfile`

The model layer does useful normalization work:

- severity aliases are mapped to canonical values
- status aliases are mapped to canonical values
- invalid model output is partially absorbed rather than immediately breaking everything

This is a practical choice for LLM-driven code, where output variation is normal.

### Parsing Layer

`utils/document_parser.py` handles file ingestion for:

- TXT
- PDF
- DOCX
- XLSX/XLS

The parser converts all files into plain text and injects file boundaries using `=== FILE: ... ===` markers. That is a simple but effective way to preserve some provenance for the LLM.

### Synthesis And Output Layer

The `synthesizer/` package is responsible for turning raw findings into deliverables:

- `synthesizer.py`: risk summary logic
- `scorecard.py`: Excel scorecard and gap register
- `memo.py`: AI-generated memo in DOCX form
- `google_output.py`: CSV and HTML output for Google Workspace users

This split is sensible. It separates:

- scoring logic
- formatted spreadsheet output
- narrative memo generation
- web-friendly text output

## End-To-End Data Flow

The actual data shape through the system looks like this:

1. Files on disk
2. Combined plain-text corpus via `parse_documents()`
3. `VendorProfile` from orchestrator
4. `list[Finding]` from each specialist agent
5. merged `list[Finding]`
6. scorecard `dict`
7. file outputs

The most important internal contract is the `Finding` model. Nearly every part of the application depends on it being stable.

That is a good design choice because it gives the project one shared schema for:

- tests
- agent output parsing
- scorecard generation
- gap register generation
- memo drafting

## What Is Good

### 1. Clear decomposition

The repository has clean major boundaries:

- ingestion
- profiling
- specialist assessment
- synthesis
- output generation

That makes the project easier to reason about than many hackathon repositories.

### 2. Strong practical use case

This is not a toy app. It targets a workflow auditors actually care about:

- vendor due diligence
- third-party risk
- multi-framework compliance review
- management reporting

That makes it a strong candidate for continued contribution because the output is immediately legible to users.

### 3. Good extension model

Adding a new framework is conceptually simple:

- add framework content in `prompts/`
- create another agent module
- register it in `AGENT_MAP`
- update routing logic

That is a healthy sign. The repo already behaves like a platform for framework-specific agents.

### 4. Useful model normalization

`models/finding.py` does important cleanup for inconsistent LLM output. Without this, the system would be much more fragile.

This is one of the most production-minded parts of the codebase.

### 5. JSON salvage logic is pragmatic

`agents/base.py` includes truncated-array salvage in `_salvage_truncated_array()`. That is a very practical workaround for long LLM responses and clearly comes from real usage pain.

### 6. Test suite exists across the main layers

The repository has tests for:

- models
- orchestrator
- agents
- parser
- synthesizer
- scorecard generation
- memo generation
- integration flow

For a hackathon-origin repo, that is a strong foundation.

### 7. Dual output strategy is smart

Supporting both Office and Google Workspace is a good product decision. It makes the tool more usable across different organizations without changing the core assessment logic.

## What Needs Work

### 1. Heavy duplication in agent implementations

The specialist agents appear to repeat the same structure:

- load prompt files
- build system prompt
- instantiate Anthropic client
- call `messages.create`
- parse JSON
- convert to `Finding`

This is manageable at the current size, but it will become maintenance debt as more frameworks are added.

What to improve:

- centralize the common LLM call and parsing flow in `agents/base.py`
- reduce each agent file to its framework-specific prompt assembly and metadata

### 2. Minimal error handling around external dependencies

The pipeline assumes many external operations succeed:

- Anthropic API calls
- document parsing libraries
- output writing
- LLM JSON format correctness

There is almost no explicit retry, recovery, or user-friendly failure reporting in `main.py` or the agent modules.

Likely failure modes today:

- API timeout or quota error aborts the full run
- malformed or empty model output crashes an agent
- one failed agent likely aborts the whole pipeline
- badly extracted PDF text silently degrades assessment quality

This is the single biggest gap between "good prototype" and "reliable internal tool".

### 3. `aggregate_findings()` is a stub

`synthesizer/aggregate_findings()` currently just returns the list unchanged.

That means the codebase has a named consolidation step but no actual consolidation logic yet.

Potential responsibilities for this function:

- deduplicate repeated findings
- merge near-identical controls across frameworks
- sort by severity and framework
- normalize empty evidence or recommendation fields
- tag findings with source agent

This is a strong contribution target because the abstraction already exists.

### 4. Framework routing is simplistic

`determine_frameworks()` only uses two booleans:

- `is_dutch_government_vendor`
- `is_ai_system`

Everything else defaults to security plus resilience.

That is simple and understandable, but it leaves value on the table. The `VendorProfile` already contains more information than the router uses.

Opportunities:

- route based on sector
- route based on personal-data processing
- distinguish software vendor vs infrastructure vendor vs advisory provider
- use `applicable_frameworks` more directly instead of ignoring most of it

### 5. Weak provenance in findings

Findings contain evidence quotes, but the structured model does not preserve source metadata such as:

- source file name
- page/sheet/paragraph
- agent that produced the finding

For audit tooling, provenance matters. Right now the text markers in `parse_documents()` help the LLM, but the final finding objects do not retain structured traceability.

### 6. Output artifacts and cache files are tracked in the repo

The working tree includes generated and cache-oriented content such as:

- `output/` files
- `__pycache__/` directories

That is a hygiene issue.

Why it matters:

- noise in diffs
- larger repo history
- confusion about what is source vs generated output
- avoidable merge friction

This is low effort to fix and worth doing early.

### 7. No explicit config layer

Important operational settings are embedded in code:

- model names
- token limits
- output defaults
- framework selection behavior

That makes experimentation and environment-specific tuning harder than necessary.

A small config module or settings object would help without overengineering the repo.

### 8. Logging is just `print`

`main.py` uses simple console printing. That is fine for a local CLI, but it becomes limiting if you want:

- structured logs
- silent mode vs verbose mode
- per-agent timing
- easier debugging of failed runs

This is not urgent, but it is an obvious maturity step.

### 9. The parser is intentionally simple but loses structure

`document_parser.py` flattens everything into plain text.

Benefits:

- easy to implement
- LLM-friendly
- consistent across file types

Cost:

- loses sheet names, headings, table context, and positional metadata
- difficult to reference exact evidence locations later
- weak basis for deterministic post-processing

This is acceptable for the current version, but it is a likely ceiling for assessment quality.

## Testing Assessment

The test suite is a real strength, but it currently looks stronger on mocked flow than on hard edge cases.

What the tests are doing well:

- validating the general pipeline shape
- mocking Anthropic cleanly
- checking file outputs are created
- verifying routing and model normalization behavior

What appears under-tested from the current code review:

- partial failure of one parallel agent
- malformed outputs that are not recoverable by `extract_json`
- parser behavior on ugly real-world PDFs and spreadsheets
- duplicate findings across agents
- ordering and determinism of scorecards
- missing or invalid environment configuration

The tests provide confidence that the happy-path system works. They do not yet provide strong confidence that the pipeline is resilient under messy input and API behavior.

## Current Maturity Level

My assessment is:

- stronger than a throwaway hackathon prototype
- not yet a hardened internal production tool

Why it is beyond a prototype:

- coherent architecture
- shared data model
- multiple outputs
- decent tests
- clear extension path

Why it is not yet production-grade:

- limited error handling
- weak provenance
- duplicated agent plumbing
- stubbed aggregation layer
- tracked generated artifacts

## Best Areas To Work On Next

### Priority 1: Reliability and failure handling

Best return on effort.

Concrete improvements:

- catch and report Anthropic API failures per agent
- allow one agent to fail without losing the entire run
- add clearer error messages for bad documents and missing API keys
- introduce timeouts and retry strategy where sensible

### Priority 2: Real aggregation logic

`aggregate_findings()` is the clearest unfinished abstraction in the repo.

Concrete improvements:

- deduplicate findings by framework plus control ID
- merge repeated findings with best evidence retained
- sort findings by severity, status, and framework for stable output
- add metadata about source agent

### Priority 3: Agent abstraction cleanup

Refactor the repeated agent pattern into reusable helpers.

Concrete improvements:

- helper for Anthropic call creation
- helper for converting parsed objects to `Finding`
- optional shared agent runner with model name, prompt fragments, and framework label inputs

This will make future framework additions faster and safer.

### Priority 4: Traceability and evidence provenance

This is a strong audit-specific enhancement.

Concrete improvements:

- extend `Finding` with source file metadata
- preserve parser-level source information in a richer document representation
- include source references in final outputs

### Priority 5: Repo hygiene and contributor experience

Low difficulty, worthwhile cleanup.

Concrete improvements:

- remove tracked generated output files
- remove tracked `__pycache__` directories
- improve `.gitignore`
- add a setup path that is more deterministic than raw `requirements.txt` alone

## Best First Contribution Ideas

If the goal is a high-value first contribution, these are the strongest candidates.

### Option A: Implement `aggregate_findings()` properly

Why this is attractive:

- small surface area
- clearly useful
- already has a named hook in the architecture
- improves every output

### Option B: Add resilient per-agent execution in `main.py`

Why this is attractive:

- directly improves reliability
- visible operational value
- does not require major redesign

Example direction:

- collect per-agent exceptions
- continue with successful agents
- include failed-agent notes in console output or memo

### Option C: Clean up generated artifacts and repo hygiene

Why this is attractive:

- fast win
- reduces confusion immediately
- good precursor before larger refactors

### Option D: Introduce a shared agent runner helper

Why this is attractive:

- reduces duplication
- prepares the repo for additional frameworks
- improves maintainability

## Suggested Contribution Order

Recommended sequence:

1. repo hygiene cleanup
2. resilient error handling in pipeline and agents
3. real `aggregate_findings()` implementation
4. shared agent abstraction refactor
5. provenance-rich findings and richer parser model

That order improves the codebase without overcomplicating it too early.

## Overall Assessment

`vendor_guard` has strong contribution potential because it already has:

- a meaningful audit use case
- a usable architecture
- clear module boundaries
- tests and output generation
- room for real engineering improvements

Its best qualities are practicality, clarity, and extensibility.

Its main weaknesses are reliability, duplication, and incomplete consolidation logic.

If this repo is going to become one of the stronger SAAF implementations, the path is straightforward: keep the architecture simple, make failures survivable, improve traceability, and harden the middle of the pipeline where findings are normalized and aggregated.
