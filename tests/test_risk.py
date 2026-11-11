from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.routers.risk import risk_session
from app.schemas.risk import ReferenceCounts, RiskIndicator, RiskMarket, RiskQuery
from app.services import risk as service

BASE = {"lat": 37.5665, "lng": 126.978, "category": "restaurant"}


def counts(num=2, den=10, **changes):
    return ReferenceCounts(
        **{
            **dict(
                cohort_size=den,
                active=den - num,
                closure_num=num,
                closure_den=den,
                survival_1_num=0,
                survival_1_den=0,
                survival_3_num=0,
                survival_3_den=0,
            ),
            **changes,
        }
    )


@pytest.mark.parametrize(
    "num,den,value,reason",
    [
        (0, 0, None, "zero_denominator"),
        (1, 9, None, "insufficient_sample"),
        (0, 10, 0.0, None),
        (10, 10, 100.0, None),
        (49, 400, 12.3, None),
    ],
)
def test_closure_sample_and_decimal_half_up(num, den, value, reason):
    c = counts(num, den)
    result = service.reference_indicators(c, c, date(2025, 2, 28), 500)[0]
    assert result.value == value and result.reason == reason
    assert result.denominator == den
    assert result.numerator == (num if value is not None else None)
    assert result.period == "(2024-02-28, 2025-02-28]"
    assert result.source == ["R5", "R6"]


def test_survival_minimum_and_local_pending_seoul_ready():
    local = counts(0, 4, survival_1_num=3, survival_1_den=4)
    seoul = counts(2, 10, survival_1_num=4, survival_1_den=5)
    result = service.reference_indicators(local, seoul, date(2024, 2, 29), 300)
    assert result[1].value is None and result[1].numerator is None and result[1].denominator == 4
    assert result[1].seoul_avg == 80 and result[1].seoul_numerator == 4
    assert result[1].period == "(2022-02-28, 2023-02-28]"
    assert result[-1].value == 4 and result[-1].seoul_avg is None
    assert result[-1].seoul_avg_reason == "not_applicable"
    with pytest.raises(ValueError):
        service.reference_indicators(seoul, local, date(2024, 2, 29), 300)


@pytest.mark.parametrize(
    "changes",
    [
        {"closure_num": 11},
        {"active": 9},
        {"survival_1_num": 1},
        {"cohort_size": 0},
        {"survival_3_den": 11},
        {"active": True},
    ],
)
def test_count_partitions_and_types(changes):
    with pytest.raises(ValidationError):
        counts(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"value": float("nan")},
        {"value": 101.0},
        {"numerator": 11},
        {"status": "pending"},
        {"source": "R5,R6"},
        {"source": ["R2"]},
        {"seoul_avg": None},
        {"denominator": 0},
    ],
)
def test_rate_model_invariants(changes):
    data = service.reference_indicators(counts(), counts(), date(2026, 11, 8), 500)[0].model_dump()
    with pytest.raises(ValidationError):
        RiskIndicator(**{**data, **changes})


def test_configuration_boundary_and_query_privacy():
    v = uuid4()
    assert Settings(_env_file=None, risk_boundary_version_id=str(v)).risk_boundary_version_id == v
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, risk_boundary_version_id="private-canary")
    assert "private-canary" not in str(exc.value)
    assert "37.5665" not in repr(RiskQuery(**BASE))
    with pytest.raises(ValidationError):
        RiskMarket(
            status="in_market", reason="boundary_version_not_selected", spatial_candidate=None
        )


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"category": None}, "CATEGORY_REQUIRED"),
        ({"category": "bakery"}, "CATEGORY_REQUIRED"),
        ({"include": ""}, "INVALID_PARAM"),
        ({"include": "lq"}, "INVALID_PARAM"),
        ({"include": "market_change,market_change"}, "INVALID_PARAM"),
        ({"include": "Market_change"}, "INVALID_PARAM"),
        ({"include": "market_change, day_night_ratio"}, "INVALID_PARAM"),
        ({"include": "day_night_ratio,"}, "INVALID_PARAM"),
        ({"lat": "NaN"}, "INVALID_PARAM"),
        ({"radius": 400}, "INVALID_PARAM"),
        ({"version_id": "private-canary"}, "INVALID_PARAM"),
        ({"include_unknown": True, "include_unknown_area": True}, "INVALID_PARAM"),
    ],
)
def test_input_validation_precedes_db_and_does_not_leak(changes, code, caplog):
    app = create_app(Settings(_env_file=None, database_url=None))
    guard = MagicMock(side_effect=AssertionError("must not connect"))
    app.state.database.get_engine = guard
    with TestClient(app) as client:
        r = client.get(
            "/api/risk", params={k: v for k, v in {**BASE, **changes}.items() if v is not None}
        )
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert r.headers["cache-control"] == "no-store"
    assert "private-canary" not in r.text + caplog.text
    guard.assert_not_called()


def test_duplicate_params_missing_db_and_openapi():
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        assert (
            client.get(
                "/api/risk",
                params=[
                    *BASE.items(),
                    ("include", "market_change"),
                    ("include", "day_night_ratio"),
                ],
            ).status_code
            == 422
        )
        r = client.get("/api/risk", params=BASE)
        assert r.status_code == 500 and r.json()["data"] is None
        schema = client.get("/openapi.json").json()
        assert {
            p["name"] for p in schema["paths"]["/api/risk"]["get"]["parameters"] if p["required"]
        } == {"lat", "lng", "category"}
        assert client.get("/api/health").status_code == 200


def test_model_failure_safe500_without_context(monkeypatch, caplog):
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[risk_session] = lambda: MagicMock()

    def fail(*args):
        raise ValueError("private-canary")

    monkeypatch.setattr(service, "_get_risk", fail)
    with TestClient(app) as client:
        r = client.get("/api/risk", params=BASE)
    assert r.status_code == 500 and r.json()["meta"] == {}
    assert "private-canary" not in r.text + caplog.text
