import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from etl.operation_logs import archive, backup, job
from etl.operation_logs import backup_export as export
from etl.operation_logs import backup_store as store
from etl.operation_logs import job_state as control
from etl.operation_logs.validation import epoch_us, parse_record

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)
OWNER, SERVICE = "tea-" + "a" * 20, "srv-" + "b" * 20
CANARY = "PRIVATE_EXPORT_CANARY"


def event(when=NOW - timedelta(minutes=1)):
    return dict(
        time=when.isoformat(),
        event="api_request",
        path="/api/health",
        status_code=200,
        duration_ms=0.0,
        request_id=str(uuid4()),
        response_complete=True,
    )


def six_events():
    common = dict(time=(NOW - timedelta(minutes=1)).isoformat())
    etl = dict(source="living_pop", run_id=str(uuid4()), status="completed", duration_ms=0.0)
    return [
        event(),
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


@pytest.fixture
def files(tmp_path):
    db, state, saved = (tmp_path / n for n in ("events.sqlite3", "job.sqlite3", "backup.sqlite3"))
    archive.initialize(db, execute=True)
    job.initialize(
        db, state, OWNER, SERVICE, (NOW - timedelta(minutes=20)).isoformat(), NOW, execute=True
    )
    raw = b"\n".join(json.dumps(v).encode() for v in six_events()) + b"\n"
    assert archive.ingest(db, io.BytesIO(raw), NOW, execute=True)["inserted"] == 6
    assert backup.run("init", saved, OWNER, SERVICE, NOW, execute=True).status == "ok"
    assert capture((db, state, saved)).status == "ok"
    return db, state, saved


def capture(files):
    return backup.run(
        "capture", files[2], OWNER, SERVICE, NOW, db=files[0], state=files[1], execute=True
    )


def read(path, now=NOW):
    budget = store.Budget()
    with store.connect(path, budget) as c:
        return store.load(c, store.target_hash(OWNER, SERVICE), epoch_us(now), budget)


def act(files, output, *, execute=True, now=NOW, owner=OWNER):
    return export.run(files[2], output, owner, SERVICE, now, execute=execute)


def byte_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_records(path, slot, values, **changes):
    budget = store.Budget()
    with store.connect(path, budget, write=True) as c:
        snap = store.load(c, store.target_hash(OWNER, SERVICE), epoch_us(NOW), budget)
        rows = sorted(
            [parse_record(json.dumps(v).encode()) for v in values], key=lambda r: r.event_hash
        )
        value = replace(snap.generations[slot], row_count=len(rows), **changes)
        digest = store.digest(snap.target, snap.origin, value, rows)
        c.execute("DELETE FROM backup_events WHERE slot=?", (slot,))
        for r in rows:
            c.execute(
                "INSERT INTO backup_events VALUES(?,?,?,?,?)",
                (slot, r.event_hash, r.event_us, r.event, r.record),
            )
        c.execute(
            "UPDATE backup_generations SET row_count=?,digest=?,cursor_ns=? WHERE slot=?",
            (len(rows), digest, value.cursor_ns, slot),
        )
        c.commit()


@pytest.mark.parametrize("sequence", [1, 2, 4])
def test_logical_round_trip_both_generations_and_rebinding(files, tmp_path, sequence):
    for _ in range(sequence - 1):
        assert capture(files).status == "ok"
    original = read(files[2])
    # SQLite permits trailing bytes; logical export must not clone them.
    with files[2].open("ab") as stream:
        stream.write(CANARY.encode())
    before = [byte_hash(p) for p in files]
    output = tmp_path / "export.sqlite3"
    result = act(files, output)
    assert result.status == "ok", asdict(result)
    assert result.output_verified and result.integrity_verified and result.created == 1
    assert result.sequence == sequence and result.generations == min(sequence, 2)
    assert result.rows == min(sequence, 2) * 6 and result.rows_skipped_expired == 0
    assert (
        result.output_sha256 == byte_hash(output) and result.output_bytes == output.stat().st_size
    )
    assert not result.encrypted and not result.remote_uploaded and not result.coverage_verified
    assert CANARY.encode() not in output.read_bytes() and read(output) == original
    assert before == [byte_hash(p) for p in files]
    for selection in ("latest", "previous") if sequence > 1 else ("latest",):
        db, state = (tmp_path / (selection + suffix) for suffix in (".sqlite3", "-state.sqlite3"))
        restored = backup.run(
            "restore",
            output,
            OWNER,
            SERVICE,
            NOW,
            db=db,
            state=state,
            generation=selection,
            execute=True,
        )
        assert restored.status == "ok" and restored.rows_restored == 6
        with control.connect(state) as c:
            value = control.load(c)
            assert value.binding == control.binding(db, OWNER, SERVICE, value.initial_ns)
        assert job.run_once(db, state, OWNER, SERVICE, None, NOW).status == "ok"


def test_expiry_exact_boundary_every_generation_and_earliest_expiry(files, tmp_path):
    assert capture(files).status == "ok"
    cutoff = NOW - timedelta(days=30)
    older = [
        event(cutoff - timedelta(microseconds=1)),
        event(cutoff),
        event(cutoff + timedelta(microseconds=1)),
    ]
    set_records(files[2], 0, older)
    set_records(files[2], 1, [event(cutoff), event()])
    before = byte_hash(files[2])
    output = tmp_path / "export.sqlite3"
    preview = act(files, output, execute=False)
    assert preview.status == "ok" and not output.exists()
    assert preview.source_rows == 5 and preview.rows == 2 and preview.rows_skipped_expired == 3
    assert preview.next_expiry_at == job.stamp(epoch_us(NOW) * 1000 + 1000)
    assert preview.output_sha256 is None and preview.output_bytes is None
    result = act(files, output)
    assert result.status == "ok" and result.rows == 2 and byte_hash(files[2]) == before
    snap = read(output)
    assert snap.generations[0].row_count == snap.generations[1].row_count == 1
    assert all(r.event_us > epoch_us(cutoff) for rows in snap.records.values() for r in rows)


def test_empty_generation_and_all_expired_are_valid_and_have_no_next_expiry(files, tmp_path):
    set_records(files[2], 0, [event(NOW - timedelta(days=30))])
    output = tmp_path / "export.sqlite3"
    result = act(files, output)
    assert result.status == "ok" and result.rows == 0 and result.rows_skipped_expired == 1
    assert result.next_expiry_at is None and read(output).generations[0].row_count == 0
    empty = tmp_path / "empty.sqlite3"
    result = export.run(output, empty, OWNER, SERVICE, NOW, execute=True)
    assert result.status == "ok" and result.source_rows == result.rows == 0
    assert result.next_expiry_at is None


def test_preview_does_not_create_files_or_write_sources_or_use_credentials(
    files, tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("keyless export cannot create HTTP clients or output files in preview")

    monkeypatch.setenv("RENDER_API_KEY", CANARY)
    monkeypatch.setattr(store.render.httpx, "Client", forbidden)
    monkeypatch.setattr(export, "create_file", forbidden)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = act(files, tmp_path / "new.sqlite3", execute=False)
    assert result.status == "ok" and result.would_create == 1 and result.created == 0
    assert result.integrity_verified and not result.output_verified
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert all(v not in json.dumps(asdict(result)) for v in (OWNER, SERVICE, CANARY, str(tmp_path)))


@pytest.mark.parametrize(
    "kind",
    [
        "target",
        "header",
        "schema",
        "canonical",
        "digest",
        "future",
        "expired_cursor",
        "ahead_cursor",
        "no_generation",
    ],
)
def test_invalid_source_never_creates_output(files, tmp_path, kind):
    owner, now = OWNER, NOW
    if kind == "target":
        owner = "tea-" + "c" * 20
    elif kind == "future":
        now = NOW - timedelta(microseconds=1)
    elif kind == "expired_cursor":
        now = NOW + timedelta(days=31)
    elif kind == "ahead_cursor":
        set_records(files[2], 0, [event()], cursor_ns=epoch_us(NOW - timedelta(minutes=1)) * 1000)
    else:
        with closing(sqlite3.connect(files[2])) as c, c:
            if kind == "header":
                c.execute("PRAGMA application_id=42")
            elif kind == "schema":
                c.execute("CREATE TABLE other(x)")
            elif kind == "canonical":
                c.execute("UPDATE backup_events SET record=?", (CANARY,))
            elif kind == "digest":
                c.execute("UPDATE backup_generations SET digest=?", ("0" * 64,))
            else:
                c.execute("DELETE FROM backup_events")
                c.execute("DELETE FROM backup_generations")
                c.execute("UPDATE backup_root SET origin=NULL,active=NULL")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    output = tmp_path / "export.sqlite3"
    result = act(files, output, owner=owner, now=now)
    assert result.status == "failed" and not output.exists() and result.created == 0
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert CANARY not in json.dumps(asdict(result))
    if kind in {"canonical", "digest"}:
        assert result.error == "source_integrity"
    if kind == "expired_cursor":
        assert result.error == "checkpoint_expired"
    if kind == "ahead_cursor":
        assert result.error == "clock_behind_checkpoint"


@pytest.mark.parametrize(
    "kind",
    [
        "relative",
        "git",
        "missing_parent",
        "existing",
        "same",
        "output_journal",
        "source_journal",
        "source_hardlink",
    ],
)
def test_paths_and_sidecars_are_not_overwritten(files, tmp_path, kind):
    output = tmp_path / "export.sqlite3"
    if kind == "relative":
        output = Path("export.sqlite3")
    elif kind == "git":
        output = Path(__file__).resolve().parents[2] / "export.sqlite3"
    elif kind == "missing_parent":
        output = tmp_path / "absent" / "export.sqlite3"
    elif kind == "same":
        output = files[2]
    elif kind == "existing":
        output.write_bytes(CANARY.encode())
    elif kind == "output_journal":
        Path(str(output) + "-journal").write_bytes(CANARY.encode())
    elif kind == "source_journal":
        Path(str(files[2]) + "-journal").write_bytes(CANARY.encode())
    else:
        os.link(files[2], tmp_path / "linked.sqlite3")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = act(files, output)
    assert result.status == "failed" and result.created == 0
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_symlink_output_and_source_rejected(files, tmp_path):
    linked = tmp_path / "linked.sqlite3"
    try:
        linked.symlink_to(files[2])
    except OSError:
        pytest.skip("OS does not allow this account to create symlinks")
    assert act(files, linked).status == "failed"
    result = export.run(linked, tmp_path / "new.sqlite3", OWNER, SERVICE, NOW, execute=True)
    assert result.status == "failed" and result.created == 0
    assert linked.is_symlink()


@pytest.mark.parametrize("stage", ["write", "commit", "verify", "hash", "interrupt"])
def test_failure_cleanup_and_commit_uncertainty_are_reported(files, tmp_path, monkeypatch, stage):
    output = tmp_path / "new.sqlite3"

    def fail(*args, **kwargs):
        raise KeyboardInterrupt if stage == "interrupt" else RuntimeError(CANARY)

    if stage == "commit":

        def uncertain(c, result):
            result.commit_outcome_unknown = True
            c.commit()
            raise sqlite3.OperationalError(CANARY)

        monkeypatch.setattr(export, "commit", uncertain)
    else:
        monkeypatch.setattr(
            export,
            {
                "write": "write_file",
                "verify": "verify_file",
                "hash": "file_hash",
                "interrupt": "write_file",
            }[stage],
            fail,
        )
    before = [byte_hash(p) for p in files]
    result = act(files, output)
    assert result.status == ("interrupted" if stage == "interrupt" else "failed")
    assert result.created == result.created_files_removed == 1 and result.orphan_files == 0
    assert not output.exists() and before == [byte_hash(p) for p in files]
    assert (
        not result.output_verified
        and result.output_sha256 is None
        and result.effects_may_be_partial
    )
    assert result.commit_outcome_unknown == (stage == "commit")
    assert CANARY not in json.dumps(asdict(result))


def test_replacement_file_and_cleanup_failure_are_preserved(files, tmp_path, monkeypatch):
    output, replacement = tmp_path / "new.sqlite3", tmp_path / "replacement.sqlite3"
    replacement.write_bytes(CANARY.encode())
    identity = archive._identity(replacement)

    def swap(*args, **kwargs):
        output.unlink()
        replacement.rename(output)
        raise RuntimeError(CANARY)

    monkeypatch.setattr(export, "verify_file", swap)
    result = act(files, output)
    assert result.orphan_files == 1 and result.created_files_removed == 0
    assert archive._identity(output) == identity and output.read_bytes() == CANARY.encode()


def test_failed_cleanup_reports_remaining_file(files, tmp_path, monkeypatch):
    output = tmp_path / "new.sqlite3"
    original = Path.unlink

    def no_remove(path, *args, **kwargs):
        if path == output:
            raise PermissionError(CANARY)
        return original(path, *args, **kwargs)

    def fail(*args, **kwargs):
        raise RuntimeError(CANARY)

    monkeypatch.setattr(Path, "unlink", no_remove)
    monkeypatch.setattr(export, "verify_file", fail)
    result = act(files, output)
    assert result.status == "failed" and result.orphan_files == 1 and result.effects_may_be_partial
    assert output.exists() and not result.output_verified


def test_output_race_never_overwrites_an_existing_file(files, tmp_path, monkeypatch):
    output = tmp_path / "new.sqlite3"
    original = export.create_file

    def race(path, *args):
        path.write_bytes(CANARY.encode())
        return original(path, *args)

    monkeypatch.setattr(export, "create_file", race)
    result = act(files, output)
    assert result.status == "failed" and result.created == result.created_files_removed == 0
    assert output.read_bytes() == CANARY.encode() and not result.effects_may_be_partial


def test_change_during_hash_and_closed_output_corruption_are_detected(files, tmp_path, monkeypatch):
    original = export.file_hash

    def changed(path, *args):
        answer = original(path, *args)
        with path.open("ab") as stream:
            stream.write(b"changed")
        return answer

    monkeypatch.setattr(export, "file_hash", changed)
    result = act(files, tmp_path / "new.sqlite3")
    assert result.error == "output_changed" and result.created_files_removed == 1
    assert result.output_sha256 is None


def test_source_may_advance_after_read_transaction_without_altering_export(
    files, tmp_path, monkeypatch
):
    original = export.write_file

    def advance(*args, **kwargs):
        # A real capture can commit only after export has released its read transaction.
        assert capture(files).sequence == 2
        return original(*args, **kwargs)

    monkeypatch.setattr(export, "write_file", advance)
    output = tmp_path / "new.sqlite3"
    result = act(files, output)
    assert result.status == "ok" and result.sequence == 1
    assert read(output).generations[0].sequence == 1 and read(files[2]).generations[1].sequence == 2


def test_actual_concurrent_writer_cannot_mix_generation_and_records(files, tmp_path, monkeypatch):
    signal = tmp_path / "writer-ready"
    code = """import json,sys,sqlite3
from pathlib import Path
from datetime import UTC,datetime
from dataclasses import replace
from etl.operation_logs import backup_store as s
from etl.operation_logs.validation import epoch_us
p=Path(sys.argv[1]); b=s.Budget()
c=sqlite3.connect(p.as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=10)
c.execute('BEGIN IMMEDIATE')
v=s.load(c,s.target_hash(sys.argv[2],sys.argv[3]),epoch_us(datetime(2026,11,15,12,0,1,tzinfo=UTC)),b)
g=replace(v.generations[0],captured_us=v.generations[0].captured_us+1)
c.execute('UPDATE backup_generations SET captured_us=?,digest=? WHERE slot=0',
 (g.captured_us,s.digest(v.target,v.origin,g,v.records[0])))
Path(sys.argv[4]).write_text('ready')
c.commit(); c.close()
"""
    original = store.bounded_records
    children = []

    def during_read(*args, **kwargs):
        if not children:
            child = subprocess.Popen(
                [sys.executable, "-c", code, str(files[2]), OWNER, SERVICE, str(signal)],
                cwd=Path(__file__).resolve().parents[2],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            children.append(child)
            deadline = time.monotonic() + 6
            while not signal.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert signal.exists() and child.poll() is None
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "bounded_records", during_read)
    output = tmp_path / "new.sqlite3"
    try:
        result = act(files, output)
        assert result.status == "ok", asdict(result)
        out, err = children[0].communicate(timeout=12)
        assert children[0].returncode == 0 and not out and not err
        assert read(output).generations[0].captured_us == epoch_us(NOW)
        assert (
            read(files[2], NOW + timedelta(seconds=1)).generations[0].captured_us
            == epoch_us(NOW) + 1
        )
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


def test_budget_and_source_limits_fail_before_creating_output(files, tmp_path, monkeypatch):
    original = store.Budget
    monkeypatch.setattr(store, "Budget", lambda: original(end=0))
    output = tmp_path / "new.sqlite3"
    assert act(files, output).error == "budget_exceeded" and not output.exists()
    monkeypatch.setattr(store, "Budget", original)
    monkeypatch.setattr(store, "MAX_BYTES", 1)
    assert act(files, output).error == "capture_limit" and not output.exists()


@pytest.mark.parametrize("kind", ["contents", "unowned", "hardlink", "capacity", "budget"])
def test_closed_verification_and_output_limits_preserve_file_guards(
    files, tmp_path, monkeypatch, kind
):
    output = tmp_path / "new.sqlite3"
    original = export.write_file

    def alter(path, identity, value, now_us, result, budget):
        if kind == "capacity":
            monkeypatch.setattr(store, "MAX_FILE", 4096)
        original(path, identity, value, now_us, result, budget)
        if kind == "budget":
            budget.end = 0
        elif kind == "hardlink":
            os.link(path, tmp_path / "twin.sqlite3")
        elif kind in {"contents", "unowned"}:
            with closing(sqlite3.connect(path)) as c, c:
                if kind == "contents":
                    c.execute("UPDATE backup_events SET record=?", (CANARY,))
                else:
                    c.execute("PRAGMA application_id=42")

    monkeypatch.setattr(export, "write_file", alter)
    result = act(files, output)
    assert result.status == "failed" and not result.output_verified
    assert result.output_sha256 is None and result.effects_may_be_partial
    if kind in {"unowned", "hardlink"}:
        assert output.exists() and result.orphan_files == 1 and result.created_files_removed == 0
    else:
        assert not output.exists() and result.created_files_removed == 1
        if kind == "contents":
            assert result.error == "output_integrity"
        if kind == "capacity":
            assert result.error == "output_capacity"
        if kind == "budget":
            assert result.error == "budget_exceeded"


def test_unknown_exception_text_and_main_interrupt_do_not_leak(
    files, tmp_path, capsys, monkeypatch
):
    def fail(*args, **kwargs):
        raise store.BackupError(CANARY)

    monkeypatch.setattr(export.store, "load", fail)
    result = act(files, tmp_path / "new.sqlite3")
    assert result.error == "operation_failed" and CANARY not in json.dumps(asdict(result))

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    argv = [
        "--backup",
        str(files[2]),
        "--output",
        str(tmp_path / "new.sqlite3"),
        "--owner-id",
        OWNER,
        "--service-id",
        SERVICE,
    ]
    monkeypatch.setattr(export, "run", interrupted)
    assert export.main(argv) == 130
    assert json.loads(capsys.readouterr().out)["error"] == "interrupted"


def test_cli_is_safe_and_reports_correct_exit_codes(files, tmp_path, capsys, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(export, "datetime", Clock)
    output = tmp_path / "new.sqlite3"
    argv = [
        "--backup",
        str(files[2]),
        "--output",
        str(output),
        "--owner-id",
        OWNER,
        "--service-id",
        SERVICE,
    ]
    assert export.main(argv) == 0
    out = capsys.readouterr()
    assert not out.err and not output.exists()
    assert all(v not in out.out for v in (OWNER, SERVICE, CANARY, str(tmp_path)))
    assert json.loads(out.out)["mode"] == "dry_run"
    assert export.main(argv + ["--execute"]) == 0
    assert json.loads(capsys.readouterr().out)["output_verified"]
    assert export.main(argv + ["--execute"]) == 1
    capsys.readouterr()
    assert export.main(["--unknown", CANARY]) == 2
    out = capsys.readouterr()
    assert not out.err and CANARY not in out.out
    assert export.main(argv[:-1] + [CANARY]) == 2
    assert CANARY not in capsys.readouterr().out


def test_abrupt_process_exit_leaves_unpublished_output_for_manual_inspection(files, tmp_path):
    output = tmp_path / "new.sqlite3"
    before = [byte_hash(p) for p in files]
    code = """import os,sys
from pathlib import Path
from datetime import UTC,datetime
from etl.operation_logs import backup_export as e
def stop(c,result): os._exit(17)
e.commit=stop
e.run(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4],
 datetime(2026,11,15,12,tzinfo=UTC),execute=True)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(files[2]), str(output), OWNER, SERVICE],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=15,
    )
    assert child.returncode == 17 and not child.stdout and not child.stderr
    assert output.exists() and Path(str(output) + "-journal").exists()
    residue = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert act(files, output).status == "failed"
    assert residue == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert before == [byte_hash(p) for p in files]
