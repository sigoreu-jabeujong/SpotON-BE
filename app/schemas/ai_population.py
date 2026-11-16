"""Identifier-free population evidence for v2 AI; never whole-population totals."""

import re
from datetime import date
from typing import Literal, Self

from pydantic import model_validator

from app.schemas.population_reference import (
    SOURCES,
    Count,
    ExcludedHours,
    Limitation,
    PopulationModel,
    PublicSourceReason,
    ReferenceReason,
    ReferenceStatus,
    Source,
)


class ContextPopulationMetric(PopulationModel):
    display: str | None
    exact_zero: bool | None
    rounded: bool | None
    unit: Literal["pct_of_public_subset", "ratio"]
    reason: Literal["zero_total", "zero_night_denominator"] | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.display is None:
            expected = (
                "zero_total" if self.unit == "pct_of_public_subset" else "zero_night_denominator"
            )
            if self.reason != expected or self.exact_zero is not None or self.rounded is not None:
                raise ValueError("invalid missing population metric")
        else:
            pattern = (
                r"(?:0|[1-9][0-9]?|100)\.[0-9]%"
                if self.unit == "pct_of_public_subset"
                else r"(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*)\.[0-9]{5}배"
            )
            if (
                len(self.display) > 64
                or not re.fullmatch(pattern, self.display)
                or self.reason is not None
                or self.exact_zero is None
                or self.rounded is None
                or (self.unit == "pct_of_public_subset" and float(self.display[:-1]) > 100)
            ):
                raise ValueError("invalid population metric")
            zero = self.display in ("0.0%", "0.00000배")
            if self.exact_zero and (not zero or self.rounded):
                raise ValueError("invalid exact zero population metric")
            if zero and not self.exact_zero and not self.rounded:
                raise ValueError("invalid rounded zero population metric")
        return self


class ContextPopulationMetrics(PopulationModel):
    day_share_pct: ContextPopulationMetric
    night_share_pct: ContextPopulationMetric
    day_night_ratio: ContextPopulationMetric

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            self.day_share_pct.unit != "pct_of_public_subset"
            or self.night_share_pct.unit != "pct_of_public_subset"
            or self.day_night_ratio.unit != "ratio"
            or (self.day_share_pct.display is None) != (self.night_share_pct.display is None)
        ):
            raise ValueError("invalid population metric units")
        return self


class ContextPopulationQuality(PopulationModel):
    selected_grid_count: Count
    used_grid_count: Count
    grids_without_rows: Count
    candidate_component_count: Count
    used_component_count: Count
    excluded_component_count: Count
    excluded_by_hour_class: ExcludedHours

    @model_validator(mode="after")
    def coherent(self) -> Self:
        excluded = self.excluded_by_hour_class
        if (
            self.used_component_count + self.excluded_component_count
            != self.candidate_component_count
            or self.used_grid_count > min(self.selected_grid_count, self.used_component_count)
            or self.grids_without_rows > self.selected_grid_count
            or excluded.day_only + excluded.night_only + excluded.both
            != self.excluded_component_count
        ):
            raise ValueError("invalid population quality")
        return self


class ContextPopulationSource(PopulationModel):
    source: Source
    status: Literal["partial", "no_data", "not_supported"]
    reason: PublicSourceReason
    metrics: ContextPopulationMetrics | None
    quality: ContextPopulationQuality
    limitations: tuple[Limitation, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            (self.status == "partial") != (self.metrics is not None)
            or (self.status == "partial") != (self.reason == "public_subset_only")
            or (self.status == "not_supported") != (self.reason == "numeric_scope_too_large")
        ):
            raise ValueError("invalid population source outcome")
        return self


class ContextPopulationReference(PopulationModel):
    status: ReferenceStatus
    reason: ReferenceReason | None
    analysis_date: date
    observation_date: date | None
    calculation_method: Literal["fixed_public_component_24h"] = "fixed_public_component_24h"
    day_hours: Literal["06-17"] = "06-17"
    night_hours: Literal["00-05,18-23"] = "00-05,18-23"
    ratio_definition: Literal["pooled_day_sum_over_pooled_night_sum"] = (
        "pooled_day_sum_over_pooled_night_sum"
    )
    population_filter_applied: Literal[False] = False
    source_validation_performed: Literal[False] = False
    population_total_validated: Literal[False] = False
    sources: tuple[ContextPopulationSource, ...]

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
            raise ValueError("invalid population observation date")
        if self.observation_date is not None and not (
            self.analysis_date.replace(day=1) <= self.observation_date <= self.analysis_date
        ):
            raise ValueError("invalid population observation period")
        return self
