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
from app.schemas.common import ErrorCode
from app.schemas.risk import ReferenceCounts
from tests.ai.context_helpers import (
    history_query,
    history_row,
    query,
    response,
    use_history,
    use_risk,
)
from tests.ai.test_gemini import Clock, make_client, ok_body


def prepare(monkeypatch, q=None, result=None, **activity):
    q = q or query()
    server, recompute = use_risk(monkeypatch, module, result or response(q), q, **activity)
    session = Mock()
    settings = Settings(_env_file=None)
    output = module.prepare_risk_interpretation(session, q, settings)
    assert server.call_count == 1 and recompute.call_count == 1
    assert server.call_args.args[0] is session
    assert server.call_args.args[1].model_dump(exclude={"include_unknown"}) == q.model_dump(
        exclude={"include_unknown"}
    )
    assert recompute.call_args.args[0] is session
    sent = recompute.call_args.args[1]
    assert sent.include == () and sent.include_unknown is None
    assert sent.model_dump(exclude={"include", "include_unknown"}) == q.model_dump(
        exclude={"include", "include_unknown"}
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
    assert p.prompt_version == "risk-interpret-v7"
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
    use_risk(monkeypatch, module, result)
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
    use_risk(monkeypatch, module, result)
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
    use_risk(monkeypatch, module, result)
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
    monkeypatch.setattr(module, "get_activity", guard)
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(Mock(), q, Settings(_env_file=None))
    assert exc.value.__context__ is None and "37.56789123" not in str(exc.value) + caplog.text
    guard.assert_not_called()
    use_risk(monkeypatch, module, response())
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
    use_risk(monkeypatch, module, result)
    for q in [query(lng=127.5), query(as_of="2025-01")]:
        with pytest.raises(AppError):
            module.prepare_risk_interpretation(Mock(), q, Settings(_env_file=None))


def mutate(result, path, value):
    target = result
    *parents, last = path
    for key in parents:
        target = target[key] if isinstance(target, dict) else getattr(target, key)
    if isinstance(target, dict):
        target[last] = value
    else:
        setattr(target, last, value)


def test_activity_allowlist_matches_server_activity(monkeypatch):
    p = prepare(monkeypatch)
    activity = p.json_context()["activity"]
    assert set(activity) == {
        "space",
        "recent_period",
        "recent_opened",
        "recent_closed",
        "groups",
        "methodology",
    }
    assert activity["space"] == "radius_500m"
    assert activity["recent_period"] == "(2025-11-08, 2026-11-08]"
    assert (activity["recent_opened"], activity["recent_closed"]) == (3, 2)
    assert activity["groups"] == [
        {"sub_category": "cafe", "open_count": 8, "avg_operating_months": 41}
    ]
    assert activity["methodology"]["yearly_trend_included"] is False
    keys = set(walk_keys(activity))
    for forbidden in ["cohort_size", "stores_batch_ids", "yearly_trend", "license_no", "source"]:
        assert forbidden not in keys
    assert not keys & FORBIDDEN_CONTEXT_KEYS


def test_restaurant_groups_are_sorted_and_keep_zero_groups(monkeypatch):
    q = query(category="restaurant")
    p = prepare(monkeypatch, q, response(q))
    groups = p.json_context()["activity"]["groups"]
    assert [g["sub_category"] for g in groups] == ["chinese", "japanese", "korean", "western"]
    korean = next(g for g in groups if g["sub_category"] == "korean")
    assert korean == {"sub_category": "korean", "open_count": 8, "avg_operating_months": 41}
    assert all(g["avg_operating_months"] is None for g in groups if g["open_count"] == 0)


def test_activity_values_change_context_hash_and_rule_changes_version_hash(monkeypatch):
    a = prepare(monkeypatch)
    b = prepare(monkeypatch, opened=4)
    assert a.context_hash != b.context_hash and a.data_version_hash == b.data_version_hash
    monkeypatch.setattr(module, "ACTIVITY_RULE_VERSION", "market-activity-license-ytd-v2")
    result = response()
    _, recompute = use_risk(monkeypatch, module, result)
    recompute.return_value.meta["data_version"]["rule_version"] = "market-activity-license-ytd-v2"
    c = module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    assert c.context_hash == a.context_hash and c.data_version_hash != a.data_version_hash


@pytest.mark.parametrize(
    "path,value",
    [
        (("meta", "as_of"), "2026-11-07"),
        (("meta", "data_updated_at"), "2026-11-09"),
        (("meta", "space"), "radius_300m"),
        (("meta", "cohort_size"), 21),
        (("meta", "cohort_size"), "20"),
        (("meta", "collected_at"), "2026-11-12"),
        (("meta", "denominator"), 8),
        (("meta", "source"), ["R5"]),
        (("meta", "franchise_classification"), {"status": "estimate"}),
        (("meta", "data_version", "stores_batch_ids"), ["00000000-0000-0000-0000-000000000099"]),
        (("meta", "data_version", "map_version"), "PRIVATE-CANARY"),
        (("meta", "data_version", "rule_version"), "market-activity-license-ytd-v0"),
        (("meta", "data_version", "brand_mapping"), {"reference_year": 2025}),
        (("data", "recent_12m", "closed"), 3),
        (("data", "recent_12m", "period"), "(2025-11-07, 2026-11-07]"),
        (("data", "error"), None),
    ],
)
def test_activity_drift_from_risk_is_rejected_without_leak(monkeypatch, path, value, caplog):
    result = response()
    _, recompute = use_risk(monkeypatch, module, result)
    activity = recompute.return_value
    if path == ("data", "error"):
        activity.data = None
    elif path[0] == "meta":
        mutate(activity.meta, path[1:], value)
    else:
        mutate(activity.data, path[1:], value)
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    assert exc.value.__context__ is None
    assert "PRIVATE-CANARY" not in str(exc.value) + caplog.text


def test_activity_group_counts_and_scope_must_match_risk(monkeypatch):
    for change in ("open_count", "scope", "optional", "missing"):
        result = response()
        _, recompute = use_risk(monkeypatch, module, result)
        data = recompute.return_value.data
        if change == "open_count":
            data.by_sub_category[0].open_count = 9
        elif change == "scope":
            data.by_sub_category[0].sub_category = "korean"
        elif change == "optional":
            data.flags.missing = ["sales"]
        else:
            recompute.return_value.meta.pop("cohort_size")
        with pytest.raises(AppError):
            module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


def test_closure_numerator_must_match_recent_closed_when_available(monkeypatch):
    result = response()
    _, recompute = use_risk(monkeypatch, module, result)
    activity = recompute.return_value
    activity.data.recent_12m.closed = 1
    activity.data.by_sub_category[0].open_count = 9
    with pytest.raises(AppError):
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


def test_activity_service_errors_propagate_unchanged(monkeypatch):
    use_risk(monkeypatch, module, response())
    failure = AppError(ErrorCode.INTERNAL_ERROR)
    monkeypatch.setattr(module, "get_activity", Mock(side_effect=failure))
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    assert exc.value is failure


def prepare_history(monkeypatch, rows, hq=None, result=None):
    result = result or response()
    use_risk(monkeypatch, module, result)
    hq = hq or history_query()
    location, server = use_history(monkeypatch, module, result, rows)
    session = Mock()
    output = module.prepare_risk_interpretation(
        session, query(), Settings(_env_file=None), history=hq
    )
    assert location.call_count == 1 and location.call_args.args[0] is session
    assert location.call_args.args[2] is hq
    assert server.call_count == 1 and server.call_args.args == (session, hq)
    return output


MIXED = [
    history_row("same_spot", "closed", 14, index=0),
    history_row("same_spot", "closed", 30, index=1),
    history_row("same_spot", "closed", None, index=2),
    history_row("same_spot", "open", 5, index=3),
    history_row(
        "same_building", "closed", 50, category="restaurant", sub_category="korean", index=4
    ),
    history_row("unverified", "other", None, index=5),
]


def test_history_aggregates_without_row_identifiers(monkeypatch, caplog):
    p = prepare_history(monkeypatch, MIXED)
    h = p.json_context()["history"]
    assert {k: v for k, v in h.items() if k != "methodology"} == {
        "basis": "latest_data_all_supported_categories",
        "data_updated_at": "2026-11-08",
        "floor_unit_provided": True,
        "same_spot_comparable": True,
        "total": 6,
        "same_category": 5,
        "same_spot": 4,
        "same_building": 1,
        "unverified": 1,
        "same_spot_open": 1,
        "same_spot_closed": 3,
        "same_spot_other": 0,
        "same_spot_closed_period_count": 2,
        "same_spot_closed_months_min": 14,
        "same_spot_closed_months_max": 30,
    }
    text = p.request.user_content + caplog.text + repr(p)
    for canary in ["PRIVATE-NAME", "PRIVATE-LICENSE", "PRIVATE-FLOOR", "마포구-서교동", "101호"]:
        assert canary not in text
    assert not set(walk_keys(p.json_context())) & FORBIDDEN_CONTEXT_KEYS


def test_history_absent_keeps_null_and_skips_lookups(monkeypatch):
    p = prepare(monkeypatch)
    assert p.json_context()["history"] is None


def test_floor_missing_or_floor_only_is_not_comparable(monkeypatch):
    rows = [history_row("unverified", "closed", 10, index=0)]
    p = prepare_history(monkeypatch, rows, history_query(floor_unit=None))
    h = p.json_context()["history"]
    assert (h["floor_unit_provided"], h["same_spot_comparable"], h["unverified"]) == (
        False,
        False,
        1,
    )
    rows = [history_row("same_building", "closed", 10, index=0)]
    p = prepare_history(monkeypatch, rows, history_query(floor_unit="2층"))
    h = p.json_context()["history"]
    assert (h["floor_unit_provided"], h["same_spot_comparable"], h["same_spot"]) == (True, False, 0)


def test_empty_history_is_valid(monkeypatch):
    p = prepare_history(monkeypatch, [])
    h = p.json_context()["history"]
    assert h["total"] == 0 and h["same_spot_closed_months_min"] is None


def test_history_changes_hashes(monkeypatch):
    without = prepare(monkeypatch)
    a = prepare_history(monkeypatch, MIXED)
    b = prepare_history(monkeypatch, MIXED[:-1])
    assert a.data_version_hash != without.data_version_hash
    assert a.data_version_hash == b.data_version_hash and a.context_hash != b.context_hash


@pytest.mark.parametrize(
    "path,value",
    [
        (("meta", "data_updated_at"), "2026-11-09"),
        (("meta", "as_of"), "2026-11-07"),
        (("meta", "denominator"), 5),
        (("meta", "collected_at"), "2026-11-12"),
        (("meta", "franchise_classification"), {"status": "estimate"}),
        (("meta", "data_version", "stores_batch_ids"), ["00000000-0000-0000-0000-000000000099"]),
        (("meta", "data_version", "rule_version"), "store-history-calendar-months-v0"),
        (("meta", "data_version", "map_version"), "PRIVATE-CANARY"),
        (("data", "total"), 5),
        (("data", "error"), None),
    ],
)
def test_history_drift_from_risk_is_rejected(monkeypatch, path, value, caplog):
    result = response()
    use_risk(monkeypatch, module, result)
    _, server = use_history(monkeypatch, module, result, MIXED)
    building = server.return_value
    if path == ("data", "error"):
        building.data = None
    elif path[0] == "meta":
        mutate(building.meta, path[1:], value)
    else:
        mutate(building.data, path[1:], value)
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(
            Mock(), query(), Settings(_env_file=None), history=history_query()
        )
    assert exc.value.code == ErrorCode.INTERNAL_ERROR and exc.value.__context__ is None
    assert "PRIVATE" not in str(exc.value) + caplog.text


def test_location_rule_mismatch_and_comparability_are_rejected(monkeypatch):
    for hq, rows in [
        (history_query(floor_unit=None), [history_row("same_building", index=0)]),
        (history_query(floor_unit="2층"), [history_row("same_spot", index=0)]),
    ]:
        result = response()
        use_risk(monkeypatch, module, result)
        use_history(monkeypatch, module, result, rows)
        with pytest.raises(AppError) as exc:
            module.prepare_risk_interpretation(
                Mock(), query(), Settings(_env_file=None), history=hq
            )
        assert exc.value.code == ErrorCode.INTERNAL_ERROR


def test_far_building_is_invalid_param_and_skips_history(monkeypatch):
    result = response()
    use_risk(monkeypatch, module, result)
    _, server = use_history(monkeypatch, module, result, MIXED)
    far = AppError(ErrorCode.INVALID_PARAM)
    monkeypatch.setattr(module, "check_history_location", Mock(side_effect=far))
    with pytest.raises(AppError) as exc:
        module.prepare_risk_interpretation(
            Mock(), query(), Settings(_env_file=None), history=history_query()
        )
    assert exc.value is far and server.call_count == 0


@pytest.mark.parametrize("nearest,ok", [(None, True), (0.0, True), (300.0, True), (300.01, False)])
def test_check_history_location_threshold(nearest, ok):
    session = Mock()
    session.scalar.return_value = nearest
    if ok:
        assert module.check_history_location(session, query(), history_query()) is None
    else:
        with pytest.raises(AppError) as exc:
            module.check_history_location(session, query(), history_query())
        assert exc.value.code == ErrorCode.INVALID_PARAM
    sql = str(session.scalar.call_args.args[0])
    assert "building_key" in sql and "ST_Distance" in sql


def test_floor_unit_normalization_is_idempotent():
    for raw in ["1층 101호", "B1", "2층", "지하1층 B101호", "162C호"]:
        once = history_query(floor_unit=raw).floor_unit
        assert history_query(floor_unit=once).floor_unit == once
