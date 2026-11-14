from collections.abc import Iterator
from datetime import date
from itertools import product

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.context import prepare_risk_interpretation
from app.core.config import Settings
from app.main import create_app
from app.routers import market
from app.schemas.risk import RiskQuery
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def activity_db(temporary_database):
    migrate(temporary_database)
    return temporary_database


@pytest.fixture
def activity_client(activity_db) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = activity_db.engine
    with TestClient(app) as client:
        yield client


def payload(client, **changes):
    r = client.get("/api/market/activity", params={**PARAMS, **changes})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def test_closed_events_distance_boundaries_and_mean_at_requested_date(activity_db, activity_client):
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s, data_updated_at=date(2025, 2, 28))
        store(s, b, "lower", 499, open_date=date(2024, 2, 28))
        store(s, b, "leap", 500, open_date=date(2024, 2, 29))
        store(s, b, "outside", 501, open_date=date(2024, 3, 1))
        store(s, b, "epsilon-outside", 500.001, open_date=date(2024, 3, 1))
        store(
            s,
            b,
            "old-closed",
            100,
            open_date=date(2020, 1, 1),
            close_date=date(2025, 2, 28),
            status="closed",
        )
        store(
            s,
            b,
            "same-day",
            100,
            open_date=date(2025, 2, 28),
            close_date=date(2025, 2, 28),
            status="closed",
        )
        store(s, b, "missing-coordinate", None, open_date=date(2024, 3, 1))
        store(
            s,
            b,
            "missing-closed",
            None,
            open_date=date(2020, 1, 1),
            close_date=date(2025, 2, 28),
            status="closed",
        )
    data = payload(activity_client, include="living_pop,sales")
    assert data["data"]["recent_12m"] == {
        "period": "(2024-02-28, 2025-02-28]",
        "opened": 2,
        "closed": 2,
    }
    assert data["data"]["by_sub_category"][0]["open_count"] == 2
    assert data["meta"]["cohort_size"] == 4 and data["meta"]["excluded_no_coord"] == 2
    assert data["meta"]["excluded_no_coord_cohort"] == "opened_by_as_of"
    assert data["meta"]["denominator"] is None
    assert data["data"]["flags"]["missing"] == ["sales", "living_pop"]
    assert data["data"]["sales"] is data["data"]["living_pop"] is None
    assert set(data["meta"]["optional_data"]) == {"sales", "living_pop"}
    assert all(v["status"] == "pending" for v in data["meta"]["optional_data"].values())
    nearby = activity_client.get("/api/stores/nearby", params=PARAMS).json()
    assert nearby["data"]["count"] == 2 and nearby["data"]["excluded_no_coord"] == 1
    assert data["meta"]["franchise_classification"]["status"] == "pending"
    assert data["meta"]["collected_at"] is None
    assert data["meta"]["data_version"]["rule_version"] == "market-activity-license-ytd-v2"


def test_historical_active_period_does_not_use_future_closure_or_latest_data(
    activity_db, activity_client
):
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s)
        store(
            s,
            b,
            "closed-later",
            open_date=date(2020, 1, 1),
            close_date=date(2025, 1, 1),
            status="closed",
        )
        store(s, b, "other", open_date=date(2020, 1, 1), status="other")
        store(s, b, "future-open", open_date=date(2024, 1, 1))
    result = payload(activity_client, as_of="2021-02")
    rows = result["data"]["by_sub_category"]
    assert rows[0]["open_count"] == 2 and rows[0]["avg_operating_months"] == 13
    assert result["data"]["recent_12m"]["closed"] == 0
    assert [r["year"] for r in result["data"]["yearly_trend"]] == [2020]
    assert result["meta"]["as_of"] == "2021-02-28"
    assert result["meta"]["operating_period_basis"] == "elapsed_months_of_active_at_as_of"
    nearby = activity_client.get("/api/stores/nearby", params={**PARAMS, "as_of": "2021-02"}).json()
    assert nearby["data"]["count"] == 2
    assert (
        nearby["data"]["markers"][0]["operating_months"] > 13
    )  # Existing latest_data contract kept.


def test_2010_trend_boundary_keeps_entire_historical_cohort_and_risk_survivors(
    activity_db, activity_client
):
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s, data_updated_at=date(2012, 11, 8))
        store(s, b, "old-active", open_date=date(1965, 1, 1))
        store(s, b, "survivor", open_date=date(2009, 1, 1))
        store(
            s,
            b,
            "cross-boundary",
            open_date=date(2009, 12, 31),
            close_date=date(2010, 1, 1),
            status="closed",
        )
        store(
            s,
            b,
            "recent-close",
            open_date=date(2008, 1, 1),
            close_date=date(2012, 6, 1),
            status="closed",
        )
        store(s, b, "boundary", open_date=date(2010, 1, 1))
        store(
            s,
            b,
            "pre-only",
            open_date=date(2000, 1, 1),
            close_date=date(2009, 12, 31),
            status="closed",
        )
    result = payload(activity_client)
    assert [(r["year"], r["opened"], r["closed"]) for r in result["data"]["yearly_trend"]] == [
        (2010, 1, 1),
        (2012, 0, 1),
    ]
    assert set(result["meta"]["yearly_periods"]) == {"2010", "2012"}
    assert result["meta"]["cohort_size"] == 6
    assert result["data"]["recent_12m"]["closed"] == 1
    assert result["data"]["by_sub_category"][0]["open_count"] == 3
    assert result["data"]["by_sub_category"][0]["avg_operating_months"] == (574 + 46 + 34) // 3
    risk = activity_client.get("/api/risk", params=PARAMS)
    assert risk.status_code == 200, risk.text
    metrics = {row["id"]: row for row in risk.json()["data"]["indicators"]}
    assert list(metrics) == [
        "closure_rate_12m",
        "survival_rate_1y",
        "survival_rate_3y",
        "competitor_count",
    ]
    assert metrics["closure_rate_12m"]["denominator"] == 4
    assert metrics["survival_rate_3y"]["denominator"] == 1
    assert risk.json()["data"]["flags"]["missing"] == []
    early = payload(activity_client, as_of="2009-12")
    assert early["data"]["yearly_trend"] == [] and early["meta"]["yearly_periods"] == {}
    assert early["meta"]["cohort_size"] == 5
    assert early["data"]["by_sub_category"][0]["open_count"] == 4
    with Session(activity_db.engine) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        for month, years in ((None, [2010, 2012]), ("2009-12", [])):
            q = RiskQuery(**PARAMS, **({"as_of": month} if month else {}))
            prepared = prepare_risk_interpretation(s, q, Settings(_env_file=None))
            assert [r.year for r in prepared.context.activity.yearly_trend] == years
            assert "official_closure_rate" not in prepared.request.user_content
            assert "official_risk" not in prepared.request.user_content


def test_quality_cohort_and_source_identity(activity_db, activity_client):
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s)
        other = batch(s, source="rest_cafe")
        store(s, b, "shared")
        store(s, other, "shared")
        store(s, b, "bad-date", date_flag="unknown-quality-flag")
        store(s, b, "missing-open", open_date=None)
        store(s, b, "missing-close", status="closed")
        store(s, b, "review", category_review_flag=True)
        store(s, b, "temp", is_temporary=True)
        store(s, b, "inverted", close_date=date(2019, 1, 1), status="closed")
        store(s, b, "future", open_date=date(2026, 11, 11))
    result = payload(activity_client)
    assert result["data"]["by_sub_category"][0]["open_count"] == 2
    assert result["meta"]["cohort_size"] == 2
    assert result["meta"]["event_basis"] == "validated_license_dates"
    assert result["meta"]["optional_data"] == {} and result["data"]["flags"]["missing"] == []


def test_filters_and_unknown_axes_match_nearby_without_brand_reclassification(
    activity_db, activity_client
):
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s)
        for n, (area, franchise) in enumerate(product([None, 0, 32, 66], [None, True, False])):
            store(s, b, str(n), area_m2=area, is_franchise=franchise)
    for area_unknown, franchise_unknown, franchise in product(
        ["true", "false"], ["true", "false"], ["all", "franchise", "independent"]
    ):
        params = {
            "area": "lt33",
            "franchise": franchise,
            "include_unknown_area": area_unknown,
            "include_unknown_franchise": franchise_unknown,
        }
        actual = payload(activity_client, **params)["data"]
        nearby = activity_client.get("/api/stores/nearby", params={**PARAMS, **params})
        assert nearby.status_code == 200
        assert (
            sum(r["open_count"] for r in actual["by_sub_category"])
            == nearby.json()["data"]["count"]
        )
    assert (
        payload(activity_client, include_unknown="false")["data"]["by_sub_category"][0][
            "open_count"
        ]
        == 4
    )


def test_empty_category_is_zero_with_null_mean_and_no_invented_years(activity_db, activity_client):
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s)
        store(s, b, "other-category")
    data = payload(activity_client, category="cafe")
    assert data["data"]["recent_12m"]["opened"] == data["data"]["recent_12m"]["closed"] == 0
    assert data["data"]["yearly_trend"] == []
    assert data["data"]["by_sub_category"] == [
        {"sub_category": "cafe", "open_count": 0, "avg_operating_months": None}
    ]
    assert data["meta"]["cohort_size"] == 0


def test_invalid_asof_and_absent_provenance_are_safe(activity_db, activity_client):
    r = activity_client.get("/api/market/activity", params=PARAMS)
    assert r.status_code == 500 and r.json()["meta"] == {}
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s)
        store(s, b, "first", open_date=date(2020, 1, 1))
    for value in ("2019-12", "2026-12"):
        r = activity_client.get("/api/market/activity", params={**PARAMS, "as_of": value})
        assert r.status_code == 422 and r.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"
        assert r.headers["cache-control"] == "no-store"


def test_route_uses_readonly_snapshot_and_statement_timeout(
    activity_db, activity_client, monkeypatch
):
    original = market.get_activity

    def checked(session, query):
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert session.scalar(text("SHOW statement_timeout")) == "3s"
        return original(session, query)

    monkeypatch.setattr(market, "get_activity", checked)
    with Session(activity_db.engine) as s, s.begin():
        b = batch(s)
        store(s, b, "active")
    assert payload(activity_client)["data"]["by_sub_category"][0]["open_count"] == 1
