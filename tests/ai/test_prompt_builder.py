import json
import math
from typing import Any

import pytest

from app.ai.client import LlmRequest
from app.ai.prompts import (
    FORBIDDEN_CONTEXT_KEYS,
    build_interpret_request,
    load_prompt_bundle,
)
from app.ai.prompts.builder import serialize_context

CONTEXT: dict[str, Any] = {
    "category": "cafe",
    "radius_m": 500,
    "as_of": "2026-09",
    "indicators": [
        {"id": "competitor_count", "type": "reference", "value": 12, "status": "ok"},
        {"id": "official_closure_rate", "type": "official", "value": None, "status": "no_data"},
    ],
    "market_name": "홍대입구역",
    "missing_items": ["living_pop"],
}


def embedded_context(request: LlmRequest) -> Any:
    start = request.user_content.index("<context>\n") + len("<context>\n")
    end = request.user_content.index("\n</context>")
    return json.loads(request.user_content[start:end])


def test_builds_llm_request_from_prompt_files() -> None:
    request = build_interpret_request(CONTEXT)
    bundle = load_prompt_bundle()
    assert isinstance(request, LlmRequest)
    assert request.system_instruction == bundle.system_instruction
    assert embedded_context(request) == CONTEXT
    assert "$context_json" not in request.user_content
    assert request.response_json_schema is None
    assert request.max_output_tokens is None


def test_schema_and_output_tokens_are_passed_through() -> None:
    schema = {"type": "object"}
    request = build_interpret_request(CONTEXT, response_json_schema=schema, max_output_tokens=256)
    assert request.response_json_schema == schema
    assert request.max_output_tokens == 256


def test_same_content_in_different_key_order_builds_same_prompt() -> None:
    reordered = dict(reversed(list(CONTEXT.items())))
    assert build_interpret_request(reordered).user_content == (
        build_interpret_request(CONTEXT).user_content
    )


def test_serialization_is_compact_sorted_and_keeps_korean() -> None:
    assert serialize_context({"b": "홍대", "a": [1, 2]}) == '{"a":[1,2],"b":"홍대"}'


def test_dollar_text_in_values_is_not_substituted_again() -> None:
    request = build_interpret_request({"note": "$context_json ${context_json} $$ $5"})
    assert embedded_context(request) == {"note": "$context_json ${context_json} $$ $5"}


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_are_rejected(number: float) -> None:
    with pytest.raises(ValueError, match="NaN"):
        build_interpret_request({"value": number})


@pytest.mark.parametrize(
    "context",
    [
        {"address": "SECRET-서울 마포구"},
        {"meta": {"lat": 37.5, "lng": 126.9}},
        {"stores": [{"Name": "SECRET-상호"}]},
        {"stores": [[{"license_no": "SECRET-123"}]]},
        {"center": {"value": 1}},
        {" Building_Key ": "SECRET-마포구-서교동-1-0"},
        {"items": ({"floor_unit": "SECRET-2층"},)},
    ],
)
def test_identifying_keys_are_rejected_without_echoing_values(context: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as raised:
        build_interpret_request(context)
    assert "식별정보" in str(raised.value)
    assert "SECRET" not in str(raised.value)
    assert raised.value.__context__ is None


def test_allowed_keys_and_identifier_like_values_pass() -> None:
    # 값 내용은 검사하지 않는다(키 이름 기준 차단). 오탐을 피하기 위한 의도된 한계다.
    request = build_interpret_request({"id": "name", "label": "address", "market_name": "명동"})
    assert embedded_context(request)["market_name"] == "명동"


def test_forbidden_keys_cover_store_and_location_identifiers() -> None:
    assert {
        "address_road",
        "address_jibun",
        "lat",
        "lng",
        "geom",
        "building_key",
        "floor_unit",
        "name",
        "license_no",
    } <= FORBIDDEN_CONTEXT_KEYS
    assert all(key == key.lower() for key in FORBIDDEN_CONTEXT_KEYS)
