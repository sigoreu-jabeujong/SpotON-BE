from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, history_session
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.nearby import NearbyQuery, NearbyStores
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.nearby import get_nearby

router = APIRouter(tags=["stores"])


def nearby_query(request: Request) -> NearbyQuery:
    params = request.query_params
    if params.get("category") not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE)
    if any(
        name not in NearbyQuery.model_fields or len(params.getlist(name)) != 1 for name in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return NearbyQuery.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


def nearby_session(
    request: Request, query: Annotated[NearbyQuery, Depends(nearby_query)]
) -> Iterator[Session]:
    yield from history_session(request)


PARAMETERS = [
    {"name": name, "in": "query", "required": name in {"lat", "lng", "category"}, "schema": schema}
    for name, schema in {
        "lat": {"type": "number", "minimum": -90, "maximum": 90},
        "lng": {"type": "number", "minimum": -180, "maximum": 180},
        "category": {"type": "string", "enum": ["cafe", "restaurant"]},
        "radius": {"type": "integer", "enum": [300, 500, 1000], "default": 500},
        "sub_category": {"type": "string", "description": "쉼표 구분 지원 업종"},
        "as_of": {"type": "string", "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$"},
        "area": {
            "type": "string",
            "enum": ["all", "lt33", "33to66", "66to99", "gte99"],
            "default": "all",
        },
        "franchise": {
            "type": "string",
            "enum": ["all", "franchise", "independent"],
            "default": "all",
        },
        "include_unknown_area": {"type": "boolean", "default": True},
        "include_unknown_franchise": {"type": "boolean", "default": True},
        "include_unknown": {
            "type": "boolean",
            "description": "기존 FE 호환. 신규 개별 토글과 혼합 불가",
        },
    }.items()
]


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
