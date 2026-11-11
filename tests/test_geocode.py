from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.routers.geocode import get_geocode_service
from app.services.kakao_local import KakaoLocalService

ADDRESS = "서울 마포구 양화로 160"


def document() -> dict[str, object]:
    return {
        "x": "126.922",
        "y": "37.5563",
        "address": {
            "address_name": "서울 마포구 동교동 162-1",
            "region_1depth_name": "서울",
            "region_2depth_name": "마포구",
            "region_3depth_name": "동교동",
            "main_address_no": "162",
            "sub_address_no": "1",
            "mountain_yn": "N",
        },
        "road_address": {"address_name": ADDRESS},
    }


@pytest.fixture
def geocode_client() -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, app_env="test", cors_origins="http://localhost:5173"))
    service = KakaoLocalService(
        api_key="test-key",
        timeout=1,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"documents": [document()]})
        ),
    )
    app.dependency_overrides[get_geocode_service] = lambda: service
    with TestClient(app) as client:
        yield client


def test_geocode_returns_current_fe_contract_and_no_store(geocode_client: TestClient) -> None:
    response = geocode_client.get(
        "/api/geocode",
        params={"query": f"{ADDRESS} 2층 201호", "category": "cafe"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "data": {
            "address_road": ADDRESS,
            "address_jibun": "서울 마포구 동교동 162-1",
            "lat": 37.5563,
            "lng": 126.922,
            "category": "cafe",
            "is_seoul": True,
            "sigungu": "마포구",
            "building_key": "마포구-동교동-162-1",
            "floor_unit": "2층 201호",
            "candidates": [],
        },
        "meta": {"source": ["R8"], "space": "point"},
        "error": None,
    }


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"query": ADDRESS}, "CATEGORY_REQUIRED"),
        ({"query": ADDRESS, "category": "bakery"}, "CATEGORY_REQUIRED"),
        ({"query": "   ", "category": "cafe"}, "INVALID_PARAM"),
        ({"query": "   ", "category": "bakery"}, "CATEGORY_REQUIRED"),
    ],
)
def test_geocode_validates_category_before_query(
    geocode_client: TestClient, params: dict[str, str], code: str
) -> None:
    response = geocode_client.get("/api/geocode", params=params)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == code


def test_geocode_error_is_common_envelope_and_obeys_cors() -> None:
    app = create_app(Settings(_env_file=None, app_env="test", cors_origins="http://localhost:5173"))
    app.dependency_overrides[get_geocode_service] = lambda: KakaoLocalService(
        api_key="test-key",
        timeout=1,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"documents": []})),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/geocode",
            params={"query": ADDRESS, "category": "cafe"},
            headers={"Origin": "http://localhost:5173"},
        )
    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "ADDRESS_NOT_FOUND"


def test_geocode_openapi_declares_common_error_models(geocode_client: TestClient) -> None:
    schema = geocode_client.get("/openapi.json").json()
    responses = schema["paths"]["/api/geocode"]["get"]["responses"]
    for status in ("404", "422", "502"):
        assert responses[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


@pytest.mark.parametrize("field", ["main_address_no", "sub_address_no"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("10000", id="existing-out-of-range"),
        pytest.param("9" * 5000, id="oversized-number"),
    ],
)
def test_out_of_range_upstream_lot_uses_existing_404(field, value) -> None:
    raw = document()
    raw["address"][field] = value
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_geocode_service] = lambda: KakaoLocalService(
        api_key="synthetic",
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"documents": [raw]})),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/geocode",
            params={"query": ADDRESS, "category": "cafe"},
            headers={"Origin": "http://localhost:5173"},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ADDRESS_NOT_FOUND"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert value not in response.text


def test_zero_padded_upstream_lot_does_not_convert_the_large_original_string() -> None:
    from app.services.kakao_local import _parse_number

    assert _parse_number("0" * 5000 + "162") == 162
    assert _parse_number("0" * 5000) == 0
    assert _parse_number("9999") == 9999
