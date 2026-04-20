from agents.base import JSONRetryFailed, fallback_finding_from_prose, invoke_chat_model_json, load_prompt
from models.finding import Finding

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a digital operational resilience audit specialist. Assess vendor documentation against DORA (Digital Operational Resilience Act):

{dora}

---

## Instructions
- Review vendor documents carefully against each DORA pillar.
- Flag if the vendor may qualify as a Critical ICT Third-Party Provider (CTPP).
- Only cite evidence explicitly present in the documents.
- Return findings as a JSON array matching this schema exactly:
  [
    {{
      "framework": "DORA",
      "control_id": "Art.9",
      "control_name": "ICT risk management framework",
      "status": "Gap",
      "severity": "Critical",
      "evidence": "No ICT risk management framework documentation provided.",
      "recommendation": "Provide documented ICT risk management framework per DORA Art.9."
    }}
  ]
- Return ONLY the JSON array. No preamble or markdown fences.
"""


def run_resilience_agent(vendor_docs: str) -> list[Finding]:
    dora = load_prompt("dora_requirements")
    system = SYSTEM_PROMPT.format(dora=dora)

    try:
        findings_data, _ = invoke_chat_model_json(
            model=MODEL,
            max_tokens=8192,
            system=system,
            user_prompt=f"Please assess the following vendor documents:\n\n{vendor_docs}",
            debug_tag="resilience",
        )
    except JSONRetryFailed as exc:
        findings_data = fallback_finding_from_prose(
            framework="DORA",
            control_id="DORA-PROSE-01",
            control_name="Narrative resilience assessment",
            raw=exc.last_raw,
        )
    return [Finding(**f) for f in findings_data]
