from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from fastapi import Request
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.cache import CacheResources
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import DatabaseConfigurationError, create_db_engine
from app.schemas.common import ErrorCode
from app.services.readiness import ReadinessProbe

NO_STORE = {"Cache-Control": "no-store"}


class DatabaseResources:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: Engine | None = None
        self.lock = Lock()
        self.cache = CacheResources(settings)
        self.readiness = ReadinessProbe(settings)

    def get_engine(self) -> Engine:
        with self.lock:
            if self.engine is None:
                self.engine = create_db_engine(self.settings)
            return self.engine

    def close(self) -> None:
        self.readiness.close()
        self.cache.close()
        with self.lock:
            if self.engine is not None:
                self.engine.dispose()
                self.engine = None


@contextmanager
def read_only_session(resources: DatabaseResources) -> Iterator[Session]:
    try:
        engine = resources.get_engine()
        with Session(engine) as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{resources.settings.database_statement_timeout_ms}ms"},
            )
            yield session
    except (SQLAlchemyError, DatabaseConfigurationError):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None


def history_session(request: Request) -> Iterator[Session]:
    with read_only_session(request.app.state.database) as session:
        yield session
