"""Synthetic server-shaped Risk, never source rows or credentials."""

from datetime import date
from uuid import UUID

from app.schemas.common import ApiResponse
from app.schemas.risk import ReferenceCounts, Risk, RiskFlags, RiskMarket, RiskQuery, RiskQueryEcho
from app.services.risk import pending_indicator, reference_indicators

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
        "source": ["R5", "R6"],
        "data_updated_at": DATE.isoformat(),
        "as_of": DATE.isoformat(),
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "denominator": None,
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
        ],
        "data_version": {
            "stores_batch_ids": [str(UUID(int=66))],
            "trdar_quarter": None,
            "map_version": "synthetic-map",
            "rule_version": "risk-reference-fixed-anniversary-v1",
        },
    }
    return ApiResponse(data=data, meta=meta)
