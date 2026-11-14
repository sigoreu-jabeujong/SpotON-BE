# 공식 지표 두 항목 제거와 2010년 이후 연도별 추이 (#140)

2026-11-15 사용자는 서울시 공식 폐업률과 창업위험도 카드/공식 링크를 삭제하고 연도별 개업·폐업 추이에서 2010년 이전을 제외하도록 요청했다. 기준 develop `a987dd8`. 기존 BE 전용 범위를 유지하며 FE 저장소와 Render 실행 배포는 수정하지 않는다.

## 변경 계약

`GET /api/risk`의 `indicators`와 `flags.missing`에서 `official_closure_rate`, `official_risk`를 제거한다. 두 ID를 공용 IndicatorId/REQUIRED_IDS에서도 제거하고 OpenAPI·AI 문맥·AI 응답 참조가 다시 허용하지 않게 한다. 필수 순서는 최근 참고 폐업률, 1년/3년 생존율, 동종업체 수의 네 항목이다. 선택 include인 market_change/day_night_ratio와 경계 후보 정보는 이번 요청과 별개로 유지한다. 공식 원천 적재 테이블이나 통계를 삭제하지 않는다.

링크 전용 상태는 이 두 항목만 쓰므로 RiskIndicator/ContextIndicator에서 link_only를 제거하고 링크 필드는 null만 허용한다. 선택 market_change의 공식 분류/R2 출처, day_night_ratio의 R4, 계산 지표의 R5/R6는 유지한다. AI 누락 문구와 공식 서비스로 유도하는 문장을 제거한다. AI verifier의 범용 금지 규칙은 완화하지 않는다. Risk 규칙 버전을 v2로 올리고 AI data_version literal/테스트 fixture도 맞춰 이전 Risk 캐시와 분리한다.

연도별 하한 상수 `YEARLY_TREND_START_YEAR=2010`을 활동 스키마에 둔다. `YearlyActivity.year`와 AI `ContextYear.year`의 최소값을 함께 바꾸고, aggregate_activity에서 개업/폐업 사건을 각각 판별할 때 2010년 이상만 연도별 카운터와 연도 집합에 넣는다. 2009년 개업·2010년 폐업은 2010년 폐업에 포함한다. 2009년 이전에 개업한 현재 영업 점포도 현재 수·평균 경과 개월·최근 폐업·Risk 코호트에는 계속 포함한다. MIN_OPEN_DATE=1960과 DB 조회 조건은 변경하지 않는다.

연도별 값은 기존 same_month_day_ytd와 윤년 clamp를 보존하며, 실제 사건이 없는 연도는 채우지 않는다. 기준일이 2010년 이전이면 yearly_trend와 yearly_periods만 빈 값이고 다른 집계는 기존 동작이다. yearly_periods는 반환된 연도만 생성한다. 활동 규칙 버전 v2와 프롬프트 v9/새 지문으로 AI 캐시를 구분하고, AI 입력·서버 문단 후보가 2010년 이전 추이를 다시 노출하지 않게 한다.

## 검증

- Risk 응답 네 필수 ID/선택 ID 순서·missing·OpenAPI와 AI 문맥/누락 문구에서 삭제된 ID/링크 부재 확인
- 2009-12-31/2010-01-01, 2009년 개업 후 2010년/최근 폐업, 과거 기준일, 현재 수/평균 개월 보존, 윤년/YTD/gap/정렬 회귀
- 이전 캐시 격리와 AI 문맥 변조 거부, 프롬프트 버전/지문 검사
- 일반 pytest·ruff·mypy 및 격리 PostGIS API/AI 흐름 회귀. 실제 개발/운영 DB는 쓰지 않는다.

## FE 전달과 완료

BE 저장소의 FE 요청 문서에 두 카드와 공식 섹션/링크 삭제, 네 필수 지표에 맞춘 타입 변경, 연도 축 2010년 이상 안내를 남긴다. BE만으로 현재 FE의 하드코딩된 카드가 사라졌다고 주장하지 않는다. API 응답 호환 변경·BE develop 병합·FE 반영 대기·운영 미배포를 구분한다. 원천 지연 #78와 생활인구 근거 #115는 계속 미해결이다.

## 실제 Claude Code 검토

2026-11-15 Claude Code가 기준 코드를 읽기 전용으로 대조했다. 명령·테스트·네트워크·Git은 실행하지 않았고 코드는 수정하지 않았다. 아래 "확인"은 정적 읽기 결과이며 테스트 통과를 뜻하지 않는다. 검색 도구가 없어 AI 관련 테스트 파일(context/interpretation/prompt 지문 테스트)과 AI 캐시 키 조립 위치는 직접 열지 못했다. 구현자가 아래 grep 목록으로 확인해야 한다.

### 결론

계획 방향은 맞다. 착수를 막는 설계 결함은 없다. 다만 다음 B1~B4는 문서 문구를 구체화하거나 구현에서 반드시 지켜야 하는 항목이다. 지키지 않으면 회귀나 AI 문맥 거부(500)가 생긴다.

### 필수 보완(blocker)

- **B1. 연도 집합 필터 위치.** `app/services/market_activity.py:92-96`은 `event <= target`이면 YTD 구간 밖 사건이라도 `years.add(event.year)`를 먼저 실행한다. 그래서 `(2020, 0, 0)` 같은 0건 행이 생기고 `tests/test_market_activity.py:62`가 이 동작을 고정한다. 2010 하한은 `years.add`와 카운터 증가 모두에 적용해야 한다. 조건은 `event is not None and event <= target and event.year >= YEARLY_TREND_START_YEAR`로 한다. 카운터에만 적용하면 2009년 0건 행이 남고, 스키마 `ge=2010`에서 ValidationError가 나 500이 된다. "실제 사건이 없는 연도는 채우지 않는다"는 기존 의미를 유지한다. 2010년 이후라도 YTD 밖 사건만 있는 연도는 계속 0건 행으로 나온다.
- **B2. 레코드가 아니라 사건만 거른다.** AI `_activity`(`app/ai/context.py:309-357`)는 활동 `meta.cohort_size == Risk meta.cohort_size`, `competitor_count == Σopen_count`, `closure.denominator == active + recent_closed`를 강제한다. 따라서 `records` 목록, `cohort_size=len(records)`, `record_profile`, `recent_12m`은 하한 적용 전 전체 레코드로 계산해야 한다. 본문 보존 목록에 **최근 12개월 개업 수(recent_opened)**가 빠져 있어 추가한다. 예를 들어 기준일 2010-03-01이면 최근 구간 `(2009-03-01, 2010-03-01]`의 2009년 개업·폐업은 recent_12m에 그대로 포함하고, yearly_trend에서만 빠진다.
- **B3. Risk 코호트에는 하한을 두지 않는다.** `app/services/risk.py`의 `aggregate_counts`와 조건 목록은 바꾸지 않는다. 과거 기준일(예: 2012) 3주년 생존율 코호트는 2008~2009 개업이고, 최근 폐업률 분모 `closure_den`은 2010년 이전 개업 현재 영업 점포를 포함한다. `YEARLY_TREND_START_YEAR`는 활동 연도별 추이 전용이다. `store_cohort.MIN_OPEN_DATE`(1960), `aggregate_activity`의 1960 검증, SQL 조건에서 이 상수를 쓰지 않는다. 회귀 테스트는 같은 입력으로 하한 도입 전후 `ReferenceCounts`가 같음을 보여야 한다. 최소한 2008·2009 개업을 포함한 2012 기준 생존율 케이스가 필요하다.
- **B4. 공식 서비스 유도 문장이 narrative에도 있다.** 본문은 "AI 누락 문구"만 언급한다. 실제로는 두 곳이다. (a) `app/ai/interpretation.py:52-58,229-230`의 `MISSING_TITLES` 두 키와 `official_risk` 분기. (b) `app/ai/narrative.py:184`의 고정 문단 "공식 창업위험도는 서울시 공식 서비스에서 추가로 확인할 수 있습니다."(문단 3 direct/connected 둘 다). (b)를 빼먹으면 링크 카드는 사라져도 본문은 계속 공식 서비스로 유도한다. 반면 `narrative.py:110-111`의 "서울시 공식 통계가 아닙니다"는 참고지표 면책 문구라 유지한다.

### 확정 결정(파일별)

**Risk 스키마·서비스(필수)**
- `app/schemas/risk.py`: `IndicatorId`와 `REQUIRED_IDS`에서 두 ID를 삭제한다. `RiskIndicator`는 다음과 같이 바꾼다.
  - `official` 판정은 `id == "market_change"`로 한다.
  - 출처는 market_change → `["R2"]`, day_night_ratio → `["R4"]`, 나머지 → `["R5","R6"]`로 한다. R1 분기는 삭제한다.
  - "unverified" 집합은 `{market_change, day_night_ratio}`로 한다.
  - `status`는 `Literal["fact","pending"]`로 한다. link_only 상호 검증 두 줄은 삭제한다.
  - **`link`와 `source_url` 둘 다** `None = None` 타입으로 둔다. 본문은 "링크 필드"라고만 써서 `source_url`이 빠질 수 있으므로 명시한다. 필드 자체는 삭제하지 않고 null로 유지한다. FE가 키 존재를 가정해도 깨지지 않게 하기 위해서다.
  - `Risk.complete_result`와 서비스의 missing 집합을 `{market_change, day_night_ratio}`로 맞춘다.
- `app/services/risk.py`: `OFFICIAL_RISK_URL` 상수를 삭제한다. `pending_indicator`는 RiskInclude 두 값만 받는다(space: market_change=`market`, day_night_ratio=`grid`). 기본 indicators는 `[*refs]`, 선택 include는 그 뒤에 붙인다. `RULE_VERSION = "risk-reference-fixed-anniversary-v2"`로 한다.
- Risk 캐시: `risk_key`에 rule이 들어가므로 v2로 키가 분리된다. 이전 페이로드는 `load_risk`의 새 스키마 검증에 실패해 discard된다. 캐시는 프로세스 로컬이고 프로세스마다 HMAC secret이 새로 만들어지므로, 배포 후에는 이전 엔트리가 남지 않는다. 버전 상향의 실질 목적은 공개 `meta.data_version.rule_version`이 응답 형태 변경을 알리는 것이다. `CACHE_VERSION` 변경은 불필요하다.

**활동 스키마·서비스(필수)**
- `app/schemas/market_activity.py`에 `YEARLY_TREND_START_YEAR = 2010`을 두고 `YearlyActivity.year`를 `ge=YEARLY_TREND_START_YEAR`로 바꾼다. `app/schemas/ai_context.py`의 `ContextYear.year`도 같은 상수를 import해 쓴다. 숫자를 따로 적지 않는다.
- `aggregate_activity`는 B1·B2대로 고친다. `yearly_periods`는 `data.yearly_trend`에서 만들어지므로 자동으로 맞는다. 기준일이 2010년 이전이면 `yearly_trend=[]`, `yearly_periods={}`이고 나머지 집계는 동일하다.
- `RULE_VERSION = "market-activity-license-ytd-v2"`. AI `_activity`는 이 상수와 직접 비교하고, `version_json["activity_rule_version"]`을 거쳐 `data_version_hash`도 바뀐다.

**AI 문맥·해석(필수)**
- `app/ai/context.py`: `_DataVersion.rule_version` Literal을 `"risk-reference-fixed-anniversary-v2"`로 바꾼다. 연도 검사에 `row.year < YEARLY_TREND_START_YEAR` 거부를 명시적으로 추가한다. 스키마로도 막히지만 변조 거부 테스트의 의도를 분명히 하기 위해서다.
- `app/schemas/ai_context.py`: `IndicatorReason`에서 `official_values_not_collected`, `Source`에서 `R1`, `ContextIndicator.status`에서 `link_only`를 삭제한다. `Space`의 `market`은 market_change 때문에 유지한다.
- `app/ai/interpretation.py`, `app/ai/narrative.py`: B4대로 고친다.
- `app/ai/verifier.py`: `PENDING_STATUSES`의 `link_only`와 금지 규칙은 범용 규칙이므로 **그대로 둔다**. 완화 금지 원칙과 일치한다.

**프롬프트(결정: 이번 PR에 포함)**
- `system.md` 규칙 3의 `link_only`와 "공식 안내만 있거나"를 삭제한다. 규칙 2(공식/참고 구분)는 선택 market_change가 official이므로 유지한다.
- `PROMPT_VERSION="risk-interpret-v9"`로 올리고 `PROMPT_HISTORY`에 새 지문을 **추가**한다. 기존 항목은 지우지 않는다. 지문은 수정된 파일로 기존 지문 테스트를 실행해 얻는다. 이 검토에서는 계산하지 않았다.
- 프롬프트 변경 없이도 AI 캐시는 context_hash와 data_version_hash 변경으로 분리된다. 따라서 v9는 캐시 분리 수단이 아니라 프롬프트 문구 정합성 때문에 필요한 것이다. 프롬프트를 고치지 않을 경우 v9 상향도 하지 않는다. 같은 내용으로 지문을 중복시키지 않기 위해서다.

### 공개 스키마·호환성

- API 호환 **파괴 변경**이다. `/api/risk` indicators가 6개에서 4개로 줄고, 기본 `flags.missing`이 `["official_closure_rate"]`에서 `[]`로 바뀐다. 또한 `IndicatorId` enum 축소가 OpenAPI의 `RiskIndicator`, `RiskFlags`, `InterpretItem.indicator_ids`, `RiskInterpretation.used_indicator_ids`에 전파된다. 활동 `yearly_trend.year`의 minimum도 2010이 된다. FE 요청 문서에 이 다섯 지점과 `status`에서 `link_only`가 사라진다는 점을 적는다.
- 유지: `RiskInterpretation.official_values` 필드명(공개 이름, 개명은 범위 밖), `RiskMarket`, 선택 include, `R2`/`R4` 출처, 공식 원천 적재 테이블, #139 진단 명령.
- 구현 전 grep(app/, tests/, docs/): `official_closure_rate`, `official_risk`, `link_only`, `OFFICIAL_RISK_URL`, `golmok`, `official_values_not_collected`, `"R1"`, `risk-reference-fixed-anniversary-v1`, `market-activity-license-ytd-v1`, `ge=1960`, `공식 창업위험도`, `공식 폐업률`. 테스트 fixture와 문서 예시 JSON에 남은 6개 ID 순서와 v1 literal을 모두 갱신한다. 현재 `tests/test_market_activity.py`와 `tests/test_risk.py`의 기존 연도와 단위 케이스는 2020년 이후 또는 참고 지표만 다뤄 하한의 영향을 받지 않는 것으로 읽었다.

### 추가할 테스트(필수)

- 활동:
  - 2009-12-31 개업(→ 행 없음), 2010-01-01 개업(→ 2010 행)
  - 2009 개업·2010 폐업(→ 2010 closed=1, 2009 행 없음)
  - 2009 개업·최근 폐업(→ recent_closed 포함)
  - 2005 개업 현재 영업(→ open_count·평균 개월 포함, cohort_size 불변)
  - 기준일 2009-12-31(→ yearly 빈 값, `yearly_periods={}`, 나머지 불변)
  - 기준일 2010-03-01(→ recent_12m에 2009 사건 포함)
  - 2010년 이후 YTD 밖 0건 행 유지
  - 윤년 clamp
- Risk: 기본 4개와 include 순서, missing, OpenAPI enum에 두 ID·link_only·R1이 없음. `link`·`source_url`이 null이 아니면 거부. B3 코호트 불변.
- AI:
  - 2009 연도 행이나 v1 rule_version을 주입하면 거부
  - missing_data와 narrative 후보 전체 텍스트에 "공식 창업위험도", "공식 서비스", URL이 없음
  - 기준일이 2010년 이전이면 연도 문장 없이 검증을 통과
  - 프롬프트 v9 지문 일치

### 선택 확장(이번 범위 밖, 필요 시 별도 결정)

- 활동 meta에 `yearly_trend_start_year: 2010`을 추가하고 AI `_activity`에서 이를 검증하는 것. FE가 "2010년 이전 미표시"와 "사건 없음"을 구분하기 쉬워진다. 다만 공개 meta가 늘어나므로 넣는다면 FE 문서에도 함께 적는다.
- `ContextActivityMethodology`에 시작 연도 literal을 추가하는 것. 문맥 해시가 바뀌지만 캐시 분리는 이미 충분하다.
- `app/routers/risk.py:31`의 summary "공식 지표 준비 상태"를 "선택 지표 준비 상태"로 바꾸는 것. OpenAPI 문구만 바뀐다.
- `official_values` 필드 개명, 공식 원천 테이블과 ETL 정리는 하지 않는다.

## Codex 반영 결정

설계 검토 B1~B4를 모두 반영한다. 두 ID와 링크 상태/값을 공용 스키마에서 거부하고, AI 문단 후보의 공식 서비스 유도 문장도 제거한다. 연도 하한은 사건별로 적용하고 전체 코호트·최근 개폐업·Risk 산식·1960년 유효 날짜 기준은 보존한다. 프롬프트 규칙3/18을 실제로 수정해 v9의 새 지문을 추가하며, Risk/활동 규칙 v2만으로도 캐시 구분은 성립한다. 전역 캐시 버전·API 필드 official_values·선택 지표·공식 원천 테이블은 바꾸지 않는다. 추가 메타 키와 시작 연도 문맥 필드는 필요하지 않아 만들지 않는다.

## 실제 Claude Code 구현 검토

구현과 회귀 검증을 읽은 Claude Code가 이 절을 직접 수정한다. 테스트 실행은 Codex의 실제 실행 결과로만 기록한다.

2026-11-15 Claude Code가 작업 트리의 변경 파일을 읽기 전용으로 대조했다. 명령·테스트·네트워크·Git은 실행하지 않았고, 코드와 다른 문서는 수정하지 않았다. 아래 "확인"은 정적 읽기 결과다.

### 실행 결과 기록(Codex 보고 기준)

- 일반 pytest 1821건 통과, ruff·mypy 통과. Codex가 보고한 결과이며 Claude Code가 직접 실행하지 않았다.
- 격리 PostGIS 통합 테스트는 **미통과·재실행 대기**다. 첫 실행은 진행 중이었고, 그 사이 지표 위치 하드코딩과 과도하게 엄격한 흐름 기대값을 고쳤다. 재실행 결과가 나오기 전까지 통합 통과를 주장하지 않는다.

### 결론

코드에서 병합을 막는 결함은 찾지 못했다. 설계 B1~B4와 파일별 결정이 모두 구현에 반영됐다. 병합 전에 남은 필수 항목은 다음 두 가지다. (1) 통합 테스트 재실행 통과. (2) FE 요청 문서에 남은 이전 계약 문구 2곳 수정(아래 D1). 나머지는 선택 사항이다.

### 항목별 확인

**공개 Risk에서 두 지표 제거**
- `app/schemas/risk.py:12-25`: `IndicatorId`는 필수 4개와 선택 2개만 남았다. `REQUIRED_IDS`도 필수 4개다.
- `RiskIndicator`(`:74-144`)는 다음을 만족한다.
  - `status`는 `fact|pending`만 허용한다.
  - `source_url`, `link`, `copy_text`는 `None` 타입이다. 키는 남고 값은 null만 허용한다.
  - official 판정은 `id == "market_change"`이고, 출처는 R2/R4/R5·R6의 세 갈래다. R1 분기는 없다.
- `Risk.complete_result`(`:184-207`)와 서비스 missing 계산(`app/services/risk.py:296-300`)은 같은 `{market_change, day_night_ratio}` 집합을 쓴다. 따라서 기본 `flags.missing=[]`이다.
- `app/services/risk.py`: `OFFICIAL_RISK_URL`이 삭제됐다. `pending_indicator`는 `RiskInclude`만 받는다(`:187-197`). 지표 순서는 `[*refs]` 뒤에 `INCLUDE_ORDER` 순으로 선택 지표를 붙인다(`:262-272`).
- `InterpretItem.indicator_ids`, `InterpretSourcedItem`, `used_indicator_ids`(`app/schemas/interpret.py:66,73,107`)는 같은 `IndicatorId`를 참조하므로 OpenAPI enum 축소가 자동으로 전파된다.

**AI 출력에서 제거**
- `app/schemas/ai_context.py:13-21,61`: `official_values_not_collected`, `R1`, `link_only`가 삭제됐다. `ContextIndicator`에는 링크 필드 자체가 없다.
- `app/ai/context.py`: `_DataVersion.rule_version`은 v2 literal이다(`:72`). v1을 주입하면 거부된다(`tests/ai/test_context.py:216-221`). 링크·source_url 값을 주입해도 LLM 호출 전에 거부된다(`:207-213`).
- `app/ai/interpretation.py:52-56`: `MISSING_TITLES`에 두 키가 없다. `official_risk` 분기도 삭제돼 누락 문구는 표본 부족 또는 "적용 기준 확인 중" 두 가지만 남았다.
- `app/ai/narrative.py:180-185`: 문단 3에서 "공식 창업위험도는 서울시 공식 서비스에서…" 문장이 삭제됐다. 참고지표 면책 문구 "서울시 공식 통계가 아닙니다"(`:109-112`)는 설계대로 남아 있다.
- `tests/ai/test_narrative.py:173-192`는 후보 전체와 missing 텍스트에 `공식 창업위험도`·`공식 폐업률`·`공식 서비스`·`golmok`·두 ID가 없음을 검사한다.
- `app/ai/verifier.py`는 이번 변경 목록에 없다. 범용 금지 규칙이 그대로 유지된다는 뜻이다.

**선택 market_change 보존**
- `RiskInclude`와 `INCLUDE_ORDER`가 유지된다. market_change는 official/R2/`market`/pending/`boundary_period_not_verified`다.
- AI `_indicator`는 official을 `market`, day_night_ratio를 `grid` 공간으로 검증한다(`app/ai/context.py:152`).
- `Space`의 `market`과 `Source`의 `R2`는 남아 있다.
- 통합 테스트 `tests/integration/test_risk.py:80-102`가 두 선택 지표의 순서·missing·`type=official`·링크 null을 검사한다. 이 테스트는 재실행 대기 중이다.

**사건별 2010 하한(B1·B2)**
- `app/services/market_activity.py:93-97`: 조건이 `event is not None and event <= target and event.year >= YEARLY_TREND_START_YEAR`이다. 이 조건이 `years.add`와 카운터 증가를 모두 감싼다. 그래서 2009년 0건 행은 생기지 않고, 2010년 이후 YTD 밖 사건의 0건 행은 남는다.
- 다음 값은 하한 적용 전의 전체 레코드로 계산되며 변경이 없다(`:78-100`, `:188`, `:199-211`).
  - 레코드 검증(1960 하한 포함)
  - `recent_opened`·`recent_closed`
  - `active`와 평균 개월
  - `meta.cohort_size=len(records)`와 `record_profile`
- 단위 테스트 `tests/test_market_activity.py`가 다음을 고정한다.
  - `:72-90`: 2009-12-31 개업·2010-01-01 폐업은 2010 폐업으로만 집계, 2010-01-01 경계, 2008 개업·최근 폐업, 2000 개업 현재 영업, 2009 이전만 있는 레코드, 2011·2012 YTD 밖 0건 행.
  - `:93-100`: 기준일이 2009-12-31이거나 2010-03-01이면 추이는 비고, recent_12m과 평균 개월에는 2009년 사건이 포함됨.
  - `:62-69`: 기존 gap 미보간 테스트도 2020년 이후 값으로 유지됨.

**Risk 코호트·생존율 불변(B3)**
- `aggregate_counts`(`app/services/risk.py:154-184`)와 조건 목록은 하한 상수를 참조하지 않는다. `store_cohort.MIN_OPEN_DATE`도 그대로 쓴다(`app/ai/context.py:52,425`).
- 통합 테스트 `tests/integration/test_market_activity.py:127-192`는 기준일 2012-11-08 데이터에서 다음을 검사한다.
  - 3주년 생존율 분모 1: 2009-01-01 개업.
  - 최근 폐업률 분모 4: 1965·2009·2010 개업 현재 영업 3건과 2008 개업·2012 폐업 1건.
  - 활동 `cohort_size=6`이 Risk와 같고, AI 문맥 생성까지 통과함.
- 설계가 요구한 "하한 도입 전후 같은 ReferenceCounts" 비교는 별도 전후 비교 대신 절대값 검증으로 대체됐다. SQL에 하한이 없으므로 이 대체는 충분하다고 판단한다. 다만 3주년 코호트 안의 2008년 개업 사례는 없다. 이 테스트 역시 재실행 대기 중이다.

**과거 기준일**
- 기준일이 2009-12이면 `yearly_trend=[]`, `yearly_periods={}`이고 `cohort_size=5`, `open_count=4`가 유지된다. AI 문맥의 연도도 빈 값이다(통합 `:181-192`).
- narrative는 연속된 두 관측 연도가 있을 때만 연도 문장을 만든다(`app/ai/narrative.py:161-172`). 따라서 빈 추이에서도 문단 검증 경로는 기존과 같다.
- `as_of="2020-02"` 과거 문맥 흐름은 `tests/integration/test_ai_context.py:120-141`에서 지표 인덱스를 새 순서(`[-1]`=competitor_count, `[2]`=survival_rate_3y)에 맞췄다.

**스키마·캐시·버전 정합**
- `YEARLY_TREND_START_YEAR`는 `app/schemas/market_activity.py:9` 한 곳에 정의돼 있다. `YearlyActivity.year`, `ContextYear.year`, AI `_activity`의 명시적 거부 조건(`app/ai/context.py:364`)이 모두 이 상수를 쓴다.
- OpenAPI `minimum == 2010` 검사가 있다(`tests/test_risk.py:176-179`).
- 버전은 다음과 같이 맞춰졌다.
  - Risk `RULE_VERSION`: `risk-reference-fixed-anniversary-v2`
  - 활동 `RULE_VERSION`: `market-activity-license-ytd-v2`
  - AI `_DataVersion` literal과 테스트 fixture(`tests/ai/context_helpers.py:118,157`): 위 값과 일치
  - 활동 rule은 `version_json["activity_rule_version"]`을 통해 `data_version_hash`에 반영된다.
- 프롬프트는 `system.md`의 규칙 3에서 `link_only`와 공식 안내 문구를 삭제했다. 규칙 18은 "2010년부터의 실제 사건 연도 … 2010년 이전 추이를 만들지 않습니다"로 바뀌었다. `PROMPT_VERSION=risk-interpret-v9`이고, v1~v8 항목을 보존한 채 v9 지문을 추가했다(`app/ai/prompts/version.py:20,23`). 지문 일치는 일반 pytest 통과로만 확인된다.
- 전역 `CACHE_VERSION`과 `official_values` 필드명은 바뀌지 않았다. 설계대로다.

### 필수 수정(문서 blocker)

- **D1. FE 요청 문서에 이전 계약 문구가 남아 있다.** `docs/fe-risk-reference-api-request.md`의 두 곳이다.
  - `:80` "`flags.missing`은 **필수 공식 폐업률에 필요한 검증 경계**와 요청된 선택 항목만 포함하며"는 같은 문서 `:38`의 "기본 `flags.missing=[]`"과 모순된다. "요청된 선택 항목(market_change/day_night_ratio)의 pending만 포함하며 기본값은 빈 배열"로 바꾼다.
  - `:118` 체크리스트 "공식 위험 링크·copy_text=null"은 삭제된 링크 카드를 계속 구현하라는 뜻으로 읽힌다. "공식 폐업률·창업위험도 카드와 링크 제거, link/source_url/copy_text=null"로 바꾼다.

  BE 코드에는 영향이 없다. 하지만 이 문서가 FE 전달 산출물이므로 병합 전에 고친다.

### 선택 사항(병합 비차단)

- `app/routers/risk.py:31` summary "인허가 참고지표와 공식 지표 준비 상태": 선택 market_change가 여전히 official이라 틀린 문구는 아니다. "선택 지표"로 바꾸면 OpenAPI 문구만 달라진다.
- FE 문서 머리말 상태줄(`:3,6`)에 #140 갱신 날짜나 상태가 반영되지 않았다. 본문 `:10-12`에 있으므로 선택 사항이다.
- `tests/ai/context_helpers.py:84`의 missing 계산식 `status == "pending" and type == "official" or id == "day_night_ratio"`는 연산자 우선순위에 기대고 있다. 현재는 day_night_ratio가 항상 pending이라 결과가 같다. 서비스와 같은 `id in {market_change, day_night_ratio}` 형태로 맞추면 의도가 분명해진다.
- `tests/ai/test_narrative.py:202-212`의 2009 변조 테스트는 `MarketActivity.model_validate` 단계에서 먼저 거부된다. 그래서 `app/ai/context.py:364`의 명시적 `row.year < 2010` 분기는 이 테스트로 도달하지 않는다. 방어 목적은 유지되고, 분기 자체를 검증하려면 meta만 조작하는 별도 경로가 필요하지만 필수는 아니다.
- OpenAPI 검사는 `RiskIndicator.id`만 본다. `RiskFlags.missing`과 AI indicator_ids enum은 같은 Literal을 공유하므로 추가 검사는 선택이다.

### 읽지 않은 범위

`README.md`, `CLAUDE.md`, `docs/be-work-plan.md`의 변경분, `app/ai/verifier.py`, 프롬프트 지문 테스트 파일, AI 캐시 저장 모듈은 열지 않았다. 문서 세 개의 #140 서술과 머리말 상태가 위 결론(통합 재실행 대기, FE 미반영, 운영 미배포)과 맞는지는 구현자가 확인한다.

## 구현 검토 후 Codex 확인

문서 blocker D1의 두 항목은 FE 요청 문서에서 수정했다. `flags.missing`을 요청한 선택 항목만 포함하는 것으로 명시하고, 체크리스트의 공식 위험 링크 구현 요구를 두 카드/링크/빈 섹션 제거로 대체했다. README·CLAUDE·통합 계획도 네 필수 지표·2010년 추이·전체 코호트 보존·FE 반영 대기·운영 미배포와 일치하도록 확인했다. 구현 검토의 통합 재실행 대기 상태는 당시의 기록이며 최종 실제 결과는 아래 별도 절로 갱신한다.

## 최종 검증

- 일반 **1,821개 통과**, 격리 로컬 PostGIS **272개 통과(skip 0)**, ruff check/format 및 strict mypy161파일 통과. 실제 개발/운영 데이터베이스를 테스트 대상으로 쓰지 않고 각 fixture의 임시 DB만 생성·정리했다.
- 새 일반 회귀15개와 통합1개를 포함한다. 2009/2010 경계·사건별 폐업·현재 수/평균 개월·2010 이전 기준일·2009 사건을 포함한 최근 12개월·2012 기준 2009 개업 3주년 생존 코호트를 보존한다. 같은 실제 서비스 집계를 AI 문맥까지 재계산해 연도와 합계를 확인했다.
- OpenAPI의 두 ID/link_only 제거·null 링크 계약·과거 연도 변조/구버전 거부·AI 모든 문단 후보/누락 안내의 삭제 항목 부재·새 프롬프트 지문을 확인했다. 기존 필터/재적재/캐시 무효화/실패 격리 통합 흐름도 통과했다.
- 첫 통합 실행의21개 실패는 기존 테스트의 배열 위치와 선택 지표 가정이었다. ID로 비교하고 선택 include를 보존하도록 고친 뒤 전체272개를 재실행해 통과했다. 일반 검사 결과로 통합 검사 성공을 대신하지 않았다.
- 실제 Claude Code 설계/구현 MD 직접 검토2회가 정상 종료했고 권한 거절은 없었다. BE 계약·설계·README·FE 요청서를 갱신했다. FE 파일·실제.env·원본/모델/migration·Render 설정/배포는 수정하지 않았다. develop 반영과 FE 반영·실행 배포는 별개이며 #78/#115 잔여는 유지한다.
