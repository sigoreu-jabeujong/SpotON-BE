"""Deterministic scope wording; the model only selects complete server paragraphs."""

from app.schemas.ai_context import ChainRiskInterpretContext


def chain_notice(context: ChainRiskInterpretContext) -> str:
    filters, brand = context.filters, context.brand_classification
    if filters.brand_scope == "non_chain":
        scope = (
            "비체인 조건에 미확인 기록을 포함했으며 독립 점포를 확정한 목록은 아닙니다. "
            if filters.brand_unknown == "include"
            else "비체인 확정 기록을 선택했지만 현재 확인된 비체인 근거는 제공하지 않습니다. "
        )
    elif filters.brand_scope == "chain":
        scope = (
            "체인 조건에 미확인 기록을 함께 포함했습니다. "
            if filters.brand_unknown == "include"
            else "브랜드 소속 근거가 조회 조건을 만족한 기록만 포함했습니다. "
        )
    else:
        scope = "미확인 포함 여부와 근거 수준을 적용한 브랜드 조회 조건입니다. "
    if filters.brand_evidence == "confirmed_only":
        scope += "추정을 확정 근거로 인정하지 않으며 현재 확정된 체인 근거는 제공하지 않습니다. "
        if filters.brand_scope == "chain" and filters.brand_unknown == "exclude":
            scope += "확인 자료가 아직 없어 이 조건의 결과는 0건입니다. "
    if brand.status == "pending":
        scope += "브랜드 판정 자료가 준비되지 않았으므로 빈 결과를 체인 부재로 해석할 수 없습니다. "
    else:
        scope += "가맹·직영·소규모 체인의 브랜드 소속을 함께 다루는 관측 기록의 추정입니다. "
    if brand.source_drift:
        scope += "원천 변경으로 주소 대조 근거는 재검증 전 미확인으로 처리했습니다. "
    return scope + "실제 가맹·직영 운영 형태와 과거 브랜드 소속을 확인한 것은 아닙니다."
