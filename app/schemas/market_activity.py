from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.nearby import NearbyQuery
from app.schemas.stores import SubCategory

ActivityInclude = Literal["sales", "living_pop"]


class ActivityQuery(NearbyQuery):
    include: tuple[ActivityInclude, ...] = ()

    @field_validator("include", mode="before")
    @classmethod
    def comma_include(cls, value: Any) -> Any:
        return value.split(",") if isinstance(value, str) else value

    @field_validator("include")
    @classmethod
    def unique_include(cls, value: tuple[ActivityInclude, ...]) -> tuple[ActivityInclude, ...]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate include")
        return value


class ActivityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class RecentActivity(ActivityModel):
    period: str
    opened: int = Field(ge=0)
    closed: int = Field(ge=0)


class YearlyActivity(ActivityModel):
    year: int = Field(ge=1960, le=9999)
    opened: int = Field(ge=0)
    closed: int = Field(ge=0)


class SubCategoryActivity(ActivityModel):
    sub_category: SubCategory
    open_count: int = Field(ge=0)
    avg_operating_months: int | None = Field(ge=0)

    @model_validator(mode="after")
    def consistent_average(self) -> Self:
        if (self.open_count == 0) != (self.avg_operating_months is None):
            raise ValueError("average requires a positive denominator")
        return self


class ActivityFlags(ActivityModel):
    missing: list[ActivityInclude]

    @field_validator("missing")
    @classmethod
    def unique_missing(cls, value: list[ActivityInclude]) -> list[ActivityInclude]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate missing")
        return value


class MarketActivity(ActivityModel):
    recent_12m: RecentActivity
    yearly_trend: list[YearlyActivity]
    by_sub_category: list[SubCategoryActivity]
    sales: None = Field(description="This release returns null; see meta.optional_data.")
    living_pop: None = Field(description="This release returns null; see meta.optional_data.")
    flags: ActivityFlags

    @model_validator(mode="after")
    def unique_groups(self) -> Self:
        years = [row.year for row in self.yearly_trend]
        categories = [row.sub_category for row in self.by_sub_category]
        if years != sorted(set(years)) or len(categories) != len(set(categories)):
            raise ValueError("duplicate or unordered activity groups")
        return self
