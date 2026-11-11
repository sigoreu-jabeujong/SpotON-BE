import csv
import hashlib
import io
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from etl.market_areas.archive import digest
from etl.market_csv import AnnualArchive, read_csv_member
from etl.market_sales.fields import FIELDS
from etl.market_stores.archive import SUPPORTED, TYPES

SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do"
RULE_VERSION = "market-sales-oa15572-annual-v1"
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_CSV_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_FIELD = 4096
MAX_INTEGER = 9223372036854775807
ROOT = Path(__file__).resolve().parents[2]


class SalesImportError(ValueError):
    """Messages contain fixed codes only."""


def fail(reason: str) -> NoReturn:
    raise SalesImportError("market_sales:" + reason)


def content_digest(rows: list[dict[str, Any]], year: int, rule_version: str = RULE_VERSION) -> str:
    ordered = sorted(rows, key=lambda r: (r["quarter"], r["market_code"], r["induty_cd"]))
    return digest({"rule_version": rule_version, "source_year": year, "rows": ordered})


def source_integer(value: str) -> int | None:
    if value == "":
        return None
    if not re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
        fail("integer")
    result = int(value)
    if result > MAX_INTEGER:
        fail("integer_range")
    return result


def _parse(
    data: bytes, year: int
) -> tuple[str, int, list[dict[str, Any]], dict[str, dict[str, tuple[str, str]]], dict[str, int]]:
    encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "cp949"
    source = data.decode(encoding, errors="strict")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in source):
        fail("control")
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    headers = next(reader, [])
    if len(headers) != len(FIELDS) or set(headers) != set(FIELDS):
        fail("headers")
    quarters = {f"{year}{q}" for q in range(1, 5)}
    seen: set[tuple[str, str, str]] = set()
    industry_labels: dict[str, str] = {}
    markets: dict[str, dict[str, tuple[str, str]]] = {}
    quarter_rows: Counter[str] = Counter()
    combinations: set[tuple[str, str]] = set()
    rows = []
    count = 0
    for cells in reader:
        count += 1
        if count > MAX_ROWS or len(cells) != len(FIELDS) or any(len(c) > MAX_FIELD for c in cells):
            fail("row_shape")
        if any(any(ord(c) < 32 for c in value) for value in cells):
            fail("control")
        raw = dict(zip(headers, cells, strict=True))
        q, kind, kind_name, code, name, industry, label = (raw[k] for k in FIELDS[:7])
        if q not in quarters:
            fail("quarter")
        if not re.fullmatch(r"[0-9]{7}", code) or not re.fullmatch(r"CS[0-9]{6}", industry):
            fail("codes")
        if kind not in TYPES or kind_name != TYPES[kind]:
            fail("type")
        if not name.strip() or len(name) > 255 or not label.strip() or len(label) > 255:
            fail("names")
        if (industry in SUPPORTED and label != SUPPORTED[industry]) or industry_labels.setdefault(
            industry, label
        ) != label:
            fail("industry_label")
        if markets.setdefault(q, {}).setdefault(code, (kind, name)) != (kind, name):
            fail("market_label")
        key = (q, code, industry)
        if key in seen:
            fail("duplicate")
        seen.add(key)
        numbers = {field: source_integer(raw[field]) for field in FIELDS[7:]}
        quarter_rows[q] += 1
        if industry in SUPPORTED:
            combinations.add((q, industry))
            rows.append(
                dict(
                    quarter=q,
                    market_code=code,
                    induty_cd=industry,
                    market_name=name,
                    market_type_code=kind,
                    market_type_name=kind_name,
                    induty_name=label,
                    est_sales=numbers[FIELDS[7]],
                    source_sales_count=numbers[FIELDS[8]],
                    source_row_sha256=digest(raw),
                )
            )
    if combinations != {(q, i) for q in quarters for i in SUPPORTED}:
        fail("incomplete_year")
    return encoding, count, rows, markets, dict(quarter_rows)


def load_archive(
    path: Path,
    expected_sha256: str,
    year: int,
    source_file_date: date,
    *,
    today: date | None = None,
) -> AnnualArchive:
    reference = today if today is not None else datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not 2000 <= year < reference.year or not date(year, 12, 31) < source_file_date <= reference:
        fail("source_date")
    try:
        raw, info, data = read_csv_member(
            path,
            expected_sha256,
            root=ROOT,
            max_zip_bytes=MAX_ZIP_BYTES,
            max_csv_bytes=MAX_CSV_BYTES,
            fail=fail,
        )
        encoding, count, rows, markets, quarter_rows = _parse(data, year)
        modified = datetime(*info.date_time).isoformat()
    except SalesImportError:
        raise
    except Exception:
        raise SalesImportError("market_sales:archive_invalid") from None
    return AnnualArchive(
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
