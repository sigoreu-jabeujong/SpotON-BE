# AI 해석 3영역 연동 계약

새 API는 `POST /api/v2/risk/interpret/sections`다. 기존 해석 API는 유지한다. [설계](designs/ai-three-section-interpretation.md)와 [구현·검수 기록](designs/ai-three-section-implementation.md)을 함께 따른다.

## 요청

```json
{
  "query": {"lat": 37.5, "lng": 127.0, "radius": 500, "category": "cafe"},
  "baseline": {
    "risk": "화면 risk GET의 meta.ai_report_basis_token",
    "activity": "sales,living_pop 포함 activity GET의 토큰",
    "location": "location-reference GET의 토큰",
    "grid": "population-reference GET의 토큰",
    "address_history": null
  },
  "time_mode": "latest_reference"
}
```

예시의 토큰 설명은 실제 64자리 hex 토큰으로 치환한다. `query`는 기존 v2 Risk 조건이며 include는 받지 않는다. 주소 이력이 선택된 경우 baseline.address_history와 `address_history: {context, category, floor_unit?}`를 함께 보낸다. context는 동일 좌표·업종으로 발급받은 v3 context_version2다. 토큰을 복호화하거나 주소/건물키로 대체하지 않는다.

location/grid는 lat/lng/radius/category/sub_category/as_of 조건만 투영하며 location에만 time_mode를 더한다. 시설 규모는 해당 참고자료에 적용되지 않는다. activity는 sales,living_pop을 포함한 전체 화면 조회와 동일하다. 서버는 같은 읽기 전용 RR에서 모든 입력을 재조회해 토큰을 대조한다.

## 응답

기존 `{data, meta}` envelope이며 data.schema_version은 ai-sections-v1이다.

- status: complete 또는 partial. advantages/cautions/summary 각각 ready 또는 unavailable이며, ready는 verification.passed=true다. unavailable의 reason은 provider_error/verification_failed/timeout/rate_limited다.
- items: 서버가 작성한 text/evidence_ids/group_id다. summary는 모든 자료 그룹에서 정확히 한 문장을 제공한다. FE는 plain text로만 표시한다.
- limitations: 모델 역할 성공과 무관하게 항상 제공하는 필수 한계 안내다. 유의점 역할이 실패해도 유의점 카드 안에 표시한다.
- metrics: value는 손실 없는 decimal 문자열 또는 null, display는 표시 문자열이다. 출처/기간/공간/대상/필터/분모와 exact_zero/rounded를 보존한다. area_label은 행정동 표시용 이름이며 모델에는 전달하지 않는다. 숫자 계산을 FE에서 반복하지 않는다.
- checklist: 기존 고정 3개 원문. 체크 상태는 저장하지 않고 결과가 교체되면 초기화한다.
- baseline/report_context_hash/generated_at: 현재 자료와 결과 식별자다. 모델 원문·후보 ID는 응답하지 않는다.

신규 정상 생성은 역할별 Gemini 1회씩 총3회다. 공급자 재시도/검증 재생성은0회이며 캐시/PDF는0회, 실패는 최대3회다. partial은 서버 캐시에 저장하지 않는다. FE는 조회/인쇄/새로고침만으로 POST하지 않는다. 배경 GET이 진행 중이거나 실패해도 마지막 성공 토큰이 같으면 이미 검증된 결과와 체크 상태를 유지한다.

## 오류·배포

409 AI_CONTEXT_CHANGED는 자료를 한 번 다시 조회한 뒤 수동으로 재생성한다. 409 AI_HISTORY_CONTEXT_OUTDATED는 주소 입력에서 재확인한다. 422는 조건/context 불일치다. 미설정·전체 실패·동시 용량 부족은503이며 자동 재시도하지 않는다. 오류 응답은 no-store다.

DB·키·환경 변경은 없다. BE 새 API/토큰/context2를 먼저 배포하고 FE main을 공개한다. v1 해석 화면은 기존 API를 계속 사용한다. 실제 Gemini/DB/브라우저 테스트는 사용자 요청에 따라 생략했으며 정적 검수 PASS를 운영 정상 판정으로 간주하지 않는다.
