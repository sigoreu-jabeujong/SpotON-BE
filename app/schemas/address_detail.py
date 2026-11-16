from typing import Literal

from pydantic import BaseModel, ConfigDict


class NormalizedDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    floor_unit: str | None
    status: Literal["parsed", "empty", "unverified"]
    reason: Literal["empty", "no_detail", "ambiguous", "invalid"] | None


class LocationRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building: Literal["matched_address_scope"]
    basis: Literal["canonical_jibun_key"]
    floor: Literal["match", "different", "unknown"]
    unit: Literal["match", "different", "unknown"]
    relation_level: Literal["same_spot", "same_floor", "same_building_scope", "unverified"]
