import pytest

from app.ai.client import (
    LlmError,
    LlmErrorKind,
    LlmRequest,
    LlmResult,
    LlmUsage,
    to_app_error,
)
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


@pytest.mark.parametrize("tokens", [0, 65537])
def test_request_rejects_out_of_range_output_tokens(tokens: int) -> None:
    with pytest.raises(ValueError):
        LlmRequest(system_instruction="s", user_content="u", max_output_tokens=tokens)
