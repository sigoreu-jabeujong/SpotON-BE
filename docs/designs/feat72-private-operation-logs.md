# BE-35 개인정보 없는 운영 로그 기반 (#72)

- 작성일: 2026-11-12, 초기 기준 develop `981d17f`(상담 PR71 병합)
- 브랜치: feat#72-private-operation-logs
- 상태: Codex 설계 → Claude 이 MD만 실제 Read/Edit → Codex 최종 점검·구현
- AI PR69는 충돌을 해결한 c81b493의 CI를 재확인 중이다. 구현 전 최신 develop을 가져오며 공개 API/계산/DB/FE 계약을 바꾸지 않는다. BE-34 캐시는 별도다.

## 1. 원본·현재 상태·범위

로컬 원본 API v1.2 §6(13쪽)과 데이터 활용 v1.2 보관 정책(15쪽)을 직접 읽었다. 서버 로그는 시각·경로·상태·처리시간·익명 request_id, LLM은 호출횟수/성공 여부만 기록하고 주소·좌표·건물/층호·payload/응답·키를 제외하며 보관30일이다. 현재 코드에는 안전한 오류 타입 로그와 ETL stdout 결과가 있지만 요청/단계 운영 기록은 없다. 기존 httpx/httpcore INFO 억제·원문 없는 오류 처리·CLI 결과/트랜잭션을 보존한다.

이번 범위는 **애플리케이션의 안전한 JSON stderr 기록 기반**이다. 로컬 파일/DB 저장·로그 수집기/외부 전송·스케줄러는 추가하지 않는다. 원본30일 보관/삭제는 배포 로그 수집기의 설정과 검증이 필요한 후속이며 현재 구현 완료로 표시하지 않는다. 호스팅/수집기를 가정하거나 새로운 비밀값/자료를 요구하지 않는다. 후속 배포 단계에서 실제 저장 대상이 필요하면 사용자에게 요청한다.

## 2. 출력 경계와 실패 정책

`app/core/operations.py`의 전용 helper들이 고정 필드만 생성한다. 일반 dict 전체/args/kwargs/예외를 로그로 넘기는 공개 기능은 만들지 않는다. 각 helper는 원문을 변환/마스킹하는 대신 허용된 숫자·enum·서버 UUID만 선택한다. UTC ISO 시각과 monotonic 처리시간(ms)을 사용하고 NaN/Infinity는 내보내지 않는다.

한 줄 JSON을 stderr에 출력하고 기존 ETL stdout·반환값/exit code·API 응답/헤더를 바꾸지 않는다. thread lock으로 레코드 쓰기를 묶고 emit 구성/직렬화/I/O 실패는 버린다. 로그 오류 원문/traceback을 다시 출력하거나 주 작업을 실패시키지 않는다. 디스크 파일·메모리 이벤트 큐·원문 보관은 없다. 다만 동기 stderr의 느린 sink/백프레셔까지 무지연 보장하지 않는다. stdout/stderr 수집기에서 JSON 이벤트를 구분해야 하며 프로세스 전체의 임의 제3자 DEBUG 로그를 자동 정화한다고 주장하지 않는다.

기본 API 실행의 uvicorn.access 로거도 비활성화해 query/알 수 없는 원문 경로가 기존 access log에 중복 기록되지 않게 한다. 기존 --no-access-log 실행 안내를 유지한다. 배포자가 로그 설정을 다시 바꾸거나 proxy가 별도 access log를 만드는 경우는 별도 점검 대상이다.

## 3. API 이벤트

순수 ASGI middleware를 기존 CORS 바깥에 추가해 실제 전송된 응답을 관측한다. HTTP만 기록하고 lifespan/WebSocket은 통과시킨다. receive/body/header/query를 읽거나 버퍼링하지 않으며 송수신 순서/예외/취소는 보존한다.

- event=api_request, time, path, status_code, duration_ms, request_id, response_complete만 기록한다.
- path는 배포 코드의 고정 허용 목록(health/geocode/history/nearby/snapshot/data-range/activity/risk/interpret/support-links/docs/OpenAPI)에 속한 경로만 사용하고 다른 경로는 고정 unmatched다. raw_path/query_string·클라이언트 입력 경로를 그대로 기록하지 않는다. CORS/404/405도 안전한 표식을 쓴다. (Claude 검토 보강) 기록값은 요청 path 문자열 자체가 아니라 허용 목록에 정의된 **상수 문자열**이어야 하며, path parameter가 있는 라우트가 있다면 실제 값이 아닌 템플릿 상수로 기록한다. trailing slash 변형·대소문자·퍼센트 인코딩 변형은 unmatched 또는 같은 상수로만 정규화하고 원문을 남기지 않는다. docs/OpenAPI는 실제 노출 경로(/docs, /redoc, /openapi.json, oauth2-redirect 등)를 코드에서 확인해 목록에 맞춘다.
- request_id는 매 요청 서버 uuid4다. 사용자가 보낸 X-Request-ID/인증헤더/IP/업종/위치/본문 값은 읽거나 복사하지 않는다. 응답에 새 ID 헤더는 추가하지 않는다.
- status_code는 send가 성공한 http.response.start의 실제 코드다. 헤더 전 취소/연결 실패는 null이며 가짜499/500을 만들지 않는다. 마지막 response.body 전송 완료면 response_complete=true, 스트림 중 예외/취소/단절은 false다. 200 헤더 뒤 스트림 실패를 완전 성공으로 기록하지 않는다. ASGI 전송 완료이지 사용자의 다운로드 완료 보장이 아니다.
- 정상·안전한422/500·CORS·전송 중 실패·바깥 취소는 finally에서1회 기록한다. 기록 실패가 본래 오류/취소를 가리지 않게 한다.
- (Claude 검토 보강, 코드 미확인) Starlette/FastAPI는 `Exception`/500 핸들러를 사용자 middleware보다 바깥의 ServerErrorMiddleware에서 처리한다. 따라서 미처리 예외의 500 응답은 이 middleware가 send를 관측하지 못하고 status_code=null·예외 전파로 보일 수 있다. Codex는 실제 등록 순서에서 "안전한 500"이 관측되는 방식(앱 내부 핸들러로 응답되는지, 바깥 핸들러인지)을 확인하고, 바깥이라면 null을 그대로 두되 문서·테스트에 그 의미를 명시한다. 가짜 500을 채우지 않는 원칙은 유지한다.
- duration_ms는 middleware 진입부터 finally 시점(마지막 body send 반환 또는 예외/취소)까지의 monotonic 차이로 정의한다.

## 4. ETL 이벤트

6개 run_import(localdata/market_areas/market_stores/market_sales/market_changes/living_pop)에 공통 decorator를 적용한다. ContextVar의 서버 run_id/고정 source로 시작·완료/실패와 단계 이벤트를 묶고 finally에서 token을 복원한다. 독립/동시/중첩 실행의 context를 섞지 않는다. 외부 함수를 직접 호출한 단계에 부모 run이 없으면 임의 ID로 기록하지 않는다.

실제 코드 위치에 read_source/collect/preflight/transform/prepare/persist 단계 context를 두며 예외는 그대로 전파한다. persist 완료는 DB transaction context/commit이 끝난 뒤다. 실패를 성공·rollback 완료로 바꾸지 않는다. commit 뒤 dispose가 실패하면 persist 완료와 전체 import 실패가 모두 가능하다는 사실을 유지한다. 로그 때문에 transaction/lock/cleanup 순서를 바꾸지 않는다.

event=etl_run 또는 etl_stage, time, source, run_id, stage, status(started/completed/failed), duration_ms만 기본으로 쓴다. 완료 결과에서는 아래 허용 항목만 선택한다.

- counts: fetched/accepted/rejected_missing_key/rejected_non_seoul/duplicates/transformed/affected/request_count/source_rows/rows/excluded_rows/inserted/repaired/grid_rows/inserted_grids. bool 아닌 유효 범위의 비음수 int만 보존하고 없는 값은0으로 만들지 않는다.
- quality_flags: 현재 정제 코드의 고정 품질 사유 allowlist에 속한 건수만. 서로 겹칠 수 있는 플래그를 합산해 최종 제외 수라고 하지 않는다. 새 사유는 검토 후 allowlist에 추가한다.
- batch_id는 인허가 결과의 실제 UUID가 있을 때만, version_id는 다른 불변 버전 결과의 UUID가 있을 때 별도 필드다. run_id를 DB 배치ID로 오인시키지 않는다. mode는 write/dry_run만 허용한다.

파일 경로/이름·원문 행·상호/주소/좌표·원문 에러·임의 flags키·code_check 원문·CSV 값·버전 UUID 아닌 임의 문자열은 기록하지 않는다. 실패는 고정 operation_failed 사유만 사용하며 상세 원문을 꺼내지 않는다. 기존 stdout 결과/검증 보고서와는 구분한다. localdata의 argparse 오류는 입력을 echo하는 기존 stderr 대신 고정 메시지로 바꾸되 SystemExit(2)/정상 help·stdout 결과를 보존한다.

## 5. LLM 시도 이벤트

GeminiClient._post의 실제 client.post 시도를 finally로 관측한다. event=llm_http_attempt, time, count=1, success(HTTP200을 관측했는지)만 쓴다. timeout/네트워크/취소도 시도1건·성공false이며 원래 예외/취소를 전파한다. 키 미설정/요청 한도에서 post 전에 중단되면0건이다. 공급자 내부 재시도는 각각1건으로 집계한다. HTTP200이어도 파싱/최종 AI 검증은 실패할 수 있으므로 이를 AI 해석 최종 성공률로 표시하지 않는다. 최종 공개 API 결과는 API 상태 로그와 구분한다. 실제 모델/키/URL/프롬프트/출력/token/오류 원문은 기록하지 않는다.

## 6. 대상·검증

core/operations.py·operational ASGI middleware·main 등록/기존 access log 비활성화, Gemini _post의 관측 finally, ETL decorator/단계 context·localdata safe parser, 관련 테스트와 BE README/CLAUDE/작업계획이 대상이다. DB 모델/migration·의존성·실제 .env/Docker·FE·외부 원본은 바꾸지 않는다. 공개 API/응답 계약이 없어 새 FE 변경 보고서는 불필요하다.

테스트는 실제 ASGI 정상/422/500/CORS/404·주소/좌표/URL path·본문/헤더 canary 비노출, 사용자 request_id 무시·동시 ID 격리, streaming 예외/취소/전송 실패·완료여부/실제코드, stderr 장애에도 응답 보존을 검증한다. ETL은 실제 인허가 합성 snapshot dry-run·6개 decorator/실패/원래 stdout·고정 parser 오류·허용 숫자/플래그/UUID만·context 복원/중첩·commit 후 로그 순서를 확인한다. Gemini는 mock transport로200/429 재시도/timeout/취소/키없음의 실제 시도 수와 원문 비노출을 대조하고 실모델은 호출하지 않는다.

전체 일반pytest·ruff/format/mypy·실제 로컬 uvicorn HTTP/JSON stderr 확인·실제 .env 비밀값 검사·FE 변경0을 확인한다. SQL/계산 변경이 없으며 개발 DB에 파괴적 테스트/적재하지 않는다. CI의 격리 PostGIS 전체 회귀도 확인한다. 지정 PR/CI/CodeQL 성공 후 일반 Squash 병합·이슈 종료·최신 develop 반영을 확인한다. 30일 보관/삭제·프록시 로그/외부 수집기 정책은 검증하지 않았다고 명시한다.

## 7. Claude 검토 요청

이 MD만 Read/Edit한다. 코드/다른문서/Git/DB/.env/네트워크 금지. 원본/코드를 읽지 않은 한계를 명시하고 필드 allowlist·경로/UUID/동시성·취소/스트리밍의 실제상태·ETL commit/집계/실패·LLM 시도 정의·sink 실패/보관30일의 범위·테스트 누락을 검토해 §8에 기록한다. 필요한 본문 수정은 근거와 함께 이 파일에만 한다. Codex가 실제 코드와 최종 대조한다.

## 8. Claude 검토 결과 (2026-11-12)

### 8.0 검토 범위·한계

- 이 MD 한 파일만 Read/Edit했다. 원본 PDF(API v1.2 §6, 데이터 활용 v1.2), 실제 코드, 테스트, README/CLAUDE, Git 이력, DB, .env, 네트워크는 **보지 않았다**. 아래 지적은 문서 내 논리와 ASGI/Starlette/uvicorn/argparse/contextvars의 일반 동작 지식에 근거한 것이며, 실제 코드와의 일치 여부는 Codex가 최종 대조해야 한다.
- 원본 요구사항(필드·30일 보관)의 문구는 §1의 요약을 그대로 신뢰했다.
- 본문 수정은 §3에 두 곳(경로 상수/템플릿, ServerErrorMiddleware 500·duration 정의)만 "Claude 검토 보강"으로 표시해 추가했다. 나머지는 권고로만 남긴다.

### 8.1 필드 allowlist

- 적절: API·ETL·LLM 이벤트 모두 고정 필드만 쓰고, 원문 변환/마스킹이 아니라 "허용값 선택" 방식인 점은 누출 위험이 가장 낮은 설계다. 일반 dict/args/예외를 받는 공개 API를 두지 않는 것도 맞다.
- 권고: allowlist 밖의 key가 들어오면 조용히 버리고, 값 타입 검사(bool 제외 비음수 int, 유한 float, enum, UUID)를 helper 내부에서 강제한다. quality_flags는 key도 고정 allowlist여야 하며 값만 검사하면 안 된다(임의 key 자체가 원문을 담을 수 있음).
- 권고: version_id/batch_id는 `uuid.UUID(str)` 파싱 후 정규화된 문자열로만 출력하고, 파싱 실패 시 필드를 생략한다.
- 권고: 레코드 전체 크기 상한(예: 수 KB)을 두면 비정상 counts 폭증에도 한 줄 쓰기가 안정적이다.

### 8.2 경로/UUID/동시성

- 경로: 허용 목록 매칭 후 **상수 문자열**을 기록해야 한다(§3 보강). path parameter 라우트가 있으면 템플릿 상수로 기록. 이것이 지켜지지 않으면 "주소/좌표가 path에 들어간 요청" canary 테스트가 핵심 방어선이 된다.
- request_id: 요청 지역변수의 uuid4로 충분하며 ContextVar 공유가 불필요하다. 사용자 X-Request-ID 무시는 적절.
- ETL ContextVar: asyncio task는 생성 시 context를 복사하지만 **ThreadPoolExecutor/스레드에서 실행되는 단계는 run_id를 상속하지 않는다**. 해당 단계는 §4 규칙상 "부모 run 없음 → 기록 안 함"이 되어 이벤트가 조용히 사라질 수 있다. Codex는 ETL에 스레드 실행이 있는지 확인하고, 있다면 `contextvars.copy_context().run` 사용 또는 해당 단계 비기록을 명시해야 한다.
- 중첩 run: run_import가 다른 run_import를 호출하는 경우 새 run_id를 발급할지, 부모를 재사용할지 문서에 정해져 있지 않다. 권고는 "자식은 새 run_id, 종료 시 token reset으로 부모 복원"이며 테스트로 고정한다.
- 멀티 프로세스: thread lock은 uvicorn `--workers`/여러 프로세스 간 줄 섞임을 막지 못한다. 레코드당 **단일 write 호출(개행 포함) + flush**로 쓰면 작은 줄은 실무상 섞임이 거의 없지만 보장은 아니다. 문서에 "프로세스 간 원자성은 보장하지 않음"을 명시하길 권한다.

### 8.3 취소/스트리밍의 실제 상태

- status_code=send 성공한 response.start 기준, 헤더 전 실패는 null, response_complete는 `more_body=False`인 마지막 body send가 예외 없이 반환된 경우만 true — 정의가 정확하고 과장(다운로드 완료 보장)을 하지 않는다.
- 주의(§3 보강): 미처리 예외의 500은 바깥 ServerErrorMiddleware가 보내므로 이 middleware에서는 status=null로 보일 가능성이 높다. "안전한 500" 테스트 기대값을 실제 구조에 맞게 정해야 한다.
- 주의: `asyncio.CancelledError`는 BaseException이므로 finally 기록 중 `except Exception`만으로 처리하면 기록 함수 내부 취소를 놓친다. 기록 helper는 동기·비대기(await 없음)로 두어 finally 안에서 재취소 지점이 없게 한다.
- 주의: HEAD 요청·204/304 등 body 없는 응답도 Starlette는 빈 body 메시지를 보내는지 확인 후 response_complete 정의가 맞는지 테스트한다.
- lifespan/WebSocket 통과는 테스트 목록(§6)에 명시되어 있지 않다(누락, 8.7 참조).

### 8.4 ETL commit/집계/실패

- persist 완료를 commit 이후로 두고, dispose 실패 시 "persist completed + run failed" 공존을 허용한 것은 사실과 맞다. 로그 때문에 transaction/lock 순서를 바꾸지 않는 원칙도 적절.
- 권고: rollback 경로에서 persist는 failed만 기록하고 "rollback 완료" 같은 상태를 만들지 않는다(문서와 일치).
- 집계: 없는 값을 0으로 채우지 않는 것과 겹치는 quality_flags를 합산하지 않는 것은 정확하다. 수집기/대시보드 쪽에서도 합산하지 않도록 README에 한 줄 경고를 권한다.
- argparse: 기본 `error()`는 `invalid choice: '<입력>'` 등으로 입력을 stderr에 echo한다. `ArgumentParser.error` 오버라이드로 고정 메시지+`sys.exit(2)`가 맞고, `--help`(exit 0, stdout)는 유지된다. 하위 parser(subparsers)가 있다면 동일 클래스로 생성되는지 확인해야 한다.
- 실패 사유: 고정 operation_failed만 쓰는 것은 안전하지만 운영 구분력이 낮다. 필요하면 예외 **클래스명**이 아닌 고정 enum(예: source_read/db/validation)을 후속으로 검토한다. 이번 범위에서는 현행 유지가 맞다.

### 8.5 LLM 시도 정의

- "client.post 실제 시도 1건 = 이벤트 1건, success = HTTP 200 관측"은 명확하고, 파싱/최종 검증 성공과 구분한 점이 적절하다.
- 주의: "공급자 내부 재시도는 각각 1건"은 **애플리케이션 코드가 _post를 여러 번 호출하는 재시도**에만 성립한다. httpx transport의 `retries` 같은 하위 계층 재시도는 client.post 1회로 보이므로 별도 집계되지 않는다. 문서 문구를 "애플리케이션 재시도 각 1건, transport 내부 재시도는 미구분"으로 해석해야 한다.
- 주의: client.post 호출 직전 요청 구성 단계에서 예외가 나면(예: URL/헤더 구성) 실제 전송이 없어도 시도 1건·false로 집계될 수 있다. 허용 가능하나 의미를 테스트/문서에서 고정한다.
- 원 요구사항의 "호출횟수"는 이벤트 수를 수집기에서 합산해야 얻어지며, 이번 범위에는 집계 저장이 없다.

### 8.6 sink 실패·보관 30일 범위

- emit 실패를 삼키고 traceback을 재출력하지 않는 정책은 적절하다. 단, `logging` 모듈 Handler를 쓰면 기본 `handleError`가 stderr에 traceback을 출력하므로 직접 write를 쓰거나 `logging.raiseExceptions=False`/handleError 오버라이드가 필요하다.
- stderr가 닫힘/BrokenPipe/None(`pythonw`, 일부 서비스 실행)인 경우도 무시 대상에 포함해 테스트한다.
- 동기 stderr 백프레셔 무지연을 보장하지 않는다는 한계 명시는 정직하며 유지한다.
- uvicorn.access 비활성화: uvicorn은 Config 생성 시 logging을 구성한 뒤 앱을 import하므로 import 시점 비활성화가 대개 유지되지만, `--log-config`/dictConfig 재적용·`--reload`·gunicorn 워커 실행에서는 덮어쓰일 수 있다. 실제 로컬 uvicorn 확인(§6)에서 access 줄이 없는지 눈으로 검증해야 한다. uvicorn.error의 "Invalid HTTP request" 경고 등 다른 로거는 이 범위 밖임을 유지한다.
- 30일 보관/삭제는 구현 완료로 표시하지 않고 후속 배포 단계로 남긴 범위 설정이 맞다. README/작업계획에 "원본 30일 보관 요구는 미충족(수집기 설정 필요)"을 명시해 완료로 오인되지 않게 해야 한다.

### 8.7 테스트 누락 권고

§6 목록에 다음을 추가하길 권한다.

1. lifespan·WebSocket 통과(이벤트 미기록, 동작 불변).
2. path parameter/trailing slash/퍼센트 인코딩/대소문자 변형 경로가 상수 또는 unmatched로만 기록되는지.
3. 미처리 예외 500에서 실제 관측되는 status_code(null 여부)와 응답 본문 보존.
4. HEAD·body 없는 응답의 response_complete.
5. stderr가 None/닫힘/BrokenPipe/write 예외일 때 응답·ETL 결과·exit code 보존 및 traceback 미출력.
6. NaN/Infinity·bool·음수·거대 int·비UUID 문자열·allowlist 밖 key 입력 시 필드 생략.
7. ETL 단계가 스레드에서 실행될 때 run_id 전파 여부(해당 시), 중첩 run의 run_id 분리·복원.
8. argparse 하위 parser·invalid choice에서 입력 미echo, `--help` exit 0.
9. LLM 요청 구성 단계 예외의 집계 의미, transport 재시도 미구분 확인.
10. uvicorn 실제 실행에서 access log 미출력(가능하면 `--reload` 포함).

### 8.8 결론

설계 방향(고정 필드 선택, 원문 무기록, 실패 무해화, 30일 보관 범위 제외)은 원 요구사항 요약과 일치하며 구현 진행에 동의한다. 구현 전 Codex가 실제 코드에서 확인할 핵심은 (1) 경로를 상수/템플릿으로 기록하는지, (2) 500 처리 위치에 따른 status_code 관측값, (3) ETL 스레드·중첩 실행 시 ContextVar 동작, (4) uvicorn access log 비활성화가 실제 실행 방식에서 유지되는지 네 가지다. 이 검토는 코드를 읽지 않은 문서 검토이므로 위 항목은 사실 확정이 아닌 확인 요청이다.

## 9. Codex 최종 점검·결정

Claude 실제 수정 diff 전체와 JSON(is_error=false,5turns,permission_denials=[])을 읽었다. 그 사이 PR71·PR69가 최신 CI/CodeQL 성공 후 일반 Squash 병합되어 실제 구현 기준은 develop `e3ebddc`다. 최신 코드를 가져왔으며 첫 설계의 미병합 상태는 당시 기록이다.

실제 앱에는 CORS 안쪽의 UnhandledErrorMiddleware가 응답 전 예외를 안전한500으로 바꾸므로 정상 경로에서 실제500을 관측한다. 별도 ASGI 앱/바깥 미들웨어의 예외는 관측 전이면null 그대로이며 둘을 테스트한다. 경로는 허용목록의 상수 값만 선택하고 docs/redoc/oauth2-redirect도 실제 등록값을 확인한다. middleware는 receive를 감싸지 않고 전송 성공 후 상태/완료를 기록한다.

ETL 단계는 현재 coordinator의 순차 함수에만 두므로 LocalDataClient의 내부 ThreadPoolExecutor에 context를 전달할 필요가 없다. worker 내부 단계/요청별 로그는 이번 범위가 아니며 미래 thread 계측에는 copy_context 등이 필요하다. 중첩 import는 새run_id를 발급하고 종료 시 부모를 복원한다. JSON은 최대4096 UTF-8 bytes·개행 포함 단일 write+flush·프로세스내 lock이며 프로세스 간 원자성은 보장하지 않는다. logging.Handler 대신 직접 stderr를 쓰고 I/O/직렬화 오류는 재출력하지 않는다. 로거 재설정/프록시 등 제3자 전체 로그·보관30일은 범위 밖이다.

batch/version UUID는 파싱·정규화 후 유효할 때만 넣고 타입/키/건수를 모두 제한한다. 없는 값/비유한값/범위 밖 정수는 버리거나 미확인null로 두며 사실처럼0으로 채우지 않는다. localdata에 subparser는 없고 고정error·help/exit 동작을 보존한다. LLM 집계는 애플리케이션 client.post 시도 기준이며 transport 내부 재시도/실제 공급자 도달·최종 AI 검증은 미구분이다. 이 범위를 문서와 테스트에 고정한다. 추가 실모델 호출·개발 DB 쓰기는 하지 않는다.
