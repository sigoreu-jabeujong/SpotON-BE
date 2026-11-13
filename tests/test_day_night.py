from dataclasses import FrozenInstanceError, fields
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Decimal,
    Inexact,
    Rounded,
    getcontext,
    localcontext,
)

import pytest

from app.analysis.day_night import DAY_HOURS, NIGHT_HOURS, calculate_day_night


def series(day="2", night="1"):
    return tuple(Decimal(day if 6 <= hour < 18 else night) for hour in range(24))


def test_eligible_totals_produce_distinct_shares_means_and_ratio():
    result = calculate_day_night(series())
    assert result.status == "calculated"
    assert result.unavailable_hours == ()
    assert (result.day_total, result.night_total) == (Decimal(24), Decimal(12))
    assert (result.day_avg_population, result.night_avg_population) == (Decimal(2), Decimal(1))
    assert (result.day_share_pct, result.night_share_pct) == (Decimal("66.7"), Decimal("33.3"))
    assert result.day_night_ratio == Decimal(2)


@pytest.mark.parametrize("hour", range(24))
def test_every_hour_belongs_to_exactly_one_of_two_twelve_hour_windows(hour):
    assert set(DAY_HOURS).isdisjoint(NIGHT_HOURS)
    assert set(DAY_HOURS) | set(NIGHT_HOURS) == set(range(24))
    assert len(DAY_HOURS) == len(NIGHT_HOURS) == 12
    values = [Decimal(0)] * 24
    values[hour] = Decimal(1)
    result = calculate_day_night(tuple(values))
    expected_day = Decimal(1 if 6 <= hour < 18 else 0)
    assert (result.day_total, result.night_total) == (expected_day, 1 - expected_day)


@pytest.mark.parametrize("day,night,share", [("1", "1999", "0.1"), ("5", "1995", "0.3")])
def test_half_up_ties_and_complement_ignore_global_precision_and_rounding(day, night, share):
    values = [Decimal(0)] * 24
    values[6], values[0] = Decimal(day), Decimal(night)
    with localcontext() as outer:
        outer.prec = 3
        outer.rounding = ROUND_HALF_EVEN
        outer.traps[Inexact] = outer.traps[Rounded] = True
        outer.Emax, outer.Emin, outer.clamp = 2, -2, 1
        before = outer.copy()
        result = calculate_day_night(tuple(values))
        assert getcontext() is outer
        assert outer.prec == before.prec and outer.rounding == before.rounding
        assert (outer.Emax, outer.Emin, outer.clamp) == (2, -2, 1)
        assert outer.traps == before.traps and outer.flags == before.flags
    assert result.day_share_pct == Decimal(share)
    assert result.day_share_pct + result.night_share_pct == Decimal("100.0")


def test_maximum_input_totals_are_exact_before_display_rounding():
    result = calculate_day_night((Decimal("999999999999999.99999"),) * 24)
    assert result.day_total == result.night_total == Decimal("11999999999999999.99988")
    assert result.day_avg_population == Decimal("999999999999999.99999")
    assert result.day_share_pct == result.night_share_pct == Decimal("50.0")
    assert result.day_night_ratio == 1


def test_small_positive_hour_is_not_rounded_to_zero_before_calculation():
    values = [Decimal(0)] * 24
    values[6] = Decimal("0.00001")
    result = calculate_day_night(tuple(values))
    assert result.day_total == Decimal("0.00001")
    assert Decimal(0) < result.day_avg_population < Decimal("0.00001")
    assert result.day_share_pct == Decimal("100.0")


def test_display_zero_percent_does_not_erase_a_positive_total():
    values = [Decimal(0)] * 24
    values[6], values[0] = Decimal("0.00001"), Decimal("1000")
    result = calculate_day_night(tuple(values))
    assert result.day_share_pct == Decimal("0.0")
    assert result.day_total > 0 and result.day_night_ratio > 0


def test_display_zero_night_percent_does_not_make_positive_night_ratio_undefined():
    values = [Decimal(0)] * 24
    values[6], values[0] = Decimal("1000"), Decimal("0.00001")
    result = calculate_day_night(tuple(values))
    assert result.status == "calculated"
    assert result.day_share_pct == Decimal("100.0")
    assert result.night_share_pct == Decimal("0.0")
    assert result.night_total == Decimal("0.00001")
    assert result.day_night_ratio == Decimal("100000000")


@pytest.mark.parametrize("unavailable", [(3,), (6, 18), tuple(range(24))])
def test_ineligible_hours_return_all_reasons_positions_without_any_partial_total(unavailable):
    values = list(series())
    for hour in unavailable:
        values[hour] = None
    original = tuple(values)
    result = calculate_day_night(original)
    assert result.status == "incomplete" and result.unavailable_hours == unavailable
    assert all(
        getattr(result, field.name) is None
        for field in fields(result)
        if field.name not in {"status", "unavailable_hours"}
    )


@pytest.mark.parametrize(
    "day,night,status,day_share,night_share,ratio",
    [
        ("0", "0", "zero_total", None, None, None),
        ("2", "0", "calculated", "100.0", "0.0", None),
        ("0", "3", "calculated", "0.0", "100.0", "0"),
    ],
)
def test_zero_total_and_zero_night_have_different_meaning(
    day, night, status, day_share, night_share, ratio
):
    result = calculate_day_night(series(day, night))
    assert result.status == status
    assert result.day_avg_population == Decimal(day)
    assert result.night_avg_population == Decimal(night)
    assert result.day_share_pct == (Decimal(day_share) if day_share is not None else None)
    assert result.night_share_pct == (Decimal(night_share) if night_share is not None else None)
    assert result.day_night_ratio == (Decimal(ratio) if ratio is not None else None)


def test_signed_zero_is_canonicalized_without_mutating_input():
    values = (Decimal("-0.00000"),) * 24
    result = calculate_day_night(values)
    assert result.status == "zero_total"
    assert not result.day_total.is_signed() and not result.night_avg_population.is_signed()
    assert all(value.is_signed() for value in values)


def test_positive_decimal_exponent_is_allowed_within_numeric_range():
    result = calculate_day_night((Decimal("1E+3"),) * 24)
    assert result.day_avg_population == result.night_avg_population == Decimal(1000)


class DecimalSubclass(Decimal):
    pass


@pytest.mark.parametrize(
    "invalid",
    [
        True,
        1,
        1.25,
        "1.25",
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("1E+15"),
        Decimal("0.000001"),
        Decimal("1.000000"),
        DecimalSubclass("1"),
    ],
)
def test_invalid_values_are_rejected_even_when_another_hour_is_ineligible(invalid):
    values = list(series())
    values[0], values[23] = None, invalid
    with localcontext() as outer:
        outer.prec, outer.rounding = 2, ROUND_DOWN
        before = outer.copy()
        with pytest.raises(ValueError, match="^population_hours_invalid$") as caught:
            calculate_day_night(tuple(values))
        assert caught.value.__context__ is None
        assert outer.prec == before.prec and outer.rounding == before.rounding
        assert outer.flags == before.flags


@pytest.mark.parametrize(
    "invalid", [(), (Decimal(1),) * 23, (Decimal(1),) * 25, [Decimal(1)] * 24, None]
)
def test_wrong_container_or_hour_count_is_rejected(invalid):
    with pytest.raises(ValueError, match="^population_hours_invalid$"):
        calculate_day_night(invalid)


def test_result_is_frozen_and_its_representation_contains_no_values():
    result = calculate_day_night(series("137.12345", "91.23456"))
    with pytest.raises(FrozenInstanceError):
        result.status = "incomplete"
    for representation in (repr(result), str(result)):
        assert "137.12345" not in representation and "91.23456" not in representation
        assert "day_total" not in representation and "share_pct" not in representation
