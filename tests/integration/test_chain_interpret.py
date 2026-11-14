import json
from datetime import date
from itertools import product

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, text, update
from sqlalchemy.orm import Session

from app.ai import chain_context
from app.core.config import Settings
from app.main import create_app
from app.models import Store
from app.models.chain import ChainPublicationState
from etl.chains import publication
from etl.chains.registry import load_registry
from tests.integration.test_chain_publication import prepared
from tests.integration.test_interpret import Provider as BaseProvider
from tests.integration.test_nearby import PARAMS, batch, store
from tests.integration.test_store_migration import migrate

pytestmark = pytest.mark.integration
BUILDING = "종로구-청운동-1-0"


@pytest.fixture
def db(temporary_database, monkeypatch):
    migrate(temporary_database, "head")
    with Session(temporary_database.engine) as s, s.begin():
        b = batch(s)
        for i in range(8):
            store(
                s,
                b,
                f"private-chain-{i}",
                name="본죽",
                building_key=BUILDING,
                floor_unit="2층 201호",
                location_level="same_spot",
            )
        for i in range(2):
            store(
                s,
                b,
                f"private-closed-{i}",
                name="본죽",
                building_key=BUILDING,
                close_date=date(2026, 10, 1),
                status="closed",
            )
        store(s, b, "private-unknown", name="동네식당", building_key=BUILDING)
        store(s, b, "private-nocoord", name="본죽", building_key=BUILDING, distance=None)
    prepared(temporary_database, monkeypatch)
    return temporary_database


class Provider(BaseProvider):
    def __init__(self, engine):
        super().__init__(engine)
        self.payloads = []

    async def generate(self, request):
        payload = json.loads(request.user_content.split("<context>")[1].split("</context>")[0])
        self.payloads.append(payload)
        wire = json.dumps(payload, ensure_ascii=False)
        assert all(
            v not in wire
            for v in (
                BUILDING,
                "private-chain",
                "본죽",
                "generation",
                "brand_key",
                "fingerprint",
                "source_revision",
            )
        )
        return await super().generate(request)


def application(db, **config):
    app = create_app(
        Settings(
            _env_file=None,
            interpret_requests_per_minute=100,
            interpret_requests_per_day=500,
            llm_api_key=SecretStr("synthetic-only"),
            **config,
        )
    )
    app.state.database.engine = db.engine
    provider = Provider(db.engine)
    app.state.interpretation.client = provider
    return app, provider


def test_v2_ai_truth_matrix_history_and_public_api_agree(db):
    app, provider = application(db)
    with TestClient(app) as client:
        for scope, unknown, evidence in product(
            ("all", "chain", "non_chain"),
            ("include", "exclude"),
            ("include_estimates", "confirmed_only"),
        ):
            query = {
                **PARAMS,
                "brand_scope": scope,
                "brand_unknown": unknown,
                "brand_evidence": evidence,
            }
            response = client.post(
                "/api/v2/risk/interpret",
                json={
                    "query": query,
                    "history": {"building_key": BUILDING, "floor_unit": "2층 201호"},
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            context = payload["data"]["evidence"]
            risk = client.get("/api/v2/risk", params=query).json()["data"]
            activity = client.get("/api/v2/market/activity", params=query).json()["data"]
            ai_count = next(
                i["value"] for i in context["indicators"] if i["id"] == "competitor_count"
            )
            assert (
                ai_count
                == next(i["value"] for i in risk["indicators"] if i["id"] == "competitor_count")
                == sum(g["open_count"] for g in activity["by_sub_category"])
            )
            assert context["history"]["total"] == 12
            assert context["history"]["same_spot"] == 8
            assert context["filters"]["brand_scope"] == scope
            assert context["brand_classification"]["status"] == "estimate"
            assert "franchise_classification" not in context
            assert payload["meta"]["brand_classification"]["generation"]
            assert "과거 브랜드 소속" in payload["data"]["body"]
            if scope == "chain" and unknown == "exclude" and evidence == "confirmed_only":
                assert "확인 자료가 아직 없어 이 조건의 결과는 0건" in payload["data"]["body"]
        past = client.post(
            "/api/v2/risk/interpret",
            json={
                "query": {
                    **PARAMS,
                    "as_of": "2020-02",
                    "brand_scope": "chain",
                    "brand_unknown": "exclude",
                }
            },
        )
        assert past.status_code == 200, past.text
        assert past.json()["data"]["evidence"]["as_of"] == "2020-02-29"
        assert db.engine.pool.checkedout() == 0
    assert provider.calls == 13


def test_pending_and_source_drift_cached_revalidation(db):
    app, provider = application(db)
    query = {**PARAMS, "brand_scope": "chain", "brand_unknown": "exclude"}
    with TestClient(app) as client:
        first = client.post("/api/v2/risk/interpret", json={"query": query})
        second = client.post("/api/v2/risk/interpret", json={"query": query})
        assert first.status_code == second.status_code == 200
        assert provider.calls == 1
        with db.engine.begin() as c:
            c.execute(
                update(Store).where(Store.license_no == "private-chain-0").values(name="바뀐상호")
            )
        changed = client.post("/api/v2/risk/interpret", json={"query": query})
        assert changed.status_code == 200, changed.text
        assert changed.json()["meta"]["context_hash"] != first.json()["meta"]["context_hash"]
        assert changed.json()["data"]["evidence"]["brand_classification"]["source_drift"]
        assert provider.calls == 2
        with db.engine.begin() as c:
            c.execute(delete(ChainPublicationState))
        pending = client.post("/api/v2/risk/interpret", json={"query": query})
        assert pending.status_code == 200, pending.text
        context = pending.json()["data"]["evidence"]
        assert context["brand_classification"]["status"] == "pending"
        assert next(v["value"] for v in context["indicators"] if v["id"] == "competitor_count") == 0
        assert "빈 결과를 체인 부재" in pending.json()["data"]["body"]
        assert provider.calls == 3


def test_new_publication_same_context_different_private_version_misses_cache(db, monkeypatch):
    monkeypatch.setattr(chain_context, "snapshot_token", lambda *args: "fixed-synthetic-view")
    app, provider = application(db)
    with TestClient(app) as client:
        first = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert first.status_code == 200, first.text
        seeds = load_registry()
        changed = (seeds[0].model_copy(update={"reviewed_on": date(2026, 11, 13)}), *seeds[1:])
        with db.engine.begin() as c:
            publication.locked(c, True)
            plan = publication.apply(c, changed, None)
            publication.apply(
                c,
                changed,
                None,
                write=True,
                expected_plan=plan["expected_plan_sha256"],
                expected_active=plan["active"],
            )
        second = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert second.status_code == 200, second.text
        assert first.json()["meta"]["context_hash"] == second.json()["meta"]["context_hash"]
        assert (
            first.json()["meta"]["data_version_hash"] != second.json()["meta"]["data_version_hash"]
        )
        assert first.json()["data"]["body"] == second.json()["data"]["body"]
        assert provider.calls == 2


@pytest.mark.parametrize("kind", ["counts", "brand_generation", "legacy", "filters"])
def test_tampered_recalculation_rejected_before_provider(db, monkeypatch, kind):
    original = (
        chain_context.get_activity
        if kind in {"counts", "brand_generation"}
        else chain_context.get_risk
    )

    def broken(*args, **kwargs):
        response = original(*args, **kwargs)
        if kind == "counts":
            response.data.recent_12m.closed += 1
        elif kind == "brand_generation":
            response.meta["brand_classification"] = {"generation": "wrong"}
        elif kind == "legacy":
            response.meta["franchise_classification"] = {"status": "pending"}
        else:
            response.data.query.filters["franchise"] = "independent"
        return response

    monkeypatch.setattr(
        chain_context,
        "get_activity" if kind in {"counts", "brand_generation"} else "get_risk",
        broken,
    )
    app, provider = application(db)
    with TestClient(app) as client:
        response = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert response.status_code == 500, response.text
        assert response.headers["cache-control"] == "no-store"
    assert provider.calls == 0


def test_trigger_failure_and_far_history_propagate_without_provider(db):
    app, provider = application(db)
    with TestClient(app) as client:
        far = client.post(
            "/api/v2/risk/interpret",
            json={"query": {**PARAMS, "lat": 37.6}, "history": {"building_key": BUILDING}},
        )
        assert far.status_code == 422, far.text
        with db.engine.begin() as c:
            c.execute(text("ALTER TABLE stores DISABLE TRIGGER spoton_chain_source_changed"))
        response = client.post("/api/v2/risk/interpret", json={"query": PARAMS})
        assert response.status_code == 500
    assert provider.calls == 0
