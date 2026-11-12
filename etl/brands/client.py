from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
from pydantic import SecretStr

from etl.brands.catalog import (
    ENDPOINT,
    MAX_PAGE_BYTES,
    MAX_RAW_BYTES,
    PAGE_SIZE,
    Catalog,
    build_catalog,
    fail,
    page,
    validate_year,
)
from etl.localdata.client import _suppress_http_url_logs


def collect(year: int, key: SecretStr | None, *, client: httpx.Client | None = None) -> Catalog:
    validate_year(year)
    if key is None or not key.get_secret_value().strip():
        fail("missing_key")
    if client is None:
        with httpx.Client(timeout=20, follow_redirects=False) as owned:
            return collect(year, key, client=owned)
    secret = key.get_secret_value().strip()
    if "%" in secret:
        secret = unquote(secret)

    def request(number: int) -> bytes:
        try:
            with client.stream(
                "GET",
                ENDPOINT,
                follow_redirects=False,
                params=dict(
                    serviceKey=secret,
                    pageNo=number,
                    numOfRows=PAGE_SIZE,
                    resultType="json",
                    jngBizCrtraYr=year,
                ),
            ) as response:
                if response.status_code != 200:
                    fail("http_status")
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        fail("page_size")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError:
            fail("request_failed")

    with _suppress_http_url_logs():
        first = request(1)
        total, _ = page(first, year, 1)
        pages = [first]
        size = len(first)
        for number in range(2, (total + PAGE_SIZE - 1) // PAGE_SIZE + 1):
            raw = request(number)
            page(raw, year, number, total)
            size += len(raw)
            if size > MAX_RAW_BYTES:
                fail("raw_size")
            pages.append(raw)
        verification = request(1)
        return build_catalog(year, tuple(pages), verification, datetime.now(UTC))
