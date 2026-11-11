import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from etl.market_areas.archive import Archive, Feature, MarketImportError, digest

BATCH_SIZE = 100
MAX_AREA_RELATIVE_ERROR = 0.01
NORMALIZE_SQL = text("""
WITH raw AS (
 SELECT i,ST_SetSRID(ST_GeomFromGeoJSON(g),5181) src
 FROM jsonb_array_elements(CAST(:geometries AS jsonb)) WITH ORDINALITY j(g,i)
), valid AS (
 SELECT *, (ST_IsValidDetail(src,0)).valid ok FROM raw
), fixed AS (
 SELECT *,CASE WHEN ok THEN src ELSE ST_MakeValid(src,'method=linework') END f FROM valid
), projected AS (
 SELECT *,ST_Transform(ST_Multi(f),4326) dest FROM fixed
)
SELECT i,ok,GeometryType(f) kind,ST_Area(f) measured_area,
 (ST_IsValidDetail(dest,0)).valid final_valid,ST_IsEmpty(dest) empty,
 encode(ST_AsEWKB(src,'NDR'),'hex') source_wkb,encode(ST_AsEWKB(dest,'NDR'),'hex') geom_hex,
 ST_XMin(dest) xmin,ST_XMax(dest) xmax,ST_YMin(dest) ymin,ST_YMax(dest) ymax
FROM projected ORDER BY i
""")


@dataclass(frozen=True, repr=False)
class PreparedArea:
    feature: Feature
    source_feature_sha256: str
    geometry_repaired: bool
    geom_hex: str

    def payload(self) -> dict[str, Any]:
        return {
            **self.feature.attributes(),
            "source_feature_sha256": self.source_feature_sha256,
            "geometry_repaired": self.geometry_repaired,
            "geom_hex": self.geom_hex,
        }


@dataclass(frozen=True, repr=False)
class PreparedArchive:
    source: Archive
    areas: tuple[PreparedArea, ...]
    content_sha256: str
    postgis_version: str


def prepare(connection: Connection, archive: Archive) -> PreparedArchive:
    """D-05: OGC linework repair in 5181, then lossless-type MultiPolygon WGS84."""
    areas = []
    for offset in range(0, len(archive.features), BATCH_SIZE):
        batch = archive.features[offset : offset + BATCH_SIZE]
        rows = (
            connection.execute(
                NORMALIZE_SQL,
                {"geometries": json.dumps([r.geometry for r in batch], allow_nan=False)},
            )
            .mappings()
            .all()
        )
        if len(rows) != len(batch):
            raise MarketImportError("market:geometry_count")
        for feature, row in zip(batch, rows, strict=True):
            if (
                row["kind"] not in {"POLYGON", "MULTIPOLYGON"}
                or row["empty"]
                or not row["final_valid"]
                or not (126.70 <= row["xmin"] <= row["xmax"] <= 127.25)
                or not (37.35 <= row["ymin"] <= row["ymax"] <= 37.80)
            ):
                raise MarketImportError("market:geometry_quality")
            difference = abs(float(row["measured_area"]) - float(feature.area_m2)) / float(
                feature.area_m2
            )
            if difference > MAX_AREA_RELATIVE_ERROR:
                raise MarketImportError("market:area_difference")
            source_hash = digest({**feature.attributes(), "source_wkb": row["source_wkb"]})
            areas.append(PreparedArea(feature, source_hash, not row["ok"], row["geom_hex"]))
    return PreparedArchive(
        archive,
        tuple(areas),
        digest([a.payload() for a in areas]),
        str(connection.scalar(text("SELECT postgis_full_version()"))),
    )
