"""Prepare immutable source rows; only administrative totals are consumed."""

import csv
import hashlib
import io
import itertools
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import shapefile  # type: ignore[import-untyped]

from app.models.admin_population import CODE_SYSTEM
from etl.admin_population.source import HEADERS, SourceInspectionError, _verified, inspect_sources

BOUNDARY_RULE = "admin-boundary-oa22160-v1"
POPULATION_RULE = "admin-local-oa23016-v1"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, repr=False)
class Prepared:
    boundary_input: str
    boundary_content: str
    population_input: str
    member_sha: str
    population_content: str
    observation_date: date
    areas: tuple[dict[str, object], ...]
    rows: tuple[dict[str, object], ...]
    excluded: tuple[dict[str, object], ...]
    source_rows: int
    boundary_without_observations: int = 0
    unmatched_code_count: int = 0


def population_digest(rows: list[dict[str, object]]) -> str:
    for row in rows:
        value = row["population"]
        if value is not None:
            number = Decimal(str(value))
            exponent = number.as_tuple().exponent
            if (
                not number.is_finite()
                or number < 0
                or number >= Decimal("1e15")
                or not isinstance(exponent, int)
                or exponent < -5
            ):
                raise SourceInspectionError("admin_population:invalid_source")
    return digest(
        [
            {
                "admin_code": r["admin_code"],
                "hour": r["hour"],
                "value_status": r["value_status"],
                "population": format(Decimal(str(r["population"])), ".5f")
                if r["population"] is not None
                else None,
                "source_row_sha256": r["source_row_sha256"],
            }
            for r in sorted(rows, key=lambda r: (str(r["admin_code"]), int(str(r["hour"]))))
        ]
    )


def prepare(
    population: Path,
    population_sha: str,
    boundary: Path,
    boundary_sha: str,
    day: date,
) -> Prepared:
    audit = inspect_sources(population, population_sha, boundary, boundary_sha)
    pop = audit["population"]
    if not isinstance(pop, dict) or not isinstance(pop.get("dates"), dict):
        raise SourceInspectionError("admin_population:invalid_source")
    if day.strftime("%Y%m%d") not in pop["dates"] or any(
        not str(d).startswith(day.strftime("%Y%m")) for d in pop["dates"]
    ):
        raise SourceInspectionError("admin_population:date_not_loaded")
    areas = []
    with zipfile.ZipFile(io.BytesIO(_verified(boundary, boundary_sha))) as archive:
        names = {Path(name).suffix.lower(): name for name in archive.namelist()}
        with shapefile.Reader(
            shp=io.BytesIO(archive.read(names[".shp"])),
            shx=io.BytesIO(archive.read(names[".shx"])),
            dbf=io.BytesIO(archive.read(names[".dbf"])),
            encoding="utf-8",
        ) as reader:
            for record in reader.iterShapeRecords():
                geometry = json.dumps(
                    record.shape.__geo_interface__, separators=(",", ":"), allow_nan=False
                )
                attrs = record.record.as_dict()
                areas.append(
                    {
                        "admin_code": attrs["ADSTRD_CD"],
                        "admin_name": attrs["ADSTRD_NM"],
                        "geometry_json": geometry,
                        "source_feature_sha256": digest({"attrs": attrs, "geometry": geometry}),
                    }
                )
    areas.sort(key=lambda a: str(a["admin_code"]))
    codes = {a["admin_code"] for a in areas}
    rows: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(_verified(population, population_sha))) as archive:
        member = f"250_LOCAL_RESD_ADMDONG_{day:%Y%m%d}.csv"
        raw = archive.read(member)
    with io.TextIOWrapper(io.BytesIO(raw), encoding="cp949", newline="") as source:
        if tuple(next(csv.reader([source.readline()]))) != HEADERS:
            raise SourceInspectionError("admin_population:invalid_source")
        first = source.readline()
        delimiter = ";" if ";" in first else ","
        for values in csv.reader(itertools.chain([first], source), delimiter=delimiter):
            if not values:
                continue
            admin, value = values[2].rstrip(" "), values[3]
            if value not in ("*", "") and (
                not re.fullmatch(r"(0|[1-9][0-9]*)(\.[0-9]{1,5})?", value)
                or Decimal(value) >= Decimal("1e15")
            ):
                raise SourceInspectionError("admin_population:invalid_source")
            if admin not in codes:
                excluded.append({"reason": "admin_boundary_unmatched", "raw": values})
                continue
            rows.append(
                {
                    "admin_code": admin,
                    "hour": int(values[1]),
                    "population": None if value in ("*", "") else Decimal(value),
                    "value_status": "suppressed"
                    if value == "*"
                    else "missing"
                    if value == ""
                    else "observed",
                    "source_row_sha256": digest(values),
                }
            )
    if not rows:
        raise SourceInspectionError("admin_population:no_matched_rows")
    content = digest(
        {
            "code_system": CODE_SYSTEM,
            "rows": [{k: v for k, v in a.items() if k != "geometry_json"} for a in areas],
        }
    )
    return Prepared(
        boundary_sha,
        content,
        population_sha,
        hashlib.sha256(raw).hexdigest(),
        population_digest(rows),
        day,
        tuple(areas),
        tuple(rows),
        tuple(excluded),
        len(rows) + len(excluded),
        len(codes - {r["admin_code"] for r in rows}),
        len({cast(list[str], r["raw"])[2].rstrip(" ") for r in excluded}),
    )
