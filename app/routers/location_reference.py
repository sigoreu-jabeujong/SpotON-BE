"""Validate all query arguments before opening the read-only reference transaction."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.report_basis import basis
from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.location_reference import LocationReference, LocationReferenceQuery
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.location_reference import get_location_reference

router = APIRouter(tags=["location reference"])


def reference_query(request: Request) -> LocationReferenceQuery:
    params = request.query_params
    if params.get("category") not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE)
    if any(
        k not in LocationReferenceQuery.model_fields or len(params.getlist(k)) != 1 for k in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return LocationReferenceQuery.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def reference_session(
    request: Request, query: Annotated[LocationReferenceQuery, Depends(reference_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/location-reference",
    response_model=ApiResponse[LocationReference],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="검색 위치 포함·반경 교차 상권의 원자료 참고값",
    openapi_extra={
        "parameters": [
            *[p for p in PARAMETERS if p["name"] in LocationReferenceQuery.model_fields],
            {
                "name": "time_mode",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["latest_reference", "analysis_period"],
                    "default": "latest_reference",
                },
            },
        ]
    },
)
def location_reference(
    request: Request,
    query: Annotated[LocationReferenceQuery, Depends(reference_query)],
    session: Annotated[Session, Depends(reference_session)],
    response: Response,
) -> ApiResponse[LocationReference]:
    response.headers.update(NO_STORE)
    return basis(
        "location", query, get_location_reference(session, query), request.app.state.settings
    )
