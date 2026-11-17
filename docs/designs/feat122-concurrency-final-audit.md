# 병합 후 동시 조회 재검증과 BE 감사 정리 (#122 / #78)

## 목적과 기준

사용자가 PR121을 최신 develop과 대조하고 동시 조회를 새로 검증한 뒤 #122 완료 여부와 #78의 남은 BE 항목까지 정리하도록 요청했다. 기준은 develop02b5288(PR121 병합), FE develop4bf012f이며 FE는 읽기 대조만 한다. root BE의 사용자 브랜치/미추적 MD/ZIP·실제.env를 보존한다. 기존 #120/#122/#124/#128/#130/#134 검증은 각 당시의 기록으로 유지하고 이번 실행을 별도 기록한다.

## 확인된 상태와 검증 계획

- PR121은 기본 풀 대기2→10초이며 SQL3초·풀3/overflow0·예산8을 보존했다. 최신 develop의 ready·이름 제외·AI 문단을 포함한다. 현재 Render는 #134의05790fa/dep-dbs5t55g1s2s73e8vorg이고 풀1/대기15초·SQL10초를 명시한다. 명시된 설정에서 두 버전의 실효 동작 차이가 없는지 소스·환경 hash로 확인하며 배포는 하지 않는다.
- 실제 개발 DB는 기존 localhost5432/spoton_dev를 검증하고 클라이언트 연결에 default_transaction_read_only=on을 추가한 메모리 설정 복사본으로만 조회한다. 설정 원본/실제.env는 변경하지 않는다. head0011·역할·인덱스/배치/행 수를 사전/사후 대조하고 DML·migration·VACUUM·컨테이너 재시작·OS 캐시 삭제는 하지 않는다.
- 개발 API는 현재 FE가 사용하는 이력/월 범위/주변/활동/Risk의5 GET 묶음을 카페·한식, 화면1개(5동시)/3개(15동시), 앱 최초/반복으로 확인한다. 대기2초 비교군과 병합본10초를 분리하고 성공 본문/날짜/배치·집계 일관성을 비교한다. 앱·캐시·연결 풀이 새로 생성된 첫 요청이며 물리 DB 콜드 재현은 아니다.
- 진단은 비공개 실행기에서만 pool TimeoutError와 DBAPI SQLSTATE(특히57014)를 원문 없이 집계한다. 원래 예외·반납·오류 변환 동작은 유지하고 실제 원문·주소·좌표·DSN은 공개하지 않는다. 최신 코드에서 새 오류가 확인되면 해당 원인만 최소 수정하고 회귀 검사한다. 재현되지 않으면 테스트를 늘려 억지로 결론을 만들지 않는다.
- 실제 Render는 현 live/Free/자동배포off·전체 환경값 hash를 읽어 사전/사후 보존을 확인한다. 카페/한식·현재/과거·반경300/500/1000m에서5 GET 동시 묶음과 반복의 응답/상태/집계·ready/CORS를 확인하고 해당 UTC 구간 로그의500/SQL timeout을 원문 없이 집계한다. LLM 생성/절전 강제/부하 상한 검증은 하지 않는다. #134 AI200/실제 브라우저 근거는 기존 실행으로 링크한다.
- #78의 일반음식점 원천 응답 지연은 기존 설정의 키를 메모리에서만 읽어 공식 endpoint에100행·1행 각1회(재시도 없이 제한시간)와 휴게100행1회로 재확인한다. 응답 원문/행/키를 저장하지 않고 상태·시간·계약 검사·건수만 기록한다. 실제 원천 적재/수정은 하지 않는다. 실패는 원인 미확정/외부 연결 문제로 구분하고 재시도·timeout을 늘려 숨기지 않는다.

## 감사 정리와 완료 판정

#122의 동시 조회/무료 풀 검토·한식 B안·AI 활성화·FE CI의 후속 완료 근거를 대조해 해당 제보 점검 범위를 닫을지 결정한다. 모든500·실제 업종 정답·제보18곳 전수·모든 브라우저 수용 검증을 완료로 확대하지 않는다.

#78은 새 근거가 있는 BE 항목(출처 배치 누적, 동시 풀 대기, 브랜드/AI 기반, 운영 배포 등)과 남은 항목(재적재 직후 자동 보호/무중단 보장, 외부 원천 지연, 공식 인구/조건부 근거, 맞춤 정렬, 로그30일 보관/삭제, FE 경계 브라우저 확인)을 분리한다. FE 소스/단위 반영과 이번에 하지 않은 브라우저 재현을 구분하며 FE 구현을 다시 요청하지 않는다. 전체 정상 판정은 미확인 항목이 있으면 보류한다.

기록은 이 설계와 기존 be-system-audit.md/fe-system-audit-request.md·두 Render 운영 안내·BE 작업계획에 필요한 만큼 반영한다. 실제 Claude Code의 이 MD Read/Edit 검토 → Codex 판단 → 재검증/필요 시 수정 → 로컬/CI → develop Squash 순서다. 이번에 실행하지 않은 전체 일반/격리 검사 수를 새 실행으로 쓰지 않는다. 이슈122의 완료는 근거 문서 병합 후 반영하며 #78은 잔여가 있으면 열린 상태를 유지한다.

## 실제 Claude Code 검토

### 범위·성격

- 읽은 파일: 이 MD, `app/db/dependencies.py`, `app/db/session.py`, `app/core/config.py`, `app/services/store_cohort.py`, `app/services/risk.py`(앞부분), `app/services/readiness.py`, `etl/localdata/client.py`, `docs/render-free-validation.md`, `docs/designs/feat120-concurrent-query-500.md`.
- Read와 이 MD Edit만 사용했다. 명령·테스트·DB·네트워크·Git·Render·원천 API는 실행하지 않았고 실제 `.env`·비공개 증빙은 열지 않았다. 아래 내용은 **계획 검토**이며 검토자가 실행한 검증은 없다.

### 종합 판단

**조건부 진행 가능.** 방향(읽기 전용·원문 미기록·배포 없음·#78 열린 상태 유지)은 맞다. 다만 아래 차단 2건은 계획대로 하면 실행 자체가 실패하거나 측정이 오염되므로 실행 전에 방법을 바꿔야 한다.

### 차단 이슈

1. **읽기 전용 강제 방법이 현재 코드로 불가능하다.** `normalize_database_url`은 query 키를 `sslmode·sslrootcert·sslcert·sslkey·sslcrl·application_name`만 허용한다(session.py:12-14, 42-50). `options=-c default_transaction_read_only=on`을 URL 복사본에 넣으면 `DatabaseConfigurationError`로 모든 API가 500, ready는 `configuration_invalid`가 된다. `create_db_engine`의 `connect_args`도 `connect_timeout`만 넘긴다(session.py:68). 코드 수정 없이 하려면 **검증용 uvicorn 프로세스 환경에만 `PGOPTIONS=-c default_transaction_read_only=on`**을 주고(libpq가 읽으므로 API 풀과 readiness의 `psycopg.connect` 모두 적용), 측정 전 같은 환경의 연결 1개로 `SHOW default_transaction_read_only = on`을 확인한다. local의 ready는 역할/읽기 전용을 검사하지 않으므로(readiness.py:126-127) ready200을 읽기 전용 증거로 쓰지 않는다. 이 설정은 세션 기본값이라 권한 경계가 아니며, API 경로 자체도 `SET TRANSACTION READ ONLY`(dependencies.py:49)를 쓴다는 이중 안전장치로만 기록한다.
2. **사전 대조가 "앱 최초" 측정을 데운다.** 컨테이너 재시작·OS 캐시 삭제를 하지 않으므로 사전 단계에서 `stores` 전체 `count(*)`/해시를 돌리면 shared_buffers·OS 캐시가 채워져 첫 묶음이 사실상 웜이 된다. 사전 단계는 카탈로그·소형 테이블(`alembic_version`, 인덱스 정의, `store_import_batches`)과 `pg_stat_user_tables`의 `n_tup_ins/upd/del`·`n_live_tup` 스냅샷으로 한정하고, 정확한 행 수는 **측정 후**에 한 번만 센다. DML 부재는 `n_tup_*` 사전/사후 델타 0으로 판정한다(통계 리셋 여부도 함께 기록).

### 필수 보완

- **앱 최초/반복의 정의**: 최초 = 새 uvicorn 프로세스·빈 앱 캐시·새 풀의 첫 묶음, 물리 DB는 웜일 수 있음. 반복 묶음은 Risk 캐시(TTL 300초, `cache_enabled`)에 걸리므로 Risk의 반복 시간은 DB 시간이 아니다. 풀 대기 비교에는 최초 묶음만 쓰고 반복은 일관성 확인용으로 분리한다.
- **로컬 대기 2초 vs 10초 공정 비교**: 두 비교군 모두 같은 `02b5288` 코드에서 프로세스 환경 `DATABASE_POOL_TIMEOUT=2`/미지정(10)만 바꾼다(pydantic-settings는 프로세스 환경이 `.env`보다 우선하므로 `.env` 수정 불필요). 그 외 SQL3초·풀3/overflow0·`CACHE_ENABLED`·`PGOPTIONS`·요청 파라미터·동시 수는 같게 하고, 비교군마다 새 프로세스, 순서는 2→10→2→10처럼 교차해 DB 버퍼 데움 순서 효과를 상쇄한다. 시작 시 실효 설정(풀/대기/SQL 수치만, DSN 제외)을 기록한다. 같은 데이터임은 응답 meta의 `stores_batch_ids`·`name_exclusion_version`이 모든 실행에서 같고 사전/사후 `n_tup_*` 델타가 0인 것으로 판정한다. 물리 콜드 없이 2초 비교군도 500 0건일 가능성이 높으며, 그 경우 "웜 조건에서 차이 미관측"으로만 쓰고 #120의 콜드 결론을 재확인했다고 쓰지 않는다.
- **진단 실행기의 예외 분류**: `read_only_session`은 `SQLAlchemyError`를 `AppError(INTERNAL_ERROR) from None`으로 바꾸므로(dependencies.py:55-56) 핸들러·로그에서는 원래 클래스가 사라진다. 비공개 실행기에서 `app.db.dependencies.read_only_session`을 감싸 예외를 받으면 `type(exc).__module__/__qualname__`, `getattr(exc.orig, "sqlstate", None)`, 경로 태그, 경과 ms만 기록하고 **같은 예외를 그대로 재발생**시킨다. `str(exc)`·`exc.statement`·`exc.params`는 기록하지 않는다. 분류: `sqlalchemy.exc.TimeoutError`=풀 대기, SQLSTATE `57014`=SQL 시간 초과, `25006`=읽기 전용 위반(발생 시 즉시 중단·보고), `08xxx`/`OperationalError` sqlstate 없음=접속. `SQLAlchemyError` 없이 생긴 500은 `current_provenance`의 출처 불변식 실패(store_cohort.py:109-120) 등 별도 범주로 센다. AI 준비처럼 같은 함수를 이름으로 import한 모듈은 감싸기가 적용되지 않을 수 있으나 이번 5 GET 범위 밖이다. PG 서버 로그는 SQLSTATE/고정 메시지 건수만 세고 `STATEMENT` 행은 읽어 옮기지 않는다.
- **Render 05790fa vs 병합 02b5288**: 배포하지 않으므로 이번 Render 결과는 **05790fa 실행 결과**로 표기한다. 두 commit의 실행 차이가 `database_pool_timeout` 기본값(2→10)·주석뿐임을 `app/`·`migrations/`·`pyproject.toml`·`uv.lock`·`Dockerfile` diff로 확인하고, Render 환경에 `DATABASE_POOL_TIMEOUT` 키가 **존재하고 값이 15**인지 직접 확인한다. 키가 없으면 두 버전의 실효 대기가 2초/10초로 달라지므로 hash가 이전과 같다는 것만으로 동등성을 주장하지 않는다. 앱은 예외 클래스를 로그에 남기지 않으므로 Render의 500은 경로·상태·시각 분포로만 분류하고 원인을 단정하지 않는다.
- **Render 실행 안전장치**: 절전 복귀는 health/ready200까지 별도 기록하고 측정에서 제외한다. 5 GET 묶음은 한 번에 하나씩 순차 실행하고 15동시는 하지 않는다(풀1). 중단 조건(예: 연속 500 2묶음 또는 FE 일반 제한 45초 초과)을 미리 정한다. 로그 조회 구간은 UTC 시작/종료로 고정하고 Free 로그 보존 한계로 조회가 불완전하면 그렇게 기록한다.
- **원천 100/1 제한 호출**: `LocalDataClient._fetch_page`는 전송 오류·429/502/503/504에 최대 3회 재시도·대기한다(client.py:25-27, 215-237). "재시도 없음"을 지키려면 프로브마다 `max_requests=1` 새 클라이언트를 쓰고, 두 번째 시도가 `request_budget`으로 막히면 원래 원인(전송/일시 상태)과 함께 "재시도 차단"으로 기록한다. `numOfRows`는 `PAGE_SIZE` 고정(client.py:210)이라 1행 프로브는 `_fetch_page`로 할 수 없으므로 같은 `httpx.Timeout(connect5/read20)`과 `_suppress_http_url_logs` 아래 별도 1회 GET 후 `_parse_page`로 계약만 검사한다. 총 3회(일반음식점 100·1, 휴게 100), 고정 관청 코드 1개, 순차 실행이다. 기록은 상태 코드·경과 시간·계약 결과 코드·`totalCount`·행 수만 하고, 예외는 클래스명만 남긴다(httpx 예외/요청 객체에 serviceKey가 든 URL이 있으므로 `str(exc)`·`request.url` 금지). 실패 시 timeout을 늘리거나 재실행해 성공으로 바꾸지 않는다. 원천 API가 시간 초과하면 그대로 "외부 지연 재확인"으로 기록한다.

### 이슈 정리 판단

- **#122**: 이번 로컬·Render 실행에서 분류되지 않은 500이 없을 때만 닫는다. 기존 문서의 "unmatched500 두 건(원인 미확정)"은 #122와 함께 사라지지 않게 #78 잔여 또는 별도 후속으로 **명시적으로 이관**한 뒤 닫는다. 새 500이 관측되면 닫지 않고 분류 결과만 기록한다.
- **#78**: 열린 상태 유지가 맞다. 이번 근거로 갱신할 수 있는 항목은 "동시 풀 대기(로컬 웜 조건)", "운영 05790fa 동시 묶음", "원천 지연 재관측(3회)"뿐이며, 원천 지연은 관측 1회분이라 해소로 쓰지 않는다.
- 결과 문서에는 실제 실행한 항목·횟수만 쓰고, 기존 #120/#122/#124/#128/#134 수치와 섞거나 이번 실행으로 표기하지 않는다.

### 비차단 제안

- Render 조합(업종2×시점2×반경3×최초/반복=24묶음·120요청)은 풀1 Free에 비해 많다. 반경 500m 기준 4묶음+반복 정도로 줄이고 300/1000m은 한식 최신만 두는 쪽이 부하·로그 분석 모두 낫다.
- 로컬 15동시는 AnyIO 기본 스레드 40 이내라 문제없지만, 비교 결과를 부하 상한 근거로 쓰지 않는다는 #120 한계를 그대로 인용한다.

## Codex 결정·실행 결과

### 실행 전 결정

- B1을 반영해 URL에 허용되지 않은options를 넣지 않는다. 실제 API와 같은 create_db_engine을 만든 뒤 진단기에서만 psycopg connect 이벤트로 read_only=True를 설정하고 checkout마다 속성을 확인한다. 같은 연결의 transaction_read_only=on을 실제 확인하며 API의 SET TRANSACTION READ ONLY도 유지한다. 역할/서버 설정 변경이나 보안 경계 승격이 아니다.
- B2를 반영해 최초 요청 전에 stores 전체 count/hash를 하지 않는다. head·소형 배치·인덱스 정의·통계 reset/행 변경 카운터만 사전 대조하고 정확한 행 수는 최종 측정 뒤1회만 센다.
- 비교군마다 별도 자식 프로세스·새 uvicorn/앱/캐시/풀을 만들고 카페는2→10, 한식은10→2 순으로 실행한다. 최초 묶음은 앱 최초이며 물리 DB의 캐시 상태가 통제되지는 않는다. 반복 Risk 시간은 앱 캐시가 포함되므로 DB 쿼리 시간으로 쓰지 않는다.
- read_only_session 바깥에서는 원래 SQLAlchemyError가 이미 AppError로 변환된다. 따라서 실행기에서 QueuePool의 원래 _do_get을 그대로 호출하며 TimeoutError만 원문 없이 집계/재발생시키고 DBAPI는 engine handle_error의 클래스·SQLSTATE만 집계한다. 서비스 코드·예외 변환·연결 수·timeout은 바꾸지 않는다.
- Render는 현재/과거500m의카페·한식4조건×최초/반복(40GET)과 한식 최신300/1000m×최초/반복(20GET), 합계60GET으로 제한한다. 한 번에5개 묶음1개만 실행하고45초 초과 또는 연속 실패2묶음이면 중단한다. 초기health/ready와 계측 UTC 구간을 분리하며 배포본05790fa/명시대기15초를 직접 확인한다.
- 원천은 별도httpx의 단발 GET3회로만 검사하고 자동 재시도하지 않는다. 일반100행과휴게100행은read20초, 일반1행은과거동일조건read30초를 유지하며 동작 client 기본값을 변경하지 않는다. 요청/응답 원문·키·원천 행을 출력/저장하지 않는다.
- 이번 새 오류가 없고 완료 근거가 갖춰지면 #122 범위를 닫되, 과거unmatched500 두 건의 원인 미확정은 #78에 명시적으로 남긴다. #78의 FE 반영 소스/단위 검사는 전체 경계 브라우저 확인과 구분한다.

### 새 실행 결과와 판정

- 로컬 actual HTTP 정상uvicorn: 카페·한식 ×5/15동시 ×대기2/10초 ×새프로세스최초/반복=160건 모두200. 병합본10초80건·비교2초80건, pool TimeoutError/SQLSTATE57014·25006 0·성공본문digest/날짜/배치/집계일치. 코드변경을추가할오류는없었다. 최초최대3.9412초/반복최대1.0356초는각SQL3초와다른HTTP시간이며2/10초성능차이는입증하지않았다.
- 연결read_only=True/transaction_read_only=on을확인했다. 사전소형metadata·쓰기카운터와사후값이같았고실제.env도같았다. 측정후stores689,440행·head0011. 실제DB재시작/캐시삭제/DML/DDL/VACUUM은0이다.
- 두실행commit의diff는app/core/config.py기본값2→10·주석뿐이며다른실행파일/etl/migration/Docker/lock은동일하다. Render의명시pool_timeout15초를직접검증하고배포05790fa/dep-dbs5t55g1s2s73e8vorg와17개envhash·Free/autoDeployoff를사전/사후일치시켰다. 병합본02b5288은배포하지않았다.
- Render5GET동시60건·추가snapshot4건·ready12건200,같은조건반복본문일치·목록=활동=Risk경쟁점수·snapshot목록/상태합계일치. 허용origin3개의preflight6/실제GET3·미허용1차단. 최초/반복묶음중앙값8.647/4.139초,최장13.691초다. 현재/과거500m카페·한식과최신300/1000m한식조건으로제한했고추가부하/절전강제/LLM은0이다.
- 계측UTC2026-11-14T13:37:52~13:39:09. 앱로그101건/2페이지에서HTTP500이상0,FreeDB로그77건/1페이지에서statement timeout/읽기전용위반0. 원문/STATEMENT/주소·키는기록하지않았다. 카운터는수집구간내관측이며전체오류부재증명이아니다.
- 원천은고정서울관청1곳·각1회·재시도0: 일반100행20.504초ReadTimeout,일반1행28.730초200/계약통과/total30174,휴게100행3.090초200/계약통과/total7303. 원문/행저장0·적재0이며외부지연이남았다고판정한다. 일반1행성공은전체수집/100행해소를뜻하지않는다.
- FE4bf012f소스의F1~F5반영을읽기대조하고단위108개를새로실행해통과했다. F2~F5최초반례의전체브라우저/지도변경·언마운트재현은이번미실행이며#134공개AI·브라우저근거를새실행으로쓰지않는다.
- #122완료범위와#78잔여를BE감사/FE전달·두Render안내·작업계획/CLAUDE에정리했다. 새unmatched500은없어추가제품코드수정이필요하지않다. 기존두unmatched500의원인미확정은#78로명시이관하고원천지연/재적재자동보호/공식자료/맞춤자격/로그30일/FE경계를남긴다. 문서병합후#122를닫고#78은유지한다.

실제Claude Code계획검토는exit0/is_error=false·12턴·권한거절0건이었다. 제품코드/모델/migration/환경값/배포수정은없으며본문의단위1,735·격리271은직전PR121근거와이번문서CI를분리해기록한다.
