# 운영 로그 작업 재개·만료 삭제 실행기 (#162)

- 기준 develop `2622133`, 2026-11-15. [이슈 #162](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/162).
- `python -m etl.operation_logs.job`의 init/run 명령을 추가한다. 기존 [보관기](feat158-operation-log-retention.md)와 [Render 전달기](feat160-render-log-adapter.md)를 재사용한다. BE 전용이며 FE/API/PG0012/원본/.env/기존 서버/Render 설정·요금제·OS 스케줄 등록은 바꾸지 않는다.

## 1. 범위와 의미

이 단계는 스케줄러가 호출할 수 있는 단발 실행기와 중단 재개 상태를 구현한다. 영구 저장소/24시간 실행 환경 선택·인증 주입·스케줄 설치·실제30일 연속 보관/백업 만료 검증은 완료하지 않는다. 기본 dry-run은 로컬 읽기 전용 계획만 제공하고 Render GET도 하지 않는다. 이는 GET을 수행하는 기존 render CLI의 dry-run과 다르다.

checkpoint는 API 페이지가 모두 처리되고 허용 이벤트가 보관기에 commit된 구간 끝이다. 전달 누락 없음이나 앱 발행 인증은 뜻하지 않으며 `coverage_verified=false`를 유지한다. 원천 보관 이전 소실·같은ns100행 경계·늦은 로그·canonical 충돌 등 기존 한계도 유지한다. 이전 결정을 뒤집어 매출·상권변화 pending을 활성화하지 않는다.

## 2. 두 파일의 소유권과 초기화

- 기존 archive 파일은 #158 형식 그대로 사용한다(추가 테이블/버전 변경 없음). 별도 제어 SQLite는 다른 application_id·정확한 job_state 테이블·user_version1로 식별한다. 두 경로는 서로 달라야 하고 하드링크도 허용하지 않는다.
- 기존 archive의 경로 안전성 검사를 부작용 없는 `validate_file_path`로 분리한다. 기존 validate_target은 그 뒤 기존 헤더 검사를 그대로 수행한다. 헤더 검사는 별도 고정 application_id를 받을 수 있게 하되 기존 호출의 기본값/동작은 보존한다. 네트워크/기존 API에서 이 값을 받지 않는다.
- 제어 파일에도 절대 로컬 경로·저장소 밖·일반 파일·비링크/비junction·부속 파일 거절·SQLite 열기 전100바이트 헤더/identity·정확한 schema·trusted_schema OFF·mode=ro/rw·1초 잠금 제한을 적용한다. 제어 파일 최대1MiB, 테이블은 singleton 한 행이다. 새 파일은 명시적 init --execute에서만 O_EXCL로 생성한다. 기존 파일 덮어쓰기/자동 복구/자동 init은 없다.
- `init --db --state --owner-id --service-id --start [--execute]`: 별도 archive가 이미 있어야 한다. start는 UTC·현재 기준30일 이내·5분 지연 이전의 명시 시각이다. 최초 cursor=start. start/기준 규칙·owner/service·archive의 정규 경로와 file identity를 SHA256 binding으로 묶고 제어 파일에는 hash/정수 시각/고정 규칙만 저장한다. 경로·키·owner 원문은 저장/출력하지 않는다.
- `run --db --state --owner-id --service-id [--execute]`: 저장 binding을 대조한다. archive 교체/복원·다른 서비스·규칙 불일치는 fail-closed이며 자동 rebind/reset/최신 파일 선택은 없다. 복원/교체 시 운영자가 확인 후 새 state와 명시 start로 다시 준비한다.

## 3. 계획·중첩·잠금

- UTC now는 실행 시작에 고정한다. 안정 끝점은 now-5분을5분 경계로 내림한다. 한 실행은 새 구간 최대6개, 각 cursor 전진5분이다. 요청 시작은 max(initial,cursor-2분), 끝은 min(cursor+5분,안정 끝점)으로 중첩한다. 마지막 짧은 구간도 허용한다. 각 요청은7분 이내여서 기존1시간 상한보다 작다.
- 새 구간이 없고 cursor>initial이면 마지막2분을1회 재조회하며 cursor는 그대로다. 초기 시각==안정 끝점이면 수집0건의 idle 계획이다. cursor가 안정 끝점보다 미래면 clock_behind_checkpoint로 실패하고 cursor를 뒤로 옮기지 않는다.
- dry-run은 제어 snapshot을 읽고 닫은 뒤 archive 만료 예정 수와 구간 계획만 읽는다. credential/GET/파일 생성·변경·쓰기 잠금 없음. 계획은 동시 실행과 시각 진행에 따라 달라질 수 있다.
- execute는 제어 파일 BEGIN IMMEDIATE를 유지해 같은 작업의 동시 실행을 막는다. 다른 실행은1초 대기 후 state_busy로 실패하며 잠금 강탈/임의 만료/자동 재시도는 없다. 프로세스 종료 시 SQLite 잠금 해제를 따른다. 전체 여러 구간 동안 잠금이 유지되므로 엄격한 총 실행시간은 보장하지 않으며 각 Render 호출의 기존 상한을 따른다.
- (Claude 검토 R1) 잠금 유지 중에는 제어 파일에 **쓰지 않는다**. BEGIN IMMEDIATE는 RESERVED 잠금만 잡고 rollback journal을 만들지 않으므로, 진행 cursor는 메모리(`proposed_until`)에만 두고 마지막에 singleton UPDATE(rowcount==1 확인) 1회+COMMIT만 수행한다. 이렇게 해야 장시간 네트워크 중 강제 종료가 hot `-journal`을 남기지 않는다. 그래도 commit 순간의 crash로 `-journal`이 남으면 기존 경로 검사처럼 열기 전에 거절하되 state_busy와 구분된 고정 오류(`state_journal_present`)로 보고하고 자동 복구/삭제는 하지 않는다. 운영 절차: 실행 중지 확인→두 파일 백업→새 state를 이전 cursor 이하의 명시 start로 init(재조회는 중복 방지로 안전).
- (R2) 제어 연결은 1초 timeout의 잠금 실패(`database is locked`)를 state_busy로 매핑한다. 잠금 순서는 항상 제어→archive이고 archive 연산은 제어 잠금을 잡지 않으므로 순환 대기는 없다. 같은 archive를 다른 state(다른 서비스)가 공유하면 archive 잠금 경합으로 해당 구간이 database_busy 실패할 수 있으며 이는 아래 부분 checkpoint 규칙으로 재개한다(공유를 막지는 않되 문서화).

## 4. 저장 순서·중단·삭제

1. 제어 소유권/대상 binding·시각을 검사한다. owner/service 형식도 render의 OWNER/SERVICE 정규식으로 **prune 전에** 검사한다(R3: run_window 안의 ArgumentsError가 삭제 이후 exit2로 나오지 않게). 잘못되면 쓰기 없이 사용법2.
2. archive.prune(path, now_fixed, execute=True)을 먼저 실행한다. 인증 누락/Render 오류가 뒤에 나더라도 이미 완료한 만료 삭제는 유지한다. 잘못된 대상/binding 상태에서는 삭제하지 않는다. (R4) prune 자체가 실패(database_busy/ownership/counts 등)하면 네트워크·구간 수집 없이 즉시 실패하고 checkpoint를 바꾸지 않는다.
3. 각 계획 구간마다 먼저 archive의 현재 (st_dev,st_ino)가 binding과 같은지 재확인한 뒤(R5: 실행 중 교체 시 다른 파일에 저장하고 원래 파일의 checkpoint를 진전시키는 것을 막음) 기존 render.run_window(execute=True)로 끝까지 조회/검증·archive commit한다. 그 다음에만 메모리 `proposed_until`을 그 구간 끝으로 진전한다. 제어 commit 직전에도 같은 identity를 다시 확인한다. (완전한 TOCTOU 제거는 아님)
4. 모든 구간 성공 후 제어 transaction을 commit한다. (R6, 진행성) 원격/archive 구간 오류(RenderLogError·api_network·archive database_busy 등)로 k≥1개 구간 뒤 멈추면, 연속 성공한 마지막 구간 끝까지만 checkpoint를 commit하고 status=failed·checkpoint_committed=true로 보고한다. 전체 rollback만 하면 매번 같은 구간(예: 반복 429/row_limit)에서 실패할 때 앞 구간도 영원히 재조회만 하고 진전이 0이 되기 때문이다. archive commit 후에만 진전하므로 at-least-once 순서는 그대로다. 반면 binding/identity 불일치·시계 오류·KeyboardInterrupt(중단 시 추가 I/O 금지)·제어 commit 실패에는 제어를 rollback한다. 이미 commit된 archive 구간과 prune은 rollback하지 않는다. 다음 실행은 확정 cursor부터 재조회하며 canonical 중복 방지로 안전하게 재개한다. 같은 구간이 계속 실패하는 정체는 자동 건너뛰기 없이 고정 오류와 `failed_window_start`(시각)로 보고해 운영자가 판단한다.

이는 두 파일의 원자적 transaction이 아니라 저장 우선·checkpoint 후의 at-least-once 방식이다. crash가 어느 지점이든 checkpoint가 archive보다 먼저 진전하지 않는다. 결과에 successful_windows/inserted/duplicate/prune_deleted와 checkpoint_committed를 별도로 기록한다. 실패해도 일부 archive 저장/삭제가 끝났을 수 있으므로 "전체 무변경"으로 표시하지 않는다. `last_confirmed_until`는 commit 후만 갱신하고 실패 시 이전 값, `proposed_until`은 성공한 미확정 구간을 구분한다.

(R7, 지연 보고) 한 실행은 최대30분만 진전하므로 호출 주기가 이보다 길거나 실패가 누적되면 backlog가 커진다. 결과에 `lag_seconds_after`(안정 끝점−확정 cursor)와 `remaining_windows`를 추가한다. Render 측 로그 보존 기간(플랜별, 이 문서에서 미확인)을 넘긴 구간은 빈 페이지로 성공해 조용한 공백이 될 수 있으므로 coverage_verified=false를 유지하고 lag 보고로 운영자가 감지하게 한다. 확정 cursor가 now-30일 이하이면 수집 내용이 모두 만료 거절되므로 `checkpoint_expired`로 실패하고 자동 건너뛰기 없이 새 state 명시 init을 요구한다.

(R8, 시각 일관성) prune과 계획은 실행 시작의 고정 now를 쓴다. run_window 내부 ingest는 자체 현재 시각으로 만료/미래를 판정하므로 30일 경계에서 수 초 차이가 있을 수 있음을 한계로 기록한다(기존 archive/render 프로토콜은 바꾸지 않는다). cursor는 정수 ns로 저장하고 run_window에 넘기는 문자열은 `YYYY-MM-DDTHH:MM:SS[.fffffffff]Z`로 만들어 render.nanoseconds 왕복이 정확히 일치함을 테스트한다. init start는 render.nanoseconds가 받는 UTC 표기(`Z` 또는 `+00:00`, 소수 0~9자리)만 받는다(Claude 구현 검토 A3: 실제 코드에 맞춰 정정).

30일 경과는 만료 조건이며 실제 삭제는 다음 성공한 prune이다. 실행기 실패/잠금/호스트 중단과 백업/원천 복사본은 여전히 별도 운영 관리가 필요하다. 자동 연속30일 보관/정시 소거를 보장하지 않는다.

## 5. CLI·검증·커밋

키는 프로세스 RENDER_API_KEY/메모리 SecretStr만 사용한다. 초기화/계획에는 필요 없다. stdout JSON1줄·고정 오류·카운트/검증 시각만 출력하고 원문/키/경로/owner/라벨을 출력하지 않는다. 성공0/실패1/사용법2/중단130. 실행기 자신의 로그를 수집 입력에 다시 넣지 않는다.

검증: 계획(지연/중첩/6개상한/idle/재조회/시계역행), init/dry-run 바이트 보존, 다른 파일/schema/헤더/링크/하드링크·서비스/교체 binding, 실제 파일의 성공/중간 실패/중단/commit 실패 후 재개·중복, 원격 오류 전 prune 반영, 두 프로세스 state 잠금, 출력 비노출을 검사한다. 기존 archive/render 회귀·전체 일반/정적·Windows/Linux 타입·CI 격리 PostGIS/CodeQL을 따른다. 실제 GET과 쓰기는 새 검증용 두 파일에만 하고 검증 후 복사본을 정리한다.

절차: 이슈/브랜치 → Codex MD → 실제 Claude MD Read/Edit → Codex 구현/기능+테스트 커밋 → 실제 검증·문서 커밋 → CI/develop PR 정상 Squash. main/수동 브랜치 삭제/실제 OS 스케줄러 설치는 하지 않는다.

## 6. Claude 검토·검증 기록

Codex 구현 대조: 진행은 메모리로만 추적하고 최종 UPDATE/COMMIT을1회 수행한다. 일반 Render 오류/네트워크/검증 가능한 archive busy는 성공 prefix를 확정하지만, binding·기타 archive 오류/DB 장애·중단에는 제어를 rollback한다. 최종 대상 재검증이 실패하면 prefix도 확정하지 않는다. `last_confirmed_until`이 기존 cursor_after의 확정 의미를 표현하며 실패 구간은 failed_window_start로 분리한다. expired checkpoint는 잘못된 대상/시계 검사 후 prune을 수행하고 수집 전에 실패한다. init start는 정확히30일인 만료점도 거절한다. hot journal의 자동 복구는 기존 보관기처럼 범위 밖이며 state_journal_present는 별도 점검을 요구한다. 제어 write는 마지막에만 있어 네트워크 중 프로세스 강제 종료 시 제어 파일 불변·OS 잠금 해제·중복 재개를 실제 프로세스로 검사한다.

Claude는 이 MD만 Read/Edit한다. 다른 파일·Git/DB/네트워크/MCP/서브에이전트 금지. 제공된 소스와 집계만 검토하며 실행한 것으로 쓰지 않는다. 판정/이유/차단과 보류를 직접 기록한다. Codex가 수정본과 실제 코드를 최종 대조한다.

### 6.1 Claude 설계 검토 (2026-11-15, 이 MD Read/Edit만 수행, 실행 없음)

판정: **REVISE → 위 반영 후 구현 진행 가능**(차단 결함은 아래 R1·R6를 본문에 반영해 해소). 검토 근거는 제공된 archive.py/render.py 소스와 이 MD뿐이며 테스트·명령을 실행하지 않았다.

확인된 적정 사항:
- 저장 순서: run_window가 archive.ingest(자체 BEGIN IMMEDIATE→commit) 완료 후 반환하고, 그 뒤에만 cursor를 진전하므로 checkpoint가 archive보다 앞서지 않는다. 제어 commit 실패 시 재조회는 event_hash PRIMARY KEY + INSERT OR IGNORE로 duplicate 집계되어 안전하다.
- 구간: 요청 최대7분은 validate_window의1시간 상한·hi≤now(안정 끝점이 now-5분 이하) 조건을 만족한다. 중첩 경계의 중복은 collect의 포함 경계(lo≤ts≤hi)와 dedupe로 흡수된다.
- dry-run: prune(execute=False)는 mode=ro·deferred BEGIN이고 키/GET이 없어 파일 바이트를 바꾸지 않는다. 잠금 순서 제어→archive로 교착이 없다.
- 기존 archive/render 프로토콜·스키마·application_id 기본값은 변경하지 않는다(헤더 검사 매개변수화는 기본값 보존 조건).

반영한 수정(본문 R 표기):
- R1(차단): 원안은 "각 구간 후 제어 cursor 갱신"이라 장시간 열린 쓰기 transaction이 hot `-journal`을 만들고, crash 후 기존 경로 검사가 `-journal`을 거절해 영구 정지할 수 있었다. 메모리 진행+최종 1회 UPDATE/COMMIT과 별도 고정 오류·수동 절차로 바꿨다.
- R6(차단, 진행성): 중간 실패 시 전체 rollback은 반복 실패 구간에서 진전 0의 영구 정체를 만든다. 원격/구간 오류에는 연속 성공분까지 부분 checkpoint, 무결성/중단 오류에는 rollback으로 구분했다.
- R3·R4·R5: prune 전 인자 검증, prune 실패 시 네트워크 금지, 구간별·commit 전 archive identity 재확인.
- R2·R7·R8: 잠금 오류 매핑/archive 공유, lag·만료 cursor 보고, 고정 now·ns 왕복 형식.

추가 권고(비차단, Codex 판단):
- binding SHA256 입력은 도메인 접두사+길이 접두 필드로 인코딩해 필드 경계 모호성을 없앤다. 두 파일 구분은 문자열이 아니라 (st_dev,st_ino) 비교와 st_nlink==1로 한다(Windows Python의 st_nlink 제공 여부를 테스트로 확인).
- dry-run 출력에 cursor_before/lag를 넣어 R1 수동 절차의 이전 cursor 확인에 쓴다(경로·owner는 계속 비출력).
- 테스트 추가: 잠금 유지 중 제어 파일에 `-journal`이 생기지 않음, 부분 checkpoint(k번째 구간 429), prune 실패 시 GET0, 구간 사이 archive 교체 시 commit 거절, 30일 초과 cursor 거절.

보류(이번 범위 밖, 기존 결정 유지): OS 스케줄 설치·영구 저장소·Render 보존 기간 확인·실제30일 연속 보관/백업 만료 검증·coverage 검증.

### 6.2 Codex 실제 구현 검증 (2026-11-15)

- 새 작업 테스트34개 통과. 실제 자식 프로세스 강제 종료 후 제어 파일/저널 불변·중복 재개, 다른 프로세스 잠금, 제어 commit 실패 rollback, 원격 오류의 성공 prefix 확정, prune 실패 후 GET0, 파일 교체/하드링크/다른 형식 거절과 ns/30일 경계를 포함한다.
- Windows 일반 전체2138통과·기존 symlink 권한1skip·PostGIS298분리,36.46초. 기존 Starlette httpx 경고1개. ruff check와420파일 format 검사, Windows/Linux mypy190파일, diff whitespace 검사 통과. Linux/PostGIS/CodeQL은 PR CI 결과로 별도 확정한다.
- 실제 Render GET을 새 검증 archive/state에 연결했다. 미리보기는 네트워크 없이 두 파일 SHA256을 보존했다. 3구간523 API행 중377삽입·146중복·메시지 거절0, 확정 끝점은2026-11-15T11:15:00.000000000Z, 지연0이다. 같은 기준 시각의 tail 재조회108행은 전부 중복·추가0·checkpoint 변경 없음이다. 검증 파일은 운영 저장소가 아니며 검수 후 정리한다. 원본 제공자 로그/키/owner/라벨은 문서에 저장하지 않는다.
- 기존 Render Free·자동 배포off를 확인했고 환경·서비스 설정·원본/운영 DB·FE는 변경하지 않았다. 원본 로그 전체 누락 검증이나30일 실제 운영을 완료한 것으로 해석하지 않는다.

수동 재초기화 유의: hot journal의 이전 확정 cursor가30일 이내라면 그 이하에서 재조회한다. 이미 만료된 cursor라면 해당 과거 구간을 자동 복구할 수 없으므로 보존 범위 안의 새 start와 과거 공백을 명시적으로 정하고 새 state를 만든다. 자동 건너뛰기는 구현하지 않는다.

### 6.3 Claude 구현 검토 (2026-11-15, 이 MD Read/Edit만 수행, 실행 없음)

판정: **PASS (차단 결함0)**. 근거는 제공된 archive.py/render.py/job_state.py/job.py/테스트 소스와 6.2의 Codex 실행 집계뿐이며, Claude는 테스트·명령·네트워크·DB를 실행하지 않았다. 6.2의 수치는 Codex 보고를 옮긴 것이고 Claude가 재현한 값이 아니다.

설계 대비 확인(R1~R8):
- 크래시 일관성(R1): `job_state.connect(write=True)`는 BEGIN IMMEDIATE(RESERVED)만 잡고, 구간 루프 동안 제어 파일에 쓰지 않는다. 진행은 지역 `cursor`/`proposed_until`에만 있고, 마지막에 `save`(binding·이전 cursor 조건부 UPDATE, rowcount==1)+`c.commit()` 1회다. `run_window`는 `archive.ingest`의 자체 commit이 끝난 뒤 반환하므로 checkpoint가 archive보다 앞서지 않는다. 제어 commit 실패 시 `connect`의 finally rollback으로 이전 cursor가 남고, 재조회는 event_hash PK + INSERT OR IGNORE로 duplicate 처리된다(`test_commit_failure_*`, `test_abrupt_exit_*`가 이 경로를 다룬다).
- 부분 진행(R6): RenderLogError·httpx.RequestError·archive `database_busy`/SQLite busy(5,6)만 break해서 성공 prefix를 확정한다. 다른 ArchiveError·sqlite 오류·`collector_contract`·KeyboardInterrupt·Exception은 전파되어 rollback된다. prefix 확정 전 `_check`를 다시 해서, 실패하면 prefix도 확정하지 않는다. 설계·6절 Codex 설명과 같다.
- R3/R4: `ids()`가 prune 전에 owner/service를 검사한다. `_check`(binding) → `plan`(시계 역행) → prune 순서이고, prune 예외는 수집 전에 전파된다(`test_prune_failure_prevents_fetch`).
- R5: 각 구간 전과 commit 직전에 `_check`가 경로·(st_dev,st_ino)·nlink를 포함한 binding 전체를 재계산한다. 6.1 권고의 "길이 접두 인코딩"은 `sort_keys` JSON 직렬화로 대체되었고 필드 경계 모호성이 없어 충분하다.
- R7/R8: `lag_seconds_after`/`remaining_windows`, `checkpoint_expired`(prune 뒤, 수집 전), `stamp()`의 9자리 소수+`Z`와 `nanoseconds` 왕복 테스트가 있다.
- dry-run: 제어는 mode=ro로 읽고 닫은 뒤 `prune(execute=False)`(mode=ro)와 계획만 수행한다. 키·`run_window`·파일 생성이 없다(`test_init_and_preview_*`가 바이트 보존을 확인). 
- 비밀/출력: 제어 파일에는 binding hash·정수 ns만 저장하고, Result에는 고정 사유·카운트·시각만 들어간다. 키는 env→SecretStr로만 `run_window`에 전달된다.
- 기존 프로토콜: archive 스키마·APPLICATION_ID·`validate_target` 동작은 그대로이고, `_header`의 `application_id` 기본값도 유지된다. render는 변경되지 않았다.

비차단 권고(Codex 판단, 수정 여부는 구현자 결정):
- A1: `render.run_window` 안의 `validate_window`는 실제 현재 시각으로 `hi<=now`를 검사한다. 실행 중 벽시계가 5분 넘게 뒤로 가면 prune 이후 ArgumentsError가 날 수 있다. 이 예외는 `run_once`에서 다시 raise되어 `main`이 exit2 `arguments`와 새 Result를 출력하므로, prune/archive 부분 효과 보고와 성공 prefix가 사라진다(데이터 안전성은 유지: rollback+재조회). 수집 루프에서 ArgumentsError를 고정 오류(예: `collector_window`)로 바꾸고 rollback하면 R3의 의도(삭제 뒤 exit2 금지)를 완전히 충족한다.
- A2: 다른 실행이 정상 commit하는 짧은 순간에 생긴 `-journal`도 `state_journal_present`로 보고된다(일시적 경합). 운영 절차는 "먼저 실행 중지 확인 후 재실행하고, 계속 남을 때만 수동 재초기화"로 읽어야 한다. 참고로 진짜 hot journal은 SQLite 자체 rollback으로 이전 cursor가 복구되어 안전 방향이다. 거절은 보수적 선택으로 유지 가능하다.
- A3: init start 허용 형식이 본문 서술(`Z`만)보다 넓었다. 본문 R8을 실제 동작으로 정정했다.
- A4: dry-run의 `prune_completed=true`는 "만료 예정 수 계산 완료"를 뜻하고 삭제가 아니다(`prune_deleted=0`, `effects_may_be_partial=false`). README/출력 설명에 명시하는 것을 권한다.
- A5: checkpoint commit은 EXCLUSIVE가 필요하다. 그 순간 동시 dry-run이 SHARED를 잡고 있으면 1초 뒤 `state_busy`가 되고 prefix가 기록되지 않을 수 있다. 재조회로 안전하지만 한계로 기록한다.
- A6: binding에 정규 경로가 들어가므로 archive 디렉터리 이동/드라이브 문자 변경도 `binding_mismatch`가 된다(의도된 fail-closed). 운영 절차 문서에 함께 적는다.
- A7: prefix 확정 직전 `_check` 실패 시 원래 원격 오류 사유가 `binding_mismatch`로 덮인다. 진단용으로 원래 사유를 별도 필드에 남기는 것을 고려한다.
- A8: `test_state_lock_is_released_after_process_exit`는 실제로 "보유 중 다른 프로세스가 state_busy"를 검사한다. 종료 후 해제는 `test_abrupt_exit_*`가 보여 주므로 테스트 이름만 정정하면 된다.

보류(범위 밖, 6.1 유지): OS 스케줄 설치·영구 저장소·Render 측 보존 기간 확인·실제30일 연속 보관/백업 만료·coverage 검증. 이 검토는 구현 PASS이며 운영 적용 완료를 뜻하지 않는다.

### 6.4 Codex 최종 대조·권고 반영

- A1을 반영했다. 수집 중 ArgumentsError는 `collector_window`라는 런타임 실패로 변환해 제어를 rollback하고, 이미 완료한 prune/삽입·확정 전 진행과 부분 효과를 Result에 보존한다. 기존 사전 인자 오류의 exit2는 유지한다. 실제 파일 테스트에서 만료 삭제1·첫 구간 저장1 후 두 번째 구간 오류를 주입해 확정 cursor 불변/부분 효과 보고를 확인했다.
- A2/A4/A5/A6는 README에 명시했다. 일시적 journal은 다른 실행 종료 후 재시도하고 지속할 때만 수동 점검한다. dry-run prune_completed는 삭제 예정 계산이며 삭제가 아니다. 동시 읽기가 commit을 지연시킬 수 있고 경로 이동도 binding 불일치다. A8의 테스트 이름은 실제 잠금 경합 의미로 정정했다.
- A7은 새 진단 필드를 추가하지 않는다. 마지막 대상 불일치가 발생하면 무결성 오류를 최종 사유로 우선하며 원격 오류가 있었더라도 checkpoint를 확정하지 않는다. 실패 구간/진행 카운트는 유지된다.
- 최종 전체 일반 테스트는2139통과·기존Windows symlink1skip·PostGIS298분리,36.72초다(새 작업 테스트35개). ruff check/420파일 format·두 플랫폼 mypy190파일·diff 검사도 다시 통과했다. 6.2는 보완 전 결과이며 이 항목이 최종 로컬 결과다.
- 실검증용 archive/state 두 파일만 소유권·identity·377행과 확정 시각을 확인해 제거했다. 원문 없는 집계/검수 기록만 비공개 보관하며 운영 저장소를 생성하지 않았다. 실제 GET 결과는6.2와 같고 보완 후 원격 재호출은 필요하지 않았다.

### 6.5 Claude 최종 재검토 (2026-11-15, 이 MD Read/Edit만 수행, 실행 없음)

판정: **PASS (차단 결함 0)**. 근거는 제공된 최종 archive.py/render.py/job_state.py/job.py/테스트 소스와 Codex 실행 집계(6.2·6.4, SAFE LIVE SUMMARY)다. Claude는 테스트·명령·네트워크·DB·Git을 실행하지 않았으므로 수치는 Codex가 보고한 값이다.

재확인 항목:
- 크래시 일관성: 제어 쓰기는 루프 뒤 `save`+`commit` 1회뿐이다. 각 구간은 `archive.ingest`의 자체 commit 뒤에만 메모리 cursor를 진전하므로 checkpoint가 archive보다 앞서지 않는다. 제어 commit 실패, 중단, 무결성/기타 오류는 `connect` finally에서 rollback되고, 재조회는 event_hash PK+INSERT OR IGNORE로 duplicate가 된다. 자식 프로세스 강제 종료 테스트가 제어 파일 바이트 불변과 `-journal` 부재를 검사한다.
- A1 반영: 루프 안 ArgumentsError는 `collector_window`(JobError)로 바뀌어 rollback된다. prune/삽입 카운트, `effects_may_be_partial=true`, 이전 `last_confirmed_until`이 Result에 남는다. 사전 `ids()` 오류만 exit2이고 효과가 없다. R3를 충족한다.
- 성공 prefix: 원격(RenderLogError·RequestError)과 archive busy만 break한다. 재검증 `_check`를 통과해야 확정하며, `last_confirmed_until`/`lag`는 commit 후에만 갱신된다. live 집계(3구간 523행·377삽입·146중복, tail 108 전부 중복·checkpoint 불변)는 설계된 at-least-once·중첩 동작과 맞는다.
- 구간/지연: 안정 끝점 5분 내림, 전진 5분×최대6, 2분 중첩, 요청 ≤7분(<1시간 상한), idle/tail 재조회, 시계 역행 거절, `checkpoint_expired`(prune 뒤·수집 전)가 코드와 본문에서 같다.
- 독립 prune: 대상/binding/시계 검사 뒤 수집 전에 실행되고, 키 누락이나 원격 오류가 뒤따라도 삭제가 유지된다. prune 실패 시 GET은 0이다.
- 잠금/파일: 제어→archive 단방향 순서로 교착이 없다. 제어 파일은 별도 application_id, 정확한 schema, journal_mode=delete, 1MiB 상한, nlink==1, 부속 파일 거절, O_EXCL init을 따른다. binding은 정규 경로·(dev,ino)·owner/service·규칙을 sort_keys JSON SHA256으로 묶고 원문은 저장하지 않는다.
- dry-run: 제어 mode=ro로 읽고 닫은 뒤 archive prune(execute=False, mode=ro)와 계획만 실행한다. 키 사용, `run_window`, 파일 생성/변경이 없으며 live 미리보기에서도 두 파일 해시가 보존됐다.
- 비밀/출력: Result에는 고정 사유·카운트·UTC 시각만 들어간다. 키는 env→SecretStr→`run_window` 경로뿐이다. archive 형식/APPLICATION_ID/`validate_target` 동작과 render 프로토콜은 변경되지 않았다.

비차단 관찰(수정 여부는 Codex 판단, 현재 동작은 모두 안전 방향):
- B1: 루프 안 구간 전 `_check`와 루프 뒤 `_check`는 try 밖에 있다. 같은 archive를 공유하는 다른 작업의 일시적 `-journal` 때문에 `validate_target`이 `database_busy`를 내면 prefix를 확정하지 않고 전체 rollback한다(R2/R6의 "busy는 prefix 확정"보다 보수적). 데이터는 안전하고 재조회된다. archive 공유를 피하라는 README 권고면 충분하다.
- B2: prune은 고정 now 기준 30일 만료이므로, 벽시계가 크게 **앞으로** 틀리면 되돌릴 수 없는 삭제가 먼저 일어날 수 있다(그 뒤 `checkpoint_expired`). 이는 기존 archive prune CLI와 같은 성질이며 이번 범위에서 프로토콜을 바꾸지 않는다. 운영 전제(NTP 등 시계 동기화)로 README·운영 절차에 명시할 것을 권한다.
- B3: 한 실행의 최대 전진은 30분이다. 호출 주기가 이보다 길거나 실패가 반복되면 lag가 줄지 않고, 결국 `checkpoint_expired`가 된다. lag/remaining_windows 보고로 감지할 수 있으나, 후속 스케줄 설계에서 호출 주기를 30분보다 충분히 짧게 정하라고 기록해 두면 좋다.
- B4: `c.commit()` 성공 직후, `checkpoint_committed=True` 대입 전에 KeyboardInterrupt가 오면 실제로는 확정됐는데 보고는 미확정이 된다. 재실행은 확정 cursor부터 진행하므로 안전하며 보고상 한계로만 남긴다.

보류(범위 밖, 6.1/6.3 유지): OS 스케줄 설치, 영구 저장소, Render 보존 기간 확인, 실제 30일 연속 보관/백업 만료, coverage 검증. 이 PASS는 구현 검수 결과이며 운영 적용 완료를 뜻하지 않는다.
