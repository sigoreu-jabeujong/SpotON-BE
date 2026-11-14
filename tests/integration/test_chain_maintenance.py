import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.chain import (
    ChainPublication as Publication,
)
from app.models.chain import (
    ChainPublicationState as State,
)
from app.models.chain import (
    ChainSourceState,
)
from app.models.chain import (
    StoreChainClassification as Evidence,
)
from app.services.chains import ChainSelection
from etl.chains import maintenance, publication
from etl.chains.common import ChainsError
from etl.chains.registry import load_registry
from tests.integration.test_nearby import PARAMS, batch, store
from tests.integration.test_store_migration import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def db(temporary_database, monkeypatch):
    migrate(temporary_database, "head")
    monkeypatch.setattr(maintenance, "check_local_database", lambda c: None)
    monkeypatch.setattr(publication, "check_local_database", lambda c: None)
    with Session(temporary_database.engine) as s, s.begin():
        b = batch(s)
        store(s, b, "synthetic-chain", name="본죽")
        store(s, b, "synthetic-unknown", name="동네식당")
    return temporary_database


def seeds(variant):
    original = load_registry()
    return (
        original[0].model_copy(update={"reviewed_on": date(2026, 11, variant + 1)}),
        *original[1:],
    )


def publish(db, variant):
    with db.engine.begin() as c:
        publication.locked(c, False)
        plan = publication.apply(c, seeds(variant), None)
    with db.engine.begin() as c:
        publication.locked(c, True)
        publication.apply(
            c,
            seeds(variant),
            None,
            write=True,
            expected_plan=plan["expected_plan_sha256"],
            expected_active=plan["active"],
        )
    return UUID(plan["generation"])


def manage(db, action="list", generations=(), write=False, **options):
    with db.engine.begin() as c:
        maintenance.locked(c, write)
        return maintenance.manage(c, action=action, generations=generations, write=write, **options)


def apply_plan(db, plan):
    return manage(
        db,
        plan["action"],
        tuple(UUID(t["generation"]) for t in plan["targets"]),
        True,
        expected_plan=plan["expected_plan_sha256"],
        expected_active=plan["active"],
    )


def proof(db):
    with db.engine.connect() as c:
        return (
            tuple(
                c.execute(
                    text(
                        "SELECT count(*),md5(string_agg(md5(row(s.*)::text),' ' order by id)) "
                        "FROM stores s"
                    )
                ).one()
            ),
            c.scalar(select(ChainSourceState.revision)),
        )


def nearby(db, **filters):
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db.engine
    with TestClient(app) as client:
        response = client.get("/api/v2/stores/nearby", params={**PARAMS, **filters})
        assert response.status_code == 200, response.text
        return response.json()


def test_prune_restores_fourth_publication_capacity_keeps_active_api(db):
    original = proof(db)
    first = publish(db, 0)
    publish(db, 1)
    active = publish(db, 2)
    before = nearby(db)
    with pytest.raises(ChainsError, match="generation_capacity"):
        publish(db, 3)
    plan = manage(db, "prune", (first,))
    assert plan["active"] == str(active)
    assert plan["targets"][0]["classifications"] == 1
    wire = json.dumps(plan, ensure_ascii=False)
    assert all(value not in wire for value in ("본죽", "동네식당", "synthetic-chain", "https://"))
    result = apply_plan(db, plan)
    assert result["removed"] == {"publications": 1, "brands": 1, "classifications": 1, "states": 0}
    assert result["active_after"] == str(active)
    assert len(result["generations"]) == 2
    assert nearby(db) == before
    fourth = publish(db, 3)
    assert fourth != active
    assert proof(db) == original
    assert len(manage(db)["generations"]) == 3


def test_disable_pending_noop_and_guarded_reactivation(db):
    original = proof(db)
    g = publish(db, 0)
    plan = manage(db, "disable")
    result = apply_plan(db, plan)
    assert result["removed"]["states"] == 1
    assert all(not p["active"] for p in result["generations"])
    data = nearby(db, brand_scope="chain", brand_unknown="exclude")
    assert data["data"]["count"] == 0
    assert data["meta"]["brand_classification"]["status"] == "pending"
    assert len(manage(db)["generations"]) == 1
    assert apply_plan(db, manage(db, "disable"))["unchanged"]
    with pytest.raises(ChainsError, match="active_changed"):
        apply_plan(db, plan)
    with db.engine.begin() as c:
        publication.locked(c, True)
        publication.activate(c, g, seeds(0), None, expected_active="none")
    assert nearby(db, brand_scope="chain", brand_unknown="exclude")["data"]["count"] == 1
    assert proof(db) == original


def test_active_missing_stale_plan_and_active_guards(db):
    old = publish(db, 0)
    active = publish(db, 1)
    for targets in ((active,), (old, active)):
        with pytest.raises(ChainsError, match="active_protected"):
            manage(db, "prune", targets)
    with pytest.raises(ChainsError, match="generation_missing"):
        manage(db, "prune", (uuid4(),))
    plan = manage(db, "prune", (old,))
    with pytest.raises(ChainsError, match="active_changed"):
        manage(
            db,
            "prune",
            (old,),
            True,
            expected_plan=plan["expected_plan_sha256"],
            expected_active="none",
        )
    with pytest.raises(ChainsError, match="plan_changed"):
        manage(db, "prune", (old,), True, expected_plan="0" * 64, expected_active=str(active))
    with db.engine.begin() as c:
        c.execute(update(Evidence).where(Evidence.generation == old).values(input_sha256="f" * 64))
    with pytest.raises(ChainsError, match="plan_changed"):
        apply_plan(db, plan)
    assert len(manage(db)["generations"]) == 2


def test_aba_same_active_uuid_changes_plan(db):
    old = publish(db, 0)
    active = publish(db, 1)
    plan = manage(db, "prune", (old,))
    apply_plan(db, manage(db, "disable"))
    with db.engine.begin() as c:
        publication.locked(c, True)
        publication.activate(c, active, seeds(1), None, expected_active="none")
    assert manage(db)["active"] == str(active)
    with pytest.raises(ChainsError, match="plan_changed"):
        apply_plan(db, plan)


def test_partial_delete_failure_rolls_back_entire_target(db, monkeypatch):
    old = publish(db, 0)
    publish(db, 1)
    plan = manage(db, "prune", (old,))
    original = maintenance._delete
    calls = []

    def broken(c, table, g):
        count = original(c, table, g)
        calls.append(table)
        if len(calls) == 2:
            raise ChainsError("injected_after_child_delete")
        return count

    monkeypatch.setattr(maintenance, "_delete", broken)
    with pytest.raises(ChainsError, match="injected_after_child_delete"):
        apply_plan(db, plan)
    assert len(calls) == 2
    assert manage(db, "prune", (old,))["expected_plan_sha256"] == plan["expected_plan_sha256"]


def test_existing_rr_reader_sees_retired_rows_after_disable_and_prune(db):
    g = publish(db, 0)
    with Session(db.engine) as reader:
        reader.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        reader.execute(text("SET TRANSACTION READ ONLY"))
        selection = ChainSelection.load(reader)
        assert reader.scalar(select(State.generation)) == g
        apply_plan(db, manage(db, "disable"))
        apply_plan(db, manage(db, "prune", (g,)))
        assert reader.scalar(select(Publication.generation)) == g
        assert reader.scalar(select(State.generation)) == g
        assert (
            selection.brands(reader, [("general_restaurant", "synthetic-chain")])[
                ("general_restaurant", "synthetic-chain")
            ].status
            == "estimated"
        )
        current = nearby(db, brand_scope="chain", brand_unknown="exclude")
        assert current["data"]["count"] == 0
        assert current["meta"]["brand_classification"]["status"] == "pending"
        reader.rollback()
    assert not manage(db)["generations"]


def test_external_foreign_key_rejects_prune_without_losing_children(db):
    old = publish(db, 0)
    publish(db, 1)
    with db.engine.begin() as c:
        c.execute(
            text(
                "CREATE TABLE cleanup_test_pin "
                "(generation uuid REFERENCES chain_publications(generation))"
            )
        )
        c.execute(text("INSERT INTO cleanup_test_pin(generation) VALUES(:g)"), {"g": old})
    plan = manage(db, "prune", (old,))
    with pytest.raises(SQLAlchemyError) as caught:
        apply_plan(db, plan)
    assert caught.value.orig.sqlstate == "23503"
    after = manage(db, "prune", (old,))
    assert after["expected_plan_sha256"] == plan["expected_plan_sha256"]
    assert after["targets"] == plan["targets"]


def test_waiting_prune_reads_pointer_after_publisher_commit(db):
    old = publish(db, 0)
    publish(db, 1)
    plan = manage(db, "prune", (old,))
    ready = threading.Event()
    identity = {}

    def waiting():
        with db.engine.begin() as c:
            identity["pid"] = c.connection.driver_connection.info.backend_pid
            ready.set()
            maintenance.locked(c, True)
            return maintenance.manage(
                c,
                action="prune",
                generations=(old,),
                write=True,
                expected_plan=plan["expected_plan_sha256"],
                expected_active=plan["active"],
            )

    with db.engine.begin() as blocker:
        publication.locked(blocker, True)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(waiting)
            try:
                assert ready.wait(2)
                blocked = False
                end = time.monotonic() + 3
                with db.admin_engine.connect() as observer:
                    while time.monotonic() < end:
                        blocked = observer.scalar(
                            text(
                                "select exists(select 1 from pg_locks "
                                "where pid=:pid and not granted)"
                            ),
                            {"pid": identity["pid"]},
                        )
                        if blocked:
                            break
                        time.sleep(0.01)
                assert blocked
                candidate = publication.apply(blocker, seeds(2), None)
                publication.apply(
                    blocker,
                    seeds(2),
                    None,
                    write=True,
                    expected_plan=candidate["expected_plan_sha256"],
                    expected_active=candidate["active"],
                )
                blocker.commit()
                with pytest.raises(ChainsError, match="active_changed"):
                    future.result(timeout=4)
            finally:
                blocker.rollback()
    assert len(manage(db)["generations"]) == 3
