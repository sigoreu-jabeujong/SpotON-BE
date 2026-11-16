from datetime import date
from fractions import Fraction

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketArea, MarketSale, MarketSaleVersion, MarketStore, MarketStoreVersion
from app.schemas.location_reference import LocationCatalog, SalesCatalog
from app.services import location_reference as service
from etl.market_sales.archive import load_archive as load_sales
from etl.market_sales.repository import save as save_sales
from etl.market_stores.archive import TYPES
from etl.market_stores.archive import load_archive as load_stores
from etl.market_stores.repository import save as save_stores
from tests.etl.market_sale_helpers import annual_sales_rows, make_sales_zip
from tests.etl.market_store_helpers import annual_rows, make_stats_zip
from tests.integration.test_location_reference import fingerprint, reference_db, request  # noqa: F401
from tests.integration.test_nearby import batch, store

pytestmark = pytest.mark.integration


def test_actual_selected_industries_aggregate_before_ranking(reference_db, tmp_path, monkeypatch):  # noqa: F811
    engine, client, catalog, _ = reference_db
    with Session(engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "restaurant-clock", category="restaurant", sub_category="korean")
    counts = [[25, 20, 30, 25], [50, 20, 5, 5], [10, 10, 50, 50], [5, 10, 35, 40]]
    stores, sales = [], []
    with Session(engine) as session:
        areas = list(session.scalars(select(MarketArea).order_by(MarketArea.market_code).limit(4)))
        for m, area in enumerate(areas):
            for row in annual_rows():
                industry = row["svc_induty_cd"]
                n = 10 + m if industry == "CS100010" else counts[m][int(industry[-1]) - 1]
                row.update(
                    trdar_cd=area.market_code,
                    trdar_cd_nm=area.market_name,
                    trdar_se_cd=area.market_type_code,
                    trdar_se_cd_nm=TYPES[area.market_type_code],
                    stor_co=str(n),
                    similr_induty_stor_co=str(n),
                    frc_stor_co="0",
                )
                stores.append(row)
            for row in annual_sales_rows():
                industry = row["서비스_업종_코드"]
                n = 10 + m if industry == "CS100010" else counts[m][int(industry[-1]) - 1]
                row.update(
                    {
                        "상권_코드": area.market_code,
                        "상권_코드_명": area.market_name,
                        "상권_구분_코드": area.market_type_code,
                        "상권_구분_코드_명": TYPES[area.market_type_code],
                        "당월_매출_금액": str(n * (2000000 if m == 2 else 1000000)),
                    }
                )
                sales.append(row)
    store_path = tmp_path / "restaurant-stores.zip"
    store_sha = make_stats_zip(store_path, stores)
    store_archive = load_stores(
        store_path, store_sha, 2025, date(2026, 5, 21), today=date(2026, 11, 17)
    )
    boundary = catalog.sales.boundary
    with Session(engine) as session:
        from app.models import MarketAreaVersion

        boundary_id = session.scalar(
            select(MarketAreaVersion.version_id).where(
                MarketAreaVersion.content_sha256 == boundary.content_sha256
            )
        )
    with engine.begin() as c:
        store_id, _, _ = save_stores(c, store_archive, boundary_id)
    sale_path = tmp_path / "restaurant-sales.zip"
    sale_sha = make_sales_zip(sale_path, sales)
    sale_archive = load_sales(
        sale_path, sale_sha, 2025, date(2026, 5, 18), today=date(2026, 11, 17)
    )
    with engine.begin() as c:
        sale_id, _, _ = save_sales(c, sale_archive, boundary_id, store_id)
    with Session(engine) as session:
        new_catalog = LocationCatalog(
            sales=SalesCatalog(
                source_year=2025,
                boundary=boundary,
                stores=fingerprint(session.get(MarketStoreVersion, store_id)),
                sales=fingerprint(session.get(MarketSaleVersion, sale_id)),
            )
        )
    monkeypatch.setattr(service, "load_catalog", lambda: new_catalog)
    for sub, expected in [
        (None, ["3110002", "3110000", "3110003"]),
        ("korean,chinese", ["3110001", "3110000", "3110002"]),
    ]:
        changes = {"category": "restaurant"}
        if sub:
            changes["sub_category"] = sub
        data = request(client, **changes)["data"]["sales"]
        a = data["market_aggregation"]
        assert a["selected_market_codes"] == expected
        assert len([i for i in a["items"] if i["selected_for_estimate"]]) == 3
        requested = {i["industry_code"] for i in a["requested_industries"]}
        direct = {}
        with Session(engine) as session:
            for code in expected:
                ss = list(
                    session.scalars(
                        select(MarketSale).where(
                            MarketSale.version_id == sale_id,
                            MarketSale.market_code == code,
                            MarketSale.quarter == "20254",
                            MarketSale.induty_cd.in_(requested),
                        )
                    )
                )
                ns = list(
                    session.scalars(
                        select(MarketStore).where(
                            MarketStore.version_id == store_id,
                            MarketStore.market_code == code,
                            MarketStore.quarter == "20254",
                            MarketStore.induty_cd.in_(requested),
                        )
                    )
                )
                direct[code] = (sum(r.est_sales for r in ss), sum(r.total_stores for r in ns))
        for market in a["items"]:
            if market["market_code"] in direct:
                s, n = direct[market["market_code"]]
                assert (market["total_sales"], market["total_store_count"]) == (str(s), str(n))
        top = data["top_markets_estimate"]
        assert Fraction(
            int(top["metric"]["numerator"]), int(top["metric"]["denominator"])
        ) == Fraction(sum(v[0] for v in direct.values()), sum(v[1] for v in direct.values()))
    assert request(client)["data"]["sales"]["market_aggregation"] is None
    empty = request(client, category="restaurant", lat=0, lng=0)["data"]["sales"][
        "market_aggregation"
    ]
    assert empty["requested_industries"] and empty["status"] == "no_data"
