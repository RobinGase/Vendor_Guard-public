from models.finding import Finding
from synthesizer.synthesizer import aggregate_findings, compute_rag_scorecard


FINDINGS = [
    Finding(framework="ISO 27001", control_id="A.8.8", control_name="Patch mgmt",
            status="Partial", severity="Medium", evidence="Monthly cycle.", recommendation="Add critical SLA."),
    Finding(framework="ISO 27001", control_id="A.5.19", control_name="Supplier relationships",
            status="Compliant", severity="Info", evidence="Policy in place.", recommendation="No action."),
    Finding(framework="DORA", control_id="Art.9", control_name="ICT risk mgmt",
            status="Gap", severity="Critical", evidence="Not provided.", recommendation="Document framework."),
    Finding(framework="NIS2", control_id="Art.21.2", control_name="MFA",
            status="Compliant", severity="Info", evidence="MFA enabled.", recommendation="No action."),
]


def test_aggregate_findings_returns_all():
    result = aggregate_findings(FINDINGS)
    assert len(result) == 4


def test_compute_rag_scorecard_structure():
    scorecard = compute_rag_scorecard(FINDINGS)
    assert "ISO 27001" in scorecard
    assert "DORA" in scorecard
    assert scorecard["DORA"]["rag"] == "Red"
    assert scorecard["ISO 27001"]["rag"] in ("Green", "Amber", "Red")


def test_compute_rag_all_compliant():
    findings = [
        Finding(framework="NIS2", control_id="Art.21", control_name="MFA",
                status="Compliant", severity="Info", evidence="MFA on.", recommendation="None."),
    ]
    scorecard = compute_rag_scorecard(findings)
    assert scorecard["NIS2"]["rag"] == "Green"


def test_compute_rag_critical_gap_is_red():
    findings = [
        Finding(framework="DORA", control_id="Art.9", control_name="ICT risk",
                status="Gap", severity="Critical", evidence="Missing.", recommendation="Add it."),
    ]
    scorecard = compute_rag_scorecard(findings)
    assert scorecard["DORA"]["rag"] == "Red"


def test_aggregate_findings_deduplicates_and_sorts():
    findings = [
        Finding(framework="ISO 27001", control_id="A.8.8", control_name="Patch mgmt",
                status="Partial", severity="Medium", evidence="Monthly cycle.", recommendation="Add SLA."),
        Finding(framework="DORA", control_id="Art.9", control_name="ICT risk",
                status="Gap", severity="Critical", evidence="Missing framework.", recommendation="Document framework."),
        Finding(framework="ISO 27001", control_id="A.8.8", control_name="Patch mgmt",
                status="Gap", severity="High", evidence="No critical patch SLA.", recommendation="Define SLA."),
    ]

    result = aggregate_findings(findings)

    assert len(result) == 2
    assert result[0].framework == "DORA"
    assert result[0].severity == "Critical"
    assert result[1].framework == "ISO 27001"
    assert result[1].status == "Gap"
    assert result[1].severity == "High"
    assert result[1].evidence == "No critical patch SLA."
