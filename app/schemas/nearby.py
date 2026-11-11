import re
from datetime import date
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.geocode import Category
from app.schemas.stores import PeriodReason, StoreSource, StoreStatus, SubCategory


class NearbyQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    category: Category
    radius: Literal[300, 500, 1000] = 500
    sub_category: tuple[SubCategory, ...] = ()
    as_of: str | None = None
    area: Literal["all", "lt33", "33to66", "66to99", "gte99"] = "all"
    franchise: Literal["all", "franchise", "independent"] = "all"
    include_unknown_area: bool = True
    include_unknown_franchise: bool = True
    include_unknown: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def exclusive_unknown_flags(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and "include_unknown" in value
            and ("include_unknown_area" in value or "include_unknown_franchise" in value)
        ):
            raise ValueError("mixed unknown flags")
        return value

    @field_validator("radius", mode="before")
    @classmethod
    def integer_radius(cls, value: Any) -> Any:
        if isinstance(value, str) and value in {"300", "500", "1000"}:
            return int(value)
        if type(value) is not int:
            raise ValueError("invalid radius")
        return value

    @field_validator("sub_category", mode="before")
    @classmethod
    def comma_categories(cls, value: Any) -> Any:
        return value.split(",") if isinstance(value, str) else value

    @field_validator("as_of")
    @classmethod
    def valid_month(cls, value: str | None) -> str | None:
        if value is not None:
            if re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", value) is None:
                raise ValueError("invalid month")
            date(int(value[:4]), int(value[5:]), 1)
        return value

    @field_validator(
        "include_unknown_area", "include_unknown_franchise", "include_unknown", mode="before"
    )
    @classmethod
    def strict_boolean(cls, value: Any) -> bool:
        if type(value) is bool:
            return value
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError("invalid boolean")

    @model_validator(mode="after")
    def consistent_filters(self) -> Self:
        allowed = (
            {"cafe"} if self.category == "cafe" else {"korean", "chinese", "japanese", "western"}
        )
        if (
            len(self.sub_category) != len(set(self.sub_category))
            or not set(self.sub_category) <= allowed
        ):
            raise ValueError("invalid sub categories")
        if self.include_unknown is not None:
            self.include_unknown_area = self.include_unknown
            self.include_unknown_franchise = self.include_unknown
        return self


class Center(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class NearbyMarker(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    source: StoreSource
    license_no: str
    name: str | None
    sub_category: SubCategory
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    distance_m: float = Field(ge=0, allow_inf_nan=False)
    open_date: date
    close_date: date | None
    operating_months: int | None = Field(ge=0)
    operating_period_status: Literal["fact", "no_data"]
    operating_period_reason: PeriodReason | None
    current_status: StoreStatus
    franchise: Literal["franchise", "independent", "unknown"]
    area_m2: float | None = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent_period(self) -> Self:
        if self.operating_months is None:
            if self.operating_period_status != "no_data" or self.operating_period_reason is None:
                raise ValueError("missing period requires a reason")
        elif self.operating_period_status != "fact" or self.operating_period_reason is not None:
            raise ValueError("calculated period cannot have a reason")
        return self


class NearbyStores(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    center: Center
    radius_m: int
    as_of: date
    count: int = Field(ge=0)
    excluded_no_coord: int = Field(ge=0)
    markers: list[NearbyMarker]
    message: str | None

    @model_validator(mode="after")
    def complete_result(self) -> Self:
        if self.count != len(self.markers):
            raise ValueError("incomplete markers")
        return self
