# 운영 상태 검사 500 추적과 동시 검사 안정화 (#124)

- 작성일: 2026-11-14 (Asia/Seoul)
- 기준: develop046c06f, 작업 브랜치feat#124-readiness. 현재 Render live8958ba7·풀1은 #122 결과를 따른다.
- 사용자 요청: 다음 단계 진행. #122의 경로 미확정500 추적, 한식 보정 근거/FE 요청 정리, AI 비활성 유지.

## 1. 범위와 실제 관측

과거19:12:21/19:12:51 KST의 두500을 Render app 로그에서 다시 확인했다. 동일 구간 request 로그는 API200·0행·hasMore=false여서 이 수단으로 원래 경로를 복구할 수 없다. 현재 Render healthCheckPath는/api/ready다. 두 건의 실제 경로·원인을 확정하지 않는다.

현재 소스의 ReadinessProbe는 캐시가 만료된 상태에서 한 검사가 실행 중이면 다른 호출자에게 즉시false를 반환한다. DB 정상 검사를 Event로 진행 중에 고정한 실제 TestClient 재현에서 검사 주도 요청200·동시 요청500, DB 검사 실행1회였다. 두 요청의 로그 경로는 모두unmatched였다. 이는 과거 두 건과 구분한 **현재 코드의 재현 가능한 결함**이다.

## 2. 변경·보존 조건

- /api/ready 경로를 고정된 운영 로그 allowlist에 추가한다. query/header/body/원시 경로를 기록하지 않고 기존 api_request 필드/오류 외피는 유지한다.
- 단일 검사 결과를 같은 실행에 합류한 요청자가 제한 시간 안에서 함께 기다리게 한다. 아직 끝나지 않은 검사나 만료된 성공 캐시를200으로 바꾸지 않는다. 실제 실패는 모든 참여자에게false/HTTP500으로 전달한다.
- SQL750ms·HTTP2.5초·성공10초/실패1초TTL·별도DB연결 최대1·reader/전체 연결 예산·조회 역할/권한·no-store·공통 응답은 유지한다. 풀·쿼리·DB/schema/인덱스·로컬.env·FE·AI 설정은 변경하지 않는다.
- 예기치 않은 장애를 식별할 최소 진단은 고정된 사유 enum·성공/실패·시간만 기록한다. 연결 URI·host·role 원문·SQL·예외 문자열·실제 revision·원시 공급자 응답을 기록하지 않는다. logger 장애는 probe 결과를 바꾸지 않는다.
- 기존 사용자 checkout/untracked 문서는 보존하고 별도 worktree에서 수행한다. #120/PR121 기본값 변경은 포함하지 않는다.

## 3. 동시성 설계

상태 잠금과 검사 실행을 분리한다. 잠금 안에서는 closed·캐시·현재Future[bool]를 선택/생성하는 짧은 상태 전이만 수행한다. 현재 실행이 없으면 한 호출자가 검사 주도자가 되고, 나머지는 그 **실행별 Future**를 공유한다.

주도자는 잠금을 놓고 기존 DB 검사를 수행한다. 연결이 닫힌 뒤 잠금 안에서 현재 결과·TTL을 갱신하고 Future에bool 결과를 게시한다. 같은 Future에 합류한 요청자는 결과/제한시간만 기다리며 DB 연결을 만들지 않는다. 다음 실행의 결과를 잘못 받아들이지 않도록 전역 마지막 값 대신 자기 Future의 결과를 사용한다.

참여자의 check 대기는 PROBE_TIMEOUT_SECONDS(2.5초) 이하다. 대기 한도는 check 진입 시각 기준 deadline에서 남은 시간으로 계산하고(매 대기마다 2.5초를 새로 주지 않음), 시간 초과 시 False를 반환한다. 기존 라우터의 asyncio.wait_for도 전체HTTP2.5초를 제한한다. HTTP 취소/타임아웃은 실제 검사 스레드를 강제로 종료하지 않고, 진행 중 Future를 유지해 후속 요청이 추가 연결을 만들지 않게 한다. 한 요청자의 취소가 공유 Future를 취소하지 않는다. 이를 위해 Future 생성 직후 잠금 안에서 `set_running_or_notify_cancel()`로 RUNNING 상태로 만들어 `cancel()`이 실패하게 하고, 공유 Future를 `asyncio.wrap_future`로 직접 감싸 wait_for에 넘기지 않는다(감싼 asyncio Future 취소가 원본 `cancel()`을 호출함). 라우터에서 직접 기다리는 형태로 바꾸려면 반드시 `asyncio.shield`를 거친다.

Future 완료 권한은 **잠금 안에서 `self._current is future`를 확인하고 `_current`를 비운 쪽 하나**만 가진다. 주도자는 이 확인을 통과하고 closed가 아닐 때만 결과·TTL 시각을 갱신한다. 실제 `set_result`와 진단 로그는 잠금 밖에서 수행한다(완료 콜백·stderr 쓰기를 상태 잠금 아래 두지 않음). 완료 권한을 잃은 쪽은 `set_result`를 호출하지 않으므로 InvalidStateError가 생기지 않는다.

close는 상태 잠금 아래closed를 설정하고 진행 중 Future의 완료 권한을 가져와(위 규칙) 잠금 밖에서 false로 완료해 대기자를 깨운다. close 이후 check는 캐시·Future를 보지 않고 즉시false이며 새 검사를 시작하지 않는다. 주도자가 나중에 끝나도 이미 완료된 Future에 다시 게시하지 않으며 성공 캐시를 복원하지 않는다. 검사 예외(Exception)는 internal_error·false로 완료하고 상태를 정리한다. BaseException은 Future를false로 완료·`_current` 정리 후 재전파한다(try/finally). 예외 원문은 로그에 넣지 않는다.

## 4. 제한된 진단 설계

실제 DB probe 실행당readiness_probe 이벤트1개를 기록한다. 고정 reason 후보는ok/configuration_missing/configuration_invalid/database_error/query_cancelled/connection_limit/revision_mismatch/unsafe_role/internal_error다. 실패 원인 코드는 진단용이며 외부 API 응답/오류 코드를 추가하지 않는다. SQLSTATE57014는 query_cancelled로만 분류하며 반드시 SQL statement_timeout이라고 단정하지 않는다. connection_limit은 **조회 역할의 rolconnlimit이 연결 예산 미만(무제한 -1 포함, 기존 거부 동작 유지)**인 경우만 뜻하고, 서버 측 연결 초과(SQLSTATE53300 등)는 database_error로 분류한다. revision_mismatch는 실제/기대 revision 값을 기록하지 않는다. 이벤트 필드는 event·time·path("/api/ready" 고정)·reason·success·duration_ms로 고정하고 request_id는 넣지 않는다(여러 요청이 한 실행을 공유함).

검사 결과를 검증하는 코드에서 사유를 결정하고 시간/enum만 로깅한다. 실제 DB 연결을 열지 않은 캐시 적중/참여자마다 같은 probe 이벤트를 중복 생성하지 않는다. HTTP 타임아웃은 API 로그 duration과probe 완료 이벤트를 구분해 해석하며 probe ok를 해당HTTP200으로 오인하지 않는다.

## 5. 회귀 검증·완료 기준

- 정상 검사를 진행 중에 고정하고 여러 호출자가 검사 종료 전에는 완료되지 않으며, 종료 후 모두true/HTTP200·실행1회인지 확인한다.
- 실제 검사 실패는 모두false/500, 만료 전 성공 캐시 재사용과 성공10/실패1초 만료 후 새 검사, 오래된 성공이 새 실패/미완료를 숨기지 않는지 확인한다.
- 참여자 시간 제한·HTTP 취소 후에도 실제 검사1회/추가연결0·다음 호출이 실행에 합류하는지, close가 대기자를 깨우며 늦은 성공을 거부하는지 확인한다. 예외 경로도 대기자가 남지 않는지 확인한다.
- 로그는/api/ready의200/500을 식별하고 path 변형은 계속unmatched다. 원문 canary/URI/예외가 로그/응답에 없고 logger 장애 시 결과는 동일한지 확인한다.
- ruff/format/mypy·일반pytest·일회용 PostGIS 통합 및 CI/CodeQL을 실행한다. 기존 로컬 개발DB와 Render 데이터는 쓰지 않는다.
- 검증/병합한commit만 현재 Free에 수동 배포한다. 배포 전 live·env 해시·진행 중 배포 부재·pool1/SQL10초/예산8을 확인하고 다른 설정은 보존한다. 실패 시 이전8958ba7로 재배포해 복구한다.
- 배포 후 ready 동시 요청·느린 실제 검사/실패를 강제한 검증용 앱(모의 DB)·업무 GET5개 묶음·본문동등성·CORS/AI503을 구분해 검사한다. 실제 Render DB를 중단하거나 권한/스키마를 깨뜨려 실패를 강제하지 않는다. 물리절전/모든500 해결로 확대하지 않는다.

## 6. 한식·FE·AI 후속

제보18곳의 정확한 명단·당시 월/필터를 사용자에게 비동기로 요청했다. 기다리는 동안 오류 작업은 계속한다. 현재13개는 상호 조사 후보이며 자동 제외 근거가 아니다. 보정에는source+license_no·원본상호/업태/배치·별도 실제업종 확인 근거·확인일·검토상태·버전이 필요하다. 재적재로 근거가 달라지면 재검토하고 목록과모든공통집계/캐시/메타를 일치시키는 별도 정책을 검토한다. 이번 작업에서 원본을 덮어쓰거나 임의 제외하지 않는다.

FE에는 최신 전달MD의브라우저 재검증·CI test 단계 추가 요청을 유지한다. FE 저장소/CI/배포와 직접 메시지 전송은 하지 않는다. 실제 AI 시연 선택은 미확정이므로 키 미설정503을 유지한다.

## 7. 실제 Claude Code 검토

2026-11-14 Claude Code 설계 검토. 지정 소스Read와 이 MD Edit만 수행했다. 구현·테스트·DB 검증은 실행하지 않았다. 재현 결과는 Codex 보고를 근거로 하며 직접 재현하지 않았다.

- 검토 파일: app/services/readiness.py, app/routers/health.py, app/core/operations.py, app/core/request_logging.py, app/db/dependencies.py, app/main.py, tests/test_render_runtime.py, tests/test_operation_logs.py.
- 소스 확인: readiness.py:64-65가 잠금 획득 실패 시 즉시False → health.py:40-41 AppError500. API_PATHS(operations.py:37-54)에 /api/ready가 없어 request_logging.py:32에서 unmatched로 기록된다. 재현 주장과 소스가 일치한다. 과거 두500과의 인과는 이 MD에서도 주장하지 않는다.
- 차단(이 MD 3·4절에 반영): ① 수동 생성 concurrent Future는 PENDING이라 `cancel()`이 성공하고, `asyncio.wrap_future`를 wait_for에 넘기면 한 요청의 타임아웃이 공유 Future를 취소해 다른 참여자가 CancelledError를 받는다 → RUNNING 전환·shield 의무화. ② close와 늦은 주도자 완료가 경합하면 이중 set_result(InvalidStateError) 또는 close 후 캐시 복원 가능 → "`_current` 동일성 확인·비운 쪽만 완료" 규칙. ③ 참여자 대기 한도를 대기 시점마다 2.5초로 두면 HTTP 응답 후에도 스레드가 남는다 → 진입 시각 deadline 기준. ④ connection_limit 사유의 의미가 모호했다 → rolconnlimit 정책 실패로 한정.
- 주의: 참여자는 asyncio 기본 executor 스레드를 최대 2.5초 점유한다. Render healthCheck 빈도에서는 수용 가능하나 대량 동시 ready는 스레드 포화를 부를 수 있으며 범위 밖으로 둔다. 주도자 검사 자체는 connect_timeout=1·SQL750ms 외에 DNS/다중 host로 2.5초를 넘을 수 있고, 그 경우 HTTP는 500이지만 주도자 결과는 closed가 아니면 캐시에 반영된다(완료 시각 기준 TTL). `patch("app.routers.health.PROBE_TIMEOUT_SECONDS")`는 서비스 대기 한도를 바꾸지 않으므로 테스트에서 서비스 상수도 별도로 다룬다. 현재 `_probe`가 잡지 않는 예외(KeyError·URL 파싱 등)는 지금 UnhandledErrorMiddleware 500이고, 변경 후에는 internal_error·AppError500으로 바뀐다(상태 코드 동일, 외피는 공통 오류). 로그는 Future 게시 후·잠금 밖에서 남겨 logger 지연이 대기자를 늦추지 않게 한다.
- 동의: 상태 잠금/검사 실행 분리, 실행별 Future로 다른 세대 결과 오인 방지, 미완료/만료 성공의200 금지, 실패 전원 전달, SQL750ms·HTTP2.5초·TTL10/1초·별도 연결 최대1 유지, 캐시 적중·참여자의 probe 이벤트 미생성, 고정 enum·시간만 기록, /api/ready allowlist 추가(변형 경로는 unmatched 유지).
- 필수 회귀 기준(5절에 추가 적용):
  1. 기존 `test_probe_single_flight_does_not_open_extra_connection`의 `assert not probe.check()`는 새 계약과 충돌하므로 "검사 종료 전 미완료, 종료 후 True·실행1회"로 교체한다.
  2. 참여자 하나가 시간 초과/HTTP 취소돼도 공유 Future는 `cancelled()`가 아니고 다른 참여자는 실제 결과(True)를 받는다.
  3. close를 검사 중 호출하면 대기자는 즉시False, 이후 주도자 True 완료는 예외 없이 무시되고 캐시·`_current`가 갱신되지 않으며 close 후 check는 실행 없이False.
  4. `_probe`가 Exception·BaseException(예: KeyboardInterrupt 대용 사용자 정의 BaseException)을 내도 대기자가 deadline 전 False로 깨어나고 `_current`가 비며, BaseException은 재전파된다.
  5. A 실행 완료 직후 B 실행이 시작돼도 A 참여자는 A 결과만 받는다(A 실패·B 성공 및 반대 조합).
  6. 성공 캐시 만료 후 새 검사가 진행 중이면 동시 호출은 오래된 True가 아니라 새 실행 결과를 기다린다.
  7. readiness_probe 이벤트는 실행당 1개·필드 집합 고정이며, canary를 넣은 URI/예외 메시지/revision 값이 로그·응답에 없고 stderr 장애 시 결과가 같다. `/api/ready/`·`/API/READY`는 unmatched.
  8. 상태 잠금 안에서 `_probe`·`_emit`·`set_result`가 호출되지 않음을 잠금 보유 여부 검사(예: 패치한 함수 안에서 `_lock.locked()` 확인)로 확인한다.

결론: 위 차단 4건을 이 MD에 반영한 조건으로 구현 진행에 동의한다. 반영본은 Codex가 직접 대조한 후 구현한다.

## 8. 구현·검증·최종 판단

### 8.1 Codex 구현 판단과 로컬 검사

- 실제 Claude CLI 검토는 exit0·오류false·권한 거절0으로 완료됐고 MD 직접 수정을 대조했다. RUNNING Future·진입 deadline·잠금 밖 완료/로그·실행별 결과·close 소유권·connection_limit 의미를 채택했다. 라우터는 기존to_thread/wait_for를 유지하여 asyncio.wrap_future/shield를 도입하지 않는다.
- `_probe`는 내부적으로bool 대신 고정사유Literal을 반환하게 변경했다. 주도자가bool 결과를 Future에 게시한 뒤 진단을 기록하므로 logger 작업을 상태 잠금 아래 두지 않는다. 외부check/HTTP 응답은bool/기존 외피다. 예상 밖 Exception은internal_error로 안전하게false, BaseException은 대기자 정리 후 재전파한다.
- 일반pytest1,676개(신규21)·focused74개·ruff/format347파일·mypy app/etl/migrations158파일이 통과했다. 동시HTTP성공/실패·단일실행·참여자타임아웃·HTTP취소·close·Exception/BaseException·세대간결과·실패TTL·잠금/로그·원문누출을 검증했다. 일회용PostGIS263개는 진행 중이다. 기존 Starlette 경고1건은 유지한다.
- 실제DB/Render/로컬.env/FE 코드는 아직 변경하지 않았다. 설계의 정책 보완/코드/테스트를 별도 커밋하고 검증/병합 뒤 수동 배포한다.

### 8.2 한식 조사 자료 확보

현재 확보한13개 후보에 대해 기존 Kakao REST 키로공식 Local 키워드API를13회 읽기 조회했다(키 출력/저장·설정 변경 없음). 11개에 결과가 있고 그중10개는 지도 분류가치킨/술집/분식, 1개는일반음식점 분류다. 2개는검색 결과가 없다. 치킨/술집/분식10개 중상호 정규화 정확일치6개·명칭차이4개다. 모두 자동 제외0이다.

비비큐치킨 명동스타점↔BBQ 명동스타점은치킨 분류·API거리0m였으나명칭이 다르고, 인생주점은검색결과가 없어추정하지 않는다. 같은좌표·비슷한상호나지도분류는동일인허가/과거업종의확정근거가아니다. [Kakao 공식 Local API](https://developers.kakao.com/docs/ko/local/dev-guide)의place_name/category_name/distance/place_url을근거후보로사용한다. API분류를인허가공식분류로바꾸지않는다.

저장소 밖 검토CSV/JSON에 source+license_no·원래상호/업태·지도후보명/분류/거리/링크·확인시각·unverified를 보관했다. 전화번호/키는 저장하지 않았다. 최종 보정의 최소 조건은 ①검토 대상의 정확한 키/조회 조건(현재 재현 가능한13개 범위) ②주소/위치·명칭·인허가의 동일성 검토 ③제외 판정 근거와 확인일/검토자/버전 ④현재 분류 보정과 과거 업종 보장의 구분 ⑤재적재 시 원문 지문 변경 재검토 ⑥API 목록/전체 집계/캐시·메타의 일관성 검증이다. 지금은 실DB UPDATE·자동 재분류·FE 목록 숨김을 하지 않는다.

### 8.3 Claude Code 구현 재검토

2026-11-14 Claude Code 구현 후속 정적 검토. 실행한 도구는 지정 파일 Read와 이 MD Edit뿐이다. 코드/테스트 수정, pytest·ruff·mypy 실행, DB·Bash·Git·네트워크 접근은 하지 않았다. 8.1의 일반1,676개·focused74개·ruff/format·mypy 통과는 Codex 관측이며 직접 재확인하지 않았다. 과거 두500의 원인과 성능 영향은 이 검토로 확정하지 않는다.

- 대조 파일: app/services/readiness.py, app/core/operations.py, app/routers/health.py, tests/test_readiness_concurrency.py, tests/test_render_runtime.py.
- 차단: 없음.
- 핵심 경합 판단(`_complete`가 잠금 안에서 `_current=None`·캐시 갱신 → 잠금 밖 `set_result`):
  - 추가 DB 중첩 없음. `_probe`의 `with psycopg.connect(...)`가 반환 전에 연결을 닫으므로(readiness.py:119-123) `_current`가 비는 시점(readiness.py:103)에는 주도자 연결이 이미 닫혔다. 그 틈에 들어온 check는 `_checked_at`이 방금 갱신돼 `_fresh()` 적중으로 같은 세대 값만 받고(readiness.py:71-72) 새 검사를 시작하지 않는다. 연결이 열린 채 `_current`가 비는 유일한 경로는 close(readiness.py:151-156)이고, 이후 check는 `_closed`로 즉시False라 새 연결이 생기지 않는다. 따라서 인스턴스당 동시 연결 최대1은 유지된다.
  - close 후True 없음. ⓐ close가 `_complete`보다 먼저 잠금을 잡으면 close가 완료 권한을 가져가 False를 게시하고, 늦은 주도자는 `_current is not future`로 no-op(이중 `set_result`/InvalidStateError 없음, 캐시 복원 없음). ⓑ `_complete`가 `_current`를 비운 뒤 `set_result(True)` 전에 close가 끼면 close는 `_current is None`이라 게시하지 않고 캐시를 초기화하며, 이후 게시된 True는 주도자·참여자 모두 마지막 `with self._lock: return result and not self._closed`(readiness.py:96-97)에서 False로 바뀐다. close 이전에 이 마지막 검사를 통과한 호출만True이며 이는 close 전 완료로 선형화되는 정상 순서다.
- 동의(코드 대조):
  - Future 생성 직후 잠금 안 `set_running_or_notify_cancel()`(readiness.py:74-77)로 `cancel()` 실패. 라우터는 `to_thread(check)`+`wait_for`만 사용하고 공유 Future를 asyncio로 감싸지 않아(health.py:35-37) HTTP 타임아웃/취소가 공유 Future를 취소하지 않는다. 참여자 대기 한도는 진입 시각 deadline 잔여(readiness.py:63-64, 93)다. `except TimeoutError`는 Python3.11+에서 `concurrent.futures.TimeoutError`와 동일하며, 코드가 이미 `datetime.UTC`(3.11+)를 쓰므로 전제와 일치한다.
  - 상태 선택 순서가 closed → 진행 중 Future → 신선 캐시라 진행 중 새 세대가 있으면 오래된 성공을 반환하지 않고, 만료 성공은 `_fresh()`에서 탈락해 200이 되지 않는다. 참여자는 자기 Future 결과만 사용해 세대 혼동이 없다.
  - Exception은 `internal_error`·False로 완료·`_current` 정리. BaseException은 `finally`에서 False 완료·정리·로그 후 재전파. 원문은 잡거나 기록하지 않는다. 대기자는 deadline 전에 깨어난다.
  - 진단: `readiness_probe`는 `_complete` 뒤·잠금 밖에서 실행당1회만 호출되고, reason은 `READINESS_REASONS` allowlist·duration은 유한/비음수만 통과, 필드는 event·time·path 고정·reason·success·duration_ms로 request_id가 없다. `_emit`은 Exception을 삼켜 결과를 바꾸지 않는다. 캐시 적중·참여자는 이벤트를 만들지 않는다. `/api/ready`는 정확 일치만 allowlist에 들어가 변형 경로는 unmatched다.
  - 테스트가 7절 필수 회귀 1~5·7·8을 다룬다: 기존 single-flight 테스트 교체(test_render_runtime.py:100-120), 참여자 타임아웃/HTTP 취소 후 `running()`·미취소·실행1회, close 대기자 해제·늦은 성공 거부, Exception/BaseException과 CANARY 미노출, 세대별 결과(양방향), 잠금 미보유 3지점, 경로 변형, logger 장애. 서비스 상수도 별도 patch한다(test_render_runtime.py:219-220).
- 주의(비차단):
  1. ⓑ 경합 창(`_current` 비움 후 `set_result` 전 close)과 "`_complete` 직후 틈의 check가 새 검사를 열지 않음"은 정적 추론으로만 확인했고 이를 고정하는 전용 테스트가 없다. 필요하면 `Future.set_result`를 감싸 그 직전에 close/check를 끼워 넣는 테스트로 보강할 수 있다.
  2. 7절 회귀6(만료 성공 + 진행 중 새 실행 시 동시 호출이 새 결과를 기다림)은 전용 테스트가 없다. 코드 순서상 `_current` 우선 확인과 만료 시 `_fresh()` 탈락으로 구조적으로 보장된다.
  3. close로 거부된 늦은 실행도 실제 reason(예: ok)으로 readiness_probe를 1회 남긴다. 4절대로 probe ok를 HTTP200으로 해석하지 않아야 한다. 주도자 duration은 check 진입부터라 잠금 대기를 포함한다.
  4. 연결 최대1 보장은 ReadinessProbe 인스턴스 단위다. 프로세스당 1은 앱 수명당 DatabaseResources 하나라는 기존 전제에 의존한다(이번에 별도 확인하지 않음). close 후에도 진행 중이던 주도자 연결은 최대 connect_timeout1·SQL750ms 수준 동안 스스로 닫힐 때까지 남는다.
  5. `test_concurrent_http_waits_for_one_actual_result`의 "검사 종료 전 미완료"는 50ms 관측이라 약한 단언이다. 실행1회·전원 동일 상태 단언이 주 근거다. 7절의 executor 스레드 점유(참여자 최대2.5초) 주의는 그대로 유효하다.
  6. `_complete`/로그 호출 중 비동기 BaseException(예: 신호)이 들어오면 로그 누락 가능성 정도가 남으며 범위 밖으로 둔다.

결론: 차단 없음. 지적한 경합에서 추가 DB 중첩이나 close 후True 반환은 정적 대조상 발생하지 않는다. 주의 1·2의 전용 테스트 보강은 선택이며, 일회용 PostGIS·CI/CodeQL 결과 확인 후 병합·배포 절차(5절)를 따르는 데 동의한다.

### 8.4 Codex 재검토 채택·배포 전 완료 검사

- 구현 재검토도 실제CLI exit0·is_error=false·권한거절0으로 완료했다. 차단 없음을 소스와 대조했고 선택 제안1·2를 채택해 완료 게시 직전close/동시check 두 경우와 만료 성공 후새 실패를 기다리는 경우3개 회귀를 추가했다.
- 최종 일반1,679개(기준1,655+신규24)·focused77개 통과. 코드 동일 상태에서 격리PostGIS263개를 별도 loopback55474의 일회용 컨테이너로 실행해 성공/skip0을 JUnit XML로 확인했다. 컨테이너ID/작업label을 확인한 뒤 제거했고 기존 개발DB컨테이너/실제 DB 내용은 건드리지 않았다. ruff/format347파일·mypy158파일 통과를 유지한다. 추가3개는 테스트만 변경하여 PostGIS를 중복 재실행하지 않는다.
- FE 최신develop4d27ab7·PR52/53 병합·CI Unit test98개 통과를 다시 확인했다. 담당자의 업태 기준 안내와 CI 추가를 완료로 갱신하고 제보18개명단/화면재검증만 요청한다. 원본 보정/AI 활성화는 미완료다.
- 검토CSV는 원본배치/지문·근거확인시각·unverified 상태와빈판정자/판정/적용기준일을 포함해 재작성했다. 입력/증빙을 검토자가 확인하기 전에는 자동제외·실DB쓰기·정책승격을 하지 않는다.
- 이 단계에서는 운영 배포 전이다. 검증한 PR을develop에Squash병합하고 그commit의실행코드가검증한branch와같은지확인한뒤수동배포한다. 배포후실측은다음절과현재Render안내에반영한다. 과거두unmatched500의경로확정은불가한한계로남긴다.

### 8.5 배포 후 검증

- PR125의 일반/격리·CodeQL 검사가 모두 성공한 뒤 develop에 Squash 병합했다. 병합commit7d4846c61291897993a1146e16945c06ca1255b1의 app/etl/migrations/tests/의존성/Docker 실행 코드가 검증한 head697d4a3과 같음을 git diff로 확인하고 수동 배포했다.
- dep-dbs3norl550s73fbvskg가2026-11-14 19:46:35 KST live가 됐다. 배포 전후 서비스·Free·자동 배포off·healthCheckPath=/api/ready·전체 환경변수/키 목록 해시가 일치한다. 풀1/overflow0/대기15초·SQL10초·워커1·예산8·expected revision0011을 보존했다. DB/schema/인덱스·로컬.env·FE를 변경하지 않았다.
- 실제 Render에서 ready6동시 초기/최종 각1회와 업무묶음마다ready2동시를 실행해 ready24건 전부200이었다. 업무5 GET×300/500/1000m×최초/반복30건도 전부200·기존8958ba7의 동일 조건 전체 JSON SHA256과 같았다. 업무묶음 최대 시간 중앙값은 최초8.428초·반복5.520초이며 추가 ready 요청이 있는 이번 관측이다. 성능 보장으로 사용하지 않는다.
- health200·세 허용 origin GET/POST preflight6건/실제GET3건·미허용/유사domain/localhost5181 차단·AI503 AI_UNAVAILABLE을 확인했다. 실모델 호출은0이다.
- 검증 시작/종료 UTC 구간을 고정하고 Render 로그를100행씩 nextStartTime/nextEndTime으로 끝까지 수집했다. 서버 ready API 이벤트28건(플랫폼 호출 포함)·readiness_probe4회 모두ok·해당 구간 HTTP500 이벤트0을 확인했다. ready는 이제 정확한 경로로 기록되고 실제 검사 이벤트는 요청 수와 구분된다. 이 결과로 과거 두unmatched500의 경로/원인을 사후 확정하지 않는다.
- 느린 정상 검사 고정 TestClient 재현도 검사 실행1회·두 요청 모두200·readiness_probe1개/ready 경로 API로그2개를 확인했다. 기존 같은 재현은200/500·두unmatched였다. 실제 DB의 장애/권한 변경은 강제하지 않았고 실패/취소/닫힘은 격리/모의 검증과 구분한다.
- 운영 문서 두 개·CLAUDE.md·통합 작업계획을 현재 배포와 일치시켰다. 이번 후속 문서 PR 병합으로 배포 commit을 다시 바꾸지 않는다(자동 배포off).

### 8.6 추가 명단 미확보에 따른 범위 확정·증빙

- 사용자가 추가18개 명단이 없다고 답했다. 이를 현재13개 후보 전체의 조사 중단 조건으로 삼지 않고, 직접 재현한13개를 먼저 검토한다. 제보18개 전체가 해결됐다고 표시하지 않는다.
- 현재 Render의13개 원본 행을 source+license_no로 다시 읽고 상호/한식 업태/review/deleted 조건이 같음을 확인했다. 원본 도로명/지번 주소·배치와 지문을 검토CSV에 추가해 지도 후보 주소와 대조할 수 있게 했다. 문자열 검사의 Windows stdin 인코딩 오류는 Unicode escape로 수정해 재확인했으며 DB 변경은 없었다.
- 자동 제외0·실제 업종 보정 미완료·AI 비활성을 유지한다. FE의 업태 안내와 CI는 담당자 반영 완료로 갱신했으며 실제 배포 화면 수용 검사는 FE 요청으로 남긴다. 전체500·대량 부하·실제15분 절전 복귀 완료로 확대하지 않는다.
- 설계/Claude 검토JSON2개·전후 재현·격리JUnit·배포/환경값 보존·실측/로그·13개 검토CSV와 근거는 저장소 밖 `%USERPROFILE%\SpotON-private-backups\render-free-20261113\readiness-followup-20261114\`에 보관한다. 원본 점포 키/주소·키/URI·예외 원문은 커밋하지 않는다.
