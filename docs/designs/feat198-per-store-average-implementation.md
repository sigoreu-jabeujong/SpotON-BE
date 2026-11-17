# 점포당 평균 추정매출 구현 (#198)

검토된 #194의 동일 분기 매출 합계/전체 점포 수 합계를 기존 location-reference 응답에 추가한다. 대표/분기별 집계, 누락/관측0/0분모, 중복 미제거, 정수 분수 및 Decimal50 표시를 보존한다. FE 공통 카드가 분석·종합·PDF에서 같은 서버값과 계산 근거를 표시한다.

변경: per_store_sales 서비스, 기존 DTO/조회 조립, FE 타입/공통 카드. DB/환경/원본/기존 사용자 파일은 변경하지 않는다. 후속 검증 결과와 실제 Claude 구현 검토를 아래 기록한다. 아직 배포를 완료했다고 표시하지 않는다.

## 검증

설계검수 B1~B4 원문과 Codex 보완/재검토는 [#194 설계 12절](feat194-per-store-sales-average.md#12-실제-claude-code-검토codex-최종-판단)에 있다. 이번 구현 검토와 설계 검토 기록을 구분한다.

최종 로컬검사: BE 전체단위2581통과/Windows권한3제외, 새산술10통과, 실제PostGIS 새API1통과. FE 신규표시 포함213개/프로필4통과, 타입빌드·lint 통과. 실제배포는 이번구현완료와구분하며 현재미반영이다.

새 산술/집계 집중 단위10개 통과. FE 타입/빌드, 기존212개 및 프로필4개 통과. 전체 BE 회귀와 실제 PostGIS 새 API 검사는 진행 중이다.

## 실제 Claude 구현 검토

### 12.3 최종 재검토 (Claude, 문서 검토만 수행)

검토 범위: 요청에 붙여 준 `app/services/per_store_sales.py`, `app/schemas/location_reference.py`, `app/services/location_reference.py`, `app/models/market_store.py`·`market_sale.py`, `etl/market_stores/archive.py`(일부), 단위·통합 테스트, FE `LocationReferenceView` 코드와 이 문서. 이 문서 외에는 아무것도 실행·수정하지 않았다. 테스트·DB 조회·빌드·배포도 수행하지 않았다. 위 "검증" 절의 통과 수치는 Claude가 재현한 결과가 아니다.

**판정: REVISE (문서 한정 1건) — 코드에는 차단 이슈 없음.** 아래 B-DOC을 해결하면, 붙여 준 코드 기준으로 PASS로 본다.

#### 차단 이슈

- **B-DOC. 12.1/12.2 기록이 이 문서에 없음.** 요청에서는 "B1–B4가 본문과 12.2(Codex)에 반영됐다"고 했지만, 이 파일에는 `## 검증`과 이 절만 있다. 12, 12.1, 12.2 번호도, B1–B4 해소 내용을 적은 본문도 없다. 그래서 구현이 B1–B4를 해소했다는 점은 코드에서 독립적으로 확인했지만(아래 표), 그 근거는 이 문서 안에서 추적할 수 없다. 12.1의 차단 이슈 원문과 12.2의 Codex 판정을 옮겨 오거나, 그 기록이 있는 위치를 링크해야 한다. 또 "진행 중"인 BE 전체 회귀와 PostGIS 새 API 검사 결과를 확정해서 적어야 한다. 이 두 가지가 채워지기 전까지 "완료"·"배포" 표기는 금지를 유지한다.

#### B1–B4 및 추가 항목의 코드 대조 (독립 확인)

| 항목 | 확인 결과 |
|---|---|
| B1 eligible 선택 유지 | `_sales`는 이름·유형·업종이 일치하는 eligible 행 중 최신 숫자 행만 `metric`으로 채운다. `attach`는 이 값만 사용한다. 점포 행과 이름·유형·업종이 다르면 `store_mapping_conflict`, `store_reference.status=no_data`, 분모 null로 처리하고 두 합계 모두에서 제외한다. 충족. |
| B1 신규 coverage scope | 전체 목록 기준은 `excluded_counts_scope="listed_items"`(included + 제외 = listed), 그룹 기준은 `"group_numeric_items"`(candidate = included + 제외)로 분리돼 있다. 스키마 validator가 두 등식을 모두 강제한다. 충족. |
| B2 내부 count 오류 시 실패 | 음수, 비정수, total≠general+franchise이면 `ValueError`가 나고 `INTERNAL_ERROR`로 응답한다. DB CHECK와도 이중으로 막힌다. 충족. |
| B2 관측 0 ≠ 누락 | 매출 0·점포>0이면 `0원/점포`, `exact_zero=True`로 반영한다. 점포 0이면 `zero_store_count` 또는 `zero_store_count_with_sales`, 행이 없으면 `store_row_missing`으로 사유를 구분한다. 충족. |
| B3 대표 분기 | latest 모드는 숫자 매출이 있는 항목 중 최신 분기, analysis 모드는 `target` 분기로 고정한다. 대표 분기의 분모가 없으면 `metric/total_*`가 null로 유지되고 이전 분기로 넘어가지 않는다(테스트 `test_missing_newest_count_never_switches_to_older_quarter`). 충족. |
| B3 상태식 | 그룹은 ready(전부 반영)/partial/no_data, 상위는 대표 분기 반영 수 = listed이면 ready이고, 반영할 key가 없으면 원래 block의 status/reason을 그대로 쓴다. 숫자 행이 없는 latest 항목은 `source_quarter=None` 상태로 `sales_unavailable`가 된다. 충족. |
| B4 반올림 | 0 < S < N이면 "1원 미만/점포" 구간이 반올림보다 우선한다. 그 외에는 정수 `divmod`로 half-up한다. `value`는 prec50 Decimal을 `"f"` 형식(지수 표기 없음)으로 만들고 끝의 0을 제거한다. 분자·분모는 문자열이라 2^53 문제가 없고, 상한 500×(2^63−1)도 지킨다. 충족. |
| noData 합계 null / 새 BE는 항상 객체 | 반영 항목이 없으면 `total_sales/total_store_count/metric`이 null이다. `attach`는 버전이 없어도 항상 `per_store_average` 객체를 반환한다. 충족. |
| 대표 included keys 제거·그룹 key 권위 | 상위 summary에는 key 목록이 없고 `groups[].included_item_keys`만 있다. validator가 그룹마다 S·N·metric을 다시 계산하고, 상위 값이 대표 그룹의 투영인지 확인한다. 충족. |
| 검증된 MV 재사용 | `_versions`가 지문·행 수·상호 FK를 검증한 store 버전을 `store_context`로 넘겨 그대로 쓴다. 다시 resolve하지 않는다. 충족. |
| meta | `items_additive=False`를 유지하고 `source_refs`에 `store-counts`(OA-15577, `similr_induty_stor_co`)를 추가했다. ETL 매핑 `similr_induty_stor_co→total_stores`와 일치한다. snapshot token은 새 필드를 포함한 직렬화 결과로 계산된다. 충족. |

#### 비차단 메모

1. **"1원 미만" + 반올림 꼬리표.** 0<S<N이면 `rounded=True`라서 FE에 "1원 미만/점포 (표시 반올림)"이 나온다. 이 경우는 반올림이 아니라 구간 표시이므로, 이 구간에서는 FE 꼬리표를 생략하거나 서버에 `display_bucket` 같은 구분 값을 두는 편이 정확하다.
2. **FE 제외 항목 표시.** `Object.values(excluded_counts).join(' / ')`는 "2 / 1"처럼 사유 없이 숫자만 보여 준다. 사유 라벨(다른 분기, 매출 없음, 점포 행 없음, 점포 0, 매핑 불일치)과 함께 표시해야 한다.
3. **FE 누락 문구.** `store_reference.total_stores`가 null이면 "자료 없음개"가 나온다. 점포 0이나 매핑 불일치 항목은 "점포당 자료 없음"만 보여서 이유를 알 수 없다. `average_contribution.reason`을 사람이 읽을 수 있는 문구로 바꿔 표시해야 한다.
4. **FE 분기·기간 표기.** 대표 카드는 `primary_quarter`를 "20254" 원문으로, 항목 카드는 "2025년 4분기"로 보여 준다. 대표 카드와 그룹 목록에는 `temporal_relation`(분석 기준 이전/이후)도 없다. 표기를 통일하고 기간 관계를 추가해야 한다. 합계 문자열도 천 단위 구분 없이 표시된다.
5. **용어.** `total_stores`의 원자료 필드는 '유사업종 점포 수'다. FE의 "자료상 전체 점포 수"는 허용 범위지만, 출처 툴팁에 원 필드명을 함께 적으면 근거가 더 분명해진다. `deduplication=not_performed`는 "중복 포함될 수 있어요"로 전달되고 있다. "고유 점포 평균이 아님"까지 한 줄로 명시할 것을 권한다.
6. **상태 범위 차이.** 상류 `mapping_conflict` 때문에 sales block이 `partial`이어도, 해당 항목에 숫자가 있으면 평균은 `ready`가 될 수 있다. 의도된 범위 차이로 보이지만 문서에 한 줄로 적어 둬야 한다.
7. **분기 계산 중복.** `_sales`의 `desired`와 `attach`의 analysis `primary`가 같은 식을 따로 계산한다. 하나의 헬퍼로 공유하거나 `attach`에 인자로 넘기면 드리프트를 막을 수 있다.
8. **validator 효율.** 그룹 멤버십을 `any(...)`로 찾아 그룹당 O(items×keys)이다. 현재 상한(500)과 실제 분기 수에서는 문제없지만, key를 set으로 바꾸면 비용 없이 개선된다. 상위 `included_item_count`가 대표 그룹의 값과 같은지, 그리고 `average_contribution.status=="included"`인 항목 집합이 대표 그룹 key와 같은지도 함께 단언할 것을 권한다.
9. **실패 범위.** 평균 계산 중 불변식이 위반되면 생활인구를 포함한 전체 location-reference가 500으로 실패한다. B2 합의(실패 시 닫기)와는 일치한다. 다만 운영 영향이 크므로 로그와 알림 사유를 구분해 둘 것을 권한다.
10. **store-counts source_ref.** 매출 ref와 달리 `boundary_compatibility="unverified"`, `name`, `boundary_*` 필드가 없다. 경계 호환이 미검증이라는 점이 같으므로 같은 표기를 복사해 두면 일관성이 생긴다. `scope_too_large`나 `no_spatial_overlap`일 때도 ref가 붙지만 무해하다.
11. **응답 타입.** `per_store_average`, `store_reference`, `per_store_metric`, `average_contribution`이 `dict[str, Any]`라서 OpenAPI 스키마에 구조가 드러나지 않는다. `no_valid_sales_store_pairs` 같은 신규 reason도 `Reason` Literal 밖에 있다. 이번 범위에서는 허용하지만, 후속 작업에서 typed 모델로 바꾸는 것을 권한다.

#### 테스트 계획 보완 (비차단, 실행하지 않음)

- 단위 테스트: `zero_store_count_with_sales`, `store_row_missing`, `sales_unavailable` 사유와 그룹·상위 `excluded_counts` 등식. 대표 분기가 partial(일부 행 누락)인 경우. analysis 모드에서 key가 있는 경우. 값이 2^63−1에 가까운 두 항목의 합(S>2^63)을 `attach` 경유로 계산하는 경우. 0<S<N 구간의 `rounded` 값. validator 변조 거부(합계·멤버십·투영을 바꾼 payload).
- 통합 테스트: `MarketStore` 조회에 `version_id` 조건을 추가해야 한다(fixture에 버전이 여러 개면 모호해진다). 혼합 분기 fixture에서 `different_quarter` 항목이 합계에 들어가지 않는지 확인해야 한다. 지금은 반영 항목만 다시 더하므로 대표 분기 외 항목이 빠졌는지는 검증되지 않는다.
- FE: 사유 라벨, "1원 미만" 꼬리표, null 점포 수 문구에 대한 스냅샷 테스트. 분석·종합·PDF 세 화면이 같은 컴포넌트를 쓰는지 확인. 이번 검토에서는 `LocationReferenceView` 하나만 확인했다.

이 검토는 구현 완료, 테스트 통과, 배포 사실을 확인하거나 주장하지 않는다.
