import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.client import LlmResult, LlmUsage
from app.core.config import Settings
from app.main import create_app
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def db(temporary_database):
    migrate(temporary_database)
    return temporary_database.engine


def seed(db):
    with Session(db) as s, s.begin():
        b = batch(s, data_updated_at=date(2026, 11, 8))
        for i in range(10):
            store(s, b, f"ai{i}", open_date=date(2025, 1, 1))
        store(s, b, "old", open_date=date(2010, 1, 1), close_date=date(2018, 1, 1), status="closed")


class Provider:
    provider = "fake"
    model = "fake-model"

    def __init__(self, db):
        self.db = db
        self.calls = 0

    async def generate(self, request):
        assert self.db.pool.checkedout() == 0
        payload = json.loads(request.user_content.split("<context>")[1].split("</context>")[0])
        wire = json.dumps(payload)
        assert "stores_batch_ids" not in wire and "building_key" not in wire
        assert "37.5665" not in wire and "126.978" not in wire
        assert request.response_json_schema["properties"]["checklist"]["minItems"] == 1
        c = payload["candidates"]
        self.calls += 1
        selection = {
            "favorable": list(c["favorable"]),
            "unfavorable": list(c["unfavorable"]),
            "checklist": ["time_flow"],
            "narrative_ids": [next(iter(c["narrative"][str(i)])) for i in range(4)],
        }
        return LlmResult(
            text=json.dumps(selection),
            provider=self.provider,
            model=self.model,
            usage=LlmUsage(),
            attempts=1,
        )


def test_real_preparation_session_closed_before_provider_and_api(db):
    seed(db)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db
    provider = Provider(db)
    app.state.interpretation.client = provider
    with TestClient(app) as c:
        for changes in [{}, {"as_of": "2020-02"}, {"category": "cafe"}]:
            r = c.post("/api/risk/interpret", json={"query": {**PARAMS, **changes}})
            assert r.status_code == 200, r.text
            assert r.headers["cache-control"] == "no-store"
            assert r.json()["data"]["verification"]["passed"] is True
        assert c.get("/api/risk", params=PARAMS).status_code == 200
    assert provider.calls == 3 and db.pool.checkedout() == 0


def test_missing_source_500_and_deadline_cleanup_does_not_poison_pool(db):
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = db
    provider = Provider(db)
    app.state.interpretation.client = provider
    with TestClient(app) as c:
        assert c.post("/api/risk/interpret", json={"query": PARAMS}).status_code == 500
        assert provider.calls == 0
    seed(db)
    app = create_app(Settings(_env_file=None).model_copy(update={"llm_time_budget": 0.001}))
    app.state.database.engine = db
    app.state.interpretation.client = provider
    with TestClient(app) as c:
        r = c.post("/api/risk/interpret", json={"query": PARAMS})
        assert r.status_code == 503 and r.json()["error"]["code"] == "AI_UNAVAILABLE"
        for _ in range(300):
            if db.pool.checkedout() == 0:
                break
            time.sleep(0.01)
        assert db.pool.checkedout() == 0
        with db.connect() as conn:
            assert conn.scalar(text("SHOW statement_timeout")) == "0"
            assert conn.scalar(text("SHOW transaction_read_only")) == "off"
            assert conn.scalar(text("SELECT 1")) == 1
        assert c.get("/api/risk", params=PARAMS).status_code == 200
    assert provider.calls == 0
