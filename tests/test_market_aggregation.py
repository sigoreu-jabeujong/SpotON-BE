import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.location_reference import LocationReferenceQuery, SalesBlock
from app.services.industry_selection import INDUSTRIES, effective_industries
from app.services.per_store_sales import attach
from tests.test_per_store_sales import FakeSession, item, row


def calculate(
    subs=(), *, missing=None, old=None, zero=None, free=None, big=False, mode="latest_reference"
):
    query = LocationReferenceQuery(category="restaurant", sub_category=subs, lat=0, lng=0)
    selection = effective_industries(query)
    counts = [[25, 20, 30, 25], [50, 20, 5, 5], [10, 10, 50, 50], [5, 10, 35, 40]]
    items, rows = [], []
    for m in range(4):
        for code, label in selection.source_order:
            j = int(code[-1]) - 1
            n = 0 if (m, j) == zero else counts[m][j]
            q = "20253" if (m, j) == old else "20254"
            amount = (
                (2**63 - 1)
                if big
                else 0
                if (m, j) == free
                else n * (2000000 if m == 2 else 1000000)
            )
            i = item(f"311000{m}", amount, q).model_copy(
                update={"industry_code": code, "industry_name": label}
            )
            r = row(f"311000{m}", n, q)
            r.induty_cd, r.induty_name = code, label
            items.append(i)
            if (m, j) != missing:
                rows.append(r)
    return attach(
        FakeSession(rows),
        SalesBlock(status="ready", items=tuple(items)),
        SimpleNamespace(version_id="synthetic"),
        date(2025, 11, 30),
        mode,
        category="restaurant",
        requested_industries=selection.canonical_order,
    )


def test_four_selected_industries_merge_to_distinct_markets_and_pooled_top_three():
    result = calculate()
    a = result.market_aggregation
    assert [m.market_code for m in a.items] == ["3110002", "3110000", "3110003", "3110001"]
    assert len(a.items) == 4 and len(result.items) == 16
    assert a.items[1].total_sales == "100000000" and a.items[1].total_store_count == "100"
    assert a.items[1].included_industry_codes == ("CS100001", "CS100002", "CS100003", "CS100004")
    top = result.top_markets_estimate
    assert (top["total_sales"], top["total_store_count"], top["metric"]["display"]) == (
        "430000000",
        "310",
        "1,387,097원/점포",
    )


def test_subset_recomputes_all_market_ranks_and_preserves_source_order():
    all_items = calculate()
    result = calculate(("chinese", "korean"))
    a = result.market_aggregation
    assert a.selected_market_codes == ("3110001", "3110000", "3110002")
    assert result.top_markets_estimate["total_sales"] == "155000000"
    assert result.top_markets_estimate["total_store_count"] == "135"
    assert result.items[0].industry_code == "CS100002"
    assert [i.industry_code for i in a.requested_industries] == ["CS100001", "CS100002"]
    assert calculate(("korean", "chinese")).market_aggregation == a
    assert (
        calculate(("korean", "chinese", "japanese", "western")).market_aggregation
        == all_items.market_aggregation
    )


@pytest.mark.parametrize(
    "kind,reason",
    [("missing", "store_row_missing"), ("old", "different_quarter"), ("zero", "zero_store_count")],
)
def test_incomplete_selected_industry_is_disclosed_and_not_added(kind, reason):
    r = calculate(**{kind: (2, 0)})
    m = next(m for m in r.market_aggregation.items if m.market_code == "3110002")
    assert m.status == "partial" and len(m.included_industry_codes) == 3
    assert m.unavailable_industries[0].reason == reason
    assert m.total_store_count == "110" and m.total_sales == "220000000"


@pytest.mark.parametrize(
    "change",
    [
        "amount",
        "rank",
        "selected",
        "industry",
        "omitted",
        "boolean",
        "reason",
        "label",
        "top_mismatch",
        "missing_average",
    ],
)
def test_schema_rejects_aggregation_tampering(change):
    data = deepcopy(calculate().model_dump(mode="json"))
    a = data["market_aggregation"]
    if change == "amount":
        a["items"][0]["total_sales"] = "1"
    elif change == "rank":
        a["items"][0]["rank"] = 3
    elif change == "selected":
        a["selected_market_codes"].reverse()
    elif change == "industry":
        a["requested_industries"] = a["requested_industries"][:1]
    elif change == "omitted":
        a["items"].pop()
    elif change == "boolean":
        a["items"][0]["rank"] = True
    elif change == "reason":
        a["items"][0]["reason"] = "store_row_missing"
    elif change == "label":
        a["requested_industries"][0]["industry_name"] = "wrong"
    elif change == "top_mismatch":
        data["top_markets_estimate"]["total_sales"] = "1"
    else:
        data["per_store_average"] = None
    with pytest.raises(ValueError):
        SalesBlock.model_validate_json(json.dumps(data))


def test_empty_upstream_restaurant_still_reports_applied_selection():
    r = attach(
        FakeSession([]),
        SalesBlock(status="no_data", reason="source_not_loaded"),
        None,
        date(2025, 11, 30),
        "latest_reference",
        category="restaurant",
        requested_industries=tuple(
            INDUSTRIES[k] for k in ("korean", "chinese", "japanese", "western")
        ),
    )
    assert r.market_aggregation.status == "no_data"
    assert r.market_aggregation.reason == "source_not_loaded"
    assert len(r.market_aggregation.requested_industries) == 4
    assert r.market_aggregation.items == ()


def test_cafe_projection_is_null():
    r = attach(
        FakeSession([row("3110000", 10)]),
        SalesBlock(status="ready", items=(item("3110000", 100),)),
        SimpleNamespace(version_id="synthetic"),
        date(2025, 11, 30),
        "latest_reference",
        category="cafe",
    )
    assert r.market_aggregation is None


def test_actual_zero_with_positive_stores_remains_in_coverage_and_denominator():
    m = next(
        m for m in calculate(free=(2, 0)).market_aggregation.items if m.market_code == "3110002"
    )
    assert m.status == "ready" and len(m.included_industry_codes) == 4
    assert m.total_store_count == "120" and m.total_sales == "220000000"


def test_aggregate_dto_accepts_exact_sums_above_individual_source_int64():
    result = calculate(big=True)
    assert result.market_aggregation.items[0].total_sales == str(4 * (2**63 - 1))
    assert result.top_markets_estimate["total_sales"] == str(12 * (2**63 - 1))
