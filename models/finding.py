from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator


# Leading characters that turn a cell value into a live formula in Excel /
# Google Sheets / LibreOffice Calc. Evidence and recommendation flow into
# spreadsheet cells, so reject these at model construction time — the
# synthesizer sanitizer is the primary defense, this is defense-in-depth
# for any future writer that forgets to call it.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _reject_formula_triggers(v: str, field_name: str) -> str:
    if v and v[0] in _FORMULA_TRIGGERS:
        raise ValueError(
            f"{field_name} must not start with a spreadsheet formula "
            f"trigger {_FORMULA_TRIGGERS!r}; got {v[:40]!r}"
        )
    return v


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
    # Length caps are generous (realistic values are far shorter) but bound
    # what a prompt-injected vendor doc can push downstream into the memo,
    # gap register, and HTML layout. A 50 KB "evidence" string won't blow
    # up the DOCX/XLSX writer or mis-render the HTML grid.
    framework: Annotated[str, Field(max_length=200)]
    control_id: Annotated[str, Field(max_length=100)]
    control_name: Annotated[str, Field(max_length=500)]
    status: Literal["Compliant", "Gap", "Partial", "Not Applicable"]
    severity: Literal["Critical", "High", "Medium", "Low", "Info"]
    evidence: Annotated[str, Field(max_length=10000)]
    recommendation: Annotated[str, Field(max_length=10000)]

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: str) -> str:
        return _normalize_severity(v)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        return _normalize_status(v)

    @field_validator("evidence")
    @classmethod
    def reject_evidence_formula(cls, v: str) -> str:
        return _reject_formula_triggers(v, "evidence")

    @field_validator("recommendation")
    @classmethod
    def reject_recommendation_formula(cls, v: str) -> str:
        return _reject_formula_triggers(v, "recommendation")


class VendorProfile(BaseModel):
    # Name / sector land in the HTML memo title and DOCX headings. Without
    # a cap a 50 KB vendor name pulled from a crafted questionnaire would
    # still render through `html.escape` without raising — but it'd blow
    # out the page layout and inflate the generated artefacts.
    name: Annotated[str, Field(max_length=200)]
    sector: Annotated[str, Field(max_length=200)]
    services: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=20)]
    processes_personal_data: bool
    is_ai_system: bool
    is_dutch_government_vendor: bool
    applicable_frameworks: Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=20)]
