"""General v2 analysis contracts, without affiliation classification."""

from datetime import date
from typing import Any, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.address_detail import LocationRelation
from app.schemas.common import ApiMeta
from app.schemas.market_activity import ActivityInclude, ActivityQuery
from app.schemas.nearby import Center, NearbyQuery
from app.schemas.risk import RiskInclude, RiskQuery
from app.schemas.store_filters import CategoryFilters
from app.schemas.stores import PeriodReason, StoreSource, StoreStatus, SubCategory

T = TypeVar("T", bound=NearbyQuery)


class AnalysisQuery(CategoryFilters):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    radius: Literal[300, 500, 1000] = 500
    as_of: str | None = None
    area: Literal["all", "lt33", "33to66", "66to99", "gte99"] = "all"
    include_unknown_area: bool = True

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
        return model.model_validate(self.model_dump(include=set(model.model_fields)))

    def echo_filters(self) -> ApiMeta:
        return self.model_dump(
            include={"sub_category", "area", "include_unknown_area"}, mode="json"
        )


class AnalysisSnapshotQuery(AnalysisQuery):
    as_of: str = Field(...)


class AnalysisActivityQuery(AnalysisQuery):
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


class AnalysisRiskQuery(AnalysisQuery):
    include: tuple[RiskInclude, ...] = ()

    @field_validator("include", mode="before")
    @classmethod
    def includes(cls, value: Any) -> Any:
        return RiskQuery.comma_include(value)

    @field_validator("include")
    @classmethod
    def unique_includes(cls, value: tuple[RiskInclude, ...]) -> tuple[RiskInclude, ...]:
        return RiskQuery.unique_include(value)


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class AnalysisStore(AnalysisModel):
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
    location_relation: LocationRelation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def consistent_period(self) -> Self:
        if self.operating_months is None:
            if self.operating_period_status != "no_data" or self.operating_period_reason is None:
                raise ValueError("missing period reason")
        elif self.operating_period_status != "fact" or self.operating_period_reason is not None:
            raise ValueError("inconsistent period")
        return self


class AnalysisNearby(AnalysisModel):
    center: Center
    radius_m: int
    as_of: date
    count: int = Field(ge=0)
    excluded_no_coord: int = Field(ge=0)
    markers: list[AnalysisStore]
    message: str | None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.count != len(self.markers):
            raise ValueError("incomplete result")
        return self


class AnalysisSnapshot(AnalysisModel):
    as_of: date
    total_at_as_of: int = Field(ge=0)
    still_open: int = Field(ge=0)
    closed_since: int = Field(ge=0)
    other: int = Field(ge=0)
    stores: list[AnalysisStore]
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


class AnalysisHistory(AnalysisModel):
    total: int = Field(ge=0)
    stores: list[AnalysisStore]
    message: str | None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.total != len(self.stores):
            raise ValueError("incomplete history")
        return self
