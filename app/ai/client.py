"""공급자와 무관한 LLM client 계약.

프롬프트·스키마·생성 결과 원문은 repr·예외 메시지에 넣지 않는다. 외부 전송 허용 필드
추출은 BE-28 책임이며 이 모듈은 받은 문자열을 그대로 공급자에 전달한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pydantic import JsonValue

from app.core.errors import AppError
from app.schemas.common import ErrorCode


class LlmErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    UPSTREAM = "upstream"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    MALFORMED_RESPONSE = "malformed_response"


class LlmError(Exception):
    """원인 예외·공급자 본문 없이 오류 종류만 담는 LLM 실패."""

    def __init__(self, kind: LlmErrorKind) -> None:
        if not isinstance(kind, LlmErrorKind):
            raise TypeError("LlmError에는 LlmErrorKind를 지정해야 합니다")
        self.kind = kind
        super().__init__(kind.value)

    def __repr__(self) -> str:
        return f"LlmError({self.kind.value!r})"


@dataclass(frozen=True)
class LlmRequest:
    system_instruction: str = field(repr=False)
    user_content: str = field(repr=False)
    response_json_schema: Mapping[str, JsonValue] | None = field(default=None, repr=False)
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_output_tokens is not None and not 1 <= self.max_output_tokens <= 65536:
            raise ValueError("max_output_tokens는 1~65536이어야 합니다")


@dataclass(frozen=True)
class LlmUsage:
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LlmResult:
    text: str = field(repr=False)
    provider: str
    model: str
    usage: LlmUsage
    attempts: int


class LlmClient(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate(self, request: LlmRequest) -> LlmResult: ...


def to_app_error(error: LlmError) -> AppError:
    """모든 LLM 실패를 기존 AI_UNAVAILABLE로 매핑한다(작업계획 6·8절)."""
    del error
    return AppError(ErrorCode.AI_UNAVAILABLE)
