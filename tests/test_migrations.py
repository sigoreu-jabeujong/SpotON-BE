from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy.exc import OperationalError

from app.db.session import DatabaseConfigurationError

ROOT = Path(__file__).resolve().parents[1]


def migration_config(buffer: StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def test_offline_sql_needs_no_database_and_preserves_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "SECRET-DUMMY-INVALID-URL")
    buffer = StringIO()
    with patch("app.db.session.create_db_engine") as create:
        command.upgrade(migration_config(buffer), "head", sql=True)
        create.assert_not_called()
    sql = buffer.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in sql
    assert "alembic_version" in sql
    assert "SECRET-DUMMY" not in sql
    buffer = StringIO()
    command.downgrade(migration_config(buffer), "0001:base", sql=True)
    assert "DROP EXTENSION" not in buffer.getvalue()


@pytest.mark.parametrize("failure", ["config", "connection"])
def test_online_migration_errors_do_not_leak_connection_details(failure: str) -> None:
    engine = Mock()
    secret = "SECRET-DUMMY-MIGRATION"
    with patch("app.db.session.create_db_engine", return_value=engine) as create:
        if failure == "config":
            create.side_effect = DatabaseConfigurationError(secret)
        else:
            engine.connect.side_effect = OperationalError("SELECT secret", {}, RuntimeError(secret))
        with pytest.raises(CommandError) as caught:
            command.upgrade(migration_config(), "head")
    assert secret not in str(caught.value)
    assert caught.value.__context__ is None
    if failure == "connection":
        engine.dispose.assert_called_once()
