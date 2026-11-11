from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.dependencies import NO_STORE, history_session
from app.routers.spatial_query import PARAMETERS, parse_spatial_query
from app.schemas.common import ApiResponse
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.schemas.snapshot import SnapshotQuery, StoreSnapshot
from app.services.store_snapshot import get_snapshot

router = APIRouter(tags=["stores"])


def snapshot_query(request: Request) -> SnapshotQuery:
    return parse_spatial_query(request, SnapshotQuery)


def snapshot_session(
    request: Request, query: Annotated[SnapshotQuery, Depends(snapshot_query)]
) -> Iterator[Session]:
    yield from history_session(request)


@router.get(
    "/stores/snapshot",
    response_model=ApiResponse[StoreSnapshot],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="과거 시점 점포의 최신 상태 분해",
    openapi_extra={
        "parameters": [{**p, "required": p["required"] or p["name"] == "as_of"} for p in PARAMETERS]
    },
)
def snapshot(
    query: Annotated[SnapshotQuery, Depends(snapshot_query)],
    session: Annotated[Session, Depends(snapshot_session)],
    response: Response,
) -> ApiResponse[StoreSnapshot]:
    response.headers.update(NO_STORE)
    return get_snapshot(session, query)
