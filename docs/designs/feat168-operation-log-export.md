# 운영 로그 원격 전송용 일관된 백업 내보내기 (#168)

작성: 2026-11-15. 기준 develop `9a406d6`. 브랜치 `feat#168-operation-log-export`.

## 1. 목적과 현재 상태

#166의 두 세대 SPBK 백업은 로컬 정기 실행·무결성·새 SPOL/SPJC 복원까지 검증됐다. 원격 계정/버킷은 아직 연결되지 않았다. 원격 전송 전에 실행 중 SQLite 파일을 단순 복사하면 일관성·논리 소유권·만료 제외·숨은 과거 데이터 배제를 별도로 보장할 수 없다.

이번 이슈는 공급자와 독립적인 **새 SPBK 파일 내보내기**다. 단일 읽기 트랜잭션에서 검증한 논리 내용만 새 파일에 쓰고, 원본을 변경하지 않으며 기존 restore를 그대로 사용할 수 있게 한다. 전송 어댑터나 암호화를 구현했다고 표시하지 않는다.

현재 단계는 **Codex 설계 대조 후 구현 진행, Claude 검토 후속 대기**다. 한도 대기 중 사용자에게 이번 #168만 Codex 검토로 BE 구현·테스트를 먼저 진행하고 Claude 검토를 뒤로 미루는 방식을 제안했고, 사용자가 이어서 “다음 스텝 진행하자”라고 지시했다. 이 응답을 제안한 진행 방식에 대한 승인으로 반영한다. 이번 이슈만 해당 순서를 적용하며 Claude 검토 완료나 PASS로 간주하지 않는다.

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
- `next_expiry_at` (남은 모든 세대의 최소 event 시각 +30일, 남은 행이 없으면 null).
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

같은 단계의13:57:02Z 읽기 전용 운영 확인에서는 기존 수집·백업 Task 모두Ready/LastTaskResult0, 백업 seq13·두 세대·무결성/배포SHA/ACL/source origin 정상, 실제0행·expired0이었다. source/config/Task/FE를 바꾸거나 새로운 제품 테스트를 실행한 결과가 아니다. 설계/실패 기록만 보존하며 구현·PR·병합은 아직 진행하지 않는다.

검토 재개 시 이 MD만 Read/Edit하도록 제한하고 source 관련 발췌·검증 근거를 UTF-8 프롬프트로 제공한다. shell/git/network/DB/MCP/agent/환경 및 다른 파일 읽기/수정 권한은 주지 않는다. 사용자의 후속 진행 지시에 따라 Codex가 먼저 구현·격리 검증하고 실제 MD diff와 검토 이유를 후속 대조한다. FE·의존성·배포 runtime은 바꾸지 않는다. Claude 검토가 미완료이면 PR/완료 보고에도 이를 명시한다.

## 11. Codex 구현 대조 및 실제 검증

### 구현 결과

- 별도 `backup_export` CLI를 추가했다. 기존 backup/archive/job 명령의 코드·형식은 바꾸지 않는다. 기본 preview·명시 execute, source 단일 readonly transaction·세대별 canonical/digest 검증·일괄 만료 제외·메타 보존·새 SPBK 재생성을 구현했다.
- 새 출력의 O_EXCL·identity/nlink·header/schema·닫힌 논리 내용 재검증·유한 SHA256을 대조한다. 전체 SQL/Python Budget은 하나이고 파일 원자적 게시나 OS I/O 강제 종료를 보장하지 않는다. preview는 출력 해시/크기가 null이다.
- source 무결성과 output 무결성/잠금/IO/용량 오류를 단계별로 구분한다. 등록되지 않은 예외 문구는 출력하지 않는다. commit 불확실/생성/정리/잔존/부분 효과를 보존하며 교체·미확인 형식·link·sidecar는 자동 삭제하지 않는다.
- 실제 다른 process가 read 중 BEGIN IMMEDIATE 후 commit을 기다리는 사례와 read 종료 후 source가 새 capture로 진행하는 사례를 격리 검증했다. 출력은 최초 읽기 시점이며 최신 상태를 따라 섞이지 않는다.
- SQLite 파일의 여유 공간/뒤에 붙은 테스트 canary를 논리 출력에 복사하지 않음을 확인했다. 테스트 중 변조용 SQLite 연결은 `closing`으로 명시 종료한다. SQLite connection context만으로는 파일 핸들이 닫히지 않는 Windows 특성을 테스트 정리 기대와 구분했다.
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

Claude는13:56Z 실제 계정 한도 실패 이력이 마지막이며 이 구현을 검토하지 않았다. 사용자 승인한 이번 #168의 Codex 선진행 순서에 따라 구현·직접 대조·실제 검사 근거를 보존하고 **Claude 후속 검토 대기**로 표시한다. B2 버킷/비밀 연결·암호화/인증·전송/다운로드 복원·원격 버전 만료 및 실행 호스트는 별도 후속이다.

### CI 및 통합 근거

기능 commit `460baf2`의 [PR169](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/169)에서 push/PR Backend CI 각3검사와 CodeQL2검사 총8개가 모두 성공했고 merge state CLEAN이었다.

- Linux 일반2223통과·Windows 전용2skip·PostGIS298분리,20.56초.
- Windows native85통과,35.16초. 기존 runner2+backup39+새 export44이며 Linux와 이 Windows runner에서는 실제 symlink 생성 검증도 통과했다.
- 실제 격리 PostGIS298통과·2225분리,146.48초.
- CodeQL actions 분석과 최종 CodeQL 검사 성공.

후속 문서 정리에서는 README를 운영 로그 절로 옮기고, exported origin은 원본 binding을 보존하므로 복원한 새 archive의 이후 capture에는 별도 새 SPBK init이 필요함을 명시했다. Python/테스트/CI 소스는 기능 commit과 동일하며 후속 HEAD의 실제 체크·병합 상태는 PR169에서 확인한다. 이 문서의 CI 성공은 Claude 검토 성공을 뜻하지 않는다.
