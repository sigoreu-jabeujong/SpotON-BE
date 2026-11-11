from datetime import date, datetime
from typing import Any

import httpx
import pytest

from etl.localdata.client import LocalDataClient, LocalDataContractError
from etl.localdata.constants import Source
from etl.localdata.dates import parse_source_date, parse_source_timestamp
from etl.localdata.dto import LocalDataRow
from etl.localdata.normalize import normalize_dates
from etl.localdata.pipeline import transform_rows
from tests.etl.test_localdata_client import envelope, row
from tests.etl.test_localdata_pipeline import BATCH_ID, raw


@pytest.mark.parametrize("code", ["0", 0, "00"])
def test_accepts_live_and_legacy_success_codes(code: object) -> None:
    payload = envelope(page=1, total=1, rows=[row("3000000", 1)])
    payload["response"]["header"]["resultCode"] = code
    assert len(LocalDataClient._parse_page(httpx.Response(200, json=payload), 1).rows) == 1


@pytest.mark.parametrize("code", [False, True, "000", " 0", "0 ", "0.0", 0.0, None, "", "22"])
def test_does_not_coerce_other_values_to_success(code: object) -> None:
    payload = envelope(page=1, total=0, rows=[])
    payload["response"]["header"]["resultCode"] = code
    with pytest.raises(LocalDataContractError, match="result_code"):
        LocalDataClient._parse_page(httpx.Response(200, json=payload), 1)


@pytest.mark.parametrize("value", ["20240229", "2024-02-29"])
def test_live_and_compact_dates(value: str) -> None:
    assert parse_source_date(value) == date(2024, 2, 29)
    result = normalize_dates(LocalDataRow.from_api({"LCPMT_YMD": value}), today=date(2026, 11, 11))
    assert result.open_date == date(2024, 2, 29)
    assert result.flags == ()


@pytest.mark.parametrize(
    "value",
    [
        "2023-02-29",
        "20240230",
        "2024-1-05",
        "2024/01/05",
        "2024 01 05",
        "２０２４０１０５",
        "2024-01-05 00:00:00",
        "2024-01-05T00:00:00+09:00",
        " 20240105",
        "20240105 ",
    ],
)
def test_bad_date_shapes_and_calendars_remain_flagged(value: str) -> None:
    assert parse_source_date(value) is None
    result = normalize_dates(LocalDataRow.from_api({"LCPMT_YMD": value}), today=date(2026, 11, 11))
    # DTO strips boundary whitespace before strict date parsing.
    if value.strip() != value:
        assert result.open_date == date(2024, 1, 5)
    else:
        assert result.flags == ("open_date_invalid",)


@pytest.mark.parametrize("value", ["20260102123456", "2026-01-02 12:34:56"])
def test_live_and_compact_timestamps(value: str) -> None:
    assert parse_source_timestamp(value) == datetime(2026, 1, 2, 12, 34, 56)


@pytest.mark.parametrize(
    "value",
    [
        "2026-1-02 12:34:56",
        "2026-01-02T12:34:56",
        "2026-01-02 24:00:00",
        "2026-01-02 12:34:56.000",
        "2026-01-02 12:34:56Z",
        "２０２６０１０２１２３４５６",
    ],
)
def test_unsupported_timestamps_are_not_guessed(value: str) -> None:
    assert parse_source_timestamp(value) is None


def test_mixed_timestamp_formats_select_latest_in_both_orders() -> None:
    older = raw("same", BPLC_NM="older", DAT_UPDT_PNT="20250101000000")
    newer = raw("same", BPLC_NM="newer", DAT_UPDT_PNT="2026-01-01 00:00:00")
    outputs = [
        transform_rows(Source.GENERAL_RESTAURANT, rows, batch_id=BATCH_ID, today=date(2026, 11, 11))
        for rows in ([older, newer], [newer, older])
    ]
    assert outputs[0].records == outputs[1].records
    assert outputs[0].records[0].name == "newer"


@pytest.mark.parametrize("missing", ["MNG_NO", "OPN_ATMY_GRP_CD"])
def test_disappearing_required_field_rejects_page(missing: str) -> None:
    rows: list[dict[str, Any]] = [row("3000000", 1), row("3000000", 2)]
    for item in rows:
        item.pop(missing)
    with pytest.raises(LocalDataContractError, match="required_fields"):
        LocalDataClient._parse_page(
            httpx.Response(200, json=envelope(page=1, total=2, rows=rows)), 1
        )


def test_individual_missing_management_key_remains_a_rejected_row() -> None:
    rows = [row("3000000", 1), {"OPN_ATMY_GRP_CD": "3000000"}]
    page = LocalDataClient._parse_page(
        httpx.Response(200, json=envelope(page=1, total=2, rows=rows)), 1
    )
    result = transform_rows(
        Source.GENERAL_RESTAURANT, page.rows, batch_id=BATCH_ID, today=date(2026, 11, 11)
    )
    assert result.report.rejected_missing_key == 1
