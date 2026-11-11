"""Outbound allowlist. No query, location identifiers, URLs or raw provenance objects."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    )


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
    franchise_classification: Literal["pending"] = "pending"
    indicators: tuple[ContextIndicator, ...] = Field(repr=False)
    flags: ContextFlags
    methodology: ContextMethodology = Field(default_factory=ContextMethodology)
