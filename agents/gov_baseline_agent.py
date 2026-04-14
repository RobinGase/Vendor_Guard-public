from agents.base import fallback_finding_from_prose, load_prompt, extract_json, invoke_chat_model
from models.finding import Finding

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a Dutch government information security audit specialist. Assess vendor documentation against BIO2 (Baseline Informatiebeveiliging Overheid 2):

{bio2}

---

## Instructions
- This assessment is conducted because the contracting organization is a Dutch government entity.
- Focus on BIO2-specific requirements: NCSC-approved cryptography, 72h critical patch SLA, 1-year log retention, documented and tested RTO/RPO.
- Only cite evidence explicitly present in the documents.
- Return findings as a JSON array matching this schema exactly:
  [
    {{
      "framework": "BIO2",
      "control_id": "BIO2-CRYPTO-01",
      "control_name": "Use of NCSC-approved cryptographic algorithms",
      "status": "Compliant",
      "severity": "Info",
      "evidence": "AES-256 and TLS 1.3 documented, both NCSC-approved.",
      "recommendation": "No action required."
    }}
  ]
- Return ONLY the JSON array. No preamble or markdown fences.
"""


def run_gov_baseline_agent(vendor_docs: str) -> list[Finding]:
    bio2 = load_prompt("bio2_controls")
    system = SYSTEM_PROMPT.format(bio2=bio2)

    raw = invoke_chat_model(
        model=MODEL,
        max_tokens=8192,
        system=system,
        user_prompt=f"Please assess the following vendor documents:\n\n{vendor_docs}",
    )
    try:
        findings_data = extract_json(raw)
    except Exception:
        findings_data = fallback_finding_from_prose(
            framework="BIO2",
            control_id="BIO2-PROSE-01",
            control_name="Narrative BIO2 assessment",
            raw=raw,
        )
    return [Finding(**f) for f in findings_data]
