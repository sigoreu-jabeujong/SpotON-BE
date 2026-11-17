import logging
import threading
import time
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from etl.localdata.client import LocalDataClient, LocalDataContractError, LocalDataRequestError
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, Source
from tests.etl.test_localdata_client import envelope, row


def response(request: httpx.Request, total: int = 501) -> httpx.Response:
    code = request.url.params["cond[OPN_ATMY_GRP_CD::EQ]"]
    page = int(request.url.params["pageNo"])
    rows = [row(code, n) for n in range((page - 1) * 100, min(page * 100, total))]
    return httpx.Response(200, json=envelope(page=page, total=total, rows=rows))


def test_parallel_collection_preserves_order_and_caps_inflight_requests() -> None:
    active = maximum = 0
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.01 * (5 - int(request.url.params["pageNo"]) % 4))
            return response(request)
        finally:
            with lock:
                active -= 1

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = LocalDataClient(SecretStr("synthetic-key"), client=transport, workers=4)
        parallel = client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    with httpx.Client(transport=httpx.MockTransport(response)) as transport:
        sequential = LocalDataClient(
            SecretStr("synthetic-key"), client=transport
        ).collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    assert parallel == sequential
    assert 1 < maximum <= 4
    assert active == 0


@pytest.mark.parametrize("workers", [0, 5, True, 1.0])
def test_invalid_workers_rejected_in_library(workers: Any) -> None:
    with pytest.raises(ValueError):
        LocalDataClient(SecretStr("synthetic-key"), workers=workers)


def test_failed_batch_does_not_schedule_next_batch() -> None:
    called: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["pageNo"])
        called.append(page)
        return httpx.Response(400) if page == 2 else response(request, total=1000)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = LocalDataClient(SecretStr("synthetic-key"), client=transport, workers=2)
        with pytest.raises(LocalDataRequestError):
            client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    assert set(called) <= {1, 2, 3}
    assert 2 in called


def test_source_request_estimate_rejects_before_remaining_pages() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        total = 301 if request.url.params["cond[OPN_ATMY_GRP_CD::EQ]"] == "3000000" else 0
        return response(request, total)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = LocalDataClient(SecretStr("synthetic-key"), client=transport, max_requests=26)
        with pytest.raises(LocalDataRequestError, match="request_budget"):
            client.collect(Source.GENERAL_RESTAURANT)
    assert len(requests) == len(SEOUL_AUTHORITY_CODES)
    assert all(request.url.params["pageNo"] == "1" for request in requests)


def test_parallel_logging_and_exception_context_do_not_retain_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "private-http-key-canary"
    logger = logging.getLogger("httpx")
    caplog.set_level(logging.DEBUG, logger="httpx")
    original = logger.level

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["pageNo"] == "1":
            return response(request, total=301)
        raise httpx.ReadError(marker, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = LocalDataClient(
            SecretStr(marker), client=transport, workers=2, sleep=lambda _: None
        )
        with pytest.raises(LocalDataRequestError) as caught:
            client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    assert marker not in caplog.text
    assert marker not in repr(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert logger.level == original


def test_total_change_rejected() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: response(request, 201 if request.url.params["pageNo"] == "1" else 200)
        )
    ) as transport:
        client = LocalDataClient(SecretStr("synthetic-key"), client=transport, workers=2)
        with pytest.raises(LocalDataContractError, match="total_count_changed"):
            client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
