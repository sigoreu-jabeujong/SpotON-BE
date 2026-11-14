"""Independent v2 brand contract. Invalid input is rejected before a DB session."""

from collections.abc import Iterator
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS
from app.routers.stores import history_query, validated_session
from app.schemas.chains import (
    ChainActivityQuery,
    ChainHistory,
    ChainNearby,
    ChainQuery,
    ChainRiskQuery,
    ChainSnapshot,
    ChainSnapshotQuery,
)
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.market_activity import MarketActivity
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.schemas.risk import Risk
from app.schemas.stores import HistoryQuery
from app.services import chain_api
from app.services.chains import ChainSelection

router = APIRouter(tags=["brand v2"], responses=VALIDATION_ERROR_RESPONSES)
T = TypeVar("T", bound=ChainQuery)
V2_PARAMETERS = [
    p
    for p in PARAMETERS
    if p["name"] not in {"franchise", "include_unknown_franchise", "include_unknown"}
] + [
    {"name": name, "in": "query", "required": False, "schema": {"type": "string", "enum": values}}
    for name, values in {
        "brand_scope": ["all", "chain", "non_chain"],
        "brand_unknown": ["include", "exclude"],
        "brand_evidence": ["include_estimates", "confirmed_only"],
        "brand_time_basis": ["observed_record"],
        "operation_type": ["any"],
    }.items()
]


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


def nearby_query(request: Request) -> ChainQuery:
    return parse(request, ChainQuery)


def snapshot_query(request: Request) -> ChainSnapshotQuery:
    return parse(request, ChainSnapshotQuery)


def activity_query(request: Request) -> ChainActivityQuery:
    return parse(request, ChainActivityQuery)


def risk_query(request: Request) -> ChainRiskQuery:
    return parse(request, ChainRiskQuery)


def nearby_session(
    request: Request, query: Annotated[ChainQuery, Depends(nearby_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def snapshot_session(
    request: Request, query: Annotated[ChainSnapshotQuery, Depends(snapshot_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def activity_session(
    request: Request, query: Annotated[ChainActivityQuery, Depends(activity_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def risk_session(
    request: Request, query: Annotated[ChainRiskQuery, Depends(risk_query)]
) -> Iterator[Session]:
    yield from history_session(request)


def status_session(request: Request) -> Iterator[Session]:
    if request.query_params:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    yield from history_session(request)


@router.get("/brands/status", response_model=ApiResponse[ApiMeta])
def status(
    session: Annotated[Session, Depends(status_session)], response: Response
) -> ApiResponse[ApiMeta]:
    response.headers.update(NO_STORE)
    chain = ChainSelection.load(session)
    data = chain.meta()
    data["publication_counts"] = (
        chain.publication.summary.get("status") if chain.publication else None
    )
    data["publication_counts_scope"] = "publication_source_supported_license_records"
    return ApiResponse(data=data, meta={})


@router.get(
    "/stores/nearby",
    response_model=ApiResponse[ChainNearby],
    openapi_extra={"parameters": V2_PARAMETERS},
)
def nearby(
    query: Annotated[ChainQuery, Depends(nearby_query)],
    session: Annotated[Session, Depends(nearby_session)],
    response: Response,
) -> ApiResponse[ChainNearby]:
    response.headers.update(NO_STORE)
    return chain_api.nearby(session, query)


@router.get(
    "/stores/snapshot",
    response_model=ApiResponse[ChainSnapshot],
    openapi_extra={
        "parameters": [
            {**p, "required": True} if p["name"] == "as_of" else p for p in V2_PARAMETERS
        ]
    },
)
def snapshot(
    query: Annotated[ChainSnapshotQuery, Depends(snapshot_query)],
    session: Annotated[Session, Depends(snapshot_session)],
    response: Response,
) -> ApiResponse[ChainSnapshot]:
    response.headers.update(NO_STORE)
    return chain_api.snapshot(session, query)


@router.get("/stores/history", response_model=ApiResponse[ChainHistory])
def history(
    query: Annotated[HistoryQuery, Depends(history_query)],
    session: Annotated[Session, Depends(validated_session)],
    response: Response,
) -> ApiResponse[ChainHistory]:
    response.headers.update(NO_STORE)
    return chain_api.history(session, query)


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
    query: Annotated[ChainActivityQuery, Depends(activity_query)],
    session: Annotated[Session, Depends(activity_session)],
    response: Response,
) -> ApiResponse[MarketActivity]:
    response.headers.update(NO_STORE)
    return chain_api.activity(session, query)


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
    query: Annotated[ChainRiskQuery, Depends(risk_query)],
    session: Annotated[Session, Depends(risk_session)],
    response: Response,
) -> ApiResponse[Risk]:
    response.headers.update(NO_STORE)
    return chain_api.risk(session, query, request.app.state.settings)
