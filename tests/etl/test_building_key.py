from __future__ import annotations

import logging
import random
import unicodedata

import pytest

from etl.address.building_key import (
    BuildingKeyFailure,
    build_from_parts,
    parse_jibun_address,
)


def assert_key(address: str, expected: str, *, authority_code: str | None = "3130000") -> None:
    if address.startswith("서울") and authority_code == "3130000":
        authority_code = None
    result = parse_jibun_address(address, authority_code=authority_code)
    assert result.failure is None
    assert result.lot is not None
    assert result.lot.key == expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("서울특별시 마포구 서교동 123-4", "마포구-서교동-123-4"),
        ("마포구 서교동 123", "마포구-서교동-123-0"),
        ("마포구 상암동 산12-3", "마포구-상암동-산12-3"),
        ("마포구 상암동 산 12-3", "마포구-상암동-산12-3"),
        ("마포구 서교동 0012-03번지", "마포구-서교동-12-3"),
        ("마포구 서교동 9999-9999", "마포구-서교동-9999-9999"),
        ("서울특별시 마포구 여의도동 12", "마포구-여의도동-12-0"),
        ("서울특별시 종로구 종로1가 12", "종로구-종로1가-12-0"),
        ("서울특별시 성동구 성수동1가 12", "성동구-성수동1가-12-0"),
        ("서울특별시 서초구 반포동 1109 반포래미안트리니원 162C호", "서초구-반포동-1109-0"),
        ("마포구 서교동 123-4(서교빌딩) 2층 201호", "마포구-서교동-123-4"),
        ("마포구 서교동 123-4 101호", "마포구-서교동-123-4"),
        ("마포구 서교동 123 외 1필지", "마포구-서교동-123-0"),
        ("마포구 서교동 123 외1필지", "마포구-서교동-123-0"),
        ("마포구 서교동 123 외 12 필지", "마포구-서교동-123-0"),
    ],
)
def test_parse_jibun_address_returns_canonical_key(address: str, expected: str) -> None:
    assert_key(address, expected)


@pytest.mark.parametrize(
    "address",
    [
        "마포구 양화로 123",
        "마포구 양화로6길 12",
        "종로구 세종대로 1",
        "종로구 세종로 1",
        "노원구 상계1동 123",
        "종로구 종로1·2·3·4가동 1",
    ],
)
def test_unsupported_legal_dong_never_builds_a_key(address: str) -> None:
    result = parse_jibun_address(f"서울특별시 {address}")
    assert result.lot is None
    assert result.failure is BuildingKeyFailure.LEGAL_DONG_UNSUPPORTED


@pytest.mark.parametrize(
    ("address", "failure"),
    [
        ("마포구 서교동 123번지 4호", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 123 4", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 123 101호", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 123-4 5", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 123 외 다수", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 12.5", BuildingKeyFailure.INVALID),
        ("마포구 서교동 -3", BuildingKeyFailure.INVALID),
        ("마포구 서교동 12-3-4", BuildingKeyFailure.INVALID),
        ("마포구 서교동 0", BuildingKeyFailure.INVALID),
        ("마포구 서교동 00012", BuildingKeyFailure.INVALID),
        ("마포구 서교동 10000", BuildingKeyFailure.INVALID),
        ("마포구 서교동 ( 123", BuildingKeyFailure.INVALID),
        ("마포구 서교동 123 (a(b))", BuildingKeyFailure.INVALID),
        ("마포구 서교동 123, 124", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 123 / 124", BuildingKeyFailure.AMBIGUOUS),
        ("마포구 서교동 123 및 124", BuildingKeyFailure.AMBIGUOUS),
    ],
)
def test_invalid_or_ambiguous_lot_has_expected_failure(
    address: str,
    failure: BuildingKeyFailure,
) -> None:
    result = parse_jibun_address(address, authority_code="3130000")
    assert result.lot is None
    assert result.failure is failure


def test_authority_context_fallback_conflict_and_non_seoul() -> None:
    assert_key("서교동 123", "마포구-서교동-123-0")
    assert_key("서울 중구 신당동 1", "중구-신당동-1-0", authority_code="3010000")
    assert parse_jibun_address("중구 신당동 1").failure is BuildingKeyFailure.AMBIGUOUS
    assert (
        parse_jibun_address("마포구 서교동 123", authority_code="3000000").failure
        is BuildingKeyFailure.GU_CONFLICT
    )
    assert_key("종로구 청운동 1", "종로구-청운동-1-0", authority_code="6110000")
    assert (
        parse_jibun_address("서울 서교동 123", authority_code="6110000").failure
        is BuildingKeyFailure.GU_MISSING
    )
    assert parse_jibun_address("부산광역시 중구 신창동 1").failure is BuildingKeyFailure.NON_SEOUL
    assert parse_jibun_address("서울특별시 해운대구 우동 1").failure is BuildingKeyFailure.NON_SEOUL
    assert (
        parse_jibun_address("마포구서교동 123", authority_code="3130000").failure
        is BuildingKeyFailure.INVALID
    )
    assert (
        parse_jibun_address("서울특별시마포구 서교동 123", authority_code="3130000").failure
        is BuildingKeyFailure.INVALID
    )


def test_unicode_normalization_is_deterministic() -> None:
    expected = "마포구-서교동-123-4"
    assert_key("마포구\u3000서교동\t１２３−４", expected)
    assert_key(unicodedata.normalize("NFD", "마포구 서교동 123–4"), expected)
    for address in (
        "마포구 서교동 ①",
        "마포구 서교동 ١٢٣",
        "마포구 서교동 12—3",
        "마포\u200b구 서교동 123",
    ):
        assert parse_jibun_address(address, authority_code="3130000").lot is None


def test_input_contract_and_no_address_leakage(caplog: pytest.LogCaptureFixture) -> None:
    canary = "SECRET-ADDRESS-8472"
    caplog.set_level(logging.DEBUG)
    result = parse_jibun_address(f"마포구 서교동 {canary}", authority_code="3130000")
    assert result.failure is BuildingKeyFailure.LOT_MISSING
    assert canary not in repr(result)
    assert canary not in caplog.text
    with pytest.raises(TypeError, match="int") as error:
        parse_jibun_address(123)  # type: ignore[arg-type]
    assert "123" not in str(error.value)


def test_length_and_random_strings_do_not_raise() -> None:
    assert parse_jibun_address("가" * 1001).failure is BuildingKeyFailure.INVALID
    assert parse_jibun_address("가" * 1000).lot is None
    randomizer = random.Random(9)
    alphabet = "가나다라마바사 0123-()외필지/,~;\t"
    for _ in range(100):
        address = "".join(randomizer.choice(alphabet) for _ in range(100))
        parse_jibun_address(address, authority_code="3130000")


def test_build_from_parts_matches_parser_and_rejects_invalid_parts() -> None:
    result = build_from_parts("마포구", "서교동", 123, 4)
    assert result.lot is not None
    assert result.lot.key == "마포구-서교동-123-4"
    assert build_from_parts("부산진구", "부전동", 1).failure is BuildingKeyFailure.NON_SEOUL
    assert (
        build_from_parts("마포구", "세종로", 1).failure is BuildingKeyFailure.LEGAL_DONG_UNSUPPORTED
    )
    assert build_from_parts("마포구", "서교동", True).failure is BuildingKeyFailure.INVALID
    assert build_from_parts("마포구", "서교동", 10000).failure is BuildingKeyFailure.INVALID
