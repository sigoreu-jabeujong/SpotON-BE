import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.db.session import create_db_engine, normalize_database_url


@dataclass
class TemporaryDatabase:
    engine: Engine
    admin_engine: Engine
    database_name: str


@pytest.fixture
def temporary_database() -> Iterator[TemporaryDatabase]:
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("SPOTON_ALLOW_DB_INTEGRATION") != "1":
        pytest.fail("명시적인 임시 DB 통합 검증 설정이 필요합니다")
    url = normalize_database_url(raw)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("통합 검증은 로컬 임시 DB만 허용합니다")
    production = Settings(_env_file=None).database_url
    if production is not None and production.get_secret_value().strip():
        configured = normalize_database_url(production.get_secret_value())
        if (configured.host, configured.port or 5432, configured.database) == (
            url.host,
            url.port or 5432,
            url.database,
        ):
            pytest.fail("일반 DATABASE_URL과 같은 DB를 테스트할 수 없습니다")

    admin = create_db_engine(Settings(_env_file=None, database_url=SecretStr(raw)))
    database_name = f"spoton_it_{uuid4().hex[:12]}"
    assert re.fullmatch(r"spoton_it_[a-f0-9]{12}", database_name)
    created = False
    engine: Engine | None = None
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}" TEMPLATE template0')
            created = True
        # URL 객체 자체를 전달해 암호를 문자열로 출력·재조립하지 않는다.
        from sqlalchemy import create_engine

        engine = create_engine(
            url.set(database=database_name),
            hide_parameters=True,
            echo=False,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        yield TemporaryDatabase(engine, admin, database_name)
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                    connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        finally:
            admin.dispose()
