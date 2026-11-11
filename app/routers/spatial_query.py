from typing import TypeVar

from fastapi import Request
from pydantic import ValidationError

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.schemas.common import ErrorCode
from app.schemas.nearby import NearbyQuery

QueryT = TypeVar("QueryT", bound=NearbyQuery)


def parse_spatial_query(request: Request, model: type[QueryT]) -> QueryT:
    params = request.query_params
    if params.get("category") not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE)
    if any(name not in model.model_fields or len(params.getlist(name)) != 1 for name in params):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return model.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


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
