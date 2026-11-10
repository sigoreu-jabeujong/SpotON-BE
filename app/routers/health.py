from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.schemas.health import HealthData
from app.schemas.responses import ERROR_RESPONSES

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=ApiResponse[HealthData],
    responses=ERROR_RESPONSES,
    summary="서버 상태 확인",
)
def health() -> ApiResponse[HealthData]:
    """프로세스 실행 상태만 확인한다. DB 준비 상태는 검증하지 않는다."""
    return ApiResponse(data=HealthData())
