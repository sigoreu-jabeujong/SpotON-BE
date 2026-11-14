import asyncio
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.ai import context as context_module
from app.ai.client import LlmError, LlmErrorKind, LlmResult, LlmUsage
from app.ai.context import prepare_risk_interpretation
from app.ai.interpretation import build_catalog, render_interpretation
from app.core.config import Settings
from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.main import create_app
from app.schemas.common import ErrorCode
from app.schemas.interpret import CandidateSelection
from app.schemas.risk import ReferenceCounts
from app.services import risk_interpret as service
from tests.ai.context_helpers import (
    history_query,
    history_row,
    query,
    response,
    use_history,
    use_risk,
)


@pytest.fixture
def prepared(monkeypatch):
    local = ReferenceCounts(
        cohort_size=20,
        active=9,
        closure_num=1,
        closure_den=10,
        survival_1_num=4,
        survival_1_den=5,
        survival_3_num=2,
        survival_3_den=5,
    )
    use_risk(monkeypatch, context_module, response(local=local))
    return prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


class Client:
    provider = "fake"
    model = "fake-model"

    def __init__(self, selection, *, bad=0, error=None, delay=0):
        self.selection = selection
        self.bad = bad
        self.error = error
        self.delay = delay
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        data = (
            {"favorable": [], "unfavorable": [], "checklist": ["private-canary"]}
            if self.calls <= self.bad
            else self.selection
        )
        return LlmResult(
            text=json.dumps(data),
            provider=self.provider,
            model=self.model,
            usage=LlmUsage(),
            attempts=1,
        )


def choice(p):
    c = build_catalog(p)
    return {
        "favorable": list(reversed(c.favorable)),
        "unfavorable": list(c.unfavorable),
        "checklist": ["access"],
        "narrative_ids": [f"paragraph_{i}_direct" for i in range(4)],
    }


def app_with(monkeypatch, p, client, **config):
    settings = Settings(_env_file=None).model_copy(update=config)
    app = create_app(settings)
    app.state.interpretation.client = client
    monkeypatch.setattr(service, "_prepare", lambda *args: p)
    return app


def test_all_comparisons_required_and_server_rendering(prepared):
    catalog = build_catalog(prepared)
    selected = choice(prepared)
    assert len(catalog.favorable) == 2 and len(catalog.unfavorable) == 1
    schema = catalog.selection_schema()
    assert set(schema["properties"]["favorable"]["items"]["enum"]) == set(catalog.favorable)
    assert schema["properties"]["favorable"]["minItems"] == 2
    assert not catalog.selection_valid({**selected, "favorable": []})
    assert not catalog.selection_valid({**selected, "unfavorable": selected["favorable"]})
    output = render_interpretation(
        prepared, catalog, CandidateSelection(**selected), model="fake", regenerated=False
    )
    assert len(output.official_values) == 6 and len(output.missing_data) >= 5
    assert output.verification.passed and output.verification.checked_numbers > 0
    assert output.favorable[0] == catalog.favorable[selected["favorable"][0]]


@pytest.mark.parametrize(
    "bad,expected,regenerated", [(0, 200, False), (1, 200, True), (2, 503, None)]
)
def test_selection_retry_and_exact_metadata(
    monkeypatch, prepared, bad, expected, regenerated, caplog
):
    provider = Client(choice(prepared), bad=bad)
    app = app_with(monkeypatch, prepared, provider)
    with TestClient(app) as c:
        r = c.post(
            "/api/risk/interpret", json={"query": query().model_dump(exclude={"include_unknown"})}
        )
    assert r.status_code == expected and r.headers["cache-control"] == "no-store"
    assert provider.calls == (1 if bad == 0 else 2)
    assert "private-canary" not in r.text + caplog.text
    if expected == 200:
        assert r.json()["data"]["verification"]["regenerated"] is regenerated
        assert r.json()["data"]["model"] == "fake-model"
        assert r.json()["data"]["method"] == "server_sentences_model_ordering"
    else:
        assert r.json()["error"]["code"] == "AI_VERIFY_FAILED"


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"query":{}}',
        '{"query":{"category":"cafe","lat":NaN,"lng":127}}',
        '{"query":{"category":"cafe","lat":37,"lat":38,"lng":127}}',
        '{"query":{"category":"cafe","lat":37,"lng":127},"indicators":[]}',
        '{"query":{"category":"cafe","lat":37,"lng":127},"building_key":"private-canary"}',
        '{"query":{"category":"cafe","lat":37,"lng":127,"radius_m":500}}',
        "not json",
    ],
)
def test_request_rejects_tampering_and_duplicate_keys(monkeypatch, prepared, raw, caplog):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider)
    with TestClient(app) as c:
        r = c.post("/api/risk/interpret", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.headers["cache-control"] == "no-store"
    assert provider.calls == 0 and "private-canary" not in r.text + caplog.text


@pytest.mark.parametrize(
    "kind", [LlmErrorKind.RATE_LIMITED, LlmErrorKind.QUOTA_EXHAUSTED, LlmErrorKind.NOT_CONFIGURED]
)
def test_provider_errors_do_not_regenerate(monkeypatch, prepared, kind):
    provider = Client(choice(prepared), error=LlmError(kind))
    app = app_with(monkeypatch, prepared, provider)
    with TestClient(app) as c:
        r = c.post(
            "/api/risk/interpret", json={"query": query().model_dump(exclude={"include_unknown"})}
        )
    assert (
        r.status_code == 503
        and r.json()["error"]["code"] == "AI_UNAVAILABLE"
        and provider.calls == 1
    )


def test_concurrency_gate_and_waiter_cancellation(monkeypatch, prepared):
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        class Blocking(Client):
            async def generate(self, request):
                entered.set()
                await release.wait()
                return await super().generate(request)

        provider = Blocking(choice(prepared))
        app = app_with(monkeypatch, prepared, provider, interpret_max_concurrent=1)
        resources = app.state.interpretation
        first = asyncio.create_task(service.interpret_risk(resources, query()))
        await entered.wait()
        second = asyncio.create_task(service.interpret_risk(resources, query()))
        await asyncio.sleep(0.01)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        release.set()
        result = await first
        assert result.data.verification.passed and provider.calls == 1
        assert not resources.gate.locked()

    asyncio.run(scenario())


def test_deadline_and_app_request_limit(monkeypatch, prepared):
    provider = Client(choice(prepared), delay=0.1)
    app = app_with(monkeypatch, prepared, provider, llm_time_budget=0.02)
    with TestClient(app) as c:
        r = c.post(
            "/api/risk/interpret", json={"query": query().model_dump(exclude={"include_unknown"})}
        )
        assert r.status_code == 503 and r.json()["error"]["code"] == "AI_UNAVAILABLE"
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider, interpret_requests_per_minute=1)
    with TestClient(app) as c:
        body = {"query": query().model_dump(exclude={"include_unknown"})}
        assert c.post("/api/risk/interpret", json=body).status_code == 200
        assert c.post("/api/risk/interpret", json=body).status_code == 503
    assert provider.calls == 1


def test_no_regeneration_with_too_little_time_and_template_failure_500(monkeypatch, prepared):
    provider = Client(choice(prepared), bad=2)
    app = app_with(monkeypatch, prepared, provider, llm_time_budget=0.5)
    with TestClient(app) as c:
        r = c.post(
            "/api/risk/interpret", json={"query": query().model_dump(exclude={"include_unknown"})}
        )
    assert (
        r.status_code == 503
        and r.json()["error"]["code"] == "AI_UNAVAILABLE"
        and provider.calls == 1
    )
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider)
    monkeypatch.setattr(
        service, "render_interpretation", Mock(side_effect=ValueError("private-canary"))
    )
    with TestClient(app) as c:
        r = c.post(
            "/api/risk/interpret", json={"query": query().model_dump(exclude={"include_unknown"})}
        )
    assert (
        r.status_code == 500
        and r.headers["cache-control"] == "no-store"
        and "private-canary" not in r.text
    )


def test_activity_facts_follow_risk_facts_with_activity_ids(prepared):
    output = render_interpretation(
        prepared,
        build_catalog(prepared),
        CandidateSelection(**choice(prepared)),
        model="fake",
        regenerated=False,
    )
    risk_ids = [item.indicator_ids for item in output.official_values[:4]]
    assert all(ids[0] not in {"recent_open_close", "avg_operating_months"} for ids in risk_ids)
    recent, average = output.official_values[4:]
    assert recent.indicator_ids == ["recent_open_close"]
    assert recent.text == (
        "참고 계산: 최근 구간 (2025-11-08, 2026-11-08]에 반경 500m의 "
        "개업 인허가 기록은 3건, 폐업 기록은 1건입니다."
    )
    assert average.indicator_ids == ["avg_operating_months"]
    assert average.text == (
        "참고 계산: 2026-11-08 기준 카페 영업 기록 9건의 개업 후 평균 경과 기간은 41개월입니다."
    )
    assert all(
        "recent_open_close" not in item.indicator_ids
        for item in output.favorable + output.unfavorable
    )


def test_longest_restaurant_combination_passes_verifier_with_large_counts(monkeypatch):
    local = ReferenceCounts(
        cohort_size=30000,
        active=12345,
        closure_num=1234,
        closure_den=13579,
        survival_1_num=400,
        survival_1_den=500,
        survival_3_num=100,
        survival_3_den=300,
    )
    seoul = ReferenceCounts(
        cohort_size=900000,
        active=400000,
        closure_num=20000,
        closure_den=420000,
        survival_1_num=9000,
        survival_1_den=20000,
        survival_3_num=3000,
        survival_3_den=10000,
    )
    q = query(category="restaurant", include="market_change,day_night_ratio", radius=1000)
    use_risk(monkeypatch, context_module, response(q, local, seoul), q, opened=2345, months=1234)
    p = prepare_risk_interpretation(Mock(), q, Settings(_env_file=None))
    catalog = build_catalog(p)
    assert len(catalog.favorable) + len(catalog.unfavorable) == 3
    selected = CandidateSelection(
        favorable=list(catalog.favorable),
        unfavorable=list(catalog.unfavorable),
        narrative_ids=[f"paragraph_{i}_direct" for i in range(4)],
        checklist=["time_flow", "access", "visibility"],
    )
    output = render_interpretation(p, catalog, selected, model="fake", regenerated=False)
    texts = [i.text for i in output.official_values]
    assert "개업 인허가 기록은 2,345건, 폐업 기록은 1,234건입니다." in texts[4]
    assert any("한식 영업 기록 12,345건의 개업 후 평균 경과 기간은 1,234개월" in t for t in texts)
    assert sum("영업 기록이 없어 평균 경과 기간을 산정하지 않았습니다" in t for t in texts) == 3
    assert [i.indicator_ids for i in output.official_values[5:]] == [["avg_operating_months"]] * 4


def test_openapi_keeps_comparison_ids_narrow():
    schema = create_app(Settings(_env_file=None)).openapi()["components"]["schemas"]
    fact = json.dumps(schema["InterpretItem"]["properties"]["indicator_ids"])
    sourced = json.dumps(schema["InterpretSourcedItem"]["properties"]["indicator_ids"])
    assert "recent_open_close" in fact and "avg_operating_months" in fact
    assert "recent_open_close" not in sourced and "avg_operating_months" not in sourced


HISTORY_BODY = {"building_key": "마포구-서교동-123-4", "floor_unit": "1층 101호"}


@pytest.mark.parametrize(
    "history",
    [
        {"building_key": "private-canary"},
        {"building_key": "마포구-서교동-123-4", "floor_unit": ""},
        {"building_key": "마포구-서교동-123-4", "floor_unit": "private-canary"},
        {**HISTORY_BODY, "name": "private-canary"},
        {"floor_unit": "1층"},
        "마포구-서교동-123-4",
        [],
    ],
)
def test_malformed_history_is_rejected_before_preparation(monkeypatch, prepared, history, caplog):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider)
    guard = Mock(side_effect=AssertionError("must not prepare"))
    monkeypatch.setattr(service, "_prepare", guard)
    body = {"query": query().model_dump(exclude={"include_unknown"}), "history": history}
    with TestClient(app) as c:
        r = c.post("/api/risk/interpret", json=body)
    assert r.status_code == 422 and r.headers["cache-control"] == "no-store"
    assert provider.calls == 0 and guard.call_count == 0
    assert "private-canary" not in r.text + caplog.text


@pytest.mark.parametrize("history", [None, HISTORY_BODY, {"building_key": "마포구-서교동-123-4"}])
def test_history_reaches_preparation_as_canonical_query(monkeypatch, prepared, history):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider)
    seen = []
    monkeypatch.setattr(service, "_prepare", lambda *args: seen.append(args) or prepared)
    body = {"query": query().model_dump(exclude={"include_unknown"})}
    if history is not None:
        body["history"] = history
    with TestClient(app) as c:
        r = c.post("/api/risk/interpret", json=body)
    assert r.status_code == 200
    sent = seen[0][4]
    if history is None:
        assert sent is None
    else:
        assert sent.building_key == history["building_key"] and sent.category == "cafe"
        assert sent.floor_unit == history.get("floor_unit")


def test_far_building_maps_to_422_without_provider_call(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider)
    monkeypatch.setattr(
        service, "_prepare", Mock(side_effect=AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE))
    )
    body = {"query": query().model_dump(exclude={"include_unknown"}), "history": HISTORY_BODY}
    with TestClient(app) as c:
        r = c.post("/api/risk/interpret", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARAM"
    assert r.headers["cache-control"] == "no-store" and provider.calls == 0


def history_output(monkeypatch, rows, hq=None, q=None, result=None, checklist=("access",)):
    q = q or query()
    result = result or response(q)
    use_risk(monkeypatch, context_module, result, q)
    use_history(monkeypatch, context_module, result, rows)
    p = prepare_risk_interpretation(
        Mock(), q, Settings(_env_file=None), history=hq or history_query()
    )
    catalog = build_catalog(p)
    selected = CandidateSelection(
        favorable=list(catalog.favorable),
        unfavorable=list(catalog.unfavorable),
        narrative_ids=[f"paragraph_{i}_direct" for i in range(4)],
        checklist=list(checklist),
    )
    return render_interpretation(p, catalog, selected, model="fake", regenerated=False)


def texts_by_id(output, identifier):
    return [i.text for i in output.official_values if i.indicator_ids == [identifier]]


def reasons(output):
    return [m.reason for m in output.missing_data]


def test_history_sentences_for_mixed_building(monkeypatch, caplog):
    output = history_output(
        monkeypatch,
        [
            history_row("same_spot", "closed", 14, index=0),
            history_row("same_spot", "closed", 30, index=1),
            history_row("same_spot", "other", None, index=2),
            history_row("same_spot", "open", 5, index=3),
            history_row("same_building", "closed", 9, index=4),
            history_row("unverified", "open", 3, index=5),
        ],
    )
    (overview,) = texts_by_id(output, "building_history")
    assert overview == (
        "참고 계산: 2026-11-08 최신 자료 기준 이 건물의 분석 대상 "
        "음식점·카페 인허가 기록은 6건이며, "
        "같은 자리로 확인된 기록 4건, 같은 건물의 다른 위치 1건, 위치 미확인 1건입니다."
    )
    (spot,) = texts_by_id(output, "same_spot_history")
    assert spot == (
        "참고 계산: 같은 자리 기록 중 영업 중 1건, 폐업 2건, 기타 상태 1건이며, "
        "영업 기간을 확인한 폐업 기록 2건의 영업 기간은 14~30개월입니다."
    )
    assert "history_latest_data_basis" in reasons(output)
    dumped = output.model_dump_json()
    assert "PRIVATE" not in dumped + caplog.text and "101호" not in dumped


@pytest.mark.parametrize(
    "rows,expected",
    [
        (
            [history_row("same_spot", "closed", 7)],
            "폐업 1건이며, 영업 기간을 확인한 폐업 기록 1건의 영업 기간은 7개월입니다.",
        ),
        ([history_row("same_spot", "open", 7)], "영업 중 1건, 폐업 0건입니다."),
        (
            [history_row("same_spot", "closed", None)],
            "폐업 기록의 영업 기간은 확인되지 않았습니다.",
        ),
    ],
)
def test_same_spot_sentence_variants(monkeypatch, rows, expected):
    (spot,) = texts_by_id(history_output(monkeypatch, rows), "same_spot_history")
    assert spot.endswith(expected)


def test_history_without_floor_or_with_floor_only_and_empty(monkeypatch):
    rows = [history_row("unverified", "closed", 12, index=i) for i in range(2)]
    output = history_output(monkeypatch, rows, history_query(floor_unit=None))
    assert texts_by_id(output, "building_history") == [
        "참고 계산: 2026-11-08 최신 자료 기준 이 건물의 분석 대상 "
        "음식점·카페 인허가 기록은 2건입니다."
    ]
    assert not texts_by_id(output, "same_spot_history")
    assert "history_floor_unit_missing" in reasons(output)
    output = history_output(
        monkeypatch, [history_row("same_building", index=0)], history_query(floor_unit="2층")
    )
    assert "history_detail_incomplete" in reasons(output)
    output = history_output(monkeypatch, [])
    assert not texts_by_id(output, "building_history")
    assert "history_no_records" in reasons(output)
    assert "history_latest_data_basis" not in reasons(output)


def test_longest_combination_with_history_stays_within_limit(monkeypatch):
    local = ReferenceCounts(
        cohort_size=30000,
        active=12345,
        closure_num=1234,
        closure_den=13579,
        survival_1_num=400,
        survival_1_den=500,
        survival_3_num=100,
        survival_3_den=300,
    )
    seoul = ReferenceCounts(
        cohort_size=900000,
        active=400000,
        closure_num=20000,
        closure_den=420000,
        survival_1_num=9000,
        survival_1_den=20000,
        survival_3_num=3000,
        survival_3_den=10000,
    )
    q = query(category="restaurant", include="market_change,day_night_ratio", radius=1000)
    result = response(q, local, seoul)
    use_risk(monkeypatch, context_module, result, q, opened=2345, months=1234)
    rows = [
        *(history_row("same_spot", "closed", 1000 + i, index=i) for i in range(1200)),
        *(history_row("same_spot", "open", 3, index=2000 + i) for i in range(1100)),
        *(history_row("same_spot", "other", None, index=4000 + i) for i in range(1050)),
        *(history_row("same_building", "closed", 3, index=6000 + i) for i in range(1300)),
        *(history_row("unverified", "open", 3, index=8000 + i) for i in range(1400)),
    ]
    use_history(monkeypatch, context_module, result, rows)
    p = prepare_risk_interpretation(Mock(), q, Settings(_env_file=None), history=history_query())
    catalog = build_catalog(p)
    output = render_interpretation(
        p,
        catalog,
        CandidateSelection(
            favorable=list(catalog.favorable),
            unfavorable=list(catalog.unfavorable),
            narrative_ids=[f"paragraph_{i}_direct" for i in range(4)],
            checklist=["time_flow", "access", "visibility"],
        ),
        model="fake",
        regenerated=False,
    )
    parts = [i.text for i in output.official_values + output.favorable + output.unfavorable]
    parts += [m.text for m in output.missing_data]
    parts += [x for c in output.checklist for x in (c.item, c.why)]
    assert sum(map(len, parts)) <= 2000
    (spot,) = texts_by_id(output, "same_spot_history")
    assert "1,000~2,199개월" in spot and "기타 상태 1,050건" in spot


def test_openapi_lists_history_ids_for_facts_only():
    schema = create_app(Settings(_env_file=None)).openapi()["components"]["schemas"]
    fact = json.dumps(schema["InterpretItem"]["properties"]["indicator_ids"])
    sourced = json.dumps(schema["InterpretSourcedItem"]["properties"]["indicator_ids"])
    assert "building_history" in fact and "same_spot_history" in fact
    assert "building_history" not in sourced and "same_spot_history" not in sourced
