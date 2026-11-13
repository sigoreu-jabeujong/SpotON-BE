from datetime import date

import pytest

from app.schemas.stores import HistoryQuery
from app.services.store_history import location_match
from etl.address.floor_unit import (
    FloorUnitFailure,
    LocationLevel,
    parse_floor_unit,
    reconcile_floor_units,
)
from etl.localdata.constants import Source
from etl.localdata.pipeline import transform_rows
from tests.etl.test_localdata_pipeline import BATCH_ID, raw

PLACES = (
    "서울 중구 명동길 14",
    "서울 중랑구 중랑천로14길 5",
    "서울 노원구 중계동 1",
    "서울 광진구 중곡동 1",
    "서울 중구 중림동 1",
    "서울 중랑구 중화동 1",
    "서울 양천구 중앙로 1",
    "서울 중구 중앙로2길 3",
    "서울 노원구 중계1동 1",
)


@pytest.mark.parametrize("address", PLACES)
@pytest.mark.parametrize("detail", ["2층", "2층 201호", "B1", "201호"])
def test_place_name_does_not_discard_explicit_detail(address: str, detail: str) -> None:
    result = parse_floor_unit(f"{address} {detail}")
    assert result.failure is None
    assert result.value is not None
    assert result.value.value == detail
    assert result.value.location_level == (
        LocationLevel.SAME_SPOT if detail == "2층 201호" else LocationLevel.SAME_BUILDING
    )


@pytest.mark.parametrize("address", PLACES)
def test_place_without_detail_is_no_detail_instead_of_false_ambiguity(address: str) -> None:
    result = parse_floor_unit(address)
    assert result.value is None
    assert result.failure is FloorUnitFailure.NO_DETAIL


@pytest.mark.parametrize(
    "detail",
    [
        "중",
        "중간",
        "중층",
        "중간층",
        "중 2층",
        "중간 2층",
        "중2층",
        "중2F",
        "중201호",
        "중간2층",
        "중B1",
        "중b1",
        "중지하1층",
        "중지상2층",
        "중제2층",
        "중2-3층",
        "중2 층",
        "중,2층",
        "중/2층",
        "중~2층",
        "중·2층",
        "중-2층",
        "중층201호",
        "중간층201호",
        "중Ｂ１",
        "중２",
        "반지하",
        "옥탑",
        "M층",
        "메자닌",
        "중2로",
        "중.2층",
        "중ㆍ2층",
        "중:2층",
        "중_2층",
        "중M층",
        "중지층",
        "중반지하",
        "중옥탑",
        "중옥상",
        "중메자닌",
        "중간.2층",
        "중간M층",
        "중간지층",
        "중간반지하",
        "중간옥탑",
        "중간옥상",
        "중간메자닌",
    ],
)
def test_ambiguous_detail_cannot_fall_through_to_another_unit(detail: str) -> None:
    result = parse_floor_unit(f"서울 중구 명동길 14 {detail} 201호")
    assert result.value is None
    assert result.failure is FloorUnitFailure.AMBIGUOUS


@pytest.mark.parametrize(
    "detail",
    ["", "2층", "2층 201호", "201호", "B1", "0층", "101-1호", "1~2층", "101동 201호"],
)
def test_changing_district_does_not_change_detail_result(detail: str) -> None:
    assert parse_floor_unit(f"서울 중구 테스트로 1 {detail}") == parse_floor_unit(
        f"서울 마포구 테스트로 1 {detail}"
    )


@pytest.mark.parametrize(
    ("stored", "level", "expected"),
    [
        (None, "unverified", "unverified"),
        ("2층 201호", "same_building", "unverified"),
        ("2층 201호", "same_spot", "same_spot"),
    ],
)
def test_new_query_does_not_promote_unverified_stored_location(
    stored: str | None, level: str, expected: str
) -> None:
    parsed = parse_floor_unit("서울 중구 명동길 14 2층 201호")
    assert parsed.value is not None
    assert location_match(parsed.value.value, stored, level) == expected


@pytest.mark.parametrize("jibun_detail,expected", [("", "2층"), ("2층 201호", None)])
def test_reconcile_keeps_real_conflict_after_accepting_district(
    jibun_detail: str, expected: str | None
) -> None:
    result = reconcile_floor_units(
        parse_floor_unit("서울 중구 명동길 14 2층"),
        parse_floor_unit(f"서울 중구 명동2가 1-1 {jibun_detail}"),
    )
    assert (result.value.value if result.value else None) == expected
    assert result.failure == (FloorUnitFailure.AMBIGUOUS if expected is None else None)


@pytest.mark.parametrize(
    "gu,code,dong", [("중구", "3010000", "중림동"), ("중랑구", "3060000", "중화동")]
)
@pytest.mark.parametrize("detail", ["", "2층", "2층 201호", "201호"])
def test_etl_retains_place_detail_without_changing_other_source_fields(
    gu: str, code: str, dong: str, detail: str
) -> None:
    road = f"서울특별시 {gu} 테스트로 1 {detail}".strip()
    jibun = f"서울특별시 {gu} {dong} 1-1 {detail}".strip()
    row = raw("PLACE-1", OPN_ATMY_GRP_CD=code, ROAD_NM_ADDR=road, LOTNO_ADDR=jibun)
    result = transform_rows(
        Source.GENERAL_RESTAURANT, [row], batch_id=BATCH_ID, today=date(2026, 11, 10)
    )
    record = result.records[0]
    assert record.building_key == f"{gu}-{dong}-1-1"
    assert record.floor_unit == (detail or None)
    assert record.location_level == (
        "same_spot" if detail == "2층 201호" else "same_building" if detail else "unverified"
    )
    assert record.address_road == road and record.address_jibun == jibun
    assert record.category == "restaurant" and record.sub_category == "korean"
    assert record.bzstat_nm == "한식" and record.category_review_flag is False
    assert record.open_date == date(2020, 1, 1) and record.close_date is None
    assert record.date_flag is None and record.status == "open"
    assert record.batch_id == BATCH_ID
    assert result.report.flags["floor_unit_ok" if detail else "floor_unit_no_detail"] == 1
    assert result.report.flags.get("floor_unit_ambiguous", 0) == 0


def test_place_keeps_f_suffix_canonicalization_and_history_query() -> None:
    result = parse_floor_unit("서울 중구 중앙로2길 3 3F")
    assert result.value is not None and result.value.value == "3층"
    query = HistoryQuery(building_key="중구-명동2가-1-1", floor_unit="중구 2층")
    assert query.floor_unit == "2층"


@pytest.mark.parametrize("detail", ["중2층", "중B1", "중.2층", "중M층"])
def test_etl_keeps_real_ambiguity_when_other_address_has_valid_unit(detail: str) -> None:
    row = raw(
        "PLACE-AMBIGUOUS-1",
        OPN_ATMY_GRP_CD="3010000",
        ROAD_NM_ADDR=f"서울특별시 중구 테스트로 1 {detail} 201호",
        LOTNO_ADDR="서울특별시 중구 중림동 1-1 2층 201호",
    )
    result = transform_rows(
        Source.GENERAL_RESTAURANT, [row], batch_id=BATCH_ID, today=date(2026, 11, 10)
    )
    assert result.records[0].floor_unit is None
    assert result.records[0].location_level == "unverified"
    assert result.report.flags["floor_unit_ambiguous"] == 1
