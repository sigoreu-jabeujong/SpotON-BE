import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.location_history import LocationHistoryQuery
from app.services.location_history import compare_detail

PARAMS = {
    "building_key": "마포구-서교동-490-0",
    "floor_unit": "2층 201호",
    "scope": "unit",
    "identity_requirement": "address_scope",
}


@pytest.mark.parametrize(
    "stored,level,scope,expected",
    [
        ("2층", "same_building", "floor", "match"),
        ("2층", "same_building", "unit", "unresolved"),
        ("2층 201호", "same_spot", "unit", "match"),
        ("2층 202호", "same_spot", "unit", "unit"),
        ("3층 201호", "same_spot", "unit", "floor"),
        ("B2 201호", "same_spot", "floor", "floor"),
        ("201호", "same_building", "unit", "unresolved"),
        ("2층 201호", "unverified", "unit", "unresolved"),
        (None, "same_building", "floor", "unresolved"),
    ],
)
def test_explicit_matching(stored, level, scope, expected):
    assert compare_detail("2층 201호", stored, level, scope) == expected


@pytest.mark.parametrize(
    "detail,scope", [("201호", "unit"), ("2층", "unit"), ("1~2층", "floor"), ("", "floor")]
)
def test_missing_and_ambiguous_detail_is_invalid(detail, scope):
    with pytest.raises(ValidationError):
        LocationHistoryQuery(**{**PARAMS, "floor_unit": detail, "scope": scope})


def test_pending_identity_and_validation_do_not_require_database():
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        response = client.get(
            "/api/v2/stores/location-history",
            params={**PARAMS, "identity_requirement": "verified_building"},
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()["data"]
        assert data["result_status"] == "pending_identity"
        assert data["location_coverage"] == "not_evaluated"
        assert data["stores"] == []
        assert (
            client.get(
                "/api/v2/stores/location-history", params={**PARAMS, "floor_unit": "201호"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v2/stores/location-history", params={**PARAMS, "status": "open"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v2/stores/location-history", params=[*PARAMS.items(), ("scope", "floor")]
            ).status_code
            == 422
        )
