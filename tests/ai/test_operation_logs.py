import asyncio
import json

import httpx
import pytest

from app.ai.client import LlmError, LlmRequest
from app.ai.limits import RequestLimiter
from tests.ai.test_gemini import Clock, Recorder, make_client, ok_body
from tests.test_operation_logs import CANARY, events


@pytest.mark.parametrize(
    "responses,retries,successes,valid",
    [
        ([httpx.Response(200, json=ok_body(CANARY))], 0, [True], True),
        ([httpx.Response(429), httpx.Response(200, json=ok_body(CANARY))], 1, [False, True], True),
        ([httpx.Response(503)], 2, [False, False, False], False),
        ([httpx.ReadTimeout(CANARY)], 0, [False], False),
        ([httpx.ConnectError(CANARY)], 0, [False], False),
        ([httpx.Response(200, json={"private": CANARY})], 0, [True], False),
    ],
)
def test_actual_application_attempts_and_http_success_are_distinct_from_parsing(
    capsys, responses, retries, successes, valid
):
    recorder = Recorder(*responses)
    client = make_client(recorder, Clock(), max_retries=retries)
    request = LlmRequest(system_instruction=CANARY, user_content=CANARY)
    if valid:
        assert asyncio.run(client.generate(request)).text == CANARY
    else:
        with pytest.raises(LlmError):
            asyncio.run(client.generate(request))
    records = events(capsys)
    assert [r["success"] for r in records] == successes
    assert len(recorder.requests) == sum(r["count"] for r in records)
    assert all(set(r) == {"event", "time", "count", "success"} for r in records)
    assert all(r["event"] == "llm_http_attempt" for r in records)
    assert CANARY not in json.dumps(records)


@pytest.mark.parametrize("blocked", ["key", "limit"])
def test_blocked_before_transport_produces_zero_attempts(capsys, blocked):
    recorder = Recorder(httpx.Response(200, json=ok_body()))
    limiter = RequestLimiter(per_minute=1, per_day=None)
    if blocked == "limit":
        limiter.acquire()
    client = make_client(
        recorder, Clock(), key=None if blocked == "key" else CANARY, limiter=limiter
    )
    with pytest.raises(LlmError):
        asyncio.run(client.generate(LlmRequest(system_instruction=CANARY, user_content=CANARY)))
    assert recorder.requests == [] and events(capsys) == []


def test_cancelled_transport_attempt_is_counted_and_cancel_is_preserved(capsys):
    async def run():
        started = asyncio.Event()

        async def handler(request):
            started.set()
            await asyncio.sleep(1000)

        client = make_client(handler, Clock())
        task = asyncio.create_task(
            client.generate(LlmRequest(system_instruction=CANARY, user_content=CANARY))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    records = events(capsys)
    assert len(records) == 1 and records[0]["success"] is False and records[0]["count"] == 1
    assert CANARY not in json.dumps(records)
