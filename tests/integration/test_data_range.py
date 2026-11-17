from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def range_database(temporary_database: TemporaryDatabase) -> TemporaryDatabase:
    migrate(temporary_database)
    return temporary_database


@pytest.fixture
def range_client(range_database: TemporaryDatabase) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = range_database.engine
    with TestClient(app) as client:
        yield client


def result(client: TestClient, **params: str) -> dict:
    response = client.get("/api/meta/data-range", params={"category": "restaurant", **params})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_historical_intervals_subcategory_and_global_upper_date(
    range_database: TemporaryDatabase,
    range_client: TestClient,
) -> None:
    with Session(range_database.engine) as session, session.begin():
        provenance = batch(session)
        store(
            session,
            provenance,
            "old-closed",
            None,
            open_date=date(1960, 5, 20),
            status="closed",
            close_date=date(1970, 1, 1),
            area_m2=0,
            is_franchise=None,
            is_temporary=None,
        )
        store(
            session,
            provenance,
            "chinese",
            open_date=date(1962, 3, 10),
            sub_category="chinese",
            status="other",
        )
        store(session, provenance, "japanese", open_date=date(1966, 8, 10), sub_category="japanese")
        # All earlier entries are unreliable or outside the basic supported cohort.
        for i, changes in enumerate(
            [
                {"open_date": date(1959, 12, 31)},
                {"open_date": None},
                {"date_flag": "open_date_invalid"},
                {"date_flag": "unknown_token"},
                {"date_flag": "close_date_invalid"},
                {"date_flag": "open_before_1960"},
                {"date_flag": "open_date_future"},
                {"date_flag": "close_date_future"},
                {"date_flag": "close_before_open"},
                {"is_temporary": True},
                {"category_review_flag": True},
                {"deleted_at": datetime.now(UTC)},
                {"sub_category": "snack"},
                {"status": "closed"},
                {"close_date": date(1960, 2, 1)},
                {"status": "closed", "close_date": date(1959, 1, 1)},
                {"status": "closed", "close_date": date(2026, 11, 11)},
            ]
        ):
            values = {"open_date": date(1960, 1, 1), **changes}
            store(session, provenance, str(i), **values)
        cafe = batch(session, source="rest_cafe", data_updated_at=date(2026, 11, 7))
        store(
            session, cafe, "cafe", category="cafe", sub_category="cafe", open_date=date(2004, 2, 29)
        )
    whole = result(range_client)
    assert whole["data"] == {
        "min_month": "1960-05",
        "max_month": "2026-11",
        "max_date": "2026-11-10",
        "data_updated_at": "2026-11-10",
        "collected_at": None,
    }
    assert result(range_client, sub_category="chinese")["data"]["min_month"] == "1962-03"
    assert result(range_client, sub_category="japanese")["data"]["min_month"] == "1966-08"
    assert result(range_client, sub_category="chinese,japanese")["data"]["min_month"] == "1962-03"
    assert result(range_client, category="cafe")["data"]["min_month"] == "2004-02"
    assert result(range_client, category="cafe")["data"]["max_date"] == "2026-11-10"
    assert whole["meta"]["space"] == "seoul" and whole["meta"]["denominator"] is None
    assert whole["meta"]["is_demo"] is False and whole["meta"]["collected_at"] is None
    assert whole["meta"]["data_version"]["rule_version"] == "store-data-range-valid-license-v1"
    for sub, minimum, previous in [
        (None, "1960-05", "1960-04"),
        ("chinese,japanese", "1962-03", "1962-02"),
    ]:
        params = {
            **PARAMS,
            "as_of": minimum,
            "radius": 300,
            "area": "gte99",
            "include_unknown": "false",
        }
        if sub:
            params["sub_category"] = sub
        nearby = range_client.get("/api/stores/nearby", params=params)
        assert nearby.status_code == 200 and nearby.json()["data"]["count"] == 0
        assert (
            nearby.json()["meta"]["data_version"]["stores_batch_ids"]
            == whole["meta"]["data_version"]["stores_batch_ids"]
        )
        assert (
            nearby.json()["meta"]["data_version"]["map_version"]
            == whole["meta"]["data_version"]["map_version"]
        )
        before = range_client.get("/api/stores/nearby", params={**params, "as_of": previous})
        assert before.status_code == 422 and before.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"


def test_empty_minimum_never_fabricates_a_month(
    range_database: TemporaryDatabase,
    range_client: TestClient,
) -> None:
    with Session(range_database.engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "restaurant")
    empty = result(range_client, category="cafe")["data"]
    assert empty["min_month"] is None
    assert empty["max_month"] == "2026-11" and empty["max_date"] == "2026-11-10"
    for month in [None, "2026-11", "2026-10"]:
        params = {**PARAMS, "category": "cafe"}
        if month:
            params["as_of"] = month
        response = range_client.get("/api/stores/nearby", params=params)
        if month == "2026-10":
            assert response.status_code == 422
        else:
            assert response.status_code == 200 and response.json()["data"]["count"] == 0


@pytest.mark.parametrize("reference", [date(2024, 2, 29), date(2023, 12, 31), date(2026, 11, 10)])
def test_date_boundaries_and_source_day_not_month_end(
    range_database: TemporaryDatabase,
    range_client: TestClient,
    reference: date,
) -> None:
    with Session(range_database.engine) as session, session.begin():
        provenance = batch(session, data_updated_at=reference)
        store(session, provenance, "old-boundary", open_date=date(1960, 1, 1))
        store(session, provenance, "on-D", open_date=reference, sub_category="japanese")
        store(
            session,
            provenance,
            "future",
            open_date=reference + timedelta(days=1),
            sub_category="western",
        )
    assert result(range_client)["data"]["min_month"] == "1960-01"
    assert result(range_client)["data"]["max_date"] == reference.isoformat()
    assert result(range_client, sub_category="japanese")["data"]["min_month"] == reference.strftime(
        "%Y-%m"
    )
    assert result(range_client, sub_category="western")["data"]["min_month"] is None


@pytest.mark.parametrize(
    "problem", ["empty", "unlinked", "wrong-source", "no-date", "bad-reason", "future-date"]
)
def test_unready_global_provenance_is_safe_failure(
    range_database: TemporaryDatabase,
    range_client: TestClient,
    problem: str,
) -> None:
    if problem != "empty":
        with Session(range_database.engine) as session, session.begin():
            provenance = batch(session)
            store(session, provenance, "restaurant")
            bad = batch(session, source="rest_cafe")
            store(session, bad, "bad", category="cafe", sub_category="cafe")
            if problem == "unlinked":
                session.delete(bad)
            elif problem == "wrong-source":
                bad.source = "general_restaurant"
            elif problem == "no-date":
                bad.data_updated_at = None
            elif problem == "bad-reason":
                bad.update_reason = "invalid"
            elif problem == "future-date":
                bad.data_updated_at = date(2099, 1, 1)
    response = range_client.get("/api/meta/data-range", params={"category": "restaurant"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["meta"] == {} and "bad" not in response.text
    assert response.headers["cache-control"] == "no-store"
