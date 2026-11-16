"""Grounded prose options. The model selects prose; it cannot invent claims or numbers.

Each option is built from the same typed, server-recalculated evidence as the cards.
Alternatives have the same facts and differ only in connective phrasing. This is a
closed vocabulary for all fifteen interpretation rules, including cohort/time scope.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import JsonValue

from app.ai.chain_notices import chain_notice
from app.ai.population_context import population_sentence
from app.schemas.ai_context import ChainRiskInterpretContext, ContextIndicator, InterpretContext
from app.schemas.interpret import InterpretItem

NOTICE = "이 해석은 공공데이터 기반 참고 정보이며 창업 성공이나 실패를 예측한 결과가 아닙니다."
LABELS = {
    "cafe": "카페",
    "korean": "한식",
    "chinese": "중식",
    "japanese": "일식",
    "western": "양식",
}
Z = 1.96  # two-sided 95%
Judgement = Literal["higher", "lower", "inside", "unknown"]
TITLES = {
    "closure_rate_12m": "최근 12개월 참고 폐업률",
    "survival_rate_1y": "개업 1주년 생존율",
    "survival_rate_3y": "개업 3주년 생존율",
}
SHORT_TITLES = {
    "closure_rate_12m": "참고 폐업률",
    "survival_rate_1y": "1주년 생존율",
    "survival_rate_3y": "3주년 생존율",
}


@dataclass(frozen=True)
class NarrativeCatalog:
    groups: tuple[dict[str, InterpretItem], ...]

    def valid(self, ids: list[str]) -> bool:
        return len(ids) == len(self.groups) and all(
            key in group for key, group in zip(ids, self.groups, strict=True)
        )

    def paragraphs(self, ids: list[str]) -> list[InterpretItem]:
        if not self.valid(ids):
            raise ValueError("invalid narrative plan")
        return [group[key] for key, group in zip(ids, self.groups, strict=True)]

    def candidates(self) -> dict[str, JsonValue]:
        return {
            str(i): {key: item.model_dump(mode="json") for key, item in group.items()}
            for i, group in enumerate(self.groups)
        }


def build_narrative(c: InterpretContext) -> NarrativeCatalog:
    rows: dict[str, ContextIndicator] = {row.id: row for row in c.indicators}
    active = rows["competitor_count"].value
    if active is None:
        raise ValueError("active record count unavailable")
    a = c.activity
    label = "·".join(LABELS[key] for key in c.sub_category)
    opening = (
        f"{c.as_of.isoformat()} 기준, 선택한 위치 반경 {c.radius_m:,}m에서 "
        f"조회 조건에 맞는 {label} 영업 인허가 기록 {active:,}건이 확인되었습니다. "
        f"최근 12개월 구간 {inclusive_period(a.recent_period)}의 "
        f"개업 기록은 {a.recent_opened:,}건, "
        f"폐업 기록은 {a.recent_closed:,}건입니다. "
    )
    averages = []
    if isinstance(c, ChainRiskInterpretContext):
        opening += chain_notice(c) + " "
    for group in a.groups:
        if group.avg_operating_months is not None:
            averages.append(f"{LABELS[group.sub_category]} {group.avg_operating_months:,}개월")
    if averages:
        opening += (
            "같은 기준일에 영업한 기록의 평균 개업 후 경과 기간은 "
            + ", ".join(averages)
            + "입니다. "
        )
        opening += "이는 폐업한 점포의 실제 영업 기간이나 앞으로 운영할 기간을 뜻하지 않습니다."
    else:
        opening += "해당 시점의 영업 기록이 없어 평균 경과 기간은 산정하지 않았습니다."
    opening_ids = ["competitor_count", "recent_open_close", "avg_operating_months"]

    comparisons = []
    comparison_ids = []
    judgements: dict[str, Judgement] = {}
    unclear_names: list[str] = []
    for key, title in TITLES.items():
        row = rows.get(key)
        if row is None or row.status != "fact" or row.value is None:
            continue
        comparison_ids.append(key)
        if row.seoul_avg is None:
            comparisons.append(
                f"{title}은 {row.value:.1f}%로 확인됐지만, "
                "같은 조건의 서울 비교값은 표본이 부족해 제공하지 않습니다."
            )
            continue
        judgements[key] = judgement = compare_with_rest_of_seoul(row)
        sentence, unclear = comparison_sentence(title, row, judgement)
        comparisons.append(sentence)
        if unclear:
            unclear_names.append(SHORT_TITLES[key])
    if unclear_names:
        # One qualifier for all unclear gaps; it names them, so it never repeats a sentence.
        comparisons.append(
            f"{'·'.join(unclear_names)}의 차이는 기록 수를 고려하면 우연으로도 생길 수 있는 "
            "정도여서 서울과 뚜렷하게 다르다고 보기는 어렵습니다."
        )
    comparison = (
        " ".join(comparisons)
        if comparisons
        else "비율 지표는 유효 표본이 부족해 지역과 서울의 차이를 해석하지 않았습니다."
    )
    comparison += (
        " 이 비교는 Spot:ON이 좌표가 확보된 인허가 기록으로 계산한 참고지표이며 "
        "서울시 공식 통계가 아닙니다."
    )
    if any(key.startswith("survival") for key in comparison_ids):
        comparison += (
            " 각 생존율은 서로 다른 시기에 개업한 집단의 해당 개업 주년까지 "
            "영업 여부를 관측한 값으로, 같은 점포 집단의 시간 경과나 현재 잔존율을 뜻하지 않습니다."
        )
    # Opposite directions are only described when both differences are clear, not noise.
    if {judgements.get("survival_rate_1y"), judgements.get("survival_rate_3y")} == {
        "higher",
        "lower",
    }:
        comparison += (
            " 서울과의 차이가 두 관측 집단에서 서로 다른 방향으로 나타나므로, "
            "초기 영업 여부와 함께 장기 운영 비용 구조도 별도로 검토할 필요가 있습니다."
        )

    activity = []
    activity_ids = []
    if a.recent_opened and a.recent_closed:
        activity.append("선택한 최근 구간에서는 신규 개업과 폐업 기록이 함께 관측되었습니다.")
    elif a.recent_opened:
        activity.append(
            "선택한 최근 구간에서는 개업 기록이 확인되었고 폐업 기록은 확인되지 않았습니다."
        )
    elif a.recent_closed:
        activity.append(
            "선택한 최근 구간에서는 폐업 기록이 확인되었고 개업 기록은 확인되지 않았습니다."
        )
    else:
        activity.append(
            "선택한 최근 구간에서는 조건에 맞는 개업·폐업 사건 기록이 확인되지 않았습니다."
        )
    activity_ids.append("recent_open_close")
    if c.nearby is not None and c.nearby.active_at_as_of:
        nearby = c.nearby
        activity.append(
            f"같은 시점 영업 기록 중 시설 규모가 확인된 기록은 {nearby.known_area:,}건, "
            f"면적 정보가 없는 기록은 {nearby.unknown_area:,}건이며, "
            "점포별 직선거리는 "
            f"{nearby.min_distance_m:.1f}~{nearby.max_distance_m:.1f}m 범위입니다."
        )
        activity_ids.append("nearby_profile")
    # Only adjacent observed years are compared; gaps are not filled with synthetic zeros.
    years = a.yearly_trend[-2:]
    if len(years) == 2 and years[1].year == years[0].year + 1:
        previous, latest = years
        activity.append(
            "연도별 추이는 연초부터 기준일과 같은 월·일까지"
            "(해당 날짜가 없으면 월말)의 구간을 비교하며, "
            f"{previous.start.isoformat()}~{previous.end.isoformat()} "
            f"개업 {previous.opened:,}건·폐업 {previous.closed:,}건, "
            f"{latest.start.isoformat()}~{latest.end.isoformat()} "
            f"개업 {latest.opened:,}건·폐업 {latest.closed:,}건이 확인되었습니다."
        )
        activity_ids.append("yearly_trend")
    activity.append(
        "이러한 기록과 점포 수만으로 시장의 포화나 성장·쇠퇴를 단정할 수 없으며, "
        "인허가 기록이 실제 점포와 항상 일대일로 대응하는 것도 아닙니다."
    )
    # Building totals mix categories/locations and latest/future events. They are evidence
    # for the information popover only, never a narrative competition/closure statistic.

    preparation = (
        "창업을 준비할 때에는 선택 조건 밖의 점포까지 포함한 "
        "실제 주변 업종·시설 규모와 보행 동선을 현장에서 살피고, "
        "임대료·고정비와 예상 고객층을 별도로 확인해 장기 운영에 필요한 비용 구조를 검토해 주세요. "
        "확보되지 않은 매출·생활인구로 수요나 수익성을 추정하지 않았습니다. " + NOTICE
    )
    preparation_ids = []
    if isinstance(c, ChainRiskInterpretContext):
        preparation = preparation.replace(
            "확보되지 않은 매출·생활인구로 수요나 수익성을 추정하지 않았습니다.",
            "전체 생활인구와 매출의 적용 기준을 확인하지 못해 수요나 수익성을 추정하지 않았습니다.",
        )
        preparation = population_sentence(c.population_reference) + " " + preparation
        preparation_ids = ["population_public_subset"]
    texts = [
        (opening, opening_ids),
        (comparison, comparison_ids),
        (" ".join(activity), activity_ids),
        (preparation, preparation_ids),
    ]
    groups = []
    for index, (text, ids) in enumerate(texts):
        # Two equivalent connection choices, always scoped to their own paragraph.
        prefix = ("", "같은 자료를 바탕으로 보면, ", "이와 함께 ", "")[index]
        alternate = text if index == 0 else prefix + text
        if index == 3:
            alternate = text.replace(
                "창업을 준비할 때에는", "이를 바탕으로 실제 창업을 준비할 때에는", 1
            )
        groups.append(
            {
                f"paragraph_{index}_direct": InterpretItem.model_validate(
                    {"text": text, "indicator_ids": ids}
                ),
                f"paragraph_{index}_connected": InterpretItem.model_validate(
                    {"text": alternate, "indicator_ids": ids}
                ),
            }
        )
    return NarrativeCatalog(tuple(groups))


def wilson_interval(successes: int, total: int, z: float = Z) -> tuple[float, float]:
    """95% Wilson score interval of successes/total (total > 0)."""
    p = successes / total
    scale = 1 + z * z / total
    center = (p + z * z / (2 * total)) / scale
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / scale
    return center - half, center + half


def compare_with_rest_of_seoul(row: ContextIndicator) -> Judgement:
    """Judge local vs the rest of Seoul with a Newcombe hybrid score interval.

    The local records are a subset of the Seoul aggregate, so the comparison excludes them
    (rest = Seoul - local). The difference is "clear" only when the 95% interval of
    local rate - rest rate excludes zero; otherwise it is within chance variation.
    """
    k, n = row.numerator, row.denominator
    seoul_k, seoul_n = row.seoul_numerator, row.seoul_denominator
    if k is None or n is None or seoul_k is None or seoul_n is None or n <= 0:
        return "unknown"
    rest_k, rest_n = seoul_k - k, seoul_n - n
    if rest_n <= 0 or not 0 <= rest_k <= rest_n or not 0 <= k <= n:
        return "unknown"
    p1, p2 = k / n, rest_k / rest_n
    l1, u1 = wilson_interval(k, n)
    l2, u2 = wilson_interval(rest_k, rest_n)
    diff = p1 - p2
    if diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2) > 0:
        return "higher"
    if diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2) < 0:
        return "lower"
    return "inside"


def comparison_sentence(
    title: str, row: ContextIndicator, judgement: Judgement
) -> tuple[str, bool]:
    """Return the sentence and whether it states a gap that is within chance variation."""
    if row.value is None or row.seoul_avg is None:
        raise ValueError("comparison requires local and Seoul values")
    counts = (
        f"({row.denominator:,}건 중 {row.numerator:,}건)"
        if row.numerator is not None and row.denominator is not None
        else ""
    )
    head = f"{title}은 {row.value:.1f}%{counts}"
    seoul = f"서울 전체 동일 업종·필터의 {row.seoul_avg:.1f}%"
    delta = Decimal(str(row.value)) - Decimal(str(row.seoul_avg))
    if judgement == "unknown":
        return f"{head}이며, 서울 전체 동일 업종·필터는 {row.seoul_avg:.1f}%입니다.", False
    # The direction word must agree with both the judgement and the displayed values.
    if (judgement == "higher" and delta > 0) or (judgement == "lower" and delta < 0):
        word = "높았습니다" if delta > 0 else "낮았습니다"
        return f"{head}로, {seoul}보다 {abs(delta):.1f}%p 뚜렷하게 {word}.", False
    if not delta:
        return f"{head}로, {seoul}와 같았습니다.", False
    return f"{head}로, {seoul}와 {abs(delta):.1f}%p 차이가 있습니다.", True


def inclusive_period(value: str) -> str:
    lower, upper = value[1:-1].split(", ")
    return f"{(date.fromisoformat(lower) + timedelta(days=1)).isoformat()}~{upper}"
