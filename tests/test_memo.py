import json
from pathlib import Path
from unittest.mock import MagicMock
from models.finding import Finding, VendorProfile
from synthesizer.memo import write_audit_memo

PROFILE = VendorProfile(
    name="Acme B.V.",
    sector="Finance",
    services=["Cloud storage"],
    processes_personal_data=True,
    is_ai_system=False,
    is_dutch_government_vendor=False,
    applicable_frameworks=["ISO 27001", "DORA"],
)

FINDINGS = [
    Finding(framework="ISO 27001", control_id="A.8.8", control_name="Patch mgmt",
            status="Gap", severity="High", evidence="Monthly only.", recommendation="Add critical SLA."),
    Finding(framework="DORA", control_id="Art.9", control_name="ICT risk",
            status="Compliant", severity="Info", evidence="Framework in place.", recommendation="No action."),
]

SCORECARD = {
    "ISO 27001": {"rag": "Amber", "total": 1, "gaps": 1, "critical": 0, "high": 1, "partial": 0},
    "DORA": {"rag": "Green", "total": 1, "gaps": 0, "critical": 0, "high": 0, "partial": 0},
}


def make_mock_response(text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = text
    return mock_msg


def test_write_audit_memo_creates_file(tmp_path, mocker):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(
        "Executive Summary\n\nOverall risk: Amber.\n\nKey findings: Patch management gap in ISO 27001."
    )
    mocker.patch("synthesizer.memo.anthropic.Anthropic", return_value=mock_client)

    out = tmp_path / "memo.docx"
    write_audit_memo(PROFILE, FINDINGS, SCORECARD, out)
    assert out.exists()


def test_write_audit_memo_calls_claude(tmp_path, mocker):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response("Audit memo content here.")
    mocker.patch("synthesizer.memo.anthropic.Anthropic", return_value=mock_client)

    out = tmp_path / "memo.docx"
    write_audit_memo(PROFILE, FINDINGS, SCORECARD, out)
    assert mock_client.messages.create.called
