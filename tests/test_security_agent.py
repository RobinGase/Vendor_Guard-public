import json
import pytest
from unittest.mock import MagicMock, patch
from agents.security_agent import run_security_agent
from models.finding import Finding


SAMPLE_VENDOR_DOCS = """
=== FILE: vendor_questionnaire.txt ===
Vendor: Acme Cloud B.V.
ISO 27001: Certified, cert expires 2026-12-01
MFA: Enabled for all admin accounts
Patch management: Monthly cycle for all systems
Encryption: AES-256 at rest, TLS 1.3 in transit
Incident response: Documented, tested annually
Sub-processors: AWS (data processing agreement in place)
"""


def make_mock_response(findings: list[dict]):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(findings)
    return mock_msg


def test_security_agent_returns_findings(mocker):
    mock_findings = [
        {
            "framework": "ISO 27001",
            "control_id": "A.8.8",
            "control_name": "Management of technical vulnerabilities",
            "status": "Partial",
            "severity": "Medium",
            "evidence": "Monthly patch cycle documented but no critical patch SLA specified.",
            "recommendation": "Define a critical patch SLA of 72 hours.",
        }
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(mock_findings)
    mocker.patch("agents.security_agent.anthropic.Anthropic", return_value=mock_client)

    findings = run_security_agent(SAMPLE_VENDOR_DOCS)

    assert len(findings) == 1
    assert isinstance(findings[0], Finding)
    assert findings[0].framework == "ISO 27001"
    assert findings[0].status == "Partial"


def test_security_agent_returns_list(mocker):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response([])
    mocker.patch("agents.security_agent.anthropic.Anthropic", return_value=mock_client)

    findings = run_security_agent(SAMPLE_VENDOR_DOCS)
    assert isinstance(findings, list)
