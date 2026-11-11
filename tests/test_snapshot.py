from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.routers.snapshot import snapshot_session
from app.schemas.nearby import NearbyMarker
from app.services.spatial_stores import SpatialStores

BASE = {"lat": "37.5665", "lng": "126.978", "category": "restaurant", "as_of": "2020-01"}


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"category": None, "as_of": None}, "CATEGORY_REQUIRED"),
        ({"category": "bakery"}, "CATEGORY_REQUIRED"),
        ({"as_of": None}, "INVALID_PARAM"),
        ({"as_of": ""}, "INVALID_PARAM"),
        ({"as_of": "2020-01-31"}, "INVALID_PARAM"),
        ({"as_of": "0000-01"}, "INVALID_PARAM"),
        ({"as_of": "2020-13"}, "INVALID_PARAM"),
        ({"lat": None}, "INVALID_PARAM"),
        ({"lat": "NaN"}, "INVALID_PARAM"),
        ({"lat": "Infinity"}, "INVALID_PARAM"),
        ({"lat": "-91"}, "INVALID_PARAM"),
        ({"lng": "181"}, "INVALID_PARAM"),
        ({"radius": "500.0"}, "INVALID_PARAM"),
        ({"radius": "301"}, "INVALID_PARAM"),
        ({"sub_category": "cafe"}, "INVALID_PARAM"),
        ({"sub_category": "korean,korean"}, "INVALID_PARAM"),
        ({"include_unknown": "1"}, "INVALID_PARAM"),
        ({"include_unknown_area": "False"}, "INVALID_PARAM"),
        ({"include_unknown": "false", "include_unknown_franchise": "false"}, "INVALID_PARAM"),
        ({"area": "wrong"}, "INVALID_PARAM"),
        ({"franchise": "unknown"}, "INVALID_PARAM"),
        ({"private": "private-input-canary"}, "INVALID_PARAM"),
    ],
)
def test_snapshot_invalid_input_precedes_db_and_hides_values(changes, code, caplog) -> None:
    app = create_app(Settings(_env_file=None, database_url=None))
    guard = MagicMock(side_effect=AssertionError("must not connect"))
    app.state.database.get_engine = guard
    params = {k: v for k, v in {**BASE, **changes}.items() if v is not None}
    with TestClient(app) as client:
        response = client.get("/api/stores/snapshot", params=params)
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert response.json()["meta"] == {} and response.headers["cache-control"] == "no-store"
    assert "canary" not in response.text + caplog.text
    guard.assert_not_called()


def test_snapshot_duplicate_keys_and_as_of_openapi() -> None:
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        duplicate = client.get("/api/stores/snapshot", params=[*BASE.items(), ("as_of", "2020-01")])
        assert duplicate.status_code == 422
        paths = client.get("/openapi.json").json()["paths"]
        for path, expected in [
            ("/api/stores/snapshot", {"lat", "lng", "category", "as_of"}),
            ("/api/stores/nearby", {"lat", "lng", "category"}),
        ]:
            required = {p["name"] for p in paths[path]["get"]["parameters"] if p["required"]}
            assert required == expected
        r = client.get("/api/stores/snapshot", params=BASE)
        assert r.status_code == 500 and r.headers["cache-control"] == "no-store"
        assert "DATABASE_URL" not in r.text and client.get("/api/health").status_code == 200


@pytest.mark.parametrize("failure", ["duplicate", "invalid-marker"])
def test_bad_selection_fails_without_partial_rows_or_cache(monkeypatch, caplog, failure) -> None:
    marker = NearbyMarker(
        source="general_restaurant",
        license_no="private-license-canary",
        name="private-name-canary",
        sub_category="korean",
        lat=37,
        lng=127,
        distance_m=0,
        open_date=date(2020, 1, 1),
        close_date=None,
        operating_months=1,
        operating_period_status="fact",
        operating_period_reason=None,
        current_status="open",
        franchise="unknown",
        area_m2=None,
    )
    selected = SpatialStores(
        as_of=date(2020, 1, 31), markers=[marker, marker], excluded_no_coord=0, meta={}
    )

    def bad_selection(*args, **kwargs):
        if failure == "invalid-marker":
            NearbyMarker.model_validate({})
        return selected

    monkeypatch.setattr("app.services.store_snapshot.get_spatial_stores", bad_selection)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[snapshot_session] = lambda: MagicMock()
    with TestClient(app) as client:
        r = client.get("/api/stores/snapshot", params=BASE)
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert r.json()["data"] is None and r.json()["meta"] == {}
    assert r.headers["cache-control"] == "no-store" and "canary" not in r.text + caplog.text
