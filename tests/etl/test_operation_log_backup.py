import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.core import operations
from etl.operation_logs import archive, backup, job
from etl.operation_logs import backup_store as store
from etl.operation_logs import job_state as control
from etl.operation_logs.validation import MAX_LINE_BYTES, epoch_us, parse_record

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)
OWNER, SERVICE = "tea-" + "a" * 20, "srv-" + "b" * 20
CANARY = "RAW_SECRET_CANARY"


def events(when=NOW - timedelta(minutes=1)):
    common = dict(time=when.isoformat())
    etl = dict(source="living_pop", run_id=str(uuid4()), status="completed", duration_ms=0.0)
    return [
        common
        | dict(
            event="api_request",
            path="/api/health",
            status_code=200,
            duration_ms=0.0,
            request_id=str(uuid4()),
            response_complete=True,
        ),
        common | dict(event="llm_http_attempt", count=1, success=True),
        common
        | dict(
            event="readiness_probe", path="/api/ready", reason="ok", success=True, duration_ms=0.0
        ),
        common | etl | dict(event="etl_run", stage="import"),
        common | etl | dict(event="etl_stage", stage="read_source"),
        common
        | dict(
            event="etl_quality",
            source="living_pop",
            run_id=str(uuid4()),
            stage="read_source",
            status="failed",
            scope="source_day_all_sources",
            spatial_compatibility="unverified",
            aggregation_status="pending",
            reason="quality_summary_unavailable",
        ),
    ]


def ingest(path, values, now=NOW):
    return archive.ingest(
        path,
        io.BytesIO(b"\n".join(json.dumps(v).encode() for v in values) + b"\n"),
        now,
        execute=True,
    )


@pytest.fixture
def files(tmp_path):
    db, state, saved = (
        tmp_path / name for name in ("events.sqlite3", "job.sqlite3", "backup.sqlite3")
    )
    archive.initialize(db, execute=True)
    job.initialize(
        db, state, OWNER, SERVICE, (NOW - timedelta(minutes=20)).isoformat(), NOW, execute=True
    )
    assert ingest(db, events())["inserted"] == 6
    assert backup.run("init", saved, OWNER, SERVICE, NOW, execute=True).status == "ok"
    return db, state, saved


def act(files, command="capture", now=NOW, *, execute=True, **kwargs):
    db, state, saved = files
    return backup.run(
        command, saved, OWNER, SERVICE, now, db=db, state=state, execute=execute, **kwargs
    )


def rows(path):
    with archive.connect(path) as c:
        return c.execute("SELECT * FROM operation_events ORDER BY event_hash").fetchall()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def advance(path, minutes):
    with control.connect(path, write=True) as c:
        before = control.load(c)
        control.save(c, before, epoch_us(NOW - timedelta(minutes=minutes)) * 1000)
        c.commit()


def test_six_events_snapshot_restore_rebind_and_nonmutation(files, tmp_path):
    db, state, saved = files
    before = digest(db), digest(state)
    result = act(files)
    assert result.status == "ok" and result.rows_captured == 6 and result.generation_committed
    assert (digest(db), digest(state)) == before
    target, restored = tmp_path / "restored.sqlite3", tmp_path / "restored-state.sqlite3"
    result = backup.run(
        "restore", saved, OWNER, SERVICE, NOW, db=target, state=restored, execute=True
    )
    assert result.status == "ok" and result.rows_restored == 6
    assert result.archive_created == result.state_created == 1 and rows(db) == rows(target)
    with control.connect(state) as original, control.connect(restored) as copied:
        a, b = control.load(original), control.load(copied)
        assert a.binding != b.binding and (a.initial_ns, a.cursor_ns) == (b.initial_ns, b.cursor_ns)
        assert b.binding == control.binding(target, OWNER, SERVICE, b.initial_ns)
    assert job.run_once(target, restored, OWNER, SERVICE, None, NOW).status == "ok"


def test_rotation_keeps_only_two_and_previous_is_selectable(files, tmp_path):
    assert act(files).sequence == 1
    db, state, saved = files
    ingest(db, [events()[0]])
    advance(state, 15)
    assert act(files).sequence == 2
    ingest(db, [events()[0]])
    advance(state, 10)
    latest = act(files)
    assert latest.sequence == 3 and latest.generations_after == 2 and latest.rows == 15
    new, newstate = tmp_path / "previous.sqlite3", tmp_path / "previous-state.sqlite3"
    result = backup.run(
        "restore",
        saved,
        OWNER,
        SERVICE,
        NOW,
        db=new,
        state=newstate,
        generation="previous",
        execute=True,
    )
    assert result.status == "ok" and result.rows_restored == 7 and result.sequence == 2


def test_every_preview_and_status_preserves_bytes(files, tmp_path):
    assert act(files).status == "ok"
    before = {p: p.read_bytes() for p in files}
    assert act(files, execute=False).rows_would_capture == 6
    assert act(files, "prune", execute=False).prune_deleted == 0
    assert act(files, "status", execute=False).integrity_verified
    assert backup.run("init", tmp_path / "absent.sqlite3", OWNER, SERVICE, NOW).status == "ok"
    result = backup.run(
        "restore",
        files[2],
        OWNER,
        SERVICE,
        NOW,
        db=tmp_path / "new.sqlite3",
        state=tmp_path / "new-state.sqlite3",
    )
    assert result.rows_would_restore == 6 and result.archive_created == 0
    assert before == {p: p.read_bytes() for p in files}
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(p.name for p in files)


def test_global_expiry_all_slots_and_restore_cannot_reintroduce(files, tmp_path):
    db, state, saved = files
    near = NOW - timedelta(days=30) + timedelta(microseconds=1)
    expiring = events(near)[0]
    ingest(db, [expiring])
    assert act(files).rows_captured == 7 and act(files).rows_captured == 7
    before = digest(db), digest(state)
    later = NOW + timedelta(microseconds=1)
    preview = act(files, "prune", later, execute=False)
    assert preview.prune_would_delete == 2 and not preview.backup_prune_committed
    # Restore filters expiry even before maintenance gets a chance to prune.
    result = backup.run(
        "restore",
        saved,
        OWNER,
        SERVICE,
        later,
        execute=True,
        db=tmp_path / "restore.sqlite3",
        state=tmp_path / "restore-state.sqlite3",
    )
    assert result.rows_restored == 6 and result.rows_skipped_expired == 1
    result = act(files, "prune", later)
    assert result.prune_deleted == 2 and result.rows == 12 and result.expired == 0
    assert expiring["request_id"].encode() not in saved.read_bytes()
    assert (digest(db), digest(state)) == before
    with store.connect(saved, store.Budget()) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM backup_events WHERE event_us<=?",
                (epoch_us(later) - archive.RETENTION_US,),
            ).fetchone()[0]
            == 0
        )


def test_source_missing_does_not_prevent_backup_expiry(files, tmp_path):
    db, state, saved = files
    near = NOW - timedelta(days=30) + timedelta(microseconds=1)
    ingest(db, [events(near)[0]])
    assert act(files).status == "ok"
    absent = tmp_path / "missing-parent" / "missing.sqlite3"
    result = backup.run(
        "capture",
        saved,
        OWNER,
        SERVICE,
        NOW + timedelta(microseconds=1),
        db=absent,
        state=state,
        execute=True,
    )
    assert result.error == "source_missing" and result.prune_deleted == 1
    assert result.backup_prune_committed and result.effects_may_be_partial
    assert act(files, "status", NOW + timedelta(microseconds=1), execute=False).rows == 6


def test_source_lock_reports_busy_after_independent_expiry(files):
    db, state, _ = files
    ingest(db, [events(NOW - timedelta(days=30) + timedelta(microseconds=1))[0]])
    assert act(files).status == "ok"
    code = (
        "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);"
        "c.execute('BEGIN IMMEDIATE');print('ready',flush=True);"
        "sys.stdin.readline();c.rollback();c.close()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(state)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        result = act(files, now=NOW + timedelta(microseconds=1))
        assert result.error == "source_busy" and result.prune_deleted == 1
        assert result.backup_prune_committed and not result.generation_committed
    finally:
        child.communicate("\n", timeout=10)
    assert child.returncode == 0


@pytest.mark.parametrize(
    "damage", ["record", "hash", "time", "kind", "digest", "count", "pointer", "schema"]
)
def test_corrupt_backup_is_never_pruned_or_restored(files, tmp_path, damage):
    assert act(files).status == "ok" and act(files).status == "ok"
    saved = files[2]
    sql = {
        "record": "UPDATE backup_events SET record='RAW_SECRET_CANARY' WHERE slot=0",
        "hash": "UPDATE backup_events SET event_hash=replace(event_hash,'a','b') WHERE slot=0",
        "time": "UPDATE backup_events SET event_us=event_us-1 WHERE slot=0",
        "kind": "UPDATE backup_events SET event='RAW_SECRET_CANARY' WHERE slot=0",
        "digest": "UPDATE backup_generations SET digest='" + "f" * 64 + "' WHERE slot=0",
        "count": "UPDATE backup_generations SET row_count=row_count+1 WHERE slot=0",
        "pointer": "UPDATE backup_root SET active=0",
        "schema": "CREATE TABLE unrelated(secret TEXT)",
    }[damage]
    with sqlite3.connect(saved) as c:
        c.execute(sql)
    before = saved.read_bytes()
    assert act(files, "prune").status == "failed"
    result = backup.run(
        "restore",
        saved,
        OWNER,
        SERVICE,
        NOW,
        db=tmp_path / "new.sqlite3",
        state=tmp_path / "new-state.sqlite3",
        execute=True,
    )
    assert result.status == "failed" and result.archive_created == 0
    assert saved.read_bytes() == before and CANARY not in json.dumps(asdict(result))


@pytest.mark.parametrize("damage", ["record", "hash", "time", "kind"])
def test_corrupt_source_leaves_previous_generation(files, damage):
    assert act(files).status == "ok"
    db, _, saved = files
    with sqlite3.connect(db) as c:
        if damage == "record":
            c.execute("UPDATE operation_events SET record=?", (CANARY,))
        elif damage == "hash":
            c.execute("UPDATE operation_events SET event_hash=upper(event_hash)")
        elif damage == "time":
            c.execute("UPDATE operation_events SET event_us=event_us-1")
        else:
            c.execute("UPDATE operation_events SET event=?", (CANARY,))
    before = saved.read_bytes()
    result = act(files)
    assert result.error == "source_integrity" and result.backup_prune_committed
    assert not result.generation_committed and saved.read_bytes() == before


def test_origin_and_target_mismatch_do_not_repurpose_snapshot(files, tmp_path):
    assert act(files).status == "ok"
    db, state, saved = files
    before = saved.read_bytes()
    result = backup.run(
        "capture", saved, "tea-" + "c" * 20, SERVICE, NOW, db=db, state=state, execute=True
    )
    assert result.error == "target_mismatch" and not result.backup_prune_committed
    other, otherstate = tmp_path / "other.sqlite3", tmp_path / "other-state.sqlite3"
    archive.initialize(other, execute=True)
    job.initialize(
        other,
        otherstate,
        OWNER,
        SERVICE,
        (NOW - timedelta(minutes=20)).isoformat(),
        NOW,
        execute=True,
    )
    result = backup.run(
        "capture", saved, OWNER, SERVICE, NOW, db=other, state=otherstate, execute=True
    )
    assert result.error == "origin_changed" and saved.read_bytes() == before


@pytest.mark.parametrize("failure", [sqlite3.OperationalError(CANARY), KeyboardInterrupt()])
def test_failed_generation_commit_rolls_back_after_prune(files, monkeypatch, failure):
    assert act(files).status == "ok"
    original = store.connect
    count = 0

    class FailedCommit:
        def __init__(self, c):
            self.c = c

        def __getattr__(self, name):
            return getattr(self.c, name)

        def commit(self):
            raise failure

    @contextmanager
    def connect(path, budget, *, write=False):
        nonlocal count
        with original(path, budget, write=write) as c:
            if write:
                count += 1
            yield FailedCommit(c) if write and count == 2 else c

    monkeypatch.setattr(store, "connect", connect)
    before = files[2].read_bytes()
    result = act(files)
    assert result.status in {"failed", "interrupted"} and not result.generation_committed
    assert result.backup_prune_committed and result.commit_outcome_unknown
    assert files[2].read_bytes() == before and CANARY not in json.dumps(asdict(result))


def test_restore_state_failure_removes_only_owned_new_archive(files, tmp_path, monkeypatch):
    assert act(files).status == "ok"
    original = files[2].read_bytes()

    def fail(*a, **k):
        raise RuntimeError(CANARY)

    monkeypatch.setattr(control, "initialize", fail)
    db, state = tmp_path / "new.sqlite3", tmp_path / "new-state.sqlite3"
    result = backup.run("restore", files[2], OWNER, SERVICE, NOW, db=db, state=state, execute=True)
    assert result.status == "failed" and result.archive_created == 1 and result.state_created == 0
    assert result.created_files_removed == 1 and result.orphan_files == 0
    assert not db.exists() and not state.exists() and files[2].read_bytes() == original


def test_old_initial_is_preserved_but_expired_cursor_is_rejected(files, tmp_path):
    db, state, saved = files
    state.unlink()
    initial = epoch_us(NOW - timedelta(days=31)) * 1000
    cursor = epoch_us(NOW - timedelta(minutes=10)) * 1000
    control.initialize(
        state,
        control.State(control.binding(db, OWNER, SERVICE, initial), initial, cursor),
        execute=True,
    )
    assert act(files).status == "ok"
    result = backup.run(
        "restore",
        saved,
        OWNER,
        SERVICE,
        NOW,
        db=tmp_path / "new.sqlite3",
        state=tmp_path / "new-state.sqlite3",
        execute=True,
    )
    assert result.status == "ok"
    with control.connect(tmp_path / "new-state.sqlite3") as c:
        assert control.load(c).initial_ns == initial
    result = backup.run(
        "restore",
        saved,
        OWNER,
        SERVICE,
        NOW + timedelta(days=31),
        db=tmp_path / "expired.sqlite3",
        state=tmp_path / "expired-state.sqlite3",
        execute=True,
    )
    assert result.error == "checkpoint_expired" and result.archive_created == 0


def test_clock_regression_cursor_regression_limits_and_budget(files, monkeypatch):
    assert act(files).status == "ok"
    before = files[2].read_bytes()
    for command in ("capture", "status", "prune"):
        result = act(files, command, now=NOW - timedelta(seconds=1))
        assert result.error == "clock_before_backup" and not result.backup_prune_committed
    monkeypatch.setattr(store, "MAX_ROWS", 5)
    assert act(files).error == "backup_integrity"  # existing count exceeds this artificial cap
    monkeypatch.setattr(store, "MAX_ROWS", 100_000)
    monkeypatch.setattr(store, "MAX_BYTES", 1)
    assert act(files).error == "capture_limit"
    assert files[2].read_bytes() == before
    original = store.Budget
    monkeypatch.setattr(store, "Budget", lambda: original(end=0))
    assert act(files).error == "budget_exceeded"


@pytest.mark.parametrize("kind", ["journal", "wal", "empty", "marker", "extra_file"])
def test_unowned_or_sidecar_files_are_unchanged(files, tmp_path, kind):
    saved = files[2]
    if kind in {"journal", "wal"}:
        (tmp_path / (saved.name + "-" + kind)).write_bytes(b"unknown")
    elif kind == "empty":
        saved.write_bytes(b"")
    elif kind == "marker":
        with sqlite3.connect(saved) as c:
            c.execute("PRAGMA application_id=42")
    else:
        saved = tmp_path / "extra.sqlite3"
        with sqlite3.connect(saved) as c:
            c.execute("CREATE TABLE other(x)")
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    result = backup.run("prune", saved, OWNER, SERVICE, NOW, execute=True)
    assert result.status == "failed" and before == {p: p.read_bytes() for p in tmp_path.iterdir()}


def test_hardlinks_and_existing_restore_targets_rejected(files, tmp_path):
    assert act(files).status == "ok"
    saved = files[2]
    linked = tmp_path / "linked.sqlite3"
    os.link(saved, linked)
    assert backup.run("status", linked, OWNER, SERVICE, NOW).error == "backup_file"
    linked.unlink()
    before = files[0].read_bytes()
    result = backup.run(
        "restore", saved, OWNER, SERVICE, NOW, db=files[0], state=files[1], execute=True
    )
    assert result.status == "failed" and files[0].read_bytes() == before
    assert (
        backup.run(
            "capture", saved, OWNER, SERVICE, NOW, db=saved, state=files[1], execute=True
        ).error
        == "same_file"
    )


def test_config_and_cli_are_private_read_only_and_exclusive(files, tmp_path, capsys, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(backup, "datetime", Clock)
    db, state, saved = files
    config = tmp_path / "private-config.json"
    values = dict(
        db=str(db), state=str(state), backup=str(saved), owner_id=OWNER, service_id=SERVICE
    )
    config.write_text(json.dumps(values))
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert backup.main(["capture", "--config", str(config)]) == 0
    out = capsys.readouterr()
    assert not out.err and all(
        v not in out.out for v in (str(db), str(config), OWNER, SERVICE, CANARY)
    )
    assert before == {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert backup.main(["capture", "--config", str(config), "--db", str(db)]) == 2
    capsys.readouterr()
    config.write_text('{"db":"' + CANARY + '","db":"other"}')
    assert backup.main(["capture", "--config", str(config), "--execute"]) == 2
    assert CANARY not in capsys.readouterr().out


def test_maximum_length_input_canonical_round_trip():
    value = events()[3] | dict(
        counts={k: 2**63 - 1 for k in operations.COUNTS},
        quality_flags={k: 2**63 - 1 for k in operations.QUALITY_FLAGS},
        batch_id=str(uuid4()),
        version_id=str(uuid4()),
        mode="dry_run",
    )
    raw = json.dumps(value).encode()
    assert len(raw) < MAX_LINE_BYTES
    parsed = parse_record(raw + b" " * (MAX_LINE_BYTES - len(raw)))
    assert parse_record(parsed.record.encode()) == parsed


def test_new_source_limit_future_and_cursor_regression_preserve_existing_snapshot(
    files, monkeypatch
):
    monkeypatch.setattr(store, "MAX_ROWS", 5)
    result = act(files)
    assert result.error == "capture_limit" and result.source_rows_current == 6
    assert result.generations_after == 0 and result.backup_prune_committed
    monkeypatch.setattr(store, "MAX_ROWS", 100_000)
    advance(files[1], 10)
    assert act(files).status == "ok"
    before = files[2].read_bytes()
    with sqlite3.connect(files[1]) as c:
        c.execute("UPDATE job_state SET cursor_ns=initial_ns")
    assert act(files).error == "cursor_regression"
    advance(files[1], 10)
    future = NOW + timedelta(microseconds=1)
    ingest(files[0], [events(future)[0]], now=NOW + timedelta(hours=1))
    assert act(files).error == "source_future_rows" and files[2].read_bytes() == before


def test_previous_generation_is_missing_until_two_captures(files, tmp_path):
    assert act(files).status == "ok"
    result = backup.run(
        "restore",
        files[2],
        OWNER,
        SERVICE,
        NOW,
        generation="previous",
        db=tmp_path / "new.sqlite3",
        state=tmp_path / "new-state.sqlite3",
        execute=True,
    )
    assert result.error == "generation_missing" and result.archive_created == 0


def test_restore_failure_does_not_delete_a_replacement_file(files, tmp_path, monkeypatch):
    assert act(files).status == "ok"
    new, state = tmp_path / "new.sqlite3", tmp_path / "new-state.sqlite3"
    replacement = tmp_path / "replacement.sqlite3"
    archive.initialize(replacement, execute=True)
    replacement_id = archive._identity(replacement)

    def replace(*a, **k):
        new.unlink()
        replacement.rename(new)
        raise RuntimeError(CANARY)

    monkeypatch.setattr(control, "initialize", replace)
    result = backup.run("restore", files[2], OWNER, SERVICE, NOW, db=new, state=state, execute=True)
    assert result.status == "failed" and result.orphan_files == 1
    assert result.created_files_removed == 0 and archive._identity(new) == replacement_id


def test_abrupt_generation_write_leaves_journal_for_explicit_manual_inspection(files):
    assert act(files).status == "ok"
    before = digest(files[0]), digest(files[1])
    code = """import os,sys
from pathlib import Path
from datetime import UTC,datetime
from etl.operation_logs import backup
original=backup.commit
def stop(c,result,field):
 if field=='generation_committed':os._exit(17)
 original(c,result,field)
backup.commit=stop
backup.run('capture',Path(sys.argv[3]),sys.argv[4],sys.argv[5],
 datetime(2026,11,15,12,tzinfo=UTC),db=Path(sys.argv[1]),state=Path(sys.argv[2]),execute=True)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, *(str(p) for p in files), OWNER, SERVICE],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=15,
    )
    assert child.returncode == 17 and not child.stdout and not child.stderr
    assert before == (digest(files[0]), digest(files[1]))
    result = act(files)
    assert result.error == "backup_journal_present" and not result.generation_committed


def test_backup_file_page_limit_and_archive_marker_are_separate(files, tmp_path, monkeypatch):
    assert act(files).status == "ok"
    before = files[2].read_bytes()
    with pytest.raises(archive.ArchiveError):
        archive.prune(files[2], NOW, execute=True)
    monkeypatch.setattr(store, "MAX_FILE", 1024)
    assert act(files, "status", execute=False).error == "backup_file"
    assert files[2].read_bytes() == before


def test_capture_needs_no_key_and_never_constructs_http_client(files, monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", CANARY)

    def no_network(*args, **kwargs):
        pytest.fail("backup must not make network requests")

    monkeypatch.setattr(store.render.httpx, "Client", no_network)
    assert act(files).status == "ok"
    assert CANARY.encode() not in files[2].read_bytes()


def test_status_reports_latest_snapshot_limit_utilization_without_source_read(files, monkeypatch):
    assert act(files).status == "ok"
    assert act(files).status == "ok"
    monkeypatch.setattr(store, "MAX_ROWS", 6)
    result = act(files, "status", execute=False)
    assert result.status == "ok" and result.near_capture_limit
    assert result.rows == 12 and result.latest_rows == 6 and result.latest_bytes > 0
    assert result.source_rows_current is None
