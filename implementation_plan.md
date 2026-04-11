# SAAF-Shell Implementation Plan

## Goal
Build a reusable compliance wrapper that reads a target repo manifest, generates sandbox and guardrail policy, and executes the target inside a dual-layer shell with filesystem, network, and privacy controls.

## Architecture
`saaf-compliance-shell` should be a sidecar CLI with three layers:
1. a manifest-driven policy compiler
2. an OpenShell sandbox runtime
3. a NeMo Guardrails policy runtime

`Vendor_Guard` is the first adapter target and should be integrated by invoking its existing `main.py` CLI rather than rewriting its internals.

## Tech Stack
- Python 3.11+
- JSON Schema / Pydantic
- NVIDIA OpenShell
- NeMo Guardrails with Colang 2.0
- Local OpenAI-compatible inference endpoint at `http://localhost:11434/v1`
- pytest
- Linux / WSL for Landlock verification

## Critical Constraints
- `Landlock` is Linux-only. Actual sandbox enforcement and verification must run in Linux, WSL2, or a Linux server.
- Use `RobinGase/Vendor_Guard` private fork as the first target.
- Prefer `target path` over submodule for v1.
- Start with deterministic regex for email and IBAN masking.
- Do not block v1 on perfect name detection.

## Recommended Repo Layout
```text
saaf-compliance-shell/
├── README.md
├── pyproject.toml
├── saaf_run.py
├── saaf_shell/
│   ├── __init__.py
│   ├── cli.py
│   ├── manifest.py
│   ├── policy_compiler.py
│   ├── sandbox.py
│   ├── target_loader.py
│   ├── runtime.py
│   ├── streaming.py
│   ├── rails_runtime.py
│   ├── rails_actions.py
│   ├── pii.py
│   └── models.py
├── config/
│   ├── rails/
│   │   ├── config.yml
│   │   ├── flows.co
│   │   ├── input_rails.co
│   │   ├── output_rails.co
│   │   └── resilience_rails.co
│   └── master_security_policy.yaml
├── templates/
│   ├── sandbox_config.template.yaml
│   └── manifest.schema.json
├── examples/
│   ├── vendor_guard.manifest.json
│   └── attack_cases/
│       ├── hardcoded_email.txt
│       └── forbidden_read_case.md
├── tests/
│   ├── test_manifest.py
│   ├── test_policy_compiler.py
│   ├── test_pii.py
│   ├── test_rails_actions.py
│   ├── test_sandbox.py
│   ├── test_runtime.py
│   ├── test_vendor_guard_adapter.py
│   └── test_end_to_end_shell.py
└── docs/
    ├── architecture.md
    ├── target-integration.md
    └── verification.md
```

## Phase 0: Platform and Integration Decisions
- Use `RobinGase/Vendor_Guard` private fork as first target
- Treat target as an external process with a manifest contract
- Prefer `target path` over submodule for v1
- Use local model endpoint env vars for Ollama/NIM
- Run sandbox verification in Linux/WSL only

## Task 1: Initialize `saaf-compliance-shell`
Files:
- `README.md`
- `pyproject.toml`
- `saaf_run.py`
- `saaf_shell/__init__.py`
- `saaf_shell/cli.py`
- `tests/test_runtime.py`

Deliverables:
- thin CLI entrypoint
- argument parsing for target path, manifest path, sandbox output path, model endpoint, and streaming

## Task 2: Define the SAAF Compatibility Manifest
Files:
- `templates/manifest.schema.json`
- `saaf_shell/models.py`
- `saaf_shell/manifest.py`
- `examples/vendor_guard.manifest.json`
- `tests/test_manifest.py`

Manifest fields:
- `name`
- `entrypoint`
- `required_filesystem_paths`
- `approved_outbound_domains`
- `approved_outbound_endpoints`
- `compliance_level`
- `input_paths`
- `output_paths`
- `environment`
- `streaming`
- `tool_timeout_seconds`

## Task 3: Build the Policy Compiler
Files:
- `saaf_shell/policy_compiler.py`
- `templates/sandbox_config.template.yaml`
- `tests/test_policy_compiler.py`

Responsibilities:
- read `manifest.json`
- generate `sandbox_config.yaml`
- convert filesystem paths into Landlock rules
- default deny outbound traffic
- allow only localhost inference endpoints

## Task 4: Add the OpenShell Runtime Wrapper
Files:
- `saaf_shell/sandbox.py`
- `saaf_shell/target_loader.py`
- `saaf_run.py`
- `tests/test_sandbox.py`

Responsibilities:
- resolve target repo root
- find manifest
- generate sandbox config
- execute target through `openshell`
- support dry-run mode

## Task 5: Add Local Model and Streaming Configuration
Files:
- `saaf_shell/streaming.py`
- `saaf_shell/runtime.py`
- `config/rails/config.yml`
- `tests/test_runtime.py`

Responsibilities:
- normalize local model endpoint config
- support Ollama and optional NIM localhost endpoints
- enable streaming for low-latency guardrails

## Task 6: Scaffold NeMo Guardrails Config
Files:
- `config/rails/config.yml`
- `config/rails/flows.co`
- `config/rails/input_rails.co`
- `config/rails/output_rails.co`
- `config/rails/resilience_rails.co`
- `saaf_shell/rails_runtime.py`
- `saaf_shell/rails_actions.py`
- `tests/test_rails_actions.py`

Responsibilities:
- load master security policy
- register rail actions
- separate input, output, and resilience concerns

## Task 7: Implement Input Rail for PII Masking
Files:
- `saaf_shell/pii.py`
- `saaf_shell/rails_actions.py`
- `config/rails/input_rails.co`
- `tests/test_pii.py`

PII scope for v1:
- Email via regex
- IBAN via regex
- Names via pluggable provider with conservative fallback

Behavior:
- sanitize input before target reasoning/tool execution
- replace with stable placeholders

## Task 8: Implement DORA Resilience Rail
Files:
- `saaf_shell/rails_actions.py`
- `config/rails/resilience_rails.co`
- `saaf_shell/runtime.py`
- `tests/test_rails_actions.py`

Behavior:
- monitor tool-call latency
- if duration is over 10s, emit `Resilience Alert`

Alert payload:
- tool name
- duration
- target repo
- compliance level
- timestamp

## Task 9: Implement GDPR Output Rail
Files:
- `config/rails/output_rails.co`
- `saaf_shell/rails_actions.py`
- `tests/test_rails_actions.py`

Behavior:
- sanitize outgoing logs and structured events
- prevent raw PII from appearing in logs or outputs

## Task 10: Build End-to-End Runtime Orchestrator
Files:
- `saaf_shell/runtime.py`
- `saaf_shell/cli.py`
- `saaf_run.py`
- `tests/test_end_to_end_shell.py`

Flow:
1. read target manifest
2. compile OpenShell YAML
3. initialize NeMo Guardrails
4. sanitize input
5. execute target in sandbox
6. stream output through rails
7. emit sanitized logs and alerts

## Task 11: Add Vendor_Guard Adapter and Example Target
Files:
- `docs/target-integration.md`
- `examples/vendor_guard.manifest.json`
- `tests/test_vendor_guard_adapter.py`

Approach:
- keep `Vendor_Guard` unchanged
- invoke its existing CLI
- use shell-side manifest for policy generation

## Task 12: Verification and Attack Simulation
Files:
- `docs/verification.md`
- `examples/attack_cases/hardcoded_email.txt`
- `examples/attack_cases/forbidden_read_case.md`
- `tests/test_end_to_end_shell.py`

Verification scenarios:
- target tries to read `/etc/shadow` -> blocked by OpenShell/Landlock
- target tries outbound non-localhost traffic -> blocked by network policy
- target emits raw email -> masked by output rail
- fake tool sleeps 11 seconds -> `Resilience Alert`

Important:
- use a fake malicious target for attack verification
- do not modify `Vendor_Guard` itself to become malicious

## Recommended Execution Order
1. repo init
2. manifest
3. policy compiler
4. sandbox wrapper
5. local model config
6. guardrails scaffold
7. input rails
8. output rails
9. resilience rails
10. runtime orchestration
11. Vendor_Guard integration
12. attack verification

## Risks
1. Landlock requires Linux/WSL
2. OpenShell interface details may vary
3. Guardrails can add latency
4. Name masking can create false positives
5. Private fork/public mirror confusion

## What Not To Do In v1
- do not rewrite `Vendor_Guard`
- do not try to perfect name masking immediately
- do not combine submodule support and target-path support in the first pass
- do not build a plugin system before one target works end-to-end

## Recommended First Milestone
Build only:
- repo init
- manifest loader
- policy compiler
- sandbox wrapper
- localhost-only network policy
- fake target verification

## Key Decisions To Confirm Before Implementation
1. Should `saaf-compliance-shell` be private initially?
2. Is `target-path only` acceptable for v1?
3. Is WSL/Linux the official verification environment?
4. Is conservative PII detection acceptable for v1?
