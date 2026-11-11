import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from etl.market_areas.archive import digest
from etl.market_stores.archive import TYPES

SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15576/S/1/datasetView.do"
RULE_VERSION = "market-changes-oa15576-csv-v1"
ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100_000
MAX_FIELD = 4096
CHANGES = {"LL": "다이나믹", "LH": "상권확장", "HL": "상권축소", "HH": "정체"}
FIELDS = (
    "기준_년분기_코드",
    "상권_구분_코드",
    "상권_구분_코드_명",
    "상권_코드",
    "상권_코드_명",
    "상권_변화_지표",
    "상권_변화_지표_명",
    "운영_영업_개월_평균",
    "폐업_영업_개월_평균",
    "서울_운영_영업_개월_평균",
    "서울_폐업_영업_개월_평균",
)
MONTH_FIELDS = (
    "operating_months_avg",
    "closed_months_avg",
    "seoul_operating_months_avg",
    "seoul_closed_months_avg",
)


class ChangeImportError(ValueError):
    """Fixed non-sensitive error codes only."""


def fail(reason: str) -> NoReturn:
    raise ChangeImportError("market_changes:" + reason)


@dataclass(frozen=True, repr=False)
class MarketChangeInput:
    source_year: int
    retrieved_at: datetime
    input_sha256: str
    input_bytes: int
    source_encoding: str
    source_rows: int
    rows: list[dict[str, Any]]
    markets: dict[str, dict[str, tuple[str, str]]]
    quarter_rows: dict[str, int]


def content_digest(rows: list[dict[str, Any]], year: int, rule_version: str = RULE_VERSION) -> str:
    return digest(
        dict(
            source_year=year,
            rule_version=rule_version,
            rows=sorted(rows, key=lambda r: (r["quarter"], r["market_code"])),
        )
    )


def _parse(
    data: bytes, year: int, now: datetime
) -> tuple[str, int, list[dict[str, Any]], dict[str, dict[str, tuple[str, str]]], dict[str, int]]:
    encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "cp949"
    source = data.decode(encoding, errors="strict")
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    headers = next(reader, [])
    if len(headers) != len(FIELDS) or set(headers) != set(FIELDS):
        fail("headers")
    seen: set[tuple[str, str]] = set()
    markets: dict[str, dict[str, tuple[str, str]]] = {}
    quarter_rows: Counter[str] = Counter()
    rows = []
    count = 0
    current_quarter = f"{now.year}{(now.month - 1) // 3 + 1}"
    for cells in reader:
        count += 1
        if count > MAX_ROWS or len(cells) != len(FIELDS) or any(len(c) > MAX_FIELD for c in cells):
            fail("row_shape")
        if any(any(ord(c) < 32 or ord(c) == 127 for c in value) for value in cells):
            fail("control")
        raw = dict(zip(headers, cells, strict=True))
        q, code, kind, name = (raw[FIELDS[i]] for i in (0, 3, 1, 4))
        if not re.fullmatch(r"20[0-9]{2}[1-4]", q) or q > current_quarter:
            fail("quarter")
        if not re.fullmatch(r"[0-9]{7}", code):
            fail("code")
        if kind not in TYPES or raw[FIELDS[2]] != TYPES[kind]:
            fail("type")
        if not name.strip() or len(name) > 255:
            fail("name")
        change, label = raw[FIELDS[5]], raw[FIELDS[6]]
        if change not in CHANGES or label != CHANGES[change]:
            fail("change_pair")
        key = (q, code)
        if key in seen:
            fail("duplicate")
        seen.add(key)
        values: dict[str, Any] = {}
        for field, output in zip(FIELDS[7:], MONTH_FIELDS, strict=True):
            value = raw[field]
            if value and (not re.fullmatch(r"0|[1-9][0-9]{0,9}", value) or int(value) > 2147483647):
                fail("months")
            values[output] = int(value) if value else None
        if q[:4] == str(year):
            quarter_rows[q] += 1
            markets.setdefault(q, {})[code] = (kind, name)
            rows.append(
                dict(
                    quarter=q,
                    market_code=code,
                    market_type_code=kind,
                    market_type_name=raw[FIELDS[2]],
                    market_name=name,
                    change_code=change,
                    change_name=label,
                    **values,
                    source_row_sha256=digest(raw),
                )
            )
    if set(quarter_rows) != {f"{year}{q}" for q in range(1, 5)}:
        fail("incomplete_year")
    return encoding, count, rows, markets, dict(quarter_rows)


def load_source(
    path: Path,
    expected_sha256: str,
    year: int,
    retrieved_at: datetime,
    *,
    now: datetime | None = None,
) -> MarketChangeInput:
    reference = (now if now is not None else datetime.now(UTC)).astimezone(ZoneInfo("Asia/Seoul"))
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        fail("retrieved_at")
    if retrieved_at > reference or not 2000 <= year < reference.year or year > 2099:
        fail("incomplete_year")
    if year >= retrieved_at.astimezone(ZoneInfo("Asia/Seoul")).year:
        fail("retrieved_at")
    if path.resolve().is_relative_to(ROOT):
        fail("repository_input")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        fail("hash")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256:
            fail("hash_or_size")
        encoding, count, rows, markets, quarters = _parse(data, year, reference)
    except ChangeImportError:
        raise
    except Exception:
        raise ChangeImportError("market_changes:source_invalid") from None
    return MarketChangeInput(
        year,
        retrieved_at.astimezone(UTC),
        expected_sha256,
        len(data),
        encoding,
        count,
        rows,
        markets,
        quarters,
    )
