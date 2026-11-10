"""설정으로 LLM client를 고른다.

한도 카운터가 client 인스턴스에 있으므로 호출하는 쪽(BE-32)은 앱 수명 동안 하나를 만들어
재사용해야 한다. 설정 오류는 앱 시작을 막지 않고 호출 시 not_configured로 실패한다.
"""

from __future__ import annotations

import httpx

from app.ai.client import LlmClient, LlmError, LlmErrorKind, LlmRequest, LlmResult
from app.ai.gemini import GEMINI_PROVIDER, GeminiClient
from app.ai.limits import RequestLimiter, RetryPolicy
from app.core.config import Settings


class UnavailableLlmClient:
    """지원하지 않는 공급자 설정용. 공급자를 호출하지 않는다."""

    def __init__(self, *, provider: str, model: str) -> None:
        self._provider = provider
        self._model = model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, request: LlmRequest) -> LlmResult:
        del request
        raise LlmError(LlmErrorKind.NOT_CONFIGURED)


def create_llm_client(
    settings: Settings,
    *,
    limiter: RequestLimiter | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LlmClient:
    if settings.llm_provider != GEMINI_PROVIDER:
        return UnavailableLlmClient(provider=settings.llm_provider, model=settings.llm_model)
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    return GeminiClient(
        api_key=api_key,
        model=settings.llm_model,
        policy=RetryPolicy.from_settings(settings),
        limiter=limiter if limiter is not None else RequestLimiter.from_settings(settings),
        max_output_tokens=settings.llm_max_output_tokens,
        transport=transport,
    )
