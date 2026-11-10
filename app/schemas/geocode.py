from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["cafe", "restaurant"]


class GeocodeCandidate(BaseModel):
    """A verified Seoul address candidate safe for downstream lookup APIs."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    address_road: str
    address_jibun: str
    lat: float
    lng: float
    category: Category
    is_seoul: Literal[True] = True
    sigungu: str
    building_key: str
    floor_unit: str | None


class GeocodeData(GeocodeCandidate):
    candidates: list[GeocodeCandidate] = Field(default_factory=list)
