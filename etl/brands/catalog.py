import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

ENDPOINT = "https://apis.data.go.kr/1130000/FftcBrandRlsInfo2_Service/getBrandinfo"
RULE_VERSION = "ftc-brand-catalog-exact-name-v2"
PAGE_SIZE = 1000
MAX_ROWS = 100000
MAX_PAGE_BYTES = 5 * 1024**2
MAX_RAW_BYTES = 140 * 1024**2
MAX_SNAPSHOT_BYTES = 200 * 1024**2
INDUSTRIES = frozenset({"외식", "서비스", "도소매"})


class BrandsError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise BrandsError("brands:" + code)


def unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(items)
    if len(result) != len(items):
        fail("duplicate_json_key")
    return result


def parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        fail("json_contract")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate_year(year: int) -> None:
    if type(year) is not int or not 2000 <= year <= datetime.now(ZoneInfo("Asia/Seoul")).year:
        fail("year")


def integer(value: object) -> int:
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and re.fullmatch(r"[0-9]{1,9}", value):
        return int(value)
    fail("response_contract")


@dataclass(frozen=True, slots=True, repr=False)
class Brand:
    year: int
    management_no: str
    headquarter_no: str
    name: str
    normalized_name: str
    industry: str
    sub_industry: str


def brand(row: object, year: int) -> Brand:
    if type(row) is not dict or row.get("jngBizCrtraYr") != str(year):
        fail("row_year")
    identifiers = []
    for key in ("brandMnno", "jnghdqrtrsMnno"):
        identifier = row.get(key)
        if (
            type(identifier) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", identifier) is None
        ):
            fail("management_no")
        identifiers.append(identifier)
    values = []
    for key, limit in (("brandNm", 255), ("indutyLclasNm", 100), ("indutyMlsfcNm", 255)):
        value = row.get(key)
        if type(value) is not str or not value.strip() or len(value) > limit or "\x00" in value:
            fail("row_contract")
        values.append(value)
    name, industry, sub = values
    if industry not in INDUSTRIES:
        fail("industry_contract")
    return Brand(year, identifiers[0], identifiers[1], name, normalize_name(name), industry, sub)


def page(
    raw: bytes, year: int, number: int, expected_total: int | None = None
) -> tuple[int, tuple[Brand, ...]]:
    if len(raw) > MAX_PAGE_BYTES:
        fail("page_size")
    data = parse_json(raw)
    if type(data) is not dict or data.get("resultCode") != "00":
        fail("provider_response")
    if integer(data.get("pageNo")) != number or integer(data.get("numOfRows")) != PAGE_SIZE:
        fail("page_contract")
    total = integer(data.get("totalCount"))
    if not 1 <= total <= MAX_ROWS or expected_total is not None and total != expected_total:
        fail("total_contract")
    items = data.get("items")
    size = min(PAGE_SIZE, total - (number - 1) * PAGE_SIZE)
    if type(items) is not list or size < 1 or len(items) != size:
        fail("page_length")
    return total, tuple(brand(row, year) for row in items)


def content_hash(rows: tuple[Brand, ...]) -> str:
    return digest(canonical({"rule_version": RULE_VERSION, "rows": [asdict(row) for row in rows]}))


@dataclass(frozen=True, repr=False)
class Catalog:
    year: int
    rows: tuple[Brand, ...]
    pages: tuple[bytes, ...]
    verification_page: bytes
    collected_at: datetime
    content_sha256: str

    def summary(self) -> dict[str, Any]:
        names = Counter(row.normalized_name for row in self.rows)
        identifiers = Counter(row.management_no for row in self.rows)
        return dict(
            reference_year=self.year,
            rows=len(self.rows),
            page_count=len(self.pages),
            collected_at=self.collected_at.isoformat(),
            content_sha256=self.content_sha256,
            rule_version=RULE_VERSION,
            ambiguous_names=sum(count > 1 for count in names.values()),
            unique_brand_ids=len(identifiers),
            repeated_brand_ids=sum(count > 1 for count in identifiers.values()),
            repeated_rows=sum(count for count in identifiers.values() if count > 1),
            industries=dict(sorted(Counter(row.industry for row in self.rows).items())),
        )


def build_catalog(
    year: int, pages: tuple[bytes, ...], verification: bytes, collected_at: datetime
) -> Catalog:
    validate_year(year)
    if not pages or len(pages) > (MAX_ROWS + PAGE_SIZE - 1) // PAGE_SIZE:
        fail("page_count")
    if sum(map(len, pages)) + len(verification) > MAX_RAW_BYTES:
        fail("raw_size")
    total, first = page(pages[0], year, 1)
    if len(pages) != (total + PAGE_SIZE - 1) // PAGE_SIZE:
        fail("page_count")
    rows = list(first)
    for number, raw in enumerate(pages[1:], 2):
        rows.extend(page(raw, year, number, total)[1])
    check = page(verification, year, 1, total)[1]

    def source_key(row: Brand) -> tuple[str, str]:
        return row.management_no, row.headquarter_no

    if sorted(first, key=source_key) != sorted(check, key=source_key):
        fail("source_changed")
    if len({source_key(row) for row in rows}) != total:
        fail("duplicate_source_key")
    ordered = tuple(sorted(rows, key=source_key))
    if (
        collected_at.tzinfo is None
        or collected_at.utcoffset() != UTC.utcoffset(collected_at)
        or not year <= collected_at.year <= datetime.now(UTC).year
        or collected_at.timestamp() > datetime.now(UTC).timestamp() + 300
    ):
        fail("collection_time")
    return Catalog(year, ordered, pages, verification, collected_at, content_hash(ordered))
