import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.routers.geocode import get_geocode_service
from app.services.kakao_local import KakaoLocalService
from tests.services.test_kakao_local import address_document


@pytest.mark.parametrize(
    "address,gu,dong",
    [
        ("서울 마포구 양화로 45", "마포구", "서교동"),
        ("서울 중구 세종대로 110", "중구", "태평로1가"),
        ("서울 중구 명동길 14", "중구", "명동2가"),
    ],
)
@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("detail", ["2층", "2층 201호"])
def test_geocode_keeps_place_details_for_single_and_multiple_candidates(
    address: str, gu: str, dong: str, count: int, detail: str
) -> None:
    docs = [address_document(gu=gu, dong=dong, main=str(100 + i), sub="") for i in range(count)]
    service = KakaoLocalService(
        api_key="test-key",
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"documents": docs})),
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_geocode_service] = lambda: service
    with TestClient(app) as client:
        response = client.get(
            "/api/geocode", params={"query": f"{address} {detail}", "category": "cafe"}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["floor_unit"] == detail
    assert len(data["candidates"]) == (count if count > 1 else 0)
    assert all(c["floor_unit"] == detail for c in data["candidates"])
    assert data["building_key"] == f"{gu}-{dong}-100-0"
