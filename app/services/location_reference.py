"""Read actual intersecting source areas; never impute a point's sales or population."""

import hashlib
import json
import re
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypeVar, cast
from zoneinfo import ZoneInfo

from geoalchemy2 import Geography
from sqlalchemy import cast as sql_cast
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import MarketArea as A
from app.models import MarketAreaVersion as B
from app.models import MarketSale as S
from app.models import MarketSaleVersion as V
from app.models import MarketStore as M
from app.models import MarketStoreVersion as MV
from app.models import Store
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.location_reference import (
    Fingerprint,
    LocationCatalog,
    LocationReference,
    LocationReferenceQuery,
    Reason,
    SalesBlock,
    SalesCatalog,
    SalesItem,
    SourceNumber,
    Status,
    TimeRelation,
)
from app.services.location_catalog import catalog_digest, load_catalog
from app.services.spatial_stores import effective_date
from app.services.store_cohort import current_provenance, temporal_cohort

MAX_MARKETS = 100
MAX_DETAILS = 500
MAX_SOURCE_ROWS = 50_000
FORMAT_VERSION = "location-reference-v1"
RULE_VERSION = "spatial-source-reported-sales-v1"
INDUSTRIES = {
    "korean": ("CS100001", "한식음식점"),
    "chinese": ("CS100002", "중식음식점"),
    "japanese": ("CS100003", "일식음식점"),
    "western": ("CS100004", "양식음식점"),
    "cafe": ("CS100010", "커피-음료"),
}
TYPES = {"A": "alley", "D": "developed", "R": "traditional_market", "U": "tourism_zone"}
Version = TypeVar("Version", B, V, MV)


@dataclass(frozen=True)
class Candidate:
    code: str
    name: str
    kind: str
    kind_code: str
    relation: Literal["contains_point", "intersects_radius"]


def _resolve(
    session: Session,
    model: type[Version],
    identity: Fingerprint,
    *references: ColumnElement[bool],
) -> list[Version]:
    rows = list(
        session.scalars(
            select(model)
            .where(
                model.source_dataset == identity.source_dataset,
                model.rule_version == identity.rule_version,
                model.input_sha256 == identity.input_sha256,
                *references,
            )
            .limit(2)
        )
    )
    if any(
        row.content_sha256 != identity.content_sha256 or row.row_count != identity.row_count
        for row in rows
    ):
        raise ValueError("inconsistent reference metadata")
    return rows


def _bounds(quarter: str) -> tuple[date, date]:
    if not isinstance(quarter, str) or re.fullmatch(r"20[0-9]{2}[1-4]", quarter) is None:
        raise ValueError("invalid source period")
    year, q = int(quarter[:4]), int(quarter[4])
    month = 3 * q
    return date(year, month - 2, 1), date(year, month, monthrange(year, month)[1])


def _temporal(quarter: str, target: date) -> TimeRelation:
    start, end = _bounds(quarter)
    return (
        "earlier_reference"
        if end < target
        else "later_reference"
        if start > target
        else "same_period"
    )


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _empty(status: Status, reason: Reason) -> SalesBlock:
    return SalesBlock(status=status, reason=reason)


def _versions(
    session: Session,
    entry: SalesCatalog,
) -> tuple[V, B, MV] | SalesBlock:
    boundaries = _resolve(session, B, entry.boundary)
    if len(boundaries) != 1:
        return (
            _empty("pending", "ambiguous_source_version")
            if boundaries
            else _empty(
                "no_data",
                "source_not_loaded",
            )
        )
    stores = _resolve(
        session,
        MV,
        entry.stores,
        MV.code_check_boundary_version_id == boundaries[0].version_id,
    )
    if len(stores) != 1:
        return (
            _empty("pending", "ambiguous_source_version")
            if stores
            else _empty(
                "no_data",
                "source_not_loaded",
            )
        )
    sales = _resolve(
        session,
        V,
        entry.sales,
        V.code_check_boundary_version_id == boundaries[0].version_id,
        V.code_check_store_version_id == stores[0].version_id,
    )
    if any(not matches for matches in (boundaries, stores, sales)):
        return _empty("no_data", "source_not_loaded")
    if any(len(matches) > 1 for matches in (boundaries, stores, sales)):
        return _empty("pending", "ambiguous_source_version")
    boundary, store, sale = boundaries[0], stores[0], sales[0]
    if (
        sale.code_check_boundary_version_id != boundary.version_id
        or sale.code_check_store_version_id != store.version_id
        or store.code_check_boundary_version_id != boundary.version_id
        or sale.source_year != entry.source_year
        or store.source_year != entry.source_year
        or sale.amount_basis != "source_reported"
        or sale.amount_period_status != "unverified"
        or sale.currency != "KRW"
        or sale.boundary_compatibility != "unverified"
    ):
        raise ValueError("inconsistent reference sources")
    for model, version in ((A, boundary), (M, store), (S, sale)):
        if (
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.version_id == version.version_id,
                )
            )
            != version.row_count
        ):
            raise ValueError("incomplete reference source")
    return sale, boundary, store


def _candidates(session: Session, query: LocationReferenceQuery, boundary: B) -> list[Candidate]:
    point = func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326)
    polygon = sql_cast(A.geom, Geography("MULTIPOLYGON", srid=4326))
    location = sql_cast(point, Geography("POINT", srid=4326))
    rows = session.execute(
        select(
            A.market_code,
            A.market_name,
            A.market_type,
            A.market_type_code,
            func.ST_Covers(A.geom, point).label("covers"),
        )
        .where(
            A.version_id == boundary.version_id,
            func.ST_DWithin(polygon, location, query.radius + 0.01, True),
            func.ST_Distance(polygon, location, True) <= query.radius,
        )
        .order_by(A.market_code)
        .limit(MAX_MARKETS + 1)
    )
    return [
        Candidate(
            row.market_code,
            row.market_name,
            row.market_type,
            row.market_type_code,
            "contains_point" if row.covers else "intersects_radius",
        )
        for row in rows
    ]


def _source(sale: V, boundary: B) -> dict[str, object]:
    return {
        "id": "sales",
        "dataset": "OA-15572",
        "name": "서울시 상권분석서비스(추정매출-상권)",
        "url": "https://data.seoul.go.kr/dataList/OA-15572/F/1/datasetView.do",
        "source_year": sale.source_year,
        "source_field": "당월_매출_금액",
        "source_file_date": sale.source_file_date.isoformat(),
        "acquired_at": sale.loaded_at.isoformat(),
        "published_at": None,
        "boundary_dataset": boundary.source_dataset,
        "boundary_file_date": boundary.source_file_date.isoformat(),
        "boundary_as_of": boundary.boundary_as_of.isoformat() if boundary.boundary_as_of else None,
        "boundary_compatibility": "unverified",
        "amount_period_status": "unverified",
    }


def _sales(
    session: Session,
    query: LocationReferenceQuery,
    target: date,
    catalog: LocationCatalog,
) -> tuple[SalesBlock, list[dict[str, object]]]:
    entry = catalog.sales
    if entry is None:
        return _empty("no_data", "source_not_loaded"), []
    resolved = _versions(session, entry)
    if isinstance(resolved, SalesBlock):
        return resolved, []
    sale, boundary, _ = resolved
    sources = [_source(sale, boundary)]
    areas = _candidates(session, query, boundary)
    if len(areas) > MAX_MARKETS:
        return _empty("not_supported", "scope_too_large"), sources
    if not areas:
        return _empty("no_data", "no_spatial_overlap"), sources
    chosen = query.sub_category or (
        ("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western")
    )
    industries = [INDUSTRIES[sub] for sub in chosen]
    if len(areas) * len(industries) > MAX_DETAILS:
        return _empty("not_supported", "scope_too_large"), sources
    desired = f"{target.year}{(target.month - 1) // 3 + 1}"
    statement = select(S).where(
        S.version_id == sale.version_id,
        S.market_code.in_([a.code for a in areas]),
        S.induty_cd.in_([code for code, _ in industries]),
    )
    if query.time_mode == "analysis_period":
        statement = statement.where(S.quarter == desired)
    else:
        today = _today()
        statement = statement.where(S.quarter <= f"{today.year}{(today.month - 1) // 3 + 1}")
    rows = list(session.scalars(statement.order_by(S.quarter.desc()).limit(MAX_SOURCE_ROWS + 1)))
    if len(rows) > MAX_SOURCE_ROWS:
        return _empty("not_supported", "scope_too_large"), sources
    grouped: dict[tuple[str, str], list[S]] = {}
    for row in rows:
        _bounds(row.quarter)
        grouped.setdefault((row.market_code, row.induty_cd), []).append(row)
    items = []
    excluded = 0
    for area in sorted(areas, key=lambda a: (a.relation != "contains_point", a.code)):
        for code, label in industries:
            raw = grouped.get((area.code, code), [])
            eligible = [
                r
                for r in raw
                if r.market_name == area.name
                and r.market_type_code == area.kind_code
                and TYPES.get(r.market_type_code) == area.kind
                and r.induty_name == label
            ]
            conflict = len(eligible) != len(raw)
            if conflict:
                excluded += 1
            selected = next((r for r in eligible if r.est_sales is not None), None)
            reason: Reason | None = (
                "mapping_conflict"
                if conflict and not eligible
                else None
                if selected is not None
                else "source_value_null"
                if eligible
                else "no_data_in_analysis_period"
                if query.time_mode == "analysis_period"
                else "no_source_rows"
            )
            amount = selected.est_sales if selected is not None else None
            if amount is not None and (type(amount) is not int or not 0 <= amount <= 2**63 - 1):
                raise ValueError("invalid source amount")
            items.append(
                SalesItem(
                    market_code=area.code,
                    market_name=area.name,
                    market_type=cast(
                        Literal[
                            "alley",
                            "developed",
                            "traditional_market",
                            "tourism_zone",
                        ],
                        area.kind,
                    ),
                    spatial_relation=area.relation,
                    industry_code=code,
                    industry_name=label,
                    source_quarter=selected.quarter if selected else None,
                    period_end_after_analysis=_bounds(selected.quarter)[1] > target
                    if selected
                    else False,
                    temporal_relation=_temporal(selected.quarter, target) if selected else None,
                    metric=SourceNumber(
                        value=str(amount), display=f"{amount:,}원", exact_zero=amount == 0
                    )
                    if amount is not None
                    else None,
                    status="ready" if selected else "no_data",
                    reason=reason,
                    excluded_source_rows=len(raw) - len(eligible),
                    selection_reason="analysis_period"
                    if query.time_mode == "analysis_period"
                    else "latest_numeric_row",
                )
            )
    available = sum(i.status == "ready" for i in items)
    reasons: Counter[Reason] = Counter(i.reason for i in items if i.reason is not None)
    missing_reason: Reason = (
        next(iter(reasons)) if len(reasons) == 1 else "mixed_unavailable_reasons"
    )
    return SalesBlock(
        status="ready"
        if available == len(items) and not excluded
        else "partial"
        if available
        else "no_data",
        reason=None
        if available == len(items) and not excluded
        else "partial_source_rows"
        if available
        else missing_reason,
        items=tuple(items),
        excluded_count=excluded,
        excluded_counts={"mapping_conflict": excluded} if excluded else {},
        reason_counts=dict(reasons),
    ), sources


def get_location_reference(
    session: Session,
    query: LocationReferenceQuery,
) -> ApiResponse[LocationReference]:
    try:
        return _get_location_reference(session, query)
    except (ValueError, TypeError, OverflowError, OSError):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None


def _get_location_reference(
    session: Session,
    query: LocationReferenceQuery,
) -> ApiResponse[LocationReference]:
    _batches, reference = current_provenance(session)
    minimum = session.scalar(
        select(func.min(Store.open_date)).where(*temporal_cohort(query, reference))
    )
    target = effective_date(reference, minimum, query.as_of)
    catalog = load_catalog()
    sales, sources = _sales(session, query, target, catalog)
    data = LocationReference(
        requested_as_of=query.as_of,
        analysis_as_of=target,
        time_mode=query.time_mode,
        sales=sales,
    )
    meta: dict[str, object] = {
        "format_version": FORMAT_VERSION,
        "rule_version": RULE_VERSION,
        "requested_scope": {
            "radius_m": query.radius,
            "category": query.category,
            "sub_category": list(query.sub_category),
        },
        "source_catalog_digest": catalog_digest(catalog),
        "source_refs": sources,
        "excluded_counts_scope": "selected_market_industry_pairs",
        "items_additive": False,
        "store_filters_applied": False,
        "population_filter_applied": False,
        "historical_boundary_compatibility": "unverified",
        "population_total_validated": False,
        "source_validation_performed": False,
        "global_content_rechecked": False,
        "is_demo": False,
    }
    serialized = json.dumps(
        {"data": data.model_dump(mode="json"), "meta": meta},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    meta["reference_snapshot_token"] = hashlib.sha256(serialized.encode()).hexdigest()
    return ApiResponse(data=data, meta=cast(ApiMeta, meta))
