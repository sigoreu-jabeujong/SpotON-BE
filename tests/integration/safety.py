from sqlalchemy.engine import URL

from app.db.session import DatabaseConfigurationError, normalize_database_url

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class IntegrationTargetError(ValueError):
    """엔진·접속 정보를 만들거나 노출하지 않는 통합 테스트 선행 조건 오류."""


def canonical_host(host: str | None) -> str:
    normalized = (host or "").lower().rstrip(".")
    return "loopback" if normalized in LOOPBACK_HOSTS else normalized


def safe_url(raw: str) -> URL:
    url: URL | None = None
    try:
        url = normalize_database_url(raw)
    except DatabaseConfigurationError:
        pass
    if url is None:
        raise IntegrationTargetError("통합 검증용 DB 접속 설정을 확인하세요")
    return url


def check_integration_target(
    test_url: str | None, database_url: str | None, allow_flag: str | None
) -> URL:
    if not test_url or not test_url.strip() or allow_flag != "1":
        raise IntegrationTargetError("명시적인 임시 DB 통합 검증 설정이 필요합니다")
    url = safe_url(test_url)
    if canonical_host(url.host) != "loopback":
        raise IntegrationTargetError("통합 검증은 로컬 임시 DB만 허용합니다")
    if database_url and database_url.strip():
        configured = safe_url(database_url)
        if (canonical_host(configured.host), configured.port or 5432, configured.database) == (
            canonical_host(url.host),
            url.port or 5432,
            url.database,
        ):
            raise IntegrationTargetError("일반 DATABASE_URL과 같은 DB를 테스트할 수 없습니다")
    return url
