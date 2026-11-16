from datetime import date
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.schemas.location_reference import LocationReferenceQuery, SourceNumber
from app.services.location_catalog import load_catalog
from app.services.location_reference import _bounds, _temporal

PATH = "/api/v2/location-reference"
PARAMS = {"lat": 37.5, "lng": 127, "category": "cafe"}


@pytest.mark.parametrize(
    "extra",
    [
        {"brand_scope": "all"},
        {"area": "all"},
        {"include": "sales"},
        {"source_version": "caller-choice"},
        {"time_mode": "nearest"},
        {"lat": "nan"},
        {"lng": "181"},
        {"radius": "500.0"},
        {"radius": "true"},
        {"as_of": "2026-13"},
        {"sub_category": "korean"},
        {"sub_category": "cafe,cafe"},
        {"amount": "1"},
    ],
)
def test_invalid_reference_input_never_acquires_database(client, monkeypatch, extra):
    engine = Mock(side_effect=AssertionError("must validate first"))
    monkeypatch.setattr(client.app.state.database, "get_engine", engine)
    response = client.get(PATH, params=PARAMS | extra)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    engine.assert_not_called()


def test_duplicate_query_and_missing_category_do_not_acquire_database(client, monkeypatch):
    engine = Mock(side_effect=AssertionError("unexpected DB"))
    monkeypatch.setattr(client.app.state.database, "get_engine", engine)
    for query in (
        "lat=37&lng=127",
        "lat=37&lng=127&category=cafe&time_mode=latest_reference&time_mode=analysis_period",
    ):
        assert client.get(PATH + "?" + query).status_code == 422
    engine.assert_not_called()


def test_source_amount_keeps_large_integer_zero_and_its_display_contract():
    maximum = 2**63 - 1
    assert SourceNumber(
        value=str(maximum), display=f"{maximum:,}원", exact_zero=False
    ).value == str(maximum)
    assert SourceNumber(value="0", display="0원", exact_zero=True).exact_zero is True
    for fields in (
        dict(value="01", display="1원", exact_zero=False),
        dict(value="0", display="0원", exact_zero=False),
        dict(value="12", display="월 12원", exact_zero=False),
        dict(value=str(2**63), display=f"{2**63:,}원", exact_zero=False),
    ):
        with pytest.raises(ValidationError):
            SourceNumber(**fields)


def test_reference_periods_are_explicit_and_catalog_contains_no_environment_ids(client):
    assert _bounds("20254") == (date(2025, 10, 1), date(2025, 12, 31))
    assert _temporal("20254", date(2023, 11, 30)) == "later_reference"
    assert _temporal("20254", date(2026, 11, 8)) == "earlier_reference"
    assert _temporal("20254", date(2025, 11, 30)) == "same_period"
    text = load_catalog().model_dump_json()
    assert '"version_id"' not in text and '"password"' not in text and '"lat"' not in text
    assert '"lng"' not in text
    assert LocationReferenceQuery(**PARAMS).time_mode == "latest_reference"
    parameters = client.get("/openapi.json").json()["paths"][PATH]["get"]["parameters"]
    assert {p["name"] for p in parameters} == set(LocationReferenceQuery.model_fields)
