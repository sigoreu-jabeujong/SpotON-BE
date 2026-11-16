"""Source-row weighted references, never a deduplicated merchant average."""

from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import MarketStore, MarketStoreVersion
from app.schemas.location_reference import SalesBlock


def metric(sales: int, stores: int) -> dict[str, Any]:
    if (
        type(sales) is not int
        or type(stores) is not int
        or not (0 <= sales <= 500 * (2**63 - 1) and 0 < stores <= 500 * (2**31 - 1))
    ):
        raise ValueError("invalid weighted inputs")
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        value = format(Decimal(sales) / stores, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    q, r = divmod(sales, stores)
    display = "1원 미만/점포" if 0 < sales < stores else f"{q + (2 * r >= stores):,}원/점포"
    return dict(
        numerator=str(sales),
        denominator=str(stores),
        value=value,
        value_precision="decimal50",
        display=display,
        unit="KRW_source_reported_per_store",
        rounded=r != 0,
        exact_zero=sales == 0,
    )


def attach(
    session: Session, block: SalesBlock, version: MarketStoreVersion | None, target: date, mode: str
) -> SalesBlock:
    from app.services.location_reference import TYPES, _bounds, _temporal

    items = list(block.items)
    if len(items) > 500:
        raise ValueError("too many weighted items")
    keys = [(i.market_code, i.source_quarter, i.industry_code) for i in items if i.metric]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate weighted item")
    quarters = sorted({str(k[1]) for k in keys}, reverse=True)
    primary = (
        f"{target.year}{(target.month - 1) // 3 + 1}"
        if mode == "analysis_period"
        else (quarters[0] if quarters else None)
    )
    rows = (
        list(
            session.scalars(
                select(MarketStore)
                .where(
                    MarketStore.version_id == version.version_id,
                    tuple_(MarketStore.market_code, MarketStore.quarter, MarketStore.induty_cd).in_(
                        keys
                    ),
                )
                .limit(501)
            )
        )
        if version is not None and keys
        else []
    )
    if len(rows) > 500:
        raise ValueError("too many store references")
    counts = {(r.market_code, r.quarter, r.induty_cd): r for r in rows}
    if len(counts) != len(rows):
        raise ValueError("duplicate store reference")
    reasons: dict[tuple[str, str | None, str], str | None] = {}
    enriched = []
    for item in items:
        key = (item.market_code, item.source_quarter, item.industry_code)
        row = (
            counts.get((item.market_code, item.source_quarter, item.industry_code))
            if item.source_quarter is not None
            else None
        )
        reason = (
            "sales_unavailable"
            if item.metric is None
            else "store_row_missing"
            if row is None
            else None
        )
        reference = None
        number = None
        if row is not None:
            if (
                any(
                    type(n) is not int or n < 0
                    for n in (row.total_stores, row.general_stores, row.franchise_stores)
                )
                or row.total_stores != row.general_stores + row.franchise_stores
            ):
                raise ValueError("invalid store counts")
            if (row.market_name, TYPES.get(row.market_type_code), row.induty_name) != (
                item.market_name,
                item.market_type,
                item.industry_name,
            ):
                reason = "store_mapping_conflict"
                reference = dict(
                    status="no_data",
                    reason=reason,
                    source_quarter=None,
                    total_stores=None,
                    general_stores=None,
                    franchise_stores=None,
                    provenance_ref="store-counts",
                )
            else:
                reference = dict(
                    status="ready",
                    reason=None,
                    source_quarter=row.quarter,
                    total_stores=str(row.total_stores),
                    general_stores=str(row.general_stores),
                    franchise_stores=str(row.franchise_stores),
                    provenance_ref="store-counts",
                )
                if row.total_stores == 0:
                    reason = (
                        "zero_store_count_with_sales"
                        if item.metric and int(item.metric.value)
                        else "zero_store_count"
                    )
                elif item.metric:
                    number = metric(int(item.metric.value), row.total_stores)
        reasons[key] = reason
        contribution = (
            "sales_unavailable"
            if item.metric is None
            else ("different_quarter" if item.source_quarter != primary else reason)
        )
        enriched.append(
            item.model_copy(
                update=dict(
                    store_reference=reference,
                    per_store_metric=number,
                    average_contribution=dict(
                        status="included"
                        if contribution is None
                        else "different_quarter"
                        if contribution == "different_quarter"
                        else "excluded",
                        reason=contribution,
                    ),
                )
            )
        )

    def group(quarter: str) -> dict[str, Any]:
        candidates = [i for i in enriched if i.metric and i.source_quarter == quarter]
        used = [i for i in candidates if i.per_store_metric is not None]
        excluded = Counter(
            reasons[(i.market_code, i.source_quarter, i.industry_code)]
            for i in candidates
            if i.per_store_metric is None
        )
        s = sum(int(i.metric.value) for i in used if i.metric)
        n = sum(int(i.per_store_metric["denominator"]) for i in used if i.per_store_metric)
        status = (
            "ready" if used and len(used) == len(candidates) else "partial" if used else "no_data"
        )
        return dict(
            source_quarter=quarter,
            temporal_relation=_temporal(quarter, target),
            period_end_after_analysis=_bounds(quarter)[1] > target,
            status=status,
            reason=None
            if status == "ready"
            else "partial_source_rows"
            if used
            else "no_valid_sales_store_pairs",
            candidate_item_count=len(candidates),
            included_item_count=len(used),
            included_market_count=len({i.market_code for i in used}),
            excluded_counts_scope="group_numeric_items",
            excluded_counts=dict(excluded),
            total_sales=str(s) if used else None,
            total_store_count=str(n) if used else None,
            metric=metric(s, n) if used else None,
            included_item_keys=[
                dict(
                    market_code=i.market_code, industry_code=i.industry_code, source_quarter=quarter
                )
                for i in used
            ],
        )

    groups = [group(q) for q in quarters]
    selected = next((g for g in groups if g["source_quarter"] == primary), None)
    used_count = selected["included_item_count"] if selected else 0
    excluded = Counter(
        i.average_contribution["reason"]
        for i in enriched
        if i.average_contribution and i.average_contribution["reason"]
    )
    status = (
        "ready"
        if used_count and used_count == len(items)
        else "partial"
        if used_count
        else "no_data"
    )
    reason = (
        None
        if status == "ready"
        else "partial_source_rows"
        if used_count
        else "no_valid_sales_store_pairs"
    )
    if not keys:
        status, reason = block.status, block.reason
    summary = dict(
        rule_version="source-row-store-weighted-v1",
        status=status,
        reason=reason,
        primary_quarter=primary,
        temporal_relation=_temporal(primary, target) if primary else None,
        period_end_after_analysis=_bounds(primary)[1] > target if primary else None,
        aggregation_basis="listed_source_rows_weighted_by_total_stores",
        store_count_basis="source_total_stores",
        deduplication="not_performed",
        unique_store_average=False,
        population_compatibility="unverified",
        amount_period_status="unverified",
        listed_item_count=len(items),
        included_item_count=used_count,
        included_market_count=selected["included_market_count"] if selected else 0,
        excluded_counts_scope="listed_items",
        excluded_counts=dict(excluded),
        total_sales=selected["total_sales"] if selected else None,
        total_store_count=selected["total_store_count"] if selected else None,
        metric=selected["metric"] if selected else None,
        groups=groups,
    )
    return SalesBlock.model_validate(
        block.model_dump() | dict(items=tuple(enriched), per_store_average=summary)
    )
