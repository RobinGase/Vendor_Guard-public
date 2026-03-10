import json
import anthropic
from models.finding import VendorProfile

MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """You are a vendor risk assessment orchestrator. Extract a structured vendor profile from the provided documents.

Return a JSON object with these exact fields:
{
  "name": "vendor legal name",
  "sector": "primary sector (Finance, Technology, Government, Healthcare, etc.)",
  "services": ["list", "of", "services"],
  "processes_personal_data": true or false,
  "is_ai_system": true if the vendor is an AI system or AI-powered product,
  "is_dutch_government_vendor": true if this vendor serves Dutch government entities,
  "applicable_frameworks": ["ISO 27001", "NIS2", "CBW", "DORA", "BIO2", "EU AI Act", "ALTAI", "EC Ethics"]
}

applicable_frameworks should include all frameworks relevant to this vendor based on their profile.
Return ONLY the JSON object. No preamble or markdown fences.
"""


def build_vendor_profile(vendor_docs: str) -> VendorProfile:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Extract the vendor profile from these documents:\n\n{vendor_docs}",
            }
        ],
    )
    raw = message.content[0].text.strip()
    data = json.loads(raw)
    return VendorProfile(**data)


def determine_frameworks(profile: VendorProfile) -> list[str]:
    agents = ["security", "resilience"]
    if profile.is_dutch_government_vendor:
        agents.append("gov_baseline")
    if profile.is_ai_system:
        agents.append("ai_trust")
    return agents
