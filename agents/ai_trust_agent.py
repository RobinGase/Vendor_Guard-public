from agents.base import fallback_finding_from_prose, load_prompt, extract_json, invoke_chat_model
from models.finding import Finding

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are an AI ethics and governance audit specialist. Assess this AI vendor's documentation against three frameworks:

## EU AI Act
{ai_act}

---

## ALTAI
{altai}

---

## EC Ethical Guidelines for Trustworthy AI
{ec_ethics}

---

## Instructions
- Determine the AI risk classification (Prohibited / High-risk / Limited risk / Minimal risk) and state it in the first finding.
- Check all high-risk AI obligations if applicable.
- Cross-reference ALTAI's 7 requirements and the EC Ethics 4 principles.
- Only cite evidence explicitly present in the documents.
- Return findings as a JSON array matching this schema exactly:
  [
    {{
      "framework": "EU AI Act",
      "control_id": "Art.9",
      "control_name": "Risk management system",
      "status": "Gap",
      "severity": "Critical",
      "evidence": "No risk management system documentation provided.",
      "recommendation": "Provide documented risk management system per EU AI Act Art.9."
    }}
  ]
- Return ONLY the JSON array. No preamble or markdown fences.
"""


def run_ai_trust_agent(vendor_docs: str) -> list[Finding]:
    ai_act = load_prompt("ai_act_requirements")
    altai = load_prompt("altai_requirements")
    ec_ethics = load_prompt("ec_ethics_guidelines")

    system = SYSTEM_PROMPT.format(ai_act=ai_act, altai=altai, ec_ethics=ec_ethics)

    raw = invoke_chat_model(
        model=MODEL,
        max_tokens=8192,
        system=system,
        user_prompt=f"Please assess the following AI vendor documents:\n\n{vendor_docs}",
    )
    try:
        findings_data = extract_json(raw)
    except Exception:
        findings_data = fallback_finding_from_prose(
            framework="EU AI Act",
            control_id="AI-PROSE-01",
            control_name="Narrative AI trust assessment",
            raw=raw,
        )
    return [Finding(**f) for f in findings_data]
