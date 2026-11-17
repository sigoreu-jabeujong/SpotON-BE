import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from app.core.errors import AppError
from app.schemas.common import ErrorCode
from app.schemas.geocode import GeocodeData
from app.services.kakao_local import KakaoLocalService

SECRET = "SECRET-KAKAO-REST-KEY"
ADDRESS = "서울 마포구 양화로 160 2층 201호"


def run(awaitable: Coroutine[Any, Any, GeocodeData]) -> GeocodeData:
    return asyncio.run(awaitable)


def address_document(
    *,
    region: str = "서울",
    gu: str = "마포구",
    dong: str = "동교동",
    main: str = "162",
    sub: str = "1",
    mountain: str = "N",
    x: str = "126.922",
    y: str = "37.5563",
) -> dict[str, object]:
    lot = main if not sub else f"{main}-{sub}"
    return {
        "x": x,
        "y": y,
        "address": {
            "address_name": f"{region} {gu} {dong} {lot}",
            "region_1depth_name": region,
            "region_2depth_name": gu,
            "region_3depth_name": dong,
            "main_address_no": main,
            "sub_address_no": sub,
            "mountain_yn": mountain,
        },
        "road_address": {"address_name": "서울 마포구 양화로 160"},
    }


def service(
    handler: Callable[[httpx.Request], httpx.Response], *, key: str | None = SECRET
) -> KakaoLocalService:
    return KakaoLocalService(
        api_key=key,
        timeout=1,
        transport=httpx.MockTransport(handler),
    )


def app_error(awaitable: Coroutine[Any, Any, GeocodeData]) -> AppError:
    with pytest.raises(AppError) as raised:
        run(awaitable)
    return raised.value


def test_geocode_maps_structured_seoul_address_and_sends_safe_request() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = request.url.params["query"]
        seen["page"] = request.url.params["page"]
        seen["size"] = request.url.params["size"]
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"documents": [address_document(sub="")]})

    result = run(service(handler).geocode(query=ADDRESS, category="cafe"))
    assert result.model_dump() == {
        "address_road": "서울 마포구 양화로 160",
        "address_jibun": "서울 마포구 동교동 162",
        "lat": 37.5563,
        "lng": 126.922,
        "category": "cafe",
        "is_seoul": True,
        "sigungu": "마포구",
        "building_key": "마포구-동교동-162-0",
        "floor_unit": "2층 201호",
        "candidates": [],
    }
    assert seen == {
        "method": "GET",
        "path": "/v2/local/search/address.json",
        "query": ADDRESS,
        "page": "1",
        "size": "5",
        "authorization": f"KakaoAK {SECRET}",
    }


def test_geocode_uses_all_multiple_candidates_in_provider_order() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "documents": [
                    address_document(main="162", sub="1"),
                    address_document(main="163", sub="2"),
                ]
            },
        )

    result = run(service(handler).geocode(query=ADDRESS, category="restaurant"))
    assert len(result.candidates) == 2
    assert result.candidates[0].model_dump() == result.model_dump(exclude={"candidates"})
    assert [candidate.building_key for candidate in result.candidates] == [
        "마포구-동교동-162-1",
        "마포구-동교동-163-2",
    ]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"documents": []}, ErrorCode.ADDRESS_NOT_FOUND),
        ({"documents": [address_document(region="경기")]}, ErrorCode.OUT_OF_SEOUL),
        ({"documents": [{"x": "bad", "y": "37.5"}]}, ErrorCode.UPSTREAM_ERROR),
        ({"not_documents": []}, ErrorCode.UPSTREAM_ERROR),
        (
            {"documents": [address_document(main="", sub="")]},
            ErrorCode.ADDRESS_NOT_FOUND,
        ),
    ],
)
def test_geocode_maps_candidate_outcomes_without_exposing_provider_data(
    payload: dict[str, object], expected: ErrorCode
) -> None:
    error = app_error(
        service(lambda _request: httpx.Response(200, json=payload)).geocode(
            query=ADDRESS,
            category="cafe",
        )
    )
    assert error.code is expected
    assert SECRET not in str(error)
    assert ADDRESS not in str(error)


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_geocode_maps_upstream_http_failure_to_fixed_error(status: int) -> None:
    error = app_error(
        service(lambda _request: httpx.Response(status, text=ADDRESS)).geocode(
            query=ADDRESS,
            category="cafe",
        )
    )
    assert error.code is ErrorCode.UPSTREAM_ERROR
    assert ADDRESS not in str(error)


def test_geocode_missing_key_does_not_call_transport() -> None:
    def unexpected(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("transport must not be called")

    error = app_error(service(unexpected, key=None).geocode(query=ADDRESS, category="cafe"))
    assert error.code is ErrorCode.UPSTREAM_ERROR


def test_geocode_does_not_log_sensitive_input(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    error = app_error(
        service(lambda _request: httpx.Response(200, json={"documents": []})).geocode(
            query=ADDRESS,
            category="cafe",
        )
    )
    assert error.code is ErrorCode.ADDRESS_NOT_FOUND
    assert ADDRESS not in caplog.text
    assert SECRET not in caplog.text
