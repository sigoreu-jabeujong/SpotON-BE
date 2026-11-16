from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.ai import context_v2
from app.ai.client import LlmError, LlmErrorKind
from app.core.config import Settings
from app.main import create_app
from app.models import LivingPopulationVersion as V
from tests.integration.test_interpret import Provider
from tests.integration.test_nearby import batch, store
from tests.integration.test_population_reference import PARAMS
from tests.integration.test_population_reference import population_db as population_db

pytestmark = pytest.mark.integration


def application(engine):
    app = create_app(
        Settings(
            _env_file=None,
            llm_api_key=SecretStr("synthetic-only"),
            interpret_requests_per_minute=100,
            interpret_requests_per_day=500,
        )
    )
    app.state.database.engine = engine
    provider = Provider(engine)
    app.state.interpretation.client = provider
    return app, provider


def test_real_sql_listener_checks_worker_stop_during_population_lookup(population_db, monkeypatch):
    from app.services import risk_interpret as service

    engine, *_ = population_db
    app, provider = application(engine)
    original_prepare = service._prepare
    original_population = context_v2.get_population_reference
    reached = []

    def prepare(resources, query, deadline, stop, history=None):
        def stop_before_sql(session, population_query):
            reached.append(True)
            stop.set()
            return original_population(session, population_query)

        monkeypatch.setattr(context_v2, "get_population_reference", stop_before_sql)
        return original_prepare(resources, query, deadline, stop, history)

    monkeypatch.setattr(service, "_prepare", prepare)
    with TestClient(app) as client:
        response = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
    assert response.status_code == 503
    assert reached and provider.calls == 0 and engine.pool.checkedout() == 0


def test_same_rr_sources_independent_get_ai_and_filters_agree(population_db, monkeypatch):
    engine, public, *_ = population_db
    app, provider = application(engine)
    original = context_v2.get_population_reference
    transactions = []

    def inspect(session, query):
        transactions.append(
            (
                session.scalar(text("SHOW transaction_isolation")),
                session.scalar(text("SHOW transaction_read_only")),
            )
        )
        return original(session, query)

    monkeypatch.setattr(context_v2, "get_population_reference", inspect)
    expected = public.get("/api/v2/population-reference", params=PARAMS).json()["data"]
    with TestClient(app) as client:
        for filters in ({}, {"include_unknown_area": False}, {"area": "lt33"}):
            response = client.post("/api/v2/risk/interpret", json={"query": PARAMS | filters})
            assert response.status_code == 200, response.text
            payload = response.json()
            context = payload["data"]["evidence"]["population_reference"]
            assert context["analysis_date"] == expected["analysis_date"]
            assert context["observation_date"] == expected["observation_date"]
            assert (
                context["sources"][0]["metrics"]["day_share_pct"]["display"]
                == expected["sources"][0]["values"]["day_share_pct"]["display"]
            )
            assert [s["status"] for s in context["sources"]] == ["partial", "no_data", "no_data"]
            assert payload["meta"]["source"] == ["R5", "R6", "R4"]
            assert "50.0%" in payload["data"]["body"]
            assert "주간 또는 야간에 치우친 제외" in payload["data"]["body"]
            assert len(payload["data"]["paragraphs"]) == 4
            assert "population_public_subset" in payload["data"]["used_indicator_ids"]
            assert engine.pool.checkedout() == 0
        old = client.post("/api/v2/risk/interpret", json={"query": PARAMS | {"as_of": "2026-10"}})
        assert old.status_code == 200, old.text
        assert old.json()["data"]["evidence"]["population_reference"]["status"] == "no_data"
        assert old.json()["meta"]["source"] == ["R5", "R6"]
    assert transactions and all(t == ("repeatable read", "on") for t in transactions)
    assert provider.calls == 4


def test_population_internal_version_drift_misses_selection_cache(population_db):
    engine, _, _, _, version, _ = population_db
    app, provider = application(engine)
    with TestClient(app) as client:
        first = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert first.status_code == 200, first.text
        assert client.post("/api/v2/risk/interpret", json={"query": PARAMS}).status_code == 200
        assert provider.calls == 1
        with engine.begin() as connection:
            connection.execute(
                update(V).where(V.version_id == version).values(content_sha256="b" * 64)
            )
        changed = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert changed.status_code == 200, changed.text
        assert provider.calls == 2
        assert (
            first.json()["meta"]["data_version_hash"] != changed.json()["meta"]["data_version_hash"]
        )
        assert first.json()["data"]["evidence"] == changed.json()["data"]["evidence"]


@pytest.mark.parametrize("failure", ["scope", "metadata", "deadline"])
def test_population_corruption_and_deadline_are_not_silently_omitted(
    population_db, monkeypatch, failure
):
    engine, *_ = population_db
    app, provider = application(engine)
    original = context_v2.get_population_reference

    def damaged(session, query):
        if failure == "deadline":
            raise LlmError(LlmErrorKind.TIMEOUT)
        response = original(session, query)
        if failure == "scope":
            response.data = response.data.model_copy(update={"analysis_date": date(2026, 11, 6)})
        else:
            response.meta["population_total_validated"] = True
        return response

    monkeypatch.setattr(context_v2, "get_population_reference", damaged)
    with TestClient(app) as client:
        response = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert response.status_code == (503 if failure == "deadline" else 500)
        assert response.headers["cache-control"] == "no-store"
        assert provider.calls == 0


@pytest.mark.parametrize("category", ["cafe", "restaurant"])
def test_default_subcategory_earliest_month_and_empty_cohort(population_db, category):
    engine, *_ = population_db
    if category == "cafe":
        with Session(engine) as session, session.begin():
            provenance = batch(session, data_updated_at=date(2026, 11, 8))
            store(
                session,
                provenance,
                "synthetic-cafe",
                category="cafe",
                sub_category="cafe",
                open_date=date(2020, 1, 1),
            )
    app, provider = application(engine)
    with TestClient(app) as client:
        for month in (None, "2020-01", "2026-11"):
            query = PARAMS | {"category": category}
            if month:
                query["as_of"] = month
            response = client.post("/api/v2/risk/interpret", json={"query": query})
            assert response.status_code == 200, response.text
        assert (
            client.post(
                "/api/v2/risk/interpret",
                json={"query": PARAMS | {"category": category, "as_of": "2019-12"}},
            ).status_code
            == 422
        )
        if category == "restaurant":
            # No chinese cohort: current succeeds; a past month remains 422, not 500.
            q = PARAMS | {"sub_category": ["chinese"]}
            assert client.post("/api/v2/risk/interpret", json={"query": q}).status_code == 200
            assert (
                client.post(
                    "/api/v2/risk/interpret", json={"query": q | {"as_of": "2026-10"}}
                ).status_code
                == 422
            )
    assert engine.pool.checkedout() == 0
