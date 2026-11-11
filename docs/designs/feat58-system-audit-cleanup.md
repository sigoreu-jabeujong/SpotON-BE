# 전체 시스템 점검·오류 수정·코드 정리 (#58)

- 기준: develop `70ea94b`, 브랜치 feat#58-system-audit-cleanup, 2026-11-12
- 요청: 구현 시스템 전체 점검/테스트, 문제·미사용 코드·주석은 Claude Code 논의 후 정리, 오류 수정·재검증.
- BE-21 공정위 인증 대기는 #57로 유지한다. 이번 점검은 새 기능 개발이나 원천 적재를 진행하지 않는다.

## 1. 점검 범위와 baseline

현재 경로는 FastAPI routers → Pydantic 입력/공통 응답·오류 → DB 읽기 전용 세션 → 점포 조회 서비스다. 주소 검색은 Kakao 실시간 호출, 인허가/경계/점포통계/매출/생활인구/변화유형 ETL은 별도 CLI다. migration head0009, 일반 앱 DB 계정, 격리 PostGIS 테스트 경계·AI client/프롬프트/검증 모듈을 확인했다. AI/risk/activity 공개 API와 브랜드 원천은 미구현/대기이므로 살아 있는 경로라고 주장하지 않는다.

- BE `ruff check .`·format220files·mypy113files 통과, 일반 **870 passed**, 격리 PostgreSQL17/PostGIS **92 passed**. 기존 Starlette/httpx 경고1건.
- FE `npm run lint`, `npm run build`(TypeScript+Vite) 통과. 코드/설정/문서는 수정하지 않는다.
- API 입력·오류/로그·CORS·READ ONLY/세션·기간/공간/출처·ETL 파싱/버전/원자성·AI 한도/실패·namespace/호출 참조를 점검했다. private 최상위 함수의 AST 참조 후보 검사에서 확정 미사용 함수는 발견하지 못했다. 정적 참조 부재만으로 프레임워크/ORM/외부용 코드를 삭제하지 않는다.
- 실제 개발 DB는 14개 앱 테이블의 전체 행/geometry hash·건수를 전후 비교하고 6개 공개 API·입력 오류·CORS를 확인한다. 파괴적 suite/downgrade는 별도 임시 DB에서만 실행한다.

## 2. 독립 재현된 오류와 제안

### F1. LLM 전체 시간 예산이 실제 await를 끊지 못함

`app/ai/gemini.py`: 현재 `remaining=deadline-monotonic()`과 httpx phase별 timeout만 지정한다. `MockTransport` async handler가 60ms 지연 후 정상 STOP을 반환할 때 request_timeout10ms/time_budget20ms를 넘겨도 약78ms 뒤 성공했다. 실제 느린 body 등에서 phase timeout과 전체 예산이 다를 수 있다. 현재 성공 경로는 deadline 재확인도 없다.

제안: Python3.11 `asyncio.timeout`으로 generate 전체 await 범위를 묶어 재시도 대기까지 전체 예산에 포함하고, `_post`에도 request_timeout/남은 예산의 min을 취소 범위로 적용한다. 성공/실패 응답 처리 전 monotonic deadline을 확인해 fake clock/즉시 반환 transport의 초과도 TIMEOUT으로 거절한다. TimeoutError는 except에서 상태만 처리하고 밖에서 LlmError(TIMEOUT)를 발생시켜 원문/키가 예외 context에 붙지 않게 한다. 취소는 CancelledError를 그대로 전파한다. 동기 CPU 작업/스케줄러를 선점하는 실시간 SLA라고 주장하지 않는다.

Claude 보완: 바깥(전체 예산)·안쪽(요청별) timeout은 예외 타입이 아니라 각 `asyncio.Timeout` 객체의 `expired()`로 구분한다. 안쪽만 만료되고 전체 예산이 남으면 기존 재시도 정책을 따르고, 바깥 만료는 재시도 없이 TIMEOUT으로 끝낸다. 변환은 `raise LlmError(TIMEOUT) from None`처럼 `__cause__`/`__context__`를 모두 끊는 방식으로 한다. httpx 자체 `TimeoutException` 매핑은 기존대로 유지한다. `asyncio.timeout`은 `loop.time()`을 쓰므로 `time.monotonic` 패치(fake clock)로는 발동하지 않는다. fake clock 검사는 응답 후 deadline 재확인만 검증하고 실제 취소는 Event 기반 검사로 검증한다.

회귀(flaky 방지: 끝나지 않는 `asyncio.Event`를 기다리는 handler와 재시도 sleep 주입을 사용하고, 경과 시간은 넉넉한 상한(예: 2초 미만)만 확인하며 ms 단위 정밀 비교를 하지 않는다): 실제 await handler가 Event를 기다릴 때 취소·timeout(실외 네트워크 없음), 개별 요청 timeout이 전체보다 작을 때 재시도 가능, 전체 budget이 retry sleep을 끊음, fake clock 늦은200 거절, caller cancellation 전파·비밀 비노출. 기존 늦은503 fake-clock 검사는 UPSTREAM 대신 예산 소진 TIMEOUT을 기대하도록 수정한다.

### F2. Retry-After NaN이 비정상 sleep으로 전달됨

`etl/localdata/client.py::_retry_delay`: `min(max(float(header),0),30)`이 헤더 `NaN`에 nan을 반환한다. `time.sleep(nan)`은 예외가 되어 기존 재시도 계약을 깨뜨린다. 독립 재현 math.isnan(...)==true.

제안: float 변환 후 `math.isfinite()`일 때만0~30초 clamp, NaN/±Infinity/파싱 오류는 기존 bounded 지수 backoff로 fallback. 음수 유한값은 기존0 유지한다. 헤더 원문은 로그/오류에 넣지 않는다. HTTP-date 형식은 기존처럼 fallback하며 이번에 새 파서를 추가하지 않는다.

회귀(sleep 주입/패치로 실제 대기 없음): NaN/±Infinity/`1e400`(float 변환 시 inf)/garbage fallback·유한값 음수/큰수 clamp 및 실제 collect_authority의429→200 성공·대기 유한값 확인.

### F3. 비정상 카카오 지번 숫자의 ValueError가 서버500으로 누출

`app/services/kakao_local.py::_parse_number`: ASCII decimal이면 즉시 int(value) 한다. main_address_no에 숫자5,000자(합성)를 넣은 MockTransport 응답으로 `ValueError`를 재현했다. 정상 지번 구성 검증 전에 Python 정수 변환 한도에서 터져 기존 ADDRESS_NOT_FOUND/UPSTREAM 오류 경로를 우회한다.

제안: 기존 `build_from_parts`의 숫자 범위0~9999에 맞춰 앞0을 제외한 유효 숫자 길이가4 이하일 때만 int로 변환한다. 원문 앞0 허용은 유지하고 과도한 값은None으로 돌려 기존 서울 주소 부적합 경로(404 ADDRESS_NOT_FOUND, no-store)를 따른다. 원문 주소/숫자를 오류에 넣지 않는다. 정상이지만 아직 건물키에 없는 법정동/지번 지원 범위를 넓히지는 않는다.

Claude 보완: CPython의 정수 문자열 자릿수 한도는 앞0도 자릿수에 포함하므로 원문 전체가 아니라 앞0을 뗀 문자열(모두 0이면 `"0"`)을 int로 변환한다. 거절된 값은 404로 단정하지 않는다. 현재 `10000`처럼 범위를 넘는 짧은 숫자가 거치는 기존 경로와 **같은 결과**가 되도록 하고, Codex가 기존 10,000 처리 결과를 먼저 테스트로 고정해 비교한다. 그 경로가 404 ADDRESS_NOT_FOUND라면 그대로 유지한다.

회귀: 정상 지번/앞0/0/9999 유지,10,000/수천자리 main·sub 거절, API에서500이 아닌 기존 공통404·CORS/no-store·원문 비노출.

### F4. CSV 수집 시각과 분기 provenance 모순 허용

`etl/market_changes/source.py::load_source`: `_parse(data,year,reference)`에 실행일을 전달한다. retrieved_at=2026-09-11, 실행일=2026-11-12이고 CSV에2025년4분기들+2026년4분기 행(선택 밖)을 넣어도 성공했다. 수집 당시는3분기여서4분기 자료가 있으면 수집시각 주장이 맞지 않는다.

제안: timezone 포함·미래 수집시각 검증을 유지하고 분기 상한은 Seoul로 변환한 `retrieved_at`을 기준으로 검사한다. 선택 연도 밖 행도 동일 검증한다. 현재 실제 원본은11월 수집·최대2026년2분기여서 재검증/저장 내용 hash에 영향이 없다. Claude 결정: 변환/식별/저장 hash를 바꾸지 않고 입력 거절만 강화하므로 rule_version v1을 유지한다. 버전을 올리면 같은 bytes/연도/경계로 새 불변 버전이 생겨 replay 재사용 계약이 깨진다. 허용 상한은 retrieved_at(Seoul)이 속한 분기로 기존 실행일 기준 규칙과 같은 강도를 유지하며 진행 중 분기 제외 등 추가 강화는 하지 않는다. 미래 수집시각 거절(실행일 비교)은 그대로 둔다. source_file_date=null을 실행일로 채우지 않는다.

회귀: 수집 후 분기 거절·수집 분기 허용·UTC↔Seoul 분기 경계(예: 2026-09-30T15:30Z=Seoul 10-01이면 4분기 허용)·선택 연도 밖 행의 동일 거절·기존 전체 실제 원본을 저장된 최초 retrieved_at으로 읽기전용 replay(같은 UUID/hash).

## 3. 정리 후보: 삭제/유지 근거

1. `etl/address/building_key.py::_legal_dong_failure`는 valid regex면None, 이후 endswith 조건과 최종 return이 모두 LEGAL_DONG_UNSUPPORTED다. 결과가 같은 중복 조건만 제거한다. 함수/법정동 규칙은 유지한다. 제거 전 valid/endswith 해당/비해당 입력의 반환값을 테스트로 고정하고 제거 후 동일함을 확인한다.
2. `etl/__init__.py`의 "수집·정제·적재 구현 예정(PHASE2)"과 `app/ai/__init__.py`의 "AI 해석 구현 예정(PHASE6)"은 현재 ETL·AI 기반 모듈 구현과 맞지 않는다. 구현된 모듈 설명으로 갱신하고 미구현 공개 AI API를 완료로 표현하지 않는다.
3. 예외 타입의 pass, DataRangeQuery의 빈 subclass, migration0001의 의도된 downgrade, package namespace, pyshp import-untyped 무시, app.models의 등록용 import/noqa는 필요하므로 삭제하지 않는다. 동작 이유를 설명하는 주석·테스트 canary/명시 잘못된 타입도 유지한다.
4. AI factory/프롬프트/검증 코드는 공개 API 미연결이어도 후속 단계용으로 구현·테스트되어 있다. 현재 route에서 안 쓴다는 이유로 지우지 않는다. 오래된 migration/설계 역사 기록도 보존한다.
5. 공통 타입/DB/ETL 전체 재설계나 무조건적인 주석 제거는 하지 않는다. 실제 오류4건과 결과가 같은 중복 조건·잘못된 현재 설명만 정리한다.

## 4. FE 점검과 남은 연결 문제

FE는 build/lint가 통과해도 `HistoryStore.open_date/name/operating_months`가 non-null이고 source가 없으며 HistoryTable이 `open_date.localeCompare`·license_no 단독key를 사용한다. BE nullable/복합 식별자 계약을 실제로 연결하면 null 정렬 오류/행 충돌 가능성이 있다. 이미 docs/fe-store-history-api-request.md에 요청되어 있어 이번 점검에서 확인 상태를 기록하고 해당 보고서로 연결한다. nearby/data-range/snapshot 기존 요청도 담당자 반영 대기다. FE 코드를 수정하거나 새 FE 이슈/PR을 만들지 않는다. 전체 FE-BE 통합 완료나 브라우저 자동 시연 완료라고 주장하지 않는다.

## 5. 검증·커밋·완료

- 설계/Claude diff 검토 기록 커밋 후 오류별 코드+의미 있는 회귀 테스트를 묶는다. 정리/검증 문서는 마지막 커밋으로 분리한다.
- 수정 전에 합성 오류를 pytest로 재현하고 수정 후 같은 테스트가 통과하도록 한다. 외부 유료 LLM은 호출하지 않고 MockTransport로 취소/예산/검증을 확인한다.
- 전체 ruff/format/mypy·일반·격리 통합 재실행, 실제 DB head0009/모델일치/버전/원천 재조회·READ ONLY CLI·기존14테이블 보존·실제 API 입력/오류/정상응답 확인.
- 실제 외부 주소 검색은 공개 시청 주소1건의 연결만 확인하고 주소/좌표/키/응답 원문은 기록하지 않는다. 외부API 실패는 서비스 가용성/권한 문제와 코드 실패를 구분하며 #57 인증 대기를 우회하지 않는다.
- 공개 API 경로/응답 타입·DB migration·원천/환경설정·FE 파일 변경은 없다. 오류 상황을 기존 계약으로 복원하는 수정이다.
- 지정 PR 양식/정확한4체크문구와 해당없음 사유, 실제 비밀값 검사·CI/CodeQL 성공 후 develop 일반 Squash 병합. main/강제push/수동브랜치삭제 없음.

## 6. Claude 실제 검토 요청

이 MD만 Read/Edit로 실제 수정한다. 위 재현·코드 위치·제안에 근거해4오류 수정과 정리/유지 범위를 검토하고 가장 타당한 안·근거·보류를 이 절에 기록한다. 코드/다른 문서/Git/DB/네트워크/.env는 읽거나 수정하지 않는다. 특히 asyncio 취소·예외 context·실제 timeout 테스트의 flakiness, 카카오 기존 범위/404, provenance검증의v1호환, 지울 수 없는 프레임워크/후속코드, FE범위를 점검한다. 이 문서 밖 코드를 읽지 않았다는 한계를 명시하고 Codex 최종 점검으로 연결한다.

### 6.1 Claude 검토 결과 (2026-11-12)

검토 방식: 이 MD만 Read/Edit했다. 코드·테스트·다른 문서·Git·DB·네트워크·.env는 읽지 않았으므로 재현 결과와 코드 위치는 Codex 기록을 근거로 삼았다. 아래 판단은 Codex가 실제 코드에서 최종 점검해야 한다.

| 항목 | 결정 | 근거 | 보류·한계 |
|---|---|---|---|
| F1 LLM 예산 | 채택(보완) | phase timeout만으로는 느린 응답과 재시도 sleep을 포함한 전체 예산을 보장하지 못한다. `asyncio.timeout` 중첩이 3.11 표준 방식이다. 바깥/안쪽 만료를 `expired()`로 구분해야 재시도 가능 여부를 잘못 판단하지 않는다. `from None`으로 응답 원문·키가 예외 체인에 남지 않게 한다. 외부 CancelledError는 `asyncio.timeout`이 변환하지 않으므로 그대로 전파된다. | 늦은503→TIMEOUT 기대값 변경은 내부 오류 분류만 바뀌는 것이다. 둘 다 공개 응답에서 같은 AI_UNAVAILABLE로 매핑되는지 Codex가 확인한다(다르면 공개 계약 변경으로 보고한다). 실시간 SLA는 주장하지 않는다. 공개 AI API가 없으므로 영향은 모듈 수준이다. |
| F2 Retry-After | 채택 | 비유한 값 fallback과 유한값 clamp는 기존 계약을 복원할 뿐이다. `1e400`도 inf가 되므로 같은 경로로 처리된다. | HTTP-date 파서는 추가하지 않는다. |
| F3 카카오 숫자 | 채택(보완) | 자릿수 한도는 앞0을 포함해 세므로 앞0을 뗀 뒤 변환해야 한다. 결과 상태코드를 새로 정하지 않고, 범위를 넘는 기존 짧은 숫자와 같은 경로를 쓰도록 해서 계약 변경을 피한다. | 기존 10,000 처리 결과를 먼저 고정한다. 지원 범위는 넓히지 않는다. |
| F4 provenance | 채택, rule_version v1 유지 | 입력 거절만 강화하고 저장 변환/hash는 바뀌지 않는다. 버전을 올리면 같은 원본의 불변 버전 재사용이 깨진다. 실제 원본(11월 수집·최대 2026Q2)은 새 규칙을 통과한다. | 같은 패턴(실행일 기준 분기 상한)이 다른 ETL(점포통계·매출·생활인구)에도 있는지는 Codex가 확인만 하고 기록한다. 있으면 별도 이슈 후보로 남기며 이번 범위에서 고치지 않는다. |
| 정리 1 중복 조건 | 채택 | 반환값이 같은 분기만 제거한다. 전후 반환값을 테스트로 고정한다. | 실제 분기 구조는 Codex가 확인한다. |
| 정리 2 패키지 docstring | 채택 | 현재 구현과 맞지 않는 "구현 예정" 설명을 바로잡는다. 공개 AI API 미구현은 명시한다. | — |
| 유지 3·4 | 유지 | 예외 pass·등록용 import/noqa·빈 subclass·의도된 downgrade·namespace·타입 무시·canary는 프레임워크/ORM/도구 의존성이 있다. AI factory/프롬프트/검증은 BE-28~32 후속용으로 테스트된 코드다. AST 참조 부재만으로 지우지 않는다. | 미사용 판단 근거는 Codex AST 검사뿐이다. 동적 참조는 검증하지 않았다. |
| FE | 기록만 | 2026-11-12 사용자 지시에 따라 FE는 수정하지 않는다. null 정렬과 license_no 단독 key 위험은 기존 요청 보고서로 연결한다. | FE 반영·통합 완료는 주장하지 않는다. |

추가 기준:
- 커밋은 F1~F4를 각각 코드+회귀 테스트 한 커밋으로 나누고, 정리 1·2는 별도 refactor/docs 커밋으로 한다. 기록 문서는 마지막에 둔다.
- 시간 관련 테스트는 실제 네트워크 없이 Event와 sleep 주입을 쓴다. 경과 시간은 넉넉한 상한만 확인한다. CI에서 한 번이라도 timing 실패가 나면 상한을 늘리지 말고 구조(주입/Event)를 고친다.
- 공개 API 경로·응답 타입·migration·환경설정·FE 변경이 없다는 5절 주장은 F1 오류 분류 매핑 확인 결과에 따라 유지 여부를 확정한다.
- 남은 일: Codex가 실제 코드와 이 diff를 대조해 최종 점검한 뒤 구현한다.

### 6.2 Codex 최종 점검

Claude의 실제 diff 전부와 JSON(is_error=false·10turns·permission_denials0)을 확인했다. 제안4건·중복 조건/잘못된 설명 정리를 채택한다. 한 가지 표현은 바로잡는다: `raise ... from None`만으로 __context__가 없어지는 것은 아니므로 TimeoutError를 잡은 except **밖에서** LlmError를 발생시킨다. 안쪽 timeout은 expired()로 자체 만료/다른 TimeoutError를 구분하며 바깥 취소(CancelledError)는 그대로 전파한다. 늦은503의 내부 UPSTREAM/TIMEOUT은 모두 client.to_app_error에서 같은 AI_UNAVAILABLE로 변환되는 것을 실제 코드에서 확인했다.

카카오10,000과 긴 지번은 기존 건물키 숫자 범위에 따른 서울 주소 부적합404 경로를 유지한다. 정상 앞0은 제거한 숫자만 int 변환해 호환을 유지한다. 다른 연간 점포/매출 ETL은 지정 연도와 파일 수정일을 검사하고 생활인구는 관측일≤file_date를 검사하므로 이번 CSV의 retrieved_at/선택 밖 분기와 같은 구조는 없다. 실제 순서·hash·저장 버전 변경 없이 입력 검증만 강화한다.
