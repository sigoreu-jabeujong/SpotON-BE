# 브랜드명 기반 프랜차이즈 추정 연동 FE 변경 요청

- 작성일: 2026-11-12 / 대상: SpotON FE 담당자
- BE 이슈: [#57](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/57)
- BE PR: [#93](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/93), develop 병합 완료 (`135ec63`)
- 상태: BE 구현·검증 / FE 타입·표시·진단서·계약·CLAUDE.md 반영 요청

이 문서는 이력·주변·시점·활동·Risk·AI 요청서에 공통으로 적용되는 가맹 추정 추가 계약입니다. 가맹 관련 필드·메타·필터·표시의 기준으로 함께 전달해 주세요. 각 API의 날짜·정렬·집계·오류 계약은 해당 요청서를 유지합니다.

## 1. 판정의 의미

공정위 기준년도 브랜드 목록과 인허가 상호가 정확히 정규화 일치한 기록을 **프랜차이즈 추정**으로 제공합니다. 실제 가맹계약·직영/가맹 구분·현재 실제 소속·개업 당시나 과거 시점의 소속을 확인한 값이 아닙니다. 현재 적용 목록의 기준년도는2025년입니다.

정규화는 NFKC·대소문자·공백만 처리합니다. 지점명 제거·부분일치·유사도·AI 추정은 없습니다. 반복 브랜드번호·동명·짧은 이름·미일치는 미확인으로 남습니다. 미일치를 개인 매장으로 표시하지 마세요. 브랜드 중분류와 SpotON 세부 업종의 동등성도 확인한 것이 아닙니다.

BE는 자동 근거를 별도 테이블에 보존하고 현재 상호·업종·원천 식별이 일치할 때만 조회에 반영합니다. 상호가 바뀌면 해당 근거가 적용되지 않습니다. 기존 수동/외부 가맹 필드는 보존하며 그 값의 별도 증빙까지 이번 작업에서 검증한 것은 아닙니다. FE에서 다시 이름 매칭하거나 브랜드 목록을 받아 계산하지 마세요.

FE 저장소는 BE가 수정하지 않습니다. 이 보고서는 BE 저장소의 요청이며 FE 구현·CLAUDE.md 동기화 완료를 뜻하지 않습니다.

## 2. 이력·주변·시점 행 타입

history/nearby의 기존 franchise enum은 유지합니다. **snapshot에는 franchise 필드도 신규 추가**합니다. 세 API 모두 아래 키를 반환하며 null은 키 생략을 뜻하지 않습니다.

| 필드 | 타입 | 의미 |
|---|---|---|
| franchise | franchise / independent / unknown | 기존 외부값 우선, 자동 이름 일치는 franchise(추정), 나머지 unknown |
| franchise_basis | catalog_exact_name / external_classification / null | 목록명 일치 추정 / 기존 외부 분류 / 분류 없음 |
| franchise_reference_year | integer 또는 null | 목록명 일치 추정의 기준년도. 현재2025, 그 외 null |

- `catalog_exact_name`: `프랜차이즈(추정)` 표시, 도움말에 `2025년 브랜드 목록과 상호 일치`와 계약/역사 한계를 표시합니다.
- `external_classification`: 기존 분류값을 표시하되 자동 목록명 일치나 이번에 확인한 계약 증빙이라고 설명하지 않습니다. 기준년도는null입니다.
- `unknown`: `정보 없음` 또는 `가맹 여부 미확인`입니다. 독립/개인으로 바꾸지 않습니다.
- 과거 이력의 개업/폐업 연도와 franchise_reference_year가 달라도 오류가 아닙니다. 당시 프랜차이즈였다는 문구를 사용하지 않습니다.
- 기존 source+license_no 복합 식별, 날짜/영업 기간 nullable, 위치 판정·정렬 규칙은 유지합니다. 표·지도·진단서에 같은 근거/문구를 적용해 주세요.

합성 행 발췌:

```json
{
  "source": "general_restaurant",
  "license_no": "SYNTHETIC-001",
  "franchise": "franchise",
  "franchise_basis": "catalog_exact_name",
  "franchise_reference_year": 2025
}
```

## 3. 필터 요청

기존 all/franchise/independent와 독립적인 unknown 토글을 재사용합니다. 요청 인자·엔드포인트는 추가하지 않습니다. 새 basis/년도는 응답 전용입니다.

```http
GET /api/stores/nearby?lat=37.5665&lng=126.978&category=restaurant&franchise=franchise&include_unknown_franchise=false
```

- **프랜차이즈 추정/기존 true만 보기**: franchise=franchise + include_unknown_franchise=false.
- 미확인도 포함: include_unknown_franchise=true. 기본값이true이므로 franchise만 보내면 미확인이 함께 나옵니다.
- independent + unknown=false는 기존 외부 false만 선택합니다. 현재 개발 자료에 false가0건이어도 실제 독립 점포가 없다는 뜻이 아닙니다.
- 면적 정보 없음 토글과 가맹 정보 없음 토글은 독립입니다. legacy include_unknown과 개별 토글을 섞지 않습니다.
- snapshot/activity/risk에도 같은 가맹 필터를 적용합니다. history는 건물 이력을 제공하는 기존 계약을 유지하며 가맹 필터를 새로 받지 않습니다.

## 4. 공통 meta와 기준일

history/nearby/snapshot/activity/risk에 `meta.franchise_classification`이 있습니다. 미적용 상태는 기존 pending/brand_mapping_blocked, 명시 적용 후에는 아래 형식입니다.

```json
{
  "status": "estimate",
  "reason": "reference_catalog_name_match",
  "reference_year": 2025,
  "source": ["R7"],
  "coverage": "partial",
  "historical_contract_verified": false,
  "industry_mapping_verified": false
}
```

이 status는 **가맹 분류 방법의 상태**입니다. 기존 지표의 fact/pending/link_only나 상권의 unverified를 바꾸지 않습니다. coverage=partial은 분류 범위가 제한됐다는 의미이며 수치 제공률이나 정확도가 아닙니다. R7은 공정위 브랜드 목록 출처입니다.

적용 시 `meta.data_version.brand_mapping`에 catalog_version_id/mapping_run_id/input_sha256/content_sha256/store_input_sha256/catalog_rule/rule_version/reference_year가 추가됩니다. UUID와hash는 추적·캐시 구분용이며 일반 화면에 표시하거나 조회조건/AI 본문으로 다시 보내지 않습니다. 매핑run 지문은 마지막 적용 당시 입력에 대한 기록입니다. 이후 원천 수정으로 미확인이 늘 수 있습니다.

인허가 `meta.as_of`, `meta.data_updated_at`, `meta.collected_at=null`은 유지합니다. 브랜드 기준년도를 인허가 기준일로 대입하거나 다운로드일/매핑실행일로 collected_at을 채우지 않습니다. 공통 `{data,meta,error}`·오류meta={}·기존 오류코드는 유지합니다.

## 5. Risk·AI·진단서

가맹 필터의 참고 폐업률·생존율·서울 비교는 동일한 목록명 일치 규칙으로 선택한 인허가 기록에 대한 계산입니다. **당시 실제 프랜차이즈 코호트의 폐업률/생존율이 아닙니다.** 기준년도 목록의 이름으로 과거를 선택하는 편향이 있을 수 있습니다. 기존 기간/분모/소표본·공식/참고 구분을 유지합니다.

Risk meta.limitations에 `franchise_name_match_not_contract_or_history`가 추가될 수 있습니다. 이를 알 수 없는 오류로 처리하지 말고 가맹 분류의 한계 안내에 반영해 주세요.

AI 요청은 계속 `{query: 원래 조회조건}`입니다. BE가 다시 집계하고 상태·기준년도·고정근거만 모델에 전달하며 이름/브랜드번호/UUID/hash는 전송하지 않습니다. 서버 반환 미확인 안내에는 `reason=franchise_name_match_estimate`가 추가됩니다. 이 문구를 삭제하거나 실제 계약 확인으로 바꾸지 마세요. 기존 classification_unverified도 미적용 상태에서 유지됩니다. prompt버전은risk-interpret-v5입니다. FE에서 프롬프트나 자체 판정을 만들 필요는 없습니다.

## 6. 수정·완료 기준

HistoryStore/NearbyMarker/SnapshotStore 타입·mock, 공통 meta/data_version 타입, 가맹필터 도움말, 지도·표·진단서·AI 한계 문구와 FE 계약/결정문서/CLAUDE.md를 검토해 주세요. 파일 분리와 테스트 구성은 담당자가 결정합니다.

- [ ] 실제 BE의 catalog_exact_name 행을 추정/기준년도/한계와 함께 표시
- [ ] unknown을 개인 매장으로 바꾸지 않고 null년도·근거를 처리
- [ ] 외부 분류와 자동 추정을 구분, 외부 증빙을 확인했다고 표시하지 않음
- [ ] 프랜차이즈만 조회 시 unknown=false, 정보 없음 포함 시 true 전달
- [ ] independent0건을 실제 독립 점포 부재로 단정하지 않음
- [ ] 이력·주변·snapshot·활동·Risk·진단서의 필터/표시 일치
- [ ] 과거 이력/생존율을 당시 실제 가맹계약 상태로 설명하지 않음
- [ ] estimate 분류 상태와 기존 지표/상권 상태를 구분
- [ ] AI query-only 요청·신규 한계 사유·기준일/null 유지
- [ ] FE 타입/mock/계약/CLAUDE.md 반영·lint/build·실제 연결 검증 결과 전달
