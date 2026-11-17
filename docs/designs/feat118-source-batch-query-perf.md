# 출처 배치 누적 시 조회 성능 검토 및 개선 (#118)

- 이슈: [#118](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/118) `출처 배치 누적 시 조회 성능 검토 및 개선`
- 브랜치: `feat#118-source-batch-query-perf` (develop `c255ded`, head 0011)
- 선행: #78 재점검의 BE 미해결 항목 "미사용 배치 누적까지 고려한 출처 조회 성능 검토", #82 `ix_stores_provenance`, #86 유지보수 실행기
- 목적: 과거 인허가 배치가 쌓일 때 출처 조회가 SQL 3초 제한을 넘는지 측정하고, 측정으로 확인된 병목만 최소 변경으로 개선한다.

## 1. 현재 구현과 확인할 질문

`app/services/store_cohort.py::current_provenance`는 요청마다 두 SQL을 실행한다.

1. **배치 목록**: `store_import_batches`마다 `EXISTS(지원 점포 AND 같은 batch_id/source)`. history의 `get_history`도 같은 쿼리를 따로 쓴다.
2. **고아 검사**: `EXISTS(지원 점포 AND NOT EXISTS(같은 batch_id/source 배치 행))`. 지원 점포 전체를 anti-join한다.

ETL(`etl/localdata/repository.py`)은 재적재 때 원천에 다시 나온 행의 `batch_id`를 새 배치로 UPDATE하고, 원천에서 사라진 행은 이전 batch_id로 남긴다. 따라서 재적재가 반복되면 `store_import_batches`에는 (a) 행이 모두 이관된 빈 배치, (b) 사라진 지원 점포가 남은 잔여 배치, (c) 미지원/제외 행만 남은 배치가 쌓인다.

질문: (Q1) 배치 수 증가가 두 쿼리를 느리게 하는가? (Q2) 대량 재적재 직후(dirty) 구간의 비용은 무엇이 지배하는가? (Q3) 의미를 바꾸지 않는 개선이 있는가?

## 2. 측정 (일회용 PostGIS 17-3.7, 합성 데이터만)

CI와 같은 이미지의 일회용 컨테이너(loopback 55472)에서 실제 migration head 0011 위에 합성 stores 689,440행(general 541,169 / rest_cafe 148,271, 지원 약 52%·삭제/검토대기/미지원 혼합)을 만들었다. 실제 점포 원자료는 복사하지 않았다. 실행 계획은 `EXPLAIN (ANALYZE, BUFFERS)`, 동시성은 4개 연결 동시 실행으로 쟀다. 단발 측정이며 SLA나 정확한 배율로 쓰지 않는다.

### 2.1 좁은 행(heap 1~2만 페이지, 캐시 적중)

| 상태 | 배치 수 | 배치 목록 | 고아 검사(기존) |
|---|---|---|---|
| A 깨끗 | 2 | 0.1ms | 43~63ms |
| B 전체 재적재 직후 | 4 | 첫 142ms(heap fetch 620,512) → 이후 0.3~0.5ms | 74~118ms(seq scan) |
| D VACUUM 후 + 과거 배치 1,320개(빈 1,200·잔여 60·미지원만 60) | 1,324 | 1.9~3.2ms | 47~54ms |
| E D에서 재적재 직후 | 1,326 | 첫 145ms(heap fetch 497,819) → 이후 2.0~2.6ms | 85~153ms(매번 heap fetch 약 688,762) |
| F E 후 VACUUM | 1,326 | 1.4~1.7ms | 48~68ms |

### 2.2 실제와 비슷한 행 폭(heap 38,362페이지, 서버 재시작+OS 캐시 비움)

과거 배치 1,262개(빈 1,200·미지원만 60). 실제 개발 DB stores는 35,584페이지다.

| 상태 | 고아 검사 기존: 4동시 / 단독 EXPLAIN | 고아 검사 후보(§3): 4동시 / 단독 EXPLAIN | 배치 목록 EXPLAIN |
|---|---|---|---|
| 깨끗·콜드 | 111~150ms / 38~40ms | 6~21ms / 0.3~0.4ms | 1.9ms |
| 재적재 직후 1회차(후보 먼저 실행) | 559~603ms / 99ms | 1,087~1,106ms / 7.5~8.1ms | 첫 168ms → 13ms |
| 재적재 직후 2회차(기존 먼저 실행) | 1,035~1,052ms / 142~148ms | 294~339ms / 7.3~7.4ms | 첫 200ms(heap fetch 731,309) → 29ms |

재적재 직후 각 회차에서 **먼저 실행된 쪽이 약 1초**를 냈다. 옛 배치의 죽은 인덱스 항목을 처음 확인하는 비용(콜드 heap I/O)이며 어느 쿼리든 먼저 닿는 쪽이 낸다. 그 뒤 PostgreSQL이 죽은 항목에 표시를 남기면 배치 목록은 빨라지지만, 기존 고아 검사는 살아 있는 행 전체를 VACUUM 전까지 매번 확인한다.

해석 한계(Claude 검토 보완):
- 죽은 항목 표시(LP_DEAD)는 그 튜플이 **모든** 트랜잭션에 죽은 것으로 보일 때만 남는다. 재적재 직후에도 더 오래된 snapshot(긴 REPEATABLE READ 요청, ETL·maintenance 세션 등)이 살아 있으면 표시가 남지 않아 "첫 확인 비용"이 여러 요청에 반복될 수 있다. 위 측정은 그런 오래된 snapshot이 없는 조건의 값이다.
- 2회차 후보의 4동시 294~339ms와 단독 EXPLAIN 7.3~7.4ms 사이의 큰 차이는 이번 측정에서 원인을 분리하지 않았다(연결·동시 대기·측정 방식 차이 가능). 후보의 정상 상태 비용은 단독 EXPLAIN 값으로만 해석하고, 4동시 값은 동시 실행 시 관측값으로만 남긴다.

### 2.3 실제 개발 DB 읽기 전용 (현재 상태)

READ ONLY REPEATABLE READ에서 확인. PostgreSQL 17.11, head 0011, 배치는 원천별 1개(빈 배치 0), stores 35,584페이지 중 all-visible 35,573. 배치 목록 1.6ms(heap fetch 0), 고아 검사 44ms(병렬 index-only, heap fetch 0). 현재 실제 DB에는 누적이 없다.

### 2.4 결론

- **Q1**: 배치 누적 자체는 병목이 아니다. 1,324개에서도 배치 목록 1.4~3.2ms. 배치당 B-tree 하강 1회 수준이며 #82 §6.5의 "미지원 행만 남은 배치" 비용도 50행 단위에서는 무시할 수 있다.
- **Q2**: dirty 구간의 비용은 배치 수가 아니라 (1) 옛 배치 죽은 항목의 첫 확인, (2) 기존 고아 검사가 매 요청 지원 점포 전체(약 34만 행)를 확인하는 구조가 지배한다. (2)는 VACUUM 전까지 요청마다 반복된다.
- **Q3**: 고아 검사를 "지원 점포 전체 anti-join"에서 "지원 점포에 존재하는 서로 다른 (batch_id, source) 키만 skip scan"으로 바꾸면 의미를 유지하면서 행 수가 아닌 키 수에 비례하게 만들 수 있다(§3).
- 이번 합성 측정에서는 어느 상태도 3초를 넘지 않았다. #82에서 기록한 5.759초는 다른 환경·데이터의 단발 값이므로 이번 값과 직접 비교하지 않는다. 재적재 직후 첫 확인 약 1초는 이 변경으로 없어지지 않으며, #82/#86의 "읽기 중지 → 커밋 → VACUUM → 확인 → 재개" 운영 절차를 유지한다.

## 3. 변경 설계

### 3.1 포함 범위

`current_provenance`의 고아 검사 SQL만 같은 의미의 recursive CTE skip scan으로 교체한다.

```sql
WITH RECURSIVE provenance_keys(batch_id, source) AS (
  (SELECT batch_id, source FROM stores
   WHERE <SUPPORTED_STORES> AND batch_id IS NOT NULL
   ORDER BY batch_id, source LIMIT 1)
  UNION ALL
  SELECT n.batch_id, n.source FROM provenance_keys k
  JOIN LATERAL (
    SELECT batch_id, source FROM stores
    WHERE <SUPPORTED_STORES> AND (batch_id, source) > (k.batch_id, k.source)
    ORDER BY batch_id, source LIMIT 1) n ON true
)
SELECT EXISTS (SELECT 1 FROM provenance_keys pk WHERE NOT EXISTS (
         SELECT 1 FROM store_import_batches b
         WHERE b.batch_id = pk.batch_id AND b.source = pk.source))
    OR EXISTS (SELECT 1 FROM stores WHERE <SUPPORTED_STORES> AND batch_id IS NULL)
```

- `<SUPPORTED_STORES>`는 기존 `app.services.store_history.SUPPORTED_STORES` 식을 그대로 재사용한다(SQLAlchemy `select`/`cte(recursive=True)`/`lateral`/`tuple_`로 작성, 손으로 쓴 SQL 문자열 아님).
- 의미 동치: 기존 고아 = "지원 점포 중 (batch_id, source)가 배치 표에 없는 행이 하나라도 있음". 지원 점포의 non-null 키 집합을 빠짐없이 열거하고(정렬 + 엄격한 `>` 진행이라 누락·중복 없음), 그중 배치 표에 없는 키가 있는지 본다. `batch_id IS NULL`은 B-tree 정렬상 row 비교에서 빠지므로 별도 EXISTS로 검사한다. NULL source는 `source IN (...)` 조건 때문에 지원 점포에 포함되지 않는다.
- 인덱스: `ix_stores_provenance (batch_id, source, category, sub_category) WHERE deleted_at IS NULL AND category_review_flag IS NOT TRUE`의 앞 두 키로 row 비교·정렬·LIMIT 1을 처리한다. predicate 함의는 #82와 같은 `SUPPORTED_STORES` 식이므로 유지된다. `batch_id IS NULL` 검사도 같은 인덱스의 첫 키로 처리된다.
- 재귀 단계 수 = 지원 점포에 존재하는 서로 다른 키 수(현재 2, 누적 시 잔여 배치 수만큼)이며 단계마다 LIMIT 1 인덱스 탐색이다.

추가 확인 사항(Claude 검토 보완):
- **NULL·종료 의미**: `stores.source`는 NOT NULL이고 `store_import_batches`의 PK는 `batch_id` 단독이다. 첫 분기는 `batch_id IS NOT NULL`이고, 재귀 분기는 row 비교에서 `batch_id IS NULL` 행이 NULL(=거짓)이 되어 빠지므로 `k`에는 NULL이 들어가지 않는다. 엄격한 `>`로 키가 단조 증가하므로 재귀는 유한하게 끝난다(LATERAL이 0행이면 종료). 같은 batch_id·다른 source 행은 별도 키 `(batch_id, 다른 source)`로 열거되어 배치 표의 `(batch_id, source)`와 맞지 않으므로 기존처럼 고아다. 빈 stores는 두 EXISTS 모두 거짓이고 이후 `not batches`로 기존과 같이 500이다. 지원 행이 없는 키는 기존 anti-join도 보지 않으므로 같다. UUID 정렬은 PostgreSQL uuid 바이트 순서이며 결과(존재 여부)는 열거 순서와 무관하다.
- **첫 분기의 LIMIT 괄호**: UNION ALL의 비재귀 항에 ORDER BY/LIMIT이 있으므로 SQL에서 반드시 괄호로 감싸져야 한다. SQLAlchemy가 compound 안에서 자동으로 괄호를 넣는지 컴파일 결과로 확인하고, 아니면 subquery로 감싼다. 재귀 항의 LIMIT은 LATERAL 서브쿼리 안이라 허용된다.
- **키 내부 정렬 의존**: 인덱스 3·4번째 키(category, sub_category)는 정렬에만 쓰인다. 현재 ETL은 지원 업종 외 행을 `category=NULL`로 두므로(B-tree 기본 NULLS LAST) 같은 키 안에서 지원 행이 먼저 나와 LIMIT 1이 곧바로 끝난다. 반대로 **지원 행이 없는 키(미지원/제외 행만 남은 배치, 지원 외 source)** 와 재적재 직후 옛 배치의 죽은 항목은 그 키의 인덱스 항목을 끝까지 선형으로 지나간다. 비용은 "키 수"가 아니라 "지원 행 없는 키의 항목 수 + 죽은 항목 수"에도 비례하며, §2의 측정(미지원만 50~60행 배치)은 이 범위에서만 확인됐다. 향후 지원 외 category 값을 NULL 대신 문자열로 저장하면 키 내부 순서가 바뀔 수 있다.
- **NULL batch_id 꼬리**: 인덱스 끝의 `batch_id IS NULL` 항목(미지원 업종의 NULL 배치 행 등)은 마지막 재귀 단계와 별도 `IS NULL` EXISTS가 지나갈 수 있다. PostgreSQL B-tree는 필수 부등호 키에서 NULL을 만나면 순방향 스캔을 멈추도록 되어 있으나, 실제 개발 DB의 `batch_id IS NULL` 행 수와 마지막 단계 EXPLAIN(BUFFERS)을 구현 검증에서 기록한다(§6).
- **인덱스 의존**: 이 쿼리는 `ix_stores_provenance`가 있어야만 키 수에 비례한다. 인덱스가 없으면 단계마다 전체 정렬/스캔이 되어 기존보다 크게 느려질 수 있다(#78/#82가 거절한 "인덱스 없는 상관 LIMIT"과 같은 위험). migration 0010을 downgrade하는 경우에는 이 코드도 함께 되돌려야 하며, 현재 앱·ETL head guard는 0011이다.
- **bind parameter**: SQLAlchemy는 `SUPPORTED_STORES`의 source/category/sub_category 값을 bind parameter로 보내지만 partial index predicate 함의에 필요한 `deleted_at IS NULL`, `category_review_flag IS NOT true`는 리터럴로 렌더링되고, row 비교의 우변은 CTE 컬럼이라 파라미터가 아니다. 따라서 custom/generic plan 어느 쪽에서도 인덱스 적격성은 파라미터 값에 의존하지 않을 것으로 본다. 다만 planner가 실제로 LATERAL 단계에 인덱스 순서 스캔을 고르는지는 §6-4 테스트와 실제 DB EXPLAIN으로 확인한다.
- **snapshot·시간 제한**: 새 SQL도 기존과 같은 READ ONLY REPEATABLE READ 세션의 한 문장이며 statement_timeout(기본 3초)은 문장 단위로 그대로 적용된다. 배치 목록과 고아 검사가 같은 snapshot을 보는 기존 의미는 바뀌지 않는다.

### 3.2 제외 범위

- 호출부(`data_range`·`market_activity`·`risk`·`spatial_stores`·`etl/localdata/maintenance.py`)는 `current_provenance`의 시그니처·반환·예외를 그대로 쓰므로 수정하지 않는다. `tests/etl/test_maintenance.py`는 이 함수를 monkeypatch하므로 영향이 없다. `get_history`에는 고아 검사가 없어 대상이 아니다.
- 배치 목록 쿼리(`current_provenance`·`get_history`)는 바꾸지 않는다. 깨끗한 상태에서 이미 1~3ms이고, dirty 첫 확인 비용은 쿼리 형태로 피할 수 없다.
- 공개 API 응답, `meta.store_batches`/`stores_batch_ids`/`data_updated_at` 계산, 고아·날짜 이상의 500 정책, READ ONLY REPEATABLE READ·SQL 3초, 캐시, migration·인덱스·모델, ETL 트랜잭션은 바꾸지 않는다.
- 시간 제한 확대·SQL 결과 캐시·검증 생략·인덱스 없는 상관 LIMIT·자동 VACUUM·자동 읽기 차단은 하지 않는다(#78/#82/#86 결정 유지).
- 잔여 배치가 쌓이면 `stores_batch_ids`가 길어지고 map_version이 섞이면 `null`이 되는 기존 의미는 그대로다(성능 문제가 아니라 기존 계약). 실제 LocalData 전체 파일에서 행이 사라지는 빈도는 확인하지 않았다.
- Render DB·FE·실제 `.env`/Docker 설정은 변경하지 않는다. 배포는 별도 수동 결정이다.

## 4. 데이터·API 계약과 오류 처리

응답 형식·필드·상태 코드 변화 없음. 고아가 있으면 기존과 같이 `AppError(INTERNAL_ERROR, NO_STORE)` → 500, 원문 비노출. SQL 오류·statement_timeout은 기존 경로(500)를 그대로 탄다. FE 계약·CLAUDE.md 동기화 대상이 아니다.

## 5. 보안·개인정보·외부 API·DB

외부 API 호출 없음. 로그·측정 기록에 주소·좌표·건물키·관리번호·원문을 남기지 않는다(측정은 건수·시간·계획 노드명만). 실제 개발 DB는 READ ONLY 세션 검증만 하며 DML/DDL/VACUUM을 실행하지 않는다. 파괴적 테스트는 일회용 DB에서만 실행한다.

## 6. 테스트 계획

일반(단위):
- 고아 검사 SQL을 PostgreSQL dialect로 컴파일해 recursive CTE·`IS NULL` 분기·`SUPPORTED_STORES` 조건이 포함되고, 비재귀 항의 ORDER BY/LIMIT이 괄호로 감싸졌는지 확인한다(DB 불필요). 이를 위해 SQL 생성은 `store_cohort.py` 안의 작은 비공개 함수(예: `_orphan_exists()`)로 분리해 테스트에서 컴파일할 수 있게 한다.

격리 PostGIS(`tests/integration/test_store_provenance_index.py` 확장):
1. 기존 `test_nullable_or_wrong_source_orphans_keep_safe_failure_policy` 6사례가 그대로 통과(NULL batch·없는 UUID·source 불일치 → 500, 삭제/검토대기/미지원 고아 → 200).
2. 새 동치 회귀: 여러 배치·키 정렬 경계(UUID 앞/뒤 순서), 같은 batch_id 다른 source, 미지원 행만 남은 배치 다음에 오는 지원 키, 고아 키가 첫/중간/마지막 위치일 때 새 쿼리 결과 = 기존 anti-join 결과를 함께 실행해 비교한다. 기존 anti-join은 테스트 안의 기준 함수로 보존한다. UUID 순서는 `batch(session, batch_id=UUID(int=n))`처럼 고정 값으로 만든다(`batch` 헬퍼가 `batch_id` 덮어쓰기를 지원; 기본 uuid4는 순서가 무작위). 한 키에 여러 행이 필요하면 `(source, license_no)` 유일 제약 때문에 license_no를 다르게 둔다. 추가 사례: 지원 행과 같은 키 안의 `category=NULL` 미지원 행, 지원 외 source 키, `batch_id IS NULL` 미지원 행이 여러 개 있는 꼬리(→ 200), `batch_id IS NULL` 지원 행 1개(→ 500), 빈 stores(두 쿼리 모두 거짓).
3. 많은 배치(예: 빈 배치 수백 + 잔여 배치 수십)에서도 결과가 같고 오류가 없음을 확인(시간 임계값은 단언하지 않음).
4. `test_actual_service_queries_are_eligible_for_provenance_index`의 캡처 조건은 현재 `statement.startswith("SELECT EXISTS")`라서 새 SQL(`WITH RECURSIVE ...`)을 잡지 못하고 `len(captured) == 3`이 실패한다. 같은 커밋에서 `WITH RECURSIVE`도 잡도록 고친다. 단언은 "JSON 어딘가에 인덱스 이름이 있음"으로는 부족하다(`IS NULL` 분기만 인덱스를 써도 통과하므로). `enable_seqscan=off`에서 계획 JSON을 순회해 `Relation Name = stores`인 모든 스캔 노드가 `ix_stores_provenance`를 쓰고, 그중 LATERAL 단계 노드의 `Index Cond`에 `(batch_id, source)` row 비교가 들어 있음을 단언한다(성능 증명 아님). SQLAlchemy가 보낸 SQL과 bind parameter를 그대로 EXPLAIN한다.
5. 기존 history/nearby/data-range/activity/risk/analysis flow 통합 회귀가 그대로 통과.

전체 검사: `ruff check .`, `ruff format --check .`, `mypy app migrations`, 일반 `pytest`, 일회용 DB의 `pytest -m integration`.

실제 개발 DB(READ ONLY): 변경 전후 `current_provenance` 결과(배치 집합·기준일) 동일, 새 SQL EXPLAIN (ANALYZE, BUFFERS) 시간·노드(LATERAL 단계가 `ix_stores_provenance` 순서 스캔인지, 마지막 단계·`IS NULL` 분기의 버퍼 수), 인덱스 기준 `batch_id IS NULL` 행 수(건수만), 5개 조회 API 응답 digest 전후 동일. 일회용 DB의 합성 dirty 상태에서도 같은 계획 노드를 기록한다.

## 7. 중단 조건과 완료 조건

- 중단: 새 쿼리가 어느 회귀 사례에서든 기존과 다른 결과를 내거나, 인덱스를 쓰지 못해 깨끗한 상태에서 기존보다 느리면 병합하지 않고 보고한다. 실제 개발 DB EXPLAIN에서 LATERAL 단계가 인덱스 순서 스캔이 아니거나(정렬/seq scan) `IS NULL` 분기·마지막 단계가 NULL 꼬리를 길게 읽는 것으로 확인되면 같은 기준으로 멈춘다. 실제 개발 DB 읽기 검증을 할 수 없으면 PR 전에 멈춘다.
- 완료: 동치·적격성 회귀 포함 전체 검사 통과, 실제 DB 읽기 전용 결과 동일, 문서(BE CLAUDE.md·작업계획) 갱신, PR CI/CodeQL 통과.

## 8. 기능별 커밋 계획

1. `docs(be): 출처 배치 누적 조회 측정과 설계·Claude 검토 기록` — 이 MD.
2. `perf(be): 출처 고아 검사를 배치 키 skip scan으로 변경` — `store_cohort.py` + 단위/격리 동치·적격성 테스트(같은 커밋에서 기존 캡처 테스트 수정 포함, 중간 커밋이 깨지지 않게).
3. `docs(be): 출처 조회 개선 결과와 작업계획 반영` — 실제 DB 검증 결과, `docs/be-work-plan.md`, `CLAUDE.md`.

## 9. Claude Code 검토 기록

### 9.1 검토 범위

Claude Code 재검토자가 Read/Grep/Glob으로 이 MD 전체와 다음 소스를 읽었다: `app/services/store_cohort.py`(`current_provenance`), `app/services/store_history.py`(`SUPPORTED_STORES`, `get_history`), `app/models/store.py`·`app/models/store_import_batch.py`(인덱스 정의·nullability·PK), `etl/localdata/repository.py`·`etl/localdata/normalize.py`(재적재 시 batch_id 이동, 지원 외 업종의 category NULL 처리), `tests/integration/test_store_provenance_index.py`·`tests/integration/test_nearby.py`(`batch`/`store` 헬퍼), `docs/designs/feat82-store-provenance-index.md`, `app/db/dependencies.py`(READ ONLY RR·statement_timeout), `current_provenance` 호출부 전체(grep: data_range·market_activity·risk·spatial_stores·maintenance, tests/etl/test_maintenance.py). 이 MD만 Edit했으며 명령·테스트·DB·네트워크·git은 실행하지 않았다. §2의 측정값은 검증하지 않고 문서 기재값으로만 다뤘다.

### 9.2 종합 판단

**조건부 진행 가능.** 제안한 recursive CTE skip scan은 기존 anti-join과 의미가 같다고 판단한다(NULL batch_id는 별도 EXISTS, source NOT NULL, 같은 batch_id·다른 source는 별도 키로 고아, 삭제/검토대기/미지원은 `SUPPORTED_STORES`로 동일 제외, 지원 행 없는 키·빈 테이블도 동일). 범위(고아 검사만 교체, 계약·timeout·인덱스 불변)와 #78/#82 결정(인덱스 없는 상관 LIMIT 금지 등)과도 맞다. 단, 성능 이득이 planner의 인덱스 순서 스캔 선택에 전적으로 의존하므로 §6-4의 강화된 계획 단언과 실제 DB EXPLAIN이 통과해야 한다.

### 9.3 발견 사항과 수정한 내용

1. **적격성 테스트 단언이 약함(§6-4 수정)**: 기존 단언은 계획 JSON 어딘가에 인덱스 이름이 있으면 통과한다. 새 SQL은 `IS NULL` 분기도 같은 인덱스를 쓰므로 LATERAL 단계가 정렬/seq scan이어도 통과할 수 있다. 모든 stores 스캔 노드의 인덱스 사용과 LATERAL 노드의 row 비교 Index Cond를 단언하도록 바꿨다. 기존 캡처 필터(`startswith("SELECT EXISTS")`)가 새 SQL을 놓쳐 `len == 3`이 깨진다는 점도 명시했다(문서의 같은 커밋 수정 계획은 타당).
2. **비용 상한의 범위가 과대 표현될 소지(§3.1 보완)**: "키 수에 비례"는 지원 행이 있는 키에만 맞다. 지원 행 없는 키·지원 외 source·죽은 항목은 선형으로 지나가며, 지원 행이 키 안에서 먼저 나오는 것은 현재 ETL이 지원 외 업종을 `category=NULL`(NULLS LAST)로 저장하기 때문이다. 이 의존과 측정 범위를 적었다.
3. **NULL batch_id 꼬리(§3.1·§6 보완)**: 마지막 재귀 단계와 `IS NULL` 분기가 인덱스 끝의 NULL 배치 항목을 지날 수 있어 실제 DB 건수·EXPLAIN(BUFFERS) 기록과 회귀 사례를 추가했다.
4. **동치 근거 명시(§3.1)**: 재귀 종료, row 비교 NULL 의미, 배치 PK가 batch_id 단독인 점, 빈 테이블, UUID 정렬 무관성을 적었다. 비재귀 항 ORDER BY/LIMIT의 괄호 필요성을 컴파일 확인 항목으로 추가했다.
5. **인덱스 의존·rollback(§3.1)**: 인덱스가 없으면 단계마다 정렬/스캔이 되어 #82가 거절한 위험과 같아지므로 0010 downgrade 시 코드도 되돌려야 함을 적었다.
6. **bind parameter·snapshot(§3.1)**: predicate 함의 조건은 리터럴, row 비교 우변은 CTE 컬럼이라 파라미터 값에 의존하지 않는다고 판단했고, 실제 선택은 테스트/EXPLAIN으로 확인하도록 했다. 같은 RR snapshot·문장 단위 3초 제한이 유지됨을 적었다.
7. **측정 해석 한계(§2.2 보완)**: LP_DEAD 표시는 오래된 snapshot이 없을 때만 남아 첫 확인 비용이 반복될 수 있다는 점과, 후보의 4동시 294~339ms 대 단독 7.3ms 차이가 원인 미분리라는 점을 적었다. SLA 비주장·약 1초 첫 확인 미해결·운영 절차 유지 서술(§2.4)은 정직하게 제한되어 있어 유지했다.
8. **테스트 실행 가능성(§6 보완)**: UUID 순서는 `batch(batch_id=UUID(int=n))`로 고정, 한 키 다행은 license_no를 다르게, 기존 anti-join은 테스트 기준 함수로 보존, SQL 생성은 단위 테스트 가능한 비공개 함수로 분리하도록 적었다. 호출부·maintenance·get_history는 변경 불필요함을 §3.2에 명시했다.

커밋 계획(§8)은 코드와 캡처 테스트 수정을 같은 커밋에 두므로 중간 커밋이 깨지지 않는다. 보안·개인정보: 새 SQL은 원문을 출력하지 않고 오류 경로가 기존과 같아 추가 위험은 없다. 측정 기록에도 건수·시간·노드명만 남기는 §5 방침이 유지된다.

### 9.4 남은 제한·구현 시 확인할 점

- 재적재 직후 첫 확인 약 1초(배치 목록 포함)는 해결되지 않으며 #82/#86 운영 절차(읽기 중지→커밋→VACUUM→확인→재개)가 계속 필요하다.
- 지원 행 없는 키의 항목 수·NULL batch 꼬리·죽은 항목이 크게 늘면 새 쿼리도 선형 비용이 생긴다. 실제 LocalData에서의 누적 규모는 측정하지 않았다.
- 지원 외 업종을 NULL이 아닌 category 문자열로 저장하도록 ETL이 바뀌면 키 내부 순서 가정을 다시 검토한다.
- 실제 개발 DB에서 LATERAL 단계 인덱스 순서 스캔, 마지막 단계·`IS NULL` 분기 버퍼 수, 변경 전후 결과·API digest 동일을 확인한 뒤 PR한다(§7 중단 조건).
- 측정값(§2)은 단발 합성 측정이며 이번 검토에서 재현하지 않았다.

## 10. 구현·검증 결과

- 구현: `app/services/store_cohort.py`에 `orphan_exists()`를 추가하고 `current_provenance`의 고아 검사만 이 쿼리로 바꿨다. SQLAlchemy 컴파일 결과에서 비재귀 항의 ORDER BY/LIMIT은 괄호로 감싸진다(단위 테스트로 고정). 배치 목록·`get_history`·호출부·응답·migration·인덱스·timeout은 바꾸지 않았다.
- 테스트: 단위 2개(컴파일 형태·세 stores 스캔의 지원 점포 조건). 격리 동치 12사례(빈 stores·전부 연결·고아 첫/중간/마지막 UUID·같은 batch 다른 source·미지원만 남은 배치 뒤 고아·미등록 키의 NULL category/미지원 source/삭제/검토대기·NULL batch 미지원 꼬리·NULL batch 지원 행·배치 340개 누적 ± 고아)에서 새 쿼리 = 기존 anti-join 기준 함수. 적격성 테스트는 `WITH RECURSIVE`를 캡처하고 모든 stores 스캔이 `ix_stores_provenance`이며 LATERAL 단계 Index Cond에 `ROW(batch_id, source) >`가 있음을 단언한다(성능 증명 아님).
- 로컬 검사: ruff check·ruff format --check(344 files)·mypy app migrations(99 files) 통과. 일반 **1,655 passed**(기준 1,653+신규 2), 일회용 PostGIS 17-3.7 격리 **263 passed**(기준 251+신규 12). 기존 Starlette 경고 1건 유지.
- 실제 개발 DB(READ ONLY REPEATABLE READ, `transaction_read_only=on`): 기존 anti-join과 새 쿼리 모두 false, `current_provenance` 배치 2개·기준일 2026-11-08. EXPLAIN ANALYZE 3회 기존 36.986~42.260ms → 새 0.097~0.103ms. LATERAL 단계는 `ix_stores_provenance` Index Only Scan(Index Cond에 row 비교, heap fetch 0), `IS NULL` 분기는 같은 인덱스 3블록이며 인덱스 predicate 기준 `batch_id IS NULL` 행 0건. 공개 랜드마크 좌표 1곳의 data-range·nearby·snapshot·activity·risk 5개 응답 digest가 기존 고아 검사 경로(테스트 안에서 교체)와 새 경로에서 모두 같았다. DML/DDL/VACUUM은 실행하지 않았다.
- 한계: 측정은 단발이며 SLA가 아니다. 재적재 직후 첫 확인(합성 콜드 약 1초)은 남으며 #82/#86 운영 절차를 유지한다. 실제 누적 배치는 현재 0개라 누적 효과는 합성 데이터로만 확인했다. Render 배포는 하지 않았다(자동 배포 off, 별도 수동 결정).
