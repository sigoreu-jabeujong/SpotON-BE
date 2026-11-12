"""API v1.2 §4-8: model ordering over server-calculated and server-authored evidence."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import JsonValue

from app.ai.context import PreparedRiskInterpretation
from app.ai.verifier import NUMBER_PATTERN, verify_output
from app.schemas.ai_context import RiskInterpretContext
from app.schemas.interpret import (
    CandidateSelection,
    ChecklistItem,
    InterpretationVerification,
    InterpretItem,
    InterpretSourcedItem,
    MissingItem,
    RiskInterpretation,
)

CHECKLIST = {
    "time_flow": ChecklistItem(
        item="시간대별 현장 유동 확인",
        why="생활인구와 실제 방문 흐름은 다르므로 영업 예정 시간에 직접 확인해 주세요.",
    ),
    "access": ChecklistItem(
        item="보행 동선과 출입 접근성 확인",
        why="지도 반경과 실제 이동 경로가 같은지 현장에서 살펴보세요.",
    ),
    "visibility": ChecklistItem(
        item="가시성과 주변 점포 확인",
        why="입구가 보이는 위치와 실제 비교 점포의 운영 모습을 확인해 주세요.",
    ),
    "operations": ChecklistItem(
        item="운영 조건 확인", why="데이터에 없는 운영 시간과 이용 조건을 현장에서 확인해 주세요."
    ),
}
TITLES = {
    "closure_rate_12m": "최근 기간 참고 폐업률",
    "survival_rate_1y": "개업 1주년 생존율",
    "survival_rate_3y": "개업 3주년 생존율",
}
ACTIVITY_LABELS = {
    "cafe": "카페",
    "korean": "한식",
    "chinese": "중식",
    "japanese": "일식",
    "western": "양식",
}
MISSING_TITLES = {
    "official_closure_rate": "공식 폐업률",
    "official_risk": "공식 창업위험도",
    "market_change": "상권변화 유형",
    "day_night_ratio": "주야간 인구비",
    **TITLES,
}


@dataclass(frozen=True)
class InterpretationCatalog:
    facts: tuple[InterpretItem, ...]
    favorable: dict[str, InterpretSourcedItem]
    unfavorable: dict[str, InterpretSourcedItem]
    missing: tuple[MissingItem, ...]

    def selection_valid(self, data: dict[str, JsonValue]) -> bool:
        selected = CandidateSelection.model_validate(data)
        return (
            set(selected.favorable) == set(self.favorable)
            and set(selected.unfavorable) == set(self.unfavorable)
            and set(selected.checklist) <= set(CHECKLIST)
        )

    def candidates(self) -> dict[str, JsonValue]:
        return {
            "favorable": {
                k: {"id": k, **v.model_dump(mode="json")} for k, v in self.favorable.items()
            },
            "unfavorable": {
                k: {"id": k, **v.model_dump(mode="json")} for k, v in self.unfavorable.items()
            },
            "checklist": {k: {"id": k, **v.model_dump(mode="json")} for k, v in CHECKLIST.items()},
        }

    def selection_schema(self) -> dict[str, JsonValue]:
        schema = CandidateSelection.model_json_schema()
        for group, options in (
            ("favorable", self.favorable),
            ("unfavorable", self.unfavorable),
            ("checklist", CHECKLIST),
        ):
            rule = schema["properties"][group]
            if options:
                rule["items"] = {"type": "string", "enum": list(options)}
            if group != "checklist":
                rule["minItems"] = rule["maxItems"] = len(options)
        return schema


def _activity_facts(c: RiskInterpretContext) -> list[InterpretItem]:
    """#60 활동 집계의 참고 계산 문장. 문맥에 없는 숫자(기간 길이 등)는 쓰지 않는다."""
    a = c.activity
    facts = [
        InterpretItem(
            text=(
                f"참고 계산: 최근 구간 {a.recent_period}에 반경 {c.radius_m}m의 "
                f"개업 인허가 기록은 {a.recent_opened:,}건, "
                f"폐업 기록은 {a.recent_closed:,}건입니다."
            ),
            indicator_ids=["recent_open_close"],
        )
    ]
    for g in a.groups:
        label = ACTIVITY_LABELS[g.sub_category]
        if g.avg_operating_months is None:
            text = (
                f"참고 계산: {c.as_of.isoformat()} 기준 {label} 영업 기록이 없어 "
                "평균 경과 기간을 산정하지 않았습니다."
            )
        else:
            text = (
                f"참고 계산: {c.as_of.isoformat()} 기준 {label} 영업 기록 {g.open_count:,}건의 "
                f"개업 후 평균 경과 기간은 {g.avg_operating_months:,}개월입니다."
            )
        facts.append(InterpretItem(text=text, indicator_ids=["avg_operating_months"]))
    return facts


def _history_items(c: RiskInterpretContext) -> tuple[list[InterpretItem], list[MissingItem]]:
    """#98 건물 이력 문장. 숫자 바로 뒤에 층·호를, '로'·'길' 바로 뒤에 숫자를 두지 않는다."""
    h = c.history
    if h is None:
        return [], []
    day = h.data_updated_at.isoformat()
    if h.total == 0:
        return [], [
            MissingItem(
                text=f"{day} 최신 자료 기준 이 건물에서 확인된 음식점·카페 인허가 기록이 없습니다.",
                reason="history_no_records",
            )
        ]
    if h.floor_unit_provided:
        overview = (
            f"참고 계산: {day} 최신 자료 기준 이 건물의 음식점·카페 인허가 기록은 "
            f"{h.total:,}건이며, 같은 자리로 확인된 기록 {h.same_spot:,}건, "
            f"같은 건물의 다른 위치 {h.same_building:,}건, 위치 미확인 {h.unverified:,}건입니다."
        )
    else:
        overview = (
            f"참고 계산: {day} 최신 자료 기준 이 건물의 음식점·카페 인허가 기록은 "
            f"{h.total:,}건입니다."
        )
    facts = [InterpretItem(text=overview, indicator_ids=["building_history"])]
    if h.same_spot:
        counts = f"같은 자리 기록 중 영업 중 {h.same_spot_open:,}건, 폐업 {h.same_spot_closed:,}건"
        if h.same_spot_other:
            counts += f", 기타 상태 {h.same_spot_other:,}건"
        low, high = h.same_spot_closed_months_min, h.same_spot_closed_months_max
        if h.same_spot_closed == 0:
            detail = f"참고 계산: {counts}입니다."
        elif low is None or high is None:
            detail = f"참고 계산: {counts}이며, 폐업 기록의 영업 기간은 확인되지 않았습니다."
        else:
            span = f"{low:,}개월" if low == high else f"{low:,}~{high:,}개월"
            detail = (
                f"참고 계산: {counts}이며, 영업 기간을 확인한 폐업 기록 "
                f"{h.same_spot_closed_period_count:,}건의 영업 기간은 {span}입니다."
            )
        facts.append(InterpretItem(text=detail, indicator_ids=["same_spot_history"]))
    missing = []
    if not h.floor_unit_provided:
        missing.append(
            MissingItem(
                text="상세 위치(층·호수)가 없어 같은 자리 기록 여부는 판단하지 않았습니다.",
                reason="history_floor_unit_missing",
            )
        )
    elif not h.same_spot_comparable:
        missing.append(
            MissingItem(
                text=(
                    "입력한 상세 위치에 층과 호수가 함께 있지 않아 "
                    "같은 자리 기록 여부는 판단하지 않았습니다."
                ),
                reason="history_detail_incomplete",
            )
        )
    missing.append(
        MissingItem(
            text=(
                "건물 이력은 요청 기준 시점이 아닌 최신 자료 기준이며 지원 업종 전체 기록입니다. "
                "폐업 원인이나 자리의 성패를 뜻하지 않습니다."
            ),
            reason="history_latest_data_basis",
        )
    )
    return facts, missing


def build_catalog(prepared: PreparedRiskInterpretation) -> InterpretationCatalog:
    c = prepared.context
    facts = []
    positive: dict[str, InterpretSourcedItem] = {}
    negative: dict[str, InterpretSourcedItem] = {}
    missing = []
    for row in c.indicators:
        if row.status != "fact":
            title = MISSING_TITLES.get(row.id, row.id)
            if row.reason in {"insufficient_sample", "zero_denominator"}:
                message = f"{title}은 표본 {row.denominator}건으로 비율을 산정하지 않았습니다."
            elif row.id == "official_risk":
                message = "공식 창업위험도 수치는 제공하지 않으며 공식 서비스 안내를 확인해 주세요."
            else:
                message = f"{title}에 필요한 자료의 적용 기준을 확인 중입니다."
            missing.append(MissingItem(text=message, reason=row.reason or "not_available"))
            continue
        if row.value is None:
            raise ValueError("fact requires a value")
        if row.id == "competitor_count":
            message = (
                f"참고 계산: {c.as_of.isoformat()} 기준 반경 {c.radius_m}m의 "
                f"동종업체 인허가 기록은 {row.value:,}건입니다."
            )
        else:
            message = (
                f"참고 계산: {TITLES[row.id]}은 {row.value:.1f}%이며 "
                f"분모는 {row.denominator}건입니다. 적용 구간은 {row.period}입니다."
            )
        facts.append(InterpretItem(text=message, indicator_ids=[row.id]))
        if row.id not in TITLES or row.seoul_avg is None:
            continue
        if row.value == row.seoul_avg:
            continue
        lower = row.value < row.seoul_avg
        favorable = lower if row.id == "closure_rate_12m" else not lower
        item = InterpretSourcedItem(
            text=(
                f"참고 비교: {TITLES[row.id]} {row.value:.1f}%는 같은 조건의 "
                f"서울 값 {row.seoul_avg:.1f}%보다 {'낮습니다' if lower else '높습니다'}."
            ),
            indicator_ids=[row.id],
            sources=list(row.source),
        )
        (positive if favorable else negative)[row.id + "_comparison"] = item
    facts.extend(_activity_facts(c))
    history_facts, history_missing = _history_items(c)
    facts.extend(history_facts)
    missing.extend(history_missing)
    missing.extend(
        [
            MissingItem(
                text=(
                    "상권 적용 시점은 미확인이고 가맹 분류는 기준년도 목록과 상호의 "
                    "일치에 따른 추정입니다. 실제 가맹계약이나 과거 소속을 증명하지 않습니다."
                    if c.franchise_classification == "estimate"
                    else "상권 적용 시점과 가맹 분류는 미확인 상태입니다."
                ),
                reason="franchise_name_match_estimate"
                if c.franchise_classification == "estimate"
                else "classification_unverified",
            ),
            MissingItem(
                text="전체 수집 완료일이 확인되지 않았으며 검증일을 수집일로 대체하지 않습니다.",
                reason="source_completion_time_not_recorded",
            ),
            MissingItem(
                text=(
                    "인허가 기록과 좌표 확보 자료를 비교한 참고 정보로, "
                    "지위승계와 현재 스냅샷에 따른 과거 재구성의 한계가 있습니다."
                ),
                reason="license_data_limitations",
            ),
        ]
    )
    return InterpretationCatalog(tuple(facts), positive, negative, tuple(missing))


def render_interpretation(
    prepared: PreparedRiskInterpretation,
    catalog: InterpretationCatalog,
    selection: CandidateSelection,
    *,
    model: str,
    regenerated: bool,
) -> RiskInterpretation:
    if not catalog.selection_valid(selection.model_dump(mode="json")):
        raise ValueError("invalid selection")
    favorable = [catalog.favorable[k] for k in selection.favorable]
    unfavorable = [catalog.unfavorable[k] for k in selection.unfavorable]
    checklist = [CHECKLIST[k] for k in selection.checklist]
    visible = [item.text for item in catalog.facts]
    visible.extend(item.text for item in favorable + unfavorable)
    visible.extend(item.text for item in catalog.missing)
    visible.extend(part for item in checklist for part in (item.item, item.why))
    text = "\n".join(visible)
    if not verify_output(
        json.dumps({"text": text}, ensure_ascii=False), context=prepared.json_context()
    ).ok:
        raise ValueError("server narrative verification failed")
    return RiskInterpretation(
        official_values=list(catalog.facts),
        favorable=favorable,
        unfavorable=unfavorable,
        missing_data=list(catalog.missing),
        checklist=checklist,
        verification=InterpretationVerification(
            checked_numbers=len(NUMBER_PATTERN.findall(text)), regenerated=regenerated
        ),
        model=model,
        generated_at=datetime.now(UTC),
    )
