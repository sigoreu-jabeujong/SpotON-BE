"""Counts of stored rows only; no demographic aggregation or readiness judgement."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from geoalchemy2 import Geography
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.models import LivingGrid as G
from app.models import LivingGridVersion as GV
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V

Source = Literal["local", "long", "short"]
SOURCES: tuple[Source, ...] = ("local", "long", "short")
Count = Annotated[int, Field(ge=0)]
RULE_VERSION = "population-quality-counts-v1"
LIMITATIONS = (
    "diagnostic_row_counts_only",
    "no_demographic_sums_or_readiness_rates",
    "absent_rows_do_not_mean_zero_people",
    "admin_component_meaning_unverified",
    "unlocated_rows_cannot_be_assigned_to_radius",
    "grid_observation_time_compatibility_unverified",
    "content_hash_not_rechecked",
)


class QualityError(ValueError):
    def __init__(self, reason: Literal["arguments", "version", "counts"]) -> None:
        super().__init__("living_pop_quality:" + reason)


class QualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class QualityQuery(QualityModel):
    observation_version_id: UUID
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False, repr=False)
    radius: Literal[300, 500, 1000] = 500


class HourCounts(QualityModel):
    source: Source
    hour: int = Field(ge=0, le=23)
    rows: Count
    observed_zero: Count
    observed_nonzero: Count
    suppressed: Count
    missing: Count
    grids_with_rows: Count
    grids_without_rows: Count
    grids_with_nonobserved_rows: Count
    grids_with_multi_admin_rows: Count


class UnlocatedCounts(QualityModel):
    source: Source
    rows: Count
    grids: Count
    scope: Literal["observation_version_global"] = "observation_version_global"


class QualityReport(QualityModel):
    rule_version: str = RULE_VERSION
    observation_version_id: UUID
    grid_version_id: UUID
    observation_date: date
    grid_as_of: date | None
    spatial_compatibility: Literal["unverified"]
    selection_basis: Literal["source_center_5179_spheroid_distance_le_radius"] = (
        "source_center_5179_spheroid_distance_le_radius"
    )
    radius_m: Literal[300, 500, 1000]
    selected_grid_count: Count
    stored_counts_match_metadata: Literal[True] = True
    content_hash_rechecked: Literal[False] = False
    hours: tuple[HourCounts, ...]
    unlocated: tuple[UnlocatedCounts, ...]
    limitations: tuple[str, ...] = LIMITATIONS


@dataclass(frozen=True, repr=False)
class GridHourCounts:
    source: str
    hour: int
    grid_id: str
    rows: int
    observed_zero: int
    observed_nonzero: int
    suppressed: int
    missing: int
    admins: int


def summarize(grid_count: int, groups: Iterable[GridHourCounts]) -> tuple[HourCounts, ...]:
    if type(grid_count) is not int or grid_count < 0:
        raise QualityError("counts")
    buckets: dict[tuple[str, int], list[GridHourCounts]] = {}
    seen: set[tuple[str, int, str]] = set()
    for group in groups:
        values = (
            group.rows,
            group.observed_zero,
            group.observed_nonzero,
            group.suppressed,
            group.missing,
            group.admins,
        )
        identity = (group.source, group.hour, group.grid_id)
        if (
            group.source not in SOURCES
            or type(group.hour) is not int
            or not 0 <= group.hour < 24
            or identity in seen
            or not group.grid_id
            or any(type(n) is not int or n < 0 for n in values)
            or group.rows < 1
            or not 1 <= group.admins <= group.rows
            or sum(values[1:5]) != group.rows
        ):
            raise QualityError("counts")
        seen.add(identity)
        buckets.setdefault((group.source, group.hour), []).append(group)
    result = []
    for source in SOURCES:
        for hour in range(24):
            rows = buckets.get((source, hour), [])
            if len(rows) > grid_count:
                raise QualityError("counts")
            result.append(
                HourCounts(
                    source=source,
                    hour=hour,
                    rows=sum(r.rows for r in rows),
                    observed_zero=sum(r.observed_zero for r in rows),
                    observed_nonzero=sum(r.observed_nonzero for r in rows),
                    suppressed=sum(r.suppressed for r in rows),
                    missing=sum(r.missing for r in rows),
                    grids_with_rows=len(rows),
                    grids_without_rows=grid_count - len(rows),
                    grids_with_nonobserved_rows=sum(r.suppressed + r.missing > 0 for r in rows),
                    grids_with_multi_admin_rows=sum(r.admins > 1 for r in rows),
                )
            )
    return tuple(result)


def _counter(value: object) -> int:
    if type(value) is not int or value < 0:
        raise QualityError("counts")
    return value


def diagnose(session: Session, query: QualityQuery) -> QualityReport:
    version = session.get(V, query.observation_version_id)
    if version is None:
        raise QualityError("version")
    grid = session.get(GV, version.grid_version_id)
    if grid is None or grid.source_crs != 5179 or version.spatial_compatibility != "unverified":
        raise QualityError("version")
    if (
        session.scalar(
            select(func.count()).select_from(G).where(G.grid_version_id == grid.grid_version_id)
        )
        != grid.row_count
    ):
        raise QualityError("counts")
    global_rows = (
        session.execute(
            select(
                O.source,
                func.count().label("rows"),
                func.count().filter(O.value_status == "observed").label("observed"),
                func.count().filter(O.value_status == "suppressed").label("suppressed"),
                func.count().filter(O.value_status == "missing").label("missing"),
                func.count().filter(O.geometry_status == "unlocated").label("unlocated_rows"),
                func.count(func.distinct(O.grid_id))
                .filter(O.geometry_status == "unlocated")
                .label("unlocated_grids"),
            )
            .where(O.version_id == version.version_id, O.grid_version_id == grid.grid_version_id)
            .group_by(O.source)
        )
        .mappings()
        .all()
    )
    actual = {r["source"]: r for r in global_rows}
    if (
        set(actual) != set(SOURCES)
        or set(version.sources) != set(SOURCES)
        or sum(r["rows"] for r in global_rows) != version.row_count
    ):
        raise QualityError("counts")
    for source in SOURCES:
        meta = version.sources[source]
        if not isinstance(meta, dict) or not isinstance(meta.get("statuses"), dict):
            raise QualityError("counts")
        if set(meta["statuses"]) != {"observed", "suppressed", "missing"}:
            raise QualityError("counts")
        expected = {k: _counter(meta.get(k)) for k in ("rows", "unlocated_rows", "unlocated_grids")}
        expected.update({k: _counter(meta["statuses"].get(k)) for k in meta["statuses"]})
        if any(actual[source][k] != n for k, n in expected.items()):
            raise QualityError("counts")
    geography = Geography(geometry_type=None, spatial_index=False)
    point = cast(func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326), geography)
    center = cast(
        func.ST_Transform(
            func.ST_SetSRID(func.ST_MakePoint(G.center_x, G.center_y), grid.source_crs), 4326
        ),
        geography,
    )
    selected = list(
        session.scalars(
            select(G.grid_id).where(
                G.grid_version_id == grid.grid_version_id,
                func.ST_Distance(center, point, True) <= query.radius,
            )
        )
    )
    groups = []
    if selected:
        rows = session.execute(
            select(
                O.source,
                O.hour,
                O.located_grid_id,
                func.count().label("rows"),
                func.count()
                .filter((O.value_status == "observed") & (O.population == 0))
                .label("zero"),
                func.count()
                .filter((O.value_status == "observed") & (O.population > 0))
                .label("nonzero"),
                func.count().filter(O.value_status == "suppressed").label("suppressed"),
                func.count().filter(O.value_status == "missing").label("missing"),
                func.count(func.distinct(O.admin_code)).label("admins"),
            )
            .where(
                O.version_id == version.version_id,
                O.grid_version_id == grid.grid_version_id,
                O.located_grid_id.in_(selected),
                O.geometry_status == "located",
            )
            .group_by(O.source, O.hour, O.located_grid_id)
        ).all()
        groups = [
            GridHourCounts(
                r.source,
                r.hour,
                r.located_grid_id,
                r.rows,
                r.zero,
                r.nonzero,
                r.suppressed,
                r.missing,
                r.admins,
            )
            for r in rows
        ]
    return QualityReport(
        observation_version_id=version.version_id,
        grid_version_id=grid.grid_version_id,
        observation_date=version.observation_date,
        grid_as_of=grid.grid_as_of,
        spatial_compatibility="unverified",
        radius_m=query.radius,
        selected_grid_count=len(selected),
        hours=summarize(len(selected), groups),
        unlocated=tuple(
            UnlocatedCounts(
                source=s, rows=actual[s]["unlocated_rows"], grids=actual[s]["unlocated_grids"]
            )
            for s in SOURCES
        ),
    )
