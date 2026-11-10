from dataclasses import replace
from datetime import date
from uuid import UUID

from etl.localdata.constants import Source
from etl.localdata.dto import LocalDataRow
from etl.localdata.pipeline import transform_rows

BATCH_ID = UUID("00000000-0000-0000-0000-000000000001")


def raw(number: str | None, **values: object) -> LocalDataRow:
    payload: dict[str, object] = {
        "OPN_ATMY_GRP_CD": "3130000",
        "MNG_NO": number,
        "BPLC_NM": "테스트 점포",
        "ROAD_NM_ADDR": "서울특별시 마포구 테스트로 1 2층 201호",
        "LOTNO_ADDR": "마포구 서교동 123-4",
        "SALS_STTS_CD": "01",
        "SALS_STTS_NM": "영업/정상",
        "SNTTN_BZSTAT_NM": "한식",
        "LCPMT_YMD": "20200101",
        "CRD_INFO_X": "200000",
        "CRD_INFO_Y": "450000",
        "DAT_UPDT_SE": "U",
        "DAT_UPDT_PNT": "20260101000000",
    }
    payload.update(values)
    return LocalDataRow.from_api(payload)


def test_filters_deduplicates_and_reports_without_personal_data() -> None:
    older = raw("M-1", BPLC_NM="old", DAT_UPDT_PNT="20250101000000")
    newer = raw("M-1", BPLC_NM="new", DAT_UPDT_PNT="20260101000000")
    missing = raw(None)
    outside = replace(raw("M-2"), authority_code="6110000")

    result = transform_rows(
        Source.GENERAL_RESTAURANT,
        [older, newer, missing, outside],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    )

    assert len(result.records) == 1
    assert result.records[0].name == "new"
    assert result.records[0].raw_crs == "EPSG:5174"
    assert result.records[0].building_key == "마포구-서교동-123-4"
    assert result.records[0].floor_unit == "2층 201호"
    assert result.records[0].location_level == "same_spot"
    assert result.report.fetched == 4
    assert result.report.accepted == 2
    assert result.report.duplicates == 1
    assert result.report.transformed == 1
    assert result.report.rejected_missing_key == 1
    assert result.report.rejected_non_seoul == 1
    assert "new" not in repr(result.report)
    assert "M-1" not in repr(result.report)
    assert result.report.flags["building_key_ok"] == result.report.transformed
    assert result.report.flags["floor_unit_ok"] == result.report.transformed


def test_duplicate_tie_breaker_is_order_independent() -> None:
    left = raw("M-1", BPLC_NM="A")
    right = raw("M-1", BPLC_NM="B")
    forward = transform_rows(
        Source.GENERAL_RESTAURANT,
        [left, right],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    )
    reverse = transform_rows(
        Source.GENERAL_RESTAURANT,
        [right, left],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    )
    assert forward.records == reverse.records
    assert forward.records[0].name == "B"


def test_store_record_has_building_key_but_keeps_later_task_fields_out() -> None:
    record = transform_rows(
        Source.REST_CAFE,
        [raw("M-1", SNTTN_BZSTAT_NM="커피숍")],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    ).records[0]
    assert record.category == "cafe"
    assert record.sub_category == "cafe"
    assert record.building_key == "마포구-서교동-123-4"
    assert record.floor_unit == "2층 201호"
    assert record.location_level == "same_spot"
    assert not hasattr(record, "deleted_at")


def test_building_key_failure_is_retained_as_a_report_count_without_rejecting_row() -> None:
    result = transform_rows(
        Source.GENERAL_RESTAURANT,
        [
            raw(
                "M-1",
                ROAD_NM_ADDR="마포구 테스트로 1 2층",
                LOTNO_ADDR="마포구 양화로 123 2층",
            )
        ],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    )

    assert result.report.transformed == 1
    assert result.records[0].building_key is None
    assert result.records[0].floor_unit == "2층"
    assert result.records[0].location_level == "unverified"
    building_key_counts = {
        name: count
        for name, count in result.report.flags.items()
        if name.startswith("building_key_")
    }
    assert building_key_counts == {"building_key_legal_dong_unsupported": 1}
    assert result.report.transformed == sum(building_key_counts.values())
    assert result.report.flags["floor_unit_ok"] == result.report.transformed
    assert result.report.flags["location_level_unverified_no_building_key"] == 1


def test_floor_unit_conflict_is_unverified_but_does_not_reject_the_row() -> None:
    result = transform_rows(
        Source.GENERAL_RESTAURANT,
        [raw("M-1", ROAD_NM_ADDR="마포구 테스트로 1 2층", LOTNO_ADDR="마포구 서교동 123 3층")],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    )

    assert result.report.transformed == 1
    assert result.records[0].floor_unit is None
    assert result.records[0].location_level == "unverified"
    floor_unit_counts = {
        name: count for name, count in result.report.flags.items() if name.startswith("floor_unit_")
    }
    assert floor_unit_counts == {"floor_unit_ambiguous": 1}
    assert result.report.transformed == sum(floor_unit_counts.values())
