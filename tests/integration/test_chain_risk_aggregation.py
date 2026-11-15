"""Optimized city aggregates equal the original row predicate, including stale inputs."""

from datetime import date
from itertools import product

import pytest
from sqlalchemy import cast, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Store
from app.models.store import STORE_GEOGRAPHY
from app.schemas.chains import ChainRiskQuery
from app.schemas.risk import RiskQuery
from app.services.chains import ChainSelection
from app.services.risk import aggregate_counts, get_risk, reference_indicators
from app.services.spatial_stores import PREFILTER_MARGIN_M, attribute_filters
from app.services.store_cohort import temporal_cohort
from tests.integration.test_chain_publication import prepared
from tests.integration.test_nearby import LAT, LNG, batch, store
from tests.integration.test_store_migration import migrate

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("state", ["pending", "published", "changed"])
def test_chain_city_aggregates_match_original_predicate(temporary_database, monkeypatch, state):
    db = temporary_database
    migrate(db, "head")
    with Session(db.engine) as s, s.begin():
        b = batch(s)
        store(s, b, "chain", name="본죽", open_date=date(2024, 11, 11))
        store(s, b, "closed", name="본죽", status="closed", close_date=date(2026, 10, 1))
        store(s, b, "no-coordinate", name="본죽", distance=None, area_m2=None)
        store(s, b, "unknown", name="동네식당", area_m2=120)
        store(s, b, "unknown-no-coordinate", name="동네식당", distance=None, area_m2=None)
        store(s, b, "outside", name="본죽", distance=5000, area_m2=120)
        store(s, b, "coffee", name="스타벅스", category="cafe", sub_category="cafe")
        store(s, b, "coffee-unknown", name="동네커피", category="cafe", sub_category="cafe")
    if state != "pending":
        prepared(db, monkeypatch)
    if state == "changed":
        with db.engine.begin() as c:
            c.execute(update(Store).where(Store.license_no == "chain").values(floor_unit="2층"))
    target = date(2026, 11, 10)
    with Session(db.engine) as s:
        for category, scope, unknown, evidence, area_unknown in product(
            ("cafe", "restaurant"),
            ("all", "chain", "non_chain"),
            ("include", "exclude"),
            ("include_estimates", "confirmed_only"),
            (("all", True), ("gte99", False)),
        ):
            area, include_unknown_area = area_unknown
            q = ChainRiskQuery(
                lat=LAT,
                lng=LNG,
                category=category,
                radius=500,
                brand_scope=scope,
                brand_unknown=unknown,
                brand_evidence=evidence,
                area=area,
                include_unknown_area=include_unknown_area,
            )
            chain = ChainSelection.load(s, q)
            legacy = q.legacy(RiskQuery)
            conditions = [
                *temporal_cohort(legacy, target),
                *attribute_filters(legacy, chain),
                Store.open_date <= target,
            ]
            located = [*conditions, Store.geom.is_not(None)]
            point = cast(func.ST_SetSRID(func.ST_MakePoint(LNG, LAT), 4326), STORE_GEOGRAPHY)
            geography = cast(Store.geom, STORE_GEOGRAPHY)
            expected_city = aggregate_counts(s, located, target)
            expected_local = aggregate_counts(
                s,
                [
                    *located,
                    func.ST_DWithin(geography, point, 500 + PREFILTER_MARGIN_M, True),
                    func.ST_Distance(geography, point, True) <= 500,
                ],
                target,
            )
            expected_missing = s.scalar(
                select(func.count())
                .select_from(Store)
                .where(
                    *conditions,
                    Store.geom.is_(None),
                )
            )
            actual = get_risk(s, legacy, Settings(_env_file=None), chain=chain)
            assert actual.data is not None
            assert actual.data.indicators == reference_indicators(
                expected_local, expected_city, target, 500
            )
            assert actual.meta is not None
            assert actual.meta["excluded_no_coord"] == expected_missing
