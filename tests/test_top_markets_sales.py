from copy import deepcopy

import pytest

from app.schemas.location_reference import SalesBlock
from tests.test_per_store_sales import calculate, item, row


def test_top_three_use_pooled_sales_over_pooled_stores_not_median_or_mean_of_means():
    result = calculate(
        [item("3110001", 1000), item("3110002", 600), item("3110003", 400), item("3110004", 9999)],
        [row("3110001", 100), row("3110002", 30), row("3110003", 20), row("3110004", 1)],
    )
    top = result.top_markets_estimate
    assert [m["market_code"] for m in top["markets"]] == ["3110001", "3110002", "3110003"]
    assert top["total_sales"] == "2000"
    assert top["total_store_count"] == "150"
    assert top["metric"]["numerator"] == "2000"
    assert top["metric"]["denominator"] == "150"
    assert top["eligible_market_count"] == 4
    assert top["status"] == "ready"
    assert result.per_store_average["total_sales"] == "11999"  # compatibility


def test_group_industries_before_ranking_and_break_ties_by_market_code():
    extra = item("3110003", 50).model_copy(update={"industry_code": "CS100001"})
    extra_row = row("3110003", 15)
    extra_row.induty_cd = "CS100001"
    result = calculate(
        [
            item("3110004", 400),
            item("3110003", 300),
            item("3110002", 200),
            item("3110001", 100),
            extra,
        ],
        [row("3110004", 20), row("3110003", 10), row("3110002", 20), row("3110001", 20), extra_row],
    )
    top = result.top_markets_estimate
    assert [m["market_code"] for m in top["markets"]] == ["3110003", "3110001", "3110002"]
    assert top["markets"][0]["industry_codes"] == ["CS100001", "CS100010"]
    assert (top["total_sales"], top["total_store_count"]) == ("650", "65")


def test_zero_sales_valid_missing_and_other_quarters_do_not_enter_sums():
    result = calculate(
        [item("3110001", 0), item("3110002", 900), item("3110003", 800, "20253")],
        [row("3110001", 50), row("3110003", 999, "20253")],
    )
    top = result.top_markets_estimate
    assert top["selected_market_count"] == 1
    assert top["metric"]["exact_zero"]
    assert top["total_store_count"] == "50"
    assert top["excluded_item_count"] == 1
    assert top["status"] == "partial"


def test_no_eligible_newest_market_never_uses_older_period():
    top = calculate(
        [item("3110001", 100), item("3110002", 999, "20253")],
        [row("3110002", 999, "20253")],
    ).top_markets_estimate
    assert top["source_quarter"] == "20254"
    assert top["metric"] is None and top["markets"] == []


@pytest.mark.parametrize(
    "field,value",
    [("total_sales", "1"), ("total_store_count", "999"), ("selected_market_count", 3)],
)
def test_schema_rejects_tampered_estimate(field, value):
    data = calculate([item("3110001", 100)], [row("3110001", 10)]).model_dump()
    data["top_markets_estimate"][field] = value
    with pytest.raises(ValueError, match="invalid top markets estimate"):
        SalesBlock.model_validate(data)


def test_schema_rejects_fabricated_source_name_and_omitted_selected_market():
    base = calculate([item("3110001", 100)], [row("3110001", 10)]).model_dump()
    for change in ("name", "members"):
        data = deepcopy(base)
        if change == "name":
            data["top_markets_estimate"]["markets"][0]["market_name"] = "fabricated"
        else:
            data["top_markets_estimate"]["markets"] = []
        with pytest.raises(ValueError, match="invalid top markets estimate"):
            SalesBlock.model_validate(data)


def test_mapping_conflict_zero_count_and_two_available_markets():
    wrong = row("3110003", 100)
    wrong.market_name = "conflict"
    result = calculate(
        [item("3110001", 100), item("3110002", 200), item("3110003", 999), item("3110004", 999)],
        [row("3110001", 10), row("3110002", 20), wrong, row("3110004", 0)],
    )
    top = result.top_markets_estimate
    assert (top["total_sales"], top["total_store_count"]) == ("300", "30")
    assert top["excluded_item_count"] == 2
    top = calculate(
        [item("3110001", 100), item("3110002", 200)], [row("3110001", 10), row("3110002", 20)]
    ).top_markets_estimate
    assert top["reason"] == "fewer_than_three_markets" and top["status"] == "partial"


def test_conflicting_market_names_exclude_entire_market_without_failing_response():
    extra = item("3110001", 200).model_copy(
        update={"industry_code": "CS100001", "market_name": "conflict"}
    )
    extra_row = row("3110001", 20)
    extra_row.induty_cd, extra_row.market_name = "CS100001", "conflict"
    top = calculate(
        [item("3110001", 100), extra, item("3110002", 300)],
        [row("3110001", 10), extra_row, row("3110002", 30)],
    ).top_markets_estimate
    assert [m["market_code"] for m in top["markets"]] == ["3110002"]
    assert top["excluded_item_count"] == 2


def test_analysis_period_and_large_exact_sums():
    top = calculate(
        [item("3110001", 2**63 - 1, "20234"), item("3110002", 1, "20234")],
        [row("3110001", 10, "20234"), row("3110002", 20, "20234")],
        mode="analysis_period",
    ).top_markets_estimate
    assert top["total_sales"] == str(2**63)
    assert top["source_quarter"] == "20234"


@pytest.mark.parametrize("change", ["rank", "industry", "metric", "method", "quarter", "boolean"])
def test_schema_rejects_selection_and_method_tampering(change):
    data = calculate(
        [item("3110001", 100), item("3110002", 200)], [row("3110001", 10), row("3110002", 20)]
    ).model_dump()
    top = data["top_markets_estimate"]
    if change == "rank":
        top["markets"].reverse()
    elif change == "industry":
        top["markets"][0]["industry_codes"] = ["CS100001"]
    elif change == "metric":
        top["metric"]["numerator"] = "1"
    elif change == "method":
        top["method"] = "median"
    elif change == "quarter":
        top["source_quarter"] = "20253"
    else:
        top["excluded_item_count"] = False
    with pytest.raises(ValueError, match="invalid top markets estimate"):
        SalesBlock.model_validate(data)
