# 운영 로그 원격 전송용 일관된 백업 내보내기 (#168)

작성: 2026-11-15. 최초 설계 기준 develop `9a406d6`, #168 병합 기준 `557a86f`. #170 후속 브랜치는 `feat#170-export-claude-review`다.

## 1. 목적과 현재 상태

#166의 두 세대 SPBK 백업은 로컬 정기 실행·무결성·새 SPOL/SPJC 복원까지 검증됐다. 원격 계정/버킷은 아직 연결되지 않았다. 원격 전송 전에 실행 중 SQLite 파일을 단순 복사하면 일관성·논리 소유권·만료 제외·숨은 과거 데이터 배제를 별도로 보장할 수 없다.

이번 이슈는 공급자와 독립적인 **새 SPBK 파일 내보내기**다. 단일 읽기 트랜잭션에서 검증한 논리 내용만 새 파일에 쓰고, 원본을 변경하지 않으며 기존 restore를 그대로 사용할 수 있게 한다. 전송 어댑터나 암호화를 구현했다고 표시하지 않는다.

현재 단계는 **#168 구현·검증·병합 완료, #170 실제 Claude 사후 검토 PASS와 권고 반영**이다. 한도 대기 중 사용자에게 이번 #168만 Codex 검토로 BE 구현·테스트를 먼저 진행하고 Claude 검토를 뒤로 미루는 방식을 제안했고, 사용자가 이어서 “다음 스텝 진행하자”라고 지시했다. 이 응답을 제안한 진행 방식에 대한 승인으로 반영했다. 당시 병합 전 검토는 없었으며 실제 후속 검토 기록은12절, 보완/검증은13절로 구분한다.

## 2. 범위

### 구현 대상

- 별도 모듈 `etl.operation_logs.backup_export`와 기본 읽기 전용 CLI.
- SPBK 단일 읽기 snapshot의 소유권·대상·세대·canonical·digest 검증.
- 모든 세대에서 원래 이벤트 시각 기준 만료된 행 제외, 세대별 digest 재계산.
- 존재하지 않는 새 출력 파일만 생성. 기존 파일 덮기/원본 prune 없음.
- 닫힌 출력의 재검증·유한 크기 SHA256·다음 이벤트 만료 시각과 고정 결과 제공.
- 기존 `backup restore`와 실제 격리 round-trip 및 실패/파일 경합 검증.

### 유지 및 후속

FE·공개 API·0012·.env·운영 DB/Render·기존 Task/config/runtime은 변경하지 않는다. 앱 실행 경로와 기존 backup CLI 결과 형식도 유지한다. 새 CLI는 내부 운영 도구이며 새 응답 계약 때문에 FE 변경을 요구하지 않는다.

B2 API/계정·비밀 저장·HTTP·자동 업로드·암호화·오프호스트 복원·외부 만료 스케줄·실행 서버 이관은 후속이다. 키·원시 Render 메시지·설정 파일을 내보내지 않는다. 전송용 파일 자체는 허용 이벤트가 담긴 평문이며 자동 업로드 대상에 추가하지 않는다.

## 3. 기존 계약 재사용

| 기존 모듈 | 재사용할 계약 | 주의점 |
| --- | --- | --- |
| `archive` | 로컬 절대 경로·Git 밖·부모/파일 reparse 검사·sidecar 거부·30일 상수 | 경로 검사만으로 파일 형식을 인증하지 않음 |
| `backup_store` | SPBK application_id/version/exact schema·파일/행/바이트 상한·target_hash·Budget·connect/load·canonical/digest | SHA256은 공격자에 대한 인증이 아님 |
| `backup` | generation cursor의 lag/30일 유효성·기존 restore | 출력 경로를 source archive/state처럼 binding하지 않음 |
| `job_state` | 복원된 새 archive의 binding 재생성 | 원본 SPJC의 inode binding을 직접 복사하지 않음 |

허용된 SPBK 논리 열만 재생성한다. 원본 SQLite 페이지/여유 공간/임의 메타데이터를 복제하지 않는다. 새 의존성·migration·런타임 배포는 필요하지 않다.

## 4. CLI 및 고정 결과

예정 인터페이스:

```text
python -m etl.operation_logs.backup_export \
  --backup <absolute-existing-source.sqlite3> \
  --output <absolute-new-output.sqlite3> \
  --owner-id <target-owner> --service-id <target-service> [--execute]
```

상위 API 경로나 실제 키/owner/service 예시는 기록하지 않는다. `--execute`가 없으면 source 읽기 검증과 계산만 하며 출력 파일·디렉터리·SQLite sidecar를 만들지 않는다. 출력 부모는 미리 존재해야 한다. 설정 파일/키/HTTP에 접근하지 않는다.

예정 결과는 정해진 필드만 포함한다:

- `status`, 고정 `error`, `mode`, `phase`, `rule_version`.
- `snapshot_as_of`, `captured_at`, `last_confirmed_until`, `sequence`, `generations`.
- `source_rows`, `rows`, `rows_skipped_expired` (세대별 합계이며 distinct 이벤트 수가 아님).
- `next_expiry_at` (남은 모든 세대의 최소 event 시각 +30일, 남은 행이 없으면 null). 복원 가능 기한은 아니며 전송/복원 전 현재 시각으로 모든 세대 cursor도 검증해야 한다.
- `would_create`, `created`, `integrity_verified`, `output_verified`, `output_bytes`, `output_sha256`.
- `commit_outcome_unknown`, `created_files_removed`, `orphan_files`, `effects_may_be_partial`.
- `encrypted=false`, `remote_uploaded=false`, `coverage_verified=false` 고정.

원본/출력 경로, target/origin hash, owner/service, 이벤트 내용·개별 hash, OS/SQLite 예외 원문은 출력하지 않는다. `output_sha256`만 전송 확인에 필요한 출력 전체 파일의 지문으로 허용한다. preview는 파일 바이트를 생성하지 않으므로 output 해시/크기는 null이다. source 무결성 확인과 출력 무결성 확인을 구분한다.

성공 0, 잘못된 인자 2, 인터럽트 130, 나머지 실패 1. 오류 출력은 기존 `SafeParser`와 같은 원문 없는 구조를 사용한다. 새 dataclass의 repr에는 민감한 경로/식별자를 두지 않는다.

## 5. 읽기와 만료 처리

1. UTC 시각을 한 번 확정해 `snapshot_as_of`로 사용한다. 기존 source/output 경로를 구분하고 같은 경로/identity·기존 output·Git 안·원격 경로·link·sidecar를 거부한다. source SPBK header/크기/nlink도 확인한다.
2. `Budget` 하나를 전체 작업에 공유한다. 기존 30초 Budget은 Python/SQL 진행 검사의 시간 예산이며 OS 파일 I/O까지 강제 중단하는 hard wall timeout이 아니다. source를 읽기 전용 BEGIN으로 열고 `store.load`로 exact schema·target·세대·canonical·hash·captured 시각을 전부 검증한다. 다른 target·미래 capture·손상은 실패하고 source를 고치지 않는다.
3. capture가 없는 초기 SPBK는 `generation_missing`으로 실패한다. 행이 0개인 유효 세대는 허용한다. 내보낼 각 세대의 cursor는 기존 `backup.validate_cursor`로 검사한다. 너무 오래되거나 현재 lag 기준보다 앞선 checkpoint를 복원 준비 완료로 표시하지 않는다. 한 세대가 부적합하다고 몰래 버리거나 최신 시각으로 갱신하지 않는다.
4. 각 slot에서 `event_us <= snapshot_as_of - RETENTION_US`인 행만 제외한다. 남은 행은 검증된 event_hash 순서를 유지한다. target/origin/active·slot/sequence·capture/initial/cursor는 보존하고 row_count/digest만 새 내용에 맞춰 계산한다.
5. source 경로 identity를 다시 확인하고 읽기 연결을 닫는다. 이 읽기 시점 이후의 정상 capture는 허용되며 출력이 source의 현재 최신 내용이라고 주장하지 않는다. 출력 쓰는 동안 source를 잠그지 않는다.
6. preview이면 여기서 완료한다. source DB·제어 DB·backup·config는 쓰지 않는다. 출력 파일도 생성하지 않는다.

30일 정책은 명시된 `snapshot_as_of` 기준이다. 쓰는 도중 만료 경계가 지나거나 나중에 파일을 보관/전송할 수 있으므로 출력 자체가 영구히 만료 없는 상태라고 주장하지 않는다. 후속 전송기는 현재 시각으로 다시 검증하고 만료 snapshot 전송을 거부/재생성해야 한다. 출력 파일도 보관/정리 대상이며 이번 이슈는 자동 정기 정리 기능을 제공하지 않는다. 실제 검증 사본은 검증 후 정리한다.

## 6. 새 파일 쓰기·재검증

1. execute에서는 출력 경로를 다시 검사한 뒤 **O_CREAT|O_EXCL**, 로컬 0600으로 새 파일을 만들고 fd의 regular/nlink/identity를 기록한다. Windows 권한은 부모 전용 ACL을 상속하며 0600만으로 Windows ACL을 보장했다고 표시하지 않는다.
2. 기록한 identity를 유지하는 전용 쓰기 연결에서 SPBK schema/root/두 세대/허용 이벤트만 작성한다. 기존 configure의 secure_delete/temp_store/페이지 상한을 유지하고 모든 루프/SQL에서 같은 Budget을 사용한다.
3. commit 전 `store.load`로 전체 결과를 다시 검사하고 예상된 generation/records/count/digest와 비교한다. 단순히 행 수만 맞는 것을 성공으로 보지 않는다. source에 대한 쓰기는 없다.
4. commit 시도 전 결과를 불확실 상태로 표시하고 성공 반환 후 해제한다. 연결을 닫은 뒤 정확한 header/소유 schema와 논리 내용을 다시 읽어 검증한다. identity·nlink·sidecar·상한을 재검사한다.
5. 같은 검증된 파일을 nofollow/fstat/identity 검사와 유한 chunk로 읽어 SHA256과 크기를 계산한다. 앞뒤 identity·크기를 대조한다. 출력이 실행 중 변하면 성공하지 않는다. 이는 일반적인 로컬 파일 경합 방어이며 권한을 가진 악성 동시 작성자에 대한 인증 보장은 아니다.
6. 출력이 닫히고 재검증·hash까지 끝난 뒤에만 `output_verified=true`로 보고한다. 외부 소비자는 이 성공 결과와 후속 검증을 사용해야 한다. 파일명 등장만으로 준비 완료로 판단하지 않는다.

출력을 새 경로에 직접 만들므로 생성 직후부터 미완성 파일이 보일 수 있다. **파일 게시의 원자성/프로세스 강제 종료 시 자동 정리**를 보장하지 않는다. SQLite 트랜잭션의 원자성과 외부 파일 게시의 원자성을 구분한다. 출력의 자동 감시/업로드는 이번에 연결하지 않는다.

## 7. 실패와 잔존 파일

- source read/target/schema/cursor/clock/상한 실패에는 출력이 없다. 기본 preview의 모든 실패에도 새 파일/sidecar가 없다.
- 출력의 생성 소유권을 fd identity로 확인하고 생성 여부/commit 시도를 기록한다. 기존 파일이 출현했으면 쓰거나 삭제하지 않는다.
- execute 도중 실패/인터럽트에는 이번 작업이 만든 것임을 identity·nlink·header 또는 생성 단계에 맞는 확인으로 증명할 수 있는 파일만 정리한다. 같은 이름의 교체 파일·다른 형식/링크·불명 sidecar는 건드리지 않는다.
- 정리하지 못한 파일은 `orphan_files`와 `effects_may_be_partial=true`로 보고한다. 원문 경로를 내보내지 않는다. 원본과 정상 과거 백업은 폐기하지 않는다.
- hard kill/crash의 잔존 파일은 기존 경로 보호로 다음 실행에서 덮지 않고 실패한다. 형식과 소유권을 확인한 수동 정리가 필요하다. 미완성 파일을 valid backup으로 취급하지 않는다.
- SQLite busy·budget·disk/commit/IO·파일 교체 오류를 고정 코드로 구분한다. source 오류를 output 손상으로 잘못 보고하지 않는다. 이미 쓴 효과가 있는데 모두 미실행인 것처럼 보고하지 않는다.

## 8. 검증 계획

| 구분 | 필요한 검증 |
| --- | --- |
| 정상 round-trip | 허용 6종 이벤트·단일/두 세대·0행 세대·재회전 seq3/4, 보존 메타와 재계산 digest, 기존 latest/previous restore 및 새 binding |
| 만료 | 정확 30일 경계/직전/직후, 서로 다른 두 세대의 모든 만료 제외, next_expiry가 최신 세대만 보지 않는지, 빈 결과 null |
| 읽기 일관성 | 별도 연결/process가 capture/prune하는 중 읽기 snapshot, source SHA/내용 불변, 읽기 종료 후 정상 새 capture 허용 |
| 무효 source | 다른 target·header/schema·canonical/digest·행/바이트/파일 상한·future capture·expired/앞선 cursor·초기 빈 SPBK |
| 파일 보호 | 상대/Git/원격/없는 부모·same file·기존 output·symlink/reparse/hardlink·journal/WAL·생성 사이 출현/교체 |
| preview | 성공/실패 모두 모든 source/config hash 불변, 출력/sidecar/디렉터리/키/HTTP 호출 0 |
| 실패 정리 | write/commit/닫힌 파일 재검증/hash/cleanup 실패·KeyboardInterrupt·budget·실제 자식 hard exit, 교체 파일과 기존 파일 보존/잔존 보고 |
| 결과 | 고정 필드와 exitcode, canary가 argv/파싱/예외/stdout에 노출되지 않음, preview는 output hash null, 암호화/전송/coverage false |
| 실행 환경 | Linux 일반 CI 및 Windows native 파일/실제 프로세스 검증, 기존 backup39·Windows runner2 회귀 |

테스트는 임시 디렉터리/가상 target으로만 실행한다. 기존 운영 SPBK는 읽기 전용 상태 검사 외에 변경하지 않는다. 실제 output을 만들 경우 전용 새 파일을 사용하고 검증 후 identity 확인 정리한다. `.env`·키·운영 DB 접속을 테스트에 사용하지 않는다.

로컬 pytest·ruff check/format·mypy가 통과한 뒤 PR을 만들고, CI Linux/Windows/PostGIS·CodeQL 성공과 정상 병합 조건을 확인한 뒤 통합한다. 실제 실행 근거와 남은 상태는11절에 기록한다.

## 9. 변경 파일 및 커밋 계획

1. `docs(be): 운영 로그 전송용 내보내기 설계`: 이 MD와 작업계획 연결. Claude 검토 전의 초안 상태를 명시한다.
2. `feat(be): 만료 제외 백업 내보내기 구현`: 새 `etl/operation_logs/backup_export.py`, 관련 의미 있는 `tests/etl/test_operation_log_export.py`, 필요한 CI/README/CLAUDE 안내를 같은 커밋에 포함한다. 기존 공통 helper 변경이 필요하면 기본 계약 유지 근거와 회귀를 함께 기록한다.
3. 구현 후 MD에 실제 검토·수정 이유·실행 근거·남은 조건을 기록한다. 모두 통과한 뒤 지정 템플릿 PR/CI/정상 Squash 통합과 main BE ff-only를 진행한다.

## 10. 검토 상태와 다음 실행 조건

### Codex 최초 대조

- 기존 SPBK load는 모든 세대의 canonical/digest/정렬과 미래 capture를 검증한다. export에서도 이를 우회하지 않는다.
- 기존 restore는 새 SPOL/SPJC를 만들어 inode binding을 새로 생성하므로 export는 SPBK 형식을 보존하는 것으로 연결할 수 있다.
- 기존 readonly connect는 소유권 확인과 단일 BEGIN을 사용한다. 파일 원본 복사 대신 검증된 논리 내용만 재생성해야 원본 여유 공간을 배제할 수 있다.
- 단일 source 읽기 시점·만료 기준 시각·신규 파일 직접 생성·인증 부재·외부 정리 부재를 구분해 보장 범위를 제한했다.
- 이 설계는 원격 버킷/키 없이 작성 가능하다. B2 실제 접속 성공이나 서버 이관을 완료했다고 표시하지 않는다.

### Claude 검토 대기

#166 보완 재검수의 실제 CLI 결과는 2026-11-15T13:07:56Z 계정 5시간 한도/23:50 Asia/Seoul 초기화 안내였다. 13:34:53Z의 준비 스크립트 실행은 초기화 예정 전임을 확인하고 `attempted=false`로 종료했으며 Claude에 요청하지 않았다. 초기화 시각은 CLI 안내이며 이후 호출 성공을 보장하지 않는다.

사용자의 다음 단계 요청 후 계정 상태 변경 가능성을 확인하기 위해 **13:56:47Z 실제 설계 검토를1회 요청**했다. 13:56:51Z exit1/is_error=true/num_turns1, 계정5시간 한도와 동일한23:50 Asia/Seoul 초기화 안내로 실패했다. 입출력 MD SHA256은 모두 `182d7cf4fee2ac41d9a18caced86b3880c212e4d264d77be369901c5728a1201`, 실제 MD 변경은 없었다. 이 호출은 검토 완료나 PASS가 아니다. 추가 반복 호출 없이 한도 해제를 기다린다.

같은 단계의13:57:02Z 읽기 전용 운영 확인에서는 기존 수집·백업 Task 모두Ready/LastTaskResult0, 백업 seq13·두 세대·무결성/배포SHA/ACL/source origin 정상, 실제0행·expired0이었다. source/config/Task/FE를 바꾸거나 새로운 제품 테스트를 실행한 결과가 아니다. **13:57Z 당시**에는 설계/실패 기록만 보존하며 구현·PR·병합은 진행하지 않은 상태였다. 이후 구현/통합은11절 기록을 따른다.

검토 재개 시 이 MD만 Read/Edit하도록 제한하고 source 관련 발췌·검증 근거를 UTF-8 프롬프트로 제공한다. shell/git/network/DB/MCP/agent/환경 및 다른 파일 읽기/수정 권한은 주지 않는다. 사용자의 후속 진행 지시에 따라 Codex가 먼저 구현·격리 검증하고 실제 MD diff와 검토 이유를 후속 대조한다. FE·의존성·배포 runtime은 바꾸지 않는다. Claude 검토가 미완료이면 PR/완료 보고에도 이를 명시한다.

## 11. Codex 구현 대조 및 실제 검증

### 구현 결과

- 별도 `backup_export` CLI를 추가했다. 기존 backup/archive/job 명령의 코드·형식은 바꾸지 않는다. 기본 preview·명시 execute, source 단일 readonly transaction·세대별 canonical/digest 검증·일괄 만료 제외·메타 보존·새 SPBK 재생성을 구현했다.
- 새 출력의 O_EXCL·identity/nlink·header/schema·닫힌 논리 내용 재검증·유한 SHA256을 대조한다. 전체 SQL/Python Budget은 하나이고 파일 원자적 게시나 OS I/O 강제 종료를 보장하지 않는다. preview는 출력 해시/크기가 null이다.
- source 무결성과 output 무결성/잠금/IO/용량 오류를 단계별로 구분한다. 등록되지 않은 예외 문구는 출력하지 않는다. commit 불확실/생성/정리/잔존/부분 효과를 보존하며 교체·미확인 형식·link·sidecar는 자동 삭제하지 않는다.
- 실제 다른 process가 read 중 BEGIN IMMEDIATE 후 commit을 기다리는 사례와 read 종료 후 source가 새 capture로 진행하는 사례를 격리 검증했다. 출력은 최초 읽기 시점이며 최신 상태를 따라 섞이지 않는다.
- SQLite 파일 뒤에 붙은 테스트 canary를 논리 출력에 복사하지 않음을 직접 확인했다. 원본 여유 페이지를 복제하지 않는 성질은 새 파일에 허용 논리 행만 INSERT하는 구성에 근거하며 여유 페이지를 별도 fixture로 검증한 것은 아니다. 테스트 중 변조용 SQLite 연결은 `closing`으로 명시 종료한다. SQLite connection context만으로는 파일 핸들이 닫히지 않는 Windows 특성을 테스트 정리 기대와 구분했다.
- FE/API/schema0012/.env/의존성·원본 DB/Render/기존 Task/config/runtime은 변경하지 않았다. Windows CI에는 새 export 테스트 파일만 추가했다.

### 로컬 검사

| 검사 | 실제 결과 |
| --- | --- |
| export+기존 backup | 82 passed, symlink 권한1skip,16.92초 |
| 전체 Windows 일반 | 2223 passed, symlink 권한2skip, PostGIS298분리,83.11초 |
| ruff check / format | 통과 /429파일 형식 확인 |
| mypy Windows / Linux target | 각193파일 통과 |
| 기존 경고 | Starlette/httpx deprecation1건 |

새 export는43통과·Windows 계정 symlink1skip이다. symlink guard의 실제 Linux 검증은 CI로 확인한다. PostGIS298은 이 로컬 실행에서 수행했다고 주장하지 않으며 CI 결과를 별도로 기록한다.

### 실제 현재 PC 백업의 내보내기·복원

2026-11-15T14:07:57Z 현재 SPBK의 두 세대를 preview한 후 전용 새 파일로 내보내고 기존 restore로 새 SPOL/SPJC를 생성했다. export/output_verified·전체 파일 SHA·복원 rows와 새 archive binding·cursor를 확인했다. 실제 원본/내보내기/복원은 모두0행, 만료 제외0행이었다. 양수6종/정확30일/동시 writer 근거는 위 격리 테스트이며 실제 양수 로그 유입 확인이 아니다.

source SPBK·config·기존 archive/state 네 파일의 SHA는 전후 동일했고 preview는 파일을 만들지 않았다. root 밖으로 나가지 않는 새 파일3개의 identity/header/nlink를 확인한 뒤 검증 사본을 모두 제거했다. 키/DPAPI/HTTP를 사용하거나 Task/배포를 전환하지 않았다. 오프호스트 복구·원격 만료·상시 운영 완료가 아니다.

### 후속 상태

**#168 병합 시점**에는13:56Z 실제 Claude 계정 한도 실패 이력이 마지막이며 이 구현을 검토하지 않은 상태였다. 사용자 승인한 Codex 선진행 순서에 따라 당시에는 **Claude 후속 검토 대기**로 표시했다. 이후 실제 검토는12절을 따른다. B2 버킷/비밀 연결·암호화/인증·전송/다운로드 복원·원격 버전 만료 및 실행 호스트는 별도 후속이다.

### CI 및 통합 근거

최종 #168 head `485b2cd`에서도8검사 성공/CLEAN을 확인했고2026-11-15T14:20:06Z squash `557a86f`로 병합한 뒤 main BE를 ff-only 갱신했다. 아래 기능 commit의 최초 CI와 최종 문서 HEAD의 CI를 구분한다.

기능 commit `460baf2`의 [PR169](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/169)에서 push/PR Backend CI 각3검사와 CodeQL2검사 총8개가 모두 성공했고 merge state CLEAN이었다.

- Linux 일반2223통과·Windows 전용2skip·PostGIS298분리,20.56초.
- Windows native85통과,35.16초. 기존 runner2+backup39+새 export44이며 Linux와 이 Windows runner에서는 실제 symlink 생성 검증도 통과했다.
- 실제 격리 PostGIS298통과·2225분리,146.48초.
- CodeQL actions 분석과 최종 CodeQL 검사 성공.

후속 문서 정리에서는 README를 운영 로그 절로 옮기고, exported origin은 원본 binding을 보존하므로 복원한 새 archive의 이후 capture에는 별도 새 SPBK init이 필요함을 명시했다. Python/테스트/CI 소스는 기능 commit과 동일하며 후속 HEAD의 실제 체크·병합 상태는 PR169에서 확인한다. 이 문서의 CI 성공은 Claude 검토 성공을 뜻하지 않는다.

## 12. Claude 후속 검토 (#170, 2026-11-15)

### 검토 방식과 한계

- 이 MD만 Read/Edit했다. 다른 파일·shell·Git·network·DB·MCP·agent·.env/설정에는 접근하지 않았다.
- 프롬프트로 제공된 발췌 소스(`archive.py`, `backup_store.py`, `backup.py`, `job_state.py`, 기존 `test_operation_log_backup.py`, 새 `backup_export.py`, 새 `test_operation_log_export.py`)와 Codex 실행 근거(validation.txt, live-proof.json, file-checks.json)만 사용한 **정적 검토**다.
- Claude는 코드나 테스트를 실행하지 않았고 CI·병합·원격 전송을 확인하지 않았다. 아래 실행 결과는 모두 Codex가 제출한 근거이며 Claude가 재현한 것이 아니다. `job.ids`/`job.stamp`/`validation.Record`/`SafeParser` 원문은 제공되지 않아 테스트 기대값(예: 잘못된 service-id → exit 2)과 근거상 통과를 근거로 추정했다.
- 검토 시점에 #168은 이미 merge(근거상 `557a86f`)된 상태다. 이 검토의 수정 권고는 사후 후속 커밋 대상이며, 병합 전 Claude 승인이 있었던 것으로 해석하지 않는다.

### 판정: **PASS (비차단 권고 포함)**

범위(키 없는 오프라인 논리 SPBK export, source 단일 readonly snapshot, 모든 세대의 이벤트 시각 만료, 세대 checkpoint/capture 메타 보존, 새 파일만 생성, 기존 restore 호환, 닫힌 파일 재검증/유한 hash, 실패 정리·부분 효과 보고)에 대해 구현은 설계와 일치하며 정적으로 실현 가능하다. 차단 결함은 찾지 못했다. 아래 R1~R4는 #170 후속에서 처리 권장, N1~N5는 기록/문서 수준이다. B2 전송·암호화·배포·외부 만료 보장·FE/API/DB/Task는 범위 밖으로 평가하지 않았다.

### 설계 ↔ 구현 대조 (근거)

| 설계 항목 | 구현 근거 | 판단 |
| --- | --- | --- |
| §5.1 경로/identity/sidecar, source header·nlink·크기 | `source == output` 거부 + `archive.validate_file_path(output, exists=False)`(존재·sidecar·Git·원격·reparse) → `store.validate(source)` | 충족. output이 존재하면 안 되므로 identity 동일성은 경로 검사로 귀결 |
| §5.2 단일 Budget, readonly BEGIN, `store.load` 전체 검증 | `run`에서 Budget 1개를 source connect/load/filter/write/verify/hash 전부에 전달. `store.connect(source)`는 `?mode=ro` + `BEGIN` 전후 `owned` | 충족. rollback journal 모드에서 deferred BEGIN의 SHARED 잠금은 트랜잭션 종료까지 유지되므로 generation·events를 같은 시점에서 읽음 |
| §5.3 generation_missing, 모든 세대 cursor 검사, 몰래 버리지 않음 | `filtered`: active/origin None → `generation_missing`; 모든 slot에 `backup.validate_cursor` | 충족. 이전 세대 cursor만 부적합해도 전체 실패(설계 의도대로) |
| §5.4 `event_us <= now-RETENTION` 제외, 순서·메타 보존, row_count/digest만 재계산 | `replace(generation, row_count=…, digest=store.digest(...))`; `store.digest`는 `len(records)`를 사용하므로 원 row_count에 의존하지 않음 | 충족. 경계 비교가 `prune`/`restore`와 동일한 `<=` |
| §5.5 source identity 재확인 후 연결 종료, 쓰기 중 비잠금 | `same_file(source, identity)`가 `with` 안, write는 `with` 밖 | 충족 |
| §6.1 O_CREAT\|O_EXCL 0600, fd identity | `create_file`: `created=1`을 open 직후 기록, fstat identity 후 `same_file` | 충족. fstat 실패 시 identity None → 정리하지 않고 orphan 보고(정직) |
| §6.2~6.3 configure(secure_delete/temp_store/max_page_count), commit 전 전체 load 비교 | `store.configure(write=True)`; `store.load(...) != value`는 Snapshot/Generation/Record dataclass 동등 비교(행 수만이 아닌 전체 내용) | 충족 |
| §6.4 commit 불확실 표시, 닫힌 후 재검증 | `commit()`의 `commit_outcome_unknown`; `verify_file`이 새 readonly connect(`validate`=sidecar/nlink/MAX_FILE/header, `owned`) + load 비교 | 충족 |
| §6.5 nofollow/fstat/유한 chunk hash, 앞뒤 대조 | `file_hash`: `O_NOFOLLOW`(POSIX), fstat identity/regular/nlink/크기, `st_size+1`까지만 읽어 증가 감지, size·mtime·ctime fingerprint 전/후 및 경로 재확인 | 충족. Windows는 O_NOFOLLOW가 없지만 `same_file`의 lstat reparse 검사와 fstat identity로 보완 |
| §7 소유 증명된 파일만 정리, 교체/sidecar 보존, orphan 보고 | `cleanup`: identity 일치·sidecar 부재·비어 있지 않으면 SPBK header 확인 후 unlink, 이후 경로+sidecar 존재를 orphan으로 계수(검사 실패도 1로 계수) | 충족(R1·N3 참고) |
| §4 결과 필드·비노출·exit code | `Result`에 경로/owner/service/target/origin 없음, REASONS 외 문구는 `operation_failed`, `0/2/130/1` | 충족 |

### 권고 (비차단, #170 후속 권장)

- **R1. 2차 인터럽트 시 부분 효과 보고 유실 가능.** `cleanup`의 orphan 계수 루프는 `try` 밖이고, `run`의 `finally`에서 KeyboardInterrupt(또는 예상 밖 예외)가 발생하면 `main`은 기본 `Result()`로 `created=0`, `effects_may_be_partial=false`를 출력한다. hard kill처럼 "출력 없음"이 아니라 **실행 효과가 없었다는 거짓 결과**가 되므로 §7 마지막 문장과 어긋난다. 창은 매우 좁다. 권장: `main`의 KeyboardInterrupt/Exception 경로에서 `--execute`였다면 `effects_may_be_partial=True`(또는 `orphan_files`를 알 수 없음으로 표시)로 보수적으로 설정하고, 이를 테스트(`cleanup` 계수 중 KeyboardInterrupt 주입)로 고정.
- **R2. `next_expiry_at`은 복원 가능 기한이 아니다.** 이벤트 만료만 반영하며 세대 cursor의 `checkpoint_expired`(cursor ≤ now−30일) 기한은 반영하지 않는다. 특히 남은 행이 0이면 null이 되어 "만료 없음"으로 오해될 수 있지만 실제로는 cursor 기준 30일 이내에 restore가 `checkpoint_expired`로 실패한다. §4 정의 자체는 정확하므로 결함은 아니다. 권장: §4/README에 "복원 가능 기한이 아님, 전송기는 현재 시각으로 `validate_cursor`까지 재검증" 명시, 필요 시 후속에 `min(next_expiry, min(cursor)+30일)` 별도 필드 검토.
- **R3. 생성 경합 테스트가 O_EXCL 경계를 실제로 통과하지 않는다.** `test_output_race_never_overwrites_an_existing_file`은 `create_file` 호출 전에 파일을 만들어 `validate_file_path`의 `exists`에서 실패하므로, 검사와 `os.open(O_EXCL)` 사이 출현은 코드상 O_EXCL로 보호되지만 테스트로 증명되지 않는다(§8 "생성 사이 출현"). 권장: `archive.validate_file_path`를 감싸 검사 직후 파일을 만드는 경합 테스트를 추가하고 `error=="filesystem"`, `created==0`, 파일 바이트 불변을 확인.
- **R4. 오류 코드 의미.** (a) 같은 경로 거부가 `output_changed`로 보고되어 §5.1/§8의 same file 의미와 다르다(`same_file` 고정 코드 권장). (b) source 단계의 `ArchiveError("path"/"ownership"/"missing")`는 source/output 구분 없이 그대로 노출된다. output 경로 검사는 phase `validation`, source는 `source`이므로 phase 필드로 구분은 가능하나 §7 "source 오류를 output 손상으로 잘못 보고하지 않는다"를 더 명확히 하려면 `source_path` 등으로 접두 권장. (c) `no_generation` 테스트는 `generation_missing` 오류값을 단언하지 않는다.

### 기록/문서 수준 (N)

- **N1.** §11 "SQLite 파일의 여유 공간/뒤에 붙은 canary" 중 테스트가 직접 증명한 것은 **파일 끝 trailing bytes**다. freelist/여유 페이지 잔존 데이터 배제는 새 파일에 논리 행만 INSERT하는 구성(삭제 없음)으로 보장되는 성질이며 별도 테스트로 증명된 것은 아니다. 표현을 그에 맞추길 권장.
- **N2.** 출력 파일에는 `target`/`origin` hash와 평문 이벤트가 들어간다. `target`은 owner/service와 공개 규칙 상수의 결정적 SHA256이므로 후보 ID를 아는 자가 일치 여부를 확인할 수 있다(비밀 동등물은 아니지만 연결 가능 식별자). B2 전송 후속에서 암호화/접근 통제 전제로 다뤄야 한다.
- **N3.** `orphan_files`는 "이번 작업이 만들었는데 남은 파일"만이 아니라 출력 경로/sidecar에 **남아 있는 모든 것**(교체 파일 포함)을 계수한다(`test_replacement…`가 1을 기대). 기존 `backup.restore`와 같은 보수적 의미이므로 유지 가능하나 README/§7에 "출력 경로 점유 수, 소유 증명 아님"으로 명시 권장.
- **N4.** preview 실패 경로(예: 무효 source를 `execute=False`로)에서 파일 미생성을 직접 단언하는 테스트는 없다. 코드상 preview는 `create_file`에 도달하지 않으므로 위험은 낮다.
- **N5.** 문서 현행화: 머리말 기준 `9a406d6`와 §10 13:57Z 문단의 "구현·PR·병합은 아직 진행하지 않는다"는 당시 기록이다. 제공 근거상 최종 head `485b2cd` 8검사 성공, squash `557a86f`(14:20:06Z), main ff-only, #168 close, #170 open이므로 §11에 최종 head/merge 근거를 추가하고 §10 문단에 "13:57Z 당시"임을 표시하길 권장. §11 수치(로컬 export 43+1skip=44, backup 39, 합계 82+1skip)는 서로 일관된다.

### 테스트 계획 평가

§8 표 대부분이 구체적 테스트로 대응된다: 1/2/4회 capture round-trip과 latest/previous restore·새 binding·`run_once`, 30일 정확 경계 ±1µs와 이전 세대가 최소 만료를 갖는 `next_expiry`, 0행/전량 만료, 실제 자식 process가 read 중 `BEGIN IMMEDIATE`로 대기 후 commit하는 일관성, read 종료 후 capture 진행, 무효 source 9종, 경로/sidecar/hardlink, write/commit/verify/hash/interrupt·용량(실제 SQLITE_FULL 중간 실패)·budget·교체·정리 실패, 자식 `os._exit` 잔존 보호, CLI 비노출·exit code. 남은 공백은 R1(2차 인터럽트), R3(O_EXCL 경합), N4(preview 실패), Linux 전용 symlink 경로는 근거상 CI 의존이라는 점이다. 근거상 통과 수치는 Codex 제출 결과이며 Claude가 확인한 실행이 아니다.

### 결론

- #168 범위: **PASS**(정적 검토 기준). 전송·암호화·원격 만료·오프호스트 복원은 미구현/미실행이며 이 판정에 포함되지 않는다.
- #170 후속: R1~R4 반영 여부와 N5 문서 현행화는 **pending**. 반영 시 해당 테스트 결과를 이 절 아래에 실제 실행 근거로 추가한다.

## 13. #170 Codex 후속 반영

### 실제 검토 실행 근거

2026-11-15T14:50:36Z 실제 Claude Code 호출을 시작해14:53:45Z exit0/is_error=false/3turns로 완료했다. 검토 MD SHA는 `b1bae052bfa461e537c30523f4ab5dc0b480b15c78da6ca1d1246e2cdc9fedff`에서 `c7fe40cc26bf5f6885e649abb8847c644100c4399b492a4e82879b677f505d9c`로 바뀌었으며12절은 Claude가 직접 추가했다. permission_denials는0이었다. 빈 비공개 작업 디렉터리·정확한 MD 경로 Read/Edit 허용·manual/추가 승인 거부·safe-mode/후크 비활성·빈 MCP를 사용했으며 실제 Git diff는 이 MD만 수정했다. 이 호출은 앞선 한도 실패와 구분되는 실제 정적 검토다.

### 권고별 결정

- R1 수용: `run`이 정리 전에 부분 효과를 표시하고, 정리/계수 중 추가 KeyboardInterrupt·예외에도 이미 확인한 생성/정리 정보를 보존한다. 계수 미완료 시 미확인 경로1개를 보수적으로 더한다. `main`은 호출 전에 execute 모드를 기억하고 최외곽 예외에도 가능한 실행 효과를 true로 보고한다. 카운터 기본0은 이 경우 부재의 증거가 아니다. cleanup의 unlink 중 Ctrl+C도 interrupted로 반영한다.
- R2 수용: `next_expiry_at`은 이벤트 만료만 의미한다. 빈 snapshot의 null도 복원 가능 기한이 아니며 전송 시 모든 세대 cursor를 현재 시각으로 재검증해야 함을 README에 명시했다. 별도 복원 유효기한 필드는 추가하지 않는다.
- R3 수용: 새 테스트는 실제 출력 경로 검사 성공과 O_EXCL open 사이에 파일을 출현시킨다. 이후 filesystem 실패·created0·경합 파일 보존을 검증한다.
- R4 수용: 같은 경로는 same_file, source 경로/형식/부재는 source_path/source_ownership/source_missing으로 구분한다. 초기 빈 SPBK의 generation_missing을 명시 단언한다. 공개 API/DB schema는 변경하지 않는다.
- N1/N2/N3/N5 수용: trailing bytes 실증과 논리 재생성의 구조적 성질을 구분하고, hash/평문 포함·orphan의 경로 점유/미확인 의미·과거 시점 기록·최종 병합 기준을 현행화했다.
- N4 수용: 무효 source9종을 execute/preview 양쪽으로 실행해 출력·sidecar·원본 비변경을 검증한다.

### 보완본 실행 검증

- 새 회귀17개를 추가했다. 전체 Windows 일반2240통과·symlink 권한2skip·PostGIS298은 분리,85.67초다. export 테스트는 총61개이며 이 Windows 계정의 symlink 권한1개를 제외한60개가 전체 검사에서 통과했다. 기존 Starlette 경고1건이다.
- ruff check·429파일 format 및 Windows/Linux mypy 각193파일을 통과했다. UTF-8·새 상대 링크·실제 .env 비밀값 미포함·BE6파일 범위를 확인했다. 기존 비추적 문서 링크1개는 원래 상태로 유지한다.
- 2026-11-15T15:01:57Z 보완본에서 현재 SPBK 두 세대를 preview/새 파일 export한 뒤 새 SPOL/SPJC로 restore하고 새 binding·cursor·출력 SHA를 확인했다. 실제 source/export/restore0행·만료 제외0행이며 원본 SPBK/config/archive/state4파일 SHA는 동일했다. 검증 사본3개는 identity/header/nlink를 확인해 정리했다. HTTP/키/Task 전환은 하지 않았다.

추가 실제 재검토·CI/통합 결과는 완료 후 기록한다. 12절의 pending은 당시 검토 권고 상태이며 현재 반영 상태는 이 절을 따른다.

## 14. Claude 최종 재검토 (#170 보완본, 2026-11-16)

### 방식과 한계

- 이 MD만 Read/Edit했고 다른 파일·shell·Git·network·DB·MCP·agent·.env/설정에는 접근하지 않았다. 프롬프트로 제공된 보완본 `backup_export.py`·`test_operation_log_export.py`·README 발췌·helper(`validation.py`, `__main__.py`, `job.py` 발췌)와 Codex 근거(validation.txt, live-proof.json, file-checks.json)만 사용한 **정적 재검토**다.
- Claude는 코드·테스트를 실행하지 않았다. 2240통과/export 61개(60+1skip)·live proof·ruff/mypy는 Codex가 제출한 결과이며 Claude가 재현하지 않았다. #170 보완본의 CI·PR·병합은 근거상 아직 없고 Claude가 확인하지 않았다. 원격 전송은 없었다.

### 판정: **PASS (차단 결함 없음)**

12절 R1~R4와 N1~N5는 아래와 같이 해소됐다. 남은 항목은 모두 비차단 문서/표기 수준이다. 범위(키 없는 오프라인 논리 SPBK export, 단일 readonly snapshot, 모든 세대 이벤트 만료, 메타 보존, 새 파일만 생성, restore 호환, 닫힌 파일 재검증·유한 hash, 실패 정리·부분 효과 보고) 밖의 B2 전송·암호화·배포·외부 만료·FE/API/DB/Task는 평가하지 않았다.

### 권고별 재확인

| 항목 | 보완본 근거(정적) | 결정 |
| --- | --- | --- |
| R1 | `run`의 `finally`가 `created`이면 정리 전에 `effects_may_be_partial=True`를 먼저 설정하고, `cleanup` 호출 자체를 `KeyboardInterrupt`/`Exception`으로 감싸 `orphan_files += 1`. `cleanup` 내부 unlink 중 Ctrl+C는 `interrupted`로 반영 후 계수 계속. `main`은 `run` 전에 `mode`를 기록하고 최외곽 `KeyboardInterrupt`/`Exception`에서 execute면 부분 효과 true. 테스트: 계수 중 `KeyboardInterrupt`/`RuntimeError` 주입, unlink 중 인터럽트, `run` 반환 후 CLI 최외곽 예외 | **해소** |
| R2 | README에 "복원 가능 기한이 아님, 0행 null이어도 cursor 30일 초과 시 복원 거부, 전송 전 현재 시각으로 모든 세대 cursor 재검증" 명시. 별도 필드 미추가 결정은 타당 | **해소**(N-a 참고) |
| R3 | `test_output_appearing_between_path_check_and_exclusive_open_is_untouched`: `archive.validate_file_path`를 모듈 속성으로 감싸 두 번째 `exists=False` 검사(= `create_file` 내부) 성공 직후 파일 출현 → `os.open(O_EXCL)`의 `FileExistsError` → `filesystem`, `created==0`(대입 전 예외), 바이트 보존, 부분 효과 false. 호출 순서상 source 검사는 경로가 달라 계수되지 않으므로 `checks==2`가 실제 O_EXCL 직전을 가리킴 | **해소** |
| R4 | (a) `source == output` → `same_file`(REASONS 포함), 테스트 단언. (b) source phase의 `path/ownership/missing`→`source_*`, `backup_*`→`source_*`, `output_changed`→`source_changed`; 테스트 `source_missing`/`source_path`/`source_ownership`. (c) `no_generation`→`generation_missing` 단언 | **해소**(N-c 참고) |
| N1 | §11 문구가 trailing bytes 실증과 "논리 행만 INSERT"라는 구조적 성질을 구분 | **해소** |
| N2 | README에 target/origin binding hash·평문 이벤트 포함, SHA256은 인증/암호화 아님 명시 | **해소** |
| N3 | README에 `orphan_files`는 교체 파일·검사 실패 포함 경로 점유/미확인 수이며 소유 증명 아님, 중단 시 보수 가산 명시 | **해소** |
| N4 | 무효 source 9종 × `execute` False/True로 출력 미생성·디렉터리 바이트 불변·canary 비노출 단언 | **해소** |
| N5 | 머리말에 `557a86f` 병합 기준, §10 문단 "13:57Z 당시" 표시, §11 병합 시점 표기 | **부분 해소**(N-b) |

### 남은 비차단 항목

- **N-a.** MD §4의 `next_expiry_at` 정의에는 "복원 가능 기한 아님" 주의가 README에만 있고 설계 본문에는 없다. §4 항목에 한 줄 추가 권장.
- **N-b.** 최종 검증 head `485b2cd`(8검사 성공)는 validation.txt에만 있고 §11 "CI 및 통합 근거"는 `460baf2`와 "PR169에서 확인"으로만 기록한다. squash `557a86f`·14:20:06Z와 함께 §11에 명시 권장.
- **N-c.** verify phase에서 store.connect가 내는 `ArchiveError("ownership"/"path")`는 접두 없이 `ownership` 등으로 보고된다(`backup_*`만 `output_*`로 변환). phase=`verify`로 구분 가능하고 source 오류로 오인되지는 않으므로 비차단이며, 일관성을 원하면 `output_ownership` 등으로 접두.
- **N-d.** `os.open` 성공과 `result.created = 1` 대입 사이의 Ctrl+C는 `created=0`·정리 없음·부분 효과 false가 될 수 있다(바이트코드 수준의 극히 좁은 창). 0바이트 파일은 다음 실행에서 `exists`로 거부되어 덮이지 않으므로 안전성 문제는 아니며 §6 "강제 종료 시 자동 정리 비보장"의 범위로 기록만 권장.
- **N-e.** `same_file` 판정은 `Path` 동등 비교라 대소문자만 다른 Windows 같은 경로는 `exists`로 거부된다. 덮어쓰기는 없으므로 오류 라벨 차이일 뿐이다.
- 기존 `test_output_race_never_overwrites_an_existing_file`은 이제 사전 존재 거부 테스트이고 실제 경합은 새 테스트가 담당한다. 이름 정리는 선택.

### 결론

- #170 보완본: **PASS**(정적 재검토 기준). R1~R4·N1~N4 **resolved**, N5 **partially resolved**(N-a/N-b 문서 보강은 선택적 후속), 차단 결함 **없음**.
- **pending(Claude 판정 외 조건):** #170 보완본의 PR·CI(Linux/Windows/PostGIS/CodeQL)·병합 결과는 아직 기록되지 않았으며 Claude가 확인하지 않았다. 실행 수치는 Codex 제출 근거다. 원격 전송·암호화·외부 만료·오프호스트 복원은 미구현/미실행이며 이 판정에 포함되지 않는다.

## 15. 최종 정적 검토 후 Codex 대조

실제 추가 검토는2026-11-15T15:02:57Z~15:04:15Z exit0/is_error=false/3turns였다. MD SHA `d6695853c5e87104cb9ed9975377eacfdad4bbddb7584b13dddb0f5563c1f856` → `00bc80fc5ac399925576be7cbe54ba84b3e347c09be027baeca0c7a833d6f895`, permission_denials0, 제공 소스/README/작업계획9파일 SHA 보존을 확인했다.14절은 Claude 직접 수정이며 PASS·차단0·R1~R4/N1~N4 해소다.

- N-a/N-b 수용: §4의 복원 기한 주의와 §11의 최종 head485b2cd/merge557a86f·시각을 명시했다.
- N-c 유지: verify 단계의 기존 ownership/path는 phase로 구분 가능하므로 오류 코드 추가 변경은 하지 않는다. source 오류로 잘못 보고되지는 않는다.
- N-d 보완: create 단계에서 O_EXCL 직후 Python의 생성/identity 기록 전에 Ctrl+C가 발생하면 created0이어도 부분 효과true·미확인 경로1을 보고하고 지우지 않는다. 실제 open 후 인터럽트를 주입하는 테스트로0바이트 파일 보존·다음 실행의 덮기 거부를 확인한다.
- N-e 대조: 현재 Windows의 Path는 대소문자를 무시해 비교한다. 별도 OS에서 경로 alias가 비교를 통과하지 않더라도 기존 파일 거부로 보호되며 데이터 안전성은 달라지지 않는다.

파일 생성 게시의 원자성·hard kill 자동 정리·원격 전송/만료 보장은 계속 범위 밖이다. 생성 직후 경계 보완을 포함한 전체 Windows2241통과·symlink 권한2skip·PostGIS298분리,79.26초를 확인했다. 새 회귀는 #168 대비18개, export 총62개다. 제한 재검토·최종CI 결과는 완료 후 기록한다.

## 16. Claude 제한 재검토 (N-d·N-a·N-b 경계, 2026-11-16)

이 MD만 Read/Edit했다. 프롬프트로 받은 보완본 `backup_export.py`/`test_operation_log_export.py`와 Codex 근거만 사용한 **정적 검토**이며 Claude는 코드·테스트를 실행하지 않았다. 2241통과·export62개는 Codex 제출 수치다. 범위는 아래 변경분으로 한정하고, 14절 PASS 이후 새로운 일반 권고는 추가하지 않는다.

| 항목 | 정적 근거 | 판정 |
| --- | --- | --- |
| N-d 코드 | `run`은 `create_file` 호출 전에 `phase="create"`로 바꾼다. `except KeyboardInterrupt`는 `phase=="create" and not created`이면 `effects_may_be_partial=True`·`orphan_files+=1`로 설정한다. 이후 `finally`는 `created==0`이라 cleanup을 하지 않고(identity가 없으면 삭제하지 않음) 이 플래그를 덮어쓰지 않는다. `main`은 `run`의 반환값을 그대로 출력하며, `run` 밖으로 빠져나온 예외도 execute이면 부분 효과를 true로 만든다. 따라서 O_EXCL open이 성공한 뒤 `result.created=1` 대입이나 fstat/identity 기록 전에 인터럽트가 들어와도 "효과 없음"으로 보고되는 경로는 없다. open 전(Budget/경로 검사) 인터럽트도 같은 보수적 true가 되지만, README의 "계수는 소유 증명이 아닌 미확인 수" 정의와 일치하므로 결함이 아니다 | **해소** |
| N-d 테스트 | `test_interrupt_after_exclusive_open_before_creation_bookkeeping_is_conservative`는 `os.open`을 감싸 `O_CREAT`인 output open이 실제로 성공한 뒤 fd를 닫고 KeyboardInterrupt를 던진다. source `_header`의 `O_RDONLY` open은 통과한다. 검증 항목: `interrupted`·`phase=="create"`·`created==0`·partial true·orphan1·0바이트 파일 보존·removed0·source 해시 불변. 재실행은 `validate_file_path`의 `exists`에서 open 전에 실패하고 파일을 바꾸지 않는다. 대상 경계를 정확히 겨냥한다 | **해소** |
| N-a | §4 `next_expiry_at` 항목에 "복원 가능 기한이 아니며 전송/복원 전 현재 시각으로 모든 세대 cursor도 검증" 문구가 있다 | **해소** |
| N-b | §11 "CI 및 통합 근거"에 최종 head `485b2cd` 8검사 성공/CLEAN, squash `557a86f`(2026-11-15T14:20:06Z), main ff-only를 기록했다. 기능 commit `460baf2`의 CI와도 구분한다 | **해소** |

참고(비차단, 결함 아님): 실제 인터럽트 창에서는 open이 반환한 fd를 닫기 전에 예외가 날 수 있어 프로세스가 끝날 때까지 fd가 남을 수 있다. CLI는 곧바로 종료하므로 보고 정확성과 데이터 안전성에는 영향이 없다.

### 결론

- 이번 변경분: **PASS**. N-d·N-a·N-b **resolved**, 이번 변경분에서 미해결 결함 **없음**, 차단 결함 **없음**. 14절 판정(R1~R4·N1~N4 resolved)은 유지되며, N5는 N-a/N-b 보강으로 **resolved**다. N-c는 Codex의 유지 결정(phase로 구분)을 수용한다.
- **pending(Claude 판정 외 조건):** #170 보완본의 PR·CI(Linux/Windows/PostGIS/CodeQL)·병합 결과는 아직 기록되지 않았고 Claude가 확인하지 않았다. 원격 전송·암호화·외부 만료·오프호스트 복원은 미구현/미실행이며 이 판정에 포함되지 않는다.

## 17. Codex 최종 확인 및 통합 범위

생성 경계의 실제 제한 재검토는2026-11-15T15:09:00Z~15:09:47Z exit0/is_error=false/3turns로 완료했다. MD SHA `d12193778033becbdaf75387f2dbdcd057e11ed4b91471eae652c3abdac63be4` → `b01addd4910a07a51a9d67e4a900fe44c660ac8f6eb7d250adf14f8ddfd9c97c`, permission_denials0·제공 소스9파일 SHA 보존을 확인했다.16절은 Claude 직접 수정이며 N-d/N-a/N-b 해소와 R1~R4/N1~N5 해소·차단0을 최종 확인했다. N-c는 phase 구분 유지 결정을 수용했다.

Codex는 세 번의 실제 MD diff와 코드/테스트를 대조했다. 마지막 전체2241통과·권한2skip 이후 Python/테스트 코드는 바꾸지 않았다. 최초0행 실제 복원과 생성 직후 중단 회귀는 구분하며, 원격 전송·실제30일 보관·오프호스트 복구를 완료로 표시하지 않는다. 이후 PR의 최종 HEAD에 대해 Linux/Windows/PostGIS/CodeQL 결과와 정상 병합 조건을 확인하고 develop에 통합한다. 실제 체크·merge SHA는 #170에 연결된 PR의 체크/병합 기록을 따른다.
