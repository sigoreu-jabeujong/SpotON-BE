# SpotON-BE

서울의 카페·음식점 입지 분석을 위한 Spot:ON 백엔드입니다. 개발 기준과 다음 작업은 [통합 작업계획서](docs/be-work-plan.md)에서 관리합니다.

현재는 FastAPI 실행 기반·health API와 PostgreSQL/PostGIS 엔진·세션·마이그레이션 기반을 제공합니다. 실제 개발 DB 연결값은 별도 설정하며 stores·데이터 적재·분석 API는 후속 작업입니다.

## 로컬 실행

Python 3.11을 설치한 뒤 저장소 루트에서 실행합니다. `uv.lock`을 커밋해 로컬·CI가 같은 의존성을 설치합니다.

```powershell
py -3.11 -m pip install uv==0.13.7
uv sync --locked --extra dev
# 환경변수가 필요하면 .env.example을 .env로 복사하고 로컬에서 값을 설정합니다.
# 기존 .env는 덮어쓰지 않습니다. health 실행에는 API 키나 DB가 필요하지 않습니다.
uv run --locked --extra dev uvicorn app.main:app --reload
```

- 상태 확인: `http://localhost:8000/api/health`
- Swagger: `http://localhost:8000/docs`
- `APP_ENV`: local/test/staging/production. 기본값 local
- `CORS_ORIGINS`: 쉼표로 구분한 허용 origin. 기본값 `http://localhost:5173`, 빈 값이면 교차 출처 접근 미허용
- DB·외부 API·LLM 설정 이름은 `.env.example`을 참고합니다. 비밀값은 실제 `.env` 또는 서버 시크릿에만 둡니다.

```json
{"data": {"status": "ok"}, "meta": {}, "error": null}
```

health는 프로세스 상태 확인용이며 DB·공공데이터 준비 상태를 보장하지 않습니다. FE의 기본 서버 주소는 `http://localhost:8000`이고 `/api`는 클라이언트가 붙입니다. `Content-Type: application/json` 요청의 CORS preflight도 허용된 origin에 한해 처리합니다.

## 검증

```powershell
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app migrations
uv run --locked --extra dev pytest
```

테스트는 DB·외부 API 없이 health 응답, Swagger, CORS 허용·거부, 설정 우선순위·비밀값 마스킹을 검증합니다. 데이터·분석 기능이 추가되면 샘플 재현 방법과 출처·라이선스를 함께 기록합니다.

## PostgreSQL·PostGIS 설정과 마이그레이션

개발 DB의 접속 URL은 실제 `.env` 또는 서버 시크릿의 `DATABASE_URL`에 설정합니다. 형식은 `postgresql+psycopg://<user>:<password>@<host>:5432/<database>`이며 기본 `postgresql://`·`postgres://`도 psycopg로 정규화합니다. `DATABASE_CONNECT_TIMEOUT`은 1~60초(기본 5초)입니다. 값은 출력·커밋하지 않습니다.

명시 포트는 1~65535를 사용합니다. URL query는 `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, `sslcrl`, `application_name`만 허용하고 중복·빈 값·접속 대상/계정 재정의 옵션은 거부합니다. 접속 시간 제한은 URL query 대신 설정값으로 관리합니다. URL fragment는 허용하지 않으므로 암호 등의 특수 문자는 percent-encoding합니다.

PostGIS 서버 패키지는 관리자가 설치해야 합니다. 실제 운영에서는 DBA가 대상 DB의 PostGIS 확장을 먼저 활성화하고, 앱 계정에는 관리자 권한을 주지 않습니다. 미설치 DB에서 권한이 부족하면 migration은 안전한 오류로 중단됩니다.

```powershell
# 실제 DB에는 접속 설정·대상·설치 권한을 확인한 후 실행합니다.
uv run --locked --extra dev alembic upgrade head
uv run --locked --extra dev alembic current

# DB 설정·연결 없이 SQL만 확인합니다.
uv run --locked --extra dev alembic upgrade head --sql
```

초기 revision `0001`은 `CREATE EXTENSION IF NOT EXISTS postgis`만 실행합니다. stores 등 사용자 테이블은 만들지 않으며 downgrade도 공유 데이터 보호를 위해 확장을 삭제하지 않습니다. 엔진은 호출 시 생성하고 접속은 지연하며, 호출자가 dispose합니다. `session_scope(create_session_factory(engine))`는 정상 종료 시 commit, 실패 시 rollback·close를 수행합니다. health는 계속 DB 설정 없이 동작합니다.

## 실제 DB 통합 검증

기본 pytest는 DB 없는 단위 검사를 실행하고 `integration`은 제외합니다. PR 생성 전에는 작업 브랜치 push로 CI의 `lint-and-test`와 `postgis-integration`을 모두 통과해야 합니다. 통합 job은 고정 digest의 PostGIS 이미지와 CI 전용 계정을 사용하고 skip·xfail·0건 실행을 실패로 처리합니다.

명시 실행 명령은 다음과 같습니다. `TEST_DATABASE_URL`과 `SPOTON_ALLOW_DB_INTEGRATION=1`이 필요하며 localhost의 테스트 DB만 허용합니다. 일반 `DATABASE_URL`과 같은 대상을 테스트하지 않습니다. 테스트가 만든 `spoton_it_` 임시 DB·role만 정리하므로 운영·일반 개발 DB를 대상으로 설정하지 않습니다.

```powershell
uv run --locked --extra dev pytest -m integration -rA --junitxml=integration.xml
```

통합 검사는 PostGIS 미설치 임시 DB에서 upgrade·공간 함수·세션 commit/rollback·권한 부족·관리자 사전 설치 후 일반 계정 migration·downgrade/재upgrade를 검증합니다. 로컬 DB가 없으면 CI 결과로 실제 검증 여부를 확인하며, CI도 실행할 수 없으면 PR과 다음 작업을 중단합니다. 설계·Claude 검토·커밋별 결과는 [작업 3 설계서](docs/designs/feat3-postgis-foundation.md)에서 확인합니다.
