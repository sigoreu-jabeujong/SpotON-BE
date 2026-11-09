from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue

T = TypeVar("T")


class ApiError(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel, Generic[T]):
    """공통 외피. 상세 meta 계약은 BE-04에서 원본 명세와 대조한다."""

    model_config = ConfigDict(extra="forbid")

    data: T | None
    meta: dict[str, JsonValue] = Field(default_factory=dict)
    error: ApiError | None = None
