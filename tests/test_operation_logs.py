import asyncio
import json
import logging
from uuid import UUID, uuid4

import pytest
from fastapi import Response

from app.core import operations
from app.core.config import Settings
from app.core.request_logging import OperationLogMiddleware
from app.main import create_app

CANARY = "RAW_INPUT_CANARY"


def events(capsys):
    return [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]


def test_api_fields_statuses_and_no_input_echo(client, capsys):
    @client.app.get("/probe/crash")
    def crash():
        raise RuntimeError(CANARY)

    responses = [
        client.get(
            "/api/health",
            params={"address": CANARY, "lat": "37.5123456"},
            headers={"X-Request-ID": CANARY, "Authorization": CANARY},
        ),
        client.get("/api/risk", params={"building_key": CANARY}),
        client.post("/api/risk/interpret", json={"query": {"address": CANARY}}),
        client.get(f"/{CANARY}/37.5123456"),
        client.get("/probe/crash"),
        client.options(
            "/api/health",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        ),
    ]
    records = events(capsys)
    assert [r.status_code for r in responses] == [200, 422, 422, 404, 500, 200]
    assert [r["status_code"] for r in records] == [200, 422, 422, 404, 500, 200]
    assert [r["path"] for r in records] == [
        "/api/health",
        "/api/risk",
        "/api/risk/interpret",
        "unmatched",
        "unmatched",
        "/api/health",
    ]
    assert len({r["request_id"] for r in records}) == len(records)
    for r in records:
        assert set(r) == {
            "event",
            "time",
            "path",
            "status_code",
            "duration_ms",
            "request_id",
            "response_complete",
        }
        assert r["event"] == "api_request" and r["response_complete"] is True
        assert UUID(r["request_id"]).version == 4
        assert r["duration_ms"] >= 0
    assert CANARY not in json.dumps(records) and "37.5123456" not in json.dumps(records)
    assert all("x-request-id" not in r.headers for r in responses)


@pytest.mark.parametrize(
    "path", ["/api/health/", "/API/HEALTH", "/%52AW_INPUT_CANARY", "/probe/" + CANARY]
)
def test_path_variants_do_not_echo_raw_paths(client, capsys, path):
    client.get(path, follow_redirects=False)
    record = events(capsys)[0]
    assert record["path"] == "unmatched"
    assert CANARY not in json.dumps(record)


@pytest.mark.parametrize(
    "mode,status,complete",
    [
        ("ok", 200, True),
        ("before", None, False),
        ("after", 200, False),
        ("start_send", None, False),
        ("body_send", 200, False),
        ("cancel", None, False),
        ("after_final", 200, True),
    ],
)
def test_asgi_streaming_cancellation_and_transport_truth(capsys, mode, status, complete):
    async def application(scope, receive, send):
        if mode == "before":
            raise RuntimeError(CANARY)
        if mode == "cancel":
            raise asyncio.CancelledError(CANARY)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if mode == "after":
            raise RuntimeError(CANARY)
        await send({"type": "http.response.body", "body": CANARY.encode()})
        if mode == "after_final":
            raise RuntimeError(CANARY)

    async def receive():
        raise AssertionError("middleware must not read request body")

    async def send(message):
        if (mode == "start_send" and message["type"] == "http.response.start") or (
            mode == "body_send" and message["type"] == "http.response.body"
        ):
            raise RuntimeError(CANARY)

    task = OperationLogMiddleware(application)(
        {
            "type": "http",
            "path": "/api/health",
            "query_string": CANARY.encode(),
            "headers": [(b"x-request-id", CANARY.encode())],
        },
        receive,
        send,
    )
    if mode == "ok":
        asyncio.run(task)
    else:
        with pytest.raises(
            asyncio.CancelledError if mode == "cancel" else RuntimeError, match=CANARY
        ):
            asyncio.run(task)
    records = events(capsys)
    assert len(records) == 1
    assert records[0]["status_code"] == status and records[0]["response_complete"] is complete
    assert CANARY not in json.dumps(records)


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_non_http_passes_through(scope_type, capsys):
    original = {"type": scope_type}
    called = []

    async def application(scope, receive, send):
        assert scope is original
        called.append(scope_type)

    async def unused():
        raise AssertionError

    asyncio.run(OperationLogMiddleware(application)(original, unused, unused))
    assert called == [scope_type] and events(capsys) == []


def test_concurrent_requests_have_distinct_server_ids(capsys):
    async def application(scope, receive, send):
        await asyncio.sleep(0)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def unused(*args):
        pass

    async def run():
        wrapped = OperationLogMiddleware(application)
        await asyncio.gather(
            *(wrapped({"type": "http", "path": "/api/health"}, unused, unused) for _ in range(20))
        )

    asyncio.run(run())
    records = events(capsys)
    assert len(records) == 20 and len({r["request_id"] for r in records}) == 20


def test_empty_body_and_head_complete(client, capsys):
    @client.app.api_route("/probe/head", methods=["HEAD"])
    def head():
        return Response()

    @client.app.get("/probe/empty")
    def empty():
        return Response(status_code=204)

    assert client.head("/probe/head").status_code == 200
    assert client.get("/probe/empty").status_code == 204
    assert all(r["response_complete"] for r in events(capsys))


@pytest.mark.parametrize("sink", [None, "broken", "closed"])
def test_sink_failures_do_not_change_api_or_etl_result(client, monkeypatch, sink):
    class Broken:
        def write(self, value):
            raise BrokenPipeError(CANARY)

        def flush(self):
            raise ValueError(CANARY)

    import io

    destination = None if sink is None else Broken() if sink == "broken" else io.StringIO()
    if sink == "closed":
        destination.close()
    with monkeypatch.context() as patch:
        patch.setattr(operations.sys, "stderr", destination)

        @operations.logged_import("localdata")
        def work():
            return {"rows": 2}

        assert client.get("/api/health").status_code == 200
        assert work() == {"rows": 2}
        operations.llm_attempt(success=True)
    assert operations._RUN.get() is None


def test_non_finite_measurements_and_unsafe_helper_values(capsys):
    operations.api_event(
        path=CANARY, status=9999, duration=float("nan"), request_id=str(uuid4()), complete=True
    )
    record = events(capsys)[0]
    assert record["path"] == "unmatched" and record["status_code"] is None
    assert record["duration_ms"] is None and CANARY not in json.dumps(record)
    operations.api_event(
        path="/api/health", status=200, duration=0, request_id=CANARY, complete=True
    )
    assert events(capsys) == []


def test_default_access_logger_disabled(monkeypatch):
    logger = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(logger, "disabled", False)
    create_app(Settings(_env_file=None))
    assert logger.disabled is True


def test_id_failure_drops_events_without_changing_work(client, monkeypatch, capsys):
    def unavailable():
        raise OSError(CANARY)

    monkeypatch.setattr(operations, "uuid4", unavailable)

    @operations.logged_import("localdata")
    def work():
        return {"rows": 2}

    assert client.get("/api/health").status_code == 200 and work() == {"rows": 2}
    assert events(capsys) == [] and operations._RUN.get() is None
