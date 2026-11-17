from __future__ import annotations

import logging
import random

import pytest

from etl.address.floor_unit import (
    FloorUnitFailure,
    FloorUnitResult,
    FloorUnitValue,
    LocationLevel,
    parse_floor_unit,
    reconcile_floor_units,
)


def assert_value(address: str, expected: str, level: LocationLevel) -> None:
    result = parse_floor_unit(address)
    assert result.failure is None
    assert result.value is not None
    assert result.value.value == expected
    assert result.value.location_level is level


@pytest.mark.parametrize(
    ("address", "expected", "level"),
    [
        ("서울 마포구 테스트로 1 1층", "1층", LocationLevel.SAME_BUILDING),
        ("서울 마포구 테스트로 1 01층", "1층", LocationLevel.SAME_BUILDING),
        ("서울 마포구 테스트로 1 2F", "2층", LocationLevel.SAME_BUILDING),
        ("서울 마포구 테스트로 1 지하 1층", "B1", LocationLevel.SAME_BUILDING),
        ("서울 마포구 테스트로 1 B1F", "B1", LocationLevel.SAME_BUILDING),
        ("서울 마포구 테스트로 1 2층 201호", "2층 201호", LocationLevel.SAME_SPOT),
        ("서울 마포구 테스트로 1 201호 2층", "2층 201호", LocationLevel.SAME_SPOT),
        ("서울 마포구 테스트로 1 2층-201호", "2층 201호", LocationLevel.SAME_SPOT),
        ("서울 마포구 테스트로 1 162c호", "162C호", LocationLevel.SAME_BUILDING),
        ("서울 마포구 테스트로 1 B1 b101호", "B1 B101호", LocationLevel.SAME_SPOT),
        ("서울 마포구 테스트로 1 1 층", "1층", LocationLevel.SAME_BUILDING),
    ],
)
def test_parse_floor_unit_normalizes_explicit_details(
    address: str,
    expected: str,
    level: LocationLevel,
) -> None:
    assert_value(address, expected, level)


@pytest.mark.parametrize(
    "address",
    [
        "서울 마포구 테스트로 101",
        "서울 마포구 테스트로 45-1",
        "서울 마포구 테스트로 지하 12",
        "서울 마포구 서교동 123-4번지",
        "서울 마포구 산12-3",
        "서울 마포구 테스트로 101 (2층)",
        "서울 마포구 3호선 대호빌딩",
    ],
)
def test_parse_floor_unit_does_not_guess_from_address_numbers(address: str) -> None:
    result = parse_floor_unit(address)
    assert result.value is None
    assert result.failure is FloorUnitFailure.NO_DETAIL


@pytest.mark.parametrize(
    ("address", "failure"),
    [
        ("테스트로 1 1~2층", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 1,2층", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 1/2층", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 123,2층", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 201~203호", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 101동 1203호", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 반지하 1층", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 395번지 17호", FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 101-1호", FloorUnitFailure.INVALID),
        ("테스트로 1 1층–201호", FloorUnitFailure.INVALID),
        ("테스트로 1 0층", FloorUnitFailure.INVALID),
        ("테스트로 1 1000층", FloorUnitFailure.INVALID),
        ("테스트로 1 10000호", FloorUnitFailure.INVALID),
        ("테스트로 1 1A2호", FloorUnitFailure.INVALID),
        ("테스트로 1 (2층", FloorUnitFailure.INVALID),
    ],
)
def test_parse_floor_unit_rejects_ambiguous_or_invalid_details(
    address: str,
    failure: FloorUnitFailure,
) -> None:
    result = parse_floor_unit(address)
    assert result.value is None
    assert result.failure is failure


def test_comma_with_whitespace_is_a_deliberate_documented_limit() -> None:
    assert_value("테스트로 45, 2층", "2층", LocationLevel.SAME_BUILDING)
    assert_value("테스트로 123, 2층 201호", "2층 201호", LocationLevel.SAME_SPOT)


@pytest.mark.parametrize(
    ("road", "jibun", "expected", "failure"),
    [
        ("테스트로 1 2층 201호", "서교동 1 2층 201호", "2층 201호", None),
        ("테스트로 1 2층", "서교동 1", "2층", None),
        ("테스트로 1 2층", "서교동 1 2층 201호", None, FloorUnitFailure.AMBIGUOUS),
        ("테스트로 1 2층", "서교동 1 101-1호", None, FloorUnitFailure.INVALID),
        ("테스트로 1", "서교동 1", None, FloorUnitFailure.NO_DETAIL),
        (None, None, None, FloorUnitFailure.EMPTY),
    ],
)
def test_reconcile_floor_units_is_conservative_and_symmetric(
    road: str | None,
    jibun: str | None,
    expected: str | None,
    failure: FloorUnitFailure | None,
) -> None:
    left = parse_floor_unit(road)
    right = parse_floor_unit(jibun)
    result = reconcile_floor_units(left, right)
    assert result == reconcile_floor_units(right, left)
    assert result.failure is failure
    assert (result.value.value if result.value is not None else None) == expected


def test_unicode_input_contract_and_privacy(caplog: pytest.LogCaptureFixture) -> None:
    assert_value("테스트로\u3000１층\u3000２０１호", "1층 201호", LocationLevel.SAME_SPOT)
    for address in ("테스트로 ①층", "테스트로 ١층", "테스트로\u200b 1층"):
        assert parse_floor_unit(address).failure is FloorUnitFailure.INVALID
    canary = "SECRET-FLOOR-472"
    caplog.set_level(logging.DEBUG)
    result = parse_floor_unit(f"테스트로 1 {canary}")
    assert result.failure is FloorUnitFailure.NO_DETAIL
    assert canary not in repr(result)
    assert canary not in caplog.text
    with pytest.raises(TypeError, match="int") as error:
        parse_floor_unit(1)  # type: ignore[arg-type]
    assert "1" not in str(error.value)


def test_random_strings_do_not_raise_and_values_hide_detail_in_repr() -> None:
    assert "201호" not in repr(FloorUnitValue("2층", "201호"))
    assert "201호" not in repr(_success(FloorUnitValue("2층", "201호")))
    randomizer = random.Random(7)
    alphabet = "가나다라마바사 0123층호BF,/-~()\t"
    for _ in range(1000):
        parse_floor_unit("".join(randomizer.choice(alphabet) for _ in range(40)))


def _success(value: FloorUnitValue) -> FloorUnitResult:
    return FloorUnitResult(value=value, failure=None)
