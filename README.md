# SpotON-BE

서울의 카페·음식점 입지 분석을 위한 Spot:ON 백엔드입니다. 개발 기준과 다음 작업은 [통합 작업계획서](docs/be-work-plan.md)에서 관리합니다.

현재는 FastAPI·health API·공통 응답·오류 처리, PostgreSQL/PostGIS 기반, stores 모델과 지방행정 인허가 데이터 수집·정제·멱등 upsert, 카카오 로컬 API 기반 서울 주소 지오코딩, AI 해석용 공급자 분리 LLM client를 제공합니다. 실제 개발 DB 연결과 원천 전체 적재·분석·AI 해석 API는 후속 작업입니다.

## 로컬 실행

Python 3.11을 설치한 뒤 저장소 루트에서 실행합니다. `uv.lock`을 커밋해 로컬·CI가 같은 의존성을 설치합니다.

```powershell
py -3.11 -m pip install uv==0.13.7
uv sync --locked --extra dev
# 환경변수가 필요하면 .env.example을 .env로 복사하고 로컬에서 값을 설정합니다.
# 기존 .env는 덮어쓰지 않습니다. health 실행에는 API 키나 DB가 필요하지 않습니다.
uv run --locked --extra dev uvicorn app.main:app --reload --no-access-log
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

## 서울 주소 지오코딩

`GET /api/geocode?query={주소}&category={cafe|restaurant}`는 카카오 로컬 API에서 검증한 서울 주소 후보를 반환합니다. 결과는 도로명·지번 주소, WGS84 좌표, `building_key`, 입력에서 명시적으로 읽은 `floor_unit`을 포함합니다. 복수 후보는 최대 5개를 `candidates`에 반환하며, 서울 외는 `OUT_OF_SEOUL`, 검색 실패는 `ADDRESS_NOT_FOUND`로 응답합니다.

실행에는 서버 전용 `KAKAO_REST_API_KEY`가 필요합니다. 키·주소·좌표는 로그에 남기지 않으며, 응답은 `Cache-Control: no-store`로 전송합니다. 키 없이 실행하면 이 경로는 `UPSTREAM_ERROR`를 반환합니다.

## AI LLM client

`app/ai/`는 AI 해석 API(BE-32)가 사용할 공급자 분리 LLM client입니다. 아직 API 경로는 없습니다. `create_llm_client(settings)`가 `LLM_PROVIDER=google`이면 Gemini `generateContent` 어댑터를 만들고, 그 밖의 값은 호출 시 실패하는 client를 돌려줘 설정 오류가 지표 API 시작을 막지 않습니다.

- 키 `LLM_API_KEY`는 서버 전용이며 `x-goog-api-key` 헤더로만 보냅니다. 기본 모델은 `LLM_MODEL=gemini-3.5-flash-lite`입니다.
- `LLM_REQUEST_TIMEOUT`(요청 1회)과 `LLM_TIME_BUDGET`(재시도 대기 포함 전체) 안에서 429·500·503·504·네트워크 오류·timeout만 `LLM_MAX_RETRIES`회까지 지터를 준 지수 백오프로 재시도합니다.
- `LLM_REQUESTS_PER_MINUTE`·`LLM_REQUESTS_PER_DAY`는 프로세스 내 한도이며 비우면 제한하지 않습니다. 일일 한도는 태평양 시간 자정에 초기화합니다. 프로젝트 계정의 실제 한도를 확인해 설정합니다.
- 모든 실패는 기존 `AI_UNAVAILABLE`(503)로 매핑합니다. 프롬프트·생성 결과·키·공급자 오류 본문은 로그와 예외에 남기지 않습니다.
- 한도 카운터가 client 인스턴스에 있으므로 호출하는 쪽은 앱 수명 동안 하나를 재사용해야 합니다.

자동 검증은 mock transport만 사용하며 실제 Gemini 호출은 확인하지 않았습니다. 상세 계약은 [작업 25 설계서](docs/designs/feat25-llm-client.md)에서 확인합니다.

## 공통 오류 응답

요청 검증 실패는 422, 없는 경로는 404, 허용되지 않은 메서드는 405 상태를 유지하면서 공통 외피로 반환합니다. 404/405에는 새 코드를 추가하지 않고 기존 `INVALID_PARAM`을 사용합니다. 주소 조회 실패용 `ADDRESS_NOT_FOUND`와는 구분합니다. 405의 `Allow` 및 HTTP 예외의 인증·재시도 프로토콜 헤더는 유지하고 임의 디버그 헤더는 제거합니다.

```json
{
  "data": null,
  "meta": {},
  "error": {"code": "INVALID_PARAM", "message": "요청 값을 확인해 주세요"}
}
```

내부 예외는 500 `INTERNAL_ERROR`와 고정 문구로 응답합니다. 응답 시작 전 애플리케이션 예외는 CORS 안쪽에서 처리해 허용된 origin의 FE도 오류 본문을 읽을 수 있습니다. 요청값·예외 원문·traceback을 응답에 넣지 않고 애플리케이션 로그에는 예외 클래스 이름만 남깁니다. 실행 안내의 `--no-access-log`는 쿼리 등 요청 정보가 Uvicorn 접근 로그에 남는 것을 막습니다.

CORS preflight·문서·리다이렉트·204/304는 프로토콜 응답으로 유지합니다. 응답 시작 후 스트리밍·background task 오류와 서버/인프라 자체 로그 정책은 후속 BE-35 범위입니다. 상세 meta·DataVersion은 원본 API 명세 확인 전까지 확정하지 않습니다.

## 검증

```powershell
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app etl migrations
uv run --locked --extra dev pytest
```

테스트는 DB·외부 API 없이 health, 공통 응답·오류·OpenAPI·CORS·정보 비노출·환경 설정, DB 설정·세션 제어와 인허가 수집·정제, LLM client의 재시도·한도·응답 분류·비노출을 검증합니다. 실제 SQL·공간 함수·권한·stores upsert는 아래 PostGIS 통합 job에서 수행합니다. 작업별 설계·Claude 검토·검증 결과는 `docs/designs/`에 기록합니다.

## 지방행정 인허가 ETL

일반음식점·휴게음식점 공식 API의 페이지 수집, 서울 25개 관청 코드 검증, 중복 제거, 날짜·상태·업종·면적 정제, EPSG:5174 원 좌표 보존과 EPSG:4326 변환, stores 멱등 upsert를 모듈로 제공합니다.

- `DATA_GO_KR_SERVICE_KEY`는 디코딩된 서비스 키를 로컬 `.env` 또는 서버 시크릿에만 설정합니다.
- 전화번호·홈페이지·대표자와 원천 JSON 전체는 DTO·DB·로그·리포트에 저장하지 않습니다.
- 실제 원천 전체 수집·개발 DB 적재 CLI는 아직 제공하지 않습니다. repository는 호출자가 명시적으로 전달한 PostgreSQL 연결만 사용합니다.
- `building_key`, `floor_unit`, 주소·좌표 보완, 삭제 동기화는 후속 작업입니다.

상세 계약과 검증 근거는 [작업 5 설계서](docs/designs/feat5-license-etl.md)에서 확인합니다.

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

통합 검사는 PostGIS 미설치 임시 DB에서 upgrade·공간 함수·세션 commit/rollback·권한 부족·관리자 사전 설치 후 일반 계정 migration·downgrade/재upgrade와 인허가 stores upsert의 멱등성·geometry·source 분리·전체 rollback을 검증합니다. 로컬 DB가 없으면 CI 결과로 실제 검증 여부를 확인하며, CI도 실행할 수 없으면 PR과 다음 작업을 중단합니다.
