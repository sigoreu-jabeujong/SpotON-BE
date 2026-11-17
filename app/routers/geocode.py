from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.address_detail import NormalizedDetail
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.geocode import Category, GeocodeData
from app.schemas.responses import GEOCODE_ERROR_RESPONSES
from app.services.kakao_local import NO_STORE_HEADERS, KakaoLocalService
from etl.address.floor_unit import parse_floor_unit

router = APIRouter(tags=["geocode"])


def get_geocode_service(request: Request) -> KakaoLocalService:
    settings = request.app.state.settings
    assert isinstance(settings, Settings)
    api_key = (
        settings.kakao_rest_api_key.get_secret_value()
        if settings.kakao_rest_api_key is not None
        else None
    )
    return KakaoLocalService(api_key=api_key, timeout=settings.kakao_request_timeout)


@router.get(
    "/geocode",
    response_model=ApiResponse[GeocodeData],
    responses=GEOCODE_ERROR_RESPONSES,
    summary="서울 주소를 좌표와 건물 키로 변환",
)
async def geocode(
    service: Annotated[KakaoLocalService, Depends(get_geocode_service)],
    response: Response,
    query: str | None = None,
    category: str | None = None,
) -> ApiResponse[GeocodeData]:
    """Return verified Seoul candidates without persisting request address data."""
    if category not in {"cafe", "restaurant"}:
        raise AppError(ErrorCode.CATEGORY_REQUIRED, headers=NO_STORE_HEADERS)
    if query is None or not query.strip() or len(query) > 1000:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE_HEADERS)
    data = await service.geocode(query=query, category=cast(Category, category))
    response.headers.update(NO_STORE_HEADERS)
    return ApiResponse(data=data, meta={"source": ["R8"], "space": "point"})


class DetailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    detail: str = Field(max_length=100)


@router.post(
    "/address-detail",
    response_model=ApiResponse[NormalizedDetail],
    responses=GEOCODE_ERROR_RESPONSES,
)
def address_detail(body: DetailInput, response: Response) -> ApiResponse[NormalizedDetail]:
    """Normalize user-entered detail only; no provider, DB or location verification."""
    result = parse_floor_unit(body.detail)
    response.headers.update(NO_STORE_HEADERS)
    return ApiResponse(
        data=NormalizedDetail.model_validate(
            {
                "floor_unit": result.value.value if result.value else None,
                "status": "parsed"
                if result.value
                else "empty"
                if not body.detail.strip()
                else "unverified",
                "reason": result.failure.value if result.failure else None,
            }
        ),
        meta={"rule_version": "address-detail-v1"},
    )
