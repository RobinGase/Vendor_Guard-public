import json
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
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(profile_data)
    mocker.patch("agents.orchestrator.anthropic.Anthropic", return_value=mock_client)

    profile = build_vendor_profile(SAMPLE_DOCS_NON_AI)
    assert isinstance(profile, VendorProfile)
    assert profile.is_ai_system is False
    assert "DORA" in profile.applicable_frameworks


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
