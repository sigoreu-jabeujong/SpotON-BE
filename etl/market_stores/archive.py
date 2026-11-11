import csv
import hashlib
import io
import re
import zipfile
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from etl.market_areas.archive import digest
from etl.market_csv import AnnualArchive, read_csv_member

SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do"
StatsArchive = AnnualArchive
RULE_VERSION = "market-stores-oa15577-annual-v1"
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_CSV_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_FIELD = 4096
ROOT = Path(__file__).resolve().parents[2]
SUPPORTED = {
    "CS100001": "한식음식점",
    "CS100002": "중식음식점",
    "CS100003": "일식음식점",
    "CS100004": "양식음식점",
    "CS100010": "커피-음료",
}
TYPES = {"A": "골목상권", "D": "발달상권", "R": "전통시장", "U": "관광특구"}
FIELDS = (
    "stdr_yyqu_cd",
    "trdar_se_cd",
    "trdar_se_cd_nm",
    "trdar_cd",
    "trdar_cd_nm",
    "svc_induty_cd",
    "svc_induty_cd_nm",
    "stor_co",
    "similr_induty_stor_co",
    "opbiz_rt",
    "opbiz_stor_co",
    "clsbiz_rt",
    "clsbiz_stor_co",
    "frc_stor_co",
)
COUNTS = {
    "similr_induty_stor_co": "total_stores",
    "stor_co": "general_stores",
    "frc_stor_co": "franchise_stores",
    "opbiz_stor_co": "open_stores",
    "clsbiz_stor_co": "closed_stores",
}


class StatsImportError(ValueError):
    """Only fixed, non-sensitive codes may be used as messages."""


def fail(reason: str) -> NoReturn:
    raise StatsImportError("market_stats:" + reason)


def content_digest(rows: list[dict[str, Any]], rule_version: str = RULE_VERSION) -> str:
    normalized = []
    for row in sorted(rows, key=lambda r: (r["quarter"], r["market_code"], r["induty_cd"])):
        value = dict(row)
        for key in ("opening_rate", "closure_rate"):
            value[key] = format(value[key], ".6f") if value[key] is not None else None
        normalized.append(value)
    return digest({"rule_version": rule_version, "rows": normalized})


def _member(path: Path, expected_sha256: str) -> tuple[bytes, zipfile.ZipInfo, bytes]:
    return read_csv_member(
        path,
        expected_sha256,
        root=ROOT,
        max_zip_bytes=MAX_ZIP_BYTES,
        max_csv_bytes=MAX_CSV_BYTES,
        fail=fail,
    )


def _parse(
    data: bytes,
    year: int,
) -> tuple[str, int, list[dict[str, Any]], dict[str, dict[str, tuple[str, str]]], dict[str, int]]:
    encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "cp949"
    source = data.decode(encoding, errors="strict")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in source):
        fail("control")
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    headers = next(reader, [])
    if len(headers) != len(FIELDS) or set(headers) != set(FIELDS):
        fail("headers")
    seen: set[tuple[str, str, str]] = set()
    industry_labels: dict[str, str] = {}
    markets: dict[str, dict[str, tuple[str, str]]] = {}
    quarter_rows: Counter[str] = Counter()
    supported_combinations: set[tuple[str, str]] = set()
    rows = []
    count = 0
    for cells in reader:
        count += 1
        if count > MAX_ROWS or len(cells) != len(FIELDS) or any(len(c) > MAX_FIELD for c in cells):
            fail("row_shape")
        raw = dict(zip(headers, cells, strict=True))
        if any(any(ord(c) < 32 for c in value) for value in cells):
            fail("control")
        q, code, industry = raw["stdr_yyqu_cd"], raw["trdar_cd"], raw["svc_induty_cd"]
        if q not in {f"{year}{i}" for i in range(1, 5)}:
            fail("quarter")
        if not re.fullmatch(r"[0-9]{7}", code) or not re.fullmatch(r"CS[0-9]{6}", industry):
            fail("codes")
        kind, name, label = raw["trdar_se_cd"], raw["trdar_cd_nm"], raw["svc_induty_cd_nm"]
        if kind not in TYPES or raw["trdar_se_cd_nm"] != TYPES[kind]:
            fail("type")
        if not name.strip() or len(name) > 255 or not label.strip() or len(label) > 255:
            fail("names")
        if industry in SUPPORTED and label != SUPPORTED[industry]:
            fail("industry_label")
        if industry_labels.setdefault(industry, label) != label:
            fail("industry_label")
        previous = markets.setdefault(q, {}).setdefault(code, (kind, name))
        if previous != (kind, name):
            fail("market_label")
        key = (q, code, industry)
        if key in seen:
            fail("duplicate")
        seen.add(key)
        values: dict[str, Any] = {}
        for field, output in COUNTS.items():
            value = raw[field]
            if not re.fullmatch(r"0|[1-9][0-9]{0,9}", value) or int(value) > 2_147_483_647:
                fail("count")
            values[output] = int(value)
        if values["total_stores"] != values["general_stores"] + values["franchise_stores"]:
            fail("count_relation")
        for field, output in (("opbiz_rt", "opening_rate"), ("clsbiz_rt", "closure_rate")):
            value = raw[field]
            if value and not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,6})?", value):
                fail("rate")
            values[output] = Decimal(value).quantize(Decimal("0.000001")) if value else None
        quarter_rows[q] += 1
        if industry in SUPPORTED:
            supported_combinations.add((q, industry))
            rows.append(
                dict(
                    quarter=q,
                    market_code=code,
                    induty_cd=industry,
                    market_name=name,
                    market_type_code=kind,
                    market_type_name=raw["trdar_se_cd_nm"],
                    induty_name=label,
                    **values,
                    source_row_sha256=digest(raw),
                )
            )
    if supported_combinations != {(f"{year}{q}", i) for q in range(1, 5) for i in SUPPORTED}:
        fail("incomplete_year")
    return encoding, count, rows, markets, dict(quarter_rows)


def load_archive(
    path: Path,
    expected_sha256: str,
    year: int,
    source_file_date: date,
    *,
    today: date | None = None,
) -> StatsArchive:
    reference = today if today is not None else datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not 2000 <= year < reference.year or not date(year, 12, 31) < source_file_date <= reference:
        fail("source_date")
    try:
        raw, info, data = _member(path, expected_sha256)
        # Field sizes are checked per cell, without changing csv's process-global limit.
        encoding, count, rows, markets, quarter_rows = _parse(data, year)
        modified = datetime(*info.date_time).isoformat()
    except StatsImportError:
        raise
    except Exception:
        raise StatsImportError("market_stats:archive_invalid") from None
    return StatsArchive(
        year,
        source_file_date,
        expected_sha256,
        len(raw),
        info.filename,
        hashlib.sha256(data).hexdigest(),
        len(data),
        modified,
        encoding,
        count,
        rows,
        markets,
        quarter_rows,
    )
