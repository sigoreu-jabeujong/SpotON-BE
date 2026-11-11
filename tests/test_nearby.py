from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.schemas.nearby import NearbyQuery
from app.services.nearby import effective_date

BASE = {"lat": "37.5663", "lng": "126.9779", "category": "cafe"}


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"category": None}, "CATEGORY_REQUIRED"),
        ({"category": ""}, "CATEGORY_REQUIRED"),
        ({"category": "bakery", "lat": "NaN"}, "CATEGORY_REQUIRED"),
        ({"lat": None}, "INVALID_PARAM"),
        ({"lng": "private-coord-canary"}, "INVALID_PARAM"),
        ({"lat": "NaN"}, "INVALID_PARAM"),
        ({"lat": "Infinity"}, "INVALID_PARAM"),
        ({"lat": "-91"}, "INVALID_PARAM"),
        ({"lng": "181"}, "INVALID_PARAM"),
        ({"radius": "500.0"}, "INVALID_PARAM"),
        ({"radius": "501"}, "INVALID_PARAM"),
        ({"sub_category": "korean"}, "INVALID_PARAM"),
        ({"sub_category": "cafe,cafe"}, "INVALID_PARAM"),
        ({"as_of": "2026-13"}, "INVALID_PARAM"),
        ({"as_of": "2026-02-01"}, "INVALID_PARAM"),
        ({"as_of": "0000-01"}, "INVALID_PARAM"),
        ({"include_unknown": "1"}, "INVALID_PARAM"),
        ({"include_unknown_area": "yes"}, "INVALID_PARAM"),
        ({"include_unknown_franchise": "False"}, "INVALID_PARAM"),
        ({"include_unknown": "true", "include_unknown_area": "true"}, "INVALID_PARAM"),
        ({"area": "lt32"}, "INVALID_PARAM"),
        ({"franchise": "unknown"}, "INVALID_PARAM"),
        ({"extra": "private-argument-canary"}, "INVALID_PARAM"),
    ],
)
def test_invalid_request_stops_before_db_and_hides_input(changes, code, caplog) -> None:
    params = {**BASE, **changes}
    params = {key: value for key, value in params.items() if value is not None}
    app = create_app(Settings(_env_file=None, database_url=None))
    guard = MagicMock(side_effect=AssertionError("must not connect"))
    app.state.database.get_engine = guard
    with TestClient(app) as client:
        response = client.get("/api/stores/nearby", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert response.json()["meta"] == {}
    assert response.headers["cache-control"] == "no-store"
    assert "canary" not in response.text + caplog.text
    guard.assert_not_called()


def test_duplicate_key_rejected_before_database() -> None:
    app = create_app(Settings(_env_file=None, database_url=None))
    with TestClient(app) as client:
        response = client.get("/api/stores/nearby", params=[*BASE.items(), ("category", "cafe")])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PARAM"


@pytest.mark.parametrize("value", [True, False, "true", "false"])
def test_legacy_flag_maps_to_both_axes(value) -> None:
    query = NearbyQuery.model_validate({**BASE, "include_unknown": value})
    expected = value is True or value == "true"
    assert query.include_unknown_area is expected
    assert query.include_unknown_franchise is expected


@pytest.mark.parametrize(
    "area,franchise", [(True, False), (False, True), (True, True), (False, False)]
)
def test_independent_unknown_flags(area: bool, franchise: bool) -> None:
    query = NearbyQuery.model_validate(
        {**BASE, "include_unknown_area": area, "include_unknown_franchise": franchise}
    )
    assert (query.include_unknown_area, query.include_unknown_franchise) == (area, franchise)


def test_restaurant_categories_and_strict_numeric_inputs() -> None:
    query = NearbyQuery.model_validate(
        {**BASE, "category": "restaurant", "sub_category": "korean,japanese", "radius": "1000"}
    )
    assert query.sub_category == ("korean", "japanese") and query.radius == 1000
    with pytest.raises(ValidationError):
        NearbyQuery.model_validate({**BASE, "radius": True})


@pytest.mark.parametrize(
    "reference,minimum,month,expected",
    [
        (date(2026, 11, 8), date(2020, 1, 15), None, date(2026, 11, 8)),
        (date(2026, 11, 8), date(2020, 1, 15), "2026-11", date(2026, 11, 8)),
        (date(2026, 11, 8), date(2020, 1, 15), "2026-10", date(2026, 10, 31)),
        (date(2026, 11, 8), date(2020, 1, 15), "2024-02", date(2024, 2, 29)),
        (date(2026, 11, 8), date(2020, 1, 15), "2020-01", date(2020, 1, 31)),
        (date(2026, 11, 8), None, "2026-11", date(2026, 11, 8)),
    ],
)
def test_actual_month_end_and_latest_source_date(reference, minimum, month, expected) -> None:
    assert effective_date(reference, minimum, month) == expected


@pytest.mark.parametrize(
    "minimum,month",
    [(date(2020, 1, 15), "2019-12"), (None, "2026-10"), (date(2020, 1, 1), "2026-12")],
)
def test_out_of_range_never_fabricates_a_date(minimum, month) -> None:
    with pytest.raises(AppError) as caught:
        effective_date(date(2026, 11, 8), minimum, month)
    assert caught.value.code == "AS_OF_OUT_OF_RANGE"


def test_openapi_and_db_unconfigured_failure_are_safe() -> None:
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/api/stores/nearby"]["get"]
        assert {p["name"] for p in operation["parameters"] if p["required"]} == {
            "lat",
            "lng",
            "category",
        }
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")
        response = client.get("/api/stores/nearby", params=BASE)
        assert response.status_code == 500 and "DATABASE_URL" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/health").status_code == 200
