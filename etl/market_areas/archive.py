import hashlib
import io
import json
import math
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

import shapefile  # type: ignore[import-untyped]
from pyproj import CRS

SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do"
RULE_VERSION = "market-areas-pyshp318-linework-v1"
MAX_ZIP_BYTES, MAX_EXPANDED_BYTES = 32 * 1024**2, 64 * 1024**2
MAX_RECORDS, MAX_POINTS = 20_000, 500_000
GU_CODES = frozenset(
    (
        "11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 11380 "
        "11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 11680 11710 11740"
    ).split()
)
MARKET_TYPES = {
    "A": ("골목상권", "alley"),
    "D": ("발달상권", "developed"),
    "R": ("전통시장", "traditional_market"),
    "U": ("관광특구", "tourism_zone"),
}
REQUIRED_FIELDS = {"TRDAR_SE_C", "TRDAR_SE_1", "TRDAR_CD", "TRDAR_CD_N", "SIGNGU_CD", "RELM_AR"}


class MarketImportError(ValueError):
    """Static reason code only; no source values, paths, geometry or SQL."""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, repr=False)
class Feature:
    market_code: str
    market_name: str
    market_type: str
    market_type_code: str
    gu_code: str
    area_m2: Decimal
    geometry: dict[str, Any]

    def attributes(self) -> dict[str, Any]:
        return dict(
            market_code=self.market_code,
            market_name=self.market_name,
            market_type=self.market_type,
            market_type_code=self.market_type_code,
            gu_code=self.gu_code,
            area_m2=format(self.area_m2, ".2f"),
        )


@dataclass(frozen=True, repr=False)
class Archive:
    input_sha256: str
    input_bytes: int
    source_file_date: date
    features: tuple[Feature, ...]


def _members(data: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = z.infolist()
        if len(files) != 5 or sum(f.file_size for f in files) > MAX_EXPANDED_BYTES:
            raise MarketImportError("market:archive_size")
        stem: str | None = None
        expanded = 0
        for info in files:
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            suffix = path.suffix.lower()
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or ":" in name
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.flag_bits & 1
                or suffix not in {".shp", ".shx", ".dbf", ".prj", ".cpg"}
                or suffix in result
            ):
                raise MarketImportError("market:archive_members")
            current = str(path.with_suffix("")).casefold()
            if stem is not None and current != stem:
                raise MarketImportError("market:archive_layer")
            stem = current
            with z.open(info) as f:
                value = f.read(MAX_EXPANDED_BYTES - expanded + 1)
            expanded += len(value)
            if expanded > MAX_EXPANDED_BYTES or len(value) != info.file_size:
                raise MarketImportError("market:archive_size")
            result[suffix] = value
    return result


def _geometry(shape: Any) -> dict[str, Any]:
    if shape.shapeType != 5:
        raise MarketImportError("market:shape_type")
    points = []
    for p in shape.points:
        if len(p) != 2 or any(not math.isfinite(v) or not 0 < v < 1_000_000 for v in p):
            raise MarketImportError("market:coordinate")
        points.append([float(p[0]), float(p[1])])
    parts = list(shape.parts)
    if (
        not points
        or len(points) > MAX_POINTS
        or not parts
        or parts[0] != 0
        or parts != sorted(set(parts))
    ):
        raise MarketImportError("market:rings")
    rings = []
    for start, end in zip(parts, [*parts[1:], len(points)], strict=True):
        ring = points[start:end]
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise MarketImportError("market:rings")
        rings.append(ring)
    errors: dict[str, int] = {}
    polygons = shapefile.organize_polygon_rings(rings, return_errors=errors)
    if errors or not polygons:
        raise MarketImportError("market:ring_orientation")
    return {
        "type": "Polygon" if len(polygons) == 1 else "MultiPolygon",
        "coordinates": polygons[0] if len(polygons) == 1 else polygons,
    }


def load_archive(path: Path, expected_sha256: str, source_file_date: date) -> Archive:
    if not re.fullmatch("[0-9a-f]{64}", expected_sha256):
        raise MarketImportError("market:expected_hash")
    if source_file_date > datetime.now(ZoneInfo("Asia/Seoul")).date():
        raise MarketImportError("market:future_file_date")
    try:
        with path.open("rb") as f:
            data = f.read(MAX_ZIP_BYTES + 1)
        if not data or len(data) > MAX_ZIP_BYTES:
            raise MarketImportError("market:archive_size")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise MarketImportError("market:hash_mismatch")
        files = _members(data)
        if files[".cpg"].decode("ascii").strip().upper().replace("-", "") != "UTF8":
            raise MarketImportError("market:encoding")
        crs = CRS.from_wkt(files[".prj"].decode("utf-8-sig"))
        expected_crs = CRS.from_epsg(5181)
        operation, expected_operation = crs.coordinate_operation, expected_crs.coordinate_operation
        ellipsoid, expected_ellipsoid = crs.ellipsoid, expected_crs.ellipsoid
        if (
            crs.to_epsg(min_confidence=90) != 5181
            or operation is None
            or expected_operation is None
            or ellipsoid is None
            or expected_ellipsoid is None
            or operation.method_code != expected_operation.method_code
            or [(p.code, p.value, p.unit_conversion_factor) for p in operation.params]
            != [(p.code, p.value, p.unit_conversion_factor) for p in expected_operation.params]
            or (ellipsoid.semi_major_metre, ellipsoid.inverse_flattening)
            != (expected_ellipsoid.semi_major_metre, expected_ellipsoid.inverse_flattening)
        ):
            raise MarketImportError("market:crs")
        dbf = files[".dbf"]
        count = struct.unpack("<I", dbf[4:8])[0]
        header, width = struct.unpack("<HH", dbf[8:12])
        if (
            not 0 < count <= MAX_RECORDS
            or header < 33
            or width < 2
            or header + count * width > len(dbf)
        ):
            raise MarketImportError("market:dbf_layout")
        if any(dbf[header + i * width : header + i * width + 1] != b" " for i in range(count)):
            raise MarketImportError("market:deleted_record")
        records = []
        codes = set()
        total_points = 0
        with shapefile.Reader(
            shp=io.BytesIO(files[".shp"]),
            shx=io.BytesIO(files[".shx"]),
            dbf=io.BytesIO(dbf),
            encoding="utf-8",
            encodingErrors="strict",
        ) as reader:
            names = [f[0] for f in reader.fields[1:]]
            field_types = {f[0]: getattr(f[1], "value", f[1]) for f in reader.fields[1:]}
            if (
                reader.shapeType != 5
                or reader.numRecords != count
                or len(names) != len(set(names))
                or not REQUIRED_FIELDS <= set(names)
                or any(
                    field_types.get(k) != ("N" if k == "RELM_AR" else "C") for k in REQUIRED_FIELDS
                )
                or len(reader.shapes()) != count
            ):
                raise MarketImportError("market:schema")
            for row in reader.iterShapeRecords():
                raw = row.record
                if any(not isinstance(raw[k], str) for k in REQUIRED_FIELDS - {"RELM_AR"}):
                    raise MarketImportError("market:attributes")
                code = str(raw["TRDAR_CD"]).strip()
                gu = str(raw["SIGNGU_CD"]).strip()
                name = str(raw["TRDAR_CD_N"]).strip()
                kind = str(raw["TRDAR_SE_C"]).strip()
                if not re.fullmatch("[0-9]{7}", code) or code in codes or gu not in GU_CODES:
                    raise MarketImportError("market:codes")
                if (
                    not name
                    or len(name) > 255
                    or any(ord(c) < 32 for c in name)
                    or kind not in MARKET_TYPES
                    or str(raw["TRDAR_SE_1"]).strip() != MARKET_TYPES[kind][0]
                ):
                    raise MarketImportError("market:attributes")
                area = Decimal(str(raw["RELM_AR"]))
                if not area.is_finite() or not 0 < area <= Decimal("9999999999999999.99"):
                    raise MarketImportError("market:area")
                area = area.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if area <= 0:
                    raise MarketImportError("market:area")
                geometry = _geometry(row.shape)
                total_points += len(row.shape.points)
                if total_points > MAX_POINTS:
                    raise MarketImportError("market:point_limit")
                records.append(Feature(code, name, MARKET_TYPES[kind][1], kind, gu, area, geometry))
                codes.add(code)
        if len(records) != count or {r.gu_code for r in records} != GU_CODES:
            raise MarketImportError("market:incomplete_snapshot")
        return Archive(
            expected_sha256,
            len(data),
            source_file_date,
            tuple(sorted(records, key=lambda r: r.market_code)),
        )
    except MarketImportError:
        raise
    except Exception:
        raise MarketImportError("market:invalid_archive") from None
