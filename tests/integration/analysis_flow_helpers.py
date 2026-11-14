"""Synthetic end-to-end BE fixtures; no real source data or network credentials."""

import json
from collections import Counter
from dataclasses import replace
from datetime import datetime

import httpx
from pydantic import SecretStr
from sqlalchemy import text

from app.ai.client import LlmError, LlmErrorKind, LlmResult, LlmUsage
from app.core.config import Settings
from app.main import create_app
from app.routers.geocode import get_geocode_service
from app.services.kakao_local import KakaoLocalService
from etl.localdata import runner
from etl.localdata.collection import AuthorityStats, CollectedSource
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, Source
from etl.localdata.dto import LocalDataRow
from etl.localdata.snapshot import save_snapshot

LAT, LNG = 37.552268, 127.000788
ROAD = "서울특별시 마포구 테스트로 1"
JIBUN = "서울특별시 마포구 서교동 123-4"
KEY = "마포구-서교동-123-4"
PRIVATE = "CANARY_STORE_76"
ENDPOINTS = {
    "/api/v2/brands/status",
    "/api/v2/stores/history",
    "/api/v2/stores/nearby",
    "/api/v2/stores/snapshot",
    "/api/v2/market/activity",
    "/api/v2/risk",
    "/api/health",
    "/api/ready",
    "/api/geocode",
    "/api/stores/history",
    "/api/meta/data-range",
    "/api/stores/nearby",
    "/api/stores/snapshot",
    "/api/market/activity",
    "/api/risk",
    "/api/risk/interpret",
    "/api/support-links",
}


def raw(identity, **changes):
    values = {
        "OPN_ATMY_GRP_CD": "3130000",
        "MNG_NO": identity,
        "BPLC_NM": PRIVATE,
        "ROAD_NM_ADDR": ROAD + " 2층 201호",
        "LOTNO_ADDR": JIBUN,
        "SALS_STTS_CD": "01",
        "SALS_STTS_NM": "영업/정상",
        "SNTTN_BZSTAT_NM": "한식",
        "LCPMT_YMD": "20200101",
        "CRD_INFO_X": "200000",
        "CRD_INFO_Y": "450000",
        "DAT_UPDT_SE": "U",
        "DAT_UPDT_PNT": "20261108000000",
        "LCTN_AREA": "50",
    }
    return LocalDataRow.from_api({**values, **changes})


def rows(source):
    if source == Source.REST_CAFE:
        return (
            raw(
                "FLOW_SHARED",
                SNTTN_BZSTAT_NM="커피숍",
                LCPMT_YMD="20261108",
                DAT_UPDT_PNT="20261107000000",
                LCTN_AREA="20",
            ),
        )
    return (
        raw("FLOW_SHARED"),
        raw("FLOW_ZERO", LCTN_AREA="0", LCPMT_YMD="20250101", ROAD_NM_ADDR=ROAD + " 2층"),
        raw(
            "FLOW_WESTERN",
            SNTTN_BZSTAT_NM="경양식",
            LCTN_AREA="10",
            LCPMT_YMD="20240101",
            ROAD_NM_ADDR=ROAD + " 3층 301호",
        ),
        raw("FLOW_CLOSED", CLSBIZ_YMD="20260201", SALS_STTS_CD="03", SALS_STTS_NM="폐업"),
        raw("FLOW_NO_COORD", CRD_INFO_X=None, CRD_INFO_Y=None, LCTN_AREA="20"),
        raw(
            "FLOW_CLOSED_NO_COORD",
            CRD_INFO_X=None,
            CRD_INFO_Y=None,
            CLSBIZ_YMD="20260201",
            SALS_STTS_CD="03",
            SALS_STTS_NM="폐업",
        ),
        raw("FLOW_NO_OPEN", LCPMT_YMD=None),
        raw("FLOW_NO_CLOSE", SALS_STTS_CD="03", SALS_STTS_NM="폐업"),
        raw(
            "FLOW_NEIGHBOR",
            LOTNO_ADDR="서울특별시 마포구 서교동 124-4",
            CLSBIZ_YMD="20210101",
            SALS_STTS_CD="03",
            SALS_STTS_NM="폐업",
        ),
    )


def import_source(database, monkeypatch, directory, source, values=None):
    # Never obtain an engine from .env; only this fixture-created database can be written.
    with database.engine.connect() as conn:
        assert conn.scalar(text("SELECT current_database()")) == database.database_name
    monkeypatch.setattr(runner, "validate_local_target", lambda settings: None)
    monkeypatch.setattr(runner, "check_local_database", lambda conn: None)
    monkeypatch.setattr(runner, "create_db_engine", lambda settings: database.engine)
    values = rows(source) if values is None else values
    counts = Counter(v.authority_code for v in values)
    collection = CollectedSource(
        source,
        datetime(2026, 11, 12, 0),
        tuple(AuthorityStats(c, counts[c], 1, counts[c]) for c in SEOUL_AUTHORITY_CODES),
        tuple(values),
    )
    path = save_snapshot(collection, directory)
    result = runner.run_import(
        source, settings=Settings(_env_file=None), write=True, from_snapshot=path
    )
    assert result["affected"] == len(values)
    return result


def geocode_document():
    return {
        "x": "127.000788",
        "y": "37.552268",
        "address": {
            "address_name": JIBUN,
            "region_1depth_name": "서울",
            "region_2depth_name": "마포구",
            "region_3depth_name": "서교동",
            "main_address_no": "123",
            "sub_address_no": "4",
            "mountain_yn": "N",
        },
        "road_address": {"address_name": ROAD},
    }


class Provider:
    provider, model = "fake", "flow-model"

    def __init__(self, engine):
        self.engine, self.calls, self.failure = engine, 0, None

    async def generate(self, request):
        assert self.engine.pool.checkedout() == 0
        wire = request.user_content
        for forbidden in (
            PRIVATE,
            ROAD,
            KEY,
            "FLOW_",
            "201호",
            "450000",
            str(LAT),
            str(LNG),
            "building_key",
            "license_no",
            "stores_batch_ids",
            "snapshot_token",
        ):
            assert forbidden not in wire
        payload = json.loads(wire.split("<context>")[1].split("</context>")[0])
        self.calls += 1
        if self.failure == "provider":
            raise LlmError(LlmErrorKind.RATE_LIMITED)
        c = payload["candidates"]
        selected = {
            "favorable": list(c["favorable"]),
            "unfavorable": list(c["unfavorable"]),
            "checklist": ["access"] if self.failure != "validation" else ["CANARY_INVALID"],
            "narrative_ids": [next(iter(c["narrative"][str(i)])) for i in range(4)],
        }
        return LlmResult(
            text=json.dumps(selected),
            provider=self.provider,
            model=self.model,
            usage=LlmUsage(),
            attempts=1,
        )


def application(database, transport=None):
    app = create_app(
        Settings(
            _env_file=None,
            llm_api_key=SecretStr("synthetic-only"),
            interpret_requests_per_minute=30,
            interpret_requests_per_day=100,
        )
    )
    app.state.database.engine = database.engine
    assert app.state.database.settings.database_url is None
    provider = Provider(database.engine)
    app.state.interpretation.client = provider
    service = KakaoLocalService(
        api_key="synthetic-only",
        timeout=1,
        transport=transport
        or httpx.MockTransport(
            lambda r: httpx.Response(200, json={"documents": [geocode_document()]})
        ),
    )
    app.dependency_overrides[get_geocode_service] = lambda: service
    return app, provider


def ok(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    value = response.json()
    assert value["error"] is None and set(value) == {"data", "meta", "error"}
    return value


def track_ai_cache_keys(app, monkeypatch):
    keys = []
    cache = app.state.database.cache.ai
    original_get = cache.get

    def get(key):
        keys.append(key)
        return original_get(key)

    monkeypatch.setattr(cache, "get", get)
    return keys


def start(client, category="restaurant"):
    road = ok(
        client.get("/api/geocode", params={"query": ROAD + " 2층 201호", "category": category})
    )["data"]
    jibun = ok(
        client.get("/api/geocode", params={"query": JIBUN + " 2층 201호", "category": category})
    )["data"]
    assert road["building_key"] == jibun["building_key"] == KEY
    assert (road["lat"], road["lng"], road["floor_unit"]) == (LAT, LNG, "2층 201호")
    return road


def query_flow(client, geo, **changes):
    filters = {k: changes[k] for k in ("sub_category",) if k in changes}
    date_range = ok(
        client.get("/api/meta/data-range", params={"category": geo["category"], **filters})
    )
    query = {
        "lat": geo["lat"],
        "lng": geo["lng"],
        "category": geo["category"],
        "radius": 500,
        "as_of": date_range["data"]["max_month"],
        **changes,
    }
    result = {"range": date_range, "query": query}
    for name, path in [
        ("nearby", "/api/stores/nearby"),
        ("snapshot", "/api/stores/snapshot"),
        ("activity", "/api/market/activity"),
        ("risk", "/api/risk"),
    ]:
        include = (
            "sales,living_pop"
            if name == "activity"
            else "market_change,day_night_ratio"
            if name == "risk"
            else None
        )
        result[name] = ok(
            client.get(path, params={**query, **({"include": include} if include else {})})
        )
    return result


def ids(items):
    return [(v["source"], v["license_no"]) for v in items]


def assert_consistent(result):
    nearby, snapshot, activity, risk = (
        result[k] for k in ("nearby", "snapshot", "activity", "risk")
    )
    n, s, a, r = (x["data"] for x in (nearby, snapshot, activity, risk))
    assert ids(n["markers"]) == ids(s["stores"])
    assert len(set(ids(n["markers"]))) == n["count"]
    assert n["count"] == s["total_at_as_of"] == len(s["stores"])
    assert s["total_at_as_of"] == s["still_open"] + s["closed_since"] + s["other"]
    assert n["count"] == sum(v["open_count"] for v in a["by_sub_category"])
    competitor = next(i for i in r["indicators"] if i["id"] == "competitor_count")
    assert competitor["value"] == n["count"]
    metas = [x["meta"] for x in (nearby, snapshot, activity, risk)]
    assert len({m["as_of"] for m in metas}) == 1
    assert {m["data_updated_at"] for m in metas} == {result["range"]["data"]["max_date"]}
    assert len({tuple(m["data_version"]["stores_batch_ids"]) for m in metas}) == 1
    assert n["excluded_no_coord"] == s["excluded_no_coord"]
    # Nearby counts active-at-T missing coordinates; analysis retains closed history too.
    assert n["excluded_no_coord"] <= activity["meta"]["excluded_no_coord"]
    assert activity["meta"]["excluded_no_coord"] == risk["meta"]["excluded_no_coord"]
    assert all(m["collected_at"] is None and m["source"] == ["R5", "R6"] for m in metas)
    assert a["sales"] is a["living_pop"] is None
    assert a["flags"]["missing"] == ["sales", "living_pop"]
    assert [i["id"] for i in r["indicators"][:4]] == [
        "closure_rate_12m",
        "survival_rate_1y",
        "survival_rate_3y",
        "competitor_count",
    ]
    assert not {"official_closure_rate", "official_risk"} & {i["id"] for i in r["indicators"]}
    return n["count"]


def updated_rows():
    return tuple(
        replace(
            v,
            closure_date="20261108",
            status_code="03",
            status_name="폐업",
            update_point="20261109000000",
        )
        if v.management_no == "FLOW_SHARED"
        else replace(v, update_point="20261109000000")
        for v in rows(Source.GENERAL_RESTAURANT)
    )
