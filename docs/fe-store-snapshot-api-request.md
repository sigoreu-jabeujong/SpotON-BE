# 과거 시점 점포 조회 API 연동을 위한 FE 수정 요청 보고서

- 작성일: 2026-11-12
- 요청 대상: SpotON FE 담당자
- 관련 작업: BE-15 / F-05
- BE 이슈: [#45](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/45)
- BE 설계·검증: [snapshot 구현 기록](designs/feat45-store-snapshot-api.md)
- 상태: **BE 구현 / FE 검토·구현 요청 / 반영 대기**

## 요청 내용

`GET /api/stores/snapshot`을 시점 조회 표·상태 카드·출력용 진단서에 연결해 주세요. 기존 FE의 관리번호 단독 key, 필수 상호·기간 타입을 실제 BE의 복합 식별자·결측 처리에 맞춰야 합니다. BE는 같은 조건의 nearby 목록을 조회해 최신 데이터 기준 영업·폐업·기타로 나누며, 표본 수와 상태별 수는 서버 값을 그대로 표시합니다.

FE 코드·문서·이슈·PR은 담당자가 관리합니다. 아래 계약·문구를 검토하고 반영해 주세요. 화면 통합·FE CLAUDE.md는 반영 대기이며 이번 BE 구현으로 완료 표시하지 않습니다.

## 1. 요청과 시점

```http
GET /api/stores/snapshot?lat={위도}&lng={경도}&category=restaurant&as_of=2020-01
```

좌표·업종·반경(300/500/1000m)·세부 업종·면적·가맹·두 unknown 토글은 [주변 API 요청 보고서](fe-nearby-api-request.md)와 같습니다. **as_of=YYYY-MM은 필수**입니다. 기존 include_unknown 단독 호환은 유지하지만 개별 토글과 섞으면 같은 값이어도 거절합니다. 세부 업종은 쉼표, bool은 true/false 문자열입니다.

- 같은 필터·as_of·배치/매핑이면 snapshot stores와 nearby markers의 점포·순서·기간이 같습니다. FE에서 목록을 다시 필터링하거나 표시 거리로 재정렬하지 않습니다.
- 과거 월은 월말, 최신 데이터 월은 원천 갱신일을 사용합니다. 현재 D=2026-11-08에서 최신 월은 11-08이며 FE의 현재 날짜나 11월 말일로 바꾸지 않습니다. 표시에는 응답 data.as_of와 meta.as_of를 사용합니다.
- 달력은 [월 범위 요청 보고서](fe-data-range-api-request.md)에 따라 같은 category/sub_category로 조회하고 min_month=null을 처리합니다. snapshot 안내의 빠른 선택에도 같은 세부 업종을 전달해 주세요.
- category 누락/잘못된 업종은 422 CATEGORY_REQUIRED, as_of 누락/형식·일반 입력 오류는 422 INVALID_PARAM, 허용 월 밖은 422 AS_OF_OUT_OF_RANGE입니다. 출처/기준일 미준비·DB 실패는 500 INTERNAL_ERROR이며 정상 0건으로 바꾸지 않습니다.

## 2. 타입·식별자·결측

| 대상 | BE 응답 | 요청 사항 |
|---|---|---|
| stores[].source | general_restaurant/rest_cafe | 신규. license_no와 함께 식별 |
| name | string 또는 null | null은 정보 없음 |
| open_date | ISO 날짜 | 시점 판단을 통과한 유효 개업일 |
| close_date | ISO 날짜 또는 null | 원천의 유효 폐업일 또는 미기재 |
| operating_months | 0 이상 정수 또는 null | 실제 0개월과 결측 구분 |
| operating_period_status | fact/no_data | 신규. 계산 완료/미산정 |
| operating_period_reason | 기존 이력의 사유 코드 또는 null | 신규. 미산정 안내 |
| current_status | open/closed/other | 최신 데이터 기준 상태. 과거 시점 상태로 바꾸지 않음 |
| franchise | franchise/independent/unknown | 신규. 자동 추정·외부 분류·미확인 표시 |
| franchise_basis | catalog_exact_name/external_classification/null | 신규. 목록명 일치 추정과 기존 외부 분류 구분 |
| franchise_reference_year | integer 또는 null | 신규. 목록명 일치 추정의 기준년도, 현재2025 |
| excluded_no_coord | 0 이상 정수 | 신규. 아래 서울 범위 의미 확인 |

license_no/sub_category/lat/lng는 유지합니다. snapshot 목록에는 distance_m/area_m2를 반환하지 않지만, franchise/franchise_basis/franchise_reference_year는 반환합니다. nullable은 키 생략을 뜻하지 않습니다. [프랜차이즈 추정 요청서](fe-franchise-classification-api-request.md)에 따라 목록명 일치를 `프랜차이즈(추정)`으로 표시하고, 기준년도를 과거 시점의 실제 가맹 소속으로 해석하지 않습니다. 가맹 관련 응답 계약은 해당 요청서를 함께 따릅니다.

표·진단서·선택 상태·목업의 key는 `${source}:${license_no}`를 사용해 주세요. 같은 관리번호의 다른 원천 두 행을 합치지 않습니다. 상호가 null일 때 빈 셀을 남기지 않고 정보 없음으로 표시합니다.

기간은 **최신 데이터 기준 전체 영업 기간**입니다. open은 D, closed는 확인된 폐업일을 종료점으로 계산합니다. 과거 T까지의 기간으로 자르거나 FE에서 다시 계산하지 않습니다. other는 기간 null/no_data/other_status일 수 있고, 실제 0개월/fact와 구분합니다. 사유 코드는 이력 보고서의 7종과 같으며 주변 후보 검증으로 일부 사유는 실제 응답에 나타나지 않을 수 있습니다.

## 3. 상태 카드·요약·좌표 미확보 수

- `total_at_as_of = still_open + closed_since + other = stores.length`를 BE가 보장합니다. FE에서 합계·비율·상태를 재계산하지 않습니다.
- still_open은 최신 기록 open, closed_since는 T 이후 폐업한 최신 기록 closed, other는 휴업 등 기타/미확인입니다. 최신 데이터의 상태를 오늘 실시간 확인한 상태로 표현하지 않도록 카드·안내 문구를 검토해 주세요.
- summary_text는 실제 T·N·A/B/C로 서버에서 만듭니다. 기존 표시 경로를 유지하되 클라이언트에서 문장을 재구성하지 않습니다. 날짜는 월뿐 아니라 실제 적용일을 포함합니다.
- 0건은 200, 수 4개 모두 0, stores=[], 요약 문구가 있는 정상 응답입니다. 로딩·오류·빈 상태를 구분합니다.
- excluded_no_coord는 **서울 전체의 같은 비공간 조건에서 geom이 없는 점포 수**입니다. 반경 안인지 확인할 수 없어 N에 포함하지 않습니다. meta.excluded_no_coord_scope=seoul_nonspatial_cohort를 확인하고 주변 표본 수와 합산하지 않습니다. 표시한다면 서울 범위를 명시하고, 문구는 FE 담당자가 BE와 검토해 주세요.
- 폐업일 없는 closed·날짜 오류·원천 수집 전 사라진 행 등은 과거 조회에서 누락될 수 있습니다. 좌표 누락 수와 날짜 제외 수를 합치거나 과거 원천 전체를 관측했다고 표시하지 않습니다.

## 4. 합성 응답 예시

아래는 **합성 데이터**이며 meta의 배치·분류 버전 등 일부 상세는 생략했습니다. 브랜드 목록 적용 후에도 개별 점포는unknown일 수 있습니다. 실제 API는 is_demo=false입니다.

```json
{
  "data": {
    "as_of": "2020-01-31",
    "total_at_as_of": 1,
    "still_open": 0,
    "closed_since": 0,
    "other": 1,
    "stores": [{
      "source": "general_restaurant",
      "license_no": "SAMPLE-001",
      "name": null,
      "sub_category": "korean",
      "lat": 37.5665,
      "lng": 126.978,
      "open_date": "2020-01-01",
      "close_date": null,
      "operating_months": null,
      "operating_period_status": "no_data",
      "operating_period_reason": "other_status",
      "current_status": "other",
      "franchise": "unknown",
      "franchise_basis": null,
      "franchise_reference_year": null
    }],
    "summary_text": "2020.01.31 기준 동일 업종 1곳 → 최신 데이터 기준 영업 0곳 · 폐업 0곳 · 기타 1곳",
    "excluded_no_coord": 2
  },
  "meta": {
    "source": ["R5", "R6"],
    "as_of": "2020-01-31",
    "space": "radius_500m",
    "denominator": 1,
    "data_updated_at": "2026-11-08",
    "collected_at": null,
    "collection_reason": "source_completion_time_not_recorded",
    "is_demo": true,
    "operating_period_basis": "latest_data",
    "excluded_no_coord_scope": "seoul_nonspatial_cohort",
    "franchise_classification": {
      "status": "estimate",
      "reason": "reference_catalog_name_match",
      "reference_year": 2025,
      "source": ["R7"],
      "coverage": "partial",
      "historical_contract_verified": false,
      "industry_mapping_verified": false
    }
  },
  "error": null
}
```

collected_at=null을 오늘·검증일·적재일로 바꾸지 않습니다. data_version의 배치 ID·매핑은 nearby와 비교할 수 있지만 endpoint별 rule_version 이름은 서로 다릅니다.

## 5. 검토 경로와 완료 기준

| 경로 | 요청 범위 |
|---|---|
| src/types/stores.ts | source·기간 상태/사유·상호/기간 nullable·가맹 분류/근거/기준년도·좌표 미확보 수 |
| src/components/analysis/nearby/SnapshotTable.tsx | 복합 key·결측/0개월/사유·서버 순서 유지 |
| src/components/analysis/nearby/SnapshotBlock.tsx | 서버 집계·요약·기준일·안내와 세부 업종 범위 요청 |
| src/pages/ReportPage.tsx 및 출력용 경로 | 동일 식별·결측·서버 순서/기간 기준 검토 |
| src/api/mocks/nearby.ts, src/constants/messages.ts | 실제 응답 구조의 합성 사례·결측·최신 상태 문구 |
| docs/api-contract.md, docs/decisions.md, CLAUDE.md | 원본 v1.2·BE 보완 계약 동기화 |

기존 getStoreSnapshot()/useStoreSnapshot()과 VITE_API_BASE_URL을 재사용할 수 있습니다. 부분 실연결은 VITE_REAL_API_PATHS에 `/stores/snapshot`을 추가하는 방식입니다. 타입/표시 반영과 BE 연결 검증을 함께 진행하며 BE 인증키·DB 설정은 FE에 넣지 않습니다.

- [ ] 실제 주소·업종·필터·as_of로 snapshot 요청과 표/진단서 표시
- [ ] source+license_no 복합 식별과 다른 원천의 같은 번호 두 행 유지
- [ ] name/기간 null의 정보 없음·사유 및 실제 0개월 구분
- [ ] 가맹 분류·추정 근거/기준년도 표시와 과거 실제 가맹 소속으로 오인하지 않는 안내
- [ ] 최신 데이터 상태와 과거 포함 시점·전체 영업 기간 구분
- [ ] 서버 수 4개·요약·순서 표시와 0건/오류 처리
- [ ] 서울 범위 좌표 미확보 표시 검토, N과 합산하지 않음
- [ ] 같은 업종 조건의 data-range·최신 월 실제 적용일 확인
- [ ] FE build·lint·회귀·실제 BE 연결 및 FE 문서 반영 결과 전달

BE 테스트·원자료 대조는 구현 기록을 따릅니다. FE 구현·안내 합의·통합 완료 여부는 담당자 검증 결과로 확인합니다.
