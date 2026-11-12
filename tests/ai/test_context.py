import asyncio
import dataclasses
import hashlib
import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from app.ai import context as module
from app.ai.prompts.builder import FORBIDDEN_CONTEXT_KEYS, serialize_context
from app.ai.prompts.loader import PromptError
from app.ai.verified import generate_verified
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.risk import ReferenceCounts
from tests.ai.context_helpers import query, response
from tests.ai.test_gemini import Clock, make_client, ok_body


def prepare(monkeypatch, q=None, result=None):
    q = q or query()
    server = Mock(return_value=result or response(q))
    monkeypatch.setattr(module, "get_risk", server)
    session = Mock()
    settings = Settings(_env_file=None)
    output = module.prepare_risk_interpretation(session, q, settings)
    assert server.call_count == 1
    assert server.call_args.args[0] is session
    assert server.call_args.args[1].model_dump(exclude={"include_unknown"}) == q.model_dump(
        exclude={"include_unknown"}
    )
    return output


def walk_keys(v):
    if isinstance(v, dict):
        for k, item in v.items():
            yield k
            yield from walk_keys(item)
    elif isinstance(v, list):
        for item in v:
            yield from walk_keys(item)


def test_allowlist_and_original_risk_numbers_and_statuses(monkeypatch):
    q = query(include="day_night_ratio,market_change", include_unknown=False)
    original = response(q)
    p = prepare(monkeypatch, q, original)
    safe = p.json_context()
    assert safe["category"] == "cafe" and safe["radius_m"] == 500
    assert safe["sub_category"] == ["cafe"]
    assert safe["as_of"] == "2026-11-08" and safe["collected_at"] is None
    assert safe["filters"]["include_unknown_area"] is False
    assert not set(walk_keys(safe)) & FORBIDDEN_CONTEXT_KEYS
    for forbidden in [
        "market_code",
        "market_name",
        "spatial_candidate",
        "source_url",
        "link",
        "copy_text",
        "data_version",
        "stores_batch_ids",
        "map_version",
    ]:
        assert forbidden not in set(walk_keys(safe))
    for before, after in zip(original.data.indicators, p.context.indicators, strict=True):
        assert after.value == before.value and after.source == tuple(before.source)
        assert after.status == before.status and after.denominator == before.denominator
    assert p.prompt_version == "risk-interpret-v5"
    assert hashlib.sha256(serialize_context(safe).encode()).hexdigest() == p.context_hash
    assert serialize_context(safe) in p.request.user_content


def test_excluded_metadata_urls_and_internal_version_never_enter_prompt(monkeypatch):
    result = response()
    result.data.indicators[1].link = "https://example.invalid/PRIVATE-CANARY"
    result.data.indicators[0].source_url = "https://example.invalid/PRIVATE-CANARY"
    result.meta["raw_user"] = {
        "address": "PRIVATE-CANARY",
        "lat": 37.56789123,
        "floor_unit": "PRIVATE-CANARY",
    }
    result.meta["data_version"]["map_version"] = "PRIVATE-CANARY"
    p = prepare(monkeypatch, result=result)
    text = p.request.user_content
    assert "PRIVATE-CANARY" not in text
    assert "37.56789123" not in text and "126.98765432" not in text
    assert "00000000-0000-0000-0000-000000000042" not in text


def test_hash_determinism_and_version_separation_and_nested_immutability(monkeypatch):
    a = prepare(monkeypatch)
    result = response()
    result.meta = dict(reversed(list(result.meta.items())))
    b = prepare(monkeypatch, result=result)
    assert a == b and hash(a) == hash(b)
    q = query(lat=37.1, lng=127.1)
    c = prepare(monkeypatch, q)
    assert c.context_hash == a.context_hash
    result.meta["data_version"]["map_version"] = "synthetic-v2"
    d = prepare(monkeypatch, result=result)
    assert d.context_hash == a.context_hash and d.data_version_hash != a.data_version_hash
    payload = a.json_context()
    payload["indicators"][2]["value"] = 99
    assert a.json_context()["indicators"][2]["value"] == 20
    with pytest.raises(ValidationError):
        a.context.indicators[2].value = 99
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.context_hash = "bad"
    for rendered in (str(a), repr(a), f"{a!r}"):
        assert "indicators" not in rendered and "user_content" not in rendered


@pytest.mark.parametrize(
    "path,value",
    [
        ("reason", "PRIVATE-CANARY"),
        ("period", "PRIVATE-CANARY"),
        ("space", "PRIVATE-CANARY"),
        ("value", 37.56789123),
        ("value", float("nan")),
        ("value", float("inf")),
        ("numerator", True),
        ("seoul_avg", 37.56789123),
        ("source", ["PRIVATE-CANARY"]),
    ],
)
def test_bad_indicator_values_are_rejected_without_context_leak(monkeypatch, path, value, caplog):
    result = response()
    setattr(result.data.indicators[2], path, value)
    monkeypatch.setattr(module, "get_risk", Mock(return_value=result))
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    assert exc.value.__context__ is None
    assert "PRIVATE-CANARY" not in str(exc.value) + caplog.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_updated_at", "PRIVATE-CANARY"),
        ("as_of", "2025-01-31"),
        ("collected_at", "2026-11-12"),
        ("survival_basis", "PRIVATE-CANARY"),
        ("minimum_samples", {"closure": 1, "survival": 1}),
    ],
)
def test_unknown_provenance_or_methodology_rejected(monkeypatch, field, value):
    result = response()
    result.meta[field] = value
    monkeypatch.setattr(module, "get_risk", Mock(return_value=result))
    with pytest.raises(AppError):
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


def test_pending_zero_and_negative_zero_handling(monkeypatch):
    zero = ReferenceCounts(
        cohort_size=0,
        active=0,
        closure_num=0,
        closure_den=0,
        survival_1_num=0,
        survival_1_den=0,
        survival_3_num=0,
        survival_3_den=0,
    )
    p = prepare(monkeypatch, result=response(local=zero))
    assert p.context.indicators[2].value is None
    assert p.context.indicators[2].numerator is None and p.context.indicators[2].denominator == 0
    result = response(
        local=ReferenceCounts(
            cohort_size=10,
            active=10,
            closure_num=0,
            closure_den=10,
            survival_1_num=0,
            survival_1_den=0,
            survival_3_num=0,
            survival_3_den=0,
        )
    )
    result.data.indicators[2].value = -0.0
    monkeypatch.setattr(module, "get_risk", Mock(return_value=result))
    with pytest.raises(AppError):
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


def test_client_indicators_cannot_be_added_to_query():
    with pytest.raises(ValidationError):
        query(indicators=[{"id": "competitor_count", "value": 9999}])


def test_invalid_radius_and_prompt_failure_are_safe(monkeypatch, caplog):
    q = query()
    q.radius = 37.56789123
    guard = Mock(side_effect=AssertionError("must not recalculate"))
    monkeypatch.setattr(module, "get_risk", guard)
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(Mock(), q, Settings(_env_file=None))
    assert exc.value.__context__ is None and "37.56789123" not in str(exc.value) + caplog.text
    guard.assert_not_called()
    monkeypatch.setattr(module, "get_risk", Mock(return_value=response()))
    monkeypatch.setattr(
        module, "load_prompt_bundle", Mock(side_effect=PromptError("PRIVATE-CANARY"))
    )
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    assert "PRIVATE-CANARY" not in str(exc.value) + caplog.text and exc.value.__context__ is None


def test_provider_mock_receives_only_prepared_payload(monkeypatch):
    p = prepare(monkeypatch)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["text"] == p.request.user_content
        assert "37.56789123" not in request.content.decode()
        assert "126.98765432" not in request.content.decode()
        assert "stores_batch_ids" not in request.content.decode()
        requests.append(body)
        return httpx.Response(200, json=ok_body('{"summary":"확인된 참고지표를 안내합니다."}'))

    client = make_client(handler, Clock())
    output = asyncio.run(generate_verified(client, p.request, context=p.json_context()))
    assert output.generations == 1 and len(requests) == 1


@pytest.mark.parametrize("den", [0, 4])
def test_generated_server_sample_reasons_match_outbound_allowlist(monkeypatch, den):
    small = ReferenceCounts(
        cohort_size=den,
        active=den,
        closure_num=0,
        closure_den=den,
        survival_1_num=0,
        survival_1_den=den,
        survival_3_num=0,
        survival_3_den=den,
    )
    p = prepare(monkeypatch, result=response(local=small, seoul=small))
    expected = "zero_denominator" if den == 0 else "insufficient_sample"
    assert p.context.indicators[2].reason == expected
    assert p.context.indicators[2].seoul_avg_reason == expected


def test_server_result_must_match_requested_coordinates_and_month(monkeypatch):
    result = response()
    monkeypatch.setattr(module, "get_risk", Mock(return_value=result))
    for q in [query(lng=127.5), query(as_of="2025-01")]:
        with pytest.raises(AppError):
            module.prepare_risk_interpretation(Mock(), q, Settings(_env_file=None))
