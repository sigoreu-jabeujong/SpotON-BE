from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.data_range import DataRange, DataRangeQuery
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.data_range import get_data_range

router = APIRouter(tags=["meta"])


def data_range_query(request: Request) -> DataRangeQuery:
    params = request.query_params
    if params.get("category") not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE)
    if any(
        name not in DataRangeQuery.model_fields or len(params.getlist(name)) != 1 for name in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return DataRangeQuery.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def data_range_session(
    request: Request, query: Annotated[DataRangeQuery, Depends(data_range_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/meta/data-range",
    response_model=ApiResponse[DataRange],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="업종별 조회 가능한 데이터 월 범위",
    openapi_extra={
        "parameters": [
            {
                "name": "category",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "enum": ["cafe", "restaurant"]},
            },
            {
                "name": "sub_category",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "description": "쉼표 구분 지원 업종"},
            },
        ]
    },
)
def data_range(
    query: Annotated[DataRangeQuery, Depends(data_range_query)],
    session: Annotated[Session, Depends(data_range_session)],
    response: Response,
) -> ApiResponse[DataRange]:
    response.headers.update(NO_STORE)
    return get_data_range(session, query)
