from datetime import date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.analysis.market_reference import (
    ChangeSource,
    SalesSource,
    project_change,
    project_sales,
    select_quarter,
)

BASE = dict(
    version_id=UUID(int=1), boundary_version_id=UUID(int=2), quarter="20254", market_code="3110001"
)


@pytest.mark.parametrize(
    "target,current,periods,wanted",
    [
        (date(2026, 1, 1), True, ("20254", "20251"), "20254"),
        (date(2026, 1, 1), False, ("20254",), None),
        (date(2025, 3, 31), False, ("20251", "20252"), "20251"),
        (date(2025, 4, 1), False, ("20251", "20252"), "20252"),
        (date(2025, 12, 31), True, ("20261",), None),
        (date(2025, 1, 1), True, (), None),
    ],
)
def test_periods_do_not_mix_history_future_or_adjacent_quarters(target, current, periods, wanted):
    assert select_quarter(target, periods, current=current) == wanted


@pytest.mark.parametrize(
    "changes",
    [
        dict(target=datetime(2025, 1, 1)),
        dict(target=date(1999, 12, 31)),
        dict(current=1),
        dict(verified_periods=["20251"]),
        dict(verified_periods=("20251", "20251")),
        dict(verified_periods=("20250",)),
        dict(verified_periods=("20255",)),
        dict(verified_periods=(20251,)),
        dict(verified_periods=("20251\n",)),
    ],
)
def test_invalid_period_arguments_are_fixed_errors(changes):
    arguments = dict(target=date(2025, 1, 1), current=True, verified_periods=("20251",)) | changes
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        select_quarter(**arguments)


@pytest.mark.parametrize(
    "amount,count,status",
    [
        (0, 0, "available"),
        (101, 7, "available"),
        (None, 0, "partial"),
        (0, None, "partial"),
        (None, None, "no_data"),
    ],
)
def test_sales_preserve_source_values_and_do_not_apply_store_filters(amount, count, status):
    row = SalesSource(**BASE, industry_code="CS100001", est_sales=amount, source_sales_count=count)
    result = project_sales(row, selected_quarter="20254", period_basis="monthly_average")
    assert result.status == status and result.row_present
    assert result.source.est_sales == amount and result.source.source_sales_count == count
    assert result.period_basis == "monthly_average" and result.currency == "KRW"
    assert result.space == "market_industry"
    assert not result.brand_filter_applied and not result.license_filters_applied
    assert not result.source_validation_performed and not result.public_activation_ready


def test_absent_sales_row_remains_distinct_from_null_values():
    result = project_sales(None, selected_quarter=None, period_basis="quarter_total")
    assert result.status == "no_data" and not result.row_present and result.source is None
    assert result.quarter is None


@pytest.mark.parametrize(
    "changes",
    [
        dict(est_sales=True),
        dict(est_sales=-1),
        dict(est_sales=2**63),
        dict(source_sales_count="3"),
        dict(industry_code="CS100005"),
    ],
)
def test_sales_strict_numbers_and_supported_industries(changes):
    with pytest.raises(ValidationError):
        SalesSource(
            **(BASE | dict(industry_code="CS100001", est_sales=10, source_sales_count=1) | changes)
        )


def test_projection_rejects_mixed_periods_and_invented_basis():
    row = SalesSource(**BASE, industry_code="CS100010", est_sales=1, source_sales_count=1)
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        project_sales(row, selected_quarter="20253", period_basis="quarter_total")
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        project_sales(row, selected_quarter="20254", period_basis="unknown")


@pytest.mark.parametrize(
    "code,name", [("LL", "다이나믹"), ("LH", "상권확장"), ("HL", "상권축소"), ("HH", "정체")]
)
def test_change_is_typed_market_wide_source_data_not_score(code, name):
    row = ChangeSource(
        **BASE,
        change_code=code,
        change_name=name,
        operating_months_avg=0,
        closed_months_avg=None,
        seoul_operating_months_avg=22,
        seoul_closed_months_avg=31,
    )
    result = project_change(row, selected_quarter="20254")
    assert result.status == "available" and result.source == row
    assert result.space == "market_all_industries" and not result.brand_filter_applied
    assert result.source.operating_months_avg == 0 and result.source.closed_months_avg is None
    assert not result.public_activation_ready and not result.source_validation_performed
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        project_change(row, selected_quarter="20251")


@pytest.mark.parametrize("basis", [None, True, 1, [], {}])
def test_missing_or_wrong_basis_has_no_implicit_default(basis):
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        project_sales(None, selected_quarter=None, period_basis=basis)


def test_change_absence_and_wrong_code_label():
    assert project_change(None, selected_quarter="20254").status == "no_data"
    with pytest.raises(ValidationError):
        ChangeSource(
            **BASE,
            change_code="LL",
            change_name="상권확장",
            operating_months_avg=None,
            closed_months_avg=None,
            seoul_operating_months_avg=None,
            seoul_closed_months_avg=None,
        )


@pytest.mark.parametrize(
    "month", [None, date(2025, 9, 1), date(2025, 12, 2), datetime(2025, 12, 1), "2025-12"]
)
def test_specific_month_requires_first_of_month_in_selected_quarter(month):
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        project_sales(
            None, selected_quarter="20254", period_basis="specific_month", source_month=month
        )


def test_specific_month_is_preserved_and_not_invented_for_other_bases():
    row = SalesSource(**BASE, industry_code="CS100001", est_sales=123, source_sales_count=1)
    result = project_sales(
        row, selected_quarter="20254", period_basis="specific_month", source_month=date(2025, 11, 1)
    )
    assert result.source_month == date(2025, 11, 1) and result.source.est_sales == 123
    assert repr(row) == "SalesSource()"
    with pytest.raises(ValueError, match="^market_reference_invalid$"):
        project_sales(
            row,
            selected_quarter="20254",
            period_basis="quarter_total",
            source_month=date(2025, 11, 1),
        )
