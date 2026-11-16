from datetime import date

import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer
from sqlalchemy import event, select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import (
    MarketArea,
    MarketAreaVersion,
    MarketSale,
    MarketSaleVersion,
    MarketStoreVersion,
)
from app.schemas.location_reference import Fingerprint, LocationCatalog, SalesCatalog
from app.services import location_reference as service
from etl.market_sales.archive import load_archive
from etl.market_sales.repository import save
from tests.etl.market_sale_helpers import annual_sales_rows, make_sales_zip
from tests.integration.market_references import seed_references
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import batch, store

pytestmark = pytest.mark.integration
PATH = "/api/v2/location-reference"
LNG, LAT = Transformer.from_crs(5181, 4326, always_xy=True).transform(200005, 450005)
PARAMS = dict(lat=LAT, lng=LNG, radius=300, category="cafe", as_of="2023-11")


def fingerprint(version):
    return Fingerprint(**{k: getattr(version, k) for k in Fingerprint.model_fields})


@pytest.fixture
def reference_db(temporary_database, tmp_path, monkeypatch):
    migrate(temporary_database)
    engine = temporary_database.engine
    with engine.begin() as c:
        boundary, stores = seed_references(c, tmp_path)
        name = c.scalar(select(MarketArea.market_name).where(MarketArea.market_code == "3110000"))
    rows = annual_sales_rows()
    for row in rows:
        row["상권_코드_명"] = name
        row["당월_매출_금액"] = "9007199254740993"
    source = tmp_path / "sales.zip"
    sha = make_sales_zip(source, rows)
    archive = load_archive(source, sha, 2025, date(2026, 5, 18), today=date(2026, 11, 16))
    with engine.begin() as c:
        sale_id, _, _ = save(c, archive, boundary, stores)
    with Session(engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "reference-clock", category="cafe", sub_category="cafe")
        catalog = LocationCatalog(
            sales=SalesCatalog(
                source_year=2025,
                sales=fingerprint(session.get(MarketSaleVersion, sale_id)),
                boundary=fingerprint(session.get(MarketAreaVersion, boundary)),
                stores=fingerprint(session.get(MarketStoreVersion, stores)),
            )
        )
    monkeypatch.setattr(service, "load_catalog", lambda: catalog)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    with TestClient(app) as client:
        yield engine, client, catalog, sale_id


def request(client, **changes):
    r = client.get(PATH, params=PARAMS | changes)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def test_postgis_real_source_values_and_relations_are_separate_from_historical_analysis(
    reference_db,
):
    engine, client, _, _ = reference_db
    statements = []

    def observe(_c, _cursor, statement, _p, _ctx, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        body = request(client)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    data = body["data"]
    assert data["analysis_as_of"] == "2023-11-30"
    item = next(i for i in data["sales"]["items"] if i["market_code"] == "3110000")
    assert item["metric"]["value"] == "9007199254740993"
    assert item["source_quarter"] == "20254" and item["temporal_relation"] == "later_reference"
    assert item["period_end_after_analysis"] is True
    assert item["spatial_relation"] == "contains_point"
    assert item["amount_period_status"] == "unverified"
    codes = [i["market_code"] for i in data["sales"]["items"]]
    assert len(codes) == len(set(codes))
    assert any(i["spatial_relation"] == "intersects_radius" for i in data["sales"]["items"])
    assert data["living_population"]["reason"] == "population_source_not_released"
    assert data["day_night"]["reason"] == "population_source_not_released"
    assert not any("admin_population" in s or "admin_areas" in s for s in statements)
    assert body["meta"]["source_refs"][0]["id"] == item["provenance_ref"]
    assert body["meta"]["global_content_rechecked"] is False
    assert not any(key in body["meta"]["requested_scope"] for key in ("lat", "lng", "brand_scope"))
    assert (
        request(client)["meta"]["reference_snapshot_token"]
        == body["meta"]["reference_snapshot_token"]
    )


def test_strict_quarter_missing_rows_and_outside_geometry_never_use_similar_area(reference_db):
    _, client, _, _ = reference_db
    strict = request(client, time_mode="analysis_period")
    assert strict["data"]["sales"]["status"] == "no_data"
    assert strict["data"]["sales"]["reason"] == "no_data_in_analysis_period"
    assert all(i["metric"] is None for i in strict["data"]["sales"]["items"])
    outside = request(client, lat=0, lng=0)
    assert outside["data"]["sales"]["reason"] == "no_spatial_overlap"
    assert outside["data"]["sales"]["items"] == []


def test_latest_valid_row_skips_null_and_preserves_exact_zero(reference_db):
    engine, client, _, vid = reference_db
    with engine.begin() as c:
        c.execute(
            update(MarketSale)
            .where(MarketSale.version_id == vid, MarketSale.quarter == "20254")
            .values(est_sales=None)
        )
        c.execute(
            update(MarketSale)
            .where(MarketSale.version_id == vid, MarketSale.quarter == "20253")
            .values(est_sales=0)
        )
    item = next(i for i in request(client)["data"]["sales"]["items"] if i["metric"])
    assert item["source_quarter"] == "20253"
    assert item["metric"] == {
        "value": "0",
        "display": "0원",
        "unit": "KRW_source_reported",
        "rounded": False,
        "exact_zero": True,
    }


def test_caps_missing_catalog_and_metadata_inconsistency_are_distinct(reference_db, monkeypatch):
    engine, client, catalog, vid = reference_db
    monkeypatch.setattr(service, "MAX_MARKETS", 0)
    assert request(client)["data"]["sales"]["reason"] == "scope_too_large"
    monkeypatch.setattr(service, "MAX_MARKETS", 100)
    monkeypatch.setattr(service, "load_catalog", lambda: LocationCatalog())
    assert request(client)["data"]["sales"]["reason"] == "source_not_loaded"
    monkeypatch.setattr(service, "load_catalog", lambda: catalog)
    with engine.begin() as c:
        c.execute(
            update(MarketSaleVersion)
            .where(MarketSaleVersion.version_id == vid)
            .values(row_count=21, source_rows=21)
        )
    response = client.get(PATH, params=PARAMS)
    assert response.status_code == 500 and response.headers["cache-control"] == "no-store"
    assert "inconsistent reference" not in response.text


def test_same_rr_database_session_and_geometry_only_radius(reference_db, monkeypatch):
    engine, client, _, _ = reference_db
    original = service._sales

    def check(session, *args):
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        return original(session, *args)

    monkeypatch.setattr(service, "_sales", check)
    # A point just outside the tiny first polygon still selects it by polygon distance.
    lng, lat = Transformer.from_crs(5181, 4326, always_xy=True).transform(199999, 450005)
    items = request(client, lng=lng, lat=lat)["data"]["sales"]["items"]
    assert (
        next(i for i in items if i["market_code"] == "3110000")["spatial_relation"]
        == "intersects_radius"
    )
