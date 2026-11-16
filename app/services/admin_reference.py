"""Official local administrative totals, with independent actual dates and scopes."""

import hashlib
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Literal

from geoalchemy2 import Geography
from sqlalchemy import cast as sql_cast
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.day_night import calculate_day_night
from app.models.admin_population import AdminArea as A
from app.models.admin_population import AdminBoundaryVersion as B
from app.models.admin_population import AdminPopulationHour as H
from app.models.admin_population import AdminPopulationVersion as V
from app.schemas.location_reference import (
    AdminCatalog,
    AdminDayNightBlock,
    AdminDayNightItem,
    AdminPopulationBlock,
    AdminPopulationItem,
    LocationReferenceQuery,
    PopulationNumber,
    Reason,
    Status,
)

MAX_AREAS = 50
MAX_HOURS = 50_000


def _number(
    value: Decimal | None,
    unit: Literal["estimated_people_hourly_mean", "ratio", "pct_of_local_hourly_population"],
    places: int,
    reason: Literal["zero_night_population", "zero_population_total"] | None = None,
) -> PopulationNumber:
    if value is None:
        return PopulationNumber(
            value=None, display=None, unit=unit, rounded=False, exact_zero=False, reason=reason
        )
    if not value.is_finite() or value < 0:
        raise ValueError("invalid admin number")
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        shown = value.quantize(Decimal(1).scaleb(-places))
    suffix = (
        "명"
        if unit == "estimated_people_hourly_mean"
        else "%"
        if unit == "pct_of_local_hourly_population"
        else ""
    )
    return PopulationNumber(
        value=format(value, "f"),
        display=f"{shown:,.{places}f}{suffix}",
        unit=unit,
        rounded=shown != value,
        exact_zero=value.is_zero(),
    )


def _empty(
    status: Status, reason: Reason
) -> tuple[AdminPopulationBlock, AdminDayNightBlock, list[dict[str, object]]]:
    return (
        AdminPopulationBlock(status=status, reason=reason),
        AdminDayNightBlock(status=status, reason=reason),
        [],
    )


def get_admin_reference(
    session: Session,
    query: LocationReferenceQuery,
    target: date,
    catalog: AdminCatalog | None,
    today: date,
) -> tuple[AdminPopulationBlock, AdminDayNightBlock, list[dict[str, object]]]:
    if catalog is None:
        return _empty("pending", "population_source_not_released")
    bfp = catalog.boundary
    boundaries = list(
        session.scalars(
            select(B)
            .where(
                B.input_sha256 == bfp.input_sha256,
                B.rule_version == bfp.rule_version,
                B.code_system == catalog.code_system,
            )
            .limit(2)
        )
    )
    if not boundaries:
        return _empty("no_data", "source_not_loaded")
    if len(boundaries) != 1:
        return _empty("pending", "ambiguous_source_version")
    boundary = boundaries[0]
    if boundary.content_sha256 != bfp.content_sha256 or boundary.row_count != bfp.row_count:
        raise ValueError("admin boundary metadata")
    if (
        session.scalar(
            select(func.count()).select_from(A).where(A.boundary_version_id == boundary.version_id)
        )
        != boundary.row_count
    ):
        raise ValueError("admin boundary rows")
    allowed = sorted(
        (
            v
            for v in catalog.observations
            if v.observation_date <= today
            and (
                query.time_mode == "latest_reference"
                or target.replace(day=1) <= v.observation_date <= target
            )
        ),
        key=lambda v: v.observation_date,
        reverse=True,
    )
    if not allowed:
        return _empty("no_data", "no_data_in_analysis_period")
    versions = []
    for fp in allowed:
        candidates = list(
            session.scalars(
                select(V)
                .where(
                    V.boundary_version_id == boundary.version_id,
                    V.input_sha256 == fp.input_sha256,
                    V.rule_version == fp.rule_version,
                    V.observation_date == fp.observation_date,
                    V.source == "local",
                    V.code_system == catalog.code_system,
                )
                .limit(2)
            )
        )
        if not candidates:
            return _empty("no_data", "source_not_loaded")
        if len(candidates) != 1:
            return _empty("pending", "ambiguous_source_version")
        v = candidates[0]
        if (
            v.content_sha256 != fp.content_sha256
            or v.row_count != fp.row_count
            or v.source_series != catalog.source_series
            or session.scalar(
                select(func.count()).select_from(H).where(H.version_id == v.version_id)
            )
            != v.row_count
        ):
            raise ValueError("admin population metadata")
        versions.append(v)
    point = func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326)
    polygon = sql_cast(A.geom, Geography("MULTIPOLYGON", srid=4326))
    location = sql_cast(point, Geography("POINT", srid=4326))
    areas = list(
        session.execute(
            select(A.admin_code, A.admin_name, func.ST_Covers(A.geom, point).label("covers"))
            .where(
                A.boundary_version_id == boundary.version_id,
                func.ST_DWithin(polygon, location, query.radius + 0.01, True),
                func.ST_Distance(polygon, location, True) <= query.radius,
            )
            .order_by(A.admin_code)
            .limit(MAX_AREAS + 1)
        )
    )
    if len(areas) > MAX_AREAS:
        return _empty("not_supported", "scope_too_large")
    if not areas:
        return _empty("no_data", "no_spatial_overlap")
    hours = list(
        session.scalars(
            select(H)
            .where(
                H.version_id.in_([v.version_id for v in versions]),
                H.admin_code.in_([a.admin_code for a in areas]),
            )
            .limit(MAX_HOURS + 1)
        )
    )
    if len(hours) > MAX_HOURS:
        return _empty("not_supported", "scope_too_large")
    grouped: dict[tuple[object, str], dict[int, H]] = {}
    for row in hours:
        group = grouped.setdefault((row.version_id, row.admin_code), {})
        if row.hour in group:
            raise ValueError("duplicate admin hour")
        group[row.hour] = row
    local_items: list[AdminPopulationItem] = []
    comparisons: list[AdminDayNightItem] = []
    sources: list[dict[str, object]] = []
    for v in versions:
        sources.append(
            {
                "id": f"population-local-{v.observation_date}",
                "dataset": "OA-23016",
                "name": "행정동 내국인 생활인구",
                "url": v.source_url,
                "observation_date": v.observation_date.isoformat(),
                "source_month": v.observation_date.strftime("%Y%m"),
                "boundary_dataset": "OA-22160",
                "boundary_as_of": boundary.boundary_as_of.isoformat()
                if boundary.boundary_as_of
                else None,
                "boundary_period": "unverified",
                "population_scope": "local",
                "acquired_at": v.loaded_at.isoformat(),
                "published_at": None,
                "source_row_count": v.source_row_count,
                "excluded_rows": v.excluded_rows,
                "quality_scope": "source_day_all_admins",
                "boundary_without_observations": v.quality.get("boundary_without_observations"),
                "unmatched_code_count": v.quality.get("unmatched_code_count"),
                "source_series": v.source_series,
            }
        )
    for area in sorted(areas, key=lambda a: (not a.covers, a.admin_code)):
        selected = next(
            (
                v
                for v in versions
                if len(grouped.get((v.version_id, area.admin_code), {})) == 24
                and all(
                    r.value_status == "observed"
                    for r in grouped[(v.version_id, area.admin_code)].values()
                )
            ),
            versions[0],
        )
        values = grouped.get((selected.version_id, area.admin_code), {})
        observed = sum(r.value_status == "observed" for r in values.values())
        complete = len(values) == observed == 24 and set(values) == set(range(24))
        numbers = tuple(
            values[h].population if h in values and values[h].value_status == "observed" else None
            for h in range(24)
        )
        summary = calculate_day_night(numbers)
        with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
            mean = sum((n for n in numbers if n is not None), Decimal(0)) / 24 if complete else None
            # day_night's shares are already rounded for the legacy grid contract.
            # Preserve unrounded values and exact-zero semantics in this contract.
            total = (summary.day_total or Decimal(0)) + (summary.night_total or Decimal(0))
            day_share = (
                summary.day_total * 100 / total
                if complete and total and summary.day_total is not None
                else None
            )
            night_share = (
                summary.night_total * 100 / total
                if complete and total and summary.night_total is not None
                else None
            )
        ref = hashlib.sha256((boundary.content_sha256 + area.admin_code).encode()).hexdigest()
        provenance = f"population-local-{selected.observation_date}"
        reason: Reason | None = (
            None if complete else "no_complete_day" if values else "no_source_rows"
        )
        local_items.append(
            AdminPopulationItem(
                area_ref=ref,
                area_name=area.admin_name,
                spatial_relation="contains_point" if area.covers else "intersects_radius",
                observation_date=selected.observation_date,
                source_month=selected.observation_date.strftime("%Y%m"),
                temporal_relation=(
                    "same_period"
                    if selected.observation_date.year == target.year
                    and selected.observation_date.month == target.month
                    else "earlier_reference"
                    if selected.observation_date < target
                    else "later_reference"
                ),
                mean_24h=_number(mean, "estimated_people_hourly_mean", 1)
                if mean is not None
                else None,
                status="ready" if complete else "no_data",
                reason=reason,
                observed_hours=observed,
                source_hours=len(values),
                selection_reason="latest_complete_day"
                if query.time_mode == "latest_reference"
                else "analysis_period",
                provenance_ref=provenance,
            )
        )
        ratio_missing = complete and summary.day_night_ratio is None
        comparisons.append(
            AdminDayNightItem(
                area_ref=ref,
                observation_date=selected.observation_date,
                provenance_ref=provenance,
                mean_day=_number(summary.day_avg_population, "estimated_people_hourly_mean", 1)
                if complete
                else None,
                mean_night=_number(summary.night_avg_population, "estimated_people_hourly_mean", 1)
                if complete
                else None,
                day_night_ratio=_number(
                    summary.day_night_ratio,
                    "ratio",
                    5,
                    "zero_night_population" if ratio_missing else None,
                )
                if complete
                else None,
                day_share_pct=_number(
                    day_share,
                    "pct_of_local_hourly_population",
                    1,
                    "zero_population_total" if day_share is None else None,
                )
                if complete
                else None,
                night_share_pct=_number(
                    night_share,
                    "pct_of_local_hourly_population",
                    1,
                    "zero_population_total" if night_share is None else None,
                )
                if complete
                else None,
                status="no_data" if not complete else "partial" if ratio_missing else "ready",
                reason=reason
                if not complete
                else "zero_night_population"
                if ratio_missing
                else None,
            )
        )
    if any(i.spatial_relation == "contains_point" and i.status == "ready" for i in local_items):
        keep = {i.area_ref for i in local_items if i.spatial_relation == "contains_point"}
        local_items = [i for i in local_items if i.area_ref in keep]
        comparisons = [i for i in comparisons if i.area_ref in keep]
    ready = sum(i.status == "ready" for i in local_items)
    status: Status = "ready" if ready == len(local_items) else "partial" if ready else "no_data"
    why: Reason | None = (
        None if status == "ready" else "partial_source_rows" if ready else "no_complete_day"
    )
    day_status: Status = (
        "ready"
        if all(i.status == "ready" for i in comparisons)
        else "partial"
        if ready
        else "no_data"
    )
    day_reason: Reason | None = (
        None
        if day_status == "ready"
        else "zero_night_population"
        if ready == len(local_items)
        else "partial_source_rows"
        if ready
        else "no_complete_day"
    )
    return (
        AdminPopulationBlock(status=status, reason=why, items=tuple(local_items)),
        AdminDayNightBlock(
            status=day_status,
            reason=day_reason,
            items=tuple(comparisons),
        ),
        sources,
    )
