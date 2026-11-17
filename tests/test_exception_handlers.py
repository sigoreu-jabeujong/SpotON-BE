from collections.abc import Iterator

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import ERROR_SPECS, AppError
from app.main import create_app
from app.schemas.common import ErrorCode
from app.schemas.responses import VALIDATION_ERROR_RESPONSES

SECRET = "SECRET-DUMMY-REQUEST-DATA"
ORIGIN = "http://localhost:5173"


class SampleInput(BaseModel):
    count: int


@pytest.fixture
def error_client() -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, app_env="test", cors_origins=ORIGIN))
    router = APIRouter(prefix="/test", responses=VALIDATION_ERROR_RESPONSES)

    @router.get("/domain/{code}")
    def domain_error(code: ErrorCode) -> None:
        raise AppError(code)

    @router.get("/query")
    def query_error(count: int) -> dict[str, int]:
        return {"count": count}

    @router.post("/body")
    def body_error(body: SampleInput) -> dict[str, int]:
        return {"count": body.count}

    @router.get("/http/{status_code}")
    def http_error(status_code: int) -> None:
        raise HTTPException(
            status_code=status_code,
            detail=SECRET,
            headers={
                "WWW-Authenticate": "Bearer",
                "Retry-After": "60",
                "X-Debug-Detail": SECRET,
            },
        )

    app.include_router(router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("code", list(ErrorCode))
def test_domain_error_mapping(error_client: TestClient, code: ErrorCode) -> None:
    response = error_client.get(f"/test/domain/{code}")
    status, message = ERROR_SPECS[code]
    assert response.status_code == status
    assert response.json() == {
        "data": None,
        "meta": {},
        "error": {"code": code.value, "message": message},
    }


@pytest.mark.parametrize("mode", ["query", "body", "json"])
def test_request_validation_hides_input(
    error_client: TestClient, caplog: pytest.LogCaptureFixture, mode: str
) -> None:
    if mode == "query":
        response = error_client.get("/test/query", params={"count": SECRET})
    elif mode == "body":
        response = error_client.post("/test/body", json={"count": SECRET})
    else:
        response = error_client.post(
            "/test/body", content=SECRET, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PARAM"
    assert SECRET not in response.text
    assert SECRET not in str(response.headers)
    assert SECRET not in caplog.text


def test_unknown_path_and_method_use_common_response(error_client: TestClient) -> None:
    missing = error_client.get("/missing")
    wrong_method = error_client.post("/api/health")
    assert missing.status_code == 404
    assert wrong_method.status_code == 405
    assert wrong_method.headers["allow"] == "GET"
    for response in (missing, wrong_method):
        assert response.json() == {
            "data": None,
            "meta": {},
            "error": {"code": "INVALID_PARAM", "message": ERROR_SPECS[ErrorCode.INVALID_PARAM][1]},
        }


@pytest.mark.parametrize("status", [401, 403, 429, 502, 503])
def test_http_status_and_protocol_headers_are_preserved(
    error_client: TestClient, status: int
) -> None:
    response = error_client.get(f"/test/http/{status}")
    assert response.status_code == status
    expected = "INTERNAL_ERROR" if status >= 500 else "INVALID_PARAM"
    assert response.json()["error"]["code"] == expected
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["retry-after"] == "60"
    assert "x-debug-detail" not in response.headers
    assert SECRET not in response.text


@pytest.mark.parametrize("status", [204, 304])
def test_no_content_status_is_not_wrapped(error_client: TestClient, status: int) -> None:
    response = error_client.get(f"/test/http/{status}")
    assert response.status_code == status
    assert response.content == b""


@pytest.mark.parametrize("path", ["/missing", "/test/query", "/test/domain/OUT_OF_SEOUL"])
@pytest.mark.parametrize("origin", [ORIGIN, "https://untrusted.example"])
def test_handled_errors_obey_cors(error_client: TestClient, path: str, origin: str) -> None:
    response = error_client.get(path, headers={"Origin": origin})
    assert response.status_code >= 400
    if origin == ORIGIN:
        assert response.headers["access-control-allow-origin"] == ORIGIN
    else:
        assert "access-control-allow-origin" not in response.headers


def test_openapi_matches_common_error_envelope(error_client: TestClient) -> None:
    schema = error_client.get("/openapi.json").json()
    for path, method, statuses in [
        ("/api/health", "get", [500]),
        ("/test/query", "get", [422, 500]),
        ("/test/body", "post", [422, 500]),
    ]:
        for status in statuses:
            response = schema["paths"][path][method]["responses"][str(status)]
            assert response["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    components = schema["components"]["schemas"]
    assert "HTTPValidationError" not in components
    assert components["ErrorCode"]["enum"] == [code.value for code in ErrorCode]
    assert "error" in components["ErrorResponse"]["required"]
