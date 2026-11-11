from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS, parse_spatial_query
from app.schemas.common import ApiResponse
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.schemas.risk import Risk, RiskQuery
from app.services.risk import get_risk

router = APIRouter(tags=["risk"])


def risk_query(request: Request) -> RiskQuery:
    return parse_spatial_query(request, RiskQuery)


def risk_session(
    request: Request, query: Annotated[RiskQuery, Depends(risk_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/risk",
    response_model=ApiResponse[Risk],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="인허가 참고지표와 공식 지표 준비 상태",
    openapi_extra={
        "parameters": [
            *PARAMETERS,
            {
                "name": "include",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "description": "market_change,day_night_ratio"},
            },
        ]
    },
)
def risk(
    request: Request,
    query: Annotated[RiskQuery, Depends(risk_query)],
    session: Annotated[Session, Depends(risk_session)],
    response: Response,
) -> ApiResponse[Risk]:
    response.headers.update(NO_STORE)
    return get_risk(session, query, request.app.state.settings)
