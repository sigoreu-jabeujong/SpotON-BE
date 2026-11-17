# 운영 로그 두 세대 백업·만료·복원 (#166)

- 기준 develop `f71fa29`, 2026-11-15. [이슈 #166](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/166).
- [시범 운영 #164](feat164-windows-log-pilot.md) 후속. 현재 PC에 키 없는 정기 백업을 연결하고 새 파일 복원을 검증한다. FE/API/0012/원본·운영 DB/.env/기존 서버/Render/기존 수집 작업은 유지한다. 같은 디스크의 백업이므로 장비 손실·오프호스트 재해복구·상시/실제30일 운영 완료를 뜻하지 않는다.

## 1. 보관 범위

백업 생성일에서 다시30일을 세면 오래된 로그가 원래 발생 후60일까지 남을 수 있다. 따라서 백업 모든 세대에도 원래 event_us 기준 `event_us <= now_us-30일` 만료를 적용한다. 별도 owned SQLite 한 파일에 최근 두 snapshot만 저장하고 과거 임의 파일을 쌓거나 폴더 glob 삭제를 하지 않는다. 수집 결과/DPAPI/키/config/.env/Git/원문 provider 로그를 복사하지 않는다. 허용 canonical 이벤트6종과 재개에 필요한 hash/정수 시각만 보관한다.

정기 유지 시 백업 만료를 먼저 독립 commit하고, 소스 잠금/오류가 뒤따라도 이전 세대의 만료는 반영한다. PC 종료/디스크 오류/프로세스 실패 시 정시 삭제를 보장하지 않으며 다음 성공한 prune에서 삭제한다. 백업은 두 최근 세대(약5분 간격)의 복구 지점이며30일 일별 이력이나 변경 불가 보관소가 아니다. source 손실/손상 시 새 캡처를 실패시켜 기존 세대를 유지한다.

(Claude 검토 보완) 무결성 실패·journal 잔존·schema 불일치는 fail-closed라 **자동 만료도 함께 정지**한다. 즉 손상/강제 종료 뒤에는 운영자가 조치하기 전까지 백업 안의 행이30일을 넘겨 남을 수 있다. 따라서 정기 결과의 연속 실패(같은 사유 반복)를 감시 대상으로 두고, 조치는 원인 확인 후 해당 백업 파일을 폐기(삭제)하고 새로 init하는 것이다(자동 수리 아님). (Claude 구현 검토 보완) 폐기 조치는 **백업 파일 자체의 손상 사유(`backup_integrity`·`backup_journal_present`·`backup_ownership`·`backup_file`)에만** 적용한다. source 손상·시계 역행·source 잠금/부재는 백업이 정상이라는 뜻이며 이때 백업을 지우면 유일한 복구 지점을 잃으므로 폐기하지 않는다(6.3 S1/S2). 백업 작업을 비활성화/제거할 때도 만료가 멈추므로 같은 방식으로 파일을 폐기하거나 prune 작업을 유지한다. restore로 만든 새 파일도 로그 사본이므로 같은30일 의무를 따른다(4절).

## 2. 별도 파일과 무결성

`etl.operation_logs.backup` CLI와 필요한 저장 모듈을 추가한다. SPBK application_id/user_version1·정확한3개 테이블(root metadata, 세대 metadata, events)·복합 PK/시간 index·DELETE journal·trusted_schema OFF·secure_delete ON·temp_store MEMORY를 사용한다. 기존 SPOL archive와 SPJC control 형식은 변경하지 않는다.

- root singleton: target hash(owner/service/고정 버전의 도메인 구분 JSON SHA256), 최초 캡처 이후 origin binding hash, 최신 slot(없음/0/1).
- generation: slot0/1, captured_us, initial_ns, cursor_ns, retained row_count, content SHA256. source binding은 root에 고정한다.
- events: slot0/1, event_hash, event_us, event, canonical record. PK(slot,event_hash). 각 세대 SHA256은 정렬된 record의 UTF-8+LF와 metadata 시각/타깃을 도메인으로 묶어 계산한다. 해시는 우발적 손상 검사이며 공격자 인증/원천 완전성/전자서명이 아니다.
- 세대당 최대100,000행·canonical64MiB, 파일 최대256MiB·SQLite max_page_count. 검증/쓰기 연산은 약30초의 monotonic/progress-handler 예산을 사용한다. 초과 시 실패하고 일부만 성공으로 보관하지 않는다. 엄격한 OS I/O 종료 SLA는 아니다.
- 경로는 기존 filesystem 검사(절대 로컬 .sqlite3·저장소 밖·비링크/비reparse·부속 파일 거절·헤더/identity)를 재사용한다. 하드링크/nlink!=1도 거절한다. 기존 빈 파일/다른 marker/schema/extra 객체는 자동 수리·덮어쓰지 않는다. init은 O_EXCL 새 파일만 생성한다. journal이 남으면 자동 recovery/삭제하지 않고 수동 점검한다.
- 메타/row를 검사할 때 타입·범위·slot 집합·count/digest·record canonical/hash/event_us/event 일치를 모두 확인한다. 임의 text/키를 허용하지 않고 오류에 원문을 넣지 않는다. 만료 행도 먼저 무결성 검사한 후 삭제해 의도치 않은 파일 정리를 막는다.

(Claude 검토 보완 — 구현 시 고정할 세부)
- application_id는 `0x5350424B`(SPBK)로 SPOL `0x53504F4C`·SPJC `0x53504A43`와 구분하고 헤더 검사는 기존 `_header(..., application_id=...)`를 재사용한다.
- row 무결성은 "저장된 record 문자열을 기존 `validation.parse_record`로 다시 파싱했을 때 canonical·event_hash·event_us·event가 저장값과 바이트 단위로 같음"으로 정의한다. 원본 archive 테이블에는 hash 형식 CHECK가 없으므로 source 행도 같은 검사를 통과해야 하며 한 행이라도 실패하면 캡처 전체를 실패시킨다. parse_record의 4096바이트 상한이 canonical(소수6자리 시각 보정 포함)에 적용되므로, 허용 최대 길이 입력의 재파싱 왕복을 테스트로 고정한다.
- 세대 digest의 입력 순서를 고정한다: 도메인 문자열(백업 규칙 버전)·target hash·origin binding·captured_us·initial_ns·cursor_ns·row_count를 정렬 JSON 한 줄로 쓴 뒤, event_hash 오름차순 record의 UTF-8+LF를 잇는다. slot 번호는 넣지 않는다. prune은 기존 digest 검증 → 삭제 → 새 count/digest 기록을 한 transaction에서 수행한다.
- `max_page_count`는 연결별 설정이므로 모든 write 연결에서 매번 설정·재확인한다. 크기 상한 판정은 OS 파일 크기가 아닌 `page_count*page_size`로 한다(auto_vacuum 없음, 해제 page는 secure_delete로 0 기록 후 재사용).
- 경로 비교는 문자열이 아닌 `(st_dev, st_ino)` identity로 db/state/backup(및 restore 대상 상호 간)을 모두 비교한다.

## 3. 명령·캡처 순서

모든 명령은 기본 preview이고 `--execute`에서만 생성/갱신한다. 출력은 고정 상태/사유·건수·시각·불리언만 JSON 한 줄이다. 파일 경로/target ID/record/key는 출력하지 않는다. 성공0/실패1/사용법2/중단130을 따른다.

- `init --backup --owner-id --service-id [--execute]`: 두 세대가 없는 owned 빈 보관소를 초기화한다. 기존 파일은 거절한다.
- `status --backup --owner-id --service-id`: 읽기 전용 무결성/세대·만료 예정 수·마지막 capture/cursor를 확인한다.
- `prune --backup --owner-id --service-id [--execute]`: 모든 세대의 만료 행을 지우고 각 count/digest를 같은 transaction에서 갱신한다. source/키/네트워크가 필요 없다. captured_us/cursor를 새 캡처인 것처럼 바꾸지 않는다.
- `capture --db --state --backup --owner-id --service-id [--execute]`: 소스와 백업 경로가 모두 다르고 target이 일치해야 한다. target/header/schema/무결성 검사 → 백업 prune 독립 commit → source control BEGIN IMMEDIATE(쓰지 않음) → source binding/cursor/시계 검사 → archive 읽기 snapshot → 허용 current rows 전체 검증 → 반대 slot의 data/metadata/root pointer 한 transaction commit 순서다. 오래된 source 행은 복사하지 않는다. future/불일치/상한은 실패하며 원본을 바꾸지 않는다.
- capture는 첫 성공의 source binding을 고정하고 이후 다른 archive/inode/initial 규칙으로의 전환을 거절한다. cursor 역행도 거절한다. 같은 source의 수집/백업은 control 잠금으로 직렬화되고 보관소 commit 전에도 source identity/binding을 재확인한다. 실패하면 새 세대는 rollback되지만 앞선 prune은 남는다. preview는 쓰기 잠금/변경 없이 같은 계획만 검증한다(실행과 시점 차이 가능).

(Claude 검토 보완 — capture 순서·스냅샷·결과 보고)
- prune 이전에는 인자 형식·경로 문법·identity 상호 비교만 한다. source db/state의 존재·소유권·헤더 검사는 **prune commit 이후**에 수행해 source 없음/손상이 백업 만료를 막지 않게 한다. 백업 자체의 무결성 실패는 prune도 막는다(1절 보완).
- 한 실행의 기준 시각 `now`는 시작 시 1회만 취해 백업 prune cutoff·source 행 cutoff·future 판정·captured_us에 같이 쓴다. captured_us가 기존 최신 세대보다 작으면(시계 역행) 실패한다.
- 일관성 근거: 수집 job은 execute 동안 control에 `BEGIN IMMEDIATE`를 쥐고 archive commit 후 checkpoint를 commit한다. capture가 control RESERVED를 얻은 상태에서 state 읽기와 archive 단일 읽기 transaction(DELETE journal의 SHARED 잠금)을 모두 끝내면, 저장된 cursor 이하의 확정 수집은 모두 archive에 있고 cursor 이후 미확정 행이 더 있을 수 있을 뿐이다(재조회 중복 방지로 안전). archive의 모든 SELECT는 한 transaction 안에서 수행한다. control·archive 읽기 transaction은 행을 메모리(상한 내)로 검증·적재한 뒤 해제하고 backup write를 수행해도 된다(권장: 수집 차단 시간 축소). 이 경우 backup commit 직전 source identity/binding 재확인은 파일 교체 탐지용이며 스냅샷 일관성은 앞선 잠금 구간이 보장한다.
- control 잠금 대기는 기존과 같은1초이며 수집 중이면 `source_busy`로 실패한다(앞선 prune은 유지).
- 기록할 slot은 backup `BEGIN IMMEDIATE` 안에서 root pointer를 다시 읽어 결정한다(세대0개→slot0, 이후 최신의 반대 slot). 덮어쓸 기존 세대도 같은 transaction에서 digest를 검증한 뒤 삭제한다.
- source cursor 검사는 `initial_ns<=cursor_ns<=now`이며 cursor가30일 만료된 source는 캡처하지 않는다(복원 불가 세대 방지). initial_ns는 최초 시작 시각으로 고정·불변이라 30일보다 오래될 수 있고 이를 거절 사유로 쓰지 않는다.
- 결과 JSON 고정 필드(값만, 경로/ID 없음): `status, error, phase, mode, backup_prune_committed, prune_deleted, prune_would_delete, generation_committed, rows_captured, source_rows_skipped_expired, generations_after, effects_may_be_partial, commit_outcome_unknown`. prune commit 후 실패면 `effects_may_be_partial=true`, backup commit 호출 중 중단/예외면 `commit_outcome_unknown=true`로 두고 다음 `status`로 확인한다. 같은 사유 코드 체계(`backup_integrity`, `backup_journal_present`, `source_busy`, `source_missing`, `binding_mismatch`, `cursor_regression`, `source_future_rows`, `capture_limit`, `budget_exceeded` 등)를 status/Task 감시에 쓴다.

prune의 잠금은 열고 닫은 뒤 source 잠금을 잡는다. 캡처는 control→source read→backup write 순서이고 복원은 backup read→새 파일만 쓰므로 기존 수집 잠금으로 돌아가는 경로가 없다. 동시 백업 변경에 대해서도 write transaction에서 metadata/target/origin을 재확인한다. 검증된 원본 schema/data는 backup 시점의 일관된 snapshot이며 미확정 수집 기록이 이미 archive에 있으면 함께 보관해도 재조회 중복 방지로 안전하다.

## 4. 새 파일 복원

`restore --backup --db <new> --state <new> --owner-id --service-id --generation latest|previous [--execute]`를 추가한다. 두 대상 모두 없어야 하고 원본/backup과 같거나 링크로 연결되면 거절한다. backup 읽기 transaction 안에서 전체 무결성과 target hash/버전을 확인한 뒤 해당 slot을 고른다. 세대가 없거나 cursor가 현재보다 미래/30일 만료면 생성 전에 실패하고 자동 건너뛰지 않는다.

현재 기준 만료 행은 복원하지 않으며 수와 skipped를 보고한다. 새 SPOL archive를 명시 초기화하고 검증된 current 행을 한 transaction으로 저장한다. 그 뒤에만 새 SPJC state를 만들며 original initial_ns/cursor_ns를 유지하되 **새 archive 경로/inode에 맞는 binding을 재계산**한다. 그래야 이전2분 중첩 재조회 의미를 유지하고 old binding의 임의 재사용을 막는다. 키/config/실제 운영 경로/Task를 자동 복구·교체하지 않는다.

(Claude 검토 보완) 복원 가능 조건의30일 판정은 **cursor_ns에만** 적용한다. initial_ns는 수집 시작 시각으로 고정되어 운영30일 이후 항상 만료 시점보다 오래되므로 거절 사유로 쓰지 않는다(job의 init 범위 검사를 restore에 재사용하지 않고 `job_state.initialize`에 검증된 State를 직접 전달). 새 state는 `initial_ns<=cursor_ns<=now`를 만족해야 한다. 결과 JSON 고정 필드는 `status, error, phase, mode, generation, archive_created, state_created, rows_restored, rows_skipped_expired, created_files_removed, orphan_files, effects_may_be_partial`이다.

두 새 파일 생성은 원자적 분산 commit이 아니다. archive 완료 후 state 생성이 실패/중단되면 새 archive만 남을 수 있고 생성 단계/부분 효과를 보고한다. (Claude 검토 보완) 기존 `archive.initialize`/`job_state.initialize`와 같이, 실패 시 **이번 실행이 O_EXCL로 만든 파일만** identity 일치를 확인해 제거를 시도하고 `created_files_removed`로 보고한다. 제거 실패·강제 종료로 남은 파일은 `orphan_files`로 보고하며, 로그 사본이므로 운영자가 삭제한다. 검증 목적의 복원 산출물은 대조가 끝나면 삭제하거나, 남겨 둘 경우 기존 SPOL prune 대상에 포함해30일을 넘기지 않는다. 기존 파일을 지우거나 덮어쓰지 않고, 다시 시도할 때는 다른 새 파일명을 사용한다. 운영 전환은 Disabled→복원 검증→명시 config/binding 변경→preview→활성화의 별도 절차다. origin binding이 바뀌면 기존 backup에 자동 이어쓰지 않고 새 보관소를 준비하며 이전 보관소의 prune/폐기도 함께 관리한다.

## 5. 정기 연결과 검증

현재 제한 ACL 폴더 아래 backup.sqlite3와 별도 고정 backup-runtime을 준비한다. 기존 collection runtime/runner/config/DPAPI와 Task action은 바꾸지 않는다. capture는 키가 없으므로 Python을 직접 실행하는 별도 Interactive/Limited 작업으로 연결한다. Task XML에는 private config 경로만 넣고 owner/service는 넣지 않도록 `capture --config <JSON>` 입력을 지원한다. config에는 db/state/backup/owner_id/service_id의 정확한5필드만 둔다. 크기 제한·중복 키/비정상 JSON/허용 밖 필드·부모 reparse/UNC/ADS/저장소 내부를 거절하고 출력을 하지 않는다.

backup-runtime은 검증된 구현 commit의 detached worktree이고 Task action의 working directory로 고정한다. 동일 사용자/SYSTEM ACL, source/manifest 해시를 설치/검증 시 대조한다. 공유 venv와 같은 사용자 신뢰 전제는 #164와 같다. 5분 주기·로그온·StartWhenAvailable·IgnoreNew·2분 상한·wakeoff·배터리 허용으로 구성하며 수집의 약2분 뒤에 배치한다. 내부 연산 예산이 정상 종료를 먼저 유도한다. 외부 강제 종료는 journal 점검이 필요하며 자동 복구/삭제하지 않는다.

(Claude 검토 보완) `--config`와 개별 경로/ID 인자는 상호 배타이며 둘 다/둘 다 없음은 사용법 오류(2)다. 행 상한(100,000/64MiB)은 실제 source 유입률로 30일 누적량을 산정해 여유를 확인한다. 초과 시 capture는 fail-closed로 계속 실패하고 기존 세대는 만료로 비어 가므로, status에 source 행 수와 상한 대비를 보고해 감시에서 상한 근접을 발견할 수 있게 한다. 내부 예산은 기존 archive 읽기 연결의 10초 progress 마감을 그대로 쓸지, 백업 모듈 전용 30초 예산을 쓸지 구현에서 하나로 고정하고 테스트한다.

actual snapshot은 status의 capture UTC 신선도와 native COM LastTaskResult로 감시한다. 결과 stdout을 무한 파일로 쌓지 않는다. 실패한 source 캡처 뒤에도 백업 prune이 반영됐는지 집계로 확인한다. source/backup 두 세대가 함께 같은 디스크에서 손실되면 복구할 수 없으며 별도 원격 대상 연결은 후속이다.

검증: 양수6종 canonical snapshot·두 slot rotation/previous 복원·target/origin 불일치·행/hash/metadata/스키마 손상·정확30일 만료와 future·source byte 불변·새 inode state 재결합·세대 commit 실패/중단·소스 잠금/없음 뒤에도 백업 prune·read-only bytes·부분 restore·파일/링크/부속물·상한/예산·안전한 출력. 실제 원본 백업/새 파일 복원과 정기 Task를 대조하되 현재0행 source와 양수 fixture를 구분한다. Windows/Linux 일반·ruff/mypy·격리 PostGIS/CodeQL과 실제 Claude 구현 검토를 따른다.

근거: [SQLite 격리](https://www.sqlite.org/isolation.html), [원자적 commit](https://www.sqlite.org/atomiccommit.html), [secure_delete](https://www.sqlite.org/pragma.html#pragma_secure_delete). 논리적 만료/삭제와 OS·미디어·다른 복사본의 완전 소거를 구분한다.

## 6. 실제 검토·실행 기록

Codex 설계 → 실제 Claude MD Read/Edit → Codex 대조/구현·검증 → 실제 Claude 구현 검토 → 기능/문서 커밋·CI/develop PR Squash를 따른다. Claude는 이 MD만 Read/Edit하고 제공 소스/집계만 검토한다. shell/Git/DB/네트워크/MCP/다른 파일/서브에이전트를 사용하지 않으며 테스트 실행을 대신 주장하지 않는다. 이유와 차단/보류를 직접 기록한다.

### 6.1 실제 Claude 설계 검토 (2026-11-15)

- 범위: 이 MD와 대화로 제공된 `archive.py`·`job_state.py`·`job.py`·`validation.py` 원문만 Read/대조했다. shell/Git/DB/네트워크/MCP/다른 파일/서브에이전트는 사용하지 않았고, 어떤 테스트·실행·실측도 하지 않았으며 그 결과를 주장하지 않는다. 사용자가 #164 후속으로 이미 승인한 로컬 두 세대 백업·만료·새 파일 복원·키 없는 정기 백업 범위이므로 추가 승인 단계를 만들지 않았다. 오프호스트/상시/실제30일 근거가 아니라는 기존 한계는 그대로다.
- 최초 판정: **REVISE**. 아래 R1~R7을 이 MD 본문에 직접 반영했다(각 절의 "Claude 검토 보완").
  - R1 일관 스냅샷: 수집 job이 execute 내내 control `BEGIN IMMEDIATE`를 쥐고 archive commit→checkpoint commit 순서이므로, control RESERVED 확보 상태에서 state와 archive 단일 읽기 transaction을 끝내면 "cursor 이하 확정분 ⊆ 스냅샷"이 성립함을 근거로 명시했다. 원문은 archive 읽기가 한 transaction이어야 한다는 점과 slot 결정 시점(backup write transaction 안 재조회)이 빠져 있었다. 수집 차단 축소를 위해 backup write 전 control 해제를 허용했고, 잠금 순서(backup prune → control → archive read → backup write, restore는 backup read → 새 파일)에 순환이 없음을 확인했다.
  - R2 교차 파일 실패 보고: prune commit/세대 commit/commit 결과 불명/restore 파일별 생성·제거·잔존을 구분하는 고정 결과 필드와 사유 코드를 정의했다(기존 job `effects_may_be_partial` 패턴과 같은 방식).
  - R3 메타·행 무결성: "canonical 일치"를 `parse_record` 재파싱의 바이트 동일성으로 정의하고, digest 입력 순서(정렬 JSON 메타+event_hash 순 record)를 고정했다. source archive에 hash CHECK가 없어 source 행도 같은 검사가 필요함을 명시했다. 재파싱 시 시각이 소수6자리로 정규화되어 길어질 수 있으므로 4096바이트 상한 왕복을 테스트 항목으로 남겼다(현재 허용 필드 구조상 실제 도달 가능성은 낮다고 판단하나 단정하지 않음).
  - R4 파일 가드: SPBK id 값, identity 기반 상호 비교, 연결별 `max_page_count` 재설정, page 기반 크기 판정을 추가했다. 기존 `validate_file_path`의 journal 잔존 거절·nlink 검사 재사용은 적절하다.
  - R5 source 실패 전 독립 만료: prune 전에는 문법/identity 검사만 하고 source 존재·헤더 검사는 prune commit 뒤로 미루도록 순서를 명확히 했다. 단일 `now`를 모든 cutoff에 공유하게 했다.
  - R6 두 세대 전역30일·fail-closed의 대가: 무결성/journal 실패가 자동 만료까지 멈춘다는 점, 백업 작업 비활성화 시 만료 정지, restore 산출물이 새 로그 사본이라는 점을 명시하고 조치(폐기 후 재init, 산출물 삭제/prune 편입, 연속 실패 감시)를 정했다. 승인 절차가 아닌 운영 절차다.
  - R7 binding/rebinding: restore의30일 판정을 cursor에만 적용하고 initial_ns(불변 시작 시각)를 거절 사유로 쓰지 않도록 했다. 그대로 두면 운영30일 이후 모든 restore가 실패할 수 있었다. 새 binding은 archive commit 뒤 새 inode로 재계산하고 기존 backup은 origin binding 고정으로 새 source에 이어쓰지 않는다는 원안은 타당하다.
- 비변경 확인: preview는 control/backup 모두 `mode=ro`·쓰기 잠금 없음·파일 생성 없음으로 비변경이며, journal 잔존 시 SQLite가 열기 전에 거절되어 읽기 전용 열기가 hot journal 복구를 시도하지 않는다. 행 상한·예산 초과 시 부분 세대를 남기지 않는 원안도 유지한다.
- 보류(구현 검토에서 확인): 행 상한의 실제 유입률 적정성, archive 읽기 예산(기존10초 vs 30초) 단일화, captured_us 역행 거절 테스트, Task의 콘솔/세션 동작은 #164 전제를 따름.
- 반영 후 판정: **설계 PASS(R1~R7 반영 본문 기준)**. 구현·테스트·실제 백업/복원/Task 결과는 아직 없으며, Codex 대조·구현과 실제 Claude 구현 검토에서 별도로 확인해야 한다.

### 6.2 Codex 구현 대조·로컬 검증

- SPBK3테이블/시간 index·두 slot·target/origin hash와 canonical 재파싱을 구현했다. 메타에 증가 sequence를 추가해 active pointer가 실제 최신 세대를 가리키는지 검사한다. digest에는 sequence/target/origin/시각/초기·확정 cursor/row_count와 정렬 record를 포함하고 slot은 포함하지 않는다. prune은 모든 세대의 digest를 검증한 뒤 event 시각으로 삭제·재계산하며 capture 시각을 바꾸지 않는다.
- 기존 filesystem helper의 기본 동작을 유지하고 고정 suffix(.json)와 syntax_only 모드만 추가했다. syntax_only는 source 부재/저널/헤더 오류 전에 백업 만료를 진행하기 위한 경로 문법·부모 reparse·identity 검사이며 SQLite 인증 용도로 쓰지 않는다. full header/schema 검사는 prune 뒤 source 연결에서 수행한다. capture 중 archive binding과 state inode를 commit 전에 재검사한다.
- source 읽기에도 백업 전용30초 global budget을 설치해 기존 archive 연결의10초 handler를 덮어쓴다. SQL/메모리 검증의 같은 예산이며 OS I/O 종료 SLA는 아니다. 현재 수집 차단은 control Reserved를 백업 commit까지 유지하는 보수적 방식이다. source 데이터/상태 파일에는 DML/commit을 하지 않는다.
- 새 백업 테스트38개 통과(8.42초):6종 양수 복원·두 세대/previous/세 번째 순환·전체 세대 정확30일 만료·원문 없는 source/backup 손상 거절·source 없음/다른 프로세스 잠금 전 독립 prune·commit 실패/중단 rollback·실제 자식 강제종료 journal 거절·복원 실패 소유 파일만 제거/교체 파일 보호·old initial 보존·cursor 만료/역행/future·상한/예산/하드링크·config/출력·키 없이 HTTP client0을 검증했다. secure_delete 이후 만료 이벤트의 고유 UUID가 백업 바이트에서 사라짐도 검사했다(미디어 완전 소거 증거가 아님).
- archive/job 기존 회귀119통과·Windows symlink1skip. 전체 일반2179통과·기존 symlink1skip·PostGIS298분리,75.46초. 기존 Starlette 경고1개다. ruff check/426파일 format·Windows/Linux mypy192파일·diff 검사 통과. Windows CI에도 백업38개를 기존 native2개와 함께 추가했다. 실제 운영 백업/복원/새 Task 연결은 아직 수행 전이다.

### 6.3 실제 Claude 구현 검토 (2026-11-15)

- 범위: 이 MD와 대화로 제공된 `archive.py`·`job_state.py`·`job.py`·`validation.py`(기존), `backup_store.py`·`backup.py`·`tests/etl/test_operation_log_backup.py`(구현), Codex 검증 요약 원문만 Read/대조했다. shell/Git/DB/네트워크/MCP/다른 파일/서브에이전트는 사용하지 않았다. 테스트·CLI·백업/복원/Task를 실행하지 않았으며 6.2의 수치(38/119/2179 등)는 Codex 보고를 옮긴 것이지 이 검토가 재현한 결과가 아니다. 사용자가 승인한 범위(로컬 두 세대 백업·event 시각 만료·새 파일 복원·키 없는 정기 capture)이므로 새 승인 단계는 만들지 않았다.
- 판정: **REVISE(구현 수정 2건 필수, 나머지 비차단)**. 설계 구조·잠금 순서·만료·복원 재결합은 타당하나, 실패 사유 코드가 1절의 운영 조치(백업 폐기)와 결합될 때 정상 백업을 지우도록 유도하는 경로가 2개 있다.

#### 필수 수정

- **S1 source 손상이 `backup_integrity`로 보고됨.** `capture`의 source 읽기가 `store.bounded_records`→`store.record`를 그대로 사용해 source 행 손상도 `BackupError("backup_integrity")`가 된다. 테스트 `test_corrupt_source_leaves_previous_generation`도 이 코드를 기대값으로 고정했다. 1절은 `backup_integrity` 연속 실패 시 백업 폐기·재init을 조치로 정했으므로, source가 손상된 바로 그 상황에서 운영자가 유일한 정상 복구 지점을 지우게 된다. 수정: source 경로는 별도 사유 `source_integrity`(source 쪽 행 수 상한도 구분이 필요하면 `source_capture_limit`)로 매핑하고, 테스트 기대값을 바꾸며, 사유 목록(3절)에 추가한다. `record()`에 사유 인자를 주거나 capture에서 BackupError를 재매핑하는 방식 모두 가능하다.
- **S2 시계 역행이 `backup_integrity`로 보고되고 만료/status까지 막음.** `store.load`가 `captured_us <= now_us`를 무결성 조건으로 검사하므로, 시계가 직전 capture 시각보다 뒤로 가면 prune·status·capture·restore가 모두 `backup_integrity`로 실패한다. `capture`의 `clock_before_backup` 분기는 load가 먼저 실패해 도달하지 않는다(테스트 `test_clock_regression...`의 첫 assert는 사유를 확인하지 않아 이를 드러내지 못함). 결과적으로 (a) S1과 같은 잘못된 폐기 유도, (b) 3절 "captured_us 역행은 실패"의 고정 사유 부재다. 시계 역행 동안 prune 정지는 더 이른 now 기준이라 30일 의무를 추가로 어기지는 않지만 사유는 구분해야 한다. 수정: load에서 미래 captured_us(및 그에 따른 cursor/행 시각 검사)를 `clock_before_backup`으로 분리하고, 테스트에서 사유 문자열과 prune/status 동작을 고정한다. 구조 손상과 시계 문제를 같은 코드로 섞지 않는다.

#### 확인한 항목(PASS)

- 일관 스냅샷: capture는 control `BEGIN IMMEDIATE`(execute)를 백업 commit까지 유지하고, archive의 count·행 SELECT를 `archive.connect`의 단일 `BEGIN` 안에서 끝낸다. 수집 job은 execute 내내 같은 control 잠금을 쥐므로 R1의 "cursor 이하 확정분 ⊆ 스냅샷"이 성립한다. 설계가 허용한 조기 해제 대신 보수적 유지를 택했고 6.2에 기록했다. 잠금 순서(backup prune → control → archive read → backup write, restore는 backup read → 새 파일)에 순환이 없다.
- 덮어쓸 세대: slot은 backup write transaction 안의 `store.load` 재조회로 결정하고, 같은 transaction에서 두 세대 digest를 모두 검증한 뒤 events→generation 순으로 삭제한다(FK ON). origin 불일치는 `origin_changed`, cursor 역행은 `cursor_regression`.
- 메타·행 무결성: 타입/범위/slot 집합/고아 slot/sequence 연속·active=최신/initial 동일/cursor·captured 단조/행 수/digest/`parse_record` 재파싱 바이트 일치를 모두 검사한다. 추가한 sequence가 pointer 뒤바뀜을 잡는다. digest 입력(정렬 JSON 메타+event_hash 순 record, slot 제외)은 2절과 일치하고 SQL `ORDER BY event_hash`(BINARY, 소문자 hex)와 Python 순서가 같다. `LIMIT 6`로 추가 schema 객체를 검출한다. 최대 길이 왕복 테스트가 있다.
- 파일 가드: SPBK 헤더·nlink=1·page 기반 크기·연결별 `max_page_count` 재설정·journal 잔존 fail-closed·O_EXCL init/실패 시 자기 파일만 제거. `distinct`는 resolve와 존재 파일 identity를 모두 비교한다.
- source 실패 전 독립 만료: prune 전에는 `syntax_only` 경로/identity 검사만 하고, source 존재·헤더·binding 검사는 prune commit 뒤다. 단일 `now_us`를 prune/source cutoff/future/captured_us에 공유한다. target(owner/service) 불일치는 prune 전에 실패하는데, 다른 대상의 설정으로 백업을 수정하지 않는다는 의미라 타당하다.
- 두 세대 전역30일: prune은 모든 slot에서 `event_us<=now-30일`을 검증 후 삭제·count/digest 재계산하고 captured_us/cursor를 바꾸지 않는다. restore는 prune 전이어도 만료 행을 다시 넣지 않는다.
- binding/rebinding: restore의 30일 판정은 cursor에만 적용하고(`validate_cursor`), initial_ns는 보존하며 새 archive inode로 binding을 재계산한다. 실패 시 identity·헤더·nlink가 일치하는 자기 생성 파일만 지우고 교체 파일은 보호한다.
- 상한·예산: 행/바이트/파일 상한 초과 시 세대를 쓰지 않는다. 30초 단일 예산이 backup·source 연결(기존 10초 handler 덮어씀)과 Python 루프에 적용되고 SQLITE_INTERRUPT→`budget_exceeded`로 매핑된다(설계 6.1 보류 항목 해소).
- 비변경 preview: prune/capture/restore preview는 `mode=ro` 연결과 rollback만 사용하고 파일을 만들지 않는다. 키/HTTP 비사용·출력에 경로/ID/원문 없음·config 상호 배타/중복 키 거절도 구현과 테스트가 맞는다.

#### 비차단 권고·보류

- N1 `binding_mismatch`가 백업 target(owner/service 설정 오류)과 source binding 불일치 두 경우에 함께 쓰인다. 운영 조치가 다르므로 target 쪽을 `target_mismatch`로 나누는 것을 권장한다.
- N2 capture 결과의 `backup_prune_committed`는 삭제 0건이어도 true가 되어 이후 어떤 실패든 `effects_may_be_partial=true`가 된다. restore도 생성 파일을 정리한 뒤 `archive_created=1`이 남아 같은 값이 된다. 보수적 과대 보고라 안전하지만, 감시는 `prune_deleted`·`created_files_removed`·`orphan_files`를 함께 본다고 5절 감시 기준에 명시하거나 실제 잔존 효과로 좁힌다.
- N3 preview capture도 control/archive에 SHARED 읽기 잠금을 잡는다. 수동 preview가 수집 job의 checkpoint commit과 겹치면 job이 `state_busy`로 끝날 수 있다(재조회로 데이터 손실은 없음). 3절 "쓰기 잠금 없이"는 맞지만 "수집에 영향 없음"으로 읽히지 않게 운영 안내에 남긴다.
- N4 `now`는 실행 시작 시 1회 취하고 control 잠금은 prune 뒤에 얻는다. 그 사이 수집 job이 5분 경계를 넘긴 시각으로 checkpoint를 확정하면 `clock_behind_checkpoint`가 일시적으로 날 수 있다. 다음 주기에 회복되는 드문 경합이며 수집 약2분 뒤 배치로 줄어든다. 사유가 연속되지 않으면 감시 경보로 다루지 않는다.
- N5 5절은 "status에 source 행 수와 상한 대비 보고"를 요구하지만 status는 source를 읽지 않고, `source_rows_current`/`capture_limit_rows`는 capture stdout에만 있다. stdout을 보관하지 않는 Task 감시에서는 상한 근접을 실패 전에 볼 수 없다. Task 연결 전에 (a) status에 선택적 source 읽기 추가 또는 (b) 최신 세대 `row_count`를 상한 대비 지표로 쓰는 것 중 하나로 설계 문구를 고정한다.
- N6 DELETE journal 모드의 commit 후 삭제된 journal 파일과 OS 블록에는 만료 전 페이지가 남을 수 있다. 5절의 "논리적 만료와 미디어 완전 소거 구분" 범위이며 추가 조치는 요구하지 않는다.
- 보류: 실제 운영 원본의 capture/새 파일 복원·정기 Task 등록/실행·실제 유입률 대비 상한 산정은 아직 근거가 없다. 이 검토는 오프호스트 DR·상시 운영·실제30일 보관 완료를 뜻하지 않는다.

- 다음 단계: S1·S2 수정과 해당 테스트(사유 문자열 고정, 시계 역행 시 status/prune 사유) 반영 후 실제 Claude 재검토에서 PASS 여부를 기록한다. N1~N5는 같은 수정에 포함하거나 근거와 함께 보류를 남긴다.

### 6.4 Codex 검수 보완·최종 로컬 검증

- S1: source canonical/행 손상만 `source_integrity`로 분리했다. 정상 backup은 보존하며 원본 점검/복원에 사용한다. 백업 파일 자체의 digest/row 손상만 `backup_integrity`다. N1 target 설정 불일치도 `target_mismatch`로 분리했다. 오류만 보고 정상 백업을 자동 삭제하지 않는다.
- S2: captured_us의 타입/내부 범위 검증과 현재 시각 대비 미래 여부를 나눴다. 현재 시각이 이전 capture보다 뒤로 가면 capture/status/prune 모두 `clock_before_backup`이고 삭제/새 세대 commit이 없다. 시계 복구 후 다시 검증하며 손상으로 간주해 폐기하지 않는다. 테스트에 정확한 사유/비변경을 고정했다.
- N2/N3/N4는 한계로 유지한다. `effects_may_be_partial`은 보수적 값이며 실제 prune_deleted·정리된 생성 파일·잔존 파일을 함께 본다. preview의 짧은 SHARED 잠금도 checkpoint commit을 지연시킬 수 있다. 실행 시작 now와 잠금 사이의 경계 경합은 다음 주기에 회복될 수 있어 연속 실패/15분 신선도와 함께 감시한다.
- N5는 status가 source를 추가로 읽지 않는 방식을 택했다. `latest_rows`/`latest_bytes`는 최신 **남아 있는 snapshot** 수치, `near_capture_limit`는 행/바이트 상한90% 기준이다. `captured_at` 신선도를 함께 보며 현재 source 실제 행 수로 해석하지 않는다. `source_rows_current`는 capture에서만 측정하고 status는 null이다. 따라서 급격한 유입 증가를 미리 예측하는 감시까지 보장하지 않는다.
- 보완된 백업 테스트39개 통과(8.47초), 전체 Windows 일반2180통과·기존 symlink1skip·PostGIS298분리,73.59초. 기존 Starlette 경고1개, ruff check/426파일 format·Windows/Linux mypy192파일·diff 검사 통과. Windows CI는 기존 native2개+backup39개를 실행한다. 6.2의 수치는 보완 전 근거다.
- 콘솔 창을 만들지 않도록 정기 작업은 같은 venv의 `pythonw.exe -E -s -B -m etl.operation_logs.backup capture --config ... --execute`로 실행한다. 로컬에서 pythonw 파일 존재와 stdout 없는 print의 정상 반환을 확인했다. 실제 GUI 프로세스의 Task 종료·capture 갱신은 연결 후 따로 관찰한다. Pythonw에는 stdout 기록을 요구하지 않고 status/Task COM으로 감시한다.
- 실제 배치 스크립트는 새 backup-runtime/config/store/manifest만 생성하며 기존 collection config/runner/DPAPI를 바꾸지 않는다. 두 번 초기 snapshot 후 새 archive/state로 복원·행/메타/새 binding 대조·검증 사본2개 정리를 수행한다. 별도 Task는 수집과 엇갈린 minute=2 mod5의 5분 반복이고 XML·CIM 검증 후 활성화한다. 실제 실행은 아직 수행 전이다.

### 6.5 추가 Claude 재검수 한도·Codex 최종 대조

2026-11-15T13:07:17Z 실제 추가 재검수를 요청했으나13:07:56Z exit1/is_error=true, MD SHA256 변화 없이 중단됐다. CLI 응답은 **Claude Code 계정5시간 사용 한도, 오늘23:50(Asia/Seoul) 초기화 예정**이다. 제품 LLM/Gemini/API키 오류나 Codex 한도가 아니다. 이 호출을 Read/Edit 검수 완료 또는 최종 PASS로 기록하지 않는다.

설계 검토6.1과 구현 검토6.3은 실제 수행됐고, S1/S2 수정 후 Codex가 코드/사유·회귀 결과를 최종 대조했다. source canonical 실패만 source_integrity로 매핑하고, backup 자체의 load/digest 실패는 별도로 유지한다. captured_us 내부 범위와 현재 시각 비교를 분리해 status/prune/capture 모두 clock_before_backup으로 실패하며 쓰지 않음을39개 테스트와 전체2180개에서 확인했다. N1 target_mismatch와 N5 최신 snapshot 상한 지표도 대조했다. FE/API/환경/기존 수집을 바꾸지 않는 사용자 승인 범위와 기존 통합 작업계획의 Codex 대조·테스트·PR 절차로 진행한다. **추가 Claude 재검수는 보류**로 남기며 완료/승인으로 간주하지 않는다.

### 6.6 실제 로컬 백업·복원·정기 실행

- 2026-11-15T13:10:10Z 구현 commit `5897ff6`의 별도 detached backup-runtime을 생성하고7개 ETL 모듈 해시를 대조했다. 전용 backup.sqlite3/config/manifest만 추가했으며 기존 collector config/runner/DPAPI 해시와 source archive/state 바이트를 모두 보존했다. 키/네트워크를 사용하지 않았다.
- 실제 source는0행이었다. 초기 capture 두 번으로 seq1/2·두 세대를 만들고 preview의 archive/state/backup/config 네 파일 해시 불변을 확인했다. 최신 세대를 새 SPOL/SPJC 파일로 복원해 행·initial/cursor·새 inode binding을 대조했고 backup 파일 해시도 보존했다. 이 검증 사본2개는 identity/소유 형식을 확인해 삭제했다. 양수6종/만료 행 검증은39개 fixture 테스트 근거이며 실제0행 결과와 섞지 않는다.
- `SpotON-OperationLogs-Backup`을 새 Disabled 상태로 등록하고 XML/CIM의 Interactive/Limited·PT5M/무기한·IgnoreNew·PT2M·배터리 허용/깨우기off·Task XML 키/대상 ID 부재를 확인한 후 활성화했다. 기존 collector Task action은 바꾸지 않았다. 콘솔 없는 pythonw로13:10:17Z 시작,13:10:18.768304Z seq3 갱신·종료0을 관찰했다.
- 추가 수동 시작 없이 원래 시간 트리거13:12:00Z에서 seq4/captured_at=13:12:00.376481Z로 갱신됐다. Native COM 두 작업 모두Ready/LastTaskResult0, 백업 다음 예정13:17:00Z·수집 다음 예정13:14:38Z다. 실제 두 세대0행·expired0·latest_rows/bytes0·near_capture_limit=false·source origin 일치, 새 파일3종의 현재 사용자/SYSTEM ACL·runtime SHA를 다시 확인했다. 이 관찰로 실제 GUI 실행과 시간 트리거/백업 갱신을 확인했다.
- 같은 PC/디스크의 시범이다. 관찰 유입0행으로 미래30일 최대량을 산정할 수 없으며100,000행/64MiB 적정성 전체를 입증하지 않는다. captured_at 신선도와 최신 snapshot 상한 지표/Task 실패를 감시한다. 오프호스트 DR·재부팅/로그오프 복구·실제30일 보관·실제 만료 발생을 완료로 주장하지 않는다. 추가 Claude 재검수 제한은6.5를 따른다.
