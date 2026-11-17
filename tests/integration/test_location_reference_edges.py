from uuid import uuid4

from pyproj import Transformer
from sqlalchemy import delete, insert, inspect, select, text, update

from app.models import MarketAreaVersion, MarketSale
from app.services import location_reference as service
from tests.integration.test_location_reference import PARAMS, PATH, reference_db, request

# Importing the fixture also makes this independent module discoverable by pytest.
__all__ = ["reference_db"]
import pytest

pytestmark = pytest.mark.integration


def only_first_market(monkeypatch):
    original = service._candidates
    monkeypatch.setattr(
        service, "_candidates", lambda *args: [r for r in original(*args) if r.code == "3110000"]
    )


def test_null_value_and_absent_row_have_distinct_reasons(reference_db, monkeypatch):
    engine, client, _, vid = reference_db
    only_first_market(monkeypatch)
    with engine.begin() as c:
        c.execute(update(MarketSale).where(MarketSale.version_id == vid).values(est_sales=None))
    null_result = request(client)["data"]["sales"]
    assert null_result["reason"] == "source_value_null"
    assert null_result["reason_counts"] == {"source_value_null": 1}
    with engine.begin() as c:
        c.execute(
            update(MarketSale)
            .where(MarketSale.version_id == vid, MarketSale.induty_cd == "CS100010")
            .values(market_code="3110004")
        )
    absent = request(client)["data"]["sales"]
    assert absent["reason"] == "no_source_rows"
    assert absent["reason_counts"] == {"no_source_rows": 1}


def test_latest_conflict_preserves_older_matching_value_and_all_conflicts_have_reason(
    reference_db, monkeypatch
):
    engine, client, _, vid = reference_db
    only_first_market(monkeypatch)
    with engine.begin() as c:
        c.execute(
            update(MarketSale)
            .where(MarketSale.version_id == vid, MarketSale.quarter == "20254")
            .values(market_name="synthetic-conflicting-name")
        )
    sales = request(client)["data"]["sales"]
    assert sales["items"][0]["source_quarter"] == "20253"
    assert sales["items"][0]["excluded_source_rows"] == 1
    assert sales["status"] == "partial" and sales["excluded_counts"] == {"mapping_conflict": 1}
    with engine.begin() as c:
        c.execute(
            update(MarketSale)
            .where(MarketSale.version_id == vid)
            .values(market_name="synthetic-conflicting-name")
        )
    conflict = request(client)["data"]["sales"]
    assert conflict["reason"] == "mapping_conflict"
    assert conflict["reason_counts"] == {"mapping_conflict": 1}
    assert conflict["items"][0]["metric"] is None


def test_missing_real_row_with_unchanged_manifest_is_internal_error(reference_db):
    engine, client, _, vid = reference_db
    with engine.begin() as c:
        c.execute(
            delete(MarketSale).where(
                MarketSale.version_id == vid,
                MarketSale.quarter == "20251",
                MarketSale.induty_cd == "CS100010",
            )
        )
    response = client.get(PATH, params=PARAMS)
    assert response.status_code == 500 and response.headers["cache-control"] == "no-store"


def test_ambiguous_identity_does_not_select_arbitrary_uuid(reference_db):
    engine, client, _, _ = reference_db
    # This corruption is confined to a disposable DB, removed by the fixture.
    with engine.begin() as c:
        assert set(inspect(c).get_pk_constraint("market_sales")["constrained_columns"]) == {
            "version_id",
            "market_code",
            "quarter",
            "induty_cd",
        }
        c.exec_driver_sql(
            "ALTER TABLE market_area_versions DROP CONSTRAINT uq_market_area_versions_input_rule"
        )
        row = dict(c.execute(select(MarketAreaVersion.__table__)).mappings().one())
        row["version_id"] = uuid4()
        c.execute(insert(MarketAreaVersion).values(**row))
    result = request(client)["data"]["sales"]
    assert result["status"] == "pending" and result["reason"] == "ambiguous_source_version"


def test_overlapping_polygons_and_a_hole_keep_correct_relations(reference_db):
    engine, client, _, _ = reference_db
    outer = "200000 450000,200000 450020,200020 450020,200020 450000,200000 450000"
    hole = "200004 450004,200008 450004,200008 450008,200004 450008,200004 450004"
    with engine.begin() as c:
        for code, rings in (("3110000", f"({outer}),({hole})"), ("3110001", f"({outer})")):
            c.execute(
                text(
                    "UPDATE market_areas SET geom=ST_Transform(ST_GeomFromText(:wkt,5181),4326) "
                    "WHERE market_code=:code"
                ),
                {"code": code, "wkt": f"MULTIPOLYGON(({rings}))"},
            )
    result = request(client)
    selected = {row["market_code"]: row for row in result["data"]["sales"]["items"]}
    assert selected["3110000"]["spatial_relation"] == "intersects_radius"
    assert selected["3110001"]["spatial_relation"] == "contains_point"
    lng, lat = Transformer.from_crs(5181, 4326, always_xy=True).transform(200002, 450002)
    selected = {
        row["market_code"]: row
        for row in request(client, lng=lng, lat=lat)["data"]["sales"]["items"]
    }
    assert (
        selected["3110000"]["spatial_relation"]
        == selected["3110001"]["spatial_relation"]
        == "contains_point"
    )
    assert result["meta"]["items_additive"] is False
