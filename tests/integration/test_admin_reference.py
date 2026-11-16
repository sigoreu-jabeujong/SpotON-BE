"""Real PostGIS, immutable imports and location/date scoped administrative references."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pyproj import Transformer
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.admin_population import AdminArea as A
from app.models.admin_population import AdminPopulationHour as H
from app.models.admin_population import AdminPopulationVersion as V
from app.schemas.location_reference import LocationCatalog
from app.services import admin_reference, location_reference
from etl.admin_population.data import digest, population_digest, prepare
from etl.admin_population.repository import save
from etl.admin_population.runner import catalog
from tests.etl.admin_population_helpers import boundary_zip, population_zip
from tests.integration.test_localdata_upsert import ROOT, migrate
from tests.integration.test_nearby import batch, store

pytestmark = pytest.mark.integration
DAY = date(2026, 10, 31)
LNG, LAT = Transformer.from_crs(5181, 4326, always_xy=True).transform(200005, 450005)
PARAMS = dict(lat=LAT, lng=LNG, radius=300, category="cafe", as_of="2023-11")


@pytest.fixture
def admin_db(temporary_database, tmp_path, monkeypatch):
    migrate(temporary_database)
    engine = temporary_database.engine
    pop, boundary = tmp_path / "p.zip", tmp_path / "b.zip"
    psha, bsha = population_zip(pop), boundary_zip(boundary)
    data = prepare(pop, psha, boundary, bsha, DAY)
    with engine.begin() as c:
        saved = save(c, data)
        fp = catalog(c, saved)
    with Session(engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "admin-clock", category="cafe", sub_category="cafe")
    monkeypatch.setattr(location_reference, "load_catalog", lambda: LocationCatalog(population=fp))
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    with TestClient(app) as client:
        yield engine, client, data, saved


def request(client, **changes):
    response = client.get("/api/v2/location-reference", params=PARAMS | changes)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_actual_source_numbers_and_same_admin_day_are_used(admin_db):
    engine, client, data, saved = admin_db
    body = request(client)
    assert body["data"]["analysis_as_of"] == "2023-11-30"
    item = body["data"]["living_population"]["items"][0]
    comparison = body["data"]["day_night"]["items"][0]
    assert item["observation_date"] == "2026-10-31"
    assert item["temporal_relation"] == "later_reference"
    assert item["spatial_relation"] == "contains_point"
    assert item["population_scope"] == "local"
    assert Decimal(item["mean_24h"]["value"]) == Decimal("12.34")
    assert item["mean_24h"]["display"] == "12.3명"
    assert item["observed_hours"] == item["source_hours"] == 24
    assert item["area_ref"] == comparison["area_ref"]
    assert item["provenance_ref"] == comparison["provenance_ref"]
    assert comparison["day_night_ratio"]["display"] == "1.00000"
    assert comparison["day_share_pct"]["display"] == "50.0%"
    assert body["meta"]["source_refs"][0]["excluded_rows"] == 24
    assert body["meta"]["population_total_validated"] is False
    with engine.begin() as c:
        assert save(c, data).reused
        assert c.scalar(select(text("count(*)")).select_from(H)) == 24
        assert c.scalar(select(V.excluded_rows).where(V.version_id == saved.population_id)) == 24
    assert (
        request(client)["meta"]["reference_snapshot_token"]
        == body["meta"]["reference_snapshot_token"]
    )


def test_strict_month_and_spatial_absence_never_use_disjoint_or_newer_sources(admin_db):
    _, client, _, _ = admin_db
    for month in ("2023-11", "2026-09", "2026-11"):
        result = request(client, time_mode="analysis_period", as_of=month)
        assert result["data"]["living_population"]["reason"] == "no_data_in_analysis_period"
    exact = request(client, time_mode="analysis_period", as_of="2026-10")
    assert exact["data"]["living_population"]["status"] == "ready"
    outside = request(client, lat=0, lng=0)
    assert outside["data"]["living_population"]["items"] == []
    assert outside["data"]["living_population"]["reason"] == "no_spatial_overlap"


@pytest.mark.parametrize("status", ["suppressed", "missing", "absent"])
def test_missing_or_masked_hour_is_never_zero_or_partial_hour_mean(admin_db, status):
    engine, client, _, saved = admin_db
    with engine.begin() as c:
        if status == "absent":
            c.execute(H.__table__.delete().where(H.version_id == saved.population_id, H.hour == 0))
            # Catalog row counts intentionally stay immutable: a physical row removal is corruption.
        else:
            c.execute(
                update(H)
                .where(H.version_id == saved.population_id, H.hour == 0)
                .values(population=None, value_status=status)
            )
    if status == "absent":
        assert client.get("/api/v2/location-reference", params=PARAMS).status_code == 500
        return
    data = request(client)["data"]
    assert data["living_population"]["status"] == "no_data"
    assert data["living_population"]["items"][0]["mean_24h"] is None
    assert data["day_night"]["items"][0]["mean_day"] is None


@pytest.mark.parametrize("all_zero", [True, False])
def test_zero_night_and_zero_total_keep_valid_means_without_ratio(admin_db, all_zero):
    engine, client, _, saved = admin_db
    with engine.begin() as c:
        c.execute(
            update(H)
            .where(
                H.version_id == saved.population_id,
                H.hour.in_(list(range(24)) if all_zero else [*range(6), *range(18, 24)]),
            )
            .values(population=Decimal(0))
        )
    data = request(client)["data"]
    assert data["living_population"]["status"] == "ready"
    assert data["day_night"]["status"] == "partial"
    comp = data["day_night"]["items"][0]
    assert comp["mean_night"]["exact_zero"] is True
    assert comp["day_night_ratio"]["value"] is None
    assert comp["day_night_ratio"]["reason"] == "zero_night_population"
    if all_zero:
        assert comp["day_share_pct"]["reason"] == "zero_population_total"
    else:
        assert comp["night_share_pct"]["exact_zero"] is True
        assert comp["night_share_pct"]["rounded"] is False
        assert comp["night_share_pct"]["display"] == "0.0%"


def test_intersecting_area_is_labeled_and_never_area_weighted(admin_db):
    _, client, _, _ = admin_db
    lng, lat = Transformer.from_crs(5181, 4326, always_xy=True).transform(200100, 450005)
    item = request(client, lat=lat, lng=lng)["data"]["living_population"]["items"][0]
    assert item["spatial_relation"] == "intersects_radius"
    assert Decimal(item["mean_24h"]["value"]) == Decimal("12.34")


def test_import_is_atomic_replay_detects_drift_and_fk_preserves_identity(admin_db):
    engine, _, data, saved = admin_db
    with pytest.raises(ValueError, match="observation_drift"), engine.begin() as c:
        c.execute(update(H).where(H.hour == 0).values(population=Decimal(3)))
        save(c, data)
    with engine.begin() as c:
        assert save(c, data).reused
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(update(H).where(H.hour == 0).values(admin_code="11119999"))
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(update(H).where(H.hour == 0).values(value_status="suppressed"))
    rows = [dict(r) for r in data.rows]
    rows[0]["observation_date"] = date(2026, 10, 30)
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(update(H).where(H.hour == 0).values(observation_date=date(2026, 10, 30)))
    with engine.begin() as c:
        assert (
            c.scalar(select(A.admin_code).where(A.boundary_version_id == saved.boundary_id))
            == "11110530"
        )


def test_limits_and_metadata_drift_fail_explicitly(admin_db, monkeypatch):
    engine, client, _, saved = admin_db
    monkeypatch.setattr(admin_reference, "MAX_AREAS", 0)
    assert request(client)["data"]["living_population"]["reason"] == "scope_too_large"
    monkeypatch.setattr(admin_reference, "MAX_AREAS", 50)
    monkeypatch.setattr(admin_reference, "MAX_HOURS", 0)
    assert request(client)["data"]["living_population"]["reason"] == "scope_too_large"
    monkeypatch.setattr(admin_reference, "MAX_HOURS", 50_000)
    with engine.begin() as c:
        c.execute(
            update(V).where(V.version_id == saved.population_id).values(content_sha256="f" * 64)
        )
    response = client.get("/api/v2/location-reference", params=PARAMS)
    assert response.status_code == 500
    assert "admin population" not in response.text


def test_downgrade_drops_only_four_new_tables_and_reupgrade_works(admin_db):
    engine, _, _, _ = admin_db
    cfg = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as c:
        count = c.scalar(text("select count(*) from stores"))
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0012")
        assert c.scalar(text("select count(*) from stores")) == count
        assert c.scalar(text("select to_regclass('admin_population_hours')")) is None
        command.upgrade(cfg, "head")
        assert c.scalar(text("select version_num from alembic_version")) == "0013"
        assert c.scalar(text("select count(*) from admin_population_hours")) == 0


@pytest.mark.parametrize("missing_containing", [False, True])
def test_shared_boundary_and_missing_containing_area_remain_separate(
    admin_db, monkeypatch, missing_containing
):
    import json

    engine, client, original, _ = admin_db
    areas = []
    for code, left in (("11110530", 200000), ("11110540", 200010)):
        geom = {
            "type": "Polygon",
            "coordinates": [
                [
                    [left, 450000],
                    [left, 450010],
                    [left + 10, 450010],
                    [left + 10, 450000],
                    [left, 450000],
                ]
            ],
        }
        areas.append(
            dict(
                admin_code=code,
                admin_name="합성동" + code[-2:],
                geometry_json=json.dumps(geom),
                source_feature_sha256=digest(geom),
            )
        )
    rows = [
        dict(
            r,
            admin_code=code,
            population=Decimal("20.00") if code.endswith("40") else r["population"],
        )
        for code in ("11110530", "11110540")
        for r in original.rows
        if not (missing_containing and code.endswith("30"))
    ]
    data = replace(
        original,
        boundary_input="c" * 64,
        boundary_content=digest(areas),
        areas=tuple(areas),
        rows=tuple(rows),
        excluded=(),
        source_rows=len(rows),
        population_content=population_digest(rows),
        boundary_without_observations=int(missing_containing),
        unmatched_code_count=0,
    )
    with engine.begin() as c:
        saved = save(c, data)
        fp = catalog(c, saved)
    monkeypatch.setattr(location_reference, "load_catalog", lambda: LocationCatalog(population=fp))
    if missing_containing:
        items = request(client)["data"]["living_population"]["items"]
        assert [(i["spatial_relation"], i["status"]) for i in items] == [
            ("contains_point", "no_data"),
            ("intersects_radius", "ready"),
        ]
        assert items[0]["reason"] == "no_source_rows" and items[0]["mean_24h"] is None
        assert Decimal(items[1]["mean_24h"]["value"]) == Decimal("20")
    else:
        lng, lat = Transformer.from_crs(5181, 4326, always_xy=True).transform(200010, 450000)
        items = request(client, lat=lat, lng=lng)["data"]["living_population"]["items"]
        assert len(items) == 2
        assert all(i["spatial_relation"] == "contains_point" for i in items)
        assert [i["area_name"] for i in items] == ["합성동30", "합성동40"]
        assert [Decimal(i["mean_24h"]["value"]) for i in items] == [Decimal("12.34"), Decimal("20")]


def test_future_month_is_rejected_without_moving_to_available_month(admin_db):
    engine, client, _, _ = admin_db
    with engine.begin() as c:
        c.execute(text("UPDATE store_import_batches SET data_updated_at='2026-10-31'"))
    response = client.get(
        "/api/v2/location-reference",
        params=PARAMS | {"as_of": "2026-11", "time_mode": "analysis_period"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"


@pytest.mark.parametrize(
    "day,night,side",
    [
        ("1", "2", "day"),
        ("0.00001", "1", "day"),
        ("1", "0.00001", "night"),
        ("0.00001", "999999999999999.99999", "day"),
    ],
)
def test_share_preserves_unrounded_value_and_distinguishes_rounded_zero(admin_db, day, night, side):
    engine, client, _, _ = admin_db
    with engine.begin() as c:
        c.execute(update(H).values(population=Decimal(night)))
        c.execute(update(H).where(H.hour.between(6, 17)).values(population=Decimal(day)))
    value = request(client)["data"]["day_night"]["items"][0][side + "_share_pct"]
    assert value["rounded"] is True and value["exact_zero"] is False
    assert Decimal(value["value"]) > 0
    if day == "1" and night == "2":
        assert value["display"] == "33.3%" and Decimal(value["value"]) > Decimal("33.3")
    else:
        assert value["display"] == "0.0%"
