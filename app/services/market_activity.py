"""API v1.2 §4-6: events retain closed licenses; active periods end at the requested date."""

from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import cast as type_cast

from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import Store
from app.models.store import STORE_GEOGRAPHY
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.market_activity import (
    YEARLY_TREND_START_YEAR,
    ActivityFlags,
    ActivityInclude,
    ActivityQuery,
    MarketActivity,
    RecentActivity,
    SubCategoryActivity,
    YearlyActivity,
)
from app.schemas.stores import SubCategory
from app.services.chains import ChainSelection
from app.services.franchise import brand_context, enrich_meta
from app.services.spatial_stores import (
    NO_COORD_SCOPE,
    PREFILTER_MARGIN_M,
    attribute_filters,
    effective_date,
)
from app.services.store_cohort import current_provenance, provenance_meta, temporal_cohort
from app.services.store_history import complete_months

RULE_VERSION = "market-activity-license-ytd-v2"
INCLUDE_ORDER: tuple[ActivityInclude, ...] = ("sales", "living_pop")
RESTAURANT_ORDER: tuple[SubCategory, ...] = ("korean", "chinese", "japanese", "western")
PENDING_REASONS = {
    "sales": "source_period_and_boundary_unverified",
    "living_pop": "population_aggregation_and_grid_time_unverified",
}


@dataclass(frozen=True, repr=False)
class ActivityRecord:
    source: str
    license_no: str
    open_date: date
    close_date: date | None
    sub_category: SubCategory


def year_cutoff(target: date, year: int) -> date:
    """Same month/day, clamped only if the date does not exist in that year."""
    return date(year, target.month, min(target.day, monthrange(year, target.month)[1]))


def selected_categories(query: ActivityQuery) -> tuple[SubCategory, ...]:
    ordered: tuple[SubCategory, ...] = ("cafe",) if query.category == "cafe" else RESTAURANT_ORDER
    return tuple(c for c in ordered if not query.sub_category or c in query.sub_category)


def aggregate_activity(
    records: list[ActivityRecord], query: ActivityQuery, target: date
) -> MarketActivity:
    lower = year_cutoff(target, target.year - 1)
    categories = selected_categories(query)
    identities: set[tuple[str, str]] = set()
    opened: Counter[int] = Counter()
    closed: Counter[int] = Counter()
    years: set[int] = set()
    active: Counter[SubCategory] = Counter()
    months: Counter[SubCategory] = Counter()
    recent_opened = recent_closed = 0
    for row in records:
        identity = (row.source, row.license_no)
        if (
            identity in identities
            or row.source not in {"general_restaurant", "rest_cafe"}
            or not row.license_no
            or row.sub_category not in categories
            or row.open_date < date(1960, 1, 1)
            or row.open_date > target
            or (row.close_date is not None and row.close_date < row.open_date)
        ):
            raise ValueError("invalid activity cohort")
        identities.add(identity)
        recent_opened += lower < row.open_date <= target
        recent_closed += row.close_date is not None and lower < row.close_date <= target
        for event, counter in ((row.open_date, opened), (row.close_date, closed)):
            if event is not None and event <= target and event.year >= YEARLY_TREND_START_YEAR:
                years.add(event.year)
                if event <= year_cutoff(target, event.year):
                    counter[event.year] += 1
        if row.close_date is None or row.close_date > target:
            active[row.sub_category] += 1
            months[row.sub_category] += complete_months(row.open_date, target)
    return MarketActivity(
        recent_12m=RecentActivity(
            period=f"({lower.isoformat()}, {target.isoformat()}]",
            opened=recent_opened,
            closed=recent_closed,
        ),
        yearly_trend=[
            YearlyActivity(year=y, opened=opened[y], closed=closed[y]) for y in sorted(years)
        ],
        by_sub_category=[
            SubCategoryActivity(
                sub_category=c,
                open_count=active[c],
                avg_operating_months=months[c] // active[c] if active[c] else None,
            )
            for c in categories
        ],
        sales=None,
        living_pop=None,
        flags=ActivityFlags(missing=[v for v in INCLUDE_ORDER if v in query.include]),
    )


def get_activity(
    session: Session, query: ActivityQuery, *, chain: ChainSelection | None = None
) -> ApiResponse[MarketActivity]:
    try:
        return _get_activity(session, query, **({"chain": chain} if chain else {}))
    except (ValueError, TypeError):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None


def _get_activity(
    session: Session, query: ActivityQuery, *, chain: ChainSelection | None = None
) -> ApiResponse[MarketActivity]:
    batches, reference = current_provenance(session)
    cohort = temporal_cohort(query, reference)
    minimum = session.scalar(select(func.min(Store.open_date)).where(*cohort))
    target = effective_date(reference, minimum, query.as_of)
    conditions = [*cohort, *attribute_filters(query, chain), Store.open_date <= target]
    excluded = int(
        session.scalar(
            select(func.count()).select_from(Store).where(*conditions, Store.geom.is_(None))
        )
        or 0
    )
    point = cast(func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326), STORE_GEOGRAPHY)
    geography = cast(Store.geom, STORE_GEOGRAPHY)
    values = session.execute(
        select(
            Store.source,
            Store.license_no,
            Store.open_date,
            Store.close_date,
            Store.sub_category,
            Store.area_m2,
            Store.status,
            func.ST_Distance(geography, point, True).label("distance_m"),
        ).where(
            *conditions,
            Store.geom.is_not(None),
            func.ST_DWithin(geography, point, query.radius + PREFILTER_MARGIN_M, True),
            func.ST_Distance(geography, point, True) <= query.radius,
        )
    ).all()
    records = [
        ActivityRecord(
            row.source,
            row.license_no,
            type_cast(date, row.open_date),
            row.close_date,
            type_cast(SubCategory, row.sub_category),
        )
        for row in values
    ]
    data = aggregate_activity(records, query, target)
    active_rows = [r for r in values if r.close_date is None or r.close_date > target]
    distances = [float(r.distance_m) for r in active_rows]
    known_area = sum(r.area_m2 is not None and r.area_m2 > 0 for r in active_rows)
    latest_open = sum(r.status == "open" for r in active_rows)
    latest_closed = sum(r.status == "closed" for r in active_rows)
    optional: ApiMeta = {
        value: {"status": "pending", "reason": PENDING_REASONS[value]}
        for value in INCLUDE_ORDER
        if value in query.include
    }
    meta: ApiMeta = {
        **provenance_meta(batches, reference, RULE_VERSION),
        "as_of": target.isoformat(),
        "space": f"radius_{query.radius}m",
        "denominator": None,
        "cohort_size": len(records),
        "event_basis": "validated_license_dates",
        "yearly_comparison_basis": "same_month_day_ytd",
        "yearly_periods": {
            str(row.year): {
                "start": f"{row.year}-01-01",
                "end": year_cutoff(target, row.year).isoformat(),
            }
            for row in data.yearly_trend
        },
        "operating_period_basis": "elapsed_months_of_active_at_as_of",
        "record_profile": {
            "active_at_as_of": len(active_rows),
            "closed_since_as_of": sum(
                r.close_date is not None and target < r.close_date <= reference for r in active_rows
            ),
            "latest_open": latest_open,
            "latest_closed": latest_closed,
            "latest_other": len(active_rows) - latest_open - latest_closed,
            "known_area": known_area,
            "unknown_area": len(active_rows) - known_area,
            "min_distance_m": round(min(distances), 1) if distances else None,
            "max_distance_m": round(max(distances), 1) if distances else None,
        },
        "avg_operating_months_denominator": "open_count",
        "avg_operating_months_rounding": "floor_mean_of_completed_months",
        "excluded_no_coord": excluded,
        "excluded_no_coord_scope": NO_COORD_SCOPE,
        "excluded_no_coord_cohort": "opened_by_as_of",
        "optional_data": optional,
    }
    if chain is None:
        enrich_meta(meta, brand_context(session))
    return ApiResponse(data=data, meta=meta)
