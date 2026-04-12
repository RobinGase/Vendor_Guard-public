from agents.base import load_prompt, extract_json, invoke_chat_model
from models.finding import Finding

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a cybersecurity audit specialist. Your task is to assess vendor documentation against the following regulatory frameworks:

{iso27001}

---

{nis2}

---

{cbw}

---

## Instructions
- Review the provided vendor documents carefully.
- For each control area, determine if the vendor is Compliant, has a Gap, is Partial, or if the control is Not Applicable.
- Only cite evidence that is explicitly present in the documents. Never invent or assume information.
- If evidence is absent, mark it as a Gap and note "No evidence provided."
- Return your findings as a JSON array of objects matching this schema exactly:
  [
    {{
      "framework": "ISO 27001",
      "control_id": "A.9.1",
      "control_name": "Access control policy",
      "status": "Gap",
      "severity": "High",
      "evidence": "No access control policy mentioned in vendor documentation.",
      "recommendation": "Provide a documented and approved access control policy."
    }}
  ]
- Return ONLY the JSON array. No preamble, no explanation, no markdown fences.
"""


def run_security_agent(vendor_docs: str) -> list[Finding]:
    iso27001 = load_prompt("iso27001_controls")
    nis2 = load_prompt("nis2_measures")
    cbw = load_prompt("cbw_requirements")

    system = SYSTEM_PROMPT.format(iso27001=iso27001, nis2=nis2, cbw=cbw)

    raw = invoke_chat_model(
        model=MODEL,
        max_tokens=8192,
        system=system,
        user_prompt=f"Please assess the following vendor documents:\n\n{vendor_docs}",
    )
    findings_data = extract_json(raw)
    return [Finding(**f) for f in findings_data]
