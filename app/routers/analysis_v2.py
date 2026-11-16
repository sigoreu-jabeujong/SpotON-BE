"""General v2 analysis contract. Invalid input is rejected before a DB session."""

from collections.abc import Iterator
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session, read_only_session
from app.routers.spatial_query import PARAMETERS
from app.routers.stores import history_query, validated_session
from app.schemas.analysis_v2 import (
    AnalysisActivityQuery,
    AnalysisHistory,
    AnalysisNearby,
    AnalysisQuery,
    AnalysisRiskQuery,
    AnalysisSnapshot,
    AnalysisSnapshotQuery,
)
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.location_history import LocationHistory, LocationHistoryQuery
from app.schemas.market_activity import MarketActivity
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.schemas.risk import Risk
from app.schemas.stores import HistoryQuery
from app.services import analysis_v2
from app.services.location_history import get_location_history

router = APIRouter(tags=["analysis v2"], responses=VALIDATION_ERROR_RESPONSES)
T = TypeVar("T", bound=AnalysisQuery)
V2_PARAMETERS = [p for p in PARAMETERS if p["name"] != "include_unknown"]


def parse(request: Request, model: type[T]) -> T:
    params = request.query_params
    if params.get("category") not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE)
    if any(k not in model.model_fields or len(params.getlist(k)) != 1 for k in params):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return model.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def nearby_query(request: Request) -> AnalysisQuery:
    return parse(request, AnalysisQuery)


def snapshot_query(request: Request) -> AnalysisSnapshotQuery:
    return parse(request, AnalysisSnapshotQuery)


def activity_query(request: Request) -> AnalysisActivityQuery:
    return parse(request, AnalysisActivityQuery)


def risk_query(request: Request) -> AnalysisRiskQuery:
    return parse(request, AnalysisRiskQuery)


def nearby_session(
    request: Request, query: Annotated[AnalysisQuery, Depends(nearby_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def snapshot_session(
    request: Request, query: Annotated[AnalysisSnapshotQuery, Depends(snapshot_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def activity_session(
    request: Request, query: Annotated[AnalysisActivityQuery, Depends(activity_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def risk_session(
    request: Request, query: Annotated[AnalysisRiskQuery, Depends(risk_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def location_query(request: Request) -> LocationHistoryQuery:
    params = request.query_params
    if any(
        k not in LocationHistoryQuery.model_fields or len(params.getlist(k)) != 1 for k in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return LocationHistoryQuery.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def location_session(
    request: Request, query: Annotated[LocationHistoryQuery, Depends(location_query)]
) -> Iterator[Session | None]:
    if query.identity_requirement == "verified_building":
        yield None
    else:
        with read_only_session(request.app.state.database, pool_retries=1) as session:
            yield session


@router.get(
    "/stores/location-history",
    response_model=ApiResponse[LocationHistory],
    openapi_extra={
        "parameters": [
            {
                "name": key,
                "in": "query",
                "required": key != "category",
                "schema": {"type": "string"},
            }
            for key in ("building_key", "floor_unit", "scope", "identity_requirement", "category")
        ]
    },
)
def location_history(
    query: Annotated[LocationHistoryQuery, Depends(location_query)],
    session: Annotated[Session | None, Depends(location_session)],
    response: Response,
) -> ApiResponse[LocationHistory]:
    response.headers.update(NO_STORE)
    return get_location_history(session, query)


@router.get(
    "/stores/nearby",
    response_model=ApiResponse[AnalysisNearby],
    openapi_extra={"parameters": V2_PARAMETERS},
)
def nearby(
    query: Annotated[AnalysisQuery, Depends(nearby_query)],
    session: Annotated[Session, Depends(nearby_session)],
    response: Response,
) -> ApiResponse[AnalysisNearby]:
    response.headers.update(NO_STORE)
    return analysis_v2.nearby(session, query)


@router.get(
    "/stores/snapshot",
    response_model=ApiResponse[AnalysisSnapshot],
    openapi_extra={
        "parameters": [
            {**p, "required": True} if p["name"] == "as_of" else p for p in V2_PARAMETERS
        ]
    },
)
def snapshot(
    query: Annotated[AnalysisSnapshotQuery, Depends(snapshot_query)],
    session: Annotated[Session, Depends(snapshot_session)],
    response: Response,
) -> ApiResponse[AnalysisSnapshot]:
    response.headers.update(NO_STORE)
    return analysis_v2.snapshot(session, query)


@router.get("/stores/history", response_model=ApiResponse[AnalysisHistory])
def history(
    query: Annotated[HistoryQuery, Depends(history_query)],
    session: Annotated[Session, Depends(validated_session)],
    response: Response,
) -> ApiResponse[AnalysisHistory]:
    response.headers.update(NO_STORE)
    return analysis_v2.history(session, query)


@router.get(
    "/market/activity",
    response_model=ApiResponse[MarketActivity],
    openapi_extra={
        "parameters": V2_PARAMETERS
        + [
            {
                "name": "include",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "description": "sales,living_pop"},
            }
        ]
    },
)
def activity(
    query: Annotated[AnalysisActivityQuery, Depends(activity_query)],
    session: Annotated[Session, Depends(activity_session)],
    response: Response,
) -> ApiResponse[MarketActivity]:
    response.headers.update(NO_STORE)
    return analysis_v2.activity(session, query)


@router.get(
    "/risk",
    response_model=ApiResponse[Risk],
    openapi_extra={
        "parameters": V2_PARAMETERS
        + [
            {
                "name": "include",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "description": "market_change,day_night_ratio"},
            }
        ]
    },
)
def risk(
    request: Request,
    query: Annotated[AnalysisRiskQuery, Depends(risk_query)],
    session: Annotated[Session, Depends(risk_session)],
    response: Response,
) -> ApiResponse[Risk]:
    response.headers.update(NO_STORE)
    return analysis_v2.risk(session, query, request.app.state.settings)
