from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.core.config import Settings
from app.db import dependencies as db_dependencies
from app.main import create_app
from app.models import Store, StoreImportBatch
from tests.integration.test_store_history import KEY, seed

pytestmark = pytest.mark.integration


def test_all_status_cohort_exact_scope_dates_and_legacy_unchanged(temporary_database):
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
        assert data["total"] == 6
        assert data["selection"]["status_filter"] == "all"
        assert data["open_count"] == 4
        assert data["closed_count"] == 2
        assert data["other_count"] == 0
        assert data["dated_closure_count"] == data["undated_closure_count"] == 1
        assert data["excluded_counts"] == {"floor": 1, "unit": 0}
        active = next(s for s in data["stores"] if s["license_no"] == "same")
        assert active["current_status"] == "open"
        assert active["operating_months"] is not None
        assert active["closure_date_status"] == "not_applicable"
        assert active["close_date"] is None
        assert client.get("/api/stores/history", params={"building_key": KEY}).json() == before
        with Session(db.engine) as session, session.begin():
            missing = session.scalar(select(Store).where(Store.license_no == "3"))
            missing.floor_unit = None
            different = session.scalar(select(Store).where(Store.license_no == "2"))
            different.floor_unit = "2층 202호"
            different.close_date = date(2022, 2, 1)
        unit = client.get("/api/v2/stores/location-history", params=params).json()["data"]
        assert unit["total"] == 4
        assert unit["result_status"] == "matched"
        assert unit["location_coverage"] == "partial"
        assert unit["unresolved_count"] == 2
        assert unit["excluded_counts"]["unit"] == 1
        floor = client.get(
            "/api/v2/stores/location-history", params={**params, "scope": "floor"}
        ).json()["data"]
        assert floor["total"] == 6
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
    assert data["total"] == 8
    assert data["open_count"] == 5
    assert data["closed_count"] == 3
    assert data["dated_closure_count"] == 1
    assert data["undated_closure_count"] == 2
    cafe_row = next(s for s in data["stores"] if s["source"] == "rest_cafe")
    assert cafe_row["close_date"] is None
    assert cafe_row["operating_months"] is None
    old_row = next(s for s in data["stores"] if s["license_no"] == "2")
    assert old_row["closure_date_status"] == "dated"
    assert old_row["operating_months"] is None


def test_checkout_retry_reestablishes_real_read_only_snapshot(temporary_database, monkeypatch):
    original_session = db_dependencies.Session
    created = []
    closed = []

    def factory(engine):
        session = original_session(engine)
        number = len(created)
        created.append(session)
        original_close = session.close

        def close():
            closed.append(number)
            original_close()

        monkeypatch.setattr(session, "close", close)
        if number == 0:

            def unavailable(**kwargs):
                raise PoolTimeout("synthetic checkout timeout")

            monkeypatch.setattr(session, "connection", unavailable)
        return session

    monkeypatch.setattr(db_dependencies, "Session", factory)
    resources = db_dependencies.DatabaseResources(Settings(_env_file=None))
    resources.engine = temporary_database.engine
    body_count = 0
    with db_dependencies.read_only_session(resources, pool_retries=1) as session:
        body_count += 1
        assert closed == [0]
        assert session.scalar(text("SELECT current_setting('transaction_read_only')")) == "on"
        assert (
            session.scalar(text("SELECT current_setting('transaction_isolation')"))
            == "repeatable read"
        )
        assert session.scalar(text("SELECT current_setting('statement_timeout')")) == "3s"
    assert body_count == 1
    assert len(created) == 2
    assert closed == [0, 1]


def test_real_single_connection_pool_recovers_after_first_wait_timeout(temporary_database):
    timeout_seen = Event()

    class ObservedPool(QueuePool):
        def _do_get(self):
            try:
                return super()._do_get()
            except PoolTimeout:
                timeout_seen.set()
                raise

    engine = create_engine(
        temporary_database.engine.url,
        poolclass=ObservedPool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.5,
    )
    resources = db_dependencies.DatabaseResources(Settings(_env_file=None))
    resources.engine = engine
    held = engine.connect()

    def request():
        with db_dependencies.read_only_session(resources, pool_retries=1) as session:
            return session.scalar(text("SELECT 42"))

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(request)
            assert timeout_seen.wait(5), "first checkout must actually time out"
            held.close()
            assert future.result(timeout=5) == 42
    finally:
        held.close()
        engine.dispose()
