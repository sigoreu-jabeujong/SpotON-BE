import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import DatabaseConfigurationError
from app.schemas.common import ErrorCode
from etl.localdata import maintenance as cli

PRIVATE = "PRIVATE-URL-CANARY"


@pytest.mark.parametrize(
    "args", [["--table", PRIVATE], [PRIVATE], ["--exec"], ["--url=" + PRIVATE]]
)
def test_invalid_arguments_never_connect_or_echo(args, monkeypatch, capsys):
    run = Mock()
    monkeypatch.setattr(cli, "run_maintenance", run)
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert value["error"] == "localdata_maintenance:arguments"
    assert value["phase"] == "arguments" and captured.out.count("\n") == 1
    assert PRIVATE not in captured.out + captured.err
    run.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [None, "postgresql://spoton_app:PRIVATE@remote.example/spoton_dev", "invalid-" + PRIVATE],
)
def test_configuration_rejected_before_engine(url, monkeypatch):
    create = Mock()
    monkeypatch.setattr(cli, "create_db_engine", create)
    result = cli.run_maintenance(settings=Settings(_env_file=None, database_url=url))
    assert result.error == "configuration" and result.vacuum_completed is False
    assert PRIVATE not in repr(result)
    create.assert_not_called()


@pytest.fixture
def wired(monkeypatch):
    engine = Mock()
    session = Mock()

    @contextmanager
    def read(*args):
        yield session

    monkeypatch.setattr(cli, "create_db_engine", lambda _: engine)
    monkeypatch.setattr(cli, "_read_session", read)
    monkeypatch.setattr(cli, "_check_target", Mock())
    vacuum = Mock()
    monkeypatch.setattr(cli, "_vacuum", vacuum)
    provenance = Mock(return_value=([Mock()], date(2026, 11, 8)))
    monkeypatch.setattr(cli, "current_provenance", provenance)
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@127.0.0.1/spoton_dev"
    )
    monkeypatch.setattr(cli, "Settings", lambda: config)
    return engine, vacuum, provenance


def test_dry_run_never_runs_vacuum_or_provenance(wired, capsys):
    engine, vacuum, provenance = wired
    assert cli.main([]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["mode"] == "dry_run" and value["phase"] == "completed"
    assert value["vacuum_completed"] is False and value["provenance_checked"] is False
    assert value["batch_count"] is None and value["reference_date"] is None
    vacuum.assert_not_called()
    provenance.assert_not_called()
    engine.dispose.assert_called_once()


@pytest.mark.parametrize(
    ("stage", "error", "code", "vacuum_done", "status"),
    [
        ("preflight", cli.OwnershipError(PRIVATE), "ownership", False, 1),
        ("preflight", DatabaseConfigurationError(PRIVATE), "configuration", False, 1),
        ("vacuum", OperationalError(PRIVATE, {}, None), "vacuum", False, 1),
        ("vacuum", KeyboardInterrupt(PRIVATE), "interrupted", False, 130),
        ("provenance", AppError(ErrorCode.INTERNAL_ERROR), "provenance", True, 1),
        ("provenance", OperationalError(PRIVATE, {}, None), "database", True, 1),
        ("provenance", RuntimeError(PRIVATE), "operation_failed", True, 1),
        ("cleanup", RuntimeError(PRIVATE), "cleanup", True, 1),
    ],
)
def test_failure_keeps_actual_completed_stage_and_hides_details(
    wired, monkeypatch, capsys, stage, error, code, vacuum_done, status
):
    engine, vacuum, provenance = wired
    if stage == "preflight":
        monkeypatch.setattr(cli, "_check_target", Mock(side_effect=error))
    elif stage == "vacuum":
        vacuum.side_effect = error
    elif stage == "provenance":
        provenance.side_effect = error
    else:
        engine.dispose.side_effect = error
    assert cli.main(["--execute"]) == status
    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert set(value) == {
        "operation",
        "mode",
        "phase",
        "vacuum_completed",
        "provenance_checked",
        "batch_count",
        "reference_date",
        "error",
    }
    assert value["error"] == "localdata_maintenance:" + code and value["phase"] == stage
    assert value["vacuum_completed"] is vacuum_done
    assert value["provenance_checked"] is (stage == "cleanup")
    assert PRIVATE not in captured.out + captured.err
    engine.dispose.assert_called_once()


def test_cleanup_failure_preserves_original_error(wired):
    engine, vacuum, _ = wired
    vacuum.side_effect = cli.OwnershipError(PRIVATE)
    engine.dispose.side_effect = RuntimeError(PRIVATE)
    result = cli.run_maintenance(execute=True)
    assert result.error == "ownership" and result.phase == "vacuum"
