# 점포 1개당 평균 추정매출 표시 설계 (#194)

작성일: 2026-11-16. 기준 BE develop `67737fa`, FE develop `80aaba2`. 사용자 요청은 기존 「인근 상권 추정매출」 목록의 매출을 더하고 점포 수로 나누어 점포 1개 기준 참고평균을 표시하는 것이다. 이번 산출물은 설계·자료 비교·실제 Claude Code 검토다. 앱/FE/ETL/DB/환경/배포 변경은 후속 구현 범위다.

## 1. 결론과 표시할 값

**점포 1개당 평균 추정매출 = 같은 자료 분기의 계산 가능 항목 매출 합계 ÷ 그 항목들의 전체 점포 수 합계.**

여기서 개수는 화면 목록 카드 수나 거래 건수가 아니라 상권·업종별 점포 수다. 분자와 분모에는 항상 같은 항목 집합을 사용한다. 월매출/분기총액 환산은 하지 않는다.

- 첫 릴리스의 성격은 **상권자료의 점포 수 가중 참고평균**이다. 검색 점포의 예상 매출이나 반경 안 고유 점포들의 실제 평균으로 확정하지 않는다.
- 사용자 요청에 따라 현재의 “상권별 금액 표시”에서 “별도 참고평균 계산”으로 확장한다. 기존 원자료 목록·인구/주야간·AI/Risk 계약은 유지한다.
- 겹치는 상권도 사용자가 보는 실제 후보 목록에 남긴다. 합계에 같은 실제 점포가 다시 반영될 수 있음을 표시한다. 구역 간 점포의 고유 ID/매출 내역이 없어 중복을 제거했다고 주장하지 않는다.
- 날짜가 섞이면 분기별로 나누어 계산한다. 대표값에 포함된 목록 항목을 표시하고 이전 분기 항목은 별도 분기의 평균으로 확인할 수 있게 한다.
- 새로운 외부 API 키는 필요하지 않다. **기존 공개 GET의 평균 필드와 FE 표시를 실제로 구현하는 작업은 필요하다.** DB에 자료가 있는 현재 상태를 API/화면 연결 완료와 혼동하지 않는다.

### 합성 예시

| 같은 분기 자료 | 매출 원자료 금액 | 전체 점포 수 | 항목별 금액/점포 |
| --- | ---: | ---: | ---: |
| A상권·커피 | 1,000,000원 | 10 | 100,000원 |
| B상권·커피 | 9,000,000원 | 30 | 300,000원 |
| 대표 참고평균 | **10,000,000 ÷ 40 = 250,000원/점포** | | |

목록 2개로 나눈 5,000,000원은 상권 항목당 평균이다. 항목별 평균을 단순 평균한 200,000원도 이번 점포 수 가중 평균과 다르다. 실제 서비스 금액을 사용한 예시는 아니다.

## 2. 현재 시스템과 확인 결과

| 구분 | 현재 | 후속 변경 |
| --- | --- | --- |
| 매출 | `MarketSale.est_sales`: 원자료 `당월_매출_금액`, BIGINT/null | 원문 금액 유지, 평균의 분자로 사용 |
| 거래 건수 | `source_sales_count`: `당월_매출_건수` | 점포 수 분모로 사용하지 않음 |
| 점포 수 | `MarketStore.total_stores/general_stores/franchise_stores` 적재 | 같은 상권·분기·업종으로 일괄 조회해 연결 |
| 원천 버전 | catalog 지문과 매출→점포→경계 FK를 `_versions()`에서 검증 | 같은 버전 묶음을 재사용, 별도 최신 UUID 검색 없음 |
| 공개 API | `/api/v2/location-reference`의 `sales.items`에 금액만 반환 | 점포 수/항목별 단가/대표·분기별 참고평균을 추가 |
| 시간 선택 | latest_reference는 **각 항목**의 최신 금액 행을 선택 | 기존 행을 바꾸지 않고 분기별 집합을 구성 |
| FE | `LocationReferenceView.tsx`가 원자료 금액 문자열 표시 | 대표평균 + 계산 근거 + 기존 상세 목록 |
| 일관성 | 같은 READ ONLY REPEATABLE READ, no-store, snapshot token | 동일 세션에서 점포 수와 평균까지 산출 |

### 2.1 이번 읽기 전용 실증

별도 로컬 원본 `spoton_dev`의 head0012에서 매출/점포/경계 표만 READ ONLY REPEATABLE READ로 조회했다. 운영 head0013, 운영 DB/환경 및 로컬 원본에는 쓰지 않았다. 실제 위치·접속정보·원자료 레코드는 문서/Claude 입력에 포함하지 않았다.

- catalog 지정 매출14,391행, 점포24,810행, 두 자료 모두2025년·같은 경계 FK다.
- 매출 분기별3,617 / 3,596 / 3,597 / 3,581행 전부 같은 분기·상권·업종의 점포 행과 연결됐다. 이 교집합에서 금액 null/분모0/이름·유형 충돌은0이었다. 모든 점포 행의 일반성·공식 모집단 동등성을 확정한 검사는 아니다.
- 기존15지점의 숫자 매출212개 모두 점포 수와 연결됐다.
- 15지점 중7지점에 후보 상권 간 **양의 면적을 가진 도형 중첩**이 있었다. 이는 실제 점포 중복의 증명이나 중복 점포 수 측정이 아니다.
- 15지점 중3지점은 현재 목록의 숫자 행에 서로 다른 자료 분기가 섞여 있었다. 따라서 혼합 분기 처리는 가상 예외가 아니다.
- 비공개 집계 증거: `sales-per-store-design-20261116/source-probe.json`. 이번에는 평균 API/FE를 구현하거나 배포·통합시험을 수행하지 않았다.

## 3. 분자·분모 연결 규칙

원천은 이미 보유한 추정매출 OA-15572와 점포현황 OA-15577을 쓴다.

1. 현재 `_versions()`가 검증한 매출 버전, 해당 매출 버전의 `code_check_store_version_id`, 해당 경계 버전을 고정한다. 두 source_year도 catalog와 같아야 한다.
2. 기존 `sales.items`의 `(market_code, source_quarter, industry_code)`와 점포 행의 `(market_code, quarter, induty_cd)`를 정확히 연결한다. 점포 버전까지 포함해야 유일하다.
3. 상권명·상권유형·업종명도 **선택된 eligible 매출 행**과 맞는지 확인한다(그 매출 행은 이미 Candidate와 일치한다). 같은 키의 다른 과거 raw 행에 충돌이 있어 기존 sales 블록이 partial이어도 선택된 행/점포 쌍이 맞으면 평균에 포함한다. 현재 선택된 매출 행과 점포 행의 충돌만 `store_mapping_conflict`로 제외한다. 이름으로 근사 연결하거나 다른 업종/상권으로 대체하지 않는다.
4. 분모는 **`total_stores`**다. 현재 ETL의 `similr_induty_stor_co → total_stores`, `stor_co → general_stores`, `frc_stor_co → franchise_stores` 매핑을 그대로 추적한다. 기존 CHECK `total = general + franchise`도 확인한다. 일반 점포 수만 사용해 전체 매출을 나누지 않는다.
5. `nearby.total`, 인허가 점포 수, 활성 점포 수, 현재 영업 중 점포 수를 분모로 바꾸지 않는다. 자료의 시점·영역·업종·분류 모집단이 다르다.
6. 매출 표와 점포 표의 기간별 구성·매출 추정 대상이 점포별로 정확히 동일하다는 공식 보장은 이번 확인으로 얻지 못했다. `population_compatibility=unverified`를 노출하고 **산술적으로 계산 가능한 참고지표**로 표시한다. 이 미확정을 이유로 모든 참고평균을 다시 pending으로 막지는 않는다.

가맹/브랜드/면적 필터는 분자·분모 양쪽 모두 적용하지 않는다. 업종은 기존 매출 목록의 선택 업종만 사용한다. 반경과 일부만 교차한 상권도 상권 전체 매출·점포 수를 함께 사용하며 면적 비례로 자르지 않는다.

## 4. 목록과 대표 분기

### 4.1 기본 latest_reference

기존 원자료 목록의 선택·순서·금액·자료분기를 바꾸지 않는다. 각 항목의 기존 최신 금액을 보존한다.

1. 숫자 매출이 있는 기존 목록의 `source_quarter`를 모은다.
2. 그중 가장 최근 분기를 `primary_quarter`로 정한다. 점포 수의 유무로 대표 분기를 과거로 이동하지 않는다.
3. 같은 분기끼리 `groups[]`를 만들고, 연결 가능한 매출/점포 쌍만 각 분기의 합계에 사용한다.
4. 대표평균은 primary_quarter 그룹이다. 최신 그룹의 분모가 모두 없으면 대표평균은 no_data다. 이전 그룹은 별도 자료 분기와 값으로 보여 줄 수 있으나 자동 대표값 대체는 하지 않는다.
5. 숫자 매출이 전혀 없으면 primary_quarter=null이고 평균도 no_data다. 점포 수 자료의 최신 분기로 매출을 만들어 넣지 않는다.

### 4.2 analysis_period

기존 분석 기준 T가 속한 자료 분기만 사용한다. `primary_quarter=desired(T의 분기)`는 숫자 매출이 없어도 유지한다. 그 분기의 매출·점포 쌍이 없으면 no_data이며 다른 분기로 대체하지 않는다. 기존 as_of 검증과 인허가 기준일 선택은 변경하지 않는다.

### 4.3 상태와 상위 상태의 전파

먼저 기존 sales 상태가 pending/not_supported/no_data이고 계산 가능한 숫자 매출이 없으면 그 상태·사유를 새 평균 객체에도 복사하고 계산을 생략한다. 합계/metric은null, groups는빈배열이다. 이때도 analysis_period의 primary_quarter는desired, latest_reference의 primary_quarter·시간필드는null이다. 전파 경로의 listed_item_count=len(items), included_item_count/included_market_count=0, excluded_counts는항목이있으면sales_unavailable=len(items),없으면{}다. 각항목기여는excluded/sales_unavailable이며상위reason은원래sales의사유를그대로쓴다.

실제 숫자 목록으로 계산할 때 대표 상태는 `included==listed && included>0 → ready`, `0<included<listed → partial`, `included==0 → no_data`다. 그룹은 listed 대신 해당 분기의 `candidate_item_count`로 같은 판정식을 쓴다. partial 사유는 `partial_source_rows`, 전부 제외된 계산 집합은 `no_valid_sales_store_pairs`다. 따라서 혼합 분기에서 대표는partial이어도 각 분기 그룹은ready일 수 있다. 기존 sales의 과거 충돌 집계가 새 평균의 제외 수로 복제되지는 않는다.

latest_reference에서 숫자 매출이 없으면 primary_quarter/temporal_relation/period_end_after_analysis는모두null이다. analysis_period의 시간 관계는 자료분기desired와T로 계산한다. 상위 상태 전파 시를 제외하면 groups는 실제 숫자 매출이 있는 분기별로 하나씩 생성한다. 최신 분기의 전부 제외된 그룹도 없애지 않는다.

### 4.4 재계산 가능한 화면

기존 전체 상세 목록을 보존하고 각 항목에 `대표평균 반영`, `다른 자료 분기`, `평균 계산 제외`를 표시한다. 대표 분기의 포함 항목들에 표시된 매출 합계를 표시된 점포 수 합계로 나누면 대표평균과 일치해야 한다. 다른 분기의 금액은 대표 합계에 넣지 않는다.

이전 분기 항목은 대표 기준의different_quarter 표시를 유지하고 자기 그룹의 제외 사유는 그룹 합계 excluded_counts로 설명한다. 첫 릴리스에서 항목별 group_contribution을 추가하지 않는다. 기존 sales.partial 주석과 새 평균.ready의 coverage 문구도 각각 원자료 상세/평균 영역으로 분리한다.

여러 업종을 선택한 음식점도 같은 분기의 상권·업종 항목을 합한다. `included_item_count`와 `included_market_count`를 구분한다. 하나의 상권 안에 4개 업종이 있으면 항목4개/상권1개다. 업종 간 고유 점포의 유일성도 확인됐다고 주장하지 않는다.

## 5. 산술·결측·중복

분기 q의 계산 가능 집합을 Iq라고 하면 `S_q = Σ sales_i`, `N_q = Σ total_stores_i`, `A_q = S_q / N_q`다. 각 항목이 매출 합과 점포 수 합에 동시에 들어가거나 동시에 빠져야 한다.

| 상태 | 계산/표시 |
| --- | --- |
| 금액≥0, 점포 수>0, 키/명칭 일치 | 분자·분모 모두 포함 |
| 금액0, 점포 수>0 | 실제0으로 포함 |
| 금액null/행 없음 | 점포 수만 분모에 넣지 않음 |
| 점포 행 없음 | 매출만 분자에 넣지 않음 |
| 점포 수0 | 0으로 나누지 않음; 매출>0이면 별도 불일치 사유 |
| 서로 다른 분기 | 각 그룹에서 계산; 대표값에는 선택 분기만 포함 |
| 점포와 선택 매출 행의 명칭/유형 불일치 | `store_mapping_conflict`로 해당 쌍 제외 |
| 점포 수 타입/음수/일반+가맹 합계 불일치 | 내부 원천 정합 오류로 fail-closed, coverage에서 정상 결측처럼 숨기지 않음 |
| 모든 쌍 제외/분모합0 | 평균null/no_data; 기존 raw 목록은 유지 |
| 완전한 같은 분기 쌍 일부만 존재 | 계산 가능한 부분 참고평균/partial + 포함·제외 수 |
| 동일 원천 식별 행이 중복됨 | 내부 정합 오류로 거부; “같은 행”을 두 번 더하지 않음 |
| 서로 다른 상권 도형 중첩 | 다른 항목으로 보존·계산, 실제 점포 중복 미제거 고지 |

`ready`는 선택 집합의 산술 완료를 뜻한다. 경계 시점/매출기간/고유 점포 모집단의 공식 검증 완료를 뜻하지 않는다. 기존 `meta.items_additive=false`는 유지한다. 별도 지표가 중복 가능 자료 행을 가중하는 것과 “반경 고유 점포 합계”는 구분한다.

### 5.1 숫자 정밀도

- BE Python int로 S/N의 분자·분모를 정확히 합한다. 큰 원화 금액과 점포 수 합계는 JSON 문자열로 반환한다.
- 매출 원문 1행의 BIGINT 상한과 합계 상한은 다르다. MAX_DETAILS=500에서 합계가2^63을 넘을 수 있으므로 현재 `SourceNumber`의 1행 상한 검증을 합계에 재사용하지 않는다. `0≤S≤500×(2^63−1)`, `0<N≤500×(2^31−1)`로 제한한다(정상 계산값 기준).
- 정확한 원본 비율은 `numerator=S`, `denominator=N`으로 보존한다. `value`는 Decimal50 유효숫자로 계산한 십진 문자열이며 순환소수의 유한 근사임을 계약에 명시한다.
- 표시 순서는 ①S=0이면“0원/점포” ②0<S<N이면반올림대신“1원 미만/점포” ③그 외는정수 `quotient,remainder=divmod(S,N)`과 `2*remainder >= N`으로원단위 HALF_UP이다. 0.4/0.5/0.6원은모두“1원 미만/점포”,1.5원은“2원/점포”다. `rounded`는 `remainder != 0`, `exact_zero`는 `S == 0`으로 정한다.
- value는 `localcontext(Context(prec=50, rounding=ROUND_HALF_UP))` 안에서 S/N을 계산하고 `format(value,'f')`를 사용한다. 소수점이 있을 때만 후행0과마지막소수점을제거한다. 정수250000이25가되도록rstrip하지 않는다. 지수 표기/음의0/전역context변경은 금지한다. 서버 validator는 원래정수비율과 value/display/rounded/exact_zero의 일치를 확인한다.
  value 검증도 같은localcontext/정규화 규칙으로 재계산한 문자열과 정확히 비교한다. float/허용오차 비교를 하지 않는다.
- FE는 서버 display를 그대로 사용하고 Number 변환·합계·나눗셈·반올림을 하지 않는다.
- 원자료 기간은 `source_reported/unverified`로 유지한다. 3으로 나누거나 곱해 월/분기 매출로 변환하지 않는다.

## 6. 공개 API 추가 계약안

기존 `GET /api/v2/location-reference`와 입력7개를 유지한다. 기존 `sales.items`의 필드/의미는 보존하고 다음 optional 필드를 추가한다. 기존 FE는 raw 금액을 계속 읽을 수 있고 새 FE는 이전 BE에서 평균 필드가 없으면 raw 금액을 평균처럼 표시하지 않는다.

### 6.1 항목 추가

`sales.items[].store_reference`:

- `status=ready|no_data`, `reason`
- `source_quarter`: 부모 금액과 같은 분기; 연결 불가능이면null
- `total_stores`, `general_stores`, `franchise_stores`: 정확한 십진 정수 문자열 또는null
- `provenance_ref="store-counts"`

점포 수0도 관측된 원자료이면 store_reference.status=ready와문자열"0"이다. 평균만null/제외처리한다. 관측0을 점포 행 부재와 혼동하지 않는다.

점포명/유형충돌이면store_reference.status=no_data/reason=store_mapping_conflict,수치는모두null이다. 숫자매출이없는항목은조회키에넣지않고store_reference=null로둔다. 누락·충돌행의숫자가화면합계에섞이지않게한다.

`sales.items[].per_store_metric`: 연결 가능한 같은 쌍의 숫자 객체 또는null.

`sales.items[].average_contribution`: `included|different_quarter|excluded`와 사유. included는 대표평균 반영이다. different_quarter의 reason도different_quarter다. 다른 분기 항목이 자체 그룹 평균에 반영될 수 있음은 그룹 included_item_keys로 확인한다.

### 6.2 대표·분기별 평균

`sales.per_store_average`:

```json
{
  "rule_version": "source-row-store-weighted-v1",
  "status": "ready",
  "reason": null,
  "primary_quarter": "20254",
  "temporal_relation": "later_reference",
  "period_end_after_analysis": true,
  "aggregation_basis": "listed_source_rows_weighted_by_total_stores",
  "store_count_basis": "source_total_stores",
  "deduplication": "not_performed",
  "unique_store_average": false,
  "population_compatibility": "unverified",
  "amount_period_status": "unverified",
  "listed_item_count": 2,
  "excluded_counts_scope": "listed_items",
  "included_item_count": 2,
  "included_market_count": 2,
  "excluded_counts": {},
  "total_sales": "10000000",
  "total_store_count": "40",
  "metric": {
    "numerator": "10000000",
    "denominator": "40",
    "value": "250000",
    "value_precision": "decimal50",
    "display": "250,000원/점포",
    "unit": "KRW_source_reported_per_store",
    "rounded": false,
    "exact_zero": false
  },
  "groups": [
    {
      "source_quarter": "20254",
      "temporal_relation": "later_reference",
      "period_end_after_analysis": true,
      "status": "ready",
      "reason": null,
      "candidate_item_count": 2,
      "excluded_counts_scope": "group_numeric_items",
      "included_item_count": 2,
      "included_market_count": 2,
      "excluded_counts": {},
      "total_sales": "10000000",
      "total_store_count": "40",
      "metric": {
        "numerator": "10000000",
        "denominator": "40",
        "value": "250000",
        "value_precision": "decimal50",
        "display": "250,000원/점포",
        "unit": "KRW_source_reported_per_store",
        "rounded": false,
        "exact_zero": false
      },
      "included_item_keys": [
        {"market_code": "3110001", "industry_code": "CS100010", "source_quarter": "20254"},
        {"market_code": "3110002", "industry_code": "CS100010", "source_quarter": "20254"}
      ]
    }
  ]
}
```

합성 예시이며 실제 점포/상권의 수치가 아니다. 예시의 분석 기준 T는2023-11-30이다. `groups[]`는 분기 내림차순으로 반환하고 재귀적 groups 필드는 없다. 대표는 primary_quarter 그룹을 참조하고 포함키를 별도로 중복 반환하지 않는다. 대표의 합계/metric/포함건수는 그 그룹과 같아야 하고 해당 그룹의 키 집합은 항목 contribution의 included 집합과 같아야 한다. 대표 coverage는 전체 목록, 그룹 coverage는 해당 분기 숫자 항목 기준이다. 시간 관계는 기존 `_temporal`/`_bounds` 규칙으로 BE가 계산한다.

대표 coverage는 **기존 전체 목록**을 한 번씩 분할한 수다. `listed_item_count = included_item_count + Σ excluded_counts`를 만족한다. 사유 우선순위는 ①sales_unavailable ②different_quarter ③store_row_missing ④store_mapping_conflict ⑤zero_store_count_with_sales/zero_store_count다. 그룹에서는①②를적용하지않는다. 내부정합 오류는이정상사유열거형에넣지않는다. 제외 항목 하나에 복수 사유를 중복 집계하지 않는다. 그룹은 해당 분기의 숫자 매출 항목 기준으로 `candidate_item_count = included_item_count + Σ excluded_counts`를 만족한다.

기존 `sales.excluded_counts`는여전히시장·업종쌍의과거raw매핑충돌을포함하는기존scope다. 새 객체는 대표 `excluded_counts_scope=listed_items`, 그룹 `group_numeric_items`를명시해 기존meta.excluded_counts_scope와혼동하지않게 한다.

no_data/pending/not_supported에서는 metric/total_sales/total_store_count는모두null이다. FE는이를0원/0개로 표시하지 않는다. 신 BE는 항상 per_store_average **객체**를 반환하며null로 생략하지 않는다. 구 BE의 field부재만 별도 호환 상태다. 소스 미적재/버전 모호성은 기존 sales 블록 상태/사유를따라 계산 가능한 값을 생성하지 않는다.

### 6.3 출처·캐시

source_refs에 별도 `store-counts` 근거를 추가한다: OA-15577 URL, source_year, rule_version, source_file_date/loaded_at, input_sha256/content_sha256, 일반·가맹 포함 범위와 분모 원천 필드similr_induty_stor_co. 경계시점은기존경계근거를참조하며점포버전에없는boundary_as_of를만들지않는다. 기존 sales 근거는 유지한다.

catalog 형식/DB version은 이번 산술 때문에 바꾸지 않는다. API의 기존 additive 계약은 유지하고 새 객체의 rule_version으로 계산 방식을 구분한다. 기존 snapshot token의 data/meta 직렬화에 새 객체·점포 근거가 포함돼 결과가 바뀌면 token도 바뀌어야 한다. 기존 cache-key 정책/기준월/취소/응답의 no-store를 유지한다.

새 필드 배포 시 기존응답과 token이 한 번 바뀌므로 FE/보고서의 이전참고캐시는 무효화된다. 이를 릴리스 기록에 남기고 기존AI 캐시의 의미를 바꾸는 것과 혼동하지 않는다.

## 7. BE 구현 변경 지점

1. `app/schemas/location_reference.py`: 점포 참조, 항목 단가, 그룹/대표평균, 사유 코드와 coverage/숫자 일관성 validators를 추가한다.
2. `app/analysis/market_reference.py` 또는 별도 `app/analysis/per_store_sales.py`: 외부 원천검증과 분리된 순수 합계·정수분모·원단위 반올림 함수. 이미 검증한 S/N 쌍을 입력받고 원자료의 기간 의미를 새로 확정하지 않는다. 현재 `project_sales`가 요구하는 검증 완료 기간을 거짓으로 넘기지 않는다.
3. `app/services/location_reference.py`: 현재 raw 선택 뒤 고정된 점포 버전에서 키 집합을 일괄 조회하고 연결/그룹/coverage/근거를 조립한다. 가능한 raw 항목을 먼저 모두 생성해 원래 목록 의미를 보존한다.
   현재 `_sales()`가 `sale,boundary,_`로버리는검증된MV를유지해그대로전달한다. DTO에같은사실을따로누적하지않고한group결과에서대표/항목기여를투영하며validator로교차일치를확인한다.
   `_sales()`의결과를query/target이있는단일후처리에서마무리하며모든early상태도이를거친다. `_empty()`등중간SalesBlock의평균필드는None일수있으나최종LocationReference model_validator가평균객체의부재/None을거부한다. 이로써내부중간상태와신BE의공개항상객체계약을구분한다. store-counts출처는검증된MV를확보했을때만추가한다.
4. SQL은 tuple `(market_code,quarter,induty_cd)` IN 최대500키 + 고정 version_id의1회 조회로 고정한다. N+1 조회를 하지 않는다. 최대501행 탐지는상한검사이며중복행의DB방지는PK가담당한다. Python키map/DTO중복도별도로거부하고기존PK/인덱스를재사용한다.
5. 신규 DDL/데이터 재적재/신규 외부 통신은 필요하지 않다. 운영 head0013/기대revision/환경17개를 유지한다. 누락 원자료가 발견된 경우에만 별도 적재 작업으로 분리한다.
6. raw null·분모0 등 정상 결측은 항목/평균의 명시 상태로 처리한다. FP·행수 불일치/중복 같은 내부 원천 정합 오류는 기존 optional endpoint의 fail-closed 정책을 따른다. Risk/AI/인구 경로에는 새 지표를 자동 입력하지 않는다.

## 8. FE·보고서 설계

현재 카드 배치와 다른 기능은 유지한다. 「인근 상권 추정매출」 안에 대표 지표 **점포 1개당 평균 추정매출**을 추가하고 기존 금액은 상세 원자료로 보존한다.

```text
인근 상권 추정매출
점포 1개당 평균 추정매출 [참고]
250,000원/점포
자료 분기 2025년 4분기 · 2상권/2항목 반영
매출 합계 10,000,000원 ÷ 점포 수 합계 40개
상권별 점포 수를 가중한 참고평균이에요. 겹치는 상권의 점포는 중복 포함될 수 있어요.
[계산에 사용한 항목 보기] [다른 분기 보기] [상권별 원자료 보기]
```

위 금액은 합성 예시다. 실제 화면에는 다음이 반드시 보인다.

- 대표 자료분기, 반영항목/전체항목 수, 점포 수 합계와 매출 합계. 점포 수 합계를 반경 내 고유 점포 수로 부르지 않는다.
- partial이면 “전체26항목 중22항목 반영”과 제외 사유를 확인할 수 있게 한다. 숫자만 크게 보여 주고 누락을 숨기지 않는다.
- “가맹·브랜드·면적 조건은 적용하지 않아요”, “월매출로 환산하지 않은 원자료 금액 기준”, “이 자리 점포의 예상/보장 매출이 아니에요”를 기존 설명과 통합한다.
- 다른 분기의 참고평균은 날짜와 함께 별도로 표시한다. 숫자 없는 그룹은0으로 표시하지 않는다.
- 분석/종합/PDF가 같은 응답과 display를 사용한다. PDF는 기존 reference 조회를 기다리며 포함/제외 근거와 계산식을 싣는다. 다른 곳에 표시할 결과를 FE에서 재산출하지 않는다.
- 공유 이미지에 이 지표를 담게 되면 동일 query key/완료대기를 적용한다. 이번 첫 릴리스에서 공유 이미지를 바꾸지 않으면 담았다고 주장하지 않는다.
- `src/types/locationReference.ts`, 기존 API 타입/`LocationReferenceView.tsx`/표시 테스트, `ReportPage.tsx`와 FE 전달 문서를 변경한다. 기존 요청7개와 주소/반경/업종 캐시 투영을 재사용한다.

## 9. 구현 수용시험

| 시험 | 기대 |
| --- | --- |
| 합성 A/B 예시 | 10,000,000/40=250,000; 항목 평균/목록 수 나눗셈과 구분 |
| 항목 순서/동일 키 중복 | 순서 독립, 중복 키 거부 |
| 매출0/N>0 | 실제0 포함·exact_zero=true |
| 매출없음/분모없음/0분모 | 반드시 쌍으로 제외, no_data와0 구분 |
| 한 항목의S>0/N=0 | 불일치 사유, 다른 정상 항목 부분평균 유지 |
| 혼합20254/20253 | 두 그룹 별도, 대표는20254; 분기 간 합산 없음 |
| 최신 분기 분모만 누락 | 대표no_data, 이전 분기로 자동 대체 없음 |
| analysis_period 자료 부재 | 다른 분기 fallback 없음 |
| 한 상권 여러 업종 | 항목수/상권수 구분, 선택 업종만 합산 |
| 중첩 상권/관광특구 | 별도 자료행 가중, unique=false/중복미제거, raw 목록 보존 |
| 큰 금액 2^53 초과·합계2^63 초과 | 문자열/정수 합계/표시 일치 |
| 1/3,0.4,0.5,0.6원/점포·1.5원 | 앞의양수4개는1원미만,1.5는2원; 지수표기없이원래분수보존 |
| 0.5원 근처의 큰 정수 비율 | Decimal 중간 반올림이 표시 방향을 바꾸지 않음 |
| coverage 분할 | 항목 수 등식·사유1개·누락 쌍 양쪽 제외·합계와포함키 일치 |
| 원천/분기/명칭/FK 불일치 | 부분 사유 또는 원천정합 오류, 다른 자료로 추정 연결 없음 |
| 동일 RR 도중 버전 변경 | 같은 snapshot으로 분자·분모·기존 결과 유지 |
| API 호환/캐시 | 구 필드 보존, 새값 변동 시token변경, 구 응답에는 총액→평균 전용 금지 |
| FE 취소/지연/404/null | 이전 조건 값 유출 없이 독립 오류/결측 표시 |
| 기존3지표·Risk/AI 회귀 | 기존 값·기간·범위/요청보호 유지 |
| 360/390px·PDF | 긴 원화/점포 수·분기·계산 근거가 잘리지 않음 |
| 과거raw충돌이있는ready항목/점포명만충돌 | 전자는선택쌍이맞으면포함,후자만store_mapping_conflict |
| 혼합분기coverage | 대표partial/각그룹ready가능,기존sales.excluded_counts와분리 |
| analysis_period 숫자0건 | 대표분기desired유지/no_data,latest의null분기와구분 |
| source미적재·구버전 | 신BE는객체+기존상태/사유,구BE만field부재 |
| 대표투영·그룹키·contribution불일치 | validator거부,한근거집합으로생성 |
| 상위전파/매출쪽충돌/점포쪽충돌 | 전파coverage등식·항목기여·null숫자,버전미확정이면점포근거도없음 |

구현 시 공식 원자료→DB→API의 대표15지점·혼합분기3지점·중첩7지점을 재대조하고 공개 실제 화면도 확인한다. 로컬/CI 검사와 실원천/공개배포 증거를 구분한다. 새 모델이 없어 Alembic migration은 만들지 않으며 0013과 원본 데이터를 보존한다.

## 10. 단계별 진행과 필요한 자료

1. 이 설계 MD를 실제 Claude Code가 검토하고 Codex가 보완·재검토 결과를 남긴다.
2. 다음 구현 범위는 BE 숫자 함수/DTO/버전고정 일괄 조회와 FE 대표값/근거/보고서다. 현재 턴은 설계까지다.
3. 기존 원천과 공개API를 재사용해 구현·테스트한다. DB/새 외부 API/LLM 비용은 추가하지 않는다.
4. CI 통과 뒤 BE를 먼저 반영하고, 새 필드의 실제 값/기존 GET·readiness를 확인한 뒤 FE를 정상 릴리스한다. 환경·schema 변경이 없으므로 실패 시 FE의 새 평균 사용을 되돌리고 이전 BE 커밋으로 복구할 수 있다. 누락/미출력에 총액이나0을 대신 표시하지 않는다.

**현재 구현 준비에 새 API 키나 사용자 자료는 필요하지 않다.** 고유 점포 중복을 제거한 실제 점포별 평균이나 브랜드/면적별 평균까지 원하면 추가로 같은 시점의 안정된 점포 ID·상권 귀속·매출 모집단/기간 정의·해당 점포별 매출/포함 범위 근거가 필요하다. 이는 이번 참고평균의 선행 차단조건이 아니다.

## 11. 공식 근거와 확인 범위

- [서울시 추정매출-상권 OA-15572](https://data.seoul.go.kr/dataList/OA-15572/F/1/datasetView.do): 원 단위 추정매출 자료. 2025년 파일 제공과2026-07-03 공간 단위 기준 변경 안내를2026-11-16 확인했다. 갱신주기 분기별은 원문 필드가 반드시 분기 누적액이라는 확인으로 사용하지 않는다.
- [서울시 점포-상권 OA-15577](https://data.seoul.go.kr/dataList/OA-15577/F/1/datasetView.do): 상권 점포·개폐업·프랜차이즈 자료, 전체 점포 수=일반+프랜차이즈 안내와2025년 파일을 같은 날 확인했다. 포털 메타의 년간 갱신 표기와 실제 파일의 기준년분기 키를 구분하며 조인은 보유 행의 분기 키로 한다.
- 내부 근거: `etl/market_sales/fields.py`, `etl/market_stores/archive.py`, 두 ORM 모델, `app/services/location_reference.py`, catalog, 기존 #186/#188/#190 설계와 FE `docs/location-reference.md`.
- 공통 상권 코드/분기/지문·도형의 일치가 기간 의미·점포별 매출 모집단·고유 점포 중복 제거를 보증하지 않는다는 판단은 위 자료와 현재 집계 구조에 근거한 **설계 판단**이다.

## 12. 실제 Claude Code 검토·Codex 최종 판단

아래 실제 MD Read/Edit 실행 결과와 보완·재검토를 기록한다. 코드 실행/원천 검증/배포를 했다고 기록하지 않는다.

### 12.1 review1 — Claude Code (2026-11-16)

**판정: REVISE (경미).** 수행 범위: 이 MD 1개의 Read와 이 절의 Edit만 했다. 코드/테스트/쿼리/Git/네트워크/DB 실행, 원천 검증, 다른 파일 열람은 하지 않았다. 코드 관련 판단은 요청에 함께 제공된 `market_sale.py`, `market_store.py`, `etl/market_stores/archive.py` 일부, `app/services/location_reference.py` 발췌만 근거로 한다. §2.1의 실증 수치는 Codex의 읽기 전용 확인 결과로 인용만 했고 재확인하지 않았다.

방향(행 단위 점포 수 가중 S/N, `total_stores` 분모, 같은 버전·분기·상권·업종 정확 연결, 중복 미제거 명시, 분기 간 합산·월 환산 금지, 기존 행 불변, 추가 필드만, DDL 없음)은 타당하며 그대로 유지한다. 아래 차단 항목은 범위를 늘리지 않는 **문서 내 규칙 결정**이며, 결정이 없으면 구현자마다 coverage 등식·상태·표시가 다르게 나와 §9 시험의 기대값을 확정할 수 없다.

#### 차단 이슈 (blocking)

**B1. 매출 쪽 매핑 충돌이 있는 `ready` 항목의 포함 여부와 사유 코드 충돌.**
현재 `_sales()`는 `conflict and eligible`이면 항목을 `status=ready`(eligible 행에서 선택)로 두면서 블록의 `excluded_count`/`excluded_counts["mapping_conflict"]`를 증가시킨다. 즉 "금액은 있으나 같은 키의 다른 분기 raw 행 일부가 명칭/유형 불일치"인 항목이 존재한다. 설계는 이 항목을 평균에 넣을지 정하지 않았고, §6.2 우선순위 ④`mapping_conflict`가 매출 측 충돌인지 점포 측 충돌인지도 불명확하다. 또 같은 이름 `mapping_conflict`가 기존 `sales.excluded_counts`(scope=`selected_market_industry_pairs`)와 새 `per_store_average.excluded_counts`에 서로 다른 scope로 나타나게 된다.
→ 결정 필요(권고안): ① 선택된 eligible 매출 행이 있고 그 행과 같은 키의 점포 행이 명칭·유형까지 일치하면 **포함**한다(기존 항목의 금액 선택을 그대로 존중). ② 점포 행이 선택 매출 행과 명칭/유형이 다르면 새 코드 `store_mapping_conflict`로 제외한다. ③ 새 객체에 `excluded_counts_scope`(대표=`listed_items`, 그룹=`group_numeric_items`)를 넣어 기존 meta의 scope와 구분한다. 점포 행 명칭 비교 대상은 Candidate가 아니라 **선택된 매출 행**임을 §3.3에 명시한다(매출 행은 이미 Candidate와 일치 검증됨).

**B2. `invalid_store_count`가 coverage 사유인지 fail-closed 오류인지 모순.**
§6.2는 `invalid_store_count`를 정상 제외 사유로 두지만 §7.6은 내부 정합 오류를 fail-closed로 처리한다. DB CHECK(`>=0`, `total = general + franchise`)와 `Integer` 타입 때문에 정상 경로에서는 발생할 수 없는 값이다.
→ 권고: `invalid_store_count`를 사유 목록에서 빼고 타입/음수/합계 불일치는 기존 `ValueError` → `INTERNAL_ERROR` 경로로 보낸다. 정상 사유는 `sales_unavailable / different_quarter / store_row_missing / store_mapping_conflict / zero_store_count_with_sales / zero_store_count`로 닫힌 열거형으로 확정한다. 항목 수준 `average_contribution`의 `other_quarter`도 `different_quarter`로 이름을 맞춘다.

**B3. 대표·그룹 `status` 판정식과 `analysis_period`의 primary_quarter 규칙 누락.**
- JSON 예시는 `ready`만 보이고 §5 표에 `partial`이 등장하지만 열거형과 판정식이 없다. latest_reference에서 대표 coverage는 전체 목록 기준이므로, 혼합 분기 지점(실증 15개 중 3개)에서는 다른 분기 항목이 `different_quarter`로 제외되어 **항상 partial**이 된다. 의도라면 명시하고, 아니라면 판정 기준을 그룹 coverage로 해야 한다.
  → 권고: `status ∈ {ready, partial, no_data}`; 대표는 `included == listed`면 ready, `0 < included < listed`면 partial, `included == 0`이면 no_data. 그룹도 같은 식을 `candidate_item_count`로 적용. FE의 "전체 N항목 중 M항목 반영" 문구와 일치한다.
- §4.1.5(숫자 매출이 없으면 primary_quarter=null)와 §4.2(T가 속한 분기만 사용)가 analysis_period에서 충돌한다.
  → 권고: analysis_period에서는 숫자 매출 유무와 무관하게 `primary_quarter = desired`(T의 분기)로 고정하고 groups는 그 1개 이하. latest_reference에서 숫자 매출이 없을 때만 `primary_quarter=null`, `temporal_relation=null`, `period_end_after_analysis=null`(기존 항목처럼 False로 채우지 않음)로 둔다.

**B4. 1원 미만 표시와 HALF_UP 규칙의 충돌, `value` 문자열 형식 미정.**
§5.1은 `0<S<N`이면 "1원 미만/점포"라고 하지만 HALF_UP으로는 0.5≤S/N<1이 "1원/점포"가 된다. 또 Decimal 결과는 `normalize()`/`str()`에 따라 `2.5E+5` 같은 지수 표기가 나올 수 있어 FE·스냅샷 토큰·validator가 흔들린다.
→ 권고: ① `S>0 and S<N`(quotient==0)이면 반올림과 무관하게 display는 "1원 미만/점포", `rounded=true`. ② 그 외는 정수 divmod HALF_UP. ③ `value`는 `decimal.localcontext(prec=50)` 안에서 계산하고 `format(v, 'f')`로 **지수 없는 고정소수점**, 불필요한 후행0 제거 규칙을 고정한다(정수면 소수점 없음). ④ schema validator는 `numerator/denominator` 정수 비율과 `value`·`display`·`rounded`·`exact_zero`의 일관성을 검사한다. 전역 Decimal context를 바꾸지 않는다.

#### 비차단 메모 (nonblocking)

1. **구버전/신버전 판별**: "필드 부재 = 구 BE, 명시적 no_data = 신 BE"가 성립하려면 신 BE는 sales 블록이 있을 때 `per_store_average`를 **항상 객체로** 보내야 한다(소스 미적재/버전 모호 시에도 `status`와 `reason`을 기존 블록에서 복사한 객체). Pydantic 기본값 `None`이 직렬화되어 `null`로 나가면 FE가 구분할 수 없으므로, `null` 금지 또는 `exclude`/`exclude_unset` 정책을 schema에 명시할 것.
2. **no_data에서의 "0"/"0" 합계**: FE가 `total_sales="0"`을 "0원"으로 렌더링할 위험이 있다. `metric=null`이면 합계 문자열도 `null`로 두는 편이 안전하다. 유지한다면 FE 규칙에 "metric null이면 합계 미표시"를 명시한다.
3. **중복 데이터원**: 대표 `included_item_keys`·그룹 `included_item_keys`·항목 `average_contribution`이 같은 사실을 세 번 표현한다. 최대 500키 × 2 페이로드이며 불일치 위험이 있다. 대표 객체에서는 `included_item_keys`를 생략하고 primary 그룹을 참조하도록 줄이거나, 유지한다면 validator로 세 표현의 일치를 강제한다.
4. **SQL**: `(version_id, market_code, quarter, induty_cd)`가 PK라 중복 행은 구조적으로 불가능하다. "501행 탐지"는 무해하나 중복 탐지 의미는 없다. 기존 `_sales()` 패턴처럼 `version_id = 고정 store version` + `market_code IN` + `induty_cd IN` + `quarter IN(선택된 분기들)`로 1회 조회 후 Python 사전에서 정확 키 매칭하는 방식이 `tuple_ IN` 보다 단순하고 `ix_market_stores_version_quarter_induty`/PK를 그대로 탄다. 어느 쪽이든 1회 조회면 충분하다.
5. **버전 전달**: 현재 `_sales()`는 `sale, boundary, _ = resolved`로 점포 버전을 버린다. 구현 시 이 `MV`를 그대로 사용하고 `sale.code_check_store_version_id == store.version_id`(이미 `_versions()`가 검증)를 재사용한다. 별도 최신 버전 조회 금지는 문서와 일치한다.
6. **합계 상한**: `est_sales ≤ 2^63−1`, 항목 ≤ 500이므로 S < 2^72, N ≤ 500 × (2^31−1). Python int로 안전하다. "집계 상한" 검증은 `S ≤ 500 × (2^63−1)` 같은 명시 상수로 적으면 충분하다.
7. **항목 단위 `store_reference`**: `total_stores=0`인 행은 `status=ready`(값 "0")인지 `no_data`인지 정한다. 권고는 ready + `per_store_metric=null` + `average_contribution=excluded(zero_store_count…)`.
8. **출처**: `store-counts` source_ref에 `MarketStoreVersion.rule_version`·`content_sha256`·`input_sha256`·`source_year`와 분모 원천 필드명 `similr_induty_stor_co`를 넣으면 provenance가 sales 근거와 대칭이 된다. `boundary_as_of`는 점포 버전에 없으므로 경계 근거를 재사용한다.
9. **meta**: `items_additive=false`는 그대로 둔다. 새 지표의 성격은 객체 내부 `aggregation_basis`·`deduplication=not_performed`·`unique_store_average=false`로 충분하며 meta에 별도 플래그를 추가할 필요는 없다. 화면 문구 "점포 수 합계"를 "반경 내 점포 수"로 부르지 않는 §8 규칙은 좋다.
10. **스냅샷 토큰**: 새 필드가 data에 들어가므로 같은 조건에서도 배포 전후 토큰이 바뀐다. FE/PDF가 토큰을 캐시 일치 판단에 쓰는 경우 배포 시점에 한 번 무효화됨을 릴리스 노트에 적는다.
11. **단위 문구**: 원천 필드명이 `당월_매출_금액`이지만 `amount_period_status=unverified`이므로 표시 단위에 "월"/"분기"를 붙이지 않는 현재 `원/점포` 표기를 유지한다.

#### 시험 보강 (§9에 추가)

- 매출 측 충돌이 있는 ready 항목(B1) 포함/제외 기대값, 점포 행 명칭만 다른 경우 `store_mapping_conflict`.
- latest_reference 혼합 분기 → 대표 `partial`, 그룹 각각 `ready` (B3).
- analysis_period에서 숫자 매출 0건 → `primary_quarter=desired`, `no_data`.
- S/N = 0.6, 0.4, 0.5 → 모두 "1원 미만/점포"; S/N = 1.5 → "2원/점포"(HALF_UP); `value`에 지수 표기 없음 (B4).
- 구 BE 응답(키 없음) vs 신 BE의 소스 미적재 응답(객체+status) FE 분기.
- 세 표현(대표 키·그룹 키·항목 contribution) 불일치 시 validator 거부.
- 대표 `excluded_counts`와 기존 `sales.excluded_counts`의 scope가 섞이지 않음.

#### 결론

B1~B4는 모두 이 MD 안에서 규칙을 확정하면 해소되며, 새 API 키·DDL·고유 점포 ID·원천 승인 절차를 요구하지 않는다. 반영 후 PASS 가능하다. 참고평균 표시 자체를 막을 이유는 없다.

### 12.2 Codex 보완 (2026-11-16)

- B1: 기존에 선택된 eligible 매출 행을 존중해 과거 다른raw충돌만으로제외하지않는다. 점포측충돌은store_mapping_conflict로분리하고대표/그룹/기존sales의coverage scope를구분했다.
- B2: invalid_store_count를정상제외사유에서제거했다. 타입/음수/합계불일치는fail-closed이며, 관측된N=0은원자료로보존하고평균만제외한다.
- B3: 대표/그룹상태를포함수비교식으로확정했다. 혼합분기대표partial/그룹ready를허용하고analysis_period는desired분기를보존한다. source상태전파와latest무자료시null시점을명시했다.
- B4: 1원미만display특례를HALF_UP보다먼저적용하고Decimal50고정소수점/후행0처리·분수원형·전역context미변경을정했다.
- 비차단보완: 신BE항상객체/미산정합계null,대표포함키중복제거/그룹단일근거·교차validator,정확집계상한,검증된MV전달,점포근거필드와snapshot token변경을명시했다. 501행은상한검사로한정했다.
- 1차 실제실행은13:15:26Z~13:17:22Z/exit0/is_error=false/3turns/MD변경true/permission_denials빈배열이다. 이번 보완도 문서만 변경했다. 수용시험은 향후 구현 시 실행할 계획이며 현재 통과로 기록하지 않는다.

### 12.3 review2 — Claude Code 최종 재검토 (2026-11-16)

**판정: PASS (구현 착수 가능, 차단 이슈 없음).** 수행 범위: 이 MD 1개를 Read하고 이 절을 Edit로 추가한 것뿐이다. 코드/테스트/쿼리/Git/네트워크/DB/에이전트 실행, 원천 검증, 다른 파일 열람은 하지 않았다. 코드 관련 판단은 요청에 함께 제공된 `market_sale.py`, `market_store.py`, `etl/market_stores/archive.py` 일부, `app/services/location_reference.py` 발췌만 근거로 한다. §2.1 수치와 §12.2의 실행 기록은 Codex가 남긴 기록을 인용한 것이고 내가 재확인하지 않았다. 이 PASS는 설계 문서의 내부 일관성과 구현 가능성에 대한 판정이다. 구현·시험 통과·배포·원천 의미 검증 완료를 뜻하지 않는다.

#### review1 차단 항목 반영 확인

| 항목 | 본문 반영 위치 | 판단 |
| --- | --- | --- |
| B1 선택된 eligible 행 존중·`store_mapping_conflict`·scope 분리 | §3.3, §5 표, §6.2 coverage/scope 문단, §9 | 해소. 비교 대상이 Candidate가 아니라 선택된 매출 행으로 고정됐고, 기존 `sales.excluded_counts`(selected_market_industry_pairs)와 새 `listed_items`/`group_numeric_items`가 분리됐다. |
| B2 비정상 점포 수 fail-closed·관측0 보존 | §5 표, §6.1, §6.2 사유 열거형, §7.6 | 해소. 정상 사유가 6개(①~⑤)로 닫혔고 `invalid_store_count`는 없다. 관측된 N=0은 `store_reference.status=ready`/"0"으로 남는다. `other_quarter`가 `different_quarter`로 통일됐다. |
| B3 상태 판정식·상위 상태 전파·analysis_period desired·latest 무자료 null | §4.2, §4.3, §9 | 해소. 현재 `_sales()`에서 sales `no_data`면 숫자 항목이 0개이고 `partial/ready`면 1개 이상이므로, "전파 조건"과 "계산 경로"가 겹치거나 비는 경우가 없다. |
| B4 1원 미만 우선·정수 divmod HALF_UP·Decimal50 고정소수점 | §5.1, §9 | 해소. `rounded=remainder!=0`이 0<S<N에서 자동으로 true가 되어 B4 권고와 일치한다. S<2^72(최대 22자리)이고 prec=50이라 정수부 지수 표기는 생기지 않으며, `format(...,'f')` + 소수점이 있을 때만 후행0 제거 규칙으로 `250000` 같은 정수는 보존된다. |
| 비차단(합계null·항상 객체·대표키 제거·MV 재사용·출처·상한·token) | §6.2 말미, §6.2 예시 아래 문단, §7.3, §6.3, §5.1, §6.3 말미 | 반영 확인. |

독립 점검에서 다음도 서로 모순되지 않음을 확인했다: 예시 T=2023-11-30 / 20254 → `later_reference`, `period_end_after_analysis=true`; 대표=primary 그룹 투영과 coverage 등식이 혼합 분기에서 "대표 partial·그룹 ready"를 만드는 것; 그룹 우선순위에서 ①②를 빼는 것(그룹 후보가 해당 분기 숫자 항목뿐이므로 ①②가 원래 생길 수 없음); analysis_period에서는 SQL이 `S.quarter == desired`로 거르므로 `different_quarter`가 생기지 않는다는 것; 합계 상한(N은 int32 열 × 최대 500)이 Python int로 안전하다는 것.

#### 차단 이슈 (blocking)

없음. 아래 항목은 기존 규칙에서 기대값을 유도할 수 있거나 구현 중 한 줄로 확정할 수 있는 수준이라, 참고평균 표시나 구현 착수를 막지 않는다.

#### 비차단 메모 (nonblocking) — 구현 PR에서 확정 권장

1. **전파 경로의 coverage 수치 명시.** §4.3 전파 시 합계/metric/groups만 정해져 있다. 일반 분할 규칙(§6.2)에서 유도하면 `listed_item_count=len(items)`, `included_item_count=0`, `included_market_count=0`, `excluded_counts={"sales_unavailable": len(items)}`(항목 0개인 `_empty` 블록은 `0`/`{}`), 각 항목 `average_contribution=excluded/sales_unavailable`이다. validator와 §9 "analysis_period 숫자0건" 기대값이 같은 값을 쓰도록 본문에 한 줄 적어 두면 좋다. 이때 `reason`은 §4.3대로 sales 사유 복사(`no_data_in_analysis_period`, `mixed_unavailable_reasons` 등)이며 `no_valid_sales_store_pairs`가 아니다.
2. **`store_reference`의 미정 칸 두 곳.** (a) `store_mapping_conflict` 항목: 충돌한 점포 행의 수치를 노출할지 정해지지 않았다. 권고는 `status=no_data`, `reason=store_mapping_conflict`, 수치 null이다(충돌 행의 점포 수가 화면 합계 재계산 §4.4에 섞이는 것을 막음). (b) 매출 null 항목: 점포 조회 키에 넣을지 정해지지 않았다. 권고는 숫자 매출 항목의 키만 조회하고 매출 null 항목은 `store_reference=null`이다(조회 키 ≤ 숫자 항목 수 ≤ 500 유지).
3. **이전 분기 항목의 그룹 내 제외 사유.** 항목 `average_contribution`은 대표 기준(`different_quarter`)만 담는다. 이전 분기 항목이 자기 그룹에서 `store_row_missing` 등으로 빠졌을 때, FE는 "그룹 included_item_keys에 없음"으로 제외 여부는 알 수 있지만 사유는 그룹 `excluded_counts` 합계로만 안다. §4.4의 "평균 계산 제외" 표시를 항목별 사유까지 보여 주려면 optional `group_contribution`(같은 열거형)을 추가하고, 그렇지 않으면 이전 분기는 그룹 단위 사유만 보인다고 FE 문서에 적는다. 어느 쪽이든 대표값의 정직성에는 영향이 없다.
4. **기존 sales `partial`과 새 평균 `ready`의 동시 표시.** 과거 raw 충돌만 있는 지점은 sales 블록 `partial/partial_source_rows`이면서 대표평균 `ready`일 수 있다(의도된 결과, §4.3). FE 문구가 "일부 누락"과 "전체 반영"을 같은 줄에서 말하지 않도록 raw 목록 주석과 평균 coverage 문구를 분리한다.
5. **`per_store_average` 생성 위치.** 신 BE는 항상 객체를 반환해야 하지만 현재 `_empty()`는 `_versions()` 내부처럼 target/time_mode가 없는 곳에서도 호출된다. analysis_period의 `primary_quarter=desired`를 채우려면 `_sales()` 반환 직후 query/target을 아는 단일 후처리 함수에서 객체를 만들고, `SalesBlock` schema는 신 BE 경로에서 필드 누락/None을 validator로 거부하는 방식이 단순하다. `store-counts` source_ref도 `_versions()`가 성공해 MV가 확정된 경우에만 추가한다(현재 sales 근거가 `_versions()` 실패 시 빈 배열인 것과 대칭).
6. **SQL 선택.** §7.4의 tuple IN과 독립 IN 대안 중 하나를 구현 PR에서 고정한다. 둘 다 고정 `version_id` 1회 조회, PK/`ix_market_stores_version_quarter_induty` 사용으로 충분하다. 독립 IN을 고르면 교차곱으로 더 읽힌 행은 Python에서 정확 키 매칭으로 버리고, 상한은 `시장 수 × 업종 수 × 분기 수`로 계산한다.
7. **value validator 비교 방식.** validator는 같은 localcontext로 S/N을 다시 계산해 문자열을 정확히 비교한다(float 비교 금지). §9 "0.5원 근처의 큰 정수 비율" 시험은 display가 정수 divmod로만 정해지는지 확인하는 시험으로 두면 된다.
8. **문구.** §4.3 첫 문단 "latest_reference는null"은 "latest_reference의 primary_quarter·시간 필드는 null"로 쓰면 오독이 줄어든다.

#### 시험 보강 (선택)

- 전파 경로(항목 있음·숫자 0건 / `_empty` 블록)의 coverage 등식과 항목 contribution.
- `store_mapping_conflict` 항목의 `store_reference` 수치가 화면 합계 재계산에 섞이지 않음.
- `_versions()` 실패 시 `store-counts` source_ref가 없고 per_store_average는 객체(sales 상태/사유 복사).

#### 결론

review1의 B1~B4와 비차단 보완은 본문에 일관되게 반영됐고, 독립 재검토에서도 상태·coverage·기간 선택·정밀도·호환성 규칙 사이에 모순은 찾지 못했다. 위 비차단 1~8은 새 API 키·DDL·고유 점포 ID·원천 승인 절차를 요구하지 않으며 구현 PR에서 확정하면 된다. 이 지표는 "상권 자료행 점포 수 가중 참고평균(중복 미제거, `unique_store_average=false`)"으로 표시하는 범위에서 구현에 착수할 수 있다. 구현·수용시험·배포는 아직 수행되지 않았다.

### 12.4 Codex 최종 판단·완료 범위

최종 설계 채택. 사용자가 요청한 합산/점포 수 나눗셈을 기존 실제 공간후보목록에 적용하는 경로이며, 상권 수로 나누거나 다른 지역을 찾는 방식으로 바꾸지 않는다. 다른 분기·중복 가능성·부분자료를 구분하면서 보유자료로 구현할 수 있다.

재검토의 비차단1~8도 문서에서 결정했다: 전파coverage/사유복사,점포충돌수치null/매출없는키조회제외,이전분기사유는그룹단위,raw와평균상태문구분리,query/target을아는단일후처리와최종응답validator,tupleIN고정,동일context문자열검증,latest null필드문구정리다. 새 요구나 보류조건을 추가한 것은 아니다.

2차 실제실행13:19:44Z~13:21:44Z/exit0/is_error=false/3turns/MD변경true/permission_denials빈배열이며설계PASS다. 완료 범위는현재시스템비교·로컬READONLY대조·설계MD·실제검수2회·보완/최종점검이다. 이번문서의JSON은합성예시이며문서검사와후속구현수용시험을구분한다. 앱/FE/ETL/DB/migration/.env/서버/배포는변경하지않았다.
