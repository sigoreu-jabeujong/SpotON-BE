"""Outbound allowlist. No query, location identifiers, URLs or raw provenance objects."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.geocode import Category
from app.schemas.risk import IndicatorId
from app.schemas.stores import SubCategory

IndicatorReason = Literal[
    "boundary_period_not_verified",
    "official_values_not_collected",
    "population_aggregation_and_grid_time_unverified",
    "zero_denominator",
    "insufficient_sample",
]
ComparisonReason = Literal["not_applicable", "zero_denominator", "insufficient_sample"]
Space = Literal["radius_300m", "radius_500m", "radius_1000m", "market", "grid"]
Source = Literal["R1", "R2", "R4", "R5", "R6"]
Limit = Literal[
    "license_records_not_business_outcomes",
    "ownership_transfer_not_separated",
    "historical_intervals_from_current_snapshot",
    "coordinate_selection_bias_possible",
    "franchise_name_match_not_contract_or_history",
    "restaurant_name_keywords_may_exclude_valid_stores",
]


class ContextModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class ContextFilters(ContextModel):
    area: Literal["all", "lt33", "33to66", "66to99", "gte99"]
    franchise: Literal["all", "franchise", "independent"]
    include_unknown_area: bool
    include_unknown_franchise: bool


class ContextIndicator(ContextModel):
    id: IndicatorId
    type: Literal["official", "reference"]
    value: int | float | None = Field(ge=0)
    unit: Literal["%", "개"] | None
    numerator: int | None = Field(ge=0)
    denominator: int | None = Field(ge=0)
    seoul_avg: float | None = Field(ge=0, le=100)
    seoul_avg_reason: ComparisonReason | None
    seoul_numerator: int | None = Field(ge=0)
    seoul_denominator: int | None = Field(ge=0)
    space: Space
    period: str | None = Field(
        pattern=r"^(?:\d{4}-\d{2}-\d{2}|\(\d{4}-\d{2}-\d{2}, \d{4}-\d{2}-\d{2}\])$"
    )
    source: tuple[Source, ...]
    status: Literal["fact", "pending", "link_only"]
    reason: IndicatorReason | None


class ContextFlags(ContextModel):
    insufficient_sample: bool
    missing: tuple[IndicatorId, ...]


class ContextMethodology(ContextModel):
    closure_sample_basis: Literal["period_denominator"] = "period_denominator"
    survival_basis: Literal["fixed_opening_anniversary"] = "fixed_opening_anniversary"
    survival_cohort: Literal["preceding_entry_year"] = "preceding_entry_year"
    survival_close_boundary: Literal["close_after_anniversary"] = "close_after_anniversary"
    rounding: Literal["decimal_half_up_1dp"] = "decimal_half_up_1dp"
    coordinate_basis: Literal["located_only"] = "located_only"
    seoul_comparison_basis: Literal["same_filters_located_license_records"] = (
        "same_filters_located_license_records"
    )
    minimum_closure_sample: Literal[10] = 10
    minimum_survival_sample: Literal[5] = 5
    limitations: tuple[Limit, ...] = (
        "license_records_not_business_outcomes",
        "ownership_transfer_not_separated",
        "historical_intervals_from_current_snapshot",
        "coordinate_selection_bias_possible",
        "restaurant_name_keywords_may_exclude_valid_stores",
    )


PERIOD_PATTERN = r"^\(\d{4}-\d{2}-\d{2}, \d{4}-\d{2}-\d{2}\]$"


class ContextActivityGroup(ContextModel):
    """T 시점 영업 기록 수와 개업 후 경과 완료 개월 평균(버림). 수명·생존 기간이 아니다."""

    sub_category: SubCategory
    open_count: int = Field(ge=0)
    avg_operating_months: int | None = Field(ge=0)

    @model_validator(mode="after")
    def consistent_average(self) -> Self:
        if (self.open_count == 0) != (self.avg_operating_months is None):
            raise ValueError("average requires a positive denominator")
        return self


class ContextActivityMethodology(ContextModel):
    event_basis: Literal["validated_license_dates"] = "validated_license_dates"
    operating_period_basis: Literal["elapsed_months_of_active_at_as_of"] = (
        "elapsed_months_of_active_at_as_of"
    )
    avg_operating_months_rounding: Literal["floor_mean_of_completed_months"] = (
        "floor_mean_of_completed_months"
    )
    yearly_trend_included: Literal[False] = False


class ContextActivity(ContextModel):
    """#60 활동 집계 중 최근 구간 개폐업 수와 T 시점 세부 업종 현황만 허용한다."""

    space: Literal["radius_300m", "radius_500m", "radius_1000m"]
    recent_period: str = Field(pattern=PERIOD_PATTERN)
    recent_opened: int = Field(ge=0)
    recent_closed: int = Field(ge=0)
    groups: tuple[ContextActivityGroup, ...] = Field(min_length=1)
    methodology: ContextActivityMethodology = Field(default_factory=ContextActivityMethodology)

    @model_validator(mode="after")
    def unique_groups(self) -> Self:
        names = [g.sub_category for g in self.groups]
        if names != sorted(set(names)):
            raise ValueError("duplicate or unordered activity groups")
        return self


class ContextHistoryMethodology(ContextModel):
    period_basis: Literal["completed_calendar_months"] = "completed_calendar_months"
    same_spot_rule: Literal["floor_and_unit_match_with_verified_location"] = (
        "floor_and_unit_match_with_verified_location"
    )
    filters_applied: Literal[False] = False


class ContextHistory(ContextModel):
    """#98 건물 이력 집계. 최신 자료 기준·지원 업종 전체이며 행 원문을 담지 않는다."""

    basis: Literal["latest_data_analysis_scope_supported_categories"] = (
        "latest_data_analysis_scope_supported_categories"
    )
    data_updated_at: date
    floor_unit_provided: bool
    same_spot_comparable: bool
    total: int = Field(ge=0)
    same_category: int = Field(ge=0)
    same_spot: int = Field(ge=0)
    same_building: int = Field(ge=0)
    unverified: int = Field(ge=0)
    same_spot_open: int = Field(ge=0)
    same_spot_closed: int = Field(ge=0)
    same_spot_other: int = Field(ge=0)
    same_spot_closed_period_count: int = Field(ge=0)
    same_spot_closed_months_min: int | None = Field(ge=0)
    same_spot_closed_months_max: int | None = Field(ge=0)
    methodology: ContextHistoryMethodology = Field(default_factory=ContextHistoryMethodology)

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        low, high = self.same_spot_closed_months_min, self.same_spot_closed_months_max
        period = self.same_spot_closed_period_count
        if (
            self.same_spot + self.same_building + self.unverified != self.total
            or self.same_category > self.total
            or self.same_spot_open + self.same_spot_closed + self.same_spot_other != self.same_spot
            or period > self.same_spot_closed
            or (period == 0) != (low is None)
            or (period == 0) != (high is None)
            or (low is not None and high is not None and low > high)
            or (self.same_spot_comparable and not self.floor_unit_provided)
            or (not self.floor_unit_provided and self.unverified != self.total)
            or (not self.same_spot_comparable and self.same_spot != 0)
        ):
            raise ValueError("inconsistent history aggregates")
        return self


class RiskInterpretContext(ContextModel):
    category: Category
    sub_category: tuple[SubCategory, ...]
    radius_m: Literal[300, 500, 1000]
    filters: ContextFilters
    as_of: date
    data_updated_at: date
    collected_at: None = None
    collection_reason: Literal["source_completion_time_not_recorded"] = (
        "source_completion_time_not_recorded"
    )
    market_status: Literal["unverified"] = "unverified"
    franchise_classification: Literal["pending", "estimate"] = "pending"
    franchise_reference_year: int | None = Field(default=None, ge=2000, le=9999)
    franchise_basis: Literal["reference_catalog_name_match"] | None = None
    indicators: tuple[ContextIndicator, ...] = Field(repr=False)
    flags: ContextFlags
    methodology: ContextMethodology = Field(default_factory=ContextMethodology)
    activity: ContextActivity = Field(repr=False)
    history: ContextHistory | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def activity_scope(self) -> Self:
        if (
            tuple(g.sub_category for g in self.activity.groups) != self.sub_category
            or self.activity.space != f"radius_{self.radius_m}m"
        ):
            raise ValueError("activity scope mismatch")
        if self.history is not None and self.history.data_updated_at != self.data_updated_at:
            raise ValueError("history reference mismatch")
        return self
