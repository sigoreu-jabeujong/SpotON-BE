"""Gemini generateContent REST 어댑터.

공식 문서(2026-11-11 확인): POST /v1beta/models/{model}:generateContent,
인증은 x-goog-api-key 헤더. 오류 본문·프롬프트·생성 결과는 로그와 예외에 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.ai.client import LlmError, LlmErrorKind, LlmRequest, LlmResult, LlmUsage
from app.ai.limits import RequestLimiter, RetryPolicy

GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_PROVIDER = "google"
MODEL_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]*")
RETRYABLE_STATUS_CODES = frozenset({429, 500, 503, 504})
BLOCKING_FINISH_REASONS = frozenset(
    {"SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class GeminiPart(_Model):
    text: str | None = None
    thought: bool | None = None


class GeminiContent(_Model):
    parts: list[GeminiPart] = []


class GeminiCandidate(_Model):
    content: GeminiContent | None = None
    finishReason: str | None = None


class GeminiPromptFeedback(_Model):
    blockReason: str | None = None


class GeminiUsageMetadata(_Model):
    promptTokenCount: int | None = None
    candidatesTokenCount: int | None = None
    totalTokenCount: int | None = None


class GeminiResponse(_Model):
    candidates: list[GeminiCandidate] | None = None
    promptFeedback: GeminiPromptFeedback | None = None
    usageMetadata: GeminiUsageMetadata | None = None


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        policy: RetryPolicy,
        limiter: RequestLimiter,
        max_output_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._policy = policy
        self._limiter = limiter
        self._max_output_tokens = max_output_tokens
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._rng = rng

    @property
    def provider(self) -> str:
        return GEMINI_PROVIDER

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, request: LlmRequest) -> LlmResult:
        if not self._api_key or not MODEL_NAME_PATTERN.fullmatch(self._model):
            raise LlmError(LlmErrorKind.NOT_CONFIGURED)

        url = f"{GEMINI_MODELS_URL}/{self._model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        body = self._body(request)
        deadline = self._monotonic() + self._policy.time_budget
        attempts = 0

        async with httpx.AsyncClient(transport=self._transport) as client:
            while True:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise LlmError(LlmErrorKind.TIMEOUT)
                self._limiter.acquire()
                attempts += 1
                timeout = min(self._policy.request_timeout, remaining)
                response, failure = await self._post(client, url, headers, body, timeout)

                retryable = True
                if response is not None:
                    if response.status_code == 200:
                        return self._parse(response.content, attempts)
                    failure = (
                        LlmErrorKind.RATE_LIMITED
                        if response.status_code == 429
                        else LlmErrorKind.UPSTREAM
                    )
                    retryable = response.status_code in RETRYABLE_STATUS_CODES
                assert failure is not None

                retry_index = attempts - 1
                if not retryable or retry_index >= self._policy.max_retries:
                    raise LlmError(failure)
                delay = self._policy.backoff(retry_index, self._rng)
                if self._monotonic() + delay >= deadline:
                    raise LlmError(failure)
                await self._sleep(delay)

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        generation_config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "maxOutputTokens": request.max_output_tokens or self._max_output_tokens,
        }
        if request.response_json_schema is not None:
            generation_config["responseJsonSchema"] = dict(request.response_json_schema)
        return {
            "systemInstruction": {"parts": [{"text": request.system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_content}]}],
            "generationConfig": generation_config,
        }

    @staticmethod
    async def _post(
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> tuple[httpx.Response | None, LlmErrorKind | None]:
        # 원인 예외가 LlmError의 __context__에 남지 않도록 except 안에서는 종류만 돌려준다.
        try:
            response = await client.post(url, json=body, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            return None, LlmErrorKind.TIMEOUT
        except httpx.HTTPError:
            return None, LlmErrorKind.UPSTREAM
        return response, None

    def _parse(self, content: bytes, attempts: int) -> LlmResult:
        payload: GeminiResponse | None
        try:
            payload = GeminiResponse.model_validate_json(content)
        except ValidationError:
            payload = None
        if payload is None:
            raise LlmError(LlmErrorKind.MALFORMED_RESPONSE)

        if payload.promptFeedback is not None and payload.promptFeedback.blockReason:
            raise LlmError(LlmErrorKind.BLOCKED)
        if not payload.candidates:
            raise LlmError(LlmErrorKind.MALFORMED_RESPONSE)

        candidate = payload.candidates[0]
        reason = candidate.finishReason
        if reason == "MAX_TOKENS":
            raise LlmError(LlmErrorKind.INCOMPLETE)
        if reason in BLOCKING_FINISH_REASONS:
            raise LlmError(LlmErrorKind.BLOCKED)
        if reason != "STOP":
            raise LlmError(LlmErrorKind.MALFORMED_RESPONSE)

        parts = candidate.content.parts if candidate.content is not None else []
        text = "".join(part.text for part in parts if part.text and part.thought is not True)
        if not text.strip():
            raise LlmError(LlmErrorKind.MALFORMED_RESPONSE)

        usage = payload.usageMetadata or GeminiUsageMetadata()
        return LlmResult(
            text=text,
            provider=GEMINI_PROVIDER,
            model=self._model,
            usage=LlmUsage(
                prompt_tokens=usage.promptTokenCount,
                output_tokens=usage.candidatesTokenCount,
                total_tokens=usage.totalTokenCount,
            ),
            attempts=attempts,
        )
