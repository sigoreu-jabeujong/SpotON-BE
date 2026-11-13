import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.ai.client import LlmError, LlmErrorKind, LlmRequest, LlmResult
from app.ai.gemini import GeminiClient
from app.ai.limits import RequestLimiter, RetryPolicy

SECRET_KEY = "SECRET-GEMINI-KEY"
SYSTEM = "SECRET-SYSTEM 지침"
USER = '{"radius": 500, "note": "SECRET-USER"}'
OUTPUT = '{"summary": "SECRET-OUTPUT"}'
MODEL = "gemini-3.5-flash-lite"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

Handler = Callable[[httpx.Request], httpx.Response]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def ok_body(
    text: str = OUTPUT, *, finish: str | None = "STOP", extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    candidate: dict[str, Any] = {"content": {"role": "model", "parts": [{"text": text}]}}
    if finish is not None:
        candidate["finishReason"] = finish
    body: dict[str, Any] = {
        "candidates": [candidate],
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 7,
            "totalTokenCount": 18,
        },
    }
    body.update(extra or {})
    return body


class Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def make_client(
    handler: Handler,
    clock: Clock,
    *,
    key: str | None = SECRET_KEY,
    model: str = MODEL,
    limiter: RequestLimiter | None = None,
    rng: float = 1.0,
    **policy: float,
) -> GeminiClient:
    values: dict[str, float] = {
        "request_timeout": 10,
        "time_budget": 20,
        "max_retries": 2,
        "base_delay": 1,
        "max_delay": 8,
    }
    values.update(policy)
    return GeminiClient(
        api_key=key,
        model=model,
        policy=RetryPolicy(
            request_timeout=values["request_timeout"],
            time_budget=values["time_budget"],
            max_retries=int(values["max_retries"]),
            base_delay=values["base_delay"],
            max_delay=values["max_delay"],
        ),
        limiter=limiter or RequestLimiter(per_minute=None, per_day=None),
        max_output_tokens=2048,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        rng=lambda: rng,
    )


def request(schema: dict[str, Any] | None = None) -> LlmRequest:
    return LlmRequest(system_instruction=SYSTEM, user_content=USER, response_json_schema=schema)


def generate(client: GeminiClient, req: LlmRequest | None = None) -> LlmResult:
    return asyncio.run(client.generate(req or request()))


def failure(client: GeminiClient) -> LlmError:
    with pytest.raises(LlmError) as raised:
        generate(client)
    return raised.value


def test_success_sends_expected_request_and_maps_result() -> None:
    clock = Clock()
    recorder = Recorder(httpx.Response(200, json=ok_body()))
    result = generate(make_client(recorder, clock))

    assert result.text == OUTPUT
    assert result.provider == "google"
    assert result.model == MODEL
    assert result.attempts == 1
    assert (result.usage.prompt_tokens, result.usage.output_tokens) == (11, 7)
    assert result.usage.total_tokens == 18

    sent = recorder.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == URL
    assert sent.headers["x-goog-api-key"] == SECRET_KEY
    assert SECRET_KEY not in str(sent.url)
    body = json.loads(sent.content)
    assert body == {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": USER}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 2048},
    }
    assert clock.sleeps == []


def test_schema_and_output_token_override_are_sent() -> None:
    recorder = Recorder(httpx.Response(200, json=ok_body()))
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    req = LlmRequest(
        system_instruction=SYSTEM,
        user_content=USER,
        response_json_schema=schema,
        max_output_tokens=512,
    )
    generate(make_client(recorder, Clock()), req)
    config = json.loads(recorder.requests[0].content)["generationConfig"]
    assert config["responseJsonSchema"] == schema
    assert config["maxOutputTokens"] == 512


def test_text_parts_are_joined_and_thought_parts_skipped() -> None:
    body = ok_body()
    body["candidates"][0]["content"]["parts"] = [
        {"text": "SECRET-THINKING", "thought": True},
        {"text": '{"summary": '},
        {"text": '"ok"}'},
    ]
    result = generate(make_client(Recorder(httpx.Response(200, json=body)), Clock()))
    assert result.text == '{"summary": "ok"}'


def test_missing_usage_is_null() -> None:
    body = ok_body()
    del body["usageMetadata"]
    result = generate(make_client(Recorder(httpx.Response(200, json=body)), Clock()))
    assert result.usage.total_tokens is None


def test_429_then_success_retries_with_bounded_backoff() -> None:
    clock = Clock()
    recorder = Recorder(
        httpx.Response(429, json={"error": {"message": "SECRET-UPSTREAM"}}),
        httpx.Response(429),
        httpx.Response(200, json=ok_body()),
    )
    result = generate(make_client(recorder, clock))
    assert result.attempts == 3
    assert clock.sleeps == [1.0, 2.0]


def test_persistent_429_stops_after_max_retries() -> None:
    clock = Clock()
    recorder = Recorder(httpx.Response(429))
    error = failure(make_client(recorder, clock, max_retries=2))
    assert error.kind is LlmErrorKind.RATE_LIMITED
    assert len(recorder.requests) == 3
    assert clock.sleeps == [1.0, 2.0]


def test_zero_retries_calls_once() -> None:
    recorder = Recorder(httpx.Response(503))
    error = failure(make_client(recorder, Clock(), max_retries=0))
    assert error.kind is LlmErrorKind.UPSTREAM
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("status", [500, 503, 504])
def test_transient_server_errors_are_retried(status: int) -> None:
    recorder = Recorder(httpx.Response(status), httpx.Response(200, json=ok_body()))
    assert generate(make_client(recorder, Clock())).attempts == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 502])
def test_client_errors_are_not_retried(status: int) -> None:
    clock = Clock()
    recorder = Recorder(httpx.Response(status))
    error = failure(make_client(recorder, clock))
    assert error.kind is LlmErrorKind.UPSTREAM
    assert len(recorder.requests) == 1
    assert clock.sleeps == []


def test_timeout_and_network_errors_are_retried() -> None:
    recorder = Recorder(
        httpx.ReadTimeout("SECRET-TIMEOUT"),
        httpx.ConnectError("SECRET-CONNECT"),
        httpx.Response(200, json=ok_body()),
    )
    assert generate(make_client(recorder, Clock())).attempts == 3


def test_persistent_timeout_reports_timeout() -> None:
    error = failure(make_client(Recorder(httpx.ReadTimeout("t")), Clock()))
    assert error.kind is LlmErrorKind.TIMEOUT


def test_backoff_that_exceeds_budget_is_not_slept() -> None:
    clock = Clock()
    recorder = Recorder(httpx.Response(429))
    error = failure(make_client(recorder, clock, time_budget=3, base_delay=4))
    assert error.kind is LlmErrorKind.RATE_LIMITED
    assert len(recorder.requests) == 1
    assert clock.sleeps == []


def test_slow_attempt_consumes_budget_before_retry() -> None:
    clock = Clock()

    def slow(request: httpx.Request) -> httpx.Response:
        del request
        clock.now += 25
        return httpx.Response(503)

    error = failure(make_client(slow, clock, time_budget=20))
    assert error.kind is LlmErrorKind.TIMEOUT
    assert clock.sleeps == []


def test_success_after_monotonic_deadline_is_rejected() -> None:
    clock = Clock()

    def late(_request: httpx.Request) -> httpx.Response:
        clock.now += 21
        return httpx.Response(200, json=ok_body())

    error = failure(make_client(late, clock, time_budget=20))
    assert error.kind is LlmErrorKind.TIMEOUT
    assert error.__context__ is None


def event_client(
    handler,
    *,
    request_timeout=1,
    time_budget=0.01,
    max_retries=0,
    sleep=asyncio.sleep,
    monotonic=time.monotonic,
):
    return GeminiClient(
        api_key=SECRET_KEY,
        model=MODEL,
        policy=RetryPolicy(request_timeout, time_budget, max_retries, 0.001, 0.001),
        limiter=RequestLimiter(per_minute=None, per_day=None),
        max_output_tokens=10,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        monotonic=monotonic,
        rng=lambda: 1,
    )


def test_total_budget_cancels_pending_transport_without_exception_context() -> None:
    async def scenario():
        cancelled = asyncio.Event()

        async def pending(_request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with pytest.raises(LlmError) as caught:
            await asyncio.wait_for(event_client(pending).generate(request()), timeout=2)
        assert caught.value.kind is LlmErrorKind.TIMEOUT
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert cancelled.is_set()

    asyncio.run(scenario())


def test_attempt_timeout_retries_when_overall_budget_remains() -> None:
    async def scenario():
        calls = 0
        cancelled = asyncio.Event()

        async def handler(_request):
            nonlocal calls
            calls += 1
            if calls == 1:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return httpx.Response(200, json=ok_body())

        result = await asyncio.wait_for(
            event_client(
                handler,
                request_timeout=0.01,
                time_budget=1,
                max_retries=1,
            ).generate(request()),
            timeout=2,
        )
        assert result.attempts == calls == 2
        assert cancelled.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("first_response_delay", [0.0, 0.05])
def test_overall_budget_cancels_retry_sleep(first_response_delay: float) -> None:
    """The asyncio budget must cancel a retry sleep that is already in progress.

    The deadline clock is frozen so the first 429 always reaches the retry sleep, however long
    it takes to answer (#100: a 10ms real budget expired before the sleep under load). Only the
    real asyncio budget can then end the blocked sleep.
    """

    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_sleep(_delay):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def throttled(_request):
            await asyncio.sleep(first_response_delay)
            return httpx.Response(429)

        with pytest.raises(LlmError) as caught:
            await asyncio.wait_for(
                event_client(
                    throttled,
                    max_retries=2,
                    time_budget=0.5,
                    sleep=blocked_sleep,
                    monotonic=lambda: 0.0,
                ).generate(request()),
                timeout=5,
            )
        assert caught.value.kind is LlmErrorKind.TIMEOUT
        assert entered.is_set() and cancelled.is_set()

    asyncio.run(scenario())


def test_caller_cancellation_propagates() -> None:
    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def pending(_request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(event_client(pending, time_budget=10).generate(request()))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(scenario())


def test_request_timeout_shrinks_to_remaining_budget() -> None:
    clock = Clock()
    timeouts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        if len(timeouts) == 1:
            clock.now += 15
            return httpx.Response(503)
        return httpx.Response(200, json=ok_body())

    generate(make_client(handler, clock, time_budget=20, request_timeout=10, rng=0.5))
    assert timeouts[0] == 10
    assert timeouts[1] == pytest.approx(4.5)


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(200, content=b"not json"), LlmErrorKind.MALFORMED_RESPONSE),
        (httpx.Response(200, json=[]), LlmErrorKind.MALFORMED_RESPONSE),
        (httpx.Response(200, json={"candidates": []}), LlmErrorKind.MALFORMED_RESPONSE),
        (
            httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
            LlmErrorKind.BLOCKED,
        ),
        (httpx.Response(200, json=ok_body(finish="SAFETY")), LlmErrorKind.BLOCKED),
        (httpx.Response(200, json=ok_body(finish="SPII")), LlmErrorKind.BLOCKED),
        (httpx.Response(200, json=ok_body(finish="MAX_TOKENS")), LlmErrorKind.INCOMPLETE),
        (httpx.Response(200, json=ok_body(finish="OTHER")), LlmErrorKind.MALFORMED_RESPONSE),
        (httpx.Response(200, json=ok_body(finish=None)), LlmErrorKind.MALFORMED_RESPONSE),
        (httpx.Response(200, json=ok_body(text="  ")), LlmErrorKind.MALFORMED_RESPONSE),
        (
            httpx.Response(200, json={"candidates": [{"finishReason": "STOP"}]}),
            LlmErrorKind.MALFORMED_RESPONSE,
        ),
    ],
)
def test_unusable_responses_are_classified_without_retry(
    response: httpx.Response, kind: LlmErrorKind
) -> None:
    recorder = Recorder(response)
    error = failure(make_client(recorder, Clock()))
    assert error.kind is kind
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    ("key", "model"),
    [(None, MODEL), ("", MODEL), (SECRET_KEY, ""), (SECRET_KEY, "../x"), (SECRET_KEY, "A?b")],
)
def test_missing_key_or_invalid_model_never_calls_provider(key: str | None, model: str) -> None:
    recorder = Recorder(httpx.Response(200, json=ok_body()))
    error = failure(make_client(recorder, Clock(), key=key, model=model))
    assert error.kind is LlmErrorKind.NOT_CONFIGURED
    assert recorder.requests == []


def test_retries_consume_request_limits() -> None:
    clock = Clock()
    limiter = RequestLimiter(
        per_minute=2,
        per_day=None,
        monotonic=clock.monotonic,
        now=lambda: datetime(2026, 11, 11, tzinfo=UTC),
    )
    recorder = Recorder(httpx.Response(429))
    error = failure(make_client(recorder, clock, limiter=limiter))
    assert error.kind is LlmErrorKind.RATE_LIMITED
    assert len(recorder.requests) == 2


def test_exhausted_daily_quota_never_calls_provider() -> None:
    clock = Clock()
    limiter = RequestLimiter(
        per_minute=None,
        per_day=1,
        monotonic=clock.monotonic,
        now=lambda: datetime(2026, 11, 11, tzinfo=UTC),
    )
    recorder = Recorder(httpx.Response(200, json=ok_body()))
    client = make_client(recorder, clock, limiter=limiter)
    generate(client)
    error = failure(client)
    assert error.kind is LlmErrorKind.QUOTA_EXHAUSTED
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.ReadTimeout("SECRET-TIMEOUT " + USER),
        httpx.ConnectError("SECRET-CONNECT " + USER),
        httpx.Response(403, json={"error": {"message": "SECRET-UPSTREAM " + SECRET_KEY}}),
        httpx.Response(200, content=b"SECRET-NOT-JSON"),
        httpx.Response(200, json=ok_body(finish="SAFETY")),
    ],
)
def test_errors_do_not_expose_secrets_or_raw_text(
    response: httpx.Response | Exception, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        error = failure(make_client(Recorder(response), Clock(), max_retries=0))
    assert error.__cause__ is None
    assert error.__context__ is None
    exposed = " ".join([str(error), repr(error), caplog.text])
    for secret in ("SECRET", SECRET_KEY, SYSTEM, USER, OUTPUT):
        assert secret not in exposed
