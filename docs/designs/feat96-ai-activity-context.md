# feat#96 AI 해석의 상권 활동 집계 문맥

- 이슈: [#96 AI 해석에 상권 활동 집계 문맥 추가](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/96)
- 브랜치: `feat#96-ai-activity-context` (develop `41475fa` 기준)
- 작업 식별자: BE-32 후속(#68 설계 §범위의 "이력/활동 추가 문맥" 중 활동 부분)
- 작성: Claude Code 설계 → Claude Code 재검토·MD 직접 수정(아래 검토 기록)

## 1. 목적

`POST /api/risk/interpret`는 현재 서버가 재계산한 Risk 참고지표만 AI 입력과 서버 문장에 사용한다. 같은 화면 STEP 02의 상권 활동 분석(`GET /api/market/activity`)은 사용자가 이미 보는 반경 집계인데 AI 해석에는 빠져 있다. 요청 형식을 바꾸지 않고 **같은 조회 조건으로 서버가 활동 집계를 재계산**해 허용된 집계만 문맥과 서버 문장에 추가한다.

## 2. 범위

### 포함

1. 같은 `RiskQuery`(include 제외)로 `ActivityQuery`를 만들고, 같은 READ ONLY REPEATABLE READ 세션에서 기존 `get_activity`를 호출한다.
2. 활동 응답 중 다음만 typed allowlist로 `RiskInterpretContext.activity`에 넣는다.
   - `recent_12m`: period 문자열, opened, closed
   - `by_sub_category[]`: sub_category, open_count, avg_operating_months(nullable)
   - 고정 방법론 enum: event_basis, operating_period_basis, avg 분모/버림 규칙, 연도 비교 미포함
3. Risk·활동 교차 검증(§4). 하나라도 어긋나면 기존과 같은 안전한 500(INTERNAL_ERROR, no-store)이다.
4. 서버 참고 계산 문장을 `official_values`에 추가한다. 모델 선택(favorable/unfavorable/checklist) 구조와 후보 생성 규칙은 바꾸지 않는다.
5. 응답 `indicator_ids`에 활동 식별자 2개(`recent_open_close`, `avg_operating_months`)를 추가한다.
6. 프롬프트 `risk-interpret-v6`(활동 해석 규칙 추가)와 지문 이력, 데이터 버전 hash에 활동 rule_version 포함.
7. README/BE CLAUDE.md(#68 "이력/활동 추가문맥 후속" 서술, #74 SQL 수)/작업계획(1절 현황·새 절) 갱신, [FE AI 요청서](../fe-risk-interpret-api-request.md)에 새 식별자·문장, indicator_ids의 항목 간 비고유성, 알 수 없는 ID를 Risk 지표 조회 실패로 처리하지 않을 것, favorable/unfavorable의 ID 범위는 그대로임을 안내.

### 제외(근거)

| 항목 | 제외 이유 |
|---|---|
| 점포 이력 문맥 | building_key/floor_unit을 요청으로 받아야 하는 계약 변경이며 #68에서 422로 확정한 규칙을 바꾼다. 별도 이슈로 분리한다. |
| 연도별 추이(yearly_trend) | 같은 월일 YTD 연도 비교는 숫자가 많고 "증가/감소 추세" 판정을 유도한다. 이번에는 최근 구간과 T 시점 현황만 쓴다. |
| 추정매출·생활인구 | 활동 API에서도 항상 null/pending이다. include를 보내지 않으며 pending 상태도 문맥에 넣지 않는다(Risk의 pending 안내는 그대로). |
| 활동 기반 유리/불리 후보 | 개업>폐업 같은 비교는 공식 기준이 없는 자체 판정이다. 사실 문장만 제공한다. |
| 요청 스키마 변경 | `{query: RiskQuery}` 그대로. 추가 필드는 계속 422다. |
| FE 저장소 수정 | 사용자 지시(2026-11-12)에 따라 요청서로만 전달한다. |

### 선행 조건

- #68(AI API)·#74(캐시)·#57(브랜드 분류) develop 반영 완료.
- 실제 개발 DB: 작업계획 3절은 2026-11-11 Docker 로컬 `spoton_dev` 연결 완료로 기록하나, 이 설계 작성 환경에서 접속 가능 여부는 확인하지 않았다. 구현 시작 시 READ ONLY 기본 쿼리로 먼저 확인하고, 불가하면 §10 중단 조건을 따른다.

## 3. 현재 구현과의 연결

| 위치 | 변경 |
|---|---|
| `app/schemas/ai_context.py` | `ContextActivity`, `ContextActivityGroup`, `ContextActivityMethodology` 추가. `RiskInterpretContext.activity` 필수 필드. |
| `app/ai/context.py` | `prepare_risk_interpretation`에서 Risk 다음 `get_activity` 호출, `_extract_activity`로 검증·투영. data_version_hash 입력에 activity rule_version 추가. `ActivityQuery`는 `checked.model_dump(exclude={"include", "include_unknown"})`로 만든다(legacy `include_unknown`을 함께 넘기면 NearbyQuery의 단독 사용 검사에 걸리고, `include`는 Risk enum이라 활동 enum과 다르다). include는 기본 `()`. |
| `app/ai/interpretation.py` | 활동 사실 문장 생성, 세부 업종 라벨. 후보/선택 로직은 그대로. |
| `app/schemas/interpret.py` | `InterpretItem.indicator_ids` 타입을 `list[IndicatorId | ActivityFactId]`로 확장. `InterpretSourcedItem`(favorable/unfavorable)은 상속으로 같이 넓어지므로 `indicator_ids: list[IndicatorId]`로 재정의해 비교 후보의 OpenAPI·계약을 유지한다. `ActivityFactId = Literal["recent_open_close", "avg_operating_months"]`. |
| `app/ai/prompts/risk_interpret/system.md`, `version.py` | 규칙 14를 목록 13 바로 뒤(「답변 형식」 앞)에 추가, v6 지문. |
| `app/services/risk_interpret.py` | `SELECTION_CACHE_RULE`만 `selection-current-validation-v2`로 올린다. AI 캐시 key는 이미 context_hash·data_version_hash·payload·prompt 지문을 포함하므로 활동 문맥·v6만으로도 자동으로 다른 key가 된다. 저장값(선택 ID·모델명)의 의미는 바뀌지 않으므로 이 상수 변경은 필수가 아닌 방어적 분리다. 그 외 로직 변경 없음. |

활동 계산 함수(`get_activity`)는 수정하지 않는다. 같은 세션 안에서 두 번째 서비스 호출이므로 SQL 직전 deadline 검사 listener(#68)가 그대로 적용된다. 예외 경로(코드 대조): `get_activity`는 ValueError/TypeError만 `AppError(INTERNAL_ERROR, NO_STORE)`로 바꾸고 SQLAlchemyError·listener의 `LlmError(TIMEOUT)`은 그대로 올린다. `prepare_risk_interpretation`은 AppError·LlmError·SQLAlchemyError를 잡지 않으므로 각각 500(no-store) / `read_only_session`이 SQLAlchemyError를 500 no-store로 변환 / `interpret_risk`가 LlmError를 503 AI_UNAVAILABLE로 처리한다. 즉 Risk와 같은 결과 코드가 유지되며 새 except를 추가하지 않는다.

Risk 캐시 적중 시에도 활동은 캐시 없이 재계산된다. Risk 캐시 key가 `pg_current_snapshot()`을 포함한 snapshot 지문이므로(#74 `risk_cache.SNAPSHOT`) 적중한 Risk는 현재 세션과 같은 가시 데이터에서 계산된 값이고, 활동도 같은 세션에서 계산되므로 §4 불변식이 성립해야 한다. TRUNCATE/rewrite 등 #74의 비MVCC 예외 범위는 기존과 같다.

## 4. 교차 검증 규칙

입력은 같은 세션의 Risk 응답(R)과 활동 응답(A)이다. 아래가 모두 참이어야 한다.

1. `A.error is None`, `A.data`가 `MarketActivity`로 재검증된다.
2. 기준: `A.meta.as_of == R.meta.as_of == context.as_of`, `A.meta.data_updated_at == R.meta.data_updated_at`, `A.meta.space == f"radius_{radius}m"`.
3. 원천: 두 응답의 `data_version.stores_batch_ids` 집합과 `map_version`이 같고, A의 `rule_version == "market-activity-license-ytd-v1"`, `source == ["R5","R6"]`, `collected_at is None`, `denominator is None`.
4. 분류: `A.meta.franchise_classification == R.meta.franchise_classification`, `data_version.brand_mapping` 유무·값이 같다.
5. 업종 범위: `[g.sub_category for g in A.by_sub_category]`가 문맥의 sub_category와 같은 집합이고 중복이 없다(활동은 고정 순서 korean→chinese→japanese→western, 문맥은 알파벳 정렬 — 집합 비교 후 문맥 순서로 정렬해 저장).
6. 수치 정합:
   - `sum(open_count) == competitor_count.value`
   - `A.recent_12m.period == closure_rate_12m.period`
   - `closure_rate_12m.denominator == sum(open_count) + A.recent_12m.closed`
   - closure_rate_12m.numerator가 있으면(분모 10 이상) `== A.recent_12m.closed`
   - `A.meta.cohort_size == R.meta.cohort_size`
7. 각 그룹: `open_count == 0 ⇔ avg_operating_months is None`(스키마가 이미 검사), avg ≥ 0 정수.
8. `A.data.sales is None and A.data.living_pop is None and A.flags.missing == []`(include 미전송 확인).

**불변식 근거(코드 대조, 재검토 추가)**

- 같은 모집단: 두 서비스 모두 `current_provenance` → `temporal_cohort(query, D)` → `min(open_date)` → `effective_date(D, min, as_of)` → `[*cohort, *attribute_filters(query), open_date <= T]` + `geom IS NOT NULL` + `ST_DWithin(r+0.01)` + `ST_Distance <= r`로 행을 고른다(`risk._get_risk` local, `market_activity._get_activity` values). 입력 query의 좌표·반경·업종·면적·가맹 필드가 같고 같은 스냅샷이면 T와 행 집합이 같다. 따라서 `R.meta.cohort_size(local.cohort_size) == A.meta.cohort_size(len(records))`.
- active: Risk `close IS NULL OR close > T` 개수 = 활동 그룹별 `close is None or close > T` 합계.
- 폐업: Risk `closure_num = count(lower < close <= T)`, 활동 `recent_closed`도 같은 `lower = year_cutoff(T, T.year-1)`·같은 반열림 구간. Risk `closure_den = count(close IS NULL OR close > lower)` = active + closure_num이며 이는 `ReferenceCounts.consistent_counts`가 이미 강제한다. 기간 문자열도 `risk.period()`와 활동 f-string이 같은 형식이다.
- 정당한 데이터에서 깨질 경우: 위 정의상 없음. 다만 활동 `aggregate_activity`는 Risk에 없는 추가 검사(같은 source+license_no 중복, 빈 license_no, 미지원 source)에서 ValueError → 500을 낸다. `uq_stores_source_license_no`·`SUPPORTED_STORES`로 앞의 둘(중복·source)은 막히지만 빈 license_no는 DB 제약으로 확인하지 못했다. 이 경우 기존 `GET /api/market/activity`도 이미 500이므로 새 결함은 아니나, **AI 해석이 Risk만 쓰던 때보다 실패할 수 있는 표면이 늘어난다**는 점을 기록한다.
- 테스트 헬퍼 주의: `tests/ai/context_helpers.response()`의 meta에는 현재 `cohort_size`가 없다(실제 Risk에는 있음). 불변식 6의 cohort_size 비교를 위해 헬퍼 meta에 `cohort_size=local.cohort_size`를 추가해야 하며, `R.meta.cohort_size`가 없거나 int가 아니면 실패로 처리한다.

검증 실패의 원문(수치·사유)은 예외 메시지·로그에 남기지 않는다. 기존 `_extract_context`와 같이 ValueError → `AppError(INTERNAL_ERROR, NO_STORE)`. `get_activity`의 AppError는 그대로 전파된다(위 §3 예외 경로).

## 5. AI 입력 계약(허용 필드)

```json
"activity": {
  "space": "radius_500m",
  "recent_period": "(2025-11-08, 2026-11-08]",
  "recent_opened": 3,
  "recent_closed": 2,
  "groups": [{"sub_category": "cafe", "open_count": 8, "avg_operating_months": 41}],
  "methodology": {
    "event_basis": "validated_license_dates",
    "operating_period_basis": "elapsed_months_of_active_at_as_of",
    "avg_operating_months_rounding": "floor_mean_of_completed_months",
    "yearly_trend_included": false
  }
}
```

- 좌표·점포 식별·상호·건물키·cohort_size 원문 meta·배치 UUID·yearly_periods는 넣지 않는다. 기존 `serialize_context`의 금지 키 검사가 마지막 관문이다.
- `avg_operating_months`는 T 시점 영업 중 기록의 개업 후 경과 완료 개월 평균(버림)이다. 폐업 점포 수명이나 생존 기간이 아니다(#60 계약).

## 6. 서버 문장(official_values 추가분)

숫자는 모두 문맥에 있는 값만 사용해 verifier의 UNKNOWN_NUMBER 검사를 통과해야 한다. "12개월"·"1년"처럼 문맥에 없는 숫자는 쓰지 않는다.

1. `recent_open_close`: `참고 계산: 최근 구간 {period}에 반경 {r}m의 개업 인허가 기록은 {opened:,}건, 폐업 기록은 {closed:,}건입니다.`
2. `avg_operating_months` (그룹마다 1문장, 문맥 순서)
   - open_count>0: `참고 계산: {as_of} 기준 {라벨} 영업 기록 {n:,}건의 개업 후 평균 경과 기간은 {m:,}개월입니다.`
   - open_count=0: `참고 계산: {as_of} 기준 {라벨} 영업 기록이 없어 평균 경과 기간을 산정하지 않았습니다.`
   - 라벨: cafe=카페, korean=한식, chinese=중식, japanese=일식, western=양식

`InterpretItem(text, indicator_ids=[...])`로 Risk 사실 문장 뒤에 붙인다. 문장이 늘어나므로 verifier `max_chars=2000` 안에 드는지 최장 경우(음식점 4그룹, 큰 숫자)를 테스트한다. 같은 문장 반복 검사(REPETITION)는 그룹 라벨이 달라 통과해야 하며, 0건 그룹이 여럿이면 라벨로 구분된다.

**verify_output 대조(재검토 추가, `app/ai/verifier.py`)**

- UNKNOWN_NUMBER: `allowed_numbers`는 문맥의 숫자 값과 문자열 안 숫자를 모두 허용한다. `as_of`(문자열 "YYYY-MM-DD"), `activity.recent_period`, `closure_rate_12m.period`가 문맥에 있으므로 날짜 조각(2026, 11, 8 등; "08"→8)은 허용된다. `{x:,}`의 천 단위 쉼표는 `NUMBER_PATTERN`이 `1,234` 한 토큰으로 읽어 1234로 비교한다. 반경 r은 `radius_m`, opened/closed/open_count/avg는 활동 정수 값으로 허용된다. "개월"·"건"은 숫자가 없어 무관하다. "12개월"·"1년"은 문맥에 12·1이 없을 수 있으므로 쓰지 않는 원칙을 유지한다.
- PERSONAL_INFO: 층·호 `\d+\s*층|\d+\s*호(?!점)` — 문장에 "층"·"호"가 숫자 뒤에 오지 않는다. 도로명 `[가-힣0-9](?<!으)(?:로|길)\s?\d+` — "기록 8건"처럼 "록"은 "로"가 아니며 "로/길" 뒤 숫자 배치가 없다. 전화번호 패턴은 날짜 뒤가 ", "·" 기준"이어서 `0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}`가 성립하지 않는다(기존 Risk 문장도 같은 날짜 형식으로 통과 중). 소수가 없어 좌표 패턴도 무관하다.
- 문장 템플릿을 바꿀 때는 "로 {숫자}", "{숫자}층/호", 0으로 시작하는 연속 숫자를 만들지 않는다. 라벨·조사 변경 시 위 패턴 회귀 테스트를 함께 둔다.
- REPETITION: `SENTENCE_SPLIT`은 마침표(숫자 사이 제외)·줄바꿈으로 나눈다. 그룹 문장은 라벨이 달라 10자 이상 동일 문장이 생기지 않는다. 활동 문장 1과 Risk competitor 문장도 표현이 달라 겹치지 않는다.
- TOO_LONG: 현재 최장 조합(음식점·include 2종·추정 분류·비교 3개·checklist 3개)의 서버 문장은 대략 1,000자 안팎으로 추정되며 활동 5문장(약 300~350자)을 더해도 2,000자 미만이다. 추정치이므로 테스트로 확인한다.
- `indicator_ids` 비고유: `avg_operating_months`는 음식점에서 최대 4개 항목이 같은 ID를 가진다. 기존에는 official_values 항목별 ID가 사실상 유일했으므로 FE가 ID를 React key·Map key로 쓰면 #78의 중복 key 결함과 같은 문제가 생긴다. FE 요청서에 "indicator_ids는 항목 간 유일하지 않음, 배열 순서/인덱스로 렌더링"을 명시한다.

## 7. 프롬프트 v6

`system.md`에 규칙 1개를 추가한다.

> 14. analysis.activity는 반경 안 인허가 기록의 최근 구간 개업·폐업 건수와 기준일 현재 영업 기록의 평균 경과 기간입니다. 평균 경과 기간을 점포 수명·생존 기간·영업 성과로 바꾸지 않고, 개업·폐업 건수 차이로 상권의 성장·쇠퇴를 판정하지 않습니다.

모델 응답 형식(후보 ID 선택)은 그대로라서 선택 schema·후보는 바뀌지 않는다. `PROMPT_VERSION=risk-interpret-v6`, `PROMPT_HISTORY`에 지문 추가(이전 항목 보존).

## 8. 보안·개인정보·외부 API·DB

- 새 외부 호출 없음. LLM으로 가는 값은 반경 집계 정수와 고정 enum뿐이며 개인/점포 식별정보가 없다.
- 소표본 한계: 그룹 open_count=1이면 avg_operating_months가 그 한 점포의 개업 후 경과 개월이 된다. LLM에는 위치·상호가 가지 않고 같은 값을 활동 API가 이미 사용자에게 보여 주므로 추가 노출은 아니라고 판단해 억제하지 않는다. 프롬프트 규칙 7(특정 점포 미지목)을 유지한다.
- 추가 SQL(코드 대조로 정정): `current_provenance` 2(배치 목록·미연결 존재) + 최소 개업일 1 + 좌표 누락 1 + 반경 행 1 + `brand_context` 1 = **6문장**. 기존 SQL 3초 제한·전체 LLM_TIME_BUDGET(기본 20초)·deadline listener 안에서 실행된다. AI 준비 SQL 수는 warm(Risk 캐시 적중) 2→8, cold 9→15(경계 설정 시 judge_market 별도)로 바뀌므로 CLAUDE.md #74의 "AI 준비는 같은 세션에서 최대2SQL" 서술과 README를 갱신한다.
- 반경 행 조회는 1000m·음식점 밀집 지역에서 수천 행을 서버 메모리로 읽을 수 있다. 기존 활동 API와 같은 비용이지만 AI 준비 시간(이전 관측 약 0.6초)에 더해지므로 실제 DB 검증에서 1000m 음식점 조합의 준비 시간을 측정해 기록한다(SLA 아님).
- 활동 행 조회는 반경 내 개별 행(source, license_no, 날짜, 업종)을 서버 메모리로 읽지만 AI 입력·로그에 넣지 않는다.
- DB 모델·migration·의존성·.env/Docker 변경 없음.

## 9. 테스트 계획

### 단위(일반 pytest, DB 불필요)

- `tests/ai/context_helpers.py`에 Risk 고정 응답과 정합하는 합성 활동 응답 `activity_response(q=None, local=None)` 추가. `response()`와 같은 `local` ReferenceCounts에서 파생한다(open_count 합 = local.active, closed = local.closure_num, cohort_size = local.cohort_size, period = 같은 T). `test_interpretation.prepared(local=...)`, `test_context`의 소표본/0분모 케이스처럼 Risk 수치를 바꾸는 테스트가 있으므로 고정값 하나로는 불변식에 걸린다. 같은 헬퍼에서 Risk `response()` meta에 `cohort_size`를 추가한다.
- 기존 context/interpretation/cache 테스트는 `get_activity`도 Mock으로 고정해야 한다. 현재 `test_context`·`test_interpretation`·`test_interpretation_cache`는 `prepare_risk_interpretation(Mock(), ...)`을 직접 호출하며 `get_risk`만 monkeypatch한다. 실제 `get_activity`가 Mock 세션에서 실행되면 `list(Mock)` TypeError → AppError로 전부 실패하므로, **활동 호출을 넣는 커밋 안에서 세 파일을 모두** 고친다(`monkeypatch.setattr(context_module, "get_activity", ...)` 공통 fixture 권장). `test_interpretation`의 `_prepare` 대체 테스트는 영향 없다.
- 허용 필드: 활동 문맥 키 집합, 금지 키·배치 UUID·cohort_size·yearly 미포함, canary 문자열이 prompt에 없음.
- 교차 검증 실패 각각(as_of, data_updated_at, batch, rule_version, 분류, 업종 집합, 합계≠competitor, denominator 불일치, numerator 불일치, cohort_size, sales≠None, activity error 응답) → AppError, 예외 context에 canary 없음.
- `get_activity` 호출 인자: 같은 세션, include=(), RiskQuery와 같은 좌표·반경·필터·as_of. legacy `include_unknown=true` 요청에서도 ActivityQuery 생성이 실패하지 않고 두 unknown 토글이 같은 값으로 전달된다.
- 예외 전파: `get_activity`가 AppError → 500 no-store, `LlmError(TIMEOUT)` → 503 AI_UNAVAILABLE(API 레벨), Risk 성공 후 활동 실패 시 공급자 호출 0회.
- 서버 문장: 카페 1그룹, 음식점 4그룹(0건 포함), 큰 수(천 단위 쉼표), 연초/월말 날짜(예: as_of 01-05, 02-29)의 기간 문자열 → verify_output 통과, `indicator_ids` 값, 2000자 이내. 최장 조합은 음식점·include 2종·추정 분류·비교 후보 3개·checklist 3개로 구성한다.
- 기존 단언 갱신: `test_interpretation`의 `len(output.official_values) == 4`(카페 기준 4+2=6), 응답 스키마에서 favorable/unfavorable의 indicator_ids가 IndicatorId만 허용하는지.
- hash: 활동 값이 바뀌면 context_hash 변경, 활동 rule이 바뀌면 data_version_hash 변경.
- 프롬프트 v6 지문 테스트(기존 test_prompts 갱신), 응답 OpenAPI의 indicator_ids enum에 새 값 존재.
- API 레벨: 기존 interpret 200/503/422 시나리오가 활동 포함 상태에서 그대로 통과.

### 통합(격리 PostGIS, CI)

- `tests/integration/test_ai_context.py`: 실제 서버 재계산에서 활동 문맥이 독립 `get_activity` 결과와 같고 교차 검증이 통과하는지, 빈 업종(0건)·과거 월.
- `tests/integration/test_analysis_flow.py`의 기존 AI 시나리오는 그대로 통과하지 않는다. 119행 `official_values`의 indicator_ids 집합 == Risk fact ID 집합 단언이 새 활동 ID 때문에 깨지므로, 응답 ID 추가 커밋에서 "Risk fact ID ∪ {recent_open_close, avg_operating_months}"로 갱신하고 활동 문장 수치가 같은 흐름의 `/api/market/activity` 응답과 같은지 추가한다(필수 함수 10종 유지).
- 이 작업 환경에서 Docker 사용 가능 여부를 먼저 확인한다. 불가하면 통합 테스트는 CI에서 실행하며 로컬 미실행 사유를 PR에 적는다.

### 실제 개발 DB(읽기 전용)

- 실제 2~3개 위치·카페/음식점(1000m 음식점 1조합 포함)에서 prepare → 활동 문맥이 `/api/market/activity` 응답과 같은지, 교차 검증 통과, 모의 공급자 interpret 200. 캐시 cold/warm 각각의 SQL 수(15/8 예상)와 준비 시간을 기록한다. 실제 LLM 호출은 0회 기본.
- 전후 head·모델 차이·기존 테이블 행/hash 보존 확인은 기존 AI 작업(#68/#74)과 같은 READ ONLY 절차를 따른다.

## 10. 중단 조건과 완료 조건

- **중단**: 실제 개발 DB에 접속할 수 없으면 §9의 실제 DB 검증 단계에서 멈춘다. 구현·단위 검사·커밋·푸시까지 진행하고, PR은 실제 DB 검증 후 만든다. 작업계획 3절 절차대로 ① 진행 내용 보존·원인/필요 조건 보고(비밀값 미출력) ② 실행 큐에서 이 작업 앞에 `실제 개발 DB 연동` 선행 작업 추가(기존 항목 재사용) ③ 이후 큐 전체 중단(DB 무관 작업도 우회 진행 금지)을 따른다. CI 통과·mock·격리 DB를 실제 DB 검증으로 대체하지 않으며 이슈 완료로 표시하지 않는다.
- **중단**: 교차 불변식이 실제 데이터에서 성립하지 않으면 계산 정의 차이를 조사·보고하고 규칙을 임의로 완화하지 않는다.
- **완료**: 단위/통합/실제 DB 검증, ruff/format/mypy, 비밀값 검사, 문서·FE 요청서 갱신, PR CI/CodeQL 통과 후 develop Squash.

## 11. 기능별 커밋 계획

각 커밋은 일반 pytest와 (CI의) 격리 통합 테스트를 모두 녹색으로 유지해야 한다. 재검토에서 원안의 커밋 2·3이 다른 테스트를 깨뜨리는 문제를 발견해 파일 배치를 조정했다.

1. `docs(be): AI 활동 문맥 설계와 Claude 검토 기록` — 이 문서
2. `feat(ai): 상권 활동 집계의 AI 문맥 추출과 교차 검증` — schemas/ai_context, ai/context, context_helpers(activity_response·Risk meta cohort_size)·test_context, **test_interpretation·test_interpretation_cache의 get_activity Mock**(없으면 Mock 세션으로 실제 get_activity가 실행되어 실패), integration/test_ai_context의 활동 문맥 검증
3. `feat(ai): 활동 참고 계산 문장과 응답 식별자 추가` — interpretation, schemas/interpret(InterpretSourcedItem 재정의 포함), test_interpretation(+cache) 단언 갱신, **integration/test_analysis_flow 119행 ID 집합 단언 갱신**
4. `feat(ai): 활동 해석 규칙을 담은 프롬프트 v6` — system.md, version.py, test_prompts, SELECTION_CACHE_RULE
5. `test(ai): 활동 문맥 격리 PostGIS 통합 검증 보강` — 빈 업종·과거 월·필터 조합 등 추가 통합 케이스(기존 단언 수정은 2·3에서 완료)
6. `docs(be): AI 활동 문맥 계약과 FE 요청서 갱신` — README, CLAUDE.md, be-work-plan, fe-risk-interpret-api-request

커밋 2에서 활동이 문맥에 들어가고 커밋 4에서 해석 규칙이 추가되므로 중간 커밋은 규칙 없이 활동 값을 모델에 보낸다. develop에는 Squash로 한 번에 반영되므로 허용하되, 실제 LLM 호출 검증은 커밋 4 이후에만 한다.

## 12. Claude Code 검토 기록

### 확인 범위

`app/ai/{context,interpretation,verifier}.py`, `app/ai/prompts/{builder,version}.py`·`system.md`, `app/services/{risk,market_activity,risk_interpret,risk_cache,store_cohort,franchise}.py`, `app/schemas/{ai_context,interpret,market_activity,risk,nearby}.py`, `app/db/dependencies.py`, `tests/ai/context_helpers.py`·`test_context`·`test_interpretation(_cache)` 호출 방식, `tests/integration/test_ai_context.py`·`test_analysis_flow.py`, CLAUDE.md #60/#68/#74/#76, 작업계획 3·8·10절을 실제로 읽고 대조했다. 코드·다른 문서·Git은 수정하지 않았다.

### 수정 사항과 이유

1. §4 불변식: SQL 정의를 대조해 성립 근거를 추가했다. 두 서비스는 같은 cohort/T/필터/거리 조건을 쓰고, `closure_den = active + closure_num`은 `ReferenceCounts` 검증기가 이미 강제한다. 원안의 판단은 맞았다. `map_version`·`denominator` 비교를 추가하고, 활동의 추가 검사(빈 license_no 등)로 AI 실패 표면이 늘어나는 점과 테스트 헬퍼 Risk meta에 `cohort_size`가 없다는 점을 기록했다.
2. §3: ActivityQuery를 만들 때 `include`와 legacy `include_unknown`도 함께 빼야 한다는 점을 적었다. 함께 넘기면 NearbyQuery의 단독 사용 검사에 걸린다. 예외 전파 경로(AppError 500, SQLAlchemyError→500, LlmError→503)를 코드 기준으로 적었다. "risk_interpret.py 변경 없음"과 SELECTION_CACHE_RULE 변경이 서로 맞지 않아, 상수만 바꾸며 필수가 아니라 방어적 분리라고 정정했다. 캐시 적중 시 일관성 근거로 `pg_current_snapshot()`을 명시했다.
3. §3/§6: `InterpretItem`을 넓히면 상속 관계인 `InterpretSourcedItem`(favorable/unfavorable)도 같이 넓어진다. 그래서 IndicatorId로 재정의하도록 했다. `avg_operating_months` ID가 여러 항목에 반복되므로 FE key 중복 위험(#78과 같은 유형)을 요청서 항목에 추가했다.
4. §6: verify_output의 숫자·개인정보·반복·길이 패턴별 통과 근거를 추가했다. 천 단위 쉼표, 날짜 조각, "개월", 층·호, 도로명, 전화번호 패턴을 확인했다. 템플릿을 바꿀 때 지킬 금지 형태도 적었다.
5. §8: 추가 SQL은 5문장이 아니라 6문장이다(`current_provenance`가 2 SQL). AI 준비는 warm 2→8, cold 9→15 SQL이 된다. 1000m 음식점 조합의 행 메모리·시간은 실측 대상으로 두었다. 소표본(open_count=1) 평균의 노출 판단도 기록했다.
6. §9/§11: 원안대로 커밋하면 커밋 2에서 `test_interpretation`·`test_interpretation_cache`가 실패한다(Mock 세션에서 실제 get_activity 실행). 커밋 3에서는 `test_analysis_flow` 119행 ID 집합 단언과 `len(official_values)==4`가 실패한다. 그래서 수정 파일을 해당 커밋으로 옮겼다. 활동 헬퍼는 Risk의 `local`에서 파생하도록 했다.
7. §2/§10: "이 PC에 DB/Docker 없음"은 작업계획 3절(2026-11-11 로컬 DB 연결 완료)과 맞지 않고 확인할 수도 없다. 그래서 "구현 시작 시 확인"으로 바꿨다. 중단 절차는 작업계획 3절의 선행 작업 추가·큐 전체 중단까지 명시했다.

### 의도적으로 유지한 것

- 활동 문맥 범위(최근 구간·T 시점 그룹만), yearly_trend·이력 문맥 제외, 활동 기반 유리/불리 후보 없음.
- 문장 템플릿 원문과 그룹별 1문장 구성(가독성 우선. ID 비고유는 FE 안내로 처리).
- `A.error is None` 검사: `get_activity`는 오류 응답을 반환하지 않지만 방어적으로 둔다.
- SELECTION_CACHE_RULE v2 변경(필수는 아니지만 무해).
- 소표본 평균 억제 없음(활동 API가 이미 같은 값을 공개).

### 남은 한계·미해결 질문

- FE가 알 수 없는 indicator_ids나 중복 ID를 어떻게 처리하는지는 FE 저장소를 읽지 않아 확인하지 못했다. FE가 ID로 Risk 지표를 엄격하게 조회하면 FE 반영 전 배포 시 화면 오류 가능성이 있으므로, 구현 후 FE 요청서와 함께 담당자 확인이 필요하다.
  - **후속 확인(작성자, FE develop `88c3aa6` 읽기 전용 대조)**: `AiResultCard`는 목록 key로 문장 `text`를 쓰고, `EvidenceChips`는 항목 안 ID 배열에만 `key={id}`를 쓴다. 활동 문장은 업종 라벨로 서로 다르고 항목당 ID가 1개라 중복 key·화면 오류는 생기지 않는다. 다만 `INDICATOR_NAME`에 없는 ID는 칩에 영문 코드가 그대로 보이고(`?? id`), 칩을 눌러도 이동할 지표 카드가 없다. FE 요청서에 두 ID의 칩 라벨과 이동 없는 칩 처리를 요청한다. FE 저장소는 수정하지 않는다.
- 2,000자 상한 여유는 추정치이며 테스트로 확정해야 한다.
- 빈 license_no 행의 실제 존재 여부(활동 500 유발)는 DB 제약으로 확인하지 못했다. 실제 DB 검증 때 0건인지 확인을 권장한다.
- 실제 DB·Docker 사용 가능 여부와 1000m 조합 준비 시간은 미확인이다.
