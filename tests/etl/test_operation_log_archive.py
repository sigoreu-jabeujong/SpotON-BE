import io
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from app.core import operations
from etl.operation_logs import archive, validation
from etl.operation_logs.__main__ import main

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)
CANARY = "RAW_INPUT_CANARY"


def event(when=NOW, **values):
    return {
        "time": when.isoformat(),
        "event": "api_request",
        "path": "/api/health",
        "status_code": 200,
        "duration_ms": 0.0,
        "request_id": str(uuid4()),
        "response_complete": True,
        **values,
    }


def stream(*events):
    return io.BytesIO(b"\n".join(json.dumps(e).encode() for e in events) + b"\n")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "events.sqlite3"
    archive.initialize(path, execute=True)
    return path


def test_real_emitters_round_trip(monkeypatch, db):
    sink = io.StringIO()
    monkeypatch.setattr(operations.sys, "stderr", sink)
    operations.api_event(
        path="/api/health", status=200, duration=2.0, request_id=str(uuid4()), complete=True
    )
    operations.llm_attempt(success=True)
    operations.readiness_probe(reason="ok", duration=0.1)

    @operations.logged_import("living_pop")
    def work():
        with operations.etl_phase("read_source"):
            operations.population_quality({k: 0 for k in operations.POPULATION_QUALITY_COUNTS})
            operations.population_quality({})
        return {"rows": 1, "flags": {}, "mode": "dry_run", "version_id": str(uuid4())}

    work()
    with pytest.raises(RuntimeError):

        @operations.logged_import("localdata")
        def failure():
            raise RuntimeError(CANARY)

        failure()
    data = sink.getvalue().encode()
    now = datetime.now(UTC) + timedelta(seconds=1)
    result = archive.ingest(db, io.BytesIO(data), now, execute=True)
    assert result["inserted"] == result["lines"] == 11
    assert result["rejected"] == 0
    with sqlite3.connect(db) as c:
        kinds = {r[0] for r in c.execute("SELECT DISTINCT event FROM operation_events")}
    assert kinds == {
        "api_request",
        "llm_http_attempt",
        "readiness_probe",
        "etl_run",
        "etl_stage",
        "etl_quality",
    }
    assert CANARY not in db.read_bytes().decode("latin1")


@pytest.mark.parametrize(
    "change",
    [
        {"raw": CANARY},
        {"path": CANARY},
        {"path": []},
        {"request_id": CANARY},
        {"request_id": str(uuid4()).upper()},
        {"status_code": True},
        {"status_code": 99},
        {"status_code": 600},
        {"duration_ms": True},
        {"duration_ms": -0.0},
        {"duration_ms": -1},
        {"duration_ms": float("inf")},
        {"duration_ms": float("nan")},
        {"response_complete": 1},
        {"time": "2026-11-15T12:00:00Z"},
        {"time": "2026-11-15T12:00:00+09:00"},
        {"time": "2026-11-15T12:00:00"},
        {"time": "2026-11-15T12:00:00.1+00:00"},
        {"time": "2026-99-15T12:00:00+00:00"},
        {"event": CANARY},
        {"event": []},
    ],
)
def test_rejects_private_or_invalid_fields(change):
    with pytest.raises(validation.Rejected):
        validation.parse_record(json.dumps(event(**change)).encode())


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b"{}",
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"time":1,"time":2}',
        b'{"event":"x","duration_ms":1e400}',
        b'{"event":"x","duration_ms":NaN}',
        b'{"event":"x","duration_ms":Infinity}',
        b'{"event":"x","counts":{"rows":1,"rows":2}}',
        b"[" * 2000,
    ],
)
def test_malformed_json_rejected(raw):
    with pytest.raises(validation.Rejected):
        validation.parse_record(raw)


@pytest.mark.parametrize(
    "values",
    [
        {"event": "llm_http_attempt", "count": True, "success": True},
        {"event": "llm_http_attempt", "count": 1.0, "success": True},
        {
            "event": "readiness_probe",
            "path": "/api/ready",
            "reason": "ok",
            "success": False,
            "duration_ms": 0,
        },
        {
            "event": "etl_run",
            "source": "localdata",
            "run_id": str(uuid4()),
            "stage": "read_source",
            "status": "started",
            "duration_ms": None,
        },
        {
            "event": "etl_run",
            "source": "localdata",
            "run_id": str(uuid4()),
            "stage": "import",
            "status": "failed",
            "duration_ms": 1,
        },
        {
            "event": "etl_run",
            "source": "localdata",
            "run_id": str(uuid4()),
            "stage": "import",
            "status": "completed",
            "duration_ms": 1,
            "counts": {},
        },
        {
            "event": "etl_stage",
            "source": "localdata",
            "run_id": str(uuid4()),
            "stage": "import",
            "status": "started",
            "duration_ms": None,
        },
        {
            "event": "etl_quality",
            "source": "living_pop",
            "run_id": str(uuid4()),
            "stage": "read_source",
            "status": "completed",
            "scope": "source_day_all_sources",
            "spatial_compatibility": "unverified",
            "aggregation_status": "pending",
            "counts": {},
        },
    ],
)
def test_per_event_invariants(values):
    with pytest.raises(validation.Rejected):
        validation.parse_record(json.dumps({"time": NOW.isoformat(), **values}).encode())


def test_no_fraction_and_fraction_are_one_canonical_event(db):
    first = event()
    second = {**first, "time": NOW.isoformat(timespec="microseconds")}
    result = archive.ingest(db, stream(first, second), NOW, execute=True)
    assert result["inserted"] == result["duplicate"] == 1


def test_cutoff_future_classification_and_replay(db):
    cutoff = NOW - timedelta(days=30)
    recent = event(cutoff + timedelta(microseconds=1))
    incoming = (
        event(cutoff),
        recent,
        recent,
        event(NOW + timedelta(microseconds=1)),
        event(raw=CANARY),
    )
    result = archive.ingest(db, stream(*incoming), NOW, execute=True)
    assert result == {
        "lines": 5,
        "expired": 1,
        "future": 1,
        "rejected": 1,
        "duplicate": 1,
        "inserted": 1,
        "would_insert": 1,
    }
    replay = archive.ingest(db, stream(recent), NOW, execute=True)
    assert replay["duplicate"] == 1 and replay["inserted"] == 0


def test_dry_runs_do_not_change_any_file(db, tmp_path):
    missing = tmp_path / "new.sqlite3"
    assert archive.initialize(missing) == {"created": 0, "would_create": 1}
    assert not missing.exists()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = archive.ingest(db, stream(event()), NOW)
    assert result["inserted"] == 0 and result["would_insert"] == 1
    assert archive.status(db, NOW) == {"rows": 0, "expired": 0}
    assert archive.prune(db, NOW)["deleted"] == 0
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_prune_exact_boundary_and_secure_delete(db):
    older, newer = event(), event(NOW + timedelta(microseconds=1))
    archive.ingest(db, stream(older, newer), NOW + timedelta(seconds=1), execute=True)
    expired_at = NOW + timedelta(days=30)
    before = db.read_bytes()
    assert older["request_id"].encode() in before
    assert archive.prune(db, expired_at) == {
        "would_delete": 1,
        "deleted": 0,
        "rows": 2,
        "expired": 1,
    }
    assert db.read_bytes() == before
    assert archive.prune(db, expired_at, execute=True) == {
        "would_delete": 1,
        "deleted": 1,
        "rows": 1,
        "expired": 0,
    }
    assert older["request_id"].encode() not in db.read_bytes()
    assert newer["request_id"].encode() in db.read_bytes()
    assert archive.prune(db, expired_at, execute=True)["deleted"] == 0
    with archive.connect(db, write=True) as c:
        assert c.execute("PRAGMA secure_delete").fetchone()[0] == 1


@pytest.mark.parametrize("data", [b"x" * 4097 + b"\n", b"x" * 9000 + b"\n", b"\xff\n", b"\n"])
def test_invalid_line_followed_by_valid_line(db, data):
    raw = data + json.dumps(event()).encode() + b"\r\n"
    result = archive.ingest(db, io.BytesIO(raw), NOW, execute=True)
    assert result["lines"] == 2 and result["rejected"] == result["inserted"] == 1


def test_no_final_newline(db):
    result = archive.ingest(db, io.BytesIO(json.dumps(event()).encode()), NOW, execute=True)
    assert result["lines"] == result["inserted"] == 1


@pytest.mark.parametrize("limit", ["MAX_LINES", "MAX_INPUT_BYTES"])
def test_input_limit_prevents_any_insert(db, monkeypatch, limit):
    monkeypatch.setattr(archive, limit, 1 if limit == "MAX_LINES" else 300)
    with pytest.raises(archive.ArchiveError, match="input_limit"):
        archive.ingest(db, stream(event(), event()), NOW, execute=True)
    assert archive.status(db, NOW)["rows"] == 0


@pytest.mark.parametrize("name", ["relative.sqlite3", "../escape.sqlite3", "bad.db"])
def test_unsafe_paths_rejected(tmp_path, name):
    path = Path(name) if name != "bad.db" else tmp_path / name
    with pytest.raises(archive.ArchiveError):
        archive.initialize(path, execute=True)


def test_repository_and_missing_files_rejected(tmp_path):
    with pytest.raises(archive.ArchiveError):
        archive.initialize(archive.ROOT / "bad.sqlite3", execute=True)
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(archive.ArchiveError, match="missing"):
        archive.status(missing, NOW)
    assert not missing.exists()


@pytest.mark.parametrize(
    "kind", ["empty", "other", "trigger", "view", "table", "index", "wal", "journal"]
)
def test_unowned_or_sidecar_files_preserved(db, kind):
    if kind == "empty":
        db.write_bytes(b"")
    elif kind == "other":
        with sqlite3.connect(db) as c:
            c.execute("PRAGMA application_id=0")
    elif kind in {"wal", "journal"}:
        Path(str(db) + "-" + kind).write_bytes(CANARY.encode())
    else:
        sql = {
            "trigger": "CREATE TRIGGER extra AFTER DELETE ON operation_events BEGIN SELECT 1; END",
            "view": "CREATE VIEW extra AS SELECT 1",
            "table": "CREATE TABLE extra(x)",
            "index": "CREATE INDEX extra ON operation_events(event)",
        }[kind]
        with sqlite3.connect(db) as c:
            c.execute(sql)
    before = db.read_bytes()
    with pytest.raises(archive.ArchiveError):
        archive.prune(db, NOW, execute=True)
    assert db.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink privilege is not assumed")
def test_links_and_sidecar_links_rejected(db, tmp_path):
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(db)
    with pytest.raises(archive.ArchiveError):
        archive.status(alias, NOW)
    side = Path(str(db) + "-journal")
    side.symlink_to(db)
    before = db.read_bytes()
    with pytest.raises(archive.ArchiveError):
        archive.prune(db, NOW, execute=True)
    assert db.read_bytes() == before


def test_windows_reparse_flag_rejected(db, monkeypatch):
    original = Path.lstat

    class Reparse:
        st_mode = 0
        st_file_attributes = 0x400

    def fake(path):
        return Reparse() if path == db else original(path)

    monkeypatch.setattr(Path, "lstat", fake)
    with pytest.raises(archive.ArchiveError, match="path"):
        archive.validate_target(db)


def test_init_failure_cleans_only_new_file(tmp_path, monkeypatch):
    db = tmp_path / "broken.sqlite3"
    monkeypatch.setattr(archive, "TABLE", "CREATE TABLE invalid (")
    with pytest.raises(sqlite3.Error):
        archive.initialize(db, execute=True)
    assert not db.exists()


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_partial_ingest_rolls_back(db, monkeypatch, failure):
    original = archive._owned
    calls = 0

    def fail(connection):
        nonlocal calls
        calls += 1
        original(connection)
        if calls == 2:
            connection.execute(
                "INSERT INTO operation_events VALUES (?,?,?,?)", ("a" * 64, 0, "api_request", "{}")
            )
            raise failure(CANARY)

    monkeypatch.setattr(archive, "_owned", fail)
    with pytest.raises(failure):
        archive.ingest(db, stream(event()), NOW, execute=True)
    monkeypatch.setattr(archive, "_owned", original)
    assert archive.status(db, NOW)["rows"] == 0


def test_two_writers_are_deduplicated(db):
    barrier = Barrier(2)
    sample = event()

    def run():
        barrier.wait()
        try:
            return archive.ingest(db, stream(sample), NOW, execute=True)
        except archive.ArchiveError as exc:
            assert str(exc) == "database_busy"
        except sqlite3.OperationalError as exc:
            assert exc.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(r["inserted"] for r in results if r is not None) == 1
    assert sum(r["duplicate"] if r is not None else 1 for r in results) == 1
    assert archive.status(db, NOW)["rows"] == 1
    assert archive.ingest(db, stream(sample), NOW, execute=True)["duplicate"] == 1


def test_real_process_lock_busy_and_release(db):
    with sqlite3.connect(db, isolation_level=None) as c:
        c.execute("BEGIN IMMEDIATE")
        result = subprocess.run(
            [sys.executable, "-m", "etl.operation_logs", "prune", "--db", str(db), "--execute"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1 and json.loads(result.stdout)["error"] == "database_busy"
        assert result.stderr == "" and str(db) not in result.stdout
        c.rollback()
    assert archive.prune(db, NOW, execute=True)["deleted"] == 0


def test_cli_lifecycle_and_safe_arguments(tmp_path):
    db = tmp_path / (CANARY + ".sqlite3")

    def run(*args, data=None):
        result = subprocess.run(
            [sys.executable, "-m", "etl.operation_logs", *args],
            input=data,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert (
            CANARY not in result.stdout + result.stderr
            and str(db) not in result.stdout + result.stderr
        )
        assert result.stderr == ""
        return result.returncode, json.loads(result.stdout)

    assert run("init", "--db", str(db))[1]["created"] == 0
    assert run("init", "--db", str(db), "--execute")[1]["created"] == 1
    assert run("init", "--db", str(db), "--execute")[0] == 1
    data = json.dumps(event(datetime.now(UTC))) + "\n"
    assert run("ingest", "--db", str(db), data=data)[1]["would_insert"] == 1
    assert run("ingest", "--db", str(db), "--execute", data=data)[1]["inserted"] == 1
    assert run("status", "--db", str(db))[1]["rows"] == 1
    assert run("prune", "--db", str(db), "--execute")[1]["deleted"] == 0
    assert run("status", "--db", str(db), "--execute")[0] == 2
    assert run("invalid" + CANARY)[1]["error"] == "arguments"


def test_interrupt_returns_safe_130(db, capsys):
    class Interrupted:
        def readline(self, limit):
            raise KeyboardInterrupt(CANARY)

    assert main(["ingest", "--db", str(db), "--execute"], stdin=Interrupted()) == 130
    out = capsys.readouterr()
    assert json.loads(out.out)["error"] == "interrupted" and CANARY not in out.out + out.err
    assert archive.status(db, NOW)["rows"] == 0


@pytest.mark.parametrize("name", ["NUL.sqlite3", "CON.sqlite3", "archive:ads.sqlite3"])
def test_windows_reserved_and_stream_paths_rejected(tmp_path, name):
    with pytest.raises(archive.ArchiveError, match="path"):
        archive.initialize(tmp_path / name, execute=True)


def test_autoindex_like_name_cannot_hide_extra_schema(db):
    with sqlite3.connect(db) as c:
        c.execute("CREATE INDEX sqliteXautoindexYextra ON operation_events(event)")
    before = db.read_bytes()
    with pytest.raises(archive.ArchiveError, match="ownership"):
        archive.ingest(db, stream(event()), NOW, execute=True)
    assert db.read_bytes() == before


def test_prune_verification_failure_rolls_back_delete(db, monkeypatch):
    archive.ingest(db, stream(event()), NOW, execute=True)
    original = archive._summary
    calls = 0

    def fail(c, cutoff):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError(CANARY)
        return original(c, cutoff)

    monkeypatch.setattr(archive, "_summary", fail)
    with pytest.raises(RuntimeError):
        archive.prune(db, NOW + timedelta(days=30), execute=True)
    monkeypatch.setattr(archive, "_summary", original)
    assert archive.status(db, NOW)["rows"] == 1


def test_uri_characters_preserved_and_help_safe(tmp_path):
    path = tmp_path / "archive#%20.sqlite3"
    archive.initialize(path, execute=True)
    assert archive.ingest(path, stream(event()), NOW, execute=True)["inserted"] == 1
    assert archive.status(path, NOW)["rows"] == 1
    result = subprocess.run(
        [sys.executable, "-m", "etl.operation_logs", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and "--help" in result.stdout and result.stderr == ""


def test_llm_identical_time_has_documented_deduplication(db):
    row = {"time": NOW.isoformat(), "event": "llm_http_attempt", "count": 1, "success": True}
    result = archive.ingest(db, stream(row, row), NOW, execute=True)
    assert result["inserted"] == result["duplicate"] == 1


@pytest.mark.parametrize("foreign", [False, True])
def test_wal_header_rejected_before_sqlite_open(db, tmp_path, foreign, monkeypatch):
    c = sqlite3.connect(db)
    if foreign:
        c.execute("PRAGMA application_id=0")
    assert c.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    c.close()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert not Path(str(db) + "-wal").exists() and not Path(str(db) + "-shm").exists()

    def never_connect(*args, **kwargs):
        raise AssertionError("SQLite must not open the rejected file")

    monkeypatch.setattr(archive.sqlite3, "connect", never_connect)
    with pytest.raises(archive.ArchiveError, match="ownership"):
        archive.status(db, NOW)
    with pytest.raises(archive.ArchiveError, match="ownership"):
        archive.prune(db, NOW, execute=True)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_clock_is_captured_after_input_eof(db, monkeypatch):
    state = {"eof": False}

    class Clock:
        @classmethod
        def now(cls, tz):
            assert state["eof"]
            return NOW + timedelta(seconds=2)

    class SlowBatch(io.BytesIO):
        def readline(self, limit):
            value = super().readline(limit)
            if not value:
                state["eof"] = True
            return value

    monkeypatch.setattr(archive, "datetime", Clock)
    data = json.dumps(event(NOW + timedelta(seconds=1))).encode() + b"\n"
    result = archive.ingest(db, SlowBatch(data), execute=True)
    assert result["future"] == 0 and result["inserted"] == 1


def test_remote_drive_is_rejected_before_file_access(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_remote_drive", lambda anchor: True)
    with pytest.raises(archive.ArchiveError, match="path"):
        archive.initialize(tmp_path / "events.sqlite3", execute=True)
    assert list(tmp_path.iterdir()) == []


def test_completed_writer_journal_disappears_during_preflight(db, monkeypatch):
    side = Path(str(db) + "-journal")
    side.write_bytes(b"")
    original = Path.lstat

    def disappearing(path):
        if path == side:
            side.unlink()
            raise FileNotFoundError
        return original(path)

    monkeypatch.setattr(Path, "lstat", disappearing)
    assert archive.status(db, NOW) == {"rows": 0, "expired": 0}
