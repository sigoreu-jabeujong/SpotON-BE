import datetime
import unicodedata
from datetime import date
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.support_catalog import DISTRICT_CONTACTS, SUPPORT_LINKS
from app.core.support_sources import MSS_NOTICE_URL
from app.db.dependencies import DatabaseResources
from app.schemas.support import SEOUL_DISTRICTS, SupportLink, SupportLinksQuery
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
    assert meta["link_catalog_version"] == "support-links-v2"
    assert meta["prioritization"] == {"status": "not_applied", "reason": "general_links_only"}
    assert all(
        meta[key] is None
        for key in ("as_of", "space", "denominator", "collected_at", "data_version")
    )
    unavailable.assert_not_called()
    assert client.app.state.database.engine is None
    regional = client.get(PATH, params={"sigungu": "마포구"})
    assert regional.status_code == 200 and len(regional.json()["data"]["links"]) == 5
    unavailable.assert_not_called()
    assert client.app.state.database.engine is None


def test_all_valid_district_category_combinations_preserve_general_links(
    client: TestClient,
) -> None:
    assert len(SEOUL_DISTRICTS) == 25
    baseline = client.get(PATH).json()
    for district in [None, *sorted(SEOUL_DISTRICTS)]:
        for category in [None, "cafe", "restaurant"]:
            params = {k: v for k, v in {"sigungu": district, "category": category}.items() if v}
            response = client.get(PATH, params=params)
            assert response.status_code == 200
            body = response.json()
            if district is None:
                assert body == baseline
                assert "district_contact_source" not in body["meta"]
            else:
                assert len(body["data"]["links"]) == 5
                assert body["data"]["links"][1:] == baseline["data"]["links"]
                assert body == client.get(PATH, params={"sigungu": district}).json()


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
    for params in ({}, {"sigungu": "마포구"}):
        body = client.get(PATH, params=params).json()
        assert {row["last_checked"] for row in body["data"]["links"]} == {"2026-11-12"}
        assert body["meta"]["data_updated_at"] == "2026-11-12"


@pytest.mark.parametrize("serialization", [False, True])
def test_internal_errors_are_safe_and_no_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    serialization: bool,
) -> None:
    def broken(query: SupportLinksQuery) -> object:
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


# Independent expected mapping transcribed from the reviewed 2026-576 notice, annex2 p25.
EXPECTED_CONTACTS = {
    "중구": ("jungbu", "02-720-4711"),
    "종로구": ("jungbu", "02-720-4711"),
    "성북구": ("jungbu", "02-720-4711"),
    "동대문구": ("jungbu", "02-720-4711"),
    "광진구": ("dongbu", "02-2215-0981"),
    "성동구": ("dongbu", "02-2215-0981"),
    "강동구": ("dongbu", "02-2215-0981"),
    "중랑구": ("dongbu", "02-2215-0981"),
    "강서구": ("seobu", "02-839-8311"),
    "양천구": ("seobu", "02-839-8311"),
    "영등포구": ("seobu", "02-839-8311"),
    "강남구": ("nambu", "02-585-8622"),
    "서초구": ("nambu", "02-585-8622"),
    "송파구": ("nambu", "02-585-8622"),
    "노원구": ("bukbu", "02-990-9101"),
    "도봉구": ("bukbu", "02-990-9101"),
    "강북구": ("bukbu", "02-990-9101"),
    "동작구": ("dongjak", "02-3482-6686"),
    "용산구": ("dongjak", "02-3482-6686"),
    "관악구": ("gwanak", "02-889-9262"),
    "구로구": ("gwanak", "02-889-9262"),
    "금천구": ("gwanak", "02-889-9262"),
    "서대문구": ("seodaemun", "02-323-2915"),
    "은평구": ("seodaemun", "02-323-2915"),
    "마포구": ("seodaemun", "02-323-2915"),
}


def test_catalog_covers_exactly_25_districts_without_overlap():
    from collections import Counter

    counts = Counter(d for item in DISTRICT_CONTACTS for d in item.districts)
    assert set(counts) == SEOUL_DISTRICTS == set(EXPECTED_CONTACTS)
    assert set(counts.values()) == {1} and len(DISTRICT_CONTACTS) == 8
    assert sorted(len(item.districts) for item in DISTRICT_CONTACTS) == [2, 3, 3, 3, 3, 3, 4, 4]


def test_reviewed_notice_constant_has_only_the_official_destination():
    url = urlsplit(MSS_NOTICE_URL)
    assert url.scheme == "https" and url.netloc == "www.mss.go.kr"
    assert url.path == "/site/smba/ex/bbs/View.do" and not url.fragment
    assert url.username is None and url.password is None and url.port is None
    assert parse_qsl(url.query) == [
        ("bcIdx", "1071565"),
        ("cbIdx", "310"),
        ("parentSeq", "1071565"),
    ]


@pytest.mark.parametrize("district", sorted(EXPECTED_CONTACTS))
def test_district_contact_matches_official_mapping_and_safe_meta(client, district):
    body = client.get(PATH, params={"sigungu": district}).json()
    links = body["data"]["links"]
    center, phone = EXPECTED_CONTACTS[district]
    assert links[0]["id"] == "semas-seoul-" + center
    assert phone in links[0]["description"] and district in links[0]["description"]
    assert "첨부 PDF 25쪽" in links[0]["description"]
    assert links[0]["url"] == MSS_NOTICE_URL
    assert links[0]["type"] == "consulting" and links[0]["region"] == "서울"
    assert len({x["id"] for x in links}) == 5 and set(links[0]) == set(links[1])
    assert body["meta"]["prioritization"] == {
        "status": "applied",
        "reason": "district_contact_first",
        "category_applied": False,
    }
    assert body["meta"]["district_contact_source"] == {
        "url": MSS_NOTICE_URL,
        "published_on": "2026-10-01",
        "checked_on": "2026-11-12",
        "page": 25,
        "table": "annex_2",
    }
    assert links[0]["last_checked"] == body["meta"]["data_updated_at"] == "2026-11-12"
    assert all(
        word not in links[0]["title"] + links[0]["description"]
        for word in [
            "맞춤",
            "추천",
            "신청 가능",
            "대출 가능",
            "자격",
            "FAX",
        ]
    )


@pytest.mark.parametrize(
    "url",
    [
        MSS_NOTICE_URL.replace("https:", "http:"),
        MSS_NOTICE_URL.replace("www.mss.go.kr", "WWW.MSS.GO.KR"),
        MSS_NOTICE_URL.replace("www.mss.go.kr", "www.mss.go.kr.evil.invalid"),
        MSS_NOTICE_URL.replace("www.mss.go.kr", "user@www.mss.go.kr"),
        MSS_NOTICE_URL.replace("www.mss.go.kr", "www.mss.go.kr:443"),
        MSS_NOTICE_URL.replace("bcIdx=1071565&cbIdx=310", "cbIdx=310&bcIdx=1071565"),
        MSS_NOTICE_URL.replace("&", "&amp;"),
        MSS_NOTICE_URL.replace("&", "%26"),
        MSS_NOTICE_URL.replace("=", "%3D"),
        MSS_NOTICE_URL + "&next=PRIVATE_CANARY",
        MSS_NOTICE_URL + "&",
        MSS_NOTICE_URL + "#fragment",
        MSS_NOTICE_URL + "&cbIdx=310",
        MSS_NOTICE_URL.replace("1071565", "1071566"),
        MSS_NOTICE_URL.replace("&parentSeq=1071565", ""),
        "https://www.mss.go.kr/",
        "https://www.mss.go.kr/common/board/Download.do?bcIdx=1071565",
    ],
)
def test_only_exact_reviewed_notice_url_is_allowed(url):
    record = SUPPORT_LINKS[0].model_dump()
    record["url"] = url
    with pytest.raises(ValidationError):
        SupportLink.model_validate(record)


def test_regional_response_and_catalog_are_isolated():
    query = SupportLinksQuery(sigungu="마포구")
    with pytest.raises(ValidationError):
        DISTRICT_CONTACTS[0].link.title = "PRIVATE_CANARY"
    with pytest.raises(AttributeError):
        DISTRICT_CONTACTS[0].districts.add("PRIVATE_CANARY")
    first = get_support_links(query)
    first.data.links.clear()
    first.meta["district_contact_source"]["url"] = "PRIVATE_CANARY"
    second = get_support_links(query)
    assert second.data.links[0].id == "semas-seoul-seodaemun"
    assert second.meta["district_contact_source"]["url"] == MSS_NOTICE_URL


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_ambiguous_catalog_does_not_claim_prioritization(client, monkeypatch, duplicate):
    contacts = (DISTRICT_CONTACTS[-1],) * 2 if duplicate else ()
    monkeypatch.setattr("app.services.support_links.DISTRICT_CONTACTS", contacts)
    response = client.get(PATH, params={"sigungu": "마포구"})
    assert response.status_code == 500 and response.headers["cache-control"] == "no-store"
    assert response.json()["data"] is None and response.json()["meta"] == {}
