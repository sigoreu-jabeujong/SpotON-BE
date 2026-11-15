import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from etl.operation_logs import archive, job, render
from etl.operation_logs import job_state as state
from etl.operation_logs.__main__ import ArgumentsError
from etl.operation_logs.validation import epoch_us

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
OWNER, SERVICE = "tea-" + "a" * 20, "srv-" + "b" * 20
KEY = SecretStr("rnd_CREDENTIAL_CANARY")
START = "2026-11-14T11:20:00.000000123Z"


def payload(when, request_id=None):
    return (
        json.dumps(
            {
                "time": when.isoformat(),
                "event": "api_request",
                "path": "/api/health",
                "status_code": 200,
                "duration_ms": 1,
                "request_id": request_id or str(uuid4()),
                "response_complete": True,
            }
        ).encode()
        + b"\n"
    )


@pytest.fixture
def files(tmp_path):
    data, control = tmp_path / "events.sqlite3", tmp_path / "job.sqlite3"
    archive.initialize(data, execute=True)
    job.initialize(data, control, OWNER, SERVICE, START, NOW, execute=True)
    return data, control


def cursor(path):
    with state.connect(path) as c:
        return state.load(c).cursor_ns


def collector(monkeypatch, *, fail_at=None, failure=None):
    calls = []
    seen = {}

    def fetch(path, owner, service, start, end, key, *, execute):
        calls.append((start, end))
        if len(calls) == fail_at:
            raise failure if failure is not None else render.RenderLogError("api_rate_limit")
        raw = seen.setdefault((start, end), payload(NOW - timedelta(minutes=1)))
        counts = archive.ingest(path, io.BytesIO(raw), NOW, execute=execute)
        return {
            "api_window_complete": True,
            "coverage_verified": False,
            "api_rows": 1,
            "rejected_messages": 0,
            "archive": counts,
        }

    monkeypatch.setattr(render, "run_window", fetch)
    return calls, seen


def test_plan_lag_overlap_limit_and_ns_roundtrip(files):
    _, control = files
    with state.connect(control) as c:
        value = state.load(c)
    safe = epoch_us(NOW - timedelta(minutes=5)) * 1000
    plan = job.plan(value, safe)
    assert len(plan) == 6 and plan[0][0] == value.initial_ns
    assert plan[1][0] == plan[0][1] - state.OVERLAP_NS
    assert all(0 < end - start <= 7 * 60 * 10**9 for start, end in plan)
    for start, end in plan:
        assert render.nanoseconds(job.stamp(start)) == start
        assert render.nanoseconds(job.stamp(end)) == end
    assert job.stamp(value.initial_ns).endswith(".000000123Z")


def test_init_and_preview_are_read_only_without_key_or_network(files, tmp_path, monkeypatch):
    data, control = files
    new = tmp_path / "new.sqlite3"
    result = job.initialize(data, new, OWNER, SERVICE, START, NOW)
    assert result.created == 0 and not new.exists()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setattr(render, "run_window", lambda *a, **k: pytest.fail("preview must not fetch"))
    result = job.run_once(data, control, OWNER, SERVICE, SecretStr(""), NOW)
    assert result.status == "ok" and result.phase == "preview" and result.planned_windows == 6
    assert (
        result.collector_invocations == result.prune_deleted == 0
        and not result.checkpoint_committed
    )
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_success_prefix_error_and_resume(files, monkeypatch):
    data, control = files
    before = cursor(control)
    calls, _ = collector(monkeypatch, fail_at=3)
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.status == "failed" and result.error == "api_rate_limit"
    assert result.successful_windows == result.inserted == 2 and result.checkpoint_committed
    assert cursor(control) == render.nanoseconds(calls[1][1]) > before
    assert result.effects_may_be_partial and result.failed_window_start == calls[2][0]
    collector(monkeypatch)
    resumed = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert resumed.status == "ok" and resumed.checkpoint_committed
    assert cursor(control) > render.nanoseconds(result.last_confirmed_until)


@pytest.mark.parametrize(
    "failure",
    [KeyboardInterrupt(), RuntimeError("RAW_CANARY"), sqlite3.OperationalError("RAW_CANARY")],
)
def test_fatal_or_interrupt_keeps_old_checkpoint_and_replay_dedupes(files, monkeypatch, failure):
    data, control = files
    before = cursor(control)
    calls, seen = collector(monkeypatch, fail_at=2, failure=failure)
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.status in {"failed", "interrupted"} and not result.checkpoint_committed
    assert cursor(control) == before and archive.status(data, NOW)["rows"] == 1
    previous = seen[(calls[0][0], calls[0][1])]

    def resume(path, *args, **kw):
        counts = archive.ingest(path, io.BytesIO(previous), NOW, execute=True)
        return {
            "api_window_complete": True,
            "coverage_verified": False,
            "api_rows": 1,
            "rejected_messages": 0,
            "archive": counts,
        }

    monkeypatch.setattr(render, "run_window", resume)
    done = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert done.status == "ok" and done.inserted == 0 and done.duplicate > 0
    assert cursor(control) > before


def test_commit_failure_does_not_advance_checkpoint(files, monkeypatch):
    data, control = files
    before = cursor(control)
    collector(monkeypatch)

    original = state.connect

    class FailedCommit:
        def __init__(self, c):
            self.c = c

        def execute(self, *args):
            return self.c.execute(*args)

        def commit(self):
            raise sqlite3.OperationalError("RAW_CANARY")

    @contextmanager
    def fail(path, *, write=False):
        with original(path, write=write) as c:
            yield FailedCommit(c) if write else c

    monkeypatch.setattr(state, "connect", fail)
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.error == "database" and not result.checkpoint_committed
    assert cursor(control) == before and archive.status(data, NOW)["rows"] == 6


def test_prune_happens_before_source_error(files, monkeypatch):
    data, control = files
    older = NOW - timedelta(days=31)
    archive.ingest(data, io.BytesIO(payload(older)), older, execute=True)
    collector(monkeypatch, fail_at=1)
    result = job.run_once(data, control, OWNER, SERVICE, SecretStr(""), NOW, execute=True)
    assert result.status == "failed" and result.prune_completed and result.prune_deleted == 1
    assert archive.status(data, NOW)["rows"] == 0


def test_prune_failure_prevents_fetch(files, monkeypatch):
    data, control = files
    before = cursor(control)

    def fail(*a, **k):
        raise archive.ArchiveError("database_busy")

    monkeypatch.setattr(archive, "prune", fail)
    monkeypatch.setattr(render, "run_window", lambda *a, **k: pytest.fail("must not fetch"))
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert (
        result.error == "database_busy" and not result.prune_completed and cursor(control) == before
    )


def test_idle_tail_replay_and_clock_rollback(files, monkeypatch):
    data, control = files
    collector(monkeypatch)
    while cursor(control) < epoch_us(NOW - timedelta(minutes=5)) * 1000:
        assert job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True).status == "ok"
    before = cursor(control)
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.planned_windows == result.successful_windows == 1
    assert (
        not result.checkpoint_committed
        and cursor(control) == before
        and result.remaining_windows == 0
    )
    bad = job.run_once(
        data, control, OWNER, SERVICE, KEY, NOW - timedelta(minutes=10), execute=True
    )
    assert bad.error == "clock_behind_checkpoint" and not bad.prune_completed


def test_expired_checkpoint_does_not_silently_jump(files, monkeypatch):
    data, control = files
    before = cursor(control)
    monkeypatch.setattr(render, "run_window", lambda *a, **k: pytest.fail("must not fetch"))
    result = job.run_once(
        data, control, OWNER, SERVICE, KEY, NOW + timedelta(days=31), execute=True
    )
    assert (
        result.error == "checkpoint_expired"
        and result.prune_completed
        and cursor(control) == before
    )


@pytest.mark.parametrize(
    "owner,service", [("bad", SERVICE), (OWNER, "bad"), ("tea-" + "c" * 20, SERVICE)]
)
def test_wrong_owner_or_id_preserves_files(files, tmp_path, owner, service):
    data, control = files
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    if owner == "bad" or service == "bad":
        with pytest.raises(ArgumentsError):
            job.run_once(data, control, owner, service, KEY, NOW, execute=True)
    else:
        assert (
            job.run_once(data, control, owner, service, KEY, NOW, execute=True).error
            == "binding_mismatch"
        )
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_replaced_archive_binding_is_rejected(files, tmp_path):
    data, control = files
    replacement = tmp_path / "replacement.sqlite3"
    archive.initialize(replacement, execute=True)
    original = data.stat().st_ino
    data.unlink()
    replacement.rename(data)
    assert data.stat().st_ino != original
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.error == "binding_mismatch" and not result.prune_completed


def test_replace_between_windows_rolls_back_checkpoint(files, tmp_path, monkeypatch):
    data, control = files
    before = cursor(control)

    def replace(*a, **k):
        other = tmp_path / "replacement.sqlite3"
        archive.initialize(other, execute=True)
        data.unlink()
        other.rename(data)
        return {
            "api_window_complete": True,
            "coverage_verified": False,
            "api_rows": 0,
            "rejected_messages": 0,
            "archive": {"inserted": 0, "duplicate": 0},
        }

    monkeypatch.setattr(render, "run_window", replace)
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.error == "binding_mismatch" and cursor(control) == before


@pytest.mark.parametrize("kind", ["archive", "extra", "journal", "wal", "empty", "oversize"])
def test_state_ownership_and_sidecar_rejection(files, tmp_path, kind):
    data, control = files
    if kind == "archive":
        control.unlink()
        archive.initialize(control, execute=True)
    elif kind == "extra":
        c = sqlite3.connect(control)
        c.execute("CREATE TABLE extra(x)")
        c.close()
    elif kind in {"journal", "wal"}:
        Path(str(control) + "-" + kind).write_bytes(b"RAW_CANARY")
    elif kind == "empty":
        control.write_bytes(b"")
    else:
        control.write_bytes(b"x" * (1024**2 + 1))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.status == "failed" and not result.prune_completed
    if kind == "journal":
        assert result.error == "state_journal_present"
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_state_cannot_be_pruned_as_archive(files):
    _, control = files
    before = control.read_bytes()
    with pytest.raises(archive.ArchiveError):
        archive.prune(control, NOW, execute=True)
    assert control.read_bytes() == before


@pytest.mark.parametrize("which", [0, 1])
def test_hardlinks_rejected(files, tmp_path, which):
    data, control = files
    os.link(files[which], tmp_path / "alias.sqlite3")
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.status == "failed" and not result.prune_completed


def test_state_lock_blocks_another_process(files):
    data, control = files
    script = """import sys
from pathlib import Path
from datetime import UTC,datetime
from pydantic import SecretStr
from etl.operation_logs.job import run_once
r=run_once(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4],SecretStr(''),datetime(2026,11,14,12,tzinfo=UTC),execute=True)
print(r.error)
"""
    with state.connect(control, write=True):
        p = subprocess.run(
            [sys.executable, "-c", script, str(data), str(control), OWNER, SERVICE],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert p.returncode == 0 and p.stdout.strip() == "state_busy" and not p.stderr
    assert cursor(control) == render.nanoseconds(START)


def test_abrupt_exit_after_archive_commit_replays_safely(files, monkeypatch):
    data, control = files
    before = control.read_bytes()
    script = """import io,os,sys,json
from pathlib import Path
from datetime import UTC,datetime
from pydantic import SecretStr
from etl.operation_logs import archive,job,render
def collect(path,*a,**k):
 raw=json.dumps({'time':'2026-11-14T11:59:00+00:00','event':'llm_http_attempt','count':1,'success':True}).encode()+b'\\n'
 archive.ingest(path,io.BytesIO(raw),datetime(2026,11,14,12,tzinfo=UTC),execute=True)
 os._exit(17)
render.run_window=collect
job.run_once(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4],SecretStr(''),datetime(2026,11,14,12,tzinfo=UTC),execute=True)
"""
    p = subprocess.run(
        [sys.executable, "-c", script, str(data), str(control), OWNER, SERVICE],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert p.returncode == 17 and not p.stdout and not p.stderr
    assert control.read_bytes() == before and not Path(str(control) + "-journal").exists()
    assert archive.status(data, NOW)["rows"] == 1 and cursor(control) == render.nanoseconds(START)
    raw = (
        json.dumps(
            {
                "time": "2026-11-14T11:59:00+00:00",
                "event": "llm_http_attempt",
                "count": 1,
                "success": True,
            }
        ).encode()
        + b"\n"
    )

    def resume(path, *a, **k):
        counts = archive.ingest(path, io.BytesIO(raw), NOW, execute=True)
        return {
            "api_window_complete": True,
            "coverage_verified": False,
            "api_rows": 1,
            "rejected_messages": 0,
            "archive": counts,
        }

    monkeypatch.setattr(render, "run_window", resume)
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.status == "ok" and result.inserted == 0 and result.duplicate == 6
    assert result.checkpoint_committed and cursor(control) > render.nanoseconds(START)


def test_init_invalid_start_existing_state_and_same_target(files):
    data, control = files
    before = control.read_bytes()
    with pytest.raises(archive.ArchiveError):
        job.initialize(data, control, OWNER, SERVICE, START, NOW, execute=True)
    with pytest.raises(state.JobError):
        job.initialize(data, data, OWNER, SERVICE, START, NOW, execute=True)
    with pytest.raises(ArgumentsError):
        job.initialize(data, control, OWNER, SERVICE, "bad", NOW, execute=True)
    assert control.read_bytes() == before


def test_cli_preview_and_usage_are_private(files, capsys, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(job, "datetime", Clock)
    data, control = files
    args = [
        "run",
        "--db",
        str(data),
        "--state",
        str(control),
        "--owner-id",
        OWNER,
        "--service-id",
        SERVICE,
    ]
    assert job.main(args) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["mode"] == "dry_run" and not out.err
    assert all(
        marker not in out.out
        for marker in (str(data), str(control), OWNER, SERVICE, KEY.get_secret_value())
    )
    assert job.main(["--token", KEY.get_secret_value()]) == 2
    assert KEY.get_secret_value() not in capsys.readouterr().out


def test_state_contains_hashes_only(files):
    data, control = files
    raw = control.read_bytes()
    assert all(
        marker.encode() not in raw for marker in (str(data), OWNER, SERVICE, KEY.get_secret_value())
    )


def test_missing_token_still_prunes_before_collector_configuration_failure(files, monkeypatch):
    data, control = files
    older = NOW - timedelta(days=31)
    archive.ingest(data, io.BytesIO(payload(older)), older, execute=True)

    def no_network(*a, **k):
        pytest.fail("missing token must not make requests")

    monkeypatch.setattr(render.httpx, "Client", no_network)
    result = job.run_once(data, control, OWNER, SERVICE, SecretStr(""), NOW, execute=True)
    assert result.error == "configuration" and result.prune_deleted == 1 and result.prune_completed
    assert not result.checkpoint_committed and archive.status(data, NOW)["rows"] == 0


def test_collector_window_error_preserves_partial_effects_and_rolls_back_state(files, monkeypatch):
    data, control = files
    before = cursor(control)
    older = NOW - timedelta(days=31)
    archive.ingest(data, io.BytesIO(payload(older)), older, execute=True)
    collector(monkeypatch, fail_at=2, failure=ArgumentsError())
    result = job.run_once(data, control, OWNER, SERVICE, KEY, NOW, execute=True)
    assert result.status == "failed" and result.error == "collector_window"
    assert result.prune_deleted == 1 and result.inserted == result.successful_windows == 1
    assert result.effects_may_be_partial and not result.checkpoint_committed
    assert result.last_confirmed_until == job.stamp(before)
    assert cursor(control) == before and archive.status(data, NOW)["rows"] == 1


@pytest.mark.parametrize("offset", [timedelta(days=-30), timedelta(days=-31), timedelta(seconds=1)])
def test_init_rejects_expired_or_future_start_without_creating_file(files, tmp_path, offset):
    data, _ = files
    new = tmp_path / "invalid-start.sqlite3"
    with pytest.raises(ArgumentsError):
        job.initialize(data, new, OWNER, SERVICE, (NOW + offset).isoformat(), NOW, execute=True)
    assert not new.exists()
