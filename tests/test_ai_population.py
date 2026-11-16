import copy
import hashlib
import json
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai import population_context as module
from app.ai.interpretation import build_catalog
from app.ai.population_context import population_sentence, project_population
from app.ai.prompts.builder import serialize_context
from app.ai.verifier import VerifyFailure, verify_output
from app.schemas.ai_population import ContextPopulationReference
from app.schemas.population_reference import PopulationReferenceQuery
from tests.ai.population_helpers import TARGET, population_response
from tests.ai.test_analysis_v2_interpret import app_with, query
from tests.ai.test_analysis_v2_interpret import prepared as prepared
from tests.ai.test_interpretation import Client, choice


def projected(**kwargs):
    q = PopulationReferenceQuery(lat=0, lng=0, category="cafe")
    return project_population(population_response(q, **kwargs), q, TARGET)


def test_projection_exact_allowlist_and_no_identifiers_or_raw_values():
    context, digest = projected()
    wire = context.model_dump(mode="json")
    assert set(wire) == {
        "status",
        "reason",
        "analysis_date",
        "observation_date",
        "calculation_method",
        "day_hours",
        "night_hours",
        "ratio_definition",
        "population_filter_applied",
        "source_validation_performed",
        "population_total_validated",
        "sources",
    }
    metric = wire["sources"][0]["metrics"]["day_share_pct"]
    assert set(metric) == {"display", "exact_zero", "rounded", "unit", "reason"}
    assert metric["display"] == "66.7%"
    assert "가가00000000" not in json.dumps(wire, ensure_ascii=False)
    assert "11110530" not in json.dumps(wire)
    assert "value" not in metric and "hourly_source_sums" not in json.dumps(wire)
    assert set(wire["sources"][0]["quality"]) == module.QUALITY
    assert len(digest) == 64
    text = population_sentence(context)
    assert "66.7%" in text and "33.3%" in text
    assert "2.00000" not in text and "전체 인구나 실제 방문객을 대표하지" in text


@pytest.mark.parametrize("status", ["pending", "no_data", "not_supported"])
def test_valid_unavailable_states_are_explanations_without_population_numbers(status):
    context, _ = projected(status=status)
    assert context.sources == ()
    assert "%" not in population_sentence(context)


@pytest.mark.parametrize(
    "day,night,expected",
    [
        ("0", "0", "합이 모두 영"),
        ("0", "1", "주간 비중은 0.0%"),
        ("0.00001", "100", "반올림 표시값"),
        ("1", "0", "야간 비중은 0.0%"),
    ],
)
def test_zero_and_rounded_zero_are_not_confused(day, night, expected):
    context, _ = projected(day=day, night=night)
    assert expected in population_sentence(context)


@pytest.mark.parametrize(
    "field,value",
    [
        ("radius", 300),
        ("category", "restaurant"),
        ("sub_category", ("cafe",)),
        ("as_of", "2026-11"),
    ],
)
def test_projection_rejects_mismatched_scope(field, value):
    q = PopulationReferenceQuery(lat=0, lng=0, category="cafe")
    response = population_response(q)
    with pytest.raises(ValueError):
        project_population(response, q.model_copy(update={field: value}), TARGET)


def test_same_month_observation_and_strict_status_and_metric_contracts():
    context, _ = projected()
    raw = context.model_dump()
    for updates in (
        {"observation_date": date(2026, 10, 31)},
        {"analysis_date": date(2026, 11, 6)},
        {"status": "no_data"},
        {"population_total_validated": True},
        {"lat": 0},
    ):
        with pytest.raises(ValidationError):
            ContextPopulationReference.model_validate(raw | updates)
    for changes in ({"unit": "ratio"}, {"display": "private-address"}, {"value": "66.7"}):
        bad = copy.deepcopy(raw)
        bad["sources"][0]["metrics"]["day_share_pct"].update(changes)
        with pytest.raises(ValidationError):
            ContextPopulationReference.model_validate(bad)


def test_sentence_is_verified_without_its_own_numbers_or_quality_counts(monkeypatch):
    context, _ = projected()
    text, evidence = module._sentence(context)
    assert "quality" not in json.dumps(evidence) and "day_hours" not in evidence
    bad = text.replace("66.7%", "98.7654%")
    assert (
        VerifyFailure.UNKNOWN_NUMBER
        in verify_output(json.dumps({"text": bad}), context={"analysis": evidence}).failures
    )
    monkeypatch.setattr(module, "_sentence", lambda _: (bad, evidence))
    with pytest.raises(ValueError, match="sentence verification"):
        population_sentence(context)


def test_source_metadata_change_changes_internal_digest_without_outbound_change():
    q = PopulationReferenceQuery(lat=0, lng=0, category="cafe")
    response = population_response(q)
    a, first = project_population(response, q, TARGET)
    response.meta["content_sha256"] = "a" * 64
    b, second = project_population(response, q, TARGET)
    assert a == b and first != second


def test_v2_actual_render_provider_payload_and_source_meta(monkeypatch, prepared):
    provider = Client(choice(prepared))
    app = app_with(monkeypatch, prepared, provider)
    with TestClient(app) as client:
        response = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["source"] == ["R5", "R6", "R4"]
    assert "66.7%" in body["data"]["body"]
    assert "전체 생활인구와 매출의 적용 기준을 확인하지 못해" in body["data"]["body"]
    assert "population_public_subset" in body["data"]["used_indicator_ids"]
    assert len(body["data"]["paragraphs"]) == 4
    catalog = build_catalog(prepared)
    assert all("population_public_subset" not in row.indicator_ids for row in catalog.facts)
    assert all(
        "population_public_subset" not in row.indicator_ids
        for row in list(catalog.favorable.values()) + list(catalog.unfavorable.values())
    )


def test_new_population_context_invalidates_ai_cache(monkeypatch, prepared):
    from app.services import risk_interpret as service

    first = replace(prepared, snapshot_token="synthetic")
    provider = Client(choice(first))
    app = app_with(monkeypatch, first, provider)
    with TestClient(app) as client:
        assert (
            client.post("/api/v2/risk/interpret", json={"query": query().model_dump()}).status_code
            == 200
        )
        population, _ = projected(day="3")
        context = first.context.model_copy(update={"population_reference": population})
        changed = replace(
            first,
            context=context,
            context_hash=hashlib.sha256(
                serialize_context(context.model_dump(mode="json")).encode()
            ).hexdigest(),
        )
        monkeypatch.setattr(service, "_prepare", lambda *args: changed)
        response = client.post("/api/v2/risk/interpret", json={"query": query().model_dump()})
        assert response.status_code == 200
        assert "75.0%" in response.json()["data"]["body"]
    assert provider.calls == 2


def test_all_public_unavailable_reasons_have_closed_explanations():
    from typing import get_args

    from app.schemas.population_reference import PublicSourceReason, ReferenceReason

    expected = (set(get_args(PublicSourceReason)) | set(get_args(ReferenceReason))) - {
        "public_subset_only"
    }
    assert set(module.REASONS) == expected
    with pytest.raises(ValueError):
        module._reason_text("invalid")
    q = PopulationReferenceQuery(lat=0, lng=0, category="cafe")
    response = population_response(q)
    response.meta.pop("content_sha256")
    with pytest.raises(ValueError, match="provenance missing"):
        project_population(response, q, TARGET)
