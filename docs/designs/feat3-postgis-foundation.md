# 작업 3: PostgreSQL·PostGIS 연결과 마이그레이션 기반

## 상태와 범위

- 이슈: [#10 PostgreSQL·PostGIS 연결과 마이그레이션 기반 구성](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/10)
- 브랜치: `feat#3-postgis-foundation`, 대상: develop. PR #9는 임의 병합하지 않으며 본 작업은 현재 develop의 PHASE 0 코드만 사용한다.
- 현재: Codex 초안 → Claude Code 검토·직접 수정 완료(2026-11-10). Codex 기능별 구현·커밋 대기.
- BE-06만 구현한다. stores 등 새 테이블·ETL·분석·FE·운영 DB endpoint는 추가하지 않는다.
- 로컬 DATABASE_URL·Docker가 없으므로 로컬 단위 검사와 작업 브랜치 CI의 실제 임시 PostGIS 검사를 모두 통과한 후 PR을 만든다.
- 완료 정의(모두 충족해야 함):
  1. 로컬 ruff check·ruff format --check·mypy·단위 pytest 통과.
  2. 기능 브랜치 push로 실행된 CI에서 기존 검사 job과 `postgis-integration` job이 모두 `success`. `skipped`·`neutral`·`cancelled`는 실패로 본다.
  3. 통합 테스트가 1개 이상 실행되고 skipped=0, xfail=0.
  4. 위 결과(커밋 SHA·run URL·통과 수)를 "구현·검증 결과"에 기록한 뒤에만 develop 대상 PR을 만든다.
- 중단 규칙: CI 실행 결과를 확인할 수 없거나, 통합 job이 실패·skip되거나, SQLite·mock 등으로만 통과시킬 수 있는 상황이면 사유를 기록하고 중단한다. PR을 만들지 않고 다음 큐로 넘어가지 않는다.

## 설계

### 0. 의존성

- Codex가 실제 pyproject를 대조한 결과 SQLAlchemy 2.1.8·psycopg 3.3.8·Alembic 1.20.1·GeoAlchemy2 0.21.0이 이미 고정돼 있다. 검토자의 신규 의존성 추가·버전 하향 제안은 적용하지 않고 기존 pyproject·uv.lock을 유지한다.
- psycopg2·asyncpg는 추가하지 않는다. 드라이버는 psycopg(3) 하나로 고정한다.

### 1. DB 설정·엔진·세션

#### 1.1 설정

- 기존 Settings의 `DATABASE_URL: SecretStr | None`을 그대로 사용한다. 기본값은 None이며 앱 import·health는 None이어도 동작해야 한다.
- `DATABASE_CONNECT_TIMEOUT: int`를 추가한다. 기본 5초, 허용 범위 1~60(범위 밖이면 설정 오류). `.env.example`에는 값 없는 `DATABASE_URL=`과 `DATABASE_CONNECT_TIMEOUT=5`만 추가한다. 실제 호스트·암호 예시는 넣지 않는다.
- URL 검증·정규화를 pydantic field_validator 안에서 하지 않는다. pydantic ValidationError는 `input_value`로 원문을 노출할 수 있으므로, 검증은 아래 `normalize_database_url()`에서 수행한다. Settings `model_config`에는 `hide_input_in_errors=True`를 지정한다.

#### 1.2 URL 정규화(`normalize_database_url(raw: str) -> sqlalchemy.engine.URL`)

- `sqlalchemy.engine.make_url()`로 파싱하고 결과는 문자열이 아닌 `URL` 객체로 다룬다. 앞뒤 공백은 제거한다.
- drivername 처리:
  - `postgresql`, `postgres` → `postgresql+psycopg`로 `url.set(drivername=...)` 변경. (`postgres`는 SQLAlchemy 1.4+에서 dialect 이름으로 인식되지 않으므로 반드시 변환해야 한다.)
  - `postgresql+psycopg` → 그대로 사용.
  - 그 외(`postgresql+psycopg2`, `postgresql+asyncpg`, `sqlite`, `mysql` 등) → 거부.
- host와 database가 비어 있으면 거부한다. query 파라미터(`sslmode` 등)는 보존한다.
- 모든 실패는 `DatabaseConfigurationError`(고정 문구, 예: "DATABASE_URL 형식이 올바르지 않습니다", "지원하지 않는 DB 드라이버입니다")로 올리고 `raise ... from None`으로 원인 예외 체인을 끊는다. 메시지·로그에 URL·사용자명·암호·호스트를 넣지 않는다.
- 시크릿 접근: `get_secret_value()`는 이 함수 호출 지점에서만 사용한다. URL을 문자열로 다시 조립하거나 `render_as_string(hide_password=False)`를 호출하지 않는다. 로그·예외에 필요하면 dialect 이름만 사용한다.
- 미설정(None 또는 빈 문자열)은 `DatabaseConfigurationError("DATABASE_URL이 설정되지 않았습니다")`.

#### 1.3 엔진(`create_db_engine(settings) -> Engine`)

- `create_engine(url_obj, echo=False, hide_parameters=True, pool_pre_ping=True, connect_args={"connect_timeout": settings.DATABASE_CONNECT_TIMEOUT})`.
- `create_engine`은 연결하지 않으므로 생성 시점에 DB 접속이 발생하지 않는다(지연 연결). 함수 안에서 `connect()`·health 쿼리를 호출하지 않는다.
- module import 시 엔진을 만들지 않는다. 전역 싱글턴·lru_cache 엔진도 이번에는 두지 않는다. 호출자가 수명과 `dispose()`를 관리한다.
- 이번에는 DB 연결을 확인하는 API endpoint를 추가하지 않는다. 기존 `/health`는 DB와 무관하게 유지한다.

#### 1.4 Base·세션

- `class Base(DeclarativeBase)`만 정의하고 모델은 만들지 않는다. naming convention(`ix/uq/ck/fk/pk`)을 MetaData에 지정해 BE-07 마이그레이션 이름을 안정화한다.
- `create_session_factory(engine) -> sessionmaker[Session]`: `autoflush=False`, `expire_on_commit=False`.
- `session_scope(factory) -> Iterator[Session]`(`contextlib.contextmanager`): 항상 새 Session을 만들며 외부 Session을 받지 않는다(중첩·기존 트랜잭션 재사용 없음 → "조용히 무시"할 기존 트랜잭션 자체가 없음).

  ```python
  session = factory()
  try:
      yield session
      session.commit()  # commit 실패도 아래 except로 들어간다
  except BaseException:
      try:
          session.rollback()
      except Exception:
          pass  # rollback 실패가 원래 예외를 가리지 않게 한다(로그에 원문 금지)
      raise  # 원래 예외를 그대로 전달
  finally:
      session.close()
  ```

- 본문에서 예외가 나면 commit을 호출하지 않는다. 외부 응답 변환(HTTP 오류 매핑)은 향후 service/router 책임이며 여기서는 예외를 삼키거나 변환하지 않는다.

### 2. Alembic

#### 2.1 파일

- root `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_enable_postgis.py`.
- `alembic.ini`에는 `sqlalchemy.url`을 두지 않는다(URL·시크릿 금지). `script_location = %(here)s/migrations`, `prepend_sys_path`는 기존 패키지 구조(src 레이아웃 여부)에 맞춘다.
- 로깅: `sqlalchemy.engine` 로거는 `WARN`으로 두어 SQL·파라미터가 출력되지 않게 한다.
- revision id는 `0001`, `down_revision = None`.

#### 2.2 env.py 온라인 모드

- 연결 결정 순서:
  1. `config.attributes.get("connection")`가 있으면 그 Connection을 사용한다(테스트가 TEST_DATABASE_URL 엔진의 연결을 주입하는 Alembic 공식 패턴). 이 경우 env.py는 엔진을 만들거나 dispose하지 않는다.
  2. 없으면 Settings로 `create_db_engine()`을 호출해 엔진을 만든다. URL을 `config.set_main_option()`에 넣지 않는다(configparser `%` 보간 오류와 시크릿 노출 위험).
- `context.configure(connection=..., target_metadata=Base.metadata, compare_type=True)` 후 `with context.begin_transaction(): context.run_migrations()`. PostgreSQL은 트랜잭션 DDL을 지원하므로 실패 시 전체가 롤백된다.
- 2번 경로에서는 `try/finally`로 `engine.dispose()`를 항상 수행한다.
- 오류 변환: `DatabaseConfigurationError`와 `sqlalchemy.exc.SQLAlchemyError`를 잡아 `alembic.util.CommandError`로 `from None` 변환한다. 메시지는 고정 문구 + 예외 클래스 이름 + (있으면) `orig.sqlstate`만 포함한다(예: "DB 마이그레이션 실패: ProgrammingError (SQLSTATE 42501)"). 원문 메시지·SQL·URL은 넣지 않는다.

#### 2.3 env.py offline 모드

- `context.configure(dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True)`로 실행한다. Settings·DATABASE_URL을 읽지 않으며 연결도 만들지 않는다.
- `alembic upgrade head --sql`이 DATABASE_URL 미설정 상태에서도 성공해야 한다.

#### 2.4 0001 마이그레이션(설치·권한)

- upgrade: `op.execute("CREATE EXTENSION IF NOT EXISTS postgis")`. 스키마는 지정하지 않는다(DB 기본 search_path 사용, 운영자가 사전 설치한 위치 존중).
- 권한: postgis는 PostgreSQL trusted extension이 아니므로 미설치 DB에서는 superuser(또는 관리형 DB의 동등 권한)가 필요하다. 이미 설치돼 있으면 `IF NOT EXISTS`가 권한 검사 전에 NOTICE로 끝나므로 일반 마이그레이션 계정으로도 통과한다.
  - 운영 절차: DBA가 대상 DB에 `CREATE EXTENSION postgis`를 먼저 수행하고, 앱 마이그레이션 계정은 superuser를 갖지 않는다. README에 이 전제를 적는다.
  - 권한 부족 시 2.2의 변환으로 "SQLSTATE 42501" 포함 고정 문구 CommandError로 중단하고 트랜잭션은 롤백된다.
- downgrade: 아무 SQL도 실행하지 않는다(`pass` + 사유 주석). PostGIS 확장은 다른 스키마·데이터가 공유할 수 있으므로 DROP하지 않는다. Alembic이 `alembic_version` 행만 제거한다. `DROP EXTENSION ... CASCADE`는 어떤 경로에서도 사용하지 않는다.
- stores 등 사용자 테이블은 만들지 않는다.

### 3. PR 전 검증 환경

#### 3.1 CI 트리거

- 기존 트리거(develop·main 대상 pull_request 등)는 유지하고 `push.branches`에 `'feat#*'`를 따옴표로 감싸 추가한다(YAML `#` 해석 혼동 방지). PR 없이 기능 브랜치 push만으로 전체 검사가 돈다.
- workflow `permissions: contents: read`. 같은 ref의 중복 실행은 `concurrency`(cancel-in-progress)로 정리하되, 완료 판정은 최종 SHA의 run으로만 한다.

#### 3.2 postgis-integration job

- 검토 초안의 구버전 이미지 대신 upstream과 Docker Hub에서 확인한 `postgis/postgis:17-3.7`을 사용하고 digest `sha256:1f0d64ef12bfb344d3569ab6419aca183258b146951daec83f0585d01e6c9cc9`로 고정한다.
- 환경값은 CI 전용 고정값만 사용한다: `POSTGRES_USER=spoton_ci`, `POSTGRES_PASSWORD=spoton_ci_only`, `POSTGRES_DB=spoton_ci`. `secrets.*`를 참조하지 않으며 운영·스테이징 값은 쓰지 않는다. 포트는 `127.0.0.1:5432`로 매핑한다.
- health check: `--health-cmd "pg_isready -U spoton_ci -d spoton_ci" --health-interval 5s --health-timeout 5s --health-retries 10`.
- job env: `TEST_DATABASE_URL=postgresql+psycopg://spoton_ci:spoton_ci_only@127.0.0.1:5432/spoton_ci`, `SPOTON_ALLOW_DB_INTEGRATION=1`. `DATABASE_URL`은 설정하지 않는다(일반 경로가 테스트 DB를 쓰지 않음을 함께 검증).
- 실행: `pytest -m integration -rA --junitxml=integration.xml`. 이어서 junit을 파싱해 tests>0, skipped=0, failures=0, errors=0이 아니면 실패시키는 단계를 둔다. pytest 종료코드 5(수집 0건)도 실패다.
- job에 `continue-on-error`·`if: ...` 조건 skip을 두지 않는다.

#### 3.3 테스트 DB 안전장치

- 통합 테스트는 `TEST_DATABASE_URL`만 사용하고 `DATABASE_URL`을 대상으로 쓰지 않는다.
- conftest에서 통합 fixture 진입 전에 모두 확인하고, 하나라도 어기면 `pytest.fail`(skip 아님):
  1. `TEST_DATABASE_URL` 설정됨.
  2. `SPOTON_ALLOW_DB_INTEGRATION=1`.
  3. host가 `localhost`·`127.0.0.1`·`::1` 중 하나.
  4. `DATABASE_URL`이 설정돼 있다면 TEST_DATABASE_URL과 host·port·database가 같지 않음.
- 실패 메시지에도 URL을 넣지 않는다.
- 통합 테스트는 superuser 연결로 임시 DB(`spoton_it_<uuid8>`, `TEMPLATE template0`)를 만들어 그 안에서만 마이그레이션하고, 종료 시 `DROP DATABASE ... WITH (FORCE)`로 제거한다. 임시 DB 이름은 코드가 생성한 접두사 `spoton_it_`인 것만 DROP한다.
  - `postgis/postgis` 이미지는 `POSTGRES_DB`와 `template_postgis`에 PostGIS를 미리 설치하므로, `template0` 기반 새 DB를 써야 "미설치 → CREATE EXTENSION" 경로가 실제로 검증된다.

#### 3.4 pytest 설정

- `pyproject.toml`: `markers = ["integration: 실제 PostgreSQL/PostGIS 필요"]`, `addopts = "--strict-markers -m 'not integration'"`. CLI의 `-m integration`이 addopts의 `-m`을 덮어쓴다.
- 통합 테스트에 `skipif`·`pytest.skip`·`importorskip`·`xfail`을 사용하지 않는다.
- health·기존 단위 테스트는 DB를 필요로 하지 않는다. SQLite로 PostGIS 검증을 대체하지 않는다.

### 4. 테스트

#### 4.1 단위(로컬·CI 공통, DB 불필요)

- URL: 미설정·빈 문자열·깨진 URL·지원하지 않는 dialect/드라이버(sqlite, mysql, psycopg2, asyncpg)·host/database 누락 거부, `postgres://`·`postgresql://` → `postgresql+psycopg` 정규화, `postgresql+psycopg://` 유지, query 파라미터 보존.
- 기밀 비노출: 고유 문자열 암호를 넣은 URL로 실패를 유도하고 예외 `str`·`repr`·`__cause__`·`__context__` 체인(from None 확인)·caplog에 암호·사용자명·호스트가 없음을 확인. Settings `repr`과 ValidationError에도 없음.
- `DATABASE_CONNECT_TIMEOUT` 범위 검증.
- Engine: `engine.url.drivername == "postgresql+psycopg"`, `echo is False`, `hide_parameters is True`, `pool._pre_ping is True`, connect_args 전달. 지연 연결: 도달 불가 주소(`127.0.0.1:1`)로 엔진 생성이 예외 없이 즉시 끝나고 `psycopg.connect`가 호출되지 않음(mock).
- 앱 import·`/health`가 DATABASE_URL 미설정에서 정상.
- Session(mock factory): 정상 종료 → commit·close, 본문 예외 → commit 미호출·rollback·close·원래 예외 전달, commit 실패 → rollback·close·commit 예외 전달, rollback도 실패 → 원래 예외 전달·close.
- Alembic offline: DATABASE_URL 미설정 상태에서 `upgrade head --sql` 출력에 `CREATE EXTENSION IF NOT EXISTS postgis`와 `alembic_version`이 포함되고, 환경에 넣은 임의 시크릿 문자열이 없음. `downgrade 0001:base --sql`에 `DROP EXTENSION`이 없음.
- Alembic 온라인 오류 변환: 엔진 생성/연결 실패를 mock으로 유도해 CommandError의 메시지에 원문·URL이 없음.

#### 4.2 통합(`-m integration`, CI 필수)

임시 DB(3.3)에서 순서대로 수행한다.

1. 사전: `pg_extension`에 postgis 없음 확인.
2. `with engine.begin() as conn: cfg.attributes["connection"] = conn; command.upgrade(cfg, "head")` → 별도 연결로 `alembic_version` = `0001` 확인(커밋 반영 검증). downgrade·재upgrade도 매번 새 `engine.begin()` 블록을 사용한다.
3. `SELECT postgis_lib_version()` 주 버전 3 이상. `ST_DWithin(ST_SetSRID(ST_MakePoint(126.9780,37.5665),4326)::geography, ST_SetSRID(ST_MakePoint(126.9790,37.5665),4326)::geography, 100)`이 true, 1m 반경은 false.
4. 트랜잭션: 테스트 코드가 임시 DB 안에만 검증용 테이블 `it_tx_probe(id int)`를 직접 만든다(마이그레이션·앱 모델 아님, DB째 삭제됨). `session_scope`로 insert 후 정상 종료 → 다른 연결에서 행 보임, 본문 예외 → 행 없음, 제약 위반으로 commit 실패 유도(DEFERRABLE INITIALLY DEFERRED 제약) → 예외 전달·행 없음. TEMP TABLE은 풀 연결이 바뀌면 보이지 않으므로 쓰지 않는다.
5. `command.downgrade(cfg, "base")` → `alembic_version` 행 없음, `pg_extension`에 postgis 유지.
6. 다시 upgrade → `0001`, 오류 없음(재실행 멱등).
7. 권한: CI 내에서 `NOSUPERUSER` 임시 role을 만들고 PostGIS 미설치 임시 DB의 owner로 지정한 뒤 그 role로 upgrade → CommandError, 메시지에 `42501` 포함, 암호 미포함, `alembic_version` 미생성(롤백). 이어서 superuser가 확장을 먼저 설치한 뒤 같은 role로 upgrade 성공(운영 절차 재현). 테스트 role·DB는 정리한다.
8. 테스트 종료 후 임시 DB·role 삭제. `spoton_ci` 기본 DB는 수정하지 않는다.

#### 4.3 실행 순서

- 로컬 ruff check·ruff format --check·mypy(`migrations/` 포함)·단위 pytest → 커밋 → 기능 브랜치 push → CI 두 job success 확인. 실패하면 수정·재검증하고, 확인 불가·반복 실패면 1장의 중단 규칙을 따른다.

## 기능별 커밋 계획

| 순서 | 커밋 | 범위·검증 |
|---|---|---|
| 1 | docs(be): PostGIS 기반 설계와 Claude 검토 기록 | 검토 완료 MD·중단 규칙 |
| 2 | feat(be): PostgreSQL 엔진과 트랜잭션 세션 구성 | 의존성·설정·URL 정규화·엔진·세션·Base 및 4.1 단위 테스트(로컬 통과) |
| 3 | feat(be): PostGIS 초기 마이그레이션 구성 | Alembic·확장 보존 downgrade·offline SQL·오류 변환 단위 테스트(로컬 통과) |
| 4 | test(be): PR 전 PostGIS 통합 검증 추가 | pytest marker·안전장치 conftest·4.2 통합 테스트·CI push 트리거·postgis-integration job·junit 검사 |
| 5 | docs(be): DB 실행 방법과 검증 결과 정리 | README(로컬/CI 실행, DBA 사전 설치 전제)·본 문서 결과 기록 |

- 각 커밋은 로컬 단위 검사를 통과한 상태로 만든다. 4번 커밋 push 후 CI가 완료 정의를 충족해야 5번으로 진행하고, 5번 push의 CI도 다시 success여야 PR을 만든다.

## Claude Code 검토 기록

2026-11-10 Claude Code 검토·직접 수정(이 파일만 수정, 코드·다른 문서·Git·명령 실행 없음).

주요 수정과 이유:

1. 완료 정의·중단 규칙 명확화: skip·neutral·cancelled를 실패로 보고, 통합 테스트 수>0·skipped=0을 junit으로 강제. "skip으로 통과"를 구조적으로 차단.
2. URL: `postgres://`는 SQLAlchemy 2에서 dialect로 인식되지 않아 변환을 필수로 명시. psycopg2·asyncpg 거부, host/database 누락 거부, `URL` 객체로만 전달. pydantic validator 안 검증은 ValidationError `input_value`로 원문이 노출될 수 있어 별도 함수로 이동, `hide_input_in_errors=True` 추가, `from None`으로 예외 체인 차단.
3. 세션: commit을 try 안에 두어 commit 실패도 rollback되게 하고, rollback 실패가 원래 예외를 가리지 않게 함. 외부 Session을 받지 않게 해 "기존 트랜잭션 무시" 모호성 제거.
4. Alembic: URL을 `set_main_option`에 넣지 않음(`%` 보간 오류·시크릿 노출). 테스트용 connection 주입 경로 추가. 오류는 클래스명+SQLSTATE만 노출해 진단성과 비밀 보호를 동시에 확보. offline은 Settings를 읽지 않음. `sqlalchemy.engine` 로그 WARN.
5. PostGIS 권한: postgis는 trusted extension이 아님을 명시하고 DBA 사전 설치 + 비superuser 마이그레이션 계정 절차와 42501 실패 경로를 통합 테스트로 검증하도록 추가.
6. 중요 오류 수정: `postgis/postgis` 이미지는 `POSTGRES_DB`에 PostGIS를 미리 설치하므로 초안대로면 CREATE EXTENSION 경로가 검증되지 않음 → `template0` 기반 임시 DB에서 검증하도록 변경.
7. 테스트 DB 안전장치: localhost 한정, 명시 허용 플래그, DATABASE_URL과 동일 대상 금지, 코드가 만든 `spoton_it_` DB만 DROP. CI 값은 고정 CI 전용값이며 `secrets.*` 미사용.
8. 트랜잭션 통합 검증에서 TEMP TABLE은 풀 연결 변경 시 보이지 않아 오탐 위험 → 임시 DB 내 검증용 테이블로 변경. 앱 테이블·마이그레이션 테이블은 추가하지 않음(stores·ETL 범위 밖 유지).
9. CI: `'feat#*'` 따옴표, `permissions: contents: read`, 이미지 태그 고정, `continue-on-error` 금지.

남은 쟁점(구현 시 확인, 해결 불가 시 중단):

- 기존 CI workflow 파일명·job 구조와 패키지 레이아웃(src 여부)은 이 문서에서 확인하지 않았다. Codex가 구현 시 실제 구조에 맞추되 위 규칙을 바꾸지 않는다.
- CI run 결과 확인 수단(gh CLI 또는 GitHub 웹)이 Codex 환경에서 가능한지 구현 전 확인해야 한다. 불가능하면 PR을 만들지 않고 중단한다.
- 관리형 DB(RDS 등)의 PostGIS 설치 권한 모델은 운영 배포 작업에서 별도로 확인한다(이번 범위 아님).
- 이미지의 실제 runner 실행은 첫 CI에서 확인한다. 위 Codex 재검토의 PostgreSQL 17·PostGIS 3.7/digest를 기준으로 검증한다.

Codex 재검토: 실제 패키지 버전·레이아웃·gh 실행 지원을 확인했다. from None은 출력상 예외 연결을 억제하지만 Python 내부 __context__ 자체를 제거하지 않으므로 URL 파싱 오류는 except 블록 밖에서 고정 예외를 발생시켜 문맥에도 원문을 남기지 않는다. 통합 테스트의 임시 DB·role은 UUID 기반 이름으로만 생성·삭제하고 생성 성공한 자원만 정리한다.

## 구현·검증 결과

구현 전. 실제 성공·실패·중단 사유를 기록하고 미실행 검사를 통과로 표시하지 않는다.
