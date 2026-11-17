# 기적재 점포의 상세 위치 복구 및 검증 설계

- 작성일: 2026-11-13
- 이슈: [#104](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/104)
- 브랜치: `feat#104-floor-location-backfill` (기준 develop `bd952e5`)
- 선행: [#102 파서 수정](feat102-address-place-floor-parser.md), [FE 피드백 분석](../be-fe-integration-feedback-review.md)
- 상태: Claude 설계 직접 검토·수정 → 구현 검토 보강·최종 PASS → 전체 검사·최종 코드 전체 복제 리허설 → 실제 개발 DB 적용·전후 API 검증 완료. PR/CI는 #104 연결 PR에서 확인한다.

## 1. 목표와 선행 확인

#102의 파서 수정은 새 입력에 적용되지만 기적재 NULL은 그대로다. 정상 지명 오인 때문에 잃은 상세 위치를 원본으로 복구하고, 위치 외 업무 값과 출처의 의미를 보존한다. 새 정책에 따른 업종·브랜드 판정, 원천 최신화는 이번 범위가 아니다.

로컬의 일반음식점/휴게음식점 format_version=2 원본 스냅샷을 찾았다. 헤더의 원문 hash·건수·당시 기준시각이 DB의 활성 normalization-v1 배치 2개와 일치한다. 일반 541,169행, 휴게 148,271행이며 migration0011이다. 메타데이터 일치만으로 쓰기를 승인하지 않는다.

- 일반음식점(`general_restaurant`): 스냅샷 전체 검증과 원래 기준일 변환·DB 전체 대조를 마쳤다. 541,169행, NULL→상세 위치 16,941행, geometry를 포함한 비위치 차이 0건이다. 이 결과는 구현 전 대조이며, 구현된 도구의 dry-run이 같은 건수(전체/변경/비위치 차이 0)를 재현하지 못하면 쓰기를 중단한다.
- 휴게음식점(`rest_cafe`): Claude 검토 중 전체 대조도 완료됐다. 148,271행, NULL→상세 위치 7,797행, 비위치 차이 0건이다. 두 원천 합계 변경 후보는 24,738행이다. 사전 geometry 대조는 X/Y/SRID/null 기준이며, 전용 도구와 격리 검사에서는 EWKB 바이트까지 검증한다.
- 실제 DB 쓰기는 아직 수행하지 않았다.

`collected_at`은 원본 스냅샷의 당시 검증 기준시각이다. 실제 전체 수집 완료시각이 아니며 다운로드 날짜나 오늘 날짜로 바꾸지 않는다. API meta.collected_at=null 계약을 유지한다.

## 2. 인터페이스와 범위

- 새 전용 모듈 `etl.localdata.floor_backfill`을 둔다. 기존 일반 upsert를 보정 명령처럼 실행하지 않는다. INSERT ON CONFLICT로 stores identity sequence가 소비되거나 비위치 열을 다시 쓰는 일을 피한다.
- CLI는 `--source general_restaurant|rest_cafe --snapshot PATH`를 받는다. 기본은 읽기 전용 dry-run이다.
- 쓰기는 `--write --expected-plan SHA256`를 모두 명시해야 한다. dry-run의 plan digest와 원본·대상·현재 DB 상태가 달라지면 쓰기를 거절한다. 원천별 별도 트랜잭션이며 한 원천의 일부만 저장하지 않는다.
- 실제 대상은 기존 `validate_local_target`·`check_local_database`를 재사용해 loopback/spoton_dev/spoton_app/비-superuser/PostGIS/head0011/유일 제약을 확인한다. 테스트는 별도 컨테이너/fixture의 DB에서 코어 동작을 검증하며 운영 대상 검사 우회 옵션은 만들지 않는다.
- FE·공개 API schema·DB 모델/migration·실제 .env·로컬 compose·원본 파일을 수정하거나 커밋하지 않는다.

## 3. 원본·비위치 값·전체 영향 검증

1. `load_snapshot`으로 본문 원문 digest·필드 allowlist·구별 건수·완전성·출처를 검증한다.
2. `transform_rows`는 원본 `collection.collected_at.date()`를 today로 사용한다. 새 배치용 ID는 업무 비교에서 제외하며 원문과 현재 정규화 규칙을 그대로 사용한다.
3. 현재 원천의 stores 행이 연결하는 활성 배치는 정확히 하나여야 한다. source/input_kind/input_sha256/rows_sha256/row_count/collection_basis/recorded_at/data_updated_at/update_reason/map_version이 원본과 맞고 rule_version이 검토한 v1/v2인 경우만 허용한다. 과거 미사용 배치는 건드리지 않는다.
4. DB의 전체 원천 키 집합과 변환 결과를 대조한다. 누락·추가·중복 키, 검토되지 않은 혼합 활성 배치, 원본 불일치는 중단 사유다.
5. 변환 결과의 모든 비위치 업무 열을 대조한다. 좌표는 Decimal 값과 geometry의 X/Y/SRID/null 상태를 확인한다. geometry는 float 근사 비교가 아니라 저장값의 `ST_AsEWKB`와 기존 적재 방식(`POINT(lng lat)`, SRID 4326)으로 만든 값의 EWKB 바이트 일치로 판정한다. 다른 pyproj/PROJ 환경의 좌표 차이도 자동 덮어쓰지 않는다. 날짜·업종·주소·건물 키·품질 플래그가 다르면 쓰기를 중단한다.
6. 위치 변화는 원래 floor_unit=NULL·location_level=NULL/unverified였던 행에서 새 파서가 명시 상세 위치를 얻는 경우만 허용한다. 기존 유효 값의 삭제·교체 또는 실제 모호 표현의 수용은 차단한다. 건물 키가 없으면 저장 location_level은 unverified를 유지한다.
   - 판정은 행 단위로 정확히 셋 중 하나다. (a) 변경: 저장 floor_unit IS NULL이고 저장 location_level이 NULL/unverified이며 새 floor_unit이 NOT NULL. (b) 동일: 저장 floor_unit이 NOT NULL이면 새 floor_unit·location_level과 정확히 같아야 한다. (c) 무변경: 새 floor_unit이 NULL이면 저장 floor_unit도 NULL이고 저장 location_level은 NULL/unverified여야 하며, location_level만의 NULL↔unverified 차이는 다시 쓰지 않는다(재실행 결정성 보장). 그 외 조합은 전체 중단 사유다.
7. 영향 집계는 전체 원천과 지원 업종을 구분하고, 층만/호만/층·호·건물 키 부재·구별 건수로 나눈다. 과거 가정 실험 8,094행을 확정 보정 수로 사용하지 않는다.
8. 원천별 전체 stores의 보호 hash를 만든다. 제외 열은 정확히 floor_unit/location_level/batch_id/updated_at이며 id·삭제 표시·is_franchise·brand_id·geometry를 포함한 나머지는 모두 보호한다. 현재 값 전체의 hash도 별도로 계산해 오래된 계획을 거절한다. 행 정렬은 source/license_no의 C collation으로 고정한다.
9. plan digest는 정확히 다음을 정규 직렬화한 SHA-256이다: source, 스냅샷 rows_sha256·input_sha256·row_count, MAP_VERSION·ETL_RULE_VERSION, 현재 활성 batch_id, 원천 전체 현재 상태 hash, 보호 hash, 정렬된 변경 목록(license_no, 새 floor_unit, 새 location_level)의 digest, 대상 식별(current_database, current_user, `inet_server_port()`, `pg_postmaster_start_time()`). 새 batch_id(uuid4)·실행 시각은 포함하지 않는다. 포트와 postmaster 시작시각을 묶으므로 복제본에서 얻은 계획은 실제 개발 DB에서 거절된다.

## 4. 쓰기 원자성과 출처

- 원본 로드·변환은 잠금 밖에서 수행한다. 쓰기 트랜잭션에서는 기존 localdata 수집기와 같은 source advisory lock을 잡고 stores/store_import_batches의 SHARE ROW EXCLUSIVE 잠금을 획득한다. 일반 SELECT는 허용하고 다른 writer는 배제한다. 잠금 대기는 `SET LOCAL lock_timeout='5s'`로 advisory lock과 테이블 잠금 모두에 적용하며, 잠금 순서는 기존 upsert와 같은 advisory → 테이블 순서로 고정한다. 시간 초과는 안전한 오류 코드로 rollback한다.
- 쓰기는 READ COMMITTED에서 잠금 획득 후 최신 상태를 다시 대조한다. REPEATABLE READ에서 advisory lock SELECT가 먼저 snapshot을 고정하면 잠금을 기다리는 동안 확정된 다른 writer의 행이 보이지 않을 수 있으므로 그 순서를 사용하지 않는다. 기본 dry-run은 REPEATABLE READ READ ONLY다.
- 잠금 후 대상·원본·비위치 대조·현재 상태 hash·계획 digest를 재확인한다. expected-plan과 다르거나 보호 조건 위반이면 UPDATE 전에 실패한다.
- 변경이 없으면 새 배치·updated_at 변경 없이 no-op이다. v2 재실행도 같은 원칙이다.
- 변경이 있으면 순서를 고정한다. ① `import_batch(collection,new_id)`의 normalization-v2 배치를 먼저 INSERT한다(stores.batch_id 참조 제약 유무와 무관하게 안전하며, commit 전에는 외부에 보이지 않는다). ② §3-6 (a) 행만 `WHERE source=:s AND license_no=:k AND batch_id=:old AND floor_unit IS NULL`로 floor_unit/location_level만 UPDATE하고 영향 행 수가 계획 변경 수와 정확히 같아야 한다. ③ `WHERE source=:s AND batch_id=:old`로 원천 전체 행의 batch_id·updated_at만 갱신하고 영향 행 수가 계획 전체 행 수와 같아야 한다. 하나라도 다르면 rollback한다. 전체 원본을 검증했으므로 새 배치가 원천 전체를 가리키며 부분 배치 혼합을 기본안으로 삼지 않는다.
- 새 배치의 data_updated_at·update_reason·recorded_at·collection_basis·input_kind·input_sha256·rows_sha256·row_count·map_version이 기존 활성 배치와 같은지 INSERT 전에 확인한다. rule_version만 v1→v2로 달라질 수 있다.
- 원본 input/rows hash·원천 갱신일·recorded_at·collection_basis·MAP_VERSION·update_reason을 보존한다. 과거 배치 metadata는 UPDATE/DELETE하지 않는다. loaded_at은 이번 DB 기록 시각이고 수집일로 노출하지 않는다. 보정 설명을 update_reason에 넣지 않는다.
- commit 전에 새 전체 위치 결과·키/건수·배치 연결·보호 hash를 다시 확인한다. 이후 검증 실패·SQL 오류·취소는 같은 트랜잭션을 rollback한다. sequence를 사용하는 stores INSERT는 실행하지 않는다.
- 출력·로그에는 건수·품질 집계·버전·비밀값이 아닌 digest·안전한 오류 코드만 남긴다. 상호/주소/관리번호 원문·키·접속 URL·SQL 예외 원문은 출력하지 않는다. plan digest는 자격증명이 아니지만 write 대상 host/port/database/user와 상태를 결합해 오사용을 방지한다.

## 5. 실제 DB 적용 절차

1. 전체 두 원본의 읽기 전용 대조를 마친다. 조건 불일치가 있으면 실제 쓰기는 멈추고 필요한 근거를 요청한다.
2. 설계의 실제 Claude 검토 후 구현·단위 검사·격리 PostGIS 검사를 통과한다.
3. 개발 DB의 custom-format 전체 백업을 저장소 밖에 만든다. 덤프와 원본은 커밋하지 않는다. 백업 직전 실제 개발 DB의 dry-run 현재 상태 hash를 기록한다.
4. 같은 PostGIS 이미지의 별도 컨테이너(다른 loopback 포트)에 그 백업을 복원한다. 복제본도 spoton_dev/spoton_app 비-superuser/head0011로 구성해 기존 대상 검사를 우회 없이 통과시킨다. 복원본 dry-run의 현재 상태 hash가 3의 기록과 같아야 하고, 그 후 dry-run→실제 쓰기→재실행 no-op→§5-6 전후 대조를 전체 데이터로 검증한다. 이 단계가 백업 복원 가능성 검증을 겸한다.
5. 유지보수 중 다른 ETL writer를 실행하지 않는다. 실제 개발 DB의 새 dry-run 계획을 계산한다. 그 현재 상태 hash가 3의 백업 시점 hash와 다르면 백업이 최신이 아니므로 3부터 다시 한다. 같을 때만 그 계획으로 원천별 쓰기를 수행한다. 앱의 3초 API 제한은 바꾸지 않으며 관리 명령의 statement timeout만 로컬 트랜잭션에서 제한적으로 높인다.
6. 전후 전체 보호 hash·다른 테이블의 내용/건수·브랜드 입력 hash 및 활성 근거·head·D를 대조한다. stores id sequence의 last_value와 stores 행 수가 전후 동일함을 확인한다. 응답 meta의 data_version.stores_batch_ids가 새 배치로 바뀜을 확인한다. risk 캐시 키는 batch id가 아니라 `pg_current_snapshot()` 등 snapshot token에 묶이므로, 무효화는 commit 후 token 변화로 확인한다. AI 캐시는 실제 키 구성 요소를 코드에서 확인해 그 기준으로 검증하며 data_version 변화만으로 무효화를 가정하지 않는다.
7. 최신 서버로 주소 검색→이력→AI 준비 문맥을 대조한다. 층만 같을 때 unverified, 층과 호 및 저장 신뢰 수준을 모두 충족할 때만 same_spot이다. 실제 앱 LLM 호출은 필수로 하지 않고 모의 공급자/준비 문맥으로 검증할 수 있다.
8. SQL 검증 실패 시 해당 원천은 커밋하지 않는다. 커밋 후 외부 검증에서 이상이 나면 추가 원천 쓰기를 중단하고 백업/기록을 보존한다. 전체 덤프를 실행 중 DB에 자동 덮어써 다른 변경을 잃는 동작은 하지 않는다.
9. commit 응답 중 연결 오류·취소가 발생하면 오류 출력만으로 미적용을 단정하지 않는다. 새 dry-run의 no_op·활성 v2 배치를 확인해 이미 적용됐는지 판단한다. 이전 쓰기 계획을 그대로 재사용하지 않는다.

## 6. 테스트와 PR

- 원본/시각/배치/키/비위치 열/geometry/계획 불일치 차단, 정상·모호 위치, 보호 hash의 허용/불허 열, 안전한 CLI/오류 출력을 단위 검사한다.
- 실제 PostGIS에서 dry-run이 쓰지 않음, 두 원천 분리, 원천 전체 배치 교체와 과거 배치 보존, 브랜드·삭제·geometry·sequence 보존, 새 위치의 이력 판정, 재실행 no-op, 실패 후 전체 rollback, 잠금/오래된 계획 거절, data_version/AI 캐시 무효화를 검증한다.
- 위 통합 검사에 다음 필수 사례를 포함한다.
  - 잠금 경합 회귀: 다른 연결이 같은 advisory lock을 잡고 stores를 변경·commit하는 동안 백필이 대기하다 획득하면, READ COMMITTED 재확인이 그 변경을 보고 stale plan으로 거절한다. lock_timeout 초과도 안전한 오류 코드와 무변경으로 끝난다.
  - 실패 주입: ①배치 INSERT 후, ②위치 UPDATE 후, ③batch_id 갱신 후 각각 예외를 주입하면 stores·store_import_batches·sequence가 모두 원상태다. 영향 행 수 불일치도 rollback한다.
  - §3-6 판정표: 기존 값 교체·삭제, NULL 층 + 비-unverified level, location_level만 NULL↔unverified 차이(재작성 없음·no-op 유지)를 각각 검사한다.
  - stores INSERT 미실행: sequence last_value·행 수·id 집합 불변.
  - plan digest 대상 결합: 같은 데이터의 다른 포트/클러스터 계획 거절, 새 batch_id와 무관한 digest 결정성.
  - 비위치 1열(예: date_flag, building_key, EWKB 1비트) 차이만 있어도 전체 원천 쓰기 거절.
  - 최초 실행 후 v2 활성 배치 상태에서 재실행 시 새 배치·updated_at 변경 없음.
- 전체 pytest·ruff check/format·mypy app etl migrations, CI pinned PostGIS 통합 묶음을 실행한다. 실제 전체 데이터 검증은 합성 테스트와 구분해 기록한다.
- 지정 양식의 PR을 develop에 제출하고 CI/CodeQL·정확한 최종 커밋·저장소 조건을 확인한 후 사용자 기존 지시에 따라 정상 Squash 병합한다. FE·main·보호 규칙 우회·수동 브랜치 삭제는 범위 밖이다.

## 7. Claude Code 설계 검토

검토자: Claude Code(실제 검토). 대상 문서만 읽고 수정했으며 코드·테스트 실행, DB·원본 접근은 하지 않았다. 검증 수치는 사용자가 제공한 결과를 기록한 것이다.

**판정: 조건부 승인.** 전용 모듈, 일반 upsert 미사용(광범위 SET·identity sequence 소비 회피), READ COMMITTED + advisory/테이블 잠금 후 재확인, 원천 전체 변환 대조 후 쓰기, 실제 전체 복제 리허설·백업 선행이라는 골격은 타당하다. 아래 결함을 본문에 직접 반영했고, 구현은 이 수정본을 따른다.

주요 지적과 반영:

1. **증거 상태 갱신(§1)**: 일반음식점의 전체 검증(541,169행, NULL→상세 16,941행, geometry 포함 비위치 차이 0)을 기록했다. 휴게음식점은 진행 중이므로 완료·차이 0 전에는 계획을 만들지 않는다. 구현 도구의 dry-run이 같은 수치를 재현해야 한다는 수용 조건을 추가했다.
2. **위치 변경 판정이 모호함(§3-6)**: NULL/unverified를 함께 허용한다고만 되어 있어 location_level만 다른 행을 다시 쓸지 정해져 있지 않았다. 재실행 결정성이 깨질 수 있으므로 변경/동일/무변경 3분류와 그 외 중단으로 확정했다.
3. **plan digest 구성 누락(§3-9)**: 구성 요소를 정했다. 복제본도 loopback/spoton_dev/spoton_app이라 기존 대상 검사만으로는 실제 DB와 구분되지 않는다. 그래서 `inet_server_port()`·`pg_postmaster_start_time()`을 결합해 리허설 계획의 실제 DB 재사용을 차단했다.
4. **쓰기 순서·범위 검증(§4)**: 배치 INSERT를 먼저 두어 참조 제약 순서 문제를 없앴다. 각 UPDATE를 `batch_id=:old` 등으로 좁혔고, 영향 행 수가 계획과 정확히 같아야 한다는 조건을 추가했다. 배치 메타데이터의 rule_version 외 동일성도 INSERT 전에 확인한다.
5. **잠금 세부(§4)**: lock_timeout이 advisory lock에도 적용됨을 명시했다. 기존 upsert와 같은 잠금 순서로 고정했다.
6. **geometry 비교 방법(§3-5)**: 근사 비교 대신 EWKB 바이트 일치로 판정한다.
7. **백업 최신성(§5-3~5)**: 백업 후 실제 DB가 바뀌면 리허설이 무의미해진다. 백업 시점 상태 hash와 복원본·실제 dry-run hash가 일치해야 진행한다.
8. **캐시 무효화 근거 오류(§5-6)**: risk 캐시 키는 data_version이 아니라 `pg_current_snapshot()` 기반 token이다. 근거를 바로잡고, AI 캐시는 실제 키 구성으로 확인하도록 했다. sequence last_value·행 수 불변 확인도 추가했다.
9. **필수 테스트 누락(§6)**: 잠금 경합 stale 거절, 단계별 실패 주입 rollback, 판정표, sequence 불변, digest 대상 결합·결정성, 비위치 1열 차이 거절, v2 재실행 no-op을 추가했다.

구현 착수 조건: 휴게음식점 전체 대조 완료(비위치 차이 0). 이 조건이 충족되지 않으면 해당 원천은 쓰지 않는다. 일반음식점도 §5의 백업·전체 복제 리허설을 통과하기 전에는 실제 개발 DB에 쓰지 않는다.

위 검토 시점의 휴게음식점 진행 중 상태는 이후 §1·§8의 전체 대조 완료로 해소됐다. 실제 Claude Code 구현 재검토의 1차 판정은 NEEDS_FIX였고, 아래 항목을 반영해 재검토한다. Claude는 소스를 읽었으며 테스트·DB를 직접 실행하지 않았다.

- 잠그는 public 테이블과 ORM이 해석하는 stores/store_import_batches가 같은지 dry-run·쓰기 코어 모두에서 단언한다. 그림자 스키마의 동일 이름 뷰를 만든 2개 격리 검사가 읽기/쓰기의 target 거절을 확인했다.
- 1,001개 NULL 행으로 실제 executemany 1,000개 + 단건 1개 청크를 실행하고, 정확한 영향 행 수와 적용 결과를 확인했다.
- building_key가 없는데 location_level이 unverified가 아니면 변환기를 신뢰해 넘기지 않고 독립적으로 거절한다.
- commit 응답 불확실성의 새 dry-run 확인 절차를 §5-9에 추가했다.
- 기존 test_analysis_flow의 캐시 호출 수 실패는 기준 develop의 테스트 본문을 임시 위치에서 실행해 무관한 트랜잭션 commit 조건으로 재현했다. API는 200이지만 global MVCC token이 바뀌어 공급자를 2회 호출하는 정당한 경우였다. 현재 검사는 실제 캐시 키가 같으면 재사용·다르면 새 호출을 요구한다. 같은 강제 조건의 현재 검사는 통과했다. 제품 캐시 로직을 완화하지 않았다. 해당 helper는 이미 기준 develop에 있었으며 이번에는 키 관찰 함수만 추가했다.

## 8. Codex 최종 판단·실행 결과

Codex는 두 원천의 전체 대조 완료로 Claude의 구현 착수 조건이 충족됐다고 판단했다. narrow UPDATE·계획의 대상/상태 결합·커밋 전 재검증·잠금 후 최신 상태 재확인을 채택한다. no-op 쓰기도 새 dry-run의 계획으로 실행해야 하며 이전 적용 전 계획의 재사용은 stale로 거절한다. 클러스터/실제 접속 포트 구분을 위해 서버 식별에 더해 연결 URL의 host/port/database/user만 포함한다(암호는 제외). clone에서 계산한 계획을 개발 DB에 사용하지 않는다.

검토 과정에서 전체 백업을 저장소 밖에 만들고 복제 컨테이너 복원을 확인했다. 최종 코드로 원본/복원본 전체 상태 hash와 실제 적용 직전 상태를 대조해 백업 최신성 조건을 충족시켰다. 실제 적용 결과는 §8.3이다.

### 8.1 구현 및 로컬 검사

- 전용 `python -m etl.localdata.floor_backfill`을 구현했다. 기본 READ ONLY 대조, 오래된 계획/다른 대상 거절, source 잠금 후 최신 상태 재확인, 좁은 UPDATE·원천 전체 새 배치 연결·커밋 전 보존 검증을 제공한다.
- 최종 일반 1,564 passed(기준 1,548 + 신규 16), 최종 격리 PostGIS 249 passed(기준 218 + 신규 31), 실패·skip 0이다. ruff check/format 332 files, mypy app etl migrations 155 files도 통과했다. 기존 Starlette deprecation 경고 1건은 남는다.
- 전체 통합 1차는 245 passed/1 failed였다. 원인은 기존 캐시 검사 가정이며 §7의 기준 코드·강제 MVCC 재현과 현재 검사 통과를 확인한 뒤 전체 249개를 재실행해 통과했다. API 오류를 캐시 검사 완화로 숨긴 것이 아니며 제품 캐시 로직은 변경하지 않았다.
- 고정된 snapshot token의 결정적 AI 캐시 적중·버전별 miss는 기존 `tests/ai/test_interpretation_cache.py`가 검증한다. 키 순서/동일 입력 결정성은 `tests/test_cache.py`에서도 검증하며 이번 전체 일반 검사에 포함됐다. DB 통합 검사는 실제 global MVCC 키가 달라지는 정당한 경우를 허용한다.
- 실제 Claude Code 최종 재검토는 PASS(전체 검사·최종 코드 리허설 통과 후 실제 쓰기 조건)다. 소스 검토이며 Claude가 테스트·DB를 직접 실행한 것은 아니다. F1/F4 보강 이전의 1차 리허설에 이어 백업을 다시 복원하고 **최종 코드로 두 원천 전체 리허설을 재실행해 통과**했다. 파일 hash도 같은 코드인지 확인한 뒤 실제 DB를 적용했다.

### 8.2 실행 명령

일반음식점과 휴게음식점을 각각 실행한다. 아래 PATH는 원본 format2 스냅샷이며 실제 원본·결과 JSON·덤프는 커밋하지 않는다. 원본과 현재 배치가 다르거나 비위치 값이 달라지면 쓰기를 중단한다.

```powershell
uv run --locked --extra dev python -m etl.localdata.floor_backfill --source general_restaurant --snapshot PATH
uv run --locked --extra dev python -m etl.localdata.floor_backfill --source general_restaurant --snapshot PATH --write --expected-plan DRY_RUN_PLAN_SHA256
```

같은 원본이라도 대상 DB·현재 상태가 달라지면 계획을 새로 계산한다. 복제본의 계획을 실제 DB에 전달하지 않는다. 오류 후에는 새 dry-run으로 상태를 확인하며 자동 전체 덤프 덮어쓰기는 하지 않는다.

### 8.3 실제 개발 DB 적용·API 전후 대조

| 원천 | 전체 검증·새 배치 연결 | NULL 상세 위치 복구 | 그중 지원 업종·검토/삭제 제외 |
|---|---:|---:|---:|
| 일반음식점 | 541,169 | 16,941 | 8,685 |
| 휴게음식점 | 148,271 | 7,797 | 2,783 |
| 합계 | 689,440 | **24,738** | **11,468** |

- 복구는 층만 19,048·호만 2,340·층과 호 3,350행이다. 건물 키 없는 407행은 상세 문자열을 보존하되 신뢰 수준 unverified를 유지했다. `same_spot` 저장 수준은 건물 키와 층·호가 모두 있는 3,269행이며, 실제 이력 비교는 요청 상세까지 일치해야 한다. 복구 24,738행 전체가 API 지원 업종이거나 같은 자리라는 뜻이 아니다.
- 원천별 원자적 커밋을 확인했다. 원천 전체 689,440행의 관리 열(batch_id/updated_at)은 새 normalization-v2 배치로 갱신했다. 원문 hash·원래 recorded_at·D·MAP_VERSION·update_reason과 이전 v1 배치 2개는 보존했으며 현재 활성 배치는 원천별 v2 하나씩이다.
- 두 원천의 보호 SHA-256이 전후 일치했다. 나머지 17개 모델 테이블의 내용/건수, sequence, migration0011, 브랜드 근거와 과거 배치 행도 동일했다. 새 dry-run의 변경 0과 쓰기 재실행 no_op을 모두 확인했다. 기존 로컬 유지보수 명령의 VACUUM(ANALYZE,TRUNCATE FALSE)·provenance 검사도 각 커밋 후 통과했다.
- 양화로45·세종대로110·명동길14 × 카페/한식 6개 흐름에서 주소 검색·이력·주변·시점·월 범위·상권 활동·Risk를 전후 대조했다. 최신 앱 TestClient와 실제 개발 DB를 사용한 공통 흐름 78요청(주소 6·데이터 72)이 모두 200이었다. 비교에는 처음 주소 검색에서 얻은 동일 좌표·건물 키·조건을 고정했다. 위치 필드를 제외한 data hash, as_of·data_updated_at·collected_at=null은 같았다. 새 stores_batch_ids와 실제 risk 캐시 키 변경도 확인했다.
- 추가 복구 표본은 원천별 1곳씩 실제 Kakao 검색의 건물 키·상세 위치·300m 위치 조건을 확인했다. 이력·AI 문맥은 각각 같은 자리 0→1건으로 바뀌고 비위치 이력 hash는 같았다. 주소 2·이력 4·AI 4요청도 모두 200이었다. 합계 TestClient 88요청이며, 앱 LLM 외부 호출은 0이고 모의 공급자 호출은 4회다. Kakao는 실제 외부 조회다.
- 상시 실행 로컬 BE도 최신 파서로 재시작했다. 별도 실제 HTTP 8건(health1·주소3·이력3·월 범위1)이 통과했고, 새 배치가 서비스되는 것을 확인했다. FE 브라우저·출력 진단서 재검증이나 운영 배포 완료를 뜻하지 않는다.
- 원본상 상세가 없거나 모호한 NULL은 그대로다. 다른 팀원의 독립 DB는 자동 보정되지 않으며 갱신 덤프 또는 해당 DB의 원본 검증·별도 실행이 필요하다. 업종 품질·브랜드 목록 확장·첫 조회 성능·배포는 이번 수정에서 해결했다고 표시하지 않는다.

### 8.4 백업·갱신 덤프 검증

- 보정 전 전체 custom-format 백업은 저장소 밖에 보관하고 SHA-256과 복원 가능성을 확인했다. 실제 적용 전에 최종 복제본과 원본 상태 hash가 일치하는지 다시 확인했다.
- 보정 후 공유용 custom-format 덤프를 별도로 생성했다(97,875,348 bytes, SHA-256 `13c9c56d8d7231a26fcbbc3878a74e7e73fa8b062fd81216e8d839424359d87b`). 소유자/ACL을 제외한 이 덤프를 별도 DB에 실제 복원하고 앱 계정의 테이블·sequence 권한을 부여해 검증했다.
- 실제 개발 DB와 복원본의 **19개 모델 테이블 전체 내용 hash/건수·sequence·head0011이 일치**했다. stores 689,440행·배치 4개도 동일했다. 이는 FE 코드·문서 변경이나 다른 팀원 PC의 자동 복원을 의미하지 않는다.
