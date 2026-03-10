import json
import pytest
from unittest.mock import MagicMock, patch
from agents.resilience_agent import run_resilience_agent
from models.finding import Finding

SAMPLE_DOCS = """
=== FILE: dora_questionnaire.txt ===
ICT risk framework: Documented and board-approved
ICT incident classification: 3-tier severity model in place
Penetration testing: Annual external pentest, last conducted 2025-11
Exit strategy: Documented for all critical ICT services
Audit rights: Granted per contract clause 12.3
"""


def make_mock_response(findings: list[dict]):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(findings)
    return mock_msg


def test_resilience_agent_returns_findings(mocker):
    mock_findings = [
        {
            "framework": "DORA",
            "control_id": "Art.24",
            "control_name": "Digital operational resilience testing",
            "status": "Compliant",
            "severity": "Info",
            "evidence": "Annual external pentest conducted November 2025.",
            "recommendation": "Continue annual testing; consider TLPT as entity grows.",
        }
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(mock_findings)
    mocker.patch("agents.resilience_agent.anthropic.Anthropic", return_value=mock_client)

    findings = run_resilience_agent(SAMPLE_DOCS)
    assert len(findings) == 1
    assert isinstance(findings[0], Finding)
    assert findings[0].framework == "DORA"


def test_resilience_agent_returns_list(mocker):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response([])
    mocker.patch("agents.resilience_agent.anthropic.Anthropic", return_value=mock_client)

    findings = run_resilience_agent(SAMPLE_DOCS)
    assert isinstance(findings, list)
