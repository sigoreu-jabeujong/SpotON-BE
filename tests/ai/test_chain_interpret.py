import asyncio
import copy
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ai import chain_context
from app.ai.context import prepare_risk_interpretation
from app.ai.prompts.builder import build_interpret_request
from app.ai.prompts.chain_version import CHAIN_PROMPT_SHA256
from app.ai.prompts.loader import CHAIN_PROMPT_VERSION, load_chain_prompt_bundle, load_prompt_bundle
from app.core.config import Settings
from app.main import create_app
from app.schemas.chains import ChainRiskQuery
from app.schemas.risk import RiskQuery
from app.services import risk_interpret as service
from app.services.chains import ChainSelection
from tests.ai.context_helpers import activity_response, response, use_risk
from tests.ai.test_interpretation import Client, choice


def query(**changes):
    return ChainRiskQuery(**{**dict(lat=37.56789123, lng=126.98765432, category="cafe"), **changes})


@pytest.fixture
def prepared(monkeypatch):
    q = query()
    risk = response(q.legacy(RiskQuery))
    activity = activity_response(risk, q.legacy(RiskQuery))
    for r in (risk, activity):
        r.meta.pop("franchise_classification")
    monkeypatch.setattr(chain_context, "get_risk", lambda *args, **kw: copy.deepcopy(risk))
    monkeypatch.setattr(chain_context, "get_activity", lambda *args, **kw: copy.deepcopy(activity))
    monkeypatch.setattr(
        chain_context.ChainSelection, "load", lambda s, q: ChainSelection(None, False, q)
    )
    monkeypatch.setattr(chain_context, "source_revision", lambda s: 17)
    return chain_context.prepare_chain_interpretation(Mock(), q, Settings(_env_file=None))


def app_with(monkeypatch, prepared, provider, **config):
    app = create_app(
        Settings(_env_file=None).model_copy(
            update={"llm_api_key": SecretStr("synthetic-only"), **config}
        )
    )
    app.state.interpretation.client = provider
    monkeypatch.setattr(service, "_prepare", lambda *args: prepared)
    return app


def test_chain_context_projection_prompt_and_render_cache(monkeypatch, prepared):
    captured = []

    class Provider(Client):
        async def generate(self, request):
            captured.append(request)
            return await super().generate(request)

    provider = Provider(choice(prepared))
    app = app_with(monkeypatch, replace(prepared, snapshot_token="synthetic-view"), provider)
    with TestClient(app) as client:
        first = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
        second = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
        assert first.status_code == second.status_code == 200, first.text
        data = first.json()["data"]
        assert data["verification"]["passed"]
        assert len(data["paragraphs"]) == 4
        assert "브랜드 판정 자료가 준비되지" in data["body"]
        assert "과거 브랜드 소속" in data["body"]
        assert provider.calls == 1
        assert first.json()["meta"]["prompt_version"] == CHAIN_PROMPT_VERSION
        assert "franchise_classification" not in data["evidence"]
        assert "generation" not in json.dumps(data["evidence"])
        assert "37.56789123" not in captured[0].user_content
        assert captured[0].system_instruction == prepared.bundle.system_instruction
        assert "analysis.brand_classification" in captured[0].system_instruction
        entry = next(iter(app.state.database.cache.ai._entries.values()))
        assert set(json.loads(entry.value)) == {"selection", "model"}


@pytest.mark.parametrize("change", ["context_hash", "data_version_hash", "snapshot_token"])
def test_chain_cache_new_provenance_misses(monkeypatch, prepared, change):
    provider = Client(choice(prepared))
    p = replace(prepared, snapshot_token="synthetic-view")
    app = app_with(monkeypatch, p, provider)
    with TestClient(app) as client:
        assert (
            client.post("/api/v2/risk/interpret", json={"query": query().model_dump()}).status_code
            == 200
        )
        monkeypatch.setattr(service, "_prepare", lambda *args: replace(p, **{change: "changed"}))
        assert (
            client.post("/api/v2/risk/interpret", json={"query": query().model_dump()}).status_code
            == 200
        )
    assert provider.calls == 2


def test_v1_v2_cache_and_prompt_are_separate(monkeypatch, prepared):
    from app.ai import context as v1

    legacy = query().legacy(RiskQuery)
    use_risk(monkeypatch, v1, response(legacy), q=legacy)
    old = replace(
        prepare_risk_interpretation(Mock(), legacy, Settings(_env_file=None)),
        snapshot_token="same-view",
    )
    new = replace(prepared, snapshot_token="same-view")
    provider = Client(choice(new))
    app = app_with(monkeypatch, new, provider)
    monkeypatch.setattr(
        service,
        "_prepare",
        lambda resources, q, *args: new if isinstance(q, ChainRiskQuery) else old,
    )
    with TestClient(app) as client:
        for _ in range(2):
            v2 = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
            v1_result = client.post(
                "/api/risk/interpret",
                json={"query": legacy.model_dump(exclude={"include_unknown"})},
            )
            assert v2.status_code == v1_result.status_code == 200
            assert v2.json()["meta"]["prompt_version"] != v1_result.json()["meta"]["prompt_version"]
    assert provider.calls == 2


@pytest.mark.parametrize(
    "raw",
    [
        '{"query":{"lat":37,"lat":38,"lng":127,"category":"cafe"}}',
        '{"query":{"lat":37,"lng":127,"category":"cafe","franchise":"all"}}',
        '{"query":{"lat":37,"lng":127,"category":"cafe","brand_scope":"chain"}}',
        '{"query":{"lat":NaN,"lng":127,"category":"cafe"}}',
        '{"query":{"lat":37,"lng":127,"category":"cafe"},"context":{"private":"canary"}}',
        '{"query":{"lat":37,"lng":127,"category":"cafe"},"history":{"building_key":"canary"}}',
    ],
)
def test_chain_invalid_input_no_database_or_provider(monkeypatch, raw):
    app = create_app(Settings(_env_file=None))

    def forbidden(*args):
        pytest.fail("invalid input opened DB")

    monkeypatch.setattr(app.state.database, "get_engine", forbidden)
    with TestClient(app) as client:
        result = client.post(
            "/api/v2/risk/interpret", content=raw, headers={"content-type": "application/json"}
        )
        assert result.status_code == 422
        assert result.headers["cache-control"] == "no-store"
        assert "canary" not in result.text


def test_prompt_fingerprint_mismatch_fails_before_provider(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, replace(prepared, prompt_sha256="bad"), provider)
    with TestClient(app) as client:
        assert (
            client.post("/api/v2/risk/interpret", json={"query": query().model_dump()}).status_code
            == 500
        )
    assert provider.calls == 0


def test_shared_v1_v2_limiter(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider, interpret_requests_per_minute=1)
    with TestClient(app) as client:
        assert (
            client.post("/api/v2/risk/interpret", json={"query": query().model_dump()}).status_code
            == 200
        )
        assert (
            client.post(
                "/api/risk/interpret",
                json={"query": query().legacy(RiskQuery).model_dump(exclude={"include_unknown"})},
            ).status_code
            == 503
        )
    assert provider.calls == 1


@pytest.mark.parametrize(
    "key",
    [
        "generation",
        "brand_key",
        "brand_name",
        "fingerprint",
        "semas_id",
        "published_at",
        "source_revision",
    ],
)
def test_forbidden_internal_identifiers(key):
    with pytest.raises(ValueError):
        build_interpret_request({"analysis": {key: "canary"}}, bundle=load_chain_prompt_bundle())


def test_chain_prompt_is_independent_packaged_and_current():
    bundle = load_chain_prompt_bundle()
    assert bundle.version == CHAIN_PROMPT_VERSION
    assert bundle.sha256 == CHAIN_PROMPT_SHA256
    assert bundle.sha256 != load_prompt_bundle().sha256
    assert "$context_json" in bundle.user_template.template
    assert "franchise_classification" not in bundle.system_instruction


def test_chain_corrupt_cache_and_single_regeneration(monkeypatch, prepared):
    provider = Client(choice(prepared), bad=1)
    p = replace(prepared, snapshot_token="synthetic-view")
    app = app_with(monkeypatch, p, provider)
    with TestClient(app) as client:
        first = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
        assert first.status_code == 200
        assert first.json()["data"]["verification"]["regenerated"]
        cache = app.state.database.cache.ai
        key = next(iter(cache._entries))
        cache.put(key, b'{"selection":{"narrative_ids":["invalid"]},"model":"bad"}')
        second = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
        assert second.status_code == 200
        assert not second.json()["data"]["verification"]["regenerated"]
    assert provider.calls == 3


def test_chain_timeout_cannot_cache_partial_result(monkeypatch, prepared):
    provider = Client(choice(prepared), delay=1)
    app = app_with(
        monkeypatch,
        replace(prepared, snapshot_token="synthetic-view"),
        provider,
        llm_time_budget=0.03,
    )
    with TestClient(app) as client:
        response = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
        assert response.status_code == 503
        assert response.json()["data"] is None
        assert not app.state.database.cache.ai._entries


def test_v1_v2_share_generation_gate(monkeypatch, prepared):
    from app.ai import context as v1

    old_query = query().legacy(RiskQuery)
    use_risk(monkeypatch, v1, response(old_query), q=old_query)
    old = prepare_risk_interpretation(Mock(), old_query, Settings(_env_file=None))

    class Tracking(Client):
        active = 0
        peak = 0

        async def generate(self, request):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.02)
                return await super().generate(request)
            finally:
                self.active -= 1

    provider = Tracking(choice(prepared))
    app = app_with(monkeypatch, prepared, provider, interpret_max_concurrent=1)
    monkeypatch.setattr(
        service,
        "_prepare",
        lambda resources, q, *args: prepared if isinstance(q, ChainRiskQuery) else old,
    )

    async def run():
        result = await asyncio.gather(
            service.interpret_risk(app.state.interpretation, query()),
            service.interpret_risk(app.state.interpretation, old_query),
        )
        assert all(r.data.verification.passed for r in result)

    asyncio.run(run())
    app.state.database.close()
    assert provider.calls == 2 and provider.peak == 1
