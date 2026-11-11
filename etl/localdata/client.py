import logging
import math
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

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
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise LocalDataContractError(f"contract_error:{name}") from None
    if result < 0 or str(value).strip() not in {str(result), f"+{result}"}:
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
    ) -> None:
        key = service_key.get_secret_value().strip()
        if not key:
            raise LocalDataRequestError("configuration_error:service_key_missing")
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
        result: list[LocalDataRow] = []
        for authority_code in SEOUL_AUTHORITY_CODES:
            result.extend(self.collect_authority(source, authority_code))
        return result

    def collect_authority(self, source: Source, authority_code: str) -> list[LocalDataRow]:
        if authority_code not in SEOUL_AUTHORITY_CODES:
            raise ValueError("지원하지 않는 관청 코드입니다")
        collected: list[LocalDataRow] = []
        expected_total: int | None = None
        max_pages: int | None = None
        page_no = 1
        while True:
            page = self._fetch_page(source, authority_code, page_no)
            if page.page_no != page_no:
                raise LocalDataContractError("contract_error:page_no_mismatch")
            if expected_total is None:
                expected_total = page.total_count
                max_pages = math.ceil(expected_total / PAGE_SIZE)
                if expected_total == 0:
                    if page.rows:
                        raise LocalDataContractError("contract_error:unexpected_rows")
                    return []
            elif page.total_count != expected_total:
                raise LocalDataContractError("contract_error:total_count_changed")

            if any(row.authority_code != authority_code for row in page.rows):
                raise LocalDataContractError("contract_error:authority_filter_ignored")
            if len(page.rows) > PAGE_SIZE:
                raise LocalDataContractError("contract_error:page_size_exceeded")
            collected.extend(page.rows)
            if len(collected) > expected_total:
                raise LocalDataContractError("contract_error:row_count_exceeded")
            if len(collected) == expected_total:
                return collected
            if not page.rows or len(page.rows) < PAGE_SIZE:
                raise LocalDataContractError("contract_error:truncated_page")
            page_no += 1
            if max_pages is None or page_no > max_pages:
                raise LocalDataContractError("contract_error:max_pages_exceeded")

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
            try:
                with _suppress_http_url_logs():
                    response = self._client.get(SOURCE_ENDPOINTS[source], params=params)
            except httpx.TransportError:
                if attempt == MAX_ATTEMPTS:
                    raise LocalDataRequestError(
                        f"request_error:transport source={source} page={page_no}"
                    ) from None
                self._sleep(min(2 ** (attempt - 1), MAX_RETRY_DELAY_SECONDS))
                continue
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
        return self._parse_page(response, page_no)

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), MAX_RETRY_DELAY_SECONDS)
            except ValueError:
                pass
        return min(float(2 ** (attempt - 1)), MAX_RETRY_DELAY_SECONDS)

    @staticmethod
    def _parse_page(response: httpx.Response, requested_page: int) -> Page:
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            raise LocalDataContractError("contract_error:non_json_response")
        try:
            payload = response.json()
        except ValueError:
            raise LocalDataContractError("contract_error:invalid_json") from None
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
