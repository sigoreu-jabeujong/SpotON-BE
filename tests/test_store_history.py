from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.models import Store, StoreImportBatch
from app.routers.stores import validated_session
from app.schemas.stores import HistoryQuery
from app.services.store_history import complete_months, location_match, operating_period

KEY = "마포구-서교동-123-4"


@pytest.mark.parametrize(
    "start,end,months",
    [
        (date(2024, 1, 15), date(2024, 2, 14), 0),
        (date(2024, 1, 15), date(2024, 2, 15), 1),
        (date(2023, 1, 31), date(2023, 2, 28), 0),
        (date(2023, 1, 31), date(2023, 3, 31), 2),
        (date(2024, 2, 29), date(2025, 2, 28), 11),
        (date(2024, 2, 29), date(2025, 3, 1), 12),
        (date(2024, 2, 29), date(2024, 2, 29), 0),
    ],
)
def test_completed_calendar_month_boundaries(start: date, end: date, months: int) -> None:
    assert complete_months(start, end) == months


@pytest.mark.parametrize(
    "left,right,level,expected",
    [
        ("2층 201호", "2층 201호", "same_spot", "same_spot"),
        ("2층 201호", "2층 202호", "same_spot", "same_building"),
        ("2층", "3층", "same_building", "same_building"),
        ("2층", "2층", "same_building", "unverified"),
        ("2층 201호", "2층", "same_building", "unverified"),
        ("2층", "2층 201호", "same_spot", "unverified"),
        ("201호", "201호", "same_building", "unverified"),
        (None, "2층 201호", "same_spot", "unverified"),
        ("2층 201호", "2층 201호", "unverified", "unverified"),
        ("2층 201호", "2층 201호", "same_building", "unverified"),
        ("2층", "1~2층", "same_building", "unverified"),
    ],
)
def test_location_requires_both_floor_and_unit(left, right, level, expected) -> None:
    assert location_match(left, right, level) == expected


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"status": "closed", "close_date": None}, "missing_close_date"),
        ({"status": "other"}, "other_status"),
        ({"open_date": None}, "missing_open_date"),
        ({"open_date": date(1959, 1, 1)}, "invalid_open_date"),
        ({"open_date": date(2027, 1, 1)}, "invalid_open_date"),
        ({"status": "closed", "close_date": date(2019, 1, 1)}, "invalid_date_order"),
        ({"date_flag": "open_date_future;close_date_invalid"}, "invalid_open_date"),
        ({"close_date": date(2025, 1, 1)}, "invalid_close_date"),
    ],
)
def test_unreliable_dates_keep_history_without_fake_zero(changes, reason) -> None:
    store = Store(open_date=date(2020, 1, 1), status="open")
    for key, value in changes.items():
        setattr(store, key, value)
    result = operating_period(
        store, date(2026, 1, 1), StoreImportBatch(data_updated_at=date(2026, 1, 1))
    )
    assert result[0] is None and result[1] == reason


def test_source_version_controls_live_duration_and_unknown_batch_stays_unknown() -> None:
    store = Store(open_date=date(2020, 1, 1), status="open")
    reference = date(2025, 3, 5)
    assert operating_period(store, reference, StoreImportBatch(data_updated_at=reference))[:2] == (
        62,
        None,
    )
    assert operating_period(store, reference, None)[:2] == (None, "missing_source_date")


@pytest.mark.parametrize("key", [KEY, "마포구-서교동-123-0", "마포구-상암동-산12-3"])
def test_canonical_building_keys(key: str) -> None:
    assert HistoryQuery(building_key=key).building_key == key


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"building_key": ""},
        {"building_key": KEY + "\n"},
        {"building_key": "remote-user-input-canary"},
        {"building_key": KEY, "floor_unit": " "},
        {"building_key": KEY, "category": "korean"},
        {"building_key": KEY, "unexpected": "private-canary"},
        [("building_key", KEY), ("building_key", KEY)],
    ],
)
def test_invalid_query_never_opens_db_or_echoes_input(params, caplog) -> None:
    app = create_app(Settings(_env_file=None))
    engine = MagicMock(side_effect=AssertionError("must not open DB"))
    app.state.database.get_engine = engine
    with TestClient(app) as client:
        response = client.get("/api/stores/history", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PARAM"
    assert response.headers["cache-control"] == "no-store"
    engine.assert_not_called()
    assert "canary" not in response.text + caplog.text


def test_history_empty_and_openapi_with_database_unconfigured() -> None:
    app = create_app(Settings(_env_file=None))
    session = MagicMock()
    session.scalars.return_value = []
    session.execute.return_value.one_or_none.return_value = None
    app.dependency_overrides[validated_session] = lambda: session
    with TestClient(app) as client:
        response = client.get("/api/stores/history", params={"building_key": KEY})
        assert response.status_code == 200
        assert response.json()["data"]["total"] == 0
        assert response.json()["meta"]["data_updated_at"] is None
        assert "/api/stores/history" in client.get("/openapi.json").json()["paths"]
        assert client.get("/docs").status_code == 200


def test_database_unconfigured_fails_history_only_without_connection_details() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/stores/history", params={"building_key": KEY})
        assert response.status_code == 500
        assert response.headers["cache-control"] == "no-store"
        assert "DATABASE_URL" not in response.text
        assert client.get("/api/health").status_code == 200


def test_noncanonical_key_rejected() -> None:
    with pytest.raises(ValidationError):
        HistoryQuery(building_key="마포구-서교동-0123-4")
