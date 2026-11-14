from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.ai.context import prepare_risk_interpretation
from app.core.config import Settings
from app.main import create_app
from app.models import (
    Brand,
    BrandCatalogVersion,
    BrandMappingRun,
    BrandMappingState,
    Store,
    StoreBrandMatch,
)
from app.schemas.risk import RiskQuery
from app.services.franchise import effective_franchise
from etl.brands import apply, assignment
from etl.brands.snapshot import save_snapshot
from etl.localdata.constants import Source
from etl.localdata.repository import upsert_records
from tests.etl.brands_helpers import catalog, item
from tests.integration.test_localdata_upsert import migrate, record
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration
KEY = "마포구-서교동-123-4"
TABLES = (StoreBrandMatch, BrandMappingState, BrandMappingRun, Brand, BrandCatalogVersion)


@pytest.fixture
def setup(temporary_database, tmp_path, monkeypatch):
    migrate(temporary_database)
    engine = temporary_database.engine
    with Session(engine) as session, session.begin():
        provenance = batch(session)
        for identity, name, flag, brand in (
            ("estimate", "Unique Bistro", None, None),
            ("unknown", "Other Place", None, None),
            ("manualfalse", "Unique Bistro", False, 1),
            ("manualtrue", "Other Place", True, 1),
            ("opaque", "Unique Bistro", None, 999),
            ("repeated", "Repeated Brand", None, None),
            ("ambiguous", "Same Brand", None, None),
        ):
            store(
                session,
                provenance,
                identity,
                name=name,
                is_franchise=flag,
                brand_id=brand,
                building_key=KEY,
            )
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@127.0.0.1/spoton_dev"
    )
    monkeypatch.setattr(apply, "create_db_engine", lambda _: engine)

    def check(c):
        assert c.scalar(text("SELECT current_database()")) == temporary_database.database_name
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0012"

    monkeypatch.setattr(apply, "check_local_database", check)
    source = catalog(
        [
            item("001", "Unique Bistro"),
            item("002", "Repeated Brand", jnghdqrtrsMnno="HQ_A"),
            item("002", "Repeated Alias", jnghdqrtrsMnno="HQ_B"),
            item("003", "Same Brand"),
            item("004", "Same Brand"),
        ]
    )
    path = tmp_path / "source.json"
    save_snapshot(path, source)
    return engine, config, source, path


def fingerprint(engine):
    with engine.connect() as c:
        return c.scalar(
            text("SELECT md5(string_agg(md5(to_jsonb(s)::text),'' ORDER BY id)) FROM stores s")
        )


def classified(engine):
    with Session(engine) as session:
        return dict(session.execute(select(Store.license_no, effective_franchise())).all())


def test_dryrun_atomic_apply_replay_preserves_entire_original_store(setup):
    engine, config, source, path = setup
    before = fingerprint(engine)
    dry = apply.run_apply(path, settings=config)
    assert dry["rows"] == 7 and dry["matched"] == 1
    with engine.connect() as c:
        assert all(c.scalar(select(func.count()).select_from(t)) == 0 for t in TABLES)
    first = apply.run_apply(path, settings=config, write=True)
    with engine.connect() as c:
        loaded = c.execute(select(BrandMappingRun.loaded_at)).scalar_one()
    again = apply.run_apply(path, settings=config, write=True)
    assert again["reused"] and not again["state_changed"] and again["catalog_reused"]
    assert first["mapping_run_id"] == again["mapping_run_id"]
    assert first["store_input_sha256"] == again["store_input_sha256"] == dry["store_input_sha256"]
    assert fingerprint(engine) == before
    with engine.connect() as c:
        assert c.execute(select(BrandMappingRun.loaded_at)).scalar_one() == loaded
        assert c.scalar(select(func.count()).select_from(StoreBrandMatch)) == 1
    assert classified(engine) == dict(
        estimate=True,
        unknown=None,
        manualfalse=False,
        manualtrue=True,
        opaque=None,
        repeated=None,
        ambiguous=None,
    )


def test_source_name_change_revert_and_manual_same_true_have_unambiguous_ownership(setup):
    engine, config, source, path = setup
    apply.run_apply(path, settings=config, write=True)
    with engine.begin() as c:
        c.execute(update(Store).where(Store.license_no == "estimate").values(name="Changed"))
    assert classified(engine)["estimate"] is None
    with engine.begin() as c:
        c.execute(update(Store).where(Store.license_no == "estimate").values(name="Unique Bistro"))
    assert classified(engine)["estimate"] is True
    with engine.begin() as c:
        c.execute(update(Store).where(Store.license_no == "estimate").values(is_franchise=True))
        c.execute(update(Store).where(Store.license_no == "estimate").values(name="Manual Name"))
    assert classified(engine)["estimate"] is True
    with engine.connect() as c:
        assert c.scalar(select(Store.is_franchise).where(Store.license_no == "estimate")) is True


def test_real_localdata_upsert_invalidates_estimate_but_preserves_manual_flags(setup):
    engine, config, source, path = setup
    apply.run_apply(path, settings=config, write=True)
    with engine.connect() as c:
        batch_id = c.scalar(select(Store.batch_id).limit(1))
    for identity in ("estimate", "manualtrue"):
        incoming = record(Source.GENERAL_RESTAURANT, identity, name="Renamed", batch=str(batch_id))
        with engine.connect() as c:
            upsert_records(c, Source.GENERAL_RESTAURANT, [incoming])
    values = classified(engine)
    assert values["estimate"] is None and values["manualtrue"] is True
    assert values["manualfalse"] is False


def test_generation_switch_isolated_and_explicit_old_catalog_reusable(setup, tmp_path):
    engine, config, source, path = setup
    first = apply.run_apply(path, settings=config, write=True)
    other = tmp_path / "other.json"
    save_snapshot(other, catalog([item("other", "Other Place")]))
    second = apply.run_apply(other, settings=config, write=True)
    assert first["mapping_run_id"] != second["mapping_run_id"]
    assert classified(engine)["estimate"] is None and classified(engine)["unknown"] is True
    restored = apply.run_apply(path, settings=config, write=True)
    assert restored["reused"] and restored["state_changed"]
    assert restored["mapping_run_id"] == first["mapping_run_id"]
    assert classified(engine)["estimate"] is True and classified(engine)["unknown"] is None


def test_post_insert_failure_rolls_back_every_new_table_and_state(setup, monkeypatch):
    engine, config, source, path = setup
    before = fingerprint(engine)

    def fail(*args):
        raise RuntimeError("PRIVATE_CANARY")

    monkeypatch.setattr(assignment, "_verify_matches", fail)
    with pytest.raises(RuntimeError):
        apply.run_apply(path, settings=config, write=True)
    with engine.connect() as c:
        assert all(c.scalar(select(func.count()).select_from(t)) == 0 for t in TABLES)
    assert fingerprint(engine) == before


def test_concurrent_apply_is_idempotent(setup):
    engine, config, source, path = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(apply.run_apply, path, settings=config, write=True) for _ in range(2)
        ]
        outputs = [f.result(timeout=20) for f in futures]
    assert outputs[0]["mapping_run_id"] == outputs[1]["mapping_run_id"]
    assert sorted(r["reused"] for r in outputs) == [False, True]


def test_concurrent_source_change_after_plan_is_not_exposed_as_positive(setup, monkeypatch):
    engine, config, source, path = setup
    original = apply.save

    def concurrent_change(c, *args):
        with engine.begin() as other:
            other.execute(
                update(Store).where(Store.license_no == "estimate").values(name="Renamed")
            )
        return original(c, *args)

    monkeypatch.setattr(apply, "save", concurrent_change)
    apply.run_apply(path, settings=config, write=True)
    assert classified(engine)["estimate"] is None


def test_input_hash_ignores_surrogate_row_ids_and_apply_preserves_empty_source(setup):
    engine, config, source, path = setup
    first = apply.run_apply(path, settings=config, write=True)
    with engine.begin() as c:
        old = dict(
            c.execute(select(Store.__table__).where(Store.license_no == "estimate"))
            .mappings()
            .one()
        )
        c.execute(Store.__table__.delete().where(Store.id == old.pop("id")))
        c.execute(Store.__table__.insert().values(**old))
    second = apply.run_apply(path, settings=config, write=True)
    assert first["store_input_sha256"] == second["store_input_sha256"]
    assert second["reused"] and second["mapping_run_id"] == first["mapping_run_id"]


def test_catalog_or_match_tamper_is_rejected_without_pointer_changes(setup):
    engine, config, source, path = setup
    first = apply.run_apply(path, settings=config, write=True)
    with engine.begin() as c:
        c.execute(update(StoreBrandMatch).values(name="ChangedEvidence"))
    with pytest.raises(ValueError, match="mapping_content"):
        apply.run_apply(path, settings=config, write=True)
    with engine.connect() as c:
        assert str(c.scalar(select(BrandMappingState.run_id))) == first["mapping_run_id"]
    assert classified(engine)["estimate"] is None


def test_filters_history_snapshot_activity_risk_and_internal_ai_agree(setup):
    engine, config, source, path = setup
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    with TestClient(app) as client:
        initial = client.get("/api/risk", params=PARAMS)
        assert (
            initial.status_code == 200
            and initial.json()["meta"]["franchise_classification"]["status"] == "pending"
        )
        apply.run_apply(path, settings=config, write=True)
        for franchise, count in (("franchise", 2), ("independent", 1), ("all", 3)):
            params = {**PARAMS, "franchise": franchise, "include_unknown_franchise": "false"}
            nearby = client.get("/api/stores/nearby", params=params)
            assert nearby.status_code == 200, nearby.text
            assert nearby.json()["data"]["count"] == count
            snap = client.get("/api/stores/snapshot", params={**params, "as_of": "2026-11"})
            activity = client.get("/api/market/activity", params=params)
            risk = client.get("/api/risk", params=params)
            for response in (snap, activity, risk):
                assert response.status_code == 200, response.text
            assert snap.json()["data"]["total_at_as_of"] == count
            assert sum(r["open_count"] for r in activity.json()["data"]["by_sub_category"]) == count
            indicator = next(
                i for i in risk.json()["data"]["indicators"] if i["id"] == "competitor_count"
            )
            assert indicator["value"] == count
        history = client.get("/api/stores/history", params={"building_key": KEY}).json()
        target = next(r for r in history["data"]["stores"] if r["license_no"] == "estimate")
        assert (
            target["franchise_basis"] == "catalog_exact_name"
            and target["franchise_reference_year"] == 2025
        )
        raw = next(r for r in history["data"]["stores"] if r["license_no"] == "manualtrue")
        assert (
            raw["franchise_basis"] == "external_classification"
            and raw["franchise_reference_year"] is None
        )
        with Session(engine) as session:
            prepared = prepare_risk_interpretation(
                session, RiskQuery(**PARAMS), Settings(_env_file=None)
            )
            safe = prepared.json_context()
            assert (
                safe["franchise_classification"] == "estimate"
                and safe["franchise_reference_year"] == 2025
            )
            assert "Unique Bistro" not in str(safe) and "catalog_version_id" not in str(safe)


def test_same_counts_new_snapshot_invalidate_internal_data_version_and_risk_cache(setup, tmp_path):
    engine, config, source, path = setup
    apply.run_apply(path, settings=config, write=True)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    with TestClient(app) as client:
        before = client.get("/api/risk", params=PARAMS).json()
        with Session(engine) as s:
            p = prepare_risk_interpretation(s, RiskQuery(**PARAMS), Settings(_env_file=None))
        another = tmp_path / "same-content.json"
        save_snapshot(
            another, replace(source, collected_at=source.collected_at + timedelta(microseconds=1))
        )
        apply.run_apply(another, settings=config, write=True)
        after = client.get("/api/risk", params=PARAMS).json()
        with Session(engine) as s:
            q = prepare_risk_interpretation(s, RiskQuery(**PARAMS), Settings(_env_file=None))
        assert before["data"] == after["data"]
        assert (
            before["meta"]["data_version"]["brand_mapping"]
            != after["meta"]["data_version"]["brand_mapping"]
        )
        assert p.context_hash == q.context_hash and p.data_version_hash != q.data_version_hash


def test_all_filter_and_unknown_combinations_agree_with_read_time_classification(setup):
    engine, config, source, path = setup
    apply.run_apply(path, settings=config, write=True)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    with TestClient(app) as client:
        for franchise, include_unknown, count in (
            ("all", True, 7),
            ("all", False, 3),
            ("franchise", True, 6),
            ("franchise", False, 2),
            ("independent", True, 5),
            ("independent", False, 1),
        ):
            response = client.get(
                "/api/stores/nearby",
                params={
                    **PARAMS,
                    "franchise": franchise,
                    "include_unknown_franchise": str(include_unknown).lower(),
                },
            )
            assert response.status_code == 200 and response.json()["data"]["count"] == count


def test_public_ai_before_and_after_mapping_uses_safe_server_authored_limit(setup):
    from tests.integration.test_interpret import Provider

    engine, config, source, path = setup
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    provider = Provider(engine)
    app.state.interpretation.client = provider
    with TestClient(app) as client:
        before = client.post("/api/risk/interpret", json={"query": PARAMS})
        assert before.status_code == 200, before.text
        assert "classification_unverified" in before.text
        apply.run_apply(path, settings=config, write=True)
        after = client.post("/api/risk/interpret", json={"query": PARAMS})
        assert after.status_code == 200, after.text
        assert "franchise_name_match_estimate" in after.text
        assert provider.calls == 2 and "Unique Bistro" not in after.text


def test_empty_downgrade_and_nonempty_downgrade_rejection(setup):
    engine, config, source, path = setup
    cfg = Config("alembic.ini")
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0010")
        command.upgrade(cfg, "head")
    apply.run_apply(path, settings=config, write=True)
    with (
        pytest.raises(RuntimeError, match="brand_downgrade_requires_empty_data"),
        engine.begin() as c,
    ):
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0010")
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0012"
