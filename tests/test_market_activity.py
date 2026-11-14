from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.routers.market import activity_session
from app.schemas.market_activity import ActivityQuery, MarketActivity, SubCategoryActivity
from app.services import market_activity as service
from app.services.market_activity import ActivityRecord, aggregate_activity, year_cutoff

BASE = {"lat": "37.5665", "lng": "126.978", "category": "restaurant"}


def query(**changes):
    return ActivityQuery.model_validate({**BASE, **changes})


def record(identity, opened, closed=None, sub="korean", source="general_restaurant"):
    return ActivityRecord(
        source,
        identity,
        date.fromisoformat(opened),
        date.fromisoformat(closed) if closed else None,
        sub,
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("2025-02-28", "2024-02-28"),
        ("2024-02-29", "2023-02-28"),
        ("2025-03-31", "2024-03-31"),
        ("2025-03-15", "2024-03-15"),
    ],
)
def test_calendar_year_lower_clamps_only_nonexistent_day(target, expected):
    target = date.fromisoformat(target)
    assert year_cutoff(target, target.year - 1) == date.fromisoformat(expected)


def test_recent_events_retain_closed_rows_and_exclusive_lower_inclusive_target():
    rows = [
        record("lower", "2024-02-28"),
        record("leap", "2024-02-29"),
        record("closed-old", "2020-01-01", "2025-02-28"),
        record("same-day", "2025-02-28", "2025-02-28"),
        record("future-close", "2025-02-28", "2026-01-01"),
    ]
    result = aggregate_activity(rows, query(), date(2025, 2, 28))
    assert result.recent_12m.opened == 3 and result.recent_12m.closed == 2
    assert result.recent_12m.period == "(2024-02-28, 2025-02-28]"
    assert result.by_sub_category[0].open_count == 3
    assert [r.year for r in result.yearly_trend] == [2020, 2024, 2025]
    assert result.yearly_trend[1].opened == 1  # Feb29 is beyond same month/day YTD cutoff.


def test_ytd_keeps_actual_event_year_with_zero_but_does_not_invent_gap_years():
    rows = [record("old", "2020-12-01"), record("current", "2025-01-01")]
    result = aggregate_activity(rows, query(), date(2025, 2, 28))
    assert [(r.year, r.opened, r.closed) for r in result.yearly_trend] == [
        (2020, 0, 0),
        (2025, 1, 0),
    ]
    assert aggregate_activity([], query(), date(2025, 2, 28)).yearly_trend == []


def test_trend_filters_each_event_and_keeps_old_active_and_recently_closed_records():
    rows = [
        record("old-active", "2000-01-01"),
        record("cross-boundary", "2009-12-31", "2010-01-01"),
        record("boundary", "2010-01-01"),
        record("recent-close", "2008-01-01", "2025-01-01"),
        record("pre-only", "2000-01-01", "2009-12-31"),
        record("ytd-outside", "2011-12-01", "2012-12-01"),
    ]
    result = aggregate_activity(rows, query(), date(2025, 2, 28))
    assert [(r.year, r.opened, r.closed) for r in result.yearly_trend] == [
        (2010, 1, 1),
        (2011, 0, 0),
        (2012, 0, 0),
        (2025, 0, 1),
    ]
    assert result.recent_12m.closed == 1 and result.recent_12m.opened == 0
    assert result.by_sub_category[0].open_count == 2
    assert result.by_sub_category[0].avg_operating_months == (301 + 181) // 2


@pytest.mark.parametrize("target", [date(2009, 12, 31), date(2010, 3, 1)])
def test_pre_2010_events_still_count_in_recent_window_and_operating_average(target):
    rows = [record("opened", "2009-06-01"), record("closed", "2008-01-01", "2009-09-01")]
    result = aggregate_activity(rows, query(), target)
    assert result.yearly_trend == []
    assert result.recent_12m.opened == result.recent_12m.closed == 1
    assert result.by_sub_category[0].open_count == 1
    assert result.by_sub_category[0].avg_operating_months == (6 if target.year == 2009 else 9)


def test_active_average_uses_target_not_future_closure_and_preserves_zero_and_null():
    rows = [record("a", "2024-01-31", "2026-01-01"), record("b", "2024-03-01")]
    result = aggregate_activity(rows, query(), date(2024, 3, 31))
    assert result.by_sub_category[0].open_count == 2
    assert result.by_sub_category[0].avg_operating_months == 1  # floor((2+0)/2)
    assert all(r.avg_operating_months is None for r in result.by_sub_category[1:])
    zero = aggregate_activity([record("new", "2024-03-31")], query(), date(2024, 3, 31))
    assert zero.by_sub_category[0].avg_operating_months == 0
    rounded = aggregate_activity(
        [record("a", "2024-02-29"), record("b", "2024-03-31")], query(), date(2024, 3, 31)
    )
    assert (
        rounded.by_sub_category[0].avg_operating_months == 0
    )  # 0.5 complete-month mean is floored.


def test_subcategories_and_requested_optional_flags_are_canonical():
    q = query(sub_category="western,korean", include="living_pop,sales")
    result = aggregate_activity([], q, date(2025, 2, 28))
    assert [r.sub_category for r in result.by_sub_category] == ["korean", "western"]
    assert result.flags.missing == ["sales", "living_pop"]
    assert result.sales is result.living_pop is None
    assert aggregate_activity([], query(), date(2025, 2, 28)).flags.missing == []
    assert [
        r.sub_category
        for r in aggregate_activity([], query(category="cafe"), date(2025, 2, 28)).by_sub_category
    ] == ["cafe"]


@pytest.mark.parametrize(
    "bad",
    [
        [record("same", "2020-01-01"), record("same", "2020-01-01")],
        [record("future", "2027-01-01")],
        [record("old", "1959-12-31")],
        [record("reversed", "2020-01-01", "2019-01-01")],
        [record("unsupported", "2020-01-01", sub="snack")],
    ],
)
def test_invalid_aggregate_cohort_rejected(bad):
    with pytest.raises(ValueError):
        aggregate_activity(bad, query(), date(2026, 1, 1))


def test_same_license_in_different_sources_is_two_records():
    rows = [record("same", "2020-01-01"), record("same", "2020-01-01", source="rest_cafe")]
    assert aggregate_activity(rows, query(), date(2026, 1, 1)).by_sub_category[0].open_count == 2


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"category": None}, "CATEGORY_REQUIRED"),
        ({"category": "bakery"}, "CATEGORY_REQUIRED"),
        ({"lat": "NaN"}, "INVALID_PARAM"),
        ({"radius": "501"}, "INVALID_PARAM"),
        ({"as_of": "0000-01"}, "INVALID_PARAM"),
        ({"include": ""}, "INVALID_PARAM"),
        ({"include": "sales,sales"}, "INVALID_PARAM"),
        ({"include": "sales,"}, "INVALID_PARAM"),
        ({"include": "Sales"}, "INVALID_PARAM"),
        ({"include": "sales, living_pop"}, "INVALID_PARAM"),
        ({"include": "private-canary"}, "INVALID_PARAM"),
        ({"extra": "private-canary"}, "INVALID_PARAM"),
        ({"include_unknown": "true", "include_unknown_area": "true"}, "INVALID_PARAM"),
        ({"sub_category": "cafe"}, "INVALID_PARAM"),
    ],
)
def test_invalid_request_is_private_and_precedes_database(changes, code, caplog):
    app = create_app(Settings(_env_file=None, database_url=None))
    guard = MagicMock(side_effect=AssertionError("must not connect"))
    app.state.database.get_engine = guard
    params = {k: v for k, v in {**BASE, **changes}.items() if v is not None}
    with TestClient(app) as client:
        r = client.get("/api/market/activity", params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert r.headers["cache-control"] == "no-store" and r.json()["meta"] == {}
    assert "canary" not in r.text + caplog.text
    guard.assert_not_called()


def test_duplicate_input_missing_database_and_openapi():
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        r = client.get(
            "/api/market/activity",
            params=[*BASE.items(), ("include", "sales"), ("include", "living_pop")],
        )
        assert r.status_code == 422
        r = client.get("/api/market/activity", params=BASE)
        assert r.status_code == 500 and r.headers["cache-control"] == "no-store"
        schema = client.get("/openapi.json").json()
        assert {
            p["name"]
            for p in schema["paths"]["/api/market/activity"]["get"]["parameters"]
            if p["required"]
        } == {"lat", "lng", "category"}
        assert (
            schema["components"]["schemas"]["MarketActivity"]["properties"]["sales"]["type"]
            == "null"
        )
        assert client.get("/api/health").status_code == 200


def test_response_average_and_group_invariants():
    for count, average in [(0, 0), (1, None), (True, 0)]:
        with pytest.raises(ValidationError):
            SubCategoryActivity(sub_category="cafe", open_count=count, avg_operating_months=average)
    data = aggregate_activity([record("a", "2020-01-01")], query(), date(2026, 1, 1)).model_dump()
    data["yearly_trend"] *= 2
    with pytest.raises(ValidationError):
        MarketActivity.model_validate(data)


def test_service_invariant_failure_is_safe500(monkeypatch, caplog):
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[activity_session] = lambda: MagicMock()

    def invalid(*args, **kwargs):
        raise ValueError("private-canary")

    monkeypatch.setattr(service, "_get_activity", invalid)
    with TestClient(app) as client:
        r = client.get("/api/market/activity", params=BASE)
    assert r.status_code == 500 and r.json()["data"] is None and r.json()["meta"] == {}
    assert r.headers["cache-control"] == "no-store" and "canary" not in r.text + caplog.text
