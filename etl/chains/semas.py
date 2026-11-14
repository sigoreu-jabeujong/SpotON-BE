import math
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from etl.brands.catalog import parse_json
from etl.chains.common import digest, fail
from etl.localdata.client import _suppress_http_url_logs

ENDPOINT = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"
QUERY = {"divId": "ctprvnCd", "key": "11", "indsLclsCd": "I2", "type": "json"}
PAGE_SIZE = 1000
MAX_ROWS = 250000
MAX_PAGE_BYTES = 5 * 1024**2
MAX_BYTES = 256 * 1024**2
SCHEMA = "semas-seoul-food-projection-v1"


class Outlet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    source_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$", repr=False)
    name: str = Field(min_length=1, max_length=255, repr=False)
    branch: str = Field(max_length=255, repr=False)
    road: str = Field(max_length=1000, repr=False)
    jibun: str = Field(max_length=1000, repr=False)
    building_no: str = Field(max_length=64, repr=False)
    floor: str = Field(max_length=50, repr=False)
    unit: str = Field(max_length=50, repr=False)
    gu_code: str = Field(pattern=r"^11[0-9]{3}$")
    industry_middle: str = Field(pattern=r"^I2[A-Za-z0-9]{0,10}$")
    industry_small: str = Field(pattern=r"^I2[A-Za-z0-9]{0,10}$")
    lat: float | None = Field(ge=-90, le=90, strict=True, allow_inf_nan=False, repr=False)
    lng: float | None = Field(ge=-180, le=180, strict=True, allow_inf_nan=False, repr=False)

    @model_validator(mode="after")
    def valid(self) -> "Outlet":
        for value in (
            self.name,
            self.branch,
            self.road,
            self.jibun,
            self.building_no,
            self.floor,
            self.unit,
        ):
            if value != value.strip() or any(ord(c) < 32 for c in value):
                raise ValueError("text_contract")
        if (self.lat is None) != (self.lng is None) or self.lat == 0 or self.lng == 0:
            raise ValueError("coordinate_pair")
        if self.lat is not None and self.lng is not None:
            if not (37 <= self.lat <= 38 and 126 <= self.lng <= 128):
                raise ValueError("coordinate_scope")
        return self


def _text(row: dict[str, Any], key: str, required: bool = False) -> str:
    value = row.get(key)
    if value is None and not required:
        return ""
    if type(value) is not str or (required and not value.strip()):
        fail("item_contract")
    if any(ord(c) < 32 for c in value):
        fail("item_contract")
    return value.strip()


def _coord(value: Any, low: int, high: int) -> float | None:
    if type(value) not in (str, int, float):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and low <= result <= high else None


def project(row: Any) -> Outlet:
    if type(row) is not dict or row.get("ctprvnCd") != "11" or row.get("indsLclsCd") != "I2":
        fail("item_scope")
    lat, lng = _coord(row.get("lat"), -90, 90), _coord(row.get("lon"), -180, 180)
    if lat is None or lng is None or not (37 <= lat <= 38 and 126 <= lng <= 128):
        lat = lng = None
    try:
        return Outlet(
            source_id=_text(row, "bizesId", True),
            name=_text(row, "bizesNm", True),
            branch=_text(row, "brchNm"),
            road=_text(row, "rdnmAdr"),
            jibun=_text(row, "lnoAdr"),
            building_no=_text(row, "bldMngNo"),
            floor=_text(row, "flrNo"),
            unit=_text(row, "hoNo"),
            gu_code=_text(row, "signguCd", True),
            industry_middle=_text(row, "indsMclsCd", True),
            industry_small=_text(row, "indsSclsCd", True),
            lat=lat,
            lng=lng,
        )
    except ValidationError:
        fail("item_contract")


def integer(value: Any) -> int:
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and re.fullmatch(r"[0-9]{1,9}", value):
        return int(value)
    fail("page_contract")


def validate_month(value: Any) -> str:
    if (
        type(value) is not str
        or not re.fullmatch(r"20[0-9]{2}(0[1-9]|1[0-2])", value)
        or value > datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m")
    ):
        fail("reference_month")
    return value


def page(raw: bytes, number: int) -> tuple[str, int, tuple[Outlet, ...]]:
    if len(raw) > MAX_PAGE_BYTES:
        fail("page_size")
    try:
        value = parse_json(raw)
    except ValueError:
        fail("json_contract")
    if type(value) is not dict:
        fail("page_contract")
    header, body = value.get("header"), value.get("body")
    if type(header) is not dict or type(body) is not dict or header.get("resultCode") != "00":
        fail("provider_response")
    month = validate_month(header.get("stdrYm"))
    total = integer(body.get("totalCount"))
    if (
        not 1 <= total <= MAX_ROWS
        or integer(body.get("pageNo")) != number
        or integer(body.get("numOfRows")) != PAGE_SIZE
    ):
        fail("page_contract")
    items = body.get("items")
    expected = min(PAGE_SIZE, max(0, total - (number - 1) * PAGE_SIZE))
    if type(items) is not list or len(items) != expected:
        fail("page_length")
    return month, total, tuple(project(row) for row in items)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: str = SCHEMA
    endpoint: str = ENDPOINT
    query: dict[str, str] = Field(default_factory=lambda: dict(QUERY), repr=False)
    reference_month: str
    observed_at: datetime
    rows: tuple[Outlet, ...] = Field(repr=False)
    content_sha256: str
    request_count: int = Field(strict=True, ge=2, le=251)
    consistency: str = "all_pages_scope_month_total_unique_and_first_page_rechecked"


def content_hash(rows: tuple[Outlet, ...]) -> str:
    return digest([r.model_dump(mode="json") for r in sorted(rows, key=lambda r: r.source_id)])


def validate_snapshot(snapshot: Snapshot) -> Snapshot:
    if (
        snapshot.schema_version != SCHEMA
        or snapshot.endpoint != ENDPOINT
        or snapshot.query != QUERY
        or not 1 <= len(snapshot.rows) <= MAX_ROWS
        or snapshot.consistency != "all_pages_scope_month_total_unique_and_first_page_rechecked"
    ):
        fail("snapshot_contract")
    validate_month(snapshot.reference_month)
    now = datetime.now(UTC)
    observed = snapshot.observed_at
    if (
        observed.tzinfo is None
        or observed.utcoffset() != UTC.utcoffset(observed)
        or observed > now.replace(microsecond=0)
        and (observed - now).total_seconds() > 300
        or observed.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m") < snapshot.reference_month
    ):
        fail("observation_time")
    expected_requests = max(1, (len(snapshot.rows) + PAGE_SIZE - 1) // PAGE_SIZE) + 1
    if (
        type(snapshot.request_count) is not int
        or snapshot.request_count != expected_requests
        or len({r.source_id for r in snapshot.rows}) != len(snapshot.rows)
        or content_hash(snapshot.rows) != snapshot.content_sha256
    ):
        fail("snapshot_hash_or_count")
    return snapshot


def collect(key: SecretStr | None, *, client: httpx.Client | None = None) -> Snapshot:
    if key is None or not key.get_secret_value().strip():
        fail("missing_key")
    if client is None:
        with httpx.Client(timeout=20, follow_redirects=False) as owned:
            return collect(key, client=owned)
    secret = unquote(key.get_secret_value().strip())
    raw_bytes = 0
    count = 0

    def request(number: int) -> bytes:
        nonlocal raw_bytes, count
        count += 1
        if count > MAX_ROWS // PAGE_SIZE + 1:
            fail("request_budget")
        start = time.monotonic()
        try:
            with client.stream(
                "GET",
                ENDPOINT,
                params={**QUERY, "ServiceKey": secret, "pageNo": number, "numOfRows": PAGE_SIZE},
                follow_redirects=False,
                timeout=20,
            ) as response:
                if response.status_code != 200:
                    fail("http_status")
                parts = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    raw_bytes += len(chunk)
                    if size > MAX_PAGE_BYTES or raw_bytes > MAX_BYTES:
                        fail("response_size")
                    if time.monotonic() - start > 60:
                        fail("response_deadline")
                    parts.append(chunk)
                return b"".join(parts)
        except httpx.HTTPError:
            fail("request_failed")

    with _suppress_http_url_logs():
        first_month, total, first = page(request(1), 1)
        rows = list(first)
        for number in range(2, max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) + 1):
            month, current_total, values = page(request(number), number)
            if month != first_month or current_total != total:
                fail("source_changed")
            rows.extend(values)
        month, current_total, check = page(request(1), 1)
        if (
            month != first_month
            or current_total != total
            or content_hash(first) != content_hash(check)
            or len({r.source_id for r in rows}) != total
        ):
            fail("source_changed_or_duplicate")
    ordered = tuple(sorted(rows, key=lambda r: r.source_id))
    return validate_snapshot(
        Snapshot(
            reference_month=first_month,
            observed_at=datetime.now(UTC),
            rows=ordered,
            content_sha256=content_hash(ordered),
            request_count=count,
        )
    )
