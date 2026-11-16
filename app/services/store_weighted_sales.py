"""Estimated weighted distribution of market means, not observed individual sales."""

from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from fractions import Fraction
from typing import Any

from app.services.sales_distribution import ratio


def store_weighted_distribution(pairs: list[tuple[int, int]]) -> dict[str, Any] | None:
    if not pairs:
        return None
    if len(pairs) > 500 or any(
        type(s) is not int or type(n) is not int or not (0 <= s <= 2**63 - 1 and 0 < n <= 2**31 - 1)
        for s, n in pairs
    ):
        raise ValueError("invalid weighted distribution inputs")
    values = sorted((Fraction(s, n), n) for s, n in pairs)
    count = sum(n for _, n in values)

    def at_rank(rank: int) -> Fraction:
        accumulated = 0
        for value, weight in values:
            accumulated += weight
            if accumulated >= rank:
                return value
        raise ValueError("invalid weighted rank")

    median = (
        at_rank(count // 2 + 1)
        if count % 2
        else (at_rank(count // 2) + at_rank(count // 2 + 1)) / 2
    )
    mean = Fraction(sum(s for s, _ in pairs), count)
    minimum, maximum = values[0][0], values[-1][0]
    bin_count = min(10, len({v for v, _ in values}))
    width = (maximum - minimum) / bin_count
    counts = [0] * bin_count
    for value, weight in values:
        index = min(bin_count - 1, int((value - minimum) // width)) if width else 0
        counts[index] += weight
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        variance = Decimal(0)
        for value, weight in values:
            delta = value - mean
            variance += (Decimal(delta.numerator) / delta.denominator) ** 2 * weight
        variance_text = format(variance / count, "f")
    return dict(
        method="store_weighted_median_v1",
        model="repeat_market_mean_for_each_reference_store",
        individual_store_sales_observed=False,
        total_store_count=str(count),
        reference_count=len(pairs),
        median=ratio(median),
        mean=ratio(mean),
        minimum=ratio(minimum),
        maximum=ratio(maximum),
        variance=dict(
            value=variance_text,
            value_precision="decimal50",
            unit="KRW_source_reported_per_store_squared",
            scope="between_market_per_store_means",
        ),
        bin_method="equal_width_exact_fraction_v1",
        bins=[
            dict(
                lower=ratio(minimum + width * index),
                upper=ratio(minimum + width * (index + 1)),
                store_count=str(weight),
                upper_inclusive=index == bin_count - 1,
            )
            for index, weight in enumerate(counts)
        ],
    )
