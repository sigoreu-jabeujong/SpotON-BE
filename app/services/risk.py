"""API v1.2 §4-7; clarified period/cohort contract in design feat64 §8."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import JsonValue
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.cache import CacheResources
from app.core.config import Settings
from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import Store
from app.models.store import STORE_GEOGRAPHY
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.franchise import ESTIMATE_LIMIT, EstimatedClassification
from app.schemas.market_judgement import BoundaryQuery
from app.schemas.risk import (
    MIN_CLOSURE_SAMPLE,
    MIN_SURVIVAL_SAMPLE,
    IndicatorId,
    ReferenceCounts,
    Risk,
    RiskFlags,
    RiskInclude,
    RiskIndicator,
    RiskMarket,
    RiskQuery,
    RiskQueryEcho,
)
from app.services.franchise import brand_context, enrich_meta
from app.services.market_activity import year_cutoff
from app.services.market_judgement import judge_market
from app.services.risk_cache import load_risk, risk_key, save_risk, snapshot_token
from app.services.spatial_stores import (
    NO_COORD_SCOPE,
    PREFILTER_MARGIN_M,
    attribute_filters,
    effective_date,
)
from app.services.store_cohort import current_provenance, provenance_meta, temporal_cohort

RULE_VERSION = "risk-reference-fixed-anniversary-v1"
OFFICIAL_RISK_URL = "https://golmok.seoul.go.kr/stateDistrict.do"
INCLUDE_ORDER: tuple[RiskInclude, ...] = ("market_change", "day_night_ratio")
SURVIVAL_IDS: tuple[tuple[int, IndicatorId], ...] = (
    (1, "survival_rate_1y"),
    (3, "survival_rate_3y"),
)


def percent(numerator: int, denominator: int) -> float:
    return float(
        (Decimal(numerator * 100) / Decimal(denominator)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    )


def period(lower: date, upper: date) -> str:
    return f"({lower.isoformat()}, {upper.isoformat()}]"


def rate_indicator(
    identifier: IndicatorId,
    numerator: int,
    denominator: int,
    seoul_num: int,
    seoul_den: int,
    minimum: int,
    space: str,
    window: str,
) -> RiskIndicator:
    ready, baseline_ready = denominator >= minimum, seoul_den >= minimum
    return RiskIndicator(
        id=identifier,
        type="reference",
        value=percent(numerator, denominator) if ready else None,
        unit="%",
        numerator=numerator if ready else None,
        denominator=denominator,
        seoul_avg=percent(seoul_num, seoul_den) if baseline_ready else None,
        seoul_avg_reason=None
        if baseline_ready
        else ("zero_denominator" if not seoul_den else "insufficient_sample"),
        seoul_numerator=seoul_num if baseline_ready else None,
        seoul_denominator=seoul_den,
        space=space,
        period=window,
        source=["R5", "R6"],
        status="fact" if ready else "pending",
        reason=None if ready else "zero_denominator" if not denominator else "insufficient_sample",
    )


def reference_indicators(
    local: ReferenceCounts,
    seoul: ReferenceCounts,
    target: date,
    radius: int,
) -> list[RiskIndicator]:
    """Ratios use the period/cohort denominator, with independent Seoul suppression."""
    if any(getattr(local, k) > getattr(seoul, k) for k in ReferenceCounts.model_fields):
        raise ValueError("local cohort exceeds Seoul cohort")
    space = f"radius_{radius}m"
    result = [
        rate_indicator(
            "closure_rate_12m",
            local.closure_num,
            local.closure_den,
            seoul.closure_num,
            seoul.closure_den,
            MIN_CLOSURE_SAMPLE,
            space,
            period(year_cutoff(target, target.year - 1), target),
        )
    ]
    for years, identifier in SURVIVAL_IDS:
        result.append(
            rate_indicator(
                identifier,
                getattr(local, f"survival_{years}_num"),
                getattr(local, f"survival_{years}_den"),
                getattr(seoul, f"survival_{years}_num"),
                getattr(seoul, f"survival_{years}_den"),
                MIN_SURVIVAL_SAMPLE,
                space,
                period(
                    year_cutoff(target, target.year - years - 1),
                    year_cutoff(target, target.year - years),
                ),
            )
        )
    result.append(
        RiskIndicator(
            id="competitor_count",
            type="reference",
            value=local.active,
            unit="개",
            numerator=local.active,
            space=space,
            period=target.isoformat(),
            source=["R5", "R6"],
            status="fact",
            reason=None,
        )
    )
    return result


def aggregate_counts(
    session: Session, conditions: list[ColumnElement[bool]], target: date
) -> ReferenceCounts:
    lower = year_cutoff(target, target.year - 1)
    columns = [
        func.count().label("cohort_size"),
        func.count()
        .filter(or_(Store.close_date.is_(None), Store.close_date > target))
        .label("active"),
        func.count()
        .filter(Store.close_date > lower, Store.close_date <= target)
        .label("closure_num"),
        func.count()
        .filter(or_(Store.close_date.is_(None), Store.close_date > lower))
        .label("closure_den"),
    ]
    for years in (1, 3):
        cohort = and_(
            Store.open_date > year_cutoff(target, target.year - years - 1),
            Store.open_date <= year_cutoff(target, target.year - years),
        )
        anniversary = Store.open_date + func.make_interval(years)
        survivor = and_(cohort, or_(Store.close_date.is_(None), Store.close_date > anniversary))
        columns.extend(
            (
                func.count().filter(survivor).label(f"survival_{years}_num"),
                func.count().filter(cohort).label(f"survival_{years}_den"),
            )
        )
    row = session.execute(select(*columns).select_from(Store).where(*conditions)).mappings().one()
    return ReferenceCounts.model_validate(dict(row))


def pending_indicator(identifier: IndicatorId, reason: str) -> RiskIndicator:
    official = identifier in {"official_closure_rate", "official_risk", "market_change"}
    return RiskIndicator(
        id=identifier,
        type="official" if official else "reference",
        value=None,
        space="market" if official else "grid",
        source=["R1"] if identifier == "official_risk" else ["R2"] if official else ["R4"],
        status="link_only" if identifier == "official_risk" else "pending",
        reason=reason,
        link=OFFICIAL_RISK_URL if identifier == "official_risk" else None,
        source_url=OFFICIAL_RISK_URL if identifier == "official_risk" else None,
    )


def get_risk(
    session: Session, query: RiskQuery, settings: Settings, *, cache: CacheResources | None = None
) -> ApiResponse[Risk]:
    try:
        key = None
        if cache is not None and cache.enabled:
            key = risk_key(cache, snapshot_token(session, cache), query, settings, RULE_VERSION)
            cached = load_risk(cache, key, query)
            if cached is not None:
                return cached
        result = _get_risk(session, query, settings)
        if cache is not None:
            save_risk(cache, key, result)
        return result
    except (SQLAlchemyError, ValueError, TypeError):
        pass
    raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)


def _get_risk(session: Session, query: RiskQuery, settings: Settings) -> ApiResponse[Risk]:
    batches, reference = current_provenance(session)
    cohort = temporal_cohort(query, reference)
    minimum = session.scalar(select(func.min(Store.open_date)).where(*cohort))
    target = effective_date(reference, minimum, query.as_of)
    conditions = [*cohort, *attribute_filters(query), Store.open_date <= target]
    excluded = int(
        session.scalar(
            select(func.count()).select_from(Store).where(*conditions, Store.geom.is_(None))
        )
        or 0
    )
    located = [*conditions, Store.geom.is_not(None)]
    seoul = aggregate_counts(session, located, target)
    point = cast(func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326), STORE_GEOGRAPHY)
    geography = cast(Store.geom, STORE_GEOGRAPHY)
    local = aggregate_counts(
        session,
        [
            *located,
            func.ST_DWithin(geography, point, query.radius + PREFILTER_MARGIN_M, True),
            func.ST_Distance(geography, point, True) <= query.radius,
        ],
        target,
    )
    refs = reference_indicators(local, seoul, target, query.radius)
    candidate = None
    if settings.risk_boundary_version_id is not None:
        candidate = judge_market(
            session,
            BoundaryQuery(
                version_id=settings.risk_boundary_version_id,
                lat=query.lat,
                lng=query.lng,
                radius=query.radius,
            ),
        )
    market = RiskMarket(
        reason="boundary_version_not_selected"
        if candidate is None
        else "boundary_period_not_verified",
        spatial_candidate=candidate,
    )
    indicators = [
        pending_indicator("official_closure_rate", "boundary_period_not_verified"),
        pending_indicator("official_risk", "official_values_not_collected"),
        *refs,
    ]
    for identifier in INCLUDE_ORDER:
        if identifier in query.include:
            indicators.append(
                pending_indicator(
                    identifier,
                    "boundary_period_not_verified"
                    if identifier == "market_change"
                    else "population_aggregation_and_grid_time_unverified",
                )
            )
    filters: dict[str, JsonValue] = query.model_dump(
        include={
            "sub_category",
            "area",
            "franchise",
            "include_unknown_area",
            "include_unknown_franchise",
        },
        mode="json",
    )
    data = Risk(
        query=RiskQueryEcho(
            lat=query.lat,
            lng=query.lng,
            category=query.category,
            radius_m=query.radius,
            as_of=target,
            filters=filters,
        ),
        market=market,
        indicators=indicators,
        flags=RiskFlags(
            insufficient_sample=any(r.status == "pending" for r in refs),
            missing=[
                r.id
                for r in indicators
                if r.status == "pending"
                and r.id in {"official_closure_rate", "market_change", "day_night_ratio"}
            ],
        ),
    )
    meta: ApiMeta = {
        **provenance_meta(batches, reference, RULE_VERSION),
        "as_of": target.isoformat(),
        "space": f"radius_{query.radius}m",
        "denominator": None,
        "cohort_size": local.cohort_size,
        "excluded_no_coord": excluded,
        "excluded_no_coord_scope": NO_COORD_SCOPE,
        "excluded_no_coord_cohort": "opened_by_as_of",
        "coordinate_basis": "located_only",
        "event_basis": "validated_license_dates",
        "closure_sample_basis": "period_denominator",
        "survival_basis": "fixed_opening_anniversary",
        "survival_cohort": "preceding_entry_year",
        "survival_close_boundary": "close_after_anniversary",
        "rounding": "decimal_half_up_1dp",
        "minimum_samples": {"closure": MIN_CLOSURE_SAMPLE, "survival": MIN_SURVIVAL_SAMPLE},
        "seoul_comparison_basis": "same_filters_located_license_records",
        "limitations": [
            "license_records_not_business_outcomes",
            "ownership_transfer_not_separated",
            "historical_intervals_from_current_snapshot",
            "coordinate_selection_bias_possible",
        ],
    }
    branding = brand_context(session)
    enrich_meta(meta, branding)
    if isinstance(branding.classification, EstimatedClassification):
        limitations = meta["limitations"]
        if isinstance(limitations, list):
            limitations.append(ESTIMATE_LIMIT)
    return ApiResponse(data=data, meta=meta)
