from collections import Counter
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.franchise import FranchiseBasis
from app.schemas.nearby import NearbyQuery
from app.schemas.stores import PeriodReason, StoreSource, StoreStatus, SubCategory


class SnapshotQuery(NearbyQuery):
    as_of: str = Field(...)


class SnapshotStore(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    source: StoreSource
    license_no: str
    name: str | None
    sub_category: SubCategory
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    open_date: date
    close_date: date | None
    operating_months: int | None = Field(ge=0)
    operating_period_status: Literal["fact", "no_data"]
    operating_period_reason: PeriodReason | None
    current_status: StoreStatus
    franchise: Literal["franchise", "independent", "unknown"] = "unknown"
    franchise_basis: FranchiseBasis | None = None
    franchise_reference_year: int | None = Field(default=None, ge=2000, le=9999)

    @model_validator(mode="after")
    def consistent_period(self) -> Self:
        if self.operating_months is None:
            if self.operating_period_status != "no_data" or self.operating_period_reason is None:
                raise ValueError("missing period requires a reason")
        elif self.operating_period_status != "fact" or self.operating_period_reason is not None:
            raise ValueError("calculated period cannot have a reason")
        return self


class StoreSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    as_of: date
    total_at_as_of: int = Field(ge=0)
    still_open: int = Field(ge=0)
    closed_since: int = Field(ge=0)
    other: int = Field(ge=0)
    stores: list[SnapshotStore]
    summary_text: str
    excluded_no_coord: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent_partition(self) -> Self:
        counts = Counter(store.current_status for store in self.stores)
        identities = {(store.source, store.license_no) for store in self.stores}
        if (
            self.total_at_as_of != len(self.stores)
            or self.total_at_as_of != self.still_open + self.closed_since + self.other
            or self.still_open != counts["open"]
            or self.closed_since != counts["closed"]
            or self.other != counts["other"]
            or len(identities) != len(self.stores)
        ):
            raise ValueError("inconsistent snapshot partition")
        return self
