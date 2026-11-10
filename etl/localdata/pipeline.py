from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from etl.address.building_key import parse_jibun_address
from etl.address.floor_unit import LocationLevel, parse_floor_unit, reconcile_floor_units
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, Source
from etl.localdata.dto import LocalDataRow
from etl.localdata.normalize import (
    CoordinateNormalizer,
    combine_flags,
    normalize_area,
    normalize_category,
    normalize_dates,
    normalize_status,
)


@dataclass(frozen=True, slots=True)
class StoreRecord:
    source: str
    license_no: str
    gu_code: str
    name: str | None
    address_road: str | None
    address_jibun: str | None
    building_key: str | None
    floor_unit: str | None
    location_level: str
    open_date: date | None
    close_date: date | None
    status: str
    status_code: str | None
    bzstat_nm: str | None
    category: str | None
    sub_category: str | None
    seoul_induty_cd: str | None
    area_m2: Decimal | None
    lat: Decimal | None
    lng: Decimal | None
    raw_x: str | None
    raw_y: str | None
    raw_crs: str | None
    coord_source: str | None
    coord_flag: str | None
    date_flag: str | None
    is_temporary: bool | None
    category_review_flag: bool
    batch_id: UUID


@dataclass(frozen=True, slots=True)
class TransformReport:
    fetched: int
    accepted: int
    rejected_missing_key: int
    rejected_non_seoul: int
    duplicates: int
    transformed: int
    update_types: dict[str, int]
    flags: dict[str, int]


@dataclass(frozen=True, slots=True)
class TransformResult:
    records: tuple[StoreRecord, ...]
    report: TransformReport


def _update_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return parsed if parsed.strftime("%Y%m%d%H%M%S") == value else None


def _dedupe_key(row: LocalDataRow) -> tuple[datetime, datetime, tuple[str, ...]]:
    oldest = datetime.min
    return (
        _update_datetime(row.update_point) or oldest,
        _update_datetime(row.last_modified_point) or oldest,
        row.canonical_values(),
    )


def transform_rows(
    source: Source,
    rows: Iterable[LocalDataRow],
    *,
    batch_id: UUID,
    today: date,
    coordinates: CoordinateNormalizer | None = None,
) -> TransformResult:
    raw_rows = list(rows)
    rejected_missing_key = 0
    rejected_non_seoul = 0
    accepted_rows: list[LocalDataRow] = []
    update_types: Counter[str] = Counter()
    for row in raw_rows:
        if row.management_no is None:
            rejected_missing_key += 1
            continue
        if row.authority_code not in SEOUL_AUTHORITY_CODES:
            rejected_non_seoul += 1
            continue
        accepted_rows.append(row)
        update_types[row.update_type or "<missing>"] += 1

    selected: dict[str, LocalDataRow] = {}
    for row in accepted_rows:
        key = row.management_no
        assert key is not None
        current = selected.get(key)
        if current is None or _dedupe_key(row) > _dedupe_key(current):
            selected[key] = row

    coordinate_normalizer = coordinates or CoordinateNormalizer()
    records: list[StoreRecord] = []
    flag_counts: Counter[str] = Counter()
    for management_no in sorted(selected):
        row = selected[management_no]
        dates = normalize_dates(row, today=today)
        status = normalize_status(row, dates)
        category = normalize_category(source, row.business_type_name)
        area, area_flags = normalize_area(row)
        coord = coordinate_normalizer.normalize(row.raw_x, row.raw_y)
        building_key_result = parse_jibun_address(
            row.jibun_address,
            authority_code=row.authority_code,
        )
        floor_unit_result = reconcile_floor_units(
            parse_floor_unit(row.road_address),
            parse_floor_unit(row.jibun_address),
        )
        quality_flags = combine_flags(dates.flags, status.flags, area_flags)
        flag_counts.update(quality_flags)
        if coord.flag is not None:
            flag_counts[coord.flag] += 1
        if category.review:
            flag_counts["category_review"] += 1
        if building_key_result.lot is None:
            assert building_key_result.failure is not None
            flag_counts[f"building_key_{building_key_result.failure.value}"] += 1
        else:
            flag_counts["building_key_ok"] += 1
        if floor_unit_result.value is None:
            assert floor_unit_result.failure is not None
            flag_counts[f"floor_unit_{floor_unit_result.failure.value}"] += 1
            floor_unit = None
            location_level = LocationLevel.UNVERIFIED.value
        elif building_key_result.lot is None:
            flag_counts["floor_unit_ok"] += 1
            flag_counts["location_level_unverified_no_building_key"] += 1
            floor_unit = floor_unit_result.value.value
            location_level = LocationLevel.UNVERIFIED.value
        else:
            flag_counts["floor_unit_ok"] += 1
            floor_unit = floor_unit_result.value.value
            location_level = floor_unit_result.value.location_level.value
        records.append(
            StoreRecord(
                source=source.value,
                license_no=management_no,
                gu_code=row.authority_code or "",
                name=row.business_name,
                address_road=row.road_address,
                address_jibun=row.jibun_address,
                building_key=(
                    building_key_result.lot.key if building_key_result.lot is not None else None
                ),
                floor_unit=floor_unit,
                location_level=location_level,
                open_date=dates.open_date,
                close_date=dates.close_date,
                status=status.value,
                status_code=row.status_code,
                bzstat_nm=row.business_type_name,
                category=category.category,
                sub_category=category.sub_category,
                seoul_induty_cd=None,
                area_m2=area,
                lat=coord.lat,
                lng=coord.lng,
                raw_x=row.raw_x,
                raw_y=row.raw_y,
                raw_crs="EPSG:5174" if row.raw_x is not None or row.raw_y is not None else None,
                coord_source=coord.coord_source,
                coord_flag=coord.flag,
                date_flag=";".join(dates.flags) or None,
                is_temporary=None,
                category_review_flag=category.review,
                batch_id=batch_id,
            )
        )

    accepted = len(accepted_rows)
    transformed = len(records)
    report = TransformReport(
        fetched=len(raw_rows),
        accepted=accepted,
        rejected_missing_key=rejected_missing_key,
        rejected_non_seoul=rejected_non_seoul,
        duplicates=accepted - transformed,
        transformed=transformed,
        update_types=dict(sorted(update_types.items())),
        flags=dict(sorted(flag_counts.items())),
    )
    return TransformResult(tuple(records), report)
