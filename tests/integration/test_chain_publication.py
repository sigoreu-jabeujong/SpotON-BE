"""Real PostgreSQL publication, drift, filter and rollback contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from itertools import product

import pytest
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import Store
from app.models.chain import (
    ChainPublication,
    ChainPublicationState,
    ChainSourceState,
    StoreChainClassification,
)
from app.services.chains import ChainSelection, source_revision
from etl.chains import publication
from etl.chains.common import ChainsError
from etl.chains.registry import load_registry
from tests.etl.test_chains_semas import item, make_snapshot
from tests.integration.test_nearby import PARAMS, batch, store
from tests.integration.test_store_migration import migrate

pytestmark = pytest.mark.integration


def publish(database, monkeypatch, snapshot=None, *, write=False, **options):
    monkeypatch.setattr(publication, "check_local_database", lambda c: None)
    with database.engine.begin() as c:
        publication.locked(c, write)
        return publication.apply(c, load_registry(), snapshot, write=write, **options)


def prepared(database, monkeypatch, snapshot=None):
    plan = publish(database, monkeypatch, snapshot)
    result = publish(
        database,
        monkeypatch,
        snapshot,
        write=True,
        expected_plan=plan["expected_plan_sha256"],
        expected_active=plan["active"],
    )
    return plan, result


def client_for(database):
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = database.engine
    return TestClient(app)


def test_publication_v2_truth_matrix_and_v1_preserved(temporary_database, monkeypatch):
    db = temporary_database
    migrate(db, "head")
    with Session(db.engine) as session, session.begin():
        b = batch(session)
        store(
            session, b, "chain", name="본죽", is_franchise=False, building_key="종로구-청운동-1-0"
        )
        store(
            session,
            b,
            "unknown",
            name="동네식당",
            is_franchise=False,
            building_key="종로구-청운동-1-0",
        )
        store(session, b, "unlocated", distance=None, name="본죽", building_key="종로구-청운동-1-0")
        store(session, b, "outside", distance=5000, name="본죽", building_key="종로구-청운동-1-0")
    with client_for(db) as client:
        legacy = client.get("/api/stores/nearby", params=PARAMS).json()
        pending = client.get("/api/v2/stores/nearby", params=PARAMS)
        assert pending.status_code == 200, pending.text
        assert pending.json()["meta"]["brand_classification"]["status"] == "pending"
        assert all(row["brand"]["status"] == "unknown" for row in pending.json()["data"]["markers"])
    plan, result = prepared(db, monkeypatch)
    assert result["summary"]["status"] == {"estimated": 3, "unknown": 1}
    repeated = publish(
        db,
        monkeypatch,
        write=True,
        expected_plan=plan["expected_plan_sha256"],
        expected_active="none",
    )
    assert repeated["unchanged"]
    with client_for(db) as client:
        assert client.get("/api/stores/nearby", params=PARAMS).json() == legacy
        for scope, unknown, evidence in product(
            ("all", "chain", "non_chain"),
            ("include", "exclude"),
            ("include_estimates", "confirmed_only"),
        ):
            positive = evidence == "include_estimates"
            expected = (
                (1 if positive else 2)
                if scope == "non_chain" and unknown == "include"
                else (0 if scope == "non_chain" else (2 if unknown == "include" else int(positive)))
            )
            params = {
                **PARAMS,
                "brand_scope": scope,
                "brand_unknown": unknown,
                "brand_evidence": evidence,
            }
            n = client.get("/api/v2/stores/nearby", params=params)
            s = client.get("/api/v2/stores/snapshot", params={**params, "as_of": "2026-11"})
            a = client.get("/api/v2/market/activity", params=params)
            r = client.get("/api/v2/risk", params=params)
            for response in (n, s, a, r):
                assert response.status_code == 200, response.text
                assert response.json()["meta"]["brand_counts"] == {
                    "estimated": 1,
                    "unknown": 1,
                    "conflict": 0,
                    "stale_or_drift": 0,
                }
            assert n.json()["data"]["count"] == s.json()["data"]["total_at_as_of"] == expected
            assert sum(row["open_count"] for row in a.json()["data"]["by_sub_category"]) == expected
            indicator = next(
                v for v in r.json()["data"]["indicators"] if v["id"] == "competitor_count"
            )
            assert indicator["value"] == expected
            assert r.json()["data"]["query"]["filters"]["brand_scope"] == scope
            assert "franchise_classification" not in r.json()["meta"]
        chain = client.get(
            "/api/v2/stores/nearby",
            params={**PARAMS, "brand_scope": "chain", "brand_unknown": "exclude"},
        ).json()["data"]
        assert chain["excluded_no_coord"] == 1
        assert chain["markers"][0]["brand"]["name"] == "본죽"
        assert "franchise" not in chain["markers"][0]
        assert chain["markers"][0]["operation"]["type"] == "unknown"
        history = client.get("/api/v2/stores/history", params={"building_key": "종로구-청운동-1-0"})
        assert history.status_code == 200
        assert history.json()["data"]["total"] == 4
        assert "franchise_classification" not in history.json()["meta"]
        assert "brand_mapping" not in history.json()["meta"]["data_version"]
        assert all("franchise" not in row for row in history.json()["data"]["stores"])


def test_drift_same_batch_other_row_and_typed_input(temporary_database, monkeypatch):
    db = temporary_database
    migrate(db, "head")
    provider = item()
    provider["bizesNm"] = "본죽"
    snapshot = make_snapshot([provider])
    with Session(db.engine) as session, session.begin():
        b = batch(session)
        store(
            session,
            b,
            "corroborated",
            name="본죽강남점",
            address_road="서울특별시 강남구 테헤란로 1",
            address_jibun="서울특별시 강남구 역삼동 1",
            floor_unit="1층",
        )
        store(session, b, "named", name="본죽", building_key="종로구-청운동-1-0")
    with Session(db.engine) as session:
        batch_id = session.scalar(select(Store.batch_id).limit(1))
    plan, _ = prepared(db, monkeypatch, snapshot)
    with Session(db.engine) as session:
        assert (
            session.scalar(
                select(StoreChainClassification.reason).where(
                    StoreChainClassification.license_no == "corroborated"
                )
            )
            == "semas_address_corroborated"
        )
    # Zero-row DML also conservatively invalidates global address corroboration.
    with db.engine.begin() as c:
        c.execute(text("UPDATE stores SET name=name WHERE false"))
    with client_for(db) as client:
        rows = client.get("/api/v2/stores/nearby", params=PARAMS).json()["data"]["markers"]
        statuses = {r["license_no"]: r["brand"] for r in rows}
        assert statuses["corroborated"]["reason"] == "source_drift"
        assert statuses["named"]["status"] == "estimated"
    # Full source revalidation, with unchanged content, refreshes only the pointer epoch.
    result = publish(
        db,
        monkeypatch,
        snapshot,
        write=True,
        expected_plan=plan["expected_plan_sha256"],
        expected_active="none",
    )
    assert result["unchanged"]
    with Session(db.engine) as session, session.begin():
        b = session.get(type(b), batch_id)
        store(
            session,
            b,
            "other",
            name="다른점포",
            address_road="서울특별시 강남구 테헤란로 1",
            address_jibun="서울특별시 강남구 역삼동 1",
            floor_unit="1층",
        )
        session.execute(update(Store).where(Store.license_no == "named").values(is_franchise=None))
    with client_for(db) as client:
        rows = client.get("/api/v2/stores/nearby", params=PARAMS).json()["data"]["markers"]
        assert all(r["brand"]["status"] == "unknown" for r in rows)
        assert {r["brand"]["reason"] for r in rows} == {
            "source_drift",
            "stale_input",
            "no_evidence",
        }
    with db.engine.begin() as c:
        publication.locked(c, True)
        with pytest.raises(ChainsError, match="activation_inputs_changed"):
            publication.activate(
                c,
                __import__("uuid").UUID(plan["generation"]),
                load_registry(),
                snapshot,
                expected_active=plan["generation"],
            )


def test_counter_all_dml_rollback_health_and_downgrade(temporary_database):
    db = temporary_database
    migrate(db, "head")
    with db.engine.connect() as c:
        assert c.scalar(select(ChainSourceState.revision)) == 0
        c.execute(text("INSERT INTO stores(source,license_no) VALUES('synthetic','x')"))
        c.execute(text("UPDATE stores SET name='changed'"))
        c.execute(text("DELETE FROM stores"))
        c.execute(text("TRUNCATE stores"))
        assert c.scalar(select(ChainSourceState.revision)) == 4
        c.rollback()
        assert c.scalar(select(ChainSourceState.revision)) == 0
    with db.engine.begin() as c:
        c.execute(text("ALTER TABLE stores DISABLE TRIGGER spoton_chain_source_changed"))
    with client_for(db) as client:
        response = client.get("/api/v2/brands/status")
        assert response.status_code == 500
        assert response.headers["cache-control"] == "no-store"
    with db.engine.begin() as c:
        c.execute(text("ALTER TABLE stores ENABLE ALWAYS TRIGGER spoton_chain_source_changed"))
    # Counter row alone does not block an empty downgrade.
    migrate(db, "0011", downgrade=True)
    with db.engine.connect() as c:
        assert c.scalar(text("select to_regclass('chain_source_state')")) is None
    migrate(db, "head")
    with Session(db.engine) as session:
        assert source_revision(session) == 0


def test_failed_publish_is_atomic_and_counter_serializes_rr_writers(
    temporary_database, monkeypatch
):
    db = temporary_database
    migrate(db, "head")
    with Session(db.engine) as session, session.begin():
        b = batch(session)
        store(session, b, "a", name="본죽")
    plan = publish(db, monkeypatch)
    original = publication.verify

    def broken(*args):
        raise ChainsError("injected_failure")

    monkeypatch.setattr(publication, "verify", broken)
    with pytest.raises(ChainsError, match="injected_failure"):
        publish(
            db,
            monkeypatch,
            write=True,
            expected_plan=plan["expected_plan_sha256"],
            expected_active="none",
        )
    monkeypatch.setattr(publication, "verify", original)
    with Session(db.engine) as session:
        assert session.scalar(select(func.count()).select_from(ChainPublication)) == 0
        assert session.get(ChainPublicationState, 1) is None
    # Separate source rows still share a counter; RR writers must rollback on 40001.
    with (
        db.engine.connect().execution_options(isolation_level="REPEATABLE READ") as one,
        db.engine.connect().execution_options(isolation_level="REPEATABLE READ") as two,
    ):
        one.execute(text("select revision from chain_source_state"))
        two.execute(text("select revision from chain_source_state"))
        one.execute(text("INSERT INTO stores(source,license_no) VALUES('synthetic','one')"))
        one.commit()
        with pytest.raises(SQLAlchemyError) as caught:
            two.execute(text("INSERT INTO stores(source,license_no) VALUES('synthetic','two')"))
        assert caught.value.orig.sqlstate == "40001"
        two.rollback()
    with db.engine.connect() as c:
        assert c.scalar(text("select count(*) from stores where license_no='two'")) == 0
    prepared(db, monkeypatch)
    with pytest.raises(CommandError, match="SQLSTATE P0001"):
        migrate(db, "0011", downgrade=True)


def test_concurrent_publish_and_unknown_input_plan_guard(temporary_database, monkeypatch):
    db = temporary_database
    migrate(db, "head")
    with Session(db.engine) as session, session.begin():
        b = batch(session)
        store(session, b, "a", name="본죽")
        store(session, b, "u", name="동네식당")
    plan = publish(db, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: publish(
                    db,
                    monkeypatch,
                    write=True,
                    expected_plan=plan["expected_plan_sha256"],
                    expected_active="none",
                ),
                range(2),
            )
        )
    assert sum(r["unchanged"] for r in results) == 1
    with db.engine.begin() as c:
        c.execute(update(Store).where(Store.license_no == "u").values(name="새로운독립상호"))
    new = publish(db, monkeypatch)
    assert new["plan_sha256"] == plan["plan_sha256"]
    assert new["expected_plan_sha256"] != plan["expected_plan_sha256"]
    with pytest.raises(ChainsError, match="plan_changed"):
        publish(
            db,
            monkeypatch,
            write=True,
            expected_plan=plan["expected_plan_sha256"],
            expected_active=plan["generation"],
        )
    with pytest.raises(ChainsError, match="active_changed"):
        publish(
            db,
            monkeypatch,
            write=True,
            expected_plan=new["expected_plan_sha256"],
            expected_active="none",
        )
    with Session(db.engine) as session:
        assert session.scalar(select(func.count()).select_from(ChainPublication)) == 1


def test_every_typed_input_change_invalidates_name_evidence(temporary_database, monkeypatch):
    db = temporary_database
    migrate(db, "head")
    with Session(db.engine) as session, session.begin():
        b = batch(session)
        store(session, b, "a", name="본죽")
    prepared(db, monkeypatch)
    changes = {
        "name": "다른상호",
        "category": "cafe",
        "sub_category": "western",
        "is_franchise": None,
        "brand_id": 12,
        "address_road": "서울특별시 중구 테스트로 1",
        "address_jibun": "서울특별시 중구 테스트동 1",
        "building_key": "중구-명동-1-0",
        "floor_unit": "2층",
        "open_date": date(2021, 1, 1),
        "close_date": date(2026, 1, 1),
        "status": "closed",
        "date_flag": "invalid",
        "is_temporary": True,
    }
    for field, value in changes.items():
        with Session(db.engine) as session:
            session.execute(update(Store).where(Store.license_no == "a").values({field: value}))
            chain = ChainSelection.load(session)
            assert (
                chain.brands(session, [("general_restaurant", "a")])[
                    ("general_restaurant", "a")
                ].reason
                == "stale_input"
            ), field
            session.rollback()
