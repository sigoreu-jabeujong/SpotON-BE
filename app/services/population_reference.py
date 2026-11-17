"""Read one population snapshot; compare public subsets without global observation scans."""

import hashlib
import json
import re
from datetime import date
from typing import cast

from geoalchemy2 import Geography
from sqlalchemy import cast as sql_cast
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.population_public_subset import (
    MAX_GRIDS,
    MAX_ROWS,
    RULE_VERSION,
    PublicRow,
    assemble_public_subset,
)
from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import LivingGrid as G
from app.models import LivingGridVersion as GV
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V
from app.models import Store
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.population_reference import (
    SOURCES,
    PopulationReference,
    PopulationReferenceQuery,
    PublicScope,
    PublicSource,
    ReferenceReason,
    ReferenceStatus,
    Source,
)
from app.services.spatial_stores import effective_date
from app.services.store_cohort import current_provenance, temporal_cohort

FORMAT_VERSION = "population-public-subset-v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _counter(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("population_reference_metadata")
    return value


def _metadata(version: V, grid: GV) -> dict[Source, tuple[int, int]]:
    if (
        version.grid_version_id != grid.grid_version_id
        or grid.source_crs != 5179
        or version.spatial_compatibility != "unverified"
        or type(version.observation_date) is not date
        or (grid.grid_as_of is not None and type(grid.grid_as_of) is not date)
        or _counter(grid.row_count) == 0
        or _counter(version.row_count) == 0
        or not isinstance(version.sources, dict)
        or set(version.sources) != set(SOURCES)
        or any(
            not isinstance(h, str) or not _SHA.fullmatch(h)
            for h in (
                version.input_sha256,
                version.content_sha256,
                grid.input_sha256,
                grid.content_sha256,
            )
        )
    ):
        raise ValueError("population_reference_metadata")
    unlocated: dict[Source, tuple[int, int]] = {}
    total = 0
    for source in SOURCES:
        data = version.sources[source]
        if not isinstance(data, dict) or not isinstance(data.get("statuses"), dict):
            raise ValueError("population_reference_metadata")
        statuses = data["statuses"]
        if set(statuses) != {"observed", "suppressed", "missing"}:
            raise ValueError("population_reference_metadata")
        count = _counter(data.get("rows"))
        missing_rows, missing_grids = (
            _counter(data.get("unlocated_rows")),
            _counter(data.get("unlocated_grids")),
        )
        if sum(_counter(n) for n in statuses.values()) != count or not (
            missing_grids <= missing_rows <= count
        ):
            raise ValueError("population_reference_metadata")
        total += count
        unlocated[source] = missing_rows, missing_grids
    if total != version.row_count:
        raise ValueError("population_reference_metadata")
    return unlocated


def _response(
    query: PopulationReferenceQuery,
    target: date,
    observation: date | None,
    status: ReferenceStatus,
    *,
    version: V | None = None,
    grid: GV | None = None,
    sources: tuple[PublicSource, ...] = (),
) -> ApiResponse[PopulationReference]:
    reasons: dict[ReferenceStatus, ReferenceReason | None] = {
        "ready": None,
        "pending": "ambiguous_source_version",
        "no_data": "no_observation_in_period",
        "not_supported": "scope_too_large",
    }
    data = PopulationReference(
        status=status,
        reason=reasons[status],
        analysis_date=target,
        observation_date=observation,
        scope=PublicScope(
            radius_m=query.radius,
            category=query.category,
            sub_category=tuple(sorted(query.sub_category)),
            as_of=query.as_of,
            grid_as_of=None if grid is None else grid.grid_as_of,
        ),
        sources=sources,
    )
    metadata = {
        "format_version": FORMAT_VERSION,
        "rule_version": RULE_VERSION,
        "observation_version_id": str(version.version_id) if version is not None else None,
        "grid_version_id": str(grid.grid_version_id) if grid is not None else None,
        "input_sha256": version.input_sha256 if version is not None else None,
        "content_sha256": version.content_sha256 if version is not None else None,
        "grid_input_sha256": grid.input_sha256 if grid is not None else None,
        "grid_content_sha256": grid.content_sha256 if grid is not None else None,
        "source_validation_performed": False,
        "population_total_validated": False,
        "global_content_rechecked": False,
        "public_subset_calculation_performed": {
            s: any(block.source == s and block.status == "partial" for block in data.sources)
            for s in SOURCES
        },
        "source": ["R4"],
        "is_demo": False,
    }
    payload = {"data": data.model_dump(mode="json"), "metadata": metadata}
    token = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    return ApiResponse(
        data=data, meta=cast(ApiMeta, metadata | {"population_snapshot_token": token})
    )


def get_population_reference(
    session: Session, query: PopulationReferenceQuery
) -> ApiResponse[PopulationReference]:
    try:
        return _get_population_reference(session, query)
    except (ValueError, TypeError, OverflowError):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None


def _get_population_reference(
    session: Session, query: PopulationReferenceQuery
) -> ApiResponse[PopulationReference]:
    _batches, reference = current_provenance(session)
    minimum = session.scalar(
        select(func.min(Store.open_date)).where(*temporal_cohort(query, reference))
    )
    target = effective_date(reference, minimum, query.as_of)
    latest = session.scalar(
        select(func.max(V.observation_date)).where(
            V.observation_date >= target.replace(day=1), V.observation_date <= target
        )
    )
    if latest is None:
        return _response(query, target, None, "no_data")
    versions = list(session.scalars(select(V).where(V.observation_date == latest).limit(2)))
    if len(versions) != 1:
        return _response(query, target, latest, "pending")
    version = versions[0]
    grid = session.get(GV, version.grid_version_id)
    if grid is None:
        raise ValueError("population_reference_metadata")
    unlocated = _metadata(version, grid)
    geography = Geography(geometry_type=None, spatial_index=False)
    point = sql_cast(func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326), geography)
    center = sql_cast(
        func.ST_Transform(
            func.ST_SetSRID(func.ST_MakePoint(G.center_x, G.center_y), grid.source_crs), 4326
        ),
        geography,
    )
    selected = list(
        session.scalars(
            select(G.grid_id)
            .where(
                G.grid_version_id == grid.grid_version_id,
                func.ST_Distance(center, point, True) <= query.radius,
            )
            .limit(MAX_GRIDS + 1)
        )
    )
    if len(selected) > MAX_GRIDS:
        return _response(query, target, latest, "not_supported", version=version, grid=grid)
    if len(set(selected)) != len(selected):
        raise ValueError("population_reference_grids")
    records = (
        []
        if not selected
        else session.execute(
            select(
                O.source,
                O.grid_id,
                O.admin_code,
                O.hour,
                O.value_status,
                O.population,
                O.grid_version_id,
                O.observation_date,
                O.geometry_status,
                O.located_grid_id,
            )
            .where(O.version_id == version.version_id, O.located_grid_id.in_(selected))
            .limit(MAX_ROWS + 1)
        ).all()
    )
    if len(records) > MAX_ROWS:
        return _response(query, target, latest, "not_supported", version=version, grid=grid)
    rows: list[PublicRow] = []
    for row in records:
        if (
            row.source not in SOURCES
            or row.grid_version_id != grid.grid_version_id
            or row.observation_date != version.observation_date
            or row.geometry_status != "located"
            or row.located_grid_id != row.grid_id
        ):
            raise ValueError("population_reference_rows")
        rows.append(
            PublicRow(
                cast(Source, row.source),
                row.grid_id,
                row.admin_code,
                row.hour,
                row.value_status,
                row.population,
            )
        )
    sources = assemble_public_subset(
        frozenset(selected),
        tuple(rows),
        unlocated,
        grid_as_of_known=grid.grid_as_of is not None,
    )
    return _response(query, target, latest, "ready", version=version, grid=grid, sources=sources)
