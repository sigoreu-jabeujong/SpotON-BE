"""Provenance query semantics, actual ORM plan eligibility and index-only migration."""

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.schemas.stores import HistoryQuery
from app.services.store_cohort import current_provenance
from app.services.store_history import get_history
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import ROOT, migrate
from tests.integration.test_nearby import batch, store

pytestmark = pytest.mark.integration
KEY = "마포구-서교동-123-4"


def seed(database: TemporaryDatabase) -> None:
    migrate(database)
    with Session(database.engine) as session, session.begin():
        first = batch(session, data_updated_at=date(2026, 11, 9))
        second = batch(session, source="rest_cafe", data_updated_at=date(2026, 11, 10))
        store(session, first, "null-review", None, building_key=KEY, category_review_flag=None)
        store(session, first, "false-review", None, building_key=KEY, category_review_flag=False)
        store(session, second, "cafe", None, building_key=KEY, category="cafe", sub_category="cafe")
        for i, changes in enumerate(
            [
                {"deleted_at": datetime(2026, 11, 11, tzinfo=UTC)},
                {"category_review_flag": True},
                {"sub_category": "snack"},
                {"source": "unsupported_source"},
            ]
        ):
            unused = batch(session, data_updated_at=date(2026, 11, 12))
            store(session, unused, f"excluded-{i}", None, building_key=KEY, **changes)
        batch(session, data_updated_at=date(2026, 11, 12))


def test_global_batches_and_history_ignore_later_excluded_batches(
    temporary_database: TemporaryDatabase,
) -> None:
    seed(temporary_database)
    with Session(temporary_database.engine) as session:
        batches, reference = current_provenance(session)
        history = get_history(session, HistoryQuery(building_key=KEY, category="cafe"))
        assert reference == date(2026, 11, 10)
        assert [b.source for b in batches] == ["general_restaurant", "rest_cafe"]
        assert history.meta["data_version"]["stores_batch_ids"] == [
            str(b.batch_id) for b in batches
        ]
        assert history.meta["as_of"] == "2026-11-10"
        assert history.data is not None and history.data.total == 3
        assert {s.license_no for s in history.data.stores} == {
            "null-review",
            "false-review",
            "cafe",
        }


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"batch_id": None}, 500),
        ({"batch_id": uuid4()}, 500),
        ({"source": "rest_cafe", "category": "cafe", "sub_category": "cafe"}, 500),
        ({"batch_id": None, "deleted_at": datetime(2026, 11, 11, tzinfo=UTC)}, 200),
        ({"batch_id": None, "category_review_flag": True}, 200),
        ({"batch_id": None, "sub_category": "snack"}, 200),
    ],
)
def test_nullable_or_wrong_source_orphans_keep_safe_failure_policy(
    temporary_database: TemporaryDatabase, changes: dict[str, object], status: int
) -> None:
    seed(temporary_database)
    with Session(temporary_database.engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "orphan", None, **changes)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = temporary_database.engine
    with TestClient(app) as client:
        response = client.get("/api/meta/data-range", params={"category": "restaurant"})
        assert response.status_code == status
        if status == 500:
            body = response.json()
            assert body["data"] is None and body["meta"] == {}
            assert body["error"]["code"] == "INTERNAL_ERROR"
            assert "orphan" not in response.text
            assert response.headers["cache-control"] == "no-store"


def test_actual_service_queries_are_eligible_for_provenance_index(
    temporary_database: TemporaryDatabase,
) -> None:
    seed(temporary_database)
    captured = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "ORDER BY store_import_batches" in statement or statement.startswith("SELECT EXISTS"):
            captured.append((statement, parameters))

    with Session(temporary_database.engine) as session:
        # Eligibility on small data, not a production latency or planner-choice assertion.
        session.execute(text("SET LOCAL enable_seqscan=off"))
        event.listen(temporary_database.engine, "before_cursor_execute", capture)
        try:
            current_provenance(session)
            get_history(session, HistoryQuery(building_key=KEY))
        finally:
            event.remove(temporary_database.engine, "before_cursor_execute", capture)
        assert len(captured) == 3
        for sql, parameters in captured:
            plan = (
                session.connection()
                .exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql, parameters)
                .scalar_one()
            )
            assert "ix_stores_provenance" in json.dumps(plan)


def test_provenance_index_migration_roundtrip_preserves_all_rows(
    temporary_database: TemporaryDatabase,
) -> None:
    seed(temporary_database)
    config = Config(str(ROOT / "alembic.ini"))
    with temporary_database.engine.begin() as connection:
        config.attributes["connection"] = connection
        snapshot = text("SELECT to_jsonb(s) FROM stores s ORDER BY id")
        before = connection.execute(snapshot).scalars().all()
        definition = connection.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_stores_provenance'")
        )
        assert "USING btree (batch_id, source, category, sub_category)" in definition
        assert (
            "deleted_at IS NULL" in definition and "category_review_flag IS NOT TRUE" in definition
        )
        command.downgrade(config, "0009")
        assert connection.scalar(text("SELECT to_regclass('ix_stores_provenance')")) is None
        assert connection.execute(snapshot).scalars().all() == before
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT to_regclass('ix_stores_provenance')")) is not None
        assert connection.execute(snapshot).scalars().all() == before
