from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, read_only_session
from app.routers.geocode import get_geocode_service
from app.schemas.address_history import AddressHistory, AddressHistoryQuery, ContextRequest
from app.schemas.common import ApiResponse, ErrorCode, ErrorResponse
from app.schemas.responses import GEOCODE_ERROR_RESPONSES
from app.services.address_context import AddressPair, create_context, decode_pair
from app.services.address_history import get_address_history
from app.services.kakao_local import KakaoLocalService

router = APIRouter(
    tags=["address history v3"],
    responses={
        **GEOCODE_ERROR_RESPONSES,
        503: {"model": ErrorResponse},
    },
)


@router.post("/address-context")
async def context(
    body: ContextRequest,
    request: Request,
    response: Response,
    service: Annotated[KakaoLocalService, Depends(get_geocode_service)],
) -> ApiResponse[dict[str, str | None]]:
    response.headers.update(NO_STORE)
    return ApiResponse(data=await create_context(service, body, request.app.state.settings))


def history_query(request: Request) -> AddressHistoryQuery:
    if any(
        k not in AddressHistoryQuery.model_fields or len(request.query_params.getlist(k)) != 1
        for k in request.query_params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return AddressHistoryQuery.model_validate(dict(request.query_params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def verified_pair(
    request: Request, query: Annotated[AddressHistoryQuery, Depends(history_query)]
) -> AddressPair:
    return decode_pair(query.context, request.app.state.settings)


def history_session(
    request: Request, pair: Annotated[AddressPair, Depends(verified_pair)]
) -> Iterator[Session]:
    with read_only_session(request.app.state.database, pool_retries=1) as session:
        if (
            session.scalar(text("SELECT to_regprocedure('spoton_history_road_key_v1(text)')"))
            is None
        ):
            raise AppError(ErrorCode.HISTORY_UNAVAILABLE, headers=NO_STORE)
        yield session


@router.get("/stores/location-history", response_model=ApiResponse[AddressHistory])
def history(
    query: Annotated[AddressHistoryQuery, Depends(history_query)],
    pair: Annotated[AddressPair, Depends(verified_pair)],
    session: Annotated[Session, Depends(history_session)],
    response: Response,
) -> ApiResponse[AddressHistory]:
    response.headers.update(NO_STORE)
    return get_address_history(session, query, pair)
