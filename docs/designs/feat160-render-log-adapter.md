# Render 운영 로그 조회·보관 전달 (#160)

- 기준 develop `1cba1d5`, 2026-11-15. [이슈 #160](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/160).
- BE 전용 `python -m etl.operation_logs.render` CLI. 기존 [#158 보관기](feat158-operation-log-retention.md)의 전용 SQLite·불변 규칙과 JSON 허용목록을 그대로 재사용한다. FE/앱 API/0012/원본 DB/.env/기존 서버/Render 요금제·설정은 바꾸지 않는다.

## 1. 확인한 근거와 범위

[Render List logs](https://api-docs.render.com/reference/list-logs)와 [공식 OpenAPI](https://api-docs.render.com/openapi/render-public-api-1.json)는 GET `/logs`의 ownerId/resource 필터, forward 방향, startTime/endTime·hasMore·nextStartTime/nextEndTime 페이지 처리를 설명한다. limit 상한은100이다. wrapper는 id/message/timestamp/labels이며 resource/type 라벨을 제공한다. API는 원문을 제공하므로 wrapper나 일반 콘솔 로그를 저장하지 않고 기존 검증을 통과한 message만 넘겨야 한다.

실제 읽기 전용 검사에서 기존 Free/자동배포off 서비스를 확인했고, workspace 로그 stream 조회는404여서 외부 보관 대상을 확인하지 못했다. application 로그 GET은200이다. 두 차례 각5건 표본에서 허용 이벤트는 각각5건·1건이었다. 따라서 일반 콘솔 행을 모두 운영 이벤트로 간주하지 않는다. timestamp/커서에는 소수6자리와9자리가 관측돼 나노초 정확도로 비교해야 한다. 인증키/원문/전달 endpoint는 출력·파일·검수 입력에 포함하지 않는다.

이번 완료는 유한 구간의 API 조회→검증→기존 보관기 전달이다. 영구 저장소 선정/자동 init·스케줄 설치·Render 스트림 설정·서비스 배포/실제30일 연속 보관은 범위 밖이다. 원문을 파일로 내린 뒤 필터하지 않는다. 실 검증의 쓰기는 별도 합성/폐기용 임시 보관기에서만 한다.

## 2. CLI·인증·조회 계약

- `--db`, `--owner-id`, `--service-id`, `--start`, `--end` 필수. 기본 dry-run, `--execute`만 기존 보관기에 쓴다. init/prune은 이 명령에서 자동 실행하지 않는다. 기간/시각은 UTC RFC3339(`Z`/`+00:00`, 소수0~9자리), start<end, 구간 최대1시간, end≤현재를 검사한다.
- 인증은 프로세스 환경 `RENDER_API_KEY`만 사용한다. CLI 인자/문서/저장 파일에 키를 넣지 않는다. `.env`나 Render CLI 파일을 자동 읽지 않는다. 검증용 private helper가 기존 인증을 메모리로 전달할 수 있다. API URL은 `https://api.render.com/v1` 고정, 사용자 endpoint/redirect/proxy/자동 재시도 없음, TLS 인증을 유지한다.
- 대상 전용 SQLite를 쓰기 없이 먼저 검사한다. GET `/services/{service-id}`로 id/ownerId/web_service를 대조한 뒤 GET `/logs`만 한다. 다른 owner/resource, request/build 로그, 범위 밖 timestamp는 실패한다. Render 환경 변경·배포·수집 대상 확장은 하지 않는다.
- 페이지당100행·1MiB, 최대20페이지/2,000행·총10MiB·실행 네트워크 예산30초, 요청별 connect/read/write/pool 최대5초로 제한한다. 응답은 스트리밍하며 원문을 남기지 않는다. 실패/상한 초과/취소에는 그 구간을 보관기에 전달하지 않는다.
- HTTP401/403은 인증,429는 한도,그 외 비200은 고정 HTTP 사유로 종료한다. httpx/httpcore 상세 로그를 CLI에서 억제하고 응답/URL/헤더/예외 문자열을 출력하지 않는다. 결과는 카운트/구간/상태만 stdout JSON1줄, 성공0/실패1/사용법2/중단130이다.
- (Claude 검토 보완 A1) `--owner-id`/`--service-id`는 네트워크 전에 고정 형식(예: owner `^(tea|usr)-[a-z0-9]{20,}$`, service `^srv-[a-z0-9]{20,}$`, 구현 시 실제 관측 형식으로 확정)을 fullmatch해야 한다. 경로는 문자열 결합이 아니라 검증된 id만 넣고 `/`·`.`·`%`·공백을 허용하지 않는다. 형식 위반은 사용법2다. 이유: `/services/{id}` 경로 조작으로 다른 엔드포인트를 GET하는 것을 막는다.
- (A2) httpx Client는 `trust_env=False`(HTTP(S)_PROXY·`.netrc`·SSL_CERT_* 환경 무시), `follow_redirects=False`, 기본 CA 검증, transport retries=0으로 만든다. 키는 비어 있지 않고 ASCII 인쇄 문자(공백·제어문자 없음)인지 먼저 검사해 header 구성 예외 문자열에 키가 실리지 않게 한다. 키는 Authorization 헤더 외 어디에도(repr/예외/결과 JSON) 넣지 않고 event hook을 쓰지 않는다. 이유: `.netrc`/프록시 환경이 인증·전송 경로를 바꾸거나 키를 제3자에 보낼 수 있다.
- (A3) 응답은 `Accept-Encoding: identity`로 요청하고, 상한(페이지1MiB·총10MiB)은 디코딩 후 바이트에 적용한다. `/services/{id}` 응답도 별도 상한(예: 256KiB)을 둔다. Content-Type이 JSON이 아니면 실패한다. wrapper JSON도 중복 키 거절·NaN/Infinity 거절·RecursionError를 고정 사유로 처리한다. 이유: 압축 폭탄·중복 키로 라벨/커서를 바꿔치기하는 입력을 막는다.
- (A4) 30초 예산은 monotonic deadline을 매 요청 전·매 chunk 수신 후 검사한다. 동기 httpx의 read timeout은 chunk 간격 기준이므로 실제 최악 시간은 "예산30초+요청 timeout5초"이며 이를 문서·테스트에 그대로 표기한다. 엄격한 벽시계 상한으로 주장하지 않는다.
- (A5) `--end`는 현재 시각 이전이어야 할 뿐 아니라, 제공기관 수집 지연을 고려해 기본적으로 `end ≤ now-5분`을 권장 경고(status 필드 `recent_window=true`)로 표시한다. 실패로 만들지는 않지만 늦게 도착한 로그가 이 실행에서 빠질 수 있음을 결과에 표시하고, 재조회(중첩 구간)는 canonical hash 중복 방지로 안전하다.
- (A6) dry-run의 의미는 "보관기 무쓰기"다. Render GET은 dry-run에서도 수행된다(읽기 전용). 보관기 사전 검사는 `validate_target`+기존 `connect(write=False)`의 `mode=ro`만 쓰고 init/prune/파일 생성은 하지 않는다. 사전 검사 후 네트워크 동안 대상이 바뀌어도 `ingest`가 다시 `validate_target`·소유권을 검사하므로 그 결과를 따른다.

## 3. 페이지·메시지 검증과 저장

- API root의 logs/list, hasMore/bool과 필수 문자열 커서를 검사한다. hasMore=true이면 커서를 원래 구간 안에서 strictly 좁혀야 한다. 동일/역행/확장 커서·순환·빈 페이지의 hasMore·상한 초과는 실패다. 원래 필터/owner/resource/direction/type는 페이지마다 유지한다.
- 나노초 RFC3339를 정수로 비교하고 제공된 커서 문자열을 그대로 재사용한다. datetime.fromisoformat의 µs 절삭으로 나노초 진행을 놓치지 않는다. 각 행의 provider timestamp는 현재 요청 구간 안, forward 정렬을 확인한다.
- resource/type 라벨 각각1개가 지정 service/app과 일치해야 한다. 이 부분 불일치는 전체 실패다. 다른 라벨 값·provider id·wrapper는 저장/출력하지 않는다. message는 기존 `parse_record`로 검증하고 불일치 행은 rejected_messages로 집계해 버린다. 검증된 canonical JSON만 메모리에 모은다.
- 모든 페이지가 끝나 hasMore=false가 된 뒤에만 기존 `ingest`로 전달한다. 보관 기준 now는 기존처럼 유한 배치를 다 읽은 뒤 고정한다. event time은 message.time, API 조회 구간은 provider timestamp이므로 둘을 같은 시각으로 강제하지 않는다. 만료/미래/중복·정확한30일 경계는 기존 보관기 규칙을 따른다.
- api_window_complete는 API의 페이지 처리가 끝났다는 뜻이다. `coverage_verified=false`를 고정해 제공기관 누락/지연·한도 드롭·retention 이전 소실·전달 완료를 보장하지 않는다. 비어 있는 구간도 "로그 발생0 확인"이 아니라 "API 반환0"이다.
- 동일 구간 재조회는 기존 canonical hash로 중복 방지한다. 체크포인트/최신 자동 선택은 없으며 자동화 시 명시적 구간·지연/중첩·재처리/누락 감시가 별도로 필요하다. 페이지 중간 결과를 성공으로 저장하거나 source cursor를 진전시키지 않는다.

### Claude 검토 보완 (B1~B6)

- (B1, 차단) 메시지 줄바꿈 주입: `ingest`는 줄 단위 BinaryIO를 읽는다. Render message에 `\n`/`\r`이 들어 있으면 한 행이 여러 줄로 쪼개져 그 일부가 허용 이벤트로 통과할 수 있다. 따라서 (1) message는 str이어야 하고 UTF-8 인코딩 후 4096바이트 이하, `\r`·`\n`·NUL을 포함하면 parse 전에 rejected로 집계한다. (2) 보관기에는 원 message 바이트가 아니라 `parse_record`가 만든 `Record.record`(canonical, `ensure_ascii=True`라 개행 없음)만 `\n`으로 이어 `io.BytesIO`로 전달한다. canonical을 다시 파싱하면 같은 hash가 나와야 하며(시간은 µs 6자리로 정규화됨) 구현 테스트에서 이 멱등성을 확인한다.
- (B2) 카운트 매핑: 보관기 `lines`는 어댑터가 넘긴 검증 행 수뿐이다. 결과 JSON은 `api_rows`(반환 wrapper 수)=`rejected_messages`+`forwarded`, 그리고 보관기 counts(`rejected`는 0이어야 함, 아니면 내부 불변식 실패)를 분리해 보고한다. forwarded 수는 보관기 상한(10,000줄·10MiB)보다 항상 작다(2,000행×4KiB).
- (B3, 차단) 커서 의미: "strictly 좁힘"만으로는 같은 나노초 타임스탬프에 100행 넘게 몰린 경우 정체(정상인데 실패)나, 다음 start가 마지막 행보다 뒤로 건너뛰는 누락을 구분할 수 없다. 구현 규칙: (a) 다음 커서는 `prev_start < next_start ≤ end` 그리고 `next_end == 원래 end`(관측이 다르면 실제 관측으로 고정), (b) 페이지 내·페이지 간 행 timestamp는 비감소, (c) `next_start`가 그 페이지 마지막 행 timestamp보다 1ns 넘게 앞서면(행 사이 미반환 구간 가능) `cursor_gap` 실패, (d) next_start가 마지막 행과 같으면(포함형) 경계 중복은 canonical hash로 흡수한다. Render의 포함/배타 의미는 문서에 명시되지 않았으므로 실제 읽기 전용 조사에서 `next_start==last_ts` / `==last_ts+1ns` 여부 boolean만 기록해 고정하고, MockTransport 테스트를 그 관측대로 작성한다. 정체(next_start 미진전)는 fail-closed `cursor_stalled`로 둔다.
- (B4) 커서 문자열은 그대로 재사용하되 동일 문자열을 나노초 정수로도 파싱해 위 비교에 쓴다. 나노초 파서는 정규식(`YYYY-MM-DDTHH:MM:SS(.d{1,9})?(Z|+00:00)`)과 정수 연산만 사용하며, 소수 9자리 초과·비UTC 오프셋·윤초(`:60`)는 실패다. provider timestamp와 message.time(µs, `parse_record`)은 서로 다른 시계이므로 비교하지 않는다.
- (B5) 라벨: `labels`는 배열이며 name 중복이 있으면 실패, resource/type은 정확히1개씩이어야 한다. level/instance 등 다른 라벨은 무시하되 저장·출력하지 않는다. 출처 신뢰: 이 어댑터가 보관하는 것은 "지정 서비스 app 로그 중 허용 스키마에 맞는 행"이며 앱이 실제로 낸 이벤트임을 암호학적으로 보장하지 않는다(다른 라이브러리가 같은 모양을 출력할 가능성). 결과에 `provenance=schema_match_only`로 표시한다.
- (B6) 원자성: 네트워크 단계 실패/취소(KeyboardInterrupt 포함)는 보관기 연결 전에 끝나 DB 불변이다. `ingest` 내부는 단일 `BEGIN IMMEDIATE` 트랜잭션이며 예외·중단 시 기존 `connect`의 rollback을 따른다. 이 구간을 가로질러 부분 성공을 표시하지 않는다. 테스트는 각 페이지 위치(1·중간·마지막)의 실패와 ingest 직전 중단에서 대상 파일 바이트/사이드카 부재를 확인한다.

## 4. 검증·커밋

1. 실제 Claude가 이 MD만 Read/Edit하고 Codex가 최종 대조한다. 초기 설계 검수 후 구현한다.
2. httpx MockTransport로1/다중 페이지, 나노초1 진행, 정확한 커서 재사용, 고정 필터/인증, 잘못된 owner/resource/type/order/시간/라벨/JSON, body·행·페이지·시간 상한, timeout/redirect/429/중간 오류의 DB 불변을 검증한다. 추가(Claude 보완): 개행/CR/NUL 포함 message 주입 거절, canonical 재파싱 hash 멱등, id 경로 조작 거절, trust_env 무시(프록시/.netrc 환경 설정 시에도 미사용), gzip 응답·디코딩 후 상한, 중복 키 wrapper, cursor_gap/cursor_stalled/동일 나노초 경계 중복, 라벨 중복, 결과 JSON·예외에 키/URL 부재.
3. 기존 보관기의 실제 임시 파일에서 dry-run byte 불변→execute→replay·중복과 원문 부재를 확인한다. 기존 emitter/수집기의 일반 회귀와 전체 정적·일반·Linux 타입 검사, CI 격리 PostGIS/CodeQL을 수행한다.
4. 실제 기존 Render키를 비공개 메모리에서 읽고 고정된 짧은 구간을 읽기 전용 조회한다. 원문은 저장하지 않고 허용 이벤트/거절/페이지/재수집 건수만 기록한다. 실행 검증은 새 임시 SQLite뿐이며 원본·운영 DB·환경/실제 저장소는 유지한다.
5. 기능+테스트, 설계/검수/README·작업계획을 기능별 커밋으로 develop PR에 반영하고 CI 후 정상 Squash 병합한다. FE/API 변경이 없어 FE 문서는 수정하지 않는다.

## 5. Claude 검토·실제 검증 기록

최초 CI의 branch 일반검사에서 기존 `test_quality_precedes_setup_failure_without_changing_cli_error`가 실패했다. 실제 duration_ms=12.345에 fixture 숫자12.34가 포함된 오탐이었다. PR 일반검사는 같은 소스로 통과했지만 재시도로 숨기지 않고 해당 테스트의 서버 시각·처리시간·UUID만 결정적으로 고정했다. 원문 전체의 비노출 단언은 그대로 유지하며 production emitter/생활인구 로직은 바꾸지 않는다. Codex가 실패 로그/테스트 의도를 대조하고 관련 테스트·정적 검증 후 CI를 다시 실행한다.

최종 확인: 관련63 tests pass(1.56초), 전체 회귀 실행 당시2096/1제외/298deselected 이후 추가8사례까지 위63개로 확인했다. 정적416·양 플랫폼 mypy188·원본 환경/사용자 파일 보존 검사를 통과했다. 새 검증 보관기는 소유권·identity·576행을 확인한 뒤 해당 파일만 정리했으며 집계 증거를 남겼다. 원본 Render 로그·운영 저장소를 삭제하지 않았다. 최종 전체 CI와 격리 PostGIS는 PR checks를 따른다.

Codex 구현 검수 최종 대조: 5.2의 R1을 README에 반영해 동일ns100행 초과 경계의 공급자 커서 누락을 탐지/복구 보장하지 않음을 명시했다. R2의 전송 설정/비JSON/서비스 응답 상한/빈 hasMore/역행 커서5개 계약 테스트도 추가했다. 소스 로직은 구현 PASS 시점과 같다. 원본 Render 로그는 변경하지 않으며 새 검증 복사본은 검증 후 정리하고 집계 증거만 보존한다.

Codex 실제 검증(2026-11-15): 기존 인증을 메모리로만 사용해 10:10:09~10:40:09 UTC 구간을 GET으로 조회했다. dry-run/execute/replay 각각6페이지·580행, 허용576/거절4, dry-run 파일 SHA 불변, 새 비공개 검증 보관기에576 삽입, 재조회576 duplicate/추가0, 최종576행이다. Free·자동배포off 재확인, 원본 Render 로그/설정·운영 DB/실제 저장소/스케줄·FE·.env 변경 없음. 결과의 api_window_complete=true는 API6페이지 종료만 뜻하며 coverage_verified=false와 schema_match_only를 유지했다. 원문/키/라벨/endpoint는 보관하거나 검수로 전달하지 않았다. 보관한 검증 복사본은 허용 canonical 이벤트뿐이다.

일반 회귀2096 passed/Windows링크1 skipped/PostGIS298 deselected(35.40초), 신규58개 추가 경계 검사까지 모두 통과했다(전체 실행 당시 신규55개, 이후 압축/응답크기/중간예산3개 추가). ruff check/format416·Windows/Linux mypy188 통과다. CI에서는 새58개와 Linux 실제 링크 사례·격리 PostGIS를 모두 실행한다. 실제 테스트/조회는 Codex 실행이며 Claude가 직접 수행한 결과가 아니다.

Codex 전송 보정: `Accept-Encoding: identity`를 요청하고 응답이 비identity 압축이면 읽기/압축 해제 전에 거절한다. 따라서 A3의 gzip 사례는 압축을 수용하는 기능이 아니라 예기치 않은 압축의 선행 거절/파일 보존을 검사한다. monotonic 예산30초와 SDK 단계별 최대5초 timeout은 적용하지만 DNS/OS 및 여러 요청 단계의 지연까지 포함한 엄격한35초 wall-clock 보장은 하지 않는다. A4의 단순35초 계산보다 이 한계 설명이 우선한다. CLI 전용 HTTP 구간에서는 자식 logger의 별도 DEBUG 설정도 고려해 Python logging을 잠시 억제하고 기존 전역 임계값을 finally에서 복원한다. 기존 앱 실행 경로에는 연결하지 않는다.

Codex 설계 최종 대조: 실제2페이지×5행 조사에서 next_start=last_timestamp+1ns, next_end 유지, 다음 페이지 비역행, 페이지 간 id 중복 없음(boolean 집계만 보관)을 확인했다. 구현은 gap/stall을 거절하고 나노초 커서를 그대로 전달한다. B6의 "보관기 연결 전"은 쓰기 연결 전이라는 뜻이며 읽기 전용 사전 검사는 네트워크 전에 수행한다. 메시지는 사전CR/LF/NUL 거절 및 canonical만 전달한다.

Claude는 이 MD의 Read/Edit만 사용한다. 다른 파일/코드·Git/DB·네트워크·MCP·서브에이전트 금지다. 제공된 소스/집계를 검토하되 직접 실행한 것으로 표시하지 않는다. 차단 지적·이유·수정과 PASS/REVISE를 이 파일에 직접 기록한다. 공식 자료 미확정 매출/상권변화의 pending도 유지한다.

### 5.1 Claude 설계 검수 (2026-11-15, Read/Edit만 사용)

검토 근거: 이 MD, 제공된 `archive.py`·`validation.py` 소스와 안전 조사 JSON. 아무것도 실행하지 않았고 Render 문서도 직접 열지 않았다. Render 커서의 포함/배타 의미는 제공 근거로 확정할 수 없어 B3에서 실측으로 고정하도록 했다.

| 관점 | 판정 | 내용 |
|---|---|---|
| 메시지 주입 | 차단→수정 | B1. 원 message를 줄 스트림에 넣으면 개행으로 위조 행이 생긴다. canonical만 전달·CR/LF/NUL 사전 거절 |
| 커서 정확성 | 차단→수정 | B3/B4. strict 진전만으로는 누락 간격·동일 나노초 정체를 구분 못 함. gap/stall 실패·실측 고정 |
| 인증/전송 | 보완 | A2. `trust_env=False`(.netrc·프록시), 키 형식 사전 검사, hook 금지 |
| owner/resource/type | 보완 | A1·B5. id 형식 fullmatch로 경로 조작 차단, 라벨 중복 거절, schema_match_only 출처 표시 |
| 네트워크/본문 상한 | 보완 | A3·A4. identity 인코딩·디코딩 후 상한·services 응답 상한, 최악 시간 35초 명시 |
| 완전성 vs coverage | PASS | coverage_verified=false·"API 반환0" 구분 적절. A5로 최근 구간 지연 표시 추가 |
| 부분 실패 원자성 | PASS(테스트 보강) | 전 페이지 완료 후 단일 ingest 트랜잭션. B6 테스트 위치 명시 |
| 보관기 재사용 | PASS(B2 조건) | `parse_record`/`ingest` 그대로, 30일·미래·중복 규칙 유지. 카운트 분리 보고 |
| 늦은 이벤트 | PASS | 중첩 재조회의 hash 중복 방지로 안전. 자동 체크포인트 없음이 범위와 일치 |
| dry-run 안전 | PASS | A6. ro 연결·init/prune 미실행, 보관기 무쓰기 의미 명확화 |

남은 비차단 사항: Render Free 로그 보존 기간과 그 이전 구간 소실은 coverage_verified=false로만 표현되며 실제 보존일은 미확인이다. 운영 저장소·스케줄·Render 스트림·실제 30일 연속 보관은 범위 밖으로 유지한다.

**판정: 위 A1~A6·B1~B6을 이 MD에 반영한 상태로 설계 PASS.** 구현은 B1·B3을 반드시 따라야 하며, 구현 후 정적 코드 검수는 별도로 수행한다. 이 PASS는 구현·실제 검증·운영 적용 완료를 뜻하지 않는다.

### 5.2 Claude 구현 정적 검수 (2026-11-15, 이 MD Read/Edit만 사용)

검토 근거: 대화로 제공된 `etl/operation_logs/render.py`·`tests/etl/test_render_log_adapter.py`·`archive.py`·`validation.py` 소스, Codex 검증 요약과 안전 조사/실행 요약 JSON. Claude는 아무것도 실행하지 않았고(테스트·Render 조회·SQLite 포함) 파일 시스템에서 해당 소스를 직접 열지도 않았다. 아래 통과/실측 수치는 모두 Codex 보고를 인용한 것이다.

| 관점 | 판정 | 근거(제공 소스 기준) |
|---|---|---|
| 인증/개인정보 | PASS | 키는 `RENDER_API_KEY`→`SecretStr`→Authorization 헤더만. 길이8~512·ASCII 33~126 사전 검사로 공백/개행/비ASCII 거절. `trust_env=False`·`follow_redirects=False`·기본 TLS·hook 없음. 오류는 고정 코드 `str(exc)`만, httpx 예외는 `api_network`로 치환, CLI 구간 `logging.disable(CRITICAL)` 후 복원. 라벨 값·provider id·wrapper·거절 message는 저장/출력하지 않음 |
| owner/resource/type | PASS | 네트워크 전 `OWNER`/`SERVICE` fullmatch(`[a-z0-9]`만이라 `/`·`.`·`%`·공백 불가)→경로 조작 차단. `/services/{id}`의 id·ownerId·`web_service` 대조 후에만 `/logs`. 행마다 라벨 name 중복 거절, resource==service·type==app 아니면 전체 실패. 정규식 길이가 설계 예시 `{20,}`와 달리 `{10,40}`인 것은 A1의 "실제 관측 형식으로 확정"에 해당하며, 실측 조회가 통과했으므로 수용 |
| 네트워크/본문/페이지 상한 | PASS | 고정 origin, services256KiB·페이지1MiB·총10MiB(디코딩 전=identity 확인 후 바이트), Content-Encoding 비identity는 스트림 읽기 전 거절, Content-Type JSON 강제, 20페이지/2,000행, 매 요청 전·chunk 후 monotonic 예산, 요청별 `min(5, 잔여)` timeout. JSON은 중복 키·NaN·`1e400`(parse_float)·RecursionError·과대 정수(ValueError)를 `api_payload`로 고정 |
| 나노초 커서 | PASS(아래 R1 기록) | 정규식+정수 연산(µs×1000+소수9자리), 윤초·비UTC·10자리 이상 거절. 허용 next_start는 `{last, last+1ns}`뿐이고 `≤lo`는 stalled, `<last`·`>end`·end 변경은 scope, `>last+1ns`는 gap. 제공 커서 문자열을 그대로 재전송. 실측(`last+1ns`, end 유지)과 B3 규칙이 일치 |
| 완전성 vs coverage | PASS | 성공 결과에 `api_window_complete=true`·`coverage_verified=false`·`provenance=schema_match_only`·`recent_window` 고정. 빈 구간도 "API 반환0" 테스트로 고정 |
| 부분 실패 원자성 | PASS | 전 페이지 `hasMore=false` 뒤에만 메모리 batch 생성→`read_input` 사전 불변식(rejected0·lines==forwarded)→단일 `ingest`. 네트워크/상한/커서/라벨 실패는 쓰기 연결 전 종료. 1·중간·마지막 페이지 실패, ingest 직전 KeyboardInterrupt, chunk 중 예산 초과의 파일 바이트 불변 테스트 존재 |
| 보관기 재사용 | PASS | `parse_record`의 canonical(`ensure_ascii`)만 `\n` 결합→`ingest`. 원 message의 CR/LF/NUL·4096바이트 초과는 parse 전 거절(B1). canonical 재파싱 hash 멱등 테스트 존재. 30일·미래·중복 규칙은 보관기 그대로. 실측 lines=rejected+future+expired+duplicate+would_insert(576=0+0+0+0+576 / 576=576+0) 성립 |
| 늦은 이벤트 | PASS | 중첩 재조회는 hash 중복으로 흡수(replay 576 duplicate). `recent_window`로 5분 이내 종료 구간 표시. 자동 체크포인트 없음은 범위와 일치 |
| dry-run 안전 | PASS | 사전 `archive.connect(path)`는 `mode=ro`+읽기 트랜잭션 rollback, `ingest(execute=False)`도 ro. init/prune 미호출, 대상 미존재 시 네트워크 전 `missing`. dry-run SHA 불변 테스트·실측 보고 일치 |

**차단 결함: 0건.**

비차단 기록·권고:

- (R1, 문서화 필수) 동일 타임스탬프 경계 절단: Render 커서가 `last+1ns`(배타형)이므로, 한 페이지가 100행에서 끊길 때 다음 미반환 행이 마지막 행과 **같은 타임스탬프**라면 그 행은 조회되지 않고 어댑터도 감지할 수 없다(gap 검사는 `last+1ns`를 정상으로 본다). 6자리(µs) 타임스탬프도 관측됐으므로 충돌 가능성이 0은 아니다. 이는 `coverage_verified=false` 범위에 포함되지만, `api_window_complete=true`가 "누락 없음"으로 읽히지 않도록 README·결과 해설에 이 한계를 명시해야 한다. 후속 자동화에서 필요하면 (a) 페이지 마지막 두 행이 같은 타임스탬프인 경우를 세는 진단 카운터, 또는 (b) 자체 포함형 커서(`startTime=last_ts`, 동일 ns 100행 초과 시 stalled fail-closed)를 별도 설계로 검토한다. 이번 범위에서 코드 변경은 요구하지 않는다.
- (R2, 테스트 보강 권고) 설계 §4-2 목록 중 제공 테스트에서 직접 확인되지 않는 항목: `trust_env=False` 생성 인자(예: `httpx.Client` 생성 spy로 `trust_env is False`·`follow_redirects is False` 확인), 비JSON Content-Type 거절, services 256KiB 상한, `hasMore=true`인 빈 페이지의 `cursor_stalled`, `lo < next_start < last`인 역행 커서의 `cursor_scope`. 코드는 정적으로 올바르게 처리하므로 차단은 아니며 PR 전 추가를 권고한다.
- (R3) A4의 "35초"는 §5의 Codex 보정(엄격한 wall-clock 보장 없음)이 우선한다는 기술을 유지한다. README에도 같은 표현을 쓴다.
- (R4) 동일 µs에 같은 내용을 가진 `llm_http_attempt` 2건처럼 canonical이 완전히 같은 정상 이벤트는 보관기 hash로 1건이 된다. #158 보관기의 기존 성질이며 이 어댑터가 새로 만든 문제는 아니지만, 운영 건수 해석 시 "고유 canonical 이벤트 수"임을 README에 남긴다.
- (R5) 행 `id`는 형식만 확인하고 중복을 검사하지 않는다. 실측에서 페이지 간 중복이 없었고 hash 중복 방지가 있으므로 수용한다.
- (R6) 결과 JSON의 `start`/`end`는 사용자 입력 문자열을 그대로 반영하나 정규식 검증을 통과한 시각뿐이라 비밀/원문 노출 위험은 없다.

범위 확인: 실측은 GET 전용·새 비공개 검증 보관기에만 쓰기였고 원본 Render 로그/설정·Free·자동배포off·운영 DB·.env·FE·스케줄·영구 저장소는 변경하지 않았다고 Codex가 보고했다. Claude는 이를 독립 확인하지 않았다. 공식 근거 미확정 매출/상권변화 pending, #158의 운영 영구 보관·주기적 prune·백업 삭제 검증 미완료는 그대로다.

**판정: 구현 PASS (차단 결함 0). R1은 README/결과 해설 문서화를 병합 전 반영, R2 테스트는 PR 전 추가 권고.** 이 PASS는 정적 검수 결과이며 CI·운영 적용·실제30일 보관 완료를 뜻하지 않는다.
