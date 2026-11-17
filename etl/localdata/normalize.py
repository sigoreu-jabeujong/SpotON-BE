from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import isfinite

from pyproj import Transformer, network

from etl.localdata.constants import Source
from etl.localdata.dates import parse_source_date
from etl.localdata.dto import LocalDataRow

SOURCE_CRS = "EPSG:5174"
TARGET_CRS = "EPSG:4326"
SEOUL_LNG_RANGE = (126.70, 127.25)
SEOUL_LAT_RANGE = (37.35, 37.80)
COORD_SCALE = Decimal("0.0000001")
MAX_AREA = Decimal("9999999999.99")

STATUS_NAMES = {
    "01": "영업/정상",
    "02": "휴업",
    "03": "폐업",
    "04": "취소/말소/만료/정지/중지",
    "05": "제외/삭제/전출",
    "06": "기타",
}
STATUS_VALUES = {"01": "open", "03": "closed"}

GENERAL_CATEGORIES = {
    "한식": ("restaurant", "korean"),
    "중국식": ("restaurant", "chinese"),
    "일식": ("restaurant", "japanese"),
    "경양식": ("restaurant", "western"),
}
CAFE_CATEGORIES = {"커피숍": ("cafe", "cafe")}
REVIEW_TYPES = frozenset({"기타", "기타 휴게음식점", "까페"})
EXCLUDED_TYPES = frozenset(
    {
        "분식",
        "뷔페식",
        "정종/대포집/소주방",
        "전통찻집",
        "이동조리",
        "출장조리",
        "패스트푸드",
        "호프/통닭",
        "통닭(치킨)",
        "복어취급",
        "김밥(도시락)",
        "횟집",
        "식육(숯불구이)",
        "탕류(보신용)",
        "냉면집",
        "외국음식전문점(인도,태국등)",
        "패밀리레스트랑",
        "키즈카페",
        "감성주점",
        "라이브카페",
        "푸드트럭",
        "룸살롱",
        "간이주점",
        "단란주점",
        "다방",
        "일반조리판매",
        "과자점",
        "관광호텔",
        "공항",
        "고속도로",
        "유원지",
        "철도역구내",
        "백화점",
        "편의점",
        "아이스크림",
        "제과점영업",
    }
)


@dataclass(frozen=True, slots=True)
class DateResult:
    open_date: date | None
    close_date: date | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StatusResult:
    value: str
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategoryResult:
    category: str | None
    sub_category: str | None
    review: bool


@dataclass(frozen=True, slots=True)
class CoordinateResult:
    lat: Decimal | None
    lng: Decimal | None
    coord_source: str | None
    flag: str | None


def _parse_date(value: str | None, flag: str, flags: list[str]) -> date | None:
    if value is None or not value.strip():
        return None
    parsed = parse_source_date(value)
    if parsed is None:
        flags.append(flag)
    return parsed


def normalize_dates(row: LocalDataRow, *, today: date) -> DateResult:
    flags: list[str] = []
    opened = _parse_date(row.license_date, "open_date_invalid", flags)
    closed = _parse_date(row.closure_date, "close_date_invalid", flags)
    if opened is not None:
        if opened < date(1960, 1, 1):
            flags.append("open_before_1960")
        if opened > today:
            flags.append("open_date_future")
    if closed is not None and closed > today:
        flags.append("close_date_future")
    if opened is not None and closed is not None and closed < opened:
        flags.append("close_before_open")
    return DateResult(opened, closed, tuple(sorted(set(flags))))


def normalize_status(row: LocalDataRow, dates: DateResult) -> StatusResult:
    flags: list[str] = []
    code = row.status_code
    if code is None:
        value = "other"
        flags.append("status_missing")
    elif code not in STATUS_NAMES:
        value = "other"
        flags.append("status_unknown")
    elif row.status_name is not None and row.status_name != STATUS_NAMES[code]:
        value = "other"
        flags.append("status_mismatch")
    else:
        value = STATUS_VALUES.get(code, "other")
    if (value == "closed" and dates.close_date is None) or (
        value == "open" and dates.close_date is not None
    ):
        flags.append("status_date_inconsistent")
    return StatusResult(value, tuple(sorted(set(flags))))


def normalize_category(source: Source, business_type: str | None) -> CategoryResult:
    if business_type is None:
        return CategoryResult(None, None, True)
    mapping = GENERAL_CATEGORIES if source is Source.GENERAL_RESTAURANT else CAFE_CATEGORIES
    if business_type in mapping:
        category, sub_category = mapping[business_type]
        return CategoryResult(category, sub_category, False)
    if business_type in EXCLUDED_TYPES:
        return CategoryResult(None, None, False)
    return CategoryResult(None, None, True)


def normalize_area(row: LocalDataRow) -> tuple[Decimal | None, tuple[str, ...]]:
    value = row.location_area if row.location_area is not None else row.facility_total_scale
    if value is None:
        return None, ()
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None, ("area_invalid",)
    if not result.is_finite() or result < 0 or result > MAX_AREA:
        return None, ("area_invalid",)
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ()


class CoordinateNormalizer:
    def __init__(self) -> None:
        network.set_network_enabled(False)  # type: ignore[attr-defined]
        self._transformer = Transformer.from_crs(SOURCE_CRS, TARGET_CRS, always_xy=True)

    def normalize(self, raw_x: str | None, raw_y: str | None) -> CoordinateResult:
        if raw_x is None and raw_y is None:
            return CoordinateResult(None, None, None, "coord_missing")
        if raw_x is None or raw_y is None:
            return CoordinateResult(None, None, None, "coord_partial")
        try:
            x = float(raw_x)
            y = float(raw_y)
        except ValueError:
            return CoordinateResult(None, None, None, "coord_non_numeric")
        if not isfinite(x) or not isfinite(y):
            return CoordinateResult(None, None, None, "coord_non_finite")
        if x <= 0 or y <= 0:
            return CoordinateResult(None, None, None, "coord_zero")
        try:
            lng_value, lat_value = self._transformer.transform(x, y)
        except Exception:
            return CoordinateResult(None, None, None, "coord_transform_failed")
        if not isfinite(lng_value) or not isfinite(lat_value):
            return CoordinateResult(None, None, None, "coord_transform_failed")
        if not (
            SEOUL_LNG_RANGE[0] <= lng_value <= SEOUL_LNG_RANGE[1]
            and SEOUL_LAT_RANGE[0] <= lat_value <= SEOUL_LAT_RANGE[1]
        ):
            return CoordinateResult(None, None, None, "coord_out_of_seoul")
        return CoordinateResult(
            lat=Decimal(str(lat_value)).quantize(COORD_SCALE, rounding=ROUND_HALF_UP),
            lng=Decimal(str(lng_value)).quantize(COORD_SCALE, rounding=ROUND_HALF_UP),
            coord_source="localdata",
            flag=None,
        )


def combine_flags(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({flag for group in groups for flag in group}))
