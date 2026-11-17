import hashlib
import io
import math
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

import shapefile  # type: ignore[import-untyped]
from pyproj import CRS
from sqlalchemy import Connection, text

from etl.living_pop.data import GRID_RULE_VERSION, fail
from etl.living_pop.source import GRID_PATTERN, FileInput, verified_bytes
from etl.market_areas.archive import digest

MAX_GRID_ZIP = 4 * 1024 * 1024
MAX_GRID_EXPANDED = 16 * 1024 * 1024
MAX_GRIDS = 20000
GRID_URL = "https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do"


@dataclass(frozen=True, repr=False)
class GridInput:
    sha256: str
    input_bytes: int
    metadata: dict[str, Any]
    features: list[dict[str, Any]]
    raw_content_sha256: str


@dataclass(frozen=True, repr=False)
class PreparedGrid:
    source: GridInput
    rows: list[dict[str, Any]]
    content_sha256: str
    postgis_version: str
    rule_version: str = GRID_RULE_VERSION


def _members(raw: bytes) -> tuple[dict[str, bytes], dict[str, Any]]:
    parts = {}
    meta = {}
    expanded = 0
    stem = None
    directories = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.infolist()) > 8:
            fail("grid_members")
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or ":" in name
                or info.flag_bits & 1
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                fail("grid_path")
            if info.is_dir():
                if path in directories or info.file_size:
                    fail("grid_directory")
                directories.add(path)
                continue
            suffix = path.suffix.lower()
            if (
                suffix not in {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".qmd"}
                or suffix in parts
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            ):
                fail("grid_members")
            current = str(path.with_suffix(""))
            if stem is not None and current != stem:
                fail("grid_layer")
            stem = current
            with z.open(info) as stream:
                value = stream.read(MAX_GRID_EXPANDED - expanded + 1)
            expanded += len(value)
            if expanded > MAX_GRID_EXPANDED or len(value) != info.file_size:
                fail("grid_size")
            parts[suffix] = value
            meta[suffix] = dict(
                bytes=len(value),
                sha256=hashlib.sha256(value).hexdigest(),
                modified=datetime(*info.date_time).isoformat(),
            )
    if not {".shp", ".shx", ".dbf", ".prj", ".cpg"} <= parts.keys() or stem is None:
        fail("grid_members")
    if directories - {PurePosixPath(stem).parent}:
        fail("grid_directory")
    return parts, meta


def _crs(wkt: bytes) -> None:
    c = CRS.from_wkt(wkt.decode("utf-8-sig"))
    e = CRS.from_epsg(5179)
    co, eo = c.coordinate_operation, e.coordinate_operation
    datum, expected_datum = c.datum, e.datum
    ellipsoid, expected_ellipsoid = c.ellipsoid, e.ellipsoid
    meridian, expected_meridian = c.prime_meridian, e.prime_meridian
    if (
        not c.is_projected
        or c.is_bound
        or co is None
        or eo is None
        or datum is None
        or expected_datum is None
        or ellipsoid is None
        or expected_ellipsoid is None
        or meridian is None
        or expected_meridian is None
        or datum.name != expected_datum.name
        or ellipsoid.semi_major_metre != expected_ellipsoid.semi_major_metre
        or ellipsoid.inverse_flattening != expected_ellipsoid.inverse_flattening
        or meridian.longitude != expected_meridian.longitude
        or meridian.unit_conversion_factor != expected_meridian.unit_conversion_factor
        or co.method_code != eo.method_code
        or [(p.code, p.value, p.unit_conversion_factor) for p in co.params]
        != [(p.code, p.value, p.unit_conversion_factor) for p in eo.params]
        or len(c.axis_info) != 2
        or any(a.unit_conversion_factor != 1 for a in c.axis_info)
    ):
        fail("grid_crs")


def load_grid(item: FileInput) -> GridInput:
    raw = verified_bytes(item, MAX_GRID_ZIP)
    parts, meta = _members(raw)
    if parts[".cpg"].decode("ascii").strip().upper().replace("-", "") != "UTF8":
        fail("grid_encoding")
    _crs(parts[".prj"])
    dbf = parts[".dbf"]
    if len(dbf) < 33:
        fail("grid_dbf")
    n = struct.unpack("<I", dbf[4:8])[0]
    header, width = struct.unpack("<HH", dbf[8:12])
    if not 0 < n <= MAX_GRIDS or header < 33 or width < 2 or header + n * width > len(dbf):
        fail("grid_dbf")
    if any(dbf[header + i * width : header + i * width + 1] != b" " for i in range(n)):
        fail("grid_deleted")
    reader = shapefile.Reader(
        shp=io.BytesIO(parts[".shp"]),
        shx=io.BytesIO(parts[".shx"]),
        dbf=io.BytesIO(dbf),
        encoding="utf-8",
    )
    if (
        [f[0] for f in reader.fields[1:]] != ["CELL_ID", "CELL_X", "CELL_Y", "GID"]
        or [f[1] for f in reader.fields[1:]] != ["C", "N", "N", "C"]
        or len(reader) != n
        or reader.shapeType != 5
    ):
        fail("grid_fields")
    features: list[dict[str, Any]] = []
    seen = set()
    for sr in reader.iterShapeRecords():
        r = sr.record.as_dict()
        shape = sr.shape
        code = r["CELL_ID"]
        gid = r["GID"]
        x, y = r["CELL_X"], r["CELL_Y"]
        if (
            not isinstance(code, str)
            or not re.fullmatch(GRID_PATTERN, code)
            or code in seen
            or not isinstance(gid, str)
            or not 1 <= len(gid) <= 14
        ):
            fail("grid_codes")
        if (
            not isinstance(x, int)
            or not isinstance(y, int)
            or not 500000 < x < 1500000
            or not 1500000 < y < 2500000
        ):
            fail("grid_center")
        seen.add(code)
        pts = [list(p) for p in shape.points]
        if (
            shape.shapeType != 5
            or len(shape.parts) != 1
            or len(pts) != 5
            or pts[0] != pts[-1]
            or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in pts)
        ):
            fail("grid_shape")
        b = shape.bbox
        if (
            abs(b[2] - b[0] - 250) > 0.001
            or abs(b[3] - b[1] - 250) > 0.001
            or abs((b[0] + b[2]) / 2 - x) > 0.001
            or abs((b[1] + b[3]) / 2 - y) > 0.001
            or {tuple(p) for p in pts} != {(b[0], b[1]), (b[0], b[3]), (b[2], b[1]), (b[2], b[3])}
        ):
            fail("grid_square")
        value = dict(
            grid_id=code,
            source_gid=gid,
            center_x=x,
            center_y=y,
            geometry={"type": "Polygon", "coordinates": [pts]},
        )
        features.append(value)
    if len(features) != n:
        fail("grid_count")
    features.sort(key=lambda f: f["grid_id"].encode("utf-8"))
    return GridInput(item.sha256, len(raw), meta, features, digest(features))


TRANSFORM_SQL = text("""WITH raw AS (
 SELECT j->>'grid_id' grid_id,ST_SetSRID(ST_GeomFromGeoJSON(j->'geometry'),5179) g
 FROM jsonb_array_elements(CAST(:values AS jsonb)) j
), transformed AS (
 SELECT *,ST_Multi(ST_Transform(g,4326)) dest FROM raw
)
SELECT grid_id,(ST_IsValidDetail(g,0)).valid valid,ST_Area(g) area,
 (ST_IsValidDetail(dest,0)).valid final_valid,ST_IsEmpty(dest) empty,
 ST_XMin(dest) xmin,ST_XMax(dest) xmax,ST_YMin(dest) ymin,ST_YMax(dest) ymax,
 encode(ST_AsEWKB(dest,'NDR'),'hex') geom_hex FROM transformed""")


def prepare_grid(connection: Connection, source: GridInput) -> PreparedGrid:
    import json

    rows = []
    for start in range(0, len(source.features), 250):
        batch = source.features[start : start + 250]
        lookup = {f["grid_id"]: f for f in batch}
        transformed = (
            connection.execute(TRANSFORM_SQL, {"values": json.dumps(batch, ensure_ascii=False)})
            .mappings()
            .all()
        )
        if len(transformed) != len(batch):
            fail("grid_transform_count")
        for row in transformed:
            if (
                not row["valid"]
                or not row["final_valid"]
                or row["empty"]
                or abs(row["area"] - 62500) > 0.01
                or not 126 < row["xmin"] <= row["xmax"] < 128
                or not 37 < row["ymin"] <= row["ymax"] < 38.2
            ):
                fail("grid_transform")
            f = lookup[row["grid_id"]]
            rows.append(
                {
                    **{k: v for k, v in f.items() if k != "geometry"},
                    "source_row_sha256": digest(f),
                    "geom_hex": row["geom_hex"],
                }
            )
    rows.sort(key=lambda r: r["grid_id"].encode("utf-8"))
    version = connection.scalar(text("SELECT postgis_full_version()"))
    return PreparedGrid(source, rows, digest(rows), str(version))
