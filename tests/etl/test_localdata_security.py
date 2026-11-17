import httpx
import pytest
from pydantic import SecretStr

from etl.localdata.client import LocalDataClient, LocalDataRequestError
from etl.localdata.constants import Source


@pytest.mark.parametrize("failure", [httpx.ConnectError("network"), httpx.ReadError("read")])
def test_transport_error_does_not_expose_key_or_url(failure: Exception) -> None:
    key = "unique-service-key-canary"

    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    client = LocalDataClient(
        SecretStr(key),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    with pytest.raises(LocalDataRequestError) as caught:
        client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    rendered = repr(caught.value) + str(caught.value)
    assert key not in rendered
    assert "apis.data.go.kr" not in rendered


def test_redirect_is_not_followed_and_is_sanitized() -> None:
    client = LocalDataClient(
        SecretStr("redirect-key-canary"),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(302, headers={"location": "https://example.com/steal"})
            ),
            follow_redirects=False,
        ),
        sleep=lambda _: None,
    )
    with pytest.raises(LocalDataRequestError) as caught:
        client.collect_authority(Source.GENERAL_RESTAURANT, "3000000")
    assert "example.com" not in str(caught.value)
    assert "redirect-key-canary" not in str(caught.value)
