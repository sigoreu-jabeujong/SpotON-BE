# feat#98 AI 해석의 점포 이력 문맥

- 이슈: [#98 AI 해석에 점포 이력 문맥 추가](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/98)
- 브랜치: `feat#98-ai-history-context` (develop `bb30668`, #96/PR97 병합 후)
- 작업 식별자: BE-32 후속(#68 설계의 "원본 선택 이력 문맥", #96에서 분리)
- 작성: Claude Code 설계 → Claude Code 재검토·MD 직접 수정(아래 검토 기록)

## 1. 목적

AI 해석은 현재 Risk 지표와 반경 활동 집계(#96)만 사용한다. 사용자가 STEP 02에서 보는 "이 건물·이 자리의 과거 점포 이력"은 빠져 있다. 요청에 **선택 이력 문맥**(`history.building_key`, `history.floor_unit`)을 받아 서버가 `get_history`를 같은 세션에서 재계산하고, 식별정보 없는 건수·기간 범위 집계만 AI 문맥과 서버 사실 문장에 추가한다.

## 2. 범위

### 포함

1. 요청: `{query: RiskQuery, history?: {building_key: str, floor_unit?: str | null}}`. `history`가 없으면 #96과 같은 결과(문맥 `history=null`, 이력 문장 없음). 최상위 `building_key`/`floor_unit`·`history` 안의 추가 필드는 422(기존 `extra=forbid` 유지).
2. 입력 검증은 기존 `HistoryQuery`(canonical building_key·floor_unit 정규화)를 재사용한다. category는 `query.category`로 채운다(이력 API와 같이 필터가 아닌 진단 맥락이며 `get_history`는 category를 쓰지 않는다). 모든 형식 오류는 **요청 검증 단계**에서 422가 된다(§3).
3. 위치 정합성: `SUPPORTED_STORES`와 같은 조건이고 `building_key`가 같으며 `geom IS NOT NULL`인 점포 중, 요청 좌표와의 최소 geography 거리(`ST_Distance(geom::geography, point, true)`, 반올림·여유값 없음)가 `HISTORY_MAX_DISTANCE_M = 300` 이하여야 한다. 아니면 422 INVALID_PARAM(no-store). 좌표 확보 점포가 없는 건물(이력 0건 포함)은 검사를 생략한다. 기준을 `query.radius`가 아닌 고정 300m(가장 작은 반경 선택값)로 둔 이유와 한계는 §2.1.
4. 같은 READ ONLY 세션에서 `get_history(session, HistoryQuery)` 재계산 후 Risk와 교차 검증(§4).
5. 허용 집계(§5)만 `RiskInterpretContext.history`에 넣는다. 상호·관리번호·원천·건물키·층호수·개폐업일 원문은 넣지 않는다.
6. 서버 참고 계산 문장과 응답 식별자 `building_history`, `same_spot_history` 추가(§6). 상세 위치 미입력·불완전, 이력 0건, 최신 자료 기준 안내는 `missing_data`.
7. 프롬프트 `risk-interpret-v7`(규칙 15), data_version_hash에 이력 rule_version(이력 있을 때), 선택 cache rule `selection-current-validation-v3`.
8. README/BE CLAUDE.md(#68·#96 절의 "building_key/floor_unit 422·이력 문맥 후속" 문구 포함)/작업계획, FE AI 요청서(27·52행 등) 갱신.

### 2.1 위치 정합성 규칙의 근거와 한계

- 목적은 **문장의 "이 건물"이 분석 지점의 건물이라는 의미 정합성**이다. 접근 통제가 아니다. 같은 건물 이력은 `GET /api/stores/history`로 이미 공개되므로 이 검사가 정보 노출을 막지는 않는다.
- `query.radius`(최대 1000m)를 쓰면 1km 떨어진 건물 이력을 "이 건물"로 서술할 수 있다. FE는 같은 geocode 결과의 좌표와 building_key를 보내므로 고정 300m로도 정상 요청은 통과해야 한다. 작성자 실측(좌표 점포가 있는 136,822개 건물키 중 점포 간 거리 300m 초과 3개)은 **점포 간 분산**이다. geocode 좌표와 가장 가까운 점포의 거리 분포는 아니므로 실제 DB 검증에서 따로 측정한다(§9). 정상 요청이 거절되면 기준을 완화하지 않고 중단·보고한다(§10).
- "가장 가까운 점포" 기준이므로 큰 필지(점포가 넓게 퍼진 건물)에도 관대하다. 300m 안의 이웃 건물 키를 보내면 통과한다. 이 검사는 건물 동일성의 증명이 아니라 개연성 검사다.
- 좌표 점포가 없는 건물은 검증할 수 없어 통과한다(이력 0건 건물은 정상 결과이므로 거절할 수 없다). 이 경우 "이 건물" 서술은 요청 키를 그대로 믿는다. 실제 DB에서 이력은 있으나 좌표 점포가 0인 건물키 수를 측정해 기록한다.
- 불일치를 조용히 버리지 않고 422로 거절한다. 받은 필드를 무시하지 않는다는 #68 원칙과 "불명확한 입력을 정제해 통과시키지 않는다"는 #66 원칙을 따른다. 422도 `limiter.acquire()` 이후이므로 분당·일일 앱 한도 1회를 소비한다(기존 Risk 422와 동일).

### 제외(근거)

| 항목 | 이유 |
|---|---|
| 이력 기반 유리/불리 후보·"폐업이 잦은 자리" 판정 | 공식 기준 없는 자체 판정. 사실 문장만 제공 |
| 이력에 Risk 필터(area·franchise·sub_category·as_of) 적용 | 이력 API 계약(#36)상 지원 업종 전체·최신 자료 기준. 바꾸지 않고 문장에 기준을 밝힌다 |
| 개별 점포 목록/상호를 AI로 전송 | 개인·점포 식별 위험. 집계만 |
| 이력 API(`GET /api/stores/history`) 변경 | 없음 |
| FE 저장소 수정 | 요청서로만 전달 |

## 3. 현재 구현과의 연결

| 위치 | 변경 |
|---|---|
| `app/schemas/interpret.py` | `InterpretHistory(building_key: str = Field(min_length=1, max_length=255), floor_unit: str \| None = Field(default=None, max_length=100))`(InterpretModel 상속: extra=forbid·strict·hide_input). field validator는 `HistoryQuery.canonical_key`/`canonical_detail`을 그대로 호출한다. `InterpretRequest.history: InterpretHistory \| None = None`과 after `model_validator`에서 `HistoryQuery(building_key, floor_unit, category=query.category)`를 만들어 `PrivateAttr`로 보관하고 `history_query()`로 꺼낸다. `HistoryFactId = Literal["building_history", "same_spot_history"]`를 `InterpretItem.indicator_ids`에만 추가(`InterpretSourcedItem`은 IndicatorId 유지) |
| `app/routers/interpret.py` | `interpret_risk(resources, body.query, body.history_query())` |
| `app/services/risk_interpret.py` | `interpret_risk(..., history: HistoryQuery \| None = None)`, `_prepare(resources, query, deadline, stop, history)`. `asyncio.to_thread`에 **위치 인자**로 넘긴다(기존 테스트의 `lambda *args: p` 패치 호환). AI cache key에 별도 항목 추가 없음(이력 집계는 payload/context_hash에 들어감. 건물키 원문은 key에 넣지 않음, §8). `SELECTION_CACHE_RULE` v3 |
| `app/ai/context.py` | `prepare_risk_interpretation(..., history: HistoryQuery \| None = None)`. Risk·활동 다음 `_check_history_location(session, query, history)`(SQL 1개, 단위 테스트에서 monkeypatch 가능한 별도 함수) → `get_history` → `_history(...)` 투영. data_version_hash의 version_json에 이력이 있을 때만 `history_rule_version` 추가 |
| `app/schemas/ai_context.py` | `ContextHistory`, `ContextHistoryMethodology`, `RiskInterpretContext.history: ContextHistory \| None = Field(default=None, repr=False)` |
| `app/ai/interpretation.py` | 이력 사실 문장·missing 안내(`_history_facts`) |
| `app/ai/prompts/...` | 규칙 15, v7 지문 |

**요청 검증 경로(DB 접속 전 422)**: `InterpretRoute`에서 `strict_body` 의존성(쿼리 인자·16KiB·중복 키·NaN)이 먼저 실행되고, 본문 모델 검증 실패는 `RequestValidationError` → `AppError(INVALID_PARAM)`(로그 없음, no-store)가 된다. 핸들러는 그 뒤에 실행되므로 DB 세션을 열지 않는다. HistoryQuery 생성까지 모델 검증 안에서 끝내야 한다. 서비스에서 HistoryQuery를 다시 만들면 `ValidationError`(ValueError 하위)가 `prepare_risk_interpretation`의 `except (ValueError, ...)`나 `interpret_risk`의 `except (ValueError, TypeError)`에 잡혀 **500**이 된다. strict 모드와의 호환: 두 필드가 JSON 문자열/null이라 strict로 문제없고, HistoryQuery 자체는 strict가 아니지만 이미 검증된 str을 받는다. `canonical_detail`은 값을 정규화하므로 HistoryQuery에는 정규화된 floor_unit이 들어간다. geocode(`kakao_local`)도 같은 `build_from_parts`/`parse_floor_unit` 결과를 내므로 geocode 출력을 그대로 보내면 통과한다(#76 흐름 테스트가 같은 값을 이력 API로 이미 검증). 빈 문자열 floor_unit은 422이므로 FE는 null을 보낸다.

**위치 불일치 422 경로**: DB 조회 후 판단하므로 `prepare_risk_interpretation` 안에서 `raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)`를 **직접** 올린다. `AppError`는 `Exception` 하위이고 ValueError가 아니므로 기존 `except (ValueError, TypeError, AttributeError, PromptError)`에 잡히지 않는다. `interpret_risk`의 except들(AiVerifyFailedError·TimeoutError·LlmError·ValueError·TypeError)도 통과해 `InterpretRoute`의 `except AppError: raise`로 422가 된다. pydantic validator나 `_extract_context`/`_history` 안에서 ValueError로 바꿔 올리면 500이 되므로 금지한다. 교차 검증 실패(§4)는 반대로 ValueError → 500이다. `get_history` 안의 `AppError(INTERNAL_ERROR)`(브랜드 분류 불일치)와 SQL 오류는 기존 활동과 같은 500, `before_cursor_execute` 검사의 deadline은 503이다.

## 4. 교차 검증(Risk R ↔ 이력 H)

1. `H.error is None`, `H.data`를 `StoreHistory`로 재검증.
2. `H.meta.data_updated_at == R.meta.data_updated_at`이고 None이 아니다. `H.meta.as_of == H.meta.data_updated_at`(get_history는 둘 다 같은 `reference`로 채운다).
3. `H.meta.data_version.stores_batch_ids` 집합(중복 없음)·`map_version` == R의 값. 이력 rule_version == `store-history-calendar-months-v1`.
4. `H.meta.franchise_classification == R.meta.franchise_classification`, `data_version.brand_mapping` 동일.
5. `H.data.total == len(H.data.stores) == H.meta.denominator`.
6. floor_unit이 없으면 모든 행의 location_match가 `unverified`여야 한다. floor 또는 unit이 없는 floor_unit이면 `same_spot` 행이 없어야 한다(`location_match`의 정의).
7. 집계 합 불변식(§5)은 `ContextHistory` 검증기가 강제한다.

근거와 한계: `get_history`와 `current_provenance`는 같은 배치 선택 쿼리(SUPPORTED_STORES 점포가 있는 배치)를 같은 REPEATABLE READ 스냅샷에서 실행하므로 2~5는 구조상 항상 성립한다. 방어적 검사이며 실패는 코드 회귀를 뜻한다. `get_history`는 고아 점포(배치 미연결)·무효 배치를 거절하지 않지만, 이 경로에서는 `get_activity`가 매번 `current_provenance`를 실행해 그런 상태면 이미 500이다(Risk 캐시 적중 시에도 활동 재계산이 수행됨). 따라서 두 결과가 정상적으로 갈라지는 경우는 없다. 이력은 T(as_of)와 무관한 최신 자료 기준이므로 R의 as_of와는 비교하지 않는다. 불일치는 원문 없는 500/no-store다.

## 5. AI 입력 계약(허용 필드)

```json
"history": {
  "basis": "latest_data_all_supported_categories",
  "data_updated_at": "2026-11-08",
  "floor_unit_provided": true,
  "same_spot_comparable": true,
  "total": 5,
  "same_category": 3,
  "same_spot": 2,
  "same_building": 2,
  "unverified": 1,
  "same_spot_open": 1,
  "same_spot_closed": 1,
  "same_spot_other": 0,
  "same_spot_closed_period_count": 1,
  "same_spot_closed_months_min": 14,
  "same_spot_closed_months_max": 14,
  "methodology": {
    "period_basis": "completed_calendar_months",
    "same_spot_rule": "floor_and_unit_match_with_verified_location",
    "filters_applied": false
  }
}
```

- 모든 수는 `HistoryStore` 필드에서 파생한다. `same_spot`/`same_building`/`unverified`는 `location_match`, `same_spot_open/closed/other`는 same_spot 행의 `store_status`, `same_category`는 `category == query.category`.
- `same_spot_comparable`: 정규화된 floor_unit을 `parse_floor_unit`으로 읽어 floor와 unit이 **모두** 있을 때만 true. `location_match`는 둘 다 있어야 same_spot을 낼 수 있다. `"2층"`처럼 층만 있으면 floor_unit_provided=true여도 같은 자리 판단이 불가능하다.
- `same_spot_closed_*`: same_spot이면서 closed이고 `operating_period_status=fact`인 기록의 수와 `operating_months` 최소·최대. 해당 기록이 없으면 min/max=null(0으로 만들지 않음). 실제 0개월은 0.
- `data_updated_at`은 문맥 최상위 `data_updated_at`과 같아야 한다.
- 검증기 불변식: `same_spot + same_building + unverified == total`, `same_category <= total`, `same_spot_open + same_spot_closed + same_spot_other == same_spot`, `0 <= period_count <= same_spot_closed`, period_count=0 ⇔ min/max=null, `min <= max`, `floor_unit_provided=false`이면 `same_spot_comparable=false`·`same_spot=same_building=0`·`unverified=total`, `same_spot_comparable=false`이면 `same_spot=0`.
- 원문 행·날짜·상호·관리번호·원천·건물키·층호수는 넣지 않는다. 금지 키(`building_key`, `floor_unit`, `name`, `license_no`)는 `serialize_context`가 다시 막는다(정확한 키 일치 검사). `floor_unit`이라는 키 자체가 금지 키라 문맥에 쓰면 ValueError이므로 `floor_unit_provided`처럼 짓는다. `status`·`id` 키는 넣지 않는다(verifier의 pending 판정과 섞이지 않도록).
- `history=None`이어도 `RiskInterpretContext` JSON에 `"history": null`이 새로 생기므로 이력 없는 요청의 context_hash·payload도 #96과 달라진다(프롬프트 v7로 어차피 캐시가 바뀜). 응답 구조는 같다.

## 6. 서버 문장

숫자는 문맥 값만 쓴다(날짜 D는 `data_updated_at` 문자열에서 2026·11·08이 허용됨). 문장 순서는 Risk 사실 → 활동(#96) → 이력이다.

- `building_history`(total>0):
  - floor_unit 있음: `참고 계산: {D} 최신 자료 기준 이 건물의 음식점·카페 인허가 기록은 {total:,}건이며, 같은 자리로 확인된 기록 {same_spot:,}건, 같은 건물의 다른 위치 {same_building:,}건, 위치 미확인 {unverified:,}건입니다.`
  - floor_unit 없음: `참고 계산: {D} 최신 자료 기준 이 건물의 음식점·카페 인허가 기록은 {total:,}건입니다.` (이 경우 모든 행이 정의상 unverified라 분해를 쓰면 "같은 자리 0건"으로 오해된다)
- `same_spot_history`(same_spot>0):
  - 폐업 0건: `참고 계산: 같은 자리 기록 중 영업 중 {open:,}건, 폐업 0건입니다.`
  - 기간 있음: `참고 계산: 같은 자리 기록 중 영업 중 {open:,}건, 폐업 {closed:,}건이며, 영업 기간을 확인한 폐업 기록 {n:,}건의 영업 기간은 {min:,}~{max:,}개월입니다.` (min==max이면 `{min:,}개월`)
  - 기간 없음(closed>0, n=0): `참고 계산: 같은 자리 기록 중 영업 중 {open:,}건, 폐업 {closed:,}건이며, 폐업 기록의 영업 기간은 확인되지 않았습니다.`
  - other>0이면 `, 기타 상태 {other:,}건`을 폐업 뒤에 넣는다.
- `missing_data`:
  - 이력 0건(total=0, 이력 사실 문장 없음): `{D} 최신 자료 기준 이 건물에서 확인된 음식점·카페 인허가 기록이 없습니다.` reason `history_no_records`. 이때 아래 상세 위치·공통 안내는 넣지 않는다.
  - floor_unit 미입력(total>0): `상세 위치(층·호수)가 없어 같은 자리 기록 여부는 판단하지 않았습니다.` reason `history_floor_unit_missing`
  - floor_unit 있으나 층·호수 중 하나만 있음(total>0): `입력한 상세 위치에 층과 호수가 함께 있지 않아 같은 자리 기록 여부는 판단하지 않았습니다.` reason `history_detail_incomplete`
  - 이력 있음 공통(total>0): `건물 이력은 요청 기준 시점이 아닌 최신 자료 기준이며 지원 업종 전체 기록입니다. 폐업 원인이나 자리의 성패를 뜻하지 않습니다.` reason `history_latest_data_basis`

verify_output 통과 근거(템플릿을 바꿀 때 지킬 조건):

- 층·호(`\d+\s*층|\d+\s*호(?!점)`): 숫자 바로 뒤에 "층"/"호"가 오지 않는다. "층·호수"·"호수"는 앞에 숫자가 없다.
- 도로명(`[가-힣0-9](?<!으)(?:로|길)\s?\d+...(?!\s*단위)`): "자리로 확인된"처럼 "로" 뒤에 숫자가 오지 않는다. "로/길" 바로 뒤에 숫자를 두지 않는다. 특히 천 단위 쉼표 수(`로 1,234건`)는 `(?![\d.])`·단위 lookahead가 쉼표에서 통과해 **매치된다**. "위치 {n}건"은 "치"라 해당 없음.
- 전화번호·좌표·지번·building_key 패턴: 날짜 `2026-11-08`·`~`·쉼표 수로는 매치되지 않는다.
- 반복(10자 이상 같은 문장 2회): 이력 문장끼리, 활동·Risk 문장과 겹치지 않는다. `SENTENCE_SPLIT`은 숫자 사이 마침표를 나누지 않는다.
- 금지 표현: "추천·성공률·폐업할 것입니다" 등 없음.
- 길이: #96 최장 1,169자 + 이력 최장 조합(분해 문장 약 110자 + 같은 자리 약 110자 + missing 약 130자, 큰 수 포함) ≈ 1,550자로 2,000자 안이다. 테스트로 확정한다.

## 7. 프롬프트 v7

> 15. analysis.history는 입력한 건물의 최신 자료 기준 인허가 기록 건수입니다. 요청 기준 시점·필터와 다른 기준이므로 analysis.activity나 지표와 섞어 계산하지 않습니다. 같은 자리 기록의 폐업·영업 기간을 자리의 좋고 나쁨, 폐업 원인, 앞으로의 결과로 해석하지 않고, same_spot_comparable이 false이거나 같은 자리로 확인되지 않은 기록을 같은 자리로 바꾸지 않습니다. analysis.history가 null이면 건물 이력을 언급하지 않습니다.

## 8. 보안·개인정보·DB

- 건물키·층호수는 서버 안에서 조회 조건으로만 쓰고 AI 입력·응답·로그·캐시 key·예외 메시지에 넣지 않는다. 기존 422/500 오류 본문은 원문을 담지 않는다(`hide_input_in_errors`, InterpretRoute는 RequestValidationError를 기록하지 않음).
- AI cache: key에 건물키를 넣지 않아도 이력 집계가 `payload`·`context_hash`로 key에 들어간다. 집계가 같은 서로 다른 건물은 같은 key를 공유할 수 있다. 캐시 값은 Risk 비교 후보 순서·checklist ID와 모델명뿐이고(이력 후보 없음) 렌더링 때 현재 후보로 재검증한 뒤 현재 요청의 문맥으로 문장을 조립하므로, 다른 건물의 수치가 섞이지 않는다. 캐시에 건물 식별 정보가 저장되지 않는다. #74의 시간차 추론 한계는 그대로다.
- 같은 자리 기록이 1건이면 min/max가 그 점포의 기간이 된다. 외부 공급자는 주소·좌표·건물키를 받지 않으므로 점포를 특정할 수 없고, 사용자는 이력 화면에서 이미 같은 값을 본다. 추가 노출은 아니라고 판단한다. 규칙 7(특정 점포 미지목) 유지.
- 추가 SQL: 위치 검사 1 + `get_history`(배치 1·점포 1·브랜드 1) = 4. AI 준비는 history가 있을 때 warm 8→12, cold 15→19 SQL이다. 위치 검사와 점포 조회는 `building_key` 인덱스를 쓴다. 대형 건물(행 수백)의 준비 시간은 실제 DB에서 측정한다.
- 응답 형식: 요청에 선택 필드 추가, 응답 `indicator_ids` 값 2종 추가. 하위 호환(history 생략 시 #96과 같은 응답 구조).

## 9. 테스트 계획

### 단위

- 요청: history 생략/정상/floor_unit null·생략, 비정규 building_key·빈 문자열/비정규 floor_unit·history 안 추가 필드·history 비객체·최상위 building_key(기존 canary 테스트 유지) → 422·no-store(공급자 0회, `_prepare` 0회, canary 비노출).
- 정규화 멱등성: `canonical_detail` 출력값을 다시 넣으면 같은 값(서비스에서 재검증하지 않더라도 회귀 방지).
- `prepare` 호출: history 있으면 위치 검사·get_history가 같은 세션·정규화된 HistoryQuery로 각 1회, 없으면 0회. `use_risk`는 기본으로 `get_history`·위치 검사를 "호출되면 실패" Mock으로 두고, 새 `use_history(...)`(context_helpers `history_response`)로 켠다.
- 위치 검사: 300m 초과 → AppError(INVALID_PARAM)가 `prepare_risk_interpretation`과 API 모두에서 422(500 아님), 좌표 점포 없음 → 통과. 순서상 get_history 미호출.
- 교차 검증 실패(§4 각 항목) → 500, 원문 canary 비노출.
- 집계: same_spot/same_building/unverified/상태/기간 min·max, floor_unit 미입력 시 모두 unverified, 층만 입력 시 comparable=false, 이력 0건, 불변식 위반 모델 거절.
- 문장: verifier 통과(큰 수 1,234 이상, min==max, 기타 상태, 폐업 0, 기간 없음, 0건), 최장 조합(#96 최장 + 이력 최장) 2,000자 이내, 금지 키 미포함, building_key canary가 prompt·응답·로그에 없음.
- hash: 이력 값 변경 → context_hash 변경, history 유무 → data_version_hash 차이.
- OpenAPI: `InterpretItem.indicator_ids`에 이력 ID 포함, `InterpretSourcedItem`에는 미포함(`test_openapi_keeps_comparison_ids_narrow` 확장).
- 프롬프트 v7 지문·규칙 15.
- API: history 포함 200·이력 ID 포함, 위치 불일치 422.

### 통합(격리 PostGIS, CI)

- `test_ai_context`: 합성 건물(같은 자리 폐업·다른 층·미확인·좌표 없는 행)에서 문맥 집계 = 독립 get_history 결과 파생값. 위치 불일치 422는 **좌표가 다른 별도 건물**을 만들어 검사한다(`analysis_flow_helpers`의 행은 모두 같은 CRD 좌표라 이웃 건물 124-4도 같은 위치다).
- `test_analysis_flow`: CI가 이름으로 강제하는 기존 함수 `test_geocode_etl_identity_and_history_scope`를 확장해 geocode 결과의 building_key/floor_unit을 history로 보낸 AI 요청 200과 이력 문장 수치 = 같은 흐름 history 응답을 확인한다(끝의 `provider.calls == 0` 단언 조정). 새 함수를 만들면 workflow `required_flow`도 바꿔야 하므로 기존 함수 확장을 택한다. 기존 history 없는 AI 요청의 `provider.calls == 1`·ID 집합 단언은 그대로 둔다. `test_invalid_conditions_do_not_invoke_provider`에 비정규 history 422를 추가한다.

### 실제 개발 DB(읽기 전용)

- 실제 건물 3~5곳(같은 자리 기록 있음/없음/floor 미입력/층만 입력/이력 0건)에서 문맥 집계 = `/api/stores/history` 파생값, 위치 검사 통과·의도한 300m 밖 422, 모의 공급자 200, SQL 수·준비 시간, 테이블 hash 보존. 실제 LLM 0회.
- 실제 geocode 결과 표본(기존 Kakao 사례 포함)에서 가장 가까운 좌표 점포까지의 거리 분포, 이력은 있으나 좌표 점포가 0인 건물키 수를 읽기 전용 SQL로 측정해 §13에 기록한다.

## 10. 중단·완료 조건

- 위치 검사·교차 검증이 실제 데이터의 정상 요청(geocode 결과를 그대로 보낸 요청)에서 실패하면 규칙을 완화하지 않고 원인을 조사·보고한다.
- 실제 개발 DB가 필요한 단계에서 DB를 쓸 수 없으면 작업계획 3절의 선행 작업 추가·큐 중단 절차를 따른다. CI·mock을 실제 DB 검증으로 대체하지 않는다.
- 완료: 단위/통합/실제 DB, ruff/format/mypy, 비밀값 검사, 문서·FE 요청서, PR CI/CodeQL 후 develop Squash. FE 반영은 담당자 대기로 표시한다.

## 11. 기능별 커밋 계획

각 커밋은 테스트를 녹색으로 유지한다.

1. `docs(be): AI 이력 문맥 설계와 Claude 검토 기록`
2. `feat(ai): 이력 문맥 요청 검증과 위치 정합성·집계 추출` — schemas(interpret 요청·ai_context), ai/context, services/risk_interpret·router 인자 전달(위치 인자), context_helpers(history_response·use_history, use_risk의 미호출 Mock)·test_context·test_interpretation(요청 422)·test_interpretation_cache, integration/test_ai_context. 이 커밋에서는 이력 문장·ID가 없고 문맥만 추가된다.
3. `feat(ai): 이력 참고 계산 문장과 응답 식별자 추가` — interpretation, schemas/interpret `HistoryFactId`, 단위(문장·verifier·길이·OpenAPI), test_analysis_flow
4. `feat(ai): 이력 해석 규칙을 담은 프롬프트 v7` — system.md, version.py, test_prompts, **test_context의 `prompt_version == "risk-interpret-v6"` 단언**, SELECTION_CACHE_RULE
5. `docs(be): AI 이력 문맥 계약과 FE 요청서 갱신` — README(157행), BE CLAUDE.md(#68·#96 문구, #98 절), 작업계획(1절 후속 목록·새 절), FE AI 요청서(history 필드·floor_unit null·위치 422·이력 ID 칩 라벨·missing reason 4종)

## 12. Claude Code 검토 기록

### 확인 범위

`app/routers/interpret.py`(InterpretRoute·strict_body·16KiB), `app/schemas/{interpret,ai_context,stores}.py`, `app/services/{risk_interpret,store_history,store_cohort,franchise,risk,risk_cache,spatial_stores,kakao_local}.py`, `app/ai/{context,interpretation,verifier}.py`, `app/ai/prompts/{builder,version}.py`·`system.md`, `app/core/errors.py`, `app/db/dependencies.py`, `app/routers/stores.py`, `tests/ai/{context_helpers,test_context,test_interpretation,test_interpretation_cache}.py`, `tests/integration/{test_ai_context,test_analysis_flow,analysis_flow_helpers}.py`, CI workflow의 `required_flow`, CLAUDE.md #36/#68/#74/#96, 작업계획 6·8·10절, feat96 설계 검토 기록을 읽고 대조했다. 코드·다른 문서·Git·DB는 건드리지 않았다.

### 수정 사항과 이유

1. §2·§3 요청 검증: "같은 validator 적용"만으로는 HistoryQuery를 어디서 만들지가 비어 있었다. 서비스에서 만들면 ValidationError(ValueError 하위)가 기존 except에 잡혀 422가 아닌 500이 된다. 그래서 `InterpretRequest` model_validator에서 HistoryQuery까지 만들고 PrivateAttr로 넘기도록 확정했다. strict 호환, geocode 출력 호환(같은 `build_from_parts`/`parse_floor_unit`), 빈 문자열 floor_unit 422를 기록했다.
2. §3 위치 422 경로: AppError는 ValueError가 아니어서 `prepare_risk_interpretation`·`interpret_risk`의 except를 통과해 422가 된다는 점을 코드 기준으로 적었다. validator나 `_extract_context` 안에서 ValueError로 올리면 500이 되므로 금지했다. 위치 검사는 단위 테스트에서 Mock 세션으로 돌 수 없어 별도 함수로 분리했다.
3. §2.3·§2.1 위치 규칙: `query.radius`(최대 1000m)를 쓰면 1km 밖 건물을 "이 건물"로 서술할 수 있어 고정 300m로 바꿨다. 대상 집합(SUPPORTED_STORES·geom 존재), 거리식(Risk와 같은 geography·반올림 없음)을 명시했다. 작성자 실측은 점포 간 분산이지 geocode 좌표와의 거리가 아니어서 실제 DB 측정 항목으로 추가했다. 좌표 점포 없는 건물 통과·이웃 건물 통과 한계, 접근 통제가 아니라는 점, 422의 한도 소비를 기록했다.
4. §4: 2~5는 같은 스냅샷·같은 배치 쿼리라 구조상 항상 성립하는 방어 검사라고 정정했다. 고아/무효 배치는 활동 재계산의 `current_provenance`가 먼저 500으로 막으므로(Risk 캐시 적중 시에도) 정상적으로 갈라지는 경우가 없다. 층만/호만 입력 시 same_spot 없음 불변식을 추가했다.
5. §5: `location_match`는 floor와 unit이 모두 있어야 same_spot을 낸다. 층만 입력해도 "상세 호수 미입력" 안내가 나가지 않는 공백이 있어 `same_spot_comparable`을 추가했다. 합 불변식, `status`/`id` 키 금지, `history: null` 추가에 따른 이력 없는 요청의 hash 변화를 기록했다.
6. §6: floor_unit이 없으면 모든 행이 unverified라 원안 문장은 "같은 자리 0건, 다른 위치 0건"으로 읽힌다. 그래서 총계만 쓰도록 바꿨다. 폐업 0건 문장, 이력 0건일 때 다른 안내 생략, 층·호 불완전 안내를 추가했다. verifier 패턴별 통과 근거를 적었고, 특히 `로 1,234건`이 도로명 패턴에 매치된다는 함정을 기록했다.
7. §8: 캐시 공유가 안전한 이유(값은 Risk 후보 ID뿐, 현재 후보 재검증·현재 문맥으로 조립)와 SQL 수(warm 12/cold 19)를 추가했다.
8. §9·§11: `_prepare`를 키워드로 넘기면 기존 `lambda *args: p` 패치가 깨지므로 위치 인자로 넘기도록 했다. 커밋 4에 test_context의 v6 단언을, 커밋 3에 OpenAPI 테스트를 넣었다. 흐름 테스트는 CI `required_flow` 때문에 기존 함수를 확장하도록 했다. 흐름 fixture는 모든 행 좌표가 같아 위치 422 검사는 test_ai_context에서 하도록 옮겼다. 문서 커밋의 구체 위치(README 157행, FE 요청서 27·52행, CLAUDE #68/#96 문구)를 적었다.
9. §7 규칙 15: activity·지표와 섞어 계산하지 않기, comparable=false 처리, history=null이면 언급하지 않기를 추가했다.

### 의도적으로 유지한 것

- 위치 불일치의 422(조용한 무시 대신). #66·#68 원칙에 맞다.
- 좌표 점포 없는 건물의 검사 생략. 이력 0건 건물이 정상 결과이므로 거절할 수 없다.
- 단일 기록 min/max 노출. 외부 공급자는 위치를 모르고 사용자는 이력 화면에서 같은 값을 본다.
- AI cache key에 건물키를 넣지 않는 결정, SELECTION_CACHE_RULE v3(필수는 아니지만 무해).
- 교차 검증 2~5(구조상 성립하지만 비용이 작은 회귀 방어).
- 처리 순서 Risk → 활동 → 위치 → 이력. 위치 검사를 먼저 하면 잘못된 요청의 Risk 계산을 아낄 수 있지만, 기존 Risk 오류(AS_OF_OUT_OF_RANGE 등) 우선순위를 유지하는 쪽을 택했다.

### 남은 한계·미해결 질문

- 고정 300m가 실제 geocode 결과에서 정상 요청을 모두 통과시키는지는 실제 DB 측정 전에는 확인되지 않는다(§9). 큰 필지에서 실패하면 §10에 따라 중단·보고한다.
- 좌표 점포가 없는 건물의 키는 위치 검증 없이 받아들인다. 그런 건물키의 비율은 미측정이다.
- FE가 `history`를 보내는 흐름, 알 수 없는 이력 ID 칩, 새 missing reason 4종의 표시는 FE 담당자 반영 대기다. 이번 검토에서 FE 저장소는 읽지 않았다(#96 후속 확인: 목록 key는 문장 text라 문장이 서로 다르면 중복 key는 없음).
- 2,000자 여유(약 1,550자)는 추정이며 테스트로 확정해야 한다.
- `canonical_detail` 정규화의 멱등성은 코드상 기대일 뿐 이번에 실행 확인하지 않았다. 단위 테스트로 고정한다.

## 13. 구현 기록

- 커밋: 설계 `b8cf372` → 요청 검증·위치·집계 `e389422` → 문장·응답 ID `1e0d105` → prompt v7 `0c5e56c` → 문서(이 커밋).
- 설계 대비 조정
  - `InterpretHistory`에는 별도 field validator를 두지 않고 `InterpretRequest`의 after model_validator에서 `HistoryQuery`를 만든다. `HistoryQuery`의 ValidationError(ValueError 하위)는 pydantic이 바깥 모델 오류로 바꿔 RequestValidationError → 422가 된다.
  - 단위 테스트의 `use_risk`는 `get_history`·`check_history_location`을 "호출되면 실패" Mock으로 두고 `use_history`가 켠다.
- 검증
  - 일반 pytest 1,414 passed, ruff check·format, mypy 154 files. 기존 `test_gemini::test_overall_budget_cancels_retry_sleep` 1회 실패는 단독 5회·전체 재실행 통과(이번 변경 무관, 시간 의존).
  - 이 PC에 Docker가 생겨 별도 포트 일회용 PostGIS(`TEST_DATABASE_URL`, 개발 DB와 분리)로 통합 212 passed(신규 2·흐름 테스트 확장 포함). CI에서도 다시 확인한다.
  - 최장 조합(#96 최장 + 같은 자리 수천 건·기간 4자리·기타 상태) 서버 문장 2,000자 이내 테스트 통과.
  - 실제 개발 DB(READ ONLY): 같은 자리 있음/호수 미입력/층만 입력/최대 건물(1,146건)/기록 0건 5사례 모두 문맥 집계=같은 세션 `get_history` 파생값, comparable 규칙 일치, 건물키·층호수 문자열 AI 입력 미포함. 이력 포함 준비 SQL 캐시 없음 17·cold 19·warm 12, 준비 0.21~0.49초(SLA 아님). 기준 건물 좌표에서 동쪽 약 1km 요청은 `prepare`·API 모두 422. 모의 공급자 API 200·prompt v7·이력 ID 각 1개, 공급자 호출 1회·실제 LLM 0회, 응답·프롬프트 건물키 0건. 검증 전후 11개 테이블 행 md5·건수 동일.
  - 측정: 지원 점포가 있는 건물키 121,182개 중 좌표 확보 점포가 없는 키 11,988개(9.9%, 18,407행). 이 키들은 위치 검증 없이 통과한다(§2.1 한계).
  - 실제 외부 연동(2026-11-13, 팀 키를 로컬 `.env`에 설정 후): 지원 점포 주소 30건(영업 중·층호수 포함, 해시 정렬 표본)을 실제 Kakao geocode에 넣어 30/30 200, 같은 building_key 29/30. geocode 좌표에서 반환 building_key의 가장 가까운 좌표 점포까지 거리 최소 0.2·중앙값 2.6·p90 15.5·최대 103.8m, **300m 초과 0건**으로 고정 300m 기준이 정상 요청을 거절하지 않음을 확인했다. 표본 주소·키·좌표는 출력하지 않았다.
  - 실제 Gemini(`gemini-3.5-flash-lite`) 호출 2회(geocode 결과를 history로 보낸 음식점·카페): 모두 200, verification passed, 재생성 0, prompt v7, building_history·same_spot_history 포함, 약 1.95초, 응답에 건물키·층호수 0건.
