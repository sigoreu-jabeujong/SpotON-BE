from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DataError

from etl.localdata.constants import Source
from tests.integration.analysis_flow_helpers import (
    ENDPOINTS,
    JIBUN,
    KEY,
    PRIVATE,
    ROAD,
    application,
    assert_consistent,
    geocode_document,
    ids,
    import_source,
    ok,
    query_flow,
    start,
    updated_rows,
)
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def database(temporary_database, monkeypatch, tmp_path):
    migrate(temporary_database)
    for source in Source:
        import_source(temporary_database, monkeypatch, tmp_path, source)
    return temporary_database


def test_geocode_etl_identity_and_history_scope(database, caplog, capfd):
    app, provider = application(database)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["data"]["status"] == "ok"
        assert client.get("/docs").status_code == 200
        assert set(client.get("/openapi.json").json()["paths"]) == ENDPOINTS
        geo = start(client, "cafe")
        history = ok(
            client.get(
                "/api/stores/history",
                params={k: geo[k] for k in ("building_key", "floor_unit", "category")},
            )
        )["data"]
        assert history["total"] == len(history["stores"]) == 9
        items = dict(zip(ids(history["stores"]), history["stores"], strict=True))
        assert len(items) == 9
        assert ("general_restaurant", "FLOW_SHARED") in items
        assert ("rest_cafe", "FLOW_SHARED") in items
        assert not any(i[1] == "FLOW_NEIGHBOR" for i in items)
        assert items[("general_restaurant", "FLOW_SHARED")]["location_match"] == "same_spot"
        assert items[("general_restaurant", "FLOW_ZERO")]["location_match"] == "unverified"
        assert items[("general_restaurant", "FLOW_WESTERN")]["location_match"] == "same_building"
        assert (
            items[("general_restaurant", "FLOW_NO_OPEN")]["operating_period_reason"]
            == "missing_open_date"
        )
        assert (
            items[("general_restaurant", "FLOW_NO_CLOSE")]["operating_period_reason"]
            == "missing_close_date"
        )
        assert items[("rest_cafe", "FLOW_SHARED")]["operating_months"] == 0
        assert history["stores"][-1]["open_date"] is None
        for item in history["stores"]:
            assert item["franchise"] == "unknown"
        assert provider.calls == 0
    captured = capfd.readouterr()
    logs = caplog.text + captured.out + captured.err
    assert all(value not in logs for value in (PRIVATE, ROAD, JIBUN, KEY, "FLOW_SHARED", "201호"))


@pytest.mark.parametrize(
    "category,changes,expected",
    [
        ("restaurant", {}, 3),
        ("cafe", {}, 1),
        ("restaurant", {"as_of": "2025-06"}, 4),
        ("restaurant", {"area": "lt33", "include_unknown_area": False}, 1),
        ("restaurant", {"franchise": "independent", "include_unknown_franchise": False}, 0),
        ("restaurant", {"sub_category": "japanese"}, 0),
    ],
)
def test_query_flow_counts_and_dates(database, category, changes, expected):
    app, provider = application(database)
    with TestClient(app) as client:
        result = query_flow(client, start(client, category), **changes)
        assert assert_consistent(result) == expected
        assert result["range"]["data"]["max_date"] == "2026-11-08"
        assert result["risk"]["meta"]["as_of"] == (
            "2025-06-30" if changes.get("as_of") else "2026-11-08"
        )
        if not changes and category == "restaurant":
            assert ids(result["nearby"]["data"]["markers"]) == [
                ("general_restaurant", "FLOW_SHARED"),
                ("general_restaurant", "FLOW_WESTERN"),
                ("general_restaurant", "FLOW_ZERO"),
            ]
            zero = result["nearby"]["data"]["markers"][-1]
            assert zero["area_m2"] is None
            assert result["activity"]["data"]["recent_12m"]["closed"] == 1
            assert result["nearby"]["data"]["excluded_no_coord"] == 1
            assert result["risk"]["meta"]["excluded_no_coord"] == 2
        if changes.get("as_of"):
            assert result["snapshot"]["data"]["closed_since"] == 1
        ai_query = {**result["query"], "include": "market_change,day_night_ratio"}
        ai = ok(client.post("/api/risk/interpret", json={"query": ai_query}))
        again = ok(client.post("/api/risk/interpret", json={"query": ai_query}))
        assert provider.calls == 1
        assert ai["data"]["verification"]["passed"] is True
        assert again["data"]["verification"]["regenerated"] is False
        assert ai["meta"]["as_of"] == result["risk"]["meta"]["as_of"]
        assert {i for item in ai["data"]["official_values"] for i in item["indicator_ids"]} == {
            i["id"] for i in result["risk"]["data"]["indicators"] if i["status"] == "fact"
        }
        competitor = next(
            i for i in ai["data"]["official_values"] if "competitor_count" in i["indicator_ids"]
        )
        assert f"{expected}건" in competitor["text"]
        assert ai["data"]["missing_data"]
        support = ok(
            client.get("/api/support-links", params={"sigungu": "마포구", "category": category})
        )
        assert [link["id"] for link in support["data"]["links"]] == [
            "semas-seoul-seodaemun",
            "seoulsbdc",
            "seoulsbdc-edu",
            "seoul-small-business",
            "sbiz24",
        ]
        assert support["meta"]["prioritization"]["category_applied"] is False


@pytest.mark.parametrize("month,target", [("2024-02", "2024-02-29"), ("2024-04", "2024-04-30")])
def test_past_month_end_and_changed_membership(database, month, target):
    app, _ = application(database)
    with TestClient(app) as client:
        geo = start(client)
        past = query_flow(client, geo, as_of=month)
        latest = query_flow(client, geo)
        assert assert_consistent(past) == assert_consistent(latest) == 3
        assert past["risk"]["meta"]["as_of"] == target
        assert ids(past["nearby"]["data"]["markers"]) != ids(latest["nearby"]["data"]["markers"])


def test_reimport_changes_all_read_models_and_invalidates_ai(database, monkeypatch, tmp_path):
    app, provider = application(database)
    with TestClient(app) as client:
        geo = start(client)
        before = query_flow(client, geo)
        assert assert_consistent(before) == 3
        ok(client.post("/api/risk/interpret", json={"query": before["query"]}))
        import_source(database, monkeypatch, tmp_path, Source.GENERAL_RESTAURANT, updated_rows())
        after = query_flow(client, geo)
        assert assert_consistent(after) == 2
        assert after["range"]["data"]["max_date"] == "2026-11-09"
        assert before["risk"]["meta"]["data_version"] != after["risk"]["meta"]["data_version"]
        ok(client.post("/api/risk/interpret", json={"query": after["query"]}))
        assert provider.calls == 2
        history = ok(
            client.get("/api/stores/history", params={"building_key": geo["building_key"]})
        )["data"]
        updated = next(
            i
            for i in history["stores"]
            if (i["source"], i["license_no"]) == ("general_restaurant", "FLOW_SHARED")
        )
        assert updated["store_status"] == "closed" and updated["close_date"] == "2026-11-08"
    with database.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM stores")) == 10


def test_replay_new_batch_same_values_changes_versions(database, monkeypatch, tmp_path):
    app, provider = application(database)
    with TestClient(app) as client:
        geo = start(client)
        first = query_flow(client, geo)
        ok(client.post("/api/risk/interpret", json={"query": first["query"]}))
        import_source(database, monkeypatch, tmp_path, Source.GENERAL_RESTAURANT)
        again = query_flow(client, geo)
        assert assert_consistent(again) == 3
        assert first["nearby"]["data"] == again["nearby"]["data"]
        assert first["risk"]["meta"]["data_version"] != again["risk"]["meta"]["data_version"]
        ok(client.post("/api/risk/interpret", json={"query": again["query"]}))
        assert provider.calls == 2
    with database.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM stores")) == 10


def test_failed_import_rolls_back_and_keeps_read_models(database, monkeypatch, tmp_path):
    app, _ = application(database)
    with TestClient(app) as client:
        geo = start(client)
        first = query_flow(client, geo)
        invalid = list(updated_rows())
        invalid[-1] = replace(invalid[-1], business_name="x" * 300)
        with pytest.raises(DataError):
            import_source(database, monkeypatch, tmp_path, Source.GENERAL_RESTAURANT, invalid)
        assert query_flow(client, geo) == first


def test_source_unprepared_is_not_empty_success(temporary_database):
    migrate(temporary_database)
    app, provider = application(temporary_database)
    with TestClient(app) as client:
        geo = start(client)
        assert client.get("/api/health").status_code == 200
        params = {k: geo[k] for k in ("lat", "lng", "category")}
        for path in (
            "/api/stores/nearby",
            "/api/stores/snapshot",
            "/api/market/activity",
            "/api/risk",
            "/api/meta/data-range",
        ):
            query = (
                {"category": geo["category"]}
                if path.endswith("data-range")
                else {**params, "as_of": "2026-11"}
            )
            r = client.get(path, params=query)
            assert r.status_code == 500 and r.json()["data"] is None
        assert client.post("/api/risk/interpret", json={"query": params}).status_code == 500
        assert provider.calls == 0
        # History preserves its existing empty-building contract; this is no readiness probe.
        history = ok(
            client.get("/api/stores/history", params={"building_key": geo["building_key"]})
        )
        assert history["data"]["total"] == 0 and history["meta"]["as_of"] is None


def test_invalid_conditions_do_not_invoke_provider(database, caplog):
    app, provider = application(database)
    with TestClient(app) as client:
        geo = start(client)
        base = {k: geo[k] for k in ("lat", "lng", "category")}
        for path, invalid in [
            ("/api/stores/nearby", {"area": PRIVATE}),
            ("/api/stores/snapshot", {"as_of": "2026-13"}),
            ("/api/risk", {"radius": PRIVATE}),
        ]:
            result = client.get(path, params={**base, **invalid})
            assert result.status_code == 422 and result.json()["error"]["code"] == "INVALID_PARAM"
            assert result.headers["cache-control"] == "no-store"
            assert PRIVATE not in result.text
        result = client.post("/api/risk/interpret", json={"query": base, "building_key": PRIVATE})
        assert result.status_code == 422 and PRIVATE not in result.text + caplog.text
        assert provider.calls == 0
        assert assert_consistent(query_flow(client, geo)) == 3


@pytest.mark.parametrize(
    "failure,calls,code", [("provider", 1, "AI_UNAVAILABLE"), ("validation", 2, "AI_VERIFY_FAILED")]
)
def test_ai_failure_keeps_other_apis_available(database, failure, calls, code, caplog):
    app, provider = application(database)
    provider.failure = failure
    with TestClient(app) as client:
        geo = start(client)
        first = query_flow(client, geo)
        failed = client.post("/api/risk/interpret", json={"query": first["query"]})
        assert failed.status_code == 503 and failed.json()["error"]["code"] == code
        assert failed.headers["cache-control"] == "no-store"
        assert provider.calls == calls
        assert assert_consistent(query_flow(client, geo)) == 3
        assert client.get("/api/support-links").status_code == 200
        assert "CANARY_INVALID" not in failed.text + caplog.text


@pytest.mark.parametrize(
    "kind,status,code",
    [
        ("empty", 404, "ADDRESS_NOT_FOUND"),
        ("outside", 422, "OUT_OF_SEOUL"),
        ("timeout", 502, "UPSTREAM_ERROR"),
        ("unauthorized", 502, "UPSTREAM_ERROR"),
        ("rate_limit", 502, "UPSTREAM_ERROR"),
        ("malformed", 502, "UPSTREAM_ERROR"),
    ],
)
def test_geocode_errors_are_safe_and_process_is_healthy(
    temporary_database, kind, status, code, caplog, capfd
):
    def respond(request):
        if kind == "timeout":
            raise httpx.ReadTimeout(PRIVATE)
        if kind in {"unauthorized", "rate_limit"}:
            return httpx.Response(401 if kind == "unauthorized" else 429, text=PRIVATE)
        doc = geocode_document()
        if kind == "outside":
            doc["address"]["region_1depth_name"] = "경기"
        payload = (
            {"documents": [] if kind == "empty" else [doc]}
            if kind != "malformed"
            else {"private": PRIVATE}
        )
        return httpx.Response(200, json=payload)

    app, provider = application(temporary_database, httpx.MockTransport(respond))
    with TestClient(app) as client:
        failed = client.get("/api/geocode", params={"query": PRIVATE, "category": "restaurant"})
        assert failed.status_code == status and failed.json()["error"]["code"] == code
        assert failed.json()["data"] is None and failed.headers["cache-control"] == "no-store"
        assert client.get("/api/health").status_code == 200
        assert provider.calls == 0
    captured = capfd.readouterr()
    assert PRIVATE not in failed.text + caplog.text + captured.out + captured.err
