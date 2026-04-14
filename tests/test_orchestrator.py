import json
from pathlib import Path
from unittest.mock import MagicMock
from agents.orchestrator import build_vendor_profile, determine_frameworks
from models.finding import VendorProfile

SAMPLE_DOCS_NON_AI = """
=== FILE: questionnaire.txt ===
Vendor: DataSafe B.V.
Sector: Finance
Services: Data backup and archival
Personal data: Yes
AI system: No
Government client: No
"""

SAMPLE_DOCS_AI_GOV = """
=== FILE: questionnaire.txt ===
Vendor: GovAI Solutions
Sector: Technology
Services: AI document classification for Dutch municipalities
Personal data: Yes
AI system: Yes
Government client: Yes
"""


def make_mock_response(profile_dict: dict):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(profile_dict)
    return mock_msg


def test_build_vendor_profile_non_ai(mocker):
    profile_data = {
        "name": "DataSafe B.V.",
        "sector": "Finance",
        "services": ["Data backup", "Archival"],
        "processes_personal_data": True,
        "is_ai_system": False,
        "is_dutch_government_vendor": False,
        "applicable_frameworks": ["ISO 27001", "NIS2", "CBW", "DORA"],
    }
    mocker.patch("agents.orchestrator.invoke_chat_model", return_value=json.dumps(profile_data))

    profile = build_vendor_profile(SAMPLE_DOCS_NON_AI)
    assert isinstance(profile, VendorProfile)
    assert profile.is_ai_system is False
    assert "DORA" in profile.applicable_frameworks


def test_build_vendor_profile_truncates_large_document_bundle(mocker):
    captured = {}

    def fake_invoke_chat_model(*, model, system, user_prompt, max_tokens):
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "name": "DataSafe B.V.",
                "sector": "Finance",
                "services": ["Data backup"],
                "processes_personal_data": True,
                "is_ai_system": False,
                "is_dutch_government_vendor": False,
                "applicable_frameworks": ["ISO 27001", "DORA"],
            }
        )

    mocker.patch("agents.orchestrator.invoke_chat_model", side_effect=fake_invoke_chat_model)

    build_vendor_profile("A" * 50000)

    assert len(captured["user_prompt"]) < 6000


def test_build_vendor_profile_extracts_json_from_wrapped_response(mocker):
    wrapped = "Vendor summary follows:\n\n{\"name\": \"DataSafe B.V.\", \"sector\": \"Finance\", \"services\": [\"Data backup\"], \"processes_personal_data\": true, \"is_ai_system\": false, \"is_dutch_government_vendor\": false, \"applicable_frameworks\": [\"ISO 27001\", \"DORA\"]}"
    mocker.patch("agents.orchestrator.invoke_chat_model", return_value=wrapped)

    profile = build_vendor_profile(SAMPLE_DOCS_NON_AI)

    assert profile.name == "DataSafe B.V."


def test_build_vendor_profile_writes_raw_response_when_debug_path_set(mocker, monkeypatch, tmp_path: Path):
    debug_path = tmp_path / "orchestrator_raw.txt"
    monkeypatch.setenv("VENDOR_PROFILE_DEBUG_PATH", str(debug_path))
    mocker.patch("agents.orchestrator.invoke_chat_model", return_value="not json at all")

    build_vendor_profile(SAMPLE_DOCS_NON_AI)

    assert debug_path.read_text(encoding="utf-8") == "not json at all"


def test_build_vendor_profile_parses_structured_prose_response(mocker):
    prose = """
Vendor Profile: CloudSafe Solutions B.V.
Sector: Financial Services
Services Provided:
- Cloud based document storage
- Data archival
Personal Data Processing: Yes
AI System: No
Dutch Government Client: No
Applicable Frameworks: ISO 27001, DORA
""".strip()

    mocker.patch("agents.orchestrator.invoke_chat_model", return_value=prose)

    profile = build_vendor_profile(SAMPLE_DOCS_NON_AI)

    assert profile.name == "CloudSafe Solutions B.V."
    assert profile.sector == "Financial Services"
    assert profile.services == ["Cloud based document storage", "Data archival"]
    assert profile.processes_personal_data is True
    assert profile.is_ai_system is False
    assert profile.is_dutch_government_vendor is False
    assert profile.applicable_frameworks == ["ISO 27001", "DORA"]


def test_determine_frameworks_non_ai_non_gov():
    profile = VendorProfile(
        name="X",
        sector="Finance",
        services=["Backup"],
        processes_personal_data=True,
        is_ai_system=False,
        is_dutch_government_vendor=False,
        applicable_frameworks=[],
    )
    frameworks = determine_frameworks(profile)
    assert "security" in frameworks
    assert "resilience" in frameworks
    assert "gov_baseline" not in frameworks
    assert "ai_trust" not in frameworks


def test_determine_frameworks_ai_gov():
    profile = VendorProfile(
        name="Y",
        sector="Technology",
        services=["AI tool"],
        processes_personal_data=True,
        is_ai_system=True,
        is_dutch_government_vendor=True,
        applicable_frameworks=[],
    )
    frameworks = determine_frameworks(profile)
    assert "security" in frameworks
    assert "gov_baseline" in frameworks
    assert "ai_trust" in frameworks
