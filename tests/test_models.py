import pytest
from pydantic import ValidationError

from models.finding import Finding, VendorProfile


def test_finding_valid():
    f = Finding(
        framework="ISO 27001",
        control_id="A.9.1",
        control_name="Access control policy",
        status="Gap",
        severity="High",
        evidence="No access control policy found in provided documents.",
        recommendation="Provide a documented access control policy.",
    )
    assert f.framework == "ISO 27001"
    assert f.status == "Gap"
    assert f.severity == "High"


def test_finding_normalizes_unknown_status():
    """Unknown status values fall back to Partial instead of crashing."""
    f = Finding(
        framework="ISO 27001",
        control_id="A.9.1",
        control_name="Access control policy",
        status="Requires Monitoring",
        severity="High",
        evidence="x",
        recommendation="y",
    )
    assert f.status == "Partial"


def test_finding_normalizes_unknown_severity():
    """Unknown severity values fall back to Medium instead of crashing."""
    f = Finding(
        framework="ISO 27001",
        control_id="A.9.1",
        control_name="Access control policy",
        status="Gap",
        severity="Extreme",
        evidence="x",
        recommendation="y",
    )
    assert f.severity == "Medium"


def test_finding_normalizes_informational():
    """'Informational' maps to 'Info'."""
    f = Finding(
        framework="DORA",
        control_id="Art.9",
        control_name="ICT risk",
        status="Compliant",
        severity="Informational",
        evidence="x",
        recommendation="y",
    )
    assert f.severity == "Info"


def test_finding_normalizes_non_compliant():
    """'Non-Compliant' maps to 'Gap'."""
    f = Finding(
        framework="NIS2",
        control_id="Art.21",
        control_name="MFA",
        status="Non-Compliant",
        severity="High",
        evidence="x",
        recommendation="y",
    )
    assert f.status == "Gap"


def test_vendor_profile_defaults():
    p = VendorProfile(
        name="Acme B.V.",
        sector="Finance",
        services=["Cloud storage", "Data processing"],
        processes_personal_data=True,
        is_ai_system=False,
        is_dutch_government_vendor=False,
        applicable_frameworks=["ISO 27001", "NIS2", "DORA"],
    )
    assert p.is_ai_system is False
    assert "DORA" in p.applicable_frameworks


def test_vendor_profile_ai_vendor():
    p = VendorProfile(
        name="SmartAudit AI",
        sector="Technology",
        services=["AI-powered audit tool"],
        processes_personal_data=False,
        is_ai_system=True,
        is_dutch_government_vendor=False,
        applicable_frameworks=["EU AI Act", "ALTAI", "EC Ethics", "ISO 27001"],
    )
    assert p.is_ai_system is True


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_finding_rejects_formula_trigger_in_evidence(trigger):
    with pytest.raises(ValidationError, match="formula trigger"):
        Finding(
            framework="ISO 27001",
            control_id="A.9.1",
            control_name="Access control",
            status="Gap",
            severity="High",
            evidence=f"{trigger}HYPERLINK(\"http://evil/\",\"click\")",
            recommendation="Document policy.",
        )


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_finding_rejects_formula_trigger_in_recommendation(trigger):
    with pytest.raises(ValidationError, match="formula trigger"):
        Finding(
            framework="ISO 27001",
            control_id="A.9.1",
            control_name="Access control",
            status="Gap",
            severity="High",
            evidence="No policy found.",
            recommendation=f"{trigger}CMD|'/C calc'!A1",
        )


def test_finding_rejects_oversized_evidence():
    with pytest.raises(ValidationError):
        Finding(
            framework="ISO 27001",
            control_id="A.9.1",
            control_name="Access control",
            status="Gap",
            severity="High",
            evidence="x" * 10001,
            recommendation="y",
        )


def test_vendor_profile_rejects_oversized_name():
    with pytest.raises(ValidationError):
        VendorProfile(
            name="A" * 201,
            sector="Finance",
            services=["x"],
            processes_personal_data=False,
            is_ai_system=False,
            is_dutch_government_vendor=False,
            applicable_frameworks=["ISO 27001"],
        )


def test_vendor_profile_rejects_oversized_services_list():
    with pytest.raises(ValidationError):
        VendorProfile(
            name="Acme",
            sector="Finance",
            services=[f"service_{i}" for i in range(21)],
            processes_personal_data=False,
            is_ai_system=False,
            is_dutch_government_vendor=False,
            applicable_frameworks=["ISO 27001"],
        )
