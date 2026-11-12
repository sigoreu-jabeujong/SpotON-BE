import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ai import context as context_module
from app.ai.client import LlmError, LlmErrorKind
from app.ai.context import prepare_risk_interpretation
from app.core.config import Settings
from app.core.errors import AppError
from app.services import risk_interpret as service
from tests.ai.context_helpers import query, response, use_risk
from tests.ai.test_interpretation import Client, app_with, choice


@pytest.fixture
def prepared(monkeypatch):
    use_risk(monkeypatch, context_module, response())
    p = prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    return replace(p, snapshot_token="synthetic-opaque-view")


def make_app(monkeypatch, prepared, provider, **config):
    return app_with(
        monkeypatch, prepared, provider, llm_api_key=SecretStr("synthetic-only"), **config
    )


def post(client):
    return client.post(
        "/api/risk/interpret", json={"query": query().model_dump(exclude={"include_unknown"})}
    )


def test_hit_selection_only_current_render_and_current_request_regeneration(monkeypatch, prepared):
    provider = Client(choice(prepared), bad=1)
    app = make_app(monkeypatch, prepared, provider)
    with TestClient(app) as client:
        first, second = post(client), post(client)
        assert first.status_code == second.status_code == 200
        assert first.json()["data"]["verification"]["regenerated"] is True
        assert second.json()["data"]["verification"]["regenerated"] is False
        assert second.json()["data"]["generated_at"] > first.json()["data"]["generated_at"]
        assert first.headers["cache-control"] == second.headers["cache-control"] == "no-store"
        assert provider.calls == 2
        cache = app.state.database.cache.ai
        assert cache.info()["hits"] == 1
        entry = next(iter(cache._entries.values()))
        assert set(json.loads(entry.value)) == {"selection", "model"}
        assert all(
            s not in entry.value.decode()
            for s in ["generated_at", "regenerated", "37.56789123", "context"]
        )


@pytest.mark.parametrize(
    "dimension", ["snapshot", "model", "prompt", "context", "data", "tokens", "query"]
)
def test_versions_and_exact_query_miss(monkeypatch, prepared, dimension):
    provider = Client(choice(prepared))
    app = make_app(monkeypatch, prepared, provider)
    with TestClient(app) as client:
        assert post(client).status_code == 200
        fields = {
            "snapshot": "snapshot_token",
            "prompt": "prompt_sha256",
            "context": "context_hash",
            "data": "data_version_hash",
        }
        if dimension in fields:
            monkeypatch.setattr(
                service,
                "_prepare",
                lambda *args: replace(prepared, **{fields[dimension]: "changed"}),
            )
        elif dimension == "model":
            provider.model = "new-model"
        elif dimension == "tokens":
            app.state.database.settings.llm_max_output_tokens += 1
        if dimension == "query":
            r = client.post(
                "/api/risk/interpret",
                json={"query": query(lat=37.56789124).model_dump(exclude={"include_unknown"})},
            )
        else:
            r = post(client)
        assert r.status_code == 200
        assert provider.calls == 2


@pytest.mark.parametrize(
    "failure", ["provider", "invalid", "corrupt", "expired", "key_removed", "render"]
)
def test_failure_and_expiry_boundaries(monkeypatch, prepared, failure):
    provider = Client(choice(prepared))
    app = make_app(monkeypatch, prepared, provider)
    with TestClient(app) as client:
        assert post(client).status_code == 200
        cache = app.state.database.cache.ai
        key = next(iter(cache._entries))
        if failure == "key_removed":
            app.state.database.settings.llm_api_key = None
        elif failure == "render":
            monkeypatch.setattr(
                service, "render_interpretation", Mock(side_effect=ValueError("private-canary"))
            )
        elif failure == "corrupt":
            cache.put(
                key,
                b'{"selection":{"favorable":[],"unfavorable":[],'
                b'"checklist":["unknown-id"]},"model":"fake"}',
            )
        else:
            cache._clock = lambda: float("inf") if failure != "expired" else 10**12
            if failure == "provider":
                provider.error = LlmError(LlmErrorKind.RATE_LIMITED)
            elif failure == "invalid":
                provider.bad = 100
        result = post(client)
        expected = (
            500 if failure == "render" else 503 if failure in {"provider", "invalid"} else 200
        )
        assert result.status_code == expected
        assert provider.calls == (1 if failure == "render" else 3 if failure == "invalid" else 2)
        assert "private-canary" not in result.text
        if failure in {"provider", "invalid"}:
            provider.error, provider.bad = None, 0
            cache._clock = lambda: 10**12
            assert post(client).status_code == 200


def test_hit_still_consumes_request_limit(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = make_app(monkeypatch, prepared, provider, interpret_requests_per_minute=2)
    with TestClient(app) as client:
        assert post(client).status_code == post(client).status_code == 200
        limited = post(client)
        assert limited.status_code == 503 and limited.json()["error"]["code"] == "AI_UNAVAILABLE"
        assert provider.calls == 1


def test_single_flight_and_distinct_key_progress(monkeypatch, prepared):
    provider = Client(choice(prepared), delay=0.04)
    app = make_app(
        monkeypatch,
        prepared,
        provider,
        interpret_max_concurrent=1,
        interpret_requests_per_minute=20,
    )

    async def run():
        resources = app.state.interpretation
        results = await asyncio.gather(
            *(service.interpret_risk(resources, query()) for _ in range(5)),
            service.interpret_risk(resources, query(radius=300)),
        )
        assert len(results) == 6 and provider.calls == 2
        assert resources.flights._active == {} and not resources.gate.locked()

    asyncio.run(run())


def test_failed_owner_not_shared_and_cancel_cleanup(monkeypatch, prepared):
    provider = Client(choice(prepared), error=LlmError(LlmErrorKind.RATE_LIMITED), delay=0.02)
    app = make_app(monkeypatch, prepared, provider)

    async def run():
        resources = app.state.interpretation
        results = await asyncio.gather(
            *(service.interpret_risk(resources, query()) for _ in range(2)), return_exceptions=True
        )
        assert all(isinstance(r, AppError) for r in results) and provider.calls == 2
        assert resources.database.cache.ai.info()["entries"] == 0
        provider.error, provider.delay = None, 10
        task = asyncio.create_task(service.interpret_risk(resources, query()))
        while provider.calls < 3:
            await asyncio.sleep(0.001)
        waiter = asyncio.create_task(service.interpret_risk(resources, query()))
        await asyncio.sleep(0.01)
        waiter.cancel()
        task.cancel()
        for cancelled in (waiter, task):
            with pytest.raises(asyncio.CancelledError):
                await cancelled
        assert resources.flights._active == {} and not resources.gate.locked()

    asyncio.run(run())


def test_same_key_waiter_does_not_occupy_provider_gate(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = make_app(monkeypatch, prepared, provider, interpret_max_concurrent=2)

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        original = provider.generate

        async def generate(request):
            if not entered.is_set():
                entered.set()
                await release.wait()
            return await original(request)

        provider.generate = generate
        resources = app.state.interpretation
        owner = asyncio.create_task(service.interpret_risk(resources, query()))
        await entered.wait()
        waiter = asyncio.create_task(service.interpret_risk(resources, query()))
        for _ in range(100):
            if any(f.users == 2 for f in resources.flights._active.values()):
                break
            await asyncio.sleep(0.001)
        assert any(f.users == 2 for f in resources.flights._active.values())
        distinct = await asyncio.wait_for(service.interpret_risk(resources, query(radius=300)), 2)
        assert distinct.data is not None and not owner.done()
        release.set()
        await asyncio.gather(owner, waiter)
        assert provider.calls == 2 and resources.flights._active == {}

    asyncio.run(run())


def test_single_flight_wait_is_inside_deadline(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = make_app(monkeypatch, prepared, provider, llm_time_budget=0.05)

    async def run():
        resources = app.state.interpretation
        # Independently hold the exact generated key without invoking a supplier.
        original = resources.flights.hold
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def delayed(key):
            async with original(key):
                await asyncio.sleep(1)
                yield True

        monkeypatch.setattr(resources.flights, "hold", delayed)
        with pytest.raises(AppError):
            await service.interpret_risk(resources, query())
        assert provider.calls == 0
        assert resources.flights._active == {} and not resources.gate.locked()

    asyncio.run(run())
