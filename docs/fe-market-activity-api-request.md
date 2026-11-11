# 상권 활동 분석 API 연동을 위한 FE 수정 요청 보고서

- 작성일: 2026-11-12
- 대상: SpotON FE 담당자 / BE-22·F-06
- BE 이슈: [#60](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/60)
- 상태: **BE 기본 지표 구현·검증 / FE 검토·반영 대기**

## 1. 요청 범위

`GET /api/market/activity`의 인허가 기반 기본 지표를 실제 화면에 연결해 주세요. 기존 `src/api/market.ts`의 getMarketActivity·쿼리 변환을 재사용할 수 있습니다. FE 저장소의 코드/설정/문서·CLAUDE.md·이슈/PR은 FE 담당자가 관리합니다. 이 보고서는 BE 저장소의 변경 요청이며 FE 반영 완료를 뜻하지 않습니다.

공정위 브랜드 목록 API는 인증 승인 대기입니다. 브랜드 정보 없이 계산할 수 있는 기본 집계를 먼저 제공하고, 미확인 프랜차이즈를 개인 매장으로 바꾸지 않습니다. 매출·생활인구 원천은 DB에 적재했지만 이 API의 집계 의미/시점 호환 검증이 남아 수치는 아직 제공하지 않습니다.

## 2. 요청 파라미터

기존 nearby와 같은 lat/lng/category 필수, radius=300/500/1000(기본500), sub_category, as_of, area, franchise, include_unknown_area/include_unknown_franchise를 사용합니다. legacy include_unknown은 개별 토글과 혼합할 수 없습니다.

- category는 cafe/restaurant, 음식점 세부 업종은 korean/chinese/japanese/western입니다.
- 선택 항목 include는 sales/living_pop 쉼표 목록입니다. 예: `include=sales,living_pop`.
- include 미제공은 미요청입니다. 빈 문자열·빈 토큰·중복·대문자·앞뒤 공백·미지원 토큰은422입니다. 미요청 시 파라미터를 생략해 주세요.
- 중복 파라미터·미지원 인자도422 INVALID_PARAM입니다. 업종 누락/부적합은 CATEGORY_REQUIRED가 우선입니다.
- as_of는YYYY-MM, 최신 데이터 월은 원천 갱신일D, 과거 월은 월말T입니다. 실제 적용일은 meta.as_of입니다. 범위 밖은422 AS_OF_OUT_OF_RANGE입니다.
- 공통 외피 `{data,meta,error}`와 기존 API 경로/응답 형식은 변경하지 않았습니다. 서버/자료 준비 실패는500 INTERNAL_ERROR이고 no-store입니다.

## 3. 기존 MarketActivity 필드의 표시 기준

기존 필드명을 유지합니다. 기간과 평균은 서버 계산값을 그대로 표시하고 FE에서 현재 날짜로 다시 계산하지 말아 주세요.

| 필드 | 의미/요청 |
|---|---|
| recent_12m.period | `(YYYY-MM-DD, YYYY-MM-DD]` 실제 기간. 시작일 제외·종료일 포함 |
| recent_12m.opened/closed | 검증된 인허가 기록의 기간 내 개업/폐업 사건 수. 폐업한 점포 기록도 포함 |
| yearly_trend | 각 연도1월1일~같은 월일까지의 YTD 비교. 연간 전체로 표기하지 않음 |
| by_sub_category.open_count | T에 유효한 인허가 점포 수. 최신 상태가 폐업이어도 폐업일이T 뒤면 포함 |
| by_sub_category.avg_operating_months | 위 점포가T까지 경과한 달력 완료 개월의 평균을 버린 정수. 폐업 점포의 수명 평균/생존율이 아님 |
| avg_operating_months=null | open_count=0인 계산 불가. 정보 없음 표시 |
| avg_operating_months=0 | 실제0개월. 정보 없음과 구분 |
| sales/living_pop | 이번 릴리스는 항상null. 수치 활성화는 후속 |
| flags.missing | 요청했지만 미산정인 선택 항목만. 미요청 항목을 결측으로 추가하지 않음 |

연도별 표·차트는 `meta.yearly_comparison_basis=same_month_day_ytd`, `meta.yearly_periods[year].start/end`를 따라 비교 기간을 안내해 주세요. 실제 사건 기록이 있는 연도만 나오며, 없는 중간 연도를0으로 채우지 않습니다. 행이 존재하면서 opened/closed=0인 경우는 해당 연도에 기록은 있지만 비교 구간 안의 사건이0인 것입니다. 2/29를 비윤년에 적용할 때는2/28로 제한합니다.

평균의 `meta.operating_period_basis=elapsed_months_of_active_at_as_of`, `avg_operating_months_denominator=open_count`, `avg_operating_months_rounding=floor_mean_of_completed_months`를 확인할 수 있습니다. history/nearby/snapshot 항목의 최신 데이터 기준 전체 영업기간과 활동 API의 과거T까지 경과기간을 같은 값으로 합치지 말아 주세요.

## 4. 미확인 자료와 meta

meta.denominator는null입니다. 평균의 분모는 업종별open_count이며 활동 응답 전체에 임의의 하나의 분모를 붙이지 않습니다. meta.cohort_size는 폐업 기록을 포함한 활동 집계 대상 수이므로 현재 영업 점포 수로 표시하지 않습니다.

`meta.excluded_no_coord`는 서울 전체의 같은 비공간 조건·T 이전 개업 기록 중 좌표 미확보 수입니다. `excluded_no_coord_scope=seoul_nonspatial_cohort`, `excluded_no_coord_cohort=opened_by_as_of`이며 T 이전 폐업도 포함해 nearby/snapshot의 값과 다를 수 있습니다. 반경 내 누락 수나 점포 총수에 합산하지 않습니다.

가맹 분류는 `meta.franchise_classification={status:"pending",reason:"brand_mapping_blocked"}`입니다. 현재 모든 실제 점포의 is_franchise는null입니다. 가맹/개인 조건에서 unknown을 제외해0건이 되면 "실제 점포 없음"으로 단정하지 말고 "선택한 분류로 확인할 수 있는 정보 없음"을 안내해 주세요. 기본 unknown 포함 집계를 개인 매장 수로 바꾸지 않습니다.

선택 항목 상태는 `meta.optional_data`에 요청된 항목만 있습니다.

| 항목 | status / reason | 표시 문구 제안 |
|---|---|---|
| sales | pending / source_period_and_boundary_unverified | 매출 집계 기간과 적용 경계를 확인하고 있어요 |
| living_pop | pending / population_aggregation_and_grid_time_unverified | 생활인구 집계 기준과 격자 적용 시점을 확인하고 있어요 |

이는 원천 파일이 없다는 뜻이나 실제 수치0이라는 뜻이 아닙니다. 미요청 항목에는 optional_data 상태나 flags.missing이 없으며 결측 안내도 생략할 수 있습니다. 후속 수치 활성화 때 블록별 schema·별도meta·시점/단위를 다시 합의합니다. 현재 FE mock의 미요청 항목까지 flags.missing에 넣는 동작은 이 계약에 맞춰 수정해 주세요.

collected_at은 실제 전체 수집 완료일 미확인으로null입니다. 오늘 날짜/검증일로 채우지 않습니다. meta.data_updated_at은 검증된 전역 인허가 갱신일D, meta.as_of는 실제 적용일T입니다. 기본 출처는R5/R6이며 매출/인구 수치를 표시한 것처럼R3/R4를 기본 집계 출처로 추가하지 않습니다.

## 5. 합성 응답 예시

다음은 구조 설명용 합성 값이며 실제 점포·시연 실측값이 아닙니다. 공통 배치 상세·연도별 상세meta는 생략했습니다.

```json
{
  "data": {
    "recent_12m": {"period": "(2025-11-08, 2026-11-08]", "opened": 2, "closed": 1},
    "yearly_trend": [{"year": 2025, "opened": 2, "closed": 0}, {"year": 2026, "opened": 2, "closed": 1}],
    "by_sub_category": [{"sub_category": "cafe", "open_count": 3, "avg_operating_months": 12}],
    "sales": null,
    "living_pop": null,
    "flags": {"missing": ["sales"]}
  },
  "meta": {
    "source": ["R5", "R6"],
    "as_of": "2026-11-08",
    "data_updated_at": "2026-11-08",
    "collected_at": null,
    "space": "radius_500m",
    "denominator": null,
    "cohort_size": 4,
    "event_basis": "validated_license_dates",
    "yearly_comparison_basis": "same_month_day_ytd",
    "operating_period_basis": "elapsed_months_of_active_at_as_of",
    "franchise_classification": {"status": "pending", "reason": "brand_mapping_blocked"},
    "optional_data": {"sales": {"status": "pending", "reason": "source_period_and_boundary_unverified"}},
    "is_demo": true
  },
  "error": null
}
```

실제 API의 `is_demo`는 false입니다. 위 예시는 합성 데이터이므로 true로 표시했습니다.

## 6. 수정 검토·완료 기준

검토 대상은 `src/types/market.ts`·`src/types/api.ts`의 meta 타입, `src/api/mocks/market.ts`, `src/components/analysis/ActivitySection.tsx`·`analysis/activity/`의 기간/평균/상태 안내, `src/pages/ReportPage.tsx`의 출력 표시, 메시지와 계약 문서·FE CLAUDE.md입니다. 구체적인 파일 분리/테스트는 FE 담당자가 결정합니다. 단계 연결은 기존 VITE_REAL_API_PATHS에 `/market/activity`를 추가하는 방식으로 검토할 수 있으며 BE 인증키는 FE에 전달하지 않습니다.

- [ ] 실제API 요청/과거월·필터 변경과 기본 집계 표시
- [ ] 폐업 기록의 폐업 사건 보존·YTD 비교 구간 안내·없는 연도 미생성
- [ ] T 기준 평균과 최신 전체 기간 구분,0개월/null 구분
- [ ] 미요청 항목은missing에 넣지 않고 요청된pending 항목의 사유 표시
- [ ] 가맹 분류 미확인으로0건인 경우 점포 부재로 단정하지 않음
- [ ] data_updated_at(D)/as_of(T)/collected_at(null) 구분·좌표 누락 수 범위 안내
- [ ] 빈 집계·422/500·로딩/재시도와 표/출력 일관성 확인
- [ ] FE lint/build/관련 회귀 및 실제BE 연결 확인 후 계약 문서·CLAUDE.md 반영 결과 전달
