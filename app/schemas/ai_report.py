"""Versioned three-role report. No model-authored numbers or arbitrary prose."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.address_history import AddressHistoryQuery
from app.schemas.analysis_v2 import AnalysisRiskQuery
from app.schemas.interpret import ChecklistItem

Role = Literal["advantages", "cautions", "summary"]
Token = str


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ReportBaseline(ReportModel):
    risk: Token = Field(pattern=r"^[0-9a-f]{64}$")
    activity: Token = Field(pattern=r"^[0-9a-f]{64}$")
    location: Token = Field(pattern=r"^[0-9a-f]{64}$")
    grid: Token = Field(pattern=r"^[0-9a-f]{64}$")
    address_history: Token | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ReportRequest(ReportModel):
    query: AnalysisRiskQuery
    baseline: ReportBaseline
    time_mode: Literal["latest_reference", "analysis_period"] = "latest_reference"
    address_history: AddressHistoryQuery | None = None

    @model_validator(mode="after")
    def history_baseline(self) -> Self:
        if (self.address_history is None) != (self.baseline.address_history is None):
            raise ValueError("history baseline mismatch")
        if self.query.include:
            raise ValueError("report uses the core risk contract")
        if (
            self.address_history is not None
            and self.address_history.category != self.query.category
        ):
            raise ValueError("history category mismatch")
        return self


class ReportMetric(ReportModel):
    id: str
    group: str
    label: str
    area_label: str | None = None
    value: str | None
    display: str
    unit: str
    status: str
    reason: str | None = None
    source_ids: list[str]
    period: str
    spatial_scope: str
    population_scope: str
    filter_scope: str
    denominator: str | None = None
    exact_zero: bool | None = None
    rounded: bool | None = None


class ReportText(ReportModel):
    text: str
    evidence_ids: list[str]
    group_id: str | None = None


class ReportVerification(ReportModel):
    """Numeric/unit/evidence structure checks; not a proof of causal interpretation."""

    passed: Literal[True] = True


class ReportSection(ReportModel):
    status: Literal["ready", "unavailable"]
    items: list[ReportText] = Field(default_factory=list)
    reason: Literal["provider_error", "verification_failed", "timeout", "rate_limited"] | None = (
        None
    )
    verification: ReportVerification | None = None
    group_count: int = Field(default=0, ge=0, le=6)
    group_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_state(self) -> Self:
        if self.status == "unavailable":
            if self.items or self.verification is not None or self.reason is None:
                raise ValueError("unverified report text")
        elif self.verification is None or self.reason is not None:
            raise ValueError("missing report verification")
        if self.group_count and (
            len(self.items) != self.group_count
            or [item.group_id for item in self.items] != self.group_ids
            or len(set(self.group_ids)) != self.group_count
        ):
            raise ValueError("incomplete summary")
        return self


class AiSectionsReport(ReportModel):
    schema_version: Literal["ai-sections-v1"] = "ai-sections-v1"
    label: Literal["AI 해석"] = "AI 해석"
    status: Literal["complete", "partial"]
    advantages: ReportSection
    cautions: ReportSection
    summary: ReportSection
    limitations: list[ReportText] = Field(min_length=1, max_length=32)
    metrics: list[ReportMetric]
    checklist: list[ChecklistItem] = Field(min_length=3, max_length=3)
    generated_at: datetime
    report_context_hash: str
    baseline: ReportBaseline

    @model_validator(mode="after")
    def complete_status(self) -> Self:
        ready = [s.status == "ready" for s in (self.advantages, self.cautions, self.summary)]
        if not any(ready) or (self.status == "complete") != all(ready):
            raise ValueError("invalid report outcome")
        return self
