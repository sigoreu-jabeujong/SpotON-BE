from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DataError

from app.core.config import Settings
from app.models import Store
from etl.localdata import runner
from etl.localdata.constants import Source
from etl.localdata.snapshot import save_snapshot
from tests.etl.test_localdata_snapshot import collection
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


def configure_isolated_runner(
    database: TemporaryDatabase, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    migrate(database)
    # Only the fixture-created disposable DB is injected. Production guards are
    # independently exercised in unit tests, and never relaxed in application code.
    monkeypatch.setattr(runner, "validate_local_target", lambda settings: None)
    monkeypatch.setattr(runner, "check_local_database", lambda connection: None)
    monkeypatch.setattr(runner, "create_db_engine", lambda settings: database.engine)
    return Settings(_env_file=None)


def test_runner_replay_is_idempotent(
    temporary_database: TemporaryDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configure_isolated_runner(temporary_database, monkeypatch)
    path = save_snapshot(collection(), tmp_path)
    for _ in range(2):
        result = runner.run_import(
            Source.GENERAL_RESTAURANT, settings=settings, write=True, from_snapshot=path
        )
        assert result["affected"] == 2
    with temporary_database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Store)) == 2


def test_runner_invalid_payload_rolls_back_entire_source(
    temporary_database: TemporaryDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configure_isolated_runner(temporary_database, monkeypatch)
    original = collection()
    invalid = replace(original.rows[1], business_name="x" * 300)
    path = save_snapshot(replace(original, rows=(original.rows[0], invalid)), tmp_path)
    with pytest.raises(DataError):
        runner.run_import(
            Source.GENERAL_RESTAURANT, settings=settings, write=True, from_snapshot=path
        )
    with temporary_database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Store)) == 0
