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
