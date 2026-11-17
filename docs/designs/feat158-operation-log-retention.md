# 운영 로그 수집·30일 만료 삭제 (#158)

- 기준: develop `fc90fd9`, 2026-11-15. [이슈 #158](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/158).
- 범위: BE 전용 운영 CLI `python -m etl.operation_logs`, 검증된 JSON 이벤트의 전용 SQLite 보관과 명시적 만료 삭제. FE/API/기존 앱 stderr·인허가/통계 DB·0012·.env·기존 서버·운영 Render 설정은 유지한다.
- 기존 [#72 설계](feat72-private-operation-logs.md)의 출력 경계를 보존하고 수집기 기능을 추가한다. 새 외부 서비스·키·유료 자원·스케줄러를 자동 생성하지 않는다.

## 1. 배포와 구현의 구분

[Render 로그 안내](https://render.com/docs/logging)는 workspace별 보관 기간을 구분한다. [Free 안내](https://render.com/docs/free)는 Free 웹의 영구 디스크 미지원을 명시한다. 그러므로 앱의 임시 파일을 영구 30일 보관의 근거로 삼지 않는다. workspace 요금제와 웹 인스턴스 요금제도 같은 것으로 추론하지 않는다. 이 단계는 지속 저장소를 가진 운영자 환경에서 쓸 수 있는 로컬 수집기 기반이다. 실 운영 수집·누락률·30일 연속 보관·주기적 삭제·백업 만료까지 검증한 것은 아니다.

기존 stdout/stderr를 일반 파일로 통째로 리다이렉트하는 방식은 원문/제3자 로그까지 저장할 수 있어 채택하지 않는다. 입력은 기존 `app/core/operations.py`가 만든 이벤트 JSON 한 줄 형식이다. Render 메시지 wrapper나 syslog 프로토콜을 직접 수신하지 않으며 해당 어댑터/배포 연결은 후속이다. 원문 로그를 수집해 놓고 나중에 지우는 방식은 쓰지 않는다.

(Claude 검토 보완) 이 수집기는 **자기 SQLite 보관본의 만료 삭제만** 다룬다. Render 플랫폼 로그 화면/보관본, 로그 스트림 수신 측, 셸 파이프 버퍼, 운영자의 임시 파일 등 수집기 이전 단계에 남는 원본의 보관 기간은 이 기능으로 제어되지 않는다. 그러므로 이번 구현으로 "#72의 원본30일 보관/삭제 완료"라고 표시하지 않고, 운영 저장소·전달 경로 선정과 실제 연결·누락/지연 측정·주기 prune 운영을 **배포 대기(pending)**로 남긴다. 현재 Render Free 웹의 stderr를 이 CLI로 전달하는 실제 경로는 없다.

## 2. 입력 검증

- API 요청, LLM HTTP 시도, readiness, ETL run/stage/quality 6종만 허용한다. 이벤트별 필수/선택 키 집합, 고정 경로/enum, 정규 UUID, finite 비음수 duration, bool과 구분한 정수 범위, 허용 count/quality 키를 검사한다. 알 수 없는 키/원문/JSON 중복 키/NaN·Infinity/잘못된 시각은 행 전체를 거절한다.
- (Claude 검토 보완) 최상위는 JSON object만 허용한다. 이벤트별 정확한 키 규칙은 현재 emitter와 같아야 한다.
  - `api_request`: {time,event,path,status_code,duration_ms,request_id,response_complete} 정확히 7키. path∈`API_PATHS`∪{"unmatched"}, status_code=null 또는 bool 아닌 int 100~599, duration_ms=null 또는 finite≥0 수, request_id=정규 소문자 UUID(`str(UUID(x))==x`), response_complete=bool.
  - `llm_http_attempt`: {time,event,count,success}, count는 정확히 int 1, success=bool.
  - `readiness_probe`: {time,event,path,reason,success,duration_ms}, path="/api/ready", reason∈`READINESS_REASONS`, success는 반드시 `reason=="ok"`와 같아야 한다.
  - `etl_run`/`etl_stage`: 필수 {time,event,source,run_id,stage,status,duration_ms}. etl_run은 stage="import"만, etl_stage는 import 이외의 Stage만 허용한다. status=failed일 때만 reason="operation_failed"를 필수로 하고 다른 status에서는 금지한다. counts와 quality_flags는 둘 다 있거나 둘 다 없어야 하며(emitter는 result dict일 때만 함께 넣음) 각각 `COUNTS`/`QUALITY_FLAGS` 부분집합 키·bool 아닌 int 0~2^63-1 값만 허용한다. batch_id/version_id는 선택 정규 UUID, mode는 선택 {"write","dry_run"}.
  - `etl_quality`: source="living_pop", stage="read_source", scope/spatial_compatibility/aggregation_status 고정 상수. completed이면 `POPULATION_QUALITY_COUNTS` 6키가 모두 있는 counts가 필수이고 reason 금지, failed이면 reason="quality_summary_unavailable" 필수·counts 금지.
  - 허용 집합은 `app.core.operations`의 상수를 import해 단일 출처로 사용하고 복사하지 않는다. emitter에 경로가 추가되면 수집기도 같은 커밋에서 따라간다. 이미 저장된 행은 재검증하지 않는다.
- JSON 파싱은 `object_pairs_hook`로 중복 키를, `parse_constant`로 NaN/Infinity 리터럴을 거절한다. `1e400`처럼 파싱 후 inf가 되는 숫자도 있으므로 duration은 파싱 뒤 `math.isfinite`를 다시 검사한다. `-0.0`은 거절한다(정규화로 다른 hash를 만들지 않기 위함). int 필드에 float(`1.0`)는 거절한다.
- UTC offset=0인 시각만 허용하고 정규 UTC 문자열로 저장한다. 유한 배치를 EOF까지 읽은 뒤 한 실행의 now를 UTC로 고정한다. 미래 이벤트는 거절하며 event_time이 `now-30*24h` 이하이면 만료로 분류해 저장하지 않는다. 받은 시각을 원래 발생 시각으로 대체하지 않는다.
- (Claude 검토 보완) emitter의 `datetime.now(UTC).isoformat()`은 `+00:00` 접미사이고 microsecond가0이면 소수부를 생략한다. 두 형태(`YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00`)만 받고 `Z`·다른 offset·naive·자리수 다른 소수는 거절한다. 저장은 epoch 기준 정수 microsecond(`event_us INTEGER`)로 하고 비교는 Python에서 계산한 cutoff를 파라미터로 바인딩한다. SQLite `datetime()`/문자열 비교에 의존하지 않는다(초 단위 절삭·형식 차이 회피).
- event_time은 emitter의 기록 시각이며 요청/작업 시작 시각이 아니다. 수집 시각(ingest time)은 보관 기준으로 쓰지 않는다. 늦게 들어온 오래된 이벤트도 event_time 기준으로 만료 판정한다. 수집기와 emitter 호스트의 시계 차이로 정상 이벤트가 미래로 거절될 수 있으므로 future는 일반 거절과 별도 건수로 출력해 운영자가 시계 문제를 구분할 수 있게 한다(허용 오차 옵션은 두지 않는다).
- 분류 순서는 형식 거절(rejected) → 미래(future) → 만료(expired) → 중복(duplicate) → 삽입(inserted)이며 상호 배타적이고 합이 읽은 행 수와 같아야 한다. 중복은 기존 저장소와 같은 실행 내 중복을 모두 포함한다.
- 입력 한 줄 UTF-8 최대4096 bytes(개행 제외), 실행당10,000행·10MiB 상한. stdin을 제한 없이 한꺼번에 읽지 않는다. 오류나 거절 결과에는 원문·예외·경로를 출력하지 않는다. 정상/거절/만료/중복/삽입 건수만 출력한다.
- (Claude 검토 보완) 입력은 stdin(바이너리)만 받으며 입력 파일 경로 옵션은 두지 않는다. `readline(limit)`으로 한도+1 바이트까지만 읽고, 초과 행은 개행까지 고정 크기 청크로 버리며 rejected 1건으로 센다(버린 바이트도 10MiB 총량에 포함). 행 끝의 `\n` 또는 `\r\n` 하나만 제거하고 마지막 개행 없는 행도 검증 대상이다. BOM·잘못된 UTF-8은 해당 행 거절이다. 10,000행 또는 10MiB 초과는 개별 거절이 아니라 실행 전체 실패(exit1·삽입0)다. emitter는 개행 포함4096 bytes 초과를 버리므로 정상 입력은 이 한도 안에 있다.
- 검증된 레코드만 canonical JSON으로 직렬화하고 SHA256을 중복 키로 사용한다. 수집 완료는 전달 구간 누락 없음이나 공급자 인증을 의미하지 않는다.
- (Claude 검토 보완) canonical은 `sort_keys=True, separators=(",",":"), ensure_ascii=True, allow_nan=False`에 정규화한 time 문자열을 사용한다. `llm_http_attempt`·`readiness_probe`는 식별자가 없으므로 시각·값이 완전히 같은 서로 다른 이벤트는 하나로 합쳐진다(microsecond 해상도라 드물지만 가능). 재전송 멱등성을 우선한 의도된 한계이며 건수 통계를 정확한 시도 수로 표현하지 않는다. 입력 순번을 hash에 넣지 않는다(재전송 시 중복 저장되므로).
- (Claude 검토 보완) 수집기 자신은 `operations`의 ETL 이벤트를 stderr로 내보내지 않는다(`EtlSource`에 추가하지 않음). 출력이 다시 수집 입력으로 연결되는 순환과 #72 이벤트 의미 변경을 피한다.

## 3. 전용 저장소와 명령

`--db`는 저장소 밖의 절대 경로·`.sqlite3` 일반 파일만 받는다. 부모 디렉터리는 이미 존재해야 하며 링크/Windows junction/reparse 경로, 저장소 내부, 디렉터리·다른 확장자·다른 SQLite DB는 거절한다. 임의 파일/DB 자동 발견이나 최신 선택은 없다. 새 파일은 init의 명시적 실행에서만 배타적으로 만들고 application_id/버전/고정 테이블 정의로 식별한다. 상태/기본 dry-run은 SQLite URI read-only로 열고 파일을 만들지 않는다.

- `init`: 기본은 경로 검사만 하는 dry-run. `--execute`에서 새 저장소만 만든다. 기존 파일을 덮어쓰지 않는다.
- `ingest`: 기본은 기존 저장소/입력 검증과 예상 건수만 계산한다. `--execute`에서만 트랜잭션으로 insert한다. 전체 입력 상한/시스템 오류 시 이번 실행은 rollback하며, 개별 잘못된 행은 건수로 집계하고 나머지 정상 행은 처리한다. 중복 레코드는 insert하지 않는다.
- `status`: 읽기 전용으로 총수/만료 수/보관 기준/규칙만 출력한다. 내용 조회/원문 export 기능은 추가하지 않는다.
- `prune`: 기본 dry-run으로 만료 건수를 센다. `--execute`에서 BEGIN IMMEDIATE 후 동일 기준의 만료 행만 DELETE한다. 경계 `event_time <= cutoff`가 만료다. 최근/미래 행이나 다른 파일을 삭제하지 않는다. 실제 삭제 건수와 남은 만료 건수를 확인하고 commit한다.

고정 규칙은 `operation-log-archive-v1`, 보관 기간은30일이며 임의 기간/임의 기준시각 CLI 옵션을 두지 않는다. 테스트만 clock을 주입한다. 쓰기는 bounded timeout·짧은 단일 writer 트랜잭션으로 직렬화한다. 기본 dry-run은 쓰기 잠금/영속 PRAGMA 변경/DDL/DELETE 없이 종료한다. trusted_schema 같은 연결별 안전 설정은 적용한다.

SQLite는 DELETE journal·secure_delete=ON·temp_store=MEMORY를 사용하고 WAL 상태의 파일을 거절한다. prune 후 이벤트 행과 해시가 주 DB에서 제거되는 것을 합성 canary로 확인한다. 이 기능이 디스크/파일시스템 snapshot·외부 백업·SSD·수집기 원본·Render 보관본의 물리적 소거까지 보장하는 것은 아니다. 백업·기타 복사본의 보관/삭제는 실제 운영 저장소 선정 후 검증한다.

### 3.1 Claude 검토 보완: 경로·파일 안전

- 경로 판정: 입력은 절대 경로여야 하고 `Path.resolve(strict=...)` 결과와 입력 경로를 `os.path.normcase`로 비교해 다르면(링크·8.3 단축명·`..`·후행 점/공백 정규화 포함) 거절한다. 대상과 모든 상위 구성요소를 `os.lstat`으로 검사해 symlink, Windows `FILE_ATTRIBUTE_REPARSE_POINT`(junction 포함)이면 거절한다. 저장소 내부 판정은 해석된 저장소 루트와 `commonpath`를 normcase로 비교한다. UNC(`\\server\`)·`\\?\`/`\\.\` 장치 경로·네트워크 경로는 SQLite 잠금 신뢰성이 없어 거절한다.
- 부속 파일: `<db>-journal`, `<db>-wal`, `<db>-shm`이 링크/reparse이면 거절한다. 기존 `-wal`/`-shm`은 ownership, 기존 `-journal`은 database_busy로 열기 전에 거절한다. 복구는 하지 않는다. 다른 writer의 journal이 검사 사이 사라졌으면 정상 진행할 수 있다.
- 검사 후 열기 사이의 교체(TOCTOU)는 완전히 막을 수 없다. 열기 전·후 (st_dev,st_ino)/Windows file index를 비교하며, 정상 writer의 크기 변화까지 금지하지 않는다. 저장 디렉터리는 운영자 전용·타 사용자 쓰기 불가·로컬 디스크가 전제다. UNC/Windows 원격 드라이브를 거절하지만 POSIX 네트워크 마운트 여부는 운영자가 확인한다. 이 전제 밖의 공격자 경쟁을 막는다고 주장하지 않는다.
- init 생성: `os.open(O_CREAT|O_EXCL|O_WRONLY|O_BINARY, 0o600)`으로 빈 파일을 배타 생성한 뒤 SQLite로 연다(POSIX 권한0600, Windows는 상위 ACL 상속임을 기록). schema 생성이 실패하면 **이번 실행이 만든 같은 inode의 파일만** 삭제하고, 다른 파일로 바뀌었으면 삭제하지 않고 실패한다. 동시 init은 O_EXCL로 한쪽만 성공한다.
- 기존 파일 보존: ingest/status/prune은 파일이 없으면 만들지 않고 실패한다(`mode=ro` 또는 `mode=rw` URI, `mode=rwc` 금지). 빈 파일·0바이트 파일·다른 application_id/user_version 파일·추가 객체가 있는 파일은 수정 없이 거절한다.
- URI는 `Path.as_uri()` 기반으로 만들어 `?`/`#`/`%`가 들어간 경로도 안전하게 전달한다. `immutable=1`은 잠금을 무시하므로 사용하지 않는다.

### 3.2 Claude 검토 보완: schema 식별과 연결 설정

- 식별: SQLite 연결 전 읽기 전용100바이트 헤더로 magic·read/write rollback 버전1·user_version1·application_id를 확인한다. 연결 후 `PRAGMA application_id`·`PRAGMA user_version`·`sqlite_master`의 정확한 객체 집합/CREATE SQL을 확인한다. 내부 autoindex도 정확한 이름1개만 허용하며 패턴으로 숨기지 않는다. **trigger/view/추가 table·index가 있으면 거절**한다. schema 조회 전 trusted_schema=OFF를 설정하고 쓰기 트랜잭션 안에서 소유권을 다시 검사한다.
- 테이블: `operation_events(event_hash TEXT PRIMARY KEY CHECK(length=64), event_us INTEGER NOT NULL, event TEXT NOT NULL, record TEXT NOT NULL)` + `event_us` 인덱스 정도로 최소화한다. 수집 시각·입력 출처·호스트 등 추가 메타데이터는 저장하지 않는다. 별도 meta 테이블을 두면 규칙 버전/보관 일수만 담는다.
- 트랜잭션: Python 3.11 `sqlite3`의 암묵적 트랜잭션을 피하기 위해 `isolation_level=None`으로 열고 `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`을 명시한다. `busy_timeout`은 고정 상수(구현 `LOCK_TIMEOUT=1.0`초, Claude 구현 검토에서 고정 상수 조건 충족으로 수용)이며 초과는 고정 코드 `database_busy`·exit1·변경0이다.
- `secure_delete`·`temp_store`는 연결 단위 설정이므로 쓰기 연결마다 설정하고 `PRAGMA secure_delete`의 반환값이1인지 확인한다(빌드 옵션으로 무시되면 prune 실패). journal_mode는 init에서 DELETE로 두고 열 때마다 `PRAGMA journal_mode` 조회값이 `delete`인지 확인한다(read-only 연결에서는 조회만). DELETE journal도 커밋 후 파일 삭제일 뿐 디스크 블록 소거가 아님을 한계에 포함한다.
- ingest 실행 순서: 입력 전체(≤10MiB)를 잠금 밖에서 읽고 검증·분류·hash 계산 → `BEGIN IMMEDIATE` → schema 재확인 → `INSERT OR IGNORE`(UNIQUE 충돌은 duplicate로 계산, rowcount 합으로 삽입 수 확인) → COMMIT. 예외·KeyboardInterrupt는 ROLLBACK 후 실패/130이며 일부 커밋은 없다. 쓰기 잠금 구간에 입력 읽기를 넣지 않는다.
- prune 실행 순서: now/cutoff를 잠금 전에 한 번 고정 → `BEGIN IMMEDIATE` → schema 재확인 → `COUNT(*) WHERE event_us <= ?` → `DELETE ... WHERE event_us <= ?`의 rowcount가 count와 같고 재조회 만료 수가0일 때만 COMMIT, 아니면 ROLLBACK·exit1. 잠금 대기 동안 시간이 흘러도 cutoff는 더 과거 쪽이므로 삭제가 늘어나지 않는다(보수적).
- dry-run(ingest/prune/status)은 `mode=ro` 연결에서 읽기만 하며 파일의 설정 변경·DDL·쓰기 잠금 없이 끝난다. 연결별 trusted_schema=OFF와 시간 제한은 적용한다. 예상 건수는 그 시점 snapshot 기준이며 이후 execute 결과와 다를 수 있음을 README에 명시한다.

### 3.3 Claude 검토 보완: 동시 실행

- 같은 프로세스: CLI는 명령마다 연결1개를 새로 열고 닫으며 전역 연결·캐시를 두지 않는다. 테스트의 같은 프로세스 병행 호출도 별도 연결로 SQLite 잠금에 맡긴다.
- 두 writer(ingest+ingest, ingest+prune, prune+prune): `BEGIN IMMEDIATE`로 직렬화되며, 늦은 쪽은 busy_timeout 안에서 기다린 뒤 정상 처리하거나 `database_busy`로 변경 없이 실패한다. (Claude 구현 검토 정정, 5.2 R1) 기존 `-journal` 사전 거절 때문에 상대 writer가 이미 페이지를 쓰기 시작해 `-journal`이 있는 구간에서는 **기다리지 않고 즉시** `database_busy`로 실패한다. 어느 경우든 변경0이며 운영자가 재실행한다. 자동 재시도는 두지 않는다. 같은 입력을 두 프로세스가 동시에 넣어도 PRIMARY KEY로 한 번만 저장된다. 두 번째 prune은 삭제0의 정상 종료(멱등)다.
- ingest의 now가 뒤에 실행된 prune의 now보다 이르면, prune 기준으로는 만료인 행이 prune 커밋 후 삽입될 수 있다. 다음 prune에서 지워지며 오류가 아니다.
- writer가 잠금을 가진 동안 status/dry-run은 busy_timeout 후 실패할 수 있다(DELETE journal 모드의 정상 동작).

### 3.4 Claude 검토 보완: CLI 출력·종료 코드

- stdout에는 고정 키 JSON 1줄만 출력한다: command, mode(dry_run/execute), rule_version, retention_days, 단계별 건수, 실패 시 고정 code. DB 경로·입력 원문·예외 문자열·SQLite 오류 메시지는 출력하지 않는다.
- 종료 코드: 성공0, 실행 실패1, 사용법 오류2(#137 probe와 동일), 중단130, `--help`0. argparse 기본 오류는 입력 인자(경로)를 stderr에 그대로 보이므로 고정 안전 메시지로 대체한다.
- 보관 기간 의미: 행은 event_time 후 30일이 지나면 **만료 대상**이 될 뿐 prune 실행 전까지 저장소에 남는다. 실제 최대 보관 기간은 `30일 + prune 실행 간격`이며 이를 "30일 후 자동 삭제"로 표현하지 않는다. status는 현재 남은 만료 건수를 보여 준다. 주기 실행(스케줄러)은 이번 범위 밖이다.

## 4. 검증과 완료 조건

1. 설계 MD를 실제 Claude Read/Edit로 검토하고 Codex가 대조한 뒤 구현한다.
2. 6종의 실제 emit 결과 round-trip, 추가 원문 key/허용 key의 잘못된 값/중복 JSON key/잘못된 UTC·미래·정확한30일 경계·입력 상한/UTF-8·원문 비출력 검증.
3. 임시 전용 디렉터리에서 init/dry-run/ingest/replay/status/prune. 기존 파일/다른 SQLite/링크/저장소 경로 방어, 반복 삭제 멱등성, 손상·잠금·rollback·2 writer를 실제 파일로 검증한다. 실제 사용자/운영 로그 삭제는 하지 않는다.
4. CLI subprocess 실제 JSON 출력과 종료코드0/실패1/사용법오류2/중단130, 도움말0을 확인한다. 기존 API/ETL 로그·일반 테스트와 ruff/format/mypy·격리 PostGIS·CI/CodeQL로 회귀를 검사한다.
   - (Claude 검토 추가 사례) emitter 실제 시각의 소수부 생략(microsecond=0) 형태와 `Z`/`+09:00` 거절, `1e400`·`-0.0`·`true`를 count에 넣은 행, readiness success/reason 불일치, etl_run의 stage≠import·failed인데 reason 없음·counts만 있고 quality_flags 없음, etl_quality completed인데 counts 5키, 4096 초과 행 뒤 정상 행 계속 처리, 마지막 개행 없는 행, `\r\n` 행, 10,000행 초과·10MiB 초과의 전체 실패와 삽입0, 분류 건수 합=읽은 행.
   - (Claude 검토 추가 사례) 정확히 cutoff인 행(만료)과 cutoff+1µs 행(보관), now+1µs(future). trigger/view가 추가된 파일·application_id 다른 파일·0바이트 파일·`-wal` 존재·journal 링크 거절과 파일 hash 불변. init 중 schema 실패 시 새 파일만 정리. ingest 도중 주입 예외/KeyboardInterrupt 후 행 수 불변. 한 프로세스가 `BEGIN IMMEDIATE`를 쥔 동안 다른 프로세스 ingest/prune의 `database_busy` 변경0과 해제 후 정상 처리. secure_delete 확인값과 prune 후 DB 파일 바이트에 canary 문자열이 남지 않음(주 DB 파일 한정). 출력에 경로·canary 비노출.
5. README/작업계획/CLAUDE에 실행 예시와 제한을 반영한다. 개발 완료와 운영 30일 보관의 미완료를 함께 기록한다. 기능·테스트 한 커밋, 문서 보완 한 커밋으로 PR/develop 정상 Squash를 진행한다.

## 5. 검토·실행 기록

CI 보완 재검증 결과: Linux 지정·기본 Windows 플랫폼 mypy 모두187 files 통과, 수집기84 passed/권한 관련1 skipped, ruff check/format413·diff·비밀값 부재 검사 통과다. 검수 소스 해시와 후속 diff를 대조해 Windows API 접근4줄 외 로직 변경이 없음을 확인했다. 수정 후 CI/CodeQL 실제 결과는 연결 PR을 따른다.

CI 플랫폼 보완: 최초 Linux CI에서 `ctypes.windll`이 POSIX 타입 stub에 없어 mypy가 실패했다. Windows 분기에서만 `getattr(ctypes,"windll",None)`로 선택 API를 가져오고 누락 시 고정 configuration 오류로 종료하도록 보완했다. 보관/검증/삭제 동작은 바꾸지 않았다. Codex가 diff를 직접 검토하고 `mypy --platform linux`와 기본 플랫폼·해당 테스트를 재검증한다. 앞의 Claude 최종 소스 검토 이후의 변경은 이 플랫폼 접근 보완뿐이며 CI 실패를 숨기지 않는다.

최신 Codex 재검증: R1~R3 및 종료된 journal 검사 경쟁을 보완한 코드에서 일반2041 passed/Windows링크1 skipped/PostGIS298 deselected(29.01초), ruff check/format413·mypy187 통과다. 신규 수집기85사례(Windows84통과/1제외, Linux는 링크 사례도 실행)이며 아래2036 등은 이전 실행 기록이다. 원본 환경/사용자 파일 보존 검사도 통과했다. 실제 운영 저장소/로그/애플리케이션 DB는 변경하지 않았다.

Codex 2차 지적 반영: R1은 journal 선행 거절을 유지하고 두 writer 테스트를 성공/duplicate 또는 busy·변경0의 두 합법적 경로로 수정했다. R2는 SQLite 연결 전에 `os.open` 읽기 전용100바이트 헤더·fstat identity·magic·rollback read/write 버전1·user_version1·application_id를 확인하며, own/foreign WAL 파일 모두 SQLite.connect가 호출되지 않고 파일/부속 파일이 그대로임을 테스트했다. 헤더 위치는 [SQLite 파일 형식](https://www.sqlite.org/fileformat.html#the_database_header)과 대조했다. 연결 후에도 전체 schema 객체를 다시 검사하고 trusted_schema를 최초 schema 조회 전에 끈다. R3는 유한 배치를 EOF까지 검증한 뒤 기준 now를 한 번 채택하며 README도 실시간 스트림이 아닌 완료 배치로 정정했다. 테스트 clock은 주입할 수 있으나 CLI에서 기준 시각 옵션을 받지는 않는다. Windows mapped remote drive는 GetDriveTypeW로 추가 차단한다. POSIX 네트워크 마운트 감별과 공격자에 의한 동시 파일 교체의 완전 방어는 보장하지 않으며 운영자 전용 로컬 디렉터리가 전제다.

Codex 실제 구현/검증(2026-11-15): 별도 `etl.operation_logs`만 추가했고 기존 emitter/API/설정/DB/FE를 바꾸지 않았다. 실제 emit6종/11개 이벤트 round-trip, 임시 파일의 init·읽기 전용 hash 보존·수집/재수집·30일 경계±1µs·주 DB의 합성 UUID 제거·비정상 schema/sidecar/예약명·입력 상한·주입 오류/중단 rollback·동시 writer·실제 subprocess 잠금/CLI를 검증했다. 전체 일반2036 passed/Windows 링크 권한 관련1 skipped/PostGIS298 deselected, 기존 Starlette 경고1개다. ruff check/format413 files·mypy187 files 통과. 링크 테스트는 Linux CI에서 실행하고 PostGIS는 CI의 격리 DB로 실행한다. 실제 사용자/운영 로그나 인허가/통계 DB는 쓰거나 삭제하지 않았다. 이 결과는 Codex 실행이며 Claude가 직접 실행한 결과가 아니다.

Codex 구현 전 대조에서 다음을 보정했다. hot journal의 자동 복구는 소유권 확인 전에 파일을 바꿀 수 있으므로 기존 `-journal`도 열기 전에 `database_busy`로 거절한다. 복구가 필요하면 운영자가 별도 점검하며 이 CLI는 복구하지 않는다. 연결별 `trusted_schema=OFF` 등 비영속 설정은 dry-run에도 허용하지만 파일 설정/내용 변경은 없다. init/열기 전후에는 file identity를 비교하며 정상 동시 writer의 크기 변화까지 동일하도록 강제하지 않는다. Windows ADS/예약 장치명도 거절한다. 아래 1차 검토의 해당 권고보다 이 보정이 우선한다.

Claude는 이 MD만 Read/Edit한다. 코드/DB/Git/네트워크·다른 파일·서브에이전트 사용 금지다. Codex가 제공한 소스와 결과를 검토할 수 있으나 실제 실행한 것으로 표현하지 않는다. 검토의 수정 이유·보류와 PASS/REVISE를 이 문서에 직접 기록한다.

### 5.1 Claude Code 설계 검토 (2026-11-15)

검토 범위: 이 MD와 사용자가 메시지로 제공한 `app/core/operations.py` 소스만 읽었다. 코드·테스트·DB·Git·네트워크는 사용하지 않았고 아무것도 실행하지 않았다. 아래 판단은 설계 문서와 제공 소스 대조 결과다.

**원안 판정: REVISE** — 방향(허용목록 입력·전용 SQLite·명시 실행·30일 고정·배포 미완료 구분)은 적절하나, 그대로 구현하면 아래 결함이 생길 수 있어 본문을 직접 보완했다.

| # | 원안 문제 | 위험 | 반영 위치 |
|---|---|---|---|
| 1 | 시각 형식 미정. emitter는 `+00:00`이고 microsecond0이면 소수부 생략 | 정상 이벤트 거절 또는 문자열 비교 오류로 30일 경계 오판 | 2절 시각 항목, 정수 µs 저장 |
| 2 | 이벤트별 키 규칙이 추상적 | readiness success/reason 불일치, etl failed+reason 누락, counts만 있는 행 등 emitter가 만들 수 없는 행 저장 | 2절 이벤트별 규칙 |
| 3 | 허용 집합 복사 가능성 | v2 경로 등 emitter 변경과 불일치 | `operations` 상수 단일 출처 |
| 4 | `1e400`→inf, `-0.0`, float int | finite 검사 우회·hash 불안정 | 2절 파싱 항목 |
| 5 | 식별자 없는 이벤트의 hash 중복 | 동일 시각 동일 값의 실제 별개 시도가 합쳐짐 | 의도된 한계로 명시 |
| 6 | 분류 순서·상한 초과 처리 모호 | 건수 해석 불일치, 부분 저장 | 2절 분류 순서·전체 실패 |
| 7 | 변조 파일의 trigger/view 미언급 | prune/ingest 때 임의 SQL 실행 | 3.2 객체 집합 정확 일치·trusted_schema=OFF |
| 8 | Python 3.11 sqlite3 암묵 트랜잭션 | BEGIN IMMEDIATE가 의도대로 안 걸리거나 중첩 오류 | 3.2 isolation_level=None |
| 9 | secure_delete는 연결 단위 | 새 연결에서 꺼진 상태로 DELETE | 3.2 연결마다 설정·반환값 확인 |
| 10 | journal/wal 부속 파일 링크 | 링크를 따라 다른 위치에 기록 | 3.1 부속 파일 검사 |
| 11 | init 실패 시 정리 범위 | 남은 빈 파일로 재init 불가 또는 남의 파일 삭제 | 3.1 같은 inode만 정리 |
| 12 | TOCTOU·네트워크 경로 | 잠금 불신·교체 | 3.1 완화+운영 전제, UNC 거절 |
| 13 | argparse 오류가 경로를 출력 | 경로 노출 | 3.4 고정 메시지·exit2 |
| 14 | "30일 보관"의 의미 | prune 주기 전에는 30일 초과 잔존 | 3.4 최대 보관=30일+실행 간격 |
| 15 | 수집기 이전 단계 원본 | Render/파이프 원본은 통제 밖인데 완료로 오해 | 1절 배포 pending 명시 |
| 16 | 수집기 자신의 이벤트 출력 | 출력→입력 순환 | 2절 마지막 항목 |

유지한 결정과 이유:

- 입력은 stdin만, Render wrapper/syslog 어댑터는 후속 — 입력 표면을 가장 작게 유지한다.
- 미래 이벤트는 허용 오차 없이 거절하되 건수를 분리 — 임의 옵션 금지 원칙을 지키면서 시계 차이를 진단 가능하게 한다.
- 기간·기준시각 CLI 옵션 없음, 테스트만 clock 주입 — 원안 그대로 적절하다.
- 개별 잘못된 행은 건너뛰고 나머지 저장 — 전달 구간 오염 한 줄로 전체 수집이 막히지 않게 한다. 상한 초과·시스템 오류만 전체 rollback.
- 새 승인 절차는 추가하지 않았다. 임시 디렉터리의 구현·테스트는 되돌릴 수 있으며, 실제 운영/사용자 로그 삭제와 배포는 원안대로 범위 밖이다.

보류(구현 범위 밖, pending 유지): 실제 운영 저장소·전달 경로 선정, Render 로그 전달 연결, 주기 prune 스케줄링, 백업/스냅샷 만료, 누락률·지연 측정, Render 플랫폼 보관본 정책, 파일 단위 물리 소거(SSD·파일시스템 snapshot) 보장.

**수정본 판정: PASS** — 위 보완(2절·3.1~3.4·4절 추가 사례)을 구현과 테스트가 그대로 따르는 조건이다. Codex는 실제 구현 diff와 테스트 결과로 각 항목을 대조해야 하며, 이 검토는 실행 결과를 확인한 것이 아니다. 운영 30일 보관/삭제는 배포 대기로 남고 이 설계 승인으로 완료 표시하지 않는다.

### 5.2 Claude Code 구현 검토 (2026-11-15)

검토 범위: 이 MD, 메시지로 제공된 `app/core/operations.py`, `etl/operation_logs/{validation,archive,__main__}.py`, `tests/etl/test_operation_log_archive.py` 소스와 Codex 검증 요약만 읽었다. Claude는 아무것도 실행하지 않았다. 아래 "통과/실패" 언급은 Codex가 보고한 결과이며 Claude가 재현한 것이 아니다.

**판정: REVISE (경미)** — 허용목록·정확한30일 경계·event time 기준·중복 제거·schema 식별·트랜잭션/rollback·출력 비노출은 설계대로 구현됐다. 아래 R1~R3을 고치면 PASS다. 새 승인 절차는 요구하지 않으며 모두 되돌릴 수 있는 코드/테스트/문서 수정이다.

설계 대조 결과(적합):

- 입력 검증: 6종 이벤트의 정확한 필수/선택 키, `etl_run`↔`stage=import`, failed↔reason, counts↔quality_flags 쌍, `etl_quality` completed 6키/failed reason, readiness success=reason=="ok"가 emitter `_emit`/`_etl_record`/`population_quality`가 만들 수 있는 형태와 일치한다. 허용 집합은 `app.core.operations`에서 import하며 Literal도 `get_args`로 재사용한다(단일 출처). 중복 키·NaN 리터럴·`1e400`(isfinite)·`-0.0`(copysign)·bool/float의 int 오인·대문자 UUID·`Z`/다른 offset/naive/3자리 소수 거절, BOM/잘못된 UTF-8/깊은 중첩(RecursionError)도 `Rejected`로 수렴한다. `Record(repr=False)`·`Rejected from None`으로 원문이 예외/repr에 실리지 않는다.
- 시각: 정규식 fullmatch 후 `fromisoformat`, 정수 µs 저장, cutoff는 Python 계산값 바인딩. 만료 `event_us <= now-30d`, 미래 `> now`가 ingest/prune/status에서 같은 식이다. 수집 시각은 저장하지 않는다. 테스트가 cutoff·cutoff+1µs·now+1µs와 소수부 생략/µs 표기의 동일 hash를 다룬다.
- 경계/상한: `readline(4099)`로 `\r\n` 포함 4096 내용까지 정상, 초과는 청크로 버리고 rejected1, 버린 바이트도 총량에 합산, 10,000행/10MiB 초과는 DB 열기 전 `input_limit`로 삽입0. 분류 합=읽은 행 불변식을 트랜잭션 안에서 검사한다.
- SQLite: 정확한 `sqlite_master` 집합(autoindex는 이름 정확 일치, LIKE 미사용), application_id/user_version/journal_mode 확인을 트랜잭션 전·후 2회. `isolation_level=None`+명시 BEGIN IMMEDIATE, 연결마다 secure_delete=ON 반환값1 확인, temp_store=MEMORY, `mode=ro|rw`(rwc 없음), `as_uri()`로 `#`/`%` 경로 처리. 예외·KeyboardInterrupt는 `finally` rollback. prune은 count→DELETE→재집계 불일치 시 rollback이며 주입 실패 테스트가 있다.
- 경로: 절대·`.sqlite3`·UNC/장치·`..`·후행 점/공백·ADS 콜론·예약 장치명, 모든 상위 구성요소 lstat symlink/reparse(0x400), resolve 비교, 저장소 루트·`.git` 상위 거절, sidecar 링크/존재 거절, 0바이트/비정규 파일 거절, 열기 전후 (dev, ino) 비교, init O_EXCL·0600·같은 identity만 정리.
- CLI: stdout 고정 키 JSON1줄, `str(ArchiveError)`는 고정 사유뿐, sqlite 오류는 busy/locked→`database_busy`, 그 외 `database`, 미분류 예외 `operation_failed`; 인자 오류2·중단130·`--help`0(SystemExit 통과). 경로/원문/예외 문구 비출력 테스트가 있다.
- 배포 한계: 1절·3.4절·Codex 요약 모두 운영 저장소/전달/스케줄/백업/Render 보관본을 pending으로 두고 "최대 보관=30일+prune 간격"을 명시한다. 완료 과장 없음.

필수 수정(REVISE 사유):

| # | 문제 | 위험 | 요구 |
|---|---|---|---|
| R1 | `connect()`가 `validate_target()`에서 `-journal` 존재 시 즉시 `database_busy`를 낸다. DELETE journal에서 상대 writer가 INSERT/DELETE를 시작해 커밋 전까지 `-journal`이 존재하므로, 3.3의 "busy_timeout 안에서 기다림"이 실제로는 지켜지지 않는다. `test_two_writers_are_deduplicated`는 두 스레드가 모두 성공해야 하는데, 한 스레드의 검사 시점이 다른 스레드의 insert~commit 구간과 겹치면 `ArchiveError("database_busy")`로 예외가 나 **비결정적으로 실패할 수 있다**(Codex 실행에서 통과한 것은 창이 짧았기 때문일 수 있음). | CI 간헐 실패, 문서-동작 불일치 | 동작(사전 거절)은 hot journal 보호 근거로 유지한다. 3.3은 위에서 직접 정정했다. 테스트는 결과 집합을 `{두 실행 모두 성공(삽입1·중복1)}` 또는 `{한쪽 성공·다른 쪽 database_busy}`로 허용하고 어느 경우든 최종 행1·실패 쪽 변경0을 단언하도록 고친다. 자동 재시도는 추가하지 않는다. |
| R2 | 소유권 확인을 SQLite가 파일을 연 **뒤에** 한다. 다른 SQLite DB가 WAL 헤더(offset18/19=2)인 경우 `mode=rw` 열기·첫 읽기에서 SQLite가 `-wal`/`-shm`을 만들고 닫을 때 정리/checkpoint할 수 있어, `_owned` 거절 전에 남의 파일 디렉터리를 건드린다. 현재 테스트의 "other"는 비-WAL이라 이 경로를 다루지 않는다. | "기존 파일 보존" 위반 가능 | SQLite 열기 전에 파일 앞 100바이트를 일반 읽기로 검사한다: magic `SQLite format 3\0`, offset18/19==1(rollback journal), offset60 user_version==1, offset68 application_id==`APPLICATION_ID`(big-endian). 불일치는 `ownership`. 열기 후 `_owned` 검사는 그대로 유지한다. WAL 헤더 타 DB의 바이트·sidecar 미생성 테스트를 추가한다. |
| R3 | CLI가 `now`를 stdin을 읽기 **전**에 고정한다. 파이프 입력을 읽는 동안 기록된 이벤트가 `future`로 버려져, 2절이 의도한 "future=시계 차이 진단" 의미가 흐려진다. | 정상 이벤트 유실·오진단 | ingest는 입력을 EOF까지 읽은 뒤(잠금 전) `now`를 고정해 분류한다(테스트 clock 주입은 유지, 예: `now` 대신 clock 함수 전달). 만료 판정은 더 늦은 now라 보수적이다. 또한 README에 ingest는 **종료된 배치 입력용**이며 실시간 스트림 연결용이 아님(10,000행 상한 포함)을 적는다. |

권고(비차단, 후속 또는 이번 커밋 선택):

- `connect()`에서 첫 `_owned` 이전에 `PRAGMA trusted_schema=OFF`를 먼저 설정한다(현재 거절 결과는 같지만 순서상 안전).
- 잔존 hot journal(크래시 후)과 일시적 동시 writer를 모두 `database_busy`로 보고해 운영자가 구분할 수 없다. 영구 잔존 시의 점검 절차(다른 writer 없음 확인 후 SQLite 도구로 복구·백업)를 README에 적거나 고정 코드 `journal_present`를 분리한다.
- `initialize()`의 `finally` 안 `_identity(path)`가 `ArchiveError`를 던지면 원래 예외를 가린다. 정리 실패는 삼키고 원래 예외를 보존한다. 초기화 도중 강제 종료로 `-journal`이 남으면 재-init이 `exists`/`database_busy`가 됨을 README에 적는다.
- 상위 경로에 `.git`이 있으면 거절하므로 홈 디렉터리 dotfiles 저장소, OneDrive 등 reparse 속성 폴더, macOS `/tmp`(symlink) 아래 경로는 거절된다. 의도된 보수적 동작으로 README에 명시한다.
- `INSERT OR IGNORE`는 CHECK 위반도 무시해 duplicate로 셀 수 있으나 hash가 항상64자라 실질 영향은 없다. 기록만 한다.
- `test_init_failure_cleans_only_new_file`은 교체된 파일을 지우지 않는 분기를 검사하지 않는다. identity가 바뀐 경우 파일이 남는지 단언하는 사례를 추가하면 3.1 문구와 맞는다.
- DELETE journal은 커밋 시 원본 페이지(삭제 행 포함)를 담은 journal 파일을 unlink만 하므로 파일시스템 블록에 남을 수 있다. 3.2·3절의 물리 소거 비보장 한계에 이미 포함되어 있으며 canary 검사는 주 DB 파일 한정임을 결과 보고에서도 유지한다.

유지·수용한 Codex 보정: hot journal 사전 거절(소유권 확인 전 자동 복구 방지), identity만 비교(크기 미비교), dry-run의 연결 단위 `trusted_schema` 설정, 예약명/ADS 거절, `LOCK_TIMEOUT=1.0`초 고정은 설계 의도에 부합해 수용한다.

배포 상태: 이 구현은 운영자 로컬 CLI 기반이다. 실제 운영 저장소·Render 전달·주기 prune·백업 만료·누락/지연 측정은 **pending**이며, R1~R3 수정 후에도 "#72 원본30일 보관/삭제 완료"로 표시하지 않는다. 실제 사용자/운영 로그 수집·삭제는 이번 범위에서 요구되지 않는다.

**R1~R3 반영 조건부 PASS** — Codex가 수정 diff와 재실행 결과(특히 R1 테스트의 두 결과 분기와 R2의 WAL 헤더 바이트·sidecar 미생성)를 이 절에 대조 기록하면 PASS로 본다. Claude의 재실행 확인은 아니다.

### 5.3 Claude Code 최종 재검토 (2026-11-15)

검토 범위: 이 MD, 메시지로 제공된 최신 `app/core/operations.py`·`etl/operation_logs/{validation,archive,__main__}.py`·`tests/etl/test_operation_log_archive.py`·README 유한 배치 절과 Codex 검증 요약만 읽었다. Claude는 아무것도 실행하지 않았다. 아래의 통과 건수(일반2041 passed/1 skipped, 신규85사례 중 84통과·Windows 링크1 제외, ruff/format413·mypy187)는 Codex 보고이며 Claude가 재현한 결과가 아니다.

차단 항목 대조:

| # | 현재 소스 근거 | 판정 |
|---|---|---|
| R1 | `validate_target`의 `-journal` 사전 거절(`database_busy`)은 hot journal 보호로 유지되고, exists와 lstat 사이에 사라진 journal은 `FileNotFoundError`→`continue`로 정상 진행한다(`test_completed_writer_journal_disappears_during_preflight`). `test_two_writers_are_deduplicated`는 busy를 `None`으로 받고 `inserted` 합=1, `duplicate`(실패 쪽은1로 계산) 합=1, 최종 행1, 재수집 duplicate1을 단언하므로 "둘 다 성공(삽입1·중복1)"과 "한쪽 성공·한쪽 busy 변경0" 두 합법 경로를 모두 결정적으로 통과한다. 3.3 문구도 즉시 busy 가능성으로 정정돼 있다. 자동 재시도는 없다. | **해결** |
| R2 | 기존 파일은 `validate_target`→`_header`에서 `os.open`(읽기 전용, POSIX `O_NOFOLLOW`)·`fstat` identity 대조 후 100바이트를 읽어 magic, offset18/19=`\1\1`(rollback), offset60 user_version=1, offset68 application_id=`0x53504F4C`(big-endian)를 확인하며, 이는 `sqlite3.connect`보다 앞선다(`connect`·`ingest` 모두 경유). 위치는 SQLite 파일 형식 헤더 정의와 맞는다. `test_wal_header_rejected_before_sqlite_open`이 own/foreign WAL 모두 `sqlite3.connect`를 호출 불가로 바꾼 상태에서 status/prune `ownership` 거절과 디렉터리 전체 바이트·sidecar 불변을 단언한다. 열기 후 `trusted_schema=OFF`가 첫 `_owned` 앞에 오고 전체 schema를 트랜잭션 전후로 재검사한다(권고1도 반영). | **해결** |
| R3 | `read_input`은 EOF까지 파싱·버퍼링한 뒤 `datetime.now(UTC)`를 한 번 채택하고, CLI `ingest`는 `now`를 넘기지 않는다(prune/status만 시작 시각 사용 — 입력 대기 없음이라 적절). `test_clock_is_captured_after_input_eof`가 EOF 이전 시각 조회를 금지하는 clock으로 입력 시작 후 생성된 이벤트의 future=0·삽입1을 확인한다. README가 "완료된 유한 배치, 실시간 무한 스트림 아님"으로 정정됐다. CLI에 기준 시각/기간 옵션은 여전히 없다. | **해결** |

추가 확인(회귀 없음): 만료 `event_us <= now-30d`·미래 `> now`의 정수 µs 비교와 event time 기준, 분류 합=lines 불변식, 상한 초과 시 DB 열기 전 전체 실패, 출력 비노출·종료코드, 기존 파일 비생성/비덮어쓰기는 5.2 판단과 동일하다. Windows 원격 드라이브 `GetDriveTypeW` 거절이 추가됐고 POSIX 마운트의 로컬 여부·운영자 전용 디렉터리는 README에 명시된 신뢰 전제다. 적대적 파일시스템 교체 경쟁의 완전 방어는 주장하지 않으며 그 표현이 정직하다.

비차단 선택 정리(이번 PASS 조건 아님):

- `initialize()` `finally`의 `_identity(path)`가 `ArchiveError`/`OSError`를 던지면 원래 예외를 가린다. 정리 실패를 삼키고 원래 예외를 유지하면 더 깔끔하다(5.2 권고 잔존).
- identity가 바뀐 파일을 init 정리가 지우지 않는 분기의 테스트는 아직 없다(5.2 권고 잔존).
- `ingest`가 `validate_target`을 입력 읽기 전과 `connect` 안에서 두 번 호출한다. 앞의 호출은 stdin을 소비하기 전 빠른 실패 효과가 있어 유지해도 무방하다.
- 3.1의 "`-journal`은 쓰기 명령에서 SQLite에 맡긴다"·3.2의 "dry-run PRAGMA 설정 변경 없이" 문구는 5절 Codex 보정(사전 거절·연결 단위 `trusted_schema`만 허용)이 우선한다고 이미 적혀 있다. 원하면 본문 문구를 직접 맞춘다.
- 잔존 journal과 일시 writer가 같은 `database_busy`로 보고되는 점은 README의 "별도 점검·자동 복구 없음" 안내로 수용한다.

배포 상태: 독립 운영자 CLI 범위로만 판정한다. 실제 영구 저장소·Render 전달 어댑터·주기 prune 스케줄러·백업/스냅샷 만료·누락/지연 측정은 **pending**이며 이번 PASS의 조건이 아니고 완료로 표시하지 않는다. 최대 잔류는 30일+prune 간격이다. 실제 사용자/운영 로그 수집·삭제는 요구되지 않았고 수행되지 않았다는 Codex 보고를 그대로 기록한다.

**최종 판정: PASS** — R1~R3 차단 항목이 제공된 소스와 테스트에서 해소됐다. Claude의 실행 확인이 아닌 소스·결과 대조 판정이다.
