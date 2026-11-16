from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import Store, StoreImportBatch
from tests.integration.test_store_history import KEY, seed

pytestmark = pytest.mark.integration


def test_closed_cohort_exact_scope_dates_and_legacy_unchanged(temporary_database):
    db = temporary_database
    seed(db)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db.engine
    params = {
        "building_key": KEY,
        "floor_unit": "2층 201호",
        "scope": "unit",
        "identity_requirement": "address_scope",
    }
    with TestClient(app) as client:
        before = client.get("/api/stores/history", params={"building_key": KEY}).json()
        r = client.get("/api/v2/stores/location-history", params=params)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["total"] == 2
        assert data["dated_closure_count"] == data["undated_closure_count"] == 1
        assert all(s["current_status"] == "closed" for s in data["stores"])
        assert data["excluded_counts"]["status"] == before["data"]["total"] - 2
        assert data["stores"][-1]["close_date"] is None
        assert client.get("/api/stores/history", params={"building_key": KEY}).json() == before
        with Session(db.engine) as session, session.begin():
            missing = session.scalar(select(Store).where(Store.license_no == "3"))
            missing.floor_unit = None
            different = session.scalar(select(Store).where(Store.license_no == "2"))
            different.floor_unit = "2층 202호"
            different.close_date = date(2022, 2, 1)
        unit = client.get("/api/v2/stores/location-history", params=params).json()["data"]
        assert unit["total"] == 0
        assert unit["result_status"] == "no_data"
        assert unit["location_coverage"] == "partial"
        assert unit["unresolved_closed_count"] == 1
        assert unit["excluded_counts"]["unit"] == 1
        floor = client.get(
            "/api/v2/stores/location-history", params={**params, "scope": "floor"}
        ).json()["data"]
        assert floor["total"] == 1
        assert floor["selection"]["unit_ignored"] is True


def test_dates_use_own_source_and_unknown_open_does_not_erase_closure(temporary_database):
    db = temporary_database
    seed(db)
    with Session(db.engine) as session, session.begin():
        cafe = session.scalar(select(Store).where(Store.source == "rest_cafe"))
        cafe.status = "closed"
        cafe.floor_unit = "2층 201호"
        cafe.close_date = date(2026, 11, 8)
        cafe_batch = session.get(StoreImportBatch, cafe.batch_id)
        cafe_batch.data_updated_at = date(2026, 11, 7)
        old = session.scalar(select(Store).where(Store.license_no == "2"))
        old.open_date = None
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db.engine
    with TestClient(app) as client:
        data = client.get(
            "/api/v2/stores/location-history",
            params={
                "building_key": KEY,
                "floor_unit": "2층",
                "scope": "floor",
                "identity_requirement": "address_scope",
            },
        ).json()["data"]
    assert data["total"] == 3
    assert data["dated_closure_count"] == 1
    assert data["undated_closure_count"] == 2
    cafe_row = next(s for s in data["stores"] if s["source"] == "rest_cafe")
    assert cafe_row["close_date"] is None
    assert cafe_row["operating_months"] is None
    old_row = next(s for s in data["stores"] if s["license_no"] == "2")
    assert old_row["closure_date_status"] == "dated"
    assert old_row["operating_months"] is None
