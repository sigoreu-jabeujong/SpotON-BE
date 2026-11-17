# Windows 로그 시범 운영 연결 (#164)

- 기준 develop `b30cf21`, 2026-11-15. [이슈 #164](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/164).
- 이전 [단발 작업](feat162-operation-log-job.md)의 후속이다. 사용자 다음 단계 지시에 따라 현재 PC에 전용 로컬 보관소와5분 주기 작업을 연결한다. FE/API/PG0012/원본 DB/.env/기존 서버/Render Free·자동배포off는 보존한다. 유료 서비스와 신규 외부 계정은 만들지 않는다.

## 1. 범위·운영 전제

현재 PC에서 비상시 시범 운영을 시작한다. C:의 별도 저장소는 프로세스/재부팅 이후 유지되지만 장비 장애·삭제·디스크 부족을 견디는 원격 영구 저장소나24시간 실행 환경은 아니다. 현재 사용자 로그인·PC 전원·네트워크가 필요하며 절전 해제/시스템 전원 정책/관리자 권한은 변경하지 않는다. 정상 상태의 호출 간격은5분, 실행 중 겹치는 호출은 건너뛴다. 누적 지연과 상태를 확인하며30일 실제 운영·전체 백업 만료·공급자 전체 누락 검증을 완료로 표시하지 않는다.

Render Free 웹은 지속 디스크를 붙일 수 없고 cron도 지속 디스크를 사용할 수 없어 기존 SQLite를 해당 서비스에 그대로 배치하지 않는다. 공식 로그 보관은 workspace 플랜에 따라 Hobby7일/Pro14일/Scale·Enterprise30일이다. 서비스 인스턴스의 Free와 workspace 플랜은 다른 개념이며 현재 workspace 플랜은 아직 실제 API로 확인하지 않았으므로7일을 운영 보수 기준으로 삼는다. 긴 중단 후 빈 API 응답은 과거 로그0을 증명하지 않는다.

근거: [Render Free](https://render.com/docs/free), [cron](https://render.com/docs/cronjobs), [로그 보관](https://render.com/docs/logging), [Microsoft Task Principal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal), [ProtectedData](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata).

## 2. 저장소·실행 소스·인증

- 저장소 밖의 새 로컬 폴더 `C:\Users\horim\SpotON-operation-logs`를 사용한다. 처음에는 부재를 확인하고 생성하며 기존 경로를 재사용/덮어쓰지 않는다. ACL 상속을 끊고 현재 사용자·SYSTEM만 허용한다. root와 부모는 비링크/비reparse·로컬 절대 경로여야 한다. 기존 백업 폴더/FE/BE.env를 비밀 저장소로 사용하지 않는다.
- `events.sqlite3`는 #158 형식, `job.sqlite3`는 #162 제어 형식이며 자동 덮어쓰기/복구는 없다. `job_state.binding()`이 archive 경로/inode를 읽으므로 **archive init(execute) → job init(execute)** 순서를 지킨다. 새 archive를 명시 init하고 start는 현재보다 약20분 전의 정확한 UTC로 고정해 최초 호출을 소량으로 제한한다. 과거 전체 backfill은 수행하지 않으며 시작 이전 공백을 명시한다.
- `runtime`은 검증된 `b30cf21`의 detached worktree다. 공유 개발 폴더의 최신 소스를 주기 작업이 임의 실행하지 않도록 한다. 기존 BE 가상환경 Python을 사용하며 실행 전 고정 commit·깨끗한 tracked/untracked 상태·lock 파일 해시를 확인한다. 공유 가상환경의 향후 변경은 운영 전제/한계이며 자체 독립 배포 환경 확보는 후속이다.
  - (Claude 검토 보완) runtime은 공유 `.git` 설정을 상속하므로 상태 검사 git 호출은 `git -c core.fsmonitor=false -c core.hooksPath=NUL --no-optional-locks -C <runtime> ...` 형태로 설정 기반 외부 프로그램 실행과 index 쓰기를 막는다. `git status --porcelain --untracked-files=all`만으로는 assume-unchanged/skip-worktree 파일 변경을 놓치므로 `git ls-files -v`에서 `h`/`S` 등 해당 표식이 없음을 함께 확인한다. HEAD는 `rev-parse HEAD`로 고정 commit과 정확히 비교한다.
  - (Claude 검토 보완) 공유 가상환경에 프로젝트 editable 설치가 있으면 `etl`이 다른 소스에서 import될 수 있다. `-m` 실행 시 작업 디렉터리(runtime)가 `sys.path[0]`이 되어 우선하지만, 구현 검증에서 자식이 import한 `etl.operation_logs.job`의 실제 파일이 runtime 아래임을 1회 확인해 기록한다.
- `config.json`에 고정 root/runtime/Python/git 경로·commit·lock/runner SHA256·대상 owner/service를 저장한다. 실제 값은 비공개 로컬 설정에만 둔다. config와 DPAPI 파일은 root의 제한 ACL을 상속한다.
- 기존 Render 키는 현재 인증 파일에서 메모리로만 읽고, 표준입력으로 별도 설정 프로세스에 넘겨 Windows DPAPI CurrentUser와 고정 용도 entropy로 암호화한 `render-key.dpapi`에 저장한다. 평문 파일/인자/환경 영구 등록/Task XML/문서/Git에는 쓰지 않는다. 복호화는 같은 Windows 사용자 문맥에서만 수행하며 메모리 문자열의 완전 소거는 보장하지 않는다.
  - DPAPI CurrentUser는 현재 사용자 문맥에 인증값을 묶어 저장하며 **같은 사용자로 실행되는 임의 프로세스**의 복호화는 막지 못한다. entropy는 용도 구분값이지 비밀이 아니다. 기존 Render 키의 권한 범위를 변경/축소하지 않는다. 노출 의심 시 기존 키를 폐기하고 작업을 정지한 뒤 새 blob으로 교체한다. 계정/장비 변경 등으로 복호화가 실패하면 아래 키 없음 경로로 처리한다. API 키 범위 조정의 가능성이나 오프라인 침해 방지 전체를 이번 근거만으로 확정하지 않는다(Codex 증거 한정).
  - (Claude 검토 보완) blob은 배타 생성(CreateNew)으로 쓰고 기존 파일을 덮지 않는다. 설정 프로세스 스크립트 본문에 키 리터럴이 없어야 하며(ScriptBlock 로깅/transcript 대비) 키를 담은 변수를 출력 스트림에 보내지 않는다.

## 3. BE 저장소 실행 wrapper

`ops/windows/run-operation-log-job.ps1 -ConfigPath <private-config> [-Execute]`를 추가한다. 기본은 preview다. 이 파일의 검증된 복사본만 제한 폴더에 배치하고 SHA256을 config에 고정한다. 설정/파일/ACL/소스 검사가 실패하면 고정 사유만 반환하고 대상 쓰기/네트워크는 하지 않는다.

실행 순서:
1. config/root와 모든 고정 파일 경로를 검사한다. 설정 크기를 제한하고 정확한 설정 필드·규칙 버전·owner/service 형식·commit/hash·현재 사용자 소유권·제한 ACL을 확인한다. root의 reparse/UNC/ADS 경로를 거절한다. wrapper 자체의 해시, runtime의 commit/상태/lock 해시를 검사한다.
   - (Claude 검토 보완) 경로는 `GetFullPath` 결과와 입력이 대소문자 무시로 정확히 같아야 하며 `\\?\`·`\\.\`·8.3 짧은 이름(`~`)·끝 점/공백·`:` 추가 사용을 거절한다. root부터 각 고정 파일까지 모든 경로 요소의 ReparsePoint 속성을 확인한다.
   - (Claude 검토 보완) ACL은 root뿐 아니라 config·DPAPI·wrapper 복사본·두 SQLite에 대해 **owner=현재 사용자 SID, 상속 차단(root), Allow ACE가 현재 사용자/SYSTEM뿐**임을 매 실행 확인한다. 파일 단위 명시 ACE 추가를 놓치지 않기 위함이다.
   - (Claude 검토 보완) wrapper 자체 해시 검사는 우발적 변경 탐지일 뿐 변조 방지가 아니다(변조자는 검사도 제거 가능). 실제 보호 경계는 root ACL과 같은 사용자 신뢰다.
2. preview는 키를 읽거나 복호화하지 않고 #162의 로컬 dry-run만 호출한다. execute만 DPAPI 복호화한다. DPAPI 파일 누락/실패는 빈 키로 단발 작업을 실행해, 이미 검증한 대상의 prune이 인증 실패로 생략되지 않게 한다. 현재 job은 빈 키에서 GET 없이 prune 후 configuration 실패한다. 설정/소유권 오류에서는 prune도 하지 않는다.
   - (Claude 검토 판단) 제공된 `job.py` 기준으로 execute 경로는 binding 검사 → `archive.prune(execute=True)` → checkpoint 만료 검사 → 창별 `render.run_window` 순서이고, `plan()`은 첫 전진 이후 항상 최소1개(중첩 재조회) 창을 만들므로 빈 키도 반드시 `run_window`에 도달한다. **`render.run_window`가 빈 키를 HTTP 전에 `RenderLogError`로 거절한다는 주장은 이번 검토에 제공된 소스로 확인할 수 없다.** 구현 검증에서 요청 수를 세는 transport(또는 네트워크 차단)로 빈 키 execute의 GET 0회·prune 완료·`status=failed`·checkpoint 미전진을 실제로 확인해야 이 경로를 채택한다. 확인되지 않으면 키 없음일 때 #158 prune CLI 직접 호출로 대체하되 binding 검사를 먼저 수행한다.
   - (Claude 검토 보완) 키 없음/복호화 실패는 child 결과와 별도로 wrapper 고정 사유 `credential_unavailable`을 함께 기록해 일반 configuration 실패와 구분한다.
   - (Claude 검토 보완) preview도 자식 환경의 `RENDER_API_KEY`를 빈 값으로 명시 덮어쓴다.
3. .NET ProcessStartInfo(UseShellExecute=false, CreateNoWindow=true)로 Python을 호출한다. 정확한 argv 경계를 보존하고 고정 작업 디렉터리에서 `-E -s -m etl.operation_logs.job run ...`을 실행한다. 키는 자식 프로세스 환경에만 주입하고 원래 세션 환경을 바꾸지 않는다. stdout/stderr를 캡처하며 원문을 그대로 출력/파일 저장하지 않는다. 약9분 타임아웃에는 자식 종료를 시도하고 고정 timeout 사유로 보고한다. hard kill 순간 journal은 기존 수동 점검 규칙을 따른다.
   - (Claude 검토 차단 해소) `ProcessStartInfo`는 기본적으로 부모 환경을 상속한다. 사용자 세션이나 상위 프로세스에 `RENDER_API_KEY`가 있으면 키 없음 경로가 의도와 달리 상속 키로 GET할 수 있으므로, preview/execute 모두 자식 `Environment["RENDER_API_KEY"]`를 명시 설정(execute 복호화 값 또는 빈 문자열)하고 상속값을 사용하지 않는다.
   - (Claude 검토 보완) stdout/stderr는 비동기로 동시에 읽어 파이프 버퍼 교착을 막고 각각 예: 64KiB 상한까지만 보관(초과분 폐기·`output_oversize` 고정 사유)한다. stdout은 정확히 JSON 한 줄이어야 한다.
   - (Claude 검토 보완) wrapper 타임아웃(약9분) < 작업 실행 상한(15분) < 반복 간격 누적 관계를 유지한다. Task Scheduler의 15분 종료는 PowerShell만 종료해 Python이 고아로 남을 수 있으므로 wrapper 타임아웃이 1차 방어다. ~~Python은 하위 프로세스를 만들지 않으므로 `Kill()` 단일 종료로 충분하다.~~ (Claude 구현 검토 정정) config의 Python은 Windows venv의 `Scripts\python.exe`이며, 이는 기본 인터프리터를 **자식 프로세스로 띄우는 redirector launcher**다. 따라서 `Process.Kill()`은 launcher만 종료하고 실제 Python은 남는다(.NET Framework/PowerShell 5.1에는 `Kill(true)`도 없다). 6.3의 R1에 따라 Job Object(`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) 또는 `%SystemRoot%\System32\taskkill.exe /PID <pid> /T /F`로 프로세스 트리를 종료한다. Job Object는 Task Scheduler가 PowerShell을 15분에 종료할 때도 handle 닫힘으로 자식 트리를 함께 정리하므로 우선 권장한다. (최종 채택: 6.4에 따라 taskkill 트리 종료만 구현했고 Job Object는 미채택이다. wrapper 자체가 강제 종료되는 경우의 고아 정리는 보장하지 않는다.)
4. 결과는 고정 wrapper 상태/사유·시각·확정 위치·정수 카운트·불리언만 whitelist로 재구성한다. child stderr와 임의 문자열/추가 필드는 버린다. 알려진 고정 child 오류만 전달하고 나머지는 job_failed로 바꾼다. execute만 `latest-result.json`을 같은 폴더의 새 임시 파일과 atomic replace로 갱신한다. preview는 결과 파일도 바꾸지 않는다. 무한 보고서/원문 로그/키 복사본은 만들지 않는다.
   - (Claude 검토 보완) child JSON은 `job.Result`의 정확한 키 집합과 타입(비음수 int·bool·`...Z` 9자리 시각 정규식·고정 enum)을 검사하고, 허용 오류 문자열은 구현 시 열거한 고정 집합으로 둔다. 종료코드(0/1/2/130)와 `status`가 모순되면 `job_failed`다. wrapper 종료코드도 고정 매핑해 `LastTaskResult`에 반영되도록 `-File` 실행과 명시 `exit`를 사용한다.
   - (Claude 검토 보완) Render 보관 보수 기준(7일) 대비 `lag_seconds_after`가 예: 6일을 넘으면 고정 플래그 `retention_risk=true`를 보고한다. 한 실행은 최대6창(30분)만 전진하므로 긴 중단 후 따라잡기는 실시간의 약6배 속도이고, 그 사이 공급자 측 만료로 생긴 공백은 탐지·복구할 수 없다.
   - (Claude 검토 보완) 임시 파일은 고정 접두어로 root 안에 만들고 실패 시 삭제를 시도한다. 수동 실행과 작업 실행이 겹쳐도 `job.sqlite3`는 `BEGIN IMMEDIATE`로 직렬화되어 한쪽이 `state_busy`로 끝난다.

## 4. OS 작업 연결

동명 작업/기존 목적 폴더가 있으면 중단하고 임의 인수/변경하지 않는다. 현재 사용자 Interactive·Limited(관리자 승격 없음), 숨김 PowerShell·프로필 없음·비대화형·기존 RemoteSigned 정책 유지로 등록한다. 비밀번호를 저장하지 않는다. 최초 미래 트리거와5분 반복, 현재 사용자 로그온 트리거, StartWhenAvailable, IgnoreNew, 최대15분 실행을 설정한다. 절전 깨우기는 끄며 배터리 전환에도 작업을 허용한다. 명시 `-Execute`와 비공개 config 경로만 Task XML에 넣고 키/owner/service는 넣지 않는다.

(Claude 검토 보완) Interactive 로그온은 DPAPI CurrentUser 복호화와 일치하는 선택이다. S4U("로그온 여부와 무관·암호 미저장")는 사용자 암호 기반 master key를 쓸 수 없어 DPAPI 복호화가 실패하므로 DPAPI 재설계 없이 전환하지 않는다. `-WindowStyle Hidden`이어도 콘솔 창이 순간 표시될 수 있으며 이는 알려진 사용성 한계다. `-ExecutionPolicy Bypass`를 쓰지 않으며, 복사본에 Zone.Identifier(MOTW)가 없어야 RemoteSigned에서 실행된다. 반복 지속 시간이 무기한인지와 배터리 관련 두 설정(시작 금지/전환 시 중지 모두 false)·WakeToRun=false·MultipleInstances=IgnoreNew·ExecutionTimeLimit=PT15M을 등록 후 내보낸 Task XML에서 실제 값으로 확인한다.

본격 활성화 전에 wrapper preview·잘못된 설정·비밀 비노출·DPAPI 왕복을 검사한다. 이후 실제 스케줄러 수동 시작과 시간 트리거를 관찰하고 LastTaskResult/마지막 결과·확정 cursor·행수를 대조한다. 권한 때문에 등록이 거절되면 관리자 승격/다른 자동시작 우회는 하지 않고 실제 거절과 실행 준비 상태를 기록한다. 등록/활성화가 성공한 것으로 표현하지 않는다.

## 5. 검증·롤백·완료

- actual PowerShell parser, 임시 ACL/DPAPI fixture와 별도 archive/state로 preview 바이트 불변, 평문·stderr canary 비노출, 잘못된 경로/config/해시 거절을 검증한다. 실제 Render GET과 운영 archive 생성은 소량이며 집계만 출력한다.
- 실제 작업 시작/시간 실행, 재조회 중복, root ACL·키 암호화·Task XML 비밀 부재, 원본 .env/사용자 untracked·Render Free/autodeployoff 보존을 검사한다. 기존 일반·정적·Windows/Linux 타입·CI PostGIS/CodeQL을 따른다. wrapper는 app/DB 코드나 의존성을 변경하지 않는다.
- 중지: `Disable-ScheduledTask -TaskName 'SpotON-OperationLogs-Pilot'`. 실행 중이면 먼저 정상 종료를 기다린다. 작업/보관소/키 파일을 자동 삭제하지 않는다. 다시 켤 때 상태·지연·journal을 먼저 점검한다. 키 교체는 작업 정지 후 같은 사용자가 새 DPAPI blob으로만 수행한다.
- 장애/수동 재초기화는 #162를 따른다. 목적 폴더 이동·다른 사용자·장비 복원은 binding/DPAPI가 달라지므로 자동 재사용하지 않는다. 백업은 이번 시범 운영에서 만들지 않으며 오프호스트 백업·복원과 복사본 만료 정책은 미완료다. 원본 제공자 보관도 통제하지 않는다.
- Codex MD → 실제 Claude Read/Edit → 구현/실검증 → 실제 Claude 구현 검토 → Codex 최종 대조 → 기능/문서 커밋·CI/develop PR Squash 절차를 따른다. 실제 작업 등록과30일 운영 증거를 구분한다.

## 6. 실제 검토·실행 기록

Claude는 이 MD만 Read/Edit한다. 제공된 소스와 집계만 읽고 shell/Git/DB/네트워크/MCP/다른 파일/서브에이전트는 사용하지 않는다. 테스트 실행 판정을 대신하지 않는다. 검토 이유와 차단/보류를 직접 기록하고 Codex가 실제 수정본을 대조한다.

### 6.1 Claude 설계 검토 (2026-11-15)

검토 대상: 이 MD와 제공된 `etl/operation_logs/job.py`·`job_state.py` 원문뿐이다. `render.py`·`archive.py`·`__main__.py`·wrapper 구현은 제공되지 않아 읽지 않았다. 아무 명령도 실행하지 않았으며 아래는 실행 증거가 아니다.

**판정: PASS (설계, 이번 수정 반영 조건).** 범위(가역적 로컬 Windows 시범·30일/24시간 완료 비주장)와 FE/앱/DB/.env/Render 보존 서술은 사용자 승인 범위와 일치하며 새 승인 절차를 추가하지 않았다. 아래 차단 1건과 보완 사항은 본문에 직접 반영했다. Codex는 diff를 대조하고, "구현 검증 필수" 항목이 실제로 통과하지 않으면 해당 경로를 채택하지 않는다.

차단(본문 반영으로 해소)
1. 자식 프로세스 환경 상속: 부모의 `RENDER_API_KEY`가 상속되면 preview의 키 미사용·키 없음 경로가 깨진다 → 3절 3에 명시 덮어쓰기 추가.

보완(본문 반영)
- git 설정 상속에 따른 fsmonitor/hook 실행·index 쓰기, assume-unchanged/skip-worktree로 인한 "깨끗함" 오판 → 2절.
- editable 설치에 의한 import 출처 혼동 확인 → 2절.
- DPAPI의 같은 사용자 프로세스 한계·계정 권한 키 위험·교체 순서·배타 생성·스크립트 로깅 → 2절.
- 경로 정규화(8.3·`\\?\`·끝 점/공백) 및 파일 단위 ACL 매 실행 확인, 자체 해시의 의미 한정 → 3절 1.
- 빈 키 경로가 `run_window`까지 도달함을 소스로 확인했으나 HTTP 전 거절 여부는 미제공 소스라 미확인 → 구현 검증 필수로 지정, 대체안 기록 → 3절 2.
- `credential_unavailable` 구분, 출력 비동기 읽기·상한, 타임아웃 계층과 고아 프로세스 → 3절 2·3.
- 결과 스키마 엄격 검사·종료코드 정합·`retention_risk`·따라잡기 속도 한계·동시 실행 → 3절 4.
- Interactive와 DPAPI의 정합, S4U 전환 금지 사유, 창 표시 한계, Task XML 실제 값 확인 → 4절.

소스 대조로 확인한 점(코드 읽기 기준)
- 초기 start 약20분 전은 `initialize`의 `now-30일 < initial ≤ safe_end` 조건과 `MAX_WINDOWS=6`(30분) 안이다.
- preview(`run_once` dry-run)는 state를 `mode=ro`로 열고 `archive.prune(execute=False)`를 호출하며 collect/checkpoint에 도달하지 않는다. archive 쪽 바이트 불변은 `archive.py` 미제공으로 5절의 실제 바이트 비교 시험에 의존한다.
- 중단 hard kill 후 남은 journal은 `validate`가 `state_journal_present`로 거절해 자동 진행하지 않는다(수동 점검 규칙과 일치). 이 경우 매 주기 같은 실패가 반복되므로 latest-result로 감지해야 한다.
- 시계 역행은 `clock_behind_checkpoint`, 30일 초과 중단은 prune 후 `checkpoint_expired`로 멈춘다.

구현 검증 필수(미실행, 결과는 Codex가 별도 기록)
- 빈 키 execute의 GET 0회·prune 완료·checkpoint 미전진(요청 계수 transport 또는 네트워크 차단).
- 부모 환경에 canary `RENDER_API_KEY`를 둔 preview/키 없음 execute에서 canary가 자식에 전달되지 않음.
- 자식 import 출처가 runtime 아래임.
- assume-unchanged 표식 파일 변경 시 wrapper 거절.
- 등록 후 Task XML의 반복 무기한·배터리·WakeToRun·IgnoreNew·PT15M·키/owner/service 부재.

보류(이번 범위 밖, 기존 서술 유지): 오프호스트 백업·복원, 공유 가상환경 독립화, Render workspace 플랜 실제 확인, 공급자 측 누락 검증, 30일 실제 운영.

### 6.2 Codex 구현·로컬 검증

- 설계 보완을 대조해 환경 allowlist/키 상속 제거, Git fsmonitor/hooks/optional locks 제한 및 assume-unchanged 거절, 파일 ACL/경로/해시, C# 동시 bounded 파이프 읽기, 정확한 결과 스키마·종료코드/부분 효과를 구현했다. 입력이 검증된 뒤에만 작업을 호출하며 DPAPI 실패는 빈 키 경로로 구분한다. preview는 키/최신 결과 파일을 바꾸지 않는다.
- 실제 PowerShell parser 오류0. 별도 비공개 native fixture17개 검사 통과 후 재사용 가능한 Windows pytest에 파일 ACL 거절을 추가해18개 시나리오를 검증한다. fixture의 자식은 모의 출력이며 실제 Render 수집 증거와 구분한다. canary를 둔 부모 환경 preview/빈 키 경로, stderr 비노출·상한, 비정상 schema/count/time/exit·자체 hash·assume-unchanged·추가 설정 거절·atomic latest 결과를 확인한다.
- 실제 core 빈 키 테스트는 httpx.Client를 실패하도록 계수해 GET0·prune1·checkpoint 불변을 검증하며 Windows wrapper 테스트와 합쳐2개 통과했다. 별도 DPAPI CurrentUser 메모리 왕복과 OS 작업 정의(등록 전) PT5M/무기한·Interactive/Limited·IgnoreNew·WakeToRun=false를 확인했다.
- 최종 로컬 일반 전체2140통과·기존 Windows symlink1skip·PostGIS298분리,63.32초. 기존 Starlette 경고1개다. ruff check/422파일 format, Windows/Linux mypy190파일, diff 검사 통과. Windows CI 전용 실행을 추가했다. 현재 실제 보관소/OS 작업 등록 전이며 다음 절에서 실행 결과를 따로 기록한다.

### 6.3 Claude 구현 검토 (2026-11-15)

검토 대상: 제공된 wrapper(`ops/windows/run-operation-log-job.ps1`) 원문, Windows pytest, CI 변경, 비공개 배치 스크립트4종(`private-root.ps1`·`protect-key.ps1`·`provision.py`·`register-task.ps1`, 키 값 없음), `job.py`/`job_state.py`, Codex 증거 요약. `render.py`·`archive.py`·`llm_ops.py`는 제공되지 않았다. 아무 명령도 실행하지 않았으며 아래는 실행 증거가 아니라 코드 읽기 판단이다. Codex가 보고한 수치(2140 통과 등)는 재현하지 않았고 그대로 인용만 한다.

**판정: REVISE (경미).** 비밀 처리·환경 격리·preview 비변경·키 없음 prune·출력 whitelist·Task 권한 설계는 6.1 조건을 충족한다. 다만 아래 R1·R2는 timeout 경로에서 설계 주장과 실제 동작이 다르고, R3는 증거 표현이 실제 검사보다 강하다. 세 항목은 코드/문구 수정만으로 해결되며, 수정 후 Codex 대조로 진행한다. 사용자 승인 범위 안의 가역 작업이므로 **새 사용자 승인 절차는 필요하지 않다.**

필수 수정
- **R1 프로세스 트리 종료.** venv `python.exe`는 redirector이므로 `process.Kill()`은 실제 Python을 남긴다(3절 3 정정 참고). 이때 남은 손자가 stdout/stderr 파이프를 계속 쥐어 `Task.WaitAll(5000)`이 실패하고 `child_timeout`으로 보고되지만, 고아 Python은 계속 실행되어 `job.sqlite3`의 `BEGIN IMMEDIATE`를 쥐거나 이후 checkpoint를 commit할 수 있다(데이터 손상은 아니나 다음 주기 `state_busy`, 보고와 실제 효과 불일치). Task Scheduler의 PT15M 종료도 같은 고아를 남긴다. → C# `Run`에서 Job Object(KILL_ON_JOB_CLOSE, 자식 생성 직후 Assign)로 트리를 묶거나 timeout 시 System32 절대 경로 `taskkill /T /F`. 검증: 타임아웃을 짧게 주입할 수 있는 테스트 매개변수로 `sleep` fixture를 실행해 timeout 후 실제 인터프리터 PID가 사라짐을 확인한다.
- **R2 호출별 timeout.** 같은 `Run`이 git 검사3회에도 540초를 쓴다. git이 멈추면 최악 27분+child 9분으로 PT15M을 넘어 Task Scheduler가 PowerShell만 죽이고 git/Python 고아가 남는다. → `Run`에 timeout 인자를 추가해 git은 예: 60초, job은 540초, 전체 합이 15분 미만이 되게 한다.
- **R3 증거 문구.** `provision.py` summary의 `free_autodeploy_off_preserved=True`는 아무 검사 없이 하드코딩된 값이다. 스크립트가 Render에 GET만 한다는 점에서 "변경 시도 없음"은 구성상 맞지만 "보존 확인"은 아니다. → 이미 받은 service GET 응답의 plan/autoDeploy 값을 비교해 실제로 확인하거나, 필드명을 `render_mutation_attempted=false`로 바꾼다. 같은 이유로 pytest의 `preview_files_unchanged`는 **모의 child**에서의 결과라 실제 #162 dry-run의 archive 바이트 불변 증거가 아니다. 실제 증거는 `provision.py`의 해시 비교가 실행된 뒤에만 기록한다.

권장(비차단)
- 정규식 끝 앵커: .NET `$`는 마지막 `\n` 앞에서도 일치한다. 키(`^[\x21-\x7e]{10,1024}$`)·시각 정규식은 `\z`로, 시각의 `\d`는 `[0-9]`로 바꾼다(유니코드 숫자 배제). child는 신뢰 코드라 위험은 낮다.
- `latest-result.json` 정체: config/source 검사 실패 시(의도적으로) 결과 파일을 쓰지 않으므로 이전 `ok`가 남는다. 감시는 `completed_at` 신선도(예: 15분 이내)와 `LastTaskResult`를 함께 봐야 한다고 4절 운영 점검에 명시한다.
- `register-task.ps1`의 `-Hidden` 설정은 작업 스케줄러 UI에서 작업을 숨겨 운영자 발견·중지를 어렵게 한다. 은밀성이 목적이 아니므로 제거를 권장한다. 또 `WakeToRun` 등 기본값 요소가 내보낸 XML에서 생략되면 검사가 실패하는데, 이 경우 작업은 비활성 상태로 남고 `registered=true, enabled=false`로 보고되므로 안전 측 실패다. 사실대로 기록하면 된다.
- 롤백(5절)에 `git worktree remove`(또는 수동 삭제 후 `git worktree prune`)를 추가한다. `git worktree add`는 공유 저장소 `.git/worktrees`에 메타데이터를 쓴다.
- git 설정 범위: `-c` 두 개와 `GIT_CONFIG_NOSYSTEM`/`GIT_CONFIG_GLOBAL=NUL`은 hook·fsmonitor·전역/시스템 설정을 막지만, 공유 저장소 local config와 `.gitattributes`의 `filter.*.clean/process`는 stat이 바뀐 파일에 대해 `git status`가 실행할 수 있다. 같은 사용자 신뢰 경계 안의 위험이므로 2절의 "설정 기반 외부 프로그램 실행을 막는다"를 "hook/fsmonitor/전역·시스템 설정 실행을 막는다(공유 local filter 설정은 같은 사용자 신뢰 범위)"로 한정한다.
- `provision.py`는 archive/job init에 runtime이 아닌 feat164 작업 트리의 `etl`을 import한다. 현재 변경은 `ops/`·`tests/ops/`·CI뿐이라 binding 규칙은 같지만, `etl/operation_logs`가 `b30cf21`과 같음을 assert하거나 runtime에서 init하는 편이 명확하다.
- Python/git 실행 파일은 root 밖이라 경로만 검사하고 해시는 고정하지 않는다. 공유 venv와 함께 같은 사용자 신뢰 전제로 이미 기록돼 있으니 유지한다.
- `ls-files -v` 출력은 64KiB 상한을 받는다. 고정 commit이라 결과가 결정적이며 넘으면 `source`로 닫힌 실패를 하므로 provision preview에서 드러난다.
- 키 파일 ACL이 넓은 경우에도 `credential_unavailable`로 빈 키 실행(prune만)이 된다. 비밀이 쓰이지 않아 안전하지만 노출 가능성 신호이므로 고정 플래그(예: `credential_acl_invalid`)로 구분하면 대응이 빠르다.
- CI Windows job: `uv run --locked --extra dev pytest ...`로 다른 job과 맞추고 `timeout-minutes`를 둔다.

코드 읽기로 확인한 점(통과)
- 환경: `EnvironmentVariables.Clear()` 후 allowlist9개만 복사하고, 키는 execute일 때만 자식에 넣는다. preview는 `key=$null`이라 `RENDER_API_KEY`가 아예 없다(빈 값 덮어쓰기보다 강함). 6.1 차단 1건 해소.
- argv: `Quote-Argument`가 `"`·제어문자·끝 역슬래시를 거절하므로 Windows 인자 분해 규칙상 경계가 정확히 보존된다. 셸을 거치지 않는다.
- 비밀: 키는 stdin→DPAPI CurrentUser→CreateNew blob, 평문 존재 검사, Task XML의 키/owner/service 부재 검사, `-ExecutionPolicy Bypass` 미사용. 복호화 바이트 배열은 `Clear`한다(문자열 사본 소거는 보장하지 않음, 2절 기록과 일치).
- ACL: root 상속 차단·owner=현재 SID·Allow ACE는 현재 사용자/SYSTEM만·사용자 FullControl 필수, 파일5종 매 실행 검사. Deny ACE도 거절(닫힌 실패).
- 경로: 고정 드라이브, `GetFullPath` 일치, `~`/`:`/끝 점·공백 거절, 상위 모든 요소의 reparse 검사.
- 키 없음: DPAPI 누락/실패 시 빈 키로 실행하고 `credential_unavailable`로 덮어써 구분한다. Codex 보고에 따르면 core 테스트에서 GET0·prune1·checkpoint 불변을 확인했다(6.1 필수 항목, 인용).
- 출력: 두 파이프를 동시에 끝까지 읽되 64KiB 초과분은 버려 교착이 없다. 정확한 키 집합, int/long만 허용(bool 거절), 시각 형식, enum, mode 일치, 종료코드-상태 정합, 미등록 오류→`job_failed`, stderr 폐기. `retention_risk`(6일)와 `effects_may_be_partial` 계산이 있다.
- 보고 파일: execute이며 source 검사 통과 후에만, root 안 CreateNew 임시 파일→`File.Replace`/`Move`. preview는 쓰지 않는다.
- Task: Interactive·LeastPrivilege·IgnoreNew·PT15M·배터리 허용·WakeToRun=false·반복 Duration 없음을 내보낸 XML로 검사한 뒤에만 Enable한다. 실패 시 자동 삭제 없이 상태를 그대로 보고한다. 비밀번호 저장 없음, Interactive는 DPAPI CurrentUser와 정합.
- `-E -s`에서 venv site-packages가 실제로 잡히는지는 `provision.py`의 runtime import 검사(httpx를 import하는 실제 `etl.operation_logs.job`)가 함께 확인하므로, 이 검사가 실제로 통과한 기록을 남겨야 한다.

정직한 증거 경계
- 현재 증거는 로컬 테스트·정적 검사·모의 child fixture·메모리 DPAPI 왕복·등록 전 Task 정의다. 실제 보관소 생성, 실제 Render GET, 실제 preview 해시 불변, 작업 등록/시간 트리거 실행, Windows CI 통과는 **아직 기록되지 않았다.** 이후 기록할 때는 `provision-summary.json`과 등록 스크립트 출력, `LastTaskResult`, `latest-result.json`의 `completed_at`/확정 cursor/행수를 근거로 쓰고, 30일 운영·24시간 가용성·백업과는 계속 구분한다.

수정 후 Codex 확인 항목: R1 트리 종료 테스트, R2 timeout 인자 반영, R3 summary 필드 정정, 권장 항목 중 채택/미채택과 사유.

### 6.4 Codex 보완·실제 시범 운영

- R1: System32의 taskkill `/PID <직접 생성한 프로세스> /T /F`로 launcher와 실제 인터프리터 트리를 종료한다. 짧은3초 timeout을 C# helper에만 주입하는 실제 Windows 테스트에서, venv가 띄운 Python이 PID를 남기고 sleep하는 동안 timeout 후 실제 PID가 사라짐을 확인했다. Job Object는 이번에 추가하지 않는다. wrapper 자체의 강제 종료/장비 종료 시 완전한 cleanup은 보장하지 않으므로 정상 종료 대기와 기존 journal 점검을 유지한다.
- R2: git 검사별10초, Python 작업540초, 종료 정리 최대30초와 짧은 파이프 대기를 사용한다. 정상적인 합계는 Task의15분보다 작다. OS 프로세스 생성/종료 자체가 멈추는 경우까지 엄격한 SLA를 주장하지 않는다.
- R3: 기존 service helper 자체가 plan=free/autoDeployTrigger=off를 이미 검증했으나 제공 소스에 없었다. provision에도 명시 assert를 추가했고 실제 GET 응답으로 확인했다. 모의 child preview와 실제 runtime preview의 바이트 불변 증거는 구분했다.
- 권고 반영: 키/시각의 `\z`와 ASCII 숫자, 감시 시각 신선도, UI에서 작업 숨김 미사용(콘솔 창만 숨김), Windows CI locked/dev 및10분 제한, 초기화에 사용하는 ETL5파일과 고정 runtime의 바이트 일치를 확인한다. 공유 Git local filter/공유 venv/외부 실행 파일은 같은 사용자 신뢰 범위이며 전면 변조 방지를 주장하지 않는다. 넓은 credential ACL은 사전 파일 ACL 검사에서 쓰기 전에 실패하므로 빈 키 경로로 조용히 진행하지 않는다.
- 최종 Windows 일반 전체2141통과·기존 symlink1skip·PostGIS298분리,59.79초. native subprocess 트리 종료 테스트를 포함한 Windows wrapper2개도 개별25.92초로 통과했다. ruff check/422파일 format·두 플랫폼 mypy190파일·diff 검사 통과. 일반의 Windows 특화2개는 Linux에서 skip하고 전용 Windows CI에서 실행하도록 한다.
- 2026-11-15T12:03:30Z 전용 보관소를 실제 생성했다. archive→job 순서로 초기화했고 start=2026-11-15T11:43:30.268581Z다. DPAPI 파일 외에 키 평문이 없음을 검사했다. 고정 runtime import와 preview의 archive/state/암호문 해시 불변을 확인했다. 과거 전체 backfill은 수행하지 않았다.
- OS 작업을 새 Disabled 상태로 만들고 XML을 검증했다. 이 Windows는 기본값 RunLevel·WakeToRun을 XML에서 생략해 최초 검증이 닫힌 실패로 멈췄다. 오류 분류의 한국어 리터럴은 PS5의 UTF-8 BOM 해석 문제로 별도 오류가 나 ASCII 분류로 고쳤다. 이 세션에서 만든 Disabled 작업의 계정 SID·단일 action/args/작업 디렉터리 일치를 확인한 후, XML 기본값과 실제 CIM Limited/Interactive/Wake=false를 함께 대조해 활성화했다. 기존 작업을 덮어쓰거나 다른 자동시작으로 우회하지 않았다.
- 12:04:46Z 활성화/시작 요청, 첫 결과 완료=12:04:52.2426862Z. LastTaskResult0·Ready,3구간 성공·API0행·삽입0·만료 삭제0·확정 끝점11:55:00Z·지연0이다. 대상 구간 API 반환이0이며 로그 전체 부재/누락 없음을 입증하지 않는다. 이전 #162의 실제377삽입 검증과 구분한다. 다음 시간 트리거 실행은 별도로 관찰한다.
- 실제 실행 후 preview는 archive/state/DPAPI/latest 네 파일 해시를 모두 보존했다. root와 파일6종의 현재 사용자/SYSTEM ACL·Task XML 키/Render owner/service 부재·작업 UI 표시·절전 깨우기off·Free/autodeployoff를 확인했다. 실제 운영 파일은 정리하지 않고 지속 보관한다.

운영 점검 보완: `latest-result.completed_at`가15분 이상 오래됐거나 `LastTaskResult!=0`, lag 증가, retention_risk가 있으면 정상으로 판단하지 않는다. Disabled로 중지하고 정상 종료를 기다린다. 폐기할 때는 별도 확인 후 등록 작업/보관소와 함께 detached runtime을 `git worktree remove`로 정리해야 하며, 파일만 임의 삭제해 Git 메타데이터를 남기지 않는다. 이번에는 삭제하지 않는다.

### 6.5 Claude 최종 재검토 (2026-11-15)

검토 대상: 이 MD, 제공된 최종 wrapper·Windows pytest2개·CI·비공개 배치 스크립트4종(키 값 없음)·`job.py`/`job_state.py`, Codex 증거(`validation.txt`·`live-summary.json`). `render.py`·`archive.py`·`llm_ops.py`, 6.4에서 말한 "Disabled 작업 재개" 절차 스크립트는 제공되지 않았다. 아무 명령도 실행하지 않았으며 수치·실행 결과는 Codex 증거를 인용한 것일 뿐 재현하지 않았다.

**판정: PASS.** 6.3의 R1~R3는 코드상 해소됐고 남은 사항은 아래 비차단 후속뿐이다. 사용자 승인 범위(가역적 로컬 시범) 안이므로 새 승인 절차는 두지 않는다.

R1~R3 대조
- R1: `KillTree`가 `%SystemRoot%\System32\taskkill.exe /PID <pid> /T /F`로 트리를 종료하고 killer 자체도 30초 제한·파이프 배수·`RENDER_API_KEY` 제거를 한다. taskkill 실패(이미 종료 등)도 `TimeoutException`으로 닫혀 `child_timeout`이 된다. 새 native 테스트가 venv redirector 아래 실제 인터프리터 PID 소멸을 검사하는 구조임을 확인했다(통과 여부는 Codex 인용). Job Object 미채택은 6.4에 한계로 기록됐다. Task의 PT15M이 PowerShell을 먼저 죽이는 경우 고아가 남을 수 있다는 점은 R2 예산으로 정상 경로에서 회피된다.
- R2: `Run(..., timeoutMs)` 상한540초 검사, git3회×10초, job540초, 종료 정리 30+5+5초로 정상 최악 약10.5분 < PT15M이다.
- R3: `provision.py`가 실제 service GET의 `plan=='free'`·`autoDeployTrigger=='off'`를 assert한 뒤에만 summary를 쓰므로 `free_autodeploy_off_preserved=True`는 이제 검사된 값이다. pytest의 `preview_files_unchanged`(모의 child)와 실제 preview 해시 불변(provision·live-summary)이 6.4에서 구분돼 있다.

코드 읽기로 추가 확인(통과)
- 넓은 credential ACL은 `try` 밖의 사전 `Assert-PrivateAcl`에서 `configuration`으로 닫혀 빈 키 실행으로 조용히 넘어가지 않는다(6.4 서술과 일치). 파일이 없거나 복호화 실패만 `credential_unavailable` 경로다.
- preview는 자식에 `RENDER_API_KEY`가 없고 `job.main`은 `os.environ.get(...,"")`이므로 키 없이 로컬 dry-run만 한다. `latest-result.json`은 execute·source 검사 통과 후에만 쓴다.
- Task 등록은 `-Hidden` 미사용(콘솔 창만 숨김)·`Settings.Hidden` 거절, 기본값 생략 XML 노드는 기본값으로 비교, 검사 통과 후에만 Enable한다. 비밀번호 미저장·Interactive/Limited·Bypass 미사용.

비차단 후속(다음 커밋 또는 기록 보완)
1. `protect-key.ps1`의 입력 검사가 아직 `$` 앵커다. 키 교체 시 표준입력에 끝 개행이 섞이면 검사를 통과해 개행 포함 값이 암호화되고, wrapper의 `\z` 검사에서 매 실행 `credential_unavailable`(prune만)로 떨어진다. 안전 측 실패지만 교체 절차 오류를 숨기므로 `\z`로 맞춘다. 이번 최초 생성은 Python `input=key`(개행 없음)로 전달됐고 실제 실행이 `credential_unavailable=false`로 성공해 영향이 없었다.
2. wrapper의 config 정규식(`source_commit`·`*_sha256`·`owner_id`·`service_id`)도 `$`다. 끝 개행 값은 이후 `Quote-Argument`/정확 비교에서 닫힌 실패하므로 위험은 없으나 일관성을 위해 `\z`를 권장한다.
3. 증거 정합: `live-summary.json`의 `last_run_utc=12:04:04Z`가 6.4의 활성화/시작 요청 `12:04:46Z`보다 42초 앞선다. Disabled 상태에서 실행됐을 리 없고 완료 `12:04:52Z`(약6초 작업)는 수동 시작과 맞으므로 시각 변환/필드 해석 차이로 보이지만, 확인 전에는 단정하지 않는다. 다음 관찰 때 Task Scheduler 작업 기록(이벤트)이나 `latest-result.completed_at`과 함께 대조해 정정 기록한다.
4. 시간 트리거 실행은 아직 증거가 없다(`next_run_utc=12:09:09Z` 예정만 있음). 첫 성공은 수동 `Start-ScheduledTask`이다. 시간 트리거 1회 이상의 `LastTaskResult=0`·`completed_at` 갱신·cursor 전진을 기록하기 전에는 "5분 주기 동작 확인"으로 표현하지 않는다.
5. 6.4의 Disabled 작업 재개 절차(SID·단일 action/args/작업 디렉터리 확인 후 Enable)는 스크립트가 제공되지 않아 Codex 서술로만 확인했다. 저장소 밖 비공개 스크립트로 두더라도 이 MD에 단계와 확인 항목을 남기거나, 최종 `register-task.ps1`이 재실행 없이 그 역할을 하지 않음을 명시한다.
6. Windows CI job은 추가됐으나 원격 CI 통과 증거는 아직 없다. PR CI 결과로 별도 기록한다.

정직한 증거 경계(현재)
- 실제로 기록된 것: 전용 보관소 생성(12:03:30Z)·DPAPI 암호문만 존재·runtime ETL5파일 바이트 일치/import 출처·실제 preview 해시 불변·작업 등록 XML/CIM 검증·수동 시작 1회 성공(3구간, API0행, 확정11:55:00Z)·실행 후 preview 4파일 해시 보존·ACL·Task XML 비밀/대상 ID 부재·Render Free/autodeploy off GET 확인(모두 Codex 인용).
- 아직 아닌 것: 시간 트리거 주기 실행, 실제 로그가 있는 구간의 수집(이번 API0행은 로그 부재/누락 없음의 증거가 아님), 로그오프·절전·재부팅 후 재개, 24시간/30일 운영, 만료 삭제의 실제 발생, 오프호스트 백업, Windows CI 통과.

### 6.6 시간 실행에서 발견한 결과 파일 교체 오류 보완

- 원래 TimeTrigger 시작=2026-11-15T21:04:38+09:00,5분 반복이다. 추가 Start-ScheduledTask 호출 없이 첫 반복에서 native COM LastRunTime=12:09:39Z, LastTaskResult=1을 관찰했다. 실제 제어 cursor는12:00Z로 진전했지만 latest는 첫 성공의11:55Z에 머물렀다. 보고 실패를 수집 전체 rollback으로 오인하지 않았다.
- 새 임시 파일2개로 PowerShell5.1의 `[IO.File]::Replace(source,destination,$null)`가 MethodInvocationException/ArgumentException을 내는 것을 재현했다. 첫 Move는 성공하고 두 번째부터 Replace가 실패하는 경로다. nullable backup 인자를 PowerShell binder에 넘기지 않고 C# `CommitReport`에서 실제 null로 호출하도록 수정했다.
- 회귀 검사에 동일 fixture의 execute2회와 기존 latest 내용/완료시각 교체 검증을 추가했다. Windows wrapper 테스트2개(19개 설정·출력 시나리오와 실제 프로세스 트리 종료)가 보완 후26.10초로 통과했고 ruff check/422파일 format·diff 검사도 통과했다. 전체 일반2141개는6.4의 보완 전 baseline이며, 최종 소스는 이후 PR의 Linux/Windows/PostGIS CI로 확인한다.
- 작업을 Disabled로 중지한 Ready 상태에서 검증된 wrapper 복사본과 config SHA만 갱신했다. preview로 archive/state/DPAPI/latest 네 파일 해시 보존을 확인한 후 Enable했다. 추가 수동 시작은 요청하지 않았고 원래 다음 시간 트리거를 기다린다. 같은 archive/state/binding과 초기 start를 그대로 유지했다.
- 시각 차이는 현재 PC의 CIM 값과 native Task Scheduler COM 값을 직접 대조했다. 첫 실행은 COM12:04:46Z/CIM12:04:04Z, 다음 예정은 COM12:09:38Z/CIM12:09:09Z였고 XML StartBoundary와 COM이 일치했다. 완료시각12:04:52Z도 COM 시작과 맞는다. 이후 관찰은 COM을 주 시각 근거로 쓰고 CIM 값을 별도로 남긴다. Operational 이벤트 로그는 꺼져 있어 켜거나 설정을 바꾸지 않았다. 전체 Windows의 일반 성질로 확대하지 않는다.
- 비공개 키 생성 입력도 `\z`로 맞췄고 기존 암호문은 다시 만들지 않았다. config 정규식의 `$`는 뒤의 정확 비교/인자 검사에서 닫힌 실패가 보장돼 이번에는 변경하지 않는다. Disabled 재개는 이 세션의 새 작업만을 대상으로 SID·단일 action/args/작업 디렉터리 비교 후 검증/활성화했으며 일반 등록 스크립트를 덮어쓰기 용도로 바꾸지 않았다.

### 6.7 Claude 6.6 보완 재검토 (2026-11-15)

검토 대상: 이 MD(6.6 포함), 제공된 최종 wrapper·Windows pytest·CI·비공개 스크립트4종(키 값 없음)·`job.py`/`job_state.py`, Codex 증거(`validation.txt`의 TIMER/REPORT FIX 절·`live-summary.json`). 이번에도 명령·Git·네트워크·DB를 사용하지 않았고 실행 결과는 Codex 증거 인용일 뿐 재현하지 않았다. 3절 3의 Job Object "우선 권장" 문장 뒤에 최종 채택(taskkill만, Job Object 미채택)을 한 줄 덧붙여 6.4와 본문이 어긋나지 않게 했다. 그 밖에 본문은 수정하지 않았다.

**판정: PASS (6.6 보완).** 사용자 승인 범위(가역적 로컬 시범) 안이며 새 승인 절차는 두지 않는다.

원인·수정 대조(코드 읽기)
- 원인 진단이 맞다. PowerShell은 `[string]` 매개변수에 `$null`을 넘기면 `String.Empty`로 바꾸므로, `File.Replace(src, dst, $null)`은 실제로 backup 경로 `""`로 호출되어 `ArgumentException`이 난다. 첫 실행은 대상이 없어 `Move` 경로라 통과했고 두 번째부터 실패한 관찰과 일치한다.
- 수정이 맞다. C# `CommitReport`는 컴파일 시점의 진짜 `null`로 `File.Replace`를 호출한다. 임시 파일이 같은 root(같은 볼륨) 안에 있어 Replace 전제를 만족한다. 실패 시 `report_write`로 닫히고 `finally`가 임시 파일 삭제를 시도한다.
- 회귀 테스트가 같은 fixture로 execute를 두 번 실행하고, 두 번째 결과가 기존 latest를 대체(내용 동일·`completed_at` 상이)했는지 확인하므로 이번 결함을 정확히 겨냥한다.
- 실패 시 보고가 정직했다. 12:09 실행은 수집 cursor가 12:00Z로 커밋됐는데도 wrapper가 `LastTaskResult=1`을 남겼고, 6.4의 신선도 점검 규칙(`completed_at` 15분·`LastTaskResult!=0`)이 실제로 이상을 드러냈다. "보고 실패 ≠ 수집 rollback" 구분도 `job.py`의 checkpoint 커밋 순서와 맞다.
- 교체 절차가 6.4 운영 규칙과 맞다. Disabled 상태에서 wrapper 복사본·config SHA만 바꿨고 archive/state/binding/초기 start를 유지했으며, 갱신 후 preview가 실제 ACL·해시 검사를 다시 통과했다(Codex 인용). 6.5 후속5(재개 절차 기록)는 6.6 마지막 항목의 단계·확인 항목 서술로 충분하다고 본다.
- 시각 근거 정리(COM 주 근거·CIM 별도 기록)로 6.5 후속3은 해소된다. 다만 StartBoundary 12:04:38Z는 작업이 Disabled였던 때이고 12:04:46Z에 Enable과 Start를 함께 요청했으므로, 첫 실행이 수동 Start인지 StartWhenAvailable 보충 실행인지는 IgnoreNew 때문에 구분할 수 없다. 결과에는 영향이 없으며 "수동 시작으로 실행"이라고 단정하지 않는 편이 정확하다.
- `protect-key.ps1` `\z` 반영으로 6.5 후속1 해소. config `$` 유지(후속2)는 닫힌 실패가 보장되므로 미채택 사유를 수용한다.

비차단 후속
1. **배치 복사본과 커밋본 일치.** 현재 실행 중인 `run.ps1`은 미커밋 작업 트리(`ops/windows/run-operation-log-job.ps1` 수정 상태)에서 복사됐다. PR 병합 후 develop의 해당 파일 SHA256이 config의 `runner_sha256`과 같은지 기록하고, 다르면 Disabled→복사본/config 갱신→preview→Enable 절차로 맞춘다. 그래야 "검증·CI 통과한 코드가 실행 중"이라고 말할 수 있다.
2. **시간 트리거 성공 증거.** 12:09:39Z에서 시간 트리거가 실제로 발동함은 확인됐다(결과는 보고 실패). 수정 후 원래 시간 트리거(12:14:38Z 이후) 1회 이상에서 COM `LastTaskResult=0`·`latest.completed_at` 갱신·cursor 전진이 기록돼야 "5분 주기 동작 확인"이라고 쓸 수 있다. 그 전에는 "시간 트리거 발동 확인, 성공 실행 관찰 대기"로 표현한다.
3. 보고 파일을 다른 프로세스가 열어 둔 순간 Replace가 공유 위반으로 실패하면 `report_write`·종료코드1이 된다. 안전 측 실패이며 다음 주기에 회복되므로 감시 도구는 짧게 읽고 닫는 방식을 쓰면 된다는 점만 운영 메모로 남긴다.
4. 최종 소스의 전체 일반·Windows·PostGIS·CodeQL CI 결과는 아직 없다(6.6이 baseline 구분을 정확히 기록함). PR CI 결과로 별도 기록한다.

정직한 증거 경계(갱신)
- 추가로 기록된 것: 시간 트리거 실제 발동 1회(12:09:39Z COM, 수집 커밋 12:00Z, 보고 실패로 `LastTaskResult=1`), PS5.1 Replace 결함 재현·수정·회귀 테스트 통과, Disabled 상태 갱신 후 preview 4파일 해시 보존(모두 Codex 인용).
- 아직 아닌 것: 수정 후 시간 트리거 성공 실행, 배치 복사본과 병합본 일치, 실제 로그가 있는 구간의 수집, 로그오프·절전·재부팅 후 재개, 24시간/30일 운영, 만료 삭제의 실제 발생, 오프호스트 백업, 최종 소스 CI 통과.

### 6.8 수정 후 시간 트리거 성공 관찰

2026-11-15T12:15:05Z 실제 재검증: 추가 수동 시작 없이 원래5분 간격의 COM LastRunTime=12:14:39Z(예정12:14:38Z), LastTaskResult0·Ready다. 최신 결과 완료=12:14:41.9528159Z로 교체됐고 확정 cursor는12:00Z→12:05Z, lag0·1구간 성공·checkpoint_committed=true다. API0행·삽입0·만료 삭제0이며 공급자 누락 없음/로그0 발생을 입증한 것으로 해석하지 않는다. 다음 예정은12:19:38Z다. 이 관찰로 실제 시간 트리거의 성공 실행과 기존 latest 교체를 확인했다.

같은 검증에서 실제 preview 네 파일 해시 보존·파일별 ACL·암호문만 존재·Task XML 비밀/대상 ID 부재·Interactive/Limited·UI 표시·깨우기off·Render Free/autodeployoff를 다시 확인했다. CIM은 이번에도12:14:14Z로 초값이 달라 주 근거로 쓰지 않았다. 현재 시범 작업은 활성 상태로 유지한다. 로그온/절전/재부팅 복구·실제30일 연속 운영·실제 로그가 있는 구간 및 실제 만료 행 삭제·오프호스트 백업/복원은 완료하지 않았다. 기존 #158/#162의 격리 만료/양수 로그 검증은 별도 근거다.

운영자는 latest를 짧게 읽고 닫으며15분 신선도와 native COM LastTaskResult/시각을 함께 점검한다. 다른 프로세스가 파일을 오래 열어 두면 Replace가 공유 위반으로 실패할 수 있고 다음 주기에 재시도한다. 실행 복사본·commit3604983의 wrapper·최종 병합본의 SHA256 일치는 CI/병합 후 한 번 더 확인한다. CI의 최종 판정은 이슈/PR 연결의 checks에 남긴다.
