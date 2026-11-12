import json

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from etl.localdata import maintenance as cli
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def maintenance_db(temporary_database, monkeypatch):
    migrate(temporary_database)
    engine = temporary_database.engine
    with Session(engine) as session, session.begin():
        provenance = batch(session)
        for i in range(20):
            store(session, provenance, f"synthetic-{i}", distance=100)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE public.stores SET (autovacuum_enabled=false)"))
        connection.execute(text("UPDATE public.stores SET name='after-update'"))
    monkeypatch.setattr(cli, "create_db_engine", lambda _: engine)
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@127.0.0.1/spoton_dev"
    )
    monkeypatch.setattr(cli, "Settings", lambda: config)

    def isolated_identity(connection):
        # Only replace the exact dev identity requirement with this UUID fixture identity.
        assert (
            connection.scalar(text("SELECT current_database()")) == temporary_database.database_name
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"

    monkeypatch.setattr(cli, "check_local_database", isolated_identity)
    return engine


def snapshot(engine):
    with engine.connect() as connection:
        return {
            name: connection.execute(text(sql)).all()
            for name, sql in {
                "stores": "SELECT to_jsonb(s) FROM stores s ORDER BY id",
                "batches": "SELECT to_jsonb(b) FROM store_import_batches b ORDER BY batch_id",
                "head": "SELECT version_num FROM alembic_version",
                "indexes": (
                    "SELECT indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname"
                ),
            }.items()
        }


@pytest.mark.parametrize("execute", [False, True])
def test_actual_vacuum_and_readonly_phases_preserve_logical_data(maintenance_db, capsys, execute):
    engine = maintenance_db
    before = snapshot(engine)
    calls = []

    def capture(conn, cursor, statement, parameters, context, many):
        if statement == cli.VACUUM_SQL:
            driver = conn.connection.driver_connection
            assert driver.autocommit is True
            assert conn.scalar(text("SHOW lock_timeout")) == cli.LOCK_TIMEOUT
            assert (
                conn.scalar(
                    text("SELECT setting::int FROM pg_settings WHERE name='statement_timeout'")
                )
                == 60000
            )
            calls.append("vacuum")
        elif statement.startswith("SELECT store_import_batches"):
            assert conn.scalar(text("SHOW transaction_read_only")) == "on"
            assert conn.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert conn.scalar(text("SHOW statement_timeout")) == "3s"
            calls.append("provenance")

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert cli.main(["--execute"] if execute else []) == 0
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    result = json.loads(capsys.readouterr().out)
    assert result["vacuum_completed"] is execute and result["provenance_checked"] is execute
    assert calls == (["vacuum", "provenance"] if execute else [])
    assert snapshot(engine) == before
    if execute:
        assert result["batch_count"] == 1 and result["reference_date"] == "2026-11-10"
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT relallvisible>0 FROM pg_class WHERE oid='public.stores'::regclass")
                )
                is True
            )


def test_vacuum_success_is_preserved_when_provenance_is_invalid(maintenance_db, capsys):
    engine = maintenance_db
    with engine.begin() as connection:
        connection.execute(text("UPDATE stores SET batch_id=NULL WHERE license_no='synthetic-0'"))
    before = snapshot(engine)
    assert cli.main(["--execute"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["vacuum_completed"] is True and result["provenance_checked"] is False
    assert result["phase"] == "provenance" and result["error"] == "localdata_maintenance:provenance"
    assert snapshot(engine) == before


@pytest.mark.parametrize("execute", [False, True])
def test_nonowner_is_rejected_before_vacuum(maintenance_db, capsys, execute):
    engine = maintenance_db
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE public.stores OWNER TO pg_database_owner"))
    before = snapshot(engine)
    assert cli.main(["--execute"] if execute else []) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"] == "localdata_maintenance:ownership"
    assert result["vacuum_completed"] is False and snapshot(engine) == before


def test_shadow_store_schema_is_rejected(maintenance_db, monkeypatch):
    engine = maintenance_db
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA shadow"))
        connection.execute(text("CREATE TABLE shadow.stores (id bigint)"))
    original = cli.check_local_database

    def shadow(connection):
        original(connection)
        connection.execute(text("SET LOCAL search_path=shadow,public"))

    monkeypatch.setattr(cli, "check_local_database", shadow)
    result = cli.run_maintenance(execute=True)
    assert result.error == "ownership" and result.vacuum_completed is False


def test_conflicting_lock_times_out_without_claiming_completion(maintenance_db):
    engine = maintenance_db
    with engine.connect() as blocker, blocker.begin():
        blocker.execute(text("LOCK TABLE public.stores IN SHARE UPDATE EXCLUSIVE MODE"))
        result = cli.run_maintenance(execute=True)
    assert result.error == "vacuum" and result.phase == "vacuum"
    assert result.vacuum_completed is False and result.provenance_checked is False
