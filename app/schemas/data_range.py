from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.store_filters import CategoryFilters


class DataRangeQuery(CategoryFilters):
    pass


class DataRange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    min_month: str | None = Field(pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])$")
    max_month: str = Field(pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])$")
    max_date: date
    data_updated_at: date
    collected_at: date | None

    @model_validator(mode="after")
    def consistent_range(self) -> Self:
        if (
            self.max_month != self.max_date.strftime("%Y-%m")
            or self.max_date != self.data_updated_at
            or (self.min_month is not None and self.min_month > self.max_month)
        ):
            raise ValueError("inconsistent date range")
        return self
