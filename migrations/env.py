import logging
import re

from alembic import context
from alembic.util import CommandError
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.db.base import Base
from app.db.session import DatabaseConfigurationError, create_db_engine

config = context.config
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def run_with_connection(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    injected = config.attributes.get("connection")
    if injected is not None:
        run_with_connection(injected)
        return
    engine = create_db_engine()
    try:
        with engine.connect() as connection:
            run_with_connection(connection)
    finally:
        engine.dispose()


def run_migrations() -> None:
    if context.is_offline_mode():
        context.configure(
            dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    failure: str | None = None
    try:
        run_online()
    except DatabaseConfigurationError:
        failure = "DB 접속 설정을 확인하세요"
    except SQLAlchemyError as exc:
        state = getattr(getattr(exc, "orig", None), "sqlstate", None)
        # SQLSTATE는 표준 5자리 코드만 허용하고 예외·SQL 원문은 출력하지 않는다.
        valid_state = isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state)
        suffix = f" (SQLSTATE {state})" if valid_state else ""
        failure = f"DB 마이그레이션 실패: {type(exc).__name__}{suffix}"
    if failure is not None:
        raise CommandError(failure)


run_migrations()
