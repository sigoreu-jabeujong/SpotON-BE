from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.location_history import LocationHistoryStore
from app.schemas.stores import HistoryQuery
from etl.address.floor_unit import parse_floor_unit


class ContextRequest(HistoryQuery):
    address: str = Field(min_length=1, max_length=1000)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    category: Literal["cafe", "restaurant"]
    floor_unit: None = None


class AddressHistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    context: str = Field(min_length=1, max_length=4096, repr=False)
    floor_unit: str | None = Field(default=None, max_length=100)
    category: Literal["cafe", "restaurant"] | None = None

    @model_validator(mode="after")
    def normalize_detail(self) -> Self:
        if self.floor_unit is not None:
            detail = parse_floor_unit(self.floor_unit).value
            if detail is None or detail.floor is None:
                raise ValueError("explicit floor required for detail search")
            self.floor_unit = detail.value
        return self


class AddressHistorySelection(BaseModel):
    building_key: str
    road_key: str | None
    scope: Literal["address", "floor", "unit"]
    floor: str | None
    unit: str | None
    identity_requirement: Literal["address_scope"] = "address_scope"
    status_filter: Literal["all"] = "all"


class AddressHistoryStore(LocationHistoryStore):
    match_evidence: Literal["road", "jibun", "both"]
    history_scope: Literal["address", "floor", "unit"]


class AddressHistory(BaseModel):
    selection: AddressHistorySelection
    result_status: Literal["matched", "no_data"]
    location_coverage: Literal["complete", "partial"]
    total: int = Field(ge=0)
    open_count: int = Field(ge=0)
    closed_count: int = Field(ge=0)
    other_count: int = Field(ge=0)
    dated_closure_count: int = Field(ge=0)
    undated_closure_count: int = Field(ge=0)
    address_conflict_count: int = Field(ge=0)
    address_unresolved_count: int = Field(ge=0)
    detail_unresolved_count: int = Field(ge=0)
    excluded_counts: dict[Literal["floor", "unit"], int]
    candidate_count: int = Field(ge=0)
    stores: list[AddressHistoryStore]
    current_vacancy: Literal["not_verified"] = "not_verified"

    @model_validator(mode="after")
    def cohort(self) -> Self:
        if self.total != len(self.stores):
            raise ValueError("total mismatch")
        if (self.open_count, self.closed_count, self.other_count) != tuple(
            sum(s.current_status == status for s in self.stores)
            for status in ("open", "closed", "other")
        ):
            raise ValueError("status counts mismatch")
        if self.dated_closure_count != sum(s.closure_date_status == "dated" for s in self.stores):
            raise ValueError("closure count mismatch")
        if self.dated_closure_count + self.undated_closure_count != self.closed_count:
            raise ValueError("closure count mismatch")
        unresolved = (
            self.address_conflict_count
            + self.address_unresolved_count
            + self.detail_unresolved_count
        )
        if self.total + unresolved + sum(self.excluded_counts.values()) != self.candidate_count:
            raise ValueError("candidate partition mismatch")
        if any(n < 0 for n in self.excluded_counts.values()):
            raise ValueError("negative count")
        if (self.result_status == "matched") != bool(self.total):
            raise ValueError("result mismatch")
        if (self.location_coverage == "partial") != bool(unresolved):
            raise ValueError("coverage mismatch")
        return self
