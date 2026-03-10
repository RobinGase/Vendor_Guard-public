import json
from unittest.mock import MagicMock
from agents.ai_trust_agent import run_ai_trust_agent
from models.finding import Finding

SAMPLE_DOCS = """
=== FILE: ai_vendor_questionnaire.txt ===
System type: AI-powered contract review tool
Risk classification: High-risk AI (legal domain)
Conformity assessment: Self-assessment completed, CE marking applied
Logging: Automatic audit trail for all AI decisions
Human override: Reviewer can reject any AI recommendation
Explainability: Confidence scores provided per recommendation
Bias testing: Conducted on 10,000 contract dataset, no significant disparities found
Data governance: Training data documented, data minimization applied
"""


def make_mock_response(findings: list[dict]):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(findings)
    return mock_msg


def test_ai_trust_agent_returns_findings(mocker):
    mock_findings = [
        {
            "framework": "EU AI Act",
            "control_id": "Art.14",
            "control_name": "Human oversight",
            "status": "Compliant",
            "severity": "Info",
            "evidence": "Reviewer can reject any AI recommendation per questionnaire.",
            "recommendation": "Verify override mechanism is technically enforced, not just procedural.",
        }
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(mock_findings)
    mocker.patch("agents.ai_trust_agent.anthropic.Anthropic", return_value=mock_client)

    findings = run_ai_trust_agent(SAMPLE_DOCS)
    assert len(findings) == 1
    assert isinstance(findings[0], Finding)
    assert findings[0].framework == "EU AI Act"
