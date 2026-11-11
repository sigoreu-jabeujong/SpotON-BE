import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from etl.localdata import runner
from etl.localdata.constants import Source
from etl.localdata.snapshot import save_snapshot
from tests.etl.test_localdata_snapshot import collection


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://spoton_app:password-canary@remote/spoton_dev",
        "postgresql://spoton_app:password-canary@localhost/spoton_test",
        "postgresql://admin:password-canary@localhost/spoton_dev",
        "sqlite:///spoton_dev",
        "postgresql://spoton_app:password-canary@localhost/spoton_dev?host=remote",
        "postgresql://spoton_app:password-canary@localhost/spoton_dev?hostaddr=127.0.0.2",
        "postgresql://spoton_app:password-canary@localhost/spoton_dev?service=production",
        "postgresql://spoton_app:password-canary@localhost/spoton_dev?options=x",
    ],
)
def test_rejects_wrong_db_target_without_echoing_password(url: str) -> None:
    with pytest.raises(ValueError) as caught:
        runner.validate_local_target(Settings(_env_file=None, database_url=url))
    assert "password-canary" not in repr(caught.value)


def test_snapshot_dry_run_has_no_database_or_api_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = save_snapshot(collection(), tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("dry-run attempted a database/API call")

    monkeypatch.setattr(runner, "create_db_engine", forbidden)
    monkeypatch.setattr(runner, "LocalDataClient", forbidden)
    settings = Settings(_env_file=None, database_url=None, data_go_kr_service_key=None)
    result = runner.run_import(Source.GENERAL_RESTAURANT, settings=settings, from_snapshot=path)
    assert result["mode"] == "dry_run" and result["affected"] == 0
    assert result["transformed"] == 2
    assert result["reference_date"] == "2026-11-11"
    output = json.dumps(result)
    for marker in ("private-name", "private-address", "synthetic-", "private-update"):
        assert marker not in output
    assert result["update_types"] == {"other": 2}


def test_write_preflight_failure_stops_before_collection_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock()
    client = MagicMock()
    monkeypatch.setattr(runner, "create_db_engine", lambda _: engine)
    monkeypatch.setattr(runner, "LocalDataClient", client)

    def fail(connection: object) -> None:
        raise runner.ImportConfigurationError("import:database_identity")

    monkeypatch.setattr(runner, "check_local_database", fail)
    settings = Settings(
        _env_file=None, database_url="postgresql://spoton_app:x@127.0.0.1/spoton_dev"
    )
    with pytest.raises(runner.ImportConfigurationError):
        runner.run_import(Source.GENERAL_RESTAURANT, settings=settings, write=True)
    client.assert_not_called()
    engine.dispose.assert_called_once()


def test_default_cli_is_dry_run_and_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: list[dict[str, object]] = []

    def fake(source: Source, **kwargs: object) -> dict[str, object]:
        captured.append(kwargs)
        raise ValueError("private-key-canary")

    monkeypatch.setattr(runner, "run_import", fake)
    assert runner.main(["--source", "general_restaurant"]) == 1
    assert captured[0]["write"] is False
    assert "private-key-canary" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        runner.main(["--source", "general_restaurant", "--write", "--dry-run"])
    with pytest.raises(SystemExit):
        runner.main(
            ["--source", "general_restaurant", "--save-snapshot", "--from-snapshot", "x.json"]
        )


@pytest.mark.parametrize(
    "identity",
    [
        ("other", "spoton_app", False, True),
        ("spoton_dev", "admin", False, True),
        ("spoton_dev", "spoton_app", True, True),
        ("spoton_dev", "spoton_app", False, False),
    ],
)
def test_connected_identity_must_match(identity: tuple[object, ...]) -> None:
    connection = MagicMock()
    connection.execute.return_value.one.return_value = identity
    with pytest.raises(runner.ImportConfigurationError, match="database_identity"):
        runner.check_local_database(connection)


@pytest.mark.parametrize(
    "revisions", [[], ["0001"], ["0002"], ["0003"], ["0004"], ["0005"], ["0002", "0002"]]
)
def test_connected_migration_must_match(revisions: list[str]) -> None:
    connection = MagicMock()
    connection.execute.return_value.one.return_value = ("spoton_dev", "spoton_app", False, True)
    connection.scalars.return_value = revisions
    with pytest.raises(runner.ImportConfigurationError, match="migration"):
        runner.check_local_database(connection)


def test_connected_unique_constraint_must_match() -> None:
    connection = MagicMock()
    connection.execute.return_value.one.return_value = ("spoton_dev", "spoton_app", False, True)
    connection.scalars.return_value = ["0006"]
    connection.scalar.return_value = "UNIQUE (license_no)"
    with pytest.raises(runner.ImportConfigurationError, match="constraint"):
        runner.check_local_database(connection)
