# 인허가 적재 후 로컬 DB 유지보수 명령 (#86)

- 기준: develop12c2180, head0010. #78의 대량 writer 직후 출처 조회 경계 후속이다.
- 목적: README의 수동 VACUUM·출처 검증을 재현 가능한 로컬 전용 명령으로 제공한다. 쿼리 성능 보장·자동 읽기 차단을 구현하는 작업은 아니다.

## 1. 기존 근거와 범위

PR83은 정적 데이터의 반복 출처 조회를 개선했지만 합성 대량 UPDATE 직후에는 옛 배치의 dead tuple을 검사하며 SQL3초를 넘었다. 이 기록은 기존 검사이며 이번 재실행 결과가 아니다. 기존 절차는 읽기 중지→ETL 커밋→별도 autocommit VACUUM(ANALYZE)stores→API 확인→읽기 재개다.

소스의 `current_provenance`는 전역 지원 점포의 source/배치·고아·기준일을 검사한다. LIMIT/임의 최신 배치·검사 생략으로 대체하지 않는다. 이번에는 운영 절차 실행기만 구현하며 API/SQL/timeout·ETL 트랜잭션·모델/migration·FE·실제.env/Docker를 바꾸지 않는다. 실제 개발 DB의 유지보수는 실행하지 않고 dry-run만 확인한다.

## 2. CLI와 단계

`python -m etl.localdata.maintenance [--execute]`. 기본 dry-run은 기존 validate_local_target으로 loopback/spoton_dev/spoton_app 확인 후 기존 READ ONLY REPEATABLE READ·SQL별 설정 제한에서 check_local_database(head0010/PostGIS/일반 계정/고유키)와 public.stores의 현재 role 소유권을 확인한다. 소유권이 다르면 고정 오류로 거절한다. 네트워크 원천/키/HTTP/LLM을 사용하지 않는다.

명시적 --execute만 별도 AUTOCOMMIT connection에서 DB identity/소유권을 다시 확인하고 고정 SQL `VACUUM (ANALYZE) public.stores`를 수행한다. SET lock_timeout5초·statement_timeout60초는 이 전용 engine 연결에만 적용하고 종료 때 engine을 dispose한다. 표준 VACUUM이며 FULL·TRUNCATE SQL/임의 테이블·스키마·URL 인자를 제공하지 않는다.

VACUUM이 정상 반환한 뒤 새 READ ONLY REPEATABLE READ 세션에서 current_provenance를 수행한다. 기존 SQL별3초 기본값과 날짜/출처/고아 검사·정렬을 재사용한다. 출처 검증 성공은 모든 API/운영 SLA 검증이 아니다. 이후 실제 API 확인/트래픽 재개는 운영자 절차다.

명령은 ETL을 실행하지 않는다. ETL 커밋·VACUUM·후속 검증은 원자적이지 않으며 실패가 앞의 커밋/물리 정리를 되돌리지 않는다. 운영자는 읽기·대량 writer·migration을 중지한 후 실행한다. 실행기가 이를 자동 제어하거나 모든 다른 세션 부재를 증명하지 않는다.

## 3. 결과와 오류

stdout JSON1개·성공0/실패1. 고정 operation/mode/phase와 vacuum_completed·provenance_checked, 성공 검증의 batch_count/reference_date만 출력한다. 좌표/주소·격자/점포·비밀값/DB URL/실제 경로·SQL 오류/traceback은 출력하지 않는다. 인자 오류도 원문 없이 arguments 코드다. 임의 positional/URL/테이블 옵션 거절.

실패는 고정 configuration/database/ownership/vacuum/provenance/operation_failed 코드와 실제 도달 단계로 구분한다. VACUUM이 성공한 뒤 검증이 실패하면 vacuum_completed=true·provenance_checked=false로 남긴다. VACUUM 자체가 취소/실패한 경우도 물리 변경 없음/rollback이라고 하지 않는다. 예외 후 engine 해제를 보장한다. 운영 실패를 정상 성공으로 바꾸지 않는다.

## 4. 검증

- 단위: 잘못된 인자/대상은 연결 전 거절·원문 비출력; 기본 dry-run은 AUTOCOMMIT/VACUUM/출처 검사 미수행; 각 단계 실패 결과와 자원 해제.
- 격리 PostGIS: 실제 migration·합성 stores 적재/UPDATE 후 실제 AUTOCOMMIT VACUUM ANALYZE, 후속 READ ONLY/REPEATABLE READ/기존 제한과 provenance 확인, 실제 소유권 거절, VACUUM 뒤 고아 오류와 완료 상태 보존, 전후 stores/배치 전체 행·head/index 불변. DB 통계/visibility 등 물리 상태 변화는 기대한다. 소규모 테스트의 시간으로 대량 성능을 주장하지 않는다.
- 실제dev: 기본 CLI dry-run만 수행하고 READ ONLY임을 별도 계측한다. 실제 VACUUM/DML/DDL은 하지 않는다. FE 변경0·일반/전체격리·ruff/format/mypy·실제 비밀값검사.
- README/BE CLAUDE/작업계획 갱신. 공개 API 계약 변경이 없어 FE 요청서/FE CLAUDE는 수정 대상이 아니다. 사용자 미추적 분석문서 보존. 지정 PR·CI/CodeQL 후 develop 정상 Squash. #78·#57은 유지한다.

## 5. Claude 검토 요청

이 MD와 지정 BE 소스만 Read, 이 MD §6만 Edit한다. .env/DB/Bash/네트워크/Git/FE/다른 파일 수정 금지. AUTOCOMMIT·소유권/대상·부분 완료·권한·timeout·트래픽 통제 경계·민감정보/오류·의미 보존을 검토한다. 검토와 테스트/실제 실행을 구분한다.

## 6. Claude 검토 결과

검토 방식: 이 MD와 지정 소스(`etl/localdata/runner.py` 1-90행, `app/db/dependencies.py`, `app/db/session.py`, `app/services/store_cohort.py`)의 정적 Read만 했다. .env·DB·네트워크·Bash·Git·FE와 다른 파일(`app/core/operations.py`, `app/core/errors.py`, 설정, 테스트, README)은 보지 않았다. 테스트나 실제 실행 결과가 아니며 PostgreSQL 동작은 일반 문서 지식에 근거한 판단이다. 범위·방향(로컬 전용·표준 VACUUM·고정 SQL·dry-run 기본·비원자성 명시)은 타당하다. 아래 차단 항목을 구현 설계에 반영해야 한다.

### 6.1 차단 항목(구현 전 결정 필요)

1. **소유권 불일치 시 VACUUM이 "성공"으로 반환된다.** 소유자(또는 PG17의 MAINTAIN 권한 보유자)가 아닌 role이 `VACUUM public.stores`를 실행하면 오류 없이 WARNING만 내고 건너뛴다. 따라서 §3의 "정상 반환 = vacuum_completed=true"는 소유권 확인 없이는 거짓 성공이 된다. 요구사항:
   - 소유권 SQL은 `pg_class c JOIN pg_namespace n`에서 `n.nspname='public' AND c.relname='stores' AND c.relkind='r'`로 고정하고, `c.relowner = (SELECT oid FROM pg_roles WHERE rolname=current_user)` 정확 일치만 허용한다. role 멤버십·PG17 MAINTAIN은 허용 근거로 쓰지 않는다(더 엄격한 쪽 유지).
   - `check_local_database`는 비한정 `'stores'::regclass`를 쓴다(runner.py 67행). search_path에 따라 public.stores와 다른 테이블을 볼 수 있으므로 `'stores'::regclass = 'public.stores'::regclass`도 함께 확인하거나 소유권 검사를 public 한정으로만 판단한다.
   - AUTOCOMMIT 연결에서 VACUUM **직전** 재확인한다(§2에 있음, 유지). 확인과 VACUUM 사이 TOCTOU는 남지만 로컬·운영자 중지 전제에서 수용 가능한 한계로 기록한다.
   - 선택 보강: VACUUM 전후 `pg_stat_user_tables`의 `vacuum_count`/`analyze_count`(public.stores) 증가를 확인하면 "건너뜀"을 탐지할 수 있다. 다만 PG14 이하는 통계 반영이 비동기라 불일치 시 실패로 단정하지 말고, 사용하려면 PG 버전 조건과 의미를 §7에서 결정한다. 사용하지 않으면 사전 소유권 확인이 유일한 근거임을 명시한다.

2. **AUTOCOMMIT 연결의 timeout은 세션 수준이어야 한다.** 기존 `read_only_session`은 `set_config('statement_timeout', ..., true)`(트랜잭션 LOCAL)를 쓴다(dependencies.py 47-50행). AUTOCOMMIT에서는 트랜잭션 블록이 없어 LOCAL/`SET LOCAL` 값이 다음 문장에 적용되지 않는다. VACUUM 연결은 `SET lock_timeout='5s'`·`SET statement_timeout='60s'`(세션) 또는 `set_config(...,false)`를 사용해야 하며, 이 패턴을 복사하면 timeout이 무효가 된다. 연결은 `engine.connect().execution_options(isolation_level="AUTOCOMMIT")`로 열고 첫 문장 전 격리 수준을 확정해야 한다(VACUUM은 트랜잭션 블록 안에서 실패). 세션 SET이 풀 연결에 남으므로 전용 engine은 공유하지 말고 종료 시 dispose(또는 NullPool)한다.

3. **`read_only_session` 재사용은 오류 단계를 뭉갠다.** 이 함수는 `SQLAlchemyError`·`DatabaseConfigurationError`를 모두 `AppError(INTERNAL_ERROR)`로 바꾸고(52-53행), `current_provenance`도 데이터 검증 실패를 같은 `AppError(INTERNAL_ERROR)`로 낸다(store_cohort.py 76행). 그대로 쓰면 statement_timeout/연결 오류(database)와 출처 무결성 실패(provenance)를 구분할 수 없다. 또 `DatabaseResources`는 `CacheResources`를 함께 만든다(24행). 요구사항: CLI는 `DatabaseResources`를 쓰지 않고, 같은 설정(`REPEATABLE READ` → `SET TRANSACTION READ ONLY` → LOCAL statement_timeout=`database_statement_timeout_ms`)을 재현한 전용 세션 헬퍼를 쓰되 예외를 단계별로 분류한다. `current_provenance` 자체 SQL·검사·정렬은 수정하지 않고 호출만 한다. AppError→provenance, SQLAlchemyError(QueryCanceled 포함)→database(또는 provenance 단계의 database) 매핑을 §3에 명시한다.

4. **설정 오류 예외 범위.** `validate_local_target`은 `ImportConfigurationError`뿐 아니라 내부 `normalize_database_url`에서 `DatabaseConfigurationError`도 던진다(runner.py 43행, session.py 33-50행). 두 예외 모두 configuration 코드로 매핑하고, 예외 메시지(`import:wrong_target` 등 포함)도 stdout에 그대로 내지 않을지 고정 코드만 낼지 결정한다. 현재 메시지는 원문 URL을 포함하지 않지만 출력은 고정 코드로 제한하는 것이 §3과 일치한다.

5. **인자 오류의 종료 코드 충돌.** 기존 `SafeParser.error`는 stderr에 `invalid arguments`를 쓰고 exit 2다(runner.py 35-37행). §3은 "stdout JSON 1개·실패1·arguments 코드"다. 재사용하면 계약과 다르다. 별도 parser 서브클래스로 stdout JSON+exit 1을 낼지, 기존 관례(exit 2)를 따를지 §7에서 하나로 정하고 테스트로 고정한다. `--help`의 exit 0·출력도 예외로 명시한다.

### 6.2 의미·경계 보완

- **VACUUM 정상 반환 ≠ dead tuple 제거.** 다른 세션의 오래된 snapshot(긴 REPEATABLE READ 읽기, idle in transaction, prepared transaction, replication slot)이 xmin을 붙잡으면 VACUUM은 성공해도 #82의 옛 버전을 회수하지 못하고, 후속 출처 검사가 여전히 3초를 넘을 수 있다. 실행기는 트래픽 중지를 증명하지 않으므로(§2) 이 경우 provenance 실패로 끝나는 것이 정상 동작이다. 결과를 "정리 완료"가 아닌 "VACUUM 명령 정상 반환"으로 문서화한다. 비슈퍼유저는 다른 role의 `pg_stat_activity` 세부를 볼 수 없으므로 다른 세션 부재 검사를 추가하더라도 증명이 아니다.
- **vacuum_completed의 의미.** `VACUUM (ANALYZE)`는 한 명령이므로 VACUUM 단계 완료 뒤 ANALYZE 중 statement_timeout이 나면 물리 정리는 일부/전부 반영되었으나 결과는 실패다. `vacuum_completed=false`는 "정상 반환을 확인하지 못함"이지 "변경 없음"이 아니라는 점을 출력 필드 설명에 고정한다(§3 방향과 일치).
- **lock_timeout 5초.** 표준 VACUUM은 SHARE UPDATE EXCLUSIVE를 요구한다. 진행 중 자동 VACUUM은 보통 양보하지만 wraparound 방지 자동 VACUUM·다른 VACUUM/ANALYZE·CREATE INDEX CONCURRENTLY·일부 DDL은 양보하지 않아 vacuum 코드로 실패할 수 있다. 재시도는 운영자 판단이며 자동 재시도는 넣지 않는 것이 적절하다.
- **statement_timeout 60초.** 689,440행 전체 UPDATE 직후 실제 소요는 검증되지 않았다(실제 dev 실행 금지). 상수는 명명된 상수로 두고, 초과 시 vacuum 실패·부분 정리 가능을 안내한다. 60초를 충분하다고 주장하지 않는다. 사용자 인자로 조정 가능하게 할지는 §7 결정 사항이다(추가하면 상·하한 검증 필요).
- **표준 VACUUM 한계.** 파일 크기를 OS에 반환하지 않고 인덱스 bloat를 재구성하지 않는다(REINDEX·FULL은 범위 밖, 유지). 대상은 stores뿐이며 store_import_batches는 대상이 아니다.
- **중단(Ctrl+C/SIGTERM).** psycopg가 실행 중 문장을 취소할 수 있으나 결과는 불확정이다. BaseException에서도 engine dispose를 보장하고, 출력할 경우 operation_failed·vacuum_completed=false(미확인)로 남긴 뒤 종료 코드를 정한다(KeyboardInterrupt를 삼켜 성공 종료하지 않음).
- **운영 로그.** 기존 ETL 6개는 `logged_import` 운영 로그를 쓴다(runner.py 75행). 이 명령에 stderr 운영 이벤트를 추가할지 여부가 설계에 없다. 추가하면 #72 고정 필드·허용값만 쓰고, 추가하지 않으면 "운영 로그 대상 아님"을 명시한다(operations.py는 이번에 읽지 않았으므로 호환성은 미확인).
- **출력.** batch_count·reference_date만 허용하는 방향은 타당하다. batch UUID·source별 날짜·SQL 오류 문자열·DB 이름/호스트·`import:*` 메시지 원문은 출력하지 않는다. 예외 연쇄(`__context__`)로 원문이 남지 않도록 except 밖에서 고정 결과를 만든다(session.py 32-34행의 기존 관례).

### 6.3 필수 테스트 추가

단위(연결 모킹):
- 인자 오류·임의 positional·`--table`/URL 옵션 거절 시 연결 생성 0회, 결정된 종료 코드·stdout 형식 고정.
- `DatabaseConfigurationError`·`ImportConfigurationError` 각각 configuration 코드, 원문/URL canary 비출력.
- dry-run에서 AUTOCOMMIT 연결 생성·VACUUM·출처 검사 호출 0회.
- provenance 단계 AppError→provenance, SQLAlchemyError→database 분류(read_only_session 경유로 뭉개지지 않음).
- VACUUM 성공 후 검증 실패에서 `vacuum_completed=true, provenance_checked=false`, VACUUM 예외에서 `vacuum_completed=false`, 모든 경로(KeyboardInterrupt 포함) engine dispose.
- stdout JSON 정확히 1줄, 허용 키만 존재.

격리 PostGIS:
- VACUUM 연결의 격리 수준이 AUTOCOMMIT이고 `SHOW lock_timeout`=5s·`SHOW statement_timeout`=60s(세션 SET이 실제 적용됨).
- 소유자 아닌 role(또는 `ALTER TABLE public.stores OWNER TO` 다른 role) → ownership 코드, VACUUM 미실행(`vacuum_count` 불변).
- search_path에 다른 스키마의 `stores`를 앞세운 경우에도 public.stores만 대상이거나 거절.
- 다른 연결이 `LOCK TABLE public.stores IN SHARE UPDATE EXCLUSIVE MODE`를 보유한 상태 → 약 5초 내 vacuum 코드, vacuum_completed=false, 자원 해제.
- 정상 실행 후 `pg_stat_user_tables`의 vacuum/analyze 횟수 증가(PG15+ 기준, 버전 조건 명시), dry-run에서는 불변.
- 후속 출처 세션이 READ ONLY(쓰기 시도 거절)·REPEATABLE READ·기존 statement_timeout 값임을 확인.
- 고아 행 주입 후 실행 → provenance 코드·vacuum_completed=true.
- 전후 stores/배치 전체 행 hash·head·인덱스 정의 불변(§4 유지).
- 오래된 snapshot을 연 다른 세션이 있을 때도 VACUUM이 성공 반환한다는 사실(=회수 보장 없음)을 문서화용으로 확인하는 것은 선택.

실제 dev: dry-run만. READ ONLY 계측은 `vacuum_count`/`analyze_count`·`n_tup_*`·head 불변 등으로 하고 VACUUM/DML/DDL은 하지 않는다(§4 유지).

### 6.4 범위 한계(문서에 유지·추가)

- 쿼리 성능·3초 이내 회복·운영 SLA를 보장하지 않는다. 소규모 격리 테스트 시간으로 대량 성능을 주장하지 않는다.
- 읽기·writer·migration 중지를 자동화하거나 증명하지 않으며, 오래된 snapshot이 있으면 정리가 무효일 수 있다.
- ETL 커밋·VACUUM·출처 검사는 원자적이지 않고 실패가 앞 단계를 되돌리지 않는다.
- 표준 VACUUM만 수행하며 공간 반환·인덱스 재구성·다른 테이블 정리·자동 VACUUM 설정 변경은 하지 않는다.
- API/SQL/timeout 기본값·`current_provenance`·ETL 트랜잭션·모델/migration·FE·실제 .env/Docker 변경 없음을 유지한다.
- 이 검토는 정적 검토이며 PostgreSQL 동작(비소유자 WARNING, AUTOCOMMIT과 LOCAL 설정, 통계 반영 시점)은 격리 테스트로 확인해야 확정된다.

## 7. Codex 최종 결정·검증

Claude의 실제 §6 수정과 지정 소스를 대조했다. 정확한 public.stores 소유자·search_path 검사, AUTOCOMMIT 세션 SET·전용 engine, 별도 읽기 세션에서 원래 DB 오류/출처 AppError 구분, 부분 완료·인터럽트·해제 실패 상태를 채택한다. 기본은 dry-run이며 stdout JSON1건/실패1, 인자오류도1, KeyboardInterrupt130, --help만 기본 도움말/0이다. 운영 로그 decorator는 붙이지 않는다.

CLI 전용 읽기 세션은 기존과 같은 READ ONLY REPEATABLE READ·설정 timeout을 쓰되 DB 예외를 AppError로 바꾸지 않는다. API 공통 세션/쿼리/설정은 변경하지 않는다. VACUUM 실패는 vacuum 코드, 후속 SQL 오류는 database·출처 유효성 AppError는 provenance 코드로 구분한다. finally dispose를 시도하고 해제 실패도 고정 cleanup 오류로 표시한다. 원래 실패가 있으면 그 원인을 보존한다.

실행 SQL은 `VACUUM (ANALYZE, TRUNCATE FALSE) public.stores`로 확정한다. [PostgreSQL17 공식 문서](https://www.postgresql.org/docs/17/sql-vacuum.html)의 TRUNCATE 설명대로 말단 빈 페이지 반환에 필요한 ACCESS EXCLUSIVE 시도를 피한다. FULL/REINDEX·물리 파일 축소를 제공하지 않는다. 고정 timeout60초/lock5초를 두고 임의 설정 인자는 추가하지 않는다.

vacuum_completed는 명령의 정상 반환 확인일 뿐 회수 성공/성능 회복 보장이 아니다. 오래된 snapshot·동시 DDL/소유권 변경·통계 반영 지연의 한계를 유지한다. 비동기 pg_stat 증가를 성공 조건으로 쓰지 않는다. 격리에서는 실제 명령·AUTOCOMMIT·세션 설정·UPDATE 후 visibility map 회복·논리 데이터 보존을 확인한다. 통계 횟수 증가에 의존하는 추가 검사는 채택하지 않았다. 운영자가 읽기/대량 writer/migration을 중지해야 하며 이 CLI가 그 상태를 증명하지 않는다. 실제dev는 dry-run만 수행한다.

## 8. 구현·검증 결과

- Claude가 이 MD §6을 직접 수정했고 Codex가 실제 diff·지정 소스 및 공식 PostgreSQL 문서를 대조 후 구현했다. Claude 결과 is_error=false·7turns·권한거절0이다. `etl/localdata/maintenance.py`만 새 실행기이며 기존 ETL/API·모델/migration·설정/의존성·FE는 변경하지 않는다.
- 신규 단위17·격리7을 포함한 **일반1,213 passed / 격리PostGIS180 passed**, ruff check/format294파일·mypy app/etl/migrations139파일 통과. 기존 Starlette 경고1건만 있다.
- 실제 임시 PostGIS에서 합성 stores20행의 UPDATE 뒤 기본 점검/VACUUM 실행을 비교했다. AUTOCOMMIT·lock5초·statement60,000ms, 후속 READ ONLY REPEATABLE READ·3초, visibility map 회복과 stores/배치 전체행·head·인덱스 보존을 확인했다. 처음 검사에서 PostgreSQL이60s를1min으로 표시해 단언이 실패했고 pg_settings의 밀리초 값을 비교하도록 수정한 뒤 재통과했다.
- public.stores 비소유자·동일이름 shadow schema 거절, 실제 충돌 잠금의5초 제한, VACUUM 정상 반환 후 고아 행 출처 실패에서 vacuum_completed=true/검증false를 확인했다. 구성/인자·DB/출처/예상밖 오류·Ctrl+C·해제실패/기존오류보존·원문 canary 비노출도 검사했다. 소규모 fixture여서 대량 성능/SLA 또는 전체 API 회복을 검증한 것은 아니다.
- 실제 개발 DB는 기본 CLI dry-run1회만 수행했다. 실제 SQL 계측으로 READ ONLY REPEATABLE READ·3초와 유지보수/DML/DDL 미실행을 확인했다. 별도 READ ONLY QA에서 **stores·store_import_batches2테이블 전체행/to_jsonb(geometry 포함)hash·건수, public 인덱스 정의·head0010, stores의 수동VACUUM/ANALYZE·DML 카운터가 전후 동일**했다. 이 QA는 CLI 자체 기능이 아니며 CLI는 hash를 재계산하지 않는다.
- README/BE CLAUDE/작업계획에 사용법·단계별 실패·비원자성·자동 제어 미포함을 반영한다. 실제.env/Docker·사용자 미추적 분석문서·FE 변경0이며 키/원본을 포함하지 않는다. #78의 자동 조회 보호/대량 운영 검증·#57 승인·생활인구 의미/시점 근거 등은 후속으로 유지한다. 지정 PR·CI/CodeQL 후 develop 정상 Squash하며 병합 상태는 연결 PR을 따른다.
