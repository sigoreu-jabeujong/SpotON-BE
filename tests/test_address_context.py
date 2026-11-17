import time

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import Store
from app.routers.geocode import get_geocode_service
from app.services.address_context import AddressPair, decode_pair, encode_pair
from app.services.address_history import address_match, stored_detail
from app.services.kakao_local import KakaoLocalService
from etl.address.road_key import parse_road
from tests.test_geocode import document


def configured() -> Settings:
    return Settings(_env_file=None, history_context_signing_key=SecretStr("s" * 32))


def test_context_verifies_same_document_and_structured_road():
    doc = document()
    doc["road_address"] = {
        "address_name": "서울 마포구 양화로 160",
        "road_name": "양화로",
        "region_2depth_name": "마포구",
        "main_building_no": "160",
        "sub_building_no": "",
        "underground_yn": "N",
    }
    app = create_app(configured())
    app.dependency_overrides[get_geocode_service] = lambda: KakaoLocalService(
        api_key="synthetic",
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"documents": [doc]})),
    )
    body = {
        "address": "서울특별시 마포구 양화로 160",
        "building_key": "마포구-동교동-162-1",
        "category": "cafe",
        "lat": 37.5563,
        "lng": 126.922,
    }
    with TestClient(app) as client:
        response = client.post("/api/v3/address-context", json=body)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        pair = decode_pair(response.json()["data"]["context"], configured())
        assert pair.road_key == "마포구|양화로|N|160|0"
        assert (
            client.post(
                "/api/v3/address-context",
                json={
                    **body,
                    "building_key": "마포구-합정동-414-0",
                },
            ).status_code
            == 422
        )
        doc["road_address"]["underground_yn"] = "Y"
        assert client.post("/api/v3/address-context", json=body).status_code == 502


def test_token_tamper_wrong_key_future_and_missing_config():
    pair = AddressPair(
        building_key="마포구-서교동-490-0", road_key=None, issued_at=int(time.time())
    )
    settings = configured()
    token = encode_pair(pair, settings)
    assert decode_pair(token, settings) == pair
    for bad in [
        token + "0",
        "corrupt",
        token.split(".")[0] + "." + "0" * 64,
        token.split(".")[0] + ".한",
    ]:
        with pytest.raises(AppError) as caught:
            decode_pair(bad, settings)
        assert caught.value.code == "INVALID_PARAM"
    with pytest.raises(AppError):
        decode_pair(
            token, Settings(_env_file=None, history_context_signing_key=SecretStr("b" * 32))
        )
    with pytest.raises(AppError) as caught:
        decode_pair(token, Settings(_env_file=None))
    assert caught.value.code == "HISTORY_UNAVAILABLE"
    assert (
        Settings(_env_file=None, history_context_signing_key="").history_context_signing_key is None
    )
    with pytest.raises(AppError):
        decode_pair(
            encode_pair(pair.model_copy(update={"issued_at": int(time.time()) + 1000}), settings),
            settings,
        )


@pytest.mark.parametrize(
    "text,key",
    [
        ("서울특별시 마포구 양화로 45 2층", "마포구|양화로|N|45|0"),
        ("서울 마포구 양화로 지하45 지하1층", "마포구|양화로|Y|45|0"),
        ("서울 마포구 양화로 45-1 (서교동)", "마포구|양화로|N|45|1"),
        ("서울 마포구 독막로9길 5", "마포구|독막로9길|N|5|0"),
        ("서울 마포구 양화로 450", "마포구|양화로|N|450|0"),
        ("서울 마포구 양화로 45, 서울 마포구 다른길 1", None),
        ("경기 마포구 양화로 45", None),
        ("서울 마포구 양화로 0", None),
    ],
)
def test_road_identity(text, key):
    result = parse_road(text)
    assert (result.key if result else None) == key


def test_invalid_v3_selection_fails_before_db():
    app = create_app(configured())
    with TestClient(app) as client:
        for query in [
            "context=bad",
            "context=a&context=b",
            "context=a&floor_unit=201호",
            "context=a&unexpected=1",
        ]:
            assert client.get("/api/v3/stores/location-history?" + query).status_code == 422


@pytest.mark.parametrize(
    "road,jibun,key,expected",
    [
        ("서울 마포구 양화로 45", None, None, "road"),
        (None, "서울 마포구 서교동 490", "마포구-서교동-490-0", "jibun"),
        ("서울 마포구 양화로 45", "서울 마포구 서교동 490", "마포구-서교동-490-0", "both"),
        ("서울 마포구 양화로 지하 45", None, "마포구-서교동-490-0", "address_conflict"),
        (
            "서울 마포구 양화로 45",
            "서울 마포구 합정동 414",
            "마포구-합정동-414-0",
            "address_conflict",
        ),
        ("서울 마포구 양화로 45", "잘못된 지번", None, "address_unresolved"),
        ("잘못된 도로명", "서울 마포구 서교동 490", "마포구-서교동-490-0", "address_unresolved"),
    ],
)
def test_address_evidence_partition(road, jibun, key, expected):
    pair = AddressPair(
        building_key="마포구-서교동-490-0", road_key="마포구|양화로|N|45|0", issued_at=0
    )
    assert (
        address_match(Store(address_road=road, address_jibun=jibun, building_key=key), pair)
        == expected
    )


def test_raw_detail_can_supply_missing_floor_but_conflicts_are_not_imputed():
    store = Store(
        address_road="서울 마포구 양화로 45 2층 201호",
        address_jibun="서울 마포구 서교동 490 2층 201호",
    )
    assert stored_detail(store) == "2층 201호"
    store.address_jibun = "서울 마포구 서교동 490 3층 201호"
    assert stored_detail(store) is None
