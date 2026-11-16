"""Descriptive public-row comparisons, never a population total contract."""

from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.nearby import NearbyQuery
from app.schemas.store_filters import CategoryFilters

Source = Literal["local", "long", "short"]
SOURCES: tuple[Source, ...] = ("local", "long", "short")
Count = Annotated[int, Field(strict=True, ge=0)]
ReferenceStatus = Literal["ready", "pending", "no_data", "not_supported"]
ReferenceReason = Literal["ambiguous_source_version", "no_observation_in_period", "scope_too_large"]
PublicSourceReason = Literal[
    "public_subset_only",
    "no_selected_grids",
    "no_source_rows",
    "no_common_public_components",
    "numeric_scope_too_large",
]
Unit = Literal[
    "public_source_value_sum", "public_source_value_hourly_mean", "pct_of_public_subset", "ratio"
]
Limitation = Literal[
    "not_population_total",
    "admin_additivity_unverified",
    "grid_period_unverified",
    "hour_sums_not_unique_people",
    "exclusion_pattern_may_bias_ratio",
    "grid_as_of_unknown",
]


class PopulationReferenceQuery(CategoryFilters):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    radius: Literal[300, 500, 1000] = 500
    as_of: str | None = None

    @field_validator("lat", "lng", mode="before")
    @classmethod
    def numeric_coordinate(cls, value: Any) -> Any:
        if type(value) is bool:
            raise ValueError("invalid coordinate")
        return value

    @field_validator("radius", mode="before")
    @classmethod
    def integer_radius(cls, value: Any) -> Any:
        return NearbyQuery.integer_radius(value)

    @field_validator("as_of")
    @classmethod
    def valid_month(cls, value: str | None) -> str | None:
        return NearbyQuery.valid_month(value)


class PopulationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class PublicNumber(PopulationModel):
    value: str | None = Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{1,5}$")
    display: str | None
    exact_zero: bool | None
    rounded: bool | None
    unit: Unit
    reason: Literal["zero_total", "zero_night_denominator"] | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.value is None:
            if self.reason is None or any(
                v is not None for v in (self.display, self.exact_zero, self.rounded)
            ):
                raise ValueError("invalid missing public number")
        elif (
            self.reason is not None
            or self.display is None
            or self.exact_zero is None
            or self.rounded is None
        ):
            raise ValueError("invalid public number")
        return self


class PublicValues(PopulationModel):
    hourly_source_sums: tuple[PublicNumber, ...] = Field(min_length=24, max_length=24)
    day_source_sum: PublicNumber
    night_source_sum: PublicNumber
    day_source_mean: PublicNumber
    night_source_mean: PublicNumber
    day_share_pct: PublicNumber
    night_share_pct: PublicNumber
    day_night_ratio: PublicNumber


class ExcludedHours(PopulationModel):
    day_only: Count
    night_only: Count
    both: Count


class PublicQuality(PopulationModel):
    selected_grid_count: Count
    grids_with_rows: Count
    grids_without_rows: Count
    candidate_component_count: Count
    used_component_count: Count
    excluded_component_count: Count
    used_grid_count: Count
    observed_rows: Count
    suppressed_rows: Count
    missing_rows: Count
    absent_hours_within_candidates: Count
    excluded_by_hour_class: ExcludedHours
    version_unlocated_rows: Count
    version_unlocated_grids: Count

    @model_validator(mode="after")
    def coherent(self) -> Self:
        excluded = self.excluded_by_hour_class
        if (
            self.grids_with_rows + self.grids_without_rows != self.selected_grid_count
            or self.used_component_count + self.excluded_component_count
            != self.candidate_component_count
            or self.used_grid_count > min(self.grids_with_rows, self.used_component_count)
            or self.observed_rows
            + self.suppressed_rows
            + self.missing_rows
            + self.absent_hours_within_candidates
            != 24 * self.candidate_component_count
            or excluded.day_only + excluded.night_only + excluded.both
            != self.excluded_component_count
            or self.version_unlocated_grids > self.version_unlocated_rows
        ):
            raise ValueError("invalid public subset quality")
        return self


class PublicSource(PopulationModel):
    source: Source
    status: Literal["partial", "no_data", "not_supported"]
    reason: PublicSourceReason
    values: PublicValues | None
    quality: PublicQuality
    limitations: tuple[Limitation, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.status == "partial") != (self.values is not None):
            raise ValueError("invalid public subset outcome")
        if (self.status == "partial") != (self.reason == "public_subset_only"):
            raise ValueError("invalid public subset reason")
        if (self.status == "not_supported") != (self.reason == "numeric_scope_too_large"):
            raise ValueError("invalid unsupported subset reason")
        return self


class PublicMethod(PopulationModel):
    name: Literal["fixed_public_component_24h"] = "fixed_public_component_24h"
    day_hours: Literal["06-17"] = "06-17"
    night_hours: Literal["00-05,18-23"] = "00-05,18-23"
    ratio_definition: Literal["pooled_day_sum_over_pooled_night_sum"] = (
        "pooled_day_sum_over_pooled_night_sum"
    )


class PublicScope(PopulationModel):
    radius_m: Literal[300, 500, 1000]
    category: Literal["cafe", "restaurant"]
    sub_category: tuple[str, ...]
    as_of: str | None
    population_filter_applied: Literal[False] = False
    timeline_basis: Literal["license_global_source_date_category_month_range"] = (
        "license_global_source_date_category_month_range"
    )
    spatial_compatibility: Literal["unverified"] = "unverified"
    grid_as_of: date | None


class PopulationReference(PopulationModel):
    status: ReferenceStatus
    reason: ReferenceReason | None
    analysis_date: date
    observation_date: date | None
    method: PublicMethod = Field(default_factory=PublicMethod)
    scope: PublicScope
    sources: tuple[PublicSource, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.status == "ready":
            if self.reason is not None or tuple(s.source for s in self.sources) != SOURCES:
                raise ValueError("invalid population sources")
        elif (
            self.sources
            or self.reason
            != {
                "pending": "ambiguous_source_version",
                "no_data": "no_observation_in_period",
                "not_supported": "scope_too_large",
            }[self.status]
        ):
            raise ValueError("invalid population status")
        if (self.reason == "no_observation_in_period") != (self.observation_date is None):
            raise ValueError("invalid population date")
        return self
