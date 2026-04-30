import os
import re
from pathlib import Path

from agents.base import EmptyInferenceResponse, extract_json, invoke_chat_model
from models.finding import VendorProfile

MODEL = "claude-opus-4-6"
MAX_VENDOR_DOC_CHARS = 1200

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
    vendor_docs = vendor_docs[:MAX_VENDOR_DOC_CHARS]
    try:
        raw = invoke_chat_model(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            user_prompt=f"Extract the vendor profile from these documents:\n\n{vendor_docs}",
        )
    except EmptyInferenceResponse as exc:
        # Empty profile call — don't crash the whole pipeline; record
        # the marker in the debug dump and fall through with an empty
        # profile so the security agent still runs on the baseline.
        raw = f"<EMPTY_RESPONSE: {exc}>"
    debug_path = os.getenv("VENDOR_PROFILE_DEBUG_PATH")
    if debug_path:
        Path(debug_path).write_text(raw, encoding="utf-8")
    try:
        data = extract_json(raw)
    except Exception:
        data = _parse_profile_from_prose(raw)
    # extract_json may return a list when the model emits `[{...}]`
    # (a common nemotron/qwen behaviour when the prompt mentions JSON
    # repeatedly). Unwrap a single-dict element; otherwise fall through
    # to prose so .get below doesn't AttributeError on a list.
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        else:
            data = _parse_profile_from_prose(raw)
    # Strip markdown artifacts whichever path produced `data` — local
    # models sometimes wrap the name in `**bold**` even when emitting JSON.
    if isinstance(data.get("name"), str):
        data["name"] = _clean_profile_field(data["name"])
    if isinstance(data.get("sector"), str):
        data["sector"] = _clean_profile_field(data["sector"])
    if isinstance(data.get("services"), list):
        data["services"] = [_clean_profile_field(s) for s in data["services"] if isinstance(s, str) and _clean_profile_field(s)]
    # VendorProfile caps services and applicable_frameworks at 20 items;
    # verbose prose responses (sub-processors + regions + certifications)
    # can easily yield 25+. Truncate before construction so a chatty
    # model doesn't take down the whole pipeline with a ValidationError.
    if isinstance(data.get("services"), list):
        data["services"] = data["services"][:20]
    if isinstance(data.get("applicable_frameworks"), list):
        data["applicable_frameworks"] = data["applicable_frameworks"][:20]
    return VendorProfile(**data)


FINANCIAL_SECTOR_KEYWORDS = ("financ", "bank", "insur", "payment", "fintech", "credit", "asset manag")


def determine_frameworks(profile: VendorProfile) -> list[str]:
    # Security is the baseline for every vendor (ISO 27001 + NIS2 + CBW).
    # Other agents only fire when their framework actually applies — e.g.
    # DORA is scoped to EU financial entities, not every vendor.
    agents = ["security"]
    sector = (profile.sector or "").lower()
    # Honour the LLM's own framework classification too: a SaaS or
    # healthcare-IT vendor whose customers include EU financial entities
    # is in DORA scope even though the vendor's own sector keyword
    # wouldn't match. The orchestrator system prompt tells the model to
    # populate applicable_frameworks for exactly this reason.
    profile_frameworks = {f.upper() for f in (profile.applicable_frameworks or [])}
    if any(kw in sector for kw in FINANCIAL_SECTOR_KEYWORDS) or "DORA" in profile_frameworks:
        agents.append("resilience")
    if profile.is_dutch_government_vendor:
        agents.append("gov_baseline")
    if profile.is_ai_system:
        agents.append("ai_trust")
    return agents


# Chars a local model likes to wrap around field values: markdown bold,
# italics, bullets, trailing punctuation. Stripping these keeps downstream
# renderings (memo title, scorecard) from showing `HealthSync**` etc.
_PROFILE_FIELD_STRIP = " \t*_`#-•:"


def _clean_profile_field(value: str) -> str:
    return value.strip(_PROFILE_FIELD_STRIP).strip()


def _parse_profile_from_prose(raw: str) -> dict:
    def extract(pattern: str, default: str = "") -> str:
        match = re.search(pattern, raw, flags=re.IGNORECASE | re.MULTILINE)
        return _clean_profile_field(match.group(1)) if match else default

    services_raw = re.findall(r"^[-*•]\s+(.+)$", raw, flags=re.MULTILINE)
    services = [_clean_profile_field(s) for s in services_raw if _clean_profile_field(s)]
    frameworks_text = extract(r"Applicable Frameworks:\s*(.+)$")
    frameworks = [_clean_profile_field(item) for item in frameworks_text.split(",") if _clean_profile_field(item)]

    return {
        "name": extract(r"Vendor (?:Profile|Name):\s*(.+)$") or extract(r"Name:\s*(.+)$"),
        "sector": extract(r"Sector:\s*(.+)$"),
        "services": services,
        "processes_personal_data": extract(r"Personal Data Processing:\s*(.+)$").lower().startswith("y"),
        "is_ai_system": extract(r"AI System:\s*(.+)$").lower().startswith("y"),
        "is_dutch_government_vendor": extract(r"Dutch Government Client:\s*(.+)$").lower().startswith("y"),
        "applicable_frameworks": frameworks,
    }
