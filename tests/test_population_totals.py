from datetime import date, datetime
from decimal import Decimal, DefaultContext, Inexact, localcontext
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.analysis.population_totals import (
    PopulationCell,
    PopulationObservation,
    PopulationScope,
    assemble_population,
)


@pytest.fixture
def inputs():
    scope = PopulationScope(
        observation_date=date(2026, 11, 7),
        grid_version_id=UUID(int=1),
        observation_version_id=UUID(int=2),
        space_id="a" * 64,
        grid_ids=("다사12341234",),
    )
    expected = tuple(
        PopulationCell(source=s, hour=h, grid_id="다사12341234", admin_code=a)
        for h in range(24)
        for s in ("local", "long", "short")
        for a in ("11140520", "11140530")
    )
    rows = tuple(
        PopulationObservation(
            scope=scope,
            cell=c,
            total_status="observed",
            total=Decimal("2.12345") if 6 <= c.hour < 18 else Decimal("1.00000"),
        )
        for c in expected
    )
    return scope, expected, rows


def test_full_components_are_order_independent_and_feed_day_night(inputs):
    scope, expected, rows = inputs
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        result = assemble_population(scope, expected, tuple(reversed(rows)))
    assert result.hours[6] == Decimal("12.74070") and result.hours[0] == Decimal("6.00000")
    assert result.summary.day_total == Decimal("152.88840")
    assert result.summary.night_total == Decimal("72.00000")
    assert result.summary.status == "calculated"
    assert (result.absent, result.suppressed, result.missing) == (0, 0, 0)
    assert not result.source_validation_performed and not result.public_activation_ready
    assert result == assemble_population(scope, tuple(reversed(expected)), rows)


def test_missing_suppressed_and_absent_do_not_become_zero_or_partial_sum(inputs):
    scope, expected, rows = inputs
    changed = list(rows)
    changed[1] = PopulationObservation(
        scope=scope, cell=expected[1], total_status="suppressed", total=None
    )
    changed[7] = PopulationObservation(
        scope=scope, cell=expected[7], total_status="missing", total=None
    )
    del changed[12]
    result = assemble_population(scope, expected, tuple(changed))
    assert (result.absent, result.suppressed, result.missing) == (1, 1, 1)
    assert result.hours[:3] == (None, None, None)
    assert result.summary.status == "incomplete" and result.summary.unavailable_hours == (0, 1, 2)
    assert result.summary.day_total is None and result.summary.night_total is None
    assert result.summary.day_night_ratio is None


def test_zero_is_observed_and_no_rows_is_not_zero(inputs):
    scope, expected, rows = inputs
    zeros = tuple(
        PopulationObservation(
            scope=scope, cell=r.cell, total_status="observed", total=Decimal("-0.00000")
        )
        for r in rows
    )
    result = assemble_population(scope, expected, zeros)
    assert result.summary.status == "zero_total" and all(
        v == 0 and not v.is_signed() for v in result.hours
    )
    absent = assemble_population(scope, expected, ())
    assert absent.absent == len(expected) and absent.summary.status == "incomplete"


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate_expected",
        "duplicate_observation",
        "unexpected",
        "scope",
        "source_hour_absent",
        "empty",
        "list",
    ],
)
def test_invalid_composition_cannot_be_reported_complete(inputs, kind):
    scope, expected, rows = inputs
    if kind == "duplicate_expected":
        expected = (*expected, expected[0])
    elif kind == "duplicate_observation":
        rows = (*rows, rows[0])
    elif kind == "unexpected":
        cell = rows[0].cell.model_copy(update={"grid_id": "다사99999999"})
        rows = (rows[0].model_copy(update={"cell": cell}), *rows[1:])
    elif kind == "scope":
        other = scope.model_copy(update={"observation_date": date(2026, 11, 8)})
        rows = (rows[0].model_copy(update={"scope": other}), *rows[1:])
    elif kind == "source_hour_absent":
        expected = tuple(c for c in expected if (c.source, c.hour) != ("short", 4))
        rows = tuple(r for r in rows if r.cell in expected)
    elif kind == "empty":
        expected = ()
    else:
        expected = list(expected)
    with pytest.raises(ValueError, match="^population_components_invalid$"):
        assemble_population(scope, expected, rows)


@pytest.mark.parametrize(
    "value",
    [
        None,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-1"),
        Decimal("1e15"),
        Decimal("0.000001"),
        1,
        "1",
        True,
    ],
)
def test_observed_total_requires_finite_nonnegative_strict_decimal(inputs, value):
    scope, expected, _ = inputs
    with pytest.raises(ValidationError):
        PopulationObservation(scope=scope, cell=expected[0], total_status="observed", total=value)


@pytest.mark.parametrize("status", ["missing", "suppressed"])
def test_nonobserved_cannot_carry_invented_zero(inputs, status):
    scope, expected, _ = inputs
    with pytest.raises(ValidationError):
        PopulationObservation(scope=scope, cell=expected[0], total_status=status, total=Decimal(0))


def test_hourly_total_cannot_overflow_existing_arithmetic_contract(inputs):
    scope, expected, rows = inputs
    huge = tuple(
        PopulationObservation(
            scope=scope, cell=r.cell, total_status="observed", total=Decimal("999999999999999")
        )
        for r in rows
    )
    with pytest.raises(ValueError, match="^population_components_invalid$"):
        assemble_population(scope, expected, huge)


@pytest.mark.parametrize("kind", ["whole_grid", "one_grid_hour"])
def test_another_grid_cannot_hide_an_omitted_grid_or_hour(inputs, kind):
    scope, expected, rows = inputs
    scope = scope.model_copy(update={"grid_ids": (*scope.grid_ids, "다사99999999")})
    if kind == "one_grid_hour":
        expected += tuple(
            c.model_copy(update={"grid_id": "다사99999999"})
            for c in expected
            if (c.source, c.hour) != ("short", 4)
        )
    rows = tuple(r.model_copy(update={"scope": scope}) for r in rows)
    with pytest.raises(ValueError, match="^population_components_invalid$"):
        assemble_population(scope, expected, rows)


def test_decimal_default_context_cannot_change_assembly(inputs, monkeypatch):
    scope, expected, rows = inputs
    values = tuple(
        PopulationObservation(
            scope=scope, cell=r.cell, total_status="observed", total=Decimal("10000.12345")
        )
        for r in rows
    )
    monkeypatch.setattr(DefaultContext, "Emax", 2)
    monkeypatch.setattr(DefaultContext, "Emin", -2)
    monkeypatch.setitem(DefaultContext.traps, Inexact, True)
    result = assemble_population(scope, expected, values)
    assert result.hours[0] == Decimal("60000.74070")
    assert result.summary.day_total == Decimal("720008.88840")


def test_scope_datetime_and_duplicate_grids_are_rejected_and_repr_hides_values(inputs):
    scope, expected, rows = inputs
    values = scope.model_dump()
    with pytest.raises(ValidationError):
        PopulationScope(**(values | {"observation_date": datetime(2026, 11, 7)}))
    with pytest.raises(ValidationError):
        PopulationScope(**(values | {"grid_ids": scope.grid_ids * 2}))
    assert repr(scope) == "PopulationScope()" and repr(rows[0]) == "PopulationObservation()"
    assert repr(expected[0]) == "PopulationCell()"
