from typing import Literal
from pydantic import BaseModel


class Finding(BaseModel):
    framework: str
    control_id: str
    control_name: str
    status: Literal["Compliant", "Gap", "Partial", "Not Applicable"]
    severity: Literal["Critical", "High", "Medium", "Low", "Info"]
    evidence: str
    recommendation: str


class VendorProfile(BaseModel):
    name: str
    sector: str
    services: list[str]
    processes_personal_data: bool
    is_ai_system: bool
    is_dutch_government_vendor: bool
    applicable_frameworks: list[str]
