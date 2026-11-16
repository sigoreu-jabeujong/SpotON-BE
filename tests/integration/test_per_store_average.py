from decimal import Decimal, localcontext

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
        name = c.scalar(select(MarketArea.market_name).where(MarketArea.market_code == "3110000"))
        c.execute(update(MarketStore).values(market_name=name))
    body = request(client)
    sales = body["data"]["sales"]
    avg = sales["per_store_average"]
    included = [i for i in sales["items"] if i["average_contribution"]["status"] == "included"]
    assert included
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
            s += int(item["metric"]["value"])
            n += count
    assert avg["total_sales"] == str(s) and avg["total_store_count"] == str(n)
    with localcontext() as ctx:
        ctx.prec = 50
        assert Decimal(avg["metric"]["value"]) == Decimal(s) / n
    assert avg["unique_store_average"] is False
    assert body["meta"]["items_additive"] is False
    assert any(r["id"] == "store-counts" for r in body["meta"]["source_refs"])
