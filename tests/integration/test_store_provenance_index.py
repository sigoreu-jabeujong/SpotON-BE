"""Provenance query semantics, actual ORM plan eligibility and index-only migration."""

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, exists, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import Store, StoreImportBatch
from app.schemas.stores import HistoryQuery
from app.services.store_cohort import current_provenance, orphan_exists
from app.services.store_history import get_history
from app.services.store_scope import SOURCE_SUPPORTED_STORES
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
        if "ORDER BY store_import_batches" in statement or statement.startswith("WITH RECURSIVE"):
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
        assert sum(sql.startswith("WITH RECURSIVE") for sql, _ in captured) == 1
        for sql, parameters in captured:
            assert "stores.name" not in sql
            plan = (
                session.connection()
                .exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql, parameters)
                .scalar_one()
            )
            stores_scans = [
                n for n in plan_nodes(plan[0]["Plan"]) if n.get("Relation Name") == "stores"
            ]
            assert stores_scans
            assert all(n.get("Index Name") == "ix_stores_provenance" for n in stores_scans)
            if sql.startswith("WITH RECURSIVE"):
                # Three stores scans: first key, LATERAL following key, NULL batch branch.
                assert len(stores_scans) == 3
                assert any(ROW_COMPARISON.search(n.get("Index Cond", "")) for n in stores_scans), (
                    json.dumps(stores_scans)
                )


ROW_COMPARISON = re.compile(r"ROW\((stores\.)?batch_id, (stores\.)?source\) >")


def plan_nodes(node: dict) -> list[dict]:
    found = [node]
    for child in node.get("Plans", []):
        found.extend(plan_nodes(child))
    return found


def reference_orphan(session: Session) -> bool:
    """The pre-#118 anti-join over every supported store, kept as the equivalence oracle."""
    linked = exists(
        select(StoreImportBatch.batch_id)
        .where(StoreImportBatch.batch_id == Store.batch_id, StoreImportBatch.source == Store.source)
        .correlate(Store)
    )
    return bool(
        session.scalar(select(exists(select(Store.id).where(SOURCE_SUPPORTED_STORES, ~linked))))
    )


def registered(session: Session, n: int, source: str = "general_restaurant") -> StoreImportBatch:
    return batch(session, batch_id=UUID(int=n), source=source)


def row(
    session: Session,
    identity: str,
    batch_id: UUID | None,
    source: str = "general_restaurant",
    **changes: object,
) -> None:
    values: dict[str, object] = dict(
        source=source,
        batch_id=batch_id,
        license_no=identity,
        name="synthetic",
        category="cafe" if source == "rest_cafe" else "restaurant",
        sub_category="cafe" if source == "rest_cafe" else "korean",
        open_date=date(2020, 1, 1),
        status="open",
    )
    values.update(changes)
    session.add(Store(**values))
    session.flush()


MAX = 2**128 - 1


def scenario_empty(session: Session) -> None:
    registered(session, 1)


def scenario_all_linked(session: Session) -> None:
    for n in (10, 20, 30):
        registered(session, n)
        row(session, f"linked-{n}", UUID(int=n))
    registered(session, 40, "rest_cafe")
    row(session, "linked-cafe", UUID(int=40), "rest_cafe")


def orphan_at(position: int) -> Callable[[Session], None]:
    def build(session: Session) -> None:
        scenario_all_linked(session)
        row(session, f"orphan-{position}", UUID(int=position))

    return build


def scenario_same_batch_other_source(session: Session) -> None:
    scenario_all_linked(session)
    row(session, "wrong-source", UUID(int=20), "rest_cafe")


def scenario_unsupported_only_then_orphan(session: Session) -> None:
    registered(session, 1)
    row(session, "linked", UUID(int=1))
    registered(session, 5)
    for i in range(20):
        row(session, f"snack-{i}", UUID(int=5), sub_category="snack")
        row(session, f"null-category-{i}", UUID(int=5), category=None, sub_category=None)
    row(session, "orphan-after", UUID(int=6))


def scenario_unsupported_rows_in_unregistered_keys(session: Session) -> None:
    scenario_all_linked(session)
    for i in range(10):
        row(session, f"null-category-{i}", UUID(int=20), category=None, sub_category=None)
        row(session, f"unregistered-snack-{i}", UUID(int=7), sub_category="snack")
        row(session, f"unsupported-source-{i}", UUID(int=8), "unsupported_source")
        row(session, f"deleted-{i}", UUID(int=9), deleted_at=datetime(2026, 11, 11, tzinfo=UTC))
        row(session, f"review-{i}", UUID(int=9), category_review_flag=True)


def scenario_null_batch_unsupported_tail(session: Session) -> None:
    scenario_all_linked(session)
    for i in range(10):
        row(session, f"null-snack-{i}", None, sub_category="snack")
        row(session, f"null-deleted-{i}", None, deleted_at=datetime(2026, 11, 11, tzinfo=UTC))


def scenario_null_batch_supported(session: Session) -> None:
    scenario_null_batch_unsupported_tail(session)
    row(session, "null-supported", None)


def accumulated(orphan: bool) -> Callable[[Session], None]:
    def build(session: Session) -> None:
        for n in range(1, 301):
            registered(session, n)  # fully migrated, empty batches
        for n in range(301, 331):
            registered(session, n)
            row(session, f"residue-{n}", UUID(int=n))
        for n in range(331, 341):
            registered(session, n)
            row(session, f"unsupported-{n}", UUID(int=n), sub_category="snack")
        registered(session, 400)
        for i in range(50):
            row(session, f"current-{i}", UUID(int=400))
        if orphan:
            row(session, "accumulated-orphan", UUID(int=350))

    return build


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (scenario_empty, False),
        (scenario_all_linked, False),
        (orphan_at(0), True),
        (orphan_at(15), True),
        (orphan_at(MAX), True),
        (scenario_same_batch_other_source, True),
        (scenario_unsupported_only_then_orphan, True),
        (scenario_unsupported_rows_in_unregistered_keys, False),
        (scenario_null_batch_unsupported_tail, False),
        (scenario_null_batch_supported, True),
        (accumulated(False), False),
        (accumulated(True), True),
    ],
)
def test_skip_scan_orphan_check_matches_former_anti_join(
    temporary_database: TemporaryDatabase, build: Callable[[Session], None], expected: bool
) -> None:
    migrate(temporary_database)
    with Session(temporary_database.engine) as session, session.begin():
        build(session)
    with Session(temporary_database.engine) as session:
        assert reference_orphan(session) is expected
        assert session.scalar(orphan_exists()) is expected


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
