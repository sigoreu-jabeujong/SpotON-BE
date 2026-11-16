"""Estimate from at most three distinct markets, ranked by eligible store count."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.schemas.location_reference import SalesItem


def ranked_market_totals(
    items: tuple["SalesItem", ...], quarter: str | None
) -> tuple[list["SalesItem"], list["SalesItem"], list[dict[str, Any]]]:
    markets: dict[str, dict[str, Any]] = {}
    candidates = [i for i in items if i.source_quarter == quarter and i.metric is not None]
    eligible = [i for i in candidates if i.per_store_metric is not None]
    names: dict[str, set[str]] = {}
    for item in eligible:
        names.setdefault(item.market_code, set()).add(item.market_name)
    # A conflicted market cannot provide a trustworthy named source.
    eligible = [i for i in eligible if len(names[i.market_code]) == 1]
    for item in eligible:
        if item.metric is None or item.store_reference is None:
            raise ValueError("invalid eligible market reference")
        market = markets.setdefault(
            item.market_code,
            dict(
                market_code=item.market_code,
                market_name=item.market_name,
                sales=0,
                stores=0,
                industry_codes=[],
            ),
        )
        market["sales"] += int(item.metric.value)
        market["stores"] += int(item.store_reference["total_stores"])
        market["industry_codes"].append(item.industry_code)
    ranked = sorted(markets.values(), key=lambda m: (-m["stores"], m["market_code"]))
    return candidates, eligible, ranked


def top_markets_estimate(items: tuple["SalesItem", ...], quarter: str | None) -> dict[str, Any]:
    from app.services.per_store_sales import metric

    candidates, eligible, all_markets = ranked_market_totals(items, quarter)
    ranked = all_markets[:3]
    sales = sum(m["sales"] for m in ranked)
    stores = sum(m["stores"] for m in ranked)
    return dict(
        method="top3_markets_by_store_count_v1",
        source_quarter=quarter,
        status="no_data"
        if not ranked
        else "partial"
        if len(ranked) < 3 or len(eligible) < len(candidates)
        else "ready",
        reason="no_valid_sales_store_pairs"
        if not ranked
        else "partial_source_rows"
        if len(eligible) < len(candidates)
        else "fewer_than_three_markets"
        if len(ranked) < 3
        else None,
        eligible_market_count=len(all_markets),
        selected_market_count=len(ranked),
        excluded_item_count=len(candidates) - len(eligible),
        total_sales=str(sales) if ranked else None,
        total_store_count=str(stores) if ranked else None,
        metric=metric(sales, stores) if ranked else None,
        markets=[
            dict(
                market_code=m["market_code"],
                market_name=m["market_name"],
                total_sales=str(m["sales"]),
                total_store_count=str(m["stores"]),
                industry_codes=sorted(m["industry_codes"]),
                metric=metric(m["sales"], m["stores"]),
            )
            for m in ranked
        ],
    )
