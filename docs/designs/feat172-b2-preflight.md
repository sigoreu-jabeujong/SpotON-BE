# B2 원격 백업 연결 사전 점검 (#172)

작성: 2026-11-16 KST. 기준 develop `b459ead`. 브랜치 `feat#172-b2-preflight`.

## 1. 목적과 범위

실제 B2 계정/버킷/키는 제공되지 않았다. 기존 SPBK 내보내기는 완료됐고 연결 검증은 미구현이다. 이번 단계는 metadata 설정과 읽기 전용 인증/버킷 점검의 BE CLI를 구현하고, 계약 fixture/MockTransport로 검증한다. 실제 공급자 연결 성공을 주장하지 않는다.

새 모듈은 `etl.operation_logs.b2_preflight`, 테스트는 `tests/etl/test_b2_preflight.py`다. 기존 HTTPX/Pydantic/파일 경로 가드를 재사용한다. FE·공개 API·0012·의존성·.env·기존 Task/runtime·운영 DB/Render는 유지한다.

업로드·다운로드·객체/버킷 변경·키 생성/디스크 저장·토큰 캐시·암호화·비용/만료/복구 검증·자동 스케줄은 구현하지 않는다. Native auth의 토큰 발급 외에 백업 객체/버킷 설정을 변경하는 작업이 없다.

## 2. 공식 계약과 정책 구분

- [authorize v4](https://www.backblaze.com/apidocs/b2-authorize-account): GET+Basic으로 단발 토큰과 storageApi 메타데이터를 받는다. v4 allowed는 buckets의 id/name·capabilities·namePrefix를 담는다.
- [list_buckets v4](https://www.backblaze.com/apidocs/b2-list-buckets): POST로 지정 bucketName을 조회한다. 권한은 **listBuckets**이며 `readBuckets`가 아니다. account/bucket ID·이름·유형을 대조한다.
- [권한 의미](https://www.backblaze.com/docs/cloud-storage-application-key-capabilities): 보고된 파일 조회/쓰기/삭제 capability와 실제 동작 검증은 구분한다.
- [Native 버킷 문법](https://www.backblaze.com/docs/cloud-storage-buckets): 6~63자 ASCII 영문/숫자/하이픈/점, 대소문자 비구분. 금지된 점·IP형식·예약 접두를 검사한다.

단일 버킷·정확한 prefix·정해진 capability 상한·비공개 유형만 허용하는 것은 SpotON의 별도 운영 정책이다. 공식 API가 모든 계정에 이 제한을 요구한다고 쓰지 않는다.

## 3. CLI와 입력

```text
python -m etl.operation_logs.b2_preflight --config <absolute-metadata.json> [--execute]
```

설정은 정확히 `bucket_name`, `region`, `prefix` 세 문자열이다. bucket_name은 Native 규칙을 따르며 비교는 ASCII 대소문자를 무시하고 요청에는 입력 표기를 유지한다. provider가 돌려준 버킷명(auth allowed name·list 응답 bucketName)도 비교 전에 같은 ASCII Native 문자/길이 검사를 통과해야 하며, Unicode lower 변환으로 ASCII와 같아지는 이름(예: Kelvin sign)은 불일치로 실패한다. region은63자 이하 소문자 DNS label, prefix는128자 이하 ASCII 경로(`A-Za-z0-9._-/`)이며 상대 경로·비어 있지 않은 segment·끝 slash를 요구하고 . 및 .. segment는 거부한다. 예시 prefix는 `spoton-operation-logs/`다.

파일은 Git 밖의 로컬 절대 JSON 경로, 존재하는 부모, 일반 파일/nlink1/비-reparse/비-symlink만 허용한다. 16KiB 이하·UTF-8·중복 키/비정상 JSON 상수·추가 필드를 거부하고 nofollow/fstat/identity·크기/mtime 대조로 읽는다. 기존 `read_config`는 키 집합이 다르고 mtime 대조가 없으므로 그대로 호출하지 않고 같은 패턴으로 새로 작성한다. `archive.validate_file_path`가 try 밖에서 던지는 `ArchiveError`와 경합 중 `OSError`(FileNotFoundError 등)도 인자 오류(2)로 고정 매핑한다. 파일/디렉터리/sidecar를 생성하거나 덮지 않는다. 기존 planning 입력 양식은 runtime 설정과 다른 형식이다.

기본 preview는 설정만 검사한다. credential 환경 조회·Client/Transport 생성·네트워크는0이다. 잘못된 metadata도 키 접근 전에 실패한다. 설정 파일은 metadata 전용이고 키 필드가 들어가면 거부한다.

execute만 현재 process의 `B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY`를 읽는다. 앱 `.env`를 로드하거나 수정하지 않는다. ID는 `[A-Za-z0-9_-]{1,128}`(Basic user-id 규칙상 `:` 금지를 포함)이고, 키는 공백/제어문자가 없는 ASCII/512자 이하로 제한한다. 값은 SecretStr/비노출 repr로 취급하고 인자·JSON 설정·로그·결과에 넣지 않는다. 비어 있거나 잘못된 키는 HTTP0으로 실패한다. 키 값은 사용자에게 채팅으로 요청하지 않는다.

## 4. 고정 네트워크 경로

1. `https://api.backblazeb2.com/b2api/v4/b2_authorize_account`로 GET. Basic은 이 요청에만 적용하며 Client 기본 auth로 두지 않는다.
2. 응답의 storageApi `apiUrl`은 https·`api[0-9]{3}.backblazeb2.com`·빈 path/단일 slash만 허용한다. credentials/port/query/fragment·다른 host/IP는 거부한다. `s3ApiUrl`은 사용하지 않고 exact `https://s3.<region>.backblazeb2.com`과 비교해 리전만 점검한다.
3. authorizationToken/accountId 및 v4 구조·권한/범위를 검증한 후에만 검증된 apiUrl의 `/b2api/v4/b2_list_buckets`로 POST한다. 본문은 accountId와 지정 bucketName뿐이고 Authorization은 raw Native 토큰이다. Basic/환경 키를 두 번째 요청에 전달하지 않는다.
4. 응답은1개 버킷이어야 하고 accountId·bucketId가 auth 범위와 같고 bucketName이 설정과 같아야 한다. bucketType은 `allPrivate`만 허용한다. 다른 유형/여러 버킷/미일치는 실패하며 자동 수정하지 않는다.

authorizationToken은 공백/제어문자 없는 출력 가능 ASCII·1024자 이하, accountId와 allowed bucket id는 `[A-Za-z0-9_-]{1,128}`로 검사한 뒤에만 헤더/본문에 넣는다(헤더 주입 방지).

최대2요청, 재시도/redirect/환경 proxy 차단, TLS 검증 유지. 구현은 `httpx.Client(trust_env=False, follow_redirects=False, verify=True)`와 `HTTPTransport(retries=0)`이며 trust_env=False로 proxy·netrc·SSL 환경 변수를 무시한다. Client/Transport는 주입 가능한 factory로 만들어 테스트가 MockTransport를 넣고 preview의 생성 횟수0을 단언한다. httpx는 기본 `Accept-Encoding`에 압축을 넣으므로 명시적으로 덮어쓴다. `Accept-Encoding: identity`·JSON MIME을 요구하고 압축 응답을 거부한다. 응답별1MiB/합계2MiB·8KiB chunk·30초 monotonic 예산·HTTP phase별 최대5초 및 잔여 예산을 사용한다. OS I/O까지 강제하는 hard wall timeout은 아니다.

오류 body/메시지는 출력·저장하지 않는다. 401 authentication,403 provider_denied_or_cap(권한/transaction cap을 단정하지 않음),429 rate_limit,3xx redirect,그외 http로 고정 분류한다. 전송 예외는 `httpx.TimeoutException`→timeout, 그 밖의 `httpx.HTTPError`(TransportError의 TLS/연결 포함, identity 강제로 사실상 도달하지 않는 DecodingError 포함)→network, 예산 소진→network_budget, 상한 초과→response_limit, Reader의 3번째 요청 시도→request_limit, 그 밖의 예외(`httpx.StreamError`/`InvalidURL` 포함)→internal로 고정하고 예외 문구는 버린다. body는 성공 응답만 제한 파싱하며 중복 키·비유한 숫자·잘못된 타입/과도한 구조는 payload 실패다.

## 5. 범위/권한 검증

`allowed.buckets`는 정확히1개이고 name이 설정과 일치해야 하며 id는 유효한 비공개 토큰이다. null/무제한·여러 버킷·name null을 거부한다. namePrefix는 설정 prefix와 정확히 같아야 하며 null/빈 문자열(prefix 무제한)은 거부한다. auth token/accountId는 비공개 메모리에서만 유지하고 응답 URL을 믿고 임의 host로 전달하지 않는다.

최소 필수 capability는 `listBuckets`다. 허용 상한은 `listBuckets/listFiles/readFiles/writeFiles/deleteFiles/readBuckets/readBucketEncryption/readBucketRetentions/readFileRetentions/readFileLegalHolds/readBucketReplications/readBucketNotifications/shareFiles`다. account/key/bucket 설정 변경·bypass·전체 버킷 나열 및 미지정 capability는 거부한다. shareFiles는 readFiles와 같은 prefix 범위의 조회용 grant와 호환하기 위해 받아들이지만 호출하지 않는다.

향후 백업에 필요한5개(`listBuckets/listFiles/readFiles/writeFiles/deleteFiles`)의 보고된 포함 여부는 `backup_capabilities_complete`로 제공한다. 부족해도 최소 조회 권한과 범위가 맞으면 **연결 점검**은 성공할 수 있다. 실제 write/delete 수행·Object Lock/replication/30일 삭제·요금 한도·암호화·오프호스트 복구의 증명이 아니다. 관련 검증 값은 false로 남긴다. key/token 만료 시각의 단위를 추정하거나 토큰을 재사용하지 않는다.

## 6. 결과와 실패

stdout JSON 한 건, 정상0/인자2/일반실패1/중단130. 고정 필드만 반환한다:

- status/error/mode/phase/rule_version.
- config_verified, credentials_read_attempted, credentials_validated.
- requests_attempted(0~2, wire 성공 보장 아님), authorization_verified, key_scope_verified, region_verified.
- bucket_private_verified, backup_capabilities_complete, connection_verified.
- backup_objects_modified=false, bucket_settings_modified=false, billing_verified=false, retention_verified=false, remote_backup_verified=false.

error는 고정 어휘만 쓴다. 모듈 상수 `ERRORS`는 정확히 credentials, authentication, provider_denied_or_cap, rate_limit, redirect, http, timeout, network, network_budget, response_limit, payload, api_url, region, scope, capability, bucket_mismatch, bucket_not_private, request_limit, internal의 19개이고, CLI 계층이 별도로 arguments, interrupted를 더한다(총 21개). `ERRORS`에 없는 reason은 internal로 접는다. 테스트는 소속 여부뿐 아니라 이 집합 전체를 리터럴 동등 비교로 고정한다. 경로·버킷/계정/키/토큰/prefix/URL·provider 원문/예외 문구를 반환하지 않는다. 보고 객체를 호출 전부터 공유해 CLI 최외곽 오류가 나도 이미 확인한 phase/카운터/모드를 잃지 않게 한다. 연결 성공은 단발 조회 결과이며 이후 전송 때 재검증해야 한다. failed 상태에서도 앞서 확인한 플래그는 보존한다.

## 7. 검증

- 공식 v4 형태의 가상 fixture + MockTransport. 실제 자격 증명/공급자 호출0.
- 기본 preview·실패 metadata의 환경 조회/Client/HTTP0, 입력/파일 hash 불변, CLI 비노출/exitcode.
- 정확한2요청·Basic 첫 요청만·토큰 둘째만·bucketName 필터·정확한 계정/id/name/type·대소문자/region/prefix.
- 무제한/다중/null 범위·부족/과잉/unknown/중복 cap·보고된 백업 grant의 한계.
- 악성 apiUrl/s3Url·redirect/proxy·429/403·timeout·TLS/예상 밖 예외·KeyboardInterrupt·키 누락/변형·canary 원문 비노출.
- body/합계/예산·압축·MIME·중복 JSON·비정상 숫자/형식·잘못된 bucket 결과·정리(close) 검증.
- source 없음/기존 JSON/link/경합 읽기·16KiB 상한·Git/상대/원격 경로·추가 키 금지.
- 기존 전체 일반/Windows native·ruff/format·Windows/Linux mypy, CI Linux/Windows/PostGIS·CodeQL.

실제 B2 연결·최소 비용/만료/복구는 사용자 계정/전용 버킷/적절한 키 제공 후 별도 확인한다. mock 성공으로 대체하지 않는다.

## 8. 커밋과 검토

이 설계를 실제 Claude가 이 MD만 Read/Edit하도록 제한해 검토한다. 제공한 코드/계약 발췌 외 다른 파일·Git/shell/DB/network/MCP/agent 도구를 허용하지 않는다. 실제 MD diff와 이유를 Codex가 대조한 뒤 구현한다.

기능과 관련 테스트, README/CLAUDE/작업계획·Windows CI 연결을 한 커밋 `feat(be): B2 연결 사전 점검 CLI 구현`에 담는다. 실제 실행/재검수 근거를 기록하고 검사 통과 뒤 지정 양식 PR·정상 Squash·main BE ff-only를 수행한다. 임시 계정/유료 자원·키 저장·기존 수집 전환은 하지 않는다.

## 9. 현재 상태

설계 검토(§10)·구현(§11)·구현 검토(§12)·보완(§13)·최종 문서 검토(§14)까지 진행했다. 다음 단계는 PR CI(Linux/Windows/PostGIS·CodeQL)다. 실제 B2 연결은 수행하지 않았다. 검토/수정/검증 근거는 아래 후속 절에 기록한다.

## 10. Claude 설계 검토 (2026-11-16)

판정: **PASS (수정 반영 후)**. 검토는 이 MD와 사용자가 제공한 helper 발췌/계약 노트만으로 하는 문서 검토다. 코드·테스트·명령·네트워크를 실행하지 않았고, 구현/테스트 통과/공급자 연결 근거가 아니다.

수정한 내용과 이유:

1. §3 `symlink만 허용` → `비-symlink`. 원문이 의도와 반대로 읽혀 구현 오류를 부를 수 있었다.
2. §3 config reader: 기존 `read_config`는 키 집합이 고정이고 mtime 대조가 없다. `validate_file_path`의 `ArchiveError`는 try 밖에서 발생하며, 경합 중 `OSError`는 잡히지 않는다. 그래서 새 reader 작성과 인자 오류(2) 매핑을 명시했다.
3. §3 key ID `:` 금지: Basic user-id에 `:`가 들어가면 base64 인코딩 전에 경계가 모호해진다.
4. §4 token/accountId 형식·길이 상한: 응답 값을 Authorization 헤더와 본문에 그대로 넣기 전에 주입과 과대 값을 막는다.
5. §4 httpx 구성: `trust_env=False`(proxy·netrc·SSL 환경 무시), redirect off, `retries=0`, `Accept-Encoding` 명시적 덮어쓰기(httpx 기본값에 압축 포함), 주입 가능한 factory를 명시했다. 마지막 항목이 없으면 preview의 Client/Transport 생성0을 테스트로 증명할 수 없다.
6. §4 전송 예외 분류: 상태 코드 분류만 있고 timeout·TLS·연결 오류가 미정이었다. 고정 코드와 문구 폐기를 명시했다.
7. §5 namePrefix null/"" 거부 명시: 계약상 prefix 무제한 키는 null로 올 수 있다. "정확히 같음"만으로는 null 처리가 암묵적이었다.
8. §6 error 고정 어휘: 비노출 보장을 테스트할 수 있게 집합을 고정한다.

확인했고 수정하지 않은 항목:

- 범위: 업로드·삭제·암호화·원격 보존이 제외되어 있다. 네트워크 경로는 authorize GET과 list_buckets POST의 고정 2건이며 읽기 전용이다(토큰 발급 외 상태 변경 없음). preview는 환경 조회·Client·네트워크가 0이다.
- 계약: list_buckets 권한이 listBuckets라는 점, v4 `allowed.buckets` 배열(null=무제한, name null 가능), raw token Authorization, bucketType 확인 모두 제공된 계약 노트와 일치한다. 단일 버킷·prefix·cap 상한·allPrivate·`api[0-9]{3}` host·s3ApiUrl exact 비교는 SpotON 정책(fail-closed)으로 구분되어 있다. host 형식이 바뀌면 실패하는 것은 의도된 보수적 동작이다.
- 한계: 2요청×phase 5초, 30초 monotonic 예산, 1MiB/2MiB 상한이 있다. hard wall timeout이 아니라는 점도 명시되어 있다.
- 증거: fixture는 합성 값이고 MockTransport 성공은 실제 공급자 증거가 아니다. 이 점이 §1·§7에 명시되어 있으며 실제 연결은 계정/버킷/키 제공 후 별도로 확인한다.
- 테스트(§7)는 모두 MockTransport, monkeypatch된 환경, tmp_path로 실행할 수 있다. 실제 자격 증명은 필요 없다.

구현 시 유의(설계 변경 아님): bucket_name 대소문자 무시 비교는 auth allowed name과 list 응답 name 모두에 같은 함수로 적용한다. `credentials_read_attempted`는 metadata 검증 통과 뒤에만 true가 되어야 한다.

## 11. Codex 대조 및 구현

설계 검토 실제 호출은2026-11-15T15:31:48Z~15:33:17Z exit0/is_error=false/9turns, MD SHA `09a0054c7f66383ecbd2a8a437c60993267c417e05ade3a299d5f0f6dff6160c` → `ac54b7af6d8237fa7ddb4a25b567566b81507d2dc6e7d3dc1ec6d3a3291a73e8`였다. permission_denials0·다른 제공 파일 SHA 보존·실제 MD 직접 수정을 확인했다. Codex는8개 수정 이유와 diff를 대조해 모두 수용했다.

새 config reader·공유 Result·엄격한 v4 parser·두 요청 Reader를 구현했다. Client뿐 아니라 명시 HTTPTransport에도 trust_env=False를 주어 SSL 환경 참조까지 막고 TLS 검증/retries0을 유지한다. key/토큰이 Client 기본 auth로 남지 않도록 요청별 auth를 사용하고 두 번째 호출은 raw Native 토큰만 전달한다. 기본 preview와 잘못된 metadata는 환경 키 조회/Client/Transport 생성 전에 종료한다.

가상 v4 payload/MockTransport의93개 사례 중 현재 Windows92통과·symlink 권한1skip,1.67초다. 실제 B2 호출·키·계정은 사용하지 않았다. 정상/readonly grant·host/scope/region/private·응답/예산·전송 오류·키/형식·metadata 경합·CLI 최외곽 중단과 비노출을 포함한다.

전체 Windows 일반2333통과·symlink 권한3skip·PostGIS298분리,82.99초다. 기존 Starlette 경고1건, ruff check/432파일 format·Windows/Linux mypy 각194파일도 통과했다. 가상 metadata로 실제 CLI preview를 실행해 config SHA 보존·환경 credential 조회/HTTP0·connection/변경 플래그 false를 확인했다. 이는 실제 B2 공급자 연결 근거가 아니다. 구현 재검토·CI 결과는 완료 후 기록한다.

## 12. Claude 구현 검토 (2026-11-16)

판정: **PASS (문서 정합화 3건 반영, 커밋 전 테스트 1건 추가 조건)**. 이 MD와 사용자가 붙여 넣은 `b2_preflight.py`/테스트/helper 발췌/계약 노트/Codex 근거만 읽고 검토했다. 코드·테스트·명령·네트워크를 실행하지 않았다. 아래 테스트 수치는 Codex 근거를 인용한 것이며 내가 확인한 결과가 아니다. MockTransport 결과는 실제 B2 공급자 근거가 아니다.

### 설계 수정과 이유

1. §6 error 어휘: 구현 `ERRORS`에 `request_limit`이 있는데 설계 목록에는 없었다. 정확한 19+2 집합으로 바꿨다. `ERRORS`에 없는 값을 `internal`로 접는다는 점도 적었다. 이 규칙은 `PreflightError(CANARY)`→internal 테스트가 이미 검증한다.
2. §4 예외 분류: 설계는 `TransportError`→network였지만 구현은 더 넓은 `httpx.HTTPError`를 잡는다. 이 범위에서 추가로 들어오는 것은 DecodingError뿐이고, 압축 응답을 body 읽기 전에 거부하므로 사실상 도달하지 않는다. 동작에는 해가 없어서 설계를 구현에 맞췄다. `StreamError`/`InvalidURL`은 HTTPError가 아니므로 internal로 간다는 점과 request_limit 경로도 명시했다.
3. §3/§4 식별자 문자 집합: 설계의 "ASCII token"보다 구현의 `[A-Za-z0-9_-]{1,128}`이 더 엄격하고 명확하다. 이 규칙은 key ID·accountId·bucket id에 같이 적용되며 `:`·공백·제어문자가 구조적으로 배제된다. 설계 문구를 실제 정규식으로 고정했다.

### 커밋 전 필수 (구현 변경 아님, 테스트 1건)

- §6은 "테스트로 집합을 고정"을 요구한다. 그런데 현재 `safe_result`는 `error ∈ ERRORS ∪ {arguments, interrupted}` 소속만 확인한다. 이 방식으로는 누군가 `ERRORS`에 원문을 담을 수 있는 새 reason을 추가해도 통과한다. `assert b2.ERRORS == frozenset({...19개 리터럴...})` 테스트 1건을 추가한다. MockTransport·환경 변수 없이 실행할 수 있다.

### 확인했고 수정하지 않은 항목

- **범위**: 요청은 authorize GET과 list_buckets POST 두 건뿐이다. `Reader`가 공유 카운터로 3번째 요청을 독립적으로 막는다. 업로드·삭제·버킷/키 변경·암호화·원격 보존 코드는 없고 결과의 변경/검증 플래그 5개는 항상 false다.
- **preview/secret**: `read_config`가 `_credentials()`와 client factory보다 먼저 실행된다. `credentials_read_attempted`는 metadata 통과 뒤에만 true가 된다. Basic은 첫 요청의 요청별 `auth`로만 전달한다. 두 번째 요청은 `auth=None`이라 httpx가 Client 기본 auth 대신 no-op Auth를 쓰고, 명시한 raw token 헤더만 나간다. 테스트도 이를 확인한다. Client 기본값을 적대적으로 설정한 factory(auth/redirect/gzip)로 덮어쓰기를 검증하는 구성이 좋다. `Config`/`Credentials`/`Authorization`은 `repr=False`이고 결과 JSON에는 bool/int/고정 문자열만 들어간다.
- **apiUrl**: `hostname`이 소문자로 바뀌므로 대문자 host는 `url not in {base, base+"/"}`에서 거부된다. 빈 `?`/`#`, trailing dot, userinfo, port, path, IP도 거부된다. 모두 fail-closed이고 의도한 정책이다. 검증 뒤에는 원문이 아니라 재구성한 `base`만 사용한다.
- **계약 fixture 가정**: v4 `apiInfo.storageApi.allowed.{buckets[id,name],capabilities,namePrefix}`, `s3ApiUrl`, list 응답 `buckets[{accountId,bucketId,bucketName,bucketType}]`가 제공된 계약 노트와 일치한다. 실제 응답에 있을 수 있는 추가 필드는 무시되므로 호환성 위험은 낮다. 반대로 실제 provider의 host 형식·s3ApiUrl 형식·Content-Type 변화는 실패로 드러나며, 이는 실제 키로 확인하기 전까지 검증되지 않은 가정이다.
- **config reader**: validate→O_NOFOLLOW open→fstat identity/nlink/REG/크기 확인→읽기→fingerprint(dev/ino/size/mtime/ctime/nlink) 재대조→lstat identity 순서로 동작한다. 모든 `ArchiveError`/`OSError`/`ValueError`(PreflightError 포함)/`Rejected`는 arguments로 매핑되고 fd는 finally에서 닫힌다. 0바이트 파일도 거부한다.
- **응답 제한**: 비200 응답은 body를 읽기 전에 분류하고 닫는다. Content-Length 사전 검사, chunk별 응답·합계 상한, chunk마다 예산을 확인한다. 실패 경로 테스트 전부가 `state["closed"]`를 확인한다.
- **runtime 한계**: 요청당 timeout은 `min(5, 잔여)`이고 전체 30초 예산이다. 단일 블로킹 read는 최대 5초까지 예산을 넘길 수 있으며 §4에 hard wall이 아니라고 명시되어 있다.
- **테스트 수**: 붙여 넣은 테스트 파일의 parametrize를 세면 93개로 §11 기재와 일치한다.

### 비차단 권고 (선택)

- `validation._pairs`/`_constant`(private)를 import한다. 응답 쪽 NaN/중복 키가 payload로 분류되려면 이 함수들이 `ValueError` 계열을 던져야 한다. Codex 근거상 해당 테스트는 통과했지만, 결합을 줄이려면 모듈 내부에 복제하는 편이 낫다.
- `git` 파일 경로 가드 테스트는 존재하지 않는 경로를 쓴다. `ROOT` 검사가 먼저 실패하긴 하지만, 모두 arguments로 뭉뚱그려지므로 missing과 구분해 증명하지는 못한다. 필요하면 `archive.validate_file_path`를 직접 호출해 `ArchiveError("path")`를 단언하는 보조 테스트를 둔다.

실제 B2 연결·비용·만료·복구는 여전히 미검증이다. 사용자 계정·전용 버킷·키를 제공받은 뒤 `--execute`로 별도 확인해야 한다.

## 13. Codex 구현 검토 대조와 보완

실제 Claude 구현 검토는2026-11-15T15:49:20Z~15:51:24Z exit0/is_error=false/7turns였다. MD SHA `702b92298e58ed1106f8511fc866daaeebfdad731d64103a46348d1d13201c74` → `ba99374baaf6481c2c0e403127a76e87471de3ad1791e58b93cc855d9349dade`, 실제 MD 변경·제공 소스 SHA 보존·permission_denials0을 확인했다. 문서 정합화3건을 수용했고 필수 오류 어휘 리터럴 동등 비교 테스트를 추가했다.

Codex가 별도로 찾은 경계 사례는 Unicode Kelvin sign이 ASCII k로 lower 변환되는 점이다. provider의 허용 버킷명과 조회 버킷명을 비교하기 전에 ASCII Native 문자/길이를 검증하는 `_same_bucket_name`을 양쪽에 공통 적용했다. 가상 confusable 이름이 auth 단계에서는1요청으로, bucket 단계에서는2요청으로 실패하고 전송/연결 성공으로 표시되지 않는 회귀2개를 추가했다. ASCII 대소문자 비구분 정상 경로는 기존 테스트로 유지한다.

비차단 제안2건은 이번 범위에서 보류한다. 엄격 JSON helper는 현재 ValueError 계열 계약과 중복/비유한 값 테스트를 공유하므로 복제하지 않는다. Git 경로 검사는 기존 공용 archive 가드와 CLI 인자 실패로 검증하며, 이번 CLI에서 공용 가드 전용 테스트를 중복 작성하지 않는다. 실제 B2 계정/키를 얻기 전까지 공급자 가정은 미검증으로 남긴다.

보완한 B2 테스트는96사례 중 Windows95통과·symlink 권한1skip,1.06초다. ruff check/432파일 format·Windows/Linux mypy 각194파일이 통과했다. 가상 설정의 실제 CLI preview도 다시 실행해 config SHA 보존·키 조회/HTTP0·connection 및 변경 플래그 false를 확인했다. 변경 파일7개의 BE 범위·UTF-8·기존 환경 키 비포함·새 문서 링크를 확인했으며 기존 미해결 링크1개와 사용자 환경/미추적 파일은 보존했다.

보완 후 전체 Windows 일반 테스트는2336통과·symlink 권한3skip·PostGIS298분리,79.65초다. 기존 Starlette/httpx 경고1건이며 실패는 없다. 소스 변경 없이 실제 Claude 최종 문서 검토와 PR의 Linux/Windows/PostGIS·CodeQL 검사를 이어간다. CI의 최종 수치와 develop 통합 SHA는 #172 연결 PR에 기록한다.

## 14. Claude 최종 문서 검토 (2026-11-16)

판정: **PASS**. 이 MD와 사용자가 붙여 넣은 `b2_preflight.py`/테스트/helper 발췌/계약 노트/Codex 근거(validation.txt·local-preview.json)만 읽었다. 코드·테스트·CLI·명령·네트워크는 실행하지 않았다. 아래 수치는 Codex 근거를 인용한 것이며 내가 확인한 결과가 아니다. MockTransport와 가상 preview는 실제 B2 공급자 근거가 아니다.

### 이전 지적의 반영 확인

1. **필수 조건(ERRORS 리터럴 고정)**: `test_error_vocabulary_is_fixed`가 19개 리터럴을 `==`로 비교한다. 구현 `ERRORS`와 §6 목록이 정확히 같다. 이 조건은 충족됐다.
2. **문서 정합화 3건(§12)**: §3/§4/§6에 반영된 상태로 남아 있고, 구현(`IDENTIFIER`, `except httpx.HTTPError`, `request_limit`)과 일치한다.
3. **비차단 권고 2건 보류(§13)**: 보류 사유가 타당하다. 응답 쪽 중복 키/NaN/1e400 사례는 `payload` 테스트로 묶여 있다. 그래서 `validation._pairs`/`_constant`가 ValueError 계열을 던지지 않도록 바뀌면 회귀가 테스트로 드러난다. Git 경로 사례는 fail-closed(arguments)이므로 보안상 문제가 없다.

### 추가 delta(Kelvin sign) 검토

- `_same_bucket_name`은 `type is str` → `BUCKET.fullmatch`(명시 ASCII 범위 `[A-Za-z0-9.-]`; `re` 기본 Unicode 모드에서도 범위가 명시적이라 U+212A는 매칭되지 않는다) → `lower()` 비교 순서로 동작한다. 설정 쪽 이름은 `read_config`에서 이미 같은 정규식을 통과하므로 양쪽 모두 ASCII일 때만 lower 비교가 일어난다. 이 비교는 정확하다.
- 함수 하나를 auth allowed name과 list `bucketName`에 공통으로 적용한다. 이는 §10의 구현 유의 사항과 일치한다. auth 단계 실패는 `scope`로 1요청, list 단계 실패는 `bucket_mismatch`로 2요청에서 멈추며 `connection_verified=false`·`closed` 상태다. 두 회귀 테스트가 요청 수·플래그·비노출을 모두 단언한다.
- 이 delta는 범위를 넓히지 않는다. 새 요청·필드·error 어휘가 없다.

### 설계 수정과 이유

1. §3: provider가 돌려준 버킷명도 비교 전에 ASCII Native 검사를 거친다는 규칙을 추가했다. 이 규칙은 §13에서 구현됐지만 설계 본문에는 "ASCII 대소문자 무시"만 있었다. 향후 리팩터링에서 `str.lower()` 단독 비교로 되돌아가지 않도록 계약으로 고정했다.
2. §9: "현재 상태"가 설계 검토 직후 시점에 머물러 있어서 §14 이후 단계(PR CI 대기)로 갱신했다. 이력 절(§10~§13)은 수정하지 않았다.

### 재확인 결과(변경 없음)

- **범위**: 고정된 두 요청(authorize GET·list_buckets POST)만 보낸다. Reader의 독립 상한이 3번째 요청을 막는다. 업로드·삭제·암호화·원격 보존이 없고 변경/검증 플래그 5개는 항상 false다.
- **preview/secret**: metadata 검증이 환경 조회와 factory보다 먼저 실행된다. local-preview.json의 `credentials_read_attempted=false`·`requests_attempted=0`·`connection_verified=false`가 이 설계와 일치한다(가상 입력). Basic은 첫 요청에만, raw token은 두 번째 요청에만 실린다. 결과에는 bool/int/고정 문자열만 들어간다.
- **계약 가정**: fixture 형태는 제공된 v4 계약 노트와 일치한다. 실제 apiUrl host 패턴·s3ApiUrl 형식·Content-Type은 실제 키로 확인하기 전까지 미검증 가정이다. 다만 어긋나면 fail-closed로 실패한다.
- **runtime**: 30초 monotonic 예산과 요청별 `min(5, 잔여)`를 쓴다. 1MiB/2MiB 상한이 있다. hard wall이 아니라는 한계는 §4에 명시돼 있다.
- **테스트 수**: 93 + ERRORS 리터럴 1 + Kelvin 2 = 96으로 §13 기재와 일치한다. 전체 2333→2336(+3)도 일치한다.

### 남은 조건

- PR의 Linux/Windows/PostGIS·CodeQL 결과는 아직 없다. §13 계획대로 PR에 기록한다.
- 실제 B2 연결·비용·만료·복구는 미검증이다. 사용자 계정·전용 비공개 버킷·범위 제한 키를 받은 뒤 `--execute`로 별도 확인한다. mock 결과로 대체하지 않는다.

## 15. 최종 검토 수용과 통합 절차

Claude 최종 실제 호출은2026-11-15T15:57:12Z~15:58:11Z exit0/is_error=false/5turns였다. MD SHA `15f6a339027dd9860aaa17b4a07e2c7dcf1b7efa267178d08ae17256ac6973c9` → `f342e51235bf85e21ce7776141e8def1c9ebb5fd79afb9e9a08a89f6291ea887`, MD 직접 변경·제공 소스 SHA 보존·permission_denials0을 확인했다. Codex는 실제 §3의 provider ASCII 사전 검사와 §9의 상태 갱신, §14 판정/수정 이유를 대조해 수용했다. 필수 조건은 해소됐고 구현 변경은 없다.

전체 검사 이후 소스 변경 없이 #172 연결 PR을 생성한다. 현재 head의 Linux/Windows/PostGIS·CodeQL 전부 성공 및 병합 가능 상태를 확인한 뒤 정상 Squash하고 주 BE develop을 ff-only로 최신화한다. 최종 CI 수치·통합 SHA·기존 Task/runtime/사용자 파일 보존 근거는 해당 PR에 기록한다. 실제 B2 연결이나 원격 백업까지 완료됐다는 뜻은 아니다.
