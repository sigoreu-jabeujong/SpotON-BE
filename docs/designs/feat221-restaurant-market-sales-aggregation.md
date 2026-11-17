# 음식점 선택 업종의 상권별 매출 합산 및 상위 3곳 표시 설계

- 이슈: [BE #221](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/221)
- 작성일: 2026-11-17
- 작성: Codex / 검토: 실제 Claude Code CLI Read·Edit 후 Codex 재검토
- 단계: 설계 완료 / Claude Code 3차 PASS / Codex 최종 재검토 완료. 기능 구현·앱 배포·DB 변경은 이번 작업에 포함하지 않는다.
- 비교 기준: BE `f9e017202373a7d2c591e7063787a0cd0b2ef328`, FE develop `9fe7a86a46417828038f24adda4f1ced31678a95`.
- 선행 설계: [상위 3개 상권 추정매출](feat219-top3-sales.md).

## 1. 사용자 요구와 이번 결정

카페는 현재의 계산·화면을 유지한다. 음식점은 사용자가 세부 설정에서 선택한 한식·중식·일식·양식의 자료를 **먼저 상권별로 합산**한다. 같은 상권이 업종 수만큼 반복 표시되지 않게 한다.

처리 순서는 다음과 같다.

1. 선택한 음식점 업종과 검색 위치 포함/반경 교차 조건으로 원자료를 조회한다.
2. 같은 기준 분기의 유효한 매출·점포 수 쌍을 상권별로 합산한다.
3. 합산 점포 수가 많은 **서로 다른 상권 최대 3곳**을 선정한다.
4. 대표 점포당 추정매출은 선정한 상권들의 **매출 합계 ÷ 점포 수 합계**로 표시한다.
5. 음식점 기본 목록에는 선정된 상권을 한 장씩, 최대 3장 표시한다. 나머지 상권은 별도 펼침 영역에서 확인한다.

따라서 한식·중식·일식·양식을 모두 선택했다면 ‘망리단길 한식’, ‘망리단길 중식’이 아니라 **‘망리단길’ 한 장에 선택 업종 합산 결과**를 표시한다. 한식·중식만 선택했으면 두 업종만 더한다. 먼저 업종별 상위 행 3개를 고르거나, 기존 3곳을 고정한 채 업종만 바꾸지 않는다.

대표값은 개별 점포의 관측 매출이나 중앙값이 아니다. 상권별 평균의 단순평균·정규분포 모델도 사용하지 않는다.

## 2. 현재 시스템과 실제 차이

| 구간 | 현재 코드에서 확인한 동작 | 필요한 변경 |
| --- | --- | --- |
| 세부 설정 전달 | FE `useDiagnosisQuery.ts`의 `subCategories`와 API `sub_category`로 선택 업종 전달. `populationParams()`가 정렬하고 `client.ts`가 쉼표 문자열로 직렬화 | 전달 경로·취소·캐시 키 보존. 전체/일부 선택에 대한 연결 검증 추가 |
| BE 업종 필터 | `CategoryFilters`가 카테고리별 허용 업종과 중복을 검증. 중복 업종은 422. `_sales()`는 선택 업종만 조회하며 음식점 선택이 생략되면 4종 전체 사용 | 새로운 업종 필터/API를 만들 필요 없음 |
| 원자료 목록 | `sales.items`는 상권×선택 업종별 `SalesItem`. 업종별 최신 숫자 자료의 분기가 서로 다를 수 있음 | 원자료 목록은 호환·감사용으로 유지 |
| 점포 수 연결 | `per_store_sales.attach()`가 같은 상권·분기·업종의 매출과 점포 수를 연결하고 결측/충돌/0분모 제외 | 기존 판정 재사용 |
| 대표 추정매출 | `top_markets_sales.top_markets_estimate()`가 **이미 유효 업종을 상권별 합산한 뒤** 점포 수 상위 3곳을 선정 | 산식을 새로 만들지 않고 공통 상권 집계 결과를 공유하도록 정리 |
| 상권별 목록 | FE `LocationReferenceView.tsx`가 여전히 `data.sales.items.map()`으로 업종별 카드를 반복 표시 | 음식점은 BE의 상권별 합산 목록으로 렌더링 |
| 출처·대표값 | 현재 상위 3곳의 금액과 실제 상권명을 표시 | 같은 선정 집합과 합산 목록이 일치하도록 검증 |

**현재 음식점 대표값 자체가 업종 행 3개를 잘못 골라 계산하는 상태는 아니다.** 부족한 부분은 전체 상권 합산 결과의 API 계약과 기본 목록의 상권 단위 표시다. 기존 대표값과 별개의 두 번째 합산 엔진을 만들면 서로 다른 값이 표시될 수 있으므로 피한다.

## 3. 선택 업종과 요청 계약

| FE 선택 | API 값 | 공식 자료 업종 코드 |
| --- | --- | --- |
| 한식 | `korean` | `CS100001` |
| 중식 | `chinese` | `CS100002` |
| 일식 | `japanese` | `CS100003` |
| 양식 | `western` | `CS100004` |
| 카페 | `cafe` | `CS100010` |

- 음식점 `sub_category` 생략 또는 FE의 빈 선택 배열은 현재처럼 4종 전체를 의미한다. 실제 빈 문자열을 직접 전달하는 것까지 허용하는 변경은 하지 않는다.
- `sub_category=korean,chinese`이면 두 업종만 요청한다. 다른 업종·카페 자료는 합산하지 않는다.
- 중복 업종·카테고리에 맞지 않는 업종·반복된 동일 쿼리 키는 기존 422 정책을 유지한다.
- 응답에는 요청에서 실제로 적용한 업종 목록을 명시한다. 생략 요청도 응답에서는 4종 전체가 드러나야 한다.
- 신규 집계 안의 업종 배열은 업종 코드순(한식→중식→일식→양식)으로 고정한다. 같은 집합이면 신규 집계 결과와 기존 대표값·순위가 같아야 한다. 기존 `sales.items`와 `meta.requested_scope.sub_category`의 요청 순서 표현, FE의 알파벳순 캐시 키는 변경하지 않는다. 응답 전체의 바이트 동일성까지 요구하는 규칙은 아니다.
- 브랜드·면적·층 등의 점포 필터로 이 공공 매출·점포 수를 재분류하지 않는다. 기존 참고자료 범위를 유지한다.

## 4. 집계·분기·순위 규칙

### 4.1 동일 분기와 집계 키

계산 분기는 기존 `per_store_average.primary_quarter`를 단일 기준으로 사용한다. `analysis_period`는 분석 기준일의 분기, `latest_reference`는 현재 로직이 선택한 최신 숫자 자료들의 최대 분기다.

집계 키는 `(market_code, primary_quarter)`다. 상권명이 같다고 다른 코드를 합치지 않는다. 하나의 요청에서 같은 경계/원천 버전을 사용하며, 상권명·상권 유형·공간 관계는 검증된 경계 정보를 따른다.

업종마다 최신 자료 분기가 다르더라도 서로 다른 분기의 금액을 합산하지 않는다. 예를 들어 한식 2025년 4분기, 중식 2025년 3분기라면 기준 분기가 2025년 4분기일 때 중식은 `different_quarter`로 기록한다. 과거 분기로 이동하거나 다른 지역 자료로 메우지 않는다.

### 4.2 유효한 매출·점포 수 쌍

기존 원자료/점포 수 검증을 먼저 통과한 행만 합산한다.

- 같은 상권·분기·업종의 매출 숫자와 **양수 점포 수**가 함께 있어야 한다.
- 매출 0원 + 양수 점포 수는 유효한 0원으로 포함한다.
- 매출 없음·점포 수 없음·점포 수 0·자료 매핑 충돌은 분자와 분모에서 함께 제외한다. `0원/0개`도 기존 정책에 따라 제외하며, 확인된 공백을 임의로 0으로 채우지 않는다.
- 같은 상권코드에서 **유효 행끼리** 명칭이 충돌하면 상권 전체를 제외한다. 매핑 불일치로 먼저 제외된 행은 남은 유효 행의 이름 충돌 검사에 넣지 않는 현재 정책을 유지한다.
- 중복 `(상권, 분기, 업종)`은 입력 결함으로 거부한다. 두 번 더하거나 임의의 행을 고르지 않는다.

현재 `_sales()`는 `SalesItem.market_name`을 경계의 `area.name`으로 채운다. 따라서 정상 API에서 같은 코드의 유효 행끼리 이름이 충돌하는 경로는 없으며, 위 명칭 충돌 규칙은 공통 함수의 방어 정책이다. 이 경우는 합성 입력/DTO 위조로 검증하고 실제 PostGIS 원자료 fixture에서 억지로 재현하지 않는다.

### 4.3 상권 합계와 대표값

상권 m의 유효 선택 업종 집합을 Jm이라 하면 다음을 계산한다.

```text
상권 매출 Sm = Σ(업종별 원자료 매출)
상권 점포 수 Nm = Σ(같은 유효 행의 점포 수)
상권 점포당 값 = Sm / Nm  (Nm > 0일 때)

순위 = Nm 내림차순, 동률은 market_code 오름차순
선정 집합 T = 이 순서의 서로 다른 상권 최대 3곳
대표 점포당 추정매출 = Σ(Sm, m∈T) / Σ(Nm, m∈T)
```

선택 업종 변경 시 **모든 후보 상권의 합계부터 다시 산정하고 재선정**한다. 매출 총액이나 점포당 금액으로 순위를 매기지 않는다. 상권 간 중복 점포를 제거하지 않으며, 서로 다른 업종 코드 간 공식 점포 수의 합을 사용한다.

금액·점포 수는 정수/정확한 십진 문자열로 처리하고 마지막 표시에서만 반올림한다. 원자료 행 합계는 단일 원자료 정수 상한보다 커질 수 있으므로 합계 필드에 단일 행 `int64` 상한을 적용하지 않는다. 기존 최대 500행 합산 범위와 `metric()`의 Decimal50·정확한 분자/분모를 재사용한다.

## 5. 선택 업종 중 자료가 빠진 경우

사용자가 가진 자료를 우선 볼 수 있게 하려는 기존 방향을 따라 **유효한 업종의 부분합도 공개**한다. 일부 업종이 빠졌다는 이유로 해당 상권 전체를 숨기지는 않는다. 다만 ‘선택 업종 전체 합계’로 표시해서는 안 된다.

| 상태 | 조건 | 표시·선정 |
| --- | --- | --- |
| `ready` | 선택 업종 모두 유효 쌍 | 합계 표시, 선정 가능 |
| `partial` | 일부 업종만 유효 쌍이며 합산 점포 수 양수 | 부분합 표시, 선정 가능. `선택 4종 중 3종 합산`과 빠진 업종/사유 제공 |
| `no_data` | 유효 쌍 없음 또는 상권 전체 명칭 충돌 | 금액·점포 수 합계·점포당 값 null, 선정 불가 |

부분 상권은 **관측된 유효 업종의 점포 수 합계**로 순위를 매긴다. 누락 업종의 점포 수를 외삽하지 않는다. 따라서 자료 완전성에 따라 순위가 달라질 수 있다는 점을 계산 상세에서 설명한다.

선정 가능한 상권이 1~2곳이면 해당 자료만 사용하고 부족 안내를 표시한다. 0곳이면 대표값 없음이다. 전체 미적재·범위 초과·공간 교차 없음 등은 기존 `sales.status/reason`을 보존하고 원인에 맞게 표시한다.

## 6. BE 응답 확장안

기존 GET `/api/v2/location-reference`에 선택 필드 `sales.market_aggregation`을 추가한다. 신규 endpoint, API키, DB 테이블·migration·원자료 적재는 필요 없다. 아래는 구현할 계약이며 현재 배포에 존재하는 필드가 아니다. 신규 서버는 카페에는 null, 음식점에는 `_empty()` 경로를 포함해 **항상 객체**를 반환한다. 필드 자체의 미존재는 이전 서버 호환 상황이다.

| 필드 | 의미 |
| --- | --- |
| `rule_version` | `restaurant_market_rollup_v1` |
| `category` | `restaurant` |
| `source_quarter` | `per_store_average.primary_quarter`와 null 포함 정확히 동일 |
| `requested_industries` | `{industry_code, industry_name}` 목록. `INDUSTRIES`의 공식 원자료 라벨(예: 한식음식점)을 사용하고 DTO에서 코드와 이름의 쌍 검증. 생략 요청은 4종 전체 |
| `status`, `reason` | 아래 6.2의 순서로 결정하는 전체 집계 상태·원인 |
| `eligible_market_count` | 합산 점포 수 양수이고 선정 가능한 상권 수 |
| `selected_market_codes` | 순위순 선정 코드, 최대 3개. 기존 `top_markets_estimate.markets`와 동일 |
| `items` | 검색된 상권마다 1개인 합산 항목. 하단 상세용 자료 없음 상권도 포함 |

`items` 각 항목은 아래 필드를 가진다.

| 필드 | 의미 |
| --- | --- |
| `market_code`, `market_name`, `market_type` | 검증된 상권 식별·이름·유형. 이름은 str 또는 null이며 아래 명칭 충돌 조건에만 null 허용 |
| `spatial_relation` | contains_point/intersects_radius. 면적 비례 배분 없음 |
| `source_quarter`, `temporal_relation` | 자료 없음 항목도 상위 집계의 기준 분기를 따름. 기준 분기가 null이면 둘 다 null |
| `status`, `reason` | ready/partial/no_data와 해당 원인 |
| `included_industry_codes` | 실제 합산한 업종 코드, 정규 순서 |
| `unavailable_industries` | 선택했지만 합산하지 못한 업종의 코드·사유·실제 자료 분기(null 가능) |
| `included_item_keys` | 합산에 사용한 `{market_code, industry_code, source_quarter}` 객체 목록. included_industry_codes와 같은 정규 업종 순서 |
| `total_sales` | 유효 행 매출 합계 문자열. 유효 쌍 없음은 null |
| `total_store_count` | 같은 행의 점포 수 합계 문자열. 유효 쌍 없음은 null |
| `per_store_metric` | 기존 `metric(Sm, Nm)` 형식. 계산 불가 시 null |
| `rank` | 선정 가능 상권 내 순위 1..K. 선정 불가는 null |
| `selected_for_estimate` | rank≤3인 선정 상권만 true |

계약의 세부 조건은 다음과 같다.

1. 기존 `sales.items`, `sales.per_store_average`, `sales.top_markets_estimate`는 유지한다. 원자료 업종별 리스트를 의미가 다른 합산 리스트로 덮어쓰지 않는다.
2. 카페는 반드시 `market_aggregation=null`이며 기존 숫자·대표값·화면을 유지한다. 새 optional 필드에 따른 직렬화 변화와 계산값 보존은 구분한다.
3. `items`는 선정 가능 상권을 rank순으로 먼저 제공하고, 선정 불가 상권은 코드순으로 뒤에 둔다. 상권 코드 집합은 `sales.items`의 상권 코드 집합과 **정확히 동일**하다. 후보의 조용한 생략을 허용하지 않는다. 상위 원자료 목록이 비어 있으면 집계 목록도 비어 있다.
4. 상권 명칭 충돌 방어 경로에서는 included 목록을 비우고 모든 선택 업종에 `market_name_conflict`를 기록한다. 이때만 `market_name=null`을 허용하고 FE 상세에는 `자료 정보 불일치 (상권 코드)`로 표시한다. 정상·선정 상권 이름은 반드시 비어 있지 않은 문자열이다. 같은 코드의 market_type/spatial_relation 불일치는 정상 집계 대상이 아닌 입력 결함으로 거부한다. 이름 충돌만 상권 제외로 처리해 기존 선정 정책과 일치시킨다.
5. `included_industry_codes`와 `unavailable_industries`는 요청 업종의 정확한 분할이다. 합산하지 않은 업종은 0원 처리하지 않는다.
6. 구조화된 strict/frozen Pydantic 모델을 정의한다. `dict[str, Any]`만으로 필드를 추가하지 않는다. `requested_industries`의 코드는 중복 없이 정규 순서여야 한다.

### 6.1 신규 사유 타입과 우선순위

기존 `Reason` Literal은 수정하지 않는다. 신규 strict DTO의 각 필드에는 다음처럼 범위를 좁힌 사유 타입을 사용한다.

| 타입·사용 필드 | 허용 값 |
| --- | --- |
| `AggregationReason` / 전체 reason | 기존 `Reason` 전체와 `no_valid_sales_store_pairs`, `fewer_than_three_markets`, 또는 null. 실제 status별 조합은 6.2 표대로 검증 |
| `MarketItemReason` / 상권 항목 reason | `partial_selected_industries`, `market_name_conflict`, `no_valid_sales_store_pairs`, 또는 null |
| `UnavailableIndustryReason` / 업종 제외 reason | `mapping_conflict`, `source_value_null`, `no_source_rows`, `no_data_in_analysis_period`, `different_quarter`, `store_row_missing`, `store_mapping_conflict`, `zero_store_count`, `zero_store_count_with_sales`, `market_name_conflict` |

기존 `average_contribution`의 `sales_unavailable`은 그 계약에서만 유지한다. 신규 업종 사유에는 더 구체적인 `SalesItem.reason`을 사용하므로 `sales_unavailable`을 새 필드의 허용 값에 넣지 않는다.

`unavailable_industries[].reason`은 null 불가이며 다음 순서로 하나를 결정한다.

1. 유효 행 명칭 충돌로 상권 전체 제외: 모든 요청 업종에 `market_name_conflict`.
2. 매출 숫자 없음: `SalesItem.reason`을 그대로 사용. 사유 자체가 없다면 입력 결함으로 거부하며 임의 사유를 만들지 않는다.
3. 매출은 있으나 기준 분기와 다름: `different_quarter`. 원래 분기는 별도 `source_quarter`에 보존한다.
4. 기준 분기 매출은 있으나 점포 수 연결 불가: 기존 행 연결에서 나온 `store_row_missing`/`store_mapping_conflict`/`zero_store_count`/`zero_store_count_with_sales`를 사용한다.
5. 그 외 유효 쌍은 `included_industry_codes`에만 넣는다. 제외 사유가 있는 행을 동시에 포함하지 않는다.

상권 항목의 reason은 `ready→null`, `partial→partial_selected_industries`, `no_data→market_name_conflict`(그 방어 조건일 때) 또는 `no_valid_sales_store_pairs`다. 구체적인 업종별 원인은 `unavailable_industries`에서 보존하며 허용 목록 밖 문자열은 거부한다.

### 6.2 전체 집계 status/reason 결정표

위에서부터 먼저 해당하는 규칙 하나를 적용한다.

| 순서 | 조건 | 전체 status / reason |
| --- | --- | --- |
| 1 | `sales.items`가 비어 있고 상위 상태가 no_data/pending/not_supported | 상위 `sales.status/reason` 그대로 |
| 2 | 그 외 선정 가능한 상권이 0곳 | no_data / no_valid_sales_store_pairs |
| 3 | 일부 상권이 partial 또는 no_data | partial / partial_source_rows |
| 4 | 상권들이 모두 ready지만 선정 가능 상권이 1~2곳 | partial / fewer_than_three_markets |
| 5 | 나머지 | ready / null |

이 전체 상태는 후보 상권 전체의 완전성을 표현한다. 대표값 카드의 부분합 안내는 **선정된 상권**만으로 판단한다. 선정 외 상권 하나가 불완전하다는 이유로 선정된 3곳도 부분합이라고 표시하지 않는다.

기존 `top_markets_estimate.status/reason`은 호환 보존한다. 기존 계약은 금액이 있는 기준 분기 행만 후보로 보기 때문에 새로운 전체 집계의 status와 다를 수 있다. 두 계약의 **선정 코드·순서·합계·대표값은 같아야 하지만 status가 같아야 하는 것은 아니다.**

분기 값도 한 가지로 고정한다. analysis_period에서는 자료가 없어도 분석 분기, latest_reference에서는 숫자 자료가 하나도 없으면 null이다. 모든 집계 항목은 이 기준 분기를 공유하며, 업종별 다른 실제 분기는 제외 내역에서만 표시한다.

## 7. 계산 코드와 DTO 검증 설계

음식점 전용 FE 합산을 만들지 않고 BE에 공통 상권 집계 결과를 둔다.

```text
기존 선택 업종 조회 → 기존 매출/점포 수 행 연결
  → 공통 상권 집계(유효 행 합산·충돌 판정)
     ├─ 기존 top_markets_estimate : 상위 3곳의 대표값
     └─ 신규 market_aggregation : 상권별 목록·업종 완전성·순위
```

- `top_markets_sales.py`의 현재 합산·정렬을 공통 함수로 분리한다. 기존 `top_markets_estimate`의 합계/멤버/marker는 유지한다.
- 요청 검증 직후 `get_location_reference()`에서 공통 `effective_industries(query)`로 실제 적용 업종을 확정한다. 반환할 `IndustrySelection`에는 **같은 집합의 두 순서 표현**을 둔다. `source_order`는 현재 `query.sub_category or 기본값` 순서, `canonical_order`는 업종 코드순이다. 음식점 생략 시 집합은 4종 전체, 카페는 cafe 하나다. `_sales()`의 조기 반환보다 **앞에서** 수행한다.
- `_sales()`에는 `source_order`를 전달해 기존 원자료·contributions·included_item_keys 순서를 보존한다. `attach()`/공통 집계에는 `canonical_order`와 category를 전달한다. 두 목록은 순서가 아니라 집합이 같아야 한다. `requested_industries`는 canonical_order로만 생성한다. 요청 원문 meta의 빈 배열이나 유효 원자료 행만 보고 선택 범위를 역추론하지 않는다. 검증된 경계 정보는 현재 각 SalesItem에 들어 있는 코드·이름·유형·공간 관계를 사용한다.
- 기존 카페 호출은 동일 산식과 입력을 보장한다. 음식점만 추가 projection을 작성한다.
- 서비스 조립 검사는 category=cafe이면 신규 projection=null, restaurant이면 빈 원자료도 객체라는 조건을 포함한다. 원자료가 있으면 DTO에서도 카페 코드와 음식점 코드의 혼입을 거부한다. 빈 응답의 category/선택 출처는 서비스의 실제 query를 기준으로 확인한다.
- DTO는 원자료에서 포함 행, 누락 업종, 합계, 상태, 순위, 선정 코드, 대표값을 재계산 검증한다. `True`/`1`, 문자열/숫자 등 타입 혼동도 거부한다.
- 원자료가 있으면 업종 코드 집합이 `requested_industries`와 같고, 각 상권마다 요청 업종별 행이 정확히 하나씩 있어야 한다. 신규 목록의 상권 코드 집합도 원자료 목록과 같아야 한다. 사유 및 포함/제외 배열은 순서까지 정규화한 뒤 검증한다.
- 응답 조립 서비스는 실제 query에서 확정한 category/업종과 집계 projection이 같은지 별도로 검사한다. DTO의 자기 일관성 검증만으로 삭제된 원자료나 빈 목록에서 원래 요청을 복원할 수 있다고 주장하지 않는다. 빈 원자료 요청도 서비스의 확정 선택값을 전달해야 한다.
- `selected_market_codes`는 기존 대표값 멤버 코드와 순서까지 같아야 한다. 해당 상권들의 합계가 대표값 분자/분모와 정확히 같아야 한다.
- 선정 상권 각각의 `total_sales`/`total_store_count`/`per_store_metric`은 기존 `top_markets_estimate.markets[]`의 `total_sales`/`total_store_count`/`metric`과 같아야 한다. `included_industry_codes`도 기존 `markets[].industry_codes`와 정규 순서까지 같아야 한다.
- 신규 `eligible_market_count`도 기존 `top_markets_estimate.eligible_market_count`와 같아야 한다. 모든 원자료 업종이 기준 분기와 다르거나 점포 수가 빠진 경우도 같은 정의를 적용한다.
- 검증에서 DB 조회나 추가 HTTP 요청을 하지 않는다. 최대 100상권·500행의 기존 제한과 단일 읽기 전용 RR 트랜잭션을 유지한다. 추가 집계 비용은 행 순회와 상권 정렬이다.
- 응답 snapshot token은 현재 data/meta를 해시하므로 새 필드 추가로 달라질 수 있다. 토큰 문자열 동일성을 회귀 조건으로 삼지 않는다. 원천 버전과 업종 조건을 보존하고 기존 AI/Risk 캐시에는 이 값을 새로 연결하지 않는다.

## 8. FE 표시 설계

`LocationReferenceView`에 요청 `category`를 명시적으로 전달한다. `LocationReferenceSection`은 `params.category`, 보고서는 진단 조건의 category를 전달한다. 업종 코드나 상권명에 특정 단어가 들어 있다는 이유로 음식점 화면을 추론하지 않는다.

### 음식점

- 대표 카드: 기존처럼 **점포당 추정 매출**과 선정 상권의 pooled 평균을 표시한다.
- 금액 아래: `망리단길 · 합정역 · 망원역 상권의 매출액을 토대로 추정했습니다.` 실제 선정된 코드의 이름만 사용한다.
- 선택 업종: `한식 · 중식 · 일식 · 양식 합산`처럼 실제 적용 범위를 표시한다.
- BE의 공식 industry_name을 임의로 축약하지 않고 업종 코드→기존 FE 선택 라벨 매핑으로 한식/중식/일식/양식을 표시한다. 원자료 내역에서는 공식 업종명을 유지한다.
- 기본 목록: `selected_market_codes`의 순서로 합산 카드 최대 3개만 표시한다. 카드 제목은 **망리단길**처럼 상권명으로 두고 공간 관계·자료 분기는 별도 보조행에 표시한다.
- 카드 금액: 해당 상권의 **선택 업종 합산 매출**. 점포 수 합계와 해당 상권 점포당 값도 표시한다. 이 합계 금액과 위 대표 점포당 금액을 혼동시키지 않는다.
- 합계 금액·점포 수는 문자열 기반 천 단위 구분 또는 BigInt 포맷만 사용한다. `Number`/`parseInt`로 바꾸지 않는다. 점포당 값은 BE의 `per_store_metric.display`를 사용하며 FE에서 다시 나누거나 반올림하지 않는다.
- 부분 자료: `선택 4종 중 3종 합산`과 빠진 업종을 표시한다. 완전 자료일 때만 선택 업종 전체 합산이라고 표현한다.
- 선정된 상권 중 하나라도 partial이면 대표 금액 아래에도 `일부 상권은 선택 업종 일부만 합산했어요`를 표시한다. 기존 top3 status만 보고 완전 자료라고 판단하지 않는다.
- `업종별 산정 내역` 펼침 영역에서 포함 업종별 원자료와 제외 사유를 확인한다. 같은 상권을 기본 화면에 여러 장 반복하지 않는다.
- `나머지 상권 보기`에는 4위 이하 상권별 합산 카드와 자료 없음 상권을 표시한다. 기본 상위 3개와 중복 렌더링하지 않는다.
- 선정 0곳이면 기본 영역에 전체 status/reason과 대표 업종별 사유를 이용한 자료 없음 안내를 표시한다. 아무 설명 없이 빈 목록으로 두지 않는다. 원자료 목록 자체가 비었으면 기존 `unavailable(sales.reason)`를 사용하고, 자료 없음 상권 내역은 펼침 영역에서 확인한다.
- 기존 업종별 `sales.items.map()`은 음식점 기본 목록에서 제거하고 감사용 내역에서만 사용한다.
- 공식 서울시 원자료 링크·실제 자료 분기·기존 참고자료 설명은 유지한다. 월매출 환산·반올림 안내·개별 점포 관측값이라는 새 문구는 추가하지 않는다.

### 카페 및 이전 서버 호환

카페는 기존 대표값·목록·출처 표시를 유지한다. 음식점은 `market_aggregation.category`와 `rule_version`이 기대값인지 확인하고 요청 category와 일치할 때만 신규 합산 목록을 표시한다.

음식점에서 `'market_aggregation' in data.sales`가 false이면 구 서버, 키는 있으나 null이면 신규 서버 계약 오류로 구분한다. 지원하지 않는 버전/category 불일치도 호환/계약 오류다. 이 경우 기존 대표값 계약은 유지하되 합산 목록에는 합산 자료를 현재 제공할 수 없다는 안내를 표시하고, 기존 업종별 자료는 `업종별 원자료` 펼침 영역에서만 보여준다. 업종별 카드를 기본 합산 카드로 되돌리지 않는다. FE가 임의로 다른 분기까지 더하지도 않는다. API 오류는 기존 오류·재시도 UI로 처리한다.

분석·요약·보고서 모두 공유 컴포넌트를 사용한다. 업종 변경 시 기존 API 키에 포함된 정렬된 `sub_category`로 재조회하고 이전 요청을 취소한다. 재조회 중 이전 업종의 결과를 새 결과처럼 보여주지 않는 현재 로딩 정책을 유지한다.

## 9. 합성 예시와 검산

아래 금액은 설명용 합성 값이며 월매출이나 실제 지역 수치가 아니다. 모든 행은 같은 분기다.

상권 A에서 4종을 선택했다고 가정한다.

| 선택 업종 | 원자료 매출 | 점포 수 |
| --- | ---: | ---: |
| 한식 | 25,000,000원 | 25 |
| 중식 | 20,000,000원 | 20 |
| 일식 | 30,000,000원 | 30 |
| 양식 | 25,000,000원 | 25 |
| A 합계 | **100,000,000원** | **100** |

전체 후보의 합산 결과가 아래와 같다면 다음 순서로 선정한다.

| 상권 | 합산 매출 | 합산 점포 수 | 순위·사용 |
| --- | ---: | ---: | --- |
| A | 100,000,000원 | 100 | 2위·선정 |
| B | 80,000,000원 | 80 | 4위·상세만 |
| C | 240,000,000원 | 120 | 1위·선정 |
| D | 90,000,000원 | 90 | 3위·선정 |

대표값은 C+A+D의 `430,000,000 ÷ 310 = 1,387,096.774...원`, 표시값은 **1,387,097원**이다. 기본 카드 순서와 출처 순서는 C→A→D다. 4곳 전체 평균이나 상권 평균 3개의 단순평균을 표시하지 않는다.

한식·중식만 선택하면 A는 45,000,000원/45개로 바뀐다. 나머지 상권도 같은 두 업종만 다시 합산한 뒤 전체 순위를 다시 정한다. 기존 C→A→D를 그대로 유지할 수 있다고 가정하지 않는다.

## 10. 구현 파일과 진행 순서

| 순서 | 대상 | 작업 |
| --- | --- | --- |
| 1 | BE `app/schemas/location_reference.py` 및 API 문서 | 신규 strict 집계 DTO와 상태/멤버/숫자 계약 정의 |
| 2 | BE `app/services/top_markets_sales.py`, `per_store_sales.py`, `location_reference.py` | 공통 상권 집계 분리, 요청 업종·경계 정보 전달, 기존 대표값과 신규 목록의 일관성 검증 |
| 3 | BE 단위·PostGIS 통합 테스트 | 전체/부분 업종·분기/결측·순위·카페 회귀·DTO 위조 검증 |
| 4 | FE `src/types/locationReference.ts`, `docs/api-contract.md` | 신규 목록 타입·호환 계약 반영 |
| 5 | FE `LocationReferenceView.tsx`, `LocationReferenceSection.tsx`, `ReportPage.tsx` | category 전달, 음식점 합산 카드·기본 3곳·펼침 상세 연결 |
| 6 | FE/API 테스트·실제 브라우저 | 업종 변경/취소/오류/모바일·인쇄 및 카페 보존 검증 |
| 7 | 정상 PR·CI → BE 배포 → FE 배포 | 공개 합산 API를 먼저 검증하고 음식점 UI 전환 |

추가 데이터가 필요한 작업이 아니다. 현재 등록된 매출·점포 수·상권 경계 데이터와 선택 업종만 사용한다. DB/ETL/브랜드 판정/생활인구/AI 산식을 함께 변경하지 않는다.

FE 개발 목업도 구현 범위에 포함한다. 현재 `src/api/mocks/index.ts`에는 `/v2/location-reference` 핸들러가 **등록되어 있지 않으며**, `client.ts`는 미등록 시 실제 fetch로 넘어간다. 따라서 기존 location-reference 목업을 갱신하는 작업이 아니라 `mocks/locationReference.ts`의 합성 fixture/핸들러와 index 등록을 새로 추가하는 작업이다. 음식점 ready/partial/no_data·전체/일부 선택·이전 계약, 카페 `market_aggregation=null` 예시를 제공하고 `is_demo=true`로 명시한다. `/v2/` 목업 차단 정책이나 운영 환경값은 바꾸지 않는다. 실제 조회 검증과 목업 검증은 구분한다.

## 11. 인수 조건과 테스트

| 구분 | 반드시 확인할 결과 |
| --- | --- |
| 전체 선택 | 음식점 4종 합이 상권당 1개 항목이며, 4업종 행을 각각 순위에 넣지 않음 |
| 일부 선택·단일 선택 | 선택 외 업종이 분자/분모/목록에 들어가지 않음 |
| 선택 생략 | 음식점 4종 전체와 같은 합계·멤버. FE 빈 배열 직렬화가 키 생략인지 확인. 중복/부적합 업종과 직접 빈 문자열 요청은 실제 API의 422 확인 |
| 재선정 | 업종 변경으로 점포 수 순서가 바뀌는 fixture에서 상위 3곳과 출처도 함께 변경 |
| 분기 | latest_reference fixture에서 업종별 다른 분기를 합치지 않음. analysis_period는 지정 분기 자료만 허용. 과거 분기/유사 지역으로 보충하지 않음 |
| 결측·0 | 누락은 0원 처리하지 않음. 0원/양수 점포는 포함. 0분모는 제외. 부분 자료의 적용 업종과 합계가 일치 |
| 후보 부족 | 1~2곳은 해당 자료만 표시. 0곳은 금액 없음·빈 선정 목록·원인 안내 |
| 순위·식별 | 같은 점포 수는 코드순. 동명 다른 코드 유지. 같은 코드 명칭 충돌은 제외. 중복 행 거부 |
| 정밀도 | 큰 정수와 1원 미만/반올림 경계 검증. 합계 후 나눔과 마지막 표시 반올림 |
| 교차 검증 | 기본 카드 3곳의 매출·점포 수 합이 대표값 분자/분모와 정확히 같고 출처 코드/순서도 같음 |
| DTO | 총액·분모·순위·selected flag·업종 목록·상권명·reason·버전 위조와 bool/int 혼동 거부. 원자료 교차곱·상권 코드 집합·서비스의 실제 query 일치 검증 |
| API/DB | 최소 4상권×4업종의 격리 PostGIS fixture에서 DB 직접 조회값으로 합계·순위·대표값 비교. 원천 읽기 전용 실제 복원본 대조와 구분 |
| FE 공통 화면 | 분석/요약/보고서에 동일 결과. 기본 상권 카드 최대 3개, 업종별 카드 중복 없음. 기타 상권은 펼침 영역 |
| FE 상태 | 신규 필드 없음/null/잘못된 버전·일시 오류·업종 변경 중 취소 시 잘못된 합계/이전 업종 값 미표시. 선정 상권 partial이면 대표 카드에도 부분합 안내 |
| 카페 회귀 | 기존 대표값·선정 코드/순서·출처·목록·생활인구가 수치와 화면 의미 기준으로 동일 |
| 모바일·인쇄 | 새 카드 360/390px에서 넘침 없음, 펼침 내역 키보드 조작, 보고서/PDF에 합산 업종과 출처 유지 |

현재 보고서의 기존 표에서 360px 기준 3px 가로 넘침이 확인된 것은 별도 UI 문제다. 이 설계의 신규 합산 카드 인수 조건과 구분하며, 그 문제를 이번 문서 작성으로 해결했다고 주장하지 않는다.

## 12. 배포·복구 및 이번 산출물의 한계

- 실제 구현 단계에서는 BE를 먼저 정상 PR/CI로 병합·배포하고, 전체/일부 업종 공개 API를 읽기 전용 검증한 뒤 FE를 전환한다.
- BE 단독 배포 중 구 FE는 기존 필드를 계속 사용할 수 있다. 신 FE에서 구 BE로 되돌아가면 위 호환 안내를 따른다.
- FE 되돌림은 이전 배포로 복귀한다. BE 되돌림은 신규 코드 배포만 되돌리고 DB/원자료를 복구할 작업은 없다.
- 설계 문서 작성·Claude 검토와 기능 구현·실제 테스트·배포는 다른 단계다. 이 문서의 테스트 표는 앞으로 실행할 인수 조건이며 이미 통과한 결과로 읽지 않는다.
- 합산 결과는 공공자료의 해당 업종 집계다. 실제 선택 점포 목록의 전체 매출이나 개별 점포 실매출을 알게 되는 것은 아니다.

## 13. Claude Code 실제 검토 기록

- 검토일: 2026-11-17. 검토 방식: 이 문서 Read·Edit만 사용. 쉘·네트워크·DB·테스트 실행 없음. 앱 코드 수정 없음.
- 비교 대상: 검토 요청에 첨부된 BE `top_markets_sales.py`, `per_store_sales.py`, `schemas/location_reference.py`, `schemas/store_filters.py`, `services/location_reference.py`, `routers/location_reference.py`와 FE `types/locationReference.ts`, `LocationReferenceView.tsx`, `LocationReferenceSection.tsx`, `api/locationReference.ts`, `api/population.ts`, `hooks/useDiagnosisQuery.ts`. `client.ts`, `ReportPage.tsx`, `PopulationReferenceQuery`, `ErrorCode`→HTTP 상태 매핑은 첨부되지 않아 확인하지 못했다.
- 구현·테스트·배포는 하지 않았다. §11 표는 아직 실행하지 않은 인수 조건이다.

### 판정: **REVISE** (경미한 수정 후 구현 가능)

방향과 핵심 산식은 사용자 요구 및 실제 코드와 일치한다. `top_markets_estimate()`는 이미 같은 분기의 유효 업종 행을 상권별로 합산하고, `(-stores, market_code)`로 정렬해 서로 다른 상권 최대 3곳을 고른 뒤 pooled `metric(Σ매출, Σ점포수)`를 계산한다. §2의 “대표값 자체는 정상이고, 부족한 것은 상권 단위 목록 계약과 FE 표시”라는 진단은 정확하다. §9 검산(C 120 → A 100 → D 90, 430,000,000 ÷ 310 = 1,387,096.77… → 1,387,097원)도 `metric()`의 반올림 규칙(`2r ≥ n`)과 맞는다. 추가 API·데이터·DB 변경이 필요 없다는 판단도 맞다. 카페 계산 경로를 변경하지 않는다는 점과 0분모 정책 및 기존 산식을 보존한다는 점도 일관된다.

다만 아래 1~4는 구현자가 임의로 판단해야 하는 공백이므로 구현 전에 문서에 확정해야 한다. 5~10은 정합성을 보완하기 위한 사항이다.

### 구현 전 확정 필요 (블로커)

1. **사유 어휘가 정의되지 않음.** BE `Reason` Literal에는 `sales_unavailable`, `store_row_missing`, `store_mapping_conflict`, `zero_store_count`, `zero_store_count_with_sales`, `different_quarter`가 없다. 이 값들은 현재 `average_contribution`이라는 비정형 dict 안에서만 쓰인다. §6은 strict Pydantic 모델을 요구하지만 `items[].reason`, `unavailable_industries[].reason`, 상권 전체 명칭 충돌 사유(§6-4)에 허용할 값 목록이 없다. 신규 `MarketAggregationReason` Literal을 열거하고, 기존 `Reason`과 별도 타입임을 명시해야 한다. 기존 `Reason`에 값을 추가하면 기존 블록 검증과 FE 문구에 영향을 준다. 같은 업종에 사유가 여러 개면 우선순위도 정해야 한다. 기존 `average_contribution.reason`을 그대로 쓰도록 정하는 방식을 권장한다.
2. **전체 `status/reason` 결정 규칙이 모호함.** §6-6의 “상위 자료 상태 우선” 규칙을 그대로 적용하면 문제가 생긴다. `sales.status`는 어느 한 상권×업종 행만 `no_data`여도 `partial`이 되기 때문에 집계 결과가 거의 항상 `partial`로 덮인다. 다음 처럼 표로 확정해야 한다: ① `sales.items`가 비어 있고 `sales.status ∈ {no_data, pending, not_supported}`이면 해당 status/reason을 그대로 전달한다 ② 그 외에는 집계 결과만으로 판단한다. 선정 가능 상권이 0곳이면 `no_data`, 하나라도 partial/no_data 상권이 있거나 선정 상권이 3곳 미만이면 `partial`, 나머지는 `ready`다. 또 기존 `top_markets_estimate.status`와 값이 다를 수 있다는 점도 명시해야 한다. 기존 status는 같은 분기이면서 금액이 있는 행만 후보로 보므로 `different_quarter`·`sales_unavailable`을 반영하지 않는다. 테스트가 두 status의 일치를 기대하지 않도록 해야 한다.
3. **요청 업종·category 전달 경로.** `attach()` 시그니처에는 category와 적용 업종이 없다. 또 meta `requested_scope.sub_category`는 `list(query.sub_category)`이므로 생략 요청에서는 `[]`이고, 순서도 요청 순서를 따른다. §7은 “서비스 시그니처 확장”만 적고 있다. `_sales()`에서 계산한 `chosen`(생략 시 기본 4종)을 `attach()`에 명시적으로 전달하고, 이 값을 `requested_industries`의 유일한 출처로 삼는다고 적어야 한다. `market_aggregation`이 null인지 객체인지에 대한 규칙도 고정해야 한다. 권장안은 다음과 같다. category가 `cafe`이면 항상 null이다. category가 `restaurant`이면 `_empty()` 경로(source_not_loaded, scope_too_large, no_spatial_overlap 등)를 포함해 **항상 객체**를 반환하고, 상위 status/reason을 담는다. 그래야 FE가 “신규 서버의 자료 없음”과 “구 서버”를 구분할 수 있다(아래 7번).
4. **DTO 자기검증 기준.** `SalesBlock` validator는 query를 알지 못한다. 대신 `_sales()`는 상권×선택 업종의 완전한 교차곱으로 `items`를 만들기 때문에 다음 조건을 검증 기준으로 명시할 수 있다: (a) `items`가 있으면 `{i.industry_code} == requested_industries` 코드 집합이고 각 상권마다 모든 업종 행이 정확히 하나씩 있다 (b) `market_aggregation.items`의 상권 코드 집합이 `sales.items`의 상권 코드 집합과 **정확히 같다**. §6-3의 “넘지 않는다”는 “같다”로 강화해야 한다 (c) 재계산은 `top_markets_estimate`와 마찬가지로 공통 함수의 결과와 정규화한 JSON이 같은지로 검증한다 (d) `selected_market_codes == [m.market_code for m in top_markets_estimate.markets]`. 이 조건이 없으면 “요청 업종의 정확한 분할”(§6-5)을 응답만으로 검증할 수 없다.

### 정합성 보완

5. **상권 명칭 충돌 규칙은 실제 데이터에서 도달할 수 없는 경로임을 명시.** `_sales()`는 모든 `SalesItem.market_name`을 경계 후보 `area.name`으로 채운다. 원자료 이름이 다른 행은 이미 `mapping_conflict`로 걸러지고, 점포 수 행의 이름이 다르면 `store_mapping_conflict`로 처리된다. 따라서 같은 코드의 유효 행끼리 이름이 충돌하는 경우는 사실상 위조된 DTO에서만 생긴다. §6-4의 “검증된 경계 상권명을 제공할 수 없다면”도 실제 경로에서는 발생하지 않는다. 동작은 유지하되 “방어 규칙이며 DTO 위조 테스트로만 검증한다”고 적어 PostGIS fixture로 재현하려는 시도를 막아야 한다.
6. **`source_quarter` 값 규칙.** `analysis_period` 모드에서 `primary_quarter`는 자료가 없어도 항상 분석 분기다. `latest_reference` 모드에서 금액 행이 없으면 null이다. 다음 두 가지를 명시해야 한다: `market_aggregation.source_quarter == per_store_average.primary_quarter`(null 포함 동일). `no_data` 상권 항목의 `source_quarter`/`temporal_relation`은 null이 아니라 상위 기준 분기를 따른다. 또는 null로 정할 수도 있는데, 어느 쪽인지 하나로 확정해야 한다. 지금은 “합계의 기준 분기”라고만 되어 있어 no_data 항목에서 해석이 갈린다.
7. **FE 호환 판별과 대체 화면.** 지금은 `hasTopMarketsContract = 'top_markets_estimate' in data.sales` 방식을 쓰고 있다. 신규 필드도 `'market_aggregation' in data.sales`(구 서버)와 값이 null인 경우를 구분해야 한다. §8은 구 서버나 지원하지 않는 버전일 때 “준비/호환 안내”를 표시한다고만 한다. 이때 기존 업종별 `sales.items` 카드를 감사용 내역으로 접어서 보여줄지, 숨길지를 정해야 한다. 권장안은 안내문과 함께 기존 카드를 `업종별 원자료` 펼침 영역에만 두는 것이다.
8. **대표 카드에서도 부분 합산을 공개.** §8은 부분 자료 표시를 개별 상권 카드에만 요구한다. 그런데 선정된 3곳 중 하나라도 `partial`이면 대표 점포당 금액 역시 부분 업종 합으로 계산된 값이다. `top_markets_estimate`에는 상권별 완전성 정보가 없으므로, FE는 `market_aggregation.items`의 status를 참조해 대표 카드 아래에 “일부 상권은 선택 업종 일부만 합산”을 표시해야 한다. 그래야 “부분 포함, 정직한 공개” 요구가 대표값까지 일관되게 적용된다.
9. **정규 순서 주장의 범위.** BE `_sales()`는 요청 순서대로 `INDUSTRIES`를 순회하므로 `sales.items`의 상권 안 순서와 `meta.requested_scope.sub_category`는 요청 순서에 따라 달라진다. FE `populationParams()`는 알파벳순(chinese, japanese, korean, western)으로 보내며, 이는 한→중→일→양 순서가 아니다. 순위·합계는 순서와 무관하므로 문제는 없다. 다만 §3의 “선택 순서로 결과가 달라지지 않는다”는 문장은 **신규 `market_aggregation`과 기존 대표값에만** 해당하도록 범위를 좁혀야 한다. 신규 필드 안의 업종 배열은 BE가 `CS100001..4` 코드순으로 정렬해 출력한다고 명시해야 한다. 기존 `sales.items` 순서와 FE 캐시 키는 바꾸지 않는다.
10. **확인되지 않은 전제.** (a) “빈 선택 배열 = 생략”은 `client.ts`가 빈 배열을 쿼리에서 빼는 경우에만 성립한다. `sub_category=`로 보내면 BE는 `[""]`로 분할해 검증에 실패한다. (b) “중복 업종 422”는 `LocationReferenceQuery`가 `CategoryFilters` 검증을 상속하는지와 `INVALID_PARAM`의 HTTP 코드에 달려 있다. 둘 다 첨부 코드로 확인할 수 없었다. §11 선택 생략 항목에 “FE 빈 배열 직렬화 결과 확인”과 “BE 직접 호출 시 상태 코드 확인”을 넣어야 한다.

### 요구 구체성 평가

- 집계 키, 동일 분기, 유효 쌍, 0원·0분모, 순위 및 동률 처리, 최대 3곳 선정, pooled 대표값, 카페 불변, 신규 API·데이터 불필요, FE 기본 3장과 나머지 펼침 구조는 구현하기에 충분히 구체적이다.
- 위 1~4(사유 어휘, 전체 status 표, 요청 업종 전달과 null/객체 규칙, DTO 자기검증 기준)를 확정하면 BE는 추가 해석 없이 구현할 수 있다. FE는 7·8이 확정되면 구현할 수 있다.
- 범위 밖의 기존 문제는 이번 설계 범위로 넓히지 않는다. 예를 들면 `per_store_average`가 명칭 충돌 행을 포함하는 점, 기존 `excluded_item_count` 문구 범위, 보고서 360px 3px 넘침이 있다.

### 2차 검토 (Claude Code, 2026-11-17)

- 방식: 이 문서 Read·Edit만 사용. 쉘·네트워크·DB·에이전트·테스트 실행 없음. 앱 코드 수정 없음. 구현·테스트·배포는 하지 않았고 §11은 여전히 미실행 인수 조건이다.
- 비교 대상: 1차 첨부 코드에 더해 이번에 첨부된 BE `schemas/population_reference.py`, `core/errors.py`, FE `api/client.ts`, `api/params.ts`, `hooks/useReportData.ts`, `ReportPage.tsx`(170~210행). FE mock(`./mocks`) 내용과 `docs/api-contract.md`는 첨부되지 않았다.

#### 판정: **REVISE** (경미. 아래 1번 모순만 해소하면 구현 착수 가능)

1차 검토의 1~10번은 §3·§4.2·§6·§6.1·§6.2·§7·§8·§11에 모두 반영되었다. 사용자 요구(카페 불변, 선택 업종을 상권별로 먼저 합산, 합산 점포 수 상위 서로 다른 상권 3곳, Σ매출÷Σ점포수 대표값, 기본 3장과 나머지 펼침)와 실제 코드 진단은 일치한다. 1차 10번의 미확인 전제는 이번 첨부 코드로 **정적으로** 확인했다(실행 검증은 아님).
- `client.ts`의 `toQueryString()`은 빈 배열과 빈 문자열을 쿼리에서 뺀다. 따라서 FE 빈 선택은 키 생략이 되고 4종 전체로 해석된다.
- `PopulationReferenceQuery`는 `CategoryFilters`를 상속한다. 중복 업종, 부적합 업종, `sub_category=`(→ `[""]`)는 `ValidationError` → `INVALID_PARAM`이 된다. 반복된 쿼리 키는 라우터의 `getlist()!=1` 검사에서 `INVALID_PARAM`이 된다. `errors.py`상 두 경우 모두 422다.

남은 사항은 다음과 같다.

#### 구현 전 해소 필요

1. **[모순] 업종 정규 순서와 기존 `sales.items` 순서 보존이 충돌함.** §7은 `effective_industries(query)`가 반환하는 **코드순** 목록을 `_sales()`와 `attach()`에 “동일하게 전달”하라고 한다. 그런데 현재 `_sales()`는 전달받은 순서대로 `industries`를 순회해 `sales.items`를 만든다. 그대로 구현하면 FE의 알파벳순 요청(chinese, japanese, korean, western)에서 `sales.items`의 상권 내 순서와 `per_store_average.contributions`·`included_item_keys` 순서가 한→중→일→양으로 바뀐다. 이는 §3의 “기존 `sales.items` 요청 순서 표현 변경하지 않는다”와 정면으로 충돌한다. 둘 중 하나로 확정해야 한다. 권장안은 다음과 같다. `_sales()`는 기존처럼 `query.sub_category or 기본값`을 요청 순서대로 순회한다. 정규 순서 목록은 `attach()`/공통 집계와 `requested_industries`에만 쓴다. 서비스에서는 두 목록의 **집합 동일성**만 검사한다. 대안은 순서 변경을 허용하고 §3 문구와 카페/음식점 회귀 기준을 고치는 것이다. 다만 사용자가 요구한 “기존 계약 불변”에 가까운 쪽은 권장안이다.

#### 정합성 보완 (구현자가 임의 판단하지 않도록 한 줄씩 명시 권장)

2. **명칭 충돌 상권의 `market_name` 값이 정해지지 않음.** §6-4는 “원문을 임의로 골라 정상 명칭으로 쓰지 않는다”고만 하고, strict DTO의 `items[].market_name` 타입(`str` 또는 `str | None`)과 그때의 값을 정하지 않았다. 권장안은 `market_name: str | None`으로 두고 `reason == market_name_conflict`일 때만 null을 허용하는 것이다. FE는 이때 상권 코드와 함께 `자료 정보 불일치`로 표시한다. 같은 코드 안에서 `market_type`/`spatial_relation`이 다른 위조 입력은 현재 `top_markets_estimate()`도 검사하지 않는다. 신규 DTO에서는 이를 거부(입력 결함)할지 명시해야 한다. 이때 이름 충돌만 “상권 제외”로 남겨야 기존 선정 결과와 어긋나지 않는다.
3. **`requested_industries`의 한글명 출처.** “코드·한글명”의 한글명이 원자료 라벨(`한식음식점`, `INDUSTRIES` 값)인지 UI 라벨(`한식`)인지 정해야 한다. §8 예시 문구(`한식 · 중식 · 일식 · 양식 합산`)는 UI 라벨이다. 권장안은 BE가 원자료 라벨 `industry_name`을 내려주고 FE가 코드→UI 라벨 매핑으로 표시하는 것이다. 어느 쪽이든 DTO 검증 대상 값으로 고정해야 한다.
4. **사유 Literal의 필드별 범위.** §6.1은 `MarketAggregationReason`을 기존 `Reason` 전체와 신규 값의 합집합으로 정의한다. 그러나 필드별 실제 도달 값은 더 좁다.
   - 상권 `items[].reason`: `partial_selected_industries`, `market_name_conflict`, `no_valid_sales_store_pairs` 또는 null.
   - `unavailable_industries[].reason`: `SalesItem.reason` 4종(`mapping_conflict`, `source_value_null`, `no_source_rows`, `no_data_in_analysis_period`)과 `different_quarter`, 점포 수 4종, `market_name_conflict`.
   - 전체 reason: 기존 `Reason`, `no_valid_sales_store_pairs`, `fewer_than_three_markets`.

   합집합 하나를 모든 필드에 쓰면 strict 검증이 약해진다. 필드별 Literal(또는 validator)로 좁힐 것을 권장한다. 또 §6.1 2단계가 `SalesItem.reason`을 그대로 쓰므로 `sales_unavailable`은 신규 DTO 어디에서도 나오지 않는다. 목록에서 빼거나 “기존 `average_contribution` 호환용, 신규 필드 미사용”이라고 적어야 한다.
5. **`eligible_market_count` 동일성.** 기존 `top_markets_estimate.eligible_market_count`(= 유효 행이 있는 상권 수)와 신규 값은 같은 정의다. 유효 행은 `per_store_metric`이 있어 점포 수가 양수이므로 상권 합계도 항상 양수다. §7의 교차 검증 목록에 `selected_market_codes`뿐 아니라 이 값의 일치도 넣어야 한다. 그래야 두 계약의 “선정 가능 상권” 정의가 분리되지 않는다.
6. **카페 null 규칙의 검증 위치.** `SalesBlock` validator는 category를 모른다. 빈 `items` 응답에서는 카페(null)와 음식점(객체)을 DTO만으로 구분할 수 없다. §7의 “서비스 검사”에 **category=cafe ⇒ null, restaurant ⇒ 객체(빈 원자료 포함)** 를 명시적으로 포함해야 한다. `items`가 있을 때는 DTO가 업종 코드(`CS100010` 대 `CS10000[1-4]`)로 교차 검증할 수 있다고 적으면 충분하다.
7. **FE 목업 자료.** `client.ts`는 목업 모드에서도 `/v2/location-reference`를 목업 응답으로 처리한다. 신규 FE를 목업으로 실행하면 음식점이 §8의 “구 서버 호환 안내”로만 보인다. §10 4~5단계에 목업 응답(음식점 ready/partial/no_data와 카페 null 예시) 갱신을 추가해야 한다. 목업 파일 자체는 이번에 확인하지 못했다.

#### 범위 확인 (추가 변경 불필요)

- 0분모 정책, `metric()` 산식·반올림, `per_store_average`·`top_markets_estimate`의 기존 수치와 status 의미는 설계상 변경되지 않는다. 부분 유효 행을 포함하고 상권 카드와 대표 카드에 coverage를 공개하는 방식(§5, §8)은 사용자 의도와 맞다.
- 신규 endpoint·API 키·DB·migration·원자료가 필요 없다는 판단은 첨부 코드와 일치한다. `attach()`는 `_empty()` 경로에서도 항상 호출되므로, §6의 “음식점은 `_empty()` 경로도 항상 객체” 규칙을 추가 조회 없이 구현할 수 있다.
- `analysis_period` 모드에서는 `_sales()`가 기준 분기 행만 조회하므로 `different_quarter`가 생기지 않는다. 이 사유는 `latest_reference`에서만 나타난다. §11 분기 테스트는 `latest_reference` fixture로 구성해야 한다.
- `latest_reference`에서 숫자 행이 전혀 없으면 `items`는 있지만 기준 분기가 null이다. 이때 §6.2 규칙 2에 따라 전체 사유는 `no_valid_sales_store_pairs`가 되고, 구체적인 원인(`no_source_rows` 등)은 업종별 `unavailable_industries`에만 남는다. 정직성 요건에는 문제가 없지만, FE 안내 문구를 고를 때 업종별 사유를 참조해야 한다.

#### 요구 구체성 평가

- 1번을 확정하면 BE 집계·DTO·서비스는 추가 해석 없이 구현할 수 있다. 2~6번은 각각 한 줄 정도의 명시로 해결되며, 구현 방향을 바꾸지 않는다.
- FE는 §8과 7번(목업)으로 구현 가능한 수준이다. 카페 화면은 신규 분기 없이 기존 렌더링을 유지하면 된다.

### 3차 검토 (Claude Code, 2026-11-17)

- 방식: 이 문서 Read·Edit만 사용. 쉘·네트워크·DB·에이전트·테스트 실행 없음. 앱 코드 수정 없음. 구현·테스트·배포는 하지 않았고 §11은 여전히 실행하지 않은 인수 조건이다.
- 비교 대상: 1·2차 첨부 코드 전체와 이번에 첨부된 FE `src/api/mocks/index.ts`. `docs/api-contract.md`, `constants/diagnosis.ts`(`RESTAURANT_SUB_CATEGORIES` 라벨)는 첨부되지 않았다.

#### 판정: **PASS** (구현 착수 가능. 아래 1~5는 비차단 보완이며, 구현 PR에서 문서와 함께 한 줄씩 반영하면 된다)

2차 검토 결과는 모두 본문에 반영되었다.
- 2차 1번(모순): §7의 `source_order`/`canonical_order` 분리로 해소되었다. `_sales()`의 기존 순회 순서, `contributions`/`included_item_keys` 순서, meta는 그대로 두고, 신규 집계와 `requested_industries`에만 코드순을 쓴다. 두 목록은 집합이 같은지만 검사한다.
- 2차 2번: §6 표와 §6-4에 이름 null 허용 조건, `market_type`/`spatial_relation` 불일치 거부가 반영되었다.
- 2차 3번: `requested_industries`는 원자료 라벨을 쓰고, FE에서 코드→UI 라벨로 매핑하도록 정해졌다.
- 2차 4번: §6.1에서 필드별 Literal을 정의하고 `sales_unavailable`을 뺐다.
- 2차 5번: §7에 `eligible_market_count` 일치 조건이 들어갔다.
- 2차 6번: §7에 서비스의 cafe/restaurant 조립 검사가 들어갔다.
- 2차 7번: §10에 목업 신규 작성이 들어갔다.
- **2차 7번의 사실관계 정정:** 2차 검토는 “`client.ts`가 목업 모드에서도 `/v2/location-reference`를 목업 응답으로 처리한다”고 적었는데, 이는 부정확했다. 이번에 첨부된 `mocks/index.ts`의 `mockRoutes`에는 `/v2/population-reference`만 있다. 따라서 `client.ts`의 `/v2/` 허용 목록을 통과하더라도 `getMockResponse()`가 null을 반환하고 실제 fetch로 넘어간다. §10의 현재 서술(“기존 목업 갱신이 아니라 신규 핸들러·index 등록”)이 맞다.

사용자 요구와 실제 코드는 다시 대조해도 일치한다.
- 카페: `market_aggregation=null`. 기존 `_sales`/`attach`/`top_markets_estimate` 경로와 수치는 변하지 않는다.
- 음식점: 선택 업종만 조회한다(생략하면 4종). 같은 `primary_quarter`의 유효 쌍만 `(market_code)` 단위로 합산한다. `(-Σ점포수, market_code)` 순서로 서로 다른 상권 최대 3곳을 고르고, 대표값은 Σ매출÷Σ점포수로 계산한다. 이 산식은 현재 `top_markets_estimate()`와 같다.
- 신규 집계의 “선정 가능” 정의(유효 쌍 = `per_store_metric` 존재 = 점포 수 양수, 이름 충돌 상권 제외)는 기존 함수의 `eligible`/`markets`와 같다. 그래서 `selected_market_codes`와 `eligible_market_count`의 일치 조건은 실제로 성립할 수 있다.
- 부분 유효 행 포함과 coverage 공개(§5, §8), 0분모 제외, `metric()` 반올림, 기존 status 의미 보존이 서로 모순되지 않는다.
- 신규 endpoint·API 키·DB·원자료는 필요 없다.

#### 비차단 보완

1. **합계 금액의 표시 형식이 정해지지 않음.** `items[].total_sales`와 `total_store_count`는 `display` 없이 정수 문자열이다. 현재 FE 계산 상세도 `{topMarkets.total_sales}원`처럼 쉼표 없이 그대로 출력한다. §8의 카드 금액(“선택 업종 합산 매출”)이 기본 화면의 주요 숫자가 되므로 형식을 정해야 한다. 원자료 행 하나의 상한이 `2**63-1`이어서 FE가 `Number()`로 바꾸면 정밀도가 깨질 수 있다. 권장안: “FE는 문자열 기반 천 단위 구분으로만 표시하고 `Number`/`parseInt`로 변환하지 않는다”를 §8에 한 줄 추가한다. BE 계약은 그대로 둔다. 점포당 값은 기존 `per_store_metric.display`를 쓴다.
2. **선정 상권이 0곳일 때 기본 영역이 정해지지 않음.** `sales.items`는 있지만 모든 상권이 `no_data`이면(예: latest_reference에서 숫자 자료 없음, 모든 업종이 다른 분기) 기본 3장 영역이 비고, 모든 항목이 접힌 “나머지 상권 보기”에만 남는다. §8에 다음을 명시해야 한다. 이 경우 기본 영역에는 전체 `status/reason`과 대표 업종별 사유로 안내문을 표시하고, 자료 없음 상권은 펼침에서 확인하게 한다. `sales.items`가 빈 경우(§6.2 규칙 1)는 지금처럼 `unavailable(sales.reason)`을 쓴다.
3. **선정 상권 단위의 교차 검증 범위.** §7은 선정 코드·순서와 pooled 분자/분모가 같아야 한다고만 요구한다. 상권별 값이 같아야 한다는 조건도 넣는 것이 안전하다: 선정 상권 각각의 `total_sales`·`total_store_count`·`per_store_metric`이 `top_markets_estimate.markets[]`의 `total_sales`·`total_store_count`·`metric`과 같고, `included_industry_codes`가 `markets[].industry_codes`와 같아야 한다. 기존 쪽은 `sorted()`인데, `CS10000[1-4]`는 사전순과 코드순이 같아서 정규 순서와 일치한다. 공통 함수를 쓰면 자연히 성립하지만, DTO 위조 테스트(§11 DTO)의 기준으로 명시해 둘 가치가 있다.
4. **카페 null 문구 통일.** §6 도입부와 §7은 “카페는 **항상** null”이라고 하는데, §6 계약 2항은 “null을 **허용**”이라고 해서 선택 사항처럼 읽힌다. “카페는 반드시 null”로 통일한다.
5. **`included_item_keys`의 형태.** 표에서는 `(market_code, source_quarter, industry_code)` 튜플 표기를 쓴다. 기존 `per_store_average.groups[].included_item_keys`와 같은 `{market_code, industry_code, source_quarter}` 객체 형태로 하고, 순서는 `included_industry_codes`(정규 순서)를 따른다고 명시해야 한다. 그러지 않으면 strict DTO와 FE 타입에서 형태를 임의로 고르게 된다.

#### 범위 확인

- 위 1~5는 계약 의미나 산식을 바꾸지 않는다. 기존 문제(최신 숫자 행 선택 시 기준 분기의 null 행을 건너뛰는 사유 표현, `per_store_average`의 명칭 충돌 행 포함, 보고서 360px 넘침)는 이번 설계 범위로 넓히지 않는다.
- 요구 구체성: BE(집계·DTO·서비스 조립)와 FE(category 전달, 기본 3장, 나머지 펼침, 부분합 안내, 구 서버 호환, 목업)는 현재 문서만으로 추가 해석 없이 구현할 수 있다. 1·2번은 FE 표시를, 3·5번은 DTO 테스트 기준을 다듬는 사항이다.
- 이 판정은 설계 문서 검토 결과다. 구현, §11 테스트 실행, 배포가 완료되었다는 뜻이 아니다.

## 14. Codex 최종 재검토

**결론: 설계 완료. 구현 단계에서 추가 API·원자료·사용자 결정 없이 착수 가능한 상태다.**

- 실제 Claude Code CLI의 1차·2차 REVISE를 반영했고 3차 PASS를 확인했다. 검토는 대상 MD에 대한 실제 Read·Edit로 수행했으며 세 번 모두 정상 종료했고 권한 거절이 없었다.
- 원래 음식점 대표 산식은 이미 상권별 합산 후 상위 3곳 선정이었다. 이를 재사용하고, 누락된 상권별 합산 목록·선택 업종 완전성·FE 기본 카드 표시를 구현할 범위로 확정했다.
- 1차 지적의 사유 타입·전체 상태 결정표·조기 반환 전 요청 선택 확정·DTO와 실제 query의 일치 검증을 명문화했다. 2차 지적의 source_order/canonical_order 충돌과 카페 null/음식점 객체 규칙을 해결했다.
- 목업 경로는 Codex가 `mocks/index.ts`와 `client.ts`를 직접 비교해 미등록 후 실제 fetch로 넘어감을 확인했다. Claude 3차에서도 2차 설명의 사실관계를 정정했다. 미래 구현에는 신규 합성 목업 핸들러 추가가 필요하다.
- 3차 비차단 권고 5건도 본문에 반영했다. 합계의 정밀한 표시, 선정 0곳 안내, 상권별 금액·점포 수·업종 일치 검증, 카페 null 필수, included_item_keys의 객체 형태와 순서를 확정했다.
- 문서의 상대 링크·UTF-8·변경 범위·합성 예시의 합산 및 반올림을 확인했다. BE/FE 앱 코드·테스트 코드·DB·환경·공개 배포는 이번에 변경하지 않았다. §11의 기능 테스트는 구현 단계에서 실행할 조건이며 이번 문서 검토로 통과했다고 주장하지 않는다.
- 구현 순서는 **BE 신규 집계 계약과 공통 집계 → 음식점 FE 상권 카드·목업 → 실제 API/브라우저 검증 → 정상 배포**다. 카페·생활인구·AI의 별도 변경은 포함하지 않는다.
