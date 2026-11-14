import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from etl.chains import __main__ as cli
from etl.chains import compare
from etl.chains.common import ChainsError
from etl.chains.registry import load_registry
from etl.localdata.runner import ImportConfigurationError
from tests.etl.test_chains_semas import make_snapshot


def test_collection_has_no_db_access_and_cannot_overwrite_existing_files(tmp_path, monkeypatch):
    snapshot = make_snapshot()
    calls = []

    def collect(key):
        calls.append(1)
        return snapshot

    def forbidden(*args, **kwargs):
        raise AssertionError("DB must not open")

    monkeypatch.setattr(cli, "collect", collect)
    monkeypatch.setattr(cli, "compare_local", forbidden)
    target = tmp_path / "new.json"
    result = cli.run(
        collect_semas=True,
        output=target,
        settings=Settings(_env_file=None, data_go_kr_service_key=SecretStr("fake")),
    )
    assert result["snapshot_saved"] is True and result["rows"] == 1
    with pytest.raises(ChainsError, match="output_exists"):
        cli.run(collect_semas=True, output=target)
    assert len(calls) == 1


def test_compare_checks_local_target_before_opening_any_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("DB must not open")

    monkeypatch.setattr(compare, "create_db_engine", forbidden)
    cfg = Settings(
        _env_file=None,
        database_url=SecretStr(
            "postgresql+psycopg://app:FAKE_CANARY@production.example.invalid/spoton"
        ),
    )
    with pytest.raises(ImportConfigurationError, match="wrong_target"):
        compare.compare_local(cfg, load_registry())


def test_failed_operations_never_echo_credential_paths_or_exception_text(monkeypatch, capsys):
    def forbidden(**kwargs):
        raise RuntimeError("SECRET_CANARY_URL")

    monkeypatch.setattr(cli, "run", forbidden)
    assert cli.main(["--compare-local"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "chains:operation_failed"}
    assert "CANARY" not in captured.out + captured.err


def test_invalid_cli_and_mixed_modes_do_not_start_network_or_db(monkeypatch, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--key", "SECRET_CANARY"])
    assert error.value.code == 2
    assert "CANARY" not in capsys.readouterr().err
    assert cli.main(["--collect-semas", "--output", "unused", "--snapshot", "SECRET_CANARY"]) == 1
    assert "CANARY" not in capsys.readouterr().out
    with pytest.raises(ChainsError):
        cli.run(collect_semas=True, output=Path(__file__).with_name("CANARY.json"))
