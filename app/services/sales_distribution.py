"""Equal-reference median: not the median of individual merchant sales."""

from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from fractions import Fraction
from typing import Any


def ratio(value: Fraction) -> dict[str, Any]:
    if value < 0:
        raise ValueError("negative reference ratio")
    s, n = value.numerator, value.denominator
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        text = format(Decimal(s) / n, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    q, r = divmod(s, n)
    return dict(
        numerator=str(s),
        denominator=str(n),
        value=text,
        value_precision="decimal50",
        display="1원 미만/점포" if 0 < value < 1 else f"{q + (2 * r >= n):,}원/점포",
        unit="KRW_source_reported_per_store",
        rounded=r != 0,
        exact_zero=s == 0,
    )


def middle(values: list[Fraction]) -> Fraction:
    n = len(values)
    if not n:
        raise ValueError("empty reference median")
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def distribution(pairs: list[tuple[int, int]]) -> dict[str, Any] | None:
    if not pairs:
        return None
    if len(pairs) > 500 or any(
        type(s) is not int or type(n) is not int or not (0 <= s <= 2**63 - 1 and 0 < n <= 2**31 - 1)
        for s, n in pairs
    ):
        raise ValueError("invalid distribution inputs")
    values = sorted(Fraction(s, n) for s, n in pairs)
    count = len(values)
    median = middle(values)
    q1 = middle(values[: count // 2]) if count > 1 else median
    q3 = middle(values[(count + 1) // 2 :]) if count > 1 else median
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        deltas = [v - values[0] for v in values]
        numbers = [Decimal(v.numerator) / v.denominator for v in deltas]
        mean = sum(numbers, Decimal(0)) / count
        variance = sum(((v - mean) ** 2 for v in numbers), Decimal(0)) / count
        variance_text = format(variance, "f")
    return dict(
        method="median_of_reference_per_store_ratios_v1",
        sample_unit="market_industry_row",
        weighting="equal_reference_rows",
        sample_count=count,
        limited_reference_count=count < 4,
        individual_store_median=False,
        outliers_removed=False,
        quartile_method="median_of_halves_excluding_center_v1",
        median=ratio(median),
        q1=ratio(q1),
        q3=ratio(q3),
        iqr=ratio(q3 - q1),
        variance=dict(
            value=variance_text,
            value_precision="decimal50",
            definition="sum_squared_deviations_divided_by_reference_count",
            unit="KRW_source_reported_per_store_squared",
        ),
    )
