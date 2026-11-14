from itertools import product

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.chains import ChainQuery

PARAMS = {"lat": 37.5665, "lng": 126.978, "category": "restaurant"}


@pytest.mark.parametrize(
    "scope,unknown,evidence",
    tuple(
        product(
            ("all", "chain", "non_chain"),
            ("include", "exclude"),
            ("include_estimates", "confirmed_only"),
        )
    ),
)
def test_supported_queries(scope, unknown, evidence):
    query = ChainQuery.model_validate(
        {**PARAMS, "brand_scope": scope, "brand_unknown": unknown, "brand_evidence": evidence}
    )
    assert query.brand_time_basis == "observed_record"


@pytest.mark.parametrize(
    "changes",
    [
        {"brand_scope": "chain"},
        {"brand_scope": "non_chain"},
        {"franchise": "all"},
        {"include_unknown": True},
        {"include_unknown_franchise": True},
        {"operation_type": "direct"},
        {"brand_time_basis": "as_of"},
        {"brand_scope": "confirmed"},
    ],
)
def test_unsupported_queries_are_rejected(changes):
    with pytest.raises(ValidationError):
        ChainQuery.model_validate({**PARAMS, **changes})


def test_v2_invalid_input_never_opens_database(monkeypatch):
    app = create_app(Settings(_env_file=None))

    def forbidden():
        pytest.fail("invalid input opened DB")

    monkeypatch.setattr(app.state.database, "get_engine", forbidden)
    with TestClient(app) as client:
        for endpoint in ("stores/nearby", "stores/snapshot", "market/activity", "risk"):
            for extra in (
                "&franchise=all",
                "&brand_scope=chain",
                "&brand_time_basis=as_of",
                "&lat=37",
            ):
                response = client.get(
                    f"/api/v2/{endpoint}?lat=37&lng=127&category=cafe&as_of=2026-10{extra}"
                )
                assert response.status_code == 422
                assert response.headers["cache-control"] == "no-store"
        assert (
            client.get(
                "/api/v2/stores/history?building_key=종로구-청운동-1-0&brand_scope=chain"
            ).status_code
            == 422
        )
        assert client.get("/api/v2/brands/status?key=x").status_code == 422
        assert (
            client.get("/api/stores/nearby", params={**PARAMS, "brand_scope": "all"}).status_code
            == 422
        )
        assert client.post("/api/v2/risk/interpret", json={}).status_code == 404


@pytest.mark.parametrize(
    "options",
    [
        {"write": True},
        {"write": True, "expected_plan": "x", "expected_active": "none"},
        {"write": True, "expected_plan": "0" * 64, "expected_active": "bad"},
        {"activate_generation": "not_a_generation"},
    ],
)
def test_invalid_publication_options_fail_before_database(monkeypatch, options):
    from etl.chains import publication
    from etl.chains.common import ChainsError

    def forbidden(*args):
        pytest.fail("invalid publication opened DB")

    monkeypatch.setattr(publication, "create_db_engine", forbidden)
    with pytest.raises(ChainsError):
        publication.run(Settings(_env_file=None), (), **options)
