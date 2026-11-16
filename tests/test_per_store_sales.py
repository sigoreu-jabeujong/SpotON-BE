from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.location_reference import SalesBlock, SalesItem, SourceNumber
from app.services.per_store_sales import attach, metric


@pytest.mark.parametrize(
    "s,n,display",
    [
        (1, 3, "1원 미만/점포"),
        (1, 2, "1원 미만/점포"),
        (3, 2, "2원/점포"),
        (0, 3, "0원/점포"),
        (10000000, 40, "250,000원/점포"),
    ],
)
def test_exact_rounding(s, n, display):
    value = metric(s, n)
    assert value["display"] == display
    assert value["exact_zero"] == (s == 0)
    assert value["rounded"] == (s % n != 0)
    assert "E" not in value["value"]


def test_large_sum_and_invalid_inputs():
    assert metric(2**64, 2)["numerator"] == str(2**64)
    for s, n in [(-1, 1), (1, 0), (True, 1), (1, -1)]:
        with pytest.raises(ValueError):
            metric(s, n)


def item(code, amount, quarter="20254"):
    return SalesItem(
        market_code=code,
        market_name=code,
        market_type="alley",
        spatial_relation="contains_point",
        industry_code="CS100010",
        industry_name="커피-음료",
        source_quarter=quarter,
        metric=SourceNumber(value=str(amount), display=f"{amount:,}원", exact_zero=amount == 0),
        status="ready",
        selection_reason="latest_numeric_row",
    )


def row(code, count, quarter="20254"):
    return SimpleNamespace(
        market_code=code,
        quarter=quarter,
        induty_cd="CS100010",
        market_name=code,
        market_type_code="A",
        induty_name="커피-음료",
        total_stores=count,
        general_stores=count,
        franchise_stores=0,
    )


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, statement):
        return self.rows


def calculate(items, rows, mode="latest_reference"):
    return attach(
        FakeSession(rows),
        SalesBlock(status="ready", items=tuple(items)),
        SimpleNamespace(version_id="synthetic"),
        date(2023, 11, 30),
        mode,
    )


def test_weighted_average_and_mixed_periods():
    result = calculate(
        [item("3110001", 1000000), item("3110002", 9000000)],
        [row("3110001", 10), row("3110002", 30)],
    )
    assert result.per_store_average["metric"]["value"] == "250000"
    result = calculate(
        [item("3110001", 1000000), item("3110002", 9000000, "20253")],
        [row("3110001", 10), row("3110002", 30, "20253")],
    )
    assert result.per_store_average["metric"]["value"] == "100000"
    assert result.per_store_average["status"] == "partial"
    assert len(result.per_store_average["groups"]) == 2


def test_missing_newest_count_never_switches_to_older_quarter():
    result = calculate(
        [item("3110001", 100), item("3110002", 900, "20253")], [row("3110002", 30, "20253")]
    )
    assert result.per_store_average["primary_quarter"] == "20254"
    assert result.per_store_average["metric"] is None
    assert result.per_store_average["total_sales"] is None


def test_zero_and_conflicting_counts_do_not_enter_either_sum():
    wrong = row("3110002", 20)
    wrong.market_name = "conflict"
    result = calculate([item("3110001", 100), item("3110002", 900)], [row("3110001", 0), wrong])
    assert result.per_store_average["metric"] is None
    assert result.items[0].store_reference["total_stores"] == "0"
    assert result.items[1].store_reference["total_stores"] is None


def test_empty_upstream_and_duplicate_items():
    result = attach(
        FakeSession([]),
        SalesBlock(status="no_data", reason="source_not_loaded"),
        None,
        date(2023, 11, 30),
        "analysis_period",
    )
    assert result.per_store_average["primary_quarter"] == "20234"
    assert result.per_store_average["reason"] == "source_not_loaded"
    with pytest.raises(ValueError):
        calculate([item("3110001", 100)] * 2, [])
