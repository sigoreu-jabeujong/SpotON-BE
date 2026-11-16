"""Project complete selected-industry coverage using the existing ranked market totals."""

from typing import TYPE_CHECKING, Any

from app.services.industry_selection import INDUSTRIES
from app.services.top_markets_sales import ranked_market_totals

if TYPE_CHECKING:
    from app.schemas.location_reference import SalesItem


def market_aggregation(
    items: tuple["SalesItem", ...],
    quarter: str | None,
    requested: tuple[tuple[str, str], ...],
    source_status: str,
    source_reason: str | None,
    temporal_relation: str | None,
) -> dict[str, Any]:
    from app.services.per_store_sales import metric

    allowed = set(INDUSTRIES.values()) - {INDUSTRIES["cafe"]}
    if not requested or requested != tuple(sorted(set(requested))) or not set(requested) <= allowed:
        raise ValueError("invalid requested market industries")
    codes = {code for code, _ in requested}
    by_market: dict[str, list[SalesItem]] = {}
    for item in items:
        by_market.setdefault(item.market_code, []).append(item)
    for rows in by_market.values():
        if len(rows) != len(codes) or {i.industry_code for i in rows} != codes:
            raise ValueError("incomplete market industry input")
        if len({(i.market_type, i.spatial_relation) for i in rows}) != 1:
            raise ValueError("conflicting market metadata")
    _, eligible, ranked = ranked_market_totals(items, quarter)
    valid_keys = {(i.market_code, i.industry_code) for i in eligible}
    totals = {m["market_code"]: m for m in ranked}
    ranks = {m["market_code"]: rank for rank, m in enumerate(ranked, 1)}
    result = []
    for code, rows in by_market.items():
        first = rows[0]
        candidates = [i for i in rows if i.source_quarter == quarter and i.per_store_metric]
        conflict = len({i.market_name for i in candidates}) > 1
        used = sorted(
            (i for i in rows if (code, i.industry_code) in valid_keys),
            key=lambda i: i.industry_code,
        )
        unavailable = []
        for item in sorted(rows, key=lambda i: i.industry_code):
            if (code, item.industry_code) in valid_keys:
                continue
            reason = (
                "market_name_conflict"
                if conflict
                else item.reason
                if item.metric is None
                else "different_quarter"
                if item.source_quarter != quarter
                else (item.average_contribution or {}).get("reason")
            )
            if reason is None:
                raise ValueError("missing unavailable industry reason")
            unavailable.append(
                dict(
                    industry_code=item.industry_code,
                    reason=reason,
                    source_quarter=item.source_quarter,
                )
            )
        total = totals.get(code)
        status = "ready" if len(used) == len(requested) else "partial" if used else "no_data"
        result.append(
            dict(
                market_code=code,
                market_name=None
                if conflict
                else total["market_name"]
                if total
                else first.market_name,
                market_type=first.market_type,
                spatial_relation=first.spatial_relation,
                source_quarter=quarter,
                temporal_relation=temporal_relation,
                status=status,
                reason=None
                if status == "ready"
                else "partial_selected_industries"
                if used
                else "market_name_conflict"
                if conflict
                else "no_valid_sales_store_pairs",
                included_industry_codes=[i.industry_code for i in used],
                unavailable_industries=unavailable,
                included_item_keys=[
                    dict(market_code=code, industry_code=i.industry_code, source_quarter=quarter)
                    for i in used
                ],
                total_sales=str(total["sales"]) if total else None,
                total_store_count=str(total["stores"]) if total else None,
                per_store_metric=metric(total["sales"], total["stores"]) if total else None,
                rank=ranks.get(code),
                selected_for_estimate=ranks.get(code, 101) <= 3,
            )
        )
    result.sort(key=lambda m: (m["rank"] is None, m["rank"] or 101, m["market_code"]))
    status, reason = (
        (source_status, source_reason)
        if not items and source_status in {"no_data", "pending", "not_supported"}
        else ("no_data", "no_valid_sales_store_pairs")
        if not ranked
        else ("partial", "partial_source_rows")
        if any(m["status"] != "ready" for m in result)
        else ("partial", "fewer_than_three_markets")
        if len(ranked) < 3
        else ("ready", None)
    )
    return dict(
        rule_version="restaurant_market_rollup_v1",
        category="restaurant",
        source_quarter=quarter,
        requested_industries=[dict(industry_code=c, industry_name=n) for c, n in requested],
        status=status,
        reason=reason,
        eligible_market_count=len(ranked),
        selected_market_codes=[m["market_code"] for m in ranked[:3]],
        items=result,
    )
