# 출처 연결 배치 조회 시간 초과 개선 (#82)

- 기준: develop `80239a2`, 관련 감사 #78/PR81
- 브랜치: `feat#82-store-provenance-index`
- 목표: 지원 점포의 전역 출처 조회에서 반복되는 SQL3초 초과를 줄이고 실제 동시 API를 재검증한다.

## 1. 확인한 문제

개발 DB stores689,440행에서 이력·주변·활동·Risk 동시 조회가500으로 실패했다. PostgreSQL 동일시각/동일PID ERROR·STATEMENT로 출처 연결 배치 조회 statement_timeout4건을 확인했다. 기존 EXISTS는 지원 점포355,835행을 heap에서 읽고 배치별 집계/조인을 수행했다. 현재배치2개라도 재적재 시 과거 배치는 보존되므로, 인덱스 없이 배치별 LIMIT1 상관 쿼리로 바꾸는 임시안은 #78에서 거절했다.

## 2. 우선 검증할 최소 변경안

기존 쿼리/지원 조건/의미를 유지하고 아래 PostgreSQL covering partial B-tree를 추가하는 안부터 격리 DB에서 비교한다.

```text
ix_stores_provenance
keys: (batch_id, source)
INCLUDE: (category, sub_category)
WHERE deleted_at IS NULL AND category_review_flag IS NOT TRUE
```

현재 EXISTS와 고아 검사에 필요한 모든 점포 조건/연결 필드를 포함한다. 지원 업종 자체를 인덱스 predicate에 복제하지 않으므로 업종 정책 변경 때 인덱스가 새 지원행을 누락하는 문제를 피한다. EXISTS의 id projection은 존재 검사에서 제거되는지 실행 계획으로 확인한다. 쿼리가 index-only scan을 선택하면 heap 전체 반복 읽기를 줄일 수 있다. 최근 쓰기 직후 all-visible이 아닐 때의 heap fetch 비용은 별도로 측정한다.

효과가 부족하면 결과를 기록하고 설계를 재검토한다. 시간 제한 확대·원천 검증 생략·SQL 캐시로 오류 은폐·인덱스 없는 상관 LIMIT 변경은 하지 않는다. 불필요한 서비스 리팩터링은 포함하지 않는다.

## 3. 보존 조건과 migration

- batch UUID+source, 지원 점포 조건, 전역 최대 기준일/정렬/출처, 고아 지원점포500, history 결측 보존을 그대로 유지한다.
- READ ONLY REPEATABLE READ·SQL3초·API/응답·캐시 무효화·FE·원천/로컬.env/Docker 설정은 유지한다.
- ORM 인덱스와 migration0010을 맞춘다. upgrade는 인덱스만 만들고 downgrade는 인덱스만 제거하며 행/기존 인덱스/출처를 바꾸지 않는다.
- 기존 migration runner의 트랜잭션 실행과 호환되는 일반 CREATE INDEX를 사용한다. 생성 중 쓰기가 대기할 수 있으므로 실제 개발 적용 전 writer 부재를 확인하고 읽기/API 검증과 구분한다. 운영 무중단 DDL을 보장하지 않는다.
- 일반/파괴적 integration suite는 별도 loopback PostGIS에만 실행한다. 격리 통과 후 실제 개발 DB에는 이 인덱스 migration만 적용하고 전후14테이블 행/geometry hash와 출처/응답을 비교한다. 데이터 재적재/수정/삭제는 하지 않는다.

## 4. 검증 계획

1. 일회용 PostGIS에 대량 합성 stores를 만들어 기존/인덱스 후 EXPLAIN ANALYZE·buffer/heap fetch·인덱스 크기와 동시 조회를 비교한다. 현재배치/미사용 과거배치 수십개, recent writes 직후와 VACUUM 후를 구분한다. 실제 점포 원자료를 복사하지 않는다.
2. 격리 회귀: 미사용/삭제/검토대기/제외업종만 연결된 배치 제외, source 불일치/고아 검증, 최신 전역 기준일, migration 왕복과 행 보존. 기존 회귀를 재사용하고 시간 임계값을 CI assertion으로 삼지 않는다.
3. ruff/format·mypy app etl migrations·일반pytest·격리integration 및 실제 비밀값 검사.
4. 실제 dev migration 전후 모델/버전/기존행 보존을 확인하고 같은 query의 정상 응답 digest를 비교한다. 실제 HTTP 동시 흐름(이력/범위/주변/활동/Risk)과 기존 실패했던 출력 화면을 검사한다. 오류는 SQLSTATE/고정 분류만 수집하며 원문·키·주소를 기록하지 않는다. 실제 LLM은 호출하지 않는다.
5. 성능 수치는 측정 조건과 함께 기록하고 전체 운영SLA/모든 API 부하 통과로 확대하지 않는다. FE5종·브랜드승인·조건부지표 미완료는 유지한다.

## 5. Claude Code 검토 요청

명시한 BE 소스와 이 MD만 Read, 이 MD §6만 Edit한다. .env·DB·Bash·네트워크·Git·FE 접근/수정은 금지한다. 인덱스의 컬럼/partial predicate/의미 보존, EXISTS projection, visibility/과거배치 비용, migration 잠금/왕복과 대량 회귀를 검토한다.

## 6. Claude Code 검토 결과

- 검토 범위: 이 MD, `app/services/store_cohort.py`, `app/services/store_history.py`, `app/models/store.py`, `app/db/dependencies.py`, `migrations/versions/0004_store_geography_index.py`, `tests/integration/test_nearby.py`만 정적으로 읽었다. DB·EXPLAIN·Bash는 실행하지 않았고 **성능은 측정하지 않았다**. 아래 성능 관련 판단은 모두 PostgreSQL planner/storage 동작에 근거한 조건부 추정이며, 격리 비교로 확인해야 한다. PostgreSQL 서버 버전은 확인하지 못했다(버전별 차이는 해당 항목에 표시).
- 종합: **조건부 진행 가능**. 컬럼 커버리지와 predicate 의미 보존은 맞다. 다만 (a) INCLUDE 때문에 B-tree deduplication이 꺼지는 점, (b) 재적재 직후 visibility map·HOT 손실로 인한 쓰기/읽기 비용, (c) downgrade의 ACCESS EXCLUSIVE 잠금, (d) 실제 SQLAlchemy가 만든 SQL에 대한 predicate 매칭 회귀가 빠져 있어 아래 필수 항목을 보완한 뒤 비교해야 한다.

### 6.1 컬럼 커버리지 (EXISTS·고아 검사)

- `SUPPORTED_STORES`(`app/services/store_history.py:16-27`)가 참조하는 stores 컬럼은 `deleted_at, source, category_review_flag, category, sub_category`이고, 두 상관 조건(`store_cohort.py:49-53`, `store_history.py:108-114`)과 고아 검사(`store_cohort.py:59-64`)는 여기에 `batch_id, source`를 더한다.
- 제안 인덱스는 key `(batch_id, source)` + INCLUDE `(category, sub_category)` + predicate `deleted_at`·`category_review_flag`로 이 7개 참조 중 6개 컬럼을 모두 담는다. predicate에만 나오는 컬럼은 질의 WHERE가 같은 절을 포함하면 index-only scan에 필요 없다(PostgreSQL 9.6+ 동작). → **커버리지 판단: 충족**.
- `batch_id`는 nullable이고 B-tree는 NULL도 저장하므로, `batch_id IS NULL`인 지원 점포도 고아 검사에서 인덱스로 발견된다(의미 손실 없음).
- 주의: 인덱스 대상 행은 "지원 점포 355,835행"이 아니라 **predicate를 통과한 모든 업종·모든 source 행**이다. 미지원 업종과 기타 source가 포함되므로 인덱스 엔트리 수·크기는 §1 수치보다 클 수 있다. 격리/실DB 비교 때 `count(*) WHERE deleted_at IS NULL AND category_review_flag IS NOT TRUE`와 인덱스 크기를 함께 기록할 것.

### 6.2 partial predicate 의미 보존과 매칭

- 지원 업종·source를 predicate에서 빼고 `deleted_at IS NULL AND category_review_flag IS NOT TRUE`만 둔 판단은 타당하다. predicate는 `SUPPORTED_STORES`의 진부분 조건이므로 인덱스가 지원 행을 누락할 수 없고, 업종/source 정책 변경 시에도 결과 집합은 그대로다(성능만 바뀜).
- `IS NOT TRUE`는 NULL과 FALSE를 모두 포함한다. 기존 `is_not(True)`와 같은 의미다.
- **매칭 조건(필수 확인)**: planner의 predicate 함의 증명은 사실상 구문 동일성에 의존한다. migration은 반드시 `category_review_flag IS NOT TRUE`(BooleanTest)로 작성해야 하며 `IS DISTINCT FROM true`, `<> true`, `COALESCE(...)` 같은 동치 표현을 쓰면 인덱스가 선택되지 않을 수 있다. SQLAlchemy는 `is_not(True)`를 bind가 아닌 리터럴 `IS NOT true`로 렌더링할 것으로 예상하지만 확인하지 않았다. 만약 bind parameter로 나가면 generic plan에서 함의가 실패할 수 있으므로, 손으로 쓴 SQL이 아니라 **실제 함수가 실행한 SQL**로 EXPLAIN 해야 한다(6.8 참고).
- 기존 인덱스(`app/models/store.py:30-39`)에는 같은 목적의 인덱스가 없어 중복은 아니다.

### 6.3 EXISTS projection(`select(Store.id)`)

- PostgreSQL은 EXISTS 서브링크의 target list를 버린다(semi/anti-join 변환이나 SubPlan 모두). 따라서 `Store.id`가 인덱스에 없어도 index-only scan을 막지 않을 것으로 예상한다. 고아 검사의 `SELECT EXISTS(SELECT stores.id ...)`도 같다.
- 바깥쪽 `linked` 서브쿼리의 `select(StoreImportBatch.batch_id)`는 store_import_batches 쪽이라 이 인덱스와 무관하다.
- 판단은 정적 추론이므로 EXPLAIN (VERBOSE)에서 stores 노드의 Output에 `id`가 없고 노드가 `Index Only Scan using ix_stores_provenance`인지 확인할 것.

### 6.4 visibility·쓰기 직후·쓰기 증폭

- 의미/정합성: REPEATABLE READ READ ONLY 스냅샷(`app/db/dependencies.py:41-51`)에서 index-only scan은 all-visible이 아닌 페이지에 대해 heap을 확인하므로, 쓰기 직후에도 결과가 달라지지 않는다. **정합성 위험은 없다고 판단**한다.
- 성능(조건부): 재적재가 다수 행을 UPDATE/INSERT하면 해당 heap 페이지가 VACUUM 전까지 all-visible이 아니게 된다. 이때 Heap Fetches가 엔트리 수에 가까워지고, 고아 검사처럼 인덱스 전체를 훑는 질의는 랜덤 heap 접근 때문에 기존 seq scan보다 **느려질 수도 있다**. 즉 "적재 직후~autovacuum 완료 전" 구간에서 timeout이 재발할 가능성은 이 인덱스만으로 배제되지 않는다. planner의 index-only 비용 추정도 `pg_class.relallvisible`(VACUUM이 갱신, ANALYZE로는 부족)에 의존한다.
- 쓰기 증폭(신규 위험, MD 미기재): 이 인덱스가 생기면 `batch_id, source, category, sub_category, deleted_at, category_review_flag` 중 하나라도 바뀌는 UPDATE는 HOT 업데이트가 될 수 없고 **stores의 모든 인덱스**에 새 엔트리를 만든다. 재적재가 기존 행의 `batch_id`를 새 배치로 바꾸는 방식이라면(읽은 범위에서 ETL은 확인 못함) 매 적재마다 전 행이 non-HOT이 되어 적재 시간·WAL·bloat가 늘 수 있다.
- 권고: §4-1의 "recent writes 직후 vs VACUUM 후" 비교에 (1) 실제 ETL과 같은 방식의 대량 UPDATE 직후, (2) 그 직후 4종 동시 API, (3) VACUUM 후를 구분하고 `Heap Fetches`, `relallvisible/relpages`, 적재 소요시간 전후를 기록한다. 직후 구간이 3초를 넘으면 "적재 후 VACUUM (ANALYZE) 절차 추가"를 별도 후속 결정으로 남기고, 이번 변경에서 timeout 확대로 덮지 않는다.

### 6.5 과거 배치 누적 성능

- 첫 질의(배치 목록)는 store_import_batches를 바깥으로 두고 배치마다 `(batch_id, source)` 범위를 탐색하는 nested-loop semi join이 기대된다(planner가 hash semi join + 인덱스 전체 스캔을 고를 수도 있음).
  - 행이 모두 새 배치로 옮겨졌거나 모두 soft-delete/검토대기인 과거 배치: predicate로 엔트리가 0개이므로 탐색 비용은 배치당 B-tree 하강 1회 수준.
  - 지원 행이 남아 있는 배치: 첫 일치에서 멈춘다.
  - **미지원 업종 행만 남은(삭제 안 된) 과거 배치**: category/sub_category가 key가 아니라 INCLUDE라 index filter로만 거르므로 그 배치의 엔트리를 끝까지 읽는다. 최악 비용은 "삭제되지 않은 미지원 행의 총합"에 비례하며, 배치 수가 늘수록 누적될 수 있다.
- 고아 검사는 배치 수와 무관하게 predicate 통과 행 전체를 anti-join하는 O(인덱스 크기) 질의가 요청마다 실행된다. 인덱스는 heap보다 좁아 유리할 가능성이 크지만, 동시 요청 수만큼 반복되는 구조 자체는 남는다.
- 권고: 합성 데이터에 "미지원 업종만 남은 과거 배치 수십 개"와 "행이 전부 이관된 과거 배치 수십 개"를 별도로 두고 비교한다. 실제 ETL이 과거 배치 행을 어떻게 남기는지(batch_id 재지정/soft-delete/잔존)는 이 리뷰 범위 밖이라 확인하지 못했으므로, 합성 시나리오는 실제 적재 방식과 맞춰 기록할 것.

### 6.6 INCLUDE와 deduplication — 비교 대안 추가 권고

- PostgreSQL 13+의 B-tree deduplication은 **INCLUDE 컬럼이 있는 인덱스에서는 동작하지 않는다**. `(batch_id, source)`는 배치당 수십만 건이 같은 값이므로, 현재 안은 중복 압축을 전혀 못 받아 크기가 클 것으로 예상한다(수치는 측정하지 않음).
- 대안 B: key `(batch_id, source, category, sub_category)`, INCLUDE 없음, 같은 predicate. 모든 컬럼이 key이므로(uuid·결정적 collation varchar 가정) deduplication 대상이 되고, 배치×업종 조합 수가 적어 크기·스캔 페이지가 크게 줄 수 있다. 커버리지·predicate 의미·정책 변경 내성은 동일하고, 6.5의 "미지원 행 끝까지 읽기" 비용도 페이지 수 기준으로 줄어든다. 쓰기 시 HOT 손실 조건은 원안과 같다.
- 권고: §4-1 비교에 원안(INCLUDE)과 대안 B를 같은 조건으로 넣어 크기·buffers·Heap Fetches·동시 조회 결과로 선택한다. 서버가 PG12 이하이면 dedup 이점은 없으므로 원안 유지도 무방하다.

### 6.7 migration 트랜잭션·잠금·왕복

- upgrade: 트랜잭션 내 일반 `CREATE INDEX`는 stores에 SHARE 잠금을 잡는다. INSERT/UPDATE/DELETE는 대기하지만 SELECT(ACCESS SHARE)는 막지 않으므로, 생성 중 읽기 API는 계속 동작한다. 단 장기 writer 트랜잭션이 있으면 CREATE INDEX가 그 뒤에서 대기하고, 대기 동안 새 writer들이 줄을 선다. MD의 "적용 전 writer 부재 확인"은 적절하다. `CONCURRENTLY`를 쓰지 않는 판단은 기존 runner(0004와 동일 패턴)와 일관되다.
- **downgrade(MD 미기재 위험)**: `DROP INDEX`(비 CONCURRENTLY)는 stores에 **ACCESS EXCLUSIVE**를 잡는다. 진행 중인 읽기가 끝날 때까지 기다리고, 그동안 뒤에 오는 모든 SELECT까지 막는다. 실제 dev DB에서 롤백할 때 읽기 API가 멈출 수 있다. 권고: downgrade/upgrade 실행 절차에 짧은 `lock_timeout`(세션 또는 migration 내부 `SET LOCAL`) 사용 여부를 Codex가 결정하고, 실패 시 재시도하도록 기록한다. migration 코드에 넣을 경우 0004와의 패턴 차이를 MD에 남길 것.
- 왕복: upgrade/downgrade 모두 인덱스만 다루면 행·출처는 바뀌지 않는다. 0004 테스트(`tests/integration/test_nearby.py:387-429`)처럼 downgrade→upgrade 중 행 digest가 같은지 확인하는 패턴을 재사용하면 충분하다.
- ORM 일치: `Index("ix_stores_provenance", "batch_id", "source", postgresql_include=[...], postgresql_where=...)`의 predicate가 migration 문자열과 같은 표현을 렌더링해야 한다. ORM과 migration DDL 일치를 검사하는 기존 테스트는 읽은 범위에서 확인하지 못했으므로 `pg_indexes.indexdef` 단언을 추가할 것.

### 6.8 회귀 검증 보완

`test_global_provenance_failure_is_not_partial_success`(`test_nearby.py:330-358`)는 empty/unlinked/wrong-source/날짜 이상을 이미 다룬다. 읽은 범위에서 다음은 확인하지 못했으므로 추가를 권고한다.

1. **필수 — 실제 SQL 기준 plan 적격성**: 손으로 쓴 SQL이 아니라 `current_provenance`/`get_history`가 실행한 SQL·파라미터를 `before_cursor_execute` 이벤트 등으로 캡처해 같은 트랜잭션에서 `EXPLAIN (FORMAT JSON)`하고, `enable_seqscan=off` 하에 두 질의(배치 목록, 고아 검사) 모두 `ix_stores_provenance`를 쓰는지 단언한다. 소규모 합성 테이블에서는 VACUUM 전이라 `Index Only Scan`이 아닐 수 있으므로 인덱스 이름만 단언하고, 이 테스트가 성능을 증명하지 않는다는 주석을 0004 테스트처럼 남긴다. 6.2의 bind/리터럴 렌더링 위험을 이 테스트가 잡는다.
2. **필수 — indexdef 단언**: `INCLUDE (category, sub_category)`(대안 B면 key 순서)와 `WHERE ((deleted_at IS NULL) AND (category_review_flag IS NOT TRUE))`.
3. 배치 제외: 삭제/검토대기/미지원 업종 행만 연결된 배치가 `meta.store_batches`·`stores_batch_ids`에 나오지 않고, 그 배치의 `data_updated_at`이 전역 기준일에 영향을 주지 않는지(더 늦은 날짜를 가진 미사용 배치로 검증).
4. `category_review_flag IS NULL`인 지원 점포가 포함되는지(`IS NOT TRUE`의 NULL 분기).
5. `batch_id IS NULL`인 지원 점포 → 500(고아), 삭제/검토대기/미지원 업종의 고아 행 → 500이 **아님**.
6. 회귀 범위: 새 인덱스가 `temporal_cohort`(`store_cohort.py:20-40`) 등 `SUPPORTED_STORES`를 쓰는 다른 질의(주변/활동/Risk)의 plan을 바꿀 수 있다. 실DB 전후 비교 때 이 질의들의 EXPLAIN도 같이 기록하고 악화 여부를 본다.
7. 시간 임계값을 CI assertion으로 쓰지 않는다는 §4-2 방침에 동의한다.

### 6.9 Codex에 요청하는 결정 사항

- 필수: 6.2 predicate 표현 고정, 6.8-1·2 테스트 추가, 6.4 쓰기 직후/VACUUM 후/ETL 적재 시간 비교, 6.7 downgrade 잠금 절차 기록.
- 권장: 6.6 대안 B(INCLUDE 없는 4컬럼 key) 병행 비교, 6.5 과거 배치 시나리오 분리, 6.1 인덱스 엔트리 수/크기 기록.
- 유지 확인: timeout 확대·SQL 캐시·검증 생략·인덱스 없는 상관 LIMIT 금지, 서비스 쿼리 미변경 방침은 이 리뷰에서도 그대로 지지한다.

## 7. Codex 최종 결정·결과

Claude의 대안 B(네 컬럼 모두 key, INCLUDE 없음)를 구현 대상으로 선택했다. 서비스 쿼리는 변경하지 않는다. 합성689,440행/지원344,720행·초기배치102개(미사용100개)에서 원안과 B를 비교했다. 미사용 중5개는 미지원 행만,95개는 점포0행인 초기 사례도 포함했다. PostgreSQL17에서 vacuum 후 인덱스 크기는 INCLUDE107,372,544bytes/B10,502,144bytes, 고아 검사133.512ms/B91.407ms였고 B의 배치조회0.260ms·동시5건156~234ms였다. 같은 데이터에 순차 적용한 단발 비교이므로 정확한 상대 성능비/SLA로 해석하지 않는다.

새 batch_id로 전체689,440행을 UPDATE하는 합성 재적재는 인덱스없음26.390초/INCLUDE37.266초/B38.579초였다. 실제 CSV 파싱/전체 upsert 비용은 측정하지 않았으며, 순차 실행의 heap bloat·캐시 차이가 포함된다. 인덱스 추가의 쓰기 비용과 HOT 제약을 공개한다.

인덱스 없는 재적재 직후의 배치조회도 측정했으며5,721.282ms(고아 검사236.011ms)였다. 이 값이 처음 §7 요약에 빠져 §8 검토에서 누락으로 지적됐다. ignored 집계 결과의 original_after_replay 값을 다시 대조해 보완한다. B의5,758.959ms와 단발 비교만으로 동등/회귀없음/우월을 판정하지 않는다.

**재적재 직후 제한:** B에서 배치조회5,758.959ms·heap fetch689,442건으로3초를 초과했다. 원안도1,786.792ms·heap fetch689,442건이었다. VACUUM 후 B는0.260ms·heap fetch0으로 회복됐다. 따라서 이 인덱스만으로 대량 재적재 직후까지 해결됐다고 주장하지 않는다. 실제개발의 현재 읽기 흐름 개선과 대량 writer 직후 운영/maintenance 경계를 구분한다. ETL 트랜잭션/원자성이나 자동VACUUM 코드를 임의 변경하지 않는다.

DDL upgrade/downgrade에 SET LOCAL lock_timeout=5s를 넣어 잠금 장기 대기를 제한했다. 인덱스 생성 시간 제한은 이 값과 다르다. 배포/롤백은 쓰기/읽기 중단 가능성을 고려하고 잠금 실패 시 트랜잭션이 롤백된 뒤 다시 실행한다. 실제dev 적용은 writer 부재·별도statement_timeout60초로 제한한다.

실제 SQLAlchemy 쿼리 캡처/EXPLAIN 적격성, NULL review flag·고아, 제외 배치의 전역 기준일, migration 왕복/전체행 보존 회귀를 추가한다. 실제dev 적용·전체검사 후 결과를 보완한다.

## 8. 대량 재적재 직후 한계에 대한 Claude 후속 검토

§7 관측을 바탕으로 최소 개선안 B와 maintenance 경계의 타당성을 검토한다. 이 MD만 Read/Edit한다.

- 검토 범위: 이 MD만 읽었다. 코드·DB·EXPLAIN·Bash는 실행하지 않았다. 아래 수치는 모두 §7에 Codex가 기록한 격리 합성 측정값이다. **실제 개발 DB 검증은 하지 않았다.** 판단은 §7 수치와 PostgreSQL 동작에 근거한 조건부 의견이다.

### 8.1 종합 판단

- **조건부 진행.** "평상시(VACUUM 후) 정상 읽기 경로의 최소 개선"으로 범위를 한정하면 진행할 수 있다. 대량 재적재 직후 구간은 **미해결 상태로 명시**한다.
- 근거: vacuum 후 B는 배치조회 0.260ms, 고아 검사 91.407ms, 동시 5건 156~234ms로 SQL 3초 한도에 여유가 크다. 크기도 INCLUDE의 약 1/10(10.5MB 대 107.4MB)이다. 서비스 쿼리와 의미는 바뀌지 않는다.
- 단, 아래 8.2의 **비교 누락 1건**이 해소되기 전에는 "B가 기존보다 나쁘지 않다"고 결론 낼 수 없다. 그 결과에 따라 진행이 차단될 수 있다(8.5).

### 8.2 재적재 직후 잔존 위험 (숨기지 않음)

- 합성 전체 UPDATE 직후 B의 배치조회는 **5,758.959ms, heap fetch 689,442건**이었다. 단건으로도 SQL 3초를 넘으므로, 이 상태(dirty)에서 해당 API는 statement_timeout을 거쳐 **500을 반환할 것으로 예상**한다. 동시 요청이면 요청마다 같은 heap 랜덤 접근이 반복되어 더 나빠질 수 있다. 이것이 합성 dirty 구간의 500 위험이며, 이번 변경의 알려진 한계로 공개한다.
- heap fetch(689,442)가 전체 행 수(689,440)와 거의 같다. 인덱스 엔트리마다 heap을 확인했다는 뜻이며, index-only의 이점이 VACUUM 전까지 사실상 없어짐을 보여 준다.
- 같은 dirty 조건에서 INCLUDE 원안은 1,786.792ms였다. heap fetch 수가 같은데 B가 약 3.2배 느리다. 순차 단발 측정이라 캐시·bloat·plan 차이일 수 있으며 원인은 확인되지 않았다.
- **누락된 비교**: §7에는 **인덱스 없음 상태의 재적재 직후 배치조회 시간이 없다.** 인덱스 없는 seq scan은 visibility map의 영향을 받지 않는다. 따라서 B가 평상시를 개선하면서 직후 구간은 기존보다 악화시킬 가능성을 배제할 수 없다.

### 8.3 쓰기 비용

- 합성 전체 UPDATE 소요: 인덱스 없음 26.390초 → B 38.579초(약 +46%). 원인은 HOT 불가에 따른 모든 인덱스 갱신이다. 실제 CSV 파싱/upsert는 측정하지 않았으므로 실제 ETL의 증가율로 일반화하지 않는다.
- 개발 ETL 시간 증가는 수용 가능하다고 본다. WAL·bloat 증가는 VACUUM 의존도를 높이므로 8.4의 운영 안내와 연결된다.

### 8.4 필수 검증·운영 안내

1. **필수 비교**: 같은 합성 데이터에서 재적재 직후 배치조회·고아 검사를 **인덱스 없음 / INCLUDE / B** 세 경우로 측정한다. 실행 순서를 바꿔 각 3회 이상 반복하고, Heap Fetches·buffers·plan 노드와 `relallvisible/relpages`를 기록한다. 단발 수치는 SLA나 상대 성능비로 쓰지 않는다.
2. **필수 운영 안내(코드 아님)**: 대량 ETL 커밋 후 읽기를 재개하기 전에 `VACUUM (ANALYZE) stores`를 수동으로 실행하라고 문서화한다. 자동 VACUUM 코드는 추가하지 않는다.
   - VACUUM은 트랜잭션 블록 안에서 실행할 수 없다. 따라서 ETL·migration 트랜잭션과 분리된 **별도 autocommit 세션**에서 실행해야 한다.
   - **ETL과 원자적이지 않다.** ETL 커밋부터 VACUUM 완료까지는 8.2의 500 위험 구간이 남는다. autovacuum이 이 구간을 줄여 줄 수는 있지만 완료 시점은 보장되지 않는다.
   - 실행 권한은 테이블 소유자 또는 superuser가 필요하다. PG17에서는 MAINTAIN 권한(`pg_maintain` 역할)으로도 가능하다. 앱/ETL 계정의 권한은 확인하지 않았다.
   - VACUUM의 SHARE UPDATE EXCLUSIVE 잠금은 읽기/쓰기를 막지 않는다. 다만 CREATE/DROP INDEX와 충돌하므로 migration과 동시에 실행하지 않는다.
3. **DBA 잠금 안내**:
   - `SET LOCAL lock_timeout=5s`는 runner가 migration을 트랜잭션 안에서 실행할 때만 효과가 있다. autocommit이면 경고만 나고 무시되므로 실제 적용 경로를 확인해야 한다.
   - lock_timeout은 **잠금 대기만** 제한한다. 인덱스 생성 시간은 별도 `statement_timeout` 60초로 제한된다.
   - downgrade의 `DROP INDEX`는 ACCESS EXCLUSIVE를 요청한다. 대기 중인 최대 5초 동안 뒤이은 SELECT도 같이 대기한다. 5초는 API의 SQL 3초 한도보다 길어서, **잠금 획득에 실패해 롤백되더라도 그 사이 읽기 요청이 500이 될 수 있다.** 따라서 롤백은 읽기 트래픽이 없는 시점에 실행한다. 잠금 실패 시에는 트랜잭션 전체가 롤백되므로 그대로 재실행하면 된다.
   - upgrade의 `CREATE INDEX`(SHARE)는 읽기는 막지 않고 writer만 막는다.
4. **3초 한도의 의미**: 현재 한도는 읽기 트랜잭션의 **SQL 문장별 statement_timeout 3초**다(§3). HTTP 전체 응답 시간 SLA가 아니다. 평상시 수치는 이 문장별 한도에 대한 여유만 보여 준다. 운영 SLA나 모든 API의 부하 통과를 뜻하지 않는다.
5. §7에 예정된 회귀(실제 SQL 캡처 EXPLAIN, indexdef, NULL flag, 고아, 제외 배치 기준일, 왕복 행 보존)는 그대로 필수다.

### 8.5 차단 조건과 최소 대안

- **차단**: 8.4-1 반복 측정에서 B의 직후 시간이 **인덱스 없음보다 일관되게 나쁘면** B를 그대로 병합하지 않는다. 그 경우 평상시 개선이 직후 구간 악화와 맞바뀌는 것이기 때문이다.
- 최소 대안(우선순위순):
  - (a) 직후 시간도 3초 안이고 인덱스 없음보다 나쁘지 않으면 **INCLUDE 원안**을 택한다. 크기 약 10배를 감수한다.
  - (b) 어느 인덱스든 직후 구간이 악화되면 B를 유지한다. 대신 "대량 ETL 후 수동 VACUUM 전에는 읽기를 열지 않음"을 **필수 배포/운영 절차**로 승격하고, 미완료 시 500 위험이 있음을 명시한다.
  - 두 경우 모두 timeout 확대, SQL 캐시, 검증 생략, 자동 VACUUM 추가는 하지 않는다.
- 비차단: B의 직후 시간이 인덱스 없음과 같거나 낫다면, 8.4-2 안내를 문서에 넣는 조건으로 B를 진행한다. 직후 구간 해결은 별도 후속 이슈로 남긴다.

## 9. Codex 후속 결정

누락됐던 원본 after_replay 측정값을 §7에 보완했다. §8.5의 운영 경계 선택을 채택한다. 이번 범위는 현재 정적 데이터의 반복 출처 조회를 개선하는 것이며, 대량 쓰기 직후의 성능은 미해결로 남긴다. 대량 인허가 ETL 커밋 후에는 읽기 요청을 재개하기 전 별도 autocommit 세션의 수동 `VACUUM (ANALYZE) stores`와 조회 확인을 필수 운영 절차로 문서화한다. ETL 커밋과 VACUUM은 원자적이지 않고 실패 시 데이터 커밋을 되돌리지 않는다. 자동 VACUUM/ETL 원자성 변경은 추가하지 않는다.

Claude의 전체 재적재 순서별3회 반복 권고는 상대 우열/SLA를 주장하기 위한 검증으로 남긴다. 이번에는 그 주장을 하지 않고 원안/B 모두의 dirty 한계와 쓰기 비용을 공개하는 범위로 한정하므로 추가 전량 UPDATE 비교는 진행하지 않는다. 현재 실제 데이터의 변경 전/후 응답·동시 흐름, 실제 SQL의 인덱스 적격성 및 migration/의미 보존 회귀는 필수로 완료한다.

일반1,166개·새 격리 회귀9개·ruff/format·mypy136files는 통과했다. 전체격리/실제dev 검증 결과는 완료 후 기록한다.

## 10. 최종 검증 결과

- 일반1,166·격리PostGIS155(새 회귀9개 포함)·ruff/format·mypy136files 통과. 기존 Starlette 경고1건 유지. 격리는 전용loopback55482의 일회용DB만 사용했고 실제DB에서 파괴적 suite를 실행하지 않았다.
- 실제dev writer 부재를 확인한 뒤 index migration0010만 적용했다. 추가 index4,440,064bytes/대상597,645행이며 heap63,595페이지 모두all-visible인 기존 정적 상태였다. 앱 계정의 stores 소유도 확인했다. 실제dev VACUUM·ETL/DML은 실행하지 않았다.
- 전후14테이블 전체행/to_jsonb(geometry 포함)hash·건수와 기존index정의 보존, 추가index1개, 앱모델차이0, head0009→0010 확인. 실제5개API의 전체응답 digest도 전후 동일했다.
- 실제API 순차 관측(ms): history468→94, range547→78, nearby1141→328, activity469→94, Risk500→140. 같은날 동일query 단발이며 정확한 성능비/SLA로 일반화하지 않는다.
- 실제5개동시조회3세트(15건) 모두200, 관측31~157ms·SQL오류0. Risk warm캐시도 포함하므로 모든측정이cold는아니다. 기존출처쿼리 EXPLAIN은 index-only semi join/heap 전체읽기없이0.096ms였다.
- 이전실패했던 실제출력화면의 후속 GET200·PNG Blob생성/저장클릭·인쇄이벤트·메모리PDF1페이지를 확인했다. 출력물문구전체정확성/OS저장인쇄대화상자는 검증하지않았고 파일을남기지않았다. 실LLM추가호출0, FE추적파일변경0.
- 대량인허가커밋후수동VACUUM·조회확인절차와 잠금/쓰기비용을 README에 반영했다. dirty구간미해결·반복비교미수행은§7~9를그대로유지한다. 전체FE/공식지표/브랜드승인/운영SLA완료를주장하지않는다.
