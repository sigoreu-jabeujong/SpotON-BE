# 공식 인허가 원천 단발 진단 (#137)

2026-11-15 사용자 요청의 다음 BE 작업이다. 기준 develop `43878f7`이며 #78의 외부 일반음식점 지연은 미해결이다. #136의 100행20초 실패·1행28.7초 성공·휴게100행3.09초 성공은 과거 표본이다. 당시 임시 진단기를 팀이 재현할 수 있는 정식 명령으로 만든다.

## 범위와 설계

`python -m etl.localdata.probe --source general_restaurant --authority-code 3130000 --rows 100 --read-timeout 20`을 제공한다. 두 Source enum과 서울25개 관청만 허용한다. Source/관청은 필수, rows는1 또는100(기본100), read timeout은 유한한0.1~30초(기본20)다. 자유 URL·키·임의header 인자는 없다. 기존 Settings의 키를 메모리에서만 읽고 실제.env를 보존한다.

공식 SOURCE_ENDPOINTS의 GET1회/page1만 전송한다. 자동 재시도하지 않고 요청별 `follow_redirects=False, auth=None`을 지정한다. connect5/write10/pool5/read선택값은 진단에만 적용한다. 소켓별 제한이며 전체 HTTP 완료 시간·DNS 시간 상한은 보장하지 않는다. 여러 페이지/관청 조회, wall-clock 기한, SIGTERM 처리는 범위 밖이다.

200/JSON 응답만 읽으며 선언된 Content-Length가2MiB를 넘으면 거부하고 디코딩된 누적 본문이2MiB를 넘으면 parser 전에 중단한다. 압축 해제된 청크는 이미 메모리에 있을 수 있어 엄격한 최대 메모리 보장은 아니다. Accept-Encoding은 httpx 기본값을 유지하며 디코딩 후 Content-Type만 복사해 재디코딩을 막는다.

기존 `LocalDataClient._parse_page`를 재사용하고 `min(total_count,requested_rows)`·page1·관청 불일치를 검사한다. 단일객체item을 list로 정규화하거나 공유 parser를 바꾸지 않는다. 관청 누락은 원래 계약처럼 허용하되 `matched/partial_missing/unverified/empty`를 구분한다. 성공은 해당 페이지 응답 계약이며 전체 수집·품질·업종 정답의 확인이 아니다.

JSON 한 줄에는 고정 operation/source/scope/page/요청행수/read timeout/phase/시도수/HTTP상태/소요ms/건수/관청검사/고정 오류만 둔다. URL·키·관청코드·원문·헤더·행·예외 문자열은 출력하거나 저장하지 않는다. httpx/httpcore URL 로그를 구성·요청·정리 구간에서 억제하고 원래 레벨로 복구한다.

성공0, 인자/설정실패2, HTTP/timeout/전송/계약/초과/정리실패1, 중단130이다. --help는 일반 도움말/0이다. 출력 단계 이전의 실패·중단을 요약하고 출력 도중 중단은 보장하지 않는다. Windows 차단 소켓의 즉시 중단도 약속하지 않는다. 실패의 부분 건수는 비우며 직접 만든 client만 닫는다. 정리 실패는 기존 원인을 덮지 않고 최초 원인을 보존한다.

DB·수집·snapshot/CSV·파일 저장·모델/migration·환경변수 추가·공개API·Render·FE·LLM은 바꾸지 않는다. 진단에서 시간 초과가 나도 성공으로 바꾸기 위해 timeout이나 재시도를 늘리지 않는다.

## 검증과 완료

실제 Claude Code의 설계 MD 검토 후 구현하고, 요청 수/수집기 params 비교·redirect/auth/재시도 금지·timeout·JSON/계약/압축/크기·중단/소유권/정리·입력/비밀 비출력/종료코드를 단위로 확인한다. 일반·정적 검사 후 기존 키를 자식 프로세스 환경으로만 전달해 실제 CLI3회(일반100/read20, 일반1/read30, 휴게100/read20)를 실행한다. 각1회이며 키/URL/원문을 저장하지 않는다.

CI/CodeQL 후 develop에 Squash하고 #137 기능만 완료한다. #78 외부 지연과 나머지 잔여, #115는 유지한다. 제품/API 배포나 DB 작업은 하지 않는다.

## 실제 Claude Code 검토

2026-11-15 검토. 읽은 범위는 이 MD, `etl/localdata/client.py`·`constants.py`·`dto.py`, `tests/etl/test_localdata_client.py`, `app/core/config.py`, `etl/localdata/maintenance.py`뿐이다. 명령·테스트·네트워크 실행은 하지 않았으므로 아래 내용은 코드 읽기에 근거한 판단이며, 실행 결과는 하나도 포함하지 않는다.

### 총평

방향은 맞다. 요청 1회, 재시도 없음, 리다이렉트 미추적, 수집기·공개 API 설정 불변, DB/파일 미사용, 비밀 비출력이라는 범위가 명확하고, 기존 `maintenance.py`의 결과 dataclass, `SafeParser`, 고정 error 접두사, JSON 1줄 출력, finally 정리 패턴과도 잘 맞는다. read timeout을 "전체 HTTP 시간 상한으로 약속하지 않는다"고 쓴 부분은 httpx 동작과 일치한다. 다만 구현 전에 문구나 결정을 바로잡아야 하는 차단 항목이 아래 5개 있다.

### 차단 항목 (구현 전 문구 수정 또는 결정 필요)

1. **"최대 2MiB(디코딩 후)"는 메모리 상한이 아니다.** httpx의 `iter_bytes()`는 원시 청크를 통째로 압축 해제한 뒤 돌려주므로, 누적 크기 검사는 청크가 이미 메모리에 풀린 뒤에야 이루어진다. 압축률이 높은 청크 하나는 2MiB를 크게 넘어 풀릴 수 있다. 문구를 "디코딩된 누적 바이트가 2MiB를 넘으면 다음 청크 전에 중단하고 parser를 호출하지 않는다"로 고치고, 원시 바이트 상한(`iter_raw` 누적 또는 `Content-Length` 사전 거부)을 함께 둘지 결정한다. 진단 결과를 수집기와 비교할 수 있도록 `Accept-Encoding`은 수집기와 같은 httpx 기본값을 유지한다(identity 강제는 측정 조건을 바꾸는 범위 확장이다).
2. **예외 분류 순서와 압축 오류.** `httpx.DecodingError`는 `RequestError`의 하위 클래스이지만 `TransportError`의 하위 클래스는 아니다. 계획처럼 "Timeout/RequestError"를 묶어 받으면 잘못된 gzip이 `transport`로 오분류된다. 잡는 순서는 `TimeoutException → DecodingError(contract 또는 별도 고정 사유) → TransportError → 그 밖의 RequestError(operation_failed)`로 명시한다. 테스트에는 `Content-Encoding: gzip` 헤더에 손상된 본문을 넣은 MockTransport 응답을 추가한다.
3. **numOfRows=1과 parser 재사용.** `_parse_page`는 `items.item`이 list가 아니면 `contract_error:rows`를 낸다. 1행 응답에서 원천이 item을 list가 아닌 단일 객체로 보낼 가능성은 이 저장소 안에서 확인되지 않는다(기존 테스트 fixture는 모두 list다). 공유 parser는 바꾸지 않는 것이 맞으므로, 단일 객체가 오면 `contract`(사유 rows)와 비0 종료로 보고하되 HTTP 상태와 소요 ms는 그대로 남긴다는 결정을 계획에 적는다. 그래야 1행 실측에서 contract 실패가 나와도 지연과 계약을 섞어 해석하지 않는다. 그 밖의 재사용 부분은 문제없다. `_parse_page`는 numOfRows 값을 검사하지 않고 page_no·totalCount·필수키만 확인하므로 1행과 100행 모두에 쓸 수 있다. 예상 행 수 `min(total, rows)`와 초과 검사는 probe가 따로 해야 한다는 계획 내용도 맞다.
4. **요청 파라미터가 수집기와 같아야 한다.** `_fetch_page`는 retry, 고정 `PAGE_SIZE`, 공유 client를 쓰므로 그대로 재사용할 수 없고, probe가 params를 새로 만들게 된다. 이때 `serviceKey`(params dict로 전달해 httpx가 인코딩), `pageNo`, `numOfRows`, `returnType=JSON`, `cond[OPN_ATMY_GRP_CD::EQ]`의 키와 인코딩 방식이 수집기와 다르면 #136 측정과 비교할 수 없다. MockTransport로 수집기 요청과 probe 요청(rows=100)의 URL path와 query를 비교하는 테스트를 추가한다. `client.py`를 리팩터링하는 일은 이번 범위에 넣지 않는다.
5. **"실패/중단도 요약 1건 유지"를 절대 보장으로 쓰면 안 된다.** `maintenance.py`의 정리 코드는 `except Exception`만 잡는다. 그래서 정리 중 두 번째 Ctrl+C나 print 도중 중단이 생기면 traceback만 남고 JSON은 나오지 않는다. 정리 단계에서도 `KeyboardInterrupt`를 잡아 기존 error가 없을 때 `interrupted`로 기록하고, 문구는 "출력 단계 이전의 실패·중단은 요약 1건으로 끝낸다"로 좁힌다. 또 Windows에서는 차단된 소켓 대기 중 누른 Ctrl+C가 그 대기(최대 read timeout)가 끝난 뒤에야 반영될 수 있으므로, "즉시 중단"을 약속하지 않는다고 적는다.

### 문구 검증: 종료 코드와 HTTP 기한

- 종료 코드: 계획은 인자·설정 실패를 2로 정했지만 기존 `maintenance.py`는 `int(result.error is not None)`이라 인자·설정 실패도 1이다. 2가 argparse 관례에 맞으므로 유지해도 되지만, 기존 CLI와 의도적으로 다르다는 점을 계획에 한 줄 적고 `main()` 테스트로 고정한다. `--help`는 argparse가 도움말을 출력한 뒤 `SystemExit(0)`으로 끝나므로 main이 이를 잡아 JSON을 덧붙이면 안 된다. 성공 0에는 `authority_check`가 `partial_missing`, `unverified`, `empty`인 경우도 포함된다는 점을 명시한다(관청 누락 허용과 일관).
- HTTP 기한: 실제 상한은 connect 5, write 10, pool 5, 그리고 소켓 수신 1회당 read X초다. 본문이 read 한도 안에서 조금씩 계속 들어오면 전체 소요 시간에는 상한이 없다. 2MiB 제한은 크기 상한일 뿐 시간 상한이 아니다. DNS 해석 시간이 connect timeout에 포함된다고도 보장하지 않는다. 그러니 "read timeout 20초 = 20초 안에 끝남"으로 읽히는 표현을 쓰지 말고, 무한 대기는 사용자 중단(130)으로만 끊긴다고 적는다. 전체 wall-clock 기한은 스레드나 신호 처리가 필요하므로 이번 범위가 아니다.
- read timeout 인자: argparse `type=float`는 `nan`, `inf`를 받아들이므로 `math.isfinite`와 0.1~30 범위를 직접 검사해야 한다. rows는 `type=int`와 `choices=[1, 100]`, 관청은 `SEOUL_AUTHORITY_CODES` 키로 제한하고 `SafeParser`를 써서 입력값이 stderr에 그대로 찍히지 않게 한다.

### 구체 개선 (권장, 차단 아님)

- **timeout 단계 구분**: `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`을 고정 사유값(connect/read/write/pool)으로 남기면, 원천 지연과 네트워크 문제를 구분하는 진단 목적에 직접 도움이 된다.
- **시간 측정**: `time.perf_counter`를 주입할 수 있게 하고, 헤더 수신까지(ms)와 본문 완료까지(ms)를 따로 남기면 #136의 "1행 28.7초"가 첫 바이트 지연인지 본문 지연인지 가릴 수 있다. 측정 시작점은 send 직전으로 정의한다.
- **고정 사유코드는 허용 목록으로 매핑**: parser 예외 메시지를 그대로 내보내지 말고 `envelope`, `result_code`, `page_no`, `total_count`, `items`, `rows`, `required_fields`, `page_no_mismatch`, `non_json_response`, `invalid_json` 등과 정확히 일치할 때만 출력하고, 나머지는 `contract`만 남긴다. `_fetch_page` 계열 메시지는 `source=…`, `page=…`를 포함하므로 섞이지 않게 한다.
- **비200과 비JSON**: 3xx·4xx·5xx는 본문을 읽지 않고 닫으며 `Location`을 출력하지 않는다. 200이지만 JSON이 아닌 응답(인증키 오류 등이 이렇게 올 수 있으나 이 저장소에서 확인한 근거는 없다)은 `contract:non_json_response`로 나오므로, 해석할 때 "키 또는 게이트웨이 문제일 수 있음"으로 읽는다고 적어 둔다.
- **timeout 적용 방식**: 주입된 client에도 요청 단위 `timeout`과 `follow_redirects=False`를 넘기고, 테스트에서는 `request.extensions["timeout"]`의 read 값을 확인한다. 직접 만드는 client는 수집기와 같은 connect 5, write 10, pool 5를 쓴다.
- **정리 순서**: 스트림 응답을 먼저 닫고, 그다음 직접 만든 client만 닫는다. 정리 실패는 기존 error를 덮어쓰지 않는다(`maintenance.py`와 같은 방식).
- **설정 범위**: `Settings()`는 DB 연결 예산 같은 관련 없는 항목의 검증 실패로도 `ValidationError`를 낸다. 이것도 `configuration`으로 처리되는 것이 맞다는 점과, 서비스 키가 공백뿐일 때도 `configuration`(LocalDataClient와 같은 strip 기준)으로 처리한다는 점을 적는다. 테스트를 위해 `Settings` 주입을 허용한다.
- **DB/파일 0 보장**: probe 모듈이 `app.db`, `sqlalchemy`, runner, loader를 import하지 않는지 정적으로 검사하는 테스트가 실행 중 쓰기 감시보다 단순하다.
- **로그 억제의 부작용**: `_suppress_http_url_logs`는 이전 레벨과 상관없이 WARNING으로 설정했다가 복구한다. 단일 스레드 CLI라서 문제는 없지만, 레벨을 복구하는지 확인하는 테스트를 넣는다.
- **문서 가독성**: 본문 대부분이 띄어쓰기 없이 붙어 있어 검토하기 어렵다. 구현 PR에서 README와 계획 문서에 옮길 때는 띄어 쓴다.

### 범위 확장으로 보고 이번에 하지 않을 것

전체 wall-clock 기한, 재시도와 backoff, 여러 관청이나 여러 페이지 조회, `Accept-Encoding` 변경, 공유 parser가 단일 객체 item을 받도록 바꾸는 일, `client.py`의 params 생성 리팩터링, 결과 파일 저장, SIGTERM 처리, 수집기나 공개 API의 timeout 조정. 이 중 단일 객체 item 수용과 수집기 timeout 조정은 #78 판단과 이어지므로 별도 이슈로 다룬다.

### 실측 계획에 대한 메모

실측 3회는 각각 표본 1개라서 지연이 재현되는지만 보여 줄 뿐, 분포나 해소 여부를 말해 주지는 않는다. 실패(비0 종료)가 나와도 그것은 진단 결과이며 기능 결함이 아니라는 계획 문구는 적절하다. 3번 결정에 따라 1행 실측이 contract로 끝날 수 있다는 점을 미리 적어 둔다.

## Codex 판단과 실행 결과

### 구현 결정

- 검토의5개차단사항을반영한다. Content-Length가2MiB를넘으면미리거부하고디코딩후누적2MiB초과시parser전에중단한다. 원시청크의압축해제순간까지포함한엄격한메모리상한은아니며전체wall-clock기한도추가하지않는다. Accept-Encoding은httpx기본값을유지한다.
- TimeoutException→DecodingError(contract)→TransportError→그밖RequestError(operation_failed)순서로분류한다. 단일객체item은공유parser를바꾸지않고contract로반환하며HTTP상태와시간을남긴다. parser실패의원문메시지는출력하지않고고정contract로요약한다.
- 원래수집기와같은Source endpoint/params/encoding을독립MockTransport비교로고정한다. 요청당follow_redirects=False뿐아니라auth=None도지정해주입client의인증challenge가추가요청을보내지못하게한다.
- response와소유client를명시적으로정리하며최초실패사유를유지한다. 정리중KeyboardInterrupt는기존사유가없을때interrupted가된다. 출력단계이전의실패/중단을요약하며출력중중단/SIGTERM이나Windows차단소켓의즉시취소는보장하지않는다.
- 설정실패/인자실패의2는기존maintenance의1과의도적으로다르며CLI단위로고정한다. 관청부분누락/미확인/빈응답은현재parser계약을유지한성공0이지만authority_check가그상태를명시한다.

초기단위57개가통과했고압축초과/직접인자/설정실패경계를추가한다. 실제원천지연과#78의잔여는그대로유지한다.

## 실제 Claude Code 구현 검토

2026-11-15 검토. 읽은 파일은 이 MD, `etl/localdata/probe.py`, `tests/etl/test_source_probe.py`, `etl/localdata/client.py`, `etl/localdata/constants.py`, `etl/localdata/dto.py`뿐이다. 명령·테스트·네트워크는 실행하지 않았다. 사용자가 전한 상태는 "focused 85개 통과 후 경계 3개 추가, 일반/정적 검사 진행 중, 실제 CLI 3회 검증 예정 또는 진행 중"이다. 아래 내용에는 내가 직접 확인한 실행 결과가 없다.

### 결론

코드에서 머지를 막을 결함은 찾지 못했다. 완료를 막는 것은 아직 기록되지 않은 검증 결과뿐이다. 하나는 ruff/format·mypy·일반 pytest의 최종 결과이고, 다른 하나는 실제 CLI 3회 요약이다. 위 "초기단위57개" 문구도 최종 테스트 수로 갱신해야 한다.

### 계획 대비 확인 (코드 읽기 기준)

- **비공개 정보**: `ProbeResult`(`probe.py:41-56`)에는 URL·key·관청 코드·헤더·행·예외 문자열 필드가 없다. 모든 except 분기(`probe.py:176-195`)는 고정 Literal만 대입하고 `str(e)`나 로그를 쓰지 않는다. `SafeParser.error`(`probe.py:72-74`)는 argparse 메시지를 버린다. 실패하면 `total_count`·`row_count`·`authority_check`를 비운다(`probe.py:213-215`). 비200 응답은 본문을 읽지 않고 닫으며, Location을 출력하지 않는다. URL 로그는 `_suppress_http_url_logs`가 구성·스트리밍·정리 구간 전체를 감싸 억제하고(`probe.py:125`) 원래 레벨로 복구한다. 테스트는 CANARY 문자열로 이를 검사한다.
- **정확히 GET 1회**: `send(..., follow_redirects=False, auth=None)`(`probe.py:161`)을 쓴다. httpx는 `auth=None`이면 client 기본 auth 대신 challenge 흐름이 없는 기본 `Auth()`를 쓰므로, 주입된 client에 DigestAuth나 `follow_redirects=True`가 있어도 추가 요청이 나가지 않는다. 테스트(`test_source_probe.py:84-112`)가 301/307/401/429/5xx 모두 1회임을 고정한다. 직접 만든 client는 기본 transport(retries=0)를 쓴다. params와 인코딩은 `_fetch_page`(`client.py:207-213`)와 같고, 테스트(`test_source_probe.py:41-63`)가 공백·`+/=%`가 들어간 key로 두 요청의 URL이 같은지 비교한다. 수집기와 마찬가지로 `trust_env` 기본값이라 환경 proxy를 따른다. 측정 조건이 같다는 뜻이다.
- **스트리밍·gzip·헤더**: Content-Type 확인을 본문을 읽기 전에 한다. Content-Length는 ASCII 숫자이고 20자 이하일 때만 2MiB와 비교해 미리 거부한다. gzip이면 이 값은 압축 크기이므로 보수적인 사전 거부일 뿐이다. 그다음 `iter_bytes()`가 디코딩한 누적량을 청크마다 검사하고, 넘으면 parser를 부르지 않는다(`probe.py:77-96`). 새 Response에는 Content-Type만 복사해 이중 디코딩을 막는다. 압축된 작은 본문이 디코딩 한도를 우회하지 못하는지와 손상된 gzip이 `contract`로 분류되는지도 테스트된다(`test_source_probe.py:219-260`).
- **예외 분류 순서**: Timeout → (DecodingError, 계약 위반) → TransportError → ResponseTooLarge → KeyboardInterrupt → Exception 순서다. 설계 결정과 일치한다. `ResponseTooLarge`는 ValueError 하위지만 그보다 먼저 잡는 `ValidationError`와 겹치지 않는다.
- **정리와 client 소유권**: response를 먼저 닫고, 직접 만든 client만 닫는다(`probe.py:197-210`). 정리 중 Exception이나 KeyboardInterrupt는 기존 error가 없을 때만 `cleanup` 또는 `interrupted`로 기록한다. 주입된 client가 닫히지 않는지(`test_source_probe.py:37`)와 직접 만든 client의 정리 실패 조합(`test_source_probe.py:315-337`)이 테스트된다.
- **CLI**: stdout에 JSON 1줄을 `allow_nan=False`로 출력한다. 종료 코드는 성공 0, arguments/configuration 2, interrupted 130, 나머지 1이다(`probe.py:237-242`). `--help`는 argparse의 `SystemExit(0)`을 그대로 통과시켜 JSON을 붙이지 않는다. 잘못된 인자를 줬을 때 stderr가 비어 있고 Settings를 읽지 않는 것도 테스트된다.

### 인정하는 한계 (차단 아님, 계획과 일치)

- 전체 HTTP 소요 시간에는 상한이 없다. read timeout은 수신 대기 1회당 한도일 뿐이다. 본문이 한도 안에서 조금씩 계속 들어오면 끝없이 이어질 수 있고, 그때는 사용자 중단(130)으로만 끊긴다.
- 최대 메모리 사용량을 엄격하게 보장하지 않는다. 압축 해제된 청크 하나가 누적 검사 전에 이미 메모리에 올라온다. 2MiB 제한은 parser 입력과 누적량의 상한이다.
- 출력 단계 중의 중단, SIGTERM, Windows에서 차단된 소켓 대기의 즉시 취소는 보장하지 않는다.

### 사소한 개선 (선택, 이번 범위 밖으로 둬도 됨)

- `elapsed_ms`를 finally에서 정리가 끝난 뒤 계산한다(`probe.py:211-212`). 그래서 close 시간이 포함되고, 헤더까지와 본문까지가 구분되지 않는다. #136의 1행 28.7초를 해석하려면 헤더 수신 ms를 따로 두는 것이 유용하다(범위 확장).
- 2MiB 안의 깊게 중첩된 JSON은 `RecursionError`로 `operation_failed`가 될 수 있다. `contract`가 더 정확하지만 노출되는 정보는 없다. `except ValidationError`의 contract 분기는 `from_api`가 pydantic을 쓰지 않으므로 사실상 실행되지 않는 방어 코드다.
- 직접 만드는 `httpx.Client` 생성 실패(예: 환경 proxy나 인증서 변수 오류)는 phase가 configuration이라 2로 끝난다. 환경 설정 오류로 보면 맞는 분류이니 README에 한 줄 적는 정도면 된다.
- 테스트 보강 후보: 영속성 import 정적 검사(`test_source_probe.py:386-399`)는 `ImportFrom`만 보고 `import sqlalchemy` 형태와 전이 import는 보지 않는다. `main()`이 직접 만든 client 경로 전체(MockTransport로 `httpx.Client` 교체)를 거칠 때 stdout에 관청 코드와 key가 없는지 확인하는 테스트, 그리고 본문 스트리밍 도중 KeyboardInterrupt 사례도 추가할 수 있다.

### 실측 기록 시 유의

실측 3회(일반음식점 100행/read 20, 1행/read 30, 휴게음식점 100행/read 20)는 각각 표본 1개다. 비0 종료는 진단 결과이고 기능 결함이 아니다. 기록에는 고정 필드 요약만 남기고 원문·URL·key는 남기지 않는다. 1행 응답이 단일 객체 item으로 오면 `contract`이지만 HTTP 상태와 ms는 남는다는 점을 함께 적는다.

## 최종 검증과 판정

- 새 회귀71개와 기존 일반 검사를 합친 **1,806개 통과**, ruff/check·format·strict mypy161 files 통과. 기존 수집기 요청과 특수문자가 든 키의 인코딩이 같고 redirect/인증challenge/429/5xx가 추가 GET을 만들지 않는 것을 확인했다. 압축 초과·부분 스트림 실패·client 정리/중단·비밀canary·CLI 종료코드를 포함한다.
- 실제 CLI3회는 각 attempts=1, stdout JSON1줄·stderr0·키/URL 비출력·종료코드1을 확인했다. 일반100행은20.063초, 일반1행은30.141초, 휴게100행은20.046초에 `localdata_probe:timeout`이었다. HTTP상태를 받지 못해 이번에는 실제 성공 응답의 계약 검사를 수행하지 못했다. 응답/계약 성공 경로는 MockTransport로 검사했으며 실측 성공으로 대신 쓰지 않는다.
- 세 경우 모두 단발 표본이므로 지연 분포·키/승인 오류·근본 원인을 단정하지 않는다. 이전 #136의 성공 표본을 이번 결과로 쓰지 않고 #78 지연은 계속 미해결로 둔다. 실측은 진단 명령의 요약/종료/비밀 비노출을 확인한 것이며 upstream 장애 해소가 아니다.
- 설계/구현의 실제 Claude Code 검토2회는 정상 종료·is_error=false·권한 거절0이었다. 구현 검토는 차단 결함을 찾지 못했고 결과 기록을 완료 조건으로 요구해 이 절에 반영했다. elapsed_ms에는 요청과 정리가 포함되고 client 생성/설정은 빠진다. 헤더 지연 분리·전체 wall-clock 기한·더 넓은 수집은 추가하지 않는다.
- 실제.env hash 보존, DB/모델/migration/기존 수집기/공개API/Render/FE 변경0. README와 BE 계획·감사에 사용법/판정 범위를 기록한다. CI/CodeQL 및 병합 상태는 연결 PR로 확인한다.
