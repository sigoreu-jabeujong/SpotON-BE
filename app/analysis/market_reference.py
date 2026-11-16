"""Internal source projections; never establish applicability or enable public metrics."""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from etl.market_changes.source import CHANGES
from etl.market_stores.archive import SUPPORTED

PeriodBasis = Literal["quarter_total", "monthly_average", "specific_month"]
_QUARTER = re.compile(r"20[0-9]{2}[1-4]")


def _quarter(value: object) -> str:
    if type(value) is not str or not _QUARTER.fullmatch(value):
        raise ValueError("market_reference_invalid")
    return value


def select_quarter(target: date, verified_periods: tuple[str, ...], *, current: bool) -> str | None:
    """The caller must validate the supplied periods; do not infer source approval."""
    if (
        type(target) is not date
        or not 2000 <= target.year <= 2099
        or type(current) is not bool
        or type(verified_periods) is not tuple
        or len(verified_periods) > 400
    ):
        raise ValueError("market_reference_invalid")
    periods = tuple(_quarter(p) for p in verified_periods)
    if len(set(periods)) != len(periods):
        raise ValueError("market_reference_invalid")
    desired = f"{target.year}{(target.month - 1) // 3 + 1}"
    if current:
        return max((p for p in periods if p <= desired), default=None)
    return desired if desired in periods else None


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    def __repr_args__(self) -> list[tuple[str | None, object]]:
        return []


class ReferenceSource(ReferenceModel):
    version_id: UUID = Field(repr=False)
    boundary_version_id: UUID = Field(repr=False)
    quarter: str = Field(pattern=r"^20[0-9]{2}[1-4]$")
    market_code: str = Field(pattern=r"^[0-9]{7}$", repr=False)


class SalesSource(ReferenceSource):
    industry_code: str
    est_sales: int | None = Field(ge=0, le=2**63 - 1)
    source_sales_count: int | None = Field(ge=0, le=2**63 - 1)

    @field_validator("industry_code")
    @classmethod
    def supported_industry(cls, value: str) -> str:
        if value not in SUPPORTED:
            raise ValueError("market_reference_invalid")
        return value


class ChangeSource(ReferenceSource):
    change_code: Literal["LL", "LH", "HL", "HH"]
    change_name: str
    operating_months_avg: int | None = Field(ge=0, le=2**31 - 1)
    closed_months_avg: int | None = Field(ge=0, le=2**31 - 1)
    seoul_operating_months_avg: int | None = Field(ge=0, le=2**31 - 1)
    seoul_closed_months_avg: int | None = Field(ge=0, le=2**31 - 1)

    @model_validator(mode="after")
    def correct_name(self) -> Self:
        if CHANGES[self.change_code] != self.change_name:
            raise ValueError("market_reference_invalid")
        return self


@dataclass(frozen=True, repr=False)
class SourceProjection:
    quarter: str | None
    row_present: bool
    source_validation_performed: Literal[False] = field(default=False, init=False)
    public_activation_ready: Literal[False] = field(default=False, init=False)
    brand_filter_applied: Literal[False] = field(default=False, init=False)
    license_filters_applied: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, repr=False)
class SalesProjection(SourceProjection):
    status: Literal["available", "partial", "no_data"]
    source: SalesSource | None
    period_basis: PeriodBasis
    source_month: date | None
    currency: Literal["KRW"] = field(default="KRW", init=False)
    space: Literal["market_industry"] = field(default="market_industry", init=False)


@dataclass(frozen=True, repr=False)
class ChangeProjection(SourceProjection):
    status: Literal["available", "no_data"]
    source: ChangeSource | None
    space: Literal["market_all_industries"] = field(default="market_all_industries", init=False)


def _selected(row: ReferenceSource | None, selected_quarter: str | None) -> None:
    if selected_quarter is not None:
        _quarter(selected_quarter)
    if row is not None and row.quarter != selected_quarter:
        raise ValueError("market_reference_invalid")


def project_sales(
    row: SalesSource | None,
    *,
    selected_quarter: str | None,
    period_basis: PeriodBasis,
    source_month: date | None = None,
) -> SalesProjection:
    if (
        (row is not None and type(row) is not SalesSource)
        or type(period_basis) is not str
        or period_basis not in {"quarter_total", "monthly_average", "specific_month"}
    ):
        raise ValueError("market_reference_invalid")
    _selected(row, selected_quarter)
    if period_basis == "specific_month":
        if (
            type(source_month) is not date
            or source_month.day != 1
            or f"{source_month.year}{(source_month.month - 1) // 3 + 1}" != selected_quarter
        ):
            raise ValueError("market_reference_invalid")
    elif source_month is not None:
        raise ValueError("market_reference_invalid")
    missing = 2 if row is None else sum(v is None for v in (row.est_sales, row.source_sales_count))
    return SalesProjection(
        selected_quarter,
        row is not None,
        "no_data" if missing == 2 else "partial" if missing else "available",
        row,
        period_basis,
        source_month,
    )


def project_change(row: ChangeSource | None, *, selected_quarter: str | None) -> ChangeProjection:
    if row is not None and type(row) is not ChangeSource:
        raise ValueError("market_reference_invalid")
    _selected(row, selected_quarter)
    return ChangeProjection(
        selected_quarter, row is not None, "no_data" if row is None else "available", row
    )
