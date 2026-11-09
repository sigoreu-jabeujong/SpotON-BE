from unittest.mock import Mock, patch

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import (
    DatabaseConfigurationError,
    create_db_engine,
    create_session_factory,
    normalize_database_url,
    session_scope,
)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_url_is_safe(raw: str | None) -> None:
    settings = Settings(_env_file=None, database_url=SecretStr(raw) if raw is not None else None)
    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL"):
        create_db_engine(settings)


@pytest.mark.parametrize("driver", ["postgres", "postgresql", "postgresql+psycopg"])
def test_postgres_driver_is_normalized(driver: str) -> None:
    url = normalize_database_url(f"{driver}://user:password@localhost/spoton?sslmode=require")
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "require"


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-url-DUMMY-SECRET",
        "postgresql://user:DUMMY-SECRET@host:wrong-port/spoton",
        "sqlite:///DUMMY-SECRET",
        "mysql://user:DUMMY-SECRET@host/spoton",
        "postgresql+psycopg2://user:DUMMY-SECRET@host/spoton",
        "postgresql+asyncpg://user:DUMMY-SECRET@host/spoton",
        "postgresql://user:DUMMY-SECRET@/spoton",
        "postgresql://user:DUMMY-SECRET@host/",
    ],
)
def test_invalid_url_does_not_expose_secrets(raw: str, caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(DatabaseConfigurationError) as caught:
        normalize_database_url(raw)
    assert "DUMMY-SECRET" not in str(caught.value) + repr(caught.value) + caplog.text
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("timeout", [0, 61])
def test_connect_timeout_is_bounded(timeout: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_connect_timeout=timeout)


def test_engine_creation_is_lazy_and_parameters_are_hidden() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql://user:DUMMY-SECRET@127.0.0.1:1/spoton"),
        database_connect_timeout=3,
    )
    with patch("psycopg.connect") as connect:
        engine = create_db_engine(settings)
        try:
            connect.assert_not_called()
            assert engine.url.drivername == "postgresql+psycopg"
            assert engine.echo is False
            assert engine.hide_parameters is True
            factory = create_session_factory(engine)
            with factory() as session:
                assert session.bind is engine
                assert session.autoflush is False
                assert session.expire_on_commit is False
            assert not Base.metadata.tables
        finally:
            engine.dispose()


def test_engine_uses_connect_timeout() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql://user:password@localhost/spoton"),
        database_connect_timeout=7,
    )
    with patch("app.db.session.create_engine") as create:
        create_db_engine(settings)
    assert create.call_args.kwargs["connect_args"] == {"connect_timeout": 7}
    assert create.call_args.kwargs["pool_pre_ping"] is True


@pytest.mark.parametrize("failure", ["none", "body", "commit", "rollback", "close"])
def test_session_lifecycle_preserves_original_failure(failure: str) -> None:
    session = Mock(spec=Session)
    factory = Mock(spec=sessionmaker, return_value=session)
    original = RuntimeError("original")
    if failure == "commit":
        session.commit.side_effect = original
    if failure in {"rollback", "close"}:
        session.rollback.side_effect = RuntimeError("rollback failed")
    if failure == "close":
        session.close.side_effect = RuntimeError("close failed")
    if failure == "none":
        with session_scope(factory) as yielded:
            assert yielded is session
        session.commit.assert_called_once()
        session.rollback.assert_not_called()
    else:
        with pytest.raises(RuntimeError) as caught, session_scope(factory):
            if failure != "commit":
                raise original
        assert caught.value is original
        session.rollback.assert_called_once()
        if failure != "commit":
            session.commit.assert_not_called()
    session.close.assert_called_once()
