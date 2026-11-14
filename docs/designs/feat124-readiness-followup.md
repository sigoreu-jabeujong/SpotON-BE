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

실행 후 기록한다. 현재까지 운영 서비스/소스/DB 데이터는 변경하지 않았다.
