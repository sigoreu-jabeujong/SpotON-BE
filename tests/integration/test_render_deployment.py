import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.config import Settings
from app.db.session import create_db_engine
from app.services.readiness import ReadinessProbe
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


def test_pool_capacity_timeout_and_return_recovery(temporary_database: TemporaryDatabase) -> None:
    config = Settings(
        _env_file=None,
        database_url=SecretStr(temporary_database.engine.url.render_as_string(hide_password=False)),
        database_pool_size=1,
        database_pool_timeout=0.1,
    )
    engine = create_db_engine(config)
    try:
        with engine.connect() as first:
            assert first.scalar(text("SELECT 1")) == 1
            with pytest.raises(PoolTimeoutError):
                engine.connect()
        with engine.connect() as recovered:
            assert recovered.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


def test_queued_request_gets_connection_after_release(
    temporary_database: TemporaryDatabase,
) -> None:
    """Issue #120: a request queued on a full pool is served once a connection is returned."""
    config = Settings(
        _env_file=None,
        database_url=SecretStr(temporary_database.engine.url.render_as_string(hide_password=False)),
        database_pool_size=1,
        database_pool_timeout=2,
    )
    engine = create_db_engine(config)

    def queued() -> tuple[int, float]:
        started = time.monotonic()
        with engine.connect() as connection:
            return connection.scalar(text("SELECT 1")), started

    try:
        with ThreadPoolExecutor(1) as executor:
            with engine.connect() as first:
                assert first.scalar(text("SELECT 1")) == 1
                future = executor.submit(queued)
                time.sleep(0.3)
                assert not future.done()  # really waiting on the pool, not failed
                released = time.monotonic()
            value, started = future.result(timeout=10)
            finished = time.monotonic()
        assert value == 1
        assert finished >= released and finished - started < 2
    finally:
        engine.dispose()


def test_real_readiness_sql_revision_and_admin_rejection(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    values = dict(
        _env_file=None,
        database_url=SecretStr(temporary_database.engine.url.render_as_string(hide_password=False)),
    )
    assert ReadinessProbe(Settings(**values, app_env="test")).check()
    assert not ReadinessProbe(
        Settings(**values, app_env="test", database_expected_revision="0001")
    ).check()
    assert not ReadinessProbe(Settings(**values, app_env="staging")).check()
