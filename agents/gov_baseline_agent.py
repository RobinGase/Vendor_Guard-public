import anthropic
from agents.base import load_prompt, extract_json, require_anthropic_api_key
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

    client = anthropic.Anthropic(api_key=require_anthropic_api_key())
    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system,
        messages=[
            {
                "role": "user",
                "content": f"Please assess the following vendor documents:\n\n{vendor_docs}",
            }
        ],
    )

    raw = message.content[0].text.strip()
    findings_data = extract_json(raw)
    return [Finding(**f) for f in findings_data]
