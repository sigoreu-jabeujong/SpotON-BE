from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.dependencies import history_session
from app.main import create_app
from app.models import Store, StoreImportBatch
from etl.localdata.constants import Source
from etl.localdata.provenance import import_batch
from tests.etl.test_localdata_snapshot import collection
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration
KEY = "마포구-서교동-123-4"


def seed(database: TemporaryDatabase) -> None:
    migrate(database)
    original = collection()
    original = replace(
        original, rows=tuple(replace(row, update_point="20261110000000") for row in original.rows)
    )
    batch = import_batch(original, uuid4())
    cafe_batch = import_batch(replace(original, source=Source.REST_CAFE), uuid4())
    with Session(database.engine) as session, session.begin():
        session.add_all([batch, cafe_batch])
        for index, changes in enumerate(
            [
                {},
                {
                    "source": "rest_cafe",
                    "category": "cafe",
                    "sub_category": "cafe",
                    "batch_id": cafe_batch.batch_id,
                    "floor_unit": "3층 301호",
                },
                {"status": "closed", "close_date": date(2022, 2, 1)},
                {"status": "closed"},
                {"open_date": None},
                {"deleted_at": datetime.now(UTC)},
                {"sub_category": "snack"},
                {"category_review_flag": True},
                {"building_key": "마포구-서교동-124-0"},
                {"is_temporary": True, "floor_unit": "2층"},
                {"is_franchise": True},
                {"is_franchise": False},
            ]
        ):
            values = dict(
                source="general_restaurant",
                license_no="same" if index <= 1 else str(index),
                name="synthetic-name",
                category="restaurant",
                sub_category="korean",
                building_key=KEY,
                floor_unit="2층 201호",
                location_level="same_spot",
                open_date=date(2020, 1, 1),
                status="open",
                batch_id=batch.batch_id,
            )
            values.update(changes)
            session.add(Store(**values))


def test_real_history_query_contract_and_version(temporary_database: TemporaryDatabase) -> None:
    seed(temporary_database)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = temporary_database.engine
    with TestClient(app) as client:
        responses = [
            client.get(
                "/api/stores/history",
                params={
                    "building_key": KEY,
                    "floor_unit": "2층 201호",
                    **category,
                },
            )
            for category in ({}, {"category": "cafe"}, {"category": "restaurant"})
        ]
        assert all(response.status_code == 200 for response in responses)
        payload = responses[0].json()
        assert all(r.json() == payload for r in responses)
        rows = payload["data"]["stores"]
        assert len(rows) == payload["data"]["total"] == 8
        assert len([r for r in rows if r["license_no"] == "same"]) == 2
        assert rows[-1]["open_date"] is None
        assert {r["franchise"] for r in rows} == {"franchise", "independent", "unknown"}
        by_license = {r["license_no"]: r for r in rows if r["source"] == "general_restaurant"}
        assert by_license["2"]["operating_months"] == 25
        assert by_license["3"]["store_status"] == "closed"
        assert by_license["3"]["operating_months"] is None
        assert by_license["3"]["operating_period_reason"] == "missing_close_date"
        assert by_license["9"]["location_match"] == "unverified"
        assert by_license["same"]["location_match"] == "same_spot"
        assert (
            next(r for r in rows if r["source"] == "rest_cafe")["location_match"] == "same_building"
        )
        assert payload["meta"]["data_updated_at"] == "2026-11-10"
        assert payload["meta"]["collected_at"] is None
        assert len(payload["meta"]["data_version"]["stores_batch_ids"]) == 2
        assert responses[0].headers["cache-control"] == "no-store"
        no_detail = client.get("/api/stores/history", params={"building_key": KEY}).json()
        assert {s["location_match"] for s in no_detail["data"]["stores"]} == {"unverified"}
        empty = client.get("/api/stores/history", params={"building_key": "마포구-서교동-9999-0"})
        assert empty.status_code == 200 and empty.json()["data"]["total"] == 0


def test_history_connection_is_read_only_and_closes_on_failure(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = temporary_database.engine

    # Exercise the real request dependency through an extra isolated test route.
    @app.get("/test/read-only")
    def forbidden_write(session: Annotated[Session, Depends(history_session)]) -> None:
        session.execute(
            text("INSERT INTO stores (source, license_no) VALUES ('test', 'write-canary')")
        )

    with TestClient(app) as client:
        response = client.get("/test/read-only")
        assert response.status_code == 500 and "canary" not in response.text
        assert client.get("/api/health").status_code == 200
    with temporary_database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Store)) == 0


def test_batch_migration_downgrade_preserves_stores(temporary_database: TemporaryDatabase) -> None:
    seed(temporary_database)
    config = Config(str(ROOT / "alembic.ini"))
    with temporary_database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")
        assert connection.scalar(text("SELECT count(*) FROM stores")) == 12
        assert connection.scalar(text("SELECT to_regclass('store_import_batches')")) is None
        command.upgrade(config, "head")
        assert connection.scalar(select(func.count()).select_from(StoreImportBatch)) == 0


def test_sql_statement_timeout_is_enforced(temporary_database: TemporaryDatabase) -> None:
    migrate(temporary_database)
    app = create_app(Settings(_env_file=None, database_statement_timeout_ms=10))
    app.state.database.engine = temporary_database.engine

    @app.get("/test/timeout")
    def slow_query(session: Annotated[Session, Depends(history_session)]) -> None:
        session.execute(text("SELECT pg_sleep(0.05)"))

    with TestClient(app) as client:
        response = client.get("/test/timeout")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "pg_sleep" not in response.text
