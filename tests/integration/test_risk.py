from datetime import date
from itertools import product
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_market_judgement import area, version
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def db(temporary_database):
    migrate(temporary_database)
    return temporary_database.engine


@pytest.fixture
def client(db):
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db
    with TestClient(app) as c:
        yield c


def payload(client, **changes):
    r = client.get("/api/risk", params={**PARAMS, **changes})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def metrics(response):
    return {r["id"]: r for r in response["data"]["indicators"]}


def test_period_closed_rows_distances_samples_and_seoul(db, client):
    with Session(db) as s, s.begin():
        b = batch(s, data_updated_at=date(2026, 11, 8))
        for i in range(8):
            store(
                s,
                b,
                f"closed{i}",
                open_date=date(2024, 1, 1),
                close_date=date(2026, 4, 1),
                status="closed",
            )
        for name, d in [
            ("active499", 499),
            ("active500", 500),
            ("out501", 501),
            ("epsilon", 500.001),
        ]:
            store(s, b, name, d, open_date=date(2026, 1, 1))
        store(
            s,
            b,
            "lower-close",
            open_date=date(2020, 1, 1),
            close_date=date(2025, 11, 8),
            status="closed",
        )
        store(
            s,
            b,
            "no-position",
            None,
            open_date=date(2020, 1, 1),
            close_date=date(2026, 1, 1),
            status="closed",
        )
    result = payload(client, include="day_night_ratio,market_change")
    m = metrics(result)
    assert (
        m["closure_rate_12m"]["numerator"],
        m["closure_rate_12m"]["denominator"],
        m["closure_rate_12m"]["value"],
    ) == (8, 10, 80)
    assert m["closure_rate_12m"]["seoul_avg"] == 66.7
    assert m["competitor_count"]["value"] == 2
    assert m["survival_rate_1y"]["value"] is None
    assert result["data"]["market"]["status"] == "unverified"
    assert result["data"]["market"]["spatial_candidate"] is None
    assert result["data"]["flags"]["missing"] == [
        "official_closure_rate",
        "market_change",
        "day_night_ratio",
    ]
    assert [r["id"] for r in result["data"]["indicators"]][-2:] == [
        "market_change",
        "day_night_ratio",
    ]
    assert m["official_risk"]["status"] == "link_only" and m["official_risk"]["copy_text"] is None
    assert m["market_change"]["type"] == "official"
    assert result["meta"]["excluded_no_coord"] == 1 and result["meta"]["denominator"] is None
    assert (
        result["meta"]["collected_at"] is None
        and result["meta"]["survival_basis"] == "fixed_opening_anniversary"
    )
    nearby = client.get("/api/stores/nearby", params=PARAMS).json()
    activity = client.get("/api/market/activity", params=PARAMS).json()
    assert nearby["data"]["count"] == 2
    assert activity["data"]["recent_12m"]["closed"] == 8


def test_fixed_anniversary_survival_cohort_boundaries_and_closure_after_horizon(db, client):
    with Session(db) as s, s.begin():
        b = batch(s, data_updated_at=date(2026, 11, 8))
        rows = [
            ("a", date(2025, 1, 1), date(2026, 1, 1)),
            ("b", date(2025, 1, 2), date(2026, 1, 3)),
            ("c", date(2025, 11, 8), None),
            ("d", date(2024, 11, 9), date(2025, 11, 8)),
            ("e", date(2025, 6, 1), None),
            ("excluded-lower", date(2024, 11, 8), None),
            ("excluded-upper", date(2025, 11, 9), None),
        ]
        for name, opened, closed in rows:
            store(
                s,
                b,
                name,
                open_date=opened,
                close_date=closed,
                status="closed" if closed else "open",
            )
        for i in range(5):
            store(
                s,
                b,
                f"three{i}",
                open_date=date(2023, 2, 1),
                close_date=date(2026, 2, 1) if i == 0 else None,
                status="closed" if i == 0 else "open",
            )
    result = payload(client)
    m = metrics(result)
    assert (
        m["survival_rate_1y"]["numerator"],
        m["survival_rate_1y"]["denominator"],
        m["survival_rate_1y"]["value"],
    ) == (3, 5, 60)
    assert (
        m["survival_rate_3y"]["numerator"],
        m["survival_rate_3y"]["denominator"],
        m["survival_rate_3y"]["value"],
    ) == (4, 5, 80)
    assert m["survival_rate_1y"]["period"] == "(2024-11-08, 2025-11-08]"
    assert result["data"]["flags"]["insufficient_sample"] is False
    assert result["data"]["flags"]["missing"] == ["official_closure_rate"]


def test_calendar_clamp_and_unobserved_future(db, client):
    with Session(db) as s, s.begin():
        b = batch(s, data_updated_at=date(2025, 2, 28))
        rows = [
            ("at-anniversary", date(2024, 2, 28), date(2025, 2, 28)),
            ("after-anniversary", date(2023, 3, 1), date(2024, 3, 2)),
            ("lower", date(2023, 2, 28), None),
            ("upper-out", date(2024, 2, 29), None),
        ]
        for name, opened, closed in rows:
            store(
                s,
                b,
                name,
                open_date=opened,
                close_date=closed,
                status="closed" if closed else "open",
            )
        for i in range(3):
            store(s, b, f"cohort{i}", open_date=date(2023, 6, 1))
        store(s, b, "future", open_date=date(2025, 3, 1))
    m = metrics(payload(client))
    assert (
        m["survival_rate_1y"]["numerator"],
        m["survival_rate_1y"]["denominator"],
        m["survival_rate_1y"]["value"],
    ) == (4, 5, 80)
    r = client.get("/api/risk", params={**PARAMS, "as_of": "2025-03"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"


def test_unknown_filters_are_independent_and_bad_intervals_excluded(db, client):
    with Session(db) as s, s.begin():
        b = batch(s)
        for i, (a, f) in enumerate(product([None, 0, 33], [None, False, True])):
            store(s, b, f"filter{i}", area_m2=a, is_franchise=f)
        for name, changes in [
            ("missing", {"open_date": None}),
            ("flag", {"date_flag": "invalid"}),
            ("review", {"category_review_flag": True}),
            ("temporary", {"is_temporary": True}),
            (
                "inverted",
                {"open_date": date(2024, 1, 1), "close_date": date(2023, 1, 1), "status": "closed"},
            ),
        ]:
            store(s, b, name, **changes)
    for area_unknown, fr_unknown, franchise in product(
        [False, True], [False, True], ["all", "franchise", "independent"]
    ):
        r = payload(
            client,
            include_unknown_area=area_unknown,
            include_unknown_franchise=fr_unknown,
            franchise=franchise,
        )
        expected = (3 if area_unknown else 1) * (
            (3 if fr_unknown else 2) if franchise == "all" else (2 if fr_unknown else 1)
        )
        assert metrics(r)["competitor_count"]["value"] == expected


def test_boundary_preview_is_unverified_and_missing_version_fails(db, client):
    with Session(db) as s, s.begin():
        b = batch(s)
        store(s, b, "one")
    with db.begin() as c:
        vid = version(c, 1)
        area(c, vid)
    client.app.state.settings.risk_boundary_version_id = vid
    result = payload(client, lat=37.5, lng=127.0)
    assert result["data"]["market"]["spatial_candidate"]["spatial_status"] == "in_market"
    assert result["data"]["market"]["market_code"] is None
    assert metrics(result)["official_closure_rate"]["status"] == "pending"
    client.app.state.settings.risk_boundary_version_id = uuid4()
    r = client.get("/api/risk", params=PARAMS)
    assert r.status_code == 500 and r.json()["data"] is None


def test_empty_source_errors_and_actual_session_configuration(db, client, monkeypatch):
    assert client.get("/api/risk", params=PARAMS).status_code == 500
    with Session(db) as s, s.begin():
        b = batch(s)
        store(s, b, "one")
    from app.routers import risk as route

    real = route.get_risk

    def inspect(s, q, settings):
        assert s.scalar(text("SHOW transaction_read_only")) == "on"
        assert s.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert s.scalar(text("SHOW statement_timeout")) == "3s"
        return real(s, q, settings)

    monkeypatch.setattr(route, "get_risk", inspect)
    result = payload(client, category="cafe")
    assert metrics(result)["competitor_count"]["value"] == 0
    assert metrics(result)["closure_rate_12m"]["value"] is None
    assert result["data"]["flags"]["insufficient_sample"] is True


def test_same_day_and_period_end_events_and_past_active_set(db, client):
    with Session(db) as s, s.begin():
        b = batch(s)
        for i in range(9):
            store(s, b, f"old{i}", open_date=date(2010, 1, 1))
        store(
            s,
            b,
            "same-day",
            open_date=date(2026, 11, 10),
            close_date=date(2026, 11, 10),
            status="closed",
        )
        store(
            s,
            b,
            "lower-close",
            open_date=date(2010, 1, 1),
            close_date=date(2025, 11, 10),
            status="closed",
        )
    current = metrics(payload(client))
    assert current["closure_rate_12m"]["denominator"] == 10
    assert current["closure_rate_12m"]["numerator"] == 1
    assert current["closure_rate_12m"]["value"] == 10
    assert current["competitor_count"]["value"] == 9
    past = metrics(payload(client, as_of="2025-01"))
    assert past["closure_rate_12m"]["value"] == 0
    assert past["competitor_count"]["value"] == 10


def test_feb29_opening_anniversary_is_feb28_in_nonleap_year(db, client):
    with Session(db) as s, s.begin():
        b = batch(s, data_updated_at=date(2025, 3, 31))
        for i, closed in enumerate(
            [
                None,
                date(2025, 2, 27),
                date(2025, 2, 28),
                date(2025, 3, 1),
                date(2025, 3, 31),
            ]
        ):
            store(
                s,
                b,
                f"leap{i}",
                open_date=date(2024, 2, 29),
                close_date=closed,
                status="closed" if closed else "open",
            )
    m = metrics(payload(client))
    assert m["survival_rate_1y"]["numerator"] == 3
    assert m["survival_rate_1y"]["denominator"] == 5
    assert m["survival_rate_1y"]["value"] == 60
