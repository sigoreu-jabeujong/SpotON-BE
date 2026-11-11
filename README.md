# SpotON-BE

서울의 카페·음식점 입지 분석을 위한 Spot:ON 백엔드입니다. 개발 기준과 다음 작업은 [통합 작업계획서](docs/be-work-plan.md)에서 관리합니다.

현재는 health·서울 주소 검색·점포 이력·주변 조회·조회 가능 월 범위·과거 점포 상태 분해 API와 인허가 ETL, 상권 경계·공식 점포 통계 버전 적재, 공급자 분리 LLM client를 제공합니다. 개발 DB에는 인허가 점포 689,440건·상권 경계 1,650건·2025년 4개 분기의 공식 지원 업종 통계 24,810행을 적재했습니다. migration `0006`이 현재 head입니다. 경계의 실제 적용 시점/통계 분기 호환은 미확인이며 분석 API와 FE 반영은 후속 작업입니다.

## 로컬 실행

Python 3.11을 설치한 뒤 저장소 루트에서 실행합니다. `uv.lock`을 커밋해 로컬·CI가 같은 의존성을 설치합니다.

```powershell
py -3.11 -m pip install uv==0.13.7
# Windows 한글 경로에서 Python 3.11의 editable 설치 인코딩 오류 방지
$env:UV_NO_EDITABLE = "1"
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

## 점포 이력 조회

`GET /api/stores/history?building_key={건물 키}&floor_unit={선택 상세 위치}&category={선택 진단 업종}`은 같은 건물의 지원 업종 이력을 반환합니다. 키는 `/api/geocode` 결과를 사용합니다. category를 지정해도 다른 지원 업종은 제거하지 않습니다. 삭제·검토 대기·미지원 업종은 제외하고, 개업일 오름차순·날짜 미확인 마지막으로 정렬합니다. 0건은 안내 메시지가 있는 정상 응답입니다.

- 실행 전 `alembic upgrade head`와 검증 snapshot 적재가 필요합니다. 기존 `0002` 데이터는 재적재하기 전 배치 출처가 없을 수 있어 영업 중 점포의 기간이 미산정됩니다.
- 식별자는 `source + license_no`입니다. 날짜·상호·기간은 null을 허용하며 기간은 `operating_period_status`·`operating_period_reason`을 함께 확인합니다. 실제 0개월과 결측을 구분합니다.
- 기간은 달력상 완료 개월 수입니다. 폐업은 확인된 폐업일, 영업 중은 DB에 연결된 검증 배치의 DAT_UPDT_PNT 최대 날짜를 종료점으로 사용합니다. 오늘·DB 적재일로 대체하지 않습니다. 동일한 층만 확인되면 같은 자리라고 표시하지 않습니다.
- `meta.collected_at`은 실제 수집 완료일이 확인되지 않으면 null입니다. CSV 검증 시각과 원천 갱신일·적재일을 구분합니다.
- health·geocode는 DB 없이 동작합니다. 이력 요청은 지연 생성한 DB 엔진과 요청별 읽기 전용 트랜잭션을 사용하고 종료 시 정리합니다. `DATABASE_STATEMENT_TIMEOUT_MS`는 SQL 문장별 제한이며 전체 요청 SLA가 아닙니다. DB 실패·timeout은 원문 없는 500 INTERNAL_ERROR입니다.
- FE의 nullable 기간·복합 식별자 호환은 [FE 수정 요청 보고서](docs/fe-store-history-api-request.md)를 통해 담당자에게 요청하며 아직 반영되지 않았습니다. 후속 API 개발 중에는 FE의 기존 `VITE_USE_MOCK=true`, `VITE_REAL_API_PATHS=/geocode,/stores/history`로 두 API만 실제 연결할 수 있습니다.

설계·원본 계약 차이·검증 기록은 [이슈 36 설계](docs/designs/feat36-store-history-api.md)를 확인합니다. 원본 v1.2 전체 계약의 일괄 동기화 완료를 뜻하지 않습니다.

## 주변 점포 조회

`GET /api/stores/nearby?lat={위도}&lng={경도}&category={cafe|restaurant}`는 선택 시점의 반경 내 지원 점포를 반환합니다. 좌표는 geocode 결과를 사용하고 radius는 300/500/1000m(기본 500), as_of는 선택 YYYY-MM입니다. 과거 월은 월말, 최신 월은 검증 배치의 전역 원천 갱신일을 적용합니다.

- `sub_category`는 음식점 4종 또는 cafe를 쉼표로 전달합니다. 면적·가맹 조건과 독립적인 `include_unknown_area`·`include_unknown_franchise`는 기본 true입니다. 기존 `include_unknown` 단독 전송은 두 조건에 함께 적용하고 개별 토글과 혼합하면 거절합니다.
- 0㎡와 null은 정보 없음입니다. 0㎡ 원본을 수정하지 않으며 응답 `area_m2=null`, 알려진 면적 필터에서는 제외합니다. 가맹 미확인을 개인 매장으로 바꾸지 않습니다.
- 원본 날짜가 유효한 점포에 `open_date<=T AND (close_date IS NULL OR close_date>T)`를 적용합니다. 날짜 미확인·오류, 폐업일 없는 폐업, 한시 영업 true는 제외합니다. 현재 상태와 전체 운영기간은 최신 데이터 기준이며 과거 시점 상태나 T까지의 기간으로 바꾸지 않습니다.
- geography 미터 거리로 반경 경계를 포함합니다. 반올림 전 거리 순서를 유지하며 표시값만 소수 첫째 자리로 반환합니다. 식별자는 `source+license_no`, 상호·기간·면적은 nullable입니다.
- `excluded_no_coord`는 **서울 전체에서 같은 비공간 조건을 만족하는 좌표 미확보 수**이며 반경 내 누락 수가 아닙니다. `meta.excluded_no_coord_scope=seoul_nonspatial_cohort`를 함께 확인합니다.
- 검증된 배치·기준일이 없거나 DB가 실패하면 500입니다. 준비 실패를 정상 0건으로 바꾸지 않습니다. 입력 오류는 422이며 모든 응답은 no-store입니다. 개발 실행은 좌표 query가 access log에 남지 않도록 `--no-access-log`를 유지합니다.

실행 전 migration `0004`까지 적용합니다. [구현·검증 기록](docs/designs/feat41-nearby-api.md), [FE 수정 요청 보고서](docs/fe-nearby-api-request.md)를 확인합니다. FE 화면·CLAUDE.md 반영은 담당자 대기이며 data-range·snapshot API는 이번 범위에 없습니다.

## 조회 가능 월 범위

`GET /api/meta/data-range?category={cafe|restaurant}&sub_category={선택 세부 업종}`은 시점 선택에 필요한 `min_month`, `max_month`, `max_date`, `data_updated_at`, `collected_at`을 반환합니다. 지원 세부 업종은 nearby와 같고 쉼표로 구분합니다. 좌표·반경·면적·가맹 등의 인자는 받지 않습니다.

- nearby와 같은 검증된 인허가 날짜 후보에서 가장 이른 개업 월을 계산합니다. 과거 폐업 점포와 좌표 미확보·속성 미확인도 날짜가 신뢰할 수 있으면 최소 월에 기여합니다. 특정 반경의 결과 존재 범위나 과거 현황 전체 관측을 뜻하지 않습니다.
- 최신 월은 전역 원천 갱신일의 월이며 실제 최신 기준일은 `max_date`입니다. 현재 자료는 `max_month=2026-11`, `max_date=2026-11-08`이고 오늘이나 11월 말일로 바꾸지 않습니다.
- 검증된 D가 있지만 해당 업종의 유효 후보가 없으면 `min_month=null`입니다. FE에는 과거 월·빠른 선택을 비활성화하도록 요청합니다. 출처·기준일 미준비는 500으로 구분하며 최소 월을 임의로 채우지 않습니다.
- 현재 `collected_at=null`을 유지합니다. 모든 응답은 no-store이고 기존 읽기 전용 일관된 세션·안전한 오류 처리를 사용합니다.

[설계·검증](docs/designs/feat43-data-range-api.md), [FE 수정 요청 보고서](docs/fe-data-range-api-request.md)를 확인합니다. 과거 시점 점포 상태 분해는 아래 snapshot API를 사용합니다.

## 과거 시점 점포 상태 분해

`GET /api/stores/snapshot`은 nearby와 같은 파라미터를 받으며 `as_of=YYYY-MM`은 필수입니다. 같은 시점·조건·배치의 nearby 점포 목록을 그대로 사용하고 최신 기록 상태에 따라 `still_open`, `closed_since`, `other`로 나눕니다. `total_at_as_of = still_open + closed_since + other = stores.length`를 보장하고 요약 문장도 서버에서 만듭니다.

- stores는 source+license_no로 식별하며 상호·기간은 nullable입니다. 기간은 최신 데이터 기준 전체 기간이고 과거 T까지로 자르지 않습니다. 상태도 D의 기록이며 실시간 확인값은 아닙니다.
- 최신 월은 D, 과거 월은 월말을 적용합니다. 폐업 당일은 제외하고 유효한 open/closed/other의 날짜 구간으로 과거 집합을 재구성합니다. 빈 결과는 200과 0 집계·빈 목록·요약입니다.
- `excluded_no_coord`는 서울 동일 비공간 조건의 좌표 미확보 수이며 전체 N과 합산하지 않습니다. 날짜 결측·원천 수집 전 누락으로 과거 자료는 불완전할 수 있습니다.
- 동일 목록의 서버 집계와 응답 모델로 합계·상태 분류·식별자 중복을 검사합니다. 위반 시 부분 응답 없이 500·no-store를 반환합니다. 기존 read-only 세션·문장 timeout·안전한 오류 처리를 사용합니다.

[설계·검증](docs/designs/feat45-store-snapshot-api.md), [FE 연동 요청 보고서](docs/fe-store-snapshot-api-request.md)를 확인합니다. FE 타입·표·진단서·CLAUDE.md 반영은 담당자 대기입니다.

## AI LLM client

`app/ai/`는 AI 해석 API(BE-32)가 사용할 공급자 분리 LLM client입니다. 아직 API 경로는 없습니다. `create_llm_client(settings)`가 `LLM_PROVIDER=google`이면 Gemini `generateContent` 어댑터를 만들고, 그 밖의 값은 호출 시 실패하는 client를 돌려줘 설정 오류가 지표 API 시작을 막지 않습니다.

- 키 `LLM_API_KEY`는 서버 전용이며 `x-goog-api-key` 헤더로만 보냅니다. 기본 모델은 `LLM_MODEL=gemini-3.5-flash-lite`입니다.
- `LLM_REQUEST_TIMEOUT`(요청 1회)과 `LLM_TIME_BUDGET`(재시도 대기 포함 전체) 안에서 429·500·503·504·네트워크 오류·timeout만 `LLM_MAX_RETRIES`회까지 지터를 준 지수 백오프로 재시도합니다.
- `LLM_REQUESTS_PER_MINUTE`·`LLM_REQUESTS_PER_DAY`는 프로세스 내 한도이며 비우면 제한하지 않습니다. 일일 한도는 태평양 시간 자정에 초기화합니다. 프로젝트 계정의 실제 한도를 확인해 설정합니다.
- 모든 실패는 기존 `AI_UNAVAILABLE`(503)로 매핑합니다. 프롬프트·생성 결과·키·공급자 오류 본문은 로그와 예외에 남기지 않습니다.
- 한도 카운터가 client 인스턴스에 있으므로 호출하는 쪽은 앱 수명 동안 하나를 재사용해야 합니다.

자동 검증은 mock transport만 사용하며 실제 Gemini 호출은 확인하지 않았습니다. 상세 계약은 [작업 25 설계서](docs/designs/feat25-llm-client.md)에서 확인합니다.

### 프롬프트 버전 관리

AI 해석 프롬프트는 `app/ai/prompts/risk_interpret/`의 `system.md`(시스템 지침)와 `user.md`(`$context_json` 하나만 쓰는 입력 템플릿)로 관리합니다. `build_interpret_request(context)`가 서버 집계를 키 정렬 JSON으로 넣어 `LlmRequest`를 만듭니다.

- 프롬프트 파일을 바꾸면 `app/ai/prompts/version.py`의 `PROMPT_VERSION`을 올리고 `PROMPT_HISTORY` 끝에 새 지문을 추가해야 합니다. 테스트가 현재 파일의 SHA-256 지문과 대조해 누락을 막습니다. 새 지문은 실패한 테스트 메시지에 표시됩니다.
- 주소·좌표·`building_key`·`floor_unit`·상호(`name`)·`license_no` 등 `FORBIDDEN_CONTEXT_KEYS`에 있는 키가 집계에 있으면 조립을 거절합니다. 값 내용은 검사하지 않으므로 허용 필드 추출은 BE-28에서 해야 합니다.
- 시스템 지침은 작업계획의 규칙(입력 숫자만 사용, 공식/참고 구분, pending·no_data, 금지 표현, 참고용 안내)만 담은 초안입니다. 지표 목록과 응답 스키마가 확정되면 보완합니다.

상세 내용은 [작업 27 설계서](docs/designs/feat27-prompt-version.md)에서 확인합니다.

### AI 결과 검증

`app/ai/verifier.py`의 `verify_output()`은 LLM 응답이 JSON 객체인지 확인한 뒤 다음을 검사합니다. 결과에는 실패 종류만 담고 응답 원문은 담지 않습니다.

- 입력 집계(값·문자열·키)에 없는 숫자. 쉼표·`%`·소수 반올림은 허용하고 정수 반올림과 비율↔백분율 환산은 허용하지 않습니다.
- 금지 표현(성공률·성공 확률, 추천/비추천, 위험점수·위험등급, LQ, 단정적 예측). 서울시 `창업위험도` 안내 이름은 허용합니다.
- pending·no_data 지표에 값을 붙인 경우, 입력에 없는 출처(지표 객체의 `id`·`value`·`status`, `source`/`sources` 관례를 따른 응답에 적용)
- 전화번호·이메일·도로명/지번 번호·층호·좌표·building_key 패턴과 식별정보 키
- 분량 상한(기본 2000자)과 같은 문장 반복

`app/ai/verified.py`의 `generate_verified()`는 검증에 실패하면 같은 요청으로 1회 다시 생성하고, 또 실패하면 `AiVerifyFailedError`(→ `AI_VERIFY_FAILED` 503)를 냅니다. 공급자 오류 `LlmError`는 그대로 전달되어 `AI_UNAVAILABLE`과 섞이지 않습니다. 응답 스키마는 아직 확정되지 않아 호출자가 Pydantic 모델을 넘기는 구조만 있습니다. 상세 내용은 [작업 29 설계서](docs/designs/feat29-ai-verifier.md)에서 확인합니다.

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

CORS preflight·문서·리다이렉트·204/304는 프로토콜 응답으로 유지합니다. 응답 시작 후 스트리밍·background task 오류와 서버/인프라 자체 로그 정책은 후속 BE-35 범위입니다. 점포 이력은 배치 출처와 데이터 버전을 제공하며, 전체 API 공통 meta·DataVersion의 원본 v1.2 일괄 동기화는 별도 작업입니다.

## 검증

```powershell
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app etl migrations
uv run --locked --extra dev pytest
```

테스트는 DB·외부 API 없이 health, 공통 응답·오류·OpenAPI·CORS·정보 비노출·환경 설정, DB 설정·세션 제어와 인허가 수집·정제, LLM client의 재시도·한도·응답 분류·비노출, 프롬프트 지문·조립과 AI 결과 검증·재생성을 검증합니다. 실제 SQL·공간 함수·권한·stores upsert는 아래 PostGIS 통합 job에서 수행합니다. 작업별 설계·Claude 검토·검증 결과는 `docs/designs/`에 기록합니다.

## 지방행정 인허가 ETL

기존 수집·정제 모듈을 연결하는 개발용 실행기를 제공합니다. 아래 명령은 저장소 루트에서
Python 3.11 환경으로 실행합니다. `DATA_GO_KR_SERVICE_KEY`는 로컬 `.env`에 디코딩한 값을
설정하며, 키·URL 전체·원문 행은 출력하지 않습니다.

```powershell
# 기본값은 dry-run: 실제 API를 읽지만 DB에 쓰지 않습니다.
uv run --locked --extra dev --no-editable python -m etl.localdata --source general_restaurant --save-snapshot
uv run --locked --extra dev --no-editable python -m etl.localdata --source rest_cafe --save-snapshot

# 기존 API 필드명 CSV와 동봉 검증 보고서를 사용하는 경우 (네트워크·DB 미사용)
uv run --locked --extra dev --no-editable python -m etl.localdata --source general_restaurant --from-csv C:\data\restaurant_seoul.csv --validation C:\data\restaurant_validation.json --save-snapshot

# 수집이 완료된 datasets/localdata/*.json 파일 경로를 지정합니다.
uv run --locked --extra dev --no-editable python -m etl.localdata --source general_restaurant --from-snapshot datasets/localdata/<snapshot>.json --write
```

- source는 `general_restaurant` 또는 `rest_cafe`이며 한 번에 하나씩 처리합니다.
- 서울 25개 관청의 전체 수집·페이지 검증이 성공해야 정제·snapshot 보관으로 넘어갑니다.
  결과 수 변화·잘린 페이지·관청 불일치·호출 실패 시 부분 자료를 적재하지 않습니다.
- `--workers`는 1~4, 기본 1입니다. 실제 요청 시도는 재시도를 포함해 실행당 최대 9,500회로
  제한합니다. 첫 페이지들로 계산한 예상 수집량이 한도를 넘으면 중단합니다. 이미 소비한
  일일 할당량은 별도이므로 이 제한이 제공처의 잔여 한도를 보장하지 않습니다.
- snapshot은 허용 DTO 필드와 관청별 건수·행 해시를 담으며 Git에서 제외됩니다. 실제 자료와
  키를 이슈·PR에 첨부하지 않습니다. API 입력은 수집 시작 KST 날짜로 판정하고, CSV 입력은
  동봉 보고서의 검증시각을 KST로 바꿔 판정합니다. 재생도 같은 날짜를 사용합니다.
- CSV 입력은 UTF-8(API 필드명 헤더)과 PASS/complete 검증 JSON이 필요합니다. 파일 해시,
  실제 행 수·25개 구 분포·관리번호 중복을 다시 검증하며 불필요한 필드는 버립니다.
  검증 보고서는 서명된 원천 증명서가 아니며, 검증시각도 실제 원천 기준일을 증명하지 않습니다.
  `input_kind`·입력/보고서 해시·`as_of_basis`를 snapshot v2에 보관해 이 한계를 구분합니다.
- `--from-csv --write`는 허용하지 않습니다. CSV dry-run으로 만든 snapshot을 확인한 뒤
  같은 파일을 `--from-snapshot --write`로 적재합니다. 원본 CSV·보고서는 수정하지 않습니다.
- `--write`는 localhost의 `spoton_dev`·`spoton_app`만 허용합니다. 연결 후 계정·권한·revision
  `0006`·PostGIS·유일 제약을 다시 검사하고 원천별 한 트랜잭션으로 점포와 배치 출처를 적재합니다.
- 같은 snapshot으로 다시 실행하면 기존 `(source, license_no)`를 갱신합니다. `affected`는
  성공적으로 처리한 입력 수이고, 값이 실제로 변경된 행 수를 뜻하지 않습니다.
- 실제 원천은 성공 코드 `0`, 날짜 `YYYY-MM-DD`, 갱신시각 `YYYY-MM-DD hh:mm:ss`를 사용합니다.
  기존 `00`·compact 날짜/시각도 허용하며 잘못된 형식은 정상값으로 추정하지 않습니다.

현재 실행·실제 적재 검증 상태는 [작업 34 설계와 검증 기록](docs/designs/feat34-localdata-import.md)을
확인합니다. 실행기 추가만으로 원천 전체 적재나 점포 이력 API 구현이 완료된 것은 아닙니다.

일반음식점·휴게음식점 공식 API의 페이지 수집, 서울 25개 관청 코드 검증, 중복 제거, 날짜·상태·업종·면적 정제, EPSG:5174 원 좌표 보존과 EPSG:4326 변환, stores 멱등 upsert를 모듈로 제공합니다.

- `DATA_GO_KR_SERVICE_KEY`는 디코딩된 서비스 키를 로컬 `.env` 또는 서버 시크릿에만 설정합니다.
- 전화번호·홈페이지·대표자와 원천 JSON 전체는 DTO·DB·로그·리포트에 저장하지 않습니다.
- 실행기의 실제 전체 적재 완료 여부는 작업 34 검증 기록을 따릅니다. repository는 호출자가
  명시적으로 전달한 PostgreSQL 연결만 사용합니다.
- `building_key`·`floor_unit` 정규화는 구현돼 있습니다. 주소·좌표 보완과 삭제 동기화는
  후속 작업입니다.

상세 계약과 검증 근거는 [작업 5 설계서](docs/designs/feat5-license-etl.md)에서 확인합니다.

## 상권 경계 적재 (BE-16)

출처는 서울특별시·서울신용보증재단의 [서울시 상권분석서비스(영역-상권), OA-15560](https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do)입니다. 공공누리 1유형(출처표시, 상업적 이용·변경 가능)이며 갱신은 비정기입니다. SHP/SHX/DBF/PRJ/CPG가 포함된 공식 ZIP과 기대 SHA256·첨부파일 수정일을 사용합니다. 원본은 저장소 밖에 보관합니다.

```powershell
# 기존 DATABASE_URL로 로컬 개발 DB identity를 확인한 후 현재 head 적용
uv run --locked --extra dev alembic upgrade head

# 기본 dry-run: 읽기 전용 DB 공간 검사, insert 없음
uv run --locked --extra dev python -m etl.market_areas `
  --zip "<공식 ZIP 경로>" `
  --expected-sha256 "<ZIP SHA256>" `
  --source-file-date 2023-10-23
# 검증 결과를 확인한 뒤 같은 명령에 --write를 추가해 적재
```

- 현재 검증 ZIP은 2,123,078 bytes, SHA256 `38bb8fab4e45a1171af4989cd7fa1275f68e5d644aa770f5431ce7ccc38384dd`입니다. UTF-8·EPSG:5181의 1,650개 고유 상권·25개 구·4유형을 확인했습니다. 이 해시/날짜는 해당 파일에만 사용하며 새 파일의 값을 임의로 같게 두지 않습니다.
- `source_file_date=2023-10-23`은 공식 첨부 수정일입니다. 내부 파일 날짜 2023-10-20·포털 갱신일 2026-09-11·DB loaded_at과 구분합니다. 실제 경계 적용일은 확인되지 않아 `boundary_as_of=null`입니다. 최신/과거 분기에 자동 적용하지 않으며 BE-17/23에서 코드·경계 호환을 검증합니다.
- market_area_versions는 원본 해시/규칙별 불변 버전, market_areas는 `(version_id, market_code)`별 MULTIPOLYGON 4326·GIST를 저장합니다. 기존 상권 간 겹침·빈 공간·hole·분리 영역은 보존하고 대표 상권을 선택하거나 합치지 않습니다.
- 원본의 RELM_AR을 area_m2로 보존합니다. 기하 면적은 덮어쓰지 않습니다. 무효 도형만 linework로 보정하며 차원 붕괴/빈 면/변환 후 무효/서울권 bbox 밖/원본 면적 대비 1% 초과 차이는 전체 실패입니다. 현재 파일은 6개 보정 후 모두 유효합니다.
- ZIP hash/CRC·해제 크기·경로·sidecar·CRS·필드·중복·25개 구 완전성을 검사합니다. 32MiB ZIP·64MiB 해제·20,000행·500,000점 상한이 있으며 모호한 winding/고아 hole을 거절합니다. 원문 geometry·경계명·코드·접속 정보는 출력하지 않습니다.
- 기본 dry-run은 READ ONLY입니다. 쓰기는 localhost의 spoton_dev·spoton_app·일반 권한·PostGIS·head 0005에서만 허용하며 advisory transaction lock 후 버전과 전체 행을 한 트랜잭션으로 적재합니다. 중간 실패는 모두 rollback하고 부분 성공하지 않습니다.
- 같은 원본/규칙은 DB 속성·NDR EWKB 기반 digest를 다시 읽어 확인한 뒤 `reused=true, inserted=0`입니다. 원래 loaded_at/행을 바꾸지 않으며 훼손 버전은 자동 수리하지 않습니다. 새 원본/규칙은 새 버전으로 공존하고 자동 active/최신 승격·삭제 경로는 없습니다.
- source gu_code는 5자리 SIGNGU_CD입니다. 점포의 7자리 관청 코드와 바로 조인하지 않습니다. 공개 API·FE 응답은 변경하지 않았습니다.

실제 적재·재실행·원자료 표본·데이터 보존 검증은 [이슈 47 기록](docs/designs/feat47-market-areas-import.md)을 확인합니다. 소진공 상가정보(R7)는 현재 필수 ETL에서 사용하지 않습니다.

## 공식 점포·개폐업 통계 적재 (BE-17)

출처는 서울특별시·서울신용보증재단 [상권분석서비스(점포-상권), OA-15577](https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do), 공공누리 1유형 출처표시입니다. 공식 연간 ZIP을 저장소 밖에 두고 첨부 수정일·기대 SHA256·완료된 연도·대조 경계 UUID를 명시합니다. 명령 자체는 네트워크 다운로드를 하지 않습니다.

```powershell
uv run --locked --extra dev python -m etl.market_stores `
  --zip "<저장소 밖 공식 연간 ZIP 경로>" `
  --expected-sha256 "<ZIP SHA256>" `
  --source-year 2025 --source-file-date 2026-05-21 `
  --code-check-boundary-version "<대조할 market_area_versions UUID>"
# 기본은 READ ONLY dry-run입니다. 확인 후 같은 명령에 --write를 추가합니다.
```

- 현재 검증 파일은 2,119,809 bytes, SHA256 `133bfc6ce79e13ee5b289490e4667dfba46a0af5d0d71df360a0d324e030a4e6`, 내부 CP949 CSV 31,051,537 bytes입니다. 첨부 수정일 2026-05-21과 통계 분기 20251~20254를 구분하며 최신 API 분기를 보장하지 않습니다.
- 원본 304,775행 전체를 검증하고 CS100001/2/3/4/10 지원 업종 24,810행만 저장합니다. 분기별 6,219/6,215/6,191/6,185행, 나머지 279,965행은 미지원 업종 제외입니다. 없는 조합을 점포 0으로 채우지 않습니다.
- `SIMILR_INDUTY_STOR_CO`가 **전체**, `STOR_CO`가 **일반**, `FRC_STOR_CO`가 **가맹** 점포 수입니다. 전체=일반+가맹을 검사하고 개폐업 수·공식 원천 비율을 그대로 보존합니다. 100% 초과 비율을 자르거나 다시 계산하지 않으며 빈 비율(null)과 실제 0을 구분합니다.
- market_store_versions는 ZIP/CSV hash·내부 파일 시각·인코딩·규칙·집계·코드 대조 결과를 저장합니다. market_stores는 `(version_id, market_code, quarter, induty_cd)`로 구분하며 같은 원본/규칙/대조 경계의 재실행은 UUID·loaded_at·내용을 유지하고 삽입 0건입니다. 전체 연도를 한 트랜잭션으로 적재하며 실패 시 버전과 행을 모두 롤백합니다.
- 대조 경계의 실제 내용 hash를 확인하고 분기별 양방향 코드·유형·명칭 차이를 건수로 남깁니다. 현재 코드/유형은 일치하고 명칭 차이는 분기별 1개입니다. `code_check_boundary_version_id`는 대조 근거이며 적용 경계 확정이 아닙니다. `boundary_compatibility=unverified`와 기존 `boundary_as_of=null`을 유지합니다.
- 공식 통계와 인허가 점포의 모집단 동일성·분기별 유효 경계는 미확인입니다. 공식 비율을 반경 지표로 합산/평균하거나 참고 폐업률로 바꾸지 않습니다. 공개 API·FE 변경은 없습니다. 적재된 공식 통계가 있으면 migration downgrade는 실패하며 기존 버전 수정·삭제나 최신 자동 선택을 하지 않습니다.

설계·Claude 검토·실제 검증은 [이슈 49 기록](docs/designs/feat49-market-stores-import.md)을 확인합니다.

## PostgreSQL·PostGIS 설정과 마이그레이션

### Docker 로컬 개발 DB

Docker Desktop의 Linux engine이 실행 중이어야 합니다. Windows에서는 WSL 2 설치·활성화 후 재부팅이 필요할 수 있습니다.

`.env.example`을 `.env`로 복사하고 `SPOTON_DB_ADMIN_PASSWORD`와 `SPOTON_DB_PASSWORD`에 서로 다른 임의 비밀번호를 설정합니다. 기존 `.env`는 덮어쓰지 않습니다. `DATABASE_URL`은 `postgresql+psycopg://spoton_app:<앱 비밀번호>@127.0.0.1:5432/spoton_dev`로 설정합니다. URL의 특수문자는 percent-encoding하고, 포트를 바꾸면 `SPOTON_DB_PORT`와 URL 포트를 함께 수정합니다.

```powershell
# 저장소 루트에서 실행. config --quiet는 비밀번호를 출력하지 않습니다.
$env:UV_NO_EDITABLE = "1"
docker compose config --quiet
docker compose up -d --wait db
docker compose ps

# 로컬 개발 DB 접속 설정을 확인한 뒤 기존 migration 적용
uv run --locked --extra dev alembic upgrade head
uv run --locked --extra dev alembic current

# 데이터는 유지하고 컨테이너만 중단
docker compose stop db
```

CI와 동일한 digest의 PostGIS 이미지를 사용하며 포트는 `127.0.0.1`에만 엽니다. `spoton_admin`은 초기화 계정이고, 백엔드는 superuser 권한이 없는 `spoton_app`으로 연결합니다. 앱 계정에는 자체 테이블·migration 생성을 위한 public 스키마 권한을 부여합니다.

데이터는 Compose의 `postgres_data` named volume에 보존합니다. `down -v`는 데이터를 삭제하므로 일반 중단에 사용하지 않습니다. 초기화 스크립트와 암호 설정은 **빈 볼륨의 최초 실행에만** 적용됩니다. 기존 볼륨에서 `.env`만 바꾸면 DB 계정 암호는 바뀌지 않습니다.

Windows의 한글 경로에서는 Python 3.11이 editable 설치의 `.pth` 파일을 시스템 인코딩으로 읽다가 시작에 실패할 수 있습니다. 위 `UV_NO_EDITABLE`은 현재 PowerShell 창에 적용되므로 새 창에서는 다시 설정합니다. 또는 `uv sync`·`uv run`에 `--no-editable`을 붙입니다. 일반 설치 후에도 저장소 루트에서 실행하면 현재 작업 중인 `app` 코드를 사용합니다.

`alembic check`는 모델에 없는 PostGIS 내부 테이블(`spatial_ref_sys`·topology 테이블)을 삭제 대상으로 보고할 수 있습니다. 자동 생성된 삭제 변경을 적용하지 말고 앱이 관리하는 테이블만 비교합니다. 로컬 DB 구성 검증 결과는 [연동 기록](docs/designs/local-postgis-setup.md)에 있습니다.

아래 기존 설정 안내는 Docker 외 PostgreSQL에도 적용됩니다.

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
