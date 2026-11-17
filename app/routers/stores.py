from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session
from app.schemas.common import ApiResponse, ErrorCode, ErrorResponse
from app.schemas.stores import HistoryQuery, StoreHistory
from app.services.store_history import get_history

router = APIRouter(tags=["stores"])


def history_query(
    request: Request,
    building_key: str | None = None,
    floor_unit: str | None = None,
    category: str | None = None,
) -> HistoryQuery:
    # Reject duplicates and unknown keys before opening a database connection.
    params = request.query_params
    if any(
        key not in {"building_key", "floor_unit", "category"} or len(params.getlist(key)) != 1
        for key in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return HistoryQuery.model_validate(
            {"building_key": building_key, "floor_unit": floor_unit, "category": category}
        )
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def validated_session(
    request: Request, query: Annotated[HistoryQuery, Depends(history_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/stores/history",
    response_model=ApiResponse[StoreHistory],
    summary="건물별 음식점·카페 인허가 이력",
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def store_history(
    query: Annotated[HistoryQuery, Depends(history_query)],
    session: Annotated[Session, Depends(validated_session)],
    response: Response,
) -> ApiResponse[StoreHistory]:
    response.headers.update(NO_STORE)
    return get_history(session, query)
