# Risk 참고지표 API 연동을 위한 FE 변경 요청 보고서

- 작성일: 2026-11-12
- 대상: SpotON FE 담당자 / BE-23·25·26, F-07
- BE 이슈: [#64](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/64)
- 상태: **BE 참고지표 구현·검증 / 계산 보완안 및 FE 계약 검토·반영 대기**

## 1. 요청 범위와 계약 차이

`GET /api/risk`의 인허가 참고지표를 연결해 주세요. 동종업체 수·최근12개월 참고 폐업률·개업 1주년/3주년 생존율과 같은 조건의 서울 비교값을 제공합니다. 공식 폐업률·상권변화 유형·주야간 인구비 수치는 아직 활성화하지 않았습니다. 공식 창업위험도는 안내 링크만 제공합니다.

아래 계산은 원본 v1.2의 모호한 구간 정의와 FE mock을 Claude 검토 후 보완한 **BE측 계약안**입니다. 원본 문서나 FE 합의가 이미 완료됐다는 뜻이 아닙니다. FE 담당자가 의미·문구를 검토하고 조정이 필요하면 BE와 합의해 주세요. FE 코드·문서·CLAUDE.md·이슈/PR은 담당자가 관리하며 이번 보고서는 BE 저장소에만 작성했습니다.

| 항목 | 기존 FE 가정/목업 | BE 구현·요청 |
|---|---|---|
| 폐업률 최소 표본 | 현재 영업 점포10건 | 기간 중 영업한 기록의 실제 분모10건 |
| 생존율 관측 | n개월 이상 운영이면 포함 | 개업 n주년 당일에 영업 중이어야 포함. 당일 폐업 제외 |
| 생존율 의미 | 현재 잔존/기간 생존 혼동 가능 | 각 점포 n주년까지의 고정 관측기간 지표. T 이전 폐업도 n주년 이후면 포함 |
| source | string | 원본 v1.2대로 string[] |
| market.status | in_market/outside | 이번에는 unverified. 지정 파일의 공간 후보는 별도 spatial_candidate |
| competitor_count 비교 | 서울 평균 예시값 | seoul_avg=null·seoul_avg_reason=not_applicable |
| 소표본 | 일부 목업 처리 | value/numerator=null·denominator=실제 표본 수 유지 |
| 서울 비교 | 예시값 | 같은 필터·좌표 확보 점포의 분자합/분모합, 지표별 분자/분모 제공 |
| market_change | 반경 자체 참고 유형 예시 | 공식 지표로 취급·원천 그대로 연결 전까지 pending |

## 2. 요청·응답 구조

기존 `getRisk()`의 쿼리 변환 경로를 재사용할 수 있습니다. lat/lng/category 필수, radius=300/500/1000(기본500), sub_category·as_of·area·franchise·독립 unknown 토글은 nearby와 같습니다. legacy include_unknown은 개별 토글과 혼합할 수 없습니다.

- include는 market_change/day_night_ratio의 쉼표 목록입니다. 미요청은 파라미터를 생략합니다.
- 빈 값/토큰·중복·공백·대소문자 오류·LQ·미지원 인자·중복 쿼리는422입니다. 주소나 경계 UUID를 이 API에 보내지 않습니다.
- as_of는 YYYY-MM입니다. 최신 월은 검증된 전역 인허가 갱신일 D, 과거 월은 월말 T이며 실제 적용일은 data.query.as_of/meta.as_of입니다. 범위 밖은422 AS_OF_OUT_OF_RANGE입니다.
- 공통 `{data,meta,error}`를 유지합니다. data는 query/market/indicators/flags입니다. query에는 서버가 해석한 좌표·업종·반경·시점·필터가 있으며 주소는 없습니다.
- 필수 지표 순서는 official_closure_rate, official_risk, closure_rate_12m, survival_rate_1y, survival_rate_3y, competitor_count입니다. 선택 지표는 요청 순서와 무관하게 market_change,day_night_ratio 순서로 뒤에 붙습니다.
- source는 배열이며 source_url은 원문/안내 URL 또는null입니다. 각 지표의 source를 표시하고 공통 meta.source를 공식 수치 출처로 대신 쓰지 않습니다. official_risk의 source_url/link는 같은 공식 안내를 가리킵니다.
- 모든 응답은 no-store이며 준비/DB 실패는500 INTERNAL_ERROR입니다. 실패를 정상0건으로 바꾸지 않습니다.

## 3. 참고지표 계산과 표시

기간 문자열 `(L, U]`는 시작일 제외·종료일 포함입니다. 연 단위 이동은 같은 월일을 사용하고 없는2/29만2/28로 제한합니다. 반경은 geography 거리의 반올림 전 경계를 포함합니다.

### 최근12개월 참고 폐업률

- L=T의 전년 같은 월일, 분모는 open<=T이고 폐업일이 없거나 close>L인 유효 인허가 기록입니다.
- 분자는 L<close<=T입니다. close=L인 기록은 양쪽에서 제외하고 close=T면 분모/분자에 포함합니다.
- 같은 날 개폐업 기록도 기간 안이면 인허가1건으로 셉니다. 실제 영업일수나 폐업 원인을 추정하지 않습니다.
- 분모10건 이상이면 소수 첫째 자리 HALF_UP, 10건 미만이면 pending입니다. 현재 점포 수가10미만이어도 기간 분모가 충분하면 비율을 반환합니다.

### 개업 1주년·3주년 생존율

n=1/3일 때 진입 코호트는 `(T-(n+1)년, T-n년]`에 개업한 점포입니다. 각 점포의 개업 n주년까지 관측 가능하며 폐업일이 없거나 n주년보다 뒤면 생존입니다. n주년 당일 폐업은 제외합니다.

예를 들어 개업 1년2개월 뒤 폐업한 점포는 현재 폐업 상태여도 1주년 생존에는 포함됩니다. 이는 **현재 잔존율·실제 창업 성공률이 아닙니다.** 제목/도움말은 `개업 1주년 생존율`, `개업 3주년 생존율`처럼 관측 의미를 알 수 있도록 검토해 주세요. 각 지표의 period는 개업 코호트 구간이며 현재 영업 상태를 다시 세지 않습니다. 분모5건 미만이면 pending입니다.

### 서울 비교·0과 null

- 서울도 같은 시점·업종·세부 업종·면적·가맹 unknown 필터의 **좌표 확보 기록**에 같은 산식을 적용합니다. 서울 공식 통계나 구별 비율의 평균이 아닙니다.
- seoul_avg와 seoul_numerator/seoul_denominator를 함께 사용합니다. 서울 비교가 없으면 사유를 표시하고0으로 채우지 않습니다.
- 소표본/0분모: value=null, numerator=null, denominator는 실제0 또는 표본 수입니다. 비율을 FE에서 역산하지 않습니다.
- 충분한 분모의 실제0%는 status=fact,value=0입니다. 실제100%도 그대로 표시합니다.
- competitor_count는 T 시점 인허가 구간의 점포 수이며0도fact입니다. 서울 평균은 적용 대상이 아닙니다.

## 4. 공식·미확인 상태와 flags

이번 응답의 market.status는 unverified이며 market_code/name/type=null, also_in/nearby_markets=[]입니다. 공식 상권 적용 정보를 확인 중이라는 안내를 사용해 주세요. 이를 상권 밖으로 바꾸지 않습니다.

서버가 경계 버전을 명시한 경우에만 spatial_candidate가 있으며, 그 안의 spatial_status=in_market/outside/ambiguous와 primary/candidates/also_in/nearby_markets는 **해당 파일 형상에 대한 후보**입니다. 현재·과거 상권을 확정한 값이 아닙니다. 후보를 확정 상권명으로 대입하거나 공식 수치를 결합하지 않습니다. UUID/hash/서버 설정명은 사용자 화면에 표시할 필요가 없습니다.

| 지표/상태 | 동작 |
|---|---|
| official_closure_rate | value=null,pending·boundary_period_not_verified |
| official_risk | value=null,link_only. 서버 link의 공식 안내로 이동, copy_text=null |
| market_change 요청 | official/null/pending·boundary_period_not_verified |
| day_night_ratio 요청 | reference/null/pending·population_aggregation_and_grid_time_unverified |
| 표본 부족 | pending·insufficient_sample, 분모 표시 |
| 0분모 | pending·zero_denominator |

`flags.insufficient_sample`은 로컬 참고 폐업률/생존율 중 표본 미달이 있으면 true입니다. 공식·선택 항목의 pending이나 서울 비교만으로 켜지지 않습니다. `flags.missing`은 필수 공식 폐업률에 필요한 검증 경계와 요청된 선택 항목만 포함하며, 단순 소표본 지표나 미요청 항목을 추가하지 않습니다.

가맹 분류는 미적용pending 또는 명시 적용 후estimate/partial입니다. [추가 계약](fe-franchise-classification-api-request.md)의 목록명 일치/기준년도/역사적 선택 편향·data_version.brand_mapping·한계 사유를 함께 표시해 주세요. 원본 is_franchise는 보존하고 현재 원문과 일치한 별도 근거를 조회에 반영합니다. unknown배제0건을 실제 점포 부재로 단정하지 않습니다.

## 5. 합성 지표 예시와 meta

아래는 설명용 합성 지표2개만 발췌한 예시입니다. 전체 응답이나 실제 점포 통계가 아닙니다.

```json
[
  {"id":"closure_rate_12m","type":"reference","value":20,"unit":"%",
   "numerator":2,"denominator":10,"seoul_avg":12.3,"seoul_avg_reason":null,
   "seoul_numerator":49,"seoul_denominator":400,"space":"radius_500m",
   "period":"(2025-11-08, 2026-11-08]","source":["R5","R6"],"status":"fact",
   "reason":null,"source_url":null,"link":null,"copy_text":null},
  {"id":"survival_rate_1y","type":"reference","value":null,"unit":"%",
   "numerator":null,"denominator":4,"seoul_avg":80,"seoul_avg_reason":null,
   "seoul_numerator":8,"seoul_denominator":10,"space":"radius_500m",
   "period":"(2024-11-08, 2025-11-08]","source":["R5","R6"],"status":"pending",
   "reason":"insufficient_sample","source_url":null,"link":null,"copy_text":null}
]
```

meta.denominator는null이며 지표별 denominator를 사용합니다. meta.cohort_size는 T이전 개업·폐업을 포함한 전체 인허가 기록 수이므로 현재 점포 수가 아닙니다. excluded_no_coord도 서울 동일 비공간 조건의 T이전 개업 전체 미확보 수이며 반경/지표별 누락 수로 합산하지 않습니다.

meta.data_updated_at은 전역 인허가 D, as_of는 적용일T, collected_at은 현재null입니다. 수집일을 오늘/검증일로 채우지 않습니다. rule_version=risk-reference-fixed-anniversary-v1, survival_basis=fixed_opening_anniversary, closure_sample_basis=period_denominator 등 산식을 확인할 수 있습니다.

인허가 자료는 지위승계에 따른 폐업·개업을 구분하지 못하고 과거 값도 현재 보관된 날짜 구간으로 재구성합니다. 결측/오류 날짜·한시 영업·상태 모순은 기존 활동 API와 같은 규칙으로 제외합니다. 좌표 확보에 따른 선택 편향이 있을 수 있습니다. 공식 위험등급·성공/실패 확률·폐업 원인으로 표현하지 않습니다.

## 6. 수정 대상·완료 기준

검토 대상은 src/types/risk.ts·src/types/api.ts·지표/상태 라벨, src/api/mocks/risk.ts·nearby.ts, RiskSection과 지표 카드·ReportPage, messages·api-contract/decisions·FE CLAUDE.md입니다. 원본 규칙/보완안 차이를 계약 문서에서 분리하고, 서버 계산값을 다시 계산하지 않도록 해 주세요. 파일 분리/테스트 방식은 담당자가 결정합니다. 기존 단계별 실제 연결 설정에 `/risk`를 추가할 수 있고 BE 키/설정은 FE에 전달하지 않습니다.

- [ ] 기본/과거/필터 변경의 실제 /risk 호출·표/진단서 표시
- [ ] 기간 분모10 기준·0분모/소표본/실제0/100% 구분
- [ ] 개업 주년 관측 의미·n주년 당일 폐업 제외·주년 후 폐업 포함 안내
- [ ] source 배열·로컬/서울 분모 구분·동종업체 수 비교 적용 없음
- [ ] unverified를 outside로 바꾸지 않고 공간 후보를 확정 상권으로 승격하지 않음
- [ ] 공식 위험 링크·copy_text=null·조건부 요청/미요청·missing/표본 부족 구분
- [ ] 가맹 미확인·기준일/수집일·좌표 미확보 범위 안내
- [ ] 422/500·재시도·로딩, 기존 API 연결 회귀·lint/build/테스트
- [ ] FE 계약·CLAUDE.md 반영 및 계산 보완안 검토 결과를 BE에 전달
