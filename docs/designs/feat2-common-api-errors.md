# 작업 2: 공통 API 응답과 오류 처리 설계

## 작업 정보와 상태

- 이슈: [#8 공통 API 응답과 오류 처리 기반 구현](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/8).
- 브랜치: `feat#2-common-api-errors`, PR 대상: `develop`.
- 범위: BE-04의 공통 외피 보강, BE-05 공통 예외 처리. 상세 meta·DataVersion은 원본 API 명세 확인 전 보류한다.
- 현재 상태: Codex 초안 → Claude Code 검토·직접 수정 → Codex 구현·로컬 테스트 완료. develop 대상 PR 생성 전 최종 검증 중.
- 기준: [통합 작업계획서](../be-work-plan.md). 이 문서는 이번 기능의 설계·검토·커밋 기록만 관리하며 공통 규칙을 복제하지 않는다.

## 문제와 목표

현재 health는 `{data, meta, error}`로 응답하지만 잘못된 경로·요청·미처리 예외는 FastAPI 기본 응답이 나온다. FE는 공통 외피와 오류 code/message를 기대한다. 상태·메시지를 통일하고 입력값·외부 예외·키·주소를 오류 응답과 로그에 노출하지 않는다.

## 1. 공통 응답 모델

- 기존 health JSON `{"data":{"status":"ok"},"meta":{},"error":null}`을 바이트 수준이 아닌 JSON 값 기준으로 그대로 보존한다.
- `ApiMeta`는 임의의 새 필드를 정하지 않고 기존 `dict[str, JsonValue]`의 타입 별칭으로 둔다. BE-04 상세 스키마 완료를 주장하지 않는다.
- `ErrorCode`는 2절 9개 값의 `StrEnum`이다. `ApiError`는 `code: ErrorCode`, `message: str`만 가지며 `extra="forbid"`다.
- `ApiResponse[T]`는 data·meta·error만 허용(`extra="forbid"`)하고 `model_validator(mode="after")`로 불변식을 강제한다.
  - 정상: data non-null, error null. 실패: data null, error non-null. 둘 다 non-null이거나 둘 다 null이면 `ValueError`.
  - `meta`는 항상 non-null 객체다(기본값 `{}`). 실패 응답의 meta는 이번 범위에서 항상 `{}`이며 요청 경로·쿼리·입력값을 담지 않는다.
  - `[]`, `{}`, `0`, `""` 같은 빈 data는 non-null이므로 정상으로 허용한다.
  - 직렬화 시 `error: null`/`data: null` 키가 반드시 남아야 한다. `response_model_exclude_none`·`exclude_none=True`를 쓰지 않는다.
- OpenAPI 이름을 고정하기 위해 실패 외피는 `class ErrorResponse(ApiResponse[None])`로 정의하고 error를 필수 ApiError로 좁힌다(`ApiResponse_NoneType_` 같은 자동 이름 방지).
- 실패 응답은 `error_response(code: ErrorCode, *, status_code: int | None = None, headers: Mapping[str, str] | None = None) -> JSONResponse` 단일 팩터리로만 만든다. 기본 상태·문구는 2절 매핑에서 가져온다. HTTPException 변환만 원래 HTTP 상태를 보존하기 위해 status_code를 지정하며 외부 예외 문자열을 message로 받지 않는다.
- DataVersion 필드·예시 버전·출처·분모를 만들어 넣지 않는다.

## 2. 오류 분류와 상태

| 코드 | HTTP | 안내 |
|---|---:|---|
| INVALID_PARAM | 422 | 요청 값을 확인해 주세요 |
| CATEGORY_REQUIRED | 422 | 업종을 선택해 주세요 |
| ADDRESS_NOT_FOUND | 404 | 주소를 찾을 수 없습니다 |
| OUT_OF_SEOUL | 422 | 서울특별시 주소만 지원합니다 |
| AS_OF_OUT_OF_RANGE | 422 | 조회 가능한 기준 시점을 벗어났습니다 |
| UPSTREAM_ERROR | 502 | 외부 데이터 서비스에 연결할 수 없습니다 |
| AI_UNAVAILABLE | 503 | AI 해석을 일시적으로 이용할 수 없습니다 |
| AI_VERIFY_FAILED | 503 | AI 해석 결과를 검증하지 못했습니다 |
| INTERNAL_ERROR | 500 | 요청 처리 중 오류가 발생했습니다 |

상태·문구는 `ERROR_SPECS: Mapping[ErrorCode, tuple[int, str]]` 한 곳에서만 정의하고, 모든 `ErrorCode`가 매핑에 있는지 테스트로 보장한다.

`AppError(code: ErrorCode)`는 코드만 받는다. 임의 상태·메시지·원인 예외·헤더를 받지 않으며 `str(exc)`도 코드만 반환한다. 이후 원본 명세와 대조하기 전에는 새 enum을 추가하지 않는다.

### 2.1 예외별 처리 위치와 응답

| 예외 | 등록 방식 | 처리 계층 | 응답 |
|---|---|---|---|
| `AppError` | `add_exception_handler(AppError, …)` | ExceptionMiddleware(CORS 안쪽) | 매핑 상태·코드·문구 |
| `fastapi.exceptions.RequestValidationError` | `add_exception_handler` | ExceptionMiddleware | 422 INVALID_PARAM |
| `starlette.exceptions.HTTPException` | `add_exception_handler` (FastAPI `HTTPException`·라우터 404/405 포함) | ExceptionMiddleware | 아래 규칙 |
| 그 외 `Exception` | 신규 `UnhandledErrorMiddleware`(3절) | CORS 안쪽 | 500 INTERNAL_ERROR |
| 그 외 `Exception`(최후 fallback) | `add_exception_handler(Exception, …)` | ServerErrorMiddleware(CORS 바깥) | 500 INTERNAL_ERROR, CORS 헤더 없음 |

- 요청 검증 오류: `errors()`, body, 입력값·위치 정보를 반환하지 않는다.
- HTTPException: 상태를 유지하고 `detail`은 버린다. `status >= 500`은 INTERNAL_ERROR, 그 외는 INVALID_PARAM. 204·304는 body 없는 `Response(status_code, headers=exc.headers)`로 반환한다(Starlette 기본 동작과 동일).
- HTTPException 헤더: Codex 재검토에 따라 `Allow`, `WWW-Authenticate`, `Retry-After`만 대소문자 무관 허용 목록으로 전달한다. 예외가 외부 서비스나 간접 입력에서 생길 수 있으므로 임의 디버그 헤더를 신뢰하지 않는다. 허용 헤더에도 키·주소·입력값을 넣지 않는다. `AppError`는 헤더를 갖지 않는다.
- 미처리 예외: 500 INTERNAL_ERROR 고정 문구만 반환한다. 로그는 `logger.error("unhandled_error type=%s", type(exc).__name__)`처럼 **예외 클래스 이름만** 남긴다. `logger.exception`, traceback, `str(exc)`, request URL·query·body는 기록하지 않는다. 운영 집계 로그는 후속 BE-35에서 설계한다.
- `ResponseValidationError`(응답 모델 불일치)는 서버 결함이므로 별도 handler 없이 미처리 예외 경로로 500 처리한다. 이 예외의 문자열에는 응답 body가 포함되므로 위 로그 규칙이 그대로 중요하다.

### 2.2 알 수 없는 API 계약

원본 명세에 NOT_FOUND 계열 코드가 없으므로 9개 코드 안에서 다음으로 고정한다.

| 상황 | HTTP | 헤더 | 응답 JSON |
|---|---:|---|---|
| 없는 경로 | 404 | — | `{"data":null,"meta":{},"error":{"code":"INVALID_PARAM","message":"요청 값을 확인해 주세요"}}` |
| 허용 안 된 메서드 | 405 | `Allow` 유지 | 위와 동일 |

- 404는 주소 조회 실패(ADDRESS_NOT_FOUND)와 의미가 달라 그 코드로 매핑하지 않는다. 클라이언트는 HTTP 상태로 경로 없음을 구분한다.
- meta에 요청 경로·메서드를 넣지 않는다. FastAPI 기본 `{"detail":"Not Found"}`는 더 이상 나오지 않는다.

## 3. 앱과 CORS 연결

### 3.1 문제

Starlette는 `Exception`·`500` 키로 등록된 handler를 ExceptionMiddleware가 아니라 **가장 바깥의 ServerErrorMiddleware**에 넘긴다. 기본 스택은 `ServerErrorMiddleware → (사용자 미들웨어: CORS) → ExceptionMiddleware → 라우터`이므로, `Exception` handler만 등록하면 500 응답이 CORS 바깥에서 만들어져 `access-control-allow-origin`이 빠진다. 브라우저 FE는 500 본문을 읽지 못한다.

`CORSMiddleware(create_app())`처럼 앱 전체를 감싸는 방식은 반환 타입이 FastAPI가 아니게 되어 `app.include_router`·`dependency_overrides`·`app.openapi()`를 쓰는 테스트 factory와 맞지 않으므로 채택하지 않는다.

### 3.2 결정: CORS 안쪽의 순수 ASGI 미들웨어

미들웨어 순서(바깥 → 안):

```text
ServerErrorMiddleware (Starlette 자동, 최후 fallback)
 └ CORSMiddleware (기존 설정 그대로)
    └ UnhandledErrorMiddleware (신규, 순수 ASGI)
       └ ExceptionMiddleware (Starlette 자동: AppError·RequestValidationError·HTTPException)
          └ 라우터
```

`add_middleware`는 나중에 추가한 것이 바깥이 되므로 `UnhandledErrorMiddleware`를 **먼저**, `CORSMiddleware`를 **나중에** 추가한다.

```python
def create_app(...) -> FastAPI:          # 반환 타입·기존 인자 유지
    app = FastAPI(..., debug=False)
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unhandled)   # fallback, CORS 없음
    app.add_middleware(UnhandledErrorMiddleware)             # 먼저 = 안쪽
    app.add_middleware(CORSMiddleware, ...)                  # 나중 = 바깥, 기존 옵션 유지
    app.include_router(...)
    return app


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if started:          # 이미 헤더 전송됨: 새 응답 불가, 상위로 전달
                raise
            logger.error("unhandled_error type=%s", type(exc).__name__)
            response = error_response(ErrorCode.INTERNAL_ERROR)
            await response(scope, receive, send)
```

- `@app.middleware("http")`(BaseHTTPMiddleware)는 쓰지 않는다. 스트리밍·contextvars·background task 관련 알려진 제약이 있고 순수 ASGI로 20줄 내외면 충분하다.
- `except Exception`은 anyio `ExceptionGroup`도 포함한다. `BaseException`(취소 등)은 잡지 않는다.
- 미들웨어가 예외를 삼키므로 ServerErrorMiddleware는 재전파·traceback 출력을 하지 않는다. fallback handler는 CORS 미들웨어 자체 오류처럼 극히 드문 경우에만 쓰인다.
- 테스트 factory 호환: `create_app()`은 매 호출 새 FastAPI 인스턴스를 반환하고 모듈 전역 상태를 두지 않는다. 테스트는 `app = create_app(...)` 후 첫 요청 전에 `app.include_router(test_router)`를 호출한다(Starlette는 첫 요청 시 미들웨어 스택을 고정하므로 미들웨어 추가는 factory 안에서만 한다).

### 3.3 프로토콜 응답

- CORS preflight(OPTIONS)는 CORSMiddleware가 직접 응답하며 외피로 감싸지 않는다. 미허용 origin preflight의 400 `Disallowed CORS origin` 텍스트도 프로토콜 응답으로 그대로 둔다.
- `/docs`·`/openapi.json`·리다이렉트는 그대로 둔다. 모든 응답 body를 강제 포장하는 미들웨어를 만들지 않는다.

### 3.4 OpenAPI

- 공통 상수 `ERROR_RESPONSES = {500: {"model": ErrorResponse}}`와 `VALIDATION_ERROR_RESPONSES = {422: {"model": ErrorResponse}, **ERROR_RESPONSES}`를 둔다.
- FastAPI는 operation의 `responses`에 `422`(또는 `4XX`/`default`)가 이미 있으면 기본 `HTTPValidationError` 스키마를 추가하지 않는다. 파라미터·body가 있는 라우트는 `VALIDATION_ERROR_RESPONSES`를 지정해 실제 422 외피와 문서를 일치시킨다.
- health는 파라미터가 없으므로 `ERROR_RESPONSES`만 지정한다. 200 스키마와 실제 JSON은 바꾸지 않는다.
- 404·405는 operation 단위 응답이 아니므로 OpenAPI에 넣지 않고 README·2.2절로 안내한다.
- `components.schemas`에 `ErrorResponse`·`ApiError`·`ErrorCode`(9개 enum)가 있고 `HTTPValidationError`가 없음을 테스트한다.

## 4. 테스트와 검증

- health의 기존 응답·Swagger·CORS 테스트를 유지한다.
- 공통 모델: 정상·실패 생성, 둘 다 null/둘 다 non-null 거부, 잘못된 코드·추가 필드 거부, `meta` 기본 `{}`, 직렬화 결과에 `error: null`/`data: null` 키 존재, `ERROR_SPECS`가 9개 코드를 모두 포함.
- 테스트 전용 라우터는 `tests/` 안에서만 정의하고 `create_app()` 결과에 `include_router`로 붙인다. AppError, query/body 검증 오류, HTTPException 4xx/5xx(헤더 포함), 미처리 `RuntimeError`를 발생시킨다. 운영 라우터에 테스트 엔드포인트를 만들지 않는다.
- 알 수 없는 API: 없는 경로 404와 2.2절 JSON 일치, 허용 안 된 메서드 405와 `Allow` 헤더.
- 정보 비노출: 예외 메시지·query·body에 더미 비밀값(예: `SECRET-DUMMY-…`)을 넣고 응답 본문·헤더와 `caplog` 전체에 없음을 검증한다. 로그에는 클래스 이름만 있는지 확인한다.
- CORS: 허용 origin으로 health 200·422·404·AppError·**미처리 500** 응답 모두에 `access-control-allow-origin`이 있고, 미허용 origin에는 없음을 검증한다.
- 500 테스트는 TestClient 기본값 `raise_server_exceptions=True`를 그대로 쓴다. 예외가 `UnhandledErrorMiddleware`를 지나 ServerErrorMiddleware까지 새면 TestClient가 예외를 다시 던져 테스트가 실패하므로, 미들웨어 순서 회귀를 자동으로 잡는다.
- OpenAPI: 3.4절 항목 검증.
- 실제 Uvicorn에서 500·CORS·로그 정보 비노출을 확인하고 7절에 기록한다. 테스트 전용 앱은 임시 폴더에만 생성한다.
- ruff check·ruff format --check·mypy app·pytest, 문서 링크·JSON 검증, GitHub CI를 실행한다.

## 5. 기능별 커밋 계획

| 순서 | 기능 | 커밋 제목 | 포함할 검증 |
|---|---|---|---|
| 1 | 설계·협업 절차 | docs(be): 공통 API 설계와 Claude 검토 절차 기록 | Claude의 설계 수정 완료, 링크·JSON 확인 |
| 2 | 공통 외피·오류 분류 | feat(be): 공통 응답과 오류 코드 모델 보강 | `ErrorCode`·`ERROR_SPECS`·`ApiResponse` 불변식·`ErrorResponse`·`error_response` 단위 테스트, health 응답 불변 |
| 3 | 요청·도메인·HTTP 오류 handler | feat(be): 요청 검증과 HTTP 오류 응답 통일 | AppError·422·404/405(Allow)·HTTPException 헤더·204/304, OpenAPI 422/500 선언과 `HTTPValidationError` 부재 |
| 4 | 미처리 예외·CORS 순서 | feat(be): 내부 예외 응답과 전체 CORS 적용 | `UnhandledErrorMiddleware`, 미들웨어 순서, 500 CORS 헤더, 로그·응답 정보 비노출 |
| 5 | 계약 문서·작업 결과 | docs(be): 공통 오류 응답과 검증 결과 정리 | README·통합계획서 정합성, 7절 결과 기록, 전체 검사 |

기능 변경과 해당 테스트는 같은 커밋에 담는다. 검토 결과 범위가 달라지면 코드 작성 전에 이 표를 수정한다. 설계·구현·테스트를 한 커밋에 몰아넣지 않는다.

## 6. Claude Code 검토 기록

Claude Code가 이 MD를 직접 읽고 검토한 뒤 Edit 도구로 1~6절을 수정했다. 코드·다른 문서·Git은 수정하지 않았고 명령도 실행하지 않았다. 따라서 아래 FastAPI 0.162.2/Starlette 동작은 공개된 동작 기준의 설계 판단이며, 4절 테스트로 구현 시 확인해야 한다.

### 6.1 변경 내용과 이유

| 절 | 변경 | 이유 |
|---|---|---|
| 1 | `ErrorCode` StrEnum, `extra="forbid"`, `model_validator`, meta 항상 `{}`, `exclude_none` 금지, `ErrorResponse` 이름 고정, 단일 `error_response` 팩터리 | non-null 외피 불변식을 타입·직렬화 양쪽에서 강제하고 OpenAPI 스키마 이름을 안정화 |
| 2 | 예외별 처리 계층 표, 로그는 클래스 이름만, `ResponseValidationError` 처리 명시 | `logger.exception`·`str(exc)`는 입력값·응답 body를 포함할 수 있음 |
| 2 | HTTPException 헤더를 허용 목록 대신 그대로 전달, 204/304 무본문 | 헤더는 서버 코드가 정하는 프로토콜 값이며 `WWW-Authenticate` 등을 깨지 않는 가장 단순한 방법. 위험 요소인 `detail`만 버림 |
| 2.2 | 알 수 없는 경로·메서드의 정확한 JSON·헤더 계약 고정 | 9개 코드 밖으로 확장하지 않고 FE가 예측 가능한 응답을 받도록 함 |
| 3 | `Exception` handler가 CORS 바깥 ServerErrorMiddleware에서 실행되는 문제를 명시하고, CORS 안쪽 순수 ASGI `UnhandledErrorMiddleware` 채택 | 500에도 CORS 헤더 보장. `create_app() -> FastAPI` 유지로 테스트 factory 호환. 앱 전체 래핑·BaseHTTPMiddleware는 기각 |
| 3.4 | 422/500 응답 상수와 `HTTPValidationError` 제거 방식 | 실제 422 외피와 OpenAPI 불일치 해소 |
| 4 | 500 테스트를 `raise_server_exceptions=True`로 변경, 정보 비노출·CORS 대상 확대, Uvicorn 확인은 선택 수동 | `False`면 미들웨어 순서가 틀려도 테스트가 통과해 회귀를 놓침 |
| 5 | 커밋 3을 handler(3)와 미처리 예외·CORS(4)로 분리 | 독립적으로 검증·리버트 가능한 단위 |

### 6.2 잔여 쟁점(구현 범위 밖, 원본 명세·후속 작업에서 결정)

- 404/405/401/403/429 등 일반 4xx를 모두 INVALID_PARAM으로 묶는 것이 원본 API 명세와 맞는지 확인 필요. 맞지 않으면 enum 추가는 명세 확인 후 별도 이슈로 한다.
- 상세 meta·DataVersion은 원본 명세 확인 전 보류(변경 없음).
- Uvicorn access log는 요청 경로와 query string(주소 등)을 기록할 수 있다. 이번 범위에서 끄거나 바꾸지 않으며 BE-35 로그 설계에서 다룬다.
- 응답 헤더 전송 후 발생한 예외와 CORS 미들웨어 자체 예외는 fallback 경로로 가며 Starlette가 traceback을 출력할 수 있다. 드문 경우로 보고 BE-35에서 함께 다룬다.
- 미허용 origin preflight의 400 텍스트 응답은 외피가 아니다(프로토콜 응답으로 의도적 유지).

### 6.3 Codex 재검토 결정

- Claude의 수정본을 읽고 CORS 안쪽 순수 ASGI 구조와 5개 기능별 커밋 구성을 채택했다.
- 실패 OpenAPI 스키마의 error를 필수로 선언하고, HTTPException 상태 보존용 factory 인자를 명시해 초안의 타입·상태 모순을 해소했다.
- Claude의 모든 HTTPException 헤더 전달 제안은 채택하지 않고 프로토콜 헤더 3개만 보존한다. 비밀값을 넣은 임의 헤더가 제거되는 테스트를 추가한다.
- Uvicorn 기본 access log가 query를 기록하므로 실행 안내에 `--no-access-log`를 추가한다. 응답 시작 후 예외·미들웨어 자체 오류의 스트리밍/인프라 로그 정책은 BE-35에 남긴다. 이번 비노출 검증은 응답 시작 전 애플리케이션 예외를 대상으로 한다.
- PR 생성 전 로컬 테스트·lint·타입 검사를 통과해야 하며 실패하면 수정 후 다시 실행한다. PR은 develop 대상으로 생성하고 병합은 별도 요청을 기다린다.

## 7. 구현·검증 결과

### 기능별 커밋

| 커밋 | 기능 |
|---|---|
| `e3e7f42` | 설계서와 Codex·Claude 협업 및 PR 전 검사 절차 |
| `50511e7` | 공통 응답 불변식·ErrorCode·고정 오류 매핑과 단위 테스트 |
| `02bb835` | 요청·도메인·HTTP 예외와 OpenAPI 오류 스키마 |
| `e741404` | 미처리 예외·CORS 및 정보 비노출 테스트 |
| 최종 문서 커밋 | README·통합 계획서·이 결과 기록 |

### 로컬 검증 결과

- ruff check·ruff format --check·mypy app 통과.
- pytest 전체 69개 통과. Starlette가 httpx 테스트 클라이언트의 향후 전환을 안내하는 deprecation 경고 1개는 남아 있으며 실패는 아니다. 의존성 전환은 별도 호환성 검토 대상으로 둔다.
- 중간 검사에서 발견한 테스트 함수 줄 길이와 import 위치의 문법 오류는 수정 후 재검증했다. 실패 상태로 PR을 생성하지 않았다.
- 실제 Uvicorn 임시 테스트 앱에서 HTTP 500의 공통 응답·허용 CORS, 예외/쿼리 더미 문자열 및 traceback의 로그 비노출을 확인했다. 임시 앱·프로세스는 종료·정리했고 운영 코드에 테스트 경로를 넣지 않았다.
- 상세 meta·DataVersion은 미구현이며 DB·ETL·FE는 변경하지 않았다. PR 생성 후 GitHub CI를 확인하고 결과를 사용자에게 보고한다.
