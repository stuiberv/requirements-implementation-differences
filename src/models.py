from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    confidence: float = Field(ge=0, le=1)
    clarification_question: str | None

    @model_validator(mode="after")
    def check_verdict(self):
        if self.status == "AMBIGUOUS" and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError("AMBIGUOUS requires a clarification question")
        if self.status == "SATISFIED" and self.severity != "none":
            raise ValueError("SATISFIED must have severity none")
        return self


class EngineeringRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk: str
    evidence: str
    explanation: str
    confidence: float = Field(ge=0, le=1)


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]
    engineering_risks: list[EngineeringRisk]
