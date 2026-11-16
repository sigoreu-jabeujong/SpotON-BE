from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chains import ChainStore
from app.schemas.stores import HistoryQuery
from etl.address.floor_unit import parse_floor_unit

POLICY = "location-history-all-status-v1"


class LocationHistoryQuery(HistoryQuery):
    floor_unit: str = Field(min_length=1, max_length=100)
    scope: Literal["floor", "unit"]
    identity_requirement: Literal["address_scope", "verified_building"]

    @model_validator(mode="after")
    def required_details(self) -> Self:
        value = parse_floor_unit(self.floor_unit).value
        if value is None or not value.floor or (self.scope == "unit" and not value.unit):
            raise ValueError("explicit floor and requested unit required")
        return self


class HistorySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building_key: str
    floor: str
    unit: str | None
    scope: Literal["floor", "unit"]
    identity_requirement: Literal["address_scope", "verified_building"]
    status_filter: Literal["all"] = "all"
    unit_ignored: bool


class LocationHistoryStore(ChainStore):
    closure_date_status: Literal["dated", "undated", "not_applicable"]

    @model_validator(mode="after")
    def closure_quality(self) -> Self:
        if self.current_status != "closed":
            if self.closure_date_status != "not_applicable" or self.close_date is not None:
                raise ValueError("non-closed store cannot have a closure date")
        elif self.closure_date_status == "not_applicable" or (
            (self.closure_date_status == "dated") != (self.close_date is not None)
        ):
            raise ValueError("closure date quality mismatch")
        return self


class LocationHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: HistorySelection
    result_status: Literal["matched", "no_data", "pending_identity"]
    location_coverage: Literal["complete", "partial", "not_evaluated"]
    total: int = Field(ge=0)
    open_count: int = Field(ge=0)
    closed_count: int = Field(ge=0)
    other_count: int = Field(ge=0)
    dated_closure_count: int = Field(ge=0)
    undated_closure_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    excluded_counts: dict[Literal["floor", "unit"], int]
    scope_limitations: list[str]
    stores: list[LocationHistoryStore]
    current_vacancy: Literal["not_verified"] = "not_verified"

    @model_validator(mode="after")
    def consistent_cohort(self) -> Self:
        if self.total != len(self.stores):
            raise ValueError("total mismatch")
        if (self.open_count, self.closed_count, self.other_count) != tuple(
            sum(s.current_status == status for s in self.stores)
            for status in ("open", "closed", "other")
        ):
            raise ValueError("status counts mismatch")
        if self.dated_closure_count != sum(s.closure_date_status == "dated" for s in self.stores):
            raise ValueError("dated mismatch")
        if self.dated_closure_count + self.undated_closure_count != self.closed_count:
            raise ValueError("closure counts mismatch")
        if any(n < 0 for n in self.excluded_counts.values()):
            raise ValueError("negative excluded count")
        if self.result_status == "pending_identity":
            if self.location_coverage != "not_evaluated" or self.total or self.unresolved_count:
                raise ValueError("pending identity cannot contain a cohort")
        elif (
            (self.result_status == "matched") != bool(self.total)
            or self.location_coverage == "not_evaluated"
            or (self.location_coverage == "partial") != bool(self.unresolved_count)
        ):
            raise ValueError("result and coverage mismatch")
        return self
