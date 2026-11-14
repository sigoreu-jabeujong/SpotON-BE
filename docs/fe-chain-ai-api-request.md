# 브랜드 조건을 유지하는 v2 AI 해석 연결 요청 (#147)

BE 구현용 계약이며 FE 저장소는 수정하지 않았다. 기존 실행 서버와 Render/운영 DB·배포도 변경하지 않았다. #145 v2 조회와 이 API를 사용하려면 head0012·브랜드 publication을 준비한 BE를 배포해야 한다. 이 문서는 FE 적용 완료를 뜻하지 않는다.

## 요청

`POST /api/v2/risk/interpret`, `Content-Type: application/json`.

```json
{
  "query": {
    "lat": 37.5665,
    "lng": 126.978,
    "category": "cafe",
    "radius": 500,
    "brand_scope": "chain",
    "brand_unknown": "exclude",
    "brand_evidence": "include_estimates"
  },
  "history": {
    "building_key": "종로구-청운동-1-0",
    "floor_unit": "2층 201호"
  }
}
```

history는 선택이며 생략할 수 있다. 제시한 좌표/건물은 형식 예시이며 실제 선택 위치와 일치하는 건물키를 보내야 한다. 가장 가까운 지원 이력 좌표가 선택 위치에서300m를 넘으면422다. 위치 좌표가 없으면 기존 위치 미확인 규칙을 유지한다. history는 최신 자료 기준 전체 지원 이력이며 브랜드·면적·과거 시점 필터로 줄이지 않는다.

query는 `/api/v2/risk`와 같은 ChainRiskQuery다. scope≠all이면 brand_unknown 명시가 필수다. brand_time_basis는 observed_record, operation_type은 any만 지원한다. 선택 include는 market_change/day_night_ratio이고 미확보 수치는 pending이다. legacy franchise/include_unknown/include_unknown_franchise, 클라이언트 수치·context·해석·배치/세대 지정·추가 query string은 거절한다. 동일 JSON 키 반복·NaN·잘못된 건물키·body 초과도422이며 DB와 모델 호출 전에 검증한다.

## 응답과 표시

기존 AI 외피/응답 구조를 유지한다. data.body는4문단 연결 본문이며 paragraphs·used_indicator_ids·evidence·verification도 함께 제공한다. 자유 생성 수치를 쓰지 않고 서버가 계산·검증한 문장 후보를 모델이 선택한다. evidence.filters는 실제 브랜드 조건이고 franchise 필드는 없다. evidence.brand_classification에는 pending/estimate·source_drift·관측 시점/부분 범위·기준년도/월과 한계만 포함한다.

meta.brand_classification은 조회 API와 같은 상태/공개 세대를, meta.brand_filters는 조회 조건을 제공한다. meta.prompt_version은 chain-risk-interpret-v1이다. context/data_version/prompt hash는 서버 응답·캐시 정합 확인용이며 LLM에는 내부 generation/원천 지문을 보내지 않는다. 원문 주소·점포명·인허가/브랜드 ID·좌표·층호도 LLM 문맥에 포함하지 않는다.

조건을 바꾸면 이전 해석을 현재 조건에 붙이지 않는다. 조회와 AI의 조건·as_of/data_updated_at·generation이 다른 경우 다시 요청한다. 같은 generation도 원천 변경으로 drift될 수 있으므로 상태와 hash를 함께 사용한다. 새 요청은 캐시 여부와 관계없이 DB 집계를 재검증한다. v1 AI에 브랜드 조건을 빼고 보내지 않는다.

브랜드 소속은 가맹·직영·소규모 체인을 포함하는 추정이다. 실제 가맹/직영 운영·비체인·과거 소속은 미확인이다. non_chain/include를 독립 점포 확정으로 표시하지 않는다. confirmed_only의 엄격 필터0건은 확인 근거가 없는 결과이며 체인 부재를 뜻하지 않는다. pending·drift 안내를 제거하지 않는다.

## 오류·한도

성공·오류 모두 no-store다. 일반 입력/위치 오류는422, DB·집계/메타 불일치는500, 모델 미설정·한도·예산 만료는503 AI_UNAVAILABLE, 선택 검증 실패는503 AI_VERIFY_FAILED다. 오류에서 부분 해석이나 추정 수치를 만들어 표시하지 않는다.

v1/v2는 같은 요청 한도·동시 실행 자원을 사용한다(기본5회/분·50회/일·동시2·20초). 경로를 바꿔 한도를 우회할 수 없다. HTTP 캐시와 별도로 서버 내부 선택 캐시만 사용하며 현재 DB의 동일 조건/자료/프롬프트에만 재사용한다.
