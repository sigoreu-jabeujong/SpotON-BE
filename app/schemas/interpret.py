from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from app.schemas.risk import IndicatorId, RiskQuery
from app.schemas.stores import HistoryQuery


class InterpretModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class InterpretHistory(InterpretModel):
    """Optional building context (#98). Used only as a server-side lookup key."""

    building_key: str = Field(min_length=1, max_length=255, repr=False)
    floor_unit: str | None = Field(default=None, max_length=100, repr=False)


class InterpretRequest(InterpretModel):
    query: RiskQuery
    history: InterpretHistory | None = None
    _history_query: HistoryQuery | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def canonical_history(self) -> Self:
        # Build the canonical query during request validation so malformed keys are 422
        # before any database access (a later ValidationError would map to 500).
        if self.history is not None:
            self._history_query = HistoryQuery(
                building_key=self.history.building_key,
                floor_unit=self.history.floor_unit,
                category=self.query.category,
            )
        return self

    def history_query(self) -> HistoryQuery | None:
        return self._history_query


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


ActivityFactId = Literal["recent_open_close", "avg_operating_months"]


class InterpretItem(InterpretModel):
    """official_values 항목. 활동 ID는 여러 항목에 반복될 수 있다."""

    text: str
    indicator_ids: list[IndicatorId | ActivityFactId]


class InterpretSourcedItem(InterpretModel):
    """Risk 지표 비교 후보. 활동 ID는 허용하지 않는다."""

    text: str
    indicator_ids: list[IndicatorId]
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
