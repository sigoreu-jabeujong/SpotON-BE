from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.health import HealthData

SECRET = "SECRET-DUMMY-INTERNAL-DETAIL"
ORIGIN = "http://localhost:5173"


@pytest.fixture
def crashing_client() -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, app_env="test", cors_origins=ORIGIN))
    router = APIRouter(prefix="/test")

    @router.get("/crash")
    def crash() -> None:
        raise RuntimeError(SECRET)

    @router.post("/crash")
    def crash_after_body(body: dict[str, str]) -> None:
        raise ValueError(body["secret"])

    @router.get("/invalid-response", response_model=HealthData)
    def invalid_response() -> dict[str, str]:
        return {"status": SECRET}

    app.include_router(router)
    # 기본 True를 유지해 예외가 외곽 ServerErrorMiddleware로 새는 회귀를 잡는다.
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("path", ["/test/crash", "/test/invalid-response"])
@pytest.mark.parametrize("origin", [ORIGIN, "https://untrusted.example"])
def test_unhandled_error_is_safe_and_obeys_cors(
    crashing_client: TestClient, caplog: pytest.LogCaptureFixture, path: str, origin: str
) -> None:
    response = crashing_client.get(path, params={"private": SECRET}, headers={"Origin": origin})
    assert response.status_code == 500
    assert response.json() == {
        "data": None,
        "meta": {},
        "error": {"code": "INTERNAL_ERROR", "message": "요청 처리 중 오류가 발생했습니다"},
    }
    assert SECRET not in response.text
    assert SECRET not in str(response.headers)
    assert SECRET not in caplog.text
    assert "unhandled_error type=" in caplog.text
    assert "Traceback" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    if origin == ORIGIN:
        assert response.headers["access-control-allow-origin"] == ORIGIN
    else:
        assert "access-control-allow-origin" not in response.headers


def test_internal_error_does_not_leak_request_body(
    crashing_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = crashing_client.post(
        "/test/crash", json={"secret": SECRET}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert SECRET not in response.text + caplog.text
    assert "unhandled_error type=ValueError" in caplog.text
