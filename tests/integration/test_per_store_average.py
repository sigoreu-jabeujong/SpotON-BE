from decimal import Decimal, localcontext
from fractions import Fraction
from statistics import median

import pytest
from sqlalchemy import select, update

from app.models import MarketArea, MarketStore
from tests.integration.test_location_reference import reference_db, request  # noqa: F401

pytestmark = pytest.mark.integration


def test_actual_api_store_join_and_weighted_summary(reference_db):  # noqa: F811
    engine, client, catalog, _ = reference_db
    # The legacy fixture intentionally uses a different store label; reject it first.
    assert request(client)["data"]["sales"]["per_store_average"]["metric"] is None
    with engine.begin() as c:
        c.execute(
            update(MarketStore).values(
                market_name=select(MarketArea.market_name)
                .where(MarketArea.market_code == MarketStore.market_code)
                .scalar_subquery()
            )
        )
    body = request(client)
    sales = body["data"]["sales"]
    avg = sales["per_store_average"]
    included = [i for i in sales["items"] if i["average_contribution"]["status"] == "included"]
    assert included
    markets = {}
    s = n = 0
    with engine.connect() as c:
        for item in included:
            count = c.scalar(
                select(MarketStore.total_stores).where(
                    MarketStore.market_code == item["market_code"],
                    MarketStore.quarter == item["source_quarter"],
                    MarketStore.induty_cd == item["industry_code"],
                )
            )
            assert int(item["store_reference"]["total_stores"]) == count
            pair = markets.setdefault(item["market_code"], [0, 0])
            pair[0] += int(item["metric"]["value"])
            pair[1] += count
            s += int(item["metric"]["value"])
            n += count
    codes = sorted(markets, key=lambda code: (-markets[code][1], code))[:3]
    top = sales["top_markets_estimate"]
    assert [m["market_code"] for m in top["markets"]] == codes
    assert top["total_sales"] == str(sum(markets[c][0] for c in codes))
    assert top["total_store_count"] == str(sum(markets[c][1] for c in codes))
    assert Fraction(int(top["metric"]["numerator"]), int(top["metric"]["denominator"])) == Fraction(
        int(top["total_sales"]), int(top["total_store_count"])
    )
    assert all(
        m["market_name"]
        == next(i["market_name"] for i in included if i["market_code"] == m["market_code"])
        for m in top["markets"]
    )
    assert avg["total_sales"] == str(s) and avg["total_store_count"] == str(n)
    with localcontext() as ctx:
        ctx.prec = 50
        assert Decimal(avg["metric"]["value"]) == Decimal(s) / n
    assert avg["unique_store_average"] is False
    expected = median(
        [
            Fraction(int(i["metric"]["value"]), int(i["store_reference"]["total_stores"]))
            for i in included
        ]
    )
    actual = avg["distribution"]["median"]
    assert Fraction(int(actual["numerator"]), int(actual["denominator"])) == expected
    assert avg["distribution"]["sample_count"] == len(included)
    assert avg["representative_method"] == "store_weighted_median_v1"
    assert len(avg["contributions"]) == len(included)
    weighted = avg["store_weighted_distribution"]
    assert weighted["total_store_count"] == str(n)
    assert sum(int(b["store_count"]) for b in weighted["bins"]) == n
    assert weighted["reference_count"] == len(included)
    from bisect import bisect_left
    from itertools import accumulate

    weighted_pairs = sorted(
        (
            Fraction(int(i["metric"]["value"]), int(i["store_reference"]["total_stores"])),
            int(i["store_reference"]["total_stores"]),
        )
        for i in included
    )
    cumulative = list(accumulate(weight for _, weight in weighted_pairs))
    expected_weighted = (
        weighted_pairs[bisect_left(cumulative, (n + 1) // 2)][0]
        + weighted_pairs[bisect_left(cumulative, n // 2 + 1)][0]
    ) / 2
    m = weighted["median"]
    assert Fraction(int(m["numerator"]), int(m["denominator"])) == expected_weighted
    assert all(c["metric"]["denominator"] == str(n) for c in avg["contributions"])
    assert sum(
        (
            Fraction(int(c["metric"]["numerator"]), int(c["metric"]["denominator"]))
            for c in avg["contributions"]
        ),
        Fraction(0),
    ) == Fraction(s, n)
    assert body["meta"]["items_additive"] is False
    assert any(r["id"] == "store-counts" for r in body["meta"]["source_refs"])
