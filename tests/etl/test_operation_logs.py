import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core import operations
from app.core.config import Settings
from etl.localdata import runner
from etl.localdata.constants import Source
from etl.localdata.snapshot import save_snapshot
from tests.etl.test_localdata_snapshot import collection
from tests.test_operation_logs import CANARY, events


def test_real_snapshot_cli_stdout_and_safe_stage_records(tmp_path, monkeypatch, capsys):
    snapshot = save_snapshot(collection(), tmp_path)
    monkeypatch.setattr(runner, "uuid4", lambda: UUID("00000000-0000-4000-8000-000000000001"))
    expected = runner.run_import(
        Source.GENERAL_RESTAURANT, from_snapshot=snapshot, settings=Settings(_env_file=None)
    )
    capsys.readouterr()
    assert runner.main(["--source", "general_restaurant", "--from-snapshot", str(snapshot)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected
    records = [json.loads(line) for line in captured.err.splitlines()]
    assert [(r["stage"], r["status"]) for r in records] == [
        ("import", "started"),
        ("collect", "started"),
        ("collect", "completed"),
        ("transform", "started"),
        ("transform", "completed"),
        ("import", "completed"),
    ]
    assert len({r["run_id"] for r in records}) == 1
    assert records[-1]["counts"]["transformed"] == 2
    assert records[-1]["batch_id"] == expected["batch_id"]
    for marker in ("private-name", "private-address", "synthetic-", str(tmp_path)):
        assert marker not in captured.err


def test_only_allowlisted_counts_flags_and_normalized_ids(capsys):
    version = str(uuid4())

    @operations.logged_import("market_sales")
    def work():
        return {
            "rows": True,
            "source_rows": -1,
            "inserted": 2**63,
            "transformed": float("inf"),
            "accepted": 3,
            "mode": CANARY,
            "batch_id": CANARY,
            "version_id": version.upper(),
            "address": CANARY,
            "code_check": {CANARY: CANARY},
            "flags": {"area_invalid": False, "open_date_invalid": 1, CANARY: 7},
        }

    work()
    records = events(capsys)
    final = records[-1]
    assert final["counts"] == {"accepted": 3}
    assert final["quality_flags"] == {"open_date_invalid": 1}
    assert final["version_id"] == version
    assert "batch_id" not in final and "mode" not in final
    assert CANARY not in json.dumps(records)


def test_nested_threaded_and_failed_runs_restore_context(capsys):
    @operations.logged_import("market_areas")
    def inner():
        with operations.etl_phase("prepare"):
            pass
        return {"rows": 1}

    @operations.logged_import("localdata")
    def outer():
        inner()
        with operations.etl_phase("transform"):
            pass
        return {"rows": 2}

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: outer(), range(8))) == [{"rows": 2}] * 8
    records = events(capsys)
    starts = [r for r in records if r["event"] == "etl_run" and r["status"] == "started"]
    assert len({r["run_id"] for r in starts}) == 16
    for run_id in {r["run_id"] for r in records}:
        group = [r for r in records if r["run_id"] == run_id]
        assert group[0]["status"] == "started" and group[-1]["status"] == "completed"
        assert len({r["source"] for r in group}) == 1
    assert operations._RUN.get() is None
    with operations.etl_phase("prepare"):
        pass
    assert events(capsys) == []

    @operations.logged_import("localdata")
    def failing():
        with operations.etl_phase("collect"):
            raise RuntimeError(CANARY)

    with pytest.raises(RuntimeError, match=CANARY):
        failing()
    assert [(r["stage"], r["status"]) for r in events(capsys)] == [
        ("import", "started"),
        ("collect", "started"),
        ("collect", "failed"),
        ("import", "failed"),
    ]
    assert operations._RUN.get() is None


@pytest.mark.parametrize("failure", [None, "save", "dispose"])
def test_persist_logs_follow_commit_and_preserve_cleanup_failure(monkeypatch, failure):
    from etl.market_areas import __main__ as cli

    state = {"committed": False}
    records = []
    monkeypatch.setattr(
        operations, "_emit", lambda e: records.append((dict(e), state["committed"]))
    )

    class Connection:
        def exec_driver_sql(self, *args):
            pass

        def rollback(self):
            pass

        @contextmanager
        def begin(self):
            yield
            state["committed"] = True

    class Engine:
        @contextmanager
        def connect(self):
            yield Connection()

        def dispose(self):
            if failure == "dispose":
                raise RuntimeError(CANARY)

    def save(*args):
        if failure == "save":
            raise RuntimeError(CANARY)
        return uuid4(), False

    monkeypatch.setattr(cli, "load_archive", lambda *args: SimpleNamespace(input_sha256="a" * 64))
    monkeypatch.setattr(cli, "validate_local_target", lambda *args: None)
    monkeypatch.setattr(cli, "create_db_engine", lambda *args: Engine())
    monkeypatch.setattr(cli, "check_local_database", lambda *args: None)
    monkeypatch.setattr(
        cli,
        "prepare",
        lambda *args: SimpleNamespace(areas=[SimpleNamespace(geometry_repaired=False)]),
    )
    monkeypatch.setattr(cli, "save", save)
    arguments = (Path(CANARY), "a" * 64, date(2026, 11, 12))
    if failure:
        with pytest.raises(RuntimeError, match=CANARY):
            cli.run_import(*arguments, write=True)
    else:
        assert cli.run_import(*arguments, write=True)["inserted"] == 1
    ends = [
        (r, committed)
        for r, committed in records
        if r["stage"] == "persist" and r["status"] != "started"
    ]
    assert len(ends) == 1
    assert ends[0][0]["status"] == ("failed" if failure == "save" else "completed")
    assert ends[0][1] is (failure != "save")
    assert records[-1][0]["status"] == ("failed" if failure else "completed")
    assert CANARY not in json.dumps(records)


@pytest.mark.parametrize(
    "source", ["market_areas", "market_stores", "market_sales", "market_changes", "living_pop"]
)
def test_each_other_runner_records_sanitized_source_failure(source, tmp_path, capsys):
    import importlib
    from datetime import UTC, datetime

    cli = importlib.import_module(f"etl.{source}.__main__")
    path = tmp_path / CANARY
    if source == "living_pop":
        args = (path,)
    elif source == "market_areas":
        args = (path, "a" * 64, date(2026, 11, 12))
    elif source == "market_changes":
        args = (path, "a" * 64, 2025, datetime(2026, 11, 12, tzinfo=UTC), uuid4())
    else:
        args = (path, "a" * 64, 2025, date(2026, 11, 12), uuid4())
        if source == "market_sales":
            args += (uuid4(),)
    with pytest.raises(ValueError):
        cli.run_import(*args, settings=Settings(_env_file=None))
    records = events(capsys)
    assert [(r["stage"], r["status"]) for r in records] == [
        ("import", "started"),
        ("read_source", "started"),
        ("read_source", "failed"),
        ("import", "failed"),
    ]
    assert all(r["source"] == source for r in records)
    assert CANARY not in json.dumps(records)


def test_argparse_does_not_echo_invalid_values_but_keeps_help(capsys):
    for arguments in (["--source", CANARY], ["--unknown", CANARY]):
        with pytest.raises(SystemExit) as raised:
            runner.main(arguments)
        assert raised.value.code == 2
        captured = capsys.readouterr()
        assert captured.err == "invalid arguments\n" and CANARY not in captured.out
    with pytest.raises(SystemExit) as raised:
        runner.main(["--help"])
    assert raised.value.code == 0 and "--source" in capsys.readouterr().out
