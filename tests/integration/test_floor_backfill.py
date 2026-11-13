from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

import etl.localdata.floor_backfill as backfill
from app.models import Store, StoreImportBatch
from app.schemas.stores import HistoryQuery
from app.services.store_history import get_history
from etl.localdata.constants import Source
from etl.localdata.provenance import import_batch
from etl.localdata.repository import upsert_records
from etl.localdata.snapshot import save_snapshot
from tests.etl.test_floor_backfill import prepared
from tests.etl.test_localdata_snapshot import collection
from tests.integration.analysis_flow_helpers import LAT, LNG, application, ok, track_ai_cache_keys
from tests.integration.test_floor_unit_upsert import migrate

pytestmark = pytest.mark.integration


def seed(database, tmp_path, source=Source.GENERAL_RESTAURANT):
    migrate(database)
    value = prepared(tmp_path, source)
    batch_id = uuid4()
    batch = import_batch(value.collection, batch_id)
    batch.rule_version = "localdata-normalization-v1"
    records = [
        replace(
            r,
            batch_id=batch_id,
            **(
                {"floor_unit": None, "location_level": "unverified"}
                if r.license_no == "RESTORE"
                else {}
            ),
        )
        for r in value.records
    ]
    with database.engine.connect() as c:
        upsert_records(c, source, records, batch=batch)
    with database.engine.begin() as c:
        c.execute(text("UPDATE stores SET is_franchise=true,brand_id=9 WHERE license_no='RESTORE'"))
        c.execute(
            text("UPDATE stores SET deleted_at=:d WHERE license_no='KEEP'"),
            {"d": datetime(2026, 1, 1, tzinfo=UTC)},
        )
    return value


def inspect(engine, value):
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        c.exec_driver_sql("SET TRANSACTION READ ONLY")
        assert c.scalar(text("SHOW transaction_read_only")) == "on"
        return backfill.inspect_source(c, value)


def apply(engine, value, plan):
    with engine.connect().execution_options(isolation_level="READ COMMITTED") as c, c.begin():
        return backfill.apply_source(c, value, plan.sha256)


def snapshot(engine):
    with engine.connect() as c:
        stores = list(c.execute(text("SELECT to_jsonb(s)::text FROM stores s ORDER BY id")))
        batches = list(
            c.execute(
                text("SELECT to_jsonb(b)::text FROM store_import_batches b ORDER BY batch_id")
            )
        )
        seq = c.execute(text("SELECT last_value,is_called FROM stores_id_seq")).one()
    return stores, batches, seq


@pytest.mark.parametrize("source", list(Source))
def test_backfill_preserves_protected_values_sequence_and_history_and_replay(
    temporary_database, tmp_path, source
):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path, source)
    before = snapshot(engine)
    plan = inspect(engine, value)
    assert snapshot(engine) == before
    assert len(plan.changes) == 1
    assert plan.counts["floor_and_unit"] == 1
    assert plan.sha256 == inspect(engine, value).sha256
    assert "RESTORE" not in repr(plan) + str(plan.summary())
    assert apply(engine, value, plan)["status"] == "applied"
    after = inspect(engine, value)
    assert not after.changes
    assert after.protected_sha256 == plan.protected_sha256
    assert snapshot(engine)[2] == before[2]
    with engine.connect() as c:
        assert (
            c.scalar(
                select(StoreImportBatch.rule_version).where(
                    StoreImportBatch.batch_id == plan.batch_id
                )
            )
            == "localdata-normalization-v1"
        )
        assert (
            c.scalar(
                select(StoreImportBatch.rule_version).where(
                    StoreImportBatch.batch_id == after.batch_id
                )
            )
            == "localdata-normalization-v2"
        )
        assert (
            c.scalar(text("SELECT count(*) FROM stores WHERE batch_id=:id"), {"id": after.batch_id})
            == 3
        )
    with Session(engine) as session:
        result = get_history(
            session, HistoryQuery(building_key="중구-명동2가-1-1", floor_unit="2층 201호")
        )
        item = next(s for s in result.data.stores if s.license_no == "RESTORE")
        assert item.location_match == "same_spot"
        result = get_history(
            session, HistoryQuery(building_key="중구-명동2가-1-1", floor_unit="2층")
        )
        assert all(s.location_match == "unverified" for s in result.data.stores)
    saved = snapshot(engine)
    with pytest.raises(backfill.BackfillError, match="stale_plan"):
        apply(engine, value, plan)
    assert apply(engine, value, after)["status"] == "no_op"
    assert snapshot(engine) == saved


@pytest.mark.parametrize("column", ["name", "date_flag", "building_key", "raw_x", "geom"])
def test_non_location_or_even_tiny_geometry_difference_blocks_entire_source(
    temporary_database, tmp_path, column
):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    with engine.begin() as c:
        if column == "geom":
            c.execute(
                text(
                    "UPDATE stores SET geom=ST_SetSRID(ST_MakePoint("
                    "ST_X(geom)+0.000000000001,ST_Y(geom)),4326) WHERE license_no='RESTORE'"
                )
            )
        else:
            c.execute(
                Store.__table__.update()
                .where(Store.license_no == "RESTORE")
                .values(**{column: "changed-canary"})
            )
    before = snapshot(engine)
    with pytest.raises(backfill.BackfillError, match="non_location|geometry"):
        inspect(engine, value)
    assert snapshot(engine) == before


@pytest.mark.parametrize(
    "field,change",
    [
        ("rows_sha256", "f" * 64),
        ("row_count", 4),
        ("map_version", "other"),
        ("rule_version", "future-unsupported"),
        ("collection_basis", "other"),
        ("update_reason", "invented-repair-reason"),
    ],
)
def test_original_batch_mismatch_blocks_planning(temporary_database, tmp_path, field, change):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    with engine.begin() as c:
        c.execute(StoreImportBatch.__table__.update().values(**{field: change}))
    with pytest.raises(backfill.BackfillError, match="provenance"):
        inspect(engine, value)


@pytest.mark.parametrize("kind", ["missing_key", "extra_key", "mixed_batch", "null_batch"])
def test_source_coverage_and_single_active_batch_are_required(temporary_database, tmp_path, kind):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    with engine.begin() as c:
        if kind == "missing_key":
            c.execute(text("DELETE FROM stores WHERE license_no='KEEP'"))
        elif kind == "extra_key":
            c.execute(text("UPDATE stores SET license_no='EXTRA' WHERE license_no='KEEP'"))
        elif kind == "null_batch":
            c.execute(text("UPDATE stores SET batch_id=NULL WHERE license_no='KEEP'"))
        else:
            new_id = uuid4()
            c.execute(
                StoreImportBatch.__table__.insert().values(
                    **value.batch_values, batch_id=new_id, rule_version="localdata-normalization-v1"
                )
            )
            c.execute(
                text("UPDATE stores SET batch_id=:id WHERE license_no='KEEP'"), {"id": new_id}
            )
    with pytest.raises(backfill.BackfillError, match="keys|active_batch"):
        inspect(engine, value)


@pytest.mark.parametrize("stored,level", [("3층", "same_building"), (None, "same_spot")])
def test_existing_location_conflict_is_not_replaced(temporary_database, tmp_path, stored, level):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    with engine.begin() as c:
        c.execute(
            text("UPDATE stores SET floor_unit=:f,location_level=:l WHERE license_no='RESTORE'"),
            {"f": stored, "l": level},
        )
    with pytest.raises(backfill.BackfillError, match="location_conflict"):
        inspect(engine, value)


def test_null_level_on_ambiguous_record_is_never_rewritten(temporary_database, tmp_path):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    with engine.begin() as c:
        c.execute(text("UPDATE stores SET location_level=NULL WHERE license_no='AMBIGUOUS'"))
    apply(engine, value, inspect(engine, value))
    with engine.connect() as c:
        assert c.scalar(select(Store.location_level).where(Store.license_no == "AMBIGUOUS")) is None
    assert not inspect(engine, value).changes


@pytest.mark.parametrize("stage", ["batch_insert", "location_update", "batch_update"])
def test_every_write_stage_rolls_back_source_batch_and_sequence(
    temporary_database, tmp_path, stage
):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    plan = inspect(engine, value)
    before = snapshot(engine)

    def fail(c, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        match = (
            (stage == "batch_insert" and lowered.startswith("insert into store_import_batches"))
            or (stage == "location_update" and lowered.startswith("update stores set floor_unit"))
            or (stage == "batch_update" and lowered.startswith("update stores set updated_at"))
        )
        if match:
            raise RuntimeError("injected failure")

    event.listen(engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected failure"):
            apply(engine, value, plan)
    finally:
        event.remove(engine, "after_cursor_execute", fail)
    assert snapshot(engine) == before


def test_waiting_for_writer_rechecks_committed_state_before_using_plan(
    temporary_database, tmp_path
):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    plan = inspect(engine, value)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.begin() as writer:
            writer.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "spoton:localdata:general_restaurant"},
            )
            future = pool.submit(apply, engine, value, plan)
            deadline = monotonic() + 3
            while True:
                waiting = writer.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks "
                        "WHERE locktype='advisory' AND NOT granted)"
                    )
                )
                if waiting:
                    break
                assert monotonic() < deadline, "backfill did not wait for the writer"
                sleep(0.01)
            writer.execute(
                text("UPDATE stores SET updated_at='2026-11-13' WHERE license_no='RESTORE'")
            )
        saved = snapshot(engine)
        with pytest.raises(backfill.BackfillError, match="stale_plan"):
            future.result(timeout=5)
    assert snapshot(engine) == saved


def test_source_and_target_identity_bind_plan_and_other_source_is_untouched(
    temporary_database, tmp_path, monkeypatch
):
    engine = temporary_database.engine
    general = seed(temporary_database, tmp_path, Source.GENERAL_RESTAURANT)
    cafe = seed(temporary_database, tmp_path, Source.REST_CAFE)
    general_plan, cafe_plan = inspect(engine, general), inspect(engine, cafe)
    with pytest.raises(backfill.BackfillError, match="stale_plan"):
        apply(engine, cafe, general_plan)
    target = backfill._target
    monkeypatch.setattr(backfill, "_target", lambda c: [*target(c), "another-port-or-cluster"])
    with pytest.raises(backfill.BackfillError, match="stale_plan"):
        apply(engine, general, general_plan)
    monkeypatch.setattr(backfill, "_target", target)
    apply(engine, general, general_plan)
    assert inspect(engine, cafe).sha256 == cafe_plan.sha256


def test_affected_row_count_mismatch_rolls_back(temporary_database, tmp_path, monkeypatch):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    plan = inspect(engine, value)
    before = snapshot(engine)
    write = backfill._write_changes
    monkeypatch.setattr(
        backfill,
        "_write_changes",
        lambda c, p, new: write(c, replace(p, row_count=p.row_count + 1), new),
    )
    with pytest.raises(backfill.BackfillError, match="affected_rows"):
        apply(engine, value, plan)
    assert snapshot(engine) == before


def test_lock_timeout_rolls_back_without_source_or_batch_writes(temporary_database, tmp_path):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    plan = inspect(engine, value)
    before = snapshot(engine)
    with engine.begin() as writer:
        writer.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "spoton:localdata:general_restaurant"},
        )
        from sqlalchemy.exc import OperationalError

        with pytest.raises(OperationalError):
            apply(engine, value, plan)
    assert snapshot(engine) == before


def test_repair_updates_history_ai_context_and_invalidates_ai_cache(
    temporary_database, tmp_path, monkeypatch
):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path, Source.GENERAL_RESTAURANT)
    seed(temporary_database, tmp_path, Source.REST_CAFE)
    app, provider = application(temporary_database)
    cache_keys = track_ai_cache_keys(app, monkeypatch)
    body = {
        "query": {"lat": LAT, "lng": LNG, "category": "restaurant", "radius": 500},
        "history": {"building_key": "중구-명동2가-1-1", "floor_unit": "2층 201호"},
    }
    with TestClient(app) as client:
        first = ok(client.post("/api/risk/interpret", json=body))
        assert len(cache_keys) == 1 and provider.calls == 1
        repeated = ok(client.post("/api/risk/interpret", json=body))
        assert {k: v for k, v in repeated["data"].items() if k != "generated_at"} == {
            k: v for k, v in first["data"].items() if k != "generated_at"
        }
        assert len(cache_keys) == 2 and all(cache_keys)
        assert provider.calls == len(set(cache_keys))
        before_calls = provider.calls
        before_keys = set(cache_keys)
        apply(engine, value, inspect(engine, value))
        after = ok(client.post("/api/risk/interpret", json=body))
        assert cache_keys[-1] not in before_keys
        assert provider.calls == before_calls + 1
        assert first["meta"]["data_version_hash"] != after["meta"]["data_version_hash"]
        assert first["meta"]["context_hash"] != after["meta"]["context_hash"]
        before_history = next(
            v["text"]
            for v in first["data"]["official_values"]
            if v["indicator_ids"] == ["building_history"]
        )
        after_history = next(
            v["text"]
            for v in after["data"]["official_values"]
            if v["indicator_ids"] == ["building_history"]
        )
        assert "같은 자리로 확인된 기록 0건" in before_history
        assert "같은 자리로 확인된 기록 1건" in after_history


@pytest.mark.parametrize("write", [False, True])
def test_shadow_schema_is_rejected_before_reading_or_writing_it(
    temporary_database, tmp_path, write
):
    engine = temporary_database.engine
    value = seed(temporary_database, tmp_path)
    plan = inspect(engine, value)
    before = snapshot(engine)
    with engine.begin() as c:
        c.exec_driver_sql("CREATE SCHEMA floor_shadow")
        c.exec_driver_sql("CREATE VIEW floor_shadow.stores AS SELECT * FROM public.stores")
        c.exec_driver_sql(
            "CREATE VIEW floor_shadow.store_import_batches "
            "AS SELECT * FROM public.store_import_batches"
        )
        c.exec_driver_sql("SET LOCAL search_path=floor_shadow,public")
        with pytest.raises(backfill.BackfillError, match="backfill:target"):
            if write:
                backfill.apply_source(c, value, plan.sha256)
            else:
                backfill.inspect_source(c, value)
    assert snapshot(engine) == before


def test_bulk_repair_executes_multiple_parameter_sets_and_chunk_boundary(
    temporary_database, tmp_path
):
    engine = temporary_database.engine
    migrate(temporary_database)
    sample = prepared(tmp_path).collection.rows[0]
    rows = tuple(replace(sample, management_no=f"BULK-{i:04}") for i in range(1001))
    original = collection(rows)
    original = replace(
        original,
        authorities=tuple(
            replace(stat, page_count=max((stat.total_count + 99) // 100, 1))
            for stat in original.authorities
        ),
    )
    path = save_snapshot(original, tmp_path)
    value = backfill.prepare_source(path, Source.GENERAL_RESTAURANT)
    batch_id = uuid4()
    batch = import_batch(value.collection, batch_id)
    batch.rule_version = "localdata-normalization-v1"
    records = [
        replace(r, batch_id=batch_id, floor_unit=None, location_level="unverified")
        for r in value.records
    ]
    with engine.connect() as c:
        upsert_records(c, Source.GENERAL_RESTAURANT, records, batch=batch)
    plan = inspect(engine, value)
    assert len(plan.changes) == 1001
    chunks = []

    def capture(c, cursor, statement, parameters, context, executemany):
        if statement.lower().startswith("update stores set floor_unit"):
            chunks.append((executemany, len(parameters) if executemany else 1))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = apply(engine, value, plan)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["status"] == "applied"
    assert chunks == [(True, 1000), (False, 1)]
    assert not inspect(engine, value).changes
