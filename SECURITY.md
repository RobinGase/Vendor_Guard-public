# Security Policy

## Reporting a vulnerability

If you believe you've found a security issue in Vendor_Guard, please **do not** open a public GitHub issue. Report it through either channel below — email is preferred, GitHub's private advisory form is the fallback. We aim to acknowledge within 72 hours and to triage within five business days.

- **Email (primary):** `security@kai-zen-innovations.com`
- **GitHub Security Advisory (fallback):** <https://github.com/RobinGase/Vendor_Guard-public/security/advisories/new>

If the issue is in the `saaf-compliance-shell` (the Firecracker + NeMo + Presidio layer that wraps Vendor_Guard in Path A), report it against that repository instead.

Please include:

- A description of the issue and the path from untrusted input to the affected code.
- A minimal reproducer (PoC script, crafted document, or env-variable configuration).
- The Vendor_Guard commit SHA and run path (A or B).
- Your assessment of severity and blast radius.

We do not currently operate a bug bounty. Credited disclosure is offered in the release notes if the reporter wants it.

## Supported versions

Only the `main` branch is supported. Pre-release tags are for reference; security fixes are cherry-picked onto `main` and released there.

The `saaf-compliance-shell` integration is pinned at **v0.9.1**. If you run Vendor_Guard against a different shell version, the trust properties described below may not hold.

## Scope

### In scope

- Vendor_Guard's Python code, tests, sample inputs, TUI, and manifest.
- The staging and environment-file interface between the host TUI and the shell VM (`saaf_run.sh`, `saaf_entrypoint.py`, `/audit_workspace/queued.env`).
- Document parsing in `utils/document_parser.py`.
- The HTML / DOCX / XLSX / CSV output generators.

### Out of scope

- The `saaf-compliance-shell` internals (report to that repo instead).
- Vulnerabilities that require the attacker to already have root on the host.
- Prompt injection in Path B (cloud, no shell). Path B is development-only and refuses to run without an explicit `SAAF_ALLOW_UNGUARDED=1` opt-in.
- Third-party dependencies — report those upstream and we'll track / pin.

## Threat model summary

### Trust boundaries

1. **Host ↔ VM (Path A only).** Vendor_Guard runs inside a Firecracker microVM. The host writes queued inputs and `queued.env` to a shared workspace; the VM reads them. The workspace is the trust boundary, not the network.
2. **Chat backend ↔ raw vendor documents.** The TUI chat backend (Claude Code SDK or Anthropic API) never sees raw vendor document text. Only filenames, sizes, the audit summary, and the *already-guardrailed* artefacts under `output/` reach the chat model. This is enforced in `tui.py::_build_chat_context`.
3. **LLM ↔ spreadsheet cells.** Model output flows into XLSX and CSV cells. Evidence / recommendation fields are user-influenceable via prompt injection in vendor documents, so cell values are sanitized against formula triggers (`=+-@\t\r`) at every writer site.

### Attacker models we defend against

- **Malicious vendor document.** The vendor submits a SOC 2 or questionnaire that contains prompt-injection payloads trying to make the agent emit false compliance findings, leak system-prompt text, or place formulas into output cells. Mitigations: Path A's NeMo Guardrails + Presidio, Pydantic Literal constraints on `status` and `severity`, formula-injection sanitization on all spreadsheet writes.
- **Malicious operator environment.** An attacker who can set environment variables for the TUI process should not gain command execution. Mitigations: no `sh -c` with env-var interpolation, URL scheme + host allowlist for `INFERENCE_URL`, argv-list subprocess calls everywhere sudo is used.
- **Malicious filename.** A vendor document with a crafted filename (newlines, shell metacharacters, quote characters) should not escape the staging layer. Mitigations: the host-side denylist rejects `\"`, `\\`, `$`, backtick, single-quote, newline, CR, and tab before staging; the VM-side parser re-checks.

### Attacker models explicitly out of scope

- A compromised host kernel or a compromised Firecracker VMM. The shell is our defense against agent compromise; the shell trusts the host kernel.
- A compromised Ollama / local model endpoint inside the VM's trust zone. We trust the model to be honest-but-possibly-manipulated, not to be an active adversary.
- Side-channel attacks against the model's weights or context.

## Security-relevant configuration

- `SAAF_ALLOW_UNGUARDED=1` — required to run Path B (no shell, no guardrails). Do not set this on any host that will process real vendor data.
- `SAAF_INFERENCE_HOST_ALLOWLIST` — comma-separated hostname / IP list that `INFERENCE_URL` must match. Defaults to `172.16.0.1,127.0.0.1,localhost`. Override only if you know you're pointing at a non-default gateway.
- `SAAF_SHELL_ROOTFS` — the shell rootfs path. Despite being used in several privileged codepaths, it is never passed through `sh -c` and never interpolated into shell commands. Still, treat it as security-relevant and do not allow untrusted users to set it for the TUI process.
- `VENDOR_AGENT_DEBUG_DIR` — when set, raw model responses are written here. Debug output may contain reproductions of injected vendor content. Point it at a path with restricted permissions and purge it when the session ends.

## Logging and evidence

Path A runs are recorded in the shell's hash-chained audit log (`/var/lib/saaf/audit.jsonl` by default). This log includes the manifest hash, start and end timestamps, and a hash of every tool invocation. If you suspect a security incident, preserve this file along with the `output/` artefacts and the `reasoning/` folder for that session before rerunning anything.

Path B produces no audit log. This is one of the reasons Path B is gated behind `SAAF_ALLOW_UNGUARDED=1`.

## Change log for security fixes

See the release notes on `main`. Security-relevant changes are tagged `[security]` in the commit message.
