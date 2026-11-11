# 점포 이력 API 연동을 위한 FE 수정 요청 보고서

- 작성일: 2026-11-12
- 요청 대상: SpotON FE 담당자
- 관련 작업: BE-12 / F-02 점포 이력
- BE 이슈: [#36](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/36)
- BE PR: [#37](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/37), develop 대상 검토 중
- 상태: **FE 검토·구현 요청 / 반영 대기**

## 요청 내용

BE에 구현한 `GET /api/stores/history`를 실제 화면과 연결할 수 있도록 FE 타입·점포 이력 표·출력용 진단서를 수정해 주세요. 현재 BE 응답에는 원천 식별자와 날짜·기간 결측이 포함됩니다. 기존 FE는 개업일과 영업 기간을 필수값으로 가정하므로 그대로 연결하면 정렬 오류나 빈 표시가 발생할 수 있습니다.

아래는 BE의 현재 구현을 기준으로 한 연동 요청입니다. FE 담당자가 계약을 검토한 뒤 반영하고, 조정이 필요한 필드는 BE와 합의해 주세요. FE 저장소의 코드·문서·이슈·PR은 FE 담당자가 관리합니다.

## 1. 대상 API와 요청 파라미터

```http
GET /api/stores/history
```

| 파라미터 | 필수 | 처리 기준 |
|---|---|---|
| `building_key` | 필수 | `/api/geocode`가 반환한 건물 키를 그대로 전달 |
| `floor_unit` | 선택 | 확인된 상세 위치만 전달. 없으면 파라미터 생략 |
| `category` | 선택 | `cafe` 또는 `restaurant`. 진단 맥락이며 이력 업종 제거 필터가 아님 |

- `category=cafe`로 요청해도 같은 건물의 지원 음식점 이력이 함께 나옵니다.
- 지원 업종은 카페와 음식점 4종(한식·중식·일식·양식)입니다. 검토 대기·제외 업종·삭제 점포는 BE에서 제외합니다.
- 지원 파라미터 외의 값, 중복 파라미터, 잘못된 건물 키·상세 위치는 `422 INVALID_PARAM`입니다.
- 공통 응답 `{ data, meta, error }`와 기존 `/api/geocode` 구조는 변경하지 않았습니다.

## 2. HistoryStore 타입 변경 요청

`src/types/stores.ts`의 `HistoryStore`에 아래 변경을 반영해 주세요. **null 허용은 키 생략을 뜻하지 않습니다.**

| 필드 | BE 응답 타입 | 요청 사항 |
|---|---|---|
| `source` | `general_restaurant \| rest_cafe` | 신규 필드. 점포 식별에 함께 사용 |
| `license_no` | string | 유지. 단독 고유 식별자로 사용하지 않음 |
| `name` | string 또는 null | null이면 `정보 없음` 표시 |
| `open_date` | ISO 날짜 문자열 또는 null | null 안전 정렬·표시 적용 |
| `close_date` | ISO 날짜 문자열 또는 null | 기존 nullable 유지. 폐업 상태인데 null인 경우도 있음 |
| `operating_months` | 0 이상의 정수 또는 null | null과 실제 0개월 구분 |
| `operating_period_status` | `fact \| no_data` | 신규 필드. 계산 완료 또는 미산정 구분 |
| `operating_period_reason` | 사유 코드 또는 null | 신규 필드. 미산정 사유 표시 |

`category`, `sub_category`, `store_status`, `franchise`, `floor_unit`, `location_match`는 기존 필드명을 유지합니다. 이번 요청 때문에 주변 점포·시점 조회 등 다른 API 타입까지 일괄 변경하지 않아도 됩니다.

### 기간 미산정 사유

| 코드 | 표시 문구 예시 |
|---|---|
| `missing_open_date` | 개업일 정보가 없어 기간을 확인할 수 없어요 |
| `invalid_open_date` | 개업일 확인이 필요해요 |
| `missing_close_date` | 폐업일 정보가 없어 기간을 확인할 수 없어요 |
| `invalid_close_date` | 폐업일 확인이 필요해요 |
| `missing_source_date` | 데이터 기준일 확인이 필요해요 |
| `invalid_date_order` | 개업일과 폐업일 확인이 필요해요 |
| `other_status` | 영업 상태 확인이 필요해요 |

문구는 FE 문구 기준에 맞춰 조정해도 됩니다. 다만 결측을 0개월로 표시하거나 폐업 상태를 영업 중으로 바꾸지 말아 주세요.

## 3. 표와 진단서 표시 요청

### 점포 식별

일반음식점과 휴게음식점에 같은 `license_no`가 있을 수 있습니다. 점포 이력 표와 진단서의 React key·중복 처리에는 `${source}:${license_no}`를 사용해 주세요. 관리번호가 같아도 원천이 다르면 서로 다른 두 행을 유지해야 합니다.

### 날짜 정렬과 결측

- BE는 개업일 오름차순, 개업일 미확인 마지막 순서로 반환합니다.
- 기존 FE의 최근 개업 순 표시는 유지하되, null을 마지막에 두고 `.localeCompare()`를 직접 호출하지 않도록 수정해 주세요.
- 같은 날짜는 source·license_no로 순서를 고정해 주세요. API 캐시 배열을 직접 정렬하지 말고 복사본을 사용해 주세요.
- 표와 출력용 진단서에 동일한 정렬·결측 표시를 적용해 주세요.
- 상호·개업일·영업 기간이 null이면 `정보 없음`을 표시하고, 기간에는 사유를 함께 보여 주세요.
- 폐업일이 null인 폐업 점포는 `폐업일 정보 없음`으로 구분할 수 있도록 해 주세요.

### 서버 계산값 표시

기간·위치·프랜차이즈는 BE가 반환한 값을 표시합니다. FE에서 다시 계산하거나 추정하지 말아 주세요.

- `operating_months=0`, `operating_period_status=fact`: `0개월` 표시.
- `operating_months=null`, `operating_period_status=no_data`: `정보 없음`과 사유 표시.
- 기간은 달력상 완료 개월 수입니다. 영업 중 점포는 검증된 원천 갱신일, 폐업 점포는 확인된 폐업일을 종료점으로 사용합니다.
- `location_match=same_spot`: 확인된 같은 자리.
- `location_match=same_building`: 확인된 같은 건물의 다른 위치.
- `location_match=unverified`: 상세 위치 미확인. 층만 같거나 한쪽 상세 위치가 없으면 이 값이 나올 수 있습니다.
- `franchise=unknown`은 `정보 없음`입니다. 개인 매장으로 바꾸지 말아 주세요.

## 4. 응답 예시

아래는 **합성 데이터**이며 화면에 필요한 필드를 중심으로 작성했습니다. `meta`의 배치 상세는 생략했습니다. `category=cafe`, 상세 위치 생략 요청에서도 음식점과 카페가 모두 반환되는 예시입니다.

```json
{
  "data": {
    "total": 2,
    "stores": [
      {
        "source": "general_restaurant",
        "license_no": "SAMPLE-001",
        "name": null,
        "category": "restaurant",
        "sub_category": "korean",
        "open_date": "2021-05-01",
        "close_date": null,
        "operating_months": null,
        "operating_period_status": "no_data",
        "operating_period_reason": "missing_close_date",
        "store_status": "closed",
        "franchise": "unknown",
        "floor_unit": null,
        "location_match": "unverified"
      },
      {
        "source": "rest_cafe",
        "license_no": "SAMPLE-001",
        "name": "예시 카페",
        "category": "cafe",
        "sub_category": "cafe",
        "open_date": "2026-11-01",
        "close_date": null,
        "operating_months": 0,
        "operating_period_status": "fact",
        "operating_period_reason": null,
        "store_status": "open",
        "franchise": "unknown",
        "floor_unit": "2층",
        "location_match": "unverified"
      }
    ],
    "message": null
  },
  "meta": {
    "source": ["R5", "R6"],
    "as_of": "2026-11-08",
    "space": "point",
    "denominator": 2,
    "data_updated_at": "2026-11-08",
    "collected_at": null,
    "collection_reason": "source_completion_time_not_recorded",
    "is_demo": true
  },
  "error": null
}
```

실제 API의 `is_demo`는 false입니다. 현재 CSV는 실제 수집 완료일이 확인되지 않아 `meta.collected_at=null`을 반환합니다. 수집일 표시를 생략하고 검증일·오늘 날짜를 대신 넣지 말아 주세요. `data_updated_at`은 검증된 원천 갱신시각 최대값의 날짜입니다.

## 5. 수정 검토 대상 파일

| 파일 | 요청 범위 |
|---|---|
| `src/types/stores.ts` | HistoryStore 필드·nullable·사유 코드 |
| `src/components/analysis/history/HistoryTable.tsx` | 복합 key·null 안전 정렬·결측 및 사유 표시 |
| `src/pages/ReportPage.tsx` | 진단서의 동일한 식별·정렬·표시 |
| `src/constants/messages.ts` | 결측 안내·기간 미산정 사유 문구 |
| `src/api/mocks/stores.ts` | 실제 응답 구조에 맞춘 합성 데이터와 경계 사례 |
| `docs/api-contract.md`, `docs/decisions.md`, `CLAUDE.md` | FE 검토 결과와 구현 계약 동기화 |

`src/api/stores.ts`의 기존 `getStoreHistory()`와 요청 파라미터 변환 경로를 재사용할 수 있습니다. 정렬 함수를 공통화한다면 표와 진단서가 함께 사용하도록 해 주세요. 구체적인 파일 분리와 테스트 구성은 FE 담당자가 결정해 주세요.

## 6. 연결 및 완료 기준

BE 기본 주소는 기존 FE 설정 `VITE_API_BASE_URL`을 따릅니다. `/api` 접두사는 기존 API client가 붙입니다. 후속 API가 아직 구현 중이면 기존 `VITE_USE_MOCK=true`, `VITE_REAL_API_PATHS=/geocode,/stores/history`로 두 API만 실제 연결할 수 있습니다. 백엔드 인증키는 FE에 전달하거나 넣지 않습니다.

- [ ] 실제 주소 검색 결과의 building_key로 점포 이력 요청 및 표시
- [ ] 같은 license_no·다른 source 2건을 표와 진단서에서 모두 유지
- [ ] open_date=null이 있어도 오류 없이 날짜 미확인 마지막으로 정렬
- [ ] name=null·기간 null은 정보 없음, 실제 0개월은 0개월로 구분
- [ ] 폐업일 없는 폐업 점포의 상태 유지 및 기간 미산정 사유 표시
- [ ] 같은 층만 확인된 점포는 same_spot으로 바꾸지 않고 서버의 미확인 표시 유지
- [ ] category=cafe 요청에서도 타 지원 음식점 이력 유지
- [ ] 0건 안내·422 입력 오류·500 서버 오류 표시 확인
- [ ] meta.collected_at=null일 때 수집일을 임의로 채우지 않음
- [ ] FE build·lint·관련 회귀 테스트 및 실제 BE 연결 확인
- [ ] FE 계약 문서·CLAUDE.md 반영 후 BE에 완료 내용 전달

BE는 기본 테스트 626개·격리 PostGIS 통합 18개·실제 API 원자료 표본 20건 대조를 통과했습니다. FE 구현·통합 완료 여부는 이 보고서를 전달한 뒤 담당자 검증 결과로 확인합니다.
