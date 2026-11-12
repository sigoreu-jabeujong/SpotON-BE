from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.context import prepare_risk_interpretation
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.market_activity import ActivityQuery
from app.schemas.risk import RiskQuery
from app.services.market_activity import get_activity
from app.services.risk import get_risk
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_market_judgement import area, version
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def db(temporary_database):
    migrate(temporary_database)
    return temporary_database.engine


def seed(db):
    with Session(db) as s, s.begin():
        b = batch(s, data_updated_at=date(2026, 11, 8))
        for i in range(10):
            store(s, b, f"context{i}", open_date=date(2025, 1, 1))
        store(
            s,
            b,
            "historical",
            open_date=date(2010, 1, 1),
            close_date=date(2018, 1, 1),
            status="closed",
        )


def test_server_recalculation_and_real_readonly_context_match(db):
    seed(db)
    q = RiskQuery(**PARAMS, include="day_night_ratio,market_change")
    config = Settings(_env_file=None)
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        actual = get_risk(s, q, config)
        activity = get_activity(s, ActivityQuery(**PARAMS))
        prepared = prepare_risk_interpretation(s, q, config)
        assert s.scalar(text("SHOW transaction_read_only")) == "on"
        assert s.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        for before, after in zip(actual.data.indicators, prepared.context.indicators, strict=True):
            assert before.value == after.value and before.denominator == after.denominator
            assert before.source == list(after.source) and before.status == after.status
    context = prepared.context.activity
    assert context.recent_period == activity.data.recent_12m.period
    assert (context.recent_opened, context.recent_closed) == (
        activity.data.recent_12m.opened,
        activity.data.recent_12m.closed,
    )
    expected = sorted(
        (g.sub_category, g.open_count, g.avg_operating_months)
        for g in activity.data.by_sub_category
    )
    assert [(g.sub_category, g.open_count, g.avg_operating_months) for g in context.groups] == (
        expected
    )
    assert sum(g.open_count for g in context.groups) == actual.data.indicators[5].value == 10
    assert prepared.context.as_of == date(2026, 11, 8)
    assert prepared.context.market_status == "unverified"
    assert "stores_batch_ids" not in prepared.request.user_content


def test_named_boundary_candidate_and_uuid_never_enter_context(db):
    seed(db)
    with db.begin() as c:
        vid = version(c, 1)
        area(
            c,
            vid,
            wkt=(
                "MULTIPOLYGON(((126.97 37.56,126.99 37.56,126.99 37.58,126.97 37.58,126.97 37.56)))"
            ),
        )
        c.execute(
            text("UPDATE market_areas SET market_name='PRIVATE-CANARY' WHERE version_id=:v"),
            {"v": vid},
        )
    q = RiskQuery(**PARAMS)
    config = Settings(_env_file=None, risk_boundary_version_id=vid)
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        actual = get_risk(s, q, config)
        assert actual.data.market.spatial_candidate.primary.market_name == "PRIVATE-CANARY"
        prepared = prepare_risk_interpretation(s, q, config)
    assert "PRIVATE-CANARY" not in prepared.request.user_content
    assert str(vid) not in prepared.request.user_content
    assert "market_code" not in prepared.json_context()
    assert prepared.context.market_status == "unverified"


def test_same_aggregates_different_coordinates_have_same_context(db):
    seed(db)
    config = Settings(_env_file=None)
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        a = prepare_risk_interpretation(s, RiskQuery(**PARAMS), config)
        b = prepare_risk_interpretation(
            s, RiskQuery(**{**PARAMS, "lat": PARAMS["lat"] + 0.000001}), config
        )
    assert a.context_hash == b.context_hash and a.data_version_hash == b.data_version_hash
    assert a.request.user_content == b.request.user_content


def test_past_empty_and_source_not_ready_are_distinct(db):
    config = Settings(_env_file=None)
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        with pytest.raises(AppError):
            prepare_risk_interpretation(s, RiskQuery(**PARAMS), config)
    seed(db)
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        past = prepare_risk_interpretation(s, RiskQuery(**PARAMS, as_of="2020-02"), config)
        empty = prepare_risk_interpretation(s, RiskQuery(**{**PARAMS, "category": "cafe"}), config)
    assert past.context.as_of == date(2020, 2, 29)
    assert past.context.data_updated_at == date(2026, 11, 8)
    assert empty.context.indicators[-1].value == 0
    assert empty.context.indicators[2].value is None
    assert [g.model_dump() for g in empty.context.activity.groups] == [
        {"sub_category": "cafe", "open_count": 0, "avg_operating_months": None}
    ]
    assert past.context.activity.recent_period == "(2019-02-28, 2020-02-29]"
    assert sum(g.open_count for g in past.context.activity.groups) == (
        past.context.indicators[-1].value
    )


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"sub_category": "japanese"},
        {"sub_category": "korean,western"},
        {"radius": 300},
        {"area": "lt33", "include_unknown_area": False},
        {"franchise": "independent", "include_unknown_franchise": False},
        {"include_unknown": False},
    ],
)
def test_activity_context_matches_independent_activity_under_filters(db, changes):
    seed(db)
    config = Settings(_env_file=None)
    with Session(db) as s, s.begin():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        q = RiskQuery(**PARAMS, **changes)
        activity = get_activity(s, ActivityQuery(**PARAMS, **changes))
        risk = get_risk(s, q, config)
        prepared = prepare_risk_interpretation(s, q, config)
    groups = prepared.context.activity.groups
    assert [(g.sub_category, g.open_count, g.avg_operating_months) for g in groups] == sorted(
        (g.sub_category, g.open_count, g.avg_operating_months)
        for g in activity.data.by_sub_category
    )
    assert prepared.context.activity.recent_closed == activity.data.recent_12m.closed
    assert sum(g.open_count for g in groups) == risk.data.indicators[5].value
    assert prepared.context.activity.space == f"radius_{q.radius}m"
