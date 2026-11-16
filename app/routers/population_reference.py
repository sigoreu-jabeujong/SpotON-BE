"""Population public-subset route; validation completes before acquiring a DB session."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.population_reference import PopulationReference, PopulationReferenceQuery
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.population_reference import get_population_reference

router = APIRouter(tags=["population reference"])


def population_query(request: Request) -> PopulationReferenceQuery:
    params = request.query_params
    if params.get("category") not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE)
    if any(
        k not in PopulationReferenceQuery.model_fields or len(params.getlist(k)) != 1
        for k in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return PopulationReferenceQuery.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def population_session(
    request: Request,
    query: Annotated[PopulationReferenceQuery, Depends(population_query)],
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/population-reference",
    response_model=ApiResponse[PopulationReference],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="원천별 동일 공개 구성의 주야간 참고 비교 (전체 인구 아님)",
    openapi_extra={
        "parameters": [p for p in PARAMETERS if p["name"] in PopulationReferenceQuery.model_fields]
    },
)
def population_reference(
    query: Annotated[PopulationReferenceQuery, Depends(population_query)],
    session: Annotated[Session, Depends(population_session)],
    response: Response,
) -> ApiResponse[PopulationReference]:
    response.headers.update(NO_STORE)
    return get_population_reference(session, query)
