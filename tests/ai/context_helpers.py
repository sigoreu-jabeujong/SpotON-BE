"""Synthetic server-shaped Risk, never source rows or credentials."""

import copy
from datetime import date
from unittest.mock import Mock
from uuid import UUID

from app.schemas.common import ApiResponse
from app.schemas.market_activity import (
    ActivityFlags,
    MarketActivity,
    RecentActivity,
    SubCategoryActivity,
)
from app.schemas.risk import ReferenceCounts, Risk, RiskFlags, RiskMarket, RiskQuery, RiskQueryEcho
from app.schemas.stores import HistoryQuery, HistoryStore, StoreHistory
from app.services.market_activity import year_cutoff
from app.services.risk import pending_indicator, period, reference_indicators
from app.services.store_scope import name_exclusion_meta

DATE = date(2026, 11, 8)


def query(**changes):
    return RiskQuery(**{**dict(lat=37.56789123, lng=126.98765432, category="cafe"), **changes})


def response(q=None, local=None, seoul=None):
    q = q or query()
    local = local or ReferenceCounts(
        cohort_size=20,
        active=8,
        closure_num=2,
        closure_den=10,
        survival_1_num=3,
        survival_1_den=5,
        survival_3_num=4,
        survival_3_den=5,
    )
    seoul = seoul or ReferenceCounts(
        cohort_size=40,
        active=16,
        closure_num=4,
        closure_den=20,
        survival_1_num=6,
        survival_1_den=10,
        survival_3_num=8,
        survival_3_den=10,
    )
    refs = reference_indicators(local, seoul, DATE, q.radius)
    indicators = [
        pending_indicator("official_closure_rate", "boundary_period_not_verified"),
        pending_indicator("official_risk", "official_values_not_collected"),
        *refs,
    ]
    if "market_change" in q.include:
        indicators.append(pending_indicator("market_change", "boundary_period_not_verified"))
    if "day_night_ratio" in q.include:
        indicators.append(
            pending_indicator("day_night_ratio", "population_aggregation_and_grid_time_unverified")
        )
    filters = q.model_dump(
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
            lat=q.lat,
            lng=q.lng,
            category=q.category,
            radius_m=q.radius,
            as_of=DATE,
            filters=filters,
        ),
        market=RiskMarket(reason="boundary_version_not_selected", spatial_candidate=None),
        indicators=indicators,
        flags=RiskFlags(
            insufficient_sample=any(r.status == "pending" for r in refs),
            missing=[
                r.id
                for r in indicators
                if r.status == "pending" and r.type == "official" or r.id == "day_night_ratio"
            ],
        ),
    )
    meta = {
        "name_exclusion": name_exclusion_meta(),
        "source": ["R5", "R6"],
        "data_updated_at": DATE.isoformat(),
        "as_of": DATE.isoformat(),
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "denominator": None,
        "cohort_size": local.cohort_size,
        "event_basis": "validated_license_dates",
        "coordinate_basis": "located_only",
        "closure_sample_basis": "period_denominator",
        "survival_basis": "fixed_opening_anniversary",
        "survival_cohort": "preceding_entry_year",
        "survival_close_boundary": "close_after_anniversary",
        "rounding": "decimal_half_up_1dp",
        "minimum_samples": {"closure": 10, "survival": 5},
        "seoul_comparison_basis": "same_filters_located_license_records",
        "franchise_classification": {"status": "pending", "reason": "brand_mapping_blocked"},
        "limitations": [
            "license_records_not_business_outcomes",
            "ownership_transfer_not_separated",
            "historical_intervals_from_current_snapshot",
            "coordinate_selection_bias_possible",
            "restaurant_name_keywords_may_exclude_valid_stores",
        ],
        "data_version": {
            "stores_batch_ids": [str(UUID(int=66))],
            "trdar_quarter": None,
            "map_version": "synthetic-map",
            "rule_version": "risk-reference-fixed-anniversary-v1",
            "name_exclusion_version": "store-name-keywords-v1",
        },
    }
    return ApiResponse(data=data, meta=meta)


RESTAURANT = ("korean", "chinese", "japanese", "western")


def activity_response(risk, q=None, *, opened=3, months=41):
    """Activity derived from a Risk response so the design §4 invariants hold.

    All active records go to the first selected sub-category; the rest are zero groups.
    """
    q = q or query()
    rows = {r.id: r for r in risk.data.indicators}
    active = rows["competitor_count"].value
    closed = rows["closure_rate_12m"].denominator - active
    ordered = ("cafe",) if q.category == "cafe" else RESTAURANT
    selected = [c for c in ordered if not q.sub_category or c in q.sub_category]
    data = MarketActivity(
        recent_12m=RecentActivity(
            period=period(year_cutoff(DATE, DATE.year - 1), DATE), opened=opened, closed=closed
        ),
        yearly_trend=[],
        by_sub_category=[
            SubCategoryActivity(
                sub_category=c,
                open_count=active if i == 0 else 0,
                avg_operating_months=months if i == 0 and active else None,
            )
            for i, c in enumerate(selected)
        ],
        sales=None,
        living_pop=None,
        flags=ActivityFlags(missing=[]),
    )
    version = copy.deepcopy(risk.meta["data_version"])
    version["rule_version"] = "market-activity-license-ytd-v1"
    meta = {
        "source": ["R5", "R6"],
        "data_updated_at": risk.meta["data_updated_at"],
        "name_exclusion": name_exclusion_meta(),
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "is_demo": False,
        "data_version": version,
        "as_of": risk.meta["as_of"],
        "space": f"radius_{q.radius}m",
        "denominator": None,
        "cohort_size": risk.meta.get("cohort_size"),
        "franchise_classification": copy.deepcopy(risk.meta["franchise_classification"]),
    }
    return ApiResponse(data=data, meta=meta)


def use_risk(monkeypatch, module, result, q=None, **activity):
    """Patch both server recalculations of the AI context module; returns the two mocks.

    History lookups fail loudly unless a test enables them with use_history().
    """
    risk = result if isinstance(result, Mock) else Mock(return_value=result)
    source = risk.return_value if isinstance(result, Mock) else result
    server = Mock(return_value=activity_response(source, q, **activity))
    monkeypatch.setattr(module, "get_risk", risk)
    monkeypatch.setattr(module, "get_activity", server)
    guard = Mock(side_effect=AssertionError("history must not be recalculated"))
    monkeypatch.setattr(module, "get_history", guard)
    monkeypatch.setattr(module, "check_history_location", guard)
    return risk, server


def history_row(
    location_match="same_spot",
    store_status="closed",
    months=14,
    *,
    category="cafe",
    sub_category="cafe",
    index=0,
):
    """Synthetic HistoryStore. Names/licence numbers are canaries that must never leak."""
    closed = store_status == "closed"
    return HistoryStore(
        source="rest_cafe" if category == "cafe" else "general_restaurant",
        license_no=f"PRIVATE-LICENSE-{index}",
        name=f"PRIVATE-NAME-{index}",
        category=category,
        sub_category=sub_category,
        open_date=date(2020, 1, 1),
        close_date=date(2021, 3, 1) if closed else None,
        operating_months=months,
        operating_period_status="fact" if months is not None else "no_data",
        operating_period_reason=None if months is not None else "missing_close_date",
        store_status=store_status,
        franchise="unknown",
        floor_unit="PRIVATE-FLOOR",
        location_match=location_match,
    )


def history_response(risk, rows):
    version = copy.deepcopy(risk.meta["data_version"])
    version["rule_version"] = "store-history-calendar-months-v1"
    meta = {
        "source": ["R5", "R6"],
        "space": "point",
        "name_exclusion": name_exclusion_meta(),
        "denominator": len(rows),
        "as_of": risk.meta["data_updated_at"],
        "data_updated_at": risk.meta["data_updated_at"],
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "is_demo": False,
        "data_version": version,
        "franchise_classification": copy.deepcopy(risk.meta["franchise_classification"]),
    }
    return ApiResponse(
        data=StoreHistory(total=len(rows), stores=list(rows), message=None), meta=meta
    )


def history_query(building_key="마포구-서교동-123-4", floor_unit="1층 101호", category="cafe"):
    return HistoryQuery(building_key=building_key, floor_unit=floor_unit, category=category)


def use_history(monkeypatch, module, risk, rows):
    """Enable history recalculation; returns (location check, history) mocks."""
    location = Mock(return_value=None)
    server = Mock(return_value=history_response(risk, rows))
    monkeypatch.setattr(module, "check_history_location", location)
    monkeypatch.setattr(module, "get_history", server)
    return location, server
