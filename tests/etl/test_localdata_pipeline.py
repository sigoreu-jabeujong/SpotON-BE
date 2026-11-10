from dataclasses import replace
from datetime import date
from uuid import UUID

from etl.localdata.constants import Source
from etl.localdata.dto import LocalDataRow
from etl.localdata.pipeline import transform_rows

BATCH_ID = UUID("00000000-0000-0000-0000-000000000001")


def raw(number: str | None, **values: object) -> LocalDataRow:
    payload: dict[str, object] = {
        "OPN_ATMY_GRP_CD": "3000000",
        "MNG_NO": number,
        "BPLC_NM": "테스트 점포",
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
    assert result.report.fetched == 4
    assert result.report.accepted == 2
    assert result.report.duplicates == 1
    assert result.report.transformed == 1
    assert result.report.rejected_missing_key == 1
    assert result.report.rejected_non_seoul == 1
    assert "new" not in repr(result.report)
    assert "M-1" not in repr(result.report)


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


def test_store_record_keeps_later_task_fields_out() -> None:
    record = transform_rows(
        Source.REST_CAFE,
        [raw("M-1", SNTTN_BZSTAT_NM="커피숍")],
        batch_id=BATCH_ID,
        today=date(2026, 11, 10),
    ).records[0]
    assert record.category == "cafe"
    assert record.sub_category == "cafe"
    assert not hasattr(record, "building_key")
    assert not hasattr(record, "deleted_at")
