import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.store_history import location_relation


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("2층", "2층"),
        ("2층 201호", "2층 201호"),
        ("지하2층", "B2"),
        ("201호", "201호"),
        ("1~2층", None),
        ("101동 2층", None),
        ("", None),
    ],
)
def test_detail_normalization_without_db_or_provider(detail, expected):
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        response = client.post("/api/address-detail", json={"detail": detail})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["floor_unit"] == expected


@pytest.mark.parametrize(
    "left,right,level,result",
    [
        ("2층", "2층", "same_building", "same_floor"),
        ("2층 201호", "2층 202호", "same_spot", "same_floor"),
        ("2층 201호", "2층 201호", "same_spot", "same_spot"),
        ("201호", "2층 201호", "same_spot", "same_building_scope"),
        ("B2", "2층", "same_building", "same_building_scope"),
        ("2층", "2층", "unverified", "unverified"),
    ],
)
def test_independent_floor_relation(left, right, level, result):
    assert location_relation(left, right, level)["relation_level"] == result


def test_unverified_details_and_limit():
    assert (
        location_relation(None, "2층", "same_building")["relation_level"] == "same_building_scope"
    )
    assert location_relation("2층", None, "same_building")["relation_level"] == "unverified"
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        response = client.post("/api/address-detail", json={"detail": "1~2층"})
        assert response.json()["data"]["status"] == "unverified"
        assert response.json()["data"]["reason"] == "ambiguous"
        assert client.post("/api/address-detail", json={"detail": "X" * 101}).status_code == 422
