from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS, parse_spatial_query
from app.schemas.common import ApiResponse
from app.schemas.nearby import NearbyQuery, NearbyStores
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.nearby import get_nearby

router = APIRouter(tags=["stores"])


def nearby_query(request: Request) -> NearbyQuery:
    return parse_spatial_query(request, NearbyQuery)


def nearby_session(
    request: Request, query: Annotated[NearbyQuery, Depends(nearby_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/stores/nearby",
    response_model=ApiResponse[NearbyStores],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="기준 시점 반경 내 점포 조회",
    openapi_extra={"parameters": PARAMETERS},
)
def nearby(
    query: Annotated[NearbyQuery, Depends(nearby_query)],
    session: Annotated[Session, Depends(nearby_session)],
    response: Response,
) -> ApiResponse[NearbyStores]:
    response.headers.update(NO_STORE)
    return get_nearby(session, query)
