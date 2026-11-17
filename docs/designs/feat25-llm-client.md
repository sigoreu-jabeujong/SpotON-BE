# 작업 25: AI 공급자 분리 LLM client

## 상태와 범위

- 이슈: [#25 AI 공급자 분리 LLM client 구현](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/25)
- 브랜치: `feat#25-llm-client`, 대상 브랜치: `develop`
  - 작업계획서는 `feat#{작업순번}`이지만, 팀원이 최근 `feat#24`처럼 이슈 번호를 쓰고 있어 순번 충돌을 피하려고 이슈 번호 25를 썼다. CI push 트리거 `feat#*`에 해당하므로 브랜치 CI가 돈다.
- canonical 작업: BE-29 (PHASE 6)
- 목적: 이후 AI 해석 API(BE-32)가 공급자와 무관하게 호출할 LLM client를 만든다. 시간 제한·호출 한도·429 대응을 client 안에서 끝내고, 실패는 한 경로로 `AI_UNAVAILABLE`에 매핑해 지표 API와 AI 장애를 분리한다.
- 포함:
  - `app/ai/client.py`: 공급자 독립 요청·결과 타입, `LlmClient` Protocol, 내부 오류 종류, `AI_UNAVAILABLE` 매핑
  - `app/ai/limits.py`: 재시도 정책(제한된 지수 백오프·full jitter·전체 시간 예산), 프로세스 내 분당·일일 요청 한도
  - `app/ai/gemini.py`: Gemini `generateContent` REST 어댑터
  - `app/ai/factory.py`: 설정으로 client를 고르는 `create_llm_client`
  - 의존 방향은 `factory → gemini → limits → client` 한 방향이다. `client.py`가 공급자 모듈을 import하지 않아 순환 import가 생기지 않는다.
  - `app/core/config.py`·`.env.example`: LLM 시간·재시도·한도 설정
  - `httpx.MockTransport`와 가짜 시계·sleep 기반 단위 테스트
- 제외:
  - AI 입력 집계 추출(BE-28), 프롬프트와 `PROMPT_VERSION`(BE-30), 결과 JSON·숫자·출처 검증과 1회 재생성(BE-31), `POST /api/risk/interpret` 라우터(BE-32), Risk·AI 캐시(BE-34), 운영 로그(BE-35)
  - API 라우터·응답 형식·오류 코드 추가, DB·migration 변경
  - 다중 프로세스·다중 서버 간 공유 한도(Redis 등)
  - 실제 Gemini 호출 자동 검증. 키가 생기면 수동 호출 결과를 이 문서에 따로 기록한다.

### 선행 조건과 중단 조건

- 선행 작업 BE-00~06 공통 응답·오류 코드·설정은 develop에 있다. `ErrorCode.AI_UNAVAILABLE`(503)은 이미 정의돼 있어 새 코드를 만들지 않는다.
- 실제 개발 DB가 필요 없다. DB 연동 지연 규칙(작업계획 3절)의 중단 경계에 해당하지 않는다.
- 팀원 안내에 따라 API 계약·지표 값이 확정되기 전에 할 수 있는 독립 작업으로 선택했다. 응답 계약을 건드리지 않는다.
- 중단 조건: 구현 중 API 응답 형식이나 오류 코드 변경이 필요해지거나, 검사(ruff·mypy·pytest)·PR CI를 통과시키지 못하면 PR을 만들지 않고 보고한다.

## 1. 공급자 독립 인터페이스 (`app/ai/client.py`)

```python
@dataclass(frozen=True)
class LlmRequest:
    system_instruction: str = field(repr=False)
    user_content: str = field(repr=False)  # BE-28이 만든 집계 JSON 문자열
    response_json_schema: Mapping[str, JsonValue] | None = field(default=None, repr=False)
    max_output_tokens: int | None = None  # None이면 설정 기본값, 1~65536


@dataclass(frozen=True)
class LlmUsage:
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LlmResult:
    text: str = field(repr=False)
    provider: str
    model: str
    usage: LlmUsage
    attempts: int


class LlmClient(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate(self, request: LlmRequest) -> LlmResult: ...
```

- 프롬프트·스키마·생성 결과 필드는 `field(repr=False)`로 둔다. 예외 트레이스백이나 디버그 출력에 원문이 남지 않게 하기 위해서다.
- 출력은 항상 JSON 텍스트를 요청한다(작업계획 8절 "AI JSON 검증"). client는 JSON 파싱·스키마 검증을 하지 않고 원문 텍스트만 돌려준다. 파싱·검증·재생성은 BE-31 범위다.
- `provider`·`model`·`attempts`·토큰 사용량은 BE-34 캐시 키(model)와 BE-35 로그(성공/실패·소요)에 쓸 수 있는 비식별 메타데이터다.
- client는 입력 내용을 검사하지 않는다. 주소·좌표·점포 식별정보를 빼는 허용 필드 추출은 BE-28의 책임이다. 이 문서는 그 경계를 명시만 한다.

### 오류 종류

client 밖으로는 `LlmError`만 나간다. 메시지는 종류 이름뿐이며 공급자 본문·URL·키·프롬프트를 담지 않는다.

| `LlmErrorKind` | 조건 | 재시도 |
|---|---|---|
| `not_configured` | 키 없음, 지원하지 않는 `LLM_PROVIDER`, 형식이 잘못된 `LLM_MODEL` | 안 함 |
| `rate_limited` | 공급자 429, 또는 프로세스 내 분당 한도 초과 | 429만 예산 안에서 재시도 |
| `quota_exhausted` | 프로세스 내 일일 한도 소진 | 안 함 |
| `timeout` | 요청 timeout, 또는 전체 시간 예산 소진 | 예산 안에서 재시도 |
| `upstream` | 네트워크 오류, 500·503·504(재시도), 그 밖의 비성공 상태 400·401·403·404 등(재시도 안 함) | 상태별 |
| `blocked` | `promptFeedback.blockReason` 존재, 또는 안전·정책 계열 `finishReason` | 안 함 |
| `incomplete` | `finishReason = MAX_TOKENS` | 안 함 |
| `malformed_response` | JSON 파싱 실패, 후보 없음, 텍스트 없음, 알 수 없는 `finishReason` | 안 함 |

- `to_app_error(error) -> AppError`는 모든 종류를 `AppError(ErrorCode.AI_UNAVAILABLE)`로 바꾼다. 종류별 HTTP 상태를 새로 만들지 않는다(작업계획 6절: 공급자 429는 기존 `AI_UNAVAILABLE`).
- `AI_VERIFY_FAILED`는 client가 만들지 않는다. 생성 결과의 의미 검증 실패는 BE-31이 판단한다. `incomplete`·`malformed_response`도 공급자 응답 자체가 쓸 수 없다는 뜻이므로 `AI_UNAVAILABLE`로 둔다. BE-31 설계에서 재생성 대상으로 바꿀 수 있다.
- `httpx` 예외 문자열에는 요청 URL이, Pydantic `ValidationError`에는 응답 원문이 들어간다. 원인 예외가 `LlmError`에 붙지 않게 **`except` 블록 안에서는 오류 종류만 기록하고 `LlmError`는 블록 밖에서 발생시킨다.** `raise ... from None`은 `__cause__`만 비우고 `__context__`에는 원래 예외를 남기므로 그것만으로는 부족하다.

### client 생성 (`app/ai/factory.py`)

`create_llm_client(settings, *, limiter=None, transport=None) -> LlmClient`

- `llm_provider == "google"`이면 `GeminiClient`, 그 밖이면 호출 시 `not_configured`를 내는 `UnavailableLlmClient`를 돌려준다. 설정 오류로 앱 시작이 실패하지 않게 해 지표 API가 계속 동작하도록 한다(작업계획 8절).
- 한도 카운터는 client 인스턴스가 가진 `RequestLimiter`에 있다. 요청마다 client를 새로 만들면 한도가 초기화되므로 **BE-32는 앱 수명 동안 하나를 만들어 재사용해야 한다**(예: `app.state`). 이번 작업은 라우터를 만들지 않으므로 연결은 BE-32 범위다.

## 2. 시간 제한·재시도·한도 (`app/ai/limits.py`)

### 재시도 정책

- 요청 하나의 timeout은 `LLM_REQUEST_TIMEOUT`(기본 10초, 1~60). 실제 timeout은 `min(요청 timeout, 남은 예산)`이다.
- 전체 시간 예산은 `LLM_TIME_BUDGET`(기본 20초, 1~120). 첫 요청 시작부터 재시도 대기까지 포함한다.
- 재시도 횟수는 `LLM_MAX_RETRIES`(기본 2, 0~5). 최초 시도 + 최대 2회 재시도다.
- 대기 시간은 full jitter 지수 백오프다: `random() × min(LLM_BACKOFF_MAX, LLM_BACKOFF_BASE × 2^재시도순번)`. 기본 base 1초, max 8초. 공식 문제 해결 문서의 "지터를 준 지수 백오프, 최대 재시도 수 제한" 권고를 따른다.
- 대기 후 남은 예산이 없으면 대기하지 않고 마지막 오류로 끝낸다. 예산을 넘겨 잠들지 않는다.
- 재시도 대상: 429, 500, 503, 504, 네트워크 오류, 요청 timeout. 재시도하지 않음: 400·401·403·404 등 클라이언트 오류(공식 문서: 400·402·403은 재시도하지 말 것), 응답 형식·차단·토큰 초과.
- 공식 문서에 429의 `Retry-After` 헤더나 `RetryInfo.retryDelay` 사용이 명시돼 있지 않으므로 이번 작업은 읽지 않는다. 키 제공 후 실제 429 응답을 확인하면 반영을 검토한다.
- 시계·sleep·난수는 생성자에서 주입받아 테스트가 실제로 기다리지 않게 한다.

### 프로세스 내 요청 한도

- `LLM_REQUESTS_PER_MINUTE`, `LLM_REQUESTS_PER_DAY`는 선택 설정이며 기본값은 없음(로컬 제한 없음)이다. 작업계획 8절에 따라 분당 15회 같은 값을 공통 고정값으로 가정하지 않고, 프로젝트 계정의 실제 한도를 확인해 운영 환경에 설정한다.
- 공급자 호출 **시도마다** 한도를 하나씩 쓴다. 재시도도 공급자 요청이므로 센다.
- 분당 한도는 최근 60초 이동 창(monotonic 시계)으로 센다. 가득 차면 기다리지 않고 `rate_limited`로 끝낸다. 요청 처리 중에 분 단위로 기다리면 예산을 넘기기 때문이다.
- 일일 한도는 공식 문서대로 태평양 시간 자정(`America/Los_Angeles`)에 초기화한다. 소진되면 `quota_exhausted`로 끝낸다.
  - Windows는 `zoneinfo`에 `tzdata` 패키지가 필요하다. 현재 잠금 파일에서 psycopg가 Windows 한정으로 설치하므로 동작하지만 간접 의존이다. Linux CI·서버는 시스템 tz 데이터를 쓴다.
- 이 한도는 **프로세스 하나 기준**이다. 공식 문서상 공급자 한도는 API 키가 아니라 프로젝트 단위이므로, 여러 worker·서버로 띄우면 합계가 넘을 수 있다. 최종 방어는 공급자 429 처리이며, 공유 카운터는 배포 구성 확정 후 별도 작업으로 남긴다.
- 분당 토큰 수(TPM)는 로컬에서 세지 않는다. 요청 전 정확한 토큰 수를 알려면 별도 countTokens 호출이 필요해 호출 수가 늘어난다. 초과는 공급자 429로 처리된다. 출력 토큰은 `maxOutputTokens`로 제한한다.
- asyncio 단일 이벤트 루프 안에서만 쓰며 스레드 간 잠금은 두지 않는다.

## 3. Gemini 어댑터 (`app/ai/gemini.py`)

공식 문서(ai.google.dev, 현재 aistudio.google.com으로 이동) 2026-11-11 확인 기준이다.

- `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- 인증: `x-goog-api-key` 헤더(공식 REST 예시 기준). 키를 URL 쿼리에 넣지 않는다. 쿼리 문자열은 프록시·접근 로그에 남을 수 있기 때문이다.
- 모델명은 `^[a-z0-9][a-z0-9.-]*$`에 맞아야 한다. 맞지 않으면 URL 경로를 만들지 않고 `not_configured`다. 기본값 `gemini-3.5-flash-lite`는 공식 모델 페이지에 Stable로 등재돼 있다. 무료 이용 범위와 실제 한도는 공식 문서에 수치가 없어 프로젝트 계정에서 확인 대기다.

요청 본문:

```json
{
  "systemInstruction": {"parts": [{"text": "<system_instruction>"}]},
  "contents": [{"role": "user", "parts": [{"text": "<user_content>"}]}],
  "generationConfig": {
    "responseMimeType": "application/json",
    "maxOutputTokens": 2048,
    "responseJsonSchema": {"...": "스키마가 있을 때만"}
  }
}
```

- `responseJsonSchema`는 공식 문서가 내부용 `responseSchema` 대신 쓰라고 안내하는 필드다.
- `temperature`는 보내지 않는다. 공식 문서상 최신 모델에서 무시되며, 값을 정할 근거가 없다.
- `systemInstruction`(Content 형식)은 이번 확인에서 generateContent 요청 필드 목록 원문을 읽지 못해 **확인 대기**다. 텍스트 생성 문서의 `system_instruction` 문자열 예시는 별도의 Interactions API(`/v1beta/interactions`) 것이라 근거로 쓰지 않는다. Google API의 proto JSON은 camelCase를 표준 표기로 쓰므로 `systemInstruction`으로 구현하고, 키 제공 후 수동 호출로 확인한다.
- 응답 `Part.thought`(boolean, "Indicates if the part is thought from the model")는 공식 API 참조에서 확인했다.
- httpx `AsyncClient`는 호출마다 열고 닫는다(기존 카카오 어댑터와 같은 방식). 테스트는 `transport`를 주입한다.
- `LLM_MAX_OUTPUT_TOKENS` 기본 2048(1~65536). 모델 출력 상한 65,536 이하다.

응답 처리(사용하는 필드만 Pydantic으로 선언, 나머지 무시):

1. 200이 아니면 2절 표에 따라 `rate_limited`·`upstream`으로 분류한다. 본문은 읽지 않는다.
2. 본문이 JSON이 아니거나 구조가 맞지 않으면 `malformed_response`.
3. `promptFeedback.blockReason`이 있으면 `blocked`.
4. `candidates`가 비어 있으면 `malformed_response`. 첫 후보만 쓴다.
5. `finishReason`: `STOP` → 정상, `MAX_TOKENS` → `incomplete`, `SAFETY`·`RECITATION`·`LANGUAGE`·`BLOCKLIST`·`PROHIBITED_CONTENT`·`SPII` → `blocked`, 그 밖이거나 없음 → `malformed_response`.
6. `content.parts[].text`를 순서대로 이어 붙인다. `thought: true`인 사고 과정 part는 제외한다. 결과가 공백뿐이면 `malformed_response`.
7. `usageMetadata.promptTokenCount`·`candidatesTokenCount`·`totalTokenCount`를 `LlmUsage`로 옮긴다. 없으면 null.

## 4. 설정

`Settings`에 추가하고 `.env.example`에도 같은 이름을 추가한다. 실제 `.env`는 읽거나 출력하지 않는다.

| 환경변수 | 기본값 | 범위 |
|---|---|---|
| `LLM_REQUEST_TIMEOUT` | 10 | 1~60초 |
| `LLM_TIME_BUDGET` | 20 | 1~120초 |
| `LLM_MAX_RETRIES` | 2 | 0~5 |
| `LLM_BACKOFF_BASE` | 1 | 0 초과~10초 |
| `LLM_BACKOFF_MAX` | 8 | 0 초과~60초 |
| `LLM_MAX_OUTPUT_TOKENS` | 2048 | 1~65536 |
| `LLM_REQUESTS_PER_MINUTE` | 없음 | 1 이상, 빈 값은 없음 |
| `LLM_REQUESTS_PER_DAY` | 없음 | 1 이상, 빈 값은 없음 |

- 기존 `LLM_PROVIDER`·`LLM_MODEL`·`LLM_API_KEY`는 그대로 쓴다. 키는 `SecretStr`로 보관하고 헤더를 만들 때만 꺼낸다.
- 한도 두 값은 `.env.example`에 빈 값으로 두므로 빈 문자열을 None으로 바꾸는 before 검증기를 둔다.
- 범위 밖 숫자 설정은 기존 설정과 같이 시작 시 검증 오류다. 반면 공급자·모델명 오류는 1절대로 호출 시 `not_configured`로 처리한다.

## 5. 보안·개인정보

- 프롬프트·스키마·생성 결과·API 키를 로그, 예외 메시지, `repr`, 응답에 남기지 않는다. 이 모듈은 로그를 쓰지 않는다.
- 기존 `configure_sensitive_request_logging()`이 `httpx`·`httpcore` 로거를 WARNING으로 고정하므로 요청 URL이 INFO로 남지 않는다. URL에는 모델명만 있고 키는 헤더에 있다.
- 공급자 오류 본문은 읽지 않는다. 오류 본문에 요청 일부가 되돌아올 수 있기 때문이다.
- 외부 전송 허용 필드 제한(주소·좌표·building_key·floor_unit·상호·license_no 제외)은 BE-28에서 보장한다. client는 받은 문자열을 그대로 전송한다.

## 6. 테스트 계획

모두 DB·네트워크 없이 `httpx.MockTransport`, 가짜 시계, 기록용 sleep으로 실행한다.

`tests/ai/test_limits.py`
- 백오프: 재시도 순번별 상한(1, 2, 4, 8, 8초), 난수 0·1 경계, max 이하 유지
- 분당 한도: 60초 안 초과 시 `rate_limited`, 60초 지난 뒤 다시 허용, 설정 없음이면 무제한
- 일일 한도: 소진 시 `quota_exhausted`, 태평양 시간 자정 전후 초기화

`tests/ai/test_gemini.py`
- 정상: URL·`x-goog-api-key` 헤더·본문(`systemInstruction`·`contents`·`generationConfig`), 스키마 유무, 키가 URL에 없음, 텍스트 합치기·사고 part 제외, usage 매핑, `attempts=1`
- 429 후 성공: sleep 호출과 `attempts=2`, 재시도 순번별 대기 상한
- 429 계속: 최대 재시도 후 `rate_limited`, 총 시도 수 = 1 + max_retries
- 예산: 대기가 남은 예산을 넘으면 기다리지 않고 종료, 요청 timeout이 남은 예산으로 줄어듦
- 500·503·504·네트워크 오류·timeout 재시도, 400·401·403·404는 1회만 호출
- 응답: 비JSON, 후보 없음, `blockReason`, `SAFETY`, `MAX_TOKENS`, 알 수 없는 finishReason, 빈 텍스트
- 설정: 키 없음·잘못된 모델명은 공급자 호출 0회로 `not_configured`
- 한도 연동: 재시도도 한도를 소모, 일일 한도 소진 시 호출 0회
- 비노출: 모든 `LlmError`의 `str`·`repr`·`__cause__`/`__context__` 체인과 caplog에 키·프롬프트·응답 원문이 없음, `LlmRequest`·`LlmResult` repr에 원문 없음

`tests/ai/test_client.py`
- 모든 `LlmErrorKind`가 `AI_UNAVAILABLE`(503)로 매핑
- `create_llm_client`: google → Gemini, 미지원 공급자 → 호출 시 `not_configured`, 공급자 호출 0회
- 비노출 확인은 `__cause__`뿐 아니라 `__context__`가 None인지까지 본다.

`tests/test_config.py`
- 새 설정 기본값, 범위 밖 값 거절, 빈 한도 값 → None, `.env.example`에 새 변수 이름 존재

통합 테스트(PostGIS)는 해당 없음. CI의 `postgis-integration`은 기존 테스트로 계속 통과해야 한다.

## 7. 완료 조건

- 위 테스트와 기존 테스트, `ruff check`·`ruff format --check`·`mypy app etl migrations`·`pytest` 통과
- PR CI(`lint-and-test`, `postgis-integration`, CodeQL) 통과
- API 응답 형식·오류 코드·DB 변경 없음
- 실제 Gemini 호출 검증은 미실시로 PR에 명시

## 8. 기능별 커밋 계획

1. `docs(be): LLM client 설계와 Claude 검토 기록` — 이 문서
2. `feat(be): 공급자 독립 LLM client 인터페이스 추가` — `app/ai/client.py`(타입·Protocol·오류·매핑), `tests/ai/test_client.py`의 매핑 테스트
3. `feat(be): LLM 요청 한도와 재시도 정책 추가` — `app/ai/limits.py`, 설정·`.env.example`, `tests/ai/test_limits.py`, `tests/test_config.py`
4. `feat(be): Gemini LLM 어댑터 구현` — `app/ai/gemini.py`, `app/ai/factory.py`, `tests/ai/test_gemini.py`, factory 테스트
5. `docs(be): README에 LLM client 설정 안내` — README 한 절

의존 방향(`client` ← `limits` ← `gemini` ← `factory`) 순서로 커밋해 각 커밋이 단독으로 ruff·mypy·pytest를 통과하게 한다.

## 9. 남은 제한

- 실제 Gemini 호출, 무료 범위·한도 수치, `systemInstruction` 필드는 키·계정 확보 후 확인 대기다.
- 한도는 프로세스 단위이며 다중 worker 합산은 막지 못한다.
- 429의 공급자 권장 대기 시간은 사용하지 않는다.
- 공급자는 Gemini 하나만 구현한다. 다른 공급자는 같은 Protocol로 추가한다.

## Claude Code 검토 기록

### 1차 작성 후 재검토 (2026-11-11, Claude Code)

설계 MD를 처음부터 다시 읽고 이슈 #25 범위, 작업계획 6·8절, 기존 `kakao_local` 어댑터 방식, 공식 Gemini 문서와 대조했다. 아래를 이 파일에 직접 고쳤다.

1. **순환 import 제거**: 처음 안에서는 `create_llm_client`가 `client.py`에 있었다. `gemini.py`가 `client.py` 타입을 쓰므로 서로 import하게 된다. 생성 함수를 `app/ai/factory.py`로 분리하고 의존 방향을 한 방향으로 적었다. 커밋 순서도 의존 방향에 맞췄다. 처음 순서는 2번 커밋이 아직 없는 `client.py` 타입을 써서 단독 통과가 안 됐다.
2. **예외 체인 비노출 보강**: `raise ... from None`만 적었는데, 이는 `__cause__`만 비우고 `__context__`에 httpx·Pydantic 예외(URL·응답 원문 포함)를 남긴다. `except` 밖에서 발생시키는 방식으로 바꾸고 테스트에 `__context__` 확인을 추가했다.
3. **외부 계약 확인 상태 정정**: `systemInstruction`은 generateContent 원문에서 확인하지 못했다. 문서 예시의 `system_instruction` 문자열은 다른 API(Interactions)의 것이라 근거에서 뺐다. 확인 대기로 표시하고 `Part.thought`는 확인 완료로 분리했다.
4. **브랜치 정보 갱신**: 브랜치를 `feat#25-llm-client`로 다시 만들었으므로 CI 트리거 설명을 고쳤다.

검토 후에도 유지한 판단과 이유:

- 모든 실패를 `AI_UNAVAILABLE` 하나로 매핑한다. 작업계획 6절이 429를 기존 코드로 매핑하도록 정했고, 새 오류 코드는 FE 계약 변경이라 이번 범위가 아니다.
- 로컬 분당 한도가 가득 차면 기다리지 않고 실패한다. 기다리면 전체 시간 예산(기본 20초)을 넘길 수 있고, 지표 API와 분리된 AI만 실패하므로 사용자 영향이 작다.
- 429 권장 대기 시간을 읽지 않는다. 공식 문서에 명시가 없어 추정 구현을 하지 않는다.
- 입력 필드 검사는 client가 하지 않는다. BE-28과 책임이 겹치면 두 곳의 규칙이 어긋날 수 있다.

남은 제한: 9절과 같다. 실제 Gemini 호출을 하지 않았으므로 요청 필드와 응답 형식은 mock 기준 검증이다.

### 구현 후 점검 (2026-11-11)

구현 코드와 이 설계를 다시 대조했다. 설계와 달라진 점과 확정한 세부 사항은 다음과 같다.

- `LLM_PROVIDER`는 대소문자를 포함해 `google`과 정확히 같아야 Gemini를 쓴다. `Google`·빈 값은 미지원 공급자로 보고 호출 시 `not_configured`다. 설정값을 임의로 정규화하지 않기 위해서다.
- 재시도 상태는 429·500·503·504로 고정했다. 공식 문제 해결 문서는 429·503에 백오프 재시도를, 클라이언트 오류(400·402·403)에 재시도 금지를 안내한다. 500·504는 일시적 서버 오류로 보고 이 작업에서 재시도 대상에 넣었다. 502를 포함한 그 밖의 상태는 명시가 없어 1회로 끝낸다.
- 로컬 분당 한도로 거절된 시도는 일일 한도를 소모하지 않는다. 공급자에 요청이 나가지 않았기 때문이다.
- `max_output_tokens`의 1~65536 범위는 `LlmRequest` 생성 시 검증한다.
- 커밋 1의 설계 MD 코드 블록이 `ruff format --check`(Markdown 코드 블록 포함)를 통과하지 못해 커밋 2에서 실제 구현 형태로 고쳤다. 커밋 1 단독은 format 검사를 통과하지 않는다. PR은 squash 병합하므로 develop에는 영향이 없어 이력을 다시 쓰지 않았다.

로컬 검사 결과: `ruff check`, `ruff format --check`, `mypy app etl migrations`, `pytest` 통과(359 passed, integration 12 deselected). 실제 Gemini 호출과 PostGIS 통합 테스트는 로컬에서 실행하지 않았다.
