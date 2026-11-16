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


def test_distribution_uses_only_same_quarter_valid_pairs():
    result = calculate(
        [item("3110001", 100), item("3110002", 900), item("3110003", 2000, "20253")],
        [row("3110001", 10), row("3110003", 20, "20253")],
    )
    avg = result.per_store_average
    assert avg["distribution"]["median"]["value"] == "10"
    assert avg["distribution"]["sample_count"] == avg["included_item_count"] == 1
    assert avg["groups"][1]["distribution"]["median"]["value"] == "100"
    assert avg["groups"][1]["distribution"]["sample_count"] == 1


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_reference",
        "no_data_reference",
        "per_store",
        "contribution",
        "median",
        "projection",
        "sample_count",
    ],
)
def test_rejects_corrupted_distribution_members_and_projection(tamper):
    from pydantic import ValidationError

    result = calculate([item("3110001", 100)], [row("3110001", 10)])
    payload = result.model_dump()
    avg = payload["per_store_average"]
    if tamper == "missing_reference":
        payload["items"][0]["store_reference"] = None
    elif tamper == "no_data_reference":
        payload["items"][0]["store_reference"].update(status="no_data", total_stores=None)
    elif tamper == "per_store":
        payload["items"][0]["per_store_metric"] = metric(200, 10)
    elif tamper == "contribution":
        payload["items"][0]["average_contribution"]["status"] = "excluded"
    elif tamper == "median":
        avg["groups"][0]["distribution"]["median"]["value"] = "999"
    elif tamper == "sample_count":
        avg["groups"][0]["distribution"]["sample_count"] = 0
    else:
        avg["distribution"] = None
    with pytest.raises(ValidationError):
        SalesBlock.model_validate(payload)


def test_previous_weighted_payload_remains_readable():
    payload = calculate([item("3110001", 100)], [row("3110001", 10)]).model_dump()
    avg = payload["per_store_average"]
    avg.pop("distribution")
    avg.pop("representative_method")
    for group in avg["groups"]:
        group.pop("distribution")
    assert SalesBlock.model_validate(payload).per_store_average["metric"]["value"] == "10"


@pytest.mark.parametrize(
    "tamper",
    [
        "partial_legacy",
        "missing_distribution",
        "missing_group",
        "duplicate_group",
        "other_contribution",
        "candidate_count",
    ],
)
def test_rejects_group_format_and_quarter_inconsistency(tamper):
    from pydantic import ValidationError

    payload = calculate(
        [item("3110001", 100), item("3110002", 900, "20253")],
        [row("3110001", 10), row("3110002", 30, "20253")],
    ).model_dump()
    avg = payload["per_store_average"]
    if tamper == "partial_legacy":
        avg.pop("distribution")
        avg.pop("representative_method")
    elif tamper == "missing_distribution":
        avg["groups"][0].pop("distribution")
    elif tamper == "missing_group":
        avg["groups"].pop()
    elif tamper == "duplicate_group":
        avg["groups"].append(avg["groups"][0])
    elif tamper == "other_contribution":
        payload["items"][1]["average_contribution"]["status"] = "included"
    else:
        avg["groups"][0]["candidate_item_count"] = 2
        avg["groups"][0]["excluded_counts"] = {"store_row_missing": 1}
    with pytest.raises(ValidationError):
        SalesBlock.model_validate(payload)


def test_cannot_drop_valid_member_and_recompute_representative():
    from pydantic import ValidationError

    payload = calculate([item("3110001", 100)], [row("3110001", 10)]).model_dump()
    full = calculate(
        [item("3110001", 100), item("3110002", 900)],
        [row("3110001", 10), row("3110002", 30)],
    ).model_dump()
    payload["items"] = full["items"]
    payload["items"][1]["average_contribution"].update(
        status="excluded", reason="store_row_missing"
    )
    avg = payload["per_store_average"]
    avg.update(listed_item_count=2, excluded_counts={"store_row_missing": 1})
    avg["groups"][0].update(candidate_item_count=2, excluded_counts={"store_row_missing": 1})
    with pytest.raises(ValidationError):
        SalesBlock.model_validate(payload)
