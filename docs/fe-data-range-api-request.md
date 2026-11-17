# 조회 가능 월 범위 API 연동을 위한 FE 수정 요청 보고서

- 작성일: 2026-11-12
- 요청 대상: SpotON FE 담당자
- 관련 작업: BE-14 / F-05
- BE 이슈: [#43](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/43)
- BE 설계·검증: [데이터 월 범위 API](designs/feat43-data-range-api.md)
- 상태: **BE 구현 / FE 검토·구현 요청 / 반영 대기**

## 요청 내용

`GET /api/meta/data-range`를 달력과 빠른 시점 선택에 연결해 주세요. 기존 FE는 category만 전달하고 최소 월을 필수 string으로 가정합니다. 선택한 세부 업종에 따라 최소 월도 달라지므로 실제 점포 조회와 같은 업종 조건을 전달해야 합니다. 유효 표본이 없으면 최소 월은 null이며, 최신 월의 실제 기준일은 max_date로 구분합니다.

아래는 현재 BE 구현 기준입니다. FE 담당자가 계약·표시 방식을 검토하고 반영해 주세요. 조정이 필요한 항목은 BE와 합의합니다. FE 코드·문서·이슈·PR은 담당자가 관리하며, 이 요청은 화면 통합 완료를 뜻하지 않습니다.

## 1. 요청과 응답 타입

```http
GET /api/meta/data-range?category=restaurant&sub_category=chinese,japanese
```

| 파라미터 | 처리 기준 |
|---|---|
| category | 필수 cafe/restaurant |
| sub_category | 선택 쉼표 구분. restaurant는 korean/chinese/japanese/western, cafe는 cafe |

미지원·중복 파라미터와 빈·중복·업종 불일치 세부 업종은 422 INVALID_PARAM입니다. category 누락·잘못된 업종은 422 CATEGORY_REQUIRED가 우선합니다. lat/lng/radius/as_of/area/franchise/unknown 토글은 전달하지 않습니다.

성공 data의 다섯 키는 항상 있습니다. null 허용은 키 생략을 뜻하지 않습니다.

| 필드 | BE 타입 | FE 요청 사항 |
|---|---|---|
| min_month | YYYY-MM 또는 null | nullable로 수정. null이면 최소 월을 임의로 채우지 않음 |
| max_month | YYYY-MM | 전역 원천 갱신일의 월. 브라우저 현재 월로 대체하지 않음 |
| max_date | ISO 날짜 | 신규 필드. 최신 월 선택 시 실제 기준일 |
| data_updated_at | ISO 날짜 | 원천 갱신일. max_date와 같음 |
| collected_at | ISO 날짜 또는 null | 실제 수집 완료일. 현재 null 유지 |

최소 월은 nearby가 시점 허용 범위를 계산할 때 쓰는 날짜 후보와 같습니다. 좌표 유무·반경·면적·가맹으로 달력 범위를 바꾸지 않습니다. 과거 폐업·유효 other·좌표 미확보·면적 0·가맹 미확인도 날짜가 신뢰할 수 있으면 최소 월에 기여합니다. 범위는 서울 적재 자료의 업종별 날짜 범위이며 특정 반경의 점포 존재 범위가 아닙니다.

## 2. 시점 선택과 빈 범위

- 업종/세부 업종을 바꾸면 같은 선택 집합으로 범위를 다시 요청하고 query key에도 포함해 주세요. 세부 업종 순서를 정규화한다면 주변 조회·달력에서 표현을 일치시킵니다.
- min_month~max_month 사이만 선택하도록 합니다. 업종 변경으로 기존 as_of가 무효가 되면 안내 후 FE 선택 정책에 따라 해제·재선택하고, 기존 과거 결과를 임의로 최신 결과로 바꾸지 않습니다.
- min_month=null이면 과거 월·빠른 선택을 비활성화하고 정보 없음 안내를 표시합니다. max_month를 최소 월로 채우거나 월 유틸에 null을 전달하지 않습니다. 이 경우 nearby의 기본/최신 월은 200·0건, 다른 월은 AS_OF_OUT_OF_RANGE일 수 있습니다.
- 범위 조회의 로딩·오류·재시도와 유효 표본 없음을 구분합니다. 출처·기준일 미준비 또는 DB 오류의 500 INTERNAL_ERROR를 빈 범위로 바꾸지 않습니다.
- 최신 월은 월말 대신 max_date가 실제 기준일입니다. D=2026-11-08에서 2026-10 선택은 10-31, 2026-11 선택은 11-08입니다. 결과 표시는 각 점포 조회 응답의 as_of를 확인해 주세요.
- 빠른 선택은 max_month에서 대상 월을 계산하고 최소 월보다 앞서면 비활성화합니다. 현재 날짜를 기준으로 조회 가능한 달력을 늘리지 않습니다.
- collected_at=null을 오늘·검증일·적재일로 대체하지 않습니다. 원천 갱신일과 실제 전체 현황 수집 완료일은 다릅니다.

min_month 이후 모든 과거 월의 원천 전체 관측이 보장되지는 않습니다. 보관한 인허가 행의 날짜 구간을 재구성하므로 수집 전에 원천에서 사라진 점포는 누락될 수 있습니다. 이 한계의 표시 문구는 담당자와 검토할 항목입니다.

## 3. 응답 예시와 확인값

아래는 빈 후보 처리를 설명하는 **합성 예시**입니다. meta 배치 상세는 생략했습니다. 실제 API의 is_demo는 false입니다.

```json
{
  "data": {
    "min_month": null,
    "max_month": "2026-11",
    "max_date": "2026-11-08",
    "data_updated_at": "2026-11-08",
    "collected_at": null
  },
  "meta": {
    "source": ["R5", "R6"],
    "as_of": "2026-11-08",
    "space": "seoul",
    "denominator": null,
    "data_updated_at": "2026-11-08",
    "collected_at": null,
    "collection_reason": "source_completion_time_not_recorded",
    "is_demo": true
  },
  "error": null
}
```

현재 개발 DB 확인값은 아래와 같습니다. 목업의 2010-01로 대체하거나 FE에 하드코딩하지 않습니다. 후속 적재에 따라 달라질 수 있습니다.

| 선택 | min_month | max_month / max_date |
|---|---|---|
| restaurant 전체·korean | 1960-05 | 2026-11 / 2026-11-08 |
| chinese | 1962-03 | 동일 |
| japanese | 1966-08 | 동일 |
| western | 1965-10 | 동일 |
| cafe | 1967-10 | 동일 |

meta는 서울 범위·denominator=null이며 분모를 0으로 대체하지 않습니다. 배치·매핑 비교는 data_version의 stores_batch_ids/map_version을 사용합니다. rule_version은 범위/주변 API별 규칙이므로 이름이 서로 다릅니다.

## 4. 수정 검토 경로와 완료 기준

| 경로 | 요청 범위 |
|---|---|
| src/types/meta.ts | sub_category 입력, min_month nullable, max_date |
| src/api/meta.ts, src/hooks/useDataRange.ts, src/api/queryKeys.ts | 기존 경로 재사용·세부 업종 전달·캐시 구분 |
| src/components/analysis/ConditionFilterBar.tsx | 주변 조회와 같은 업종 조건으로 범위 요청 |
| src/components/analysis/AsOfPicker.tsx | null 안전 범위·빠른 선택·최신 월 실제 기준일 |
| src/components/analysis/nearby/SnapshotBlock.tsx | 안내의 범위 요청·null 안전 빠른 선택 |
| src/api/mocks/meta.ts, src/constants/messages.ts | 빈 범위·최신 기준일·오류 합성 사례와 문구 |
| docs/api-contract.md, docs/decisions.md, CLAUDE.md | 원본 v1.2·구현 계약 반영 |

기존 VITE_API_BASE_URL을 따릅니다. 일부 경로 실연결은 VITE_REAL_API_PATHS에 `/meta/data-range`를 추가하는 방식을 사용해 주세요. 후속 BE-15 snapshot도 구현했으며, [snapshot 요청 보고서](fe-store-snapshot-api-request.md)의 타입·표시 반영 및 연결 확인 후 해당 경로를 함께 전환할 수 있습니다. BE 키·DB 설정은 FE에 넣지 않습니다.

- [ ] 같은 category/sub_category로 범위 요청·캐시 갱신
- [ ] 실제 업종별 최소 월·범위 밖 선택 차단
- [ ] min_month=null에서 달력·빠른 선택 비활성화 및 안내
- [ ] 최신 월은 max_date·조회 as_of로 표시
- [ ] collected_at=null의 임의 대체 없음
- [ ] 로딩·오류·재시도·유효 후보 없음 구분
- [ ] 업종 변경으로 기존 선택 월이 무효가 된 경우 처리
- [ ] FE build·lint·회귀·실제 BE 연결 확인
- [ ] FE 계약·CLAUDE.md 반영 결과 전달

BE 검사·원자료 대조는 구현 기록을 따릅니다. FE 구현·표시 합의·화면 통합은 담당자 반영 대기입니다.
