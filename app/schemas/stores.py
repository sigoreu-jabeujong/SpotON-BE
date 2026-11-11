import re
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.geocode import Category
from etl.address.building_key import build_from_parts
from etl.address.floor_unit import parse_floor_unit

StoreSource = Literal["general_restaurant", "rest_cafe"]
StoreStatus = Literal["open", "closed", "other"]
SubCategory = Literal["cafe", "korean", "chinese", "japanese", "western"]
PeriodReason = Literal[
    "missing_open_date",
    "invalid_open_date",
    "missing_close_date",
    "invalid_close_date",
    "missing_source_date",
    "invalid_date_order",
    "other_status",
]


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    building_key: str = Field(min_length=1, max_length=255)
    floor_unit: str | None = Field(default=None, max_length=100)
    category: Category | None = None

    @field_validator("building_key")
    @classmethod
    def canonical_key(cls, value: str) -> str:
        match = re.fullmatch(r"([가-힣]+구)-([가-힣0-9]+)-(산?)([0-9]{1,4})-([0-9]{1,4})", value)
        if match is None:
            raise ValueError("invalid building key")
        gu, dong, mountain, main, sub = match.groups()
        result = build_from_parts(gu, dong, int(main), int(sub), bool(mountain))
        if result.lot is None or result.lot.key != value:
            raise ValueError("invalid building key")
        return value

    @field_validator("floor_unit")
    @classmethod
    def canonical_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        result = parse_floor_unit(value)
        if result.value is None:
            raise ValueError("invalid floor unit")
        return result.value.value


class HistoryStore(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    source: StoreSource
    license_no: str
    name: str | None
    category: Category
    sub_category: SubCategory
    open_date: date | None
    close_date: date | None
    operating_months: int | None = Field(ge=0)
    operating_period_status: Literal["fact", "no_data"]
    operating_period_reason: PeriodReason | None
    store_status: StoreStatus
    franchise: Literal["franchise", "independent", "unknown"]
    floor_unit: str | None
    location_match: Literal["same_spot", "same_building", "unverified"]

    @model_validator(mode="after")
    def consistent_period(self) -> Self:
        if self.operating_months is None:
            if self.operating_period_status != "no_data" or self.operating_period_reason is None:
                raise ValueError("missing period requires a reason")
        elif self.operating_period_status != "fact" or self.operating_period_reason is not None:
            raise ValueError("calculated period cannot have a missing reason")
        return self


class StoreHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    total: int = Field(ge=0)
    stores: list[HistoryStore]
    message: str | None
