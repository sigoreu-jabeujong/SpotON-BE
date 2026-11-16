# 생활인구·주야간 API 연결과 부분 공개자료 비교 설계 (#178)

작성 2026-11-16, 기준 BE `b9d9ad3`, 확인한 로컬 FE `540bd8d` 및 기존 origin/develop의 해당 호출. **이번 결과물은 설계와 BE 안의 FE 전달 문서다. 앱 코드·FE·DB0012·환경·서버·배포는 변경하지 않는다.** 사용자가 요구한 Claude Code 대화/검토와 Codex 판단은 후속 절에 실제 결과만 기록한다.

## 1. 문제와 범위

| 경로 | 실제 상태 | 필요한 조치 |
|---|---|---|
| FE 생활인구 | `src/api/market.ts`와 `ACTIVITY_INCLUDE=['sales','living_pop']`, 조건부 표시 컴포넌트가 있음 | 새 부분자료 계약을 별도로 요청하고 의미에 맞게 표시 |
| FE 주야간 | `getRisk(params, include)`·표시 ID는 있으나 `SummaryPage.tsx:33`, `ActivitySection.tsx:33`에서 `useRisk(params)`라 include가 비어 있음 | 새 인구 API 호출/캐시·화면·보고서를 연결. 구형 Risk include만 추가하는 것으로 완료하지 않음 |
| BE 활동 | `MarketActivity.living_pop: None`, 서비스도 항상 null | 기존 필드를 무리하게 채우지 않고 새 typed 응답 작성 |
| BE Risk | 요청 시 `pending_indicator`, schema도 day_night_ratio의 pending 외 상태와 단위 '배'를 허용하지 않음 | 기존 Risk와 독립한 부분자료 API로 먼저 실제 조회/계산 연결 |
| BE 내부 | `assemble_population`은 모든 격자×3원천×24시간 기대 집합 검사. 시간 하나라도 None이면 `calculate_day_night`의 모든 결과 null | 기존 strict 함수는 보존. 원천별·동일 공개 구성의 새로운 부분자료 조립기를 추가 |
| AI | v1/v2 문맥에 실제 인구가 없으며 `_activity`는 값이 있으면 오류 | 이번 첫 구현은 기존 AI에 인구를 끼워 넣지 않음. 별도 후속 계약 없이 AI가 이 수치를 사용한다고 표시하지 않음 |

문제는 외부 API 키 누락이 아니라 우리 BE의 읽기·계산·응답 미연결이다. 기존 CSV/격자 적재 경로를 재사용하며 외부 API/LLM 키를 새로 요구하지 않는다. 로컬 적재 기록과 운영 DB의 실제 보유 자료는 구분한다. “15개 중2개 산정”은 전달받은 사례이며 이 설계에서 같은15곳을 재측정한 실적이 아니다.

## 2. 결정: 전체 인구와 공개자료의 고정 구성 비교를 분리

**추천안은 내국인/장기외국인/단기외국인 각각의 24시간 모두 공개된 같은 원천 구성만 비교하는 별도 참고 지표다.** 외국인 원천이 없거나 비공개여도 내국인 블록은 계산한다. 어떤 시간의 비공개 한 건이 반경 전체를 막지 않으며 해당 구성만24시간 비교에서 제외한다. `*`/빈 셀/없는 행을0으로 바꾸거나 다른 원천으로 보충하지 않는다.

이 값의 이름은 **“내국인 공개자료 주야간 비교(부분)”** 등으로 한다. 단위 없는 배수는 “공개자료 주간값 ÷ 야간값”이며 실제 반경 전체 인구비·방문객·고객·시장규모·완전한 하한으로 부르지 않는다. 기본 강조 블록은 local로 고정하고 local이 없을 때 long/short로 자동 대체하지 않는다. 다른 두 원천도 자기 이름·상태로 보여준다. 세 원천의 합계나 비중은 제공하지 않는다.

| 대안 | 판단 |
|---|---|
| `*`/없는 행을0·1·2·중앙값 등으로 대치 | 채택하지 않음. 비공개 추측/없는 행 의미 확정이 됨 |
| 시간마다 있는 숫자만 합쳐 D/N | 채택하지 않음. 주간과 야간의 대상 구성이 달라져 결측 패턴이 비율에 섞임 |
| 완전한 내국인+불완전 외국인 모두 합산 | 채택하지 않음. 자료 부재가0명처럼 해석되고 원천 범위가 불명확해짐 |
| 반경 전체가 모두 완전해야 계산 | 전체 인구의 strict 경로에는 보존하지만 이번 참고 지표의 조건으로 쓰지 않음 |
| 같은 원천의 고정 공개 구성24시간 비교 | 채택. 제외 구성/범위와 선택 편향을 항상 함께 표시하고 전체 인구로 외삽하지 않음 |

[#176 설계](feat176-reference-activation.md)의 인구 부분 중 “모든 원천/격자가 완전해야 모든 수치 제공”은 **전체 인구 경로에만 유지**한다. 새 공개자료 참고값에 그 승인 gate를 복제하지 않는다. 기존 `reference-indicators`/`reference-interpret`·8표/0013·공식 승인 계획은 이번 별도 API의 선행조건이 아니다. 브랜드/매출/상권변화 설계는 바꾸지 않는다.

## 3. 공식 사실과 새 참고 산술의 한계

[서울시 공식 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do)는 통신/공공자료로 인구를 추계하며 작은 속성값을 마스킹하고 소수값/세부 합계 차이가 있음을 설명한다. 2026-11-16 재조회에서도 안내를 확인했고 내국인 개별 페이지는 지연103을 반환했다. 마스킹 기준 숫자를 코드로 추정하거나 지연을 인증 실패로 해석하지 않는다. 근거의 자세한 쟁점은 [원천 검증](../population-source-verification.md)에 있다.

행정동 간 비중복·가산성/전체 기대 구성·없는 행의 뜻·격자 날짜별 적용은 여전히 미확정이다. 그래서 이번에는 파일에 실제 제공된 **공개 원천값의 고정 구성 산술**만 제공한다. `(grid,admin)` 각각을 구성으로 보존하고 이 합을 격자의 완전한 인구 총계라고 하지 않는다. row-derived 후보 집합은 독립 기대 집합이 아니며 strict 함수를 통과시키는 근거로 사용하지 않는다. `source_validation_performed=false`, `population_total_validated=false`, `spatial_compatibility=unverified`, `global_content_rechecked=false`를 그대로 반환한다. `public_subset_calculation_performed=true`는 이 산술 수행만 뜻한다.

공식 시간구분과 구별해 SpotON 기준 주간06~17/야간00~05,18~23의 같은 관측일을 쓴다.24시간 합은 하루 고유 인원수가 아니다. 원천별 행정동 구성의 중복 가능성과 공개된 구성에 치우친 선택 편향 때문에 값이나 배수로 전체 반경의 주야간 우세·창업 유불리를 확정하지 않는다. 전체 인구 산출에는 기존 공식 근거 검증이 여전히 필요하다.

## 4. 부분 조립 알고리즘

1. 하나의 READ ONLY REPEATABLE READ 세션에서 분석일T·관측 버전V·격자G·반경 선택을 확정한다. 서로 다른 날짜/버전의 원천을 섞지 않는다.
2. 기존 품질 진단의 기준대로 G의 `center_x/center_y`(EPSG5179)를4326 geography로 변환하고 반올림 전 타원체 거리≤radius인 격자 S를 고른다. polygon centroid·면적 가중·가짜 좌표·근접 대체를 쓰지 않는다. 미위치 원천은 전역 누락 상태로 별도 알리고 반경에 배정하지 않는다.
3. 각 s∈{local,long,short}에 대해 S 안에 당일 실제 한 행 이상 존재한 `(grid_id,admin_code)`의 합집합 U_s를 만든다. 대상 행은 V·G가 일치하고 `geometry_status='located'`이며 `located_grid_id∈S`인 행뿐이다. 원천별로 독립이다. U_s는 “당일 파일에 나타난 후보 구성”일 뿐 반경 전체 기대 모집단이 아니다.
4. 각 c∈U_s가00~23에 정확히 한 행씩 있고 모두 `observed`·유효 Decimal이면 C_s에 넣는다. 원본 숫자0은 포함한다. 한 시각이라도 suppressed/missing/행 부재면 그 c만 C_s에서 제외한다. 다른 admin 구성/원천은 차단하지 않는다. 중복/상태-값 모순/타 버전·날짜 혼입은 무결성 오류다(관측 PK가 version·source·hour·admin·grid 중복을 이미 막으므로 중복 검사는 방어용이다). 제외된 각 c는 비관측 시각(suppressed/missing/행 부재)이 어디에 있는지에 따라 `day_only`(06~17에만), `night_only`(00~05·18~23에만), `both` 중 정확히 하나로 분류한다. 세 수의 합은 제외 수와 같다.
5. C_s가 비어 있으면 그 원천은 no_data다. 아니면 `P_s[h]=Σ(c∈C_s)原値(c,h)`의24시간을 만든다. 같은 C_s를 모든 시간과 D/N에 사용한다. 기존 `calculate_day_night`를 순수 산술로 재사용하고 strict `assemble_population`은 호출/완화하지 않는다. 새 함수 후보는 `assemble_public_subset`이다.
6. 원천 입력과 **시간별 합 P_s[h]**는 기존 Numeric(20,5) 범위(1e15 미만)·소수 5자리를 지키고, 산술은 독립 50자리 Decimal Context로 한다. 12시간 합 D/N은 저장하지 않는 값이라 1.2e16 미만까지 허용한다(§6). 시간별 합이 상한을 넘는 정상 자료는 조용히 자르지 않고 해당 원천만 `not_supported/numeric_scope_too_large`다. 잘못된 원천 숫자는 500이다. 이 둘은 `calculate_day_night` 호출 전 사전 검사로 구분한다.

제공 수치:24개 `hourly_source_sums`, `day_source_sum`, `night_source_sum`, `day_source_mean`, `night_source_mean`, `day_share_pct`, `night_share_pct`, `day_night_ratio`. `hourly_source_sums`·day/night 합/평균의 단위는 **공개 원천값 합/시간별 공개 원천값 합**이며 “명”으로 표시하지 않는다. 모두 명시된 공개 구성에 대한 산술이다. 백분율은 이 공개 구성 D+N의 비중이다.

| 상태 | 합/평균 | 비중 | 배수 |
|---|---|---|---|
| C_s>0,N>0 | 실제 산술 | 계산 | D/N; D=0이면 실제0 보존 |
| C_s>0,D>0,N=0 | 실제0 포함 | 100/0 | null, zero_night_denominator |
| C_s>0,D=N=0 | 실제0 | null, zero_total | null, zero_night_denominator |
| C_s=0 또는 원천 행 없음 | 전부null | null | null;0으로 채우지 않음 |

## 5. 품질 수치와 표시 규칙

원천별 `selected_grid_count=|S|`, `grids_with_rows`, `grids_without_rows`, `candidate_component_count=|U_s|`, `used_component_count=|C_s|`, `excluded_component_count=|U_s|-|C_s|`, `used_grid_count`, 원천 행의 observed/suppressed/missing 수, `absent_hours_within_candidates=24|U_s|-실제행수`를 반환한다. 한 구성의 제외 원인은 겹칠 수 있어 reason별 개수를 더해 총 제외 수로 쓰지 않는다. 없는 격자에서 후보 구성 자체가 없으면 absent_hours 분모에 들어가지 않는다는 한계를 명시한다.

원천별로 `excluded_by_hour_class={day_only,night_only,both}`도 반환한다(§4.4. 합은 excluded_component_count). 마스킹은 작은 값에 걸리기 때문에 주간이나 야간 한쪽만 작은 구성이 체계적으로 빠질 수 있다. 이는 측정하려는 주야간 차이와 상관된 선택 편향이다. 그래서 day_only>0 또는 night_only>0이면 block limitations에 `exclusion_pattern_may_bias_ratio`를 넣고, FE는 “주간/야간 한쪽에만 비공개·누락이 있는 구성 N개가 빠져 배수가 달라 보일 수 있어요”를 표시한다. 왜곡 방향(과대/과소)은 단정하지 않는다.

비공개 보호: 값 계산에는 24시간 모두 공개된 구성만 들어가고 suppressed 구성은 통째로 빠진다. 숨긴 수치를 계산항/추정값/범위로 반환하지 않는다. C_s=1이면 공개 구성 하나의 원천값이 드러날 수 있다. 이미 공개된 값의 산술이라는 경계이며, 다른 공개자료와 결합한 추론·구성 존재 여부의 차분까지 모두 막는다는 보장은 아니다. 개별 구성/좌표/원문은 제공하지 않는다.

첫 계약에서는 `used_component_fraction`도 생략하고 사용/후보 구성의 정수 개수만 제공한다. `coverage_pct`/대표성/반경 인구의 제공률/전체 누락 인구를 만들지 않는다. U_s=C_s여도 complete/verified가 아니고 모든 숫자 결과의 status는 **partial**이다. 공간 미위치 건수는 version_global이며 반경 내 누락 격자 수와 섞지 않는다.

FE는 값 옆에 “공개된 동일 구성만 비교한 참고값이며 전체 인구를 대표하지 않아요”를 항상 표시한다. 기본으로 보여주는 것은 배수·주야 비중·사용 구성 수/후보 구성 수다. 합/평균은 “공개 원천값 합(인원수 아님)” 라벨을 붙인 상세 영역에만 둔다. 산술값이 있으면 전체 블록을 “자료 확인 중”으로 숨기지 않는다. 값이 없는 원천만 사유를 보여준다. 숫자 원천값 합을 사람 아이콘 옆 인원으로 보여주는 기존 LivingBody는 재사용하지 않는다. 성별/연령/국적 항목 합으로 마스킹된 총계를 복원하거나 숨겨진 값의 범위를 역산하지 않는다.

## 6. 신규 GET 계약: 첫 구현의 완결 범위

**`GET /api/v2/population-reference`**를 새로 만든다. 명칭 충돌을 피하려고 #176의 승인 지표 endpoint와 분리한다. 첫 구현은 DB조회·산술·typed 응답·OpenAPI·BE 문서와 모의/실DB 검증까지 포함한다. 기존 `/api[/v2]/market/activity`·`risk`·`risk/interpret`는 이번 첫 구현에서 계약을 바꾸지 않는다. 새 값은 기존 living_pop.total이나 pending RiskIndicator에 넣지 않는다. FE는 새 응답 전용 카드로 연결한다.

**Query.** 전용 `PopulationReferenceQuery(CategoryFilters)`로 **`lat`, `lng`, `radius`, `category`, `sub_category`, `as_of`의 6개 인자만** 받는다.
- 필수: `lat`, `lng`, `category`(cafe|restaurant).
- 선택: `radius`(기본 500, 정수 300|500|1000), `sub_category`(기본 빈 tuple, 쉼표 구분), `as_of`(기본 None, `YYYY-MM`).
- 검증 재사용: category와 중복 없는 sub_category의 대응(cafe→cafe, restaurant→음식점 4종)은 `CategoryFilters` 검증기, radius/as_of는 기존 `NearbyQuery` 검증기. 좌표는 유한수이며 기존 범위(±90/±180)를 따른다.
- DB 접속 전 422: 중복 query key, 빈 token(예: `sub_category=`), 알 수 없는 인자, `include`, `area`, `include_unknown_area`, `brand_*`, `operation_type`, legacy `franchise`, 클라이언트 계산값·원천 UUID·정책 인자.
- 인허가 API query를 통째로 넘기지 않고 체인 publication도 조회하지 않는다. category/sub_category는 허용 분석월 검증에만 쓰고 인구 원천 행을 거르지 않으므로 `scope.population_filter_applied=false`다.

**분석일 T.** `current_provenance(session)`은 category 인자 없이 **전역 원천일 D**를 반환한다(점포 batch metadata 오류는 기존대로 500). 이어 `temporal_cohort(CategoryFilters(category, sub_category), D)` 조건의 최소 개업일 M을 구하고 `effective_date(D, M, as_of)`로 T를 정한다.
- as_of 생략 또는 현재 월이면 T=D, 과거 월이면 그 월말이다.
- 최소월 이전·미래 월은 기존 `AS_OF_OUT_OF_RANGE`/422/no-store다. M이 없으면 D의 월만 허용한다.
- T를 category별 최신 원천일이라고 설명하지 않고 `timeline_basis=license_global_source_date_category_month_range`로 고정한다. category를 생략하거나 sub_category에서 추측하는 경로는 없다.
- Codex 최종 소스 대조: `store_cohort.py:25`의 `temporal_cohort(query: CategoryFilters, reference)`는 query에서 category/sub_category만 읽는다. 전용 CategoryFilters 입력으로 기존 조건을 재사용할 수 있음을 확인했다. 향후 구현 시 이 소스가 달라지면 계약을 재검토한다.

**관측 버전 V.** `[T가 속한 월의 1일, T]` 범위에서 가장 최신 `observation_date`의 버전이다.
- 같은 날짜에 버전이 여러 개면 loaded_at/UUID 순으로 임의 선택하지 않고 `pending/ambiguous_source_version`이다. 더 오래된 날짜로 회피하지 않는다. 같은 RR 세션에서 날짜 MAX와 그 날짜 후보를 `LIMIT 2`로 읽어 판정한다.
- 그 월에 버전이 없으면 `no_data/no_observation_in_period`이며 다른 월로 fallback하지 않는다.
- 세 원천은 V 하나의 날짜/버전 metadata를 공유한다. 반경 안 개별 원천의 빈 행·비공개는 그 block만 no_data/partial로 처리하고 metadata 손상은 500이다.
- `grid_as_of=null`은 명시적 미확인으로 허용하고 limitations의 `grid_as_of_unknown`으로 표시한다.

**응답 최상위.** 기존 `ApiResponse` 외피와 `data={status, reason, analysis_date, observation_date, method, scope, sources}`다.
- status는 `ready|pending|no_data|not_supported`이며 모두 HTTP 200이다. ready의 reason은 null이다.
- 최상위 사유(닫힌 목록): `pending/ambiguous_source_version`, `no_data/no_observation_in_period`, `not_supported/scope_too_large`(선택 격자 >1000 또는 세 원천 합산 선택 행 >100,000). 별도 “원천 미준비” 상태는 없다. metadata 손상은 500이다.
- `sources`는 ready일 때만 정확히 [local, long, short] 순서의 3개 block이고, 그 밖에는 `[]`다.
- `analysis_date`는 모든 200 응답에서 T다(T를 못 정하면 422/500이므로). `observation_date`는 ready·ambiguous_source_version·scope_too_large에서 V의 날짜이고, no_observation_in_period에서만 null이다.
- `method`는 고정 객체 `{name:"fixed_public_component_24h", day_hours:"06-17", night_hours:"00-05,18-23", ratio_definition:"pooled_day_sum_over_pooled_night_sum"}`다. 배수는 구성별 배수의 평균이 아니라 합끼리의 비이므로 값이 큰 구성의 영향이 크다.
- `scope`는 `{radius_m, category, sub_category, as_of, population_filter_applied:false, timeline_basis, spatial_compatibility:"unverified", grid_as_of}`이며 좌표를 담지 않는다.

**원천 block.** 각 block은 `{source, status, reason, values, quality, limitations}`이고 status는 `partial|no_data|not_supported`다.
- block 사유(닫힌 목록): partial→`public_subset_only`, 선택 격자 0→세 block 모두 `no_data/no_selected_grids`, 그 원천의 located 행 없음→`no_data/no_source_rows`, U>0·C=0→`no_data/no_common_public_components`, 어떤 P_s[h]≥1e15→`not_supported/numeric_scope_too_large`.
- partial이 아니면 `values=null`이다. 한 source가 실패해도 다른 source 값은 유지한다. 단 malformed 원천 값·metadata 불일치·참조 무결성 오류는 전체 500/no-store다.
- `quality`는 **모든 block 상태에서 아래 정수 필드가 전부 필수(non-null)**다. ready이면 선택 행을 이미 다 읽었으므로 항상 계산할 수 있다.
  - 반경 기준: `selected_grid_count`, `grids_with_rows`(그 원천 located 행이 1개 이상인 S의 격자 수), `grids_without_rows`, `candidate_component_count`, `used_component_count`, `excluded_component_count`, `used_grid_count`(C_s 구성의 서로 다른 격자 수), `observed_rows`, `suppressed_rows`, `missing_rows`(선택된 그 원천 행 기준), `absent_hours_within_candidates`, `excluded_by_hour_class={day_only, night_only, both}`.
  - 버전 전역 기준: `version_unlocated_rows`, `version_unlocated_grids`(V metadata의 그 원천 값). 반경 수치와 더하거나 섞지 않는다.
- `limitations`는 정렬·중복 없는 닫힌 enum 배열이다. 항상 `not_population_total`, `admin_additivity_unverified`, `grid_period_unverified`, `hour_sums_not_unique_people`를 넣고, 조건부로 `exclusion_pattern_may_bias_ratio`(day_only>0 또는 night_only>0), `grid_as_of_unknown`(grid_as_of=null)을 넣는다. 목록 변경은 format_version 변경이다.

**values.** `hourly_source_sums`(00~23 순서, 정확히 24개), `day_source_sum`, `night_source_sum`, `day_source_mean`, `night_source_mean`, `day_share_pct`, `night_share_pct`, `day_night_ratio`가 모두 필수다.
- 각 수치는 `PublicNumber={value: string|null, display: string|null, exact_zero: bool|null, rounded: bool|null, unit, reason: string|null}`다.
- unit enum: `public_source_value_sum`(시간별 합·D/N 합), `public_source_value_hourly_mean`(평균), `pct_of_public_subset`(비중), `ratio`(배수). 인원 단위는 없다.
- 유효 숫자의 reason은 null이다. 밤 0의 배수만 `value=null, reason=zero_night_denominator`, D=N=0인 두 비중은 `value=null, reason=zero_total`이다. value가 null이면 display·exact_zero·rounded도 null이고 unit은 유지한다. 그 외 partial의 시간별 합·합·평균은 항상 숫자다.

**숫자 규칙.** value는 canonical 고정소수 문자열이며 지수·NaN·Infinity·음수 0을 금지한다. 합·평균·배수는 소수 5자리, 비중은 소수 1자리, HALF_UP이다. 입력이 소수 5자리 이하이므로 A=day_source_sum×10^5, B=night_source_sum×10^5는 정확한 정수다.
- 표시값: 평균 A/12·B/12, 배수 A/B, day 비중 100A/(A+B)의 정확한 유리수를 정수 몫·나머지로 HALF_UP한 값이다(2×나머지 ≥ 제수면 올림). night 비중은 `100.0 − 표시 day 비중`이다(기존 `calculate_day_night`와 같음). 표시의 기준 구현은 이 정수 HALF_UP이다. 순수 함수의 50자리 Context 결과는 내부 산술/회귀 대조에 사용하며, 표시를 만들 때 Decimal의 재반올림 경로로 대체하지 않는다. 두 경로의 동일성은 구현 테스트에서 확인한다.
- `exact_zero`: 반올림 전 수학값이 0인지.
- `rounded`는 **숫자마다 따로** 정확한 유리수와 표시값의 불일치로 판정한다. 합(시간별 포함)은 항상 false다. day 평균은 A%12≠0, night 평균은 B%12≠0이다. 배수는 B>0일 때 (A×10^5)%B≠0이다. 비중은 A+B>0일 때 (A×1000)%(A+B)≠0이며, (B×1000)%(A+B)와 항상 같으므로 day/night 비중이 같은 flag를 갖는다. 전역·이전 계산의 Decimal Inexact flag는 쓰지 않는다.
- 상한: 시간별 P_s[h]만 기존 입력 상한 1e15 미만을 요구하고, 저장하지 않는 D/N은 12시간 합이므로 1.2e16 미만까지 허용한다. 정상 시간 합의 상한 초과만 그 source의 not_supported이며 잘못된 원천 값은 500이다.

**display.** value에 천 단위 구분자만 추가하고 비중에는 `%`, 배수에는 `배`를 붙인다. 합·평균에는 접미사가 없다. 추가 반올림이나 명·방문객 표기는 없다. `"0.00000"`/`"0.0"`이면서 exact_zero=false인 값은 양수가 반올림되어 0으로 보이는 것이며 분모 0 판정에 쓰지 않는다. FE는 서버 display와 flag/reason을 그대로 쓴다.

**meta와 token.** meta는 `format_version=population-public-subset-v1`, 계산 규칙, T/관측일, V/G version UUID·input/content metadata SHA·grid_as_of, 공개 부분산술/시간·공간 한계, `population_snapshot_token`을 포함한다.
- `meta.public_subset_calculation_performed`는 `{local:bool,long:bool,short:bool}`이며 해당 block이 partial일 때만 true다. 최상위가 ready가 아니면 세 값 모두 false다. `source_validation_performed`, `population_total_validated`, `global_content_rechecked`는 항상 false다.
- token은 format/rule/표시 버전 + T + V/G metadata + canonical 공개 data(values·quality·status·limitations 포함)의 SHA256인 **결과 지문**이다. 좌표·개별 구성·row hash는 입력에서 뺀다. 같은 scope·숫자·품질을 만든 서로 다른 위치/구성은 같은 token일 수 있다. 따라서 token은 query key나 보고서 요청 조건을 대체하지 않으며 같은 위치·같은 원천 구성임을 증명하지 않는다. hash에 위치 익명성이나 외부자료 결합에 대한 역추적 방지 보장도 하지 않는다.
- 유일한 V가 선택되지 않은 no_observation/ambiguous 상태에서는 meta의 V/G 식별자·SHA와 scope.grid_as_of를 null로 둔다. ambiguous의 관측 날짜만 MAX 날짜로 유지하며 임의 후보 metadata를 반환하지 않는다. source 수행 bool map은 모두 false다.
- 개별 격자/admin/원문값·명부·좌표/주소·파일 경로/키는 응답·LLM·오류 로그에 넣지 않는다. 외피에도 좌표를 echo하지 않는다.

## 7. 조회·검증·성능·원천 변경

별도 `app/analysis/population_public_subset.py`, `app/schemas/population_reference.py`, `app/services/population_reference.py`, `app/routers/population_reference.py`를 추가하고 `main.py`에 `/api/v2` prefix로 등록한다. 기존 네 생활인구 표/PK·상태·provenance를 읽기만 한다. **새 DDL/migration/승인8표·운영 환경변수 추가가 필수인 설계가 아니다.** 기존 DB 연결과 원천 CSV 적재가 필요하며 운영 자료/역할 SELECT 권한은 실제 반영 전 별도로 확인한다.

같은 기존 READ ONLY RR session에서 metadata→선택 중심점→선택 행을 읽고 계산한다. global full content hash 재검사를 요청마다 수행했다고 주장하지 않으며 현재 selected rows의 타입/일관성과 canonical digest만 검사한다. V/G metadata는 **JSON 내부 일관성만** 대조한다: `sources` 키가 정확히 {local,long,short}, 각 `statuses` 키가 {observed,suppressed,missing}이고 음이 아닌 정수, 원천별 상태 합=rows, 원천 rows 합=`row_count`, V의 grid_version_id로 G가 존재하고 source_crs=5179. `population_quality.diagnose`처럼 버전 전체 관측 행이나 전체 격자를 COUNT/GROUP BY하는 전역 scan은 요청마다 하지 않는다(그 대조는 import/clone 진단의 몫이다). 그다음 선택된 모든 행의 source/date/version/grid/status/value/geometry/중복을 검사한다. 전체 metadata 일치가 global raw hash 검증은 아니다. 전체 파일 검증은 기존 import/clone 대조로 별도 남긴다. DB 소유자의 원천 조작 방지 보장을 이 API에 새로 주장하지 않는다.

첫 구현은 **숫자·선택 캐시를 만들지 않는다**. 매 요청 실제 source snapshot으로 계산하므로 기존 Risk/AI 캐시에서 인구값을 꺼내지 않는다. HTTP `Cache-Control: no-store` 유지. 요청 중 ETL commit은 시작 snapshot과 섞이지 않으며 다음 요청은 새 버전/선택 digest를 쓴다. version이 여러 개로 늘면 ambiguity로 전환된다. 기존 version 원문 CHECK를 승격/UPDATE하지 않는다.

기존 SQL timeout/풀 크기·기존 서버 예산은 유지한다. 선택 격자≤1000, 관측행≤100,000을 limit+1로 먼저 검사하고 초과하면 최상위 `not_supported/scope_too_large`로 수치 없이 반환한다(250m 격자에서 반경 1000m는 약 50격자이므로 이 상한은 정상 요청에서는 걸리지 않는 방어선이다). 잘라낸 부분을 정상 범위 값으로 내지 않는다. geography 선택 시 기존 geom GiST가 중심 속성 함수의 인덱스라고 가정하지 않고10,125격자 scan 및 관측 PK 접근 EXPLAIN/실측이 예산 내인지 clone에서 확인한다. 필요 인덱스가 생기면 별도 DDL/검토/복구 계획 없이 몰래0012에 만들지 않는다. SQL/DB/timeout 오류는 기존 고정500/503/no-store 계약을 따르고 pending으로 숨기지 않는다.

## 8. FE 전달과 AI 범위

구체적인 FE 변경 요청은 [연동 문서](../fe-population-reference-api-request.md)에 둔다. FE 저장소/CLAUDE/이슈/PR은 직접 변경하지 않는다. FE는 기존 API 주소를 새 API로 일괄 교체하지 않고 새 `getPopulationReference`·hook·query key·모의 adapter·전용 카드/보고서로 추가한다. 기존 활동/Risk 점포 지표 요청은 그대로다. `useRisk(params,['day_night_ratio'])`만 추가하는 수정은 기존 pending을 요청할 뿐이므로 이번 연결의 해법으로 안내하지 않는다.

화면/보고서는 같은 새 응답과 서버 규칙을 사용하고 다른 query/관측일/표본의 값을 결합하지 않는다. 장소/반경/월/category/sub_category가 바뀌면 query key 변경·기존 요청 취소·옛 결과 초기화를 수행한다. local 부재를foreign으로 대체하지 않는다. 프로필과 무관하게 새 경로는항상 `/api/v2/population-reference`이며 입력6개만 projection한다. key는 `['population-reference',canonical(lat,lng,radius,category,sorted(sub_category),as_of)]`이고 기본값/생략/순서만 다른 동일query는같은key다. 브랜드/면적/프로필만 바뀌고6인자가 같으면 동일결과를 재사용한다. 서버 반환 analysis_date/관측일과 다른 점포 섹션의 실제T가 다르면 결합해서 설명하지 않고 각 기준일을 유지한다. report는 요청key와token을 함께 확인하고token만으로 동일위치라 판정하지 않는다. mock는 가상이며 실제 BE/실자료 검증을 대신하지 않는다.

첫 구현에서 인구는 **기존 AI 해석에 포함되지 않는다**. 기존 `_activity`/Risk schema/프롬프트/validator/cache 불변성을 유지한다. 인구 참고값을 설명하는 AI가 필요하면 #176의 별도 typed namespace/서버 재계산·같은 snapshot/공유한도·고정 서술 후보에 public_subset 의미를 추가하는 후속이 필요하다. 클라이언트 계산값을 기존 AI 요청에 첨부하거나 성공/실패 판단 후보에 넣지 않는다.

## 9. 구현·검증·적용 순서와 종료 조건

| 단계 | 산출물/완료 조건 |
|---|---|
| A 산술·계약 | 새 subset 함수/schema와 유한 fixture. 단일 비공개가 해당 구성만 제외, source 독립·24h 동일 구성·0/null/반올림·범위 검증 |
| B 실제 BE API | router→RSS loader→subset→typed response 연결, OpenAPI/422-before-DB/no-store와 기존 API/AI 회귀. 프로세스/DB 변경 없는 테스트 client부터 |
| C 분리 DB 실증 | 기존 전체 dump→별도 clone 복원/0012/원본 hash 보존. 현재 실자료에서 기존 strict/새 방식 산정 source 수·사유·U/C/격자수·성능만 비교. 실제 좌표/원문은 private. 전달받은15곳과 같은 집합이 확보되지 않으면 “동일15곳 재현”이라고 쓰지 않음 |
| D FE 전달 | 새 계약/예시/문구/날짜/소스/문자열/반올림/부분범위·mock·에러/캐시 계약 전달. 담당자 반영과 실제 브라우저 확인 전 FE 완료로 표시하지 않음 |
| E 테스트/배포 | 정상 PR/CI/CodeQL→develop. 운영 DB의 관측/격자 보유·SELECT·SQL시간 확인 후 실제 BE 수동 반영, FE는 담당자 일정. 기존 인구 null 계약은 보존하며 새 API를 쓰는 화면만 새 자료 표시 |

대표 테스트는 (1) local 정상+long/short 부재, (2) U의 한 구성 한시각*로 다른 구성 유지, (3) 시간별 단순 SUM이면 만들어질 가짜 D/N을 고정 구성으로 차단, (4) 후보가 하루종일 미제공된 경우를 기대분모에 꾸미지 않음, (5) 복수admin을 보존하되 전체 인구라고 하지 않음, (6) 밤0/전체0/낮0/작은 양수 반올림0, (7) 관측일/버전/원천/격자 혼입·중복/비정상 Decimal, (8) 같은날 복수버전/미래/그 달 없음/no_selected_grids, (9) 100001행/1001격자 무절단, (10) 동시 ETL의 RR 일관성/다음 요청 변경, (11) 인구 없이 기존 AI/캐시/브랜드·개폐업 결과 동등, (12) BE 호출/FE 예시가 실제 schema와 같은지 검증, (13) 제외 구성의 day_only/night_only/both 분류 합이 제외 수와 같은지와 limitations 플래그, (14) category 필수/빈sub_category/brand·area·include·franchise의 구문 오류는422-before-DB, 실제 최소월·미래월 범위는D/M 조회 후422임을 구분, (15) 유리수 나머지 기반 숫자별 반올림 flag(day/night 평균 각각)·정수 HALF_UP과 50자리 quantize의 일치·D/N>1e15 합 허용·token을 query key 대신 쓰지 않는지, (16) 모든 block 상태에서 quality 필드 전부 non-null·limitations 닫힌 enum·상태별 observation_date null 규칙, (17) 요청 경로에 버전 전역 COUNT/GROUP BY scan이 없는지(쿼리 로그/EXPLAIN) 확인이다.

새 endpoint만 추가하므로 첫 rollback은 이전 BE artifact로 되돌리고 FE의 새 block 호출을 담당자가 중지하는 방식이다. 이전 코드가 읽던 DB0012/행/metadata는 그대로여야 한다. source 파일/DB를 지우거나 placeholder에 부분 인구를 넣어 구형 FE가 “전체 인구”로 읽게 하지 않는다. 새 API 장애가 기존 점포/AI의 실패로 전파되지 않는지 확인한다. 이번 설계의 완료·구현/실증·운영 BE 배포·FE 화면 반영·공식 전체 인구 검증을 각각 기록하고 #115/#78은 전체 완료로 닫지 않는다.

## 10. Claude Code 논의 요청과 실제 결과

아래 질문으로 실제 MD Read/Edit 대화를 요청했고 10.1절에 첫 결과를 보존했다. Codex의 수용/수정과 재검토는 그 뒤에 기록한다. 실행하지 않은 검토는 PASS로 표시하지 않는다.

1. 고정 `(grid,admin)` 공개 구성24시간 비교가 결측 편향을 숨기지 않고 실용적인가? 전체 인구 승인을 기다리지 않는 공개행 산술의 명칭/단위를 더 엄격히 분리해야 하는가?
2. all-source strict 대신 source 독립 비교와 local 고정 강조안, 새 endpoint·0012 읽기 전용·기존 API/AI 불변안에 차단 문제가 있는가?
3. U/C/누락 분모·반올림0·T/같은달·복수버전·RSS/상한·FE 프로필/문구/모의 계약 중 실행자가 추측할 부분이 있는가?
4. 문제를 해결한 것처럼 보이지만 실제로 결과가 더 안 나오는 조건은 무엇이고, clone에서 어떤 자료로 이를 판정해야 하는가?

검토 후 실제 MD 변경/근거를 Codex가 대조하고 수용/수정 이유를 기록한 뒤 재검토한다. 검토 입력에는 실제 인구 행·키/.env·개별 좌표·기관 답변 원문을 넣지 않는다.


### 10.1 Claude Code 1차 검토 (2026-11-16)

검토 범위: 이 두 MD와 사용자가 제공한 BE/FE 소스 일부(`day_night.py`, `population_totals.py`, `population_quality.py` 일부, `living_population.py`, `market_activity.py`/`risk.py` schema·service 일부, `spatial_stores.effective_date`, `chains` schema/router 일부, FE `risk.ts`/`params.ts`/`market.ts`/`SummaryPage`/`ActivitySection`/`indicatorFormat`)와 Codex 근거 요약뿐이다. 코드·SQL·테스트·실자료·원천 페이지·공식 검증은 실행하지 않았다. 이전에 기록된 Claude 검토나 Codex의 수용/거절 판단은 없으므로 이번이 첫 검토다.

**Q1 고정 공개 구성 비교의 정직성.** 공개 구성을 명시하고 그 구성의 기술(descriptive) 산술로만 표기한다면 정직하다. 대안별 판단은 다음과 같다.
- all-source strict: 거의 항상 마스킹되는 외국인 원천 때문에 내국인 값까지 막힌다. 전달받은 “15곳 중 2곳”과 같은 증상이 나는 구조적 원인이다.
- 격자 단위 완전성(격자 안의 모든 admin이 공개될 때만 사용): 제외만 늘어난다. U가 행에서 도출되므로 타당성도 더해지지 않는다.
- 시간별 단순 합: 시간마다 구성이 달라 무효다.
- 결론: `(grid,admin)` 24시간 고정 구성이 정직하면서 가장 작은 단위다.

남은 과학적 위험은 두 가지다.
- (a) admin 간 가산성이 확인되지 않았다. 구성이 겹치면 합/평균은 이중으로 셀 수 있으므로 총계로 읽혀서는 안 된다. 배수와 비중은 겹친 구성에 가중치가 더 실릴 뿐 정의는 유지되지만, 역시 반경 전체의 비율은 아니다.
- (b) 마스킹은 작은 값에 걸리므로 제외가 주야간 차이와 상관된 선택 편향이다.

그래서 이번에 (b)를 제외 패턴 수(`day_only/night_only/both`)와 limitations 플래그로 드러내도록 추가했다. 또 합/평균이 사람 수로 읽히는 것을 줄이려고 FE 기본 표시를 배수·비중·구성 수로 바꾸고 합은 상세 영역으로 내렸다. 이 조치 후에도 합 숫자가 노출되는 한 오독 위험은 0이 아니다. 하지만 단위 enum과 라벨로 충분히 구분되며, 추가로 막아야 할 차단 문제는 아니다.

**Q2 차단 문제.** source 독립 비교, local 고정 강조, 새 READ ONLY endpoint, 0013/승인 체계와의 독립, 기존 `living_pop:None`·Risk pending·AI `_activity` 불변 조건에서 차단 문제는 찾지 못했다. 기존 `RiskIndicator`는 day_night_ratio가 pending이 아니거나 unit이 '배'이면 schema에서 거부한다. 따라서 새 값을 기존 계약에 넣지 않는 결정은 회피가 아니라 필수다. FE에 include만 추가하라고 안내하지 않는 것도 맞다.

**Q3 실행자가 추측해야 했던 부분 → 수정함.**
1. 최상위/블록 상태와 HTTP 코드가 섞여 있었다. 최상위 `ready|pending|no_data|not_supported`(모두 200)과 블록 `partial|no_data|not_supported`로 나누고, 사유 목록을 닫았다(closed list). “원천 미준비”는 정의되지 않은 상태라서 삭제했다.
2. scope_too_large가 최상위 사유인지 원천 사유인지 불명확했다. 최상위로 정했다(격자 상한은 원천과 무관하다).
3. `rounded`·`exact_zero`·`display`·`unit`의 정확한 정의가 없었다. 판정식, unit enum, 추가 반올림 없는 display 규칙을 넣었다.
4. U_s 대상 행이 `grid_id`인지 `located_grid_id`인지 불명확했다. located 행만 쓰도록 정했다.
5. v1/v2 프로필 adapter를 담당자 선택으로 남겨 두었다. 인자를 5개로 줄이고 v2 경로로 고정했다(아래 Codex 이견 참고).
6. snapshot token에 canonical query, 즉 좌표가 들어가 있었다. 좌표·격자 ID를 빼고 서버 산출 본문만 hash하도록 바꿨다. 좌표 공간이 작아서 hash로 위치를 역추적할 수 있기 때문이다.

T/같은 달/복수 버전/RR/상한/no-store/422 순서/0·null 표는 소스(`effective_date`, `calculate_day_night`의 zero_total·night=0 처리, 관측 PK)와 일치하므로 그대로 두었다.

**Q4 해결된 것처럼 보이지만 실제로 값이 잘 안 나오는 조건과 clone 판정 자료.**
- (i) 관측 적재 지연: 기본 요청(T=현재 원천일)의 달에 관측 버전이 없으면 모든 위치가 최상위 `no_data/no_observation_in_period`가 된다. 같은 달 규칙은 시간적 정직성을 위해 유지한다. 판정 자료는 clone의 `living_population_versions.observation_date` 분포와 현재 T, as_of 월별 T의 대조다. 기본 요청이 전부 no_data이면 FE 카드가 기본 화면에서 비어 있게 된다. 이를 “연결 완료”가 아니라 “적재 필요”로 따로 기록한다. fallback으로 덮지 않는다.
- (ii) 외국인 원천: 작은 값이 마스킹되어 long/short는 대부분 `no_common_public_components`일 가능성이 높다. local 값만 나오는 것을 실패로 보지 않는다.
- (iii) 상업지의 야간 마스킹: night_only 제외가 많아 C가 작거나 0이 될 수 있다.
- (iv) 격자 도형/관측 격자 불일치: unlocated나 grids_without_rows가 많아진다.
- (v) 반경 300m: 격자가 몇 개뿐이라 C=0이 쉽게 나온다.
- (vi) 같은 날짜의 복수 버전: 재적재 후 pending이 된다.

clone에서는 다음을 비교한다. 대상은 전달받은 15곳을 확보하면 그 집합, 확보하지 못하면 자치구별로 층화한 비공개 좌표 집합이다. 반경 300/500/1000, 기본 요청과 as_of 월별 요청에서 원천별로 strict 대비 새 방식의 status/reason 분포, |S|·|U|·|C|, 제외 패턴 분포, 최상위 사유 분포, 응답 시간을 본다. 그다음 “local partial 비율”과 “기본 요청이 no_observation인지”를 각각 보고한다. 합격 기준 숫자는 이 설계에서 미리 정하지 않는다. 대신 이 두 수치를 보고하기 전에는 “유용한 결과가 나온다”고 쓰지 않는다.

**Codex 판단과 이견.** 기록된 Codex 수용/거절 결정은 아직 없다. Codex 근거 요약(현재 소스에 계산 경로가 연결되지 않음, FE include 누락, 공식 안내 재확인, 공개행 산술은 별도 참고값)에는 동의한다. 이번에 Codex 원안과 다르게 고친 점과 이유는 다음과 같다.
- ChainQuery를 그대로 재사용하고 점포 필터를 `*_applied=false`로 echo하던 방식을 5개 인자 전용 query로 바꿨다. 적용되지 않는 필터를 받으면 같은 값이 필터별로 다른 결과처럼 보이고, 캐시 key가 불필요하게 갈라지며, v1 adapter를 추측해야 한다.
- token 입력에서 query를 뺐다. 위치 역추적 위험 때문이다.
- “원천 미준비” 상태를 없앴다. 정의되지 않은 상태였다.

Codex가 위 변경 중 하나를 거절한다면 그 항목에 한해 REVISE로 되돌리고 사유를 이 절에 기록한다.

**판정: PASS (이번 문서 수정 포함 기준).** 이유는 다음과 같다.
- 결측을 0으로 바꾸지 않는다.
- 전체 인구라고 주장하지 않는다.
- 비공개 값을 역산할 경로가 없다.
- 기존 API/AI 계약을 바꾸지 않는다.
- 새 DDL/환경변수가 필요 없다.
- 상태·자릿수·인자·token을 실행자가 추측할 부분이 남지 않았다.

이 PASS는 설계 구현 가능성에 대한 판정이다. 구현·clone 실증·운영 배포·FE 반영·공식 전체 인구 검증의 완료를 뜻하지 않는다. 남은 비차단 확인 사항은 다음과 같다.
- ChainQuery의 sub_category가 필수인지 실제 정의에서 확인
- `current_provenance`가 sub_category별로 다른 T를 내는지 확인
- 중심점 geography 선택의 EXPLAIN 확인(§7)


## 11. Codex 대조·수용과 수정 후 재검토 요청

실제1차 대화는2026-11-16T07:40:48Z~07:44:42Z, exit0/is_error=false/18turns, 두MD 직접 수정·제공 BE/FE source SHA 보존·permission_denials0이었다. Claude의 원천별 고정 공개 구성/편향 구분·top/block 상태 분리·located 조건·기존 API/AI 분리·최소query 원칙을 수용했다. 원안과 다른 변경은 다음처럼 결정했다.

| 논점 | Codex 판단과 근거 |
|---|---|
| 5인자 query의 category 생략 | 원칙은수용, 개수는6개로수정. CategoryFilters.category는필수이고 sub_category는기본빈tuple다. current_provenance는전역D이며 최소월 검사에는 temporal_cohort(category,sub)가 필요하므로 category를추측할수없음. main/FE 계약을함께수정 |
| token에서 위치/개별명부 제외 | 수용. 결과지문으로한정하고 query key/동일위치·동일구성의증명으로사용하지않도록추가. 위치역추적 불가라는절대보장은철회 |
| 편향 경고의 비공개 문구 | 수용·보완. 분류에는 셀빈값/행부재도들어가므로 “비공개·누락”으로수정. 실제개수만표시하고방향은확정하지않음 |
| 공개 산술의비밀복원 불가 | 값을추측하지않는계산은수용, 다른공개자료와의모든추론차단보장은하지않도록범위수정 |
| rounded/zero/단위 | 명확화수용. Context flag의연쇄오염·정밀도와구분하려고정확한정수 나머지판정으로고정. 시간입력상한과12시간합상한구분, 각수치reason/values필수필드도정함 |
| 유용성 평가 | 수용. clone에서 실제local partial 수와월내관측부재·U/C/제외/시간을보고하기전 산정률개선/전체기능완료라고쓰지않음 |

10.1절은 실제 1차 검토 이력으로 보존한다. 그 안의 5인자·category 미확인·절대 privacy 표현보다 수정 본문과 이 절을 우선한다. 아직 실제 앱/API/DB/FE/AI는 변경하지 않았다. 다음 실제 Claude 재검토에서 category/T 근거·상태/숫자·FE 일치와 이견을 다시 확인한다.

## 12. Claude Code 최종(delta) 재검토 (2026-11-16)

검토 범위: 이 두 MD, 사용자가 이번에 제공한 소스 일부(`day_night.py`, `population_totals.py`, `population_quality.diagnose` 일부, `living_population.py` 모델, `market_activity`/`risk` schema·service 일부, `effective_date`, `chains` schema/router 일부, `store_filters.CategoryFilters`, `store_cohort.current_provenance`, `market_activity` 서비스 일부, FE `risk.ts`/`params.ts`/`market.ts`/`SummaryPage`/`ActivitySection`/`indicatorFormat`), 10.1절과 11절, Codex 근거 요약뿐이다. 코드·SQL·테스트·실자료·원천 페이지·공식 검증은 실행하지 않았다. `temporal_cohort`의 실제 정의는 제공되지 않아 확인하지 못했다.

### 12.1 Codex 결정 대조

| Codex 결정 | 판단과 근거 |
|---|---|
| 5인자 → 6인자(category 필수) | **동의.** 제공된 `CategoryFilters`는 `category: Category`가 기본값 없는 필수이고 `sub_category`는 기본 `()`다. `current_provenance(session)`은 category 인자 없이 전역 `max(data_updated_at)`을 반환한다. 반면 M은 `temporal_cohort(query, reference)` 조건의 `min(open_date)`라 category에 의존하고, `effective_date`의 최소월 검사가 M을 쓴다. 따라서 category 없이는 as_of 422 경계를 정할 수 없다. 1차 검토의 5인자 안은 이 사실을 확인하지 못한 오류였다. 10.1의 비차단 확인 2건(sub_category 필수 여부, sub_category별 T)도 이것으로 해소된다: sub_category는 선택이며 D는 전역이다. 남은 것은 `temporal_cohort`가 category/sub_category만 읽는지이며, §6에 구현 gate로 넣었다. |
| token = 결과 지문, query key·위치/구성 증명 아님 | **동의.** 같은 결과를 내는 다른 반경이 같은 token을 갖는 것은 지문 정의상 정상이다. FE가 보고서 결합에 요청 key와 token을 함께 쓰는 규칙과 일관된다. 1차 검토의 “hash로 역추적 불가” 함의를 철회한 것도 맞다. |
| 편향 문구 “비공개·누락” | **동의.** §4.4 분류는 suppressed·missing·행 부재를 모두 포함한다. |
| privacy 범위 축소 | **동의.** suppressed 구성은 통째로 빠지므로 숨긴 값이 산술항에 들어가지 않는다. 하지만 다른 공개자료와 결합한 추론까지 막는다고는 말할 수 없다. 노출되는 suppressed 여부·개수 자체는 원천 파일에 이미 공개된 표시다. |
| 정확한 유리수 나머지 기반 rounded | **동의, 판정식 검증함(손 계산).** 입력 소수 ≤5자리이므로 A, B는 정수다. A/12가 소수 5자리로 정확 ⇔ A%12=0, A/B ⇔ (A·10^5)%B=0, 100A/(A+B)가 소수 1자리로 정확 ⇔ (1000A)%(A+B)=0이다. 1000(A+B)≡0이므로 night 비중 flag는 day와 같다. 단 기존 본문의 “평균 rounded = A%12≠0 **또는** B%12≠0”은 숫자마다 flag를 두는 PublicNumber와 맞지 않아 **숫자별(day 평균 A, night 평균 B)**로 고쳤다. |
| 시간 상한 1e15 / D·N 1.2e16 | **동의.** `calculate_day_night`은 시간 입력만 `<1e15`를 검사하고 D/N은 검사하지 않는다. §4.6의 “중간 합계 Numeric(20,5) 상한” 표현이 D/N에도 적용되는 것처럼 읽혀 시간별 합에만 적용되도록 고쳤다. |

1차 검토 이후 Codex와 남은 이견은 없다.

### 12.2 이번에 찾아 고친 구체적 모호성

1. **요청마다 전역 scan 여부(차단급).** §7의 “V/G metadata 건수 상태 합 대조”는 `diagnose`처럼 버전 전체 관측 행을 GROUP BY하는 것으로 읽힐 수 있었다. 그렇게 구현하면 요청마다 전체 버전 scan이 생겨 기존 SQL timeout 예산을 위협한다. metadata JSON 내부 일관성만 검사하고 전역 COUNT는 import/clone 진단에 남기도록 고정했다(테스트 17).
2. **quality 필드와 null 여부.** “계산 가능한 개수만 채운다”와 “계산 가능한 모든 개수 필수”가 충돌했고 필드 이름 일부(`version_unlocated_*`, 상태별 행 수)가 없었다. 닫힌 필드 목록을 정하고 ready의 모든 block 상태에서 전부 non-null로 했다.
3. **limitations 값.** `exclusion_pattern_may_bias_ratio` 외의 값이 정의되지 않았다. 닫힌 enum(상시 4개 + 조건부 2개)으로 정했다.
4. **`method`/`scope` 내용과 날짜 null 규칙.** 비어 있던 객체 구조와 상태별 `observation_date` null 조건을 정했다. `analysis_date`는 200에서 항상 존재한다.
5. **반올림 값 계산.** flag는 정확한 유리수 기준인데 값은 50자리 결과의 quantize여서 이중 반올림 가능성을 설명해야 했다. 정수 HALF_UP을 기준으로 정하고, 자릿수 한계로 50자리 경로와 같음을 밝힌 뒤 테스트하도록 했다.
6. **배수 정의.** 구성별 배수의 평균이 아니라 합끼리의 비임을 `method.ratio_definition`에 명시했다. 큰 구성의 영향이 커진다는 점도 함께 적었다.

### 12.3 논의 질문(§10) 답변

**Q1. 고정 공개 행 `(grid,admin)` 24시간 구성을 원천별로 쓰는 안 vs complete-grid/strict/all-source.**
- all-source strict는 외국인 원천 마스킹 때문에 내국인 값까지 막아 실제로 값이 거의 안 나온다. complete-grid는 row-derived U 안에서 제외만 늘릴 뿐 기대 모집단 타당성을 더하지 못한다. 시간별 단순 합은 시간마다 구성이 달라 무효다. 원천별 고정 구성이 결측을 0으로 바꾸지 않으면서 가장 작은 정직한 단위라는 1차 결론을 유지한다.
- 과학적 정직성: admin 가산성과 격자 도형의 날짜 적용이 미확인이므로 합·평균은 중복이 있을 수 있는 공개 원천값의 산술일 뿐 인구 총계가 아니다. 배수·비중은 “이 공개 구성 집합의 주간 합 대 야간 합”으로는 정의가 성립한다. 하지만 중복 구성에 더 큰 가중치가 실리고 마스킹 선택 편향이 있어 반경 전체의 주야간 인구비가 아니다. 본문은 이를 `not_population_total`·`admin_additivity_unverified`·`grid_period_unverified`·편향 플래그·“인원수 아님” 라벨·합의 상세 영역 배치로 드러낸다. 이 조건을 지키면 인구 총계를 함의하지 않는다고 판단한다. 다만 합 숫자를 노출하는 한 오독 위험은 0이 아니다.

**Q2. 같은 구성의 주야, 0/반올림, 파일 기준 개수 vs 실제 coverage, 원천별 실패, 선택 편향, privacy.**
- 같은 C_s를 24시간과 D/N 모두에 쓰므로 주간·야간의 대상 구성이 같다. 원본 0은 포함하고, 결측은 구성 단위로 빠지며 0이 되지 않는다. 실제 0·반올림 0·밤 0·전체 0은 exact_zero·reason으로 구분된다.
- `used/candidate_component_count`는 파일에 나타난 후보 대비 개수일 뿐 반경 coverage가 아니며, `coverage_pct`·fraction을 만들지 않는 결정이 맞다. 하루 종일 행이 없는 구성은 U에 들어가지 않아 분모에서 보이지 않는다는 한계는 §5에 명시돼 있다.
- 원천 실패는 block 단위로 격리되고 무결성 오류만 전체 500이다. 선택 편향은 day_only/night_only 개수와 경고로 드러내되 방향은 단정하지 않는다. suppressed 값이 계산에 들어가지 않으므로 마스킹을 역산하는 경로는 없다(외부자료 결합 추론까지 막는다는 보장은 하지 않는다).

**Q3. 0013과 독립한 새 READ ONLY 0012 endpoint, 정확한 query/T/날짜/버전, 한도·timeout, 무결성/오류/상태 외피, strict schema·Decimal 단위, FE v1/v2·캐시·보고서·mock 일관성.**
- 0013 승인 체계는 전체 인구 경로의 gate이고 이 API는 기존 0012 표를 읽기만 하므로 독립이 맞다. DDL·환경변수는 필요 없다.
- query 6인자, T(전역 D + category 최소월), V(같은 월·같은 날짜 복수 버전은 pending), 격자 ≤1000·행 ≤100,000 limit+1, 기존 SQL timeout, 500/503/no-store, top/block 닫힌 상태·사유, PublicNumber 문자열·unit enum, 숫자 규칙이 12.2의 수정 후에는 실행자가 추측할 부분 없이 정해졌다.
- FE는 프로필과 무관하게 v2 경로·6인자 key·요청 취소·이전 값 초기화·report의 key+token 이중 확인·mock 시나리오가 BE 계약과 일치한다. FE 문서도 같은 내용으로 맞췄다.

**Q4. 기존 API/AI 계약 유지, 오해 소지 있는 living_pop.total=사람 수 금지, include만 추가하라는 안내 금지.**
- 제공된 `RiskIndicator`는 day_night_ratio를 pending 외 상태로 거부하고 unit에 '배'가 없다. AI `_activity`는 `living_pop`이 null이 아니면 오류다. 기존 FE `LivingPopulation.total: number`는 사람 수 표시를 전제한다. 따라서 새 값을 이 필드들에 넣지 않는 것은 필수다.
- FE 문서는 `useRisk(params, ['day_night_ratio'])`가 여전히 pending만 받는다고 명시하고, BE 구현 전에는 새 endpoint가 404일 수 있다고 안내한다. “include만 추가하면 된다”는 안내는 두 문서 어디에도 없다.

### 12.4 판정: **PASS** (이번 12.2 수정 포함 기준)

이유:
- Codex의 6개 정정을 소스와 대조해 모두 수용했고 남은 이견이 없다.
- 차단급이던 요청당 전역 scan 해석을 제거했고, quality·limitations·method/scope·날짜 null·반올림 값·배수 정의를 닫았다.
- 결측을 0으로 바꾸지 않고, 인구 총계·완전성을 주장하지 않으며, 기존 API/AI 계약과 DDL을 바꾸지 않는다.

이 PASS는 설계의 구현 가능성 판정이다. 구현·테스트·clone 실증·운영 배포·FE 반영·공식 전체 인구 검증의 완료를 뜻하지 않는다. 남은 구현 단계 확인(비차단, 결과에 따라 REVISE 가능):
- `temporal_cohort`가 category/sub_category만 읽는지(§6 gate)
- 중심점 geography 선택·관측 접근의 EXPLAIN/실측(§7)
- clone에서 local partial 비율과 기본 요청의 `no_observation_in_period` 여부 보고(10.1 Q4). 보고 전에는 “유용한 결과가 나온다”고 쓰지 않는다
- 같은 날짜 재적재로 복수 버전이 생기면 DDL 없이는 그 날짜가 계속 pending이다. 운영 적재 절차에서 같은 날짜 복수 버전을 만들지 않는지 확인한다


## 13. Codex 최종 대조와 문서 완료 범위

실제 Claude 재검토는 2026-11-16T07:47:10Z~07:51:46Z, exit0/is_error=false/12turns였다. 두 MD를 직접 수정했고 제공 BE/FE 소스 SHA 보존·permission_denials0을 확인했다. 12.2의 요청당 전역 COUNT 제거, quality/limitations/method/scope·날짜 null 규칙, 숫자별 반올림 판정·시간 상한·배수 정의를 실제 본문/FE 문서와 대조해 수용했다. 표시값은 검토된 정수 HALF_UP 경로로 고정했다. 단위/편향/부분자료라는 의미를 기존 인구 총계와 섞지 않는 조건도 유지한다.

Claude가 보지 못해 남긴 temporal_cohort 확인은 Codex가 실제 `app/services/store_cohort.py:25`의 전체 함수와 대조해 해소했다. category/sub_category 외 query 속성을 읽지 않는다. 또한 최종 대조에서 구문422-before-DB와 D/M 조회 뒤 날짜 범위422를 구분했고, 산술 수행 여부는 meta의 원천별 bool map으로 명시했다. token은 좌표를 뺀 공개 결과 지문이므로 같은 scope/출력의 다른 위치는 구분하지 못한다는 의미를 명확히 했다. 비공개 원천을 0으로 채우거나 전체 인구 승인을 새로 만든 변경은 없다.

검토 입력/산출 문서의 SHA·시각·도구 결과는 저장소 밖 검토 기록에 남겼다. 이번 작업은 BE Markdown6개뿐이다. 공식 페이지 재조회와 정적 소스 대조·문서 검사/기존 코드 자동 CI를 새 인구 API 실행·실데이터 산정률 개선·공식 근거 확인으로 표시하지 않는다. 새 endpoint/계산 조립기·FE·DB0012/환경·기존 서버/Render·Task/runtime은 변경하지 않았다. 실제 CI/일반 squash·로컬 develop 갱신 결과는 #178 연결 PR에 기록한다.
