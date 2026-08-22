from typing import Literal
from pydantic import BaseModel, ConfigDict


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    status: Literal[
        "SATISFIED",
        "PARTIALLY_SATISFIED",
        "NOT_SATISFIED",
        "AMBIGUOUS",
        "UNABLE_TO_VERIFY",
    ]
    requirement: str
    evidence: str
    explanation: str
    severity: Literal["none", "low", "medium", "high"]
    confidence: float
    clarification_question: str | None


class EngineeringRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk: str
    evidence: str
    explanation: str
    confidence: float


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]
    engineering_risks: list[EngineeringRisk]