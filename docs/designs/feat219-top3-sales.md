# 점포 수 상위 3개 상권 기반 추정매출 (#219)

## 최신 결정과 산식
검색 결과의 같은 기준 분기에서 매출 및 양수 점포 수가 함께 확인된 자료만 사용한다. 동일 상권의 대상 업종 자료를 먼저 합산한다. 상권별 유효 점포 수 내림차순, 동률은 상권코드 오름차순으로 최대 3개의 서로 다른 상권을 선정한다.
대표값 = 선정 상권 매출 합계 / 선정 상권 점포 수 합계. 상권별 평균의 단순평균이나 중앙값을 사용하지 않는다. 0원 매출은 유효하며, 누락/0분모/매핑 충돌은 분자와 분모에서 함께 제외한다. 최근 분기에 유효 쌍이 없어도 과거 분기로 이동하지 않는다. 1~2곳이면 해당 자료만 산정하고 부족 안내를 표시한다. 0곳이면 값 없음이다. 일부 업종이 제외된 경우 유효한 업종만 합산하며 제외 수를 표시한다.

## API와 화면
GET /api/v2/location-reference 의 sales.top_markets_estimate를 추가한다. method=top3_markets_by_store_count_v1, source_quarter, status/reason, eligible_market_count, selected_market_count, excluded_item_count, total_sales, total_store_count, metric, markets를 제공한다. markets에는 실제 선정 상권 코드/이름/대상 업종/합계/점포 수/점포당 값이 순위순으로 들어간다. DTO에서 원자료와 동일한 규칙으로 재계산하여 선정/순위/명칭/분자/분모를 검증한다.
기존 per_store_average와 분포 필드는 과거 소비자를 위해 보존한다. 새 FE 대표값은 top_markets_estimate.metric만 사용한다. 새 계약에서 값이 없으면 전체평균/중앙값으로 대체하지 않는다. 새 계약이 없는 구버전 서버만 기존 UI를 유지한다. 새 값에는 과거 히스토그램을 표시하지 않는다. 금액 아래에 실제 선정 이름으로 '○○ · ○○ · ○○ 상권의 매출액을 토대로 추정했습니다.'를 표시한다. 자료 분기, 사용 상권 수, 접을 수 있는 계산 기준을 제공한다. 원자료 리스트에는 반영/상위 3곳 외 자료를 구분한다.

## 해석 및 범위
상권·업종별 합계로 만든 참고값이다. 개별 점포 매출/중앙값/정규분포/월매출을 추정하지 않는다. 상권 간 점포 중복 제거는 하지 않는다. DB/원천/환경/생활인구/AI 입력은 변경하지 않는다. 추가 API키나 자료는 필요 없다.

## 검증 계획
불균등 점포 수, 4곳 중 3곳 선택, 복수 업종 상권 통합, 동률 순서, 부족/빈 결과, 0원, 누락/분기 혼합, DTO 위조 거부를 검증한다. FE 선정 명칭/합계/자료 없음 및 구계약 호환을 검증한다. 실제 DB 복원본 읽기 전용 대조, 일반/통합 테스트, lint/type/build, Claude 실제 MD 검토 후 정상 PR/CI/배포 절차를 따른다.

## Claude 검토
판정: **REVISE**

검토 범위: 사용자가 대화에 첨부한 BE `top_markets_sales.py`/`per_store_sales.py`/`location_reference.py`/관련 테스트, FE 타입/`LocationReferenceView.tsx`/`SalesDistributionChart(.test).tsx` 코드를 정적으로 읽고 검토함. 테스트·lint·build는 실행하지 않았음(결과 주장 없음).

### 결정사항과 일치하는 부분 (확인됨)
- 동일 기준 분기(`primary`)만 사용, 과거 분기 이동 없음. 상권별 업종 합산 후 `(-점포 수, market_code)` 정렬, 최대 3개의 서로 다른 상권 선정. market_code가 7자리 고정이므로 문자열 오름차순 = 숫자 오름차순.
- 대표값 = 선정 상권 매출 합 / 점포 수 합(`metric(sales, stores)`). 중앙값·평균의 평균·분포를 쓰지 않음.
- 0원 매출 + 양수 점포는 `per_store_metric`이 생성되어 포함되고, 누락/0점포/store 매핑 충돌은 `per_store_metric is None`으로 분자·분모에서 함께 제외됨.
- `per_store_average`는 변경 없이 유지됨(테스트 1에서 11999 확인).
- DTO는 `top_markets_estimate(self.items, primary_quarter)`로 전체 dict를 재계산·동등 비교하므로 선정/순위/명칭/분자/분모/업종/상태 위조가 거부됨.
- FE는 새 계약이 있으면 `top_markets_estimate.metric`만 표시하고, 값이 없을 때 중앙값/전체평균으로 대체하지 않으며 히스토그램을 렌더하지 않음. 선정 이름 출처 문장, 자료 분기, 사용 상권 수, 접이식 계산 기준, 3곳 미만 안내, 제외 수, 원자료 목록의 반영/상위 3곳 외 구분이 구현됨.
- 테스트 기대값 손계산 결과 일치: 2000/150, 동률 케이스 `["3110003","3110001","3110002"]`·650/65, 0원·누락·타 분기 케이스, 빈 결과 케이스.

### 수정 필요 (차단)
1. **동일 상권코드에서 상권명이 다른 경우 API 전체 실패**: `top_markets_sales.py`의 `raise ValueError("inconsistent market name")`가 `attach()` 안에서 발생하면 위치 참고자료 응답 전체가 500/검증 오류가 됨. 문서 결정("매핑 충돌은 분자와 분모에서 함께 제외")과 맞지 않음. 해당 상권(또는 충돌 행)을 제외하고 `excluded_item_count`/reason에 반영하거나, 이 경우를 의도적으로 실패시킬 것이라면 그 결정을 문서에 명시하고 테스트를 추가할 것.
2. **FE 검증 계획 미충족**: 첨부된 FE 테스트는 구 히스토그램(`SalesDistributionChart`)용뿐임. `LocationReferenceView`에 대해 다음 항목의 테스트가 없음: (a) 선정 상권 이름 문장 `A · B · C 상권의 매출액을 토대로 추정했습니다.`, (b) 계산 기준의 합계, (c) `metric: null` 새 계약에서 '자료 없음' 표시 및 중앙값/히스토그램 미표시, (d) 1~2곳 부족 안내·제외 수, (e) `top_markets_estimate`가 없는 구계약에서 기존 UI 유지, (f) 원자료 목록의 '추정 매출 산정에 반영한 상권'/'점포 수 상위 3개 상권 외 참고자료' 구분.
3. **production 코드의 `assert`**: `top_markets_sales.py`의 `assert item.metric is not None and item.store_reference is not None`는 `python -O`에서 제거됨. 명시적 `if ...: raise ValueError` 또는 조건 필터로 바꿀 것.

### 수정 권장 (비차단)
4. **null과 미존재 구분**: FE 타입은 `top_markets_estimate?: ... | null`이고, 화면은 `!topMarkets`(null 포함)일 때 구 중앙값 UI로 돌아감. BE 스키마도 `per_store_average`는 있고 `top_markets_estimate=None`인 payload를 허용함. "구버전 서버만 기존 UI" 결정을 보장하려면 FE에서 `'top_markets_estimate' in data.sales`(키 미존재)일 때만 구 UI를 쓰도록 하거나, BE에서 `per_store_average`가 있으면 `top_markets_estimate` 생략/null을 거부할 것.
5. **BE 테스트 공백**: 다음 테스트를 추가할 것. 0점포(`zero_store_count_with_sales`)·store 매핑 충돌 행이 top3 합계에서 제외되는 경우, 2곳만 유효한 경우 `status="partial"`/`reason="fewer_than_three_markets"`, `analysis_period` 모드, 위조 케이스(순위 뒤바꿈, `industry_codes` 변조, `markets[i].metric`/`metric` 변조, `method`/`source_quarter` 변조). 그리고 실제 API로 `top_markets_estimate`를 DB 값과 대조하는 통합 테스트도 없음(`test_per_store_average.py`는 기존 지표만 검증함).
6. **reason 우선순위 정보 손실**: 제외 행이 있고 상권도 3곳 미만이면 `reason`은 `partial_source_rows`만 남음. FE는 count로 둘 다 안내하므로 화면은 문제없지만, API 소비자를 위해 문서에 우선순위를 명시하거나 reason 목록으로 제공하는 방안을 검토할 것.
7. **`excluded_item_count` 범위**: 선정되지 않은 상권(4위 이하)의 제외 행도 포함되어 `status=partial`이 될 수 있음. 의도라면 문서에 "기준 분기 전체 후보 대비 제외 수"라고 정의를 명시할 것. 또한 매출 자체가 없는(`metric is None`) 항목은 포함되지 않는다는 점도 문서화할 것.
8. **FE 표기**: 계산 기준의 `total_sales`/`total_store_count`와 상권별 값이 천 단위 구분 없이 원문 문자열로 출력됨(예: `2000000원`). BigInt 기반 포맷을 권장함. 새 계약에서 제외 항목 라벨이 여전히 '평균 계산 제외'로 나와서 대표값 용어와 어긋남.
9. **포맷/lint 위험**: `LocationReferenceView.tsx`의 새 블록에 100자를 넘는 JSX 줄과 인라인 삼항 `) : <p ...>`가 있음. Prettier check가 CI에 있다면 실패할 가능성이 큼. 포맷터 실행 후 커밋할 것.
10. **strict 동등 비교의 한계(경미)**: `top_markets_estimate`가 `dict[str, Any]`라서 `True == 1` 같은 타입 위조는 동등 비교를 통과할 수 있음. 필요하면 전용 Pydantic 모델(strict)로 정의할 것.

### 범위
DB/원천/생활인구/AI 입력 변경은 첨부 코드에서 보이지 않았고, 무관한 변경도 발견하지 못함.

## Codex 1차 검토 반영
동일 상권코드 명칭 충돌은 해당 상권 전체를 제외하여 다른 상권/생활인구 응답을 보존한다. assert를 명시적 입력 오류로 바꿨다. FE View 테스트와 실제 DB 통합 검증을 추가했다. 제외 수는 기준 분기의 매출 숫자가 있는 후보 전체 대비 유효하지 않은 행의 수다(4위 이하 상권도 포함). 매출이 없는 행/다른 분기는 이 수에 포함되지 않는다. reason은 자료 없음, 제외 행 있음, 3곳 미만 순서로 우선하며 FE는 수를 이용해 부족과 제외를 동시에 표시한다. 새 필드가 명시적 null이면 자료 없음으로 표시하고 과거값을 쓰지 않는다. DTO 비교는 정렬 JSON으로 수행하여 bool/int 등의 타입 변조도 거부한다.

## Claude 2차 검토
판정: **REVISE** (산식·BE 검증은 결정과 일치함. FE 표시 오류 1건, 테스트/CI 공백 때문에 REVISE로 판정함)

검토 범위: 대화에 첨부된 BE `top_markets_sales.py`/`per_store_sales.py`/`schemas/location_reference.py`/`tests/test_top_markets_sales.py`/`tests/test_per_store_sales.py`/`tests/integration/test_per_store_average.py`, FE `types/locationReference.ts`/`LocationReferenceView.tsx`/`LocationReferenceView.test.tsx`/`SalesDistributionChart.tsx`를 정적으로만 읽음. 테스트·lint·type·build·DB 대조는 실행하지 않았고 결과도 주장하지 않음.

### 1차 지적 반영 확인
- #1 해결: 명칭 충돌 상권은 `names` 집합으로 상권 전체를 제외하고 예외를 던지지 않음. `test_conflicting_market_names_exclude_entire_market_without_failing_response`의 기대값(선정 `3110002`, 제외 2)을 손으로 계산해 보니 일치함.
- #3 해결: `assert`가 명시적 `ValueError`로 바뀜.
- #4 해결: FE가 `'top_markets_estimate' in data.sales`일 때만 새 계약으로 판단하고, 명시적 null이면 '자료 없음'을 표시함(구 중앙값으로 대체하지 않음).
- #5 BE 부분 해결: 0점포/매핑 충돌 제외(300/30, 제외 2), 2곳 `fewer_than_three_markets`/`partial`, `analysis_period`(20234, 2^63 합계), 순위/업종/metric/method/분기/bool 위조 테스트를 손으로 계산해 보니 모두 맞음.
- #6·#7 해결: reason 우선순위와 `excluded_item_count`의 정의를 문서에 적음.
- #10 해결: `json.dumps(sort_keys=True)`에서 `False`→`false`, `0`→`0`로 직렬화되어 서로 다르게 나오므로 bool 위조가 거부됨.
- 산식 재확인: 같은 분기만 사용하고, 업종을 먼저 합산한 뒤 `(-stores, market_code)` 순으로 최대 3곳을 고름. 대표값은 매출 합 ÷ 점포 수 합이고, 0원은 유효, 누락/0분모는 분자·분모에서 함께 제외됨. 과거 분기로 이동하지 않으며 `per_store_average`는 변경되지 않음. 결정사항과 일치함.

### 수정 필요 (차단)
1. **명칭 충돌로 제외된 행을 FE가 '상위 3개 상권 외'로 잘못 표시함**: 명칭 충돌 상권의 행도 `per_store_metric`이 있으므로 `average_contribution.status == 'included'`임. FE는 이 행이 `topMarkets.markets`에 없다는 이유로 '점포 수 상위 3개 상권 외 참고자료'로 표시함. 그런데 실제 사유는 순위가 아니라 명칭 충돌이고, 이 행은 `excluded_item_count`에도 들어가 있음. 같은 화면에서 "N개 항목 제외"와 "상위 3곳 외"가 동시에 성립하는 셈이라 모순됨. 명칭 충돌 상권만 있는 경우에는 상단에 "상권이 없어요"가, 목록에 "상위 3개 상권 외"가 함께 나옴. 해결 방안: BE가 항목별 `top_markets_contribution`(selected/not_top3/excluded+reason)을 제공하고 DTO에서 함께 재계산·검증하는 방안을 권장함. 최소한 FE에서 같은 `market_code`에 서로 다른 `market_name`이 있으면 '자료 정보 불일치로 제외'로 표시해야 함.
2. **FE 테스트가 핵심 결정을 실제로 검증하지 못함** (`LocationReferenceView.test.tsx` 첫 번째 테스트):
   - (a) `top_markets_estimate = null`인 경우를 `per_store_average` 없이 검사함. 그래서 '구 중앙값/전체평균으로 대체하지 않음'이 증명되지 않음. `per_store_average`(가중 중앙값·히스토그램 포함)를 함께 넣고, `metric: null`인 경우와 `null`인 경우 모두에서 구 값·'점포 수 기준 매출 분포'·'가중 중앙값'이 없음을 단언해야 함.
   - (b) 검증 계획에 있는 원자료 목록 구분('추정 매출 산정에 반영한 상권' / '점포 수 상위 3개 상권 외 참고자료')과 `excluded_item_count > 0` 안내 문구의 테스트가 없음.
   - (c) 빈 결과 fixture가 `status: 'ready'`·`selected_market_count: 1`인 채로 `metric: null`이라 BE에서 나올 수 없는 상태임. `no_data`/0/[]로 맞춰야 함.
3. **Prettier 실패 가능성**: 위 테스트 블록의 `})` 바로 앞에 빈 줄이 있음(`expect(...).toContain('자료 없음')` 다음). Prettier는 블록 끝의 빈 줄을 제거하므로 `format:check`가 CI에 있으면 실패함. 1차 #9(새 JSX 블록 포맷)도 포함해 포맷터를 실행한 뒤 커밋해야 함.
4. **통합 테스트가 상위 3곳 선정을 실제로 검증하지 못할 가능성**: `test_per_store_average.py`는 `update(MarketStore).values(market_name=name)`로 **모든** 점포 행의 상권명을 `3110000`의 명칭으로 덮어씀. fixture에 상권이 여러 개 있으면 다른 상권은 `store_mapping_conflict`가 되어 사실상 1곳만 남음. 이 경우 순위·동률·업종 합산이 실제 API 경로에서 검증되지 않음. 상권별로 각각 이름을 맞추고, `included`가 4개 이상 상권을 포함한다는 전제를 `assert`로 확인해야 함. 또한 테스트가 API 응답의 점포 수로 기대값을 만들고 있어, 상위 3곳 계산이 DB와 독립적으로 대조되지 않음. DB에서 조회한 `total_stores`로 순위와 합계를 다시 계산해 비교하고, `top["metric"]`과 `markets[*].market_name`도 단언해야 함. 덧붙여 이 테스트는 fixture DB에 `UPDATE`를 실행하므로 검증 계획의 "실제 DB 복원본 읽기 전용 대조"와는 다른 것임. 복원본 대조를 실제로 수행했다면 그 근거(조회 쿼리, 대조 결과)를 문서에 남기고, 수행하지 않았다면 미수행으로 명시해야 함.

### 수정 권장 (비차단)
5. **업스트림 자료 없음 시 reason 불일치**: `keys`가 없으면(`source_not_loaded` 등) `per_store_average`는 블록의 reason을 그대로 쓰는데, `top_markets_estimate`는 `no_valid_sales_store_pairs`를 반환함. 그 결과 FE가 "같은 분기의 매출과 점포 수를 함께 확인할 수 있는 상권이 없어요"라고 표시하는데, 실제 원인과 다를 수 있음. 업스트림 사유를 전달하거나 FE에서 `data.sales.reason`을 우선 사용하고, 이 경우의 테스트를 추가할 것.
6. **`eligible_market_count` 정의**: 명칭 충돌로 제외된 상권은 이 수에 포함되지 않음. 문서의 필드 정의에 이 점을 추가할 것.
7. **null/생략 직렬화 확인**: FE는 키의 존재 여부로 신·구 계약을 구분함. 응답 직렬화에 `exclude_none`(또는 `response_model_exclude_none`)이 적용되어 있다면 새 서버의 null이 생략되어 구 UI로 돌아감. 라우터 설정을 확인하고, 실제 API 응답에 키가 항상 존재한다는 통합 단언을 추가할 것.
8. **BE 스키마 테스트 추가**: `top_markets_estimate`가 있는데 `per_store_average`가 None인 payload의 거부, 명칭 충돌 상권이 점포 수 1위일 때 다음 상권들로 채워지는지 확인하는 테스트를 추가할 것.
9. **1차 #8 미반영**: 계산 기준의 합계·상권별 값이 천 단위 구분 없이 출력됨(테스트도 `2000원`을 그대로 단언함). 새 계약에서도 제외 항목 라벨이 '평균 계산 제외'로 나옴. BigInt 포맷을 쓰고 라벨을 '추정 매출 산정 제외'로 바꾸는 것을 권장함.

### 범위
첨부된 코드에서 DB 스키마/원천/생활인구/AI 입력 변경과 무관한 작업은 발견되지 않음. 이 검토는 문서 추가 외에 코드를 수정하지 않았고 명령도 실행하지 않음.

## Codex 2차 최종 판단
명칭 충돌 행은 화면에서도 순위 외 자료가 아니라 자료 불일치 제외로 구분한다. View 테스트에서 기존 가중 중앙값 객체와 새 계약을 동시에 넣어 새 metric 없음/null일 때 기존 금액/그래프를 표시하지 않음을 확인한다. 부족/제외/선정 여부 테스트를 보완하고 formatter를 실행했다.
격리 통합 fixture는 각 상권의 명칭을 개별 경계명과 맞추고, DB에서 읽은 점포 수로 합계를 독립 검증한다. 이 fixture는 적은 상권을 사용하는 API 연결 검증이며, 4곳 이상 순위와 동률/복수 업종은 17개 단위 테스트로 검증했다. 별도로 실제 복원 DB 15곳을 읽기 전용 API로 조회하여 결과 원자료 행을 독립 합산/정렬한 값과 선정 상권/분자/분모가 일치함을 확인했다. 복원본에 DML/DDL을 실행하지 않았다. 해당 15곳 검증은 원자료 자체의 공식 정확성 재검증이 아닌 API 계산 연결 검증이다.
eligible_market_count는 명칭 충돌 제외 후 후보 수다. 새 필드 null은 자료 없음이고 실제 attach 응답은 항상 계산 객체를 포함한다. 상위 자료 전체가 없는 경우에는 원자료 블록 상태가 별도로 제공되며 대표 추정값은 없음으로 표시한다. 계산 상세의 원문 정수 문자열은 정밀도를 보존한다.

## Claude 3차 검토
판정: **PASS** (최신 결정의 산식, API 계약, DTO 검증, FE 표시 원칙이 일치함. 아래 항목은 머지를 막지 않는 후속 보완 사항임)

검토 범위: 대화에 첨부된 BE `top_markets_sales.py`/`per_store_sales.py`/`schemas/location_reference.py`/`tests/test_top_markets_sales.py`/`tests/test_per_store_sales.py`/`tests/integration/test_per_store_average.py`, FE `types/locationReference.ts`/`LocationReferenceView.tsx`/`LocationReferenceView.test.tsx`/`SalesDistributionChart.tsx`를 정적으로만 읽음. 테스트·lint·type·build·formatter·DB 대조는 실행하지 않았고, 그 결과도 주장하지 않음. Codex가 적은 formatter 실행과 실제 복원 DB 15곳 대조는 근거 자료를 받지 못해 확인하지 못함.

### 결정사항 일치 재확인
- 같은 기준 분기의 후보(`metric` 있음)만 사용하고, `per_store_metric`이 있는 항목(양수 점포, 매핑 일치)만 유효로 봄. 상권별로 업종을 먼저 합산한 뒤 `(-stores, market_code)` 순으로 서로 다른 상권을 최대 3곳 선정함. 대표값은 선정 상권 매출 합 ÷ 점포 수 합(`metric`)이고, 중앙값·정규분포·개별 점포 매출을 쓰지 않음. 과거 분기로 이동하지 않음.
- 0원 매출 + 양수 점포는 포함됨(`exact_zero`). 누락/0점포/매핑 충돌/명칭 충돌은 분자·분모에서 함께 제외되고 `excluded_item_count`에 들어감. 1~2곳이면 `partial`이고, 0곳이면 `metric=None`, `total_*=None`, `markets=[]`임(`metric(0,0)` 호출 없음).
- DTO는 `per_store_average`가 없으면 `top_markets_estimate`를 거부하고, 있으면 `primary_quarter`로 다시 계산한 결과와 정렬 JSON으로 비교함. 순위·명칭·업종·분자·분모·method·분기·bool 타입 위조를 거부함. `per_store_average`의 계산 경로와 값은 바뀌지 않았음(기존 테스트 유지, 11999 단언).
- FE는 키가 있으면 새 계약으로만 표시함. `metric` 없음/null일 때 기존 금액·가중 중앙값·히스토그램을 쓰지 않음. 선정 이름 출처 문장, 자료 분기, 사용 상권 수, 접이식 계산 기준, 부족·제외 안내, 목록의 반영/상위 3곳 외/명칭 불일치 제외 구분, 새 계약의 '추정 매출 산정 제외' 라벨이 구현됨. 구계약(키 없음)에서는 기존 UI가 그대로임.
- 2차 차단 #1: FE의 명칭 충돌 판정 조건(같은 코드·분기, `per_store_metric` 있음, 이름 다름)이 BE `names` 집합 규칙과 같음. 해결됨.
- 2차 차단 #2(a)(b): 가중 중앙값 객체를 함께 넣고 `metric:null`/`null` 두 경우에 기존 값·그래프가 나오지 않음을 단언함. 반영/상위 3곳 외 구분과 제외 수 안내도 단언함. 해결됨.
- 2차 차단 #4: 통합 fixture가 상권별 경계명으로 맞춰졌고, DB `total_stores`로 순위와 합계를 독립적으로 다시 계산하며 이름도 단언함. 적은 상권 수라는 한계는 문서에 명시됨. 해결된 것으로 봄.
- 단위 테스트 기대값 손계산: 2000/150·eligible 4·ready, 업종 합산 후 3110003(25)·3110001·3110002 = 650/65, 0원 1곳·제외 1·partial, 과거 분기 미이동, 매핑 충돌+0점포 = 300/30·제외 2, 2곳 `fewer_than_three_markets`, 명칭 충돌 상권(동률 1위 후보) 제외 후 3110002만 선정·제외 2, `analysis_period` 20234·2^63. 모두 일치함. 테스트 수는 파라미터 포함 17개로 문서 기술과 맞음.

### 후속 보완 권장 (비차단)
1. **FE 명칭 충돌 라벨 테스트 없음**: '자료 정보 불일치로 추정 매출 산정 제외' 분기는 구현됐지만 `LocationReferenceView.test.tsx`에 이를 단언하는 케이스가 없음. 같은 `market_code`·분기에 이름이 다른 두 included 항목을 넣고, 이 라벨이 나오며 '상위 3개 상권 외'는 나오지 않음을 단언할 것.
2. **빈 결과 fixture가 BE에서 나올 수 없는 상태**: `status:'no_data'`인데 `reason:null`, `eligible_market_count:8`, `excluded_item_count:2`가 그대로 남아 있음. BE 규칙상 `reason='no_valid_sales_store_pairs'`, `eligible_market_count=0`이어야 함. 이 상태에서는 목록에 '상위 3개 상권 외 참고자료'도 함께 렌더됨. 화면 단언 자체에는 영향이 없지만, 실제 계약과 맞게 fixture를 고칠 것. 첫 fixture의 상권별 합(100×3)과 전체 합(2000)이 맞지 않고 `market_code`가 7자리가 아닌 점도 같이 정리하면 좋음.
3. **자료 없음일 때 제외 수 미표시**: `metric`이 null이면 `excluded_item_count > 0` 안내가 렌더되지 않음. 예를 들어 후보가 모두 0점포/누락이면 "상권이 없어요"만 나옴. 결정의 "제외 수를 표시"를 빈 결과에도 적용할지 정하고, 적용한다면 안내를 분기 밖으로 옮길 것.
4. **업스트림 사유 미전달(2차 #5 유지)**: `keys`가 없을 때(`source_not_loaded`, `outside_coverage` 등) 카드에 "같은 분기의 매출과 점포 수를 함께 확인할 수 있는 상권이 없어요"가 나오고, 목록 영역에는 `unavailable(data.sales.reason)`가 따로 나옴. 문구가 실제 원인과 다를 수 있음. Codex 판단(블록 상태 별도 제공)은 수용 가능하지만, `data.sales.status === 'no_data'`일 때 카드 문구를 일반 '자료 없음'으로 바꾸는 방안을 권장함.
5. **명칭 충돌 판정 범위**: BE `names`는 유효 행만으로 만듦. 같은 상권의 다른 업종 행이 이름이 달라 `store_mapping_conflict`로 빠지면, 남은 유효 행으로 상권이 그대로 선정됨. 결정상 충돌 행만 제외되므로 산식 위반은 아니지만, 이 동작을 의도한 것인지 문서에 한 줄 적어 둘 것.
6. **통합 테스트 견고성**: (a) 검증용 `select(MarketStore.total_stores)`에 `version_id` 조건이 없어, fixture에 버전이 여러 개면 다른 버전 값을 읽을 수 있음. (b) `MarketArea`에 같은 코드의 행이 여러 개면 scalar subquery가 실패할 수 있음. (c) update 전 첫 요청에서 `top_markets_estimate` 키가 존재하고 `metric is None`인지 단언하면 2차 #7(키 생략 직렬화) 우려도 실제 API 경로에서 확인됨.
7. **스키마 거부 테스트(2차 #8 일부)**: `per_store_average=None` + `top_markets_estimate` 존재 payload의 거부는 코드상 처리되지만 테스트가 없음. 한 줄 케이스로 추가할 것.
8. **FE method 확인**: FE는 `method`를 확인하지 않고 표시함. 이후 `v2`가 나왔을 때 문구가 틀어지지 않도록 `method === 'top3_markets_by_store_count_v1'`일 때만 새 카드를 표시하고, 그 외에는 '자료 없음'을 표시하는 방안을 권장함.
9. **실제 복원 DB 15곳 대조 근거**: 결과 요약(대상 위치 수, 비교 항목, 불일치 0건)이나 비공개 산출물 경로를 PR에 남기면 검증 계획 충족이 추적 가능해짐. 개인정보·원천 원문은 포함하지 말 것.
10. **천 단위 표기(1·2차 유지)**: 원문 정수 문자열을 유지한 Codex 판단은 수용함. BigInt `toLocaleString`도 정밀도를 보존하므로 가독성 개선은 선택 사항으로 남김.

### 범위
첨부 코드에서 DB 스키마/원천/환경/생활인구/AI 입력 변경이나 무관한 작업은 발견되지 않음. 이 검토는 이 문서에 내용을 추가한 것 외에 코드를 수정하지 않았고, 명령·테스트·네트워크·DB 접근도 하지 않음.
