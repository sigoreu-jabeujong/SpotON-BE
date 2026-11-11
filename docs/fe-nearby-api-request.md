# 주변 점포 조회 API 설계에 대한 FE 변경 검토 요청

- 작성일: 2026-11-12
- 요청 대상: SpotON FE 담당자
- 관련 작업: BE-13 / F-03·F-04
- BE 설계 이슈: [#38](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/38)
- BE 설계: [주변 점포 API 설계](designs/feat38-nearby-api-design.md)
- 상태: **설계안 검토 요청 / API 미구현 / FE 미반영**

## 요청 내용

주변 점포 조회 API의 공간·시점·필터 계약을 BE에서 설계하고 있습니다. 아래 FE 영향 사항을 검토해 주세요. 아직 실제 API가 구현된 것은 아니므로 이 문서를 실행 가능한 API 연동 완료 보고서로 사용하지 않습니다. FE 구현은 담당자가 계약 검토 후 진행하며, BE가 FE 코드·문서·이슈·PR을 직접 수정하거나 만들지 않습니다.

점포 이력 API의 선행 [BE PR #37](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/37)이 아직 검토 중입니다. 이 요청은 이력 요청 보고서와 별개로 주변 지도·필터·주변 점포 표·진단서에 필요한 항목을 다룹니다.

## 1. 예정 요청 계약

```http
GET /api/stores/nearby
```

| 인자 | 설계안 |
|---|---|
| lat, lng | 필수 WGS84 좌표. 기존 geocode 결과 |
| category | 필수 cafe/restaurant. 주변 조회에서는 실제 업종 필터 |
| radius | 기본 500, 300/500/1000m |
| sub_category | 음식점 korean/chinese/japanese/western, 카페 cafe. 기존 client처럼 쉼표로 전달 |
| as_of | 선택 YYYY-MM. 실제 적용일은 응답 as_of 확인 |
| area | all/lt33/33to66/66to99/gte99 |
| franchise | all/franchise/independent |
| include_unknown_area | 면적 정보 없음 포함, 기본 true |
| include_unknown_franchise | 프랜차이즈 정보 없음 포함, 기본 true |

기존 FE의 include_unknown 단독 전송은 두 조건에 같은 값을 적용하는 호환 인자로 유지하는 설계입니다. 신규 개별 인자와 기존 인자를 섞으면 422로 거절합니다. 개별 토글을 도입할 경우 공통 query 타입·변환 함수·URL 상태·query key를 함께 검토해 주세요.

**사용자 확정 사항: 0㎡는 정보 없음입니다.** BE는 DB 원본 0을 보존하고 응답 area_m2=null로 표시하며, 필터에서는 0/null을 같은 unknown으로 다루도록 설계합니다. 0㎡를 확인된 33㎡ 미만으로 표시하지 말아 주세요. 정보 없음 포함이 켜져 있으면 해당 행이 결과에 포함될 수 있고, 꺼져 있으면 제외됩니다. 합성 목업에서도 0㎡를 실측 면적으로 표시하지 않도록 검토해 주세요.

원본 API v1.2의 독립 플래그를 반영하되 이번 설계에서는 지원 업종을 늘리지 않습니다. 주변 category 필터와 달리 이력 category는 진단 맥락이라는 차이를 유지해 주세요.

## 2. 응답 타입 검토 요청

기존 NearbyStores의 center/radius_m/as_of/count/markers/message는 유지하는 안입니다. 변경·보완 검토 대상은 아래와 같습니다.

| 대상 | 요청 사항 |
|---|---|
| marker.source | general_restaurant/rest_cafe 신규 식별자. 관리번호와 함께 사용 |
| marker.name | string 또는 null. 정보 없음 표시 |
| marker.open_date | 시점 판단에 필요한 유효 날짜. 성공 마커에서는 null 아님 |
| marker.close_date | 날짜 또는 null |
| marker.operating_months | 정수 또는 null. 실제 0개월과 구분 |
| marker.operating_period_status/reason | fact/no_data 및 이력 API와 같은 사유 코드/null |
| marker.current_status | 현재 데이터의 open/closed/other. 선택 과거 시점의 색으로 재해석하지 않음 |
| marker.franchise | franchise/independent/unknown. unknown을 개인 매장으로 바꾸지 않음 |
| meta.excluded_no_coord_scope | 아래 좌표 누락 수의 집계 범위 명시 |
| meta.operating_period_basis | latest_data. 목록 운영기간이 선택 과거 T까지의 기간이 아님을 구분 |

점포 식별에는 `${source}:${license_no}`를 사용해 주세요. 지도 마커·팝업/선택 상태·표·진단서·목업에서 관리번호 단독 식별을 사용하는 경로를 함께 확인해 주세요. 구체적인 공통 타입 분리와 테스트 구성은 FE 담당자가 결정해 주세요.

영업 기간 사유 코드는 missing_open_date/invalid_open_date/missing_close_date/invalid_close_date/missing_source_date/invalid_date_order/other_status입니다. 다만 nearby는 시점 판단이 불가능한 점포를 먼저 제외하므로 모든 사유가 실제 마커에서 발생하는 것은 아닙니다. 기간 미산정에는 정보 없음과 사유, 실제 0에는 0개월을 표시해 주세요. 기간·거리·상태를 FE에서 다시 계산하지 않습니다.

## 3. 좌표 누락 수 표시를 먼저 확인해 주세요

좌표가 없으면 반경 안인지 알 수 없습니다. 현재 명세의 `excluded_no_coord`에 다음 의미를 명시하는 설계안을 제안합니다.

- 서울 전체에서 같은 업종·시점·면적·가맹 등 비공간 조건을 만족하지만 geom이 없는 점포 수.
- 응답 meta.excluded_no_coord_scope=seoul_nonspatial_cohort.
- 반경 내 누락 수나 이 동네의 누락률로 표시하지 않음.
- 반경만 바꿔도 이 값은 바뀌지 않으며, 주변 점포 수와 합산하지 않음.

표시 문구는 `서울 전체 동일 조건 중 좌표 미확보 N건`처럼 범위를 함께 보여 주거나 반경 수치와 분리하는 방향으로 검토해 주세요. **반경 내 누락 수가 반드시 필요하다면 이 정의로 확정하지 않고 위치 확인 자료와 계약을 BE와 먼저 합의해야 합니다.** 담당자 합의 전 완료로 처리하지 않습니다.

## 4. 시점·거리·필터 표시

- 기준일은 원천 갱신일을 사용합니다. D=2026-11-08인 데이터에서 2026-10 선택은 10-31, 2026-11 선택은 11-08입니다. 현재월 말일을 만들어 표시하지 말아 주세요.
- D는 원본 API v1.2 및 BE PR #37과 같은 검증 배치의 전역 갱신 최대 날짜입니다. 이는 각 원천의 전체 현황 관측 완료일을 뜻하지 않습니다.
- 과거 T에 영업했던 점포라도 현재는 closed/other일 수 있습니다. 반환 current_status를 그대로 표시합니다.
- 목록 operating_months는 현재 데이터 기준 전체 영업 기간입니다. 과거 T는 포함 점포를 고르는 기준이며 기간을 T까지로 다시 계산하지 않습니다. 오해가 없도록 표·팝업·진단서 문구를 검토해 주세요.
- BE는 반경 경계를 포함하고 최종 거리로 포함 여부를 결정합니다. 표시용 반올림 거리로 FE에서 다시 필터링하지 않습니다.
- 표시 거리만 같은 마커도 실제 거리는 다를 수 있습니다. BE의 실제 거리 순서를 유지하고 표시값·식별자로 다시 정렬하지 않습니다.
- 면적·가맹의 정보 없음 포함 여부는 독립 조건입니다. 필터 결과에 포함된 미확인 점포를 확인된 가맹점이나 면적 확인 점포로 바꾸지 않습니다.
- 현재 적재 데이터의 가맹 여부는 모두 미확인입니다. 브랜드 원천 매핑 이전에 상호로 FE가 가맹 여부를 추정하지 않습니다.
- 현재 가맹 미확인 포함을 끄면 가맹 분류에 관계없이 0건이 될 수 있습니다. 이를 확인된 가맹점이 실제로 0곳이라는 뜻으로 표시하지 않습니다. 추가 데이터 상태 안내 방식은 BE와 검토해 주세요.
- 빈 결과는 count=0, markers=[], 안내 메시지입니다. 기준일/배치가 준비되지 않은 오류를 0건으로 바꾸지 않습니다.
- 잘못된 일반 인자는 422 INVALID_PARAM, 업종 누락/잘못된 업종은 422 CATEGORY_REQUIRED, 시점 범위 밖은 422 AS_OF_OUT_OF_RANGE입니다. DB 오류·문장 timeout은 현행 500 INTERNAL_ERROR 설계입니다.

## 5. 표시 검토용 합성 응답

아래는 **API 미구현 상태의 합성 예시**입니다. 선택 시점은 2026-10-31, 최신 데이터 기준일은 2026-11-08입니다. 두 점포는 합성 중심점과 같은 좌표여서 거리 0m입니다. meta의 배치 상세는 생략했습니다.

```json
{
  "data": {
    "center": {"lat": 37.5663, "lng": 126.9779},
    "radius_m": 500,
    "as_of": "2026-10-31",
    "count": 2,
    "excluded_no_coord": 3,
    "markers": [
      {
        "source": "rest_cafe",
        "license_no": "SAMPLE-001",
        "name": null,
        "sub_category": "cafe",
        "lat": 37.5663,
        "lng": 126.9779,
        "distance_m": 0,
        "open_date": "2026-10-15",
        "close_date": "2026-11-02",
        "operating_months": 0,
        "operating_period_status": "fact",
        "operating_period_reason": null,
        "current_status": "closed",
        "franchise": "unknown",
        "area_m2": null
      },
      {
        "source": "rest_cafe",
        "license_no": "SAMPLE-002",
        "name": "예시 카페",
        "sub_category": "cafe",
        "lat": 37.5663,
        "lng": 126.9779,
        "distance_m": 0,
        "open_date": "2026-10-20",
        "close_date": null,
        "operating_months": null,
        "operating_period_status": "no_data",
        "operating_period_reason": "other_status",
        "current_status": "other",
        "franchise": "unknown",
        "area_m2": null
      }
    ],
    "message": null
  },
  "meta": {
    "source": ["R5", "R6"],
    "as_of": "2026-10-31",
    "space": "radius_500m",
    "denominator": 2,
    "data_updated_at": "2026-11-08",
    "collected_at": null,
    "is_demo": true,
    "excluded_no_coord_scope": "seoul_nonspatial_cohort",
    "operating_period_basis": "latest_data"
  },
  "error": null
}
```

## 6. 수정 검토 경로와 완료 기준

검토 대상은 `src/types/stores.ts`, `src/types/api.ts`, `src/api/params.ts`, 진단 조건 타입·URL 변환, 주변 지도·표·팝업·진단서, `src/constants/messages.ts`와 관련 목업·문서·CLAUDE.md입니다. 기존 getNearbyStores()와 query 변환 경로를 우선 활용해 주세요. BE-14 data-range나 snapshot 구현 완료를 이번 요청에 포함하지 않습니다.

후속 data-range는 원본 v1.2처럼 category 필수·sub_category 선택으로 최소 월을 계산할 계획입니다. 해당 API가 구현될 때 nearby와 같은 업종 조건을 전달해 달력 범위와 질의 허용 범위를 맞춰야 합니다.

- [ ] 좌표 누락 수의 서울 범위 표시 또는 다른 계약을 BE와 합의
- [ ] 독립 unknown 조건과 legacy include_unknown 전달 방식 확인
- [ ] 마커 복합 식별자·nullable 상호/기간·0개월 표시 반영
- [ ] 사용자 결정에 따라 0㎡ 원본의 응답 null·정보 없음 토글 처리 확인
- [ ] 과거 포함 조건과 현재 상태·전체 영업 기간의 구분 표시
- [ ] 반경·업종·면적·가맹·시점 필터의 요청 값 확인
- [ ] 0건·입력 오류·범위 오류·DB 오류 표시 확인
- [ ] 실제 API 구현 후 BE와 연결해 지도·표·진단서 검증
- [ ] FE 계약·CLAUDE.md 반영 및 결과 전달

현재 완료한 것은 BE 설계와 읽기 전용 DB·공간 함수 확인입니다. 위 API·FE 구현과 통합 검증은 대기입니다.
