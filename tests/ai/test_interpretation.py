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
from app.main import create_app
from app.schemas.interpret import CandidateSelection
from app.schemas.risk import ReferenceCounts
from app.services import risk_interpret as service
from tests.ai.context_helpers import query, response, use_risk


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
    assert len(output.official_values) == 4 and len(output.missing_data) >= 5
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
