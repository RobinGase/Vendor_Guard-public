import json
from pathlib import Path
from unittest.mock import MagicMock, patch


PROFILE_RESPONSE = {
    "name": "TestVendor B.V.",
    "sector": "Finance",
    "services": ["Cloud backup"],
    "processes_personal_data": True,
    "is_ai_system": False,
    "is_dutch_government_vendor": False,
    "applicable_frameworks": ["ISO 27001", "NIS2", "CBW", "DORA"],
}

SECURITY_FINDINGS = [
    {
        "framework": "ISO 27001",
        "control_id": "A.8.8",
        "control_name": "Patch management",
        "status": "Partial",
        "severity": "Medium",
        "evidence": "Monthly patching only.",
        "recommendation": "Add critical patch SLA.",
    }
]

RESILIENCE_FINDINGS = [
    {
        "framework": "DORA",
        "control_id": "Art.9",
        "control_name": "ICT risk management",
        "status": "Compliant",
        "severity": "Info",
        "evidence": "Framework documented.",
        "recommendation": "No action required.",
    }
]


def make_mock_response(data):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(data) if isinstance(data, (dict, list)) else data
    return mock_msg


def test_full_pipeline(tmp_path, mocker):
    """End-to-end: questionnaire file in, three output files out."""
    questionnaire = tmp_path / "vendor_q.txt"
    questionnaire.write_text("Vendor: TestVendor B.V.\nISO 27001: Certified\nMFA: Yes")

    def mock_create(**kwargs):
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        # Determine which call this is by inspecting the system prompt content
        if not system:
            # memo call — no system prompt
            return make_mock_response("Audit memo content.")
        if "orchestrator" in system.lower() or "vendor profile" in system.lower() or "applicable_frameworks" in system:
            return make_mock_response(PROFILE_RESPONSE)
        if "DORA" in system or "resilience" in system.lower() or "digital operational resilience" in system.lower():
            return make_mock_response(RESILIENCE_FINDINGS)
        # default: security agent
        return make_mock_response(SECURITY_FINDINGS)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = mock_create
    mocker.patch("agents.orchestrator.anthropic.Anthropic", return_value=mock_client)
    mocker.patch("agents.security_agent.anthropic.Anthropic", return_value=mock_client)
    mocker.patch("agents.resilience_agent.anthropic.Anthropic", return_value=mock_client)
    mocker.patch("synthesizer.memo.anthropic.Anthropic", return_value=mock_client)

    from main import run_pipeline
    outputs = run_pipeline(
        questionnaire_path=questionnaire,
        doc_paths=[],
        output_dir=tmp_path,
    )

    assert (tmp_path / "scorecard.xlsx").exists()
    assert (tmp_path / "gap_register.xlsx").exists()
    assert (tmp_path / "audit_memo.docx").exists()


def test_full_pipeline_continues_when_one_agent_fails(tmp_path, mocker):
    questionnaire = tmp_path / "vendor_q.txt"
    questionnaire.write_text("Vendor: TestVendor B.V.\nISO 27001: Certified\nMFA: Yes")

    def mock_create(**kwargs):
        system = kwargs.get("system", "")
        if not system:
            return make_mock_response("Audit memo content.")
        if "orchestrator" in system.lower() or "vendor profile" in system.lower() or "applicable_frameworks" in system:
            return make_mock_response(PROFILE_RESPONSE)
        if "DORA" in system or "resilience" in system.lower() or "digital operational resilience" in system.lower():
            raise RuntimeError("simulated agent failure")
        return make_mock_response(SECURITY_FINDINGS)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = mock_create
    mocker.patch("agents.orchestrator.anthropic.Anthropic", return_value=mock_client)
    mocker.patch("agents.security_agent.anthropic.Anthropic", return_value=mock_client)
    mocker.patch("agents.resilience_agent.anthropic.Anthropic", return_value=mock_client)
    mocker.patch("synthesizer.memo.anthropic.Anthropic", return_value=mock_client)

    from main import run_pipeline
    outputs = run_pipeline(
        questionnaire_path=questionnaire,
        doc_paths=[],
        output_dir=tmp_path,
    )

    assert outputs["scorecard_xlsx"].exists()
    assert outputs["gap_register_xlsx"].exists()
    assert outputs["memo_docx"].exists()
