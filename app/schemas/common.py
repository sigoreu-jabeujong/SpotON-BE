from enum import StrEnum
from typing import Generic, Self, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

T = TypeVar("T")
ApiMeta: TypeAlias = dict[str, JsonValue]


class ErrorCode(StrEnum):
    INVALID_PARAM = "INVALID_PARAM"
    CATEGORY_REQUIRED = "CATEGORY_REQUIRED"
    ADDRESS_NOT_FOUND = "ADDRESS_NOT_FOUND"
    OUT_OF_SEOUL = "OUT_OF_SEOUL"
    AS_OF_OUT_OF_RANGE = "AS_OF_OUT_OF_RANGE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    AI_VERIFY_FAILED = "AI_VERIFY_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    code: ErrorCode
    message: str


class ApiResponse(BaseModel, Generic[T]):
    """공통 외피. 상세 meta 계약은 BE-04에서 원본 명세와 대조한다."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    data: T | None
    meta: ApiMeta = Field(default_factory=dict)
    error: ApiError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("응답에는 data 또는 error 중 하나만 값이 있어야 합니다")
        return self


class ErrorResponse(ApiResponse[None]):
    data: None = None
    error: ApiError = Field(...)
