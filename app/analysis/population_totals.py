"""Assemble a caller-established component set; not a source approval or API service."""

from dataclasses import dataclass, field
from datetime import date
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis.day_night import DayNightSummary, calculate_day_night

MAX_COMPONENTS = 100_000
_LIMIT = Decimal("1e15")
SOURCES = ("local", "long", "short")
GridId = Annotated[str, Field(pattern=r"^[가-힣]{2}[0-9]{8}$")]


class PopulationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    def __repr_args__(self) -> list[tuple[str | None, object]]:
        return []


class PopulationScope(PopulationModel):
    observation_date: date
    grid_version_id: UUID = Field(repr=False)
    observation_version_id: UUID = Field(repr=False)
    space_id: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    grid_ids: tuple[GridId, ...] = Field(min_length=1, max_length=1000, repr=False)

    @model_validator(mode="after")
    def unique_grids(self) -> Self:
        if len(set(self.grid_ids)) != len(self.grid_ids):
            raise ValueError("population_components_invalid")
        return self


class PopulationCell(PopulationModel):
    source: Literal["local", "long", "short"]
    hour: int = Field(ge=0, le=23)
    grid_id: str = Field(pattern=r"^[가-힣]{2}[0-9]{8}$", repr=False)
    admin_code: str = Field(pattern=r"^11[0-9]{6}$", repr=False)


class PopulationObservation(PopulationModel):
    scope: PopulationScope = Field(repr=False)
    cell: PopulationCell = Field(repr=False)
    total_status: Literal["observed", "suppressed", "missing"]
    total: Decimal | None = Field(repr=False)

    @model_validator(mode="after")
    def consistent_total(self) -> Self:
        if self.total_status != "observed":
            if self.total is not None:
                raise ValueError("population_components_invalid")
            return self
        value = self.total
        if type(value) is not Decimal or not value.is_finite() or value < 0 or value >= _LIMIT:
            raise ValueError("population_components_invalid")
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -5:
            raise ValueError("population_components_invalid")
        return self


@dataclass(frozen=True, repr=False)
class PopulationAssembly:
    hours: tuple[Decimal | None, ...]
    summary: DayNightSummary
    absent: int
    suppressed: int
    missing: int
    source_validation_performed: Literal[False] = field(default=False, init=False)
    public_activation_ready: Literal[False] = field(default=False, init=False)


def assemble_population(
    scope: PopulationScope,
    expected: tuple[PopulationCell, ...],
    observations: tuple[PopulationObservation, ...],
) -> PopulationAssembly:
    """Expected components must come from independent, applicable source evidence.

    Row-derived expectations cannot establish completeness. Matching a caller's
    set validates its arithmetic only; it cannot prove no omitted components.
    """
    if (
        type(scope) is not PopulationScope
        or type(expected) is not tuple
        or not 1 <= len(expected) <= MAX_COMPONENTS
        or any(type(c) is not PopulationCell for c in expected)
        or type(observations) is not tuple
        or len(observations) > MAX_COMPONENTS
        or any(type(o) is not PopulationObservation for o in observations)
    ):
        raise ValueError("population_components_invalid")
    keys = set(expected)
    if len(keys) != len(expected) or {(c.grid_id, c.source, c.hour) for c in keys} != {
        (g, s, h) for g in scope.grid_ids for s in SOURCES for h in range(24)
    }:
        raise ValueError("population_components_invalid")
    actual = {}
    for observation in observations:
        if observation.scope != scope or observation.cell not in keys or observation.cell in actual:
            raise ValueError("population_components_invalid")
        actual[observation.cell] = observation
    absent = suppressed = missing = 0
    totals = [Decimal(0) for _ in range(24)]
    incomplete = set()
    with localcontext(
        Context(
            prec=50,
            rounding=ROUND_HALF_UP,
            Emin=-999999,
            Emax=999999,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[InvalidOperation, DivisionByZero, Overflow],
        )
    ):
        for cell in expected:
            item = actual.get(cell)
            if item is None:
                absent += 1
            elif item.total_status == "suppressed":
                suppressed += 1
            elif item.total_status == "missing":
                missing += 1
            else:
                assert item.total is not None
                totals[cell.hour] += item.total.copy_abs() if item.total.is_zero() else item.total
                if totals[cell.hour] >= _LIMIT:
                    raise ValueError("population_components_invalid")
                continue
            incomplete.add(cell.hour)
    hours = tuple(None if h in incomplete else v for h, v in enumerate(totals))
    return PopulationAssembly(hours, calculate_day_night(hours), absent, suppressed, missing)
