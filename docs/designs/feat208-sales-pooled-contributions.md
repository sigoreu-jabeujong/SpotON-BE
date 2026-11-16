# 목록 합계·전체 점포 수 기준 평균과 그래프 (#208)

2026-11-17 사용자 최신 요청 및 직접 선택을 따른다. 대표값은 같은 분기의 유효 목록 매출 S=Σsᵢ, 점포 수 N=Σnᵢ로 구한 S/N이다. 각 그래프 막대는 **sᵢ/N**이며 모든 막대의 정확한 분수 합이 S/N이다. sᵢ/nᵢ 값들의 중앙값 또는 단순 평균이 아니다. 사용자 선택: '각 리스트 매출 ÷ 전체 점포 수'. 예: s=[100,900], n=[10,30]이면 대표25, 막대2.5/22.5다.

## 계약과 구현

- 기존 `per_store_average.metric`, `total_sales`, `total_store_count`의 정확한 가중평균 계산을 대표로 사용한다. `representative_method=pooled_sales_over_total_stores_v1`, `graph_basis=each_sales_over_group_total_stores_v1`로 표시 의미를 버전 관리한다.
- 대표 및 각 분기 그룹에 `contributions`를 추가한다. 각 항목은 market_code/industry_code/source_quarter와 `metric(sᵢ,N)`을 가진다. 같은 그룹의 모든 denominator는 동일한 N 문자열, numerator는 해당 원자료 매출 문자열이다. 표시 금액은 원 단위 반올림하므로 표시된 정수들의 합과 전체 표시 평균이 1원 단위로 다를 수 있지만, 정확한 numerator/denominator 분수들의 합은 항상 대표 평균과 같다.
- 기존 분기 선택/유효 대상/0점포·점포수 없음·매핑충돌 제외를 유지한다. 다른 분기는 별도 그룹과 그 그룹의 N을 사용한다. 원자료 금액·각 항목 자체 점포당 값·점포수는 보존한다. 자료 없는 대표는 null/기여 목록 빈 배열이며 실제0은0으로 포함한다.
- 기존 median/q1/q3/variance distribution은 구버전 payload 호환용으로 보존하나 새 FE 대표·그래프에는 사용하지 않는다. 저장된 이전 median marker도 DTO가 읽을 수 있다. 새 DTO는 기여 목록의 전체 구성/원자료 numerator/전체 denominator/계산/대표 투영을 재검증한다. 전체 응답 snapshot에 새 값도 포함된다.
- 고유 점포 중복 제거/개별 점포 매출 분포 복원·정규분포·분산 추정은 하지 않는다. 이 차트는 사용자가 선택한 공통 분모 기준의 평균 구성 그래프다. 기존 데이터의 중첩 여부 메타는 유지하되 사용자가 지운 반복 경고 문구를 복원하지 않는다.

## FE

대표에는 서버 metric을 사용하며 중앙값 라벨·산정 대상 표기를 평균으로 바꾼다. 목록 총매출과 총점포 수의 나눗셈을 표시하고, 막대는 서버 contributions의 원 단위 금액을 표시한다. 모든 막대의 기준은 전체 점포 수이며 분모를 항목별 점포 수로 바꾸지 않는다. 막대 길이는 전체 평균 대비 해당 기여값의 비중이다. FE Number는 길이 표시에만 사용하고 합계·평균·기여액을 재계산하지 않는다. 정확한 표시 문자열과 분모/원자료 키 매칭을 유지하고 데이터가 없으면 그래프 자료 없음으로 둔다. 상하/Home/End 키로 항목을 선택하고 인쇄에는 모든 막대가 보이도록 높이 제한을 해제한다. 기존 생활인구 문구·박스·출처와 제거한 접미사는 유지한다.

## 검증·배포

합성 예제의 공통 분모/정확한 분수 합, 혼합 분기·누락·실제0·분모 변조·대표 투영을 시험한다. 실제 DB 복원 clone15위치에서 원자료 S/N과 기여 분수 합을 독립 대조한다. FE의 전체 평균/막대·결측/중복키/분기/단위/실제0과 모바일·선택·인쇄를 확인한다. BE ruff/mypy/unit/실제 PostGIS·CI 후 develop Squash→BE 선배포→FE 정상 develop/main PR·공개 검증 순서다. DB/schema0013/환경/원천/AI·생활인구 계약은 변경하지 않는다.

## 실제 검토·실행 기록

Codex 관련42개 및 실제 PostGIS API1개 통과. FE223+배포프로필4개 통과. 최종 전체 검사·Claude 검토·공개 반영은 별도 기록한다.

## Claude 코드 검토 (2026-11-17)

**판정: PASS** (차단 이슈 없음, 아래는 선택 개선 사항)

검토 범위: 사용자가 제공한 BE `per_store_sales.py`, `location_reference.py`, 단위·통합 테스트와 FE 타입, `LocationReferenceView.tsx`, `SalesDistributionChart.tsx`, 차트 테스트의 실제 코드다. 테스트·CI·배포는 Claude가 직접 실행하지 않았으며, 위 실행 기록은 작성자 기록을 그대로 둔다.

확인한 사항:
- 대표값: `group()`의 `s=Σsᵢ`, `n=Σnᵢ`(유효 `per_store_metric` 항목의 denominator 합)로 `metric(s,n)`을 계산하고, `summary`가 primary 그룹을 그대로 투영한다. sᵢ/nᵢ의 중앙값·단순평균은 사용하지 않는다.
- 막대: `contributions`는 같은 `used` 목록에 `metric(sᵢ, n)`을 적용하므로 모든 denominator가 그룹의 N과 같고, numerator는 원자료 매출 문자열이다. Σ(sᵢ/N)=S/N은 분수로 정확히 성립한다. 다른 분기 그룹은 자기 N을 쓴다(단위 테스트 denominator "7"로 확인됨). 대표 `contributions`는 primary 그룹만 투영하고, primary가 없으면 `[]`이다.
- 포함 규칙: 기존 분기 선택, 점포 행 없음/매핑 충돌/0점포 제외, 다른 분기 분리 규칙을 그대로 쓴다. 실제 0 매출(점포 수>0)은 `exact_zero=True`로 포함되고, 자료 없음은 `metric=None`·`contributions=[]`로 구분된다.
- DTO 검증: pooled 표식이 있으면 `graph_basis`가 필수이고, 각 그룹 contributions를 items의 원자료 금액과 store_reference 점포 수에서 순서까지 재계산해 비교한다. 빈 그룹은 `[]`이어야 하며, 대표 투영도 비교한다. 이전 weighted(표식 없음)·median 표식 payload는 pooled 검사를 거치지 않으므로 계속 읽힌다. distribution은 계속 생성·검증되므로 API 호환성이 유지된다.
- FE: 대표는 서버 `metric.display`, 막대 금액은 서버 `contributions[].metric.display`를 쓴다. 분모가 `total_store_count`와 같은지, numerator가 원자료 값과 같은지, 키가 중복되지 않는지, primary 분기인지, 개수가 `included_item_count`와 같은지, 단위가 맞는지 확인하며, 어긋나면 "그래프를 표시할 자료가 없어요"로 처리한다. `Number`는 막대 너비(sᵢ/S 비율, 너비 합 100%)와 그 전제(유한·0 이상·평균 이하)를 확인하는 데만 쓰고, 합계·평균·기여액은 재계산하지 않는다. sᵢ≤S이고 decimal50 문자열에서 Number로의 변환이 단조이므로 `c.value <= mean`이 정상 데이터를 잘못 거부하지 않는다. 평균이 0이면 너비 0%이고 NaN이 생기지 않는다. distribution(median 등)은 FE에서 참조하지 않는다.
- 상하/Home/End 이동, roving tabIndex, 인쇄 시 `print:max-h-none`이 구현되어 있다. DB/env/AI/생활인구 계약은 변경되지 않았다.

선택 개선 사항(비차단):
1. `LocationReferenceView`의 `<summary>계산 기준·비교 평균</summary>`에서 "비교 평균"은 중앙값 시절 표현이 남은 것으로 보인다. 내용에 맞게 "계산 기준"으로 바꾸기를 권한다.
2. 항목 카드의 "점포당 {per_store_metric}"(sᵢ/nᵢ)은 같은 상권 막대값(sᵢ/N)과 다르다. 설계상 보존 대상이지만 사용자가 혼동할 수 있으므로 "해당 상권 자체 점포 수 기준"처럼 기준을 명시하기를 권한다.
3. "매출 합계 {total_sales}원 ÷ 점포 수 합계 {total_store_count}개"와 차트의 "전체 {N}개"는 천 단위 구분 없이 원 문자열로 표시된다. 표시 전용 문자열 포맷(정규식 삽입)을 쓰면 계산 계약을 바꾸지 않고 읽기 쉽게 만들 수 있다.
4. FE 테스트 fixture는 display를 "2.5원/점포", "22.5원/점포"로 두지만, 실제 BE display는 원 단위 반올림으로 "3원/점포", "23원/점포"(합 26 ≠ 대표 25)이다. 정수 표시의 반올림 차이를 보여 주는 실제 형식 fixture를 하나 추가하기를 권한다.
5. 설계 문서의 "FE Number는 길이 표시에만 사용"을 "길이 표시와 그 표시 전제 확인에만 사용"으로 고치면 실제 코드와 정확히 맞는다.

### Codex 실행 확인
전체 단위2,627 통과/Windows권한3 skip, 관련42/실제 PostGIS API1 통과, ruff check·format/mypy app+etl204파일 통과. 실제 복원DB15위치에서 S/N 및 기여분수 합을 확인했다. 실제 Claude 검토 PASS·차단0. FE는 계산 기준 제목과 해당 상권 점포당 라벨로 보완하고, 반올림 표시 합을 정확한 평균으로 오해시키는 문장은 평균에 반영되는 금액이라는 설명으로 정리했다. 실제11항목 replay의 상하/Home/End·끝 경계·360/390·인쇄 전체막대·PDF324,889byte·JS오류0을 확인했다. 이는 Codex 실행이며 Claude가 실행한 시험이 아니다. 전체 PostGIS CI 및 공개 결과는 연결PR에 기록한다.
