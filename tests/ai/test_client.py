import asyncio

import httpx
import pytest

from app.ai.client import (
    LlmError,
    LlmErrorKind,
    LlmRequest,
    LlmResult,
    LlmUsage,
    to_app_error,
)
from app.ai.factory import create_llm_client
from app.ai.gemini import GeminiClient
from app.core.config import Settings
from app.core.errors import ERROR_SPECS
from app.schemas.common import ErrorCode

PROMPT = "SECRET-PROMPT-서울 마포구 양화로 160"
OUTPUT = '{"summary": "SECRET-OUTPUT"}'


@pytest.mark.parametrize("kind", list(LlmErrorKind))
def test_every_llm_error_maps_to_ai_unavailable(kind: LlmErrorKind) -> None:
    error = to_app_error(LlmError(kind))
    assert error.code is ErrorCode.AI_UNAVAILABLE
    assert ERROR_SPECS[error.code][0] == 503


def test_llm_error_only_carries_kind() -> None:
    error = LlmError(LlmErrorKind.UPSTREAM)
    assert str(error) == "upstream"
    assert repr(error) == "LlmError('upstream')"
    with pytest.raises(TypeError):
        LlmError("upstream")  # type: ignore[arg-type]


def test_request_and_result_repr_hide_raw_text() -> None:
    request = LlmRequest(
        system_instruction=PROMPT,
        user_content=PROMPT,
        response_json_schema={"type": "object", "description": PROMPT},
    )
    result = LlmResult(
        text=OUTPUT,
        provider="google",
        model="gemini-3.5-flash-lite",
        usage=LlmUsage(prompt_tokens=1, output_tokens=2, total_tokens=3),
        attempts=1,
    )
    assert "SECRET" not in repr(request)
    assert "SECRET" not in repr(result)


def test_factory_selects_gemini_for_google() -> None:
    settings = Settings(_env_file=None, llm_provider="google", llm_api_key="k")
    client = create_llm_client(settings)
    assert isinstance(client, GeminiClient)
    assert (client.provider, client.model) == ("google", settings.llm_model)


@pytest.mark.parametrize("provider", ["openai", "Google", ""])
def test_factory_unsupported_provider_fails_without_calling(provider: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    settings = Settings(_env_file=None, llm_provider=provider, llm_api_key="k")
    client = create_llm_client(settings, transport=httpx.MockTransport(handler))
    request = LlmRequest(system_instruction="s", user_content="u")
    with pytest.raises(LlmError) as raised:
        asyncio.run(client.generate(request))
    assert raised.value.kind is LlmErrorKind.NOT_CONFIGURED
    assert raised.value.__context__ is None
    assert calls == []


@pytest.mark.parametrize("tokens", [0, 65537])
def test_request_rejects_out_of_range_output_tokens(tokens: int) -> None:
    with pytest.raises(ValueError):
        LlmRequest(system_instruction="s", user_content="u", max_output_tokens=tokens)
