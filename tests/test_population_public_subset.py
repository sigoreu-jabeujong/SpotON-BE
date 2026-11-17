from dataclasses import replace
from decimal import Decimal, Inexact, localcontext

import pytest

from app.analysis.population_public_subset import PublicRow, assemble_public_subset

G = "가가00000000"
OTHER = "가가00000001"
UNLOCATED = {"local": (24, 1), "long": (0, 0), "short": (0, 0)}


def rows(source="local", grid=G, admin="11110530", day="2", night="1"):
    return tuple(
        PublicRow(source, grid, admin, h, "observed", Decimal(day if 6 <= h < 18 else night))
        for h in range(24)
    )


def assemble(data, grids=frozenset({G, OTHER})):
    return assemble_public_subset(grids, tuple(data), UNLOCATED, grid_as_of_known=False)


def test_partial_is_source_independent_and_never_claims_population_completeness():
    result = assemble(rows())
    domestic, long, short = result
    assert tuple(x.source for x in result) == ("local", "long", "short")
    assert domestic.status == "partial" and domestic.reason == "public_subset_only"
    assert long.reason == short.reason == "no_source_rows"
    assert long.values is short.values is None
    assert domestic.quality.used_component_count == 1
    assert domestic.quality.grids_without_rows == 1
    assert domestic.quality.version_unlocated_rows == 24
    assert "not_population_total" in domestic.limitations
    assert "grid_as_of_unknown" in domestic.limitations
    assert domestic.values.day_night_ratio.value == "2.00000"
    assert domestic.values.day_share_pct.value == "66.7"
    assert domestic.values.night_share_pct.value == "33.3"
    assert domestic.values.day_source_mean.display == "2.00000"
    assert "명" not in domestic.model_dump_json()


def test_one_suppressed_hour_excludes_only_its_component_for_all_24_hours():
    good = rows()
    bad = list(rows(admin="11110540", day="999", night="99"))
    bad[7] = replace(bad[7], status="suppressed", population=None)
    domestic = assemble(good + tuple(bad))[0]
    assert domestic.values.day_night_ratio.value == "2.00000"
    assert domestic.values.hourly_source_sums[7].value == "2.00000"
    assert domestic.values.hourly_source_sums[0].value == "1.00000"
    q = domestic.quality
    assert (q.candidate_component_count, q.used_component_count, q.excluded_component_count) == (
        2,
        1,
        1,
    )
    assert (q.suppressed_rows, q.absent_hours_within_candidates) == (1, 0)
    assert q.excluded_by_hour_class.day_only == 1
    assert "exclusion_pattern_may_bias_ratio" in domestic.limitations


def test_missing_cell_absent_hour_and_source_are_not_zero_or_cross_source_fallback():
    a = list(rows())
    a[0] = replace(a[0], status="missing", population=None)
    del a[12]
    domestic, foreign, _ = assemble(tuple(a) + rows("long"))
    assert domestic.reason == "no_common_public_components" and domestic.values is None
    assert domestic.quality.missing_rows == 1
    assert domestic.quality.absent_hours_within_candidates == 1
    assert domestic.quality.excluded_by_hour_class.both == 1
    assert foreign.status == "partial"
    assert foreign.values.day_night_ratio.value == "2.00000"


def test_time_varying_available_rows_do_not_manufacture_a_day_night_ratio():
    only_day = tuple(r for r in rows() if 6 <= r.hour < 18)
    only_night = tuple(r for r in rows(admin="11110540") if not 6 <= r.hour < 18)
    domestic = assemble(only_day + only_night)[0]
    assert domestic.values is None
    assert domestic.quality.used_component_count == 0
    assert domestic.quality.excluded_by_hour_class.day_only == 1
    assert domestic.quality.excluded_by_hour_class.night_only == 1
    assert domestic.quality.absent_hours_within_candidates == 24


def test_empty_selection_and_whole_day_absent_are_not_fabricated_components():
    empty = assemble((), frozenset())
    assert all(x.reason == "no_selected_grids" and x.values is None for x in empty)
    empty = assemble(())
    assert all(x.reason == "no_source_rows" for x in empty)
    assert all(x.quality.candidate_component_count == 0 for x in empty)
    assert all(x.quality.absent_hours_within_candidates == 0 for x in empty)


@pytest.mark.parametrize(
    "day,night,share,ratio,reason",
    [
        ("0", "1", "0.0", "0.00000", None),
        ("1", "0", "100.0", None, "zero_night_denominator"),
        ("0", "0", None, None, "zero_night_denominator"),
    ],
)
def test_real_zero_and_zero_denominator(day, night, share, ratio, reason):
    value = assemble(rows(day=day, night=night))[0].values
    assert value.day_share_pct.value == share
    assert value.day_night_ratio.value == ratio
    assert value.day_night_ratio.reason == reason
    if share is None:
        assert value.day_share_pct.reason == "zero_total"
        assert value.day_share_pct.exact_zero is None
    assert value.night_source_sum.exact_zero == (night == "0")


def test_small_positive_rounded_zero_is_not_an_exact_zero():
    value = assemble(rows(day="0.00001", night="100000"))[0].values
    ratio = value.day_night_ratio
    assert ratio.value == "0.00000" and ratio.rounded and not ratio.exact_zero
    assert ratio.reason is None and value.day_share_pct.value == "0.0"


def test_positive_night_rounded_share_zero_retains_nonzero_denominator():
    value = assemble(rows(day="999999999999999.99999", night="0.00001"))[0].values
    assert value.day_share_pct.value == "100.0"
    assert value.night_share_pct.value == "0.0"
    assert not value.night_share_pct.exact_zero and value.night_share_pct.rounded
    assert value.day_night_ratio.reason is None and value.day_night_ratio.value is not None


def test_rounding_flags_are_per_number_and_shares_use_complement_on_ties():
    data = list(rows(day="0", night="0"))
    data[6] = replace(data[6], population=Decimal("0.00001"))
    data[0] = replace(data[0], population=Decimal("0.00012"))
    value = assemble(data)[0].values
    assert value.day_source_mean.rounded and not value.night_source_mean.rounded
    # 1/(1+15) = 6.25%: round day to 6.3, use its complement 93.7, not 93.8.
    value = assemble(rows(day="1", night="15"))[0].values
    assert value.day_share_pct.value == "6.3" and value.night_share_pct.value == "93.7"
    assert value.day_share_pct.rounded and value.night_share_pct.rounded


def test_global_decimal_context_and_row_order_cannot_change_the_result():
    data = rows(day="2.12345", night="1.00001")
    expected = assemble(data)
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert assemble(tuple(reversed(data))) == expected


def test_hour_overflow_is_per_source_but_large_day_sum_is_supported():
    high = rows(day="999999999999999.99999", night="1")
    value = assemble(high)[0].values
    assert value.day_source_sum.value == "11999999999999999.99988"
    domestic, long, _ = assemble(high + rows(admin="11110540") + rows("long"))
    assert domestic.reason == "numeric_scope_too_large" and domestic.values is None
    assert long.status == "partial"


@pytest.mark.parametrize(
    "change",
    [
        {"population": Decimal("NaN")},
        {"population": Decimal("Infinity")},
        {"population": Decimal("-1")},
        {"population": Decimal("1.000001")},
        {"population": Decimal("1e15")},
        {"population": None},
        {"status": "suppressed", "population": Decimal("1")},
        {"status": "other"},
        {"hour": True},
        {"hour": 24},
        {"source": "unexpected"},
        {"grid_id": "다사12345678"},
        {"admin_code": "canary"},
    ],
)
def test_malformed_rows_raise_fixed_errors_instead_of_becoming_partial(change):
    data = list(rows())
    data[0] = replace(data[0], **change)
    with pytest.raises(ValueError, match="population_public_subset_invalid"):
        assemble(data)


def test_duplicate_rows_are_rejected_and_source_components_are_not_deduplicated_by_grid():
    with pytest.raises(ValueError, match="population_public_subset_invalid"):
        assemble(rows() + rows())
    value = assemble(rows() + rows(admin="11110540", day="4", night="2"))[0]
    assert value.quality.used_component_count == 2 and value.quality.used_grid_count == 1
    assert value.values.day_source_sum.value == "72.00000"
    assert value.values.day_night_ratio.value == "2.00000"
