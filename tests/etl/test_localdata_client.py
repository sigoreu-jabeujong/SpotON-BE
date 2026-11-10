from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from etl.localdata.client import LocalDataClient, LocalDataContractError
from etl.localdata.constants import PAGE_SIZE, SEOUL_AUTHORITY_CODES, Source


def envelope(*, page: int, total: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_CODE"},
            "body": {
                "pageNo": page,
                "numOfRows": PAGE_SIZE,
                "totalCount": total,
                "items": {"item": rows} if rows else {},
            },
        }
    }


def row(code: str, number: int) -> dict[str, str]:
    return {"OPN_ATMY_GRP_CD": code, "MNG_NO": f"M-{number}", "TELNO": "010-secret"}


def make_client(handler: Any, *, sleeps: list[float] | None = None) -> LocalDataClient:
    return LocalDataClient(
        SecretStr("key-canary"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_official_seoul_authority_codes_are_fixed() -> None:
    assert len(SEOUL_AUTHORITY_CODES) == 25
    assert len(set(SEOUL_AUTHORITY_CODES.values())) == 25
    assert all(code.isdigit() and len(code) == 7 for code in SEOUL_AUTHORITY_CODES)
    assert SEOUL_AUTHORITY_CODES["3000000"] == "종로구"
    assert SEOUL_AUTHORITY_CODES["3240000"] == "강동구"


def test_collects_multiple_pages_and_sends_fixed_contract() -> None:
    code = "3000000"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["pageNo"])
        rows = [row(code, number) for number in range((page - 1) * 100, min(page * 100, 101))]
        return httpx.Response(200, json=envelope(page=page, total=101, rows=rows))

    result = make_client(handler).collect_authority(Source.GENERAL_RESTAURANT, code)

    assert len(result) == 101
    assert len(requests) == 2
    assert all(request.url.scheme == "https" for request in requests)
    assert requests[0].url.params["numOfRows"] == "100"
    assert requests[0].url.params["cond[OPN_ATMY_GRP_CD::EQ]"] == code
    assert requests[0].url.params["serviceKey"] == "key-canary"
    assert not hasattr(result[0], "TELNO")


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({}, "envelope"),
        ({"response": {"header": {}, "body": {}}}, "result_code"),
        (
            {"response": {"header": {"resultCode": "22"}, "body": {}}},
            "result_code",
        ),
    ],
)
def test_rejects_invalid_contract(payload: dict[str, Any], error: str) -> None:
    client = make_client(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(LocalDataContractError, match=error):
        client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")


def test_rejects_non_json_without_echoing_body() -> None:
    secret_body = "<xml>private-canary</xml>"
    client = make_client(
        lambda _: httpx.Response(200, text=secret_body, headers={"content-type": "application/xml"})
    )
    with pytest.raises(LocalDataContractError) as caught:
        client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    assert secret_body not in str(caught.value)


def test_retries_transient_status_then_succeeds() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "99"}),
            httpx.Response(503),
            httpx.Response(200, json=envelope(page=1, total=0, rows=[])),
        ]
    )
    sleeps: list[float] = []
    client = make_client(lambda _: next(responses), sleeps=sleeps)
    assert client.collect_authority(Source.REST_CAFE, "3000000") == []
    assert sleeps == [30.0, 2]


def test_truncated_page_and_wrong_authority_fail() -> None:
    truncated = make_client(
        lambda _: httpx.Response(
            200,
            json=envelope(page=1, total=101, rows=[row("3000000", 1)]),
        )
    )
    with pytest.raises(LocalDataContractError, match="truncated_page"):
        truncated.collect_authority(Source.GENERAL_RESTAURANT, "3000000")

    wrong = make_client(
        lambda _: httpx.Response(
            200,
            json=envelope(page=1, total=1, rows=[row("3010000", 1)]),
        )
    )
    with pytest.raises(LocalDataContractError, match="authority_filter_ignored"):
        wrong.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
