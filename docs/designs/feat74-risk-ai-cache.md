# BE-34 Risk·AI 메모리 캐시와 버전 무효화 (#74)

- 작성일: 2026-11-12, 기준 develop `542bde7`, 브랜치 feat#74-risk-ai-cache
- 상태: Codex 설계 → Claude 이 MD만 Read/Edit → Codex 최종 결정·구현/검증
- DB 모델/migration·의존성·실제 .env/Docker·FE 저장소는 바꾸지 않는다. 현재 query-only/이력 미지원·공식/조건부 pending·원천/수집일 한계도 유지한다.

## 1. 원본·현재 구조·결정 근거

로컬 원본 API v1.2 §6(12~13쪽)·데이터 활용 v1.2 보관정책(15쪽)을 직접 읽었다. 최대7일, 분석조건/데이터버전·AI의 모델/프롬프트/위치 해시 분리, 원문 building_key/floor_unit 미보관을 확인했다. 현재 Risk는 매번 aggregate SQL, AI는 서버 Risk 재계산→후보 ID 생성→검증/조립이며 캐시가 없다.

배치 ID만으로는 같은 배치의 행 수정·삭제를 감지하지 못하고 stores.updated_at도 모든 SQL 갱신을 강제하지 않는다. 전용 revision 테이블/트리거는 정확하지만 쓰기 경합·migration·DB 권한 범위를 늘린다. 이번에는 **같은 DB 가시성 스냅샷에서만 재사용**하는 보수적인 메모리 캐시를 택한다.

[PostgreSQL17 snapshot 함수](https://www.postgresql.org/docs/17/functions-info.html#FUNCTIONS-PG-SNAPSHOT)·[Repeatable Read](https://www.postgresql.org/docs/17/transaction-iso.html#XACT-REPEATABLE-READ)를 확인했다. 스냅샷은64bit XID의 xmin/xmax/in-progress 집합이고 REPEATABLE READ는 처음 non-control statement의 가시성을 유지한다. 이를 namespace로 쓴다는 것은 캐시 기능에 대한 PostgreSQL 보장이 아니라 이 설계의 추론이다. 일반 MVCC 트랜잭션 변경에서 보이는 행 집합이 다르면 같은 토큰을 재사용하지 않도록 제한하고 격리 테스트로 확인한다. 개발 DB의 실제 READ ONLY REPEATABLE READ 세션4개에서 같은 snapshot을 확인했으나 이것만으로 동시성/운영 hit율을 보장하지 않는다.

## 2. 수명·한도·실패 범위

앱별 CacheResources를 DatabaseResources에1개 생성해 Risk 경로와 AI worker가 공유한다. 프로세스 간/재시작 후 공유하지 않으며 종료 시 cache를 닫고 폐기한다. Redis/파일/DB 캐시 저장·외부 서비스·추가 키는 없다.

- CACHE_ENABLED=true, RISK_CACHE_TTL_SECONDS=300, AI_CACHE_TTL_SECONDS=300. 공유 cache의 타이밍 노출 창을 줄이기 위해 후속 검토 뒤 AI 기본값도5분으로 정했다. TTL은1~604800초(7일)만 허용한다.
- CACHE_MAX_ENTRIES=256, CACHE_MAX_BYTES=4194304를 각 Risk/AI cache에 적용한다. 양쪽 합계 payload 최대8MiB이고 Python 객체/lock/key overhead까지 RSS 상한이라고 주장하지 않는다.
- thread-safe bounded LRU에 immutable bytes만 저장한다. TTL은 삽입 시점의 monotonic 기준이며 hit로 연장하지 않는다. 초과 payload는 저장하지 않고 entry/bytes 한도에서 LRU 축출한다. 출력은 매번 decode·모델 검증·새 객체다. lifespan의1초 sweep으로 유휴 앱도 만료 참조를 정리하며 정지/지연·secure erase의 한계는 §12~14를 따른다.
- in-memory cache/codec/난수 생성 실패는 miss·저장 생략으로 처리한다. 실제 DB 실패·입력/원천 오류·모델 오류는 기존422/500/503을 유지하고 stale 성공으로 대체하지 않는다. 정상 AI hit는 공급자를 호출하거나 현재 공급자 가용성을 확인하지 않는다.
- 정상 hit도 DB 세션/가시성 확인을 거친다. cache가 있어도 DB 장애에서 오프라인 성공을 제공하지 않는다. CACHE_ENABLED=false면 snapshot 쿼리·cache read/write 없이 기존 경로를 쓴다.

## 3. DB 가시성 토큰

Risk/AI 입력 준비에 쓰는 **같은** 세션에서1개의 SELECT로 transaction_read_only/isolation/primary 여부와 current_database/current_user/pg_postmaster_start_time/search_path/pg_current_snapshot::text를 읽는다. READ ONLY·REPEATABLE READ·primary가 아니면 캐시를 우회한다. 데이터 SQL과 snapshot을 다른 connection/transaction에서 읽지 않는다. pg_current_xact_id/txid_current처럼 XID를 새로 배정하는 함수는 호출하지 않는다.

DB/role/서버 시작/search_path/snapshot 지문은 앱 수명의 무작위32byte 비밀키로 HMAC하고 내부 토큰만 사용한다. 평문 DB 정보/트랜잭션 ID/조회조건을 key·로그·응답·repr에 남기지 않는다. 일반 INSERT/UPDATE/DELETE/commit·원천/설정 변경을 새 key로 분리한다. 오래된 read snapshot의 늦은 결과는 별도 key에만 저장되어 새 snapshot의 결과를 덮지 않는다. 이전 entry의 물리 삭제는 TTL/LRU/종료 때이며 새 요청의 논리적 무효화와 구분한다.

무관한 테이블/다른 DB 쓰기·진행/rollback·vacuum 등으로도 miss가 날 수 있다. 낮은 hit율은 성능 한계이지 더 넓은 snapshot을 임의 재사용할 이유가 아니다. 데이터 복구/마이그레이션·임의 DBA 우회·비MVCC 의존성·공급자의 같은 모델명 내부 교체는 자동 감지를 보장하지 않으며 배포/복구 때 앱 재시작·cache 폐기 정책이 필요하다. 현재 SQL은 기준일/값을 DB snapshot으로 계산하며 별도 현재시각/사용자 RLS 의존성을 추가하지 않는다.

## 4. Risk key·저장값·복원

현재 get_risk의 세션/조회조건/설정 인자에 선택적 cache 자원을 더한다. 기존3인자 내부 호출은 cache 없이 동작하게 보존한다. API router는 앱 cache를 전달한다. 성공 응답만 저장하며 hit는 expensive cohort/aggregate/market 계산을 생략한다.

HMAC key는 cache 규칙버전·snapshot 토큰·Risk rule version·선택 경계 UUID·category·반경·정렬된 실효 세부 업종·area/franchise/정규화한 두 unknown flag·선택 include를 포함한다. 좌표는 원본의6자리 값에 **정확한 float.hex guard**를 더한다. 원문 좌표는 key가 만들어지는 동안만 사용하며 key는 digest다. 원본의6자리만 쓴 key와 차이를 문서화한다: 6자리가 같아도 반경 경계의 서로 다른 좌표를 섞지 않기 위한 보완이다.

요청 월은 생략/명시를 보수적으로 별도 구분한다. raw cache lookup 전에 최신D/최소월 집계 SQL을 반복하지 않기 위한 것으로, 값이 같은 생략/명시 월도 별도 miss일 수 있다. 실효T/D·data_version은 해당 snapshot의 검증된 결과에 보존되며 원본의 effective_as_of key보다 좁게 재사용한다. 계산/응답 의미는 바꾸지 않는다.

값은 **data.query 전체를 제외한** Risk 결과·meta·실효T JSON이다. 입력 좌표/주소/건물키/층호/원문query는 값에도 보관하지 않는다. 시장 후보의 공개 기관/코드·provenance·출처는 기존 응답 의미로만 보존한다. hit마다 현재 검증 query의 좌표/필터/표시 순서와 캐시된T로 query echo를 새로 만들고 Risk/ApiResponse 모델을 검증한다. 업종 순서·legacy unknown 표현이 달라도 같은 집합/조건이면 재사용하되 현재 query echo를 반환한다. malformed cache는 폐기 후 새 계산이며 source 실패를 가리지 않는다.

## 5. AI key·값·동시성·예산

prepare_risk_interpretation의 선택적 cache를 통해 같은 worker 세션에서 snapshot을 읽고 Risk cache를 공유한다. PreparedRiskInterpretation에 repr 제외 내부 snapshot_token을 더하되 context_json/prompt/공개 응답에는 넣지 않는다. cache 없는 기존 호출/테스트는 token=None이며 기존 동작이다.

AI key는 snapshot·정규화한 Risk query digest·data_version_hash/context_hash·prompt version/SHA·client provider/model·max_output_tokens·실제 서버 후보 목록/선택 Schema digest를 포함한다. 같은 집계라도 다른 원천 snapshot/정확좌표/선택항목/모델/프롬프트/후보 변경은 재사용하지 않는다. building_key/floor_unit은 여전히422여서 해당 입력 캐시는 만들지 않는다. 현재 모델의 같은 이름 내부 교체는 감지하지 않으며 기본 TTL/재시작 정책과 구분한다.

AI 값은 최종 검증에 성공한 CandidateSelection의 ID 배열·최종 model만 저장한다(§9·§10 후속 검토를 채택). 시각·재생성 이력·프롬프트·입력 context·모델 원문 text·사용량·원문 위치는 저장하지 않는다. hit에도 현재 후보 membership/방향/전체 포함과 최종 서버 문장 검증을 다시 한다. generated_at은 현행 함수대로 **현재 응답의 서버 문장 조립 시각**, regenerated는 **이번 요청의 재생성 여부**이며 hit는false다. 새 공급자 호출/품질 점수라는 뜻이 아니다. 현재 public 응답 필드·meta·NO_STORE는 유지하며 cache key/hit 상세를 공개하지 않는다.

모든 유효 API 요청은 기존5/분·50/일 app limiter를 통과하며 hit도 요청으로 센다. provider 한도는 miss의 실제 호출에서만 소비된다. 키가 비어 기능 미설정인 경우는 cache로 숨기지 않으며 정상 경로의503을 유지한다. 테스트의 custom client는 명시한 합성 키로 캐시를 검증한다.

기존 동시2 semaphore·전체20초 예산 안에서 준비→후보→AI key를 만들고 **동일 key의 모델 호출만 single-flight lock**으로 합친다. semaphore는 준비/공급자 실행 구간에 각각 적용하고 key 대기 중에는 점유하지 않아 다른 key를 막지 않는다. 대기자는 lock 후 다시 cache를 확인한다. lock의 owner/waiter 참조를 finally 줄여0이면 제거하므로 유니크 key가 무한 축적되지 않는다. 취소/실패/예산 초과는 lock/gate를 정리한다. 실패는 저장/공유하지 않고 대기자는 남은 예산이1초 이상일 때 기존 생성/검증 재생성 규칙으로 새 시도를 허용한다. Risk 동시 cold miss의 SQL은 합치지 않아 DB 대기 lock/새 시간제한을 만들지 않는다.

## 6. 구현·검증 범위

core/cache.py(범용 bytes LRU/TTL·HMAC 자원), services/risk_cache.py(snapshot/codec/key), config/db resource/main 종료, Risk router/service, AI context/interpret 서비스·기존 render 의미 유지, 관련 테스트·BE 문서/기존 FE AI 요청서 안내를 다룬다. API schema/DB 모델/migration·의존성·실제 .env/Docker·FE 저장소는 바꾸지 않는다.

단위: TTL 경계/LRU/bytes/oversize/종료/비활성/난수·cache 오류 우회, key 필터/6자리 경계 exact guard/순서 정규화·원문/repr 비노출·값 복사/손상 복구, AI snapshot/데이터/프롬프트/모델/후보 분리·현재 문장 조립시각·현재 요청 기준0/1회 재생성/오류 미저장·hit limiter·동시 miss1회/대기자·owner 취소/20초/lock 정리·기존 API/프롬프트·운영 로그 회귀.

격리 PostGIS: 실제 READ ONLY REPEATABLE READ snapshot hit·SQL 생략, 동일 배치/updated_at 변경 없는 UPDATE·INSERT/DELETE·원천meta 변경·진행/commit/rollback의 무효화, 늦은 옛 snapshot과 새 snapshot 격리, READ COMMITTED/read-write 우회·DB/source 오류는 캐시로 숨기지 않음, 같은6자리 좌표지만 반경 경계가 다른 실제 결과, 실제 서버 재계산+mock transport의 AI hit/miss·세션 정리. 개발 DB는 읽기만 하며 warm/cold·cache stats/모의 공급자 호출 수·14테이블 hash/head0009/모델차이를 확인한다. 실제 모델 호출은 필요하지 않으며 하지 않는다.

전체 일반/격리PostGIS·ruff/format/mypy·실제 .env 비밀값 검사·FE 변경0·지정PR·CI/CodeQL 후 develop 일반 Squash 병합한다. 기존 BE의 FE 보고서는 HTTP no-store/서버 내부cache·현재 조립시각/요청별 재생성 안내만 갱신하며 FE 코드는 바꾸지 않는다. 분산cache/전체 의미 검증·운영 hit율/SLA는 완료로 주장하지 않는다.

## 7. Claude 검토 요청

이 MD만 Read/Edit한다. 코드/다른문서/Git/DB/.env/네트워크 금지. 원본/실제 코드·공식문서/실측을 읽지 않은 한계를 명시하고 snapshot namespace의 정확성/가정·대안 revision 트리거·키 충돌/개인정보·bounded TTL/복원·AI 동시성/취소/한도·원래 시각·오류 경계·테스트 누락을 검토해 §8에 직접 기록한다. 본문 수정은 근거와 함께 이 파일에만 한다. Codex가 실제 코드/공식 자료·격리 테스트와 최종 대조한다.

## 8. Claude 검토 결과 (2026-11-12)

### 8.0 검토 범위·한계

- 이 MD만 읽고 §8만 추가했다. §1~§7 본문은 수정하지 않았다. 아래 제안 중 무엇을 본문에 반영할지는 Codex가 결정한다.
- 원본 API/데이터 활용 v1.2 PDF, 실제 코드(get_risk, prepare_risk_interpretation, 세션/트랜잭션 설정, ETL 적재 방식, 운영 로그 저장 위치, limiter 범위), PostgreSQL 17 공식 문서, 개발 DB 실측은 **읽거나 실행하지 않았다**. 아래의 PostgreSQL 동작(TRUNCATE의 MVCC 비안전성, 트랜잭션 abort 의미, now()의 시점 등)은 일반 지식에 근거하므로 PG17 문서와 격리 테스트로 확인해야 한다.
- 심각도: **[높음]** 구현 전 결정 필요, **[중간]** 구현 시 반영 권장, **[낮음]** 문서화·선택.

### 8.1 snapshot namespace의 정확성·가정

1. **[높음] 비MVCC 연산으로 같은 토큰이 다른 결과를 낼 수 있음.** 같은 snapshot 텍스트(xmin:xmax:xip)는 일반 heap 행 가시성이 같다는 뜻일 뿐이다. `TRUNCATE`는 MVCC-safe가 아니어서 이미 존재하는 이전 snapshot에서 truncate commit 후 테이블이 비어 보일 수 있다. 테이블을 재작성하는 일부 DDL(`ALTER TABLE` rewrite, `CLUSTER`, `VACUUM FULL`)과 비동시 `REFRESH MATERIALIZED VIEW`도 비슷한 위험이 있는지 PG17 문서로 확인해야 한다. 새 snapshot은 새 토큰을 받으므로 대부분 안전하지만 "같은 토큰 = 같은 결과" 불변식은 깨질 수 있다. **ETL이 TRUNCATE+COPY/교체 방식으로 적재하는지 실제 코드를 확인**하고, 그렇다면 (a) ETL을 DELETE/INSERT로 바꾸거나 (b) ETL 완료 후 앱 cache를 폐기하는 절차를 §3에 명시하거나 (c) §8.2의 revision을 병행한다. §3의 "비MVCC 의존성"에 TRUNCATE를 명시적으로 넣는 것을 권장한다.
2. **[높음] 현재시각·세션 GUC 의존성 재확인.** 쓰기가 없는 유휴 클러스터에서는 같은 snapshot이 몇 시간 동안 유지될 수 있다. SQL 어디서든 `now()/CURRENT_DATE/current_timestamp`를 쓰면 같은 토큰에서도 결과가 바뀐다. §3은 의존성이 없다고 쓰지만 실제 SQL(Risk aggregate, market, 최신D/최소월 계산)에서 grep으로 검증해야 한다. `TimeZone`(timestamptz→date 변환), `DateStyle`, `extra_float_digits`처럼 결과에 영향을 주는 세션 GUC는 지문에 넣거나 앱에서 고정된 값임을 확인한다. Python 쪽 `date.today()`가 Risk 결과(예: 기준월 기본값)에 쓰이면 key에도 들어가야 한다.
3. **[높음] 세션이 실제로 READ ONLY REPEATABLE READ인지 확인.** §3은 이 조건이 아니면 우회한다고 했다. 현재 Risk/AI 세션의 기본 격리수준이 READ COMMITTED라면 hit율이 항상 0이 된다. 이 기능을 쓰려면 세션 시작 시 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`(또는 SQLAlchemy execution_options)를 설정하는 변경이 함께 들어가야 하며 §6 범위에 명시해야 한다. 격리수준을 바꾸면 기존 다중 statement 읽기의 일관성 의미도 바뀐다(개선이지만 회귀 테스트 대상). 읽기 전용 RR은 직렬화 실패가 없다는 점도 함께 확인한다.
4. **[높음] snapshot SELECT 실패는 단순 "miss 처리"로 끝나지 않음.** PostgreSQL에서 트랜잭션 안의 statement가 실패하면 트랜잭션 전체가 aborted 상태가 되어 이후 데이터 SQL도 실패한다. §2의 "cache 실패→miss"를 snapshot SQL에 적용하려면 SAVEPOINT로 감싸거나, snapshot SQL 실패를 DB 오류(기존 500/503)로 분류해야 한다. 권한 문제(일부 관리형 DB에서 `pg_postmaster_start_time` 등)도 포함하여 둘 중 하나로 명시할 것을 권장한다. 개인적으로는 "DB 오류로 분류"가 단순하다. 같은 DB의 같은 함수이므로 실패하면 데이터 SQL도 사실상 실패할 가능성이 높다.
5. **[중간] snapshot은 첫 statement에서 고정된다.** RR에서는 첫 non-control statement가 snapshot을 정하므로 snapshot SELECT가 데이터 SQL보다 먼저든 나중이든 같은 트랜잭션이면 동일하다. 단 commit/rollback으로 트랜잭션이 끝난 뒤 같은 Session에서 다시 읽으면 새 트랜잭션이 된다. 준비 함수 중간에 commit하는 코드가 없는지(autocommit, `session.commit()`, `expire_on_commit` 재로드) 확인한다.
6. **[중간] hit율 사전 측정 권장.** XID는 클러스터 전역이라 같은 클러스터의 다른 DB나 다른 앱의 쓰기, ANALYZE 같은 XID 할당 작업만 있어도 토큰이 바뀐다. 특히 **API·ETL 운영 로그(기준 커밋 542bde7)나 다른 요청 단위 기록이 같은 클러스터에 INSERT되면 거의 모든 요청이 miss**가 될 수 있다. 구현 전 운영과 비슷한 환경에서 5~10분간 `pg_current_snapshot()`을 주기적으로 샘플링해 동일 토큰 지속 시간을 측정하고, 측정 결과가 나쁘면 §8.2 대안으로 바꾸는 판단 기준을 남기기를 권장한다.
7. **[낮음] 지문 구성은 대체로 타당하다.** 시작 시각으로 재시작·PITR 복구·failover를 분리하고, 데이터베이스와 role로 다른 DB와 RLS 가능성을 분리한다. `pg_is_in_recovery()`로 standby를 우회하는 것도 맞다. 다만 같은 시작 시각을 가진 서로 다른 클러스터는 사실상 불가능하므로 추가 식별자(`system_identifier`, `pg_control_system()`)는 선택 사항이다.

### 8.2 대안 revision 트리거 비교

- **statement-level 트리거 + 단일 revision 행:** row-level이 아닌 `FOR EACH STATEMENT`(INSERT/UPDATE/DELETE/**TRUNCATE** 포함)로 대상 약 14개 테이블에서 revision 1행을 증가시키면 ETL 대량 적재에서도 statement당 1회만 쓰여 경합이 작다. TRUNCATE도 감지하므로 §8.1-1을 해결하고, 무관한 쓰기로 인한 miss가 없어 hit율이 높다. 단점은 migration·트리거 권한·DDL 미감지·트리거 누락 테이블 위험이다.
- **ETL 완료 시 data_version 기록(애플리케이션 규약):** 가장 단순하지만 수동 SQL 수정은 감지하지 못한다.
- 권장: 이번 범위(migration 금지)에서는 snapshot 방식을 유지하되 §8.1-1, §8.1-6의 결과에 따라 후속 이슈로 statement-level 트리거를 검토한다는 **전환 조건**을 §1이나 §6에 기록한다.

### 8.3 key 충돌·개인정보

1. **[중간] 정규 인코딩.** key 입력 결합은 구분자 연결이 아니라 길이 접두나 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` 같은 정규 직렬화로 해야 필드 경계 모호성에 의한 충돌이 없다. HMAC-SHA256 출력은 절단하지 않고 32byte 전체를 쓴다. Risk와 AI는 별도 cache지만 key 입력에 `"risk"/"ai"` 도메인 태그를 넣으면 안전하다.
2. **[낮음] float 정규화.** `float.hex`에서 `-0.0`과 `0.0`은 다르다. 잘못된 결과가 아니라 불필요한 miss일 뿐이다. NaN/inf는 key 생성 전 입력 검증에서 거부되는지 확인한다. 정확한 hex를 넣으면 6자리 값은 사실상 중복이지만, 문서상 원본 규칙과의 대응을 위해 유지해도 무방하다.
3. **[높음] 사용자 간 정보 노출(타이밍과 generated_at).** cache는 모든 사용자가 공유한다. 좌표가 주소 지오코딩으로 결정적으로 정해지면 공격자가 특정 주소와 조건으로 요청해 (a) 응답 지연(hit/miss)이나 (b) **AI 응답의 원래 generated_at**을 보고 "최근 5분/1시간 안에 누군가 이 위치를 조회했는지와 그 시각"을 알 수 있다. 특히 (b)는 명시적인 응답 필드라 타이밍보다 확실하다. 대응안: ① 위험을 수용하고 문서화(익명 서비스이고 TTL이 짧음), ② generated_at을 분이나 시 단위로 거칠게 만들기, ③ 사용자/세션 단위 partition(인증이 없으면 불가). 최소한 §5에 이 노출과 결정을 기록할 것을 권장한다.
4. **[낮음] 메모리 덤프.** 프로세스 메모리에 HMAC 키와 key가 함께 있으므로 덤프가 유출되면 좌표 격자를 대입해 조회 위치를 역추정할 수 있다(비용은 크지만 불가능하지 않음). HMAC은 메모리 유출 상황의 익명화가 아니라는 점과, Risk 결과 자체(주변 후보 시장)가 대략적인 위치를 시사한다는 점을 개인정보 한계로 적는다. cache stats와 로그에는 key 접두도 남기지 않는다.

### 8.4 bounded TTL·복원

1. **[중간] miss와 hit의 동등성.** codec 왕복(Decimal 정밀도, float 표현, timezone-aware datetime, Enum, None과 누락 필드 구분)으로 응답이 미세하게 달라질 수 있다. "같은 입력에서 miss 응답 JSON == hit 응답 JSON(허용된 필드 제외)" golden 테스트를 필수로 넣는다.
2. **[중간] 요청 단위 필드 제외.** Risk meta에 request_id, trace, 응답시각, 처리시간 같은 요청별 값이 있으면 저장하지 말고 hit마다 새로 만들어야 한다. Risk meta에 계산시각이 있다면 AI처럼 원래 시각을 유지할지 결정해 명시한다(현재 §4에는 없음).
3. **[낮음] 설정 검증.** TTL 1~604800 외에 MAX_ENTRIES/MAX_BYTES의 최소값(≥1), 정수가 아닌 값, 하나의 entry가 MAX_BYTES보다 큰 경우의 동작을 config 단계에서 검증하고 테스트한다. TTL은 시계를 주입할 수 있게 만들어 경계(정확히 만료 시점)를 결정적으로 테스트한다.
4. **[낮음] 멀티 워커 메모리.** uvicorn/gunicorn 워커가 N개이면 cache도 N개이고 payload 상한은 8MiB×N이 된다. hit율도 워커 분산만큼 낮아진다. §2에 기재할 것을 권장한다.
5. **[낮음] lock 범위.** threading.Lock 안에서는 dict/LRU 조작만 하고 encode/decode/모델 검증은 lock 밖에서 한다. async 경로에서는 threading.Lock을 잡은 채 await하지 않는다.

### 8.5 AI 동시성·취소·한도

1. **[높음] provider 호출 중 DB 트랜잭션 유지 여부.** AI key를 만들려면 snapshot이 필요하지만, provider 호출(최대 20초) 동안 RR 트랜잭션이나 connection을 유지하면 xmin horizon이 묶여 vacuum 정리를 막고 pool을 점유한다. 준비, 후보 생성, key 계산 후 **DB 세션을 닫고** provider를 호출하는 순서를 명시하고 테스트한다. 저장 key는 입력 snapshot 기준이므로 늦게 저장해도 §3의 격리 의미가 유지된다.
2. **[중간] 대기자가 gate 슬롯을 점유하는 문제.** 동시 2 semaphore 안에서 single-flight를 기다리면 같은 key의 대기자가 슬롯 하나를 차지해 다른 key의 처리량이 절반이 된다. 대기는 gate 밖에서 하고 owner만 gate를 얻거나, 대기자도 남은 20초 예산을 기준으로 timeout하도록 순서를 명시한다.
3. **[중간] owner 실패 시 대기자 동작.** "실패는 공유하지 않는다"를 문자 그대로 적용하면 대기자가 차례로 새 owner가 되어 provider를 반복 호출하고 각자 예산을 소진할 수 있다. 권장: 대기자는 owner 실패 후 남은 예산이 충분할 때만 1회 재시도하고, 부족하면 기존 503/504를 반환한다. 이 규칙을 테스트로 고정한다.
4. **[중간] lock 참조 카운트 정확성.** 카운트 증감과 dict 등록·삭제 사이에 await가 없어야 하며(이벤트 루프 단일 스레드 가정), acquire 중 CancelledError가 나도 finally에서 감소해야 한다. AI worker가 스레드 기반이면 asyncio.Lock 대신 threading 기반으로 바꾸고 이벤트 루프 간 공유를 피해야 한다. 실제 실행 모델을 코드로 확인한다.
5. **[낮음] single-flight의 실익.** limiter가 앱 전체 5/분이고 동시성이 2라면 같은 key의 동시 miss는 드물다. 복잡도 대비 이득이 작으므로, 구현 위험이 크면 생략하는 것도 선택지다(중복 호출 최대 2회).
6. **[낮음] limiter.** hit도 요청으로 세는 것은 타당하다. hit/miss에 따른 429 차이가 없어 cache 상태가 limiter로 노출되지 않는다. limiter가 앱 전체인지 IP 단위인지는 실제 코드로 확인한다.

### 8.6 원래 생성시각

- 원래 generated_at, model, regenerated를 유지하는 것은 정직한 표현이므로 동의한다. 다만 §8.3-3의 노출을 고려해야 한다. 렌더된 문장이나 meta에 "오늘/기준일"이 hit 시점으로 다시 계산되는 곳이 없는지(render 생성시각 변경 범위) 확인하고, generated_at과 TTL을 합쳐도 원본 보관정책 7일을 넘지 않음을 테스트한다. 기본 1시간이면 문제없다.

### 8.7 오류 경계

- §8.1-4(snapshot SQL 실패 시 트랜잭션 abort) 외에는 타당하다. 추가로 다음을 명시할 것을 권장한다.
  - hit의 decode나 모델 검증이 실패하면 해당 entry를 삭제하고 **같은 요청 안에서** 새 계산으로 넘어간다. 이때 이미 연 세션과 snapshot을 그대로 재사용해도 된다.
  - 종료(close) 이후 늦게 끝난 저장 시도는 조용히 무시한다.
  - 응답 시 "cache 저장 실패"를 사용자 오류로 만들지 않는다.

### 8.8 테스트 누락 제안 (§6 보강)

1. TRUNCATE(그리고 ETL 실제 적재 방식)와 기존 snapshot 결과의 관계를 격리 PostGIS에서 확인한다(§8.1-1).
2. SQL과 Python에서 현재시각·TimeZone 의존성이 없음을 확인한다. 같은 snapshot에서 TimeZone GUC를 바꾸는 테스트도 넣는다(§8.1-2).
3. 실제 앱 세션 설정에서 RR READ ONLY가 적용되어 hit가 발생하는 end-to-end 테스트를 넣는다(§8.1-3).
4. snapshot SQL 강제 실패 시 데이터 SQL과 응답 코드가 어떻게 되는지 확인한다(§8.1-4).
5. miss와 hit의 응답 JSON 동등성 golden 테스트를 넣는다(§8.4-1).
6. provider 호출 중 DB connection이 반납되었는지(pool checked-out 수) 확인한다(§8.5-1).
7. owner 실패와 예산 부족 상황에서 대기자의 provider 호출 횟수 상한을 확인한다(§8.5-3).
8. gate 슬롯 점유 상황에서 다른 key의 처리를 확인한다(§8.5-2).
9. 잘못된 설정값(0, 음수, 상한 초과, 비정수)을 검증한다(§8.4-3).
10. 로그, cache stats, repr, 예외 메시지에 좌표, key 접두, snapshot 문자열이 없는지 확인한다.
11. API·ETL 운영 로그의 DB 쓰기 여부와 그로 인한 hit율 측정 결과를 기록한다(§8.1-6).

### 8.9 결론

전체 방향(메모리 전용, HMAC key, 원문 비보관, 성공만 저장, hit에서도 재검증, 오류를 stale로 숨기지 않음)은 타당하다. 구현 전에 결정이 필요한 항목은 **§8.1-1 TRUNCATE/ETL, §8.1-2 현재시각 의존성, §8.1-3 RR 세션 적용, §8.1-4 snapshot SQL 실패 분류, §8.3-3 generated_at/타이밍 노출, §8.5-1 provider 호출 중 DB 세션 유지** 6가지다. 나머지는 구현과 테스트 단계에서 반영하면 된다.

## 9. 추가 검토안: 원래 호출 시각을 공유하지 않는 selection 캐시

Codex가 실제 코드를 확인했다. 현재 render_interpretation은 공급자가 반환한 생성시각이 아니라 **서버가 문장을 조립하는 순간 datetime.now(UTC)**를 generated_at으로 넣는다. FE 요청서도 "서버 UTC 생성시각"이라고 설명한다. 현재 verification.regenerated는 해당 요청에서 generate_verified가2번 생성했는지다. 따라서 처음 §5의 과거 timestamp/재생성 metadata까지 공유하는 안을 다음으로 수정하려 한다.

- AI 캐시에는 검증된 후보ID 배열·실제 model만 저장하고 원래 생성시각/원래 regenerated·사용자/요청ID는 보관하지 않는다.
- hit에도 서버가 현재 snapshot의 context/후보로 응답을 새로 조립한다. generated_at은 현행 함수대로 **이 응답의 서버 문장 조립 시각**이며 공급자 요청시각/새 LLM호출 보장이 아니다. 이 의미를 BE·기존 FE 요청서에 분명히 적는다. API 필드/타입은 바꾸지 않는다.
- regenerated는 **이번 요청의** 재생성 여부로 유지한다. hit는 새 공급자 호출/재생성이 없어서false이고, miss는 현재 generated.generations>1이다. 과거 요청의 검증 이력을 재사용하지 않는다.
- cache hit 여부/원래 요청 시간·snapshot/key는 공개하지 않는다. 이에 따라 캐시가 다른 사용자의 정확한 요청시각을 직접 반환하는 경로를 제거한다. 공유 cache의 타이밍/동일 선택 반복에 의한 통계적 추론까지 완전히 막지는 못하며, HMAC도 메모리 덤프 유출 시 익명화를 보장하지 않는다. 완전한 사용자별 partition/고정시간 응답은 인증/세션·성능 계약이 필요한 별도 범위다.

현재 ETL은 INSERT/UPSERT/DELETE 기반이며 runtime Risk SQL/Python에 현재시각 기준일 의존성은 없다. snapshot guard는 실제 READ ONLY REPEATABLE READ를 확인하고 TimeZone/DateStyle/extra_float_digits도 포함한다. snapshot SQL 오류는 aborted transaction을 감추는 miss가 아니라 기존 DB500이다. provider 시작 전 세션 종료는 기존 _prepare 구조를 보존한다. TRUNCATE/테이블 rewrite/복구는 동시 runtime 지원 범위에서 제외하고 요청 drain→cache 폐기→변경→앱 재시작 정책을 명시하며, 격리 테스트에서는 명시적 폐기 뒤 새 조회를 확인한다.

Claude 추가 요청: 이 MD만 Read/Edit로 §9 수정안의 정직성/생성시각·재생성 필드 계약/직접 시각 노출 완화와 잔여 한계를 검토해 §10에 기록한다. 다른 파일/코드/원본/네트워크는 읽지 않는다. 실제 코드 확인은 위 Codex 설명을 전제로 하며 코드를 읽은 것으로 표시하지 않는다.

## 10. Claude 후속 검토 결과: §9 수정안 (2026-11-12)

### 10.0 범위·한계

- 이 MD만 읽고 §10만 추가했다. §1~§9 본문은 수정하지 않았다.
- render_interpretation의 `datetime.now(UTC)`, regenerated의 의미(generations>1), ETL의 INSERT/UPSERT/DELETE 방식, 현재시각 의존성이 없다는 점, `_prepare`의 세션 종료 순서, snapshot SQL 오류를 500으로 처리하는 방식은 모두 **§9에 적힌 Codex의 설명을 전제로 했다.** 실제 코드, FE 요청서, 원본 PDF, PostgreSQL 문서는 읽지 않았고 실행이나 측정도 하지 않았다. 아래 판단은 그 전제가 맞을 때만 성립한다.

### 10.1 정직성·생성시각 계약

1. **[동의] 원래 시각을 저장하지 않는 쪽이 §5 원안보다 낫다.** 현행 generated_at이 "공급자 생성시각"이 아니라 "서버가 문장을 조립한 시각"이라면, hit에서도 지금 조립하므로 같은 의미를 유지한다. 원안(과거 시각 재사용)은 현행 필드 의미와 오히려 어긋났고 §8.3-3의 직접 노출 경로도 만들었다. §9 수정안은 기존 계약과 맞고 노출 경로도 없앤다.
2. **[중간] 필드 이름이 주는 인상과 실제 의미가 다르다.** 소비자는 `generated_at`을 "AI가 이 해석을 만든 시각"으로 읽기 쉽다. hit에서는 LLM 선택이 최대 TTL(기본 1시간) 전에 이루어졌을 수 있다. API 필드를 바꾸지 않는 결정은 유지하되, BE 문서와 FE 요청서에 다음을 그대로 적을 것을 권장한다. "generated_at은 이 응답의 서버 문장 조립 시각이다. 모델의 후보 선택은 이보다 이전(최대 AI_CACHE_TTL_SECONDS)에 이루어졌을 수 있다. 새 공급자 호출을 의미하지 않는다." 화면 문구에 "방금 AI가 분석" 같은 표현을 쓰지 않도록 FE 안내에도 넣는다.
3. **[중간] model 필드의 의미.** hit에서 저장된 model을 반환하는 것은 정직하다(그 모델이 선택을 만들었으므로). key에 provider/model이 들어가 있으므로 설정이 바뀌면 다른 key가 된다. 다만 공급자가 같은 이름의 모델을 내부에서 교체한 경우는 §5에서 이미 한계로 적었고, 그 외에 추가 문제는 없다.
4. **[낮음] 근거 데이터는 현재 snapshot 기준이다.** hit도 현재 snapshot의 context와 후보로 조립하고 key에 snapshot이 포함되므로, 문장 속 수치는 조립 시점의 데이터와 일치한다. "선택은 과거, 수치는 현재"라는 어긋남은 key 설계상 생기지 않는다. 이 점은 §9 설명의 정직성을 뒷받침한다.

### 10.2 regenerated 필드 계약

1. **[동의] "이번 요청의 재생성 여부"로 정의하는 것은 일관된다.** hit=false, miss=generations>1로 하면 과거 요청의 검증 이력을 다른 사용자에게 넘기지 않는다.
2. **[중간] 품질 신호로 오해할 수 있다.** 처음 생성 때 1차 검증에 실패하고 재생성으로 통과한 선택이 hit에서는 `regenerated=false`로 나간다. 소비자가 이 값을 "첫 시도에 통과한 깨끗한 결과"로 해석하면 오해가 된다. 문서에 "regenerated는 이번 요청에서 공급자 재호출이 있었는지만 나타내며, 결과 품질이나 이력을 나타내지 않는다"라고 명시할 것을 권장한다.
3. **[중간] hit 재검증 실패 시 경로를 명시해야 한다.** §5는 hit에서도 membership/방향/문장 검증을 다시 한다고 했다. key에 후보 목록과 Schema digest가 있으므로 이론상 실패하면 안 되지만, 검증 규칙 코드가 key에 반영되지 않은 채 바뀌었거나 entry가 손상되면 실패할 수 있다. 권장 규칙: entry 삭제 → 같은 요청 안에서 miss 경로로 진행 → regenerated는 그 miss 경로의 generations로 계산 → hit 실패 자체는 재생성 횟수에 포함하지 않는다. 이를 보장하려면 **검증 규칙 버전(또는 prompt/validator 버전)을 AI key에 포함**하는 것이 안전하다. 이때 miss 경로로 넘어가면 공급자 호출 예산(20초, 동시2)을 그 시점부터 소비한다는 점도 테스트한다.
4. **[낮음] 기타 verification 필드.** verification에 regenerated 외의 필드(검증 통과 항목, 시도 횟수 등)가 있다면 모두 "이번 요청 기준"인지 확인해야 한다. 이번 검토에서는 필드 목록을 보지 못했다.

### 10.3 직접 시각 노출 완화와 잔여 한계

1. **[동의] 직접 노출 경로는 제거된다.** 저장 payload가 후보 ID 배열과 model뿐이면 응답 필드로 다른 사용자의 요청시각을 돌려줄 방법이 없다.
2. **[높음, 잔여] 타이밍 노출은 원안보다 오히려 더 두드러진다.** AI miss는 공급자 호출로 수 초가 걸리고 hit는 DB 준비와 조립만 하므로 지연 차이가 매우 크다. 정확한 좌표와 조건을 재현할 수 있는 공격자(주소 지오코딩이 결정적이면 가능)는 1회 요청으로 "최근 AI_CACHE_TTL_SECONDS 안에 누군가 같은 조건을 조회했는지"를 높은 확률로 알 수 있다. 시각은 알 수 없지만 존재 여부는 알 수 있다. §9는 이를 "통계적 추론"으로 표현했지만 실제로는 단일 관측으로도 거의 확실한 신호가 될 수 있으므로 표현을 더 정확히 적을 것을 권장한다. 선택지는 다음과 같다.
   - ① 위험 수용과 문서화: 익명 서비스이고 공개 상권 분석이며 조건 재현이 필요하다는 근거를 기록한다.
   - ② AI_CACHE_TTL 단축: 노출 창을 줄이는 대신 hit율이 낮아진다.
   - ③ hit 최소 응답시간 패딩: 노출은 줄지만 gate 슬롯과 worker를 점유하고 캐시의 지연 이점이 사라진다. 비용 절감(공급자 호출 감소) 목적이라면 여전히 의미는 있다.
   - 권장은 ①과 함께 TTL 기본값을 근거와 함께 재확인하는 것이다. 결정은 Codex와 사용자가 한다.
3. **[중간] 부수 채널 확인.** 응답 헤더(`Server-Timing`, `X-Cache`, `Age`, ETag), 오류 메시지, 운영 로그 API(542bde7)에서 cache hit 여부나 처리시간이 외부로 보이지 않는지 확인한다. 내부 운영 로그에 hit/miss와 지연을 남기는 것은 괜찮지만 좌표나 key 접두는 남기지 않는다(§8.3-4).
4. **[낮음] Risk cache 타이밍.** Risk hit/miss의 차이는 SQL 비용 정도라 AI보다 작지만 같은 종류의 존재 신호다. TTL 300초로 창이 짧다는 점을 같은 결정 항목에 넣는다.
5. **[낮음] limiter 상호작용.** hit도 요청으로 세므로 공격자의 반복 탐지도 5/분·50/일로 제한된다. limiter가 앱 전체 단위라면 공격자가 정상 사용자의 한도를 소진시키는 문제가 있지만 이는 캐시와 무관한 기존 한계다.

### 10.4 §9 둘째 문단(ETL·세션·운영 정책)

- INSERT/UPSERT/DELETE 기반 ETL, 현재시각 비의존, TimeZone/DateStyle/extra_float_digits 지문 포함, snapshot SQL 오류의 500 처리, provider 호출 전 세션 종료는 §8.1-1~4와 §8.5-1의 지적을 해소한다(Codex 설명이 맞다는 전제).
- **[중간]** "요청 drain→cache 폐기→변경→앱 재시작" 정책은 운영 절차에 의존한다. alembic migration이나 수동 TRUNCATE/복구가 배포 절차 밖에서 일어나면 감지하지 못한다는 점을 §3 한계에 그대로 남겨야 한다. 앱 재시작으로 cache가 사라지므로 실무에서는 "변경 후 반드시 재시작" 한 줄 규칙으로 충분하다.
- **[낮음]** ETL이 UPSERT를 쓸 때 `ON CONFLICT DO UPDATE`는 MVCC 행 버전을 만들므로 snapshot 변경으로 감지된다. 값이 같은 no-op UPDATE도 새 XID를 받아 무효화되며(불필요한 miss), 정확성 문제는 없다.

### 10.5 문서 정합성

- **[중간] §5 셋째 문단과 §8.6이 §9와 충돌한다.** §5는 "원래 generated_at·regenerated metadata 저장, hit 시 today/now로 바꾸지 않음"이라고 하고, §8.6은 그 안에 동의했다. §9를 채택한다면 §5 본문을 §9 내용으로 고치거나 "§9로 대체됨"을 표시해야 구현자가 혼동하지 않는다. 이번 요청 범위상 §5는 직접 수정하지 않았다.
- §6 단위 테스트 목록의 "원래 생성시각"도 "hit generated_at=현재 조립 시각, regenerated=false"로 바뀌어야 한다.

### 10.6 테스트 보강 제안

1. 저장 payload를 decode해 후보 ID 배열과 model 외의 필드(generated_at, regenerated, 요청ID, 사용자 정보, 프롬프트, 모델 원문)가 없는지 확인한다.
2. hit 응답의 generated_at이 요청 시작과 종료 사이에 있고 miss 때의 시각과 다른지 확인한다(시계 주입).
3. miss에서 재생성(generations=2)으로 저장된 선택이 hit에서 regenerated=false로 나가는지 확인한다.
4. hit 재검증 실패 시 entry 삭제, 같은 요청 안의 miss 전환, 공급자 호출 1회, regenerated 계산, 예산 소비를 확인한다(§10.2-3).
5. 응답 헤더와 공개 오류에 cache 상태나 처리시간이 노출되지 않는지 확인한다(§10.3-3).
6. miss와 hit 응답 JSON이 generated_at·regenerated를 제외하고 같은지 golden 테스트로 확인한다(§8.4-1과 통합).

### 10.7 결론

§9 수정안은 기존 필드 의미와 맞고, 다른 사용자의 요청시각이 응답 필드로 직접 나가는 경로를 없애므로 §5 원안보다 정직하고 안전하다. **채택을 권장한다.** 남은 결정 항목은 (1) hit/miss 지연 차이에 의한 존재 노출을 수용할지와 TTL 기본값(§10.3-2), (2) 검증 규칙 버전을 AI key에 넣을지와 hit 재검증 실패 경로(§10.2-3), (3) §5·§6 본문을 §9에 맞게 고치는 것(§10.5)이다. generated_at과 regenerated의 의미는 BE와 FE 문서에 §10.1-2, §10.2-2의 문구로 명시한다.

## 11. Codex 최종 결정

두 번의 Claude 실제 MD diff와 JSON(첫5turns/후속3turns·is_error=false·permission_denials=[])을 읽었다. §9·§10의 selection-only 캐시를 채택하고 §5·§6을 갱신했다. generated_at은 현재 서버 문장 조립 시각, regenerated는 현재 요청 기준(hit=false)이며 과거 사용자 시각/이력은 보관하지 않는다. 공유 cache의 hit/miss 지연 차이로 같은 조건의 최근 조회 존재를 추론할 수 있는 한계는 수용·명시하고 AI 기본 TTL을3600→300초로 줄였다. 무인증 공개 분석·앱 요청 한도를 고려한 기본이며 완전 익명성/타이밍 보호를 주장하지 않는다. 운영 정책으로 더 높은 격리가 필요하면 세션 partition/응답시간 정책을 별도 설계한다.

실제 ETL은 INSERT/UPSERT이며 Risk/market/cohort/spatial 코드에 NOW/CURRENT_DATE/date.today나 중간 commit/rollback 의존성은 없다. READ ONLY REPEATABLE READ는 이미 기존 세션에 적용되어 의미를 바꾸지 않는다. snapshot SQL은 DB 작업이므로 실패하면500이며 임의 catch→동일 aborted transaction 재사용은 하지 않는다. TimeZone/DateStyle/extra_float_digits 지문도 포함한다. 한 guard 호출은1 SQL이며 AI 준비의 token 취득과 Risk cache 조회가 같은 세션에서 각각 호출되어 최대2 metadata SQL을 쓴다. 세션 상태 memoization의 숨은 전제를 늘리는 미세 최적화는 보류한다.

비MVCC TRUNCATE/rewrite/복구는 지원되는 동시 runtime 갱신이 아니다. 실제 ETL에는 없음을 확인했고 운영 요청 drain·cache 폐기·변경·재시작 정책과 격리 검증으로 경계를 남긴다. 일반 DML commit/rollback·진행 writer·옛 snapshot/새 snapshot은 실제 PostGIS에서 별도 확인한다. hit율이 낮아 실제 공급자 호출 절감이 안 되거나 TRUNCATE/다중 writer 운영 요구가 생기면 별도 revision 트리거 설계로 전환한다. 기본 운영 로그는 stderr만 쓰므로 조회마다 DB XID를 만들지 않는다.

provider 전에 DB 세션을 닫는 기존 _prepare 구조를 유지하고, 동일 key 대기는 semaphore 밖에서 한다. 입출력/캐시 decode/ID membership 실패는 entry 폐기 후 같은 요청의 miss로 가지만 서버 템플릿 문장 검증 실패는 기존500이며 공급자 재호출로 숨기지 않는다. AI key에 cache/검증 규칙 버전·후보/Schema·prompt 지문을 넣는다. 응답 header/오류/로그에 cache hit·키/스냅샷을 공개하지 않는다. app 종료 후 늦은 저장도 무시한다.

## 12. 최종 보관 점검·Claude 추가 검토 요청

구현 후 점검에서 get/put 시에만 만료 제거하면 유휴 앱에 expired bytes가 장시간 남을 수 있음을 발견했다. TTL은 삽입 때 monotonic 기준, hit 시 연장 없음이다. 최대7일 보관 의도를 위해 앱 lifespan에 종료 가능한 비동기 정리 task를 추가한다. 1초마다 두 cache에서 만료 항목을 제거하고, 종료 시 task cancel/await 후 cache.close로 전부 비운다. thread lock 아래 최대4096항목/각 cache를 순회하고 payload/key/개인정보를 로그로 남기지 않는다. 비활성 앱은 task를 실행하지 않는다. prune/시계 오류는 요청 결과를 바꾸지 않는다.

이 작업은 만료 후 다음 요청 없이도 참조를 정리하는 best-effort 앱 메모리 정책이다. 프로세스 정지/OS suspend/이벤트루프 지연/시계 오류 때 정리의 정확한 벽시계 시한·메모리 덤프/스왑/GC의 secure erase를 보장하지 않는다. 정상 작동 시 TTL 경계부터 재사용하지 않고 다음 sweep(통상1초 내)에 cache 참조를 제거한다. 최대7일은 사용 가능한 entry TTL의 상한이며 법적/물리적 완전삭제 SLA는 주장하지 않는다.

Claude는 **이 MD만 Read/Edit**하고 §13에 이 보완의 적절성, lifespan 취소/cleanup·실패 처리·테스트 누락만 검토한다. 코드/DB/.env/외부/다른파일/Git 도구 접근은 금지한다. 구현은 Codex가 §13 검토 후 수행한다.

## 13. Claude 최종 보관 점검 검토 (2026-11-12)

### 13.0 범위·한계

- 이 MD만 읽고 §13만 추가했다. §1~§12는 수정하지 않았다. 실제 코드(core/cache.py, lifespan/main, config), 테스트, Python/asyncio 문서는 읽지 않았고 실행이나 측정도 하지 않았다. 아래 판단은 §2·§11·§12의 설명이 실제 구현과 같다는 전제에서만 성립한다.

### 13.1 적절성·TTL

1. **[동의] 보완이 필요하고 방향도 맞다.** get/put 때만 정리하면 유휴 앱에서 만료 bytes가 다음 접근까지 무기한 남는다. 이 상태는 "사용 가능한 TTL 상한 7일"과 별개로 보관 의도와 어긋난다. TTL 경계부터 재사용을 막는 것(get 판정)과 참조 제거(sweep)를 구분한 §12의 설명은 정직하다.
2. **[중간] 만료 판정 경계를 하나로 통일한다.** get과 prune이 같은 함수(예: `now >= inserted + ttl`이면 만료)를 써야 한다. 그렇지 않으면 경계 시점에 get은 miss인데 prune은 남기거나, 그 반대가 생긴다.
3. **[중간] "최대4096항목"과 §2의 CACHE_MAX_ENTRIES=256의 관계를 명시한다.** 4096이 설정 상한이라면 config 검증 상한과 같은 값임을 적고, 순회 비용 근거로 쓴다. 다른 의미라면 수치를 정정한다.
4. **[낮음] 순회 비용.** 1초마다 최대 수천 항목을 thread lock 아래 순회하는 것은 μs~ms 수준이라 허용 가능하다. 단 이 작업은 이벤트 루프 스레드에서 실행되므로 lock 안에서는 만료 키 수집·삭제·bytes/count 갱신만 한다(§8.4-5). LRU 순서가 hit로 바뀌어도 TTL이 cache별 고정값이면 삽입 순서가 곧 만료 순서다. 따라서 삽입 순서 보조 구조를 두면 앞에서부터 만료분만 pop할 수 있다. 다만 현재 규모에서는 선택 사항이다.
5. **[낮음] monotonic 시계의 한계.** OS suspend 동안 monotonic이 진행하지 않는 플랫폼에서는 벽시계 기준 보관이 TTL보다 길어질 수 있다. §12에서 이미 보장하지 않는다고 적었으므로 충분하다. 벽시계를 함께 쓰면 시계 변경 위험이 새로 생기므로 추가하지 않는 것을 권장한다.

### 13.2 lifespan 취소·cleanup

1. **[높음] 종료 순서를 고정한다.** ① cache를 closed로 표시해 늦은 put을 무시한다(§11). ② sweep task를 cancel한다. ③ task를 await하되, 그 task의 CancelledError만 흡수하고 lifespan 자체가 취소된 경우에는 다시 raise한다(3.11+에서는 `current_task().cancelling()` 확인). ④ `cache.close()`로 전부 비운다. ⑤ close는 idempotent하게 만든다. ④는 ③이 예외로 끝나도 반드시 실행되도록 `finally`에 둔다.
2. **[높음] 시작 실패 경로를 처리한다.** task를 만든 뒤 lifespan의 나머지 시작 단계(DB 자원 등)가 실패해도 task가 cancel되고 cache가 닫혀야 한다. task 생성 직후부터 try/finally 범위에 포함한다.
3. **[중간] task 참조를 보관한다.** `create_task` 결과를 app state나 자원 객체에 강참조로 보관해 GC로 사라지지 않게 한다. 이름(예: `cache-sweeper`)을 붙이면 진단이 쉽다.
4. **[낮음] await 시간 상한.** sweep 본문에 블로킹 I/O가 없으므로 cancel 후 await는 즉시 끝나야 한다. 방어적으로 `wait_for(…, 짧은 timeout)`를 둘 수 있지만, timeout이 나도 close는 진행한다.
5. **[낮음] 멀티 워커.** 워커마다 task 1개와 cache 2개가 생기며 각자 정리한다. 별도 조정은 필요 없다.

### 13.3 실패 처리

1. **[높음] 반복 단위로 예외를 격리한다.** 루프 안에서 각 prune 호출을 `except Exception`으로 감싸야 한다. 그렇지 않으면 1회 오류(시계, 회계 불일치 등)로 task가 조용히 죽고, 그 뒤로는 정리가 영구히 멈춘다. CancelledError/BaseException은 잡지 않는다. 한 cache의 실패가 다른 cache의 prune을 막지 않도록 cache별로 감싼다.
2. **[중간] 예상 밖의 종료를 감지한다.** done callback에서 취소가 아닌 종료를 예외 클래스명만으로 기록한다. 연속 실패 로그는 rate-limit한다. payload·key·좌표·snapshot은 로그에 남기지 않는다(§12 유지).
3. **[중간] 회계 일관성.** prune과 get/put이 같은 lock 아래에서 entry 삭제와 bytes/count 감소를 함께 처리해야 한다. 그래야 LRU 한도 판정이 실제 보관량과 어긋나지 않는다.
4. **[낮음] 참조 잔존.** dict에서 제거해도 진행 중인 hit의 decode가 같은 bytes를 잡고 있으면 그 요청이 끝날 때까지 남는다. §12의 "secure erase 미보장" 범위에 포함되므로 문서화로 충분하다.

### 13.4 테스트 권고

1. 시계와 sweep 간격을 주입하고 `prune_once()`를 직접 호출해 실제 1초 sleep 없이 결정적으로 테스트한다.
2. TTL 경계(직전/정확히/직후)에서 get과 prune의 판정이 일치하는지 확인한다.
3. prune 후 남은 항목의 LRU 순서, bytes/count 회계, 다음 put의 축출 동작이 맞는지 확인한다.
4. CACHE_ENABLED=false면 task가 생성되지 않는지 확인한다.
5. 정상 종료 시 task가 done 상태이고, 두 cache가 비어 있으며, 늦은 put이 무시되는지 확인한다. close를 두 번 호출해도 문제가 없는지 확인한다.
6. lifespan 시작이 중간에 실패해도 task가 cancel되고 cache가 닫히는지 확인한다.
7. prune에서 강제 예외가 나도 다음 반복이 실행되고, 다른 cache는 정리되며, 요청 결과는 바뀌지 않는지 확인한다. 로그에는 예외 클래스명만 남는지도 확인한다.
8. 외부 취소(lifespan 취소)가 흡수되지 않고 전파되는지 확인한다.
9. 여러 스레드가 get/put하는 동안 prune을 반복하는 stress 테스트로 회계 불변식(bytes ≥ 0, count ≤ max)을 확인한다.
10. 선택 사항으로, 최대 항목 수에서 prune 1회의 소요 시간이 이벤트 루프를 눈에 띄게 막지 않는지 측정한다.

### 13.5 결론

§12 보완은 **채택을 권장한다**. 구현 전에 반영할 항목은 다음 세 가지다. (1) 종료·시작 실패 경로의 cancel→await→close 순서와 외부 취소 전파(§13.2-1·2). (2) 반복 단위 예외 격리로 task가 조용히 죽지 않게 하는 처리(§13.3-1). (3) get/prune 만료 판정의 통일과 4096/256 수치 정합(§13.1-2·3). 나머지는 구현·테스트 단계에서 반영하면 된다.

## 14. Codex 최종 구현·검증

세 번째 실제 Claude MD diff/JSON도 확인했다(is_error=false,3turns,permission_denials=[]). §12~13의 주기 정리를 채택했다. 실제 구현은 cache.close를 먼저 실행해 closed/전량 제거로 늦은 put을 차단한 다음 task cancel/await하고 바깥 finally에서 DB 자원을 닫는다. task는 cache 객체와 context 지역변수의 강참조로 유지하고 비활성 때 생성하지 않는다. 별도의 시작 단계는 없으며 생성부터 yield/종료를 try/finally로 감쌌다. 외부 취소는 current_task.cancelling으로 구분해 전파한다. get/put/prune의 <=now 경계·lock/bytes 회계를 통일했다.

각 cache의 prune 오류를 격리하고 반복을 계속한다. 기본256/설정상한4096항목의 참조 정리만 수행하며, 새로운 예외/정리 로그와 rate-limit 관측기는 이번 범위에 추가하지 않았다. 정리 실패의 물리 삭제 SLA는 주장하지 않으며 재사용은 get에서 만료/시계 오류일 때 차단한다. 중첩 비활성·정상/시작실패/외부취소 종료·idle sweep·독립 cache 실패·다중 스레드 회계를 결정적 테스트로 확인했다.

- 일반 **1,166 passed**, 격리 PostGIS **124 passed**, ruff/format **273 files**, mypy app/etl/migrations **135 files** 통과. 새 일반52·통합7이다. 기존 Starlette 경고1건은 그대로다. 전체 통합에서 기존 세션 검사 wrapper의 신규 cache keyword 미수용을 수정했고, 해시의 우연한2글자 일치를 정보 유출로 보던 테스트도 긴 canary로 바로잡았다. 실패를 무시하거나 검사 대상을 줄이지 않았다.
- 실제 PG17 격리 DB에서 cold/warm JSON일치·warm 집계SQL0, 같은batch/updated_at불변 area/geometry UPDATE·INSERT/DELETE·batch meta 변경, 진행/commit/rollback·옛RR/새RR분리, readwrite/READ COMMITTED 우회·GUC분리·snapshotSQL실패500·원천오류500, 같은6자리/정확좌표 다른500m경계, AI 서버준비+모의공급자1회·세션닫힘, TRUNCATE drain/restart를 검증했다. 개발 DB에 파괴적 suite를 실행하지 않았다.
- 실제 개발 DB 카페/음식점 각각 uncached 결과와 JSON일치. cold **0.6195/0.6367초·9 SQL**, warm **0.0099/0.0080초·3 SQL**이다. 단일 개발 환경 관측이며 성능 SLA가 아니다. AI2요청은 모의 공급자1회·실모델0회였고 현재조립시각/요청별regenerated=false를 확인했다. sweep 추가 전 측정이며 캐시 계산 경로는 동일하다.
- 개발 DB는 READ ONLY로 head0009·모델차이0·14테이블 전체 행/geometry hash·건수 보존을 확인했다. 전체 hash 검사만 검증용 세션 제한을120초로 높여 완료했으며 실제 .env/설정 파일은 바꾸지 않았다. 유휴 개발 DB 61개/300.375초 샘플에서 가시성 snapshot은1종이었다. 운영 쓰기 부하의 hit율 근거로 확대하지 않는다.
- 공개 API schema·프롬프트·모델/migration·의존성·실제 .env/Docker·FE 저장소 변경은 없다. 기존 BE의 FE AI 요청서에 서버cache·현재 generated_at/요청별 regenerated 의미만 보완했다. FE 코드/CLAUDE.md/계약·실제 화면은 담당자 대기다. 브랜드 #57 승인, 공식/조건부 수치·AI 추가문맥·지원 맞춤 정렬·로그30일 보관/삭제·전체 통합은 완료로 표시하지 않는다.

비밀값 검사·지정 PR·CI/CodeQL 후 일반 Squash 병합하며 실제 PR 상태는 이슈74 연결 기록을 따른다. 로컬 원본/집계 evidence·검증 helper는 ignored datasets에만 보관하며 커밋하지 않는다.
