# 상권·업종별 점포당 추정매출 중앙값 검토·적용 (#203)

최신 구현: 대표값의 표본 단위는 상권·업종 행이다. FE 4개 미만에서는 산포 수치를 숨긴다. 검토 이력 아래 최종 보완/판정이 이전 REVISE의 현재 상태를 대체한다.

사용자는 전체매출/전체점포 수보다 극단값 영향을 줄이는 대표값을 요청했다. 같은 분기의 유효 `(상권,업종)`별 `매출/점포 수`를 정확한 Fraction으로 정렬한 비가중 중앙값을 대표값으로 채택한다. 홀수는 가운데 값, 짝수는 가운데 두 값의 산술평균이다. 점포 수 가중 중앙값은 큰 상권을 다시 강하게 반영하므로 채택하지 않는다. 이것은 설계 판단이며 원자료로 개별 점포 매출 분포를 복원한 결과가 아니다.

분산은 중앙값을 계산하거나 선택하는 공식이 아니다. 임의 분산 임계값이나 이상치 삭제 없이 항상 같은 중앙값 규칙을 쓴다. 기존 가중평균과 합계/분모·포함/제외 키는 호환·비교용으로 보존한다. 혼합 분기/누락/0분모/명칭충돌 규칙은 #194/#198과 같다. 실제0도 포함하고 중첩 상권도 중복 미제거로 표시한다.

분포 객체는 sample_unit=market_industry_row, weighting=equal_reference_rows, individual_store_median=false를 명시한다. 대상 수는 점포 수가 아닌 상권·업종 항목 수다. 0개이면null, 1개이면 그 값, 2개이면 두 값 중간값이다. 4개 미만은 단순 안내를 표시하며, 이를 통계적 신뢰도나 신뢰구간으로 해석하지 않는다.

Q1/Q3는 정렬한 자료의 중앙값을 제외한 하위/상위 절반의 중앙값(median-of-halves)으로 정한다. 1개는 Q1=Q3=중앙값, IQR=Q3-Q1이다. 유한 표본의 선택한 사분위 정의를 API에 노출한다. 분산은 현재 참조항목들에 대한 Σ(x-평균)²/n의 기술통계이며 n-1 추정분산·전체 점포의 분산이 아니다. Decimal50으로 계산하고 최초 값에 대한 정확한 차이를 먼저 구해 큰 금액/동일 비율의 반올림 오차를 줄인다. 분산 단위는 (원자료 원/점포)²다.

대표값은 새 distribution.median이며 기존 per_store_average.metric은 가중평균으로 그대로 둔다. 대표/각 분기에 distribution을 추가하고 전체 snapshot token에 포함한다. 최종 DTO validator가 포함 항목에서 분포를 재계산하고 대표 투영도 확인한다. API 입력/DB/환경/AI/인구는 변경하지 않는다.

FE는 중앙값을 제목과 함께 대표로 표시하고 비교 접기 영역에 가중평균·분산·IQR을 둔다. 기존 서버에서 새 필드가 없으면 평균이라는 기존 제목을 유지해 평균을 중앙값으로 오표시하지 않는다. 같은 컴포넌트를 분석·종합·PDF에서 사용한다. 원자료 기간 미확정/중복 가능성/개별 점포 중앙값 아님을 표시한다.

통계 근거: [NIST 산포 측도](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm), [NIST 상자그림과 사분위](https://itl.nist.gov/div898/handbook/prc/section1/prc16.htm). 중앙값과IQR은 극단값에 상대적으로 덜 민감한 요약이라는 근거이며 현재 자료에 대한 정규성·독립성·모집단 대표성 보증은 아니다.

수용시험: 빈/1/2/홀짝/실제0/반올림1원미만, 큰 정수 비율 정렬, 극단값/순서독립, 동일 값 분산0, 알려진 사분위/분산, 분기·부분/제외 집합 동일, API/FE/보고서 표시와 이전 버전 호환. 구현·검수/검사·공개반영의 실제 결과를 구분한다.

## 실제 Claude 검토 및 실행 기록

### 구현 검토 (Claude, 2026-11-16) — 판정: **REVISE**

검토 범위와 한계: 사용자가 제공한 코드(`app/services/sales_distribution.py`, `app/services/per_store_sales.py`, `app/schemas/location_reference.py`, `app/services/location_reference.py`, 모델/ETL 일부, 단위·통합 테스트, FE `LocationReferenceView`)를 읽고 검토만 했다. 셸·테스트·빌드·DB·네트워크는 실행하지 않았고 코드는 수정하지 않았다. 아래 내용 중 "테스트 통과", "배포됨"을 뜻하는 것은 없다. FE 타입 정의, 종합/PDF 화면, 보고서 저장 경로는 제공되지 않아 확인하지 못했다.

#### 설계와 일치함 (확인함)
- 중앙값: `Fraction(s, n)`을 정확히 정렬하고, 홀수 개는 가운데 값, 짝수 개는 가운데 두 값의 평균을 쓴다. 가중치가 없고 개별 점포 단위가 아니며, `individual_store_median=False`와 `weighting=equal_reference_rows`를 명시한다. 0개는 `None`, 1개는 그 값, 2개는 두 값의 중간값으로 설계와 같다.
- Q1/Q3: `values[:n//2]`와 `values[(n+1)//2:]`의 중앙값을 쓰므로 홀수일 때 가운데 값을 뺀 median-of-halves가 맞다. n=1이면 Q1=Q3=중앙값이고, IQR은 정렬 후 계산해 음수가 될 수 없다(`ratio`의 음수 가드도 만족).
- 분산: 최솟값과의 정확한 Fraction 차이를 Decimal50으로 바꾼 뒤 두 단계(two-pass)로 Σ(x-평균)²/n을 계산한다. 이상치 제거나 임계값에 따른 방식 전환은 없다. 다만 이후 단계에서 반올림이 일어나므로 "정확한 분산"이 아니라 "Decimal50 근사"다. 설계 문구와 모순되지는 않는다.
- 같은 분기 원칙: `group(quarter)`에서 `per_store_metric is not None`인 같은 분기 항목만 쓴다. 0분모, 명칭 충돌, 점포 행 누락, 매출 없음 항목은 가중평균과 똑같이 빠진다. 다른 분기 항목은 그 분기의 group 분포에만 들어간다.
- 입력 범위: 금액은 2^63-1 이하, 점포 수는 1 이상 2^31-1 이하(Integer 컬럼), 항목은 500개 이하로 attach/SourceNumber 제약과 맞다. 중앙값 분자가 약 2^95여도 `Decimal(int)`는 정확하고, 나눗셈만 50자리로 반올림된다.
- 대표값 투영(top-level `distribution` = primary group)과 snapshot token(`data.model_dump` 전체를 해시) 포함을 확인했다. 기존 `metric`(가중평균), 합계, 분모, `included_item_keys`도 보존된다.
- FE 하위 호환: `representative_method`와 `distribution`이 모두 없으면 "평균" 제목과 합계÷합계 문구를 유지하므로, 평균을 중앙값으로 잘못 표시하지 않는다.

#### 차단 사항 (수정 필요)
1. **최종 validator가 표본 수와 항목 정합성을 강제하지 않음** (`app/schemas/location_reference.py`의 `SalesBlock.coherent`)
   - 분포를 재계산할 때 `if i.metric and i.store_reference` 필터를 생산 코드와 똑같이 쓴다. 그래서 포함 키에 `store_reference=None`인 항목이 있으면 조용히 빠지고, `sample_count < included_item_count`인 분포가 통과한다. `store_reference.status="no_data"`(total_stores=None)가 포함되면 `int(None)`에서 ValueError가 아닌 TypeError가 난다.
   - 추가할 검사: `distribution.sample_count == included_item_count`, 포함 항목마다 `store_reference.status == "ready"`·`average_contribution.status == "included"`(primary)·`per_store_metric == metric(s_i, n_i)`. 실패하면 ValueError로 통일한다.
2. **이전 payload 재검증 호환성 미확인/불일치**
   - 최상위 검사는 `avg[key]`(KeyError)를 쓰고 group 검사는 `group.get("distribution")`을 쓴다. `distribution`이 없는 #194/#198 시절 저장 snapshot을 `SalesBlock`으로 다시 검증하면 KeyError나 `invalid sales distribution`으로 실패한다.
   - 보고서나 PDF가 저장된 payload를 BE 모델로 다시 읽는 경로가 있는지 확인해야 한다. 경로가 있다면 `representative_method`가 없는 레거시 블록은 분포 검사를 건너뛰도록 분기한다. 아울러 `per_store_average.rule_version`(`source-row-store-weighted-v1`)과 `FORMAT_VERSION`이 그대로인데 대표값의 의미가 바뀌었으므로, `representative_method`만으로 충분한지 버전 상향이 필요한지 결정하고 기록한다.
3. **FE 소표본 사분위·분산 표기가 오해를 부름** (`LocationReferenceView`)
   - n=1이면 "사분위 범위 X ~ X", "항목 간 분산: 0"이 표시되어 "산포 없음"으로 읽힌다. n=2이면 "사분위 범위"가 실제로는 최솟값~최댓값이고, n=3이면 Q1/Q3가 최솟값/최댓값이다.
   - `limited_reference_count`(n<4)일 때는 사분위, IQR, 분산을 숨기거나 "하위·상위 절반의 중앙값(항목 n개)"처럼 정의대로 표기한다. 안내 문구 "지역 전체를 대표하기 어려워요"도 고친다. 이 문구는 n≥4면 지역을 대표한다는 반대 함의를 만들기 때문에, "비교 항목이 4개 미만이에요" 같은 중립 사실로 바꾸는 편이 낫다.
4. **FE 라벨 불일치(중앙값 모드)**
   - 제목 "상권별 점포당…"은 실제 표본 단위(상권·업종 행)와 다르다. 음식점 카테고리에서는 한 상권에서 최대 4개 업종 행이 각각 같은 비중으로 들어가므로 "상권·업종별"로 써야 한다.
   - 항목 카드의 제외 상태가 여전히 "평균 계산 제외"다. "대표값 계산 제외"로 바꾼다.
   - 다른 분기 목록에서 `g.distribution`이 null이면 "가중평균 자료 없음"으로 나온다. `useMedian` 기준으로 "중앙값 자료 없음"을 표시한다.
5. **수용시험 미충족(제공된 테스트 기준)**
   - 설계 17행의 항목 가운데 다음이 없다: 홀수 n(3, 5)의 알려진 Q1/Q3, n=2 사분위, `limited_reference_count=True`, 중앙값 표시 반올림 경계(예: 0.5 → "1원 미만", x.5 반올림).
   - `attach` 수준의 distribution 검증도 없다. 여기에는 분기별 group 분포, 부분/제외 항목이 분포에서 빠지는지, 포함 키 집합과 분포 표본이 같은지가 들어간다.
   - 분포·투영을 변조한 payload를 validator가 거부하는지 확인하는 테스트, 통합 테스트의 `distribution.median` 대조, FE·종합·PDF 표시와 이전 버전 호환 테스트도 없다.
   - 이 테스트들을 추가하고, 실행 결과는 실행한 사람이 별도로 기록해야 한다.

#### 비차단 권고
- 분산 원값은 최대 50자리 (원/점포)²라 읽기 어렵다. 접기 영역에 두는 것은 맞지만, 표시용으로 표준편차(원/점포)나 IQR만 쓰는 것을 검토한다. `variance.value`의 끝자리 0 정규화가 `ratio`와 다르지만(결정적이라 validator에는 문제없음) 하나로 통일하는 것을 권한다.
- 동일 비중 설계에서는 점포 1~2개짜리 행의 비율도 한 표를 가진다. 중앙값이 이를 어느 정도 흡수하지만, "점포 수가 적은 항목도 같은 비중"이라는 문구를 접기 영역에 추가할 것을 권한다.
- 중첩 상권(관광특구 등) 중복은 문구로 공개되어 있다. 같은 점포가 여러 행에 반영될 수 있으므로 표본이 독립이 아니라는 점은 현재처럼 통계적 신뢰도 해석 금지로 유지한다.

#### 결론
중앙값, median-of-halves 사분위, 모분산(/n) 계산 로직 자체는 설계와 일치한다. 다만 위 1·3·4·5는 수정해야 하고, 2는 저장 payload 재검증 경로를 확인한 뒤 처리해야 한다. 그 전까지 **REVISE**이며, 수정과 테스트 실행 결과가 기록된 뒤 다시 검토한다.


### 검토 지적에 따른 수정 및 확인 (Codex)

1. 포함된 모든 항목의 source metric/ready store reference/양의 분모/같은 분기/per_store_metric 재계산/primary included 상태를 검증한다. 표본 수는 included_item_count와 일치해야 한다. 누락·변조는 ValueError로 거절한다.
2. 기존 저장 보고서/PDF 경로의 검색 결과 BE LocationReference 재역직렬화 경로는 없으며 FE는 조회 응답을 렌더링한다. 그래도 기존 weighted payload 재검증 호환을 유지한다. representative_method/distribution이 모두 없는 레거시는 분포 검증만 생략하며 기존 metric 검증은 유지한다. 새 응답은 반드시 새 marker와 distribution을 함께 검증한다. 기존 rule_version은 가중평균 계산 규칙으로 유지하고 새 representative_method는 대표값 선택 규칙을 버전 관리한다. 전체 payload snapshot hash에는 새 필드가 포함된다.
3. 4개 미만에서는 FE 사분위·IQR·분산 표시는 숨긴다(API는 정의된 기술통계 유지). '4개 미만, 퍼짐 판단 자료가 적음'으로만 설명해 지역 대표성의 보장을 암시하지 않는다.
4. 제목은 상권·업종별로 수정, 제외는 대표값 계산 제외, 다른 분기도 중앙값 모드에 맞춰 표시한다. 점포가 적은 행도 같은 비중임을 명시한다.
5. 홀수3/5 분위수, 2개·0.5/x.5 표시, 혼합 분기·누락 제외, 분포/표본 수/원천/기여/대표 투영 변조 거절 및 이전 payload 읽기 테스트를 추가했다. 실제 실행 29개 통과. FE214+프로필4개 통과. 최종 통합/타입/빌드 결과와 배포 결과는 완료 후 별도 기록한다. Claude가 실행한 테스트가 아니다.

### 수정본 구현 재검토 (Claude, 2026-11-16) — 판정: **REVISE** (소규모, validator 무결성 2건 + FE 라벨 1건)

검토 범위와 한계: 이번 요청에 제공된 현재 코드(`app/services/sales_distribution.py`, `app/services/per_store_sales.py`, `app/schemas/location_reference.py`, `app/services/location_reference.py`, `app/models/market_sale.py`·`market_store.py`, `etl/market_stores/archive.py` 일부, `tests/test_sales_distribution.py`, `tests/test_per_store_sales.py`, `tests/integration/test_per_store_average.py`, FE `LocationReferenceView`)를 읽기만 했다. 셸·테스트·타입검사·빌드·DB·네트워크·에이전트를 실행하지 않았고 코드는 수정하지 않았다. 위 Codex 절의 "29개 통과", "FE214+프로필4개 통과"는 Claude가 확인한 결과가 아니다. 테스트 기대값이 코드와 맞는지는 손으로 추적해 확인했지만, 이는 실행 결과가 아니다. FE 타입 정의(`types/locationReference`), 종합/PDF 화면, FE 테스트 코드는 이번에도 제공되지 않아 확인하지 못했다.

#### 통계 결정과 계산 — 설계와 일치함 (재확인)
- **대표값**: 같은 분기의 유효 `(상권,업종)` 행마다 `Fraction(매출, 점포 수)`를 구하고, 같은 비중으로 정렬한 중앙값을 쓴다. 홀수 n은 가운데 값, 짝수 n은 가운데 두 값의 산술평균이다. 점포 수 가중이 아니며 개별 점포 중앙값도 아니다(`individual_store_median=False`). 기존 `metric`은 Σ매출/Σ점포 가중평균으로 그대로 남아 비교값 역할을 한다. 매출 합계/점포 합계를 대표값으로 쓰던 방식은 중앙값으로 대체되었다.
- **Q1/Q3**: `values[:n//2]`와 `values[(n+1)//2:]`의 중앙값이므로, 홀수일 때 가운데 값을 뺀 median-of-halves가 맞다. n=1이면 Q1=Q3=중앙값, n=2이면 Q1=최솟값·Q3=최댓값이다. 손 계산 결과 [1,2,3]→(1,3), [1..5]→(1.5,4.5), [1..4]→(1.5,3.5)이며 테스트 기대값과 같다.
- **분산**: 최솟값과의 정확한 Fraction 차이를 Decimal50으로 바꾼 뒤 두 단계로 Σ(x-평균)²/n을 계산한다. n-1 보정은 없고, 이상치 제거·임계값 분기·대표 방식 자동 전환 코드도 없다. 동일 값 21개는 차이가 모두 정확히 0이므로 결과도 "0"이다. 결과는 결정적이지만 Decimal50 근사값이며, validator는 같은 함수로 다시 계산하므로 비교가 일관된다.
- **같은 분기·제외 규칙**: `group()`은 `per_store_metric is not None`인 같은 분기 행만 쓴다. 0점포, 명칭 충돌, 점포 행 누락, 매출 없음 행은 가중평균과 분포에서 똑같이 빠진다. 실제 0원 매출은 표본에 포함된다(`exact_zero`). analysis_period 모드에서 primary 분기에 행이 없으면 대표 분포는 null이 되며, 이전 분기로 자동 대체되지 않는다.
- **입력 범위**: 금액 ≤ 2^63-1(BigInteger/SourceNumber), 점포 수 1 ~ 2^31-1(Integer), 행 ≤ 500 제약이 distribution 가드와 맞는다. 범위를 벗어나면 ValueError가 난다.
- **이전 지적 반영 확인**: 포함 항목마다 ready 상태의 store_reference, 양수 점포 수, 같은 분기, `per_store_metric` 재계산 일치, primary 항목의 `included` 상태를 검사한다. 분포 재계산과 `sample_count == len(used)`도 검사한다(이전 1번 해소). 레거시 분기를 추가했다(2번, 아래 B2 예외 있음). n<4일 때 사분위·IQR·분산을 숨긴다(3번 해소). 제목 "상권·업종별", "대표값 계산 제외", 다른 분기의 "중앙값" 표기, 동일 비중 문구를 반영했다(4번 해소). 홀수 사분위, 0.5/1.5 표시, 혼합 분기, 변조 거절, 레거시 읽기 테스트를 추가했다(5번 대부분 해소).

#### 차단 사항
- **B1. validator가 "제외 집합"의 정당성을 검사하지 않음 → 체리피킹 변조가 통과함** (`SalesBlock.coherent`)
  - 현재 validator는 `included_item_keys`에 있는 항목만으로 분포를 다시 계산한다. 같은 분기에서 유효한 `per_store_metric`이 있는 항목을 키에서 빼고, 해당 item의 `average_contribution`을 `excluded`로 바꾸고, `excluded_counts`/`candidate_item_count`/`included_item_count`와 합계·분포를 그에 맞게 고치면 그대로 통과한다. 대표 중앙값을 의도한 값으로 고를 수 있다는 뜻이다. 다음이 검사되지 않는다.
    - 그 분기에서 `metric`이 있는 모든 item 수가 `candidate_item_count`와 같은지
    - 키에 없는 같은 분기 item에 `per_store_metric`이 없는지(= ready·양수 점포·명칭 일치가 아닌지)
    - 비 primary 분기 member의 contribution이 `different_quarter`인지
    - `groups`가 `metric`이 있는 item의 분기 집합과 1:1이며 중복이 없는지
  - 설계 17행의 "분기·부분/제외 집합 동일"과 11행의 "최종 DTO validator가 재계산" 주장을 충족하려면 위 4개 검사와 해당 변조 거절 테스트가 필요하다. 생산 경로(`attach`)는 올바르게 계산하므로 현재 응답 값이 틀렸다는 뜻은 아니다. validator의 보증 범위가 문서보다 좁다는 뜻이다.
- **B2. 레거시 판정이 부분 제거에 열려 있음**
  - `has_distribution`은 최상위 `representative_method`/`distribution` 키 존재 여부로만 정해진다. 최상위 두 키만 지우고 `groups[*].distribution`을 남기거나 변조하면 레거시 분기로 들어간다. 이때 포함 항목이 있는 group의 `distribution`은 전혀 비교되지 않으므로 변조된 group 분포가 통과한다. 빈 group만 `is not None` 검사를 받는다.
  - 수정 방법: 레거시로 판정되면 모든 group에 `"distribution"` 키가 없어야 한다고 강제한다. 반대로 새 모드라면 모든 group에 키가 있어야 한다. 이 경우를 다루는 테스트를 추가한다. 현재 `test_previous_weighted_payload_remains_readable`은 group 분포까지 지우므로 이 구멍을 잡지 못한다.
- **B3. FE 분산 라벨이 분모를 틀리게 설명함** (`LocationReferenceView`)
  - "항목 간 분산 … · 전체 항목 수로 나눈 기술통계"라고 표시하지만, 실제 분모는 `sample_count`(primary 분기에 포함된 항목 수)다. 같은 카드에 "전체 N항목 중 M항목 반영"이 함께 보이므로, 사용자는 "전체 항목 수"를 `listed_item_count`(N)로 읽는다.
  - "대상 {sample_count}개 항목 수로 나눈(n으로 나눈) 기술통계"로 고친다. 단위도 "(원자료 원/점포)²"로 바꿔 설계 9행과 맞춘다.

#### 비차단 권고
- validator 안에서 `avg["groups"]`, `k["market_code"]` 등의 KeyError와 `int(...)`의 TypeError는 pydantic이 ValidationError로 바꾸지 않는다. 서비스는 `ValueError/TypeError/OverflowError/OSError`만 잡으므로 KeyError는 그대로 새어 나간다. 현재 BE에는 재역직렬화 경로가 없다고 기록되어 있고(Codex 2번) 생산 payload에는 모든 키가 있으므로 지금은 영향이 없다. 다만 위 dict 접근을 `.get` 또는 형식 검사 + ValueError로 감싸면 거절 방식이 하나로 정리된다.
- `total_stores`는 `str.isdigit()`로만 검사한다. "007"이나 유니코드 숫자도 통과하므로 `^[1-9][0-9]*$`로 제한하고 상한 2^31-1을 validator에서도 명시하는 것을 권한다. 현재는 distribution 가드에서 ValueError가 나므로 안전성 문제는 아니다.
- FE의 "사분위 범위 Q1 ~ Q3"라는 표현은 IQR(폭)과 헷갈릴 수 있다. "하위·상위 절반 중앙값(Q1~Q3)"으로 정의를 함께 적는 것을 권한다. 분산 원값은 50자리까지 나올 수 있으므로 접기 영역에 두는 현재 배치를 유지한다.
- 포함 항목 라벨은 `distribution` 기준으로, 제외 항목 라벨은 `useMedian` 기준으로 정한다. 현재 데이터 조합에서는 결과가 같지만, 같은 기준(`useMedian`)으로 통일하면 이해하기 쉽다.
- 중첩 상권(관광특구 등) 중복과 같은 점포가 여러 행에 반영되는 문제는 공개 문구에 이미 있다. 4개 미만 안내가 신뢰도나 신뢰구간 주장이 아니라는 점도 현재 문구에서 유지된다.

#### 미확인 (Claude 미실행, 별도 기록 필요)
- FE 타입 정의에 `distribution`/`representative_method`/`variance.value`가 들어 있는지, 그리고 타입검사·빌드 결과
- 종합/PDF 화면이 같은 컴포넌트를 쓰는지
- 통합 테스트(PostGIS)를 실제로 실행한 결과
- 배포 여부

#### 결론
중앙값 대표값, median-of-halves 사분위, n으로 나누는 기술 분산, 같은 분기·제외 규칙, 가중평균 비교 보존, 소표본 표시 숨김은 설계와 일치한다. 생산 경로 계산에서는 정확성 버그를 찾지 못했다. 다만 validator가 "포함 항목 재계산"까지만 보증하고 제외 집합과 레거시 경계는 보증하지 않는다(B1·B2). FE에는 분모를 잘못 설명하는 라벨이 남아 있다(B3). 따라서 **REVISE**다. B1~B3을 수정하고 변조 테스트를 추가한 뒤, 실행한 사람이 그 실행 결과를 기록하면 PASS로 판단할 수 있다.

### 2차 검토 B1–B3 보완 (Codex)
분기 집합·중복/모든 후보 수/모든 적격 항목과 포함 집합 일치/다른 분기 기여 상태/대표 포함 수를 추가 검사했다. 각 항목의 양의 ready 원천 비율과 per_store_metric을 먼저 대조하므로 적격 행을 제외로 돌려 집합과 중앙값을 다시 쓰는 변조도 거절한다. 레거시는 모든 그룹에 distribution 키가 없어야 하며 새 모드는 모든 그룹에 있어야 한다. FE 분산 분모는 대상 sample_count임을 직접 표기하고 원자료 원 단위를 사용한다. 형식 부분 제거/분기 누락·중복/후보 수/체리피킹 변조 테스트를 추가해 관련 36개 통과. 임의 외부 payload 보안 인증이 아닌 신뢰된 서버 생성 응답의 원천 정합성 검사다.

### B1–B3 최종 재검토 (Claude, 2026-11-16) — 판정: **PASS** (코드 검토 기준, 차단 사항 없음)

검토 범위와 한계: 이번 요청에 제공된 현재 코드만 읽었다. 대상은 `sales_distribution.py`, `per_store_sales.py`, `schemas/location_reference.py`, `services/location_reference.py`, 모델·ETL 일부, BE 단위·통합 테스트, FE `LocationReferenceView.tsx`·`LocationReferenceView.test.tsx`·`types/locationReference.ts`·`LocationReferenceSection.tsx`·`ReportPage.tsx`다. 셸·테스트·타입검사·빌드·DB·네트워크·에이전트는 실행하지 않았고 코드는 수정하지 않았다. 위 Codex 절의 "관련 36개 통과"와 이전의 "29개", "FE214+프로필4개"는 Claude가 실행하거나 확인한 결과가 아니다. 이 PASS는 코드와 설계가 일치한다는 판단이며 테스트 통과·배포를 뜻하지 않는다. 검토 기준은 사용자 지시에 따라 "신뢰된 서버가 생성한 응답의 원천 정합성"이다. 임의 외부 입력을 막는 보안 인증 수준까지 요구하지 않았다.

#### 이전 차단 사항 해소 확인
- **B1 해소**
  - `group_quarters`는 중복이 없어야 하고 `metric`이 있는 item 분기 집합과 같아야 한다.
  - 모든 item에 대해 `metric`과 ready `store_reference`(ASCII 정규 정수, 0~2^31-1, 같은 분기)가 있을 때만 `per_store_metric`을 기대한다. 이 기대값은 `metric(s, n)`과 정확히 같아야 하고, 그 외에는 `None`이어야 한다.
  - group마다 `used == eligible`(같은 분기 + `per_store_metric` 있음, item 순서 동일)이고 `candidate_item_count == len(candidates)`, `len(keys) == len(used) == included_item_count`다. 키가 중복되면 `len(used) < len(keys)`이므로 거절된다.
  - 따라서 적격 행을 `excluded`로 돌려 표본에서 빼면 `per_store_metric`이 남아 eligible과 불일치하고, `per_store_metric`까지 지우면 item 재계산과 불일치한다. `test_cannot_drop_valid_member_and_recompute_representative`를 손으로 추적한 결과 `invalid distribution eligibility`로 거절되는 것이 맞다.
  - 다른 분기 member는 `different_quarter`, primary member는 `included`인지 검사한다. primary 포함 수 투영도 검사한다.
- **B2 해소**: 모든 group에서 `("distribution" in group) != has_distribution`이면 거절하므로 부분 제거가 막힌다. `partial_legacy`와 `missing_distribution` 테스트가 두 방향을 모두 다룬다. 완전한 레거시 payload는 기존 metric·합계 검증을 받은 뒤 통과한다.
- **B3 해소**: FE 문구가 "대상 {sample_count}개 항목 수로 나눈 기술통계 · (원자료 원/점포)²"로 바뀌어 `listed_item_count`와 혼동되지 않는다. FE 테스트도 "4개 항목 수로 나눈 기술통계"와 단위를 확인한다.

#### 통계 결정 최종 확인 (설계와 일치)
- **대표값**: 같은 분기의 적격 `(상권,업종)` 행마다 정확한 `Fraction(매출, 점포 수)`를 구해 동일 비중으로 정렬한 중앙값을 쓴다. 홀수 n은 가운데 값, 짝수 n은 가운데 두 값의 산술평균이다. 개별 점포 중앙값이 아니며(`individual_store_median=False`), 점포 수 가중 중앙값도 아니다. Σ매출/Σ점포 가중평균은 `metric`으로 남아 비교값 역할만 한다.
- **Q1/Q3**: 하위 `values[:n//2]`, 상위 `values[(n+1)//2:]`의 중앙값이므로 홀수 n에서 가운데 값을 뺀다. n=1이면 Q1=Q3=중앙값이고, IQR은 Q3−Q1(≥0)이다.
- **분산**: 정렬 후 최솟값과의 정확한 Fraction 차이를 Decimal50으로 바꿔 Σ(x−평균)²/n을 계산한다. n−1 보정·이상치 제거·분산 임계값에 따른 방식 전환은 없다. 결과는 결정적인 Decimal50 근사값이며, validator는 같은 함수로 다시 계산한다. 테스트의 [1,2,3,4]→1.25와 동일 값 21개→"0"은 손으로 추적한 결과와 같다.
- **표시 경계**: `ratio`의 "1원 미만/점포"(0<x<1)와 반올림 표시는 가중평균 `metric()`과 같은 규칙이다.
- **소표본·중첩**: n<4이면 `limited_reference_count=True`이고, FE는 사분위·IQR·분산을 숨긴 채 중립 안내만 표시한다. 신뢰도나 신뢰구간 주장은 없다. 중첩 상권 중복 가능성과 "개별 가게 매출의 중앙값은 아니에요" 문구는 접기 영역 밖에 있어 항상 보인다.

#### 생산 경로 정확성
`attach`에서 차단 수준의 정확성 버그는 찾지 못했다.
- included ⇔ (primary 분기 ∧ `per_store_metric` 있음)이 성립한다.
- 최상위 `included_item_count + Σexcluded_counts == listed_item_count`가 항상 맞는다.
- `distribution`과 `metric`은 같은 `used` 집합에서 투영되므로, 한쪽만 null이 되는 경우가 없다.
- 그래서 FE의 `distribution?.median ?? metric` 대체 경로가 새 서버 응답에서 가중평균을 중앙값 제목으로 표시하는 일은 일어나지 않는다.
- analysis_period 모드에서 primary 분기에 행이 없으면 null이 되며 다른 분기로 대체되지 않는다.

#### FE·보고서 확인 (이전 "미확인" 갱신)
- `types/locationReference.ts`에 `distribution?`·`representative_method?`·group `distribution?`이 선택 필드로 정의되어 레거시 응답과 호환된다. 타입검사·빌드 결과는 Claude가 실행하지 않았다.
- 분석 화면(`LocationReferenceSection`)과 보고서/PDF(`ReportPage`의 `PopulationBlock`)가 같은 `LocationReferenceView`를 사용함을 확인했다. "종합" 화면 코드는 이번에도 제공되지 않아 확인하지 못했다.
- 중앙값 모드의 라벨은 "상권·업종별", "중앙값 산정 대상", "대표값 계산 제외", 다른 분기 "중앙값"이다. 레거시 모드의 라벨은 "점포 1개당 평균", 합계÷합계 문구다. FE 테스트가 두 모드를 모두 다룬다.

#### 비차단 권고 (PASS를 막지 않음)
1. **PDF에서 접기 영역이 닫힌 채 인쇄될 수 있음**: `ReportPage`는 `window.print()`를 쓰고 `<details>`는 기본적으로 닫혀 있다. 그래서 PDF에는 가중평균 비교, IQR·분산, "같은 비중", "자동 전환 없음" 문구가 빠질 수 있다. 핵심 고지(개별 가게 중앙값 아님, 중복 포함 가능, 동일 비중 중앙값)는 접기 영역 밖에 있어 오해를 부르지는 않는다. 다만 설계 15행의 "비교 접기 영역"을 PDF에도 남기려면 `print:` 스타일로 펼치거나 보고서 전용으로 정적 렌더링하는 것을 권한다.
2. **validator가 `primary_quarter` 선택 규칙을 다시 유도하지 않음**: latest 모드에서는 최신 group 분기, analysis 모드에서는 item `selection_reason`으로 확인할 수 있다. 최상위 `status`/`reason`과 최상위 `excluded_counts`의 사유별 분포도 합계만 검사한다. 생산 경로는 올바르고 신뢰 경계 안의 응답이므로 차단하지 않는다. 문서 13행의 "validator가 재계산"은 포함 집합·분포·투영의 재계산으로 읽어야 한다.
3. **문서 1행 제목**: "상권별 점포당…"을 실제 표본 단위에 맞게 "상권·업종별 점포당…"으로 맞추는 것을 권한다.
4. **FE 테스트 공백**: 중앙값 모드의 다른 분기 "중앙값" 라벨과 "대표값 계산 제외" 라벨을 렌더링해 확인하는 테스트는 없다. 추가를 권한다.
5. 이전 비차단 권고는 유지한다: "사분위 범위" 표현, 분산 문자열의 끝자리 0 정규화, validator dict 접근의 KeyError 통일.

#### 결론
요청된 통계 결정(동일 비중 상권·업종 비율의 정확한 Fraction 중앙값, 같은 적격 분기, 가중평균 비교 보존, 개별 점포 중앙값 아님, median-of-halves Q1/Q3, n=1 처리, /n 기술 분산의 Decimal50·정확한 차이 계산, 이상치 제거·임계값 전환 없음)은 현재 코드와 일치한다. B1–B3은 해소되었고 차단 사항은 남아 있지 않으므로 **PASS**다.

다음은 Claude가 실행하지 않았으므로 실행한 사람이 실제 결과를 별도로 기록해야 한다.
- BE 단위·통합(PostGIS) 테스트 결과
- FE 테스트·타입검사·빌드 결과
- 배포 여부


### 실행 결과·최종 판단 (Codex, 2026-11-16)

실제 Claude CLI Read/Edit를 3회 진행해 최종 PASS(차단0, 2026-11-16T14:20:43Z 완료)를 받았다. 비차단 권고인 임의 payload 인증/키 타입 전면 개편은 외부 입력을 받지 않는 서버 응답 검증의 이번 범위를 넘어 추가하지 않는다. PDF 비교 details는 닫힌 채 인쇄될 수 있으나 대표값과 필수 설명은 항상 표시한다. 공개 PDF는 별도로 검증한다. 문서 제목은 표본 단위에 맞췄다.

Codex 실행: 관련36개 통과, PostGIS342개 통과(마지막 validator 추가 전이며 최종 API/CI에서 재검증), 최초 전체 단위2588개 통과/Windows 권한3개 skip 후 변경은 관련 시험으로 확인했다. ruff check/format, mypy app+etl203개 파일 통과. FE214+profile4, lint, 타입·build 통과. 실제 DB 복원 clone15개 위치에서 원자료 S/N·기존 가중평균·독립 Fraction 중앙값 일치를 확인했다. 최종 CI·공개 반영 결과는 PR 기록을 참조한다. 이는 Claude가 실행한 테스트가 아니다.
