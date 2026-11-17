from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import MarketArea, MarketAreaVersion
from app.schemas.market_judgement import BoundaryQuery
from app.services.market_judgement import judge_market
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration

BOX = "MULTIPOLYGON(((126.99 37.49,127.01 37.49,127.01 37.51,126.99 37.51,126.99 37.49)))"
HOLE = (
    "MULTIPOLYGON(((126.99 37.49,127.01 37.49,127.01 37.51,126.99 37.51,126.99 37.49),"
    "(126.999 37.499,126.999 37.501,127.001 37.501,127.001 37.499,126.999 37.499)))"
)
MULTI = (
    "MULTIPOLYGON(((126.99 37.49,127.01 37.49,127.01 37.51,126.99 37.51,126.99 37.49)),"
    "((127.09 37.49,127.11 37.49,127.11 37.51,127.09 37.51,127.09 37.49)))"
)


def version(c, count):
    vid = uuid4()
    c.execute(
        insert(MarketAreaVersion).values(
            version_id=vid,
            source_dataset="OA-15560",
            source_url="https://example.invalid",
            source_file_date=date(2023, 10, 23),
            boundary_as_of=None,
            input_sha256=vid.hex * 2,
            input_bytes=100,
            source_crs=5181,
            rule_version="synthetic",
            row_count=count,
            repaired_count=0,
            content_sha256="2" * 64,
            postgis_version="synthetic",
        )
    )
    return vid


def area(c, vid, code="3110001", kind="alley", wkt=BOX):
    c.execute(
        insert(MarketArea).values(
            version_id=vid,
            market_code=code,
            market_name="synthetic",
            market_type=kind,
            market_type_code={
                "alley": "A",
                "developed": "D",
                "traditional_market": "R",
                "tourism_zone": "U",
            }[kind],
            gu_code="11110",
            area_m2=100,
            source_feature_sha256="3" * 64,
            geometry_repaired=False,
            geom=func.ST_GeomFromText(wkt, 4326),
        )
    )


def lookup(engine, vid, **changes):
    with Session(engine) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        result = judge_market(
            s, BoundaryQuery(**{**dict(version_id=vid, lat=37.5, lng=127.0), **changes})
        )
        assert s.scalar(text("SHOW transaction_read_only")) == "on"
        return result


@pytest.fixture
def db(temporary_database):
    migrate(temporary_database)
    return temporary_database.engine


def test_covers_edges_hole_boundary_and_multipart(db):
    with db.begin() as c:
        v = version(c, 1)
        area(c, v, wkt=HOLE)
        multi = version(c, 1)
        area(c, multi, wkt=MULTI)
    assert lookup(db, v).spatial_status == "outside"
    assert len(lookup(db, v).nearby_markets) == 1  # Distance is to the hole ring, not centroid.
    for lat, lng in [(37.49, 126.99), (37.5, 126.99), (37.5, 126.999), (37.495, 127.0)]:
        assert lookup(db, v, lat=lat, lng=lng).spatial_status == "in_market"
    assert lookup(db, multi, lng=127.1).spatial_status == "in_market"
    assert lookup(db, multi, lng=127.05).spatial_status == "outside"
    with pytest.raises(ValidationError):
        lookup(db, multi, lat=127.0, lng=37.5)
    assert lookup(db, multi, lat=0.0, lng=0.0).nearby_markets == []


def test_detail_and_zone_overlaps_version_isolation_and_radius(db):
    with db.begin() as c:
        single = version(c, 3)
        area(c, single)
        area(c, single, "3110002", "tourism_zone")
        area(c, single, "3110003", "tourism_zone")
        overlap = version(c, 3)
        area(c, overlap)
        area(c, overlap, "3110002", "developed")
        area(c, overlap, "3110003", "tourism_zone")
        tourism = version(c, 2)
        area(c, tourism, "3110004", "tourism_zone")
        area(c, tourism, "3110005", "tourism_zone")
    a = lookup(db, single, radius=300)
    assert a == lookup(db, single, radius=1000)
    assert a.primary.market_code == "3110001" and len(a.also_in) == 2
    assert a.provenance.version_id == single and a.provenance.boundary_as_of is None
    assert a.provenance.applicability == "unverified"
    b = lookup(db, overlap)
    assert b.spatial_status == "ambiguous" and b.primary is None
    assert [r.market_code for r in b.candidates] == ["3110001", "3110002"]
    assert len(b.also_in) == 1
    z = lookup(db, tourism)
    assert z.spatial_status == "ambiguous" and len(z.candidates) == 2 and z.also_in == []
    outside = lookup(db, tourism, lng=127.015)
    assert outside.spatial_status == "outside"
    assert [r.market_code for r in outside.nearby_markets] == ["3110004", "3110005"]


def test_geography_polygon_distance_499_500_501_and_rounding(db):
    with db.begin() as c:
        v = version(c, 4)
        for i, distance in enumerate([499, 500, 500.001, 501], 1):
            wkt = c.scalar(
                text("""WITH p AS(SELECT ST_SetSRID(ST_MakePoint(127,37.5),4326)::geography g)
              SELECT ST_AsText(ST_Multi(ST_MakePolygon(ST_MakeLine(ARRAY[
              ST_Project(g,:d,0)::geometry,ST_Project(g,:d+50,0.001)::geometry,
              ST_Project(g,:d+50,-0.001)::geometry,ST_Project(g,:d,0)::geometry])))) FROM p"""),
                {"d": distance},
            )
            area(c, v, f"311000{i}", wkt=wkt)
        expected = list(
            c.scalars(
                text("""SELECT market_code FROM market_areas WHERE version_id=:v
          AND ST_Distance(geom::geography,
              ST_SetSRID(ST_MakePoint(127,37.5),4326)::geography,true)<=500
          ORDER BY market_code"""),
                {"v": v},
            )
        )
    result = lookup(db, v)
    assert result.spatial_status == "outside"
    codes = [r.market_code for r in result.nearby_markets]
    assert codes == expected and "3110001" in codes
    assert "3110003" not in codes and "3110004" not in codes


def test_missing_empty_and_partial_versions_fail_without_fallback(db):
    with db.begin() as c:
        good = version(c, 1)
        area(c, good)
        empty = version(c, 1)
        partial = version(c, 2)
        area(c, partial)
    for vid in [uuid4(), empty, partial]:
        with pytest.raises(AppError) as exc:
            lookup(db, vid)
        assert exc.value.__context__ is None
    assert lookup(db, good).spatial_status == "in_market"
