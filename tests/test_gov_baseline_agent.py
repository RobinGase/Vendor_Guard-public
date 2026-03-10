import json
from unittest.mock import MagicMock
from agents.gov_baseline_agent import run_gov_baseline_agent
from models.finding import Finding

SAMPLE_DOCS = """
=== FILE: bio2_questionnaire.txt ===
Cryptography: AES-256, TLS 1.3 (NCSC-approved algorithms)
Patch management: Critical patches within 48 hours
Logging retention: 13 months
RTO: 4 hours, RPO: 1 hour, tested Q3 2025
BIO2 processing agreement: Signed
"""


def make_mock_response(findings: list[dict]):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(findings)
    return mock_msg


def test_gov_baseline_agent_returns_findings(mocker):
    mock_findings = [
        {
            "framework": "BIO2",
            "control_id": "BIO2-LOG-01",
            "control_name": "Logging retention",
            "status": "Compliant",
            "severity": "Info",
            "evidence": "Logging retention documented as 13 months, exceeding 12-month minimum.",
            "recommendation": "No action required.",
        }
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(mock_findings)
    mocker.patch("agents.gov_baseline_agent.anthropic.Anthropic", return_value=mock_client)

    findings = run_gov_baseline_agent(SAMPLE_DOCS)
    assert len(findings) == 1
    assert isinstance(findings[0], Finding)
    assert findings[0].framework == "BIO2"
