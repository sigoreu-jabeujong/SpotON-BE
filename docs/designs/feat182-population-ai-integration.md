# 공개 생활인구 부분자료의 AI 해석 연결 설계 (#182)

## 1. 이번 단계와 실제 배포 기준

2026-11-16 사용자의 “다음 스텝” 요청을 받아, 직전 배포에서 남긴 **부분 공개자료의 AI 반영**을 다음 구현 대상으로 설계한다. 이번 산출물은 설계·실제 Claude Code 검토·Codex 최종 판단이다. 앱/FE 구현·운영 배포는 이번 문서의 완료와 구분한다. 원천 공식 근거를 대신 승인하거나 전체 인구를 계산하지 않는다.

- BE PR181: `cd7360c0666652f38652715d239743142acf0198`, Render `dep-dbtc91ek1f9s73bfv1e0`, live.
- FE PR74 → main PR75: `0ed17dff56930590130ddf021e635c935819e40e`, [Vercel 배포](https://vercel.com/ryu-min-jis-projects/spot-on-fe/BpjkFHUK5fUMVz8ytRGS1uCWZrPc).
- [공개 사이트](https://spot-on-fe.vercel.app)의 분석·종합진단·보고서에 GET `/api/v2/population-reference`가 연결됐다. 실제 공개 브라우저/모바일/PDF·기존 AI 200 확인은 [PR181](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/181), [FE PR75](https://github.com/sigoreu-jabeujong/SpotON-FE/pull/75)의 실행 기록이다. 이번에 재실행했다고 주장하지 않는다.
- 기존 `activity.living_pop=null`, Risk `day_night_ratio=pending`, AI의 전체 생활인구 미사용은 유지됐다. 새 인구 비교가 AI에 연결된 상태가 아니다.
- BE #115의 행정동 가산성·행 부재 의미·관측일별 격자 적용 근거는 아직 없다. 외부 문의는 제출하지 않았다.

이번에는 BE 설계 MD와 작업 안내만 바꾼다. 기존 DB0012/원문·환경파일·키·17개 Render 환경변수·Vercel 설정·서버·고정 로그 Task/runtime·FE 및 사용자 파일을 보존한다. 새로운 API 키는 필요 없다. 이미 동작하는 LLM 연결을 재사용하는 후속 구현이다.

## 2. 현재 코드에서 확인한 연결 지점

| 위치 | 현재 동작 | 필요한 변경 |
|---|---|---|
| `app/services/risk_interpret.py:_prepare` | v1/v2를 같은 읽기 전용 RR 세션에서 준비한 뒤 세션을 닫고 모델 호출 | v2 준비 중 인구 조회까지 완료; 외부 HTTP 자기 호출 금지 |
| `app/ai/chain_context.py:prepare_chain_interpretation` | Risk·활동·선택 이력·브랜드 문맥을 재계산, 제한된 outbound 및 context hash | 전용 인구 projection을 같은 세션에서 생성하고 hash에 포함 |
| `app/services/population_reference.py:get_population_reference` | 원천별 고정 공개 구성 24시간·metadata·원천별 quality/한계, 읽기만 수행 | 기존 함수를 재사용; 인구 집계의 별도 복사본을 만들지 않음 |
| `app/ai/interpretation.py:build_catalog` | 전체 생활인구 미확인 문구를 항상 추가 | 전체 지표와 부분 비교를 구분해 모순 없는 안내 생성 |
| `app/ai/narrative.py:build_narrative` | 네 번째 준비 문단에 생활인구 미확보 안내 고정 | 같은 문단에 부분 비교와 제한을 붙이되 4문단 수 유지 |
| `app/schemas/interpret.py` | 허용 근거 ID와 `narrative_ids` 정확히 4개 | 새 별도 근거 ID를 추가; 유리/불리 후보의 Risk ID 허용 범위는 유지 |
| `app/ai/prompts/chain_interpret`, `chain_version.py` | 독립 v2 프롬프트 v1·불변 지문 이력 | v2 프롬프트만 새 버전·지문 추가, v1 프롬프트 v9 불변 |
| FE `AiInfoPopover`, messages, types | 사용 자료는 `evidence.indicators` fact에서 추출; 생활인구 미확보 고정 설명 존재 | 부분 자료 별도 상태/관측일/한계를 안내, Risk fact로 승격하지 않음 |

현재 결과는 서버가 문장을 만들고 모델이 후보 ID만 선택하는 방식이다. 이를 유지한다. 인구를 모델이 자유롭게 서술·계산하도록 변경하지 않는다.

## 3. 선택한 API와 문맥 계약

### 3.1 기존 v2 해석 경로에 서버가 자동 연결

후속 구현은 POST `/api/v2/risk/interpret`의 **요청 형식을 그대로 유지**한다. 사용자가 제출하는 값은 기존 query/history뿐이다. 클라이언트 인구 값·날짜·토큰·정책 플래그는 받지 않는다. v1 `/api/risk/interpret`의 프롬프트·문맥·본문·캐시 규칙은 유지한다.

서버가 검증한 `ChainRiskQuery`에서 `lat,lng,radius,category,sub_category,as_of` 6개만 명시적으로 투영해 `PopulationReferenceQuery`를 만든다. `sub_category`는 `checked.sub_category` 원래 tuple(미지정이면 `()`)이며 context의 확장된 기본 업종 목록을 넣지 않는다. scope 비교는 `tuple(sorted(projected.sub_category))`와 한다. `include`, `brand_*`, `area`, `operation_type` 등은 전달하지 않는다. 브랜드/업종/면적 필터가 인구 자료에 적용된다고 설명하지 않는다. category/sub_category는 인허가 허용월 검증에만 쓰인다.

`get_population_reference(session, projected_query)`를 `prepare_chain_interpretation` 안에서 호출한다. 이미 사용 중인 **동일 RR 세션**을 사용하며, 별도 DB 세션·직렬 HTTP·FE의 조회 결과 재사용은 금지한다. 모델 호출 동안 DB 연결을 보유하지 않는다. 새 조회는 기존 deadline/stop의 SQL 직전 검사를 그대로 받는다.

서버 투영의 일치 조건:

1. 인구 응답 오류 없음/data 존재와 typed 계약 재검증.
2. 인구 `analysis_date == context.as_of`, `scope.radius_m/category/sub_category/as_of`가 투영 입력(서버의 sorted sub_category 포함)과 일치, `population_filter_applied=false` 확인. 관측일이 있으면 `[analysis_date 월 1일, analysis_date]` 안이어야 한다.
3. 현재 인구 API meta에는 인허가 D 필드가 없다. 없는 필드를 읽거나 D 확인용 쿼리를 추가하지 않는다. Risk `_get_risk`와 인구 `_get_population_reference` 모두 같은 RR의 `current_provenance(session)` 및 같은 `temporal_cohort(category/sub_category)`의 MIN(open_date)로 `effective_date`를 부른다. 기존 Risk가 먼저 월 하한을 검증한다. `_checked_risk`의 고정 MIN_OPEN_DATE 비교는 그 뒤의 방어 검사여서 더 이른 업종 월을 허용하지 않는다. 따라서 정상 요청 T는 같다. 빈 cohort·최초 허용 월·그 직전 월·현재 월을 cafe/restaurant 및 세부 업종에서 회귀 검사한다.
4. category/subcategory로 거른 인허가 D가 아니라 기존 전역 D가 사용된다는 계약을 유지.
5. 불일치는 500 `INTERNAL_ERROR`/no-store; 다른 날짜로 fallback하지 않음.

### 3.2 새 outbound allowlist

`ChainRiskInterpretContext`에 typed `population_reference: ContextPopulationReference`를 추가한다. 실제 v2 준비에서는 모든 성공 경로에 명시적으로 설정한다. v1 context에는 필드를 추가하지 않는다. FE는 새 evidence를 optional로 읽어 배포 전후 응답을 모두 표시할 수 있게 한다.

| 필드 | 허용 내용 |
|---|---|
| `status/reason` | 기존 API의 닫힌 최상위 상태/사유; 숫자가 없는 상태도 그대로 전달 |
| `analysis_date/observation_date` | 서버가 정한 분석일·관측일, 다른 의미의 날짜로 바꾸지 않음 |
| `calculation_method/day_hours/night_hours/ratio_definition` | `fixed_public_component_24h`, 주간 06~17시·야간 나머지, pooled 비 정의. 기존 `method` 객체를 통째로 복사하지 않는다. 그 안의 `name`은 outbound 금지 키다 |
| `population_filter_applied` | 고정 false |
| `source_validation_performed/population_total_validated` | 고정 false; 참으로 승격 금지 |
| `sources` | ready일 때만 local/long/short 순서 3개; 각 source의 status/reason/limitations |
| 원천별 `metrics` | partial일 때만 day_share_pct/night_share_pct/day_night_ratio. 각 객체의 정확한 키는 `display,exact_zero,rounded,unit,reason` 5개; `value`는 보내지 않음. null/zero/rounding 의미와 기존 display를 보존 |
| 원천별 `quality` | 정확한 키는 `selected_grid_count,used_grid_count,grids_without_rows,candidate_component_count,used_component_count,excluded_component_count,excluded_by_hour_class.{day_only,night_only,both}` |

**제외:** 좌표·주소·건물/점포·브랜드 명칭·행정동/격자 식별자·UUID·원천 파일명/해시·API result token·source version identifiers·원문·시간별24개 값·합계·평균·전역 미위치 행 수·`PublicNumber.value`·`observed_rows/suppressed_rows/missing_rows/absent_hours_within_candidates/version_unlocated_*`. 인구 총계나 인원수처럼 읽힐 수 있는 합/평균은 모델에 주지 않는다. 기존 `FORBIDDEN_CONTEXT_KEYS`·정확한 Pydantic allowlist·`serialize_context` 검사를 유지한다.

`ContextPopulationReference`는 새 `PublicValues` 전체를 상속하지 않는다. 명시적 필드 투영과 상태별 validator를 사용한다. ready의 3개 원천 순서/중복/상태와 metrics의 nullable 관계, 비중=`pct_of_public_subset`·배수=`ratio` 단위를 검사한다. display는 기존 API helper가 생성한 값에서 그대로 복사하고 포맷터를 중복 구현하지 않는다. `PopulationReference` 재검증만으로 display의 산술 정합성이 증명되는 것은 아니며 helper의 실제 계산↔projection 대조 검사를 추가한다. 원천별 partial은 source 검증 완료의 의미가 아니다. `sources/source` 키는 기존 API와 일치하게 유지하며 local/long/short는 원천 구분자다. R4 출처와 혼동하지 않는다.

## 4. AI 본문과 검증 규칙

### 4.1 표시와 고정 문장

부분 자료는 RiskIndicator가 아니다. **유리/불리 후보에 넣지 않고**, `official_values`에도 추가하지 않는다. 근거 ID `population_public_subset`를 `InterpretItem.indicator_ids`, 응답 `used_indicator_ids` 및 FE EvidenceId의 허용 목록에 추가한다. `InterpretSourcedItem`의 유리/불리 ID 목록과 기존 `IndicatorId`는 확장하지 않는다.

현재 네 번째 준비 문단에 서버가 짧은 인구 부분 비교를 추가한다. 문단 그룹 0~3·각 그룹 1개 선택·`CandidateSelection` 길이4·최대1회 재생성·서버 조립 방식을 유지한다. 인구 값으로 기존 점포 지표의 좋고 나쁨이나 추천·고객층·수익성·미래를 설명하지 않는다.

- 내국인이 partial이면 원천명을 붙여 **주간/야간 비중** 두 display만 기본 문장에 표시한다. 배수는 evidence/기존 카드에 보존하고 첫 AI 본문에는 넣지 않는다. 과도한 숫자와 작은 분모의 큰 배수에 의미를 부여하지 않기 위한 선택이다.
- 내국인이 없으면 “내국인 공개자료 비교는 제공되지 않는다”와 정확한 서버 사유만 안내한다. 외국인 값을 내국인의 대체값으로 쓰지 않는다.
- 장기/단기 외국인은 각 원천별 partial 여부만 같은 문단에 표시한다. 본문을 세 원천의 숫자로 채우지 않으며 상세 값은 기존 카드/evidence에서 각각 확인한다. 합산·평균·상호 대체 금지.
- 세 원천 모두 값이 없거나 최상위가 pending/no_data/not_supported이면 해당 상태와 사유만 쓰고 숫자는 만들지 않는다.
- 부분 숫자가 하나라도 사용되면 관측일·“공개된 동일 구성의 부분자료”·전체 인구/방문객을 대표하지 않음·점포 필터와 무관함을 같은 문단 안에 명시한다.
- 특정 원천의 제외가 day_only 또는 night_only에 있으면 제외 패턴에 따라 비중이 치우칠 수 있음을 안내한다. 표시 가능한 내국인에서 제외가 없어도 공식 가산성/격자 기간 미확인 한계는 유지한다.
- 전체 living_pop/day_night는 계속 pending이다. 고정 `population_not_available` 안내는 “전체 생활인구는 미확정; 공개 부분자료 비교는 별도”로 구체화한다. v1 문구는 바꾸지 않는다. 매출 미확보 안내도 유지한다.

예시 문장(설명용 합성값): “관측일 YYYY-MM-DD 내국인 공개자료의 같은 공개 구성에서는 주간 비중 60.0%, 야간 비중 40.0%입니다. 이는 부분자료 비교이며 전체 인구나 실제 방문객 수를 대표하지 않습니다. 점포의 업종·브랜드·면적 조건으로 인구 자료를 거른 결과도 아닙니다.” 실제 문장은 서버의 date/display만 사용하며 비중을 재계산하지 않는다.

### 4.2 숫자·제로·원문 보호

`PublicNumber`의 display·reason·exact_zero·rounded를 그대로 사용한다. total=0으로 두 비중이 null이면 비중을 쓰지 않고 `zero_total` 사유를 안내한다. 양수가 반올림되어0.0%이면 “반올림 표시값”임을 명시하고 실제0이라고 서술하지 않는다. night=0의 null 배수와 실제 day=0의 0배를 혼동하지 않는다. 본문에서는 배수를 사용하지 않더라도 evidence의 의미를 검증한다.

기존 숫자 whitelist·반올림 허용·개인정보 패턴·길이·반복·금지 표현·출처 검사를 완화하지 않는다. 기존 본문 검증은 approved_narrative의 숫자도 허용하므로 인구 문장 검증으로 충분하지 않다. **인구 부분 문장을 별도 서버 함수로 만든 직후 `verify_output({text: 인구문장}, context={analysis: sentence_evidence})`를 실행하며 이때 후보 문장 자신을 문맥에 넣지 않는다。** `sentence_evidence`의 정확한 허용 필드는 `analysis_date,observation_date`와 실제 문장에 쓰는 원천의 `status/reason,day_share_pct/night_share_pct.{display,rounded,reason}`다. quality·시간대·다른 원천의 숫자를 넣지 않는다. 실패는500/no-store이고 그 문장은 후보에 넣지 않는다. 없는 숫자로 바꾼 문장의 UNKNOWN_NUMBER 거절, 주야간 display를 바꾸거나 원천을 바꾼 문장의 canonical builder 불일치, 원천별 null의 숫자화 방지를 각각 검사한다. 최종 전체 본문 검증도 그대로 수행한다. whitelist는 필드별 수치 관계나 사실 정확도를 증명하지 않으며 고정 builder·명시 투영·계산 대조가 이를 담당한다. 기존 pending-ID 검증은 id 없는 인구 블록을 보호하지 않으므로 새 상태별 문장 분기가 필요하다. source-status `partial`을 기존 Risk `fact`나 `verified`로 변환하지 않는다.

검증 코드를 유지해도 문맥에 추가된 quality·시간대 숫자는 허용 숫자 집합을 넓힌다. 필드를 위 최소 목록으로 고정하고 인구 별도 검증에는 필요한 날짜/display/상태만 전달한다. 임의 숫자 검증의 동일 강도나 개인정보 안전성을 숫자 whitelist만으로 주장하지 않는다. 한계 문장은 원천마다 반복하지 않고 문단에 한 번만 쓴다.

현재 사실/결측 안내의 검증 상한은 `VerifyPolicy.max_chars=2000`, 본문은8000이다. 세 원천을 모두 장황하게 나열해 상한을 무작정 올리지 않는다. 최대 기존 Risk·history·브랜드 안내와 조합한 길이 검사를 통과하는 짧은 문장을 채택한다. 길이 제한 때문에 한계만 지우는 truncation은 금지한다.

## 5. 캐시·오류·성능

- v2 `chain-risk-interpret-v2`로 버전을 올리고 append-only 지문 이력을 추가한다. v1 `risk-interpret-v9`/기존 지문은 보존한다.
- `CHAIN_SELECTION_CACHE_RULE`을 별도 새 값으로 올린다. 인구 typed projection이 context_hash와 모델 payload에 포함돼 원천 수치·quality·상태·관측일 변화 시 캐시가 달라져야 한다.
- 기존 result token은 조회 위치/코호트의 ID가 아니므로 AI 캐시 키로 단독 사용하지 않는다. 기존 query hash·브랜드/source revision·prompt fingerprint·payload/schema를 유지한다. 내부 provenance/version hash에는 인구 projection 규칙 버전과 내부 data-version metadata의 digest를 추가하되 LLM에는 노출하지 않는다.
- 캐시 hit에도 현재 RR 문맥을 재계산하고 선택 ID 유효성을 재검증한다. 기존 캐시가 오래된 인구 숫자를 반환하지 않게 한다. 유효 TTL/late write/Flights/공급자 공유 quota는 유지한다.
- 유효한 pending/no_data/not_supported는 AI 전체 실패가 아니다. 해당 사유를 넣고 나머지 지표로 해석한다. 단, DB 연결/권한/metadata/행 손상·날짜 불일치·기존 SQL timeout은 500 또는 기존 deadline 경로로 전달한다. `except Exception → population=None`으로 손상을 감추지 않는다.
- 모델 시간/쿼터·전체 deadline 실패는 기존503 의미를 유지한다. 인구 조회가 예산을 넘었다고 성공인 척 기존 캐시나 오래된 날짜를 사용하지 않는다.
- 인구 조회의1000격자/100,000행 limit+1과 전역 관측 COUNT 없음, 같은 RR를 유지한다. 운영 statement_timeout10초/풀1·대기15초·전체 LLM 예산은 변경하지 않는다. 기존 인구 GET의 응답 시간은 추가 AI 조회의 측정치로 재사용하지 않는다.
- 임의 로그 경로 추가나 고정 운영 수집기의 whitelist/runtime 변경은 하지 않는다. 모델 원문·집계·쿼리·주소·키를 새 로그에 남기지 않는다.

## 6. FE 작업과 배포 순서

후속 구현에는 BE와 작은 FE 변경이 함께 필요하다. 현재 FE body는 plain text를 출력하므로 새 본문을 표시할 수 있지만, 타입과 정보 팝오버의 사용 자료/미확보 고정 안내를 동기화해야 한다.

1. BE typed projection·동일 RR 조회·4문단 서버 문장·프롬프트v2/캐시·계약과 검사를 격리 브랜치에서 구현한다. 이 시점에는 운영 배포하지 않는다.
2. FE `types/risk.ts`에 `population_public_subset` 및 optional typed evidence를 추가한다. `AiInfoPopover`는 기존 fact 목록과 별개로 **부분 공개자료 상태와 관측일**을 표시한다. evidence에 없으면 기존 안내, 있으면 “전체 생활인구 미확정·공개 부분자료 별도 참고” 안내를 사용한다. 값이 없는 상태를 숫자 사용으로 표시하지 않는다. `MESSAGES.ai.info.unavailableText`와 rules 마지막 줄의 고정 안내를 이 조건으로 바꾼다. 아직 연결 전인 BE와도 정상 동작해야 한다.
3. `MESSAGES.ai.evidenceNames.population_public_subset`를 추가하고 `evidenceChip`의 `target=null`로 이름만 표시한다. RiskIndicator 앵커로 연결하거나 새 화면 이동을 추가하지 않는다. 기존 unknown-ID 방어를 유지한다.
4. AI 본문은 POST가 계산한 evidence를 기준으로 설명한다. GET 카드와 독립 요청이므로 그 사이 적재가 바뀌면 관측일·상태가 다를 수 있다. FE/보고서는 AI evidence의 관측일을 별도로 표시하고 카드 날짜와 다르면 둘을 유지한다. 엄격한 cross-request snapshot 보장은 새 계약 없이는 제공하지 않는다.
5. 복제 DB·제한 모델·브라우저/보고서 검증 후 **호환 FE develop PR→main release PR→Vercel 배포→기존 BE에서 기존 안내 확인→BE PR 정상 병합→Render Free에 정확한 commit 배포→신규 AI/FE 공개 검증** 순서로 진행한다. BE를 먼저 배포하면 구형 FE의 미사용 고정 문구와 새 본문이 모순되므로 금지한다. API 키/환경변수/호스팅 설정을 다시 요청하거나 바꾸지 않는다.
6. 실패 시 먼저 이전 BE commit으로 복구한다. 호환 FE는 새 evidence가 없는 이전 BE 응답에 기존 안내를 표시한다. FE도 복구하려면 BE가 이전 버전임을 확인한 뒤 이전 FE deployment로 복구한다. schema0012/원천을 바꾸지 않아 DB downgrade가 필요 없다. 실제 배포 ID·각 head CI·실제 공개 모델/브라우저 근거를 별도 실행 기록에 남긴다.

v2의 추가 안내/문장 분기는 공용 `build_catalog/build_narrative` 안에서도 `ChainRiskInterpretContext`에만 적용한다. `InterpretItem`의 공유 근거 enum에는 새 값이 추가되므로 v1 OpenAPI가 완전히 동일하다고 주장하지 않고, 기존 v1 실제 응답·프롬프트/hash/문구를 골든 비교한다. v2 프롬프트에는 “analysis.population_reference의 부분자료는 공개된 같은 구성의 비중 비교로만 설명하고 전체 인구·Risk day_night_ratio·점포 필터 모집단과 동일시하지 않는다. candidates.narrative 문단 외 수치를 생성하지 않는다”를 추가한다. 기존 규칙20은 전체 인구/고객/수익성 추정 금지를 유지하되 이 제한된 부분 비교와 모순되지 않게 고친다. v2 네 번째 문단의 기존 미확보 문장은 “전체 생활인구와 매출의 적용 기준을 확인하지 못해 수요나 수익성을 추정하지 않았습니다”로 바꾸고 새 한계 문장과 중복되지 않게 한다. v1 문장은 그대로다.

v2 문단에 원천 partial 상태/비중이 사용되면 `prepared.response_meta.source`를 `[R5,R6,R4]`로 설정해 현재 `interpret_risk`의 meta 병합 경로를 사용한다. 새 partial이 하나도 없으면 `[R5,R6]`, v1은 항상 기존 그대로다. R4 포함은 공식 인구 승인 표시가 아니다.

새 인구 문장이 있으면 pending/no_data/not_supported 안내만 있는 경우에도 근거 ID `population_public_subset`을 붙인다. R4 부착 조건과 근거 ID 부착 조건은 다르다. 내부 인구 version digest의 정확한 metadata 키는 `format_version,rule_version,observation_version_id,grid_version_id,input_sha256,content_sha256,grid_input_sha256,grid_content_sha256` 8개이며 기존 `version_json`에서만 해시화한다. 이 원문은 outbound/응답에 추가하지 않는다.

성능 합격선은 후속 실험의 목표이며 현재 측정 결과가 아니다. 동일 복제 DB/조건에서300·500·1000m×각5회(15회)의 warm prepare를 기존 코드와 비교해 **각 prepare≤6초 및 인구 연결에 따른 증가≤3초**를 모두 만족해야 배포한다. cold는 별도로 기록하며 warm 결과를 cold 보장으로 쓰지 않는다. 실제 운영 모델 호출은 부분자료 정상/유효 no_data 각1회 이내로 제한해 전체 기존 예산 안의 정상 완료를 확인한다. 미달이면 조회/투영을 보완하고 재검증하며 timeout/한도 상향으로 통과시키지 않는다.

이번 설계에서 위 구현·FE 수정·배포를 실행했다고 표시하지 않는다. 원천 갱신·전체 인구 승인·매출 활성화·새0013 승인 저장소는 별도다.

## 7. 후속 구현의 완료 검사

| 검사 | 필수 반례/근거 |
|---|---|
| 투영·비노출 | allowlist 정확 일치; 실제 식별자·좌표·hourly/sum/mean/value/token/UUID 제외; 잘못된 단위/status 거절·helper display 그대로 대조; v1 context/응답 골든 불변 |
| 동일 RR 실제 PostGIS | API와 같은 scoped 자료; 브랜드/면적 필터를 바꿔도 인구 projection 동일; 두 업종/세부 업종·빈cohort·최초월/그직전/현재월의 Risk→인구 월 범위 일치; scope/date/월하한 변조500; 모델 호출 전 연결 반환 |
| 결측 분리 | local만 없음·외국인만 없음·세 원천 partial/혼합 no_data·관측월 없음·동일날짜중복pending·상한not_supported; valid missing으로 AI 전체 실패하지 않음 |
| 숫자·편향 | actual0/rounded0/zero_total/zero_night_denominator·반올림 경계·day_only/night_only/both; 합계/가산성/대표성/고객/유불리 주장 없음 |
| 문장·선택 검증 | 인구문장 analysis-only 선검증·없는 숫자 UNKNOWN_NUMBER·주야간/원천 교환 canonical 비교; 4그룹·새ID의 Risk 유불리 금지; 숫자/자유문장/그룹 변조 거절; 최대history+브랜드추정+3지표pending 길이·반복/개인정보 검사 |
| 캐시 | 인구 상태/quality/date/display·prompt 변경은 miss; 같은 문맥은 검증 hit; 원천 변경 직후 이전 수치 재사용 금지; v1 키/문구/프롬프트 불변 |
| 시간·DB 오류 | 인구 SQL 직전 deadline LlmError→기존503/worker취소·metadata손상500 vs valid no_data200 구분; 모델 호출 시 DB 미보유; 기존 quota·503·no-store 유지; warm prepare 15회 각≤6초·증가≤3초 |
| FE/모델·실서버 | 실제 모델 payload의 비노출/ID선택/숫자 검증, 새 본문+정보창·조건 변경/취소·모바일·보고서·PDF; 같은 안정 원천의 카드↔AI evidence 대조 |
| 배포/보존 | 정확한 PR head CI/CodeQL→호환FE먼저/기존BE검증→BE배포·ID/공개모델·브라우저; BE먼저복구; DB0012/원천·환경/파일·기존Task/runtime 보존 |

원래 제보의15개 위치 목록은 제공되지 않았다. 새 임의 표본을 원래 표본의 정확도/산정률 개선으로 설명하지 않는다. 전체 인구 미확정은 #115/#78에 남긴다.

## 8. 검토·실행 기록

### 8.1 Codex 초안

BE `cd7360c`와 FE develop `4bdb631`/main `0ed17df`의 해당 소스를 읽었다. 기존 API 키 부족이 아니라 서버 문맥/후보/프롬프트·FE 안내의 연결 작업이라는 점을 확인했다. 위 문서의 조회·projection·프롬프트·캐시·FE 변경안은 아직 구현하지 않았다.

### 8.2 실제 Claude Code 검토

검토 실행 후 이 절에 실제 판정과 지적 사항을 추가한다. 실행 전 PASS라고 적지 않는다.

#### 8.2.1 검토 범위와 근거

- 검토자: Claude Code (claude-opus-5-5), 2026-11-16. 설계 검토만 했다. 앱/FE 코드 수정·shell·git·DB·네트워크·테스트 실행·배포는 하지 않았다.
- 근거: 이 MD와 사용자가 대화에 붙여 넣은 소스 발췌(`chain_context.py`, `context.py` 일부, `interpretation.py`, `narrative.py`, `verifier.py`, `prompts/builder.py`, `chain_interpret/system.md`, `chain_version.py`, `risk_interpret.py`, `population_reference.py`(service·schema), `ai_context.py`, `interpret.py`, `db/dependencies.py`, FE `types/risk.ts`, `AiInfoPopover.tsx`, `evidenceChip.ts`, `AiResultCard.tsx`, `useReportData.ts`, `messages.ts` 일부). 저장소 파일을 직접 대조하지 않았다. 발췌에 없는 `effective_date`, `temporal_cohort`, `CategoryFilters`, `ChainRiskQuery`, `assemble_public_subset`, `LlmError`, `interpretationMatches`의 본문은 확인하지 못했다.
- §1·§8.1의 PR/배포/테스트 기록은 과거 기록으로만 읽었다. 이번 검토에서 재현하거나 새로 실행했다고 주장하지 않는다.

#### 8.2.2 판정: **REVISE**

전체 방향(같은 RR 세션 재사용, 6필드 명시 투영, 서버 문장 + 모델은 ID만 선택, 4문단 유지, 유리/불리 후보 제외, v1 불변, 전체 인구 미확정 유지, 새 키·0013 불필요)은 기존 소스로 구현할 수 있고 범위도 가장 작다. 다만 아래 **차단 4건**은 구현자가 임의로 정하거나, 설계에서 보장한다고 쓴 내용이 실제 코드에서 성립하지 않는다. 이 4건을 문서에서 결정한 뒤 PASS로 바꿀 수 있다.

#### 8.2.3 차단(blocking) 지적

**B1. `analysis_date == context.as_of` 동치 조건이 정상 요청을 500으로 만들 수 있음**
- Risk 쪽 `_checked_risk`는 `target == effective_date(reference, MIN_OPEN_DATE, query.as_of)`, 즉 **고정 하한 `MIN_OPEN_DATE`**를 쓴다.
- 인구 쪽 `_get_population_reference`는 `minimum = MIN(Store.open_date) WHERE temporal_cohort(query, reference)`, 즉 **업종별 cohort 최소 개업일**을 쓴다. 이 값이 `None`일 수도 있다.
- 두 값이 다르면(요청 월이 업종 최소 개업월보다 이르거나, cohort가 비어 있는 경우 등) 위반이 아닌 정상 입력도 §3.1-2/5 규칙에 따라 500이 된다. `effective_date` 본문과 `as_of` 하한 검증이 발췌에 없어 이런 경우가 실제로 생기는지 확인하지 못했다.
- 결정 필요(하나 선택):
  - (a) `as_of` 검증 하한 ≥ 모든 업종의 cohort 최소 월임을 코드로 증명하고, 그 경계 회귀(가장 이른 허용 월 × cafe/restaurant)를 §7에 추가한다. 그러면 500 유지가 타당하다.
  - (b) 불일치를 손상이 아닌 "비교 불가"로 보고 상태를 하나 정의한다. 다만 이 경우 닫힌 `ReferenceStatus`를 확장해야 하므로 (a)를 권고한다.
- 함께 정리할 것: "관측일 ≤ 분석일"만 적혀 있다. 소스 쿼리는 `observation_date ∈ [target 월 1일, target]`이므로 **하한(같은 월)도 검사**한다고 적는다. `scope.category/sub_category/as_of`가 투영 입력과 같은지도 같이 검사한다(비용 없음).

**B2. 인구 문장의 숫자 검증이 사실상 항상 통과함**
- `render_interpretation`에서 본문(body)은 `context={"analysis": ..., "approved_narrative": catalog.narrative.candidates()}`로 검증한다. 후보 문장 자체가 허용 숫자 집합에 들어가므로 4번째 문단의 숫자는 **어떤 값이어도 통과**한다.
- §4.1에 따라 인구 문장은 `official_values`/`missing_data`에 넣지 않는다. 그래서 analysis-only로 검사하는 첫 번째 `verify_output`(visible 텍스트)에도 걸리지 않는다.
- 결과적으로 §4.2의 "verify_output으로 서버 수치와 문장 숫자 일치를 증명"은 현재 구조에서 성립하지 않는다.
- 최소 수정: 인구 부분 문장을 하나의 고정 문자열로 만들고 `render_interpretation`(또는 `build_catalog`)에서 **`{"analysis": context}`만으로 별도 `verify_output`**을 한 번 더 실행한다. 이 문장의 숫자는 관측일과 display뿐이므로 analysis-only로 통과해야 정상이다.
- 추가할 회귀: display 하나를 1자리 바꾼 문장이 `UNKNOWN_NUMBER`로 거절되는지 확인한다. 검증기 자체는 바꾸지 않는다.

**B3. 배포 순서 때문에 FE 고정 안내와 본문이 모순되는 구간이 생김**
- §6-5는 BE 배포 후 FE 배포 순서다. 그 사이 운영 FE의 `MESSAGES.ai.info.unavailableText`("미확보 매출·생활인구 … 분석에 사용하지 않아요")와 rules 마지막 줄이, 새 본문의 부분 생활인구 문장과 같은 화면에서 모순된다. "FE 고정 안내 모순 없음" 요구를 위반한다.
- FE는 `evidence`가 `[key: string]: unknown`이라 새 필드를 optional로 받을 수 있다. 따라서 **FE를 먼저 배포**하고 BE를 나중에 배포하는 순서로 바꾼다.
  - FE는 `evidence.population_reference`가 없으면 기존 문구, 있으면 "전체 생활인구는 미사용 · 공개 부분자료 비교만 별도 참고(관측일 X)" 문구를 쓴다.
  - 롤백도 BE만 되돌리면 된다.
- §6-1/5 순서와 §7 배포 행을 이에 맞게 고친다.

**B4. outbound `metrics`/`quality` 필드 집합이 확정되지 않음**
- §3.2 "PublicNumber 중 … 서버 문자열·display·zero/rounding/reason"에서 `value`(최대 5자리 소수 문자열)를 넣는지 정해지지 않았다. 구현자마다 hash/캐시·검증기 허용 숫자·FE evidence가 달라진다.
- 권고: `display, exact_zero, rounded, unit, reason`만 보내고 `value`는 제외한다.
  - 모델과 문장에 불필요하다.
  - `\d{2,3}\.\d{4,}` 좌표 패턴과 비슷한 문자열이 허용 숫자 집합에 들어가는 것도 막는다.
- "display 일치 검사"는 display 규칙을 다시 구현하지 않는다(규칙이 이중화되면 어긋난다). `PopulationReference.model_validate` 재검증과 필드별 `unit` 고정(share=`pct_of_public_subset`, ratio=`ratio`)만 확인한다고 명시한다.
- `quality`의 정확한 필드명 목록도 적는다: `selected_grid_count, used_grid_count, grids_without_rows, candidate_component_count, used_component_count, excluded_component_count, excluded_by_hour_class.{day_only,night_only,both}`.
- 명시적으로 제외할 필드: `observed/suppressed/missing_rows`, `absent_hours_within_candidates`, `version_unlocated_*`.

#### 8.2.4 비차단(nonblocking) 지적

- **N1 숫자 whitelist의 실효 강도.** `allowed_numbers`는 문맥 전체에서 허용 숫자를 모은다. quality 카운트와 `"06-17"`, `"00-05,18-23"`(0,5,6,17,18,23)이 추가되면 Risk/활동 문장의 숫자 검사도 그만큼 느슨해진다. 검증기 코드는 그대로지만 효과는 약해지므로, 숫자 필드는 B4의 최소 집합으로 제한한다. 시간대는 숫자 대신 닫힌 Literal 라벨(`day_06_17` 등) 사용을 검토한다.
- **N2 pending 보호 범위.** `_pending_ids`는 `id` 키가 있는 객체만 본다. 인구 source 블록(`status: no_data`)은 대상이 아니다. 인구 쪽 보호는 서버 고정 문장과 B2의 검증에만 의존한다는 점을 문서에 적는다.
- **N3 `sources` 키와 출처 검사.** `_sources`가 문맥의 `source` 키 값 `local/long/short`도 known source로 수집한다. 실질적 해는 없다. 키 이름은 `sources`/`source`를 유지해도 되지만, 대안으로 `population_sources`/`kind`를 쓰면 출처 검사 의미가 섞이지 않는다. 결정만 한다.
- **N4 반복·길이 검사.** 본문 검증에서 `_has_repetition`은 10자 이상 같은 문장이 반복되면 실패한다. 세 원천에 같은 한계 문장을 반복하지 말고 한 번만 쓴다. `population_not_available` 문구를 늘리면 visible 텍스트 상한 2000자에 더 가까워진다. history + estimate 브랜드 + 3지표 pending 등 최장 조합 회귀를 §7에 명시한다.
- **N5 v1 공유 코드 분기.** `build_catalog`/`build_narrative`는 v1·v2 공용이다. 인구 문장과 `population_not_available` 문구 변경은 `isinstance(c, ChainRiskInterpretContext)` 분기 안에만 둔다. 공용 `InterpretItem.indicator_ids`/`used_indicator_ids` Literal을 넓히면 v1 OpenAPI enum도 바뀐다(값은 불변). v1 응답 골든 비교 회귀로 "값 불변"을 증명한다.
- **N6 기존 고정 문장과의 모순.** 4번째 문단의 "확보되지 않은 매출·생활인구로 수요나 수익성을 추정하지 않았습니다"와 `system.md` 규칙 20("생활인구 … 추정하지 않습니다")은 v2에서 부분 비교와 함께 쓰인다. "전체 생활인구 미확보, 공개 부분자료는 비중 비교만"으로 v2 문장과 v2 프롬프트 규칙을 함께 고친다. 새 규칙 문구 초안을 구현 PR에 포함한다. Risk `day_night_ratio`(pending, "주야간 인구비")와 부분 주간/야간 비중을 같은 지표로 읽지 않게 한다는 문구도 넣는다.
- **N7 응답 meta 출처.** `interpret_risk`의 meta `source`는 `["R5","R6"]` 고정이다. v2에서 부분 숫자를 본문에 쓸 때 R4를 추가할지 정한다. 권고: 어떤 원천이든 partial이 본문에 쓰이면 v2 meta에 `R4` 추가, v1 불변.
- **N8 deadline 예외 계층.** `before_cursor_execute`의 `check()`가 던지는 `LlmError`가 `ValueError` 하위 클래스라면 `get_population_reference`가 이를 500으로 바꿔 503 의미가 깨진다. 기존 Risk 경로가 동작하므로 아닐 가능성이 높지만 발췌로는 확인할 수 없다. "인구 SQL 직전 deadline → 503" 회귀를 §7에 명시한다.
- **N9 성능.** 격자 선택은 `ST_Transform(center)`를 geography로 캐스트하고 `spatial_index=False`라 버전 내 격자를 전부 훑는 형태다. 풀 1·statement_timeout 10초·LLM 전체 예산 안에서 prepare 시간이 늘어난다. 복제 DB 측정의 합격 기준(예: 1000m 반경 prepare 시간이 기존 대비 몇 초 이내, 예산의 몇 % 이하)을 숫자로 정한다. 정하지 않으면 롤아웃 판정 기준이 없다.
- **N10 D 재확인 중복.** 같은 RR 스냅샷에서 Risk와 인구가 모두 `current_provenance`를 호출하므로 §3.1-3의 별도 D 비교는 설계상 항상 같다. 쿼리를 하나 더 쓰지 않으려면 analysis_date·월 범위 검사(B1)로 대체해도 된다. 유지한다면 테스트 목적임을 적는다.
- **N11 evidenceChip.** §6-3이 "연결할지"로 열려 있다. 권고: 활동 ID와 같게 이름만 표시하고 `target=null`로 이동하지 않는다. 이동하면 AI 해석 화면을 벗어나는 기존 문제가 생긴다. `MESSAGES.ai.evidenceNames.population_public_subset`만 추가한다.
- **N12 보고서/PDF.** `useReportData`는 인구 카드(GET)와 캐시된 AI를 따로 쓴다. 보고서의 AI 영역에는 AI evidence의 관측일을 표시하고, 카드와 날짜가 다르면 둘 다 표시하며 하나로 합치지 않는다고 §6-4에 적는다.
- **N13 캐시.** prepare가 캐시 hit에도 매번 실행되므로 "오래된 숫자 재사용 금지"는 현재 구조로 이미 충족된다. context_hash/payload가 키에 포함되기 때문이다. `CHAIN_SELECTION_CACHE_RULE` 증가는 필수는 아니지만 무해하다. 인구 version id/sha digest는 `version_json`에만 넣고 응답 meta에는 hash만 노출한다(현행과 같음).

#### 8.2.5 요구 항목별 확인 결과

| 항목 | 결과 |
|---|---|
| 같은 읽기 전용 RR·HTTP 자기 호출 없음·모델 호출 전 연결 반환 | 충족(`_prepare`의 세션 안에서 호출하면 됨) |
| 정확한 6필드 투영 | 충족. `sub_category`는 원래 값(None 포함)을 그대로 `CategoryFilters`에 넘기고 기본값 확장은 스키마에 맡긴다고 명시 권고 |
| 전역 D·업종 월 하한 | **B1** |
| 존재하지 않는 metadata 필드 | 없음. `population_filter_applied`는 data.scope, `source_validation_performed/population_total_validated`는 meta에 실제로 있음 |
| 날짜/반경 일치 | B1(하한·scope 동치 추가) |
| 원 식별자·`name` 키 비노출 | 충족(`method.name` → `calculation_method` 개명, 금지 목록 명시) |
| 독립 outbound 투영 | **B4** |
| partial ≠ 전체/fact, v1 보존 | 충족(N5 회귀 필요) |
| 4문단 그룹 | 충족 |
| 0/반올림/null/외국인 원천 독립 | 충족(문장 규칙 명확) |
| 승인된 서버 문장 + 모델 ID만 | 충족 |
| 유리/불리 추론 없음 | 충족 |
| 숫자/개인정보/길이 검증기 불변 | 코드 불변은 충족, 실효 검증은 **B2**·N1 |
| 프롬프트/캐시 drift 식별 | 충족(N6 문구 필요) |
| 유효 no_data vs 손상 metadata | 충족(서비스가 ValueError→500, 정상 상태→200 경로). N8 회귀 필요 |
| FE 고정 안내·근거 UI | **B3**, N11, N12 |
| 롤아웃·실제 테스트 합격 기준 | B3, N9(숫자 합격선 없음) |
| 전체 인구 공식 근거 | 미확정 유지, 만들어 내지 않음 — 충족 |

이 검토에서 실행한 테스트는 없다. 위 판정은 발췌 소스와 문서 정합성에 대한 정적 검토 결과다.

### 8.3 Codex 최종 대조

첫 실제 Claude 검토는09:18:04Z~09:21:06Z, exit0/is_error=false/3turns, MD 직접 Read/Edit, source SHA 보존·권한 거부0이었다. REVISE와 지적 이력은8.2절에 보존했다.

- B1: 추가로 `risk.py:_get_risk`(cohort MIN), `spatial_stores.py:effective_date`, `store_cohort.py:temporal_cohort`, `CategoryFilters`를 대조했다. `_checked_risk`의 고정 하한은 실제 Risk의 업종별 월 검증을 우회하지 않는다. 같은 정상 요청 T가 같다는 근거와 가장 이른 월/빈 cohort 회귀, scope·관측월 하한 검증을3.1/7절에 구체화했다. 불일치를 유효 no_data로 숨기지 않는다.
- B2: 채택. 인구 문장을 analysis-only로 별도 선검증하고 후보 자체를 whitelist에 넣지 않는다. 기존 전체 본문 검증을 유지하고 whitelist가 필드 의미를 증명하지 않는 한계도 적었다.
- B3: 채택. 호환 FE 먼저 배포하고 기존 BE 응답을 확인한 뒤 BE를 배포한다. 복구는 BE가 먼저다.
- B4: 채택. 5개 metric 키와 정확한 quality 키를 확정, value/추가 행 카운터 제외. 포맷터를 복제하지 않고 helper display를 직접 대조한다.
- N1~N7/N10~N13: 최소 키·pending 보호의 실제 경계·출처 구분·최대 길이/반복·v1 분기/공유enum의 경계·v2 문구·R4 meta·D 중복조회 제거·이동 없는 근거칩·보고서 날짜·내부 캐시 digest를 명시했다.
- N8: `LlmError`는 ValueError가 아닌 Exception의 직접 하위 클래스임을 실제 소스로 확인했다. SQL 직전 deadline의503 회귀는 추가한다.
- N9: warm prepare15회 각≤6초/증가≤3초, 실제 모델 최대2회 및 기존 전체 예산이라는 후속 합격선을 정했다. 현재 달성 결과라고 쓰지 않았다.

보완본의 실제 Claude 재검토 후 최종 판정을 이어 기록한다. 이 단계에서 앱/FE/DB/운영 변경이나 새 수치 검증은 수행하지 않았다.

### 8.4 실제 Claude Code 최종 재검토

#### 8.4.1 검토 범위와 근거

- 검토자: Claude Code (claude-opus-5-5), 2026-11-16. 이 MD를 Read하고 이 절만 Edit로 추가했다. §1~§8.3 본문은 고치지 않았다. shell·git·DB·네트워크·하위 에이전트·테스트 실행·배포는 하지 않았다. 앱/FE 코드는 수정하지 않았고 env/설정/키는 읽지 않았다.
- 근거: 보완된 §1~§7과 §8.3, 그리고 대화에 붙여 넣은 소스 발췌다. 발췌는 8.2와 같은 파일에 이번에 추가된 `risk.py`(`get_risk`/`_get_risk`), `spatial_stores.py:effective_date`, `store_cohort.py`(`temporal_cohort`/`current_provenance`/`MIN_OPEN_DATE`), `store_filters.py:CategoryFilters`, `ai/client.py:LlmError`를 더한 것이다. 저장소 파일을 직접 대조하지 않았다.
- 여전히 본문을 확인하지 못한 것: `ChainRiskQuery.legacy`, `assemble_public_subset`, `load_chain_prompt_bundle`, `AppError` 클래스 계층, FE `interpretationMatches`.
- §1·§8.1·§8.3의 PR/배포/CI/실행 시각 기록은 과거 기록으로만 읽었다. 이번에 재현하거나 새로 실행했다고 주장하지 않는다.

#### 8.4.2 판정: **PASS**

8.2의 차단 지적 B1~B4는 보완본에서 모두 해소됐다. 남은 지적은 아래 F1~F7이며 모두 비차단이다. 설계의 큰 결정을 바꾸지 않고 구현 PR 안에서 문구나 회귀 하나로 고정할 수 있다. 새 API 키, 0013 승인, schema 변경, 검증기 완화는 필요 없다. 전체 생활인구의 공식 근거는 계속 미확정이며, 이 설계는 그 근거를 만들어 내지 않는다.

PASS는 "설계가 기존 소스로 구현 가능하다"는 판정이다. 구현·테스트·배포가 끝났다는 뜻이 아니다. 이번 검토에서 실행한 테스트는 없다.

#### 8.4.3 B1~B4 해소 확인

**B1 해소 — Risk와 인구의 T가 정상 요청에서 같다.** 8.2에서는 "`_checked_risk`의 고정 하한만으로는 Risk의 실제 cohort를 알 수 없다"고 지적했다. 이번에 제공된 `_get_risk` 본문으로 다음을 확인했다.
- `_get_risk`가 이미 `minimum = MIN(open_date) WHERE temporal_cohort(query, reference)`로 `effective_date(reference, minimum, as_of)`를 부른다. 다음 두 요청은 Risk 단계에서 `AS_OF_OUT_OF_RANGE`로 끝나고 인구 조회까지 가지 않는다.
  - 요청 월이 업종 cohort의 최소 월보다 이른 요청
  - cohort가 비어 있는데 최신 월이 아닌 요청
- `get_risk`는 `SQLAlchemyError/ValueError/TypeError`만 500으로 바꾸므로 `AppError`는 그대로 전달된다. 다만 `AppError`가 `ValueError` 하위가 아니라는 점은 발췌로 확인하지 못했다. 기존 동작이며 이번 설계로 바뀌지 않는다.
- 통과한 요청은 "요청 월 ≥ cohort 최소 월 ≥ 1960-01"을 만족한다. 따라서 `MIN_OPEN_DATE`를 넣은 `_checked_risk`의 재계산도 같은 T를 낸다. 이 비교는 방어 검사일 뿐이다.
- 인구 `_get_population_reference`도 같은 RR 트랜잭션에서 `current_provenance`를 다시 호출하므로 같은 reference를 얻는다. `temporal_cohort`는 `category`와 `sub_category or 기본값`만 사용하므로 6필드 투영에서 같은 cohort와 같은 minimum, 같은 T가 나온다. 결국 `analysis_date == context.as_of` 위반의 500은 손상이나 드리프트에서만 생긴다.
- 관측월 하한 `[T 월 1일, T]` 검사, scope 동치, 빈 cohort·최초 월·그 직전 월·현재 월 회귀도 §3.1-2/3과 §7에 반영됐다. 남은 표현상 모호점은 F1 하나다.

**B2 해소.** §4.2는 인구 문장을 만든 직후 `{analysis: projection}`만으로 별도 `verify_output`을 실행하도록 했다. 후보 문장 자체는 허용 숫자 집합에서 뺐다. 실패하면 500/no-store다.
- 날짜는 문자열로 직렬화되므로 연·월·일 숫자가 허용되고, display의 숫자도 허용된다. 그 밖의 숫자는 `UNKNOWN_NUMBER`로 거절된다.
- 주간·야간 값을 바꿔 넣거나 원천을 바꾼 문장은 whitelist로 잡히지 않는다. §4.2는 이를 canonical builder 비교 회귀로 따로 잡는다고 적었다. 검증기 코드는 바뀌지 않는다.
- 선검증 문맥을 얼마나 좁힐지는 F2에 적었다.

**B3 해소.** §6-5/6과 §7은 다음 순서로 고정됐다: 호환 FE 먼저 → 기존 BE에서 기존 안내 확인 → BE 배포. 복구는 BE를 먼저 되돌린다.
- FE는 `evidence.population_reference` 유무로 `unavailableText`와 rules 마지막 줄을 분기한다.
- 새 FE와 구 BE 조합은 기존 문구가 되고, 새 FE와 새 BE 조합은 새 문구가 된다. 따라서 어느 배포 시점에도 고정 안내와 본문이 모순되지 않는다.

**B4 해소.** metrics의 키는 정확히 5개(`display,exact_zero,rounded,unit,reason`)이고 `value`는 뺐다. quality의 정확한 키 목록과 제외 카운터도 §3.2에 확정됐다.
- 포맷터는 다시 구현하지 않는다. helper가 만든 display를 그대로 복사하고 대조 검사를 추가한다.
- unit은 share=`pct_of_public_subset`, ratio=`ratio`로 고정했다.

**N8 확인.** 제공된 `client.py`에서 `LlmError(Exception)`임을 확인했다.
- `get_population_reference`의 래퍼는 `ValueError/TypeError/OverflowError`만 잡는다. `prepare_chain_interpretation`의 except 튜플에도 `LlmError`가 없다.
- 따라서 SQL 직전 deadline `LlmError`는 `interpret_risk`의 `except (TimeoutError, LlmError)`까지 그대로 가서 기존 `AI_UNAVAILABLE` 의미를 유지한다. §7의 회귀로 고정된다.

#### 8.4.4 비차단 지적 (구현 PR에서 고정)

- **F1 `scope.sub_category` 비교 기준.** 인구 `_response`는 `tuple(sorted(query.sub_category))`, 즉 투영 입력을 **확장 없이** 그대로 넣는다. 미지정이면 `()`이다. 반면 `context.sub_category`와 `chain_query_parts`는 기본값으로 확장한 값이다.
  - §3.1-2의 "투영 입력(서버의 sorted sub_category 포함)"을 확장값 `sub`로 읽고, 투영은 원래 값으로 하면 `sub_category`를 지정하지 않은 모든 기본 요청이 500이 된다.
  - 권고: 투영에는 `checked.sub_category` 원래 값을 그대로 넘긴다(8.2.5 권고, GET과 같은 동작). 비교는 `tuple(sorted(projected.sub_category))`와 한다.
  - "cafe/restaurant의 sub_category 미지정 기본 요청 → 200" 회귀를 §7 행에 명시적으로 넣는다.
- **F2 선검증 문맥 범위.** §4.2에는 "`typed_projection`"과 "필요한 날짜/display/상태만"이라는 두 표현이 함께 있다. 좁은 쪽으로 고정한다: `analysis_date`, `observation_date`, 문장에 쓰는 원천의 `day_share_pct/night_share_pct`의 display·rounded·reason. quality 카운트가 들어가면 우연히 같은 숫자인 잘못된 display가 통과할 수 있다.
- **F3 whitelist 확대의 잔여 영향(N1 부분 해소).** `day_hours="06-17"`, `night_hours="00-05,18-23"`과 quality 카운트가 전체 `json_context()`에 들어간다. 그러면 visible 텍스트와 본문 검증에서 0·5·6·17·18·23과 각 카운트가 Risk·활동 문장의 허용 숫자로도 추가된다. Risk·활동 문장은 서버 builder가 만들므로 실해는 작다. 둘 중 하나를 고르면 된다.
  - 숫자 없는 닫힌 라벨로 바꾸고, 시간 정의는 v2 프롬프트 문구에 둔다.
  - 이 잔여 영향을 §4.2 한계에 한 줄로 남긴다.
- **F4 v2 프롬프트 문구의 키 이름.** §6 말미의 새 규칙 초안 "approved_narrative 외 수치를 생성하지 않는다"에서 `approved_narrative`는 서버 검증 문맥의 이름이다. 모델 payload에는 `analysis`와 `candidates`만 있다. "candidates.narrative 문단 외 수치를 생성하지 않는다"로 고친다. 프롬프트 지문은 고친 문구로 확정한다.
- **F5 4번째 문단의 기존 문장(v2).** §4.1은 `population_not_available` 결측 문구만 바꾼다. narrative 고정 문장 "확보되지 않은 매출·생활인구로 수요나 수익성을 추정하지 않았습니다"를 v2에서 어떻게 쓸지 정해지지 않았다.
  - 권고: v2에서만 "전체 생활인구와 매출은 확보되지 않아 수요나 수익성을 추정하지 않았습니다"로 바꾼다.
  - 새 인구 한계 문장과 10자 이상 같은 문장이 생기지 않도록 반복 검사 회귀에 넣는다.
- **F6 근거 ID와 R4 부착 조건.** `pending/no_data/not_supported` 상태만 안내하는 문장에도 `population_public_subset`을 `indicator_ids`에 붙일지 정해지지 않았다.
  - 권고: 인구 문장이 있으면 상태와 무관하게 ID를 붙인다. FE 정보창의 상태 표시와 맞추기 위해서다.
  - `meta.source`의 R4는 §6대로 partial을 쓸 때만 붙인다. 두 조건이 다르다는 점을 테스트로 고정한다.
- **F7 내부 version digest 키.** §5의 "내부 data-version metadata의 digest"에 들어갈 키를 현재 meta에 실제로 있는 키로 명시한다: `format_version, rule_version, observation_version_id, grid_version_id, input_sha256, content_sha256, grid_input_sha256, grid_content_sha256`.
  - 이 값들은 `version_json`에만 넣고 LLM이나 응답에는 hash만 노출한다.
  - `population_snapshot_token`은 단독 키로 쓰지 않는다.

#### 8.4.5 요구 항목 최종 확인

| 항목 | 결과 |
|---|---|
| 같은 읽기 전용 RR·자기 HTTP 없음·모델 호출 전 연결 반환 | 충족 |
| 정확한 6필드 투영 | 충족 (F1 비교 기준 고정) |
| 전역 D·업종 월 하한 | 충족 (B1 해소, 제공된 `_get_risk`/`effective_date` 근거) |
| 존재하지 않는 metadata 필드 | 없음 (F7 키도 현재 meta에 존재) |
| 날짜/반경 일치 | 충족 (관측월 하한 포함) |
| 원 식별자·`name` 키 비노출, 독립 outbound | 충족 (B4 해소) |
| partial ≠ 전체/fact, v1 보존, 4문단 | 충족 (v1 골든 회귀 명시) |
| 0/반올림/null/외국인 원천 독립 | 충족 |
| 승인된 서버 문장 + 모델 ID만, 유리/불리 추론 없음 | 충족 |
| 숫자/개인정보/길이 검증기 불변 | 충족 (B2 해소, F2·F3 잔여) |
| 프롬프트/캐시 drift 식별 | 충족 (F4 문구) |
| 유효 no_data vs 손상 metadata, deadline 503 | 충족 (N8 소스 확인) |
| FE 고정 안내·근거 UI·보고서 날짜 | 충족 (B3 해소) |
| 롤아웃·실제 테스트 합격선 | 충족 (숫자 합격선은 미측정 목표로 명시됨) |
| 전체 인구 공식 근거 | 미확정 유지, 만들어 내지 않음 |

이 판정은 붙여 넣은 소스 발췌와 문서 정합성에 대한 정적 검토 결과다. 테스트·DB·모델 호출·배포는 실행하지 않았다.

### 8.5 Codex 최종 확정과 이번 검증

실제 최종 검토는09:23:28Z~09:26:07Z exit0/is_error=false/3turns, MD 직접 Read/Edit·source SHA 보존·권한 거부0으로 **PASS**였다. 1차 차단4건의 해소에 이견이 없다.

F1~F7은 비차단 상세화로 채택했다. 원래 sub_category와 미지정 tuple, 최소 sentence_evidence, 전체 검증의 whitelist 확대 한계, 모델 payload의 candidates.narrative 명칭, v2 고정 문장, 상태 안내의 근거 ID와 R4의 서로 다른 조건, 내부 digest8키를 위 본문에 확정했다. 공개 helper의 raw value나 식별자를 새로 보내는 변경은 없다. 두 업종의 sub_category 미지정 기본 요청200을 후속 필수 회귀에 포함한다. 이 최종 상세화 자체를 Claude가 다시 검토했다고 기록하지 않는다.

이번 변경은 설계 MD/CLAUDE.md/README/작업계획 4개다. 새 문서 연결·UTF-8·known-secret 비포함·diff 공백과 기존 사용자 파일/환경 보존을 검사한다. 앱/FE 코드·기존 배포는 변경하지 않았고, 기존 인구 배포의 테스트 숫자나 실제 모델 호출을 이번 실행으로 재사용하지 않는다. 정확한 문서 head CI/PR·정상 병합 결과는 연결 PR과 #182 실행 기록을 따른다. 후속 구현 이슈는 이 설계를 다시 반복하지 않고 6~7절의 순서/완료 기준을 실행한다.
