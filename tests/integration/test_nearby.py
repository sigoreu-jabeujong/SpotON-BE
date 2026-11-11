"""Real PostGIS contracts; fixtures create and destroy only isolated test databases."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import product
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import Store, StoreImportBatch
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration
LAT, LNG = 37.5665, 126.978
PARAMS = {"lat": LAT, "lng": LNG, "category": "restaurant"}


@pytest.fixture
def nearby_database(temporary_database: TemporaryDatabase) -> TemporaryDatabase:
    migrate(temporary_database)
    return temporary_database


def batch(session: Session, **changes: object) -> StoreImportBatch:
    values = dict(
        batch_id=uuid4(),
        source="general_restaurant",
        data_updated_at=date(2026, 11, 10),
        recorded_at=datetime(2026, 11, 12, tzinfo=UTC),
        collection_basis="synthetic_test",
        input_kind="csv",
        rows_sha256="0" * 64,
        row_count=1,
        map_version="test-v1",
        rule_version="test-v1",
    )
    values.update(changes)
    result = StoreImportBatch(**values)
    session.add(result)
    session.flush()
    return result


def store(
    session: Session,
    provenance: StoreImportBatch,
    identity: str,
    distance: float | None = 100,
    **changes: object,
) -> Store:
    values = dict(
        source=provenance.source,
        batch_id=provenance.batch_id,
        license_no=identity,
        name="synthetic",
        category="restaurant",
        sub_category="korean",
        open_date=date(2020, 1, 1),
        status="open",
        area_m2=Decimal("33"),
        is_franchise=False,
    )
    values.update(changes)
    result = Store(**values)
    session.add(result)
    session.flush()
    if distance is not None:
        session.execute(
            text("""
            UPDATE stores SET geom = ST_Project(
              ST_SetSRID(ST_MakePoint(:lng, :lat),4326)::geography,
              :distance, radians(90))::geometry WHERE id=:id
        """),
            {"lat": LAT, "lng": LNG, "distance": distance, "id": result.id},
        )
    return result


@pytest.fixture
def nearby_client(nearby_database: TemporaryDatabase) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = nearby_database.engine
    with TestClient(app) as client:
        yield client


def payload(client: TestClient, **changes: object) -> dict:
    response = client.get("/api/stores/nearby", params={**PARAMS, **changes})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def identities(result: dict) -> set[str]:
    return {m["license_no"] for m in result["data"]["markers"]}


def test_distance_boundary_sort_and_latest_period(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
) -> None:
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        for identity, distance in [
            ("inside", 499),
            ("boundary", 500),
            ("outside", 501),
            ("epsilon-outside", 500.001),
            ("z-nearer", 100.01),
            ("a-farther", 100.04),
            ("round-inside", 499.96),
        ]:
            store(session, provenance, identity, distance, name=None)
    result = payload(nearby_client)
    markers = result["data"]["markers"]
    assert [m["license_no"] for m in markers] == [
        "z-nearer",
        "a-farther",
        "inside",
        "round-inside",
        "boundary",
    ]
    assert [m["distance_m"] for m in markers] == [100, 100, 499, 500, 500]
    assert result["data"]["count"] == len(markers) == 5
    assert markers[0]["name"] is None
    assert markers[0]["operating_months"] == 82
    assert markers[0]["operating_period_status"] == "fact"
    assert markers[0]["lat"] != 0 and markers[0]["lng"] != 0
    historical = payload(nearby_client, as_of="2021-02")
    assert historical["data"]["as_of"] == "2021-02-28"
    assert historical["data"]["markers"][0]["operating_months"] == 82
    assert result["meta"]["operating_period_basis"] == "latest_data"
    assert result["meta"]["collected_at"] is None


def test_temporal_quality_and_closure_day(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
) -> None:
    cases = {
        "good": {},
        "closed": {"status": "closed", "close_date": date(2021, 2, 28)},
        "closes-next": {"status": "closed", "close_date": date(2021, 3, 1)},
        "opens-last": {"open_date": date(2021, 2, 28)},
        "opens-next": {"open_date": date(2021, 3, 1)},
        "other": {"status": "other"},
        "other-closed": {"status": "other", "close_date": date(2021, 3, 1)},
        "unknown-status": {"status": None},
        "missing-open": {"open_date": None},
        "old": {"open_date": date(1959, 12, 31)},
        "future-open": {"open_date": date(2026, 11, 11)},
        "inverted": {"status": "closed", "close_date": date(2019, 1, 1)},
        "future-close": {"status": "closed", "close_date": date(2026, 11, 11)},
        "missing-close": {"status": "closed"},
        "open-with-close": {"close_date": date(2021, 1, 1)},
        "temporary": {"is_temporary": True},
        "review": {"category_review_flag": True},
        "deleted": {"deleted_at": datetime.now(UTC)},
        "unsupported": {"sub_category": "snack"},
    }
    flags = [
        "open_before_1960",
        "open_date_invalid",
        "close_date_invalid",
        "close_before_open",
        "open_date_future",
        "close_date_future",
        "new_unknown_flag",
        "open_date_invalid;close_date_invalid",
    ]
    cases.update({f"flag-{index}": {"date_flag": flag} for index, flag in enumerate(flags)})
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        for identity, changes in cases.items():
            store(session, provenance, identity, **changes)
    february = payload(nearby_client, as_of="2021-02")
    assert identities(february) == {
        "good",
        "opens-last",
        "other",
        "unknown-status",
        "closes-next",
        "other-closed",
    }
    january = payload(nearby_client, as_of="2021-01")
    assert identities(january) == {
        "good",
        "closed",
        "other",
        "unknown-status",
        "closes-next",
        "other-closed",
    }
    closed = next(m for m in january["data"]["markers"] if m["license_no"] == "closed")
    assert closed["current_status"] == "closed" and closed["operating_months"] == 13
    other = next(m for m in february["data"]["markers"] if m["license_no"] == "other")
    assert other["operating_months"] is None and other["operating_period_reason"] == "other_status"


def test_supported_subcategories_and_all_radius_choices(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
) -> None:
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        for sub, distance in [
            ("korean", 250),
            ("chinese", 400),
            ("japanese", 750),
            ("western", 1100),
        ]:
            store(session, provenance, sub, distance, sub_category=sub)
    assert identities(payload(nearby_client, radius=300)) == {"korean"}
    assert identities(payload(nearby_client, radius=500)) == {"korean", "chinese"}
    assert identities(payload(nearby_client, radius=1000)) == {"korean", "chinese", "japanese"}
    assert identities(payload(nearby_client, radius=1000, sub_category="chinese,japanese")) == {
        "chinese",
        "japanese",
    }


def test_area_franchise_unknown_axes_and_zero_preservation(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
) -> None:
    areas = [None, Decimal("0"), Decimal("32.99"), Decimal("33"), Decimal("66"), Decimal("99")]
    franchises = [None, False, True]
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        for i, j in product(range(6), range(3)):
            store(session, provenance, f"{i}-{j}", area_m2=areas[i], is_franchise=franchises[j])
    for area_name, selected in [
        ("all", {2, 3, 4, 5}),
        ("lt33", {2}),
        ("33to66", {3}),
        ("66to99", {4}),
        ("gte99", {5}),
    ]:
        for unknown_area, unknown_franchise in product([False, True], repeat=2):
            result = payload(
                nearby_client,
                area=area_name,
                franchise="franchise",
                include_unknown_area=str(unknown_area).lower(),
                include_unknown_franchise=str(unknown_franchise).lower(),
            )
            expected_areas = selected | ({0, 1} if unknown_area else set())
            expected_franchises = {2} | ({0} if unknown_franchise else set())
            assert identities(result) == {
                f"{i}-{j}" for i, j in product(expected_areas, expected_franchises)
            }
            for marker in result["data"]["markers"]:
                if marker["license_no"].startswith(("0-", "1-")):
                    assert marker["area_m2"] is None
                if marker["license_no"].endswith("-0"):
                    assert marker["franchise"] == "unknown"
    legacy = payload(nearby_client, include_unknown="false")
    assert len(identities(legacy)) == 8
    independent = payload(nearby_client, franchise="independent", include_unknown="false")
    assert identities(independent) == {f"{i}-1" for i in [2, 3, 4, 5]}
    with Session(nearby_database.engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(Store).where(Store.area_m2 == 0)) == 3
        )


def test_no_coord_scope_is_nonspatial_and_uses_same_filters(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
) -> None:
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "visible")
        store(session, provenance, "unknown-area", None, area_m2=0)
        store(session, provenance, "known-area", None, area_m2=33)
        store(session, provenance, "wrong-time", None, open_date=date(2022, 1, 1))
        store(session, provenance, "temporary", None, is_temporary=True)
    result = payload(nearby_client, as_of="2021-02")
    far_away = payload(nearby_client, lat=0, lng=0, radius=1000, as_of="2021-02")
    assert result["data"]["excluded_no_coord"] == far_away["data"]["excluded_no_coord"] == 2
    assert far_away["data"]["count"] == 0 and far_away["data"]["message"]
    assert result["meta"]["excluded_no_coord_scope"] == "seoul_nonspatial_cohort"
    known = payload(nearby_client, as_of="2021-02", include_unknown_area="false")
    assert known["data"]["excluded_no_coord"] == 1


def test_global_reference_category_minimum_and_empty_cohort(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
) -> None:
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "restaurant", open_date=date(2020, 5, 20))
        cafe = batch(session, source="rest_cafe", data_updated_at=date(2026, 11, 7))
        store(
            session, cafe, "cafe", category="cafe", sub_category="cafe", open_date=date(2023, 1, 1)
        )
    result = payload(nearby_client, category="cafe")
    assert result["meta"]["data_updated_at"] == result["data"]["as_of"] == "2026-11-10"
    assert len(result["meta"]["data_version"]["stores_batch_ids"]) == 2
    for month in ["2019-12", "2026-12"]:
        response = nearby_client.get("/api/stores/nearby", params={**PARAMS, "as_of": month})
        assert (
            response.status_code == 422 and response.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"
        )
    empty = payload(nearby_client, sub_category="western")
    assert empty["data"]["count"] == 0
    old_empty = nearby_client.get(
        "/api/stores/nearby", params={**PARAMS, "sub_category": "western", "as_of": "2020-05"}
    )
    assert old_empty.status_code == 422
    # Attribute filters cannot narrow the category's valid temporal bounds.
    assert (
        payload(nearby_client, as_of="2020-05", area="gte99", include_unknown="false")["data"][
            "count"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "problem", ["empty", "unlinked", "wrong-source", "no-date", "bad-date", "future-date"]
)
def test_global_provenance_failure_is_not_partial_success(
    nearby_database: TemporaryDatabase,
    nearby_client: TestClient,
    problem: str,
) -> None:
    if problem != "empty":
        with Session(nearby_database.engine) as session, session.begin():
            provenance = batch(session)
            store(session, provenance, "good")
            bad = batch(session, source="rest_cafe")
            store(session, bad, "bad", category="cafe", sub_category="cafe")
            if problem == "unlinked":
                session.delete(bad)
            elif problem == "wrong-source":
                bad.source = "general_restaurant"
            elif problem == "no-date":
                bad.data_updated_at = None
            elif problem == "bad-date":
                bad.update_reason = "unparseable_update_point"
            elif problem == "future-date":
                bad.data_updated_at = date(2099, 1, 1)
    response = nearby_client.get("/api/stores/nearby", params=PARAMS)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["meta"] == {} and "bad" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_multidirection_candidate_has_no_false_negatives_and_exact_final_boundary(
    nearby_database: TemporaryDatabase,
) -> None:
    # 5 centers x 3 radii x 24 bearings x 4 offsets, including the exact boundary.
    with nearby_database.engine.connect() as connection:
        result = connection.execute(
            text("""
          WITH points AS (
            SELECT ST_SetSRID(ST_MakePoint(lng,lat),4326)::geography p
            FROM (VALUES (126.978,37.5665),(126.8,37.5),(127.1,37.6),
                         (126.95,37.45),(127.05,37.65)) c(lng,lat)
          ), cases AS (
            SELECT p,r,ST_Project(p,r+delta,radians(bearing)) q
            FROM points CROSS JOIN (VALUES (300),(500),(1000)) rs(r)
            CROSS JOIN generate_series(0,345,15) bearing
            CROSS JOIN (VALUES (-1.0),(0.0),(0.001),(1.0)) offsets(delta)
          ) SELECT count(*) total,
            count(*) FILTER (WHERE ST_Distance(q,p,true)<=r
                            AND NOT ST_DWithin(q,p,r+0.01,true)) missed,
            count(*) FILTER (WHERE ST_DWithin(q,p,r+0.01,true) AND ST_Distance(q,p,true)>r) extras
          FROM cases
        """)
        ).one()
        assert result.total == 1440 and result.missed == 0 and result.extras > 0


def test_expression_index_plan_and_downgrade_preserve_data(
    nearby_database: TemporaryDatabase,
) -> None:
    with Session(nearby_database.engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "preserved")
    config = Config(str(ROOT / "alembic.ini"))
    with nearby_database.engine.begin() as connection:
        before = connection.execute(text("SELECT id, ST_AsEWKB(geom), batch_id FROM stores")).all()
        definition = connection.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_stores_geography_gist'")
        )
        assert (
            "USING gist (((geom)::geography))" in definition
            and "WHERE (geom IS NOT NULL)" in definition
        )
        # Small synthetic table: force planner solely to verify expression eligibility,
        # not to claim representative production performance.
        connection.execute(text("SET LOCAL enable_seqscan=off"))
        plan = connection.scalar(
            text("""
          EXPLAIN (FORMAT JSON) SELECT id FROM stores WHERE geom IS NOT NULL
          AND ST_DWithin(geom::geography,
              ST_SetSRID(ST_MakePoint(126.978,37.5665),4326)::geography,500.01,true)
          AND ST_Distance(geom::geography,
              ST_SetSRID(ST_MakePoint(126.978,37.5665),4326)::geography,true)<=500
        """)
        )
        assert "ix_stores_geography_gist" in str(plan)
        assert "_st_expand" in str(plan) and "Index Cond" in str(plan)
        config.attributes["connection"] = connection
        command.downgrade(config, "0003")
        assert connection.scalar(text("SELECT to_regclass('ix_stores_geography_gist')")) is None
        assert (
            connection.execute(text("SELECT id, ST_AsEWKB(geom), batch_id FROM stores")).all()
            == before
        )
        assert connection.scalar(select(func.count()).select_from(StoreImportBatch)) == 1
        command.upgrade(config, "head")
        assert (
            connection.execute(text("SELECT id, ST_AsEWKB(geom), batch_id FROM stores")).all()
            == before
        )
