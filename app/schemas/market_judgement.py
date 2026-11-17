from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MarketType = Literal["alley", "developed", "traditional_market", "tourism_zone"]


class BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class BoundaryQuery(BoundaryModel):
    version_id: UUID
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    radius: Literal[300, 500, 1000] = 500


class MarketRef(BoundaryModel):
    market_code: str = Field(pattern=r"^[0-9]{7}$")
    market_name: str = Field(min_length=1)
    market_type: MarketType


class BoundaryProvenance(BoundaryModel):
    version_id: UUID
    source_dataset: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_file_date: date
    boundary_as_of: date | None
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_version: str = Field(min_length=1)
    judgement_rule_version: Literal["market-spatial-explicit-version-v1"] = (
        "market-spatial-explicit-version-v1"
    )
    applicability: Literal["unverified"] = "unverified"
    reason: Literal["boundary_period_not_verified"] = "boundary_period_not_verified"


class SpatialJudgement(BoundaryModel):
    spatial_status: Literal["in_market", "outside", "ambiguous"]
    primary: MarketRef | None
    candidates: list[MarketRef]
    also_in: list[MarketRef]
    nearby_markets: list[MarketRef]

    @model_validator(mode="after")
    def consistent_groups(self) -> Self:
        codes = [self.primary.market_code] if self.primary else []
        for group in (self.candidates, self.also_in, self.nearby_markets):
            group_codes = [r.market_code for r in group]
            if group_codes != sorted(set(group_codes)):
                raise ValueError("unordered or duplicate markets")
            codes.extend(group_codes)
        if len(codes) != len(set(codes)):
            raise ValueError("overlapping result groups")
        if any(r.market_type != "tourism_zone" for r in self.also_in):
            raise ValueError("also_in requires tourism zones")
        if self.spatial_status == "outside":
            if self.primary or self.candidates or self.also_in:
                raise ValueError("outside cannot contain covering markets")
        else:
            if self.nearby_markets:
                raise ValueError("nearby is only for outside")
            if self.spatial_status == "in_market":
                if self.primary is None or self.candidates:
                    raise ValueError("in_market requires one primary")
                if self.primary.market_type == "tourism_zone" and self.also_in:
                    raise ValueError("tourism primary cannot have also_in")
            else:
                if self.primary or len(self.candidates) < 2:
                    raise ValueError("ambiguous requires multiple candidates")
                tourism = [r.market_type == "tourism_zone" for r in self.candidates]
                if any(tourism) and (not all(tourism) or self.also_in):
                    raise ValueError("mixed candidate priorities")
        return self


class BoundaryJudgement(SpatialJudgement):
    provenance: BoundaryProvenance
