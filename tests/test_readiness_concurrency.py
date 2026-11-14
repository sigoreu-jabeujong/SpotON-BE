import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import MagicMock, patch

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core import operations
from app.core.config import Settings
from app.main import create_app
from app.services.readiness import ReadinessProbe
from tests.test_render_runtime import good_row

CANARY = "PRIVATE_READY_CANARY"


def records(capsys):
    return [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]


@pytest.mark.parametrize("reason,status", [("ok", 200), ("database_error", 500)])
def test_concurrent_http_waits_for_one_actual_result(reason, status, capsys):
    entered, release, completed = Event(), Event(), Event()
    start = Barrier(5)

    def slow():
        entered.set()
        assert release.wait(3)
        return reason

    with (
        patch.object(ReadinessProbe, "_probe", side_effect=slow) as query,
        TestClient(create_app(Settings(_env_file=None))) as client,
        ThreadPoolExecutor(4) as workers,
    ):

        def request():
            start.wait(timeout=3)
            response = client.get("/api/ready")
            completed.set()
            return response

        tasks = [workers.submit(request) for _ in range(4)]
        try:
            start.wait(timeout=3)
            assert entered.wait(3)
            assert not completed.wait(0.05)
        finally:
            release.set()
        responses = [task.result(timeout=3) for task in tasks]
        assert [r.status_code for r in responses] == [status] * 4
        assert all(r.headers["cache-control"] == "no-store" for r in responses)
        assert query.call_count == 1
    events = records(capsys)
    probes = [r for r in events if r["event"] == "readiness_probe"]
    assert len(probes) == 1 and probes[0]["reason"] == reason
    assert set(probes[0]) == {"event", "time", "path", "reason", "success", "duration_ms"}
    api = [r for r in events if r["event"] == "api_request"]
    assert len(api) == 4 and all(r["path"] == "/api/ready" for r in api)


def test_waiter_timeout_cannot_cancel_or_replace_running_probe(monkeypatch):
    entered, release, joined = Event(), Event(), Event()
    probe = ReadinessProbe(Settings(_env_file=None))

    def slow():
        entered.set()
        assert release.wait(3)
        return "ok"

    with patch.object(probe, "_probe", side_effect=slow) as query, ThreadPoolExecutor(2) as pool:
        leader = pool.submit(probe.check)
        try:
            assert entered.wait(3)
            monkeypatch.setattr("app.services.readiness.PROBE_TIMEOUT_SECONDS", 0.02)
            assert probe.check() is False
            flight = probe._current
            assert flight is not None and flight.running() and not flight.cancel()
            monkeypatch.setattr("app.services.readiness.PROBE_TIMEOUT_SECONDS", 2.5)
            original = flight.result

            def wait(*args, **kwargs):
                joined.set()
                return original(*args, **kwargs)

            with patch.object(flight, "result", side_effect=wait):
                survivor = pool.submit(probe.check)
                assert joined.wait(3)
                release.set()
                assert survivor.result(timeout=3) is True
            assert leader.result(timeout=3) is True
            assert query.call_count == 1 and not flight.cancelled()
        finally:
            release.set()


def test_http_cancellation_does_not_cancel_shared_probe():
    entered, release = Event(), Event()
    app = create_app(Settings(_env_file=None))
    probe = app.state.database.readiness

    def slow():
        entered.set()
        assert release.wait(3)
        return "ok"

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            first = asyncio.create_task(c.get("/api/ready"))
            assert await asyncio.to_thread(entered.wait, 3)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            flight = probe._current
            assert flight is not None and flight.running() and not flight.cancelled()
            asyncio.get_running_loop().call_later(0.02, release.set)
            assert (await c.get("/api/ready")).status_code == 200

    with patch.object(probe, "_probe", side_effect=slow) as query:
        try:
            asyncio.run(scenario())
            assert query.call_count == 1
        finally:
            release.set()
            app.state.database.close()


def test_close_wakes_waiter_and_rejects_late_success():
    entered, release, joined = Event(), Event(), Event()
    probe = ReadinessProbe(Settings(_env_file=None))

    def slow():
        entered.set()
        assert release.wait(3)
        return "ok"

    with patch.object(probe, "_probe", side_effect=slow) as query, ThreadPoolExecutor(2) as pool:
        leader = pool.submit(probe.check)
        try:
            assert entered.wait(3)
            flight = probe._current
            original = flight.result

            def wait(*args, **kwargs):
                joined.set()
                return original(*args, **kwargs)

            with patch.object(flight, "result", side_effect=wait):
                waiter = pool.submit(probe.check)
                assert joined.wait(3)
                probe.close()
                assert waiter.result(timeout=1) is False
            assert not leader.done()
            release.set()
            assert leader.result(timeout=3) is False
            assert probe.check() is False
            assert probe._current is None and probe._checked_at is None
            assert query.call_count == 1
        finally:
            release.set()


class ProbeAbort(BaseException):
    pass


@pytest.mark.parametrize("error", [RuntimeError(CANARY), ProbeAbort(CANARY)])
def test_probe_exception_completes_waiters_without_raw_details(error, capsys):
    entered, release, joined = Event(), Event(), Event()
    probe = ReadinessProbe(Settings(_env_file=None))

    def fail():
        entered.set()
        assert release.wait(3)
        raise error

    with patch.object(probe, "_probe", side_effect=fail), ThreadPoolExecutor(2) as pool:
        leader = pool.submit(probe.check)
        try:
            assert entered.wait(3)
            flight = probe._current
            original = flight.result

            def wait(*args, **kwargs):
                joined.set()
                return original(*args, **kwargs)

            with patch.object(flight, "result", side_effect=wait):
                waiter = pool.submit(probe.check)
                assert joined.wait(3)
                release.set()
                assert waiter.result(timeout=3) is False
            if isinstance(error, ProbeAbort):
                with pytest.raises(ProbeAbort):
                    leader.result(timeout=3)
            else:
                assert leader.result(timeout=3) is False
            assert probe._current is None
        finally:
            release.set()
    events = records(capsys)
    assert len(events) == 1 and events[0]["reason"] == "internal_error"
    assert CANARY not in json.dumps(events)


@pytest.mark.parametrize("first,second", [("ok", "database_error"), ("database_error", "ok")])
def test_waiter_uses_its_own_generation_result(first, second):
    entered, release, joined, captured, return_waiter = (Event() for _ in range(5))
    probe = ReadinessProbe(Settings(_env_file=None))
    calls = 0

    def run():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(3)
            return first
        return second

    with (
        patch.object(probe, "_probe", side_effect=run),
        patch("app.services.readiness.monotonic", return_value=100) as clock,
        ThreadPoolExecutor(2) as pool,
    ):
        leader = pool.submit(probe.check)
        try:
            assert entered.wait(3)
            flight = probe._current
            original = flight.result

            def delayed(*args, **kwargs):
                joined.set()
                result = original(*args, **kwargs)
                captured.set()
                assert return_waiter.wait(3)
                return result

            with patch.object(flight, "result", side_effect=delayed):
                waiter = pool.submit(probe.check)
                assert joined.wait(3)
                release.set()
                assert captured.wait(3)
                assert leader.result(timeout=3) is (first == "ok")
                clock.return_value = 111
                assert probe.check() is (second == "ok")
                return_waiter.set()
                assert waiter.result(timeout=3) is (first == "ok")
            assert calls == 2
        finally:
            release.set()
            return_waiter.set()


def test_failed_probe_ttl_and_success_expiration():
    probe = ReadinessProbe(Settings(_env_file=None))
    with (
        patch.object(probe, "_probe", side_effect=["database_error", "ok", "database_error"]) as q,
        patch("app.services.readiness.monotonic", return_value=100) as clock,
    ):
        assert probe.check() is False
        clock.return_value = 100.99
        assert probe.check() is False and q.call_count == 1
        clock.return_value = 101.01
        assert probe.check() is True and q.call_count == 2
        clock.return_value = 111.02
        assert probe.check() is False and q.call_count == 3


def test_state_lock_is_not_held_during_probe_completion_or_logging():
    entered, release = Event(), Event()
    probe = ReadinessProbe(Settings(_env_file=None))
    lock_states = []

    def slow():
        lock_states.append(probe._lock.locked())
        entered.set()
        assert release.wait(3)
        return "ok"

    with (
        patch.object(probe, "_probe", side_effect=slow),
        patch(
            "app.services.readiness.readiness_probe",
            side_effect=lambda **kw: lock_states.append(probe._lock.locked()),
        ),
        ThreadPoolExecutor(1) as pool,
    ):
        leader = pool.submit(probe.check)
        try:
            assert entered.wait(3)
            probe._current.add_done_callback(lambda f: lock_states.append(probe._lock.locked()))
        finally:
            release.set()
        assert leader.result(timeout=3)
    assert lock_states == [False, False, False]


@pytest.mark.parametrize(
    "change,reason",
    [
        (None, "ok"),
        (("revisions", [CANARY]), "revision_mismatch"),
        (("connection_limit", -1), "connection_limit"),
        (("table_write", True), "unsafe_role"),
    ],
)
def test_probe_diagnostics_use_fixed_reasons_without_database_values(change, reason, capsys):
    row = good_row()
    if change:
        row[change[0]] = change[1]
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = row
    with patch("app.services.readiness.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        probe = ReadinessProbe(
            Settings(
                _env_file=None,
                app_env="staging",
                database_url=SecretStr(f"postgresql://reader:{CANARY}@localhost/check"),
            )
        )
        assert probe.check() is (reason == "ok")
    event = records(capsys)[0]
    assert event["reason"] == reason and CANARY not in json.dumps(event)


@pytest.mark.parametrize(
    "error,reason",
    [
        (psycopg.OperationalError(CANARY), "database_error"),
        (psycopg.errors.QueryCanceled(CANARY), "query_cancelled"),
    ],
)
def test_database_exception_diagnostics_do_not_emit_exception_text(error, reason, capsys):
    with patch("app.services.readiness.psycopg.connect", side_effect=error):
        probe = ReadinessProbe(
            Settings(
                _env_file=None,
                database_url=SecretStr(f"postgresql://reader:{CANARY}@localhost/check"),
            )
        )
        assert probe.check() is False
    events = records(capsys)
    assert events[0]["reason"] == reason and CANARY not in json.dumps(events)


@pytest.mark.parametrize("path", ["/api/ready/", "/API/READY", "/api/ready/" + CANARY])
def test_readiness_path_variants_still_do_not_log_input(client, capsys, path):
    client.get(path, follow_redirects=False)
    events = [e for e in records(capsys) if e["event"] == "api_request"]
    assert len(events) == 1 and events[0]["path"] == "unmatched"
    assert CANARY not in json.dumps(events)


def test_probe_result_survives_broken_logging(monkeypatch):
    class Broken:
        def write(self, value):
            raise OSError(CANARY)

        def flush(self):
            raise OSError(CANARY)

    monkeypatch.setattr(operations.sys, "stderr", Broken())
    probe = ReadinessProbe(Settings(_env_file=None))
    with patch.object(probe, "_probe", return_value="ok"):
        assert probe.check() is True
