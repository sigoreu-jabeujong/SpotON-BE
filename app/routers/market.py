from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS, parse_spatial_query
from app.schemas.common import ApiResponse
from app.schemas.market_activity import ActivityQuery, MarketActivity
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.market_activity import get_activity

router = APIRouter(tags=["market"])


def activity_query(request: Request) -> ActivityQuery:
    return parse_spatial_query(request, ActivityQuery)


def activity_session(
    request: Request, query: Annotated[ActivityQuery, Depends(activity_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/market/activity",
    response_model=ApiResponse[MarketActivity],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="인허가 기반 활동 분석과 선택 지표 준비 상태",
    openapi_extra={
        "parameters": [
            *PARAMETERS,
            {
                "name": "include",
                "in": "query",
                "required": False,
                "schema": {
                    "type": "string",
                    "description": "sales,living_pop; currently null with pending reasons.",
                },
            },
        ]
    },
)
def activity(
    query: Annotated[ActivityQuery, Depends(activity_query)],
    session: Annotated[Session, Depends(activity_session)],
    response: Response,
) -> ApiResponse[MarketActivity]:
    response.headers.update(NO_STORE)
    return get_activity(session, query)
