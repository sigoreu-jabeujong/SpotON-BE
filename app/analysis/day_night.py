"""Internal arithmetic for 24 eligible hourly totals, never a source validation.

The caller must establish the same date, space and population for every hour,
preserve source states, and pass None for an ineligible total without substituting
zero. This module does not establish completeness or handle raw observations.
``calculated`` means arithmetic succeeded, not that the source is verified.

Totals combine hourly estimates; they are not unique daily visitor counts.
Shares are rounded for display, so 0.0% need not mean an exact zero. Averages and
the ratio use a 50-digit Decimal context; consumers choose their display format.
"""

from dataclasses import dataclass
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Literal

DAY_HOURS = tuple(range(6, 18))
NIGHT_HOURS = tuple(range(6)) + tuple(range(18, 24))
_ZERO = Decimal("0")
_INPUT_LIMIT = Decimal("1e15")


@dataclass(frozen=True, repr=False)
class DayNightSummary:
    status: Literal["calculated", "incomplete", "zero_total"]
    unavailable_hours: tuple[int, ...] = ()
    day_total: Decimal | None = None
    night_total: Decimal | None = None
    day_avg_population: Decimal | None = None
    night_avg_population: Decimal | None = None
    day_share_pct: Decimal | None = None
    night_share_pct: Decimal | None = None
    day_night_ratio: Decimal | None = None


def calculate_day_night(hours: tuple[Decimal | None, ...]) -> DayNightSummary:
    """Use SpotON's 06:00 <= hour < 18:00 day within one observation date.

    Input totals must fit Numeric(20,5), with at most five decimal places in
    their representation. None retains ineligibility, not its upstream cause.
    Incomplete input yields no numeric outputs; invalid input always raises a
    fixed error, even if another hour is None. A zero night leaves the ratio
    undefined, including when status is calculated and the shares are 100/0.
    """
    if type(hours) is not tuple or len(hours) != 24:
        raise ValueError("population_hours_invalid")
    unavailable = []
    for hour, value in enumerate(hours):
        if value is None:
            unavailable.append(hour)
            continue
        if (
            type(value) is not Decimal
            or not value.is_finite()
            or value < _ZERO
            or value >= _INPUT_LIMIT
        ):
            raise ValueError("population_hours_invalid")
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -5:
            raise ValueError("population_hours_invalid")
    if unavailable:
        return DayNightSummary(status="incomplete", unavailable_hours=tuple(unavailable))

    # None was handled above; canonicalize signed zeros without changing input.
    values = tuple(
        value.copy_abs() if value.is_zero() else value for value in hours if value is not None
    )
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
        day = sum((values[hour] for hour in DAY_HOURS), _ZERO)
        night = sum((values[hour] for hour in NIGHT_HOURS), _ZERO)
        total = day + night
        share = (
            (day * 100 / total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if total else None
        )
        return DayNightSummary(
            status="calculated" if total else "zero_total",
            day_total=day,
            night_total=night,
            day_avg_population=day / 12,
            night_avg_population=night / 12,
            day_share_pct=share,
            night_share_pct=Decimal("100.0") - share if share is not None else None,
            day_night_ratio=day / night if night else None,
        )
