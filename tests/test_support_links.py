import datetime
import unicodedata
from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.support_catalog import SUPPORT_LINKS
from app.db.dependencies import DatabaseResources
from app.schemas.support import SEOUL_DISTRICTS, SupportLink
from app.services.support_links import get_support_links

PATH = "/api/support-links"
IDS = ["seoulsbdc", "seoulsbdc-edu", "seoul-small-business", "sbiz24"]
URLS = [
    "https://www.seoulsbdc.or.kr/main.do",
    "https://edu.seoulsbdc.or.kr/main/index.jsp",
    "https://news.seoul.go.kr/economy/small-business-supports",
    "https://www.sbiz24.kr",
]


def test_general_catalog_contract_and_no_runtime_io(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unavailable = Mock(side_effect=AssertionError("unexpected I/O"))
    monkeypatch.setattr(DatabaseResources, "get_engine", unavailable)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", unavailable)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unavailable)
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["error"] is None
    links = body["data"]["links"]
    assert [link["id"] for link in links] == IDS
    assert [link["url"] for link in links] == URLS
    assert [link["type"] for link in links] == ["consulting"] + ["support_program"] * 3
    assert [link["region"] for link in links] == ["서울"] * 3 + ["전국"]
    for link in links:
        assert set(link) == {
            "id",
            "org_name",
            "title",
            "description",
            "url",
            "type",
            "region",
            "last_checked",
        }
        assert link["org_name"] and link["title"] and link["description"]
        assert link["last_checked"] == "2026-11-12"
    meta = body["meta"]
    assert meta["source"] == ["R17"] and meta["is_demo"] is False
    assert meta["data_updated_at"] == "2026-11-12"
    assert meta["link_catalog_version"] == "support-links-v1"
    assert meta["prioritization"] == {"status": "not_applied", "reason": "general_links_only"}
    assert all(
        meta[key] is None
        for key in ("as_of", "space", "denominator", "collected_at", "data_version")
    )
    unavailable.assert_not_called()
    assert client.app.state.database.engine is None


def test_all_valid_district_category_combinations_preserve_all_links(client: TestClient) -> None:
    assert len(SEOUL_DISTRICTS) == 25
    baseline = client.get(PATH).json()
    for district in [None, *sorted(SEOUL_DISTRICTS)]:
        for category in [None, "cafe", "restaurant"]:
            params = {k: v for k, v in {"sigungu": district, "category": category}.items() if v}
            response = client.get(PATH, params=params)
            assert response.status_code == 200
            assert response.json() == baseline


@pytest.mark.parametrize(
    "params",
    [
        {"sigungu": ""},
        {"sigungu": "수원시"},
        {"sigungu": "서울특별시 마포구"},
        {"sigungu": " 마포구"},
        {"sigungu": "마포구　"},
        {"sigungu": unicodedata.normalize("NFD", "마포구")},
        {"sigungu": "null"},
        {"category": ""},
        {"category": "Cafe"},
        {"category": "restaurant "},
        {"category": "snack"},
        {"category": "null"},
        {"url": "https://private.invalid/UNTRUSTED_CANARY"},
        {"lat": "37.5"},
        [("sigungu", "마포구"), ("sigungu", "마포구")],
        [("category", "cafe"), ("category", "restaurant")],
    ],
)
def test_invalid_input_is_safe_422(client: TestClient, params: object) -> None:
    response = client.get(PATH, params=params)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "data": None,
        "meta": {},
        "error": {"code": "INVALID_PARAM", "message": "요청 값을 확인해 주세요"},
    }
    assert "UNTRUSTED_CANARY" not in response.text


@pytest.mark.parametrize(
    "url",
    [
        "http://www.sbiz24.kr",
        "https://www.sbiz24.kr.evil.invalid",
        "https://evil.invalid/www.sbiz24.kr",
        "https://user@www.sbiz24.kr",
        "https://www.sbiz24.kr:443",
        "https://www.sbiz24.kr?next=elsewhere",
        "https://www.sbiz24.kr#fragment",
        "https://www.sbiz24.kr?",
        "https://www.sbiz24.kr/\n",
        "https://127.0.0.1/",
        "javascript:alert(1)",
    ],
)
def test_catalog_rejects_unsafe_destinations(url: str) -> None:
    record = SUPPORT_LINKS[0].model_dump()
    record["url"] = url
    with pytest.raises(ValidationError):
        SupportLink.model_validate(record)


def test_catalog_and_response_mutation_are_isolated() -> None:
    with pytest.raises(ValidationError):
        SUPPORT_LINKS[0].url = "https://private.invalid"
    first = get_support_links()
    assert first.data is not None
    first.data.links.clear()
    first.meta["source"] = ["UNTRUSTED_CANARY"]
    second = get_support_links()
    assert second.data is not None and len(second.data.links) == 4
    assert second.meta["source"] == ["R17"]


def test_manual_check_date_does_not_follow_request_clock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class LaterDate(date):
        @classmethod
        def today(cls) -> date:
            return date(2040, 1, 1)

    monkeypatch.setattr(datetime, "date", LaterDate)
    body = client.get(PATH).json()
    assert {row["last_checked"] for row in body["data"]["links"]} == {"2026-11-12"}
    assert body["meta"]["data_updated_at"] == "2026-11-12"


@pytest.mark.parametrize("serialization", [False, True])
def test_internal_errors_are_safe_and_no_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    serialization: bool,
) -> None:
    def broken() -> object:
        if serialization:
            return {"data": {"links": "PRIVATE_FAILURE_CANARY"}}
        raise RuntimeError("PRIVATE_FAILURE_CANARY")

    monkeypatch.setattr("app.routers.support.get_support_links", broken)
    response = client.get(PATH, headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "PRIVATE_FAILURE_CANARY" not in response.text + caplog.text
    assert "unhandled_error type=" in caplog.text


def test_openapi_and_cors(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][PATH]["get"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert set(parameters) == {"sigungu", "category"}
    assert all(p["required"] is False for p in parameters.values())
    assert len(parameters["sigungu"]["schema"]["enum"]) == 25
    assert set(operation["responses"]) == {"200", "422", "500"}
    assert (
        schema["components"]["schemas"]["SupportLink"]["properties"]["last_checked"]["format"]
        == "date"
    )
    response = client.options(
        PATH,
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
