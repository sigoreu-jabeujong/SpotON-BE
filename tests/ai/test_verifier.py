import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from app.ai.verifier import (
    VerifyFailure,
    VerifyPolicy,
    VerifyResult,
    allowed_numbers,
    verify_output,
)

CONTEXT: dict[str, Any] = {
    "category": "cafe",
    "radius_m": 500,
    "as_of": "2026-09",
    "source": ["R8"],
    "indicators": [
        {"id": "competitor_count", "type": "reference", "value": 1200, "status": "ok"},
        {"id": "closure_rate_12m", "type": "reference", "value": 12.53, "status": "ok"},
        {"id": "survival_rate_3y", "type": "reference", "value": None, "status": "pending"},
        {"id": "official_closure_rate", "type": "official", "value": None, "status": "no_data"},
        {"id": "precise_rate", "type": "reference", "value": 37.1234, "status": "ok"},
    ],
    "market_name": "홍대입구역",
}


def verify(output: Any, **kwargs: Any) -> VerifyResult:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return verify_output(text, context=kwargs.pop("context", CONTEXT), **kwargs)


def failures(output: Any, **kwargs: Any) -> set[VerifyFailure]:
    return set(verify(output, **kwargs).failures)


def summary(text: str) -> dict[str, Any]:
    return {"summary": text}


def test_valid_interpretation_passes_and_returns_data() -> None:
    output = {
        "summary": (
            "2026-09 기준 반경 500m 안의 동종 카페는 1,200곳입니다. "
            "최근 12개월 참고 폐업률은 12.5%이며 3년 생존율은 자료가 준비 중입니다. "
            "서울시 창업위험도 안내를 함께 확인해 주세요. 이 결과는 참고용 정보입니다."
        ),
        "indicators": [{"id": "survival_rate_3y", "value": None}],
        "sources": ["R8"],
    }
    result = verify(output)
    assert result.ok
    assert result.failures == ()
    assert result.data == output


def test_allowed_numbers_include_values_strings_and_keys() -> None:
    numbers = allowed_numbers(CONTEXT)
    for expected in ["500", "2026", "9", "8", "1200", "12.53", "3", "12"]:
        assert Decimal(expected) in numbers


@pytest.mark.parametrize("text", ["not json", "{", '{"a": NaN}', '{"a": Infinity}', ""])
def test_malformed_json(text: str) -> None:
    assert verify(text).failures == (VerifyFailure.MALFORMED_JSON,)


@pytest.mark.parametrize("text", ["[]", '"요약"', "12", "null"])
def test_top_level_must_be_object(text: str) -> None:
    assert verify(text).failures == (VerifyFailure.NOT_OBJECT,)


class Interpretation(BaseModel):
    summary: str


def test_schema_mismatch_uses_given_model() -> None:
    assert failures({"summary": "자료 없음"}, response_model=Interpretation) == set()
    assert VerifyFailure.SCHEMA_MISMATCH in failures(
        {"headline": "자료 없음"}, response_model=Interpretation
    )


@pytest.mark.parametrize(
    "output",
    [
        summary("동종 카페는 1,300곳입니다."),
        summary("폐업률이 15%로 높습니다."),
        {"summary": "요약", "count": 7},
        summary("폐업률은 약 13%입니다."),  # 정수 반올림은 새 숫자로 본다
        summary("폐업률은 0.1253입니다."),  # 비율↔백분율 환산 불허
        summary("2026.09 기준입니다."),
    ],
)
def test_unknown_numbers_fail(output: dict[str, Any]) -> None:
    assert VerifyFailure.UNKNOWN_NUMBER in failures(output)


@pytest.mark.parametrize(
    "text",
    [
        "폐업률은 12.53%입니다.",
        "폐업률은 12.5%입니다.",
        "폐업률은 12.530%입니다.",
        "동종 카페는 1200곳입니다.",
        "반경 500m 기준입니다.",
    ],
)
def test_allowed_number_forms_pass(text: str) -> None:
    assert VerifyFailure.UNKNOWN_NUMBER not in failures(summary(text))


@pytest.mark.parametrize(
    "text",
    [
        "창업 성공률이 높습니다.",
        "성공 확률은 알 수 없습니다.",
        "성공 가능성이 큽니다.",
        "이 입지를 추천합니다.",
        "비추천 입지입니다.",
        "위험 점수는 낮습니다.",
        "위험등급은 보통입니다.",
        "LQ가 높습니다.",
        "입지 계수가 큽니다.",
        "반드시 성공합니다.",
        "무조건 실패합니다.",
        "곧 폐업할 것입니다.",
        "이 자리는 망할 수 있습니다.",
    ],
)
def test_forbidden_expressions_fail(text: str) -> None:
    assert VerifyFailure.FORBIDDEN_EXPRESSION in failures(summary(text))


def test_official_risk_guide_name_is_not_forbidden() -> None:
    assert failures(summary("서울시 창업위험도 안내를 확인해 주세요.")) == set()


def test_decimal_points_do_not_create_false_repeated_sentences() -> None:
    context = {"values": [80.0, 40.0], "denominator": 5}
    text = (
        "개업 기간 비율은 80.0%이며 분모는 5건입니다. 다른 기간 비율은 40.0%이며 분모는 5건입니다."
    )
    assert VerifyFailure.REPETITION not in failures(summary(text), context=context)


@pytest.mark.parametrize("indicator_id", ["survival_rate_3y", "official_closure_rate"])
def test_pending_indicator_with_value_fails(indicator_id: str) -> None:
    output = {"summary": "요약", "indicators": [{"id": indicator_id, "value": 500}]}
    assert VerifyFailure.PENDING_AS_VALUE in failures(output)


@pytest.mark.parametrize("status", ["link_only", "unverified"])
def test_unavailable_values_rejected_even_if_number_is_known(status):
    context = {
        "radius_m": 500,
        "indicators": [{"id": "official_risk", "status": status, "value": None}],
    }
    verdict = verify_output(
        json.dumps({"indicators": [{"id": "official_risk", "value": 500}]}), context=context
    )
    assert VerifyFailure.PENDING_AS_VALUE in verdict.failures


def test_pending_indicator_with_null_value_and_ok_indicator_pass() -> None:
    output = {
        "summary": "요약",
        "indicators": [
            {"id": "survival_rate_3y", "value": None},
            {"id": "competitor_count", "value": 1200},
        ],
    }
    assert failures(output) == set()


@pytest.mark.parametrize(
    "output",
    [
        {"summary": "요약", "source": "R9"},
        {"summary": "요약", "sources": ["R8", "블로그"]},
        {"summary": "요약", "detail": {"Source": "뉴스"}},
    ],
)
def test_unknown_source_fails(output: dict[str, Any]) -> None:
    assert VerifyFailure.UNKNOWN_SOURCE in failures(output)


def test_source_without_any_input_source_fails() -> None:
    assert VerifyFailure.UNKNOWN_SOURCE in failures(
        {"summary": "요약", "source": "R8"}, context={"radius_m": 500}
    )


@pytest.mark.parametrize(
    "text",
    [
        "문의는 010-1234-5678로 주세요.",
        "문의는 02 123 4567입니다.",
        "owner@example.com으로 연락하세요.",
        "서울 마포구 양화로 160에 있습니다.",
        "와우산로29길 5 건물입니다.",
        "서교동 123-4번지입니다.",
        "2층 201호 자리입니다.",
        "B1 매장입니다.",
        "좌표는 37.556312입니다.",
        "마포구-서교동-123-4 건물입니다.",
    ],
)
def test_personal_info_patterns_fail(text: str) -> None:
    assert VerifyFailure.PERSONAL_INFO in failures(summary(text))


@pytest.mark.parametrize(
    "text",
    [
        "반경 500m 기준으로 1200곳입니다.",
        "500m로 보면 1200곳입니다.",
        "참고 지표로 3년 생존율은 준비 중입니다.",
        "정밀 비율 37.1234도 참고 지표입니다.",
        "홍대입구역 상권 기준입니다.",
    ],
)
def test_personal_info_patterns_avoid_common_phrases(text: str) -> None:
    assert VerifyFailure.PERSONAL_INFO not in failures(summary(text))


@pytest.mark.parametrize("key", ["address", "Lat", " building_key ", "license_no", "name"])
def test_forbidden_output_keys_are_personal_info(key: str) -> None:
    assert VerifyFailure.PERSONAL_INFO in failures({"summary": "요약", key: "x"})


def test_too_long() -> None:
    policy = VerifyPolicy(max_chars=20)
    assert VerifyFailure.TOO_LONG in failures(summary("가" * 21), policy=policy)
    assert VerifyFailure.TOO_LONG not in failures(summary("가" * 20), policy=policy)


def test_repeated_long_sentence_fails_but_short_phrase_passes() -> None:
    sentence = "이 결과는 참고용 정보입니다"
    assert VerifyFailure.REPETITION in failures(
        {"summary": f"{sentence}. {sentence}.", "note": "자료 없음"}
    )
    assert VerifyFailure.REPETITION in failures({"a": sentence, "b": f" {sentence} "})
    assert VerifyFailure.REPETITION not in failures({"a": "자료 없음", "b": "자료 없음"})


def test_multiple_failures_are_collected_in_stable_order() -> None:
    result = verify(summary("성공률은 99%이고 010-1234-5678로 문의하세요."))
    assert result.failures == (
        VerifyFailure.UNKNOWN_NUMBER,
        VerifyFailure.FORBIDDEN_EXPRESSION,
        VerifyFailure.PERSONAL_INFO,
    )
    assert result.data is None
    assert not result.ok


def test_result_repr_hides_output() -> None:
    passed = verify(summary("SECRET 자료 없음"))
    failed = verify(summary("SECRET 성공률"))
    assert "SECRET" not in repr(passed)
    assert "SECRET" not in repr(failed)


def test_extremely_precise_number_is_unknown_not_crash() -> None:
    text = "1200." + "0" * 40 + "1"
    assert VerifyFailure.UNKNOWN_NUMBER in failures(summary(f"동종 카페 {text}곳"))
