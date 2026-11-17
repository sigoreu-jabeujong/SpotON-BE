from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from etl.localdata.constants import Source
from etl.localdata.dto import LocalDataRow
from etl.localdata.normalize import (
    EXCLUDED_TYPES,
    GENERAL_CATEGORIES,
    REVIEW_TYPES,
    CoordinateNormalizer,
    normalize_area,
    normalize_category,
    normalize_dates,
    normalize_status,
)


def raw(**changes: str | None) -> LocalDataRow:
    base = LocalDataRow.from_api(
        {
            "OPN_ATMY_GRP_CD": "3000000",
            "MNG_NO": "M-1",
            "SALS_STTS_CD": "01",
            "SALS_STTS_NM": "영업/정상",
            "SNTTN_BZSTAT_NM": "한식",
        }
    )
    return replace(base, **changes)


def test_date_boundaries_and_flags_are_deterministic() -> None:
    result = normalize_dates(
        raw(license_date="19591231", closure_date="20270101"),
        today=date(2026, 11, 10),
    )
    assert result.open_date == date(1959, 12, 31)
    assert result.flags == ("close_date_future", "open_before_1960")
    assert normalize_dates(raw(license_date="19600101"), today=date(2026, 11, 10)).flags == ()
    assert normalize_dates(raw(license_date="20230230"), today=date(2026, 11, 10)).flags == (
        "open_date_invalid",
    )


def test_status_uses_official_codes_and_does_not_guess() -> None:
    dates = normalize_dates(raw(), today=date(2026, 11, 10))
    assert normalize_status(raw(), dates).value == "open"
    assert normalize_status(raw(status_code="03", status_name="폐업"), dates).value == "closed"
    mismatch = normalize_status(raw(status_code="01", status_name="폐업"), dates)
    assert mismatch.value == "other"
    assert mismatch.flags == ("status_mismatch",)


def test_category_lists_are_disjoint_and_exact() -> None:
    assert not (set(GENERAL_CATEGORIES) & EXCLUDED_TYPES)
    assert not (set(GENERAL_CATEGORIES) & REVIEW_TYPES)
    assert not (EXCLUDED_TYPES & REVIEW_TYPES)
    assert normalize_category(Source.GENERAL_RESTAURANT, "한식").sub_category == "korean"
    assert normalize_category(Source.GENERAL_RESTAURANT, "분식").review is False
    assert normalize_category(Source.REST_CAFE, "커피숍").category == "cafe"
    assert normalize_category(Source.REST_CAFE, "기타").review is True
    assert normalize_category(Source.REST_CAFE, "스타벅스 커피숍").category is None


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "abc", "10000000000"])
def test_invalid_area_becomes_none(value: str) -> None:
    area, flags = normalize_area(raw(location_area=value))
    assert area is None
    assert flags == ("area_invalid",)


def test_area_uses_location_then_facility_and_quantizes() -> None:
    assert normalize_area(raw(location_area="12.345", facility_total_scale="99"))[0] == Decimal(
        "12.35"
    )
    assert normalize_area(raw(location_area=None, facility_total_scale="7"))[0] == Decimal("7.00")


def test_epsg_5174_coordinate_conversion_and_failures() -> None:
    normalizer = CoordinateNormalizer()
    # EPSG:5174 정의의 (200000, 450000) 기준 변환값을 고정해 축 순서와 CRS 회귀를 잡는다.
    converted = normalizer.normalize("200000", "450000")
    assert converted.flag is None
    assert converted.coord_source == "localdata"
    assert converted.lng == Decimal("127.0007880")
    assert converted.lat == Decimal("37.5522680")
    assert normalizer.normalize(None, None).flag == "coord_missing"
    assert normalizer.normalize("200000", None).flag == "coord_partial"
    assert normalizer.normalize("x", "450000").flag == "coord_non_numeric"
    assert normalizer.normalize("NaN", "450000").flag == "coord_non_finite"
    assert normalizer.normalize("0", "450000").flag == "coord_zero"
    assert normalizer.normalize("200000", "100000").flag == "coord_out_of_seoul"
