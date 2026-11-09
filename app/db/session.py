from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


class DatabaseConfigurationError(ValueError):
    """DB 접속 정보 원문을 포함하지 않는 설정 오류."""


def normalize_database_url(raw: str) -> URL:
    url: URL | None = None
    try:
        url = make_url(raw.strip())
    except (ArgumentError, ValueError, TypeError):
        pass
    # except 밖에서 발생시켜 내부 __context__에도 파싱 원문을 남기지 않는다.
    if url is None:
        raise DatabaseConfigurationError("DATABASE_URL 형식이 올바르지 않습니다")
    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise DatabaseConfigurationError("지원하지 않는 DB 드라이버입니다")
    if not url.host or not url.database:
        raise DatabaseConfigurationError("DATABASE_URL에 호스트와 DB 이름이 필요합니다")
    return url.set(drivername="postgresql+psycopg")


def create_db_engine(settings: Settings | None = None) -> Engine:
    config = settings if settings is not None else get_settings()
    if config.database_url is None or not config.database_url.get_secret_value().strip():
        raise DatabaseConfigurationError("DATABASE_URL이 설정되지 않았습니다")
    url = normalize_database_url(config.database_url.get_secret_value())
    return create_engine(
        url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": config.database_connect_timeout},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
        raise
    else:
        session.close()
