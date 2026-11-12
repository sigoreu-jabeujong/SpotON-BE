# FE 요청서 재검증과 원천 배치 조회 지연 검토 (#78)

- 작성일: 2026-11-12
- 기준: BE develop `1f81baf`, FE develop `21ec13f`
- 브랜치: `feat#78-audit-recheck`
- 요청: FE 감사 요청서 재검증 → 실제 Claude Code 재점검 → 합의한 방향으로 수정·검증.

## 1. 범위와 재관측

FE 직접 수정 금지는 유지한다. 새 요청의 FE 수정 범위는 사용자에게 확인 중이며 답변 전에는 FE 파일·문서·이슈·PR을 변경하지 않는다. 요청서의 query-only AI 본문, unverified 표시, null 안전 정렬, source+license_no 식별, 결측/0 구분 방향을 실제 코드와 재대조한다.

실제 Chrome에서 정상 이력 5행·과거 2024-02-29 조회200을 재확인했다. BE 스키마를 통과한 합성 응답으로 다른 원천 동일 관리번호의 중복 key 경고, null 상호·기간 빈칸, null 개업일의 localeCompare 오류(표0행·진단서main0)를 다시 재현했다. 브라우저용 실모델 송신0을 강제했다. 키 값이나 원문 화면·주소는 저장하지 않는다.

추가로 실제 화면의 여러 API 동시 조회에서 이력·주변·활동·Risk가 약3.0초 후500으로 실패했다. 단독 이력은2.266초/0.328초200이었다. 타임아웃 SQLSTATE를 아직 수집하지 않았으므로 모든500의 동일 원인을 단정하지 않는다.

읽기 전용 EXPLAIN ANALYZE에서 현재 연결 배치 조회의 EXISTS가 Merge Join/집계로 변환되어 stores 355,835행을 읽었다(325.517ms, hit2,266/read32,874 blocks). 같은 조건의 상관 scalar subquery `SELECT stores.id ... LIMIT 1 IS NOT NULL`은 각 배치당 한 행을 찾았다(0.416ms, hit3/read67 blocks, 실제 배치2개). 측정값은 개발 DB의 한 시점이며 SLA가 아니다. 초기/동시 지연과 관련 있는 불필요한 전역 읽기를 줄이는 수정 후보로 삼는다.

## 2. 검토한 변경안과 보존할 계약 (미적용)

- 연결된 지원 점포가 존재하는 배치만 반환하는 공통 조회 함수를 추가하고 history·current_provenance의 중복 쿼리를 대체한다.
- 배치 UUID와 source를 모두 대조하고, 기존 SUPPORTED_STORES와 배치 정렬을 그대로 유지한다. id는 NOT NULL PK이므로 scalar 결과의 null 여부로 존재를 판단할 수 있다.
- 배치와 매칭되는 점포가 없으면 scan 비용은 남는다. 인덱스·migration·DB 설정을 이번에 추가하거나 실제 개발 DB에 쓰지 않는다.
- current_provenance의 미연결 점포·잘못된 기준일 검증은 유지한다. history는 기존의 결측 보존 정책을 유지한다. 기준일은 건물/업종 필터와 무관한 전역 연결 배치의 최대값이다.
- READ ONLY REPEATABLE READ·SQL3초·캐시 무효화·공개 API/응답·FE 계약은 바꾸지 않는다. 지연을 숨기기 위해 timeout을 늘리지 않는다.

## 3. 검증·완료 기준

격리 PostGIS에서 기존 EXISTS와 새 쿼리의 배치 목록·순서를 직접 비교한다. 미사용 배치, 삭제/검토대기/제외업종만 연결된 배치, source 불일치, null/없는 배치, 여러 유효 배치를 포함한다. 전역 기준일/출처·고아 점포의 안전한500·history의 결측 정책은 기존 API 통합 검사와 대조한다. 시간 임계값을 CI assertion으로 삼지 않는다.

수정 후 일반pytest·격리integration·ruff/format·mypy를 실행한다. 실제 읽기 API와 동시 화면 조회를 다시 측정하고 SQL 오류 시 원문 없이 sqlstate/종류만 수집한다. 지도는 키 존재와 SDK/마커 실제 성공을 구분하며 인증·플랫폼 권한 부재면 해당 검증만 중단하고 요청한다. 실모델/원천 전체수집은 이번에 반복하지 않는다.

요청서·감사보고서·작업계획에 이번 측정과 미해결 상태를 반영한다. 다른 사용자의 untracked 분석 문서는 보존하고 커밋하지 않는다. PR은 Refs #78로 연결하고 전체 해결 전 이슈를 닫지 않는다. CI/CodeQL 정상 후 develop 일반 Squash로 병합한다.

## 4. Claude Code 검토 요청

이번 재점검은 명시된 소스만 Read, 이 설계 MD와 FE 감사 요청서만 Edit하도록 제한한다. 실제 사용자의 재검증 요청에 따라 기존 MD만 검토하던 방식에서 소스 읽기를 허용한다. .env·DB·Bash·네트워크·Git·그 밖의 파일과 모든 코드 수정은 금지한다. 두 MD에 검토 결과를 직접 남긴다. 구현·측정은 Codex가 최종 대조하고 수행한다.

## 5. Claude Code 검토 결과

대조 소스(Read만): `app/services/store_history.py`, `app/services/store_cohort.py`, `app/services/spatial_stores.py`, `app/models/store.py`, `app/models/store_import_batch.py`, interpret/risk/nearby/stores 스키마. FE 소스는 작업 폴더 제한으로 읽지 못했다(요청서 부록에 기록). EXPLAIN 수치는 §1의 Codex 관측을 인용한 것이며 Claude Code가 DB에서 직접 확인하지 않았다.

### 5.1 의미 동등성 — 동등, 차단 없음

- `stores.id`는 `BIGINT` PK(NOT NULL)이므로 `(SELECT stores.id ... LIMIT 1) IS NOT NULL`은 조건을 만족하는 행이 하나 이상 있을 때만 true다. `EXISTS(SELECT stores.id ...)`와 결과 집합이 같다. LIMIT 1에 ORDER BY는 필요 없다.
- `stores.batch_id`가 NULL인 행은 `=` 비교가 NULL이라 두 쿼리 모두 매칭하지 않는다.
- 조건은 `SUPPORTED_STORES AND stores.batch_id = b.batch_id AND stores.source = b.source` 그대로 옮긴다. 현재 history와 current_provenance의 두 쿼리는 문자 그대로 같으므로 공통 함수로 묶어도 동작이 바뀌지 않는다.
- 구현 주의: SQLAlchemy에서 `.scalar_subquery()`로 만들고 `.correlate(StoreImportBatch)`를 명시한다. 자동 상관에 맡겼다가 상관이 깨지면 비상관 서브쿼리(모든 배치에 같은 값)가 되어 결과가 조용히 달라진다. 컴파일된 SQL에서 서브쿼리 안의 `store_import_batches.batch_id` 참조를 확인하는 테스트가 필요하다.
- ORDER BY `source, batch_id`를 유지하면 `stores_batch_ids`·`store_batches`·`map_version` 메타 순서도 같다.

### 5.2 source 매칭 — 보존 필요

- 배치는 `batch_id` PK라 batch_id만으로도 한 행이지만, 다른 source 점포가 같은 batch_id를 참조하는 비정상 연결을 거르려면 source 조건을 빼면 안 된다.
- history의 `batch.source != store.source`이면 batch=None으로 두는 Python 검사(`store_history.py:133`)도 유지한다. current_provenance는 고아 검사(`linked`)가 batch_id+source를 함께 보므로 nearby의 `batch_map.get`이 source를 다시 보지 않아도 안전하다. 이번 변경으로 이 전제를 깨지 않는다.

### 5.3 미사용 배치 비용 — 병합 전 확인 필요(조건부 차단)

- `stores.batch_id`에는 인덱스가 없다(`app/models/store.py`). 따라서 상관 서브쿼리는 배치마다 stores를 순차 스캔하다가 첫 매칭에서 멈춘다. Codex가 관측한 hit3/read67은 매칭 행이 물리적으로 앞쪽에 있었기 때문이며, 구조적으로 보장되는 값이 아니다.
- **연결된 지원 점포가 없는 배치는 배치마다 stores 전체를 끝까지 읽는다.** 미사용 배치가 k개이면 비용은 약 k×전역 스캔으로, 현재의 단일 Merge Join(1회 전역 읽기)보다 나빠질 수 있다. ETL 재적재 시 기존 점포가 새 batch_id로 갱신되고 이전 배치 행이 남는 구조라면 k는 적재 횟수만큼 늘어난다.
- 그러므로 병합 전에 개발 DB(읽기 전용)에서 ① 전체 배치 수 ② 연결 점포가 없는 배치 수 ③ ETL이 이전 배치 행을 남기는지를 확인한다. k=0이거나 아주 작고 늘지 않는다면 진행한다. k가 늘어나는 구조라면 이 변경만으로는 회귀 위험이 있으므로, 인덱스 같은 별도 이슈 없이 병합하지 않는다. 설계 범위(인덱스·migration 미추가)는 유지하되, 그 범위로 해결할 수 없다는 판단 자체를 기록한다.
- 매칭 행이 VACUUM·UPDATE 이후 테이블 뒤쪽으로 이동하면 사용 중인 배치도 느려질 수 있다. 재측정 때 실제 배치 수와 함께 기록한다.

### 5.4 기대 효과의 범위

- current_provenance의 고아 점포 검사(`SELECT EXISTS(... SUPPORTED_STORES AND NOT linked)`)도 지원 점포 전체를 읽는 전역 anti-join이다. 이번 변경은 배치 목록 쿼리만 줄이므로 nearby/snapshot/risk 등 current_provenance 경로에는 전역 읽기 1회가 남는다. 같은 경로의 `min(open_date)`·no-coord count도 별도 비용이다.
- 반면 history는 고아 검사를 하지 않으므로 전역 읽기가 거의 사라질 것으로 예상된다.
- Codex 관측 325ms는 3.0초 500을 혼자 설명하지 못한다. 이 변경을 "동시 조회500 해결"로 기록하지 말고, sqlstate 수집 후 판단한다는 §1 입장을 유지한다.

### 5.5 기준일·고아 점포 검증 보존 — 설계 방향 동의

- 공통 함수는 **연결 배치 목록만** 반환하고, 검증은 호출부에 그대로 둔다. current_provenance의 고아 점포·배치 없음·`data_updated_at` null/`update_reason`/1960 이전/recorded_at(Asia/Seoul) 이후 → 500은 유지하고, history에는 이 검증을 끌어들이지 않는다(reference=None → `missing_source_date`, 메타 null 정책 유지).
- 기준일은 두 경로 모두 건물·업종·반경 필터 없이 전역 연결 배치의 `data_updated_at` 최대값이다. 공통 함수에 필터 인자를 추가하지 않는다.
- history의 두 쿼리가 같은 REPEATABLE READ 스냅샷을 공유하는 전제(`history_session`)도 바뀌지 않는다.

### 5.6 필요한 회귀 테스트

격리 PostGIS 통합 테스트에 기존 EXISTS 쿼리를 오라클로 두고, 새 함수와 배치 목록·순서가 같은지 비교한다.

1. 점포가 없는 배치, 삭제·검토대기·제외업종 점포만 연결된 배치 → 둘 다 제외
2. batch_id는 같고 source가 다른 점포만 연결된 배치 → 제외
3. batch_id NULL 점포 → 어떤 배치도 연결하지 않음
4. source별 유효 배치 여러 개 → 포함, `(source, batch_id)` 순서, reference는 최대값
5. current_provenance: 고아 지원 점포 → 500, 배치 기준일 무효 → 500 (기존 테스트로 충분하면 재사용)
6. history: 연결 배치 없음 → 200 + reference null + `missing_source_date`, source 불일치 batch → None
7. 단위 테스트: 컴파일 SQL에 상관 서브쿼리와 `LIMIT`이 있고, 바깥 FROM에 `stores`가 교차 조인으로 추가되지 않았는지 확인

시간 임계값 assertion은 넣지 않는다(§3 동의).

### 5.7 결론

- 의미 동등성·source 매칭·검증 보존 측면의 차단 지적은 없다.
- **조건부 차단 1건**: 미사용 배치 수 확인(5.3) 전에는 병합하지 않는다.
- 과도한 변경(인덱스·timeout·쿼리 재구성 확대)은 이번 범위에 제안하지 않는다. 고아 검사 전역 스캔은 측정 결과에 따라 후속 이슈로 분리한다.

## 6. Codex 최종 판단·실행 결과

Claude의 조건부 차단 지적을 채택해 §2의 쿼리 변경안은 적용하지 않는다. 실제 배치는 현재2개/연결2개/미사용0개지만, `etl/localdata/runner.py`는 적재마다 새 UUID를 만들고 `repository.py`는 점포의 batch_id를 갱신한 뒤 새 배치를 INSERT한다. 이전 배치를 삭제하지 않으므로 재적재 이후 미사용 배치가 늘어날 수 있다. 현재2개에서의 성능만 보고 상관 LIMIT 쿼리를 병합하면 이후 회귀가 생길 수 있다.

계약·BE 코드·인덱스·migration·timeout은 바꾸지 않는다. 배치 조회 지연은 #78의 별도 미해결 항목으로 기록한다. 원인 SQLSTATE와 재현 부하를 고정한 뒤 미사용 배치가 누적된 경우까지 포함해 인덱스/실행 계획을 검토해야 한다. 초기 브라우저500의 원인을 단일 SQL로 확정하거나 해결됐다고 주장하지 않는다.

추가 실제 HTTP 검사에서 이력·월범위·주변·활동·Risk 순차5건과5개 동시조회2세트(10건)는 모두200이었다. 관측 SQL 오류0으로 초기500의 SQLSTATE는 확보하지 못했다. 간헐 실패가 남으므로 전체 정상 판정을 하지 않는다. 이는 운영부하/SLA 검사가 아니다.

지도는 BE 로컬 환경에 있던 JavaScript 키를 테스트 자식 프로세스에만 전달했다. 실제 FE 환경 파일은 바꾸지 않았다. Chrome은 `KAKAO_SCRIPT_ERROR`/`net::ERR_BLOCKED_BY_ORB`였고, 같은 SDK의 직접 HTTPS 요청은401·도메인 제한 응답이었다. 키가 없다고 재보고하지 않고 해당 키의 `http://localhost:5173` SDK 도메인 등록을 요청한 뒤 지도 의존 검사를 중단했다. 상세 설정 근거는 [공식 지도 가이드](https://apis.map.kakao.com/web/guide/)다.

정상 이력5행·과거월200, 유효 합성 응답의 결측/식별 문제3종을 재현했다. 별도 실제 FE 요약 화면에서 query echo/집계/context 본문의 AI422와 unverified의 outside 오표시도 재확인했다. 원래 query-only 조건으로 보낸 별도 BE 호출은 모의 공급자로200이었다. 실제 LLM 호출은 이번 재점검 전체0회다.

출력 경로 재검사에서 진단서 main1·인쇄 이벤트·메모리 PDF1페이지는 확인했다. 같은 실행의 요약 PNG 생성은 확인되지 않았다. 이 실행에는 여러 API500이 섞였으므로 이를 별도 PNG 구현 결함으로 확정하지 않는다. 기존 감사의 정상 표본 PNG 통과 기록과 이번 실행을 구분한다.

코드 변경이 없어 기존 일반1,166/격리146·정적 검사 결과는 재사용하며 이번에 재실행했다고 표시하지 않는다. 이번 변경은 검토 MD·요청서·감사보고서·작업계획에 한정하고 문서 diff/링크·staged 비밀값 검사를 수행한다. FE5종 수정·지도·BE 간헐500은 미완료 상태로 유지한다.

## 7. 도메인 등록 후 지도 후속 검증

사용자가 FE는 기존대로 BE 재검증·요청서 보완만 진행하라고 확정했고, JavaScript SDK 도메인 등록 완료를 알렸다. BE develop `4cf9ac4`에서 `feat#78-map-verification`을 만든다. SDK 단독 로딩은 실제200·Map 생성자 존재·네트워크 오류0을 확인했다. 이를 실제 앱 지도/마커 통과로 대신하지 않는다.

기존 검증 계획의 지도 항목을 이어서 실제 읽기 API와 SDK로500m/300m 마커 수, 표 선택·지도 강조/정보창, 마커 선택·표 강조, 정보창 닫기를 확인한다. source가 다른 같은 관리번호 두 행은 BE Nearby 스키마를 통과하는 합성 응답으로 별도 대조한다. SQL 실패는 handle_error에서 종류·SQLSTATE와 고정 쿼리 분류만 수집해 BE 간헐500과 구분한다. FE/환경 파일·실제 DB·timeout 변경, 실LLM 호출, 원자료/키/지도 화면 원문 저장은 하지 않는다.

실제 SDK200·타일 응답45건200·pageerror0을 관측했다. 실제500m 마커152개와300m 마커44개가 API count와 같았다. 표→마커 강조/해당 상호 정보창, 마커 DOM click 이벤트→표 선택, 닫기→선택 해제를 확인했다. 300m는 실제 라디오 레이블 클릭 후 조회 버튼으로 변경했다. 첫 harness의 sr-only radio 직접 check 타임아웃은 레이블 클릭으로 보정했으며 FE 결함으로 분류하지 않는다. 지도 이동/확대·모바일·모든 물리 마우스 hit test를 통과했다고 확대하지 않는다.

BE `ApiResponse[NearbyStores]` 검증을 통과한 합성 두 행(source 다름/license_no 같음)에서 마커 DOM2개지만 선택 관리 마커1개, 두 표 행 동시 선택, 두 번째 행이 자기 정보창을 표시하지 못함을 확인했다. NearbyMap은 Map 키·클릭콜백·find, NearbyTable은 key/선택, NearbySection은 selectedId에 단독 관리번호를 사용한다. 기존 F4의 영향 범위를 지도까지 확대할 근거다. 단순 React key 교체만으로는 이 동작을 해결할 수 없다.

이번 브라우저 실행의 실제 BE GET13건은 모두200, SQL 오류0, 실LLM 송신0이었다(합성 nearby 응답은 서버 GET 집계에서 제외). 500이 다시 관측되지 않았으므로 기존 간헐500의 원인/해결은 여전히 미확정이다. SDK 도메인 차단은 이번 테스트 origin에서 해제됐지만 FE 환경 파일에 키를 옮기거나 영구 설정하지 않았으므로 담당자 실제 실행 환경과 구분한다.

## 8. 지도 후속 Claude Code 검토

대조 소스(Read만): `app/schemas/nearby.py`, FE `src/components/map/NearbyMap.tsx`, `src/components/analysis/NearbySection.tsx`, `src/components/analysis/nearby/NearbyTable.tsx`, `src/types/stores.ts`, 이 MD와 FE 감사 요청서. FE는 수정하지 않았다. 브라우저·DB·네트워크·Bash·Git은 사용하지 않았으므로 아래는 §7의 Codex 관측을 소스로 설명할 수 있는지 확인한 정적 대조이며, Claude Code가 직접 재현한 결과가 아니다. 이 절 외의 문서는 Edit하지 않았다.

### 8.1 §7 관측과 소스 대조 — 4종 모두 코드로 설명됨

| 관측 | 소스 근거 | 판단 |
|---|---|---|
| 마커 DOM2개 | `NearbyMap.tsx:117-126`이 markers마다 `makeMarkerElement`와 `CustomOverlay({map})`를 만들어 지도에 바로 올린다 | 일치 |
| 관리 마커1개 | `NearbyMap.tsx:127` `overlays.set(m.license_no, …)`가 같은 키를 덮어써서 **마지막(두 번째) 오버레이만** Map에 남는다 | 일치 |
| 두 행 동시 선택 | `NearbyTable.tsx:58` `selected = m.license_no === selectedId`, `:62,77` 클릭 인자도 license_no. `NearbySection.tsx:30,73,115`의 selectedId는 단일 string | 일치 |
| 두 번째 선택 시 첫 정보창 | `NearbyMap.tsx:141` `markers.find(m => m.license_no === selectedId)`가 첫 일치 행을 반환 → 정보창 내용·위치·panTo 모두 첫 점포 | 일치 |

추가로 마커 클릭(`NearbyMap.tsx:119`)은 어느 DOM이든 같은 license_no를 보내므로 두 마커가 구별되지 않는다. §7의 "단순 React key 교체로 해결 불가" 판단은 맞다(key는 `NearbyTable.tsx:61` 한 곳뿐이고 선택·지도 경로는 별도).

### 8.2 §7이 직접 서술하지 않은 소스상 결과 (미관측, 확인 요청)

- **강조 대상 불일치**: 관리 마커가 두 번째 것이므로 첫 번째 행을 선택해도 `NearbyMap.tsx:134-138`은 두 번째 마커 DOM을 강조하고, 정보창은 첫 점포를 표시한다. 첫 번째 마커 DOM은 Map에 없어 영원히 강조되지 않는다.
- **이전 마커 잔존**: 덮어써진 첫 오버레이는 Map에서 빠지므로 markers 갱신(`:115-116`)·언마운트 cleanup(`:86-88`) 어느 쪽에서도 `setMap(null)`되지 않는다. 같은 지도 인스턴스에서 반경·필터를 바꾸면 고아 마커가 남는 구조다. 요청서 4번의 "변경 후 이전 마커가 남지 않는지" 항목이 필요한 근거가 소스에 있다. 다만 `SectionErrorBoundary resetKey`나 상위 isPending 분기로 NearbyMap이 재마운트되는 경우에도 지도 객체는 정리되지만 고아 오버레이 자체는 해제되지 않는다. 실제 잔존 여부는 브라우저로 확인해야 한다.
- 위 두 항목은 정적 추론이며 결함 확정으로 기록하지 않는다.

### 8.3 수정 방향 검토 — 타당, 보완 2건

- 요청서 4번의 NearbyMap(Map 키·클릭 콜백·강조·find), NearbySection(selectedId·콜백), NearbyTable(key·선택 비교·행/버튼 클릭 인자) 지정은 위 소스 지점을 빠짐없이 덮는다.
- BE `NearbyMarker`는 `source: StoreSource`를 필수로 반환하고(`nearby.py:81`), 요청서 부록의 `UNIQUE(source, license_no)` 판단상 `${source}:${license_no}`는 응답 안에서 유일하다. BE 계약 변경은 필요 없다.
- 보완①: FE `stores.ts:48-62` `NearbyMarker` 타입에 **source가 없다**. 복합 식별자를 쓰려면 타입에 source 추가가 선행돼야 하므로 요청서 4번에 명시를 권장한다. 같은 타입은 BE와 달리 `name`·`operating_months`를 non-null로 두고 `operating_period_status/reason`이 없다(`nearby.py:83,90-92`).
- 보완②: 식별자 생성은 한 helper로 통일하고, NearbySection의 콜백 인자와 NearbyMap/NearbyTable 비교가 같은 함수를 쓰도록 권장한다. 오버레이 정리는 키 유일성에 의존하지 않게(생성한 오버레이를 모두 해제) 하면 비정상 응답에서도 잔존이 없다. 이는 FE 담당자 선택 사항이며 요구 계약이 아니다.

### 8.4 완료/한계 구분 — 타당

- §7·요청서 §6의 "SDK/타일/마커 건수/정상 표본 선택은 통과, 복합 식별은 미완료" 구분과 완료 기준 체크(정상 표본만 [x], 복합 식별 [ ])는 소스와 모순이 없다.
- "마커 DOM click 이벤트"를 물리 hit test와 구분하고 모바일·확대/이동을 범위 밖으로 둔 표현도 적절하다. 합성 응답이 실제 자료의 중복 발견이 아니라는 단서도 유지돼 있다.

### 8.5 추가 관찰 (지도 nullable, 우선순위 낮음)

BE `NearbyMarker.name`은 nullable이다. 현재 `NearbyMap.tsx:208` title은 `${m.name}`이라 null이면 문자열 "null"이 되고, 정보창 제목(`:224`)과 표 셀(`NearbyTable.tsx:82`)은 빈칸, 버튼 aria-label(`:74`)도 "null …"이 된다. `operating_months=null`은 정보창 `—`, 표 빈칸이다. 요청서 5번(이력 중심)의 결측 표시 원칙을 nearby 표·정보창에도 적용할지 요청서에 범위로 적어 둘 것을 제안한다. 화면 장애가 아니라 표시 보완으로 분류한다.

### 8.6 제안 회귀 기준 (FE 수정 후 FE 담당자 확인용, FE 코드 직접 수정 없음)

같은 BE 스키마 통과 합성 2행(source 다름·license_no 같음·좌표 다름)으로:

1. 두 번째 행 클릭 → 그 행만 `aria-pressed=true`, 정보창 제목·위치가 두 번째 점포, 두 번째 마커 DOM만 `data-selected=true`
2. 첫 번째 행 클릭 → 첫 번째 마커 DOM이 강조됨(현재 소스상 실패 예상 지점)
3. 각 마커 DOM 클릭 → 대응 행만 선택
4. 반경/필터 변경 후 지도 내 점포 마커 DOM 수 = 새 응답 count, 언마운트 후0(고아 없음)
5. React 중복 key 경고0, 정보창 닫기 → 선택 해제
6. 정상 실데이터 500m/300m 건수·선택은 §7 결과와 같음(회귀 없음)

BE 쪽은 공개 API·응답을 유지하며, 필요하면 같은 license_no·다른 source 두 마커가 `ApiResponse[NearbyStores]`를 통과함을 단위 테스트로 고정하는 정도만 제안한다(이번 범위에서 추가하지 않음).

### 8.7 결론

§7의 지도 관측 4종은 모두 FE 소스로 설명된다. 기존 F4를 지도 선택·정보창까지 확장하는 방향과 테스트 완료/한계 구분은 타당하다. 차단 지적은 없고 요청서 보완 권장은 ① NearbyMarker 타입 source 추가 명시 ② 강조 불일치·고아 마커는 소스상 예상이므로 회귀 기준 1~4로 확인 ③ nearby nullable 표시 범위 명시 세 가지다. Codex가 요청서 반영 여부를 최종 판단한다.

## 9. 지도 후속 Codex 최종 판단

- Claude의 NearbyMarker.source 타입·선택 상태/콜백/Map/find 전체 복합 식별·서로 다른 좌표의 회귀·주변 nullable 표시 보완을 채택했다. 요청서에 반영했으며, 코드만으로 추론한 고아 오버레이 잔존과 nullable 지도 표시는 실제 브라우저 확정 결함으로 쓰지 않았다. FE 코드는 수정하지 않는다.
- Claude CLI는 실제 MD를 수정했고 오류없음/권한거절0을 확인했다. Codex가 실제 diff와 소스를 대조했다. 이번 검토는 소스 정합성 확인이며 Claude가 SDK/DB를 직접 실행한 것은 아니다.
- 지도 실행 후 별도 출력 재검사에서 이력·주변·활동·Risk500이 재발했다. PostgreSQL 로그의 같은 시각 ERROR와 동일 backend PID STATEMENT를 연결해 출처 연결 배치 조회4건의 `canceling statement due to statement timeout`을 확인했다. 원문 SQL/파라미터를 출력·보고서·커밋하지 않고 고정 쿼리 분류와 건수만 남겼다. 이 실행의 직접 원인은 DB statement_timeout이며, SQLSTATE 자체는 직접 수집하지 않았다. 과거 모든500의 원인을 확정하지 않는다.
- §7의 지도 실행(모든BE GET200/SQL오류0)과 별도 출력 실행(500/timeout4건)은 구분한다. 후자의 PNG는 미확인, 진단서main/인쇄 이벤트/메모리 PDF1페이지는 통과다. 지도 도메인 차단은 이번 origin에서 해소됐지만 전체 시스템 정상은 아니다.
- 출처 쿼리의 LIMIT 임시안은 여전히 미적용이다. 성능 수정은 미사용 배치 누적과 동시 조회를 포함해 설계·검증해야 하며 #78의 BE 후속으로 남긴다. FE 수정범위/로컬환경 변경은 확대하지 않고 요청서·감사·작업계획을 갱신한다.
