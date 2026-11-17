import logging
import math
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

from etl.localdata.collection import AuthorityStats, CollectedSource
from etl.localdata.constants import (
    PAGE_SIZE,
    SEOUL_AUTHORITY_CODES,
    SOURCE_ENDPOINTS,
    SUCCESS_RESULT_CODES,
    Source,
)
from etl.localdata.dto import LocalDataRow

TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 30.0


class LocalDataError(RuntimeError):
    """요청 원문이나 개인정보를 포함하지 않는 ETL 오류."""


class LocalDataRequestError(LocalDataError):
    pass


class LocalDataContractError(LocalDataError):
    pass


@dataclass(frozen=True, slots=True)
class Page:
    page_no: int
    total_count: int
    rows: tuple[LocalDataRow, ...]


def _safe_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise LocalDataContractError(f"contract_error:{name}")
    if isinstance(value, str) and not value.isascii():
        raise LocalDataContractError(f"contract_error:{name}")
    result: int | None = None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        pass
    if result is None or result < 0 or str(value).strip() not in {str(result), f"+{result}"}:
        raise LocalDataContractError(f"contract_error:{name}")
    return result


@contextmanager
def _suppress_http_url_logs() -> Iterator[None]:
    loggers = [logging.getLogger("httpx"), logging.getLogger("httpcore")]
    previous = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.WARNING)
        yield
    finally:
        for logger, level in zip(loggers, previous, strict=True):
            logger.setLevel(level)


class LocalDataClient:
    def __init__(
        self,
        service_key: SecretStr,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        workers: int = 1,
        max_requests: int | None = None,
        progress: Callable[[Source, str, int, int], None] | None = None,
    ) -> None:
        key = service_key.get_secret_value().strip()
        if not key:
            raise LocalDataRequestError("configuration_error:service_key_missing")
        if type(workers) is not int or not 1 <= workers <= 4:
            raise ValueError("workers must be an integer from 1 to 4")
        if max_requests is not None and (type(max_requests) is not int or max_requests < 1):
            raise ValueError("max_requests must be positive")
        self._workers = workers
        self._max_requests = max_requests
        self._progress = progress
        self.request_count = 0
        self._request_lock = Lock()
        self._service_key = service_key
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0, read=20.0, write=10.0, pool=5.0),
            follow_redirects=False,
        )
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "LocalDataClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def collect_source(self, source: Source) -> list[LocalDataRow]:
        return list(self.collect(source).rows)

    def collect(self, source: Source) -> CollectedSource:
        started = datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None, microsecond=0)
        initial_requests = self.request_count
        with _suppress_http_url_logs():
            first_pages: dict[str, Page] = {}
            for code in SEOUL_AUTHORITY_CODES:
                first_pages[code] = self._fetch_page(source, code, 1)
                if self._progress is not None:
                    self._progress(source, code, 0, first_pages[code].total_count)
            remaining = sum(
                max(math.ceil(page.total_count / PAGE_SIZE) - 1, 0) for page in first_pages.values()
            )
            if self._progress is not None:
                self._progress(source, "all", 0, len(first_pages) + remaining)
            if (
                self._max_requests is not None
                and self.request_count + remaining > self._max_requests
            ):
                raise LocalDataRequestError("request_error:request_budget")
            rows: list[LocalDataRow] = []
            stats: list[AuthorityStats] = []
            for code, first in first_pages.items():
                authority_rows = self._collect_authority(source, code, first)
                rows.extend(authority_rows)
                stats.append(
                    AuthorityStats(
                        code,
                        first.total_count,
                        max(math.ceil(first.total_count / PAGE_SIZE), 1),
                        len(authority_rows),
                    )
                )
        return CollectedSource(
            source, started, tuple(stats), tuple(rows), self.request_count - initial_requests
        )

    def collect_authority(self, source: Source, authority_code: str) -> list[LocalDataRow]:
        if authority_code not in SEOUL_AUTHORITY_CODES:
            raise ValueError("지원하지 않는 관청 코드입니다")
        with _suppress_http_url_logs():
            first = self._fetch_page(source, authority_code, 1)
            return self._collect_authority(source, authority_code, first)

    def _collect_authority(
        self, source: Source, authority_code: str, first: Page
    ) -> list[LocalDataRow]:
        collected: list[LocalDataRow] = []
        expected_total = first.total_count
        max_pages = max(math.ceil(expected_total / PAGE_SIZE), 1)

        def accept(page_no: int, page: Page) -> None:
            if page.page_no != page_no:
                raise LocalDataContractError("contract_error:page_no_mismatch")
            if page.total_count != expected_total:
                raise LocalDataContractError("contract_error:total_count_changed")
            if any(
                row.authority_code is not None and row.authority_code != authority_code
                for row in page.rows
            ):
                raise LocalDataContractError("contract_error:authority_filter_ignored")
            if len(page.rows) > PAGE_SIZE:
                raise LocalDataContractError("contract_error:page_size_exceeded")
            if page_no < max_pages and len(page.rows) != PAGE_SIZE:
                raise LocalDataContractError("contract_error:truncated_page")
            collected.extend(page.rows)
            if len(collected) > expected_total:
                raise LocalDataContractError("contract_error:row_count_exceeded")
            if self._progress is not None and (
                page_no == 1 or page_no == max_pages or page_no % 50 == 0
            ):
                self._progress(source, authority_code, page_no, expected_total)

        accept(1, first)
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for start in range(2, max_pages + 1, self._workers):
                page_numbers = range(start, min(start + self._workers, max_pages + 1))
                pages = pool.map(
                    lambda page_no: self._fetch_page(source, authority_code, page_no), page_numbers
                )
                for page_no, page in zip(page_numbers, pages, strict=True):
                    accept(page_no, page)
        if len(collected) != expected_total:
            raise LocalDataContractError("contract_error:truncated_page")
        return collected

    def _fetch_page(self, source: Source, authority_code: str, page_no: int) -> Page:
        params = {
            "serviceKey": self._service_key.get_secret_value(),
            "pageNo": str(page_no),
            "numOfRows": str(PAGE_SIZE),
            "returnType": "JSON",
            "cond[OPN_ATMY_GRP_CD::EQ]": authority_code,
        }
        response: httpx.Response | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            with self._request_lock:
                if self._max_requests is not None and self.request_count >= self._max_requests:
                    raise LocalDataRequestError("request_error:request_budget")
                self.request_count += 1
            transport_failed = False
            try:
                with _suppress_http_url_logs():
                    response = self._client.get(SOURCE_ENDPOINTS[source], params=params)
            except httpx.TransportError:
                transport_failed = True
            if transport_failed:
                if attempt == MAX_ATTEMPTS:
                    raise LocalDataRequestError(
                        f"request_error:transport source={source} page={page_no}"
                    )
                self._sleep(min(2 ** (attempt - 1), MAX_RETRY_DELAY_SECONDS))
                continue
            assert response is not None
            if response.status_code in TRANSIENT_STATUS_CODES and attempt < MAX_ATTEMPTS:
                self._sleep(self._retry_delay(response, attempt))
                continue
            break
        if response is None:
            raise LocalDataRequestError("request_error:no_response")
        if response.status_code != 200:
            raise LocalDataRequestError(
                f"request_error:http_{response.status_code} source={source} page={page_no}"
            )
        page = self._parse_page(response, page_no)
        if any(
            row.authority_code is not None and row.authority_code != authority_code
            for row in page.rows
        ):
            raise LocalDataContractError("contract_error:authority_filter_ignored")
        return page

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                seconds = float(retry_after)
                if math.isfinite(seconds):
                    return min(max(seconds, 0.0), MAX_RETRY_DELAY_SECONDS)
            except ValueError:
                pass
        return min(float(2 ** (attempt - 1)), MAX_RETRY_DELAY_SECONDS)

    @staticmethod
    def _parse_page(response: httpx.Response, requested_page: int) -> Page:
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            raise LocalDataContractError("contract_error:non_json_response")
        parsed = True
        try:
            payload = response.json()
        except ValueError:
            parsed = False
            payload = None
        if not parsed:
            raise LocalDataContractError("contract_error:invalid_json")
        if not isinstance(payload, Mapping):
            raise LocalDataContractError("contract_error:envelope")
        envelope = payload.get("response")
        if not isinstance(envelope, Mapping):
            raise LocalDataContractError("contract_error:envelope")
        header = envelope.get("header")
        body = envelope.get("body")
        if not isinstance(header, Mapping) or not isinstance(body, Mapping):
            raise LocalDataContractError("contract_error:envelope")
        result_code = header.get("resultCode")
        success = (type(result_code) is int and result_code == 0) or (
            isinstance(result_code, str) and result_code in SUCCESS_RESULT_CODES
        )
        if not success:
            raise LocalDataContractError("contract_error:result_code")
        page_no = _safe_int(body.get("pageNo"), name="page_no")
        total_count = _safe_int(body.get("totalCount"), name="total_count")
        items = body.get("items")
        raw_rows: object
        if total_count == 0 and items in (None, "", {}):
            raw_rows = []
        elif isinstance(items, Mapping):
            raw_rows = items.get("item")
        else:
            raise LocalDataContractError("contract_error:items")
        if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
            raise LocalDataContractError("contract_error:rows")
        if raw_rows and any(
            not any(key in row for row in raw_rows) for key in ("MNG_NO", "OPN_ATMY_GRP_CD")
        ):
            raise LocalDataContractError("contract_error:required_fields")
        rows = tuple(LocalDataRow.from_api(row) for row in raw_rows)
        if page_no != requested_page:
            raise LocalDataContractError("contract_error:page_no_mismatch")
        return Page(page_no=page_no, total_count=total_count, rows=rows)
