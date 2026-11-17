import dataclasses
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.ai import context as context_module
from app.ai.context import prepare_risk_interpretation
from app.ai.interpretation import build_catalog, render_interpretation
from app.ai.narrative import (
    NOTICE,
    build_narrative,
    compare_with_rest_of_seoul,
    comparison_sentence,
    inclusive_period,
    wilson_interval,
)
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
    # The local records are a large share of this small Seoul aggregate, so none of the
    # displayed gaps is clear once the overlap is removed.
    assert "13.0%와 0.6%p 차이가 있습니다" in result.body
    assert "84.3%와 9.8%p 차이가 있습니다" in result.body
    assert "58.4%와 2.1%p 차이가 있습니다" in result.body
    assert "(81건 중 11건)" in result.body and "(17건 중 16건)" in result.body
    # One qualifier names every unclear gap instead of repeating a sentence per indicator.
    assert result.body.count("우연으로도") == 1
    assert "참고 폐업률·1주년 생존율·3주년 생존율의 차이는" in result.body
    assert "뚜렷하게 높았" not in result.body and "뚜렷하게 낮았" not in result.body
    assert "서로 다른 방향" not in result.body
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


def test_removed_official_metrics_and_site_guide_are_absent_from_all_candidates(sample):
    from app.ai.interpretation import build_catalog

    catalog = build_catalog(sample)
    text = str(catalog.candidates()) + " ".join(m.text for m in catalog.missing)
    for removed in (
        "official_closure_rate",
        "official_risk",
        "공식 창업위험도",
        "공식 폐업률",
        "공식 서비스",
        "golmok",
    ):
        assert removed not in text
    assert {r.id for r in sample.context.indicators} == {
        "closure_rate_12m",
        "survival_rate_1y",
        "survival_rate_3y",
        "competitor_count",
    }


def test_pre_2010_year_is_rejected_in_public_and_ai_contracts():
    with pytest.raises(ValueError):
        YearlyActivity(year=2009, opened=1, closed=0)
    with pytest.raises(ValueError):
        ContextYear(year=2009, opened=1, closed=0, start=date(2009, 1, 1), end=date(2009, 11, 8))


def test_tampered_pre_2010_trend_is_rejected_before_llm(monkeypatch):
    _, activity = use_risk(monkeypatch, context_module, response())
    activity.return_value.data.yearly_trend = [
        YearlyActivity.model_construct(year=2009, opened=2, closed=1)
    ]
    activity.return_value.meta.update(
        yearly_comparison_basis="same_month_day_ytd",
        yearly_periods={"2009": {"start": "2009-01-01", "end": "2009-11-08"}},
    )
    with pytest.raises(AppError):
        prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


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


def rate_row(k, n, seoul_k, seoul_n):
    """Minimal stand-in for ContextIndicator with display values derived from the counts."""

    def percent(a, b):
        return float((Decimal(a) * 100 / Decimal(b)).quantize(Decimal("0.1"), ROUND_HALF_UP))

    return SimpleNamespace(
        numerator=k,
        denominator=n,
        seoul_numerator=seoul_k,
        seoul_denominator=seoul_n,
        value=percent(k, n),
        seoul_avg=percent(seoul_k, seoul_n),
    )


@pytest.mark.parametrize(
    "k,n,low,high",
    [(24, 30, 0.627, 0.905), (21, 32, 0.483, 0.796)],
)
def test_wilson_interval_matches_hand_calculation(k, n, low, high):
    lower, upper = wilson_interval(k, n)
    assert lower == pytest.approx(low, abs=0.001)
    assert upper == pytest.approx(high, abs=0.001)


@pytest.mark.parametrize(
    "row,expected",
    [
        # Hongdae cafe 500m (production 2026-11-16): visible gaps, but within chance.
        (rate_row(24, 30, 1555, 1877), "inside"),
        (rate_row(21, 32, 1525, 2477), "inside"),
        (rate_row(20, 169, 1890, 16269), "inside"),
        (rate_row(40, 100, 1000, 10000), "higher"),
        (rate_row(2, 100, 3000, 10000), "lower"),
        # Same local 16/20: clear against a large rest of Seoul, not against a tiny one.
        (rate_row(16, 20, 5000, 10000), "higher"),
        (rate_row(16, 20, 20, 26), "inside"),
        # The local records are all of Seoul: nothing to compare against.
        (rate_row(16, 20, 16, 20), "unknown"),
    ],
)
def test_local_rate_is_judged_against_the_rest_of_seoul(row, expected):
    assert compare_with_rest_of_seoul(row) == expected


def test_comparison_sentences_by_judgement():
    clear = comparison_sentence("개업 1주년 생존율", rate_row(40, 100, 1000, 10000), "higher")
    assert clear == (
        "개업 1주년 생존율은 40.0%(100건 중 40건)로, 서울 전체 동일 업종·필터의 10.0%보다 "
        "30.0%p 뚜렷하게 높았습니다.",
        False,
    )
    inside = comparison_sentence("개업 1주년 생존율", rate_row(24, 30, 1555, 1877), "inside")
    assert inside == (
        "개업 1주년 생존율은 80.0%(30건 중 24건)로, 서울 전체 동일 업종·필터의 82.8%와 "
        "2.8%p 차이가 있습니다.",
        True,
    )
    same = comparison_sentence("t", rate_row(5, 10, 50, 100), "inside")
    assert same[0].endswith("50.0%와 같았습니다.") and same[1] is False
    unknown = comparison_sentence("t", rate_row(16, 20, 16, 20), "unknown")
    assert unknown == (
        "t은 80.0%(20건 중 16건)이며, 서울 전체 동일 업종·필터는 80.0%입니다.",
        False,
    )
    # A judgement that disagrees with the displayed sign never produces a direction word.
    mismatch = comparison_sentence("t", rate_row(2, 100, 3000, 10000), "higher")
    assert "뚜렷하게" not in mismatch[0] and mismatch[1] is True


def counts(**changes):
    base = dict(
        cohort_size=30000,
        active=12345,
        closure_num=1234,
        closure_den=13579,
        survival_1_num=950,
        survival_1_den=1000,
        survival_3_num=100,
        survival_3_den=1000,
    )
    return ReferenceCounts(**{**base, **changes})


def seoul_counts(**changes):
    base = dict(
        cohort_size=900000,
        active=364000,
        closure_num=36000,
        closure_den=400000,
        survival_1_num=40000,
        survival_1_den=50000,
        survival_3_num=30000,
        survival_3_den=50000,
    )
    return ReferenceCounts(**{**base, **changes})


def body_for(monkeypatch, local, seoul):
    use_risk(monkeypatch, context_module, response(local=local, seoul=seoul), opened=10, months=63)
    prepared = prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))
    return output(prepared).body


def test_opposite_direction_note_needs_two_clear_differences(monkeypatch):
    body = body_for(monkeypatch, counts(), seoul_counts())
    assert "1주년 생존율은 95.0%(1,000건 중 950건)로" in body
    assert "80.0%보다 15.0%p 뚜렷하게 높았습니다" in body
    assert "60.0%보다 50.0%p 뚜렷하게 낮았습니다" in body
    assert "(13,579건 중 1,234건)" in body
    assert "서로 다른 방향" in body
    # Only the near-equal closure rate (9.1% vs 9.0%) is named as within chance.
    assert "다. 참고 폐업률의 차이는 기록 수를 고려하면 우연으로도" in body


def test_opposite_direction_note_is_absent_when_one_gap_is_noise(monkeypatch):
    local = counts(survival_3_num=5, survival_3_den=10)
    body = body_for(monkeypatch, local, seoul_counts())
    assert "뚜렷하게 높았습니다" in body
    assert "50.0%(10건 중 5건)로, 서울 전체 동일 업종·필터의 60.0%와 10.0%p 차이가 있습니다" in body
    assert "3주년 생존율의 차이는 기록 수를 고려하면 우연으로도" in body
    assert "서로 다른 방향" not in body


@pytest.mark.parametrize(
    "interval,expected",
    [
        ("(2024-02-29, 2025-02-28]", "2024-03-01~2025-02-28"),
        ("(2024-11-30, 2025-11-30]", "2024-12-01~2025-11-30"),
    ],
)
def test_open_left_period_is_displayed_as_inclusive_calendar_dates(interval, expected):
    assert inclusive_period(interval) == expected
