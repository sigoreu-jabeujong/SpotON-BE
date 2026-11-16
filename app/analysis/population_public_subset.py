"""Compare the same public row components across 24 hours, independently per source."""

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.analysis.day_night import DAY_HOURS, calculate_day_night
from app.schemas.population_reference import (
    SOURCES,
    ExcludedHours,
    Limitation,
    PublicNumber,
    PublicQuality,
    PublicSource,
    PublicSourceReason,
    PublicValues,
    Source,
    Unit,
)

RULE_VERSION = "population-public-fixed-components-v1"
MAX_GRIDS = 1000
MAX_ROWS = 100_000
SCALE = 100_000
HOUR_LIMIT = 10**20  # 1e15, expressed in exact source units of 1e-5.
_GRID = re.compile(r"^[가-힣]{2}[0-9]{8}$")
_ADMIN = re.compile(r"^11[0-9]{6}$")


@dataclass(frozen=True, repr=False)
class PublicRow:
    source: Source
    grid_id: str
    admin_code: str
    hour: int
    status: str
    population: Decimal | None


def _invalid() -> None:
    raise ValueError("population_public_subset_invalid")


def _units(value: Decimal | None) -> int:
    if type(value) is not Decimal or not value.is_finite() or value < 0 or value >= Decimal("1e15"):
        _invalid()
    assert isinstance(value, Decimal)
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -5:
        _invalid()
    n, d = value.as_integer_ratio()
    units, remainder = divmod(n * SCALE, d)
    if remainder:
        _invalid()
    return units


def _decimal(units: int) -> Decimal:
    return Decimal(f"{units // SCALE}.{units % SCALE:05d}")


def _number(
    n: int, d: int, places: int, unit: Unit, *, complement: int | None = None
) -> PublicNumber:
    if d == 0:
        return PublicNumber(
            value=None,
            display=None,
            exact_zero=None,
            rounded=None,
            unit=unit,
            reason="zero_night_denominator" if unit == "ratio" else "zero_total",
        )
    scaled, remainder = divmod(n * 10**places, d)
    scaled += int(2 * remainder >= d)
    if complement is not None:
        scaled = complement
    whole, fraction = divmod(scaled, 10**places)
    value = f"{whole}.{fraction:0{places}d}"
    suffix = "%" if unit == "pct_of_public_subset" else "배" if unit == "ratio" else ""
    return PublicNumber(
        value=value,
        display=f"{whole:,}.{fraction:0{places}d}{suffix}",
        exact_zero=n == 0,
        rounded=remainder != 0,
        unit=unit,
    )


def _values(hours: list[int]) -> PublicValues:
    # Retain the independently tested pure arithmetic; presentation uses exact rationals.
    summary = calculate_day_night(tuple(_decimal(h) for h in hours))
    day = sum(hours[h] for h in DAY_HOURS)
    night = sum(hours[h] for h in range(24) if h not in DAY_HOURS)
    if summary.day_total != _decimal(day) or summary.night_total != _decimal(night):
        _invalid()
    share = _number(day * 100, day + night, 1, "pct_of_public_subset")
    share_units = None if share.value is None else int(share.value.replace(".", ""))
    return PublicValues(
        hourly_source_sums=tuple(_number(h, SCALE, 5, "public_source_value_sum") for h in hours),
        day_source_sum=_number(day, SCALE, 5, "public_source_value_sum"),
        night_source_sum=_number(night, SCALE, 5, "public_source_value_sum"),
        day_source_mean=_number(day, 12 * SCALE, 5, "public_source_value_hourly_mean"),
        night_source_mean=_number(night, 12 * SCALE, 5, "public_source_value_hourly_mean"),
        day_share_pct=share,
        night_share_pct=_number(
            night * 100,
            day + night,
            1,
            "pct_of_public_subset",
            complement=None if share_units is None else 1000 - share_units,
        ),
        day_night_ratio=_number(day, night, 5, "ratio"),
    )


def assemble_public_subset(
    grid_ids: frozenset[str],
    rows: tuple[PublicRow, ...],
    unlocated: dict[Source, tuple[int, int]],
    *,
    grid_as_of_known: bool,
) -> tuple[PublicSource, ...]:
    if (
        type(grid_ids) is not frozenset
        or len(grid_ids) > MAX_GRIDS
        or any(type(g) is not str or not _GRID.fullmatch(g) for g in grid_ids)
        or type(rows) is not tuple
        or len(rows) > MAX_ROWS
        or set(unlocated) != set(SOURCES)
    ):
        _invalid()
    grouped: dict[Source, dict[tuple[str, str], dict[int, int | None]]] = {
        s: defaultdict(dict) for s in SOURCES
    }
    counts = {s: {"observed": 0, "suppressed": 0, "missing": 0} for s in SOURCES}
    for row in rows:
        if (
            type(row) is not PublicRow
            or row.source not in SOURCES
            or row.grid_id not in grid_ids
            or not _ADMIN.fullmatch(row.admin_code)
            or type(row.hour) is not int
            or not 0 <= row.hour < 24
            or row.status not in {"observed", "suppressed", "missing"}
        ):
            _invalid()
        component = grouped[row.source][row.grid_id, row.admin_code]
        if row.hour in component:
            _invalid()
        if row.status == "observed":
            component[row.hour] = _units(row.population)
        else:
            if row.population is not None:
                _invalid()
            component[row.hour] = None
        counts[row.source][row.status] += 1
    result: list[PublicSource] = []
    for source in SOURCES:
        candidates = grouped[source]
        hours = [0] * 24
        used_grids: set[str] = set()
        used = day_only = night_only = both = 0
        for (grid_id, _admin), component in candidates.items():
            unavailable = {h for h in range(24) if component.get(h) is None}
            if unavailable:
                has_day = bool(unavailable.intersection(DAY_HOURS))
                has_night = bool(unavailable.difference(DAY_HOURS))
                day_only += has_day and not has_night
                night_only += has_night and not has_day
                both += has_day and has_night
                continue
            used += 1
            used_grids.add(grid_id)
            for h in range(24):
                value = component[h]
                assert value is not None
                hours[h] += value
        counter = counts[source]
        grids_with_rows = len({g for g, _ in candidates})
        global_rows, global_grids = unlocated[source]
        quality = PublicQuality(
            selected_grid_count=len(grid_ids),
            grids_with_rows=grids_with_rows,
            grids_without_rows=len(grid_ids) - grids_with_rows,
            candidate_component_count=len(candidates),
            used_component_count=used,
            excluded_component_count=len(candidates) - used,
            used_grid_count=len(used_grids),
            observed_rows=counter["observed"],
            suppressed_rows=counter["suppressed"],
            missing_rows=counter["missing"],
            absent_hours_within_candidates=24 * len(candidates) - sum(counter.values()),
            excluded_by_hour_class=ExcludedHours(
                day_only=day_only, night_only=night_only, both=both
            ),
            version_unlocated_rows=global_rows,
            version_unlocated_grids=global_grids,
        )
        limitations: list[Limitation] = [
            "not_population_total",
            "admin_additivity_unverified",
            "grid_period_unverified",
            "hour_sums_not_unique_people",
        ]
        if day_only or night_only:
            limitations.append("exclusion_pattern_may_bias_ratio")
        if not grid_as_of_known:
            limitations.append("grid_as_of_unknown")
        reason: PublicSourceReason = (
            "no_selected_grids"
            if not grid_ids
            else "no_source_rows"
            if not candidates
            else "no_common_public_components"
            if not used
            else "numeric_scope_too_large"
            if max(hours) >= HOUR_LIMIT
            else "public_subset_only"
        )
        result.append(
            PublicSource(
                source=source,
                status="partial"
                if reason == "public_subset_only"
                else "not_supported"
                if reason == "numeric_scope_too_large"
                else "no_data",
                reason=reason,
                values=_values(hours) if reason == "public_subset_only" else None,
                quality=quality,
                limitations=tuple(sorted(limitations)),
            )
        )
    return tuple(result)
