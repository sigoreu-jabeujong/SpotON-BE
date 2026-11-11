"""API v1.2 §4-7 / work plan §7: spatial candidates, never temporal applicability."""

from collections.abc import Sequence

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import MarketArea, MarketAreaVersion
from app.schemas.common import ErrorCode
from app.schemas.market_judgement import (
    BoundaryJudgement,
    BoundaryProvenance,
    BoundaryQuery,
    MarketRef,
    SpatialJudgement,
)

DISTANCE_PREFILTER_MARGIN_M = 0.01


def classify_markets(
    covering: Sequence[MarketRef], nearby: Sequence[MarketRef] = ()
) -> SpatialJudgement:
    """Keep equal-priority overlaps ambiguous; code order never selects a winner."""
    if len({r.market_code for r in covering}) != len(covering):
        raise ValueError("duplicate covering market")
    if covering and nearby:
        raise ValueError("nearby is only for outside")
    details = sorted(
        (r for r in covering if r.market_type != "tourism_zone"), key=lambda r: r.market_code
    )
    zones = sorted(
        (r for r in covering if r.market_type == "tourism_zone"), key=lambda r: r.market_code
    )
    choices = details or zones
    return SpatialJudgement(
        spatial_status="outside"
        if not choices
        else "in_market"
        if len(choices) == 1
        else "ambiguous",
        primary=choices[0] if len(choices) == 1 else None,
        candidates=choices if len(choices) > 1 else [],
        also_in=zones if details else [],
        nearby_markets=sorted(nearby, key=lambda r: r.market_code),
    )


def judge_market(session: Session, query: BoundaryQuery) -> BoundaryJudgement:
    """Caller supplies one READ ONLY REPEATABLE READ transaction; no version fallback."""
    try:
        return _judge_market(session, query)
    except (SQLAlchemyError, ValueError, TypeError):
        pass
    # Raise outside except so a database exception with bound coordinates has no context.
    raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)


def _judge_market(session: Session, query: BoundaryQuery) -> BoundaryJudgement:
    version = session.get(MarketAreaVersion, query.version_id)
    if version is None:
        raise ValueError("boundary version unavailable")
    actual_count = session.scalar(
        select(func.count())
        .select_from(MarketArea)
        .where(MarketArea.version_id == query.version_id)
    )
    if not actual_count or actual_count != version.row_count:
        raise ValueError("incomplete boundary version")
    point = func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326)
    base = select(MarketArea.market_code, MarketArea.market_name, MarketArea.market_type).where(
        MarketArea.version_id == query.version_id
    )
    covering = [
        MarketRef(**row._mapping)
        for row in session.execute(base.where(func.ST_Covers(MarketArea.geom, point)))
    ]
    nearby: list[MarketRef] = []
    if not covering:
        polygon = cast(MarketArea.geom, Geography("MULTIPOLYGON", srid=4326))
        location = cast(point, Geography("POINT", srid=4326))
        nearby = [
            MarketRef(**row._mapping)
            for row in session.execute(
                base.where(
                    func.ST_DWithin(
                        polygon, location, query.radius + DISTANCE_PREFILTER_MARGIN_M, True
                    ),
                    func.ST_Distance(polygon, location, True) <= query.radius,
                )
            )
        ]
    judgement = classify_markets(covering, nearby)
    provenance = BoundaryProvenance(
        version_id=version.version_id,
        source_dataset=version.source_dataset,
        source_url=version.source_url,
        source_file_date=version.source_file_date,
        boundary_as_of=version.boundary_as_of,
        input_sha256=version.input_sha256,
        content_sha256=version.content_sha256,
        rule_version=version.rule_version,
    )
    return BoundaryJudgement(**judgement.model_dump(), provenance=provenance)
