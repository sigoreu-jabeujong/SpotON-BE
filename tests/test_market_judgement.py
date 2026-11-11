from datetime import date
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.schemas.market_judgement import (
    BoundaryProvenance,
    BoundaryQuery,
    MarketRef,
    SpatialJudgement,
)
from app.services.market_judgement import classify_markets, judge_market


def ref(code="3110001", kind="alley"):
    return MarketRef(market_code=code, market_name="synthetic", market_type=kind)


def test_details_priority_multiple_zones_and_order_independence():
    detail = ref()
    zones = [ref("3110003", "tourism_zone"), ref("3110002", "tourism_zone")]
    result = classify_markets([*zones, detail])
    assert result.spatial_status == "in_market" and result.primary == detail
    assert result.candidates == result.nearby_markets == []
    assert result.also_in == list(reversed(zones))
    assert classify_markets([detail, *reversed(zones)]) == result


@pytest.mark.parametrize("kind", ["alley", "developed", "traditional_market", "tourism_zone"])
def test_single_type_can_be_primary(kind):
    r = ref(kind=kind)
    result = classify_markets([r])
    assert result.primary == r and result.spatial_status == "in_market"
    assert result.candidates == result.also_in == result.nearby_markets == []


@pytest.mark.parametrize("tourism", [False, True])
def test_equal_priority_overlap_keeps_candidates(tourism):
    a = ref("3110002", "tourism_zone" if tourism else "traditional_market")
    b = ref("3110001", "tourism_zone" if tourism else "developed")
    zone = ref("3110003", "tourism_zone")
    result = classify_markets([a, b] if tourism else [a, zone, b])
    assert result.spatial_status == "ambiguous" and result.primary is None
    assert result.candidates == [b, a]
    assert result.also_in == ([] if tourism else [zone])


def test_outside_sorted_nearby_is_not_selected():
    a, b = ref("3110002"), ref()
    result = classify_markets([], [a, b])
    assert result.spatial_status == "outside" and result.primary is None
    assert result.candidates == result.also_in == [] and result.nearby_markets == [b, a]
    assert classify_markets([]).nearby_markets == []


@pytest.mark.parametrize(
    "groups", [([ref(), ref()], []), ([ref()], [ref("3110002")]), ([], [ref(), ref()])]
)
def test_duplicates_and_covering_with_nearby_fail(groups):
    with pytest.raises(ValueError):
        classify_markets(*groups)


@pytest.mark.parametrize(
    "changes",
    [
        {"lat": float("nan")},
        {"lng": float("inf")},
        {"lat": 90.001},
        {"lng": -180.001},
        {"radius": 400},
        {"version_id": "latest"},
        {"unknown": True},
    ],
)
def test_invalid_input_is_rejected(changes):
    with pytest.raises(ValidationError):
        BoundaryQuery(**{**dict(version_id=uuid4(), lat=37.5, lng=127.0), **changes})


def test_coordinates_hidden_in_repr_and_error_string():
    q = BoundaryQuery(version_id=uuid4(), lat=37.567891, lng=126.987654)
    assert "37.567891" not in repr(q) and "126.987654" not in repr(q)
    with pytest.raises(ValidationError) as exc:
        BoundaryQuery(version_id=q.version_id, lat="sensitive-input", lng=0.0)
    assert "sensitive-input" not in str(exc.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"primary": ref()},
        {"candidates": [ref(), ref("3110002")]},
        {"also_in": [ref("3110002", "tourism_zone")]},
        {"spatial_status": "in_market"},
        {"spatial_status": "ambiguous", "candidates": [ref()]},
        {"spatial_status": "ambiguous", "candidates": [ref(), ref("3110002", "tourism_zone")]},
        {"spatial_status": "in_market", "primary": ref(), "nearby_markets": [ref("3110002")]},
        {"nearby_markets": [ref("3110002"), ref()]},
        {"spatial_status": "in_market", "primary": ref(), "also_in": [ref()]},
        {
            "spatial_status": "in_market",
            "primary": ref("3110001", "tourism_zone"),
            "also_in": [ref("3110002", "tourism_zone")],
        },
    ],
)
def test_result_invariants(changes):
    with pytest.raises(ValidationError):
        SpatialJudgement(
            **{
                **dict(
                    spatial_status="outside",
                    primary=None,
                    candidates=[],
                    also_in=[],
                    nearby_markets=[],
                ),
                **changes,
            }
        )


def test_unknown_market_type_rejected():
    with pytest.raises(ValidationError):
        ref(kind="unknown")


def test_provenance_date_does_not_verify_applicability():
    values = dict(
        version_id=uuid4(),
        source_dataset="OA-15560",
        source_url="https://example.invalid",
        source_file_date=date(2023, 10, 23),
        boundary_as_of=date(2023, 10, 20),
        input_sha256="1" * 64,
        content_sha256="2" * 64,
        rule_version="synthetic",
    )
    p = BoundaryProvenance(**values)
    assert p.applicability == "unverified" and p.boundary_as_of != p.source_file_date
    with pytest.raises(ValidationError):
        BoundaryProvenance(**values, applicability="verified")


@pytest.mark.parametrize("error", [SQLAlchemyError("sensitive-bind"), ValueError("private")])
def test_database_failures_hide_details_and_context(error):
    session = Mock()
    session.get.side_effect = error
    with pytest.raises(AppError) as exc:
        judge_market(session, BoundaryQuery(version_id=uuid4(), lat=37.5, lng=127.0))
    assert "sensitive-bind" not in str(exc.value) and "private" not in str(exc.value)
    assert exc.value.__context__ is None
    assert exc.value.headers == {"Cache-Control": "no-store"}
