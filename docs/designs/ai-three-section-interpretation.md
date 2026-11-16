# AI 해석 3영역 개편 설계

작성일: 2026-11-17 (KST). 작성: Codex. 기준 BE `e41f7d5` / FE `84f6fe3`의 원격 develop. 사용자 스케치를 기준으로 작성했다.

현재 상태: 설계 작성 및 Claude Code 3차 정적 검수 PASS. 비차단 권고를 아래처럼 후속 명확화했다. Claude Code 실제 검수와 보완 결과는 12절에 기록한다. 이 문서는 기능 구현·테스트·Gemini 실호출·배포 완료를 의미하지 않는다. 설계와 검수를 먼저 마친 뒤 이 계약으로 구현한다.

## 1. 사용자 요구와 결정

`AI 해석 보기`를 누르면 바깥 결과 블록 안에 다음 순서로 보여 준다.

```text
AI 해석                               ⓘ 자료 범위·한계
주소·업종·반경·분석 시점
┌─────────────────────────────────────────────┐
│ ┌──────────────────┐ ┌───────────────────┐ │
│ │ 이점             │ │ 유의점            │ │
│ │ 근거 있는 항목   │ │ 근거 있는 항목    │ │
│ └──────────────────┘ └───────────────────┘ │
│ 수치로 본 해석                             │
│ 실제 자료의 수치·기준을 정리한 문단         │
│ 수치 요약: 값 / 기간·공간 / 출처·상태       │
│ 계약 전 확인사항                           │
│ 안내 문구                     3개 중 0개 확인│
│ □ 시간대별 현장 유동 확인                  │
│ □ 보행 동선과 출입 접근성 확인             │
│ □ 가시성과 주변 점포 확인                  │
└─────────────────────────────────────────────┘
```

- 상단 왼쪽은 이점, 오른쪽은 유의점. 하단 종합 해석과 계약 전 확인사항은 전체 폭이다.
- 모바일에서는 이점 → 유의점 → AI 해석 → 계약 전 확인사항 순서의 한 단 배치다. 360px에서 가로 넘침 없이 표시한다.
- 이점은 검증 가능한 비교 근거가 있을 때만 제공한다. 자료가 없으면 `현재 자료로 확인할 수 있는 이점이 없어요.`라고 표시한다. 성공 가능성·임대료·가시성·실제 보행량을 추정해서 채우지 않는다.
- 한 번의 정상 신규 생성에 Gemini HTTP 호출 3회를 사용한다. 역할은 이점 / 유의점 / 수치 중심 종합 해석으로 고정한다. 체크리스트는 모델 호출 대상이 아니다.
- 인증 오류·취소·시간 초과·할당량 부족으로 3회가 모두 발송되지 못할 수 있다. 실패를 숨기기 위해 나머지 호출을 소비하지 않는다. 실패 경로도 최대 3회다.
- 같은 검증 결과의 캐시 재사용과 PDF 열기는 0회다. 수동 재시도는 새로운 생성 요청이며 최대 3회가 다시 발생할 수 있다. 이를 사용량 안내와 기록에서 구분한다.

## 2. 현재 코드에서 확인한 차이

| 위치 | 현재 동작 | 필요한 변경 |
|---|---|---|
| FE `AiInterpretation.tsx` | 사용자 버튼 POST·조건별 캐시·취소·기준 문맥 대조 | 새 응답 모델·새 경로·3영역 상태와 캐시 |
| FE `AiResultCard.tsx` | `body`를 문단으로 나열한 뒤 체크리스트 | 상단 2열 + 하단 해석·수치 요약 + 고정 체크리스트 |
| FE `AiChecklist.tsx` | React state, 비영속 체크·확인 개수 | 재사용. 조건/새 결과 변경 시 초기화 |
| BE `risk_interpret.py` | 서버 재조회 후 1개 selection 생성·캐시 | 새 조정기에서 같은 증거로 역할별 생성 3개 |
| BE `interpretation.py` | favorable/unfavorable 후보·4문단·체크리스트 후보 | 독립 역할 후보·수치 문장·정확히 고정된 체크리스트 |
| BE `verified.py` | `MAX_GENERATIONS=2` | 새 경로에서는 재생성하지 않는 검증기 사용 |
| BE `gemini.py` | 요청마다 공급자 정책의 재시도 가능 | 새 경로 전용 정책 `max_retries=0` |
| BE `context_v2.py` | Risk·활동·이력·격자 공개 부분자료를 같은 RR에서 준비 | 위치별 매출·행정동 인구도 별도 typed 참고 문맥으로 준비 |

최신 v2는 브랜드 제거 후 `AnalysisRiskQuery` / `prepare_v2_interpretation`을 사용한다. 오래된 chain 전용 문서를 현재 코드로 취급하지 않는다. 새 구현도 브랜드 필드를 복구하지 않는다.

기존 Gemini client는 공급자 재시도, 기존 검증기는 1회 재생성이 가능하다. `generate_verified`를 역할별로 그대로 3번 호출하면 HTTP 3회 보장이 깨진다. 기존 경로의 정책을 전역 변경하지 않고 새 경로에서만 1회 생성·1회 검증을 사용한다.

## 3. 자료 준비와 근거 목록

FE 수치를 요청 본문으로 받지 않는다. 단일 READ ONLY REPEATABLE READ 세션에서 기존 서비스 함수를 호출하고, 모든 연결을 반환한 뒤 모델을 호출한다. 기존 prepare 함수를 각각 실행해 별도 트랜잭션을 만들지 않고 새 prepare에 결합한다.

| 항목 | 서버 함수와 실제 응답 필드 | 기준·결측 |
|---|---|---|
| Risk | analysis_v2.risk / data.indicators | 분자·분모·status/reason·공식/참고 구분 |
| 활동 | analysis_v2.activity / data.recent_12m, data.avg_operating_months | 선택 전체 통합 평균 그대로. 세부 업종 평균을 재평균하지 않음 |
| 카페 매출 | get_location_reference / sales.top_markets_estimate.metric | 실제 method·자료분기·상권 범위. 없으면 미제공 |
| 음식점 매출 | 같은 함수 / sales.market_aggregation과 top_markets_estimate | restaurant_market_rollup_v1와 top3_markets_by_store_count_v1, selected_market_codes와 top.markets 일치 때만 top.metric. RestaurantSales와 같은 허용 조건·업종 합산·부분성 |
| 행정동 인구 | 같은 함수 / living_population.items, day_night.items | area_ref/observation_date/provenance_ref/population_scope 4필드 일치로만 짝지음. 복수 동은 각각 표시·비합산 |
| 격자 부분자료 | get_population_reference / 원천별 결과 | 전체 인구와 구분. 행정동 값 대체 금지 |
| 주소 이력 | address_context.decode_pair + address_history.get_address_history(session,query,pair) / v3 응답의 집계·selection·coverage | 이미 받은 서명 context와 현재 AddressHistoryQuery를 검증한 뒤 같은 RR 재조회. 옛 get_history로 대체하지 않음 |

새 요청의 optional address_history에는 이미 발급받은 context와 현재 scope/detail 조건만 보낸다. 서명·규칙·선택 범위와 현재 query의 주소/위치 정합을 검증하고 v3 DB 함수 준비도 확인한다. 현재 AddressPair는 좌표를 담지 않으므로 그대로 좌표 바인딩이 된다고 주장하지 않는다. address-context 발급 시 기존 검증된 lat/lng/category를 포함하는 context_version=2 서명 payload를 발급하도록 함께 확장한다. decode_pair는 기존v1/v2 모두 허용해 기존 주소이력 GET은 호환하고, 새 보고서에 이력을 넣을 때만v2의 좌표/업종을 query와 대조한다. 옛 토큰이면 모델0회409 AI_HISTORY_CONTEXT_OUTDATED로 구분하고 “주소를 다시 확인해 주세요”를 안내한다. 이 오류는 GET 갱신으로 해결되지 않으므로 기존 주소 확인/발급 흐름으로 이동시킨다. 기존 URL의v1토큰도 같게 처리하고 자동 Gemini 재요청은 없다. 이때 발급 단계의 Kakao 요청과 Gemini3회를 구분한다. 새 보고서 자체는 토큰을 발급하지 않는다. 서명 토큰만 맞고 다른 좌표인 요청은 거절한다. 새 생성 과정에서 Kakao 또는 context 발급을 추가 호출하지 않는다. 이력을 요청한 상태에서 서명 키/0014 함수가 미준비면 전체 보고서를503(모델0회)으로 종료한다. address_history router의 pool 재대기/새 session을 호출하지 않고 이미 준비한 RR 세션과 decode_pair/get_address_history만 사용한다. 이력 미조회·상세 위치 미확인은 not_requested/미확인으로 명시하고 가짜 같은자리 집계를 만들지 않는다. old history 필드를 복구하지 않는다.

MetricEvidence에는 id/kind/value(정확한 decimal 문자열 또는 null)/display/unit/status/reason/source_ids/period/spatial_scope/population_scope/filter_scope/denominator를 둔다. 금액은 FE Number 변환이나 임의 합산을 하지 않는다. 수치 요약은 표의 지원 대표/집계 값을 모두 서버 순서로 표시한다. 상권별·연도별 원자료 전체가 아니라 위 요약 범위이며 나머지는 기존 상세 보기를 사용한다.

모델에는 주소·좌표·점포명·건물키·층호 원문·서명 context·인허가번호·브랜드/개인 ID·내부 UUID를 보내지 않는다. 행정동/상권 식별 코드·이름도 임시 evidence ID로 대체하고 화면 이름·출처 링크는 서버가 붙인다. maxItems:0의 실제 Gemini 수용 여부는 미검증이며 거절 시 해당 role unavailable로 처리한다. 새 카탈로그는 기존 build_catalog의 sales_not_available/population_not_available/옛 history 문장을 재사용하지 않고 실제 상태로 작성한다. 위치 참고자료를 기존 Risk fact나 유리/불리로 자동 승격하지 않는다.

### 필수 baseline과 내부/공개 지문

baseline은 필수다. GET마다 발급하는 내용·판본 기반의 새 meta.ai_report_basis_token을 FE가 그대로 반환한다. FE JSON 재직렬화/해시나 MVCC snapshot·txid·요청 시작시간은 사용하지 않는다. 기존 reference_snapshot_token은 응답 data 직렬화 기반이지만 새 계약은 의미를 분명히 하기 위해 새 전용 토큰을 일관되게 사용한다.

| baseline 키 | 발급 GET / 실제 필드 | 지문 대상 / 재계산 |
|---|---|---|
| risk | /api/v2/risk → meta.ai_report_basis_token | 정규화 query + Risk 지표/기간/버전. analysis_v2.risk 재조회 후 issue_report_basis |
| activity | /api/v2/market/activity → meta.ai_report_basis_token | 동일 선택 조건의 통합 평균/활동 집계/판본. analysis_v2.activity 후 같은 함수 |
| location | /api/v2/location-reference → 같은 새 meta 필드 | query/time_mode + sales/행정동 인구·주야간의 실제 data/원천 판본. get_location_reference 후 같은 함수 |
| grid | /api/v2/population-reference → 같은 새 meta 필드 | 정규화6조건 + 원천별 부분 결과/판본. get_population_reference 후 같은 함수 |
| address_history | /api/v3/stores/location-history → 같은 새 meta 필드, 명시 미요청은 null | 검증된 서명문맥의 선택 범위 + 현재 집계/coverage/판본. get_address_history 후 같은 함수 |

해당 meta 필드는 현재 없는 경우 구현에서 추가한다. 기존 meta 필드 의미를 바꾸지 않는다. 중앙 issue_report_basis(kind, normalized_scope, redacted_data, source_versions)는 고정 JSON/Decimal/date 정규화와 도메인 ai-report-basis-v1을 사용한다. persistent HISTORY_CONTEXT_SIGNING_KEY에서 HKDF-SHA256(info=ai-report-basis-v1)으로 파생한 용도별 키의 HMAC이므로 식별자를 공개하지 않고 프로세스/독립 트랜잭션이 달라도 같은 내용이면 같은 토큰이다. 실제 판본의 관측일/loaded_at은 포함하지만 요청 생성시각 등 임시값은 제외한다. 서버가 수치를 그대로 재조회한 뒤 verify_report_basis로 대조한다. 무관한 DB 쓰기는 토큰을 바꾸지 않는다. 키 미설정이면 새 보고서는 모델0회 AI_UNAVAILABLE 503, 기존 GET은 정상 동작하되 새 meta 토큰만 생략한다. 토큰은 요청/로그에 수치나 식별 원문을 노출하지 않는다.

각 토큰과 분석일/time_mode는 필수이며 누락422, 값/범위 불일치409 AI_CONTEXT_CHANGED(모델0회)다. FE는409 때 무한 reload하지 않는다. 해당 GET들을 한 번 갱신하고 사용자에게 다시 요청하도록 안내한다. 자동 POST/구 endpoint fallback은 없다. 재차 불일치하면 기준을 확인하라는 안내만 유지한다. 키 교체나 실제 원천 갱신도 이 경로로 처리한다.

기존 Risk context_hash/data_version_hash 의미는 유지한다. 서버 내부 report_cache_key는 기존 CacheResources.key의 프로세스 비밀 HMAC을 사용해 query/검증된 이력 범위/판본·메트릭·후보·3종 프롬프트 버전과 SHA·모델·토큰 상한을 묶는다. 응답 report_context_hash는 식별자·좌표·context 토큰을 제외한 집계 문맥·자료 버전만으로 계산한다. 내부 key와 공개 hash는 별개이며 식별정보의 소금 없는 SHA를 공개하지 않는다.

FE도 Risk·위치참고·선택 이력·격자 GET의 현재 전체 baseline을 키/sectionsMatches에 사용한다. 새 선택 조건의 GET이 pending/error면 버튼을 대기시키고 GET을 최신화한 뒤 캐시를 비교한다. Risk만 같다고 예전 위치 참고 해석을 재사용하지 않는다. latest_reference는 실제 분기/관측일을 표시하고 analysis_period는 다른 기간으로 대체하지 않는다.

## 4. Gemini 3개 역할과 검증

| 역할 | 모델 작업 | 화면 |
|---|---|---|
| advantages | 검증된 비교 이점 후보 전부의 순서 선택 | 왼쪽 이점 |
| cautions | 검증된 불리한 비교 후보 전부의 순서 선택 | 오른쪽 유의점 |
| summary | 실제 메트릭에 기반한 수치 문장 그룹 서버가 정한 G개 그룹에서 각1개를 선택하고 순서 결정 | 아래 수치로 본 해석 + 전체 지원 메트릭 요약 |

이점/비교형 유의점 후보는 기존 비교 가능한 최대3개 지표를 기준으로 만든다. 배열의 minItems=maxItems=후보수, 전체 ID 집합 일치를 강제하여 모델이 근거를 버리지 못하게 한다. 확장 시 서버의 상한/선정 규칙부터 버전 변경한다. 후보0개일 때만 이점 없음 문구를 쓴다. 이 경우 maxItems=0이고 빈 items/enum은 만들지 않는다. 해당 역할도 정상 생성에서는 호출하여 총3회다.

역할별 다른 지시문·후보집합을 사용하며 자유 문장/새 숫자/URL 대신 해당 역할의 ID만 반환한다. 역할 교차·중복·없는 ID·상반된 주장·그룹 누락을 거절한다. summary는 서버가 Risk/활동/매출/행정동인구/격자/주소이력의 최대6개 도메인에서 G개 그룹(1≤G≤6)을 구성하고 그룹마다 대안 문장을 둔다. 모델은 각 그룹에서 정확히1개를 고르며 minItems=maxItems=G다. 지표가 전부 없으면 자료 없음 단일 그룹(G=1)을 만들고 세 번째 호출은 유지한다. 서버가 group_count와 group_ids를 응답에 붙이며 FE는 문단수=G, 각 group_id 한 번씩을 검증한다. 모델이 그룹을 골라서 빼는 계약이 아니다. 서버가 text/evidence_ids 문장을 조립한다. 표본 부족·미래 참고자료·인구 범위 등 필수 한계는 모델 선택과 무관하게 항상 유의점에 추가한다.

자기 문장을 검증 whitelist로 쓰지 않고 최소 원시 evidence의 수치 토큰과 대조한다. 원화 큰 정수·decimal·display·단위/날짜를 타입별 canonical 토큰으로 처리한다. 서버 문장 자체의 결정적 불일치는500, 모델의 잘못된 ID/스키마는 해당 역할 verification_failed다. 서로 다른 날짜·공간을 직접 비교해 창업 성공/실제 유동·매출 효과·인과관계를 만들지 않는다.

## 5. 호출 수·제한·실행 순서

기존 요청은 공급자 재시도와 검증 재생성이 가능하므로 그대로3번 호출하지 않는다. 새 전용 client는 RetryPolicy(max_retries=0), 기존 공급자 limiter 공유, httpx transport retry0, 생성 검증도1회다. 기존 v1/v2 프롬프트·재시도 정책은 유지한다. 전역 사용량은 정상 요청당 최대3배가 되므로 공급자 RPM/RPD(기본 None 포함)와 사용자 안내를 운영에서 확인한다. 유료 한도·요금제는 임의 변경하지 않는다.

1. 기존 v1/v2와 공유하는 논리 요청 limiter를1회 차감한다. 새 report admission은 서로 다른 보고서 동시1개이며 기다리지 않고503(발송0)이다. 동일 전체 baseline/서버 비밀 HMAC의 진행 요청은 공유 flight에 합류할 수 있다. 전체35초는 최초 요청 시작부터 계산하며 follower가 연장하지 않는다.
2. 같은 세션의 DB 준비는 별도 db_prepare_gate(1)를 사용한다. 기존 InterpretationResources.gate의 준비·공급자 두 용도를 분리하고 기존 API의 준비/생성 사용처도 대응시킨다. 이에 따라 기존 준비 동시성은2에서1로 줄 수 있고 새 보고서가2슬롯을 요구할 때 legacy1개만 실행 중이어도503이 될 수 있다. 응답 계약/한도 상한은 유지하나 처리량이 같다는 주장은 하지 않는다. 공급자 동시 상한 자체는 기존 interpret_max_concurrent를 공유한다. DB gate 대기도 포함한 준비의 응답 대기는8초이나 SQL/풀/스레드를 실제8초에 중단한다는 보장이 아니다. SQL 전후 deadline/stop과 statement_timeout을 확인한다.
3. to_thread 준비 작업은 shield된 관리 Task가 소유하고 실제 종료·rollback/연결 반환까지 DB gate를 보유한다. HTTP 요청의8초 초과·취소 때는 stop을 설정하고 발송0으로 종료하지만, 남은 준비 스레드가 끝나기 전 gate를 놓거나 후속 준비를 누적하지 않는다. cleanup 예외를 회수한다. Render 풀1에서 준비 조회 증가가 다른 GET 지연에 영향을 주는 점을 운영 위험으로 기록한다.
4. 현재 자료 검증 후 완전 보고서 cache를 확인한다. 캐시는 API 키가 구성된 경우 활성화하며 기존256개/4MiB 상한을 공유한다. 저장 내용은 역할별 선택 ID+model만이고 HIT에도 현재 후보로 재검증·렌더링한다. partial/취소/큰 항목은 지속 캐시하지 않는다.
5. flight는 준비·baseline 검증·캐시 확인·생성 전체를 감싼다(아래 번호는 책임별 설명). 논리 limiter는 follower도 각 HTTP 요청마다 차감하며 admission503 이전 차감은 복구하지 않는다. 기존 lock-only Flights.hold 대신 새 ReportFlights(shared Task + waiter 수)를 쓴다. complete/partial/예외를 현재 모든 waiter에게 동일 전달한다. 준비 전 합류한 waiter도 자신의 baseline을 공유 준비 결과와 각각 대조한 뒤 결과를 받을 수 있다. asyncio.shield로 한 waiter의 취소가 공유 작업을 취소하지 않게 하고 마지막 waiter 소멸 시 취소한다. partial도 현재 flight에서는 공유하고 종료 후 registry에서 제거한다. follower가 cache miss라고 자동으로 새3회를 발송하지 않는다.
6. provider capacity pool은 legacy 모델 생성과 공유하며 새 report는 min(2,interpret_max_concurrent) 슬롯을 원자적으로 즉시 예약한다. 부족하면 대기 없이503(발송0)이다. 캐시 MISS 확인 직후 예약한다. 공개 API try_reserve(n)를 구현하며 Semaphore._value를 건드리지 않는다. 예약한 슬롯 안에서3역할을 로컬 작업 슬롯으로 스케줄한다. 실제 HTTP마다 예약 슬롯 하나를 쓰고 전역 슬롯을 중첩 획득하지 않는다. legacy 생성은 같은 pool의1슬롯을 쓴다.
7. 기본2슬롯일 때 HTTP는2회+1회, 각 최대10초다. 설정1슬롯이면3회 순차·각8초다. 실제 상한은 전체 남은 시간과의 최솟값이다. 예산은 준비 응답대기8 + 후보/검증2 + HTTP20(1슬롯24) + 조립1 =31(35)초다. 부족하면 조기 timeout/partial이며 어떤 부하에서도 성공을 보장한다는 의미는 아니다. 전체/개별 TimeoutError를 role.timeout 또는 AI_UNAVAILABLE로 구분한다. 실행 중 DB cleanup만 응답 deadline 밖에 남을 수 있다.
8. report admission은 공유 작업이 실제 완료되고 DB cleanup이 반환할 때 해제한다. 조건 변경 직후 재요청이 아직 사용 중이면503과 “이전 해석을 정리하고 있어요. 잠시 후 다시 시도해 주세요.” 안내를 제공하며 자동 재시도하지 않는다. endpoint는 Request.is_disconnected() 감시 Task(최대250ms 주기)를 두고 disconnect를 waiter 해제로 처리한다. 마지막 waiter 종료/공유 deadline이면 대기 작업과 HTTP를 닫는다. 이미 발송된 호출의 과금 취소를 보장하지 않는다. 논리50회/일은 Gemini최대150회/일임을 운영 기록에 명시한다. 키 미설정은0회이고 현재 client는401/403을 UPSTREAM으로 묶으므로 새 경로용 AUTHENTICATION 오류 분류를 추가하고 그 경우와 NOT_CONFIGURED/QUOTA_EXHAUSTED만 전역 실패로 미발송 역할을 취소한다. 일반 UPSTREAM은 역할 오류로 처리한다. 기존 API의 외부 오류 계약은 바꾸지 않는다. 역할별 일반 오류는 나머지 역할을 계속한다.

새 전체 예산35초·역할별 토큰2048(768로 축소하지 않음)·FE45초를 사용한다. SDK를 새로 도입하지 않고 기존 REST 어댑터를 사용한다. 프록시 실제 제한·콜드/동시 요청 시간은 아직 확인하지 않았으며35초 내 운영 성공을 사전 주장하지 않는다. 논리 요청/역할별 실제 발송·성공·실패/cache/시간만 기록하고 원문·주소·키를 로그에 남기지 않는다.

## 6. 새 API 계약

기존 /api/risk/interpret, /api/v2/risk/interpret의 구 prompt/body는 보존한다. 새 POST /api/v2/risk/interpret/sections를 추가하고 자동 구 API fallback을 금지한다(추가 호출 방지).

요청은 AnalysisInterpretRequest의 AnalysisRiskQuery 검증을 재사용하되 옛 history 대신 optional address_history와 필수 baseline/time_mode를 갖는 새 schema다. 토큰4096자, baseline 전체8KiB, 전체 body16KiB를 상한으로 두고 unknown/중복 필드·본문 크기·명시 상세위치·서명 오류를 DB 이전에 검증한다. 해당 상한은 구현에서 현행 토큰 최대 직렬화 크기와 정적으로 대조하여 축소/확장 근거를 기록한다.

응답은 ApiResponse<AiSectionsReport>이며 새 schema_version=ai-sections-v1, label, status, advantages, cautions, summary, metrics, 고정 checklist3개, generated_at, 공개 report_context_hash를 갖는다. 각 역할은 ready/unavailable, ready일 때만 검증 통과한 text/evidence_ids 및 verification을 갖는다. advantages/cautions의 ready 빈 후보는 정상이며 summary.ready는 group_count(G)와 정확히 같은 문단수 및 고유 group_ids를 요구한다. meta는 기존 Risk 기준과 새 자료의 날짜/판본을 구분한다. 기존 RiskInterpretation.body 필수 조건으로 새 응답을 판정하지 않는다.

일부 역할 실패 시 data.status=partial, 해당 카드만 unavailable + reason(provider_error/verification_failed/timeout/rate_limited)로 표시하고 텍스트/verification은 없다. 전역 passed:true는 만들지 않는다. 나머지 검증 역할과 서버 metrics·체크리스트는 표시한다. 초기에는 역할별 재시도 버튼을 두지 않는다. 사용자 전체 재시도만 새로운 최대3회이며 이전 결과와 섞지 않고 원자적으로 교체한다.

모든 역할 실패는 AI_UNAVAILABLE 또는 AI_VERIFY_FAILED 503이며 새 수치 요약도 제공하지 않는다. 기존 GET 지표와 FE의 고정 현장 확인사항은 유지한다. 서버 원천/문장/지문 손상500, 입력422, 현재 기준 불일치409. AI_CONTEXT_CHANGED 및 AI_HISTORY_CONTEXT_OUTDATED가 없으면 새 계약에 추가한다. 전자는 GET1회 갱신 후 안내만, 후자는 주소 확인으로 이동하며 window.location.reload()를 재사용하지 않는다. 모든 응답은 no-store, 오류/로그에 원문을 노출하지 않는다.

## 7. 계약 전 확인사항: 정확히 기존 3개

제목 `계약 전 확인사항`, 안내 `확인한 항목을 체크해 보세요. 체크 상태는 저장되지 않아요.`, 최초 `3개 중 0개 확인`을 유지한다.

| item | why |
|---|---|
| 시간대별 현장 유동 확인 | 생활인구와 실제 방문 흐름은 다르므로 영업 예정 시간에 직접 확인해 주세요. |
| 보행 동선과 출입 접근성 확인 | 지도 반경과 실제 이동 경로가 같은지 현장에서 살펴보세요. |
| 가시성과 주변 점포 확인 | 입구가 보이는 위치와 실제 비교 점포의 운영 모습을 확인해 주세요. |

BE 기존 CHECKLIST의 `time_flow`, `access`, `visibility`를 고정 순서로 사용한다. 기존 네 번째 operations 후보와 모델 선택은 새 계약에서 사용하지 않는다. FE 실패 화면에도 같은 고정 문구를 제공하기 위해 전용 상수로 동기화하고 API 성공 응답과 대조한다. 기존 endpoint의 checklist 후보는 유지한다.

FE `AiChecklist`의 label/input/설명 연결·aria-live 개수 표시와 React state를 재사용한다. 서버/localStorage/sessionStorage에 체크 상태를 저장하지 않는다. 새 보고서·조회 조건 변경 시 컴포넌트 key를 바꾸어 체크 상태를 초기화한다. 별도 ScreenReportPage는 빈 체크 상태로 시작한다. 해당 보고서 화면에서 체크한 상태만 PDF에 반영하며 새 모델 요청은 하지 않는다.

## 8. FE 연결·접근성·PDF

- 초기 새 보고서는 production v2에서만 사용한다. v1 로컬/Preview는 기존 AI 경로·구조를 유지한다. 새 UI의 로컬 검증은 명시 v2 설정과 전용 합성 mock으로 구분한다.
- 새 `AiSectionsReport` 타입, API 함수, hook, query key, `sectionsMatches`를 기존 타입과 분리한다. 기존 `RiskInterpretation.body` 필수 조건에 새 계약을 억지로 맞추지 않는다.
- 캐시 키는 조회 조건/검증된 이력 범위/주소 표시/기존 baseline/time_mode/새 schema·prompt 버전을 포함한다. 수신 응답의 baseline과 현재 요청을 대조하고 report hash는 서버 검증 후 보관한다. 조건 변경/이탈 시 AbortSignal과 세대 ID로 stale 응답을 차단한다.
- `AI 해석 보기`는 논리 POST 1회만 발송한다. FE가 Gemini를 직접 호출하거나 세 API를 따로 호출하지 않는다. 자동 생성·자동 재시도·화면 복귀·PDF에서 재생성을 하지 않는다.
- 생성 중에는 이점·유의점·AI 해석 자리와 한 개의 live status를 보여 준다. 중복 클릭은 막고 결과 도착 시 한 번만 알린다. 새 요청 상태에는 기존 결과를 계속 섞어 보여 주지 않는다.
- 상단 두 카드의 제목은 h3, 바깥 AI 해석은 h2. 색만으로 이점/유의점을 구분하지 않는다. 모바일은 DOM 순서 그대로 한 단, 수치·링크는 줄바꿈하며 360/390px을 확인한다.
- 하단 h3는 `수치로 본 해석`으로 구분하고 실패 카드의 안내는 각 카드 안에 둔다. 수치 요약은360px에서 카드형으로 바꾸며 생성 상태 알림 live region은 하나만 유지한다. 체크리스트 개수의 독립 aria-live는 유지한다.
- 수치 요약 표에는 값·상태·기간/공간·출처를 함께 표시한다. 행정동 인구·상권 매출을 주소 점포의 직접 측정치로 표현하지 않는다. 상세 한계는 기존 정보 팝업과 각 근거에 둔다.
- `ScreenReportPage`는 새 결과 컴포넌트를 공유하고 QueryClient의 검증된 캐시만 사용한다. 미요청/실패는 안내로 표시하며 Gemini 호출0회. PDF에서 카드와 체크리스트의 페이지 잘림·시각적 순서를 확인한다.

## 9. 구현 파일과 순서

1. BE: 새 report schema·MetricEvidence·역할 후보/프롬프트 3종·서버 문장 검증. schema와 prompt SHA를 버전 관리한다.
2. BE: 동일 RR prepare와 지문, 전용 no-retry client와 기존 공유 limiter/gate, 3역할 조정기·부분 결과·완전 결과 캐시·새 router.
3. FE: 새 타입/API/hook/문맥 검증, AiResultCard 새 구조, 기존 체크리스트 재사용, 목업·인쇄·오류 표시.
4. 계약 문서와 양쪽 CLAUDE.md의 현재 규칙을 함께 갱신한다. 옛4문단/prompt를 새3영역으로 오인하는 fallback을 만들지 않는다.
5. 실제 코드 검토와 구현 검증 뒤 context v2 발급/기존v1 decode 호환과 새 GET별 basis token 발급을 포함한 BE 새 endpoint를 먼저 반영하고 기존 AI 회귀를 확인한다. 이후 FE develop→main으로 새 UI를 공개한다. 새 endpoint 준비 전에 FE를 전환하지 않는다.
6. 복구는 FE의 기존 AI 경로/이전 버전을 먼저 복구한 뒤 필요 시 BE를 복구한다. 기존 API가 공존하므로 DB 마이그레이션·원천 재적재 없이 복구한다.

이번 문서는 원본 사용자 작업 폴더의 미커밋 변경과 분리된 worktree에서 작성한다. 실제 DB/키/.env/원천/호스팅 설정은 읽거나 변경하지 않는다. 구현·배포를 이미 완료한 것처럼 기록하지 않는다.

## 10. 검증 계획 (아직 실행하지 않음)

사용자의 이전 추가 테스트 생략 지시는 유지한다. 아래는 구현의 필요 검증 항목을 명세한 것이며 지금 실행한 결과가 아니다. 실구현에서 검증을 생략하면 해당 미검증 범위를 공개 기록에 명시한다. 실 API 호출은 실제 검증 단계에서 정상 최초 생성 한 번(3회)으로 제한하고 모의 검증과 구분한다.

- HTTP transport 계수: complete MISS3/HIT0/중복 leader3·follower0/입력422·baseline409의0/실패·timeout·잘못된 JSON의 최대3. 공급자 retry/검증 재생성0을 실제 transport에서 단언한다.
- source drift·매출방법 변경·위치참고/인구 판본 변경은 캐시 miss. 같은 수치라도 판본·날짜·범위가 다르면 재사용하지 않는다.
- 같은 RR·LLM 전 연결 반환·SQL 직전 deadline·공급자 슬롯 공유·동시 요청 한도·취소 후 잔여 작업과 캐시 미기록.
- 이점 없는 경우, 세 역할의 후보 조작/중복/반대 주장·수치/출처 변조·결측/실제0·혼합시점·부분/전체 실패. 기존 v1/v2 AI 계약 보존.
- FE 한 번 클릭·새 경로·응답불일치 거부·조건 변경·캐시·인쇄의0콜·3개 체크 항목/초기화·모바일·키보드·부분오류.

## 11. 완료 기준

설계 완료: 사용자 구조·정확히3회 정상 생성/최대3회 실패·체크리스트·자료별 근거·운영 제한을 명세하고 Claude 실제 검토의 차단 지적을 해소한다.

구현 완료: 새 endpoint와 FE가 같은 계약으로 실제 동작하고 수치·출처·실제 호출 수·실패 격리를 확인한다. 문서 PASS만으로 구현 완료라 하지 않는다. 배포 완료: 새 운영 주소의 해당 기능까지 확인된 별도 기록이 있어야 한다.

## 12. Claude Code 실제 검토와 Codex 판단

### 12.1 1차 실제 검토

Claude Code 2.1.322 / claude-opus-5-5, 도구 없는 정적 검토 1turn, 180.81초, exit0/is_error=false. 설계 SHA256 ff16c144946dd33a17cc6797b3011ffb130ef49c4e7b90c92ca4fe3d5e634de8 보존. 판정 NEEDS_CHANGES.

- B1: lock-only Flights의 partial 중복 생성/취소 문제 → 공유 Task·waiter/부분결과 공유·disconnect 감시로 보완.
- B2: 기존 gate 경합·to_thread 조기 해제·시간예산 불일치 → DB/공급자 분리, report동시1, 공급자 원자 즉시 예약, 준비 cleanup 소유·시간예산 명세.
- B3: 모델이 실제 이점 후보를 버리는 문제 → 전체 후보 집합/개수 일치와 빈 enum 제거.
- B4: 화면의 음식점 합산·통합 영업기간·v3 이력과 불일치 → 서비스/필드 대응, v3 서명 문맥, 새 결측 카탈로그로 보완.
- B5: 선택적 Risk baseline만으로 새 참고자료 대조 불가 → 필수 복합 baseline과 FE캐시 조건으로 보완.
- B6: 공개 식별 지문의 대입 위험 → 내부 비밀 HMAC key와 식별자 없는 공개 hash 분리.

비차단 N1~N12도 no-retry client/전역실패, 토큰2048, 결정적 문장검증500, ID캐시·상한, 공유한도, 제목/모바일/인쇄 체크 상태, v1 프로필, 복수 동, 전체실패503,409,풀1 위험, 미실행 검증 기록에 반영했다. runtime 성공·검증시험·실제 호출/배포를 수행했다는 판정은 아니다.

### 12.2 보완본 재검토

Claude Code / claude-opus-5-5, 도구 없는1turn, 107.07초, exit0/is_error=false. 보완본 SHA256 f276ee006a7d7525395167e8c7e8ed17c12bc5fc203ddf39dba78ff7990c0607 보존. NEEDS_CHANGES: B1~B6 대부분 해소, R1(필수 baseline의 GET 발급필드/내용 의미 불명확), R2(summary 그룹 수/누락 규칙 불일치) 남음.

Codex 보완: GET별 신규 meta.ai_report_basis_token·서버 발급/재계산 함수·persistent HMAC·비트랜잭션 내용 지문,409 갱신1회 규칙을 명세했다. summary는 서버 결정G개 그룹·각1개·group_count/group_ids와 자료없음 G=1로 고정했다. v3 기존 토큰의 좌표 미포함을 직접 확인하여 버전2 서명문맥 발급/기존GET의v1호환도 추가했다. N1~N8의 flight 범위/limiter 차감, 미준비503, 인증오류 분류, 처리량 변화/슬롯예약 시점, cleanup 후입장해제, 생성 알림/체크 카운트 분리, 미검증 schema 위험, 최대150call/일을 반영했다.

### 12.3 최종 재검토

Claude Code / claude-opus-5-5, 도구 없는1turn, 68.14초, exit0/is_error=false. 검토 대상 SHA256 8711fc5386a213ff3f29b14ea5cf759bc333a5d3740ce8ccfdd5efbb9174bd25 보존. 최종 판정 PASS, R1/R2 해소, 추가 차단 없음.

Codex는 이 판단을 수용한다. 비차단 N1~N7에 대해서는 다음을 추가 명확화했다:409는 GET갱신1회로 단일화, 옛 이력 토큰은 AI_HISTORY_CONTEXT_OUTDATED 및 주소 재확인, 기존 signing key에서HKDF 용도별 키파생, activity GET basis token도 필수 추가, 격자 GET 실패 시 전체 새 보고서 대기와 구체 안내, DB gate 대기 포함8초, maxItems:0 실제공급자 수용의 미검증 위험 유지. 이 명확화 문장과 activity token 표 추가는 Codex의 후속 정리이며 Claude가 네 번째로 검토한 것이라고 주장하지 않는다.

### 12.4 검수 범위와 다음 단계

검수는 제공 설계·소스의 정적 대조이며 실행 시험/원천 승인/Gemini 실호출/성능/배포 확인이 아니다. 실제 모델 호출은0회, 앱/FE 구현·DB/환경/운영 변경은0건이다. 현재 결과물은 구현에 사용할 설계와 검수 기록이다. 다음 구현은9절 순서로 BE/FE 계약을 함께 변경하며 기존 기능을 삭제하지 않는다. 사용자의 추가 테스트 생략 요청은10절의 미실행 기록과 함께 유지한다.
