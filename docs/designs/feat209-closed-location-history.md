# 동일 건물·층·자리의 폐업 점포 이력: 알고리즘 분석과 구조 설계

작성일: 2026-11-17 (Asia/Seoul) · 이슈 #209 · 상태: 설계/분석, 구현·데이터 보정·추가 배포 전.

## 1. 결론과 이번 요구의 적용 기준

과거 점포 이력은 **선택한 위치와 일치하는 폐업 인허가 기록만** 보여주는 별도 조회로 바꾼다. 현재 구조는 같은 지번의 지원 업종 인허가 목록에 위치 일치 설명을 붙일 뿐이어서, 층이 다른 점포와 영업 중인 점포도 그대로 표시한다. 주소 입력칸을 고치는 것만으로 해결되지 않는다.

기본 조건은 `선택한 주소/검증된 건물 AND 명시한 층 일치 AND 폐업 상태`다. 호수까지 입력했다면 호수도 일치해야 한다. 층만 같다고 같은 자리로 표시하지 않는다. 층·호수 결측/충돌을 같은 위치라고 추정하지 않고, 일치 결과가 없다고 건물 전체 목록으로 자동 확대하지 않는다.

원천상 영업 중·휴업·기타 상태는 메인 과거 이력에 반환하지 않는다. 과거에 폐업한 사업자가 있고 같은 위치에서 다른 사업자가 현재 영업해도, 예전 폐업 기록은 유효한 과거 이력이다. **폐업 이력이 있다는 사실로 현재 공실·임대 가능 여부를 판단하지 않는다.** 현재 공실 판단은 이번 기능의 출력이 아니다.

현재 `building_key`는 물리적 건물 고유번호가 아니라 지번 주소 범위다. 따라서 1차로 가능한 ‘같은 주소 범위·층의 폐업 이력’과 추가 건물 근거가 필요한 ‘동일 건물·층의 폐업 이력’을 구분한다. 사용자 요구인 동일 건물 보장은 후자까지 갖춰야 완료다.

이번에는 BE 저장소의 설계 문서와 작업 기준만 변경한다. FE·BE 앱, DB/원본, 환경, Render/Vercel, 유료 AI 호출은 변경하지 않는다.

## 2. 조사 기준과 실제 재현

코드 기준: BE develop `1692ab28196d1580d86fb1d2b796fdd48dc95240`, FE main `913eee545716ef6706ee7ac1a4bf94671d7bca8f`. FE는 읽기만 했으며 작업 폴더의 구버전 대신 원격 main을 대조했다.

공개 GET 재현: `서울특별시 마포구 양화로 45 2층`, 업종 cafe. `/api/geocode`는 아래 두 후보를 반환하고 두 후보 모두 `floor_unit=2층`을 보존했다. 서로 다른 지번이므로 두 후보를 합치면 안 된다.

| 후보 | 도로명 | building_key |
|---|---|---|
| 첫 번째 | 서울 마포구 양화로 45 | 마포구-서교동-490-0 |
| 두 번째 | 서울 마포구 양화로 지하 45 | 마포구-합정동-414-0 |

첫 번째 후보를 `/api/v2/stores/history`에 요청한 결과다. 점포명·관리번호·개별 사업자 정보는 기록하지 않았다.

| floor_unit 입력 | 반환 건수 | 원천상 폐업 | 원천상 영업 중 | 층 일치 기록 | 층 일치 중 폐업 |
|---|---:|---:|---:|---:|---:|
| 생략 | 75 | 47 | 28 | 비교 없음 | 비교 없음 |
| 2층 | 75 | 47 | 28 | 3 | 2 |
| 2층 201호 | 75 | 47 | 28 | 3 | 2 |

세 요청의 `(source, license_no)` 전체 집합이 동일했다. 2층 요청에서 나머지 폐업 기록은 다른 층/위치 범위 15건, 상세 미확인 30건이다. 2층의 폐업 2건도 201호 일치 기록은 아니다. 해당 표본에서 **주소 범위+2층+폐업이면 2건, 주소 범위+2층201호+폐업을 엄격히 적용하면 0건**이 예상된다. 이는 물리적 건물 검증 전의 참고 수치이며 전체 서비스 정확도/전체 서울 coverage를 뜻하지 않는다.

이번 표본은 폐업일 없는 폐업 행이 0건이지만, 기존 통합 테스트에는 해당 경로가 존재한다. 일반음식점의 자료 기준은 2026-11-08, 휴게음식점은 2026-11-07이고 `collection_basis=validation_checked_at`이다. 11월17일에 사업장 현장을 확인했다거나 전체 원천의 최신 수집을 완료했다는 의미가 아니다. 여기서 ‘영업 중’은 관측 자료의 정규화 상태다.

Codex 보고에 따르면 관련 기존 단위 테스트 97개를 실행해 통과했다(Claude 검토자는 재실행하지 않음, 위 공개 GET 수치도 Codex 재현값이다; `test_store_history.py`, `test_address_detail.py`, `etl/test_floor_unit.py`). 이 결과는 현재 동작의 회귀 확인이며 아래 새 폐업/범위 정책이 구현됐다는 증거가 아니다. 공개 확인은 주소 검색과 이력 GET만 읽기 전용으로 수행했다(분석기의 v1/v2 상태 필드 대조·상세 재확인 포함 주소4회/이력8회).

## 3. 현재 처리 경로와 근본 원인

| 계층/파일 | 현재 동작 | 요구와의 차이 |
|---|---|---|
| FE `InputPage.tsx` | 후보 선택 후 상세 편집·정규화, URL의 `detail`/`floor` 보존 | 기본 주소 문자열은 층을 빼고 저장한다. 별도 floor를 같이 봐야 한다 |
| FE `api/params.ts:toStoreHistoryParams` | building_key와 존재하는 floor_unit을 보낸다 | 층 자체가 무조건 누락되는 코드는 아니다 |
| BE `schemas/stores.py:HistoryQuery` | 키 검증, 층호 파싱·정규화 | 필터 정책/범위 파라미터가 없다 |
| BE `services/store_history.py:get_history` | SQL은 `SUPPORTED_STORES AND building_key=요청키` | **status와 floor_unit 조건이 없다** |
| BE `location_match`/`location_relation` | 조회된 각 행에 층/호수 일치도를 붙인다 | 설명용 필드이며 목록을 제거하지 않는다 |
| BE `services/chain_api.py:history` | 같은 목록에 v2 브랜드 정보를 붙인다 | v1의 store_status가 v2에서는 current_status로 바뀔 뿐 필터하지 않는다 |
| FE `storeAdapters.ts` | current_status를 화면용 store_status로 변환한다 | 같은 자료의 명칭 변환이다 |
| FE `utils/history.ts`, `HistoryTable.tsx` | 최근 개업 순 정렬·더보기·관계 표시 | 폐업 전용/동일 층 전용 필터가 없다 |
| FE `ReportPage.tsx`, `useReportData.ts` | 이력 훅의 같은 자료를 출력한다 | 표만 숨기면 보고서·건수·AI와 달라질 수 있다 |

기존 `get_history`에 status 조건 한 줄만 넣으면 AI의 기존 건물 전체/같은 자리 영업·폐업 집계까지 바뀐다. `app/ai/context.py:_history`와 `app/ai/chain_context.py`가 같은 서비스를 재조회하며, `same_spot_open`, `same_spot_closed`, 분모·배치·규칙 버전을 검증하기 때문이다. API 변경의 영향을 FE 한 표로 한정할 수 없다.

## 4. 위치를 세 수준으로 나누는 기준

| 수준 | 반드시 필요한 근거 | 허용되는 설명 | 금지되는 추론 |
|---|---|---|---|
| 주소 범위 | 검증된 canonical building_key | 같은 지번 주소 범위 | 물리적 같은 건물·동 확정 |
| 같은 층 | 주소/건물 근거 + 양쪽의 명시적 정규화 층 | 같은 주소 범위·층, 또는 검증된 같은 건물·층 | 같은 층의 여러 가게를 같은 자리로 합침 |
| 같은 호수 | 위 근거 + 양쪽의 명시적 호수 일치 | 같은 주소/건물·층·호수 | 실제 임차 구획·점유·임대 가능 확정 |

현재 key는 `구-법정동-산여부/본번-부번` 조합이다(`etl/address/building_key.py`). 같은 지번에 여러 동·상가가 있으면 개별 건물을 분리할 수 없다. `location_level=same_spot`도 파서가 층과 호수를 얻었다는 내부 분류이며 현장 검증 증빙이 아니다(`etl/address/floor_unit.py`, `localdata/pipeline.py`).

층은 B1과 1층을 별도로 다루며, 201호라는 숫자만으로 2층을 추정하지 않는다. ‘A동 2층’과 ‘B동 2층’, 지상/지하 도로명, 도로명/지번의 층 충돌, 복수층, 호수 변경·구획 분할은 별도 확인 대상으로 둔다. 현재 파서는 동·복수층 등 모호한 입력을 보수적으로 거절한다. 이를 해제하려면 동 정보도 분리해 보존하는 설계가 먼저 필요하다.

반대 방향의 오류도 있다. 한 물리 건물이 여러 필지(`외 n필지`)·합필/분필·대표 지번 변경으로 **여러 building_key에 나뉘어** 있을 수 있고, 주소 파싱에 실패해 building_key가 null인 인허가는 어떤 key 조회에도 나오지 않는다. 따라서 address_scope 결과는 ‘같은 지번 범위에 섞임(과다 포함)’뿐 아니라 ‘같은 건물의 다른 지번 기록 누락(과소 포함)’ 가능성이 있다. 이 누락은 조회 대상 행 자체가 없으므로 아래 `location_coverage=partial` 계수로 드러나지 않는다. 응답은 `scope_limitations`에 `address_scope_not_physical_building`·`other_lot_records_not_searched`를 고정 사유로 항상 포함하고, FE는 0건을 ‘이 건물에 폐업 기록 없음’으로 표시하지 않는다(검토 보완 R3).

카카오 공식 문서에서 `b_code`는 법정 코드이며 건물 고유번호가 아니다. 도로명 응답의 지하 여부와 사용자 입력 점포의 지하층도 같은 개념으로 합치지 않는다. 주소 좌표나 건물명 일치만으로 물리적 건물을 확정하지 않는다. 근거: [Kakao Local 공식 응답 정의](https://developers.kakao.com/docs/ko/local/dev-guide#address-coord).

## 5. 채택 구조: 원본 후보 조회와 공개 폐업 이력 분리

권장 파이프라인은 다음 순서다.

1. 주소 후보와 상세 입력을 별도로 받고 후보의 키·좌표를 확정한다. 검색/후보/상세 변경 시 이전 요청을 취소·무효화한다.
2. BE가 층·호수를 정규화하고 `scope=floor|unit`과 요구 건물 식별 수준을 검증한다.
3. 같은 읽기 스냅샷에서 지원 업종·원천/삭제/이름 제외 정책을 적용한 위치 후보를 구한다.
4. 원천 정규화 상태 `closed`만 남긴다. `open`, `other`, null을 폐업으로 추정하지 않는다. 상태로 제외된 행은 위치가 미확인이어도 `location_coverage` 판정에 쓰지 않는다(영업 중 미확인 행 때문에 partial이 되지 않음).
5. 요청한 주소/검증된 건물 → 층 → 필요시 호수 순으로 명시적 일치만 남긴다. 각 폐업 후보는 `match`·`different`·`unresolved` 셋 중 하나로 분류한다(아래 위치 판정 규칙).
6. 남은 행의 날짜 품질과 중복 식별을 검증하고 정렬·건수·브랜드·메타를 생성한다.
7. 화면·보고서·이미지·새 AI 이력 문맥이 같은 선택 정책/버전을 사용한다.

### 폐업 후보의 위치 판정 규칙 (검토 보완 R1)

기존 `location_match`/`location_relation.relation_level`은 설명용 요약 분류다. relation_level만 필터하면 개별 floor/unit 필드의 unknown/different 구분을 잃는다. 층/호수의 세부 비교를 명시적으로 사용해야 한다. 새 서비스는 다음 순수 함수로 판정하며 기존 두 함수의 출력은 바꾸지 않는다.

| 원천 행 상태 | scope=floor (요청 층 F) | scope=unit (요청 F+U) |
|---|---|---|
| `location_level` ∉ {same_spot, same_building} 또는 floor_unit null/파싱 실패 | unresolved | unresolved |
| 층 있음, 층 ≠ F | different | different |
| 층 = F (호수 유무 무관) | match | 호수 = U → match; 호수 ≠ U → different; 호수 없음 → unresolved |
| 층 없음·호수만 있음 | unresolved (호수로 층 추정 금지) | unresolved |

- 현재 파서에서 floor+unit이면 `same_spot`, 하나만 있으면 `same_building`이 저장된다(`etl/address/floor_unit.py:FloorUnitValue.location_level`). 따라서 층만 있는 `same_building` 행은 floor 범위의 정상 match 후보다. `same_spot`만 match로 보면 표본의 층 일치 2건도 사라지므로 금지한다.
- 층 비교는 정규화 문자열(`2층`, `B1`) 동등성이다. `B1`과 `1층`은 different다.
- Codex 추가 GET 확인: 2층 폐업2건 중 1건은 층만 있고 호수가 없으며, 1건은 212호다. 201호 unit 조회에서는 전자는 unresolved, 후자는 different다. 전체 후보75건의 상태 제외28 + 다른 층15 + 다른 호수1 + 미확인31 + 일치0 = 75다.

새 서비스 `closed_location_history.py`와 새 요청/응답 모델을 두고, 기존 `get_history`는 기존 API/AI의 호환 경로로 보존한다. 공통 후보 로더를 추출할 경우 기존 전역 원천 검증·RR·이름 제외·삭제·업종 정책을 유지하는지 회귀 검사한다. FE에서 숨기기만 하는 구현은 채택하지 않는다.

### 범위 판정표

| 요청 | 원천 기록 | 폐업 메인 표 |
|---|---|---|
| 2층, floor | 같은 주소/요구 건물·2층·폐업 | 포함, 같은 층 이력 |
| 2층, floor | 같은 층·영업 중/기타 | 제외 |
| 2층, floor | 1층/B2·폐업 | 제외(different), 같은 층으로 간주하지 않음 |
| 2층201호, unit | 같은 주소/요구 건물·2층201호·폐업 | 포함, 같은 층·호수 기록 |
| 2층201호, unit | 2층202호·폐업 | 제외(different), 0건이어도 층 전체로 확대하지 않음 |
| 2층201호, unit | 2층만 있음(호수 없음)·폐업 | stores에서 제외하되 unresolved로 계수 → location_coverage=partial |
| 2층, floor | 층 미확인(상세 없음/파싱 실패)·폐업 | stores에서 제외하되 unresolved로 계수 → partial |
| 2층201호, floor 명시 선택 | 같은 주소/요구 건물·2층·폐업 | 별도 ‘같은 층’ 범위에서만 포함 |
| 201호만 입력, unit | 층을 알 수 없음 | 층 재입력 안내, 자동 추정 금지 |
| 상세 없음/1~2층/동 충돌 | 같은 주소에 기록 있음 | 상세 확인 안내, 넓은 목록 자동 반환 금지 |
| 동일 지번·다른 동/건물 | 2층·폐업 | 검증 건물 범위에서는 제외/식별 보류 |
| 예전 폐업 A + 현재 영업 B | 층·호수가 일치 | A만 반환, 현재 공실 여부는 미확인 |

UI는 호수가 있으면 unit, 명시 층만 있으면 floor를 기본 선택한다. 범위를 바꿀 때 제목·검색 조건·캐시·AI도 바뀐다. ‘같은 층’에서 ‘같은 자리’라는 표현을 사용하지 않는다.

## 6. API 계약 제안 (아직 미구현)

새 `GET /api/v2/stores/location-history`를 권장한다. 현재 경로의 기본 의미를 조용히 바꾸거나 FE가 `location_relation`만 보고 자체 필터하지 않는다.

1단계(건물 근거 미확보) 기간에는 `identity_requirement=verified_building` 요청을 422로 거절하지 않고 항상 `result_status=pending_identity`로 응답한다. FE 1단계의 기본값은 `address_scope`이며 제목은 ‘같은 주소(지번) 범위’로 표시한다. 사용자 요구인 ‘동일 건물’은 3·4단계 전에는 충족되지 않았다고 명시한다.

필수: `building_key`, `floor_unit`, `scope=floor|unit`, `identity_requirement=address_scope|verified_building`. 선택: 진단 맥락 category. 반경·면적·브랜드·as_of를 이 이력의 숨은 필터로 재사용하지 않는다. 폐업 상태는 서버 정책으로 고정하며 클라이언트가 open으로 바꿀 수 없게 한다. 두 업종의 지원 이력을 유지하고 업종 전용 보기 도입은 별도 정책으로 한다.

검증된 물리적 건물 조회에는 후속의 서버 발급 `location_id`를 추가한다. 임의 UUID나 key를 곧바로 건물 검증 근거로 신뢰하지 않는다. ID는 건물/동·선택 주소·매핑 publication과 결합되고, 조회 시 서버가 유효한 매핑과 요청 키의 관계를 검증한다.

응답의 공통 외피는 유지한다. 아래 data는 주소 범위의 2층201호를 선택했지만 원천 상세 결측 후보가 남은 경우의 예상 구조다. 아직 이 API를 구현하거나 실제 호출한 결과가 아니다.

```json
{
  "selection": {
    "scope": "unit",
    "identity_requirement": "address_scope",
    "building_key": "마포구-서교동-490-0",
    "floor": "2층",
    "unit": "201호",
    "status_filter": "closed"
  },
  "result_status": "no_data",
  "location_coverage": "partial",
  "total": 0,
  "dated_closure_count": 0,
  "undated_closure_count": 0,
  "unresolved_closed_count": 31,
  "excluded_counts": {"status": 28, "floor": 15, "unit": 1},
  "scope_limitations": ["address_scope_not_physical_building", "other_lot_records_not_searched"],
  "stores": [],
  "current_vacancy": "not_verified"
}
```

위 수치는 Codex가 추가로 확인한 표본의 호수 유무(층만 있는 폐업1건, 212호 폐업1건)를 반영한 제안 응답 예시다. 실제 새 API 호출 결과는 아니다. `excluded_counts`의 합+`unresolved_closed_count`+`total`은 주소 범위 지원 업종 후보 수(표본75)와 같아야 한다.

실제 stores는 `current_status=closed`만 허용하는 별도 typed 모델이다. `total=len(stores)`, `dated_closure_count+undated_closure_count=total`을 강제한다. meta는 `history_policy_version=closed-location-v1`, 정규화 버전, 원천별 자료 기준/수집 근거·배치, 실제 식별 수준, 건물 매핑 버전을 포함한다. 브랜드 enrichment는 최종 반환 집합에 한해서 수행하고 brand_counts의 분모도 일치시킨다.

**상태는 두 축으로 분리한다(검토 보완 R2, 초안의 단일 enum `partial`을 대체).** 초안처럼 partial을 matched/no_data와 같은 enum에 두면 표본처럼 상세 미확인 폐업 행이 하나라도 있는 거의 모든 주소에서 결과가 partial이 되고, 일치 2건이 있는 경우와 0건인 경우를 구분할 수 없다. 따라서 ‘일치 여부’와 ‘미확인 후보 존재’를 별도 필드로 둔다.

| 필드 | 값 | 의미/동작 |
|---|---|---|
| result_status | matched | 요구 식별·층/호수 조건을 만족하는 폐업 기록이 1건 이상 |
| result_status | no_data | 비교를 수행했고 일치 폐업 기록 0건 (‘이력 없음’ 단정은 location_coverage를 함께 봐야 함) |
| result_status | pending_identity | verified_building을 요구했으나 건물/동 근거 미확보·충돌. stores 비움, 비교 미수행 |
| location_coverage | complete | 상태 필터 후 남은 폐업 후보 중 unresolved 0건 |
| location_coverage | partial | unresolved 폐업 후보 ≥1건; `unresolved_closed_count`로 수 표시, 확인된 일치 행만 반환 |
| location_coverage | not_evaluated | pending_identity일 때만 |
| (FE 전용) needs_detail | — | 주소는 확정했지만 층/필요 호수가 없어 비교 불가; API 호출 없이 입력 안내 |

우선순위: 요청 검증 실패(422) → pending_identity(coverage=not_evaluated, 계수0) → matched/no_data 판정과 coverage 판정은 독립. 표시 우선순위는 FE에서 `pending_identity` > `no_data+partial`(‘확인하지 못함’) > `no_data+complete`(‘일치 폐업 기록 없음’, 단 scope_limitations 문구 병기) > `matched`(+partial이면 ‘추가 기록이 있을 수 있음’)이다. `no_data+partial`을 ‘과거 이력 없음’으로 표시하지 않는다. 확인된 0건과 조회 실패(기존 오류 외피)는 별개다.

층 미입력의 표현은 하나로 통일한다. 필드 자체 누락/타입/중복/지원 외 enum/invalid·ambiguous 상세는 422 INVALID_PARAM이다. FE가 층 미입력을 알고 있으면 요청 없이 needs_detail UI를 표시하며 API result_status에는 needs_detail이 없다. 다음은 모두 422다: scope=unit인데 층 또는 호수 누락, scope=floor인데 층 누락(호수만 입력 포함), floor_unit 파싱 실패. scope=floor에 호수가 함께 오면 허용하고 호수는 비교에 쓰지 않으며 selection에 `unit_ignored=true`를 표시한다.

공개 제외 사유는 각 행을 하나의 사유에만 넣는 우선순위 계수(상태→건물→층→호수)로 집계하고, 날짜 품질은 제외 사유가 아니라 반환 행의 dated/undated 분류다(날짜 결측 폐업은 제외하지 않음). 상세 이름/관리번호는 미확인 목록에 노출하지 않는다.

일치 행 정렬은 유효 폐업일 내림차순, 날짜 미확인 마지막, 동률 source/license_no로 안정화한다. 현재 FE `utils/history.ts:sortHistoryRecentFirst`는 개업일 내림차순으로 다시 정렬하므로 새 표·보고서·이미지는 이 함수를 재사용하지 않고 서버 순서를 그대로 쓰거나 같은 폐업일 기준 정렬 함수를 새로 둔다. 영업 기간은 `complete_months`(달력 월)만 재사용하고, 날짜 검증은 아래 7절의 원천별 기준으로 새로 구현한다(기존 `operating_period` 그대로 재사용 금지, 검토 보완 R4). 전체 배열 반환은 1차 주소 범위에서만 적용하고 페이지네이션 도입 시 total을 전체 조건 집합으로 명확히 정의한다.

## 7. 폐업·시간·식별의 세부 규칙

- LocalData 정규화에서 정상 상태 코드는 01=open, 03=closed이며 휴업/기타·상태명 충돌 등은 other다. 이 정규화 결과와 관련 근거를 사용하고 상호의 ‘폐업’ 문구·폐업일 유무만으로 상태를 덮어쓰지 않는다.
- 폐업 상태가 확인됐어도 폐업일이 결측/무효면 삭제하지 않는다. 날짜 미확인 폐업 기록으로 분리하고 기간·폐업 연도는 null로 둔다. today/자료 기준일로 폐업일을 대입하지 않는다.
- 미래/역전/원천 기준보다 뒤인 날짜는 검증된 날짜로 사용하지 않는다. 서로 다른 원천의 기준일을 섞어 기간을 계산하지 않는다. 날짜 유효성을 확인한 행만 dated_closure_count에 들어간다.
- **현재 코드와의 차이(검토 보완 R4)**: 기존 `get_history`는 `reference`를 모든 원천 배치의 `data_updated_at` 최댓값 하나로 정하고(`store_history.py`), `operating_period`가 그 값으로 폐업일 미래 여부를 판정한다. 표본처럼 일반음식점 11-08·휴게음식점 11-07이면 휴게음식점의 11-08 폐업일이 통과된다. 새 서비스는 행의 `(batch_id, source)`가 일치하는 배치의 `data_updated_at`을 그 행의 기준으로 쓰고, 배치가 없거나 원천이 다르거나 기준일이 null이면 폐업일을 미검증(undated, 사유 `missing_source_date`)으로 둔다. 기존 API의 동작은 바꾸지 않는다.
- 행마다 `closure_date_status=valid|missing|invalid|unverified_source_date`를 `operating_period_status`와 분리해 둔다. 개업일만 결측인 폐업 행은 폐업일이 유효하면 dated이고 기간만 null이다(`operating_period_status`가 no_data라고 undated로 세지 않음). `close_before_open`/폐업일<개업일은 폐업일을 invalid로 보고 undated로 센다. 1960년 이전·`close_date_future`·`close_date_invalid` 플래그도 invalid다.
- 같은 날 개·폐업이나 한 달 미만 영업은 `operating_months=0`(fact)이며 날짜 결측의 null과 구분한다.
- `(source, license_no)`가 인허가 기록 식별이다. 원천 간 같은 관리번호를 합치지 않고, 이름·좌표·층호가 같다는 이유만으로 별도 인허가를 합치지 않는다. 인허가 수를 독립 물리 점포 수라고 부르지 않는다.
- stores는 해당 식별자의 최신 적재 상태를 가진다. 같은 인허가의 상태가 다시 영업으로 갱신됐다면 현행 폐업 전용 집합에서 제외한다. 현재 DB만으로 모든 과거 폐업·재개업 사건을 복원할 수 있다고 가정하지 않는다.
- 과거 월(as_of) 당시 영업 상태와 최신 관측 상태가 폐업인 이력은 다르다. 메인 폐업 이력은 최신 관측 자료의 폐업 기록이며, 반경의 과거 시점 조회 알고리즘은 바꾸지 않는다. 완전한 사건 타임라인은 후속 불변 status_observation/이전 상태 이력이 확보돼야 한다.
- 소스별 검증일과 collected_at 미확정은 그대로 노출한다. ‘현재 영업 중 제외’는 관측 자료의 open 제외이며 실시간 현장 조사 보장은 아니다.

## 8. 물리적 같은 건물까지 보장하는 데이터 구조

기존 stores와 raw 주소를 덮어쓰지 않고 별도의 검증된 위치 근거를 제안한다. 아래 테이블/컬럼은 설계 초안이며 migration0014를 만들거나 운영0013을 바꾸지 않았다.

| 구조 | 역할/필수 속성 |
|---|---|
| location_resolution_publication | 적용 세대, 근거 원천 버전·수집시점·검증 규칙·해시·승인/되돌림 기준 |
| building_identity | 공급자와 공적 식별키, 주소 범위, 건물/동 구분, 유효기간·철거/재건축 관계 |
| store_location_evidence | source/license_no + 원본 주소 해시/배치 + publication + building_id/block + 명시 floor/unit + 매칭 근거/상태 |

매핑의 유효기간은 두 가지다(검토 보완 R6). (1) 건물 자체의 유효기간: 폐업 기록은 과거 사건이므로, 재건축·철거 전 건물에서 폐업한 기록을 현재 건물 ID에 연결하지 않는다. 폐업일이 building_identity 유효 구간 밖이거나 폐업일이 undated이면 verified_building 범위에서 unresolved로 둔다. (2) evidence 지문의 유효성: `(source, license_no)`의 원본 주소 hash·batch_id·정규화 규칙 버전 중 하나라도 바뀌면 stale이다. 인허가 재적재(새 batch)는 주소가 같아도 지문 재확인 전까지 stale로 취급해 자동 재사용하지 않는다.

위치 근거 상태는 verified/ambiguous/unverified/stale을 구분한다. 주소나 원본 배치가 바뀌어 지문이 다르면 기존 evidence를 stale로 내려 자동 재사용하지 않는다. key 하나에 여러 건물이 연결되면 사용자 선택/원천 동 근거 없이 첫 건물로 고정하지 않는다. 검색 후보도 같은 publication을 사용하고, 요청부터 결과/AI까지 한 세대에서 비교한다.

추가 공적 건물 원천의 새 연결·승인과 개별 동 구분 능력은 이번에 검증하지 않았다. 기존 SEMAS 필드는 아래 재사용 절을 먼저 확인한다. 실제 제공 ID의 범위·근거를 검증한 뒤 테이블 키를 확정한다. 공적 ID 하나가 여러 동을 포괄하면 동 식별을 추가하기 전까지 verified_building으로 승격하지 않는다. 좌표 반경·주소 유사도·카카오 b_code/장소 id를 대체 고유 건물 ID로 임의 사용하지 않는다.

세부 공간은 역사적으로 호수 명칭이 바뀔 수 있다. 층·호수 정확 일치는 해당 표기의 동일성까지만 뜻한다. 물리적으로 같은 임차 공간을 확정하려면 별도 단위 공간 ID와 유효기간/변경 근거가 필요하다. 그 전에는 ‘같은 자리 확정’ 대신 ‘층·호수 일치 인허가 기록’으로 표현한다.

엄격한 verified_building 조회는 해당 매핑이 없으면 pending_identity다. 기존 지번 기준의 참고 결과를 보려면 사용자가 ‘같은 주소 범위의 폐업 이력 참고’로 범위를 명시 변경해야 하며, 메인 표에 조용히 섞지 않는다.

## 9. FE·출력·AI를 같은 정책으로 연결

### 기존 SEMAS 자료를 먼저 검증하는 순서 (Codex 추가 대조)

프로젝트에는 이미 `etl/chains/semas.py:Outlet`이 `bldMngNo → building_no`, `flrNo → floor`, `hoNo → unit`을 투영하고 Snapshot의 rows에 보존하는 코드가 있다. 따라서 ‘건물 관련 원천이 전혀 없다’고 결론 내리거나 곧바로 사용자에게 새 API 키를 요구하지 않는다. 보유 스냅샷의 실제 필드 채움률·값 정의·관측월·사용 조건·개별 동 분리 능력을 먼저 검사한다. 이번에는 실제 스냅샷 행을 전수 읽거나 해당 값의 공적 식별 신뢰도를 승인하지 않았다.

다만 `etl/chains/linking.py:eligible`은 원천상 open, 폐업일 없음, 날짜 플래그 없음 등의 현재 사업장만 브랜드 보강 대상으로 허용한다. `compatible_details`도 명시 정보의 ‘모순 없음’ 검사여서 양쪽 상세 결측을 엄격한 위치 일치로 확인하지 않는다. linking은 building_no를 건물 일치 판정키로 사용하지 않는다. 그러므로 기존 브랜드 추정 링크를 복사하거나 eligible의 closed 금지만 없애 과거 폐업 장소의 건물·호수를 확정해서는 안 된다.

재사용은 별도의 source/license_no ↔ 원천 건물/동·층호 근거 연결로 검증한다. 현재 가게의 이름·좌표·호수를 과거 폐업 가게에 대입하지 않는다. 과거 날짜와 건물의 유효기간, 주소 충돌, 여러 인허가/원천 점포의 다대다 후보를 판정하고 애매하면 unresolved다. 보유 SEMAS로 근거가 충분하지 않은 범위에 한해서 추가 공적 건물 원천을 검토한다. 건물 번호 하나가 물리적 동이나 임차 구획까지 구분하는지는 별도 검증한다.

FE 입력/URL은 기본 주소, 정규화 floor/unit, 입력 원문, 미확인 여부와 후보 identity를 보존한다. 이력 요청은 화면 제목에 보이는 범위와 동일한 선택을 직렬화한다. 호수 입력 시 unit 범위를 기본으로 하고 floor로 확대할 때 명시 선택을 받는다. 상세 미확인으로 계속한 경우 다른 반경 분석은 가능하지만 동일 위치 과거 이력은 상세 입력 안내를 보여준다.

화면·보고서·요약 이미지에 새 이력 훅을 공통 사용하고 `total`, 정렬, 날짜 미확인, partial/pending/0건 안내를 맞춘다. React Query 키는 building_key/location_id·층호·scope·identity_requirement·FE 상수 정책 버전(closed-location-v1)을 포함한다. 매핑 세대는 요청 전에 FE가 알 수 없으므로 키가 아니라 응답 meta로 확인하고, 응답 세대가 화면의 이전 세대와 다르면 보고서/AI 결과를 재요청한다. 이전 광역 이력 캐시를 새 폐업 표의 데이터로 재사용하지 않는다. 공유 링크·주소 변경·필터 변경·인쇄 대기를 재검증한다.

AI는 서버가 같은 RR 스냅샷에서 새 폐업 이력 서비스를 다시 계산해 식별자 없는 집계만 사용한다. 새 optional location_history 선택 모델을 제안하며 기존 history와 동시 지정은 금지한다. 기존 history를 보내는 구 클라이언트의 계약은 유지한다. 새 FE는 새 선택을 보내고 기존 AI 캐시를 표시하지 않는다.

새 근거 ID/캐시에는 closed-location-v1, identity 수준/매핑 세대, 층호·scope·source 배치/규칙, `location_coverage`·`unresolved_closed_count`를 넣는다. 기존 #98 원칙대로 building_key·층호 원문은 AI 입력·로그·캐시 key 원문에 넣지 않고 집계와 HMAC 지문으로만 구분한다. 매핑 publication이 바뀌거나 evidence가 stale로 내려가면 같은 RR 스냅샷 지문이라도 다른 캐시 namespace가 되도록 publication id를 key에 포함한다. 1~2단계(매핑 없음)에서는 매핑 세대를 `null`로 고정하고, 3단계 이후 null과 실제 세대를 같은 키로 취급하지 않는다. AI 출력은 ‘선택한 층의 폐업 인허가 N건’과 ‘선택 호수 일치 폐업 인허가 N건’을 구분하고, 현재 영업 중 N건을 과거 이력 수로 소개하지 않는다. 기존 ContextHistory의 same_spot_open을 의미만 바꿔0으로 채우지 않는다. 새 DTO/서버 문장 검증을 추가하고 pending/partial/0건과 공실 미확인을 근거에 포함한다.

AI 연동이 준비되기 전에 새 표를 공개한다면 해당 위치 이력의 기존 AI 문단을 함께 숨긴다. **구체 방법(검토 보완 R5)**: 문단을 화면에서만 숨기면 서버 AI 캐시·보고서 문장에 영업 중 포함 집계가 남는다. 2단계 FE는 v1/v2 해석 요청에서 기존 선택 필드 `history`를 생략한다(현재 `toInterpretHistory`/`toRiskInterpretRequest`가 붙이는 값). 이 필드는 #98 이후 optional이므로 BE 변경 없이 가능하고, 구 FE/구 클라이언트 계약은 그대로 유지된다. 4단계의 `location_history`는 기존 `check_history_location`(같은 key 좌표 점포가 분석점 300m 이내, 좌표 점포 없는 key는 생략되는 한계 포함)을 재사용하고, v1(`app/ai/context.py`)과 v2 체인(`app/ai/chain_context.py`) 양쪽의 문맥·프롬프트 버전·선택 캐시 규칙을 함께 올린다. 한쪽만 올려 v1/v2가 다른 이력 의미를 갖게 하지 않는다. 반경 Risk 지표의 분모와 주변 점포 수·생존율·개폐업 추이까지 폐업 전용 필터로 바꾸지 않는다. 이력 선택 정책은 반경 상권 분석 정책과 별개다.

## 10. 구현 순서와 완료 기준

1. **BE 폐업/상세 선택 순수 함수와 새 API**: 현재 지원 범위를 유지하며 closed-only·층/호수 exact·결측 상태·건수/분모를 구현한다. 기존 get_history/구 AI 계약은 보존한다. 신규 API의 OpenAPI 고정 목록·버전/오류 테스트도 갱신한다.
2. **FE 전용 이력 연결**: 새 훅·캐시·범위 UI·제목·표·보고서·이미지, 상세 미확인/부분/0건/오류를 맞춘다. 이 단계의 주소 범위 결과를 물리적 같은 건물 완료라고 표시하지 않는다. 같은 FE 배포에서 AI 해석 요청의 `history` 필드를 생략한다(9절 R5). BE 1단계가 운영에 live인 것을 확인한 뒤 FE를 공개한다(BE 선배포, FE 후배포). 1~2단계만으로 사용자 요구 중 ‘영업 중 제외·선택 층/호수 일치’는 충족 가능하지만 ‘동일 물리 건물’은 3단계 결과에 따라 pending으로 남는다.
3. **건물 식별 근거 확보·검증**: 실제 공식 원천·ID/동 구분을 검증하고 불변 evidence를 preview/검토/복구 검증 후 적용한다. 원본 보존·전수 지문·동일 지번 복수 건물·재건축·미확인 비율을 점검한다. 없으면 이 단계만 pending으로 둔다.
4. **엄격 건물 범위와 새 AI 계약**: 동일 publication·같은 RR·캐시/근거/문장 검증을 연결한다. FE와 BE의 호출 순서가 호환되는 순서로 배포한다. 기존 API를 사용하는 구 FE/AI를 깨뜨리지 않는다.
5. **운영 확인**: 사용자 주소 두 후보·다른 층/호수/동·영업 중 제외·0건/partial·보고서·모바일·동시 요청을 검증한 후 완료 기록을 남긴다. 이번 설계 PR은 기능 완료/운영 적용을 뜻하지 않는다.

필수 인수 조건:

| 범주 | 확인할 사항 |
|---|---|
| 상태 | open/other/null은 메인 배열·total·브랜드 counts·새 AI 폐업 집계에 0건; closed만 허용 |
| 위치 | 다른 층·지하/지상·다른 호수·다른 동·동일 지번 복수 건물 혼입 0건 |
| 세부 결측 | 상세 없음/모호/충돌은 안내 또는422; 원천 상세 결측을 일치로 추정하지 않음 |
| 범위 | unit의0건을 floor/주소 전체로 자동 대체하지 않음; 명시 범위 변경 시 제목/캐시도 변경 |
| 표본 | 주소 범위2층 floor: matched·total2·coverage=partial(층 미확인 폐업 후보30 존재 가정); 2층201호 unit: no_data·total0·coverage=partial; verified_building은 매핑 없으면 pending_identity·not_evaluated. 계수 합=후보75 |
| 상태 축 | matched/no_data와 complete/partial 4조합과 pending_identity 각각의 FE 문구; no_data+partial을 ‘이력 없음’으로 표시하지 않음 |
| 날짜 | 날짜 결측 폐업 유지·기간null, 미래/역전·동일일 경계, 실제0개월과null 구분; 휴게음식점 행의 폐업일이 자기 원천 기준일(11-07) 뒤·일반음식점 기준일(11-08) 이하이면 undated; 개업일만 결측인 폐업은 dated |
| 식별 | source+license_no 충돌/재적재/원본 변경 evidence stale/매핑 세대 변경 재검증 |
| 시간 | 폐업 후 재영업된 최신open은 제외; 폐업A+현재영업B에서A는 유지, 공실 판정 금지 |
| 출력 | 표=건수=보고서=이미지=새 AI 정책 집합; 기존 건물 전체/구 AI는 회귀 통과 |
| 운영 | 무료 풀1 조건의 동시 조회, 취소/타임아웃, DB/원본 지문·환경값 보존 |

위치 evidence 전수 보강이나 자료 최신 수집은 별도 실행이다. 새 API의 실제 반환 수·운영 성능·엄격 건물 coverage는 구현 후 측정하며 이번 표본/단위 테스트로 대신하지 않는다.

## 11. 검토 기록

Codex: 현재 코드·공개 API·기존 테스트를 대조해 작성. 실제 Claude Code의 문서 Read/Edit 검토 후 쟁점을 보완하고 최종 채택 결정을 이 절에 기록한다. 검토자는 DB/네트워크/앱 변경이나 테스트·배포를 실행하지 않는다.

### 11.1 Claude Code 실제 검토 (2026-11-17)

**검토 범위**: Read/Edit 도구만 사용. 읽은 파일은 이 설계 MD, BE `app/services/store_history.py`, `app/schemas/stores.py`, `app/schemas/address_detail.py`, `etl/address/floor_unit.py`, `app/ai/context.py`(앞부분, #98 이력 검사 상수·import), FE `src/api/params.ts`, `src/utils/history.ts`다. `chain_api.py`, `chain_context.py`, `building_key.py`, `localdata/pipeline.py`, FE `storeAdapters.ts`와 테스트 파일은 이번에 직접 읽지 않았으며, 해당 서술은 Codex의 대조 결과를 따른다. 2절의 공개 GET 수치와 97개 단위 테스트 통과는 Codex가 전달한 결과이고 검토자가 재현·실행하지 않았다. DB·네트워크·테스트·배포는 실행하지 않았고 이 MD 외의 파일은 수정하지 않았다.

**판정**: 방향(새 API 분리, 기존 get_history/구 AI 보존, address_scope와 verified_building 구분, 공실 미판정)은 타당하다. 아래 차단 2건은 이 문서에서 보완했으므로 1단계 구현 착수가 가능하다. 3단계(건물 식별)는 원천 미확보로 pending이 맞다.

| ID | 구분 | 발견 | 근거 | 보완(이 문서 반영 위치) |
|---|---|---|---|---|
| R1 | 차단(보완함) | 위치 일치 판정에 기존 `location_match`/`location_relation`을 쓰면 층만 있는 행이 match에서 빠지거나(same_spot만 볼 때) `unknown`/`different`가 섞여 partial 계수가 틀어짐 | 파서가 층 단독이면 `same_building`을 저장; `location_relation`은 호수 없음과 다름을 모두 `unknown`/`different`로 혼용 | 5절 ‘위치 판정 규칙’ 표: match/different/unresolved 3분류 순수 함수 |
| R2 | 차단(보완함) | 초안 단일 enum의 partial이 matched/no_data를 덮어, 미확인 행이 흔한 실제 주소에서 거의 항상 partial이 되고 ‘2건 일치’와 ‘0건’을 구분 못 함. 예시 JSON(partial·total0)과 10절 표본(2건/0건)도 서로 다른 상태 체계를 씀 | 표본: 2층 범위에서도 상세 미확인 폐업 30건 | 6절: `result_status`(matched/no_data/pending_identity) × `location_coverage`(complete/partial/not_evaluated) 두 축, 표시 우선순위, 계수 합 불변식; 예시 JSON·10절 표본 행 통일 |
| R3 | 권고(보완함) | 같은 지번의 여러 건물(과다)만 다루고 한 건물의 여러 지번·building_key null 행(과소)은 누락 | `외 n필지` 대표 지번 규칙, key 생성 실패 행 | 4절: `scope_limitations` 고정 사유, 0건을 ‘이 건물 기록 없음’으로 표시 금지 |
| R4 | 권고(보완함) | ‘원천 기준일을 섞지 않는다’와 ‘기존 기간 계산 재사용’이 모순. 기존 코드는 전 원천 최대 `data_updated_at` 하나로 폐업일 미래 여부를 판정 | `store_history.py`의 `reference = max(...)` | 7절: 행 자기 배치 기준일, `closure_date_status` 분리, 개업일만 결측인 폐업은 dated; 6절 정렬·FE 정렬 함수 재사용 금지 |
| R5 | 권고(보완함) | ‘AI 문단 숨김’만으로는 서버 캐시·보고서에 영업 중 포함 집계가 남음. v1/v2 AI 동시 갱신과 300m 위치 검사 재사용이 명시되지 않음 | FE `toInterpretHistory`가 history를 항상 붙임; #98 history는 optional | 9절: 2단계 FE는 `history` 생략, 4단계는 v1·v2 체인 문맥 동시 버전 상승 |
| R6 | 권고(보완함) | 매핑의 시간 유효성(재건축 전 폐업 기록)과 재적재 시 evidence 지문 기준이 불명확 | 폐업 기록은 과거 사건 | 8절: 건물 유효 구간 밖·undated는 unresolved, batch/주소hash/규칙 변경 시 stale; 9절: 캐시에 publication id, null 세대 구분 |
| R7 | 권고(보완함) | 1단계에서 verified_building 요청 처리와 floor 범위의 호수 동반, 호수만 입력 시 422 여부가 불명확 | — | 6절: verified_building은 1단계에 항상 pending_identity, floor+호수는 허용·`unit_ignored`, 호수만은 422 |
| R8 | 권고(해결됨, 11.2·11.3) | 표본의 ‘2층 폐업2건이 201호 일치 아님’이 호수 다름인지 없음인지 미기록 | 2절 서술 | Codex 추가 GET: 층만 있는 폐업1건(unresolved)+212호 폐업1건(different unit). 5절 판정 근거·6절 JSON 반영. 새 API 구현 후 실제 응답으로 재확인 |
| R9 | 참고 | ‘폐업 후 재영업된 최신 open 제외’는 현행 stores 최신 상태 모델과 일치하나, 같은 관리번호의 이전 폐업 사건은 복원 불가 | 7절 기존 서술 | 변경 없음. 완전한 사건 타임라인은 후속 status_observation |

**채택 결정**: R1~R7 반영본을 최종 명세로 한다. 단일 enum `partial` 설계는 폐기하고 두 축 모델로 통일한다. 이 검토는 설계 문서 보완이며 API/FE/AI 구현, 테스트 실행, 데이터 보정, 배포 완료를 뜻하지 않는다.

### 11.2 Codex 최종 대조·보완

- R1~R7을 재확인해 채택했다. R1의 ‘혼용’은 relation_level만 보고 필터할 때 세부 unknown/different를 잃는다는 의미로 명확히 했다. 기존 floor/unit 비교 필드 자체가 같은 값을 반환한다는 주장은 하지 않는다.
- R8은 실제 추가 조회로 해결했다. 2층 폐업2건은 호수 결측1건과 212호1건이다. unit201호는 확인 일치0, 미확인31, 상태 제외28/다른 층15/다른 호수1이며 총75다. 제안 JSON과 판정표에 반영했다. 새 API는 여전히 미구현이다.
- 기존 SEMAS의 건물관리번호·층·호수 필드 보존과 open 전용 브랜드 연결 코드를 직접 읽고 재사용 검증 순서를 추가했다. 건물 관련 원천이 전혀 없다는 뜻으로 읽히지 않도록 보완했다. 폐업 당시의 물리 건물·동/임차 공간 식별 근거는 여전히 검증이 필요하다.
- 1·2단계는 ‘주소 범위+명시 층/호수+폐업’에 한정해 제공한다. 3·4단계 이후 검증된 건물 조회를 기본으로 전환하며, 실패하면 주소 범위로 자동 대체하지 않는다. 별도 선택한 참고 조회와 엄격 건물 조회를 구분한다.
- 이번 결과는 구조 설계·실제 현재 동작 검증이다. 앱 구현·FE 변경·DB 보정·기능 배포를 실행한 것으로 표시하지 않는다.

### 11.3 Claude Code 좁은 최종 재검토 (2026-11-17)

**읽은 범위**: Read/Edit만 사용. 이 설계 MD 전체, `etl/chains/semas.py`, `etl/chains/linking.py`. 다른 앱/FE/테스트 파일은 다시 읽지 않았다. 공개 GET(R8 추가 조회 포함)과 기존 단위 테스트 97개는 Codex가 전달한 결과이며 검토자가 실행·재현하지 않았다. Bash·네트워크·DB·테스트·배포는 실행하지 않았고 이 MD 외 파일은 수정하지 않았다.

**판정: PASS(차단 결함 0)**. 이 재검토에서 수정한 것은 R8 행 표기와 이 절뿐이다.

- **SEMAS 재사용 절(9절) 사실 확인**: `semas.py:project`는 `bldMngNo→building_no`, `flrNo→floor`, `hoNo→unit`을 공백 정리한 원문 문자열로 투영하고 `Snapshot.rows`에 보존한다(정규화·검증된 건물 ID로 해석하지 않음). `linking.py:eligible`은 `status=="open"`·`close_date is None`·`date_flag` 없음·비한시·유효 개업일만 허용하고, `compatible_details`는 양쪽에 명시된 floor/unit의 충돌만 거절하며 결측은 통과시키는 ‘모순 없음’ 검사다. 주소 연결 키 `address_keys`는 lot/road 키만 쓰고 building_no는 사용하지 않는다. 설계 서술과 일치한다.
- **보충 주의(문서 반영 불요, 구현 시 참고)**: `Outlet`에는 영업 상태·개폐업일 필드가 없고 Snapshot은 단일 `reference_month` 관측이다. 따라서 과거 폐업 인허가의 건물 근거로 쓰려면 폐업 시점과 관측월의 시간 불일치를 9절·8절(R6) 규칙대로 unresolved로 다뤄야 한다. 이는 기존 ‘현재 가게 정보를 과거 폐업 가게에 대입 금지’와 같은 방향이다.
- **R8 계수 확인**: 2층 floor 기준 폐업47 = 일치2 + 다른 층15 + 층 미확인30. unit 201호에서 일치2가 호수 결측1(unresolved)·212호1(different unit)로 나뉘므로 unresolved 31, excluded {status28, floor15, unit1}, total0이다. 28+15+1+31+0=75로 6절 JSON·5절 서술·불변식과 맞는다. 10절 표본의 floor 범위 ‘층 미확인30’과 unit 범위 31도 모순이 없다. 11.1의 R8 ‘미반영’은 해결로 갱신했다(숫자는 Codex 재현값이며 새 API 실제 응답은 구현 후 확인).
- 11.2 Codex 결정(1·2단계 주소 범위 한정, 엄격 건물 조회 실패 시 자동 대체 금지, SEMAS 우선 검증 후 추가 원천 검토)을 수용한다. 구현·데이터 검증·배포 완료를 뜻하지 않는다.
