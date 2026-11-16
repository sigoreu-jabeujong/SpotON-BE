from fractions import Fraction

import pytest

from app.services.sales_distribution import distribution


def test_median_is_not_weighted_mean_or_median_of_totals():
    result = distribution([(100, 10), (20000, 1000), (900000, 1000)])
    assert result["median"]["value"] == "20"
    assert result["sample_count"] == 3
    assert result["individual_store_median"] is False
    assert result["outliers_removed"] is False


@pytest.mark.parametrize(
    "pairs,expected",
    [
        ([], None),
        ([(0, 1)], Fraction(0)),
        ([(1, 3), (1, 2)], Fraction(5, 12)),
        ([(0, 1), (10, 1), (20, 1), (100000, 1)], Fraction(15)),
    ],
)
def test_empty_small_even_and_zero(pairs, expected):
    result = distribution(pairs)
    if expected is None:
        assert result is None
    else:
        m = result["median"]
        assert Fraction(int(m["numerator"]), int(m["denominator"])) == expected
        assert m["exact_zero"] == (expected == 0)


def test_quartiles_population_variance_and_order_independence():
    pairs = [(1, 1), (2, 1), (3, 1), (4, 1)]
    result = distribution(pairs)
    assert result == distribution(list(reversed(pairs)))
    assert result["q1"]["value"] == "1.5"
    assert result["q3"]["value"] == "3.5"
    assert result["iqr"]["value"] == "2"
    assert result["variance"]["value"] == "1.25"
    assert result["limited_reference_count"] is False


def test_exact_large_fraction_sorting_and_input_guards():
    identical = distribution([(1, 3), (2, 6), (3, 9)] * 7)
    assert identical["variance"]["value"] == "0"
    pairs = [(2**63 - 1, 2**31 - 1), (2**63 - 2, 2**31 - 2)]
    result = distribution(pairs)
    expected = sum((Fraction(s, n) for s, n in pairs), Fraction(0)) / 2
    assert (
        Fraction(int(result["median"]["numerator"]), int(result["median"]["denominator"]))
        == expected
    )
    for invalid in [[(1, 0)], [(-1, 1)], [(True, 1)], [(1, 1)] * 501]:
        with pytest.raises(ValueError):
            distribution(invalid)


@pytest.mark.parametrize("values,q1,q3", [([1, 2, 3], "1", "3"), ([1, 2, 3, 4, 5], "1.5", "4.5")])
def test_odd_quartiles_exclude_middle(values, q1, q3):
    result = distribution([(v, 1) for v in values])
    assert result["q1"]["value"] == q1
    assert result["q3"]["value"] == q3


def test_small_sample_and_display_boundaries():
    result = distribution([(0, 1), (1, 1)])
    assert result["limited_reference_count"] is True
    assert result["median"]["display"] == "1원 미만/점포"
    assert result["q1"]["value"] == "0" and result["q3"]["value"] == "1"
    assert distribution([(1, 1), (2, 1)])["median"]["display"] == "2원/점포"
