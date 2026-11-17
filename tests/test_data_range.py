from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.data_range import DataRangeQuery


@pytest.mark.parametrize(
    "params,code",
    [
        ({}, "CATEGORY_REQUIRED"),
        ({"category": ""}, "CATEGORY_REQUIRED"),
        ({"category": "bakery", "lat": "private-canary"}, "CATEGORY_REQUIRED"),
        ({"category": "cafe", "sub_category": "korean"}, "INVALID_PARAM"),
        ({"category": "restaurant", "sub_category": "cafe"}, "INVALID_PARAM"),
        ({"category": "restaurant", "sub_category": "korean,korean"}, "INVALID_PARAM"),
        ({"category": "restaurant", "sub_category": "korean,"}, "INVALID_PARAM"),
        ({"category": "restaurant", "sub_category": "snack"}, "INVALID_PARAM"),
        ({"category": "cafe", "sub_category": ""}, "INVALID_PARAM"),
        *[
            ({"category": "cafe", key: "private-canary"}, "INVALID_PARAM")
            for key in [
                "lat",
                "lng",
                "radius",
                "as_of",
                "area",
                "franchise",
                "include_unknown",
                "include_unknown_area",
                "include_unknown_franchise",
                "extra",
            ]
        ],
        ([("category", "cafe"), ("category", "cafe")], "INVALID_PARAM"),
        (
            [("category", "restaurant"), ("sub_category", "korean"), ("sub_category", "japanese")],
            "INVALID_PARAM",
        ),
    ],
)
def test_bad_range_request_never_connects_or_echoes_input(params, code, caplog) -> None:
    app = create_app(Settings(_env_file=None, database_url=None))
    guard = MagicMock(side_effect=AssertionError("must not connect"))
    app.state.database.get_engine = guard
    with TestClient(app) as client:
        response = client.get("/api/meta/data-range", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert response.json()["meta"] == {}
    assert response.headers["cache-control"] == "no-store"
    assert "canary" not in response.text + caplog.text
    guard.assert_not_called()


def test_category_selection_needs_no_synthetic_coordinates() -> None:
    query = DataRangeQuery.model_validate(
        {"category": "restaurant", "sub_category": "korean,japanese"}
    )
    assert query.sub_category == ("korean", "japanese")
    assert set(query.model_dump()) == {"category", "sub_category"}
    assert DataRangeQuery(category="cafe").sub_category == ()


def test_range_openapi_and_missing_db_failure() -> None:
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/api/meta/data-range"]["get"]
        assert {p["name"] for p in operation["parameters"]} == {"category", "sub_category"}
        assert {p["name"] for p in operation["parameters"] if p["required"]} == {"category"}
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")
        properties = schema["components"]["schemas"]["DataRange"]["properties"]
        assert any(t.get("type") == "null" for t in properties["min_month"]["anyOf"])
        assert properties["max_date"]["format"] == "date"
        response = client.get("/api/meta/data-range", params={"category": "cafe"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert response.json()["meta"] == {} and "DATABASE_URL" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/health").status_code == 200
