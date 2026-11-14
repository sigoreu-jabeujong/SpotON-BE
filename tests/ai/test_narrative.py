import dataclasses
from datetime import date
from unittest.mock import Mock

import pytest

from app.ai import context as context_module
from app.ai.context import prepare_risk_interpretation
from app.ai.interpretation import build_catalog, render_interpretation
from app.ai.narrative import NOTICE, build_narrative, inclusive_period
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.ai_context import ContextYear
from app.schemas.interpret import CandidateSelection
from app.schemas.market_activity import YearlyActivity
from app.schemas.risk import ReferenceCounts
from tests.ai.context_helpers import query, response, use_risk
from tests.ai.test_interpretation import history_output, history_row


@pytest.fixture
def sample(monkeypatch):
    local = ReferenceCounts(
        cohort_size=99,
        active=70,
        closure_num=11,
        closure_den=81,
        survival_1_num=16,
        survival_1_den=17,
        survival_3_num=9,
        survival_3_den=16,
    )
    seoul = ReferenceCounts(
        cohort_size=400,
        active=174,
        closure_num=26,
        closure_den=200,
        survival_1_num=59,
        survival_1_den=70,
        survival_3_num=73,
        survival_3_den=125,
    )
    use_risk(monkeypatch, context_module, response(local=local, seoul=seoul), opened=10, months=63)
    return prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


def output(prepared, ids=None):
    catalog = build_catalog(prepared)
    return render_interpretation(
        prepared,
        catalog,
        CandidateSelection(
            favorable=list(catalog.favorable),
            unfavorable=list(catalog.unfavorable),
            checklist=["access"],
            narrative_ids=ids if ids is not None else [f"paragraph_{i}_direct" for i in range(4)],
        ),
        model="synthetic",
        regenerated=False,
    )


def test_percentage_points_are_exact_and_evidence_preserves_denominators(sample):
    result = output(sample)
    assert "0.6%p 높았습니다" in result.body
    assert "9.8%p 높았습니다" in result.body
    assert "2.1%p 낮았습니다" in result.body
    assert len(result.paragraphs) == 4
    assert result.body == "\n\n".join(p.text for p in result.paragraphs)
    assert result.body.endswith(NOTICE)
    assert not any(p.text.startswith(("#", "1.", "- ")) for p in result.paragraphs)
    evidence = {row["id"]: row for row in result.evidence["indicators"]}
    assert evidence["closure_rate_12m"]["denominator"] == 81
    assert evidence["competitor_count"]["value"] == 70
    assert evidence["closure_rate_12m"]["source"] == ["R5", "R6"]
    assert result.evidence["collected_at"] is None
    assert set(result.used_indicator_ids) == {
        key for p in result.paragraphs for key in p.indicator_ids
    }


@pytest.mark.parametrize(
    "ids",
    [
        [],
        ["paragraph_0_direct"],
        ["paragraph_0_direct"] * 4,
        ["paragraph_1_direct", "paragraph_0_direct", "paragraph_2_direct", "paragraph_3_direct"],
        ["paragraph_0_direct", "paragraph_1_direct", "invented_text_999", "paragraph_3_direct"],
    ],
)
def test_model_cannot_insert_text_omit_or_reorder_flows(sample, ids):
    with pytest.raises(ValueError):
        output(sample, ids)


def test_both_prose_variants_preserve_facts_and_final_notice(sample):
    direct = output(sample, [f"paragraph_{i}_direct" for i in range(4)])
    connected = output(sample, [f"paragraph_{i}_connected" for i in range(4)])
    assert direct.body != connected.body
    assert direct.evidence == connected.evidence
    assert direct.used_indicator_ids == connected.used_indicator_ids
    assert connected.body.endswith(NOTICE)


def test_empty_cohort_does_not_invent_rates_or_operating_period(monkeypatch):
    empty = ReferenceCounts(
        cohort_size=0,
        active=0,
        closure_num=0,
        closure_den=0,
        survival_1_num=0,
        survival_1_den=0,
        survival_3_num=0,
        survival_3_den=0,
    )
    use_risk(monkeypatch, context_module, response(local=empty, seoul=empty), opened=0)
    prepared = prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    result = output(prepared)
    assert "%p" not in result.body
    assert "평균 경과 기간은 산정하지 않았습니다" in result.body
    assert "유효 표본이 부족" in result.body
    assert not result.favorable and not result.unfavorable
    assert result.evidence["collected_at"] is None


def test_building_totals_and_different_category_records_never_enter_body(monkeypatch):
    result = history_output(
        monkeypatch,
        [
            history_row("same_spot", "closed", 14, index=0),
            history_row("same_building", "closed", 30, index=1),
            history_row("unverified", "open", 3, index=2),
        ],
    )
    assert "이 건물" not in result.body
    assert "위치 미확인" not in result.body
    assert "building_history" not in result.used_indicator_ids
    assert "same_spot_history" not in result.used_indicator_ids
    assert result.evidence["history"]["total"] == 3


def test_yearly_ytd_does_not_replace_rolling_twelve_month_counts(sample):
    years = tuple(
        ContextYear(year=y, opened=o, closed=c, start=date(y, 1, 1), end=date(y, 11, 8))
        for y, o, c in [(2025, 4, 6), (2026, 7, 9)]
    )
    activity = sample.context.activity.model_copy(update={"yearly_trend": years})
    prepared = dataclasses.replace(
        sample, context=sample.context.model_copy(update={"activity": activity})
    )
    result = output(prepared)
    assert "개업 기록은 10건" in result.body
    assert "2026-01-01~2026-11-08 개업 7건·폐업 9건" in result.body
    assert "yearly_trend" in result.used_indicator_ids


def test_missing_years_are_not_filled_or_compared(sample):
    years = tuple(
        ContextYear(year=y, opened=1, closed=2, start=date(y, 1, 1), end=date(y, 11, 8))
        for y in (2024, 2026)
    )
    c = sample.context.model_copy(
        update={"activity": sample.context.activity.model_copy(update={"yearly_trend": years})}
    )
    assert "yearly_trend" not in {
        key
        for p in build_narrative(c).paragraphs([f"paragraph_{i}_direct" for i in range(4)])
        for key in p.indicator_ids
    }


@pytest.mark.parametrize("year,end", [(2027, "2027-11-08"), (2026, "2026-12-31")])
def test_future_or_mismatched_yearly_period_is_rejected_before_llm(monkeypatch, year, end):
    _, activity = use_risk(monkeypatch, context_module, response())
    activity.return_value.data.yearly_trend = [YearlyActivity(year=year, opened=2, closed=1)]
    activity.return_value.meta.update(
        yearly_comparison_basis="same_month_day_ytd",
        yearly_periods={str(year): {"start": f"{year}-01-01", "end": end}},
    )
    with pytest.raises(AppError):
        prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


@pytest.mark.parametrize(
    "interval,expected",
    [
        ("(2024-02-29, 2025-02-28]", "2024-03-01~2025-02-28"),
        ("(2024-11-30, 2025-11-30]", "2024-12-01~2025-11-30"),
    ],
)
def test_open_left_period_is_displayed_as_inclusive_calendar_dates(interval, expected):
    assert inclusive_period(interval) == expected
