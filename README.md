# SpotON-BE

서울의 카페·음식점 입지 분석을 위한 Spot:ON 백엔드입니다. 개발 기준과 다음 작업은 [통합 작업계획서](docs/be-work-plan.md)에서 관리합니다.

현재는 FastAPI·health API와 공통 응답·오류 처리 기반을 제공합니다. DB 연결·데이터 적재·분석 API는 후속 작업입니다.

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
uv run --locked --extra dev mypy app
uv run --locked --extra dev pytest
```

테스트는 DB·외부 API 없이 health, 공통 응답 불변식, 9개 도메인 오류, 요청·HTTP·내부 오류, OpenAPI, CORS, 정보 비노출과 환경 설정을 검증합니다. 기능별 설계·Claude 검토·커밋 결과는 [작업 2 설계서](docs/designs/feat2-common-api-errors.md)에 기록했습니다. 데이터·분석 기능이 추가되면 샘플 재현 방법과 출처·라이선스를 함께 기록합니다.
