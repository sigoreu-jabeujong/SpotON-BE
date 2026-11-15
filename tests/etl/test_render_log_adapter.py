import gzip
import json
import logging
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from etl.operation_logs import archive, render
from etl.operation_logs.__main__ import ArgumentsError
from etl.operation_logs.validation import parse_record

OWNER = "tea-" + "a" * 20
SERVICE = "srv-" + "b" * 20
KEY = SecretStr("rnd_CREDENTIAL_CANARY")
START, END = "2026-11-14T12:00:00Z", "2026-11-14T12:01:00Z"
T1, T2 = "2026-11-14T12:00:10.123456789Z", "2026-11-14T12:00:20.123456789Z"
CURSOR = "2026-11-14T12:00:10.123456790Z"


def event():
    return json.dumps(
        {
            "time": "2026-11-14T12:00:10+00:00",
            "event": "api_request",
            "path": "/api/health",
            "status_code": 200,
            "duration_ms": 1,
            "request_id": str(uuid4()),
            "response_complete": True,
        }
    )


def row(stamp=T1, message=None):
    return {
        "id": str(uuid4()),
        "timestamp": stamp,
        "message": event() if message is None else message,
        "labels": [{"name": "resource", "value": SERVICE}, {"name": "type", "value": "app"}],
    }


def page(rows, more=False, cursor=CURSOR):
    return {"logs": rows, "hasMore": more, "nextStartTime": cursor, "nextEndTime": END}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "events.sqlite3"
    archive.initialize(path, execute=True)
    return path


def source(pages, service=None):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/services/" + SERVICE:
            return httpx.Response(
                200,
                json=service
                if service is not None
                else {"id": SERVICE, "ownerId": OWNER, "type": "web_service"},
            )
        value = pages[len(calls) - 2]
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    return httpx.MockTransport(handler), calls


def run(db, pages, **kw):
    transport, calls = source(pages)
    result = render.run_window(db, OWNER, SERVICE, START, END, KEY, transport=transport, **kw)
    return result, calls


def test_complete_window_dry_execute_replay_and_filters(db):
    sample = row()
    pages = [page([sample], True), page([row(T2)])]
    before = db.read_bytes()
    dry, calls = run(db, pages)
    assert db.read_bytes() == before and dry["archive"]["would_insert"] == 2
    assert dry["api_window_complete"] and dry["coverage_verified"] is False
    assert dry["provenance"] == "schema_match_only" and dry["api_rows"] == dry["forwarded"] == 2
    for request in calls:
        assert (
            request.method == "GET"
            and request.url.scheme == "https"
            and request.url.host == "api.render.com"
        )
        assert request.headers["authorization"] == "Bearer " + KEY.get_secret_value()
        assert request.headers["accept-encoding"] == "identity"
        assert KEY.get_secret_value() not in str(request.url)
    for request in calls[1:]:
        assert request.url.params["resource"] == SERVICE and request.url.params["ownerId"] == OWNER
        assert request.url.params["type"] == "app" and request.url.params["direction"] == "forward"
        assert request.url.params["limit"] == "100" and request.url.params["endTime"] == END
    assert calls[2].url.params["startTime"] == CURSOR
    result, _ = run(db, pages, execute=True)
    assert result["archive"]["inserted"] == 2
    replay, _ = run(db, pages, execute=True)
    assert replay["archive"]["duplicate"] == 2 and replay["archive"]["inserted"] == 0


@pytest.mark.parametrize(
    "message",
    ["RAW_CANARY", "{}", "[]", "{}\n" + event(), "\r" + event(), "\0" + event(), "x" * 4097],
)
def test_unsafe_messages_discarded_not_split(db, message):
    result, _ = run(db, [page([row(message=message), row(T2)])], execute=True)
    assert result["api_rows"] == 2 and result["rejected_messages"] == 1 and result["forwarded"] == 1
    assert result["archive"]["rejected"] == 0 and result["archive"]["inserted"] == 1
    assert b"RAW_CANARY" not in db.read_bytes()


def test_canonical_reparse_hash_and_nanoseconds():
    original = parse_record(event().encode())
    assert original.event_hash == parse_record(original.record.encode()).event_hash
    assert render.nanoseconds(CURSOR) - render.nanoseconds(T1) == 1
    assert render.nanoseconds("2026-11-14T12:00:10.1Z") == render.nanoseconds(
        "2026-11-14T12:00:10.100000000+00:00"
    )


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-11-14T12:00:10.1234567890Z",
        "2026-11-14T12:00:60Z",
        "2026-11-14T12:00:10+09:00",
        "2026-11-14T12:00:10",
        "not-time",
    ],
)
def test_timestamp_rejection(stamp):
    with pytest.raises(render.RenderLogError):
        render.nanoseconds(stamp)


@pytest.mark.parametrize(
    "which", ["resource", "type", "duplicate", "outside", "order", "structure"]
)
def test_metadata_scope_failure_does_not_write(db, which):
    a, b = row(), row(T2)
    if which == "resource":
        a["labels"][0]["value"] = "srv-" + "c" * 20
    if which == "type":
        a["labels"][1]["value"] = "request"
    if which == "duplicate":
        a["labels"].append(a["labels"][0])
    if which == "outside":
        a["timestamp"] = "2026-11-14T11:00:00Z"
    if which == "order":
        a, b = b, a
    if which == "structure":
        a.pop("id")
    before = db.read_bytes()
    with pytest.raises(render.RenderLogError):
        run(db, [page([a, b])], execute=True)
    assert db.read_bytes() == before


@pytest.mark.parametrize(
    "cursor,end,reason",
    [
        (START, END, "cursor_stalled"),
        ("2026-11-14T12:00:10.123456791Z", END, "cursor_gap"),
        (CURSOR, "2026-11-14T12:02:00Z", "cursor_scope"),
        ("2026-11-14T12:01:01Z", END, "cursor_scope"),
    ],
)
def test_bad_cursor_rolls_back_whole_window(db, cursor, end, reason):
    p = page([row()], True, cursor)
    p["nextEndTime"] = end
    before = db.read_bytes()
    with pytest.raises(render.RenderLogError, match=reason):
        run(db, [p], execute=True)
    assert db.read_bytes() == before


def test_inclusive_boundary_deduplicates(db):
    sample = row()
    p = page([sample], True, T1)
    result, _ = run(db, [p, page([sample, row(T2)])], execute=True)
    assert result["archive"]["inserted"] == 2 and result["archive"]["duplicate"] == 1


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "api_authentication"),
        (403, "api_authentication"),
        (429, "api_rate_limit"),
        (302, "api_http"),
        (500, "api_http"),
    ],
)
def test_http_failures_no_redirect_retry_or_write(db, status, reason):
    before = db.read_bytes()
    transport, calls = source(
        [
            httpx.Response(
                status, headers={"Location": "https://evil.invalid"}, text=KEY.get_secret_value()
            )
        ]
    )
    with pytest.raises(render.RenderLogError, match=reason):
        render.run_window(db, OWNER, SERVICE, START, END, KEY, transport=transport, execute=True)
    assert len(calls) == 2 and db.read_bytes() == before


@pytest.mark.parametrize("index", [0, 1, 2])
def test_failure_at_any_page_preserves_database(db, index):
    times = ["2026-11-14T12:00:10Z", "2026-11-14T12:00:20Z", "2026-11-14T12:00:30Z"]
    cursors = ["2026-11-14T12:00:10.000000001Z", "2026-11-14T12:00:20.000000001Z", CURSOR]
    pages = [page([row(t)], i < 2, cursors[i]) for i, t in enumerate(times)]
    pages[index] = httpx.ReadTimeout(KEY.get_secret_value())
    before = db.read_bytes()
    with pytest.raises(httpx.ReadTimeout):
        run(db, pages, execute=True)
    assert db.read_bytes() == before and not Path(str(db) + "-journal").exists()


@pytest.mark.parametrize(
    "field,value", [("id", "other"), ("ownerId", "other"), ("type", "static_site")]
)
def test_service_mismatch_does_not_fetch_logs(db, field, value):
    info = {"id": SERVICE, "ownerId": OWNER, "type": "web_service", field: value}
    transport, calls = source([], info)
    with pytest.raises(render.RenderLogError, match="service_scope"):
        render.run_window(db, OWNER, SERVICE, START, END, KEY, transport=transport, execute=True)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "../../logs"),
        ("service", "srv-/other"),
        ("start", END),
        ("end", "2999-01-01T00:00:00Z"),
        ("start", "2026-11-14T10:00:00Z"),
    ],
)
def test_arguments_before_network(db, field, value):
    args = {"owner": OWNER, "service": SERVICE, "start": START, "end": END, field: value}
    transport, calls = source([])
    with pytest.raises(ArgumentsError):
        render.run_window(db, **args, key=KEY, transport=transport)
    assert not calls


@pytest.mark.parametrize("key", ["", "short", "rnd_bad key", "rnd_bad\nkey", "rnd_한글키키키키"])
def test_credential_rejected_before_network(db, key):
    transport, calls = source([])
    with pytest.raises(render.RenderLogError, match="configuration"):
        render.run_window(db, OWNER, SERVICE, START, END, SecretStr(key), transport=transport)
    assert not calls


@pytest.mark.parametrize(
    "body", [b'{"logs":[],"logs":[]}', b'{"x":NaN}', b'{"x":1e400}', b"[" * 2000]
)
def test_malformed_json_no_write(db, body):
    response = httpx.Response(200, content=body, headers={"Content-Type": "application/json"})
    with pytest.raises(render.RenderLogError, match="api_payload"):
        run(db, [response], execute=True)


def test_compression_and_body_cap(db, monkeypatch):
    encoded = gzip.compress(json.dumps(page([row()])).encode())
    response = httpx.Response(
        200,
        content=encoded,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    with pytest.raises(render.RenderLogError, match="api_payload"):
        run(db, [response])
    monkeypatch.setattr(render, "MAX_TOTAL", 1)
    with pytest.raises(render.RenderLogError, match="response_limit"):
        run(db, [page([])])


def test_page_and_row_limits(db, monkeypatch):
    monkeypatch.setattr(render, "MAX_PAGES", 1)
    before = db.read_bytes()
    with pytest.raises(render.RenderLogError, match="page_limit"):
        run(db, [page([row()], True)], execute=True)
    assert db.read_bytes() == before
    monkeypatch.setattr(render, "MAX_ROWS", 0)
    with pytest.raises(render.RenderLogError, match="row_limit"):
        run(db, [page([row()])], execute=True)


def test_budget_interrupt_and_archive_invariant_before_write(db, monkeypatch):
    transport, calls = source([page([])])
    monkeypatch.setattr(render, "NETWORK_SECONDS", 0)
    with pytest.raises(render.RenderLogError, match="network_budget"):
        render.run_window(db, OWNER, SERVICE, START, END, KEY, transport=transport)
    assert not calls
    monkeypatch.setattr(render, "NETWORK_SECONDS", 30)
    before = db.read_bytes()
    monkeypatch.setattr(
        archive, "ingest", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(KeyboardInterrupt):
        run(db, [page([row()])], execute=True)
    assert db.read_bytes() == before


def test_cli_no_secrets_or_http_logging(db, monkeypatch, capsys, caplog):
    old_disable = logging.root.manager.disable

    def fail(*a, **k):
        assert logging.root.manager.disable >= logging.CRITICAL
        logging.getLogger("httpcore.connection").critical(KEY.get_secret_value())
        raise httpx.ReadTimeout(KEY.get_secret_value())

    monkeypatch.setattr(render, "run_window", fail)
    monkeypatch.setenv("RENDER_API_KEY", KEY.get_secret_value())
    args = [
        "--db",
        str(db),
        "--owner-id",
        OWNER,
        "--service-id",
        SERVICE,
        "--start",
        START,
        "--end",
        END,
    ]
    assert render.main(args) == 1
    out = capsys.readouterr()
    assert json.loads(out.out)["error"] == "api_network" and not out.err
    assert KEY.get_secret_value() not in out.out + out.err + caplog.text
    assert logging.root.manager.disable == old_disable
    assert render.main(["--api-key", KEY.get_secret_value()]) == 2
    assert KEY.get_secret_value() not in capsys.readouterr().out


def test_empty_window_is_not_zero_coverage_proof(db):
    result, _ = run(db, [page([])])
    assert result["api_rows"] == result["forwarded"] == 0 and result["api_window_complete"]
    assert not result["coverage_verified"] and result["archive"]["lines"] == 0


def test_page_body_limit_preserves_file(db):
    before = db.read_bytes()
    response = httpx.Response(
        200, content=b" " * (render.MAX_BODY + 1), headers={"Content-Type": "application/json"}
    )
    with pytest.raises(render.RenderLogError, match="response_limit"):
        run(db, [response], execute=True)
    assert db.read_bytes() == before


def test_compressed_response_is_refused_without_reading_stream(db):
    class Unreadable(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("compressed source must not be decoded")
            yield b""

    response = httpx.Response(
        200,
        stream=Unreadable(),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    with pytest.raises(render.RenderLogError, match="api_payload"):
        run(db, [response], execute=True)


def test_network_budget_during_chunk_has_no_partial_write(db, monkeypatch):
    clock = {"value": 0.0}
    monkeypatch.setattr(render.time, "monotonic", lambda: clock["value"])

    class Delayed(httpx.SyncByteStream):
        def __iter__(self):
            clock["value"] = 31.0
            yield b" " * 8192

    response = httpx.Response(200, stream=Delayed(), headers={"Content-Type": "application/json"})
    before = db.read_bytes()
    with pytest.raises(render.RenderLogError, match="network_budget"):
        run(db, [response], execute=True)
    assert db.read_bytes() == before


def test_client_ignores_environment_proxy_and_redirects(db, monkeypatch):
    original = httpx.Client
    options = []

    def client(*args, **kw):
        options.append(kw)
        return original(*args, **kw)

    monkeypatch.setattr(render.httpx, "Client", client)
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.invalid:8080")
    run(db, [page([])])
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False


def test_non_json_content_type_preserves_file(db):
    before = db.read_bytes()
    response = httpx.Response(200, text="RAW_CANARY", headers={"Content-Type": "text/plain"})
    with pytest.raises(render.RenderLogError, match="api_payload"):
        run(db, [response], execute=True)
    assert db.read_bytes() == before


def test_service_response_limit_preserves_file(db):
    before = db.read_bytes()

    def handler(request):
        return httpx.Response(
            200,
            content=b" " * (render.SERVICE_BODY + 1),
            headers={"Content-Type": "application/json"},
        )

    with pytest.raises(render.RenderLogError, match="response_limit"):
        render.run_window(
            db,
            OWNER,
            SERVICE,
            START,
            END,
            KEY,
            execute=True,
            transport=httpx.MockTransport(handler),
        )
    assert db.read_bytes() == before


def test_empty_more_page_is_stalled(db):
    before = db.read_bytes()
    with pytest.raises(render.RenderLogError, match="cursor_stalled"):
        run(db, [page([], True)], execute=True)
    assert db.read_bytes() == before


def test_cursor_before_last_row_is_rejected(db):
    before = db.read_bytes()
    with pytest.raises(render.RenderLogError, match="cursor_scope"):
        run(db, [page([row()], True, "2026-11-14T12:00:05Z")], execute=True)
    assert db.read_bytes() == before
