from typing import Literal
from pydantic import BaseModel, field_validator


VALID_SEVERITIES = ["Critical", "High", "Medium", "Low", "Info"]
VALID_STATUSES = ["Compliant", "Gap", "Partial", "Not Applicable"]

SEVERITY_ALIASES = {
    "informational": "Info",
    "information": "Info",
    "none": "Info",
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "moderate": "Medium",
    "low": "Low",
    "info": "Info",
    "minor": "Low",
    "major": "High",
    "severe": "Critical",
}

STATUS_ALIASES = {
    "compliant": "Compliant",
    "gap": "Gap",
    "partial": "Partial",
    "partially compliant": "Partial",
    "partially met": "Partial",
    "not applicable": "Not Applicable",
    "not assessed": "Not Applicable",
    "n/a": "Not Applicable",
    "na": "Not Applicable",
    "met": "Compliant",
    "fully compliant": "Compliant",
    "non-compliant": "Gap",
    "noncompliant": "Gap",
    "not compliant": "Gap",
    "missing": "Gap",
    "absent": "Gap",
    "not met": "Gap",
    "not provided": "Gap",
    "in progress": "Partial",
    "requires monitoring": "Partial",
    "requires improvement": "Partial",
    "needs improvement": "Partial",
    "observation": "Partial",
    "planned": "Partial",
    "under review": "Partial",
}


def _normalize_severity(v: str) -> str:
    key = v.lower().strip()
    if key in SEVERITY_ALIASES:
        return SEVERITY_ALIASES[key]
    # If it's already a valid value, return it
    if v in VALID_SEVERITIES:
        return v
    # Fallback: default to Medium for anything unknown
    return "Medium"


def _normalize_status(v: str) -> str:
    key = v.lower().strip()
    if key in STATUS_ALIASES:
        return STATUS_ALIASES[key]
    # If it's already a valid value, return it
    if v in VALID_STATUSES:
        return v
    # Fallback: default to Partial for anything unknown
    return "Partial"


class Finding(BaseModel):
    framework: str
    control_id: str
    control_name: str
    status: Literal["Compliant", "Gap", "Partial", "Not Applicable"]
    severity: Literal["Critical", "High", "Medium", "Low", "Info"]
    evidence: str
    recommendation: str

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: str) -> str:
        return _normalize_severity(v)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        return _normalize_status(v)


class VendorProfile(BaseModel):
    name: str
    sector: str
    services: list[str]
    processes_personal_data: bool
    is_ai_system: bool
    is_dutch_government_vendor: bool
    applicable_frameworks: list[str]
