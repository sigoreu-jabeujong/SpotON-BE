"""Location-linked source values; independent from historical Risk and whole population."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.population_reference import PopulationReferenceQuery

Status = Literal["ready", "partial", "no_data", "pending", "not_supported"]
Reason = Literal[
    "partial_source_rows",
    "population_source_not_released",
    "admin_boundary_unmatched",
    "source_not_loaded",
    "ambiguous_source_version",
    "outside_coverage",
    "no_spatial_overlap",
    "no_source_rows",
    "source_value_null",
    "mixed_unavailable_reasons",
    "no_data_in_analysis_period",
    "no_complete_day",
    "zero_night_population",
    "mapping_conflict",
    "scope_too_large",
]
Relation = Literal["contains_point", "intersects_radius"]
TimeRelation = Literal["same_period", "earlier_reference", "later_reference"]
TimeMode = Literal["latest_reference", "analysis_period"]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LocationReferenceQuery(PopulationReferenceQuery):
    time_mode: TimeMode = "latest_reference"


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Fingerprint(ReferenceModel):
    source_dataset: str = Field(min_length=1, max_length=32)
    rule_version: str = Field(min_length=1, max_length=128)
    input_sha256: Sha
    content_sha256: Sha
    row_count: int = Field(gt=0)


class SalesCatalog(ReferenceModel):
    source_year: int = Field(ge=2000, le=2099)
    sales: Fingerprint
    boundary: Fingerprint
    stores: Fingerprint

    @model_validator(mode="after")
    def datasets_match(self) -> Self:
        if (
            self.sales.source_dataset,
            self.boundary.source_dataset,
            self.stores.source_dataset,
        ) != (
            "OA-15572",
            "OA-15560",
            "OA-15577",
        ):
            raise ValueError("invalid location catalog")
        return self


class LocationCatalog(ReferenceModel):
    format_version: Literal["location-reference-catalog-v1"] = "location-reference-catalog-v1"
    sales: SalesCatalog | None = None


class SourceNumber(ReferenceModel):
    value: str = Field(pattern=r"^(0|[1-9][0-9]*)$")
    display: str = Field(min_length=1)
    unit: Literal["KRW_source_reported"] = "KRW_source_reported"
    rounded: Literal[False] = False
    exact_zero: bool

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.display != f"{int(self.value):,}원" or self.exact_zero != (self.value == "0"):
            raise ValueError("invalid source number")
        if int(self.value) > 2**63 - 1:
            raise ValueError("invalid source number")
        return self


class SalesItem(ReferenceModel):
    market_code: str = Field(pattern=r"^[0-9]{7}$")
    market_name: str
    market_type: Literal["alley", "developed", "traditional_market", "tourism_zone"]
    spatial_relation: Relation
    industry_code: str = Field(pattern=r"^CS10000[1-4]$|^CS100010$")
    industry_name: str
    source_quarter: str | None = Field(default=None, pattern=r"^20[0-9]{2}[1-4]$")
    period_end_after_analysis: bool = False
    temporal_relation: TimeRelation | None = None
    metric: SourceNumber | None = None
    status: Literal["ready", "no_data"]
    reason: Reason | None = None
    amount_basis: Literal["source_reported"] = "source_reported"
    amount_period_status: Literal["unverified"] = "unverified"
    selection_reason: Literal["latest_numeric_row", "analysis_period"]
    provenance_ref: Literal["sales"] = "sales"
    excluded_source_rows: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.status == "ready":
            if self.metric is None or self.source_quarter is None or self.reason is not None:
                raise ValueError("invalid sales item")
        elif self.metric is not None or self.reason is None:
            raise ValueError("invalid sales item")
        return self


class SalesBlock(ReferenceModel):
    status: Status
    reason: Reason | None = None
    items: tuple[SalesItem, ...] = ()
    excluded_count: int = Field(default=0, ge=0)
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    reason_counts: dict[Reason, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.status == "ready") != (self.reason is None):
            raise ValueError("invalid sales block")
        if self.excluded_count != sum(self.excluded_counts.values()) or any(
            v < 0 for v in self.excluded_counts.values()
        ):
            raise ValueError("invalid excluded counts")
        if any(v <= 0 for v in self.reason_counts.values()) or sum(
            self.reason_counts.values()
        ) != sum(row.reason is not None for row in self.items):
            raise ValueError("invalid reason counts")
        return self


class UnreleasedPopulation(ReferenceModel):
    status: Literal["pending"] = "pending"
    reason: Literal["population_source_not_released"] = "population_source_not_released"
    items: tuple[()] = ()


class LocationReference(ReferenceModel):
    requested_as_of: str | None
    analysis_as_of: date
    time_mode: TimeMode
    sales: SalesBlock
    living_population: UnreleasedPopulation = Field(default_factory=UnreleasedPopulation)
    day_night: UnreleasedPopulation = Field(default_factory=UnreleasedPopulation)
