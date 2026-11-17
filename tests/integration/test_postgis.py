from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.db.session import create_session_factory, session_scope

from .conftest import TemporaryDatabase

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def migrate(database: TemporaryDatabase, revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        action = command.downgrade if downgrade else command.upgrade
        action(config, revision)


def test_real_postgis_migration_and_session_lifecycle(
    temporary_database: TemporaryDatabase,
) -> None:
    database = temporary_database
    with database.engine.connect() as connection:
        assert not connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')")
        )
    migrate(database, "0001")
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        assert int(str(connection.scalar(text("SELECT postgis_lib_version()"))).split(".")[0]) >= 3
        sql = text(
            "SELECT ST_DWithin("
            "ST_SetSRID(ST_MakePoint(126.9780,37.5665),4326)::geography, "
            "ST_SetSRID(ST_MakePoint(126.9790,37.5665),4326)::geography, :radius)"
        )
        assert connection.scalar(sql, {"radius": 100}) is True
        assert connection.scalar(sql, {"radius": 1}) is False
    with database.engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE it_tx_probe (id int UNIQUE DEFERRABLE INITIALLY DEFERRED)")
        )
    factory = create_session_factory(database.engine)
    with session_scope(factory) as session:
        session.execute(text("INSERT INTO it_tx_probe VALUES (1)"))
    with pytest.raises(RuntimeError), session_scope(factory) as session:
        session.execute(text("INSERT INTO it_tx_probe VALUES (2)"))
        raise RuntimeError("expected rollback")
    with pytest.raises(IntegrityError), session_scope(factory) as session:
        session.execute(text("INSERT INTO it_tx_probe VALUES (1)"))
    with database.engine.connect() as connection:
        assert connection.execute(
            text("SELECT id FROM it_tx_probe ORDER BY id")
        ).scalars().all() == [1]
    migrate(database, "base", downgrade=True)
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
        assert connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')")
        )
    migrate(database, "0001")
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"


def test_postgis_installation_requires_privilege(temporary_database: TemporaryDatabase) -> None:
    database = temporary_database
    role = f"spoton_it_{uuid4().hex[:12]}"
    created = False
    restricted = None
    try:
        with database.admin_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(
                f"CREATE ROLE \"{role}\" LOGIN PASSWORD 'ci_role_only' NOSUPERUSER"
            )
            created = True
            connection.exec_driver_sql(
                f'ALTER DATABASE "{database.database_name}" OWNER TO "{role}"'
            )
        restricted = create_engine(
            database.engine.url.set(username=role, password="ci_role_only"), hide_parameters=True
        )
        config = Config(str(ROOT / "alembic.ini"))
        with pytest.raises(CommandError, match="42501") as caught, restricted.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
        assert "ci_role_only" not in str(caught.value)
        with database.engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('alembic_version')")) is None
        with database.engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION postgis"))
        with restricted.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
        with database.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    finally:
        if restricted is not None:
            restricted.dispose()
        if created:
            admin_user = database.admin_engine.url.username
            assert admin_user is not None
            quoted_admin = database.admin_engine.dialect.identifier_preparer.quote(admin_user)
            with database.admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.exec_driver_sql(
                    f'ALTER DATABASE "{database.database_name}" OWNER TO {quoted_admin}'
                )
                # 임시 DB의 객체 의존성을 제거한 뒤 이번 테스트가 만든 role만 정리한다.
            with database.engine.begin() as connection:
                connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            with database.admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.exec_driver_sql(f'DROP ROLE "{role}"')
