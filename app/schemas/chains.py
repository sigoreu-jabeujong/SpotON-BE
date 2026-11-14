"""Independent v2 input: chain affiliation is never the legacy franchise flag."""

from datetime import date
from typing import Any, Literal, Self, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ApiMeta
from app.schemas.market_activity import ActivityInclude, ActivityQuery
from app.schemas.nearby import Center, NearbyQuery
from app.schemas.risk import RiskInclude, RiskQuery
from app.schemas.store_filters import CategoryFilters
from app.schemas.stores import PeriodReason, StoreSource, StoreStatus, SubCategory

T = TypeVar("T", bound=NearbyQuery)
BRAND_FIELDS = {
    "brand_scope",
    "brand_unknown",
    "brand_evidence",
    "brand_time_basis",
    "operation_type",
}
COMMON_FIELDS = {
    "lat",
    "lng",
    "radius",
    "category",
    "sub_category",
    "as_of",
    "area",
    "include_unknown_area",
}


class ChainQuery(CategoryFilters):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    radius: Literal[300, 500, 1000] = 500
    as_of: str | None = None
    area: Literal["all", "lt33", "33to66", "66to99", "gte99"] = "all"
    include_unknown_area: bool = True
    brand_scope: Literal["all", "chain", "non_chain"] = "all"
    brand_unknown: Literal["include", "exclude"] = "include"
    brand_evidence: Literal["include_estimates", "confirmed_only"] = "include_estimates"
    brand_time_basis: Literal["observed_record"] = "observed_record"
    operation_type: Literal["any"] = "any"

    @model_validator(mode="before")
    @classmethod
    def explicit_unknown(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("brand_scope", "all") != "all":
            if "brand_unknown" not in value:
                raise ValueError("brand_unknown must be explicit for selected scope")
        return value

    @field_validator("radius", mode="before")
    @classmethod
    def integer_radius(cls, value: Any) -> Any:
        return NearbyQuery.integer_radius(value)

    @field_validator("as_of")
    @classmethod
    def valid_month(cls, value: str | None) -> str | None:
        return NearbyQuery.valid_month(value)

    @field_validator("include_unknown_area", mode="before")
    @classmethod
    def strict_boolean(cls, value: Any) -> bool:
        return NearbyQuery.strict_boolean(value)

    def legacy(self, model: type[T]) -> T:
        fields = COMMON_FIELDS | ({"include"} if "include" in model.model_fields else set())
        return model.model_validate(
            {
                **self.model_dump(include=fields),
                "franchise": "all",
                "include_unknown_franchise": True,
            }
        )

    def echo_filters(self) -> ApiMeta:
        return self.model_dump(
            include=BRAND_FIELDS | {"sub_category", "area", "include_unknown_area"}, mode="json"
        )


class ChainSnapshotQuery(ChainQuery):
    as_of: str = Field(...)


class ChainActivityQuery(ChainQuery):
    include: tuple[ActivityInclude, ...] = ()

    @field_validator("include", mode="before")
    @classmethod
    def includes(cls, value: Any) -> Any:
        return ActivityQuery.comma_include(value)

    @field_validator("include")
    @classmethod
    def unique_includes(cls, value: tuple[ActivityInclude, ...]) -> tuple[ActivityInclude, ...]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate include")
        return value


class ChainRiskQuery(ChainQuery):
    include: tuple[RiskInclude, ...] = ()

    @field_validator("include", mode="before")
    @classmethod
    def includes(cls, value: Any) -> Any:
        return RiskQuery.comma_include(value)

    @field_validator("include")
    @classmethod
    def unique_includes(cls, value: tuple[RiskInclude, ...]) -> tuple[RiskInclude, ...]:
        return RiskQuery.unique_include(value)


class ChainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class ChainBrand(ChainModel):
    status: Literal["estimated", "unknown", "conflict"]
    brand_key: UUID | None = None
    name: str | None = None
    basis: str | None = None
    reason: str | None = None
    reference_year: int | None = None
    reference_month: str | None = None
    time_basis: Literal["observed_record"] = "observed_record"
    historical_membership: Literal["not_verified"] = "not_verified"


class ChainOperation(ChainModel):
    type: Literal["unknown"] = "unknown"
    basis: None = None


class ChainStore(ChainModel):
    source: StoreSource
    license_no: str
    name: str | None
    category: Literal["cafe", "restaurant"]
    sub_category: SubCategory
    open_date: date | None
    close_date: date | None
    operating_months: int | None = Field(ge=0)
    operating_period_status: Literal["fact", "no_data"]
    operating_period_reason: PeriodReason | None
    current_status: StoreStatus
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    distance_m: float | None = Field(default=None, ge=0)
    area_m2: float | None = Field(default=None, gt=0)
    floor_unit: str | None = None
    location_match: Literal["same_spot", "same_building", "unverified"] | None = None
    brand: ChainBrand
    operation: ChainOperation = Field(default_factory=ChainOperation)

    @model_validator(mode="after")
    def consistent_period(self) -> Self:
        if self.operating_months is None:
            if self.operating_period_status != "no_data" or self.operating_period_reason is None:
                raise ValueError("missing period reason")
        elif self.operating_period_status != "fact" or self.operating_period_reason is not None:
            raise ValueError("inconsistent period")
        return self


class ChainNearby(ChainModel):
    center: Center
    radius_m: int
    as_of: date
    count: int = Field(ge=0)
    excluded_no_coord: int = Field(ge=0)
    markers: list[ChainStore]
    message: str | None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.count != len(self.markers):
            raise ValueError("incomplete result")
        return self


class ChainSnapshot(ChainModel):
    as_of: date
    total_at_as_of: int = Field(ge=0)
    still_open: int = Field(ge=0)
    closed_since: int = Field(ge=0)
    other: int = Field(ge=0)
    stores: list[ChainStore]
    summary_text: str
    excluded_no_coord: int = Field(ge=0)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if (
            self.total_at_as_of != len(self.stores)
            or self.total_at_as_of != self.still_open + self.closed_since + self.other
        ):
            raise ValueError("incomplete partition")
        return self


class ChainHistory(ChainModel):
    total: int = Field(ge=0)
    stores: list[ChainStore]
    message: str | None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.total != len(self.stores):
            raise ValueError("incomplete history")
        return self
