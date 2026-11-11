from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.risk import IndicatorId, RiskQuery


class InterpretModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class InterpretRequest(InterpretModel):
    query: RiskQuery


class CandidateSelection(InterpretModel):
    favorable: list[str] = Field(max_length=3)
    unfavorable: list[str] = Field(max_length=3)
    checklist: list[str] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        for group in (self.favorable, self.unfavorable, self.checklist):
            if len(group) != len(set(group)):
                raise ValueError("duplicate candidate")
        return self


class InterpretItem(InterpretModel):
    text: str
    indicator_ids: list[IndicatorId]


class InterpretSourcedItem(InterpretItem):
    sources: list[str]


class MissingItem(InterpretModel):
    text: str
    reason: str


class ChecklistItem(InterpretModel):
    item: str
    why: str


class InterpretationVerification(InterpretModel):
    passed: Literal[True] = True
    checked_numbers: int = Field(ge=0)
    mismatches: list[None] = Field(default_factory=list, max_length=0)
    regenerated: bool


class RiskInterpretation(InterpretModel):
    label: Literal["AI 해석"] = "AI 해석"
    method: Literal["server_sentences_model_ordering"] = "server_sentences_model_ordering"
    official_values: list[InterpretItem]
    favorable: list[InterpretSourcedItem]
    unfavorable: list[InterpretSourcedItem]
    missing_data: list[MissingItem]
    checklist: list[ChecklistItem]
    verification: InterpretationVerification
    model: str
    generated_at: datetime
