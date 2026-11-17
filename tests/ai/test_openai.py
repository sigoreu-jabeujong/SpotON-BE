import asyncio
import json

import httpx
import pytest

from app.ai.client import LlmError, LlmErrorKind, LlmRequest
from app.ai.limits import RequestLimiter, RetryPolicy
from app.ai.openai import OpenAIClient


def client(handler):
    return OpenAIClient(
        api_key="unit-test-secret",
        model="gpt-4.1-mini",
        policy=RetryPolicy(10, 35, 0, 1, 1),
        limiter=RequestLimiter(per_minute=None, per_day=None),
        max_output_tokens=2048,
        transport=httpx.MockTransport(handler),
    )


def test_responses_contract_empty_candidates_and_usage():
    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer unit-test-secret"
        body = json.loads(request.content)
        assert body["store"] is False
        assert "reasoning" not in body
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"]["properties"]["ids"]["items"] == {"type": "string"}
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": '{"ids":[]}'}]}
                ],
                "usage": {"input_tokens": 5, "output_tokens": 4, "total_tokens": 9},
            },
        )

    schema = {
        "type": "object",
        "properties": {"ids": {"type": "array", "minItems": 0, "maxItems": 0}},
        "required": ["ids"],
        "additionalProperties": False,
    }
    result = asyncio.run(client(handler).generate(LlmRequest("instructions", "data", schema)))
    assert result.provider == "openai" and result.attempts == 1
    assert result.text == '{"ids":[]}' and result.usage.total_tokens == 9
    assert "items" not in schema["properties"]["ids"]


def test_sol_uses_low_reasoning_and_counts_only_visible_output():
    def handler(request):
        assert json.loads(request.content)["reasoning"] == {"effort": "low"}
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {"type": "message", "content": [{"type": "output_text", "text": "result"}]},
                ],
            },
        )

    model = client(handler)
    model._model = "gpt-6.1-sol"
    result = asyncio.run(model.generate(LlmRequest("instructions", "data")))
    assert result.text == "result" and result.model == "gpt-6.1-sol"


@pytest.mark.parametrize(
    "status,code,kind",
    [
        (401, "invalid_api_key", LlmErrorKind.AUTHENTICATION),
        (403, "forbidden", LlmErrorKind.AUTHENTICATION),
        (429, "insufficient_quota", LlmErrorKind.QUOTA_EXHAUSTED),
        (429, "rate_limit_exceeded", LlmErrorKind.RATE_LIMITED),
        (503, "upstream", LlmErrorKind.UPSTREAM),
    ],
)
def test_errors_are_sanitized_without_retries(status, code, kind):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"code": code, "message": "sensitive-provider-message"}}
        )

    with pytest.raises(LlmError) as error:
        asyncio.run(client(handler).generate(LlmRequest("private-system", "private-user")))
    assert error.value.kind == kind and len(calls) == 1
    assert "sensitive" not in str(error.value) and error.value.__context__ is None


@pytest.mark.parametrize(
    "payload,kind",
    [
        ({"status": "incomplete"}, LlmErrorKind.INCOMPLETE),
        (
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal"}]}],
            },
            LlmErrorKind.BLOCKED,
        ),
        ({"status": "completed", "output": []}, LlmErrorKind.MALFORMED_RESPONSE),
    ],
)
def test_rejects_unusable_responses(payload, kind):
    with pytest.raises(LlmError) as error:
        asyncio.run(
            client(lambda _: httpx.Response(200, json=payload)).generate(
                LlmRequest("system", "user")
            )
        )
    assert error.value.kind == kind
