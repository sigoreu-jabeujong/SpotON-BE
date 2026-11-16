"""Bounded offline inspection of OA-23016 daily CSVs and OA-22160 polygons.

Only exact shared administrative codes are matched. This checks source structure
and technical compatibility, not historical boundary applicability or full totals.
"""

import csv
import hashlib
import io
import itertools
import math
import re
import struct
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zlib import error as ZlibError

import shapefile  # type: ignore[import-untyped]
from pyproj import CRS
from pyproj.exceptions import CRSError

MAX_ZIP_BYTES = 64 * 1024**2
MAX_EXPANDED_BYTES = 128 * 1024**2
MAX_ROWS = 400_000
MAX_POINTS = 500_000
MAX_FIELD = 4096
RULE_VERSION = "admin-local-source-inspection-v1"
AGE_BANDS = ("0~9세", *(f"{a}~{a + 4}세" for a in range(10, 70, 5)), "70세 이상")
HEADERS = (
    "일자",
    "시간",
    "행정동코드",
    "생활인구합계",
    *(f"{sex} {age}" for sex in ("남자", "여자") for age in AGE_BANDS),
)
_MEMBER = re.compile(r"250_LOCAL_RESD_ADMDONG_(20[0-9]{6})\.csv")
_ADMIN = re.compile(r"11[0-9]{6} {0,5}")
_VALUE = re.compile(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,5})?")


class SourceInspectionError(ValueError):
    """Fixed code only, without source rows, file paths or archive content."""


def fail() -> None:
    raise SourceInspectionError("admin_population:invalid_source")


def _verified(path: Path, expected: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail()
    if not path.is_file() or path.stat().st_size > MAX_ZIP_BYTES:
        fail()
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_ZIP_BYTES or hashlib.sha256(raw).hexdigest() != expected:
        fail()
    return raw


def _members(archive: zipfile.ZipFile, maximum: int) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if (
        not 1 <= len(members) <= maximum
        or len({m.filename for m in members}) != len(members)
        or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES
        or any(m.is_dir() or m.flag_bits & 1 or m.file_size < 0 for m in members)
    ):
        fail()
    return members


def inspect_population(path: Path, sha256: str) -> dict[str, object]:
    raw = _verified(path, sha256)
    codes: set[str] = set()
    days: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    delimiters: Counter[str] = Counter()
    keys: set[tuple[str, str, int]] = set()
    observed_hours: dict[tuple[str, str], set[int]] = defaultdict(set)
    precision = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for member in _members(archive, 31):
                match = _MEMBER.fullmatch(member.filename)
                if match is None:
                    fail()
                assert match is not None
                day = match[1]
                datetime.strptime(day, "%Y%m%d")
                with (
                    archive.open(member) as binary,
                    io.TextIOWrapper(
                        binary,
                        encoding="cp949",
                        newline="",
                    ) as source,
                ):
                    if tuple(next(csv.reader([source.readline()]))) != HEADERS:
                        fail()
                    first = source.readline()
                    delimiter = ";" if ";" in first else ","
                    delimiters[delimiter] += 1
                    for row in csv.reader(itertools.chain([first], source), delimiter=delimiter):
                        if not row:
                            continue
                        if (
                            len(row) != len(HEADERS)
                            or any(len(v) > MAX_FIELD for v in row)
                            or row[0] != day
                            or not re.fullmatch(r"[0-2][0-9]", row[1])
                            or not _ADMIN.fullmatch(row[2])
                        ):
                            fail()
                        hour, admin = int(row[1]), row[2].rstrip(" ")
                        key = (day, admin, hour)
                        if hour > 23 or key in keys or len(keys) >= MAX_ROWS:
                            fail()
                        keys.add(key)
                        codes.add(admin)
                        days[day] += 1
                        total = row[3]
                        if total == "*":
                            statuses["suppressed"] += 1
                        elif total == "":
                            statuses["missing"] += 1
                        else:
                            if not _VALUE.fullmatch(total) or Decimal(total) >= Decimal("1e15"):
                                fail()
                            statuses["observed"] += 1
                            precision = max(precision, len(total.partition(".")[2]))
                            observed_hours[(day, admin)].add(hour)
    except (
        csv.Error,
        UnicodeError,
        zipfile.BadZipFile,
        KeyError,
        OverflowError,
        ValueError,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        struct.error,
        ZlibError,
    ):
        fail()
    return {
        "dataset": "OA-23016",
        "input_sha256": sha256,
        "input_bytes": len(raw),
        "row_count": len(keys),
        "dates": dict(sorted(days.items())),
        "codes": sorted(codes),
        "statuses": dict(statuses),
        "max_precision": precision,
        "complete_admin_days": sum(len(hours) == 24 for hours in observed_hours.values()),
        "data_delimiters": dict(delimiters),
        "age_fields_validated": False,
        "coverage_basis": "file_members_only",
    }


def inspect_boundary(path: Path, sha256: str) -> dict[str, object]:
    raw = _verified(path, sha256)
    codes: set[str] = set()
    points = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = _members(archive, 5)
            names = {Path(m.filename).suffix.lower(): m.filename for m in members}
            stems = {Path(m.filename).stem for m in members}
            if len(stems) != 1 or set(names) != {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
                fail()
            if archive.read(names[".cpg"]).decode("ascii").strip().upper() != "UTF-8":
                fail()
            crs = CRS.from_wkt(archive.read(names[".prj"]).decode("utf-8-sig"))
            if crs.to_epsg() != 5181:
                fail()
            reader = shapefile.Reader(
                shp=io.BytesIO(archive.read(names[".shp"])),
                shx=io.BytesIO(archive.read(names[".shx"])),
                dbf=io.BytesIO(archive.read(names[".dbf"])),
                encoding="utf-8",
            )
            if reader.numRecords != reader.numShapes:
                fail()
            if {f[0] for f in reader.fields[1:]} != {
                "ADSTRD_CD",
                "ADSTRD_NM",
                "XCNTS_VALU",
                "YDNTS_VALU",
                "RELM_AR",
            } or not 1 <= len(reader) <= 1000:
                fail()
            for record in reader.iterShapeRecords():
                code = record.record["ADSTRD_CD"]
                if (
                    not isinstance(code, str)
                    or not re.fullmatch(r"11[0-9]{6}", code)
                    or code in codes
                    or record.shape.shapeType != 5
                    or not record.record["ADSTRD_NM"]
                ):
                    fail()
                codes.add(code)
                points += len(record.shape.points)
                if points > MAX_POINTS or any(
                    not math.isfinite(v) for point in record.shape.points for v in point
                ):
                    fail()
    except (
        UnicodeError,
        zipfile.BadZipFile,
        KeyError,
        OverflowError,
        ValueError,
        shapefile.ShapefileException,
        CRSError,
        struct.error,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        ZlibError,
    ):
        fail()
    return {
        "dataset": "OA-22160",
        "input_sha256": sha256,
        "input_bytes": len(raw),
        "row_count": len(codes),
        "codes": sorted(codes),
        "source_epsg": 5181,
        "points": points,
        "geometry_validated_by_postgis": False,
    }


def inspect_sources(
    population: Path, population_sha: str, boundary: Path, boundary_sha: str
) -> dict[str, object]:
    pop = inspect_population(population, population_sha)
    areas = inspect_boundary(boundary, boundary_sha)
    p = set(cast_codes(pop["codes"]))
    g = set(cast_codes(areas["codes"]))
    return {
        "rule_version": RULE_VERSION,
        "mode": "offline_inspection",
        "database_access": False,
        "population": pop,
        "boundary": areas,
        "matched_code_count": len(p & g),
        "population_only_codes": sorted(p - g),
        "boundary_only_codes": sorted(g - p),
        "historical_boundary_compatibility": "unverified",
        "population_total_validated": False,
    }


def cast_codes(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise SourceInspectionError("admin_population:invalid_source")
    return [str(v) for v in value]
