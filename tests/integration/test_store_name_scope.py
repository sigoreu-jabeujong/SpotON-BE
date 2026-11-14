"""Shared name policy against real PostGIS; all data is synthetic and isolated."""

import hashlib
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text, update
from sqlalchemy.orm import Session

from app.ai.context import prepare_risk_interpretation
from app.core.config import Settings
from app.main import create_app
from app.models import Store
from app.schemas.risk import RiskQuery
from app.schemas.stores import HistoryQuery
from app.services.risk import get_risk
from app.services.store_cohort import current_provenance, orphan_exists
from app.services.store_scope import (
    NAME_EXCLUSION_KEYWORDS,
    NAME_EXCLUSION_VERSION,
    SUPPORTED_STORES,
    excluded_by_name,
    name_exclusion_meta,
)
from etl.brands.assignment import plan
from etl.brands.catalog import canonical, digest
from tests.etl.brands_helpers import catalog, item
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import PARAMS, batch, store
from tests.integration.test_store_provenance_index import plan_nodes, reference_orphan

pytestmark = pytest.mark.integration
KEY = "마포구-서교동-123-4"


@pytest.fixture
def db(temporary_database):
    migrate(temporary_database)
    return temporary_database.engine


@pytest.fixture
def client(db):
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db
    with TestClient(app) as c:
        yield c


def result(client, path, **params):
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["name_exclusion"] == name_exclusion_meta()
    assert body["meta"]["data_version"]["name_exclusion_version"] == NAME_EXCLUSION_VERSION
    return body


def test_sql_and_python_agree_on_all_keywords_and_boundaries(db):
    names = [
        None,
        "",
        "식당",
        "카페 M",
        "CAFE",
        "cOfFeE",
        "BAKERY",
        "치 킨",
        "ＣＡＦＥ",
        "baKery",
        "치킨",
        *["앞" + word + "뒤" for word in NAME_EXCLUSION_KEYWORDS],
    ]
    with Session(db) as s, s.begin():
        b = batch(s)
        expected = set()
        for category in ("restaurant", "cafe"):
            for n, name in enumerate(names):
                identity = f"{category}-{n}"
                store(
                    s,
                    b,
                    identity,
                    name=name,
                    category=category,
                    sub_category="korean" if category == "restaurant" else "cafe",
                )
                if not excluded_by_name(category, name):
                    expected.add(identity)
        actual = set(s.scalars(select(Store.license_no).where(SUPPORTED_STORES)))
        assert actual == expected


def test_all_lists_aggregates_dates_and_ai_use_same_scope_without_mutating_rows(db, client):
    with Session(db) as s, s.begin():
        older = batch(s, data_updated_at=date(2026, 10, 1))
        newest = batch(s)
        cafe_batch = batch(s, source="rest_cafe")
        for i in range(10):
            store(
                s,
                older,
                f"keep-{i}",
                name=None if i == 0 else "정상식당",
                building_key=KEY,
                open_date=date(2025, 1, 1),
            )
            store(
                s,
                newest,
                f"exclude-{i}",
                name="치킨호프",
                building_key=KEY,
                open_date=date(1990, 1, 1),
            )
        for identity, name in [("closed-keep", "정상식당"), ("closed-drop", "인생주점")]:
            store(
                s,
                newest if identity.endswith("drop") else older,
                identity,
                name=name,
                building_key=KEY,
                status="closed",
                close_date=date(2026, 4, 1),
            )
        store(s, older, "far-keep", 1500, name="정상식당", open_date=date(2025, 1, 1))
        store(s, newest, "far-drop", 1500, name="분식", open_date=date(2025, 1, 1))
        store(s, older, "no-coord-keep", None, name="정상식당", building_key=KEY)
        store(s, newest, "no-coord-drop", None, name="커피", building_key=KEY)
        store(
            s,
            cafe_batch,
            "actual-cafe",
            name="카페 커피",
            category="cafe",
            sub_category="cafe",
            building_key=KEY,
        )
    with db.connect() as c:
        before = c.execute(text("SELECT to_jsonb(s) FROM stores s ORDER BY id")).scalars().all()
    history = result(client, "/api/stores/history", building_key=KEY)
    assert {r["license_no"] for r in history["data"]["stores"]} == {
        *[f"keep-{i}" for i in range(10)],
        "closed-keep",
        "no-coord-keep",
        "actual-cafe",
    }
    nearby = result(client, "/api/stores/nearby", **PARAMS)
    assert {r["license_no"] for r in nearby["data"]["markers"]} == {f"keep-{i}" for i in range(10)}
    assert nearby["data"]["excluded_no_coord"] == 1
    snapshot = result(client, "/api/stores/snapshot", **PARAMS, as_of="2025-01")
    assert {r["license_no"] for r in snapshot["data"]["stores"]} == {
        *[f"keep-{i}" for i in range(10)],
        "closed-keep",
    }
    assert snapshot["data"]["total_at_as_of"] == 11
    activity = result(client, "/api/market/activity", **PARAMS)
    assert sum(r["open_count"] for r in activity["data"]["by_sub_category"]) == 10
    assert activity["data"]["recent_12m"]["closed"] == 1
    risk = result(client, "/api/risk", **PARAMS)
    metrics = {r["id"]: r for r in risk["data"]["indicators"]}
    assert metrics["competitor_count"]["value"] == 10
    assert (
        metrics["closure_rate_12m"]["numerator"],
        metrics["closure_rate_12m"]["denominator"],
    ) == (1, 11)
    assert metrics["closure_rate_12m"]["seoul_avg"] == 8.3  # 1 / (10+1 far+1 closed)
    assert metrics["survival_rate_1y"]["denominator"] == 10
    assert risk["meta"]["excluded_no_coord"] == 1
    dates = result(client, "/api/meta/data-range", category="restaurant")
    assert dates["data"]["min_month"] == "2020-01"  # excluded 1990 record cannot set minimum
    assert dates["data"]["max_date"] == "2026-11-10"
    for response in (nearby, snapshot, activity, risk, dates):
        assert response["meta"]["data_updated_at"] == "2026-11-10"
        assert (
            response["meta"]["data_version"]["stores_batch_ids"]
            == history["meta"]["data_version"]["stores_batch_ids"]
        )
    invalid = client.get("/api/stores/nearby", params={**PARAMS, "as_of": "1995-01"})
    assert invalid.status_code == 422 and invalid.json()["meta"] == {}
    cafe = result(client, "/api/stores/nearby", **{**PARAMS, "category": "cafe"})
    assert cafe["data"]["count"] == 1
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        prepared = prepare_risk_interpretation(
            s,
            RiskQuery(**PARAMS),
            Settings(_env_file=None),
            history=HistoryQuery(building_key=KEY),
        )
        assert sum(g.open_count for g in prepared.context.activity.groups) == 10
        assert (
            "restaurant_name_keywords_may_exclude_valid_stores"
            in prepared.context.methodology.limitations
        )
        assert "치킨호프" not in prepared.request.user_content
        assert '"keywords":' not in prepared.request.user_content
    with db.connect() as c:
        assert (
            c.execute(text("SELECT to_jsonb(s) FROM stores s ORDER BY id")).scalars().all()
            == before
        )


@pytest.mark.parametrize("orphan", [None, "missing-batch", "source-mismatch"])
def test_hidden_name_cannot_hide_broken_provenance(db, client, orphan):
    from uuid import uuid4

    with Session(db) as s, s.begin():
        b = batch(s)
        changes = {"batch_id": None if orphan is None else uuid4()}
        if orphan == "source-mismatch":
            changes = {"source": "rest_cafe"}
        store(s, b, "hidden-orphan", name="치킨", **changes)
    with Session(db) as s:
        assert reference_orphan(s) is True
        assert s.scalar(orphan_exists()) is True
    r = client.get("/api/meta/data-range", params={"category": "restaurant"})
    assert r.status_code == 500 and r.json()["meta"] == {}


def test_all_filtered_newest_batch_keeps_reference_and_brand_input(db, client):
    with Session(db) as s, s.begin():
        old = batch(s, data_updated_at=date(2026, 10, 1))
        latest = batch(s)
        store(s, old, "older", name="일반식당")
        store(s, latest, "newest", name="Unique Cafe", building_key=KEY)
    source = catalog([item("1", "Unique Cafe")])
    with db.connect() as c:
        actual = plan(c, source)
        # Original brand hash independently calculated from all synthetic source rows.
        rows = c.execute(
            select(
                Store.source,
                Store.license_no,
                Store.name,
                Store.category,
                Store.sub_category,
                Store.is_franchise,
                Store.brand_id,
            ).order_by(Store.license_no)
        ).mappings()
        expected = hashlib.sha256(b"store-brand-input-v1\n")
        for row in rows:
            expected.update(digest(canonical(dict(row))).encode("ascii") + b"\n")
        assert actual.input_sha256 == expected.hexdigest() and actual.counts["total"] == 2
    with Session(db) as s:
        batches, reference = current_provenance(s)
        assert len(batches) == 2 and reference == date(2026, 11, 10)
    response = result(client, "/api/stores/history", building_key=KEY)
    assert response["data"]["total"] == 0
    with db.begin() as c:
        c.execute(update(Store).where(Store.license_no == "newest").values(name="정상식당"))
    assert result(client, "/api/stores/history", building_key=KEY)["data"]["total"] == 1
    with db.begin() as c:
        c.execute(update(Store).where(Store.license_no == "newest").values(name="호프"))
    assert result(client, "/api/stores/history", building_key=KEY)["data"]["total"] == 0


def test_operational_index_eligible_with_actual_generic_risk_query(db):
    with db.begin() as c:
        sql = (Path(__file__).parents[2] / "docs/sql/render-free-risk-name-v1.sql").read_text(
            encoding="utf-8"
        )
        c.exec_driver_sql(sql)
    with Session(db) as s, s.begin():
        b = batch(s)
        store(s, b, "kept")
        store(s, b, "excluded", name="치킨")
    captured = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "FILTER (WHERE" in statement and "ST_DWithin" not in statement:
            captured.append((statement, parameters))

    event.listen(db, "before_cursor_execute", capture)
    try:
        with Session(db) as s:
            get_risk(s, RiskQuery(**PARAMS), Settings(_env_file=None))
    finally:
        event.remove(db, "before_cursor_execute", capture)
    assert len(captured) == 1
    sql, params = captured[0]
    # Convert real DBAPI placeholders to PREPARE parameters, preserving static literals.
    keys = list(dict.fromkeys(re.findall(r"%\(([^)]+)\)s", sql)))
    positional = re.sub(r"%\(([^)]+)\)s", lambda m: "$" + str(keys.index(m[1]) + 1), sql)
    with db.connect() as c:
        c.exec_driver_sql("SET LOCAL enable_seqscan=off")
        c.exec_driver_sql("SET LOCAL plan_cache_mode=force_generic_plan")
        c.exec_driver_sql("PREPARE scope_risk AS " + positional)
        from psycopg import sql as pgsql

        execute = pgsql.SQL("EXPLAIN (FORMAT JSON) EXECUTE scope_risk({})").format(
            pgsql.SQL(",").join(pgsql.Literal(params[k]) for k in keys)
        )
        with c.connection.driver_connection.cursor() as cursor:
            cursor.execute(execute)
            explained = cursor.fetchone()[0]
        scans = [n for n in plan_nodes(explained[0]["Plan"]) if n.get("Relation Name") == "stores"]
        assert scans and all(n.get("Index Name") == "ops_free_risk_name_v1" for n in scans)
        assert all("name" not in n.get("Filter", "") for n in scans)
