from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.geocode import Category
from app.schemas.stores import SubCategory


class CategoryFilters(BaseModel):
    """API v1.2 §2-2/§4-5: supported category selection, without location/attributes."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    category: Category
    sub_category: tuple[SubCategory, ...] = ()

    @field_validator("sub_category", mode="before")
    @classmethod
    def comma_categories(cls, value: Any) -> Any:
        return value.split(",") if isinstance(value, str) else value

    @model_validator(mode="after")
    def consistent_categories(self) -> Self:
        allowed = (
            {"cafe"} if self.category == "cafe" else {"korean", "chinese", "japanese", "western"}
        )
        if (
            len(self.sub_category) != len(set(self.sub_category))
            or not set(self.sub_category) <= allowed
        ):
            raise ValueError("invalid sub categories")
        return self
