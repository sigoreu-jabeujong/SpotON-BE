from collections.abc import Mapping
from types import MappingProxyType

from starlette.responses import JSONResponse

from app.schemas.common import ApiError, ErrorCode, ErrorResponse

ERROR_SPECS: Mapping[ErrorCode, tuple[int, str]] = MappingProxyType(
    {
        ErrorCode.INVALID_PARAM: (422, "요청 값을 확인해 주세요"),
        ErrorCode.CATEGORY_REQUIRED: (422, "업종을 선택해 주세요"),
        ErrorCode.ADDRESS_NOT_FOUND: (404, "주소를 찾을 수 없습니다"),
        ErrorCode.OUT_OF_SEOUL: (422, "서울특별시 주소만 지원합니다"),
        ErrorCode.AS_OF_OUT_OF_RANGE: (422, "조회 가능한 기준 시점을 벗어났습니다"),
        ErrorCode.UPSTREAM_ERROR: (502, "외부 데이터 서비스에 연결할 수 없습니다"),
        ErrorCode.AI_UNAVAILABLE: (503, "AI 해석을 일시적으로 이용할 수 없습니다"),
        ErrorCode.AI_VERIFY_FAILED: (503, "AI 해석 결과를 검증하지 못했습니다"),
        ErrorCode.INTERNAL_ERROR: (500, "요청 처리 중 오류가 발생했습니다"),
    }
)


class AppError(Exception):
    def __init__(self, code: ErrorCode, *, headers: Mapping[str, str] | None = None) -> None:
        if not isinstance(code, ErrorCode):
            raise TypeError("AppError에는 ErrorCode를 지정해야 합니다")
        self.code = code
        self.headers = headers
        super().__init__(code.value)


def error_response(
    code: ErrorCode,
    *,
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    default_status, message = ERROR_SPECS[code]
    body = ErrorResponse(error=ApiError(code=code, message=message))
    return JSONResponse(
        status_code=default_status if status_code is None else status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )
