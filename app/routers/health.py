import asyncio

from fastapi import APIRouter, Request, Response

from app.core.errors import AppError
from app.db.dependencies import NO_STORE, DatabaseResources
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.health import HealthData
from app.schemas.responses import ERROR_RESPONSES
from app.services.readiness import PROBE_TIMEOUT_SECONDS

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


@router.get(
    "/ready",
    response_model=ApiResponse[HealthData],
    responses=ERROR_RESPONSES,
    summary="DB 연결·스키마·배포 계정 준비 상태 확인",
)
async def ready(request: Request, response: Response) -> ApiResponse[HealthData]:
    resources: DatabaseResources = request.app.state.database
    try:
        available = await asyncio.wait_for(
            asyncio.to_thread(resources.readiness.check), timeout=PROBE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        available = False
    if not available:
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
    response.headers.update(NO_STORE)
    return ApiResponse(data=HealthData())
