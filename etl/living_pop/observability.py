"""Read-only quality counters for one validated source day, without population sums."""

from collections.abc import Iterable
from itertools import groupby

from app.core.operations import population_quality
from etl.living_pop.data import Observation


def summarize(rows: Iterable[Observation]) -> dict[str, int]:
    counts = dict(
        suppressed_rows=0,
        missing_value_rows=0,
        observed_zero_rows=0,
        unlocated_rows=0,
        multi_admin_groups=0,
        multi_admin_rows=0,
    )
    previous: tuple[str, int] | None = None
    for key, block in groupby(rows, key=lambda row: (row.source, row.hour)):
        if previous is not None and key <= previous:
            raise ValueError("quality_input_order")
        previous = key
        # At most one source/hour block is retained; admin identity is used unchanged.
        grids: dict[str, tuple[str, int, bool]] = {}
        for row in block:
            counts["suppressed_rows"] += row.value_status == "suppressed"
            counts["missing_value_rows"] += row.value_status == "missing"
            counts["observed_zero_rows"] += row.value_status == "observed" and row.population == 0
            counts["unlocated_rows"] += not row.located
            first, size, multi = grids.get(row.grid_id, (row.admin_code, 0, False))
            grids[row.grid_id] = (first, size + 1, multi or row.admin_code != first)
        for _, size, multi in grids.values():
            if multi:
                counts["multi_admin_groups"] += 1
                counts["multi_admin_rows"] += size
    return counts


def record_quality(rows: Iterable[Observation]) -> None:
    try:
        counts = summarize(rows)
    except Exception:
        population_quality(None)
    else:
        population_quality(counts)
