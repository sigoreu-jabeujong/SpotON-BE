"""v2 adapters share existing license cohorts and arithmetic, with an explicit filter."""

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Store
from app.models.store import STORE_GEOGRAPHY
from app.schemas.chains import (
    ChainActivityQuery,
    ChainBrand,
    ChainHistory,
    ChainNearby,
    ChainQuery,
    ChainRiskQuery,
    ChainSnapshot,
    ChainSnapshotQuery,
    ChainStore,
)
from app.schemas.common import ApiMeta, ApiResponse
from app.schemas.market_activity import ActivityQuery, MarketActivity
from app.schemas.nearby import NearbyQuery
from app.schemas.risk import Risk, RiskQuery
from app.schemas.snapshot import SnapshotQuery
from app.schemas.stores import HistoryQuery
from app.services.chains import ChainSelection
from app.services.market_activity import get_activity
from app.services.nearby import get_nearby
from app.services.risk import get_risk
from app.services.spatial_stores import PREFILTER_MARGIN_M, attribute_filters
from app.services.store_cohort import temporal_cohort
from app.services.store_history import get_history
from app.services.store_snapshot import get_snapshot


def metadata(session: Session, chain: ChainSelection, meta: ApiMeta, target: date) -> ApiMeta:
    result = dict(meta)
    result.pop("franchise_classification", None)
    version = result.get("data_version")
    if isinstance(version, dict):
        version.pop("brand_mapping", None)
    result["brand_classification"] = chain.meta()
    query = chain.query
    if query is not None:
        legacy = query.legacy(NearbyQuery)
        reference = date.fromisoformat(str(result["data_updated_at"]))
        point = cast(
            func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326), STORE_GEOGRAPHY
        )
        geography = cast(Store.geom, STORE_GEOGRAPHY)
        status = chain.count_status()
        rows = session.execute(
            select(status, func.count())
            .select_from(Store)
            .where(
                *temporal_cohort(legacy, reference),
                attribute_filters(legacy)[0],
                Store.open_date <= target,
                or_(Store.close_date.is_(None), Store.close_date > target),
                Store.geom.is_not(None),
                func.ST_DWithin(geography, point, query.radius + PREFILTER_MARGIN_M, True),
                func.ST_Distance(geography, point, True) <= query.radius,
            )
            .group_by(status)
        )
        counts: dict[str, int] = {str(key): int(value) for key, value in rows}
        result["brand_counts"] = {
            key: int(counts.get(key, 0))
            for key in ("estimated", "unknown", "conflict", "stale_or_drift")
        }
        result["brand_counts_scope"] = "active_at_as_of_located_before_brand_filter"
        result["brand_filters"] = query.echo_filters()
    return result


def stores(
    session: Session, chain: ChainSelection, values: list[Any], category: str | None = None
) -> list[ChainStore]:
    brands = chain.brands(session, [(v.source, v.license_no) for v in values])
    result = []
    for row in values:
        raw = row.model_dump(exclude={"franchise", "franchise_basis", "franchise_reference_year"})
        if "store_status" in raw:
            raw["current_status"] = raw.pop("store_status")
        raw.setdefault("category", category)
        raw["brand"] = brands.get(
            (row.source, row.license_no), ChainBrand(status="unknown", reason="no_evidence")
        )
        result.append(ChainStore.model_validate(raw))
    return result


def nearby(session: Session, query: ChainQuery) -> ApiResponse[ChainNearby]:
    chain = ChainSelection.load(session, query)
    old = get_nearby(session, query.legacy(NearbyQuery), chain=chain)
    assert old.data is not None
    data = old.data.model_dump(exclude={"markers"})
    data["markers"] = stores(session, chain, old.data.markers, query.category)
    return ApiResponse(
        data=ChainNearby.model_validate(data),
        meta=metadata(session, chain, old.meta, old.data.as_of),
    )


def snapshot(session: Session, query: ChainSnapshotQuery) -> ApiResponse[ChainSnapshot]:
    chain = ChainSelection.load(session, query)
    old = get_snapshot(session, query.legacy(SnapshotQuery), chain=chain)
    assert old.data is not None
    data = old.data.model_dump(exclude={"stores"})
    data["stores"] = stores(session, chain, old.data.stores, query.category)
    return ApiResponse(
        data=ChainSnapshot.model_validate(data),
        meta=metadata(session, chain, old.meta, old.data.as_of),
    )


def history(session: Session, query: HistoryQuery) -> ApiResponse[ChainHistory]:
    chain = ChainSelection.load(session)
    old = get_history(session, query, chain=chain)
    assert old.data is not None
    rows = stores(session, chain, old.data.stores)
    meta = dict(old.meta)
    meta["brand_classification"] = chain.meta()
    counts = Counter(
        "stale_or_drift"
        if row.brand.reason in {"source_drift", "stale_input"}
        else row.brand.status
        for row in rows
    )
    meta["brand_counts"] = {
        key: counts[key] for key in ("estimated", "unknown", "conflict", "stale_or_drift")
    }
    meta["brand_counts_scope"] = "returned_unfiltered_license_history"
    return ApiResponse(
        data=ChainHistory(total=len(rows), stores=rows, message=old.data.message), meta=meta
    )


def activity(session: Session, query: ChainActivityQuery) -> ApiResponse[MarketActivity]:
    chain = ChainSelection.load(session, query)
    old = get_activity(session, query.legacy(ActivityQuery), chain=chain)
    assert old.data is not None
    return ApiResponse(
        data=old.data,
        meta=metadata(session, chain, old.meta, date.fromisoformat(str(old.meta["as_of"]))),
    )


def risk(session: Session, query: ChainRiskQuery, settings: Settings) -> ApiResponse[Risk]:
    chain = ChainSelection.load(session, query)
    old = get_risk(session, query.legacy(RiskQuery), settings, chain=chain)
    assert old.data is not None
    old.data.query.filters = query.echo_filters()
    return ApiResponse(data=old.data, meta=metadata(session, chain, old.meta, old.data.query.as_of))
