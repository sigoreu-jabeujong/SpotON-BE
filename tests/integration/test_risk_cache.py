from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.cache import CacheResources
from app.core.config import Settings
from app.db.dependencies import read_only_session
from app.main import create_app
from app.models import StoreImportBatch
from app.schemas.risk import RiskQuery
from app.services import risk as service
from app.services import risk_cache
from tests.integration.test_interpret import Provider, seed
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import LNG, PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def db(temporary_database):
    migrate(temporary_database)
    seed(temporary_database.engine)
    return temporary_database.engine


def make_app(db, **config):
    app = create_app(Settings(_env_file=None, **config))
    app.state.database.engine = db
    return app


def get(client, **changes):
    result = client.get("/api/risk", params={**PARAMS, **changes})
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    return result.json()


def active(result):
    return next(i["value"] for i in result["data"]["indicators"] if i["id"] == "competitor_count")


def test_warm_hit_skips_aggregation_and_batchless_dml_invalidates(db, monkeypatch):
    app = make_app(db)
    original = service._get_risk
    calculate = Mock(wraps=original)
    monkeypatch.setattr(service, "_get_risk", calculate)
    statements = []

    def executed(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db, "before_cursor_execute", executed)
    try:
        with TestClient(app) as client:
            first = get(client)
            statements.clear()
            assert get(client) == first and calculate.call_count == 1
            assert len([s for s in statements if "pg_current_snapshot" in s]) == 1
            assert not any("FROM stores" in s for s in statements)
            with db.begin() as conn:
                conn.execute(text("UPDATE stores SET area_m2=1 WHERE license_no='ai0'"))
            assert get(client) == first and calculate.call_count == 2
            assert active(get(client, area="33to66")) == active(first) - 1
            with db.begin() as conn:
                conn.execute(text("UPDATE stores SET geom=NULL WHERE license_no='ai1'"))
            assert active(get(client)) == active(first) - 1
            with db.begin() as conn:
                conn.execute(text("DELETE FROM stores WHERE license_no='ai2'"))
            assert active(get(client)) == active(first) - 2
            with Session(db) as session, session.begin():
                existing = session.scalar(text("SELECT batch_id FROM store_import_batches LIMIT 1"))
                provenance = session.get(StoreImportBatch, existing)
                store(session, provenance, "inserted", open_date=date(2025, 1, 1))
            assert active(get(client)) == active(first) - 1
            with db.begin() as conn:
                conn.execute(text("UPDATE store_import_batches SET map_version='new-map'"))
            assert (
                get(client)["meta"]["data_version"]["map_version"]
                != first["meta"]["data_version"]["map_version"]
            )
    finally:
        event.remove(db, "before_cursor_execute", executed)


def test_old_snapshot_cannot_replace_new_view_and_writer_rollback(db):
    app = make_app(db)
    resources = app.state.database
    q = RiskQuery(**PARAMS)
    with read_only_session(resources) as old:
        before = service.get_risk(old, q, resources.settings, cache=resources.cache)
        with db.begin() as writer:
            writer.execute(text("UPDATE stores SET geom=NULL WHERE license_no='ai0'"))
            with read_only_session(resources) as during:
                assert (
                    service.get_risk(during, q, resources.settings, cache=resources.cache) == before
                )
        with read_only_session(resources) as new:
            current = service.get_risk(new, q, resources.settings, cache=resources.cache)
            assert current != before
            assert service.get_risk(old, q, resources.settings, cache=resources.cache) == before
            assert service.get_risk(new, q, resources.settings, cache=resources.cache) == current
        with db.connect() as writer:
            writer.execute(text("DELETE FROM stores"))
            writer.rollback()
        with read_only_session(resources) as after:
            assert service.get_risk(after, q, resources.settings, cache=resources.cache) == current
    resources.close()


def test_readwrite_readcommitted_bypass_and_guc_namespace(db):
    cache = CacheResources(Settings(_env_file=None))
    with Session(db) as session:
        assert risk_cache.snapshot_token(session, cache) is None
    with Session(db) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        assert risk_cache.snapshot_token(session, cache) is None
    app = make_app(db)
    with read_only_session(app.state.database) as session:
        first = risk_cache.snapshot_token(session, cache)
        session.execute(text("SET LOCAL TIME ZONE 'Asia/Seoul'"))
        assert risk_cache.snapshot_token(session, cache) != first
    app.state.database.close()


def test_database_and_source_failures_never_hidden_by_hit(db, monkeypatch):
    app = make_app(db)
    with TestClient(app) as client:
        get(client)
        original = risk_cache.SNAPSHOT
        monkeypatch.setattr(risk_cache, "SNAPSHOT", text("SELECT 1/0"))
        failed = client.get("/api/risk", params=PARAMS)
        assert failed.status_code == 500 and failed.headers["cache-control"] == "no-store"
        monkeypatch.setattr(risk_cache, "SNAPSHOT", original)
        assert active(get(client)) == 10
        with db.begin() as conn:
            conn.execute(text("UPDATE store_import_batches SET data_updated_at=NULL"))
        assert client.get("/api/risk", params=PARAMS).status_code == 500


def test_exact_coordinate_guard_at_real_radius_boundary(db):
    with Session(db) as session, session.begin():
        session.execute(text("DELETE FROM stores"))
        b = batch(session)
        store(session, b, "boundary", 500)
    app = make_app(db)
    with TestClient(app) as client:
        near, far = LNG + 0.00000002, LNG - 0.00000002
        assert round(near, 6) == round(far, 6)
        assert active(get(client, lng=near)) == 1
        assert active(get(client, lng=far)) == 0
        assert active(get(client, lng=near)) == 1


def test_real_ai_preparation_reuses_selection_and_closes_session(db):
    app = make_app(db, llm_api_key=SecretStr("synthetic-only"))
    provider = Provider(db)
    app.state.interpretation.client = provider
    with TestClient(app) as client:
        first = client.post("/api/risk/interpret", json={"query": PARAMS})
        second = client.post("/api/risk/interpret", json={"query": PARAMS})
        assert first.status_code == second.status_code == 200
        assert provider.calls == 1 and app.state.database.cache.ai.info()["hits"] == 1
        assert second.json()["data"]["generated_at"] > first.json()["data"]["generated_at"]
        assert second.json()["data"]["verification"]["regenerated"] is False
        with db.begin() as conn:
            conn.execute(text("UPDATE stores SET geom=NULL WHERE license_no='ai0'"))
        assert client.post("/api/risk/interpret", json={"query": PARAMS}).status_code == 200
        assert provider.calls == 2 and db.pool.checkedout() == 0


def test_non_mvcc_maintenance_requires_draining_and_restarting_cache(db):
    app = make_app(db)
    with TestClient(app) as client:
        assert active(get(client)) == 10
    assert not app.state.database.cache.enabled
    with db.begin() as conn:
        conn.execute(text("TRUNCATE stores"))
    with Session(db) as session, session.begin():
        store(session, batch(session), "replacement")
    fresh = make_app(db)
    with TestClient(fresh) as client:
        assert active(get(client)) == 1
