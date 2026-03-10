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


def test_finding_invalid_status():
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        Finding(
            framework="ISO 27001",
            control_id="A.9.1",
            control_name="Access control policy",
            status="Unknown",
            severity="High",
            evidence="x",
            recommendation="y",
        )


def test_finding_invalid_severity():
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        Finding(
            framework="ISO 27001",
            control_id="A.9.1",
            control_name="Access control policy",
            status="Gap",
            severity="Extreme",
            evidence="x",
            recommendation="y",
        )


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
