"""Thin general-v2 projection over the shared analysis calculations."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.analysis_v2 import (
    AnalysisActivityQuery,
    AnalysisHistory,
    AnalysisNearby,
    AnalysisQuery,
    AnalysisRiskQuery,
    AnalysisSnapshot,
    AnalysisSnapshotQuery,
    AnalysisStore,
)
from app.schemas.common import ApiResponse
from app.schemas.market_activity import ActivityQuery, MarketActivity
from app.schemas.nearby import NearbyQuery
from app.schemas.risk import Risk, RiskQuery
from app.schemas.snapshot import SnapshotQuery
from app.schemas.stores import HistoryQuery
from app.services.market_activity import get_activity
from app.services.nearby import get_nearby
from app.services.risk import get_risk
from app.services.store_history import get_history
from app.services.store_snapshot import get_snapshot


def stores(values: list[Any], category: str | None = None) -> list[AnalysisStore]:
    result = []
    for row in values:
        raw = row.model_dump()
        if "store_status" in raw:
            raw["current_status"] = raw.pop("store_status")
        raw.setdefault("category", category)
        result.append(AnalysisStore.model_validate(raw))
    return result


def nearby(session: Session, query: AnalysisQuery) -> ApiResponse[AnalysisNearby]:
    old = get_nearby(session, query.legacy(NearbyQuery))
    assert old.data is not None
    return ApiResponse(
        data=AnalysisNearby.model_validate(
            {
                **old.data.model_dump(exclude={"markers"}),
                "markers": stores(old.data.markers, query.category),
            }
        ),
        meta=old.meta,
    )


def snapshot(session: Session, query: AnalysisSnapshotQuery) -> ApiResponse[AnalysisSnapshot]:
    old = get_snapshot(session, query.legacy(SnapshotQuery))
    assert old.data is not None
    return ApiResponse(
        data=AnalysisSnapshot.model_validate(
            {
                **old.data.model_dump(exclude={"stores"}),
                "stores": stores(old.data.stores, query.category),
            }
        ),
        meta=old.meta,
    )


def history(session: Session, query: HistoryQuery) -> ApiResponse[AnalysisHistory]:
    old = get_history(session, query)
    assert old.data is not None
    return ApiResponse(
        data=AnalysisHistory(
            total=old.data.total, stores=stores(old.data.stores), message=old.data.message
        ),
        meta=old.meta,
    )


def activity(session: Session, query: AnalysisActivityQuery) -> ApiResponse[MarketActivity]:
    return get_activity(session, query.legacy(ActivityQuery))


def risk(session: Session, query: AnalysisRiskQuery, settings: Settings) -> ApiResponse[Risk]:
    return get_risk(session, query.legacy(RiskQuery), settings)
