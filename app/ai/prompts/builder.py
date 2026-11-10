"""서버 집계를 AI 해석 요청(LlmRequest)으로 조립한다.

허용 필드 추출은 BE-28 책임이다. 이 함수는 외부 전송 직전 마지막 관문으로 식별정보 키를
한 번 더 막는다(작업계획 8절). 값 내용은 검사하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import JsonValue

from app.ai.client import LlmRequest
from app.ai.prompts.loader import load_prompt_bundle

# stores·geocode·nearby의 실제 필드명 기준. 지표 식별은 `id`, 상권명은 `market_name`을 쓴다.
FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "address",
        "address_road",
        "address_jibun",
        "query",
        "lat",
        "lng",
        "latitude",
        "longitude",
        "raw_x",
        "raw_y",
        "geom",
        "center",
        "building_key",
        "floor_unit",
        "name",
        "store_name",
        "license_no",
        "brand_id",
        "phone",
        "tel",
    }
)


def _find_forbidden_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key.strip().lower() in FORBIDDEN_CONTEXT_KEYS:
                return key
            found = _find_forbidden_key(child)
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for child in value:
            found = _find_forbidden_key(child)
            if found is not None:
                return found
    return None


def serialize_context(context: Mapping[str, JsonValue]) -> str:
    """키 정렬·한글 유지·NaN 금지 JSON. 같은 내용이면 항상 같은 문자열이다."""
    forbidden = _find_forbidden_key(context)
    if forbidden is not None:
        raise ValueError(f"AI 입력에 식별정보 키를 넣을 수 없습니다: {forbidden}")
    try:
        return json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except ValueError:
        raise ValueError("AI 입력에 NaN·Infinity를 넣을 수 없습니다") from None


def build_interpret_request(
    context: Mapping[str, JsonValue],
    *,
    response_json_schema: Mapping[str, JsonValue] | None = None,
    max_output_tokens: int | None = None,
) -> LlmRequest:
    bundle = load_prompt_bundle()
    return LlmRequest(
        system_instruction=bundle.system_instruction,
        user_content=bundle.user_template.substitute(context_json=serialize_context(context)),
        response_json_schema=response_json_schema,
        max_output_tokens=max_output_tokens,
    )
