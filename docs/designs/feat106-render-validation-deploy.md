# #106 Render BE 검증 배포

> 아래 최초안과 Claude 의견 중 충돌하는 항목은 마지막 **Codex 최종 결정**을 따른다.

- 이슈: https://github.com/sigoreu-jabeujong/SpotON-BE/issues/106
- 상태: 구현 전 설계. 실제 Claude Code 검토 후 보완한다.
- 범위: DB 풀·워커 예산, Docker 실행, DB readiness, 조회 전용 Render 내부 연결, 검증 배포.
- 선행: Render `spoton-db-check` PostgreSQL17.11/PostGIS3.6.2 복원·24API 비교 통과. `spoton_api`는 연결 제한8·기본READONLY·문장3초이며 암호는 현재 Windows 사용자의 DPAPI 저장소에만 있다.

## 1. 결정안

1. Settings에 `database_pool_size=3`(1~20), `database_max_overflow=0`(0~20), `database_pool_timeout=2`초(0.1~30), `web_concurrency=1`(1~8), `database_connection_budget=8`(1~1000), `database_expected_revision="0011"`(숫자4자리)를 추가한다. `2 * web_concurrency * (pool_size+overflow) <= connection_budget`를 검사한다. 2는 단일 인스턴스의 교체 배포 중 구·신 인스턴스 동시 실행 예산이다. 실제 플랫폼 인스턴스 수·DB 역할 한도를 자동 발견하는 기능은 아니며 Render는 인스턴스1·자동확장 없음으로 고정한다. 3*1*2=6개로 역할8 안에서2개 여유를 둔다. Settings가 ETL에도 쓰이므로 기존 CLI 보호·지역DB 동작을 유지한다.
2. `create_db_engine()`에 pool_size/max_overflow/pool_timeout을 명시하고 기존 lazy connect, pool_pre_ping, 숨김 파라미터, connect_timeout, READONLY/RR·SQL3초·캐시 의미를 유지한다. 워커마다 독립 엔진이다. lease timeout은 SQL·HTTP 예산과 구분한다.
3. `app.runtime` Docker 진입점이 PORT(기본10000,1~65535)·Settings를 검증하고 `uvicorn.run("app.main:app",host="0.0.0.0",port=...,workers=...,access_log=False,timeout_graceful_shutdown=30)`을 실행한다. 사전 DB 연결·migration·ETL을 실행하지 않는다. 기존 로컬 uvicorn 사용법은 유지하며 배포는 이 진입점만 사용한다.
4. 기존 `/api/health`는 무DB liveness로 유지한다. 새 `/api/ready`는 기존 공통 응답·no-store·안전한 INTERNAL_ERROR500을 사용하고 READONLY/RR 세션에서 migration revision을 확인한다. staging/production에서는 기본READONLY, 비관리 역할, public 스키마 CREATE·DB CREATE/TEMP 없음, 앱 테이블 쓰기 권한 없음, 역할 연결 상한≥설정 예산도 검사한다. 모델·쿼리는 서비스에 둔다. 실패 시 비밀값·현재 역할·DB호스트·실제 revision을 응답하지 않는다. 운영용 추가 경로이며 기존 FE 계약은 변경하지 않는다.
5. Docker는 Python3.11-slim-bookworm digest 고정, uv0.13.7 digest 고정, uv.lock --locked no-dev/non-editable 설치, multi-stage·비root UID10001을 사용한다. runtime에는 설치된 app+etl 패키지가 모두 필요하다(app에서 etl 주소/브랜드 유틸 import). .dockerignore는 앱/etl/lock/프로젝트metadata만 허용해 .env·docs·datasets·data·덤프·.git·.venv가 build context에 들어가지 않게 한다. secret ARG/ENV를 이미지에 쓰지 않는다.
6. Render에는 같은 워크스페이스·싱가포르의 검증 웹서비스1개를 Docker/GitHub public repo develop로 만든다. 검증 BE는 유료 최소 등급0.5CPU/512MB로 시작하고 실제 메모리/응답을 확인한다. 자동배포는 끄고 검증한 commit을 배포한다. healthCheckPath=/api/ready. DB는 조회 전용 계정+내부 URL+sslmode=require(내부 인증서는verify-full 미지원)를 쓴다. 외부 검증 PC의 DB/32 허용 목록은 확장하지 않는다.
7. 실제 .env는 읽어 출력/수정/커밋하지 않는다. 필요한 런타임 키(Kakao REST/Juso/LLM)만 Settings의 SecretStr에서 메모리로 받아 Render 비밀 환경변수에 설정하며 정부ETL/DB관리자 키는 전송하지 않는다. API 앱 한도·LLM 한도는 현재 설정과 명시된 제한을 유지한다. CORS는 현재 허용된 localhost5173만 우선 사용하고 FE 공개 origin은 별도 전달/합의 후 추가한다. FE 파일·설정은 직접 바꾸지 않는다.

## 2. 검사·완료 조건

- 설정 범위·2배 교체 예산의 경계, 실제 QueuePool 용량/overflow/대기 실패·반환 복구, lazy connect·안전 오류 회귀.
- PORT/워커 실행 인자 검증, health 무DB 유지, readiness의 DB실패/미준비revision/관리계정 차단 및 READONLY 역할 성공.
- 일반 전체 pytest·ruff·format·mypy, 별도 일회용 PostGIS의 통합 suite. 개발DB에 파괴적suite를 실행하지 않는다.
- Docker 이미지 실제 build/start, nonroot·런타임dependency·context비밀파일미포함, 외부 Render read-role DB로 ready 및 대표요청·종료 확인. 실행중인 로컬 개발 서버와 DB는 그대로 둔다.
- GitHub PR·CI/CodeQL 확인 후 일반 develop Squash. 동일 artifact/commit의 Render deploy, 배포HTTP ready·대표API·CORS·소규모동시요청·조회계정/내부SSL 설정 확인. 실제 앱LLM 호출은 배포 확인에 필수로 쓰지 않는다.
- 소유자·API암호·URI·키를 gh issue/PR/로그/문서에 포함하지 않는다. 비밀값 scan과 수동 diff review를 수행한다.
- 배포 URL·commit·인스턴스/풀 예산·readiness·관측 성능·제약을 문서와 BE측 FE 전달 요청서에 기록한다. FE 연결·브라우저 전체·운영이전·원격ETL·실제LLM안전성 완료로 주장하지 않는다.

## 3. Claude Code 검토 요청

이 MD 파일만 Read/Edit한다. 코드·다른문서·Git·DB·네트워크·.env·키에는 접근하지 않는다. 이 문서 전체가 제공된 입력이며 실제 코드/DB/공식문서를 읽지 않은 한계를 유지한다. 풀 예산/교체배포·readiness의 권한/5초health 제한·Docker 패키지/secret·readrole내부TLS·런타임키/공개API·자동배포·검사/종료의 누락을 검토하고 필요한 보정을 이 파일에 직접 기록한다. 통상 선택은 최선안을 제안하고 Codex가 실제 코드·격리·Docker·Render로 최종 대조한다.

검토 결과는 이 절 아래에 추가한다. 완료/검증을 수행한 것으로 꾸미지 않는다.

### 3.1 Claude Code 검토 결과 (2026-11-13, 문서 단독 검토)

한계: 이 파일만 읽었다. 코드·DB·Render/uv/uvicorn 공식 문서·실제 버전/digest는 확인하지 않았다. 아래에서 "[확인필요]"로 표시한 플랫폼 동작은 기억에 기반한 것이며 Codex가 실제 문서·환경과 대조해야 한다. 아무것도 실행·검증하지 않았다.

종합: 방향(무DB liveness와 DB readiness 분리, 2배 교체 예산, 비root·digest 고정, 런타임 키 최소화)은 타당하다. 다만 아래 **필수(P1)** 항목은 그대로 구현하면 배포 실패·연쇄 재시작·예산 초과·키 남용으로 이어질 수 있으므로 1절에 반영한 뒤 구현할 것을 권장한다.

#### P1 — 구현 전 반영 권장

1. **readiness가 health check 제한 시간 안에 끝나야 한다(1·2·4·6항).** 최악 경로가 `pool_timeout(2s) + connect_timeout(현재값 미확인) + pre_ping 왕복 + 권한검사 SQL(역할 상한 3s)`이라 health check 제한(문서 기준 5초)을 넘을 수 있다. 보정:
   - `/api/ready` 전체에 하드 예산(권장 ≤2.5s)을 두고, readiness 전용으로 checkout 대기를 짧게 하며(권장 0.5~1s) 트랜잭션 안에서 `SET LOCAL statement_timeout = '1s'`를 쓴다(READONLY 트랜잭션에서도 SET은 허용됨). connect_timeout 실제 값을 확인해 합이 예산 안에 들어가게 한다.
   - **결과 캐시**: 성공 결과를 워커별 메모리에 TTL(권장 10~15s) 동안 캐시하고, 동시 probe는 진행 중인 검사 하나를 공유(single-flight)한다. Render probe가 몇 초마다 DB 연결 1개를 점유하면 pool 3개 중 1개를 계속 쓰게 된다. 실패 결과는 캐시하지 않거나 짧게(≤2s) 캐시한다.
   - **검사 분할**: 무거운 권한·역할 검사(4항)는 프로세스 시작 후 첫 성공 시 1회 + 긴 TTL(예: 5분)로 하고, 매 probe에서는 `SELECT 1` 수준 + revision 확인만 한다.
   - **부하 시 연쇄 실패**: 사용자 요청이 pool을 모두 점유하면 readiness가 pool timeout으로 실패 → Render가 unhealthy로 판정·재시작 → 남은 인스턴스 부하가 증가하는 연쇄가 생길 수 있다. 캐시된 최근 성공이 TTL 안에 있으면 pool 포화만으로는 not-ready로 바꾸지 않는다. Render의 연속 실패 기준·재시작 동작은 [확인필요].
2. **pool 포화 시 오류 계약(2·4항).** sync 엔드포인트라면 FastAPI threadpool(기본 약 40)이 pool 3개를 기다리므로 동시 요청 4개부터 2초 뒤 `sqlalchemy.exc.TimeoutError`가 난다. 이 예외를 일반 API에서는 비밀값 없는 503(서비스 일시 불가) 또는 기존 공통 오류 코드로 매핑하고, 500 스택이 로그·응답에 원문 그대로 나가지 않는지 테스트한다. readiness 실패 응답도 500보다 **503**이 의미에 맞다(Render는 2xx/3xx가 아니면 모두 실패로 본다 [확인필요]). 기존 공통 응답에 503 코드가 없을 때만 500을 유지하고 그 이유를 기록한다.
3. **`default_transaction_read_only`는 보안 경계가 아니다(4항).** 이 설정은 기본값일 뿐이라 해당 역할이 `SET TRANSACTION READ WRITE`로 쓰기 모드로 바꿀 수 있다. 실제 경계는 권한이 없다는 사실이다. readiness의 권한 검사를 다음으로 구체화한다:
   - `pg_roles`: `rolsuper/rolcreaterole/rolcreatedb/rolreplication/rolbypassrls` 모두 false.
   - 앱 스키마 안의 어떤 객체(테이블·시퀀스·함수·스키마)도 소유하지 않는다(소유자는 GRANT 없이 ALTER/DROP 가능).
   - `pg_write_all_data`, `pg_database_owner`, `pg_execute_server_program`, `pg_write_server_files`, `pg_read_server_files`, 그리고 앱 소유 역할에 `pg_has_role(..., 'USAGE')`이 없다(상속 경로 포함).
   - 스키마의 **모든** 테이블(PostGIS `spatial_ref_sys` 포함)에 INSERT/UPDATE/DELETE/TRUNCATE가 없고, 시퀀스에 UPDATE가 없다. `public` CREATE, DB CREATE/TEMP가 없다.
   - `alembic_version`에 SELECT가 있다(없으면 revision 확인이 권한 오류로 계속 실패한다 — 복원 DB의 GRANT 확인 필요).
   - `rolconnlimit = -1`(무제한)은 "상한 미설정"이므로 staging/production에서 실패로 처리한다(역할 상한을 예산 보호 장치로 쓰는 전제와 맞춘다).
4. **역할 연결 예산 8에는 앱 외 세션도 포함된다(1항).** 교체 배포 중 6개를 쓰면 남는 것은 2개뿐이다. Codex/외부 검증 PC가 `spoton_api`로 psql·통합 확인을 하면 같은 한도를 소모해 배포 중 신규 인스턴스 readiness가 실패할 수 있다. 보정: 배포 창에서는 외부 `spoton_api` 세션을 0~1개로 제한하고, 외부 검증은 가능하면 별도 역할을 쓰도록 2절에 명시한다. 4항의 "역할 연결 상한 ≥ 설정 예산"은 정의를 `rolconnlimit >= database_connection_budget`로 고정하고, 인스턴스 수는 자동 발견하지 못한다는 점(수동 scale-out 시 예산 위반)을 운영 제약으로 기록한다.
5. **`WEB_CONCURRENCY` 환경변수 충돌(1·3·6항).** Render가 일부 런타임에 `WEB_CONCURRENCY`를 자동 설정할 수 있다 [확인필요]. Settings 필드 이름이 이 환경변수와 연결되면 의도치 않게 워커 수가 바뀌어 예산 검증에 실패하거나(그나마 안전한 쪽) 예산이 달라질 수 있다. 보정: Render 환경변수에 `WEB_CONCURRENCY=1`을 명시하고, 실제 env 키 이름(prefix 여부)을 문서에 적는다.
6. **graceful shutdown 30초와 Render 종료 대기의 경합(3항).** Render는 SIGTERM 후 기본 약 30초 뒤 SIGKILL을 보낸다 [확인필요, 서비스 설정 `maxShutdownDelaySeconds`]. 둘 다 30초면 정리 도중 강제 종료될 수 있다. 보정: `timeout_graceful_shutdown=20`(또는 Render 종료 대기를 45s 이상으로 설정)을 쓰고, lifespan 종료에서 `engine.dispose()`를 호출해 구 인스턴스 연결을 빨리 반환한다(교체 예산 회수). Docker는 exec 형식 `CMD ["python","-m","app.runtime"]`로 python이 PID1이 되어 SIGTERM을 직접 받게 한다(shell 형식 금지).
7. **"동일 artifact" 표현 수정(2절 5번째 항목).** Render가 GitHub에서 Docker로 빌드하면 CI·로컬에서 빌드한 이미지와 **다른 artifact**다. digest 고정과 `--locked` 설치로 재현성은 높지만 같은 artifact는 아니다. 권장: 문구를 "동일 commit(+고정 base digest·lock)"으로 고치고, Render 배포 로그의 commit SHA가 검증한 SHA와 같은지 확인한다. 진짜 동일 artifact가 필요하면 레지스트리 이미지 기반 서비스로 바꾸되 이번 검증 범위에서는 불필요하다.
8. **공개 엔드포인트의 키 남용(7항).** 검증 웹서비스도 인터넷에 공개되며 Render web service는 inbound IP 제한이 없다 [확인필요]. Kakao/Juso/LLM 키를 쓰는 경로가 공개되면 비용·쿼터가 소모된다. 보정:
   - 배포 확인에 실제 LLM 호출이 필수가 아니므로 **검증 배포에서는 LLM 키를 넣지 않거나** 기능 플래그로 LLM 경로를 끄는 것을 권장한다(키가 없을 때 안전한 오류/폴백이 되는지 테스트). 넣는다면 공급자 콘솔의 사용량 상한을 별도로 설정한다.
   - 앱의 IP 기반 한도가 있다면 Render 프록시 뒤에서 모든 요청이 프록시 IP로 보여 전역 제한이 되거나, `forwarded_allow_ips="*"`로 X-Forwarded-For를 무조건 신뢰하면 클라이언트가 위조할 수 있다. uvicorn의 `proxy_headers` 동작과 실제 한도 키를 확인하고 결정을 기록한다 [확인필요].
   - production에서 `/docs`·`/redoc`·`/openapi.json` 노출 여부를 결정한다(기존 FE 계약과 무관하면 비활성 권장).
9. **Settings가 ETL 키를 필수로 요구하면 배포가 실패한다(1·7항).** Settings가 ETL과 공용이므로 정부 ETL·관리자 DB 키가 필수 필드라면 Render에 전송하지 않는 정책과 충돌한다. API 런타임에서 해당 필드가 optional인지 확인하고, 반대로 Kakao/Juso 등 API 필수 키는 staging/production에서 누락 시 시작 단계에서 바로 실패(비밀값 미출력)하게 한다. `env_file=.env`가 컨테이너에 없을 때도 정상 동작해야 한다.

#### P2 — 보완 권장

10. **expected revision 이중 관리.** `"0011"`을 Settings 기본값에 하드코딩하면 다음 migration 때 잊기 쉽다. 이미지에 alembic 스크립트를 넣지 않는다면(5항 allowlist) 현재 방식은 유지하되, CI 테스트로 `Settings().database_expected_revision == alembic head`를 검증한다. revision 형식 검증(숫자4자리)이 기존 revision 명명 규칙과 맞는지도 확인한다. 실제 revision은 응답하지 않고 서버 로그에만 남긴다(호스트·역할 제외).
11. **Docker 세부(5항).**
   - uv 이미지 `0.13.7`과 digest가 실제로 존재하는지 확인 [확인필요]. builder: `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `UV_PYTHON_DOWNLOADS=never`, 의존성 레이어(`--no-install-project`)와 프로젝트 레이어를 나눠 캐시한다.
   - venv는 shebang에 절대경로가 들어가므로 builder와 runtime의 경로를 같게 한다(예: `/app/.venv`). runtime에는 `PATH`, `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, `USER 10001:10001`(숫자) 설정, uv 바이너리는 runtime에 복사하지 않는다.
   - `.dockerignore` allowlist(`*` 후 `!app/ !etl/ !pyproject.toml !uv.lock`)를 쓸 때 `pyproject.toml`의 `readme`/`license-files`가 참조하는 파일이 빠지면 빌드가 실패한다. 허용한 디렉터리 안에서 다시 `**/.env*`, `**/__pycache__`, `**/*.dump`, `**/*.sql.gz`를 제외한다.
   - etl 패키지와 그 의존성(예: 데이터 처리 라이브러리)이 512MB 메모리에 미치는 영향: 앱 시작 후 RSS와 대표 요청 중 최대 RSS를 측정해 기록한다. 큰 import가 app 경로에서 끌려오면 공용 유틸 분리를 후속 이슈로 남긴다.
   - 비밀값 미포함 검사는 build context뿐 아니라 최종 이미지 레이어(`docker history`, 파일 목록)와 `docker inspect`의 Env에서도 수행한다.
12. **내부 TLS [확인필요].** Render 내부 URL이 SSL을 지원하는지, `sslmode=require`가 내부 호스트에서 실제로 협상되는지 확인되지 않았다. 지원하지 않으면 연결이 바로 실패한다. 배포 후 `SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()`로 확인하고 결과(값만, 호스트 제외)를 기록한다. require는 서버 인증을 하지 않으므로 "암호화만, 인증서 검증 없음"이라는 제약을 문서에 남긴다. 암호에 특수문자가 있으면 URL 인코딩이 필요하다.
13. **pool 세부.** `pool_recycle`(예: 1800s)을 함께 두면 플랫폼 idle 끊김 대응이 pre_ping만 쓸 때보다 안정적이다(선택). `pool_timeout`은 checkout 대기만 의미하고 새 연결 생성은 `connect_timeout`이 지배한다는 점을 2항에 명시한다. workers>1이면 uvicorn이 워커 프로세스마다 앱을 import하므로 엔진이 import 시점에 연결하지 않는다는 기존 lazy connect가 필수다.
14. **비밀 전달 경로(7항).** DPAPI에서 꺼낸 값과 Render API 키를 명령행 인자·셸 히스토리·로그에 남기지 않는다(stdin/메모리 전달). Render API로 env를 설정할 때는 다른 env를 덮어쓰는 일괄 PUT인지 개별 키 갱신인지 확인한다 [확인필요].
15. **롤백·정리 조건 누락.** 2절에 추가한다: (a) readiness 실패나 오류율 증가 시 Render 이전 배포로 롤백하는 절차와 판단 기준, (b) 검증 종료 후 서비스 유지/일시정지/삭제 결정과 비용 책임자, (c) 실패 배포가 남긴 DB 세션이 없는지 `pg_stat_activity`(앱 역할 기준 개수만)로 확인.

#### 2절에 추가할 테스트(제안)

- 예산 경계(budget=8): `(pool,overflow,workers)=(4,0,1)`·`(3,1,1)` 통과(=8), `(5,0,1)` 실패(10), `(3,0,2)` 실패(12), `(4,1,1)` 실패(10). budget 상한 1000과 workers 8 조합도 확인.
- pool: 3개 점유 상태에서 4번째 요청이 약 `pool_timeout` 뒤 안전 오류(비밀값·호스트 없음), 반환 후 즉시 복구.
- readiness: 예산 초과 시간 안 응답(DB 지연을 흉내 내서 하드 예산 확인), 캐시 hit 시 DB 미접속, 동시 probe single-flight, 역할이 테이블 소유자/`pg_write_all_data` 멤버/`rolconnlimit=-1`일 때 not-ready, `alembic_version` 권한 없음 → not-ready(원인 비노출).
- runtime: `WEB_CONCURRENCY`·`PORT` 경계/비숫자, SIGTERM 시 graceful 종료와 `engine.dispose()` 호출.
- 키 누락: LLM 키 없음에서 해당 경로가 안전하게 비활성/오류, API 필수 키 누락 시 시작 실패(값 미출력).

#### Codex 최종 대조 체크리스트

- [ ] connect_timeout 실제 값과 readiness 최악 시간 합계
- [ ] Render health check 제한 시간·실패 판정·재시작 동작, `WEB_CONCURRENCY` 자동 설정 여부, 종료 대기 기본값
- [ ] Render 내부 URL SSL 지원 여부
- [ ] uv 0.13.7 / python 3.11-slim-bookworm digest 실재 여부
- [ ] Settings의 ETL 필드 필수 여부, env 키 이름
- [ ] 기존 공통 오류 코드에 503 존재 여부, 앱 rate limit의 키(IP 등)와 프록시 헤더 처리
- [ ] 복원 DB에서 `spoton_api`의 `alembic_version` SELECT·객체 소유 여부

## 4. Codex 최종 결정

- 교체 예산은 readiness 연결까지 포함한 `2 * workers * (pool_size + max_overflow + 1) <= budget`이다. 기본은 `2*(3+0+1)=8`이다. Render 인스턴스1·자동 확장 없음·WEB_CONCURRENCY=1을 명시한다. 배포 중 외부 reader 검증 세션을 열지 않는다. 관리자 관측은 별도 계정이다.
- readiness는 API QueuePool과 독립적인 직접 연결1개, connect_timeout1초·SQL750ms·HTTP2.5초를 사용한다. 단일 실행 잠금과 성공10초/실패1초 캐시를 둔다. HTTP 취소가 연결 스레드를 즉시 중단시키지는 않으므로 잠금을 연결 정리까지 유지한다. 모든 권한 검사를 같은 짧은 쿼리에서 수행한다.
- 기존 INTERNAL_ERROR/500 계약을 유지한다. 일반 API pool timeout도 기존 안전한 DB 예외 매핑을 따른다. 운영 probe는 비정상 HTTP로 배포를 차단하며 503 신규 오류 계약은 추가하지 않는다.
- 기본 READ ONLY만으로 권한을 판단하지 않는다. revision, 역할 특권, 쓰기 역할, public/DB CREATE·TEMP, 모든 public 테이블·시퀀스 쓰기, 객체 소유 및 유한 역할 연결 제한을 검사한다. 복원 시험에서 별도로 READ WRITE 상태의 INSERT/CREATE/TEMP/SET ROLE 거절을 확인했다.
- Render 종료 대기는45초, Uvicorn graceful shutdown은30초다. lifespan에서 풀을 dispose한다. PORT 기본10000이며 프로세스는 비root로 실행한다.
- 검증 서비스에는 Kakao REST·Juso 조회 키만 메모리로 전달한다. **LLM 키는 넣지 않는다.** 주소 조회는 기존 외부 서비스 예산을 따른다. ETL 키·소유자 DB URL은 전달하지 않는다. CORS는 현재 localhost5173만 허용하며 FE 공개 주소 확정 후 추가한다.
- Render 내부 연결의 `sslmode=require`는 암호화만 제공하며 서버 인증서 검증을 보장하지 않는다. 외부 검증은 verify-full이다. 배포 후 실제 API 세션의 pg_stat_ssl을 관리자 계정으로 확인한다.
- 동일 artifact가 아니라 **동일 commit + 고정 base digest + uv.lock**을 검증한다. 실제 이미지 빌드와512MB/0.5CPU 실행으로 app+etl 설치 및 메모리를 확인한다. CI는 expected revision과 Alembic head 일치를 검사한다.
- Render health check의5초 제한·비정상 상태 판정 및 Docker 실행 기준은 공식 문서를 확인했다. `/docs`는 기존 동작을 유지한다. 신규 proxy 신뢰·IP 기반 한도 로직을 추가하지 않는다. 기존 LLM 한도는 provider 공통 제한이며 이번 검증에서 키를 생략한다.
- 최초 배포 실패 시 기존 개발 환경으로 계속 개발한다. 정상 배포 이후 readiness/대표 조회가 실패하면 Render 이전 성공 배포로 되돌리고 DB 쓰기/ETL을 중단한다. 현재 서비스는 검증용 유료 서비스로 유지하며 비용이 계속 발생한다. 임의 삭제·운영 전환은 하지 않는다.

## 5. 로컬 검증 결과

- ruff check/format, mypy app·etl·migrations 통과. HTTP probe timeout을 포함한 신규 모듈31건과 최종 일반 전체1595건을 통과했다. 기존 Starlette/httpx deprecation 경고1건이 남아 있다.
- 격리 PostGIS17/3.7 테스트251건 중250건 통과, 신규 ready 경로 때문에 OpenAPI 기대 목록1건 실패. 기대 경로를 수정한 뒤 해당 검사를 재실행해 통과했다. CI에서 전체 재실행한다. 실제 QueuePool 초과 대기/반환 복구, readiness SQL·revision 불일치·배포 관리자 차단을 포함한다.
- Docker 실제 build, 0.5CPU·512MB 제한에서 health/ready/Risk200, UID10001, runtime에 .env/.git/pytest 없음, 이미지 ENV에 런타임 비밀 없음 확인. Python base 이미지의 공개 GPG_KEY를 자체 비밀로 오인한 검사 조건은 실제 애플리케이션 비밀 이름 검사로 수정했다. 관측 메모리82.97MiB이며 최대 부하 수치는 아니다.
- 이 이미지 + Render 조회 역할의 외부 TLS verify-full 연결에서 로컬 DB와24API 전체 JSON 일치(정상22·오류422 2건), 반경 경계3건, 동시3의6요청을 통과했다. 최장 단일 관측2.297초이며 네트워크 포함 전체 응답 시간이지 SQL SLA 검증이 아니다.
- Render 서비스 생성·내부 TLS 연결·공개 URL·최종 commit의 실배포 검증은 이 단계에서는 아직 수행하지 않았다.
