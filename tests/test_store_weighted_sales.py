from fractions import Fraction
from statistics import median

import pytest

from app.services.store_weighted_sales import store_weighted_distribution


def exact(number):
    return Fraction(int(number["numerator"]), int(number["denominator"]))


def test_673_store_weights_change_the_reference_median_and_conserve_histogram_mass():
    result = store_weighted_distribution([(50000, 500), (20000, 100), (73000, 73)])
    assert result["total_store_count"] == "673"
    assert result["reference_count"] == 3
    assert exact(result["median"]) == 100
    assert exact(result["mean"]) == Fraction(143000, 673)
    assert sum(int(b["store_count"]) for b in result["bins"]) == 673
    assert result["bins"][-1]["store_count"] == "73"
    assert result["individual_store_sales_observed"] is False


@pytest.mark.parametrize(
    "pairs", [[(10, 2), (90, 2)], [(0, 3)], [(1, 3), (2, 2), (100, 1)], [(100, 10), (1000, 20)]]
)
def test_weighted_median_matches_small_expanded_model_and_exact_between_group_variance(pairs):
    result = store_weighted_distribution(pairs)
    values = [Fraction(s, n) for s, n in pairs for _ in range(n)]
    assert exact(result["median"]) == median(values)
    assert sum(int(b["store_count"]) for b in result["bins"]) == len(values)
    assert result == store_weighted_distribution(list(reversed(pairs)))


def test_known_variance_zero_single_bin_and_no_expansion_of_huge_counts():
    result = store_weighted_distribution([(0, 1), (40, 2)])
    # Weighted values [0,20,20], exact variance 800/9.
    assert result["variance"]["value"].startswith("88.888888")
    same = store_weighted_distribution([(0, 2**31 - 1)] * 500)
    assert same["variance"]["value"] == "0"
    assert len(same["bins"]) == 1
    assert same["bins"][0]["store_count"] == str(500 * (2**31 - 1))
    assert store_weighted_distribution([]) is None
    for pairs in [[(1, 0)], [(-1, 2)], [(True, 1)], [(1, 1)] * 501]:
        with pytest.raises(ValueError):
            store_weighted_distribution(pairs)
