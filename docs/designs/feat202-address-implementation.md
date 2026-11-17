# 주소 상세 보존·동일 층 구현과 배포 (#202)

## 공개 배포·검증 완료 (2026-11-16, #206)

- BE PR204를 최신 매출 중앙값 PR205와 통합하고 작업 기준 문서 충돌만 두 항목 보존으로 해결했다. 최종 통합 CI는 [Backend CI](https://github.com/sigoreu-jabeujong/SpotON-BE/actions/runs/43885991671) 일반 2622 통과/OS 2 skip, 실제 PostGIS 342 통과/skip 없음, Windows·Ruff·mypy·CodeQL 모두 통과했다. 앞선 신규 엔드포인트 목록 누락도 수정 후 재검증했다.
- BE `02e8bde4146c28880dfb6ea5172b0093575717e8` / Render `dep-dbth87m1egvs73al18g0` live. 이전 운영 `f645f88`을 포함해 기존 기능을 보존했다. DB/schema0013·원본에 쓰기/마이그레이션 없이 배포했다. 기존 17개 환경변수의 값 지문 일치, 자동 배포 off 유지다.
- FE 기능 PR95 → 운영 PR97 `3bd77fdfcbf8d4f57588aed6f80092a29177ef9b` / Vercel `8BHsftQymqfu84k2EopX4x697Kuy` 성공. 이 SHA는 아래 공개 검증 기준이며 사이드바 주소 표시 보완은 [FE PR101](https://github.com/sigoreu-jabeujong/SpotON-FE/pull/101)에서 추적한다. Production v2와 기존 환경을 유지했다.
- 실제 API: ready200, 정규화 4가지와 길이 초과422, 5작업자/10개 동시 정규화 모두200. 사용자 입력 `서울특별시 마포구 양화로 45 2층`은 후보2개를 반환한다. 첫 후보(서교동490)의 이력 v1/v2 각각75건이며 `same_floor=3`, `same_building_scope=23`, `unverified=49`로 일치한다. 같은 층 3건은 기존 `location_match=unverified`를 유지해 AI 같은자리 집계로 승격되지 않는다.
- 실제 Chrome 공개 브라우저4시나리오 통과: 두 번째 후보 선택→2층201호 편집→Enter확정→결과 표시, 입력 재방문·재검색 후 층호 유지, 새 보고서 링크의 재검증과 PDF 저장/층호 표시, 모바일390px 상세 편집/가로 넘침 없음. 두 번째 후보는 `양화로 지하45`라는 별도 주소이므로 첫 후보와 같은 건물이라고 합치지 않는다. 후보 키·좌표를 선택 그대로 보존한다. 해당 공개 검증에서 history/nearby/activity/location-reference/risk/brands status와 주소 API가 모두200, 브라우저 실행 오류0이었다. AI 유료 호출은 실행하지 않았다.
- 로컬 가상API 브라우저10개 통과: 위 기본 흐름 외 오래된 검색·후보 변경 확인 응답 차단, 모호 상세 미확인 계속, Enter/필터 변경 확인 유지, 중복 floor·상세/floor 충돌 차단, 확인 중 재검색 잠김 방지, 정규화503 후 명시적 미확인 계속을 포함한다. 기능 FE216+프로필4, 최신 표시 보완 기반 FE217+프로필4 및 lint/build도 통과했다. 가상API 오류 검사는 운영 장애 재현으로 표현하지 않는다.

원천 층·호수와 지번 범위 비교이며 실제 임차/입점이나 물리적 건물·동 고유성의 확인이 아니다. 원천 상세가 없으면 상세 미확인을 유지한다. 재배포가 필요하면 이 API를 제공하는 BE를 먼저 준비하고 FE를 배포한다. 롤백 시에는 새 API를 사용하는 FE부터 이전 버전으로 되돌린 뒤 BE를 복원한다. 아래 이전 재검토·미완료 체크는 당시 기록이며 현재 완료 상태는 본 절을 따른다.

## Codex 최종 보완·실행 상태 (2026-11-16)

첫 전체 CI에서 PostGIS 341개 통과/1개 실패: `analysis_flow_helpers.ENDPOINTS`의 기존 고정 API 목록에 새 정규화 경로가 빠져 있었다. 목록을 추가하고 해당 실제 DB 흐름에서 POST 응답 전체를 검증하도록 보완했다. 최종 CI 결과는 아래 후속 실행 기록을 따른다.

아래 Claude 재검토의 단일 차단 항목(필터 변경 시 주소 재검증)을 수정했다. 확인 키는 주소·상세·업종·건물키·층호·좌표로 한정하며, 중복 파라미터 검사는 생략하지 않는다. 입력 재제출 중 확인 상태 초기화, 잘못된 URL 안내, 공통 FE 응답 타입, 입력 변경 시 이전 상세 초기화, 가드 지오코딩 60초 제한, 주석도 보완했다. 결과 표·출력용 보고서에 독립 위치 관계를 표시한다. 원문 상세가 모호하면 미확인이라고 명시하며 실제 입점·물리적 건물 고유 일치로 표시하지 않는다.

Codex 실제 실행: BE 일반 pytest 2594 통과/Windows 권한 3 skip(추가 한 테스트 이전), 보완 후 주소 단위 14 통과, 격리 PostGIS 이력/publication 10 통과. Ruff·mypy 217파일 통과. FE Vitest 216 + 배포 프로필 4 통과, 타입 포함 build·lint 통과. 로컬 브라우저 8개 통과: 단일 후보/복원/재검색, 복수 후보·호수 편집, 오래된 검색 응답 차단, 후보 변경 중 확인 응답 차단, 모호 상세 미확인 계속, Enter 확정·필터 변경 확인 유지, 중복 floor 차단, 직접 링크 상세/floor 충돌 차단. 브라우저는 실제 FE+가상 API 응답이며 운영 성공의 증거로 취급하지 않는다. API 계약은 [이력 연동 문서](../fe-store-history-api-request.md)에 반영했다. CI와 공개 배포는 다음 단계이며 아직 완료로 표시하지 않는다. 아래 재검토의 미완료 체크는 해당 검토 시점 기록이다.

사용자가 #195의 기능 구현과 FE·BE 공개 배포를 승인했다. 기존 원본/DB/schema0013·환경 비밀은 보존한다.

설계 보완: 상세 편집마다 Kakao를 다시 호출하는 대신 POST /api/address-detail에서 기존 파서만 실행한다. 이미 선택한 후보 identity·좌표를 그대로 유지하므로 상세 재확인이 다른 건물을 선택하는 문제를 피한다. 새로운 API는 DB/공급자/키가 필요 없다. 기존 API/AI location_match는 유지하며 새 location_relation으로 층 관계를 표시한다.

FE는 후보 선택과 확정을 분리하고 주소 변경 세대를 검사해 오래된 검색 응답 이동을 막는다. 입력 복원/결과/보고서가 같은 상세주소를 보존하도록 한다. 모호한 상세는 명시적으로 미확인 계속을 선택한다. 구현 검수·회귀·CI·공개 검증 결과는 실행 후 기록한다.

## 수정 후 재검토 (2026-11-16)

수정 후 코드를 다시 읽고 판단한 결과다. 검토자는 명령·테스트·네트워크·Git을 실행하지 않았다. 아래 실행 수치는 **사용자가 전달한 결과를 옮긴 것이며, 검토자가 재현하지 않았다.**

- 사용자 전달 실행 결과: BE 전체 pytest 2594 통과 / OS 사유 3건 skip, 주소 관련 집중 테스트 40건 통과. FE 테스트 215건 + 신규 4건 통과, build·lint 통과. 브라우저 4개 시나리오 통과(`address-browser-impl-results.json`: 단일 후보 재방문·재제출 시 층 보존 / 다중 후보 호수 수정 시 identity 보존 / 오래된 검색 응답 무시 / 후보 변경 후 오래된 확인 응답 무시).
- 재검토 범위(정적 읽기): BE `app/schemas/address_detail.py`, `app/routers/geocode.py`, `app/schemas/stores.py`, `app/schemas/chains.py`, `app/services/store_history.py`, `etl/address/floor_unit.py`, `tests/test_address_detail.py` / FE(`SpotON-FE-address-impl`) `src/pages/InputPage.tsx`, `src/components/common/AddressVerification.tsx`, `src/utils/addressConfirmation.ts`, `src/utils/diagnosisAddress.ts`, `src/hooks/useDiagnosisQuery.ts`, `src/api/client.ts`, `src/components/layout/ResultLayout.tsx`, `ConditionBar.tsx`, `src/components/analysis/ConditionFilterBar.tsx`, `src/pages/ReportPage.tsx`, `src/router.tsx`.

### 이전 차단 사항 1–6 처리 상태

| # | 상태 | 근거 |
|---|---|---|
| 1 후보 변경 중 이전 후보로 이동 | 해결 | `CandidateList.onSelect`가 `generation.current`를 올리고 `confirming`을 해제한다. 브라우저 4번 시나리오와 일치한다. |
| 2 미확인 상세가 주소 문자열에 섞임 | 해결 | `address`에는 기본 주소만 넣는다. 원문 상세는 `detail`, 미확인 여부는 `detailMode=unverified`로 따로 저장한다. `diagnosisAddress()`는 `… · 입력 상세: X (미확인)`으로 구분해 표시하고, ConditionBar와 보고서 머리글이 이 함수를 같이 쓴다. |
| 3 입력 복원 시 상세 중복·덮어쓰기 | 해결 | 복원 시 주소칸에는 기본 주소, 상세칸에는 `detailText ?? floorUnit`을 넣는다. 검색에 성공해도 후보에 `floor_unit`이 있을 때만 상세를 바꾼다(아래 권장 3 참고). |
| 4 응답 계약 타입 고정 | BE 해결 / FE 일부 | BE: `NormalizedDetail`·`LocationRelation`(`Literal`, `extra="forbid"`)을 `/address-detail` 응답과 `HistoryStore`·`ChainStore`에 적용했다. `reason` Literal은 `FloorUnitFailure` 값과 일치한다. FE는 아직 인라인 제네릭을 쓴다(`status: string`, 아래 권장 4). |
| 5 BE 회귀 테스트 | 실행 통과(사용자 전달) / 공백 일부 남음 | 아래 권장 5 참고 |
| 6 FE 신규 동작 검증 | 실행 통과(사용자 전달) | 목업 모드의 `/address-detail` 목업 경로는 이번에도 확인하지 않았다. |

### 남은 배포 차단 사항

1. **[FE] 결과 화면에서 필터를 적용할 때마다 주소 재검증이 일어나고 화면 전체가 내려감**
   `AddressVerification`은 `confirmed.has(search)`와 `checked === search`로 통과 여부를 판단한다. 그런데 `search`는 반경·세부 업종·시점·면적·브랜드까지 포함한 전체 쿼리 문자열이다. `ConditionFilterBar`의 "조회"(`updateQuery`)로 조건만 바꿔도 `search`가 달라진다. 그러면 `ResultLayoutContent` 전체가 "주소와 상세 위치를 확인하고 있어요…" 화면으로 바뀌고(지도·표·필터 상태가 언마운트됨), `/address-detail`과 Kakao `/geocode`를 다시 호출한다. Kakao 응답이 실패하거나 후보 순위·좌표가 바뀌면 주소를 바꾸지 않았는데도 결과 화면이 "다시 확인해 주세요"로 막힌다. 브라우저 4개 시나리오에는 결과 화면 필터 변경이 들어 있지 않다.
   → 해결: 확인 키를 identity 필드(`address`, `detail`, `detailMode`, `category`, `bk`, `floor`, `lat`, `lng`)만으로 만든다(`rememberAddress`와 가드 양쪽 모두). 그리고 "결과 화면 필터 변경 시 재검증·언마운트가 없다"는 테스트를 추가한다.

### 배포 전 정리 권장 (차단은 아님)

1. **[FE] 확인 중 다시 검색하면 확정 버튼이 계속 비활성으로 남음**: `onSubmit`은 세대를 올리지만 `setConfirming(false)`를 하지 않는다. 진행 중이던 `confirm`의 `finally`는 토큰이 달라 해제를 건너뛴다. 같은 주소로 다시 검색해 후보 1건이 선택되면 "확인 중…" 상태로 남고, 상세를 수정하거나 후보를 다시 골라야 풀린다. → `onSubmit`에서도 `setConfirming(false)`를 호출한다.
2. **[FE] 잘못된 URL이 "확인 중" 문구에 머무름**: `invalid`(중복 파라미터, `detail` 100자 초과, `detailMode`+`floor` 동시 지정 등)이면 effect가 바로 반환하고 `failed`가 설정되지 않는다. 그래서 실패 문구 대신 "확인하고 있어요…"가 계속 보인다. 하위 화면은 렌더링되지 않으므로 안전 문제는 아니다. → `invalid`일 때는 실패 문구를 보여 준다.
3. **[FE] 검색어에 층·호가 있을 때 상세 초기값**: `onSuccess`는 후보 `floor_unit`이 없고 검색어에 `층`/`호`가 있으면 상세칸에 **검색어 전체**를 넣는다. 모호한 상세라면 그 전체 문자열이 `detail`로 저장된다. 그러면 ConditionBar와 보고서에 주소가 두 번 보이고, 100자를 넘으면 `/address-detail`이 422를 반환하며 가드에서도 `invalid`로 처리된다. 사용자가 입력한 상세가 있어도 후보 `floor_unit`이 있으면 그 값으로 덮어쓴다. 다중 후보에서는 `next[0]` 기준으로 초기화되고, 후보를 고를 때 다시 맞추지 않는다.
4. **[FE] 신규 응답 타입 미공유**: `InputPage`·`AddressVerification`이 `/address-detail` 응답 타입을 인라인으로 따로 적고 있다(`status: string`). BE `NormalizedDetail`/`LocationRelation`에 맞는 공용 타입을 `types/`에 둔다.
5. **[BE] `tests/test_address_detail.py` 공백**: 이 파일은 `floor_unit` 값과 `relation_level`만 검사한다. `status`·`reason` 값, 100자 초과 422, `requested=None`/`stored=None` 경로, v1·v2 이력 응답에 `location_relation`이 실리고 `location_match`가 바뀌지 않는다는 라우트 수준 회귀는 이 파일에 없다(집중 40건에 다른 파일이 포함되었는지는 확인하지 않았다).
6. **[BE] 의미 정리**: `relation_level == "unverified"`일 때도 `building: "matched_address_scope"`를 반환한다. API 명세에 의미를 명시한다.
7. **[FE] 가드 요청 시간 제한**: 공유 링크로 처음 열 때 가드의 `/geocode`는 기본 45초 제한을 쓴다. 잠든 서버를 깨우는 입력 화면 첫 검색(60초)보다 짧아서 cold start 때 실패 문구가 뜰 수 있다.
8. **[FE] 주석 불일치**: `onSuccess`의 "1건이면 바로 결과 화면으로" 주석이 현재 동작과 맞지 않는다.

### 배포 전 완료 조건 (재검토 기준)

- [x] 이전 차단 사항 1–3 해결 (코드 확인)
- [x] BE 응답 DTO 타입 고정 (코드 확인)
- [x] BE pytest 2594 통과/3 skip, 집중 40 통과 — 사용자 전달 결과
- [x] FE test 215+4, build, lint 통과, 브라우저 4개 시나리오 통과 — 사용자 전달 결과 (typecheck 단독 실행 여부는 전달되지 않음)
- [ ] 남은 차단 1(필터 변경 시 재검증) 해결과 테스트
- [ ] API 명세에 `POST /api/address-detail`와 `location_relation` 반영
- [ ] CI 통과 기록(링크)
- [ ] FE·BE 배포 — **아직 하지 않음**
- [ ] 공개 환경 확인: 다중 후보 선택→확정, 상세 수정 중 이전 응답 무시, 모호한 상세 미확인 계속, 결과→입력 복원, 결과 화면 필터 변경 후에도 화면 유지, 공유 링크 새로 열기, 보고서 상세 표시

---

## (이전) 실제 Claude Code 구현 검토 — 수정 전 기록

아래는 수정 전에 검토한 기록이다. 현재 상태는 위의 "수정 후 재검토"를 따른다.

테스트·린트·타입 검사·CI·배포는 **실행하지 않았다.** 아래 내용은 모두 코드를 읽고 판단한 것이다.

### 설계 의도와 일치하는 부분

- **Kakao identity 전환 방지**: `/api/address-detail`은 `parse_floor_unit`만 호출하고 Kakao·DB·키를 쓰지 않는다. FE는 `{ ...selected, floor_unit: normalized }`로 이미 고른 후보의 `building_key`·좌표를 그대로 쓰므로, 상세를 다시 확인해도 건물이 바뀌지 않는다. `NO_STORE_HEADERS`, `extra="forbid"`, `hide_input_in_errors=True`, `max_length=100`도 적용되어 있다.
- **라우팅·CORS**: `/api` prefix로 등록되어 있고 CORS가 `POST`·`Content-Type`을 허용한다. FE `apiPost('/address-detail')`가 `${BASE_URL}/api/address-detail`로 호출되므로 경로가 맞는다.
- **기존 계약 유지**: `location_match`는 바뀌지 않았고 `location_relation`은 새 필드로 추가되었다. v2 `/api/v2/stores/history`는 `chain_api.stores()`의 `model_dump` 경로로 `location_relation`을 그대로 넘기며, `ChainStore`에도 필드가 있어서 `extra="forbid"`에 걸리지 않는다.
- **`HistoryQuery.floor_unit`**: 파싱되지 않는 값은 422로 거부하므로, 미확인 상세가 비교 기준으로 섞이지 않는다.
- **선택과 확정 분리 + 세대 검사**: 후보가 1건이어도 바로 이동하지 않고 확정 버튼을 거친다. 검색 `onSuccess`와 `confirm` 모두 `generation` 토큰을 비교한다. 주소·업종을 바꾸거나 상세 입력을 바꾸면 세대가 올라가 이전 응답이 무시된다.
- **모호한 상세 처리**: 정규화에 실패하면 오류 문구를 보여 주고 "상세 위치 미확인으로 계속"을 명시적으로 고르게 한다.

### (수정 전) 배포 전 차단 사항 — 처리 상태는 위 표 참고

1. **[FE] 확인 중 후보를 바꿔도 이전 후보로 이동함**
   `CandidateList`의 `onSelect`는 `setSelected`만 하고 `generation.current`를 올리지 않는다. 확정 버튼은 `confirming` 동안 비활성이지만 후보 목록은 계속 누를 수 있다. `confirm`은 호출 시점의 `selected`(A)를 클로저로 잡고 있으므로, 응답 전에 사용자가 B를 골라도 토큰이 같아 **A의 `building_key`·좌표로 결과 화면에 이동한다.** 이는 "후보 선택 후 확정"이라는 핵심 의도에 반한다.
   → 해결: 후보를 고를 때 세대를 올리거나, 확인 중에는 후보 목록을 비활성화한다. 그리고 이동 직전에 현재 선택된 후보가 확인을 시작한 후보와 같은지 비교한다.

2. **[FE] 미확인 상세가 주소 문자열에 표시 없이 섞임**
   `goToResult`가 `address`를 `[도로명/지번, c.floor_unit ?? detail.trim()]`으로 만든다. 그래서 "미확인으로 계속"을 고르거나 정규화 API가 실패했을 때도, 원문 상세(예: `101동 2층`, `1~2층`)가 `address`에 그대로 붙는다. 이때 `floor`(URL `floorUnit`)는 null이다. 결과·보고서 화면에서는 이 상세가 비교에 쓰이지 않았는데도 정규화된 주소처럼 보일 수 있다.
   → 해결: 미확인 상세는 `address`에 붙이지 않는다. 표시해야 한다면 "미확인" 표시와 함께 별도 필드로 다루고, 결과·보고서 문구를 함께 맞춘다.

3. **[FE] 입력 복원 시 상세주소가 두 군데에 저장되고 검색하면 덮어씀**
   결과 화면에서 STEP 01로 돌아오면 `initialAddress`(=`query.address`)에는 이미 상세가 붙어 있고, 상세 입력칸도 `query.floorUnit`으로 채워진다. 이 상태로 다시 검색하면 상세가 붙은 주소가 Kakao 검색어로 다시 나간다. 이어서 `onSuccess`의 `setDetail(next[0].floor_unit ?? '')`가 복원된 상세를 지운다. 2번처럼 미확인 상세가 섞여 있으면 후보의 `floor_unit`이 null이 되어 상세 입력칸이 빈칸이 된다. 설계 문단의 "입력 복원/결과/보고서가 같은 상세주소를 보존"을 충족하지 못한다.
   → 해결: URL에 기본 주소와 상세를 나눠서 저장한다(또는 복원할 때 `address`에서 상세를 떼어 낸다). 검색에 성공했을 때 사용자가 이미 입력한 상세는 덮어쓰지 않는다.

4. **[BE·FE] 신규 응답 계약이 타입으로 고정되지 않음**
   `/address-detail`의 `response_model=ApiResponse[dict[str, str | None]]`, 그리고 `HistoryStore`·`ChainStore`의 `location_relation: dict[str, str] | None`은 OpenAPI에 키·enum이 드러나지 않는다(`status`: parsed/empty/unverified, `relation_level`: same_spot/same_floor/same_building_scope/unverified, `floor`·`unit`: match/different/unknown). FE도 인라인 제네릭으로 응답 타입을 손으로 적고 있다.
   → 해결: Pydantic 모델과 `Literal`로 계약을 고정하고, API 명세 문서와 FE 타입(`types/`)에 반영한다.

5. **[BE] 회귀 테스트 공백 + 미실행**
   `tests/test_address_detail.py`는 아직 실행하지 않았다. 또한 다음 경우가 빠져 있다.
   - 요청 상세 없음(`requested=None`)일 때 `relation_level`, 즉 가장 흔한 경로
   - 저장 상세 없음(`stored=None`) → `unverified`
   - `/api/address-detail`의 `status`·`reason` 값과 100자 초과 422
   - v1 `/api/stores/history`, v2 `/api/v2/stores/history` 응답에 `location_relation`이 실리고 기존 `location_match` 값이 바뀌지 않는다는 회귀
   → 해결: 위 케이스를 추가하고 전체 pytest·ruff·mypy를 통과시킨다.

6. **[FE] 신규 동작 검증 없음**
   InputPage의 후보 선택→확정, 세대 무효화(검색·확인 각각), 미확인 계속, API 실패 경로에 대한 테스트를 확인하지 못했다. 또 목업 모드에서 `/address-detail` 목업 경로가 있는지 확인하지 않았다. 목업 응답이 없으면 `client.ts`가 실제 서버로 요청을 보낸다.
   → 해결: 테스트를 추가하고 lint·typecheck·build를 통과시킨다. 목업 경로를 추가하거나 `VITE_REAL_API_PATHS`를 어떻게 다룰지 정한다.

### (수정 전) 배포 전 정리 권장

- `location_relation`은 `relation_level == "unverified"`일 때도 `"building": "matched_address_scope"`를 반환한다. 미확인 상태와 의미가 엇갈리므로 값을 조건부로 바꾸거나 문서에 의미를 명시한다.
- 상세가 빈칸이어도 `confirm()`이 `/address-detail`을 호출한다. 서버가 잠들어 있거나 네트워크가 실패하면 상세 없이도 오류 문구가 뜬다. 빈칸이면 호출을 건너뛴다.
- `onSuccess`의 주석 "1건이면 바로 결과 화면으로"는 현재 동작(1건이어도 확정 필요)과 맞지 않는다.
- 후보가 여러 개일 때 상세 초기값이 `next[0]`에서 온다. 후보를 고를 때는 상세가 다시 맞춰지지 않는다.
- 결과·보고서 화면이 `location_relation`을 실제로 어떻게 표시하는지는 이번 범위에서 읽지 않았다. 배포 전에 따로 확인해야 한다.

### (수정 전) 배포 전 완료 조건 — 현재 기준은 위 "재검토 기준" 목록

- [ ] 위 차단 사항 1–6 해결
- [ ] BE: pytest(신규·기존), ruff, mypy 통과 기록
- [ ] FE: lint, typecheck, test, build 통과 기록
- [ ] API 명세에 `POST /api/address-detail`와 `location_relation` 반영
- [ ] CI 통과 후 FE·BE 배포, 공개 환경에서 확인: 다중 후보 선택→확정, 상세 수정 중 이전 응답 무시, 모호한 상세 미확인 계속, 결과→입력 복원, 보고서 상세 표시
- [ ] 위 실행 결과를 이 문서에 실제 수치·링크로 기록 (현재 기록 없음)
