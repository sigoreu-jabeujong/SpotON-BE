# 생활인구 미확정 데이터 정책·ETL 품질 로그 (#90)

- 기준: develop69e5519, head0010.
- 사용자 답변은 공식 의미/버전 근거 확보가 아닌 미확정 데이터 취급 정책이다. 공간 수치 API의 pending을 해제하지 않는다.

## 1. 사용자 확정 규칙과 현행 보존

동일 격자/시각의 서로 다른 행정동 행은 공급기관 확인 전 임의 합산하지 않는다. 원천 ZIP/CSV와 현행 불변 관측의 행정동 차원·원문 행 hash를 보존하고 미확정 케이스를 따로 계수한다. raw/staging이라는 역할 때문에 새 테이블을 만들거나 기존 행을 제거하지 않는다.

행 부재는0명이 아니며 missing/no_data로 다룬다. 현재 행 상태missing은 원천 셀 결측이고, 행 부재와 별개다. 임의 행/값/좌표를 만들지 않으며 *는suppressed/null로 보존한다. 관측일2026-11-07과 SHP의 공식 대응 자료 전 공간 인구 합계/주야간 API는 보류한다. 원천 수집·정제·불변 관측 적재는 허용하며 이번에는 기존 manifest dry-run만 실행한다.

기존 코드가 이 보존/보류를 이미 수행한다. 빠진 기능은 미확정 케이스의 별도 ETL 운영 로그다. 원본/metadata/해시·적재 규칙/PK·모델/migration·CLI stdout·API/FE·.env/Docker·외부 수집/실LLM 호출을 바꾸지 않는다.

## 2. 품질 요약

검증된 DailyInput.rows는source/hour/admin/grid순이다. source/hour블록 단위로 격자별 행정동 구분·행 수를 잠시 세어 다음6개 **행/그룹 건수**만 만든다. 53만 전체 조합 map을 추가 보유하거나 population을 합산하지 않는다. 원본 순서/행/payload/해시를 수정하지 않는다.

- suppressed_rows: 비공개 셀인 행 수.
- missing_value_rows: 원천 합계 셀이 비어 있는 행 수. 행 자체가 없는 조합 수가 아니다.
- observed_zero_rows: 실제 관측값이0인 행 수. 비공개/셀 결측을 포함하지 않는다.
- unlocated_rows: SHP에서 공간정보를 찾지 못한 행 수.
- multi_admin_groups: (원천,시각,격자)에 서로 다른 행정동이2개 이상 있는 그룹 수.
- multi_admin_rows: 해당 복수행정동 그룹에 속한 모든 행 수.

관측일은manifest가 단일 일자로 검증한 값이다. 여러 원천의 그룹을 합친 건수이며 원천을 제거한 고유격자 수가 아니다. 플래그끼리 겹칠 수 있어 합산 제외 수/인구/완전성/제공률을 만들지 않는다. 없는 행을 판별할 공식 조합 기준은 미확인이므로 행 부재 수를 생성하지 않는다.

## 3. 이벤트·실패 경계

app/core/operations.py에 living_pop run에만 허용되는 고정 품질 이벤트 helper를 추가한다. 기존 UUID/run context·_counts검증·_emit의4096bytes/개행/lock/민감정보 비출력/실패 무해화를 재사용한다. 다른 source/부모run 없음/유효UUID 없음은 기록하지 않는다.

이벤트는 event=etl_quality, source=living_pop, run_id, stage=read_source, status=completed|failed, scope=source_day_all_sources, spatial_compatibility=unverified, aggregation_status=pending이다. completed는 입력 품질 요약 계산만 성공했다는 뜻이며 DB 적재/수집 완전성·공간 검증 성공이 아니다. 유효한6개 비음수 int카운터(부울 제외,상한2**63-1)만 counts로 기록한다. 추가 키/임의 객체는 출력하지 않는다.

summary 계산 불가/필수 카운터 누락/타입 위반이면 status=failed·고정reason=quality_summary_unavailable로 남기고 counts를 넣지 않는다. 예외 문자열/코드/경로/좌표/행정동·격자코드/인구 값을 남기지 않는다. 로그·품질 요약 오류가 ETL의 정상 결과·DB 오류·취소를 바꾸지 않게 한다. 기존 API/ETL 이벤트 형식은 유지하고 새 이벤트만 추가한다.

load_input 성공 후 read_source phase가 끝난 직후, 설정/DB 준비 전에1번 기록한다. 따라서 DB 준비·적재가 이후 실패해도 그 품질 현황은 남고 기존 실패 이벤트가 뒤따른다. read_source 자체가 실패한 경우는 기존 read_source/import failed만 남기고 읽지 못한 품질 건수를 추정하지 않는다.

## 4. 파일·검사

- etl/living_pop/observability.py: 입력 품질 요약·안전 기록 조정. source/hour블록별 임시 map만 사용한다.
- app/core/operations.py: 고정키/유효수/현재living_pop run만의 이벤트. API/일반 ETL 로그의 기존 허용키는 확장하지 않는다.
- etl/living_pop/__main__.py: 성공한 read_source 다음 이벤트1회, stdout/DB/원본 불변.
- 단위: 실제 합성 manifest168행의 상태/그룹 대조, 같은 격자의 원천·시각 구분, 서로 다른 행정동만 식별, 행 부재 비합성·입력payload/hash 보존, 안전한 키/숫자/UUID·부모context·로그 실패 무해화·summary실패 미확인/0비치환.
- 격리PostGIS: 실제 import dry-run/write/replay·후속 DB 오류 때 품질 이벤트 존재/순서·commit 실패 구분, 기존 보존/해시/멱등성 검사. 다른 공간API는pending유지.
- 실제dev: 기존 manifest read-only dry-run, stdout와6카운터 대조·원문 비노출·원본hash/관측4테이블 보존. 새수집/적재/DML/DDL/VACUUM 없음. 전체 일반/격리·ruff/format/mypy·비밀값 검사 후 지정PR/CI/CodeQL/develop 정상Squash.
- BE README/CLAUDE/작업계획에 확정 정책과 이벤트 의미를 반영한다. 공개 API/FE 계약 변경이 없어 FE 요청서/FE CLAUDE는 대상이 아니다. #57·#78 및 공간 집계의 공식 근거 대기는 유지한다.

## 5. Claude 검토 요청

이 MD와 지정 BE 소스만 Read하고 §6만 Edit한다. .env/DB/원본/네트워크/Bash/Git/FE/다른 파일 수정 금지. 사용자 규칙과 원천 사실 구분·행 부재/셀 결측·복수행정동 비합산·메모리/원문 보존·로그 실패 무해화/후속DB오류·값/코드 비노출을 검토한다. 실행/DB 검증을 했다고 주장하지 않는다.

## 6. Claude 검토 결과

검토 범위: 이 MD와 지정 소스6개(app/core/operations.py, etl/living_pop/__main__.py·input.py·data.py, tests/etl/living_pop_helpers.py, tests/integration/test_living_pop_import.py)만 정적으로 Read했다. source.py·repository.py·grid.py·모델은 읽지 않았으므로 value_status 문자열, 중복 키 거절, PK 구성은 미확인이다. 실행·DB·원본 접근은 하지 않았고 아래 수치는 fixture 코드를 읽고 계산한 기대값이다.

### 6.1 판정

사용자 정책(행 부재≠0, 셀 결측≠행 부재, 복수행정동 비합산, 좌표·값 비보완, pending 유지)과 현행 코드는 충돌하지 않는다. load_input은 행정동·원천·시각 차원을 보존한 채 정렬하고, 그 뒤에 content hash를 계산한다. 따라서 summary를 load_input 반환 뒤에 읽기만 하면 hash·payload·적재가 바뀌지 않는다. 설계를 막는 차단 사항은 없다. 다만 아래 B1~B5를 구현 전 필수 조건으로 §3·§4에 반영해야 한다.

### 6.2 구현 전 필수 조건(차단 수준)

- **B1 완전성 검사에 _counts를 그대로 쓰지 않는다.** 기존 `_counts`는 잘못된 키를 조용히 빼므로 일부 카운터만 담긴 completed 이벤트가 나올 수 있다. 새 helper는 6개 키가 모두 있고 각각 `type(v) is int`(bool 제외)이며 0~2**63-1일 때만 completed로 기록해야 한다. 하나라도 어긋나면 counts 없이 failed+quality_summary_unavailable을 남긴다. 기존 `COUNTS`/`QUALITY_FLAGS`/`_etl_record`에 새 키를 추가하지 않는다. 그래야 etl_run/etl_stage 형식이 바뀌지 않는다.
- **B2 정렬 가정 위반은 잘못된 수가 아니라 failed로 처리한다.** 블록 단위 계수는 rows가 (source,hour,admin_code,grid_id) 순서라는 가정에 의존한다. 같은 (source,hour) 블록이 닫힌 뒤 다시 나타나거나 키가 역행하면 그룹이 이중 계수된다. summary는 블록 키의 단조 증가를 검사하고, 위반이면 계산을 중단한 뒤 quality_summary_unavailable로 남겨야 한다. rows를 재정렬하거나 복사·정렬하지 않는다. `list.sort` 같은 in-place 정렬은 원본 순서와 hash 전제를 깨므로 금지한다.
- **B3 호출 위치와 예외 범위를 고정한다.** summary 계산과 기록은 `with etl_phase("read_source")` 블록 **밖**, `Settings()`·`validate_local_target` **앞**에 둔다. 블록 안에 두면 summary 실패가 read_source failed로 잘못 기록된다. 계산과 기록 전체는 `except Exception`으로만 감싼다. KeyboardInterrupt/CancelledError 같은 BaseException은 삼키지 않고 전파해 취소 의미를 보존한다. 반환값은 run_import에 넘기지 않는다. 그래야 stdout JSON 키·값과 exit code가 바뀌지 않는다.
- **B4 행정동 구분은 저장값 그대로 비교한다.** 복수행정동 판정은 Observation.admin_code(이미 load_input이 정규화해 저장·hash하는 값)의 서로 다른 값 집합 크기≥2로 한다. 앞 8자리 자르기·코드 매핑·공백 재처리 같은 추가 정규화를 하지 않는다. 그룹 키는 원천 grid_id다(located_grid_id 아님). 따라서 unlocated 격자도 그룹으로 계산하고 unlocated_rows와 겹칠 수 있다고 문서화한다. 원천 간·시각 간 그룹을 합치지 않는다. 같은 (source,hour,admin,grid) 중복이 load_input에서 거절되는지는 이번 범위에서 확인하지 못했다. 따라서 행 수가 아니라 서로 다른 admin 집합으로 판정해야 한다.
- **B5 상태 판정은 value_status를 기준으로 한다.** observed_zero_rows는 value_status가 관측값(실제 문자열은 source.py에서 확인)이고 population==Decimal(0)인 행이다. population이 None이라고 0으로 보지 않는다. suppressed/missing은 population 값이 아니라 value_status로만 센다. 세 카운터의 합으로 "값 있는 행"이나 제공률을 만들지 않는다.

### 6.3 권고(비차단)

- `missing_value_rows`라는 이름만 보면 행 부재로 오독할 수 있다. 이름을 유지한다면 README와 이벤트 설명에 "원천 합계 셀이 빈 행, 행 부재 미포함"을 명시한다. 또는 `blank_value_rows`로 바꾸는 것을 Codex가 결정한다.
- stdout의 sources에는 이미 원천별 statuses/unlocated가 있다. 이벤트는 원천 합산 6개로 충분하다. 원천별 분해를 추가하면 4096bytes 안에 들어가지만 이번 범위를 넘으므로 후속으로 둔다.
- etl_quality에는 duration_ms를 넣지 않는다. 같은 stage=read_source의 etl_stage completed 이벤트와 혼동하지 않도록 event명만으로 구분한다. completed는 "입력 요약 계산 성공"일 뿐이다. 이후 import failed가 따라올 수 있다는 설명을 README에 둔다.
- "durable"은 `_emit`의 write+flush로 DB 단계 전에 stderr에 내보냈다는 뜻이다. 외부 수집기 보관·30일 정책은 여전히 미구현(#72)이다. 기록 실패·4096 초과 시 이벤트가 조용히 빠질 수 있으며, 이는 fail-soft 의도대로이므로 품질 이벤트 존재를 import 성공 조건으로 쓰지 않는다.
- 메모리: (source,hour) 블록마다 grid→admin 집합과 grid→행수 map만 두고 블록이 끝나면 버린다. 실제 블록은 격자 약1만 개 규모로 추정한다. 전체 53만 조합 map이나 rows 사본을 만들지 않는다.

### 6.4 필수 테스트

1. **fixture 기대값(정적 계산, 구현 시 실제 load_input으로 확인)**: 원천당 24시×행정동2×격자`가가00000000`=48행, local에 unlocated 격자`가가99999999` 24행이 더해져 총168행이다. 기대값은 suppressed_rows=27(원천별 행0 3개+local unlocated24), missing_value_rows=3, observed_zero_rows=3, unlocated_rows=24, multi_admin_groups=72(3원천×24시), multi_admin_rows=144다. SHP에만 있고 관측 행이 없는 `가가00000001`은 어떤 카운터에도 나타나지 않아야 한다(행 부재 비합성).
2. **fixture 약점 보완**: 기존 fixture에서는 located 행 전부가 복수행정동이다(144=located 행 수). 그래서 "located 행 수"나 "격자 전체 행 수"로 잘못 구현해도 통과한다. patches로 (a) 한 시각만 단일 행정동인 격자, (b) 같은 격자·같은 행정동이 다른 원천/시각에만 있는 경우, (c) 같은 시각 같은 격자에 다른 원천만 겹치는 경우를 추가한다. 이 세 경우가 multi로 계산되지 않는지 확인한다.
3. **비변경 확인**: summary 전후에 rows의 id·순서·payload, input_sha256·content_sha256이 같은지 확인한다. dry-run/write/replay 각각에서 stdout JSON이 기능 추가 전 기대값과 바이트 단위로 같은지, 반환 dict에 새 키가 없는지 확인한다. exit code도 같아야 한다.
4. **실패 경계·순서**: Settings/validate_local_target/create_db_engine/prepare/persist에 각각 오류를 주입한다. stderr의 etl_quality completed가 해당 실패 etl_stage/etl_run failed보다 먼저 1회 있는지, stdout이 기존 고정 오류 코드인지 확인한다. load_input 실패 시에는 etl_quality가 없고 기존 read_source/import failed만 있어야 한다.
5. **fail-soft**: summary 내부 예외, 카운터 누락·bool·음수·2**63 초과, stderr write/flush 예외, 직렬화 실패 각각을 주입한다. failed+quality_summary_unavailable(counts 없음)이 남거나 이벤트가 생략되는지 확인한다. 어느 경우든 ETL 반환값·DB 결과·예외 종류가 같아야 한다. 0으로 채운 counts가 나오면 실패로 판정한다.
6. **취소 전파**: summary 중 KeyboardInterrupt를 주입했을 때 삼켜지지 않고 import failed 후 전파되는지 확인한다. 정렬 역행(B2) 입력은 failed로 기록되는지 확인한다.
7. **context 제한**: run 밖 호출, source가 living_pop이 아닌 run, run_id=None일 때 출력이 없는지 확인한다. 고정 키 집합만 출력되고 키 순서/값 enum이 고정인지 확인한다.
8. **비노출**: stderr 전체에서 manifest 경로, `가가00000000`·`가가99999999`, `11110530`, `12.34`, `postgresql`, 예외 문자열이 없는지 확인한다. 기존 integration은 stdout만 검사하므로 stderr 검사를 추가한다.
9. **격리 PostGIS 회귀**: 기존 168/24/3/144·replay 동일 UUID/hash·4테이블 rollback·동시 writer 결과가 그대로인지 확인한다.

### 6.5 남는 한계

value_status 실제 문자열, 중복 행 거절 여부, 실제 일자의 복수행정동 규모는 이번 정적 검토 범위 밖이다. 이 이벤트는 공급기관 확인 전의 계수일 뿐이므로, 합산 가능성이나 공간 집계 pending 해제의 근거로 쓰지 않는다.

## 7. Codex 최종 결정·검증

Claude CLI 실제 Read/Edit9턴·permission_denials0·오류없음을 확인하고 §6과 지정 소스를 재검토했다. B1~B5를 수용한다. _counts 결과에6키 완전성 검사를 더하고 source/hour블록 단조증가를 검사한다. admin 원문 동일성·원천 grid_id·value_status observed/suppressed/missing을 사용한다(source.py 확인). 기존 parser의 동일 source/hour/admin/grid 중복 거절 및 모델PK도 유지한다. summary는 성공한 read_source 밖·설정/DB 전에 두며 Exception만 무해화하고 BaseException은 전파한다. missing_value_rows 이름은 유지하고 셀 결측이라는 의미를 README에 명시한다. duration/원천별 세부·인구 합계·행 부재 수는 추가하지 않는다.

### 7.1 구현·실행 검증

- source/hour 블록별 grid→첫admin/행수/다른admin 여부만 보유한다. 원본 grid_id와 admin_code를 비교하며 원본 순서/payload/hash를 수정하지 않는다. `_counts` 결과6키 완전성을 확인하고 bool/음수/64bit초과/누락은 실패로 기록한다. 기존 이벤트 허용키/metadata/스토리지·반환 dict는 유지한다.
- 일반1,276·격리PostGIS184(신규 단위16·통합4)·ruff/format299파일·strict mypy141파일을 통과했다. 기존 Starlette 경고1건이다. 실제 합성168행 기대6카운터 일치·단일행정동과 원천/시각 분리·미좌표 다중행정동·실제0/빈셀/비공개·없는 조합 비생성·input/content hash/payload/순서 보존을 확인했다.
- 잘못된 source/hour순서·카운터형/상한·context/UUID제한·summary/로그 오류 무해화·취소 전파·설정/engine 실패의 고정오류/품질이벤트 순서를 확인했다. 기존 generic sink/직렬화/로그 테스트도 통과했다. 격리 DB의 정상 dry-run/write/replay·후속prepare/persist 실패·신규4테이블 rollback·summary/sink실패에도 실제 저장 및 기존UUID/hash 재사용을 확인했다. CLI stdout에 새필드가 없으며 source metadata와 기존 고정 실패출력을 보존한다.
- 실제 기존 manifest의 READ ONLY dry-run은531,922행·75.235초다(파일읽기/검증/DB내용hash 포함, API 지연이나 SLA가 아님). suppressed_rows57,779·missing_value_rows0·observed_zero_rows0·unlocated_rows24·multi_admin_groups75,360·multi_admin_rows156,786을 출력했다. 별도 READ ONLY SQL의 행/그룹 집계와6개 모두 일치했다. 마지막 두 수는 원천/시각/격자 단위 그룹 및 해당 행 수이며 인구나 고유 격자 수가 아니다.
- 전후 원본4파일 SHA256 및 생활인구4테이블 전체행/geometry 포함 hash·건수/head0010이 같다. 실제dev에는 DML/DDL/원천 재적재/신규 수집/VACUUM·외부LLM호출을 하지 않았다. 실행 helper/결과/로컬 manifest/원본/.env는 추적하지 않는다. 테스트용PostGIS만 별도 loopback55490 UUID이름 DB로 격리했다.

### 7.2 한계·반영

completed는 입력 품질 요약 계산 성공뿐이다. 로그 sink 실패 시 이벤트가 사라질 수 있고 외부 수집기/30일보관·삭제는 여전히 후속이다. 해당 결과로 복수행정동 합산 가능성·행 부재0·SHP공식시점 일치를 확정하지 않는다. 사용자 규칙과 공식근거를 구분해 README/BE CLAUDE/작업계획에 반영했다. 공개API·FE 계약 변경은 없어 FE 요청서 수정 대상이 아니다. 공식근거/브랜드#57/전체감사#78은 대기이며 #90 지정PR·모든CI/CodeQL성공 후 develop 정상Squash한다. 실제 병합 상태는 연결 PR을 따른다.
