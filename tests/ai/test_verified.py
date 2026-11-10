import asyncio
import json
from typing import Any

import pytest

from app.ai.client import LlmError, LlmErrorKind, LlmRequest, LlmResult, LlmUsage
from app.ai.verified import AiVerifyFailedError, VerifiedOutput, generate_verified
from app.ai.verifier import VerifyFailure
from app.core.errors import ERROR_SPECS
from app.schemas.common import ErrorCode

CONTEXT: dict[str, Any] = {"radius_m": 500, "indicators": [{"id": "count", "value": 12}]}
GOOD = json.dumps({"summary": "반경 500m 안에 12곳이 있습니다."}, ensure_ascii=False)
BAD = json.dumps({"summary": "SECRET 성공률 99%"}, ensure_ascii=False)
REQUEST = LlmRequest(system_instruction="SECRET-SYSTEM", user_content="SECRET-USER")


class FakeClient:
    provider = "fake"
    model = "fake-model"

    def __init__(self, *outputs: str | LlmError) -> None:
        self.outputs = list(outputs)
        self.requests: list[LlmRequest] = []

    async def generate(self, request: LlmRequest) -> LlmResult:
        self.requests.append(request)
        output = self.outputs.pop(0)
        if isinstance(output, LlmError):
            raise output
        return LlmResult(
            text=output, provider=self.provider, model=self.model, usage=LlmUsage(), attempts=1
        )


def run(client: FakeClient) -> VerifiedOutput:
    return asyncio.run(generate_verified(client, REQUEST, context=CONTEXT))


def test_first_generation_passes() -> None:
    client = FakeClient(GOOD)
    output = run(client)
    assert output.generations == 1
    assert output.data == json.loads(GOOD)
    assert output.result.text == GOOD
    assert client.requests == [REQUEST]


def test_failed_first_generation_is_regenerated_once_with_same_request() -> None:
    client = FakeClient(BAD, GOOD)
    output = run(client)
    assert output.generations == 2
    assert client.requests == [REQUEST, REQUEST]


def test_second_failure_raises_ai_verify_failed_without_raw_text() -> None:
    client = FakeClient(BAD, BAD, GOOD)
    with pytest.raises(AiVerifyFailedError) as raised:
        run(client)
    error = raised.value
    assert len(client.requests) == 2
    assert error.failures == (VerifyFailure.UNKNOWN_NUMBER, VerifyFailure.FORBIDDEN_EXPRESSION)
    app_error = error.to_app_error()
    assert app_error.code is ErrorCode.AI_VERIFY_FAILED
    assert ERROR_SPECS[app_error.code][0] == 503
    assert error.__context__ is None
    assert error.__cause__ is None
    for text in (str(error), repr(error)):
        assert "SECRET" not in text
        assert "unknown_number" in text


def test_failures_of_last_generation_are_reported() -> None:
    with pytest.raises(AiVerifyFailedError) as raised:
        run(FakeClient("not json", "[]"))
    assert raised.value.failures == (VerifyFailure.NOT_OBJECT,)


@pytest.mark.parametrize(
    "outputs", [(LlmError(LlmErrorKind.RATE_LIMITED),), (BAD, LlmError(LlmErrorKind.TIMEOUT))]
)
def test_provider_errors_propagate_without_extra_generation(outputs: tuple[Any, ...]) -> None:
    client = FakeClient(*outputs)
    with pytest.raises(LlmError):
        run(client)
    assert len(client.requests) == len(outputs)


def test_verified_output_repr_hides_data() -> None:
    output = run(FakeClient(GOOD))
    assert "12곳" not in repr(output)
