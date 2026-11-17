from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.routers.population_reference import population_session
from app.schemas.common import ErrorCode
from app.schemas.population_reference import PopulationReferenceQuery
from app.services.population_reference import _response

BASE = "/api/v2/population-reference"
VALID = {"lat": "37.5", "lng": "127", "category": "cafe"}


@pytest.mark.parametrize(
    "extra",
    [
        {"brand_scope": "all"},
        {"area": "all"},
        {"include": "living_pop"},
        {"franchise": "all"},
        {"policy": "zero"},
        {"population": "1"},
        {"radius": "500.0"},
        {"radius": "true"},
        {"lat": "nan"},
        {"lng": "181"},
        {"as_of": "2026-13"},
        {"sub_category": ""},
        {"sub_category": "korean"},
        {"sub_category": "cafe,cafe"},
        {"observation_version_id": "source"},
    ],
)
def test_invalid_input_rejected_without_acquiring_database(client, monkeypatch, extra):
    engine = Mock(side_effect=AssertionError("database acquired before validation"))
    monkeypatch.setattr(client.app.state.database, "get_engine", engine)
    r = client.get(BASE, params=VALID | extra)
    assert r.status_code == 422 and r.headers["cache-control"] == "no-store"
    engine.assert_not_called()


def test_duplicate_key_and_missing_category_rejected_before_database(client, monkeypatch):
    engine = Mock(side_effect=AssertionError("unexpected database"))
    monkeypatch.setattr(client.app.state.database, "get_engine", engine)
    for query in ["lat=37&lng=127&category=cafe&radius=300&radius=500", "lat=37&lng=127"]:
        assert client.get(BASE + "?" + query).status_code == 422
    engine.assert_not_called()


def test_route_calls_actual_service_contract_and_provides_complete_openapi(monkeypatch):
    app = create_app(Settings(_env_file=None, app_env="test"))
    session = Mock()
    app.dependency_overrides[population_session] = lambda: session

    def reply(actual_session, query):
        assert actual_session is session
        assert query == PopulationReferenceQuery(lat=37.5, lng=127.0, category="cafe")
        return _response(query, date(2026, 11, 8), None, "no_data")

    monkeypatch.setattr("app.routers.population_reference.get_population_reference", reply)
    with TestClient(app) as client:
        r = client.get(BASE, params=VALID)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["data"]["reason"] == "no_observation_in_period"
        assert body["data"]["sources"] == []
        assert body["meta"]["public_subset_calculation_performed"] == dict(
            local=False, long=False, short=False
        )
        assert body["meta"]["observation_version_id"] is None
        assert not any(key in body["data"]["scope"] for key in ("lat", "lng", "brand_scope"))
        params = client.get("/openapi.json").json()["paths"][BASE]["get"]["parameters"]
        assert {p["name"] for p in params} == set(PopulationReferenceQuery.model_fields)


def test_internal_error_keeps_no_store_and_does_not_expose_detail(client, monkeypatch):
    client.app.dependency_overrides[population_session] = lambda: Mock()

    def fail(*args):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers={"Cache-Control": "no-store"})

    monkeypatch.setattr("app.routers.population_reference.get_population_reference", fail)
    r = client.get(BASE, params=VALID)
    assert r.status_code == 500 and r.headers["cache-control"] == "no-store"
    assert r.json()["data"] is None
