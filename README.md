# SpotON-BE

## Render 무료 검증 배포

현재 [API 문서](https://spoton-be-free.onrender.com/docs)와 [DB 준비 상태](https://spoton-be-free.onrender.com/api/ready)를 사용할 수 있다. Free 웹1/DB1, SQL10초·풀1/overflow0/대기15초·워커1·연결 예산8을 사용한다. Docker 시작 시 migration/ETL은 실행하지 않고, 자동 배포는 꺼 둔다.

구성·환경변수·권한·운영 인덱스·복원 절차와2026-12-13 DB 만료는 [현재 Render 안내](docs/render-free-validation.md), FE URL·목업 해제·CORS·절전 후 대기는 [FE 연결 안내](docs/fe-render-validation-api-request.md)를 따른다. 로컬 .env와 코드 기본 설정은 별도로 유지한다.

서울의 카페·음식점 입지 분석을 위한 Spot:ON 백엔드입니다. 개발 기준과 다음 작업은 [통합 작업계획서](docs/be-work-plan.md)에서 관리합니다.

현재는 health·서울 주소 검색·점포 이력·주변 조회·조회 가능 월 범위·과거 점포 상태 분해·기본 상권 활동·Risk 참고지표·검증 후보 기반 AI 해석·상담/지원기관 공통 링크 API와 인허가/상권/생활인구 원천 적재, 공급자 분리 LLM client를 제공합니다. 개발 DB에는 점포 689,440건·상권 경계 1,650건·2025년 점포 통계 24,810행·추정매출 14,391행·공식 상권변화 유형 6,600행과 2026-11-07 생활인구 531,922행·공식 250m 격자 10,125개를 적재했습니다. migration `0011`가 현재 head입니다. 원천별 시점을 혼합하지 않으며 브랜드명 기반 프랜차이즈 추정·필터를 제공하며, 공식 지표 연결·조건부 매출/인구 수치와 FE 반영은 후속 작업입니다.

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

## 기본 상권 활동 분석

`GET /api/market/activity?lat={위도}&lng={경도}&category={cafe|restaurant}`는 nearby와 같은 공간·업종·면적·가맹·시점 조건으로 인허가 기반 활동을 집계합니다. 선택 `include=sales,living_pop`은 해당 지표의 준비 상태를 요청합니다. 중복·빈 값·미지원 인자는 422이며 DB/원천 준비 실패는 500입니다.

- 최근 12개월은 `(T의 전년 같은 월일, T]`이며 존재하지 않는 2월 29일만 28일로 제한합니다. 폐업 기록도 보존해 구간 내 개업·폐업을 각각 셉니다. 연도별 추이는 각 연도 1월 1일~T와 같은 월일까지의 YTD 비교이고 실제 사건이 없는 연도를 임의로 만들지 않습니다.
- 세부 업종별 점포 수와 평균은 T에 영업 중인 인허가 기록 기준입니다. 평균은 T까지 경과한 달력 완료 개월의 평균을 버린 정수이며, 점포 수 0이면 null입니다. 최신 데이터 기준 전체 영업기간·폐업 점포의 수명·생존율과 구분합니다.
- 명시 적용한 브랜드 목록은 `meta.franchise_classification.status=estimate`이며 기준년도 목록과 상호의 일치 추정입니다. 미적용 DB는pending입니다. 원본 가맹 필드는 보존하고 현재 이름/업종과 저장 근거가 같을 때만 별도 근거를 조회에 반영합니다. 미확인을 개인 매장으로 바꾸거나 필터0건을 실제 점포 부재로 단정하지 않습니다.
- 매출·생활인구 수치는 이번 릴리스에서 항상 null입니다. 요청한 항목만 `flags.missing`과 `meta.optional_data`에 pending 및 사유를 반환합니다. 적재된 원천이 있어도 집계 기간·경계/격자 적용 시점 검증 전에는 수치를 활성화하지 않습니다.
- `meta.as_of`는 실제 적용일 T, `data_updated_at`은 전역 인허가 갱신일 D, `collected_at`은 현재 null입니다. `denominator=null`, `cohort_size`는 폐업을 포함한 집계 대상 수이며 좌표 미확보 수는 서울 전체 동일 비공간 조건 기준입니다. no-store·읽기 전용 일관된 트랜잭션을 사용합니다.

[설계·검증](docs/designs/feat60-market-activity-api.md), [FE 변경 요청](docs/fe-market-activity-api-request.md)을 확인합니다. FE 연결과 조건부 수치 결합 완료를 뜻하지 않습니다.

## Risk 선행 상권 판정

내부 `judge_market(session, BoundaryQuery)`는 명시한 경계 UUID에서 상권 포함·밖·중첩을 구분합니다. 외곽선과 hole 경계를 포함하고 세부 상권 우선·관광특구 병기·동순위 후보 보존을 적용합니다. 상권 밖일 때만 반경과 교차하는 폴리곤 목록을 반환합니다. 호출자는 읽기 전용 일관된 세션을 제공해야 합니다.

현재 경계의 적용일은 미확인이므로 결과의 `applicability=unverified`를 유지합니다. 공식 통계 연결이나 현재/과거 상권 확정 근거가 아닙니다. 공개 Risk에서의 후보 제공은 아래 규칙을 따릅니다. [설계·Claude 검토·검증](docs/designs/feat62-market-judgement.md)을 확인합니다.

## Risk 참고지표 조회

`GET /api/risk?lat={위도}&lng={경도}&category={cafe|restaurant}`는 nearby와 같은 시점·필터로 동종업체 수·최근12개월 참고 폐업률·개업1주년/3주년 생존율과 동일 조건 서울 비교값을 반환합니다. include=market_change,day_night_ratio는 선택 항목 상태를 요청합니다.

- 폐업률 분모는 기간 중 영업한 인허가 기록이며 최소10건입니다. 생존율은 `(T-(n+1)년,T-n년]` 개업 코호트의 각 점포가 n주년에 영업 중이었는지 계산하며 최소5건입니다. 주년 후 T전에 폐업해도 고정 n년 생존에는 포함됩니다. 현재 잔존율·성공확률과 다릅니다. 이는 원본의 모호한 구간을 보완한 BE 계약안이며 FE/원본 합의는 대기입니다.
- 비율은 소수1자리 HALF_UP, 소표본/0분모는 value/numerator=null·실제 denominator를 보존하고 실제0%와 구분합니다. 서울도 같은 필터의 좌표 확보 인허가 기록 기준이며 공식 서울 수치가 아닙니다.
- 공식 폐업률·상권변화 유형·주야간 인구비는 미확인 자료 사유와 pending을 반환합니다. 공식 창업위험도는 안내 링크만 제공합니다. 가맹 미확인을 개인 매장으로 바꾸지 않습니다.
- 선택 서버 설정 `RISK_BOUNDARY_VERSION_ID`는 UUID이며 기본 미선택입니다. 지정해도 공간 후보만 표시하고 market.status=unverified를 유지합니다. 현재·과거 상권 확정/공식 통계 연결로 승격하지 않습니다. 실제 .env를 자동 수정하지 않습니다.
- D/T/수집일null·지표별 분모·서울 범위의 좌표 미확보 수·인허가/지위승계/과거 재구성 한계를 함께 확인합니다. 입력 오류422·DB/준비 실패500·no-store·읽기 전용 일관된 트랜잭션을 사용합니다.

[설계·검증](docs/designs/feat64-risk-reference-api.md), [FE 변경 요청](docs/fe-risk-reference-api-request.md)을 확인합니다. FE 구현·계산 문구 합의·CLAUDE.md 반영은 담당자 대기입니다.

## 상담·지원기관 링크

`GET /api/support-links`는 서울시 자영업지원센터·소상공인아카데미·서울시 소상공인 지원사업 안내·소상공인24의 공식 시작 주소를 반환합니다. DB나 인증키 없이 동작하며 요청 중 외부 사이트를 호출하지 않습니다. 선택 sigungu는 서울25개 구의 정확한 구명, category는 cafe/restaurant입니다. 생략은 허용하며 빈 값·중복·미지원 인자는422 INVALID_PARAM입니다.

- 구 생략(category만 지정 포함)은 기존 공통4개·순서와 `prioritization={status:not_applied,reason:general_links_only}`를 유지합니다. 구를 지정하면 공식 공고의 관할 센터 연락처1개를 맨 앞에 추가해5개를 반환하며 `prioritization={status:applied,reason:district_contact_first,category_applied:false}`입니다. 업종/자격/모집 추천은 하지 않습니다.
- 지역 연락처는 중기부 제2026-576호(2026-10-01) 첨부 PDF25쪽 별표2의8센터/25구 기준입니다. 예를 들어 마포구는 서울서대문센터입니다. 연결은 개별 지점/예약이 아닌 공식 공고 페이지이며 전화·관할·표 위치는 description에서 확인합니다. 카탈로그 버전은 구 생략/지정 모두support-links-v2입니다.
- 항목은 id/org_name/title/description/url/type/region/last_checked입니다. last_checked는 KST 수동 확인일(현재2026-11-12)이며 요청 날짜로 바꾸지 않습니다. data_updated_at도 목록 확인일 기준이며 개별 공고 공표일·마감일이 아닙니다.
- 서버 설정 목록은 분기1회 수동 점검하며 후속 공고의 관할 변경도 확인합니다. 구 지정의 district_contact_source는 공식 URL·공고일·확인일·표 위치이며 공고일과 카탈로그 확인일을 구분합니다. 요청 시 페이지를 호출하지 않으며 이후 접속/신청 성공을 보장하지 않습니다.
- 출처는 R17, is_demo=false이며 정상/422/서버500은 공통 외피·no-store입니다. 기존4호스트 외에는 검토한 중기부 공고 URL1개만 정확히 허용하며 사용자 입력을 URL에 붙이지 않습니다. [지역 안내 설계·Claude 검토·검증](docs/designs/feat88-district-support-contacts.md), [FE 연결 요청](docs/fe-support-links-api-request.md)을 확인합니다. FE 코드/CLAUDE.md 반영은 담당자 대기입니다.

## AI LLM client

`app/ai/`는 `POST /api/risk/interpret`가 사용하는 공급자 분리 LLM client입니다. `create_llm_client(settings)`가 `LLM_PROVIDER=google`이면 Gemini `generateContent` 어댑터를 만들고, 그 밖의 값은 호출 시 실패하는 client를 돌려줘 설정 오류가 지표 API 시작을 막지 않습니다.

- 키 `LLM_API_KEY`는 서버 전용이며 `x-goog-api-key` 헤더로만 보냅니다. 기본 모델은 `LLM_MODEL=gemini-3.5-flash-lite`입니다.
- `LLM_REQUEST_TIMEOUT`(요청 1회)과 `LLM_TIME_BUDGET`(재시도 대기 포함 전체) 안에서 429·500·503·504·네트워크 오류·timeout만 `LLM_MAX_RETRIES`회까지 지터를 준 지수 백오프로 재시도합니다.
- `LLM_REQUESTS_PER_MINUTE`·`LLM_REQUESTS_PER_DAY`는 프로세스 내 한도이며 비우면 제한하지 않습니다. 일일 한도는 태평양 시간 자정에 초기화합니다. 프로젝트 계정의 실제 한도를 확인해 설정합니다.
- 모든 실패는 기존 `AI_UNAVAILABLE`(503)로 매핑합니다. 프롬프트·생성 결과·키·공급자 오류 본문은 로그와 예외에 남기지 않습니다.
- 한도 카운터가 client 인스턴스에 있으므로 호출하는 쪽은 앱 수명 동안 하나를 재사용해야 합니다.

자동 검증은 mock transport를 사용합니다. #68에서는 실제 Gemini를 연결한 AI API 2건의 200 응답도 확인했습니다. 공급자 client 자체의 계약은 [작업 25 설계서](docs/designs/feat25-llm-client.md)에서 확인합니다.

### 프롬프트 버전 관리

AI 해석 프롬프트는 `app/ai/prompts/risk_interpret/`의 `system.md`(시스템 지침)와 `user.md`(`$context_json` 하나만 쓰는 입력 템플릿)로 관리합니다. `build_interpret_request(context)`가 서버 집계를 키 정렬 JSON으로 넣어 `LlmRequest`를 만듭니다.

- 프롬프트 파일을 바꾸면 `app/ai/prompts/version.py`의 `PROMPT_VERSION`을 올리고 `PROMPT_HISTORY` 끝에 새 지문을 추가해야 합니다. 테스트가 현재 파일의 SHA-256 지문과 대조해 누락을 막습니다. 새 지문은 실패한 테스트 메시지에 표시됩니다.
- 주소·좌표·`building_key`·`floor_unit`·상호(`name`)·`license_no` 등 `FORBIDDEN_CONTEXT_KEYS`에 있는 키가 집계에 있으면 조립을 거절합니다. 값 내용은 검사하지 않으므로 허용 필드 추출은 BE-28에서 해야 합니다.
- 시스템 지침은 공식/참고 구분·pending/no_data·금지 표현·참고용 안내를 유지하며, 현재 API에서는 문장 생성 대신 요청별 서버 후보 ID의 정렬/선택만 허용합니다. 원본/FE 계약 합의 완료와는 구분합니다.

상세 내용은 [작업 27 설계서](docs/designs/feat27-prompt-version.md)에서 확인합니다.

### AI 입력 집계 준비

내부 `prepare_risk_interpretation(session,query,settings)`가 서버 Risk를 재계산하고 업종·필터·반경·기준일·지표/분모/출처/상태만 추출합니다. 주소·좌표·점포 식별값·상권 후보·URL·원본 메타/UUID는 프롬프트에 넣지 않습니다. 사유 코드와 숫자/기간도 검증하며, 입력은 중첩 구조까지 불변으로 만들고 context hash와 내부 데이터/프롬프트 버전을 구분합니다.

현재 프롬프트 `risk-interpret-v4`는 안내 전용/미확인 상태·고정 주년 관측·서울 비교 한계를 유지하고, 요청별 허용 후보 ID만 선택하도록 제한합니다. 준비 함수 호출자는 기존 읽기 전용 세션을 제공해야 합니다. [집계 준비 설계·검증](docs/designs/feat66-ai-risk-context.md)을 확인합니다.

### AI 해석 API

`POST /api/risk/interpret`는 JSON `{ "query": { "lat": 37.5, "lng": 127.0, "category": "cafe", "radius": 500, "as_of": "2026-11" } }`처럼 원래 Risk 조회 조건만 받습니다. 이 예시는 합성 좌표입니다. Risk 전체 응답·클라이언트 수치·주소·building_key/floor_unit·중복 키·URL query는 422로 거절합니다. 선택 필드 `history: {"building_key": "...", "floor_unit": "1층 101호" | null}`(geocode 결과 그대로)를 보내면 서버가 같은 건물 이력을 재계산해 건수·같은 자리 영업 기간 범위만 AI 입력과 참고 계산 문장(`building_history`·`same_spot_history`)에 추가합니다(#98, prompt risk-interpret-v7). 건물키·층호수·상호는 AI 입력·응답·로그·캐시에 넣지 않으며, 형식 오류나 요청 좌표 300m 밖 건물은 422입니다. 최상위 building_key/floor_unit은 계속 422입니다. 서버는 같은 조건으로 상권 활동 집계(최근 구간 개폐업 수·세부 업종별 영업 수와 평균 경과 개월)를 재계산해 Risk와 교차 검증한 뒤 AI 입력과 `official_values` 참고 계산 문장에 추가합니다(#96, prompt risk-interpret-v6). 활동 문장의 `indicator_ids`는 `recent_open_close`·`avg_operating_months`이며 여러 항목에 반복될 수 있습니다.

- 서버가 Risk를 재계산하고 식별정보 없는 허용 집계와 문장 후보만 모델에 전송합니다. 모델은 모든 유리/불리 비교의 순서와 현장 질문 1~3개를 고릅니다. 숫자·비교 방향·최종 문장은 서버가 만들며, `method=server_sentences_model_ordering`으로 이 역할을 표시합니다. 자유로운 AI 서술이나 성공 가능성 판정이 아닙니다.
- `official_values`에는 참고 계산도 포함됩니다. 필수 사실·미확인/자료 한계는 전부 보존하고, 소표본·공식/조건부 지표 pending·수집일 null을 임의로 채우지 않습니다. `verification.checked_numbers`는 표시 문장의 숫자 출현 횟수이며 정확도 점수가 아닙니다.
- 프로세스별 기본 한도는 `INTERPRET_REQUESTS_PER_MINUTE=5`, `INTERPRET_REQUESTS_PER_DAY=50`, `INTERPRET_MAX_CONCURRENT=2`입니다. 공급자 client 한도와 별개이며 다중 worker 전역 한도·프로젝트 quota를 보장하지 않습니다. 캐시 적중도 앱 요청 한도를 소비하고 공급자 한도는 실제 호출에만 적용합니다.
- 대기·DB 준비·생성/검증 후 최대 1회 재생성·조립을 `LLM_TIME_BUDGET`(기본 20초)에 포함합니다. 읽기 전용 DB 세션은 모델 호출 전에 닫습니다. 취소 시 실행 중 동기 SQL은 문장 제한 이후 정리되므로 즉시 강제 중단이나 네트워크 전체 SLA를 보장하지 않습니다.
- 입력 오류 422, DB/서버 결함 500, 한도·공급자·시간 초과 503 `AI_UNAVAILABLE`, 두 번의 선택 검증 실패 503 `AI_VERIFY_FAILED`입니다. 실패를 기본 문장으로 대체하지 않습니다. 모든 응답은 no-store입니다.

[설계·Claude 검토·실제 검증](docs/designs/feat68-risk-interpret-api.md), [FE 변경 요청](docs/fe-risk-interpret-api-request.md)을 확인합니다. FE 구현·CLAUDE.md 반영은 담당자 대기이며 추가 문맥·전체 BE-32 통합 완료를 뜻하지 않습니다.

### Risk·AI 서버 캐시

앱마다 별도 메모리 LRU/TTL 캐시를 사용합니다. 환경 설정 기본값은 `CACHE_ENABLED=true`, `RISK_CACHE_TTL_SECONDS=300`, `AI_CACHE_TTL_SECONDS=300`, `CACHE_MAX_ENTRIES=256`, `CACHE_MAX_BYTES=4194304`입니다. TTL은 1~604800초(최대7일), 각 캐시의 항목 상한은 1~4096, payload bytes 상한은 1024~67108864입니다. 기본 Risk/AI payload 합계는 최대8MiB이며 Python 객체·키·인덱스 등의 비용은 별도입니다. worker마다 메모리와 캐시가 독립적이고 재시작/종료 시 폐기합니다.

- 원문 좌표·조회조건을 key에 저장하지 않고 앱 수명의 난수 salt로 HMAC합니다. 좌표6자리와 정확한 float guard를 함께 사용해 반경 경계가 다른 요청을 합치지 않습니다. Risk 값에는 query echo가 없고 현재 요청으로 복원합니다. 업종집합/필터·요청 월·경계/계산 규칙도 구분합니다.
- 같은 primary의 READ ONLY REPEATABLE READ 가시성 지문을 확인합니다. 일반 MVCC INSERT/UPDATE/DELETE는 배치ID·updated_at이 같아도 새 namespace가 되며 옛 트랜잭션은 별도로 유지됩니다. 관련 없는 쓰기/rollback에도 보수적으로 miss가 발생합니다. 적중에도 DB 접속이 필요하며 DB/원천 오류를 과거 성공으로 대체하지 않습니다.
- AI는 현재 허용 후보와 재대조한 선택 ID·모델명만 저장합니다. 데이터/컨텍스트·프롬프트·공급자/모델·후보/Schema·검증 규칙이 달라지면 재사용하지 않습니다. 같은 key의 동시 생성은 합치며 대기 중에는 실행 슬롯을 점유하지 않습니다. 실패/미설정 키는 저장하거나 이전 성공으로 숨기지 않습니다.
- `generated_at`은 **현재 응답의 서버 문장 조립 시각**입니다. 새 공급자 호출 시각이 아니며, `verification.regenerated`는 **현재 요청**의 검증 재생성 여부(적중 시 false)입니다. 선택 결과는 TTL 동안 재사용될 수 있고 과거 사용자의 생성시각/재생성 이력은 저장하지 않습니다. HTTP 응답은 계속 `no-store`이고 적중 여부를 응답/로그로 공개하지 않습니다. 공유 캐시의 응답시간·반복 선택 차이로 최근 동일 조건 조회를 추론할 수 있는 한계가 있어 완전 익명성을 보장하지 않습니다.
- 동시 TRUNCATE·테이블 rewrite·DB 복구는 지원 갱신 범위 밖입니다. 이런 유지보수는 **요청 drain → 캐시 종료 → 변경 → 앱 재시작** 순서로 수행합니다. 일반 MVCC 갱신에 따른 옛 항목은 더 이상 조회되지 않습니다. 만료 후 다음 요청이 없어도 1초 간격 sweep으로 참조를 정리하고, 종료 시 정리 task를 취소·회수하고 늦은 저장을 막습니다. TTL 경계부터 재사용하지 않지만 OS 정지/이벤트 루프 지연·시계 오류 중의 정확한 물리 삭제 시한이나 메모리 덤프/스왑의 secure erase는 보장하지 않습니다. 분산 캐시·오프라인 응답·운영 hit율/SLA도 미검증입니다.

[설계·Claude 검토·검증](docs/designs/feat74-risk-ai-cache.md)에 선택 근거와 지원 범위를 기록합니다.

### AI 결과 검증

`app/ai/verifier.py`의 `verify_output()`은 LLM 응답이 JSON 객체인지 확인한 뒤 다음을 검사합니다. 결과에는 실패 종류만 담고 응답 원문은 담지 않습니다.

- 입력 집계(값·문자열·키)에 없는 숫자. 쉼표·`%`·소수 반올림은 허용하고 정수 반올림과 비율↔백분율 환산은 허용하지 않습니다.
- 금지 표현(성공률·성공 확률, 추천/비추천, 위험점수·위험등급, LQ, 단정적 예측). 서울시 `창업위험도` 안내 이름은 허용합니다.
- pending·no_data 지표에 값을 붙인 경우, 입력에 없는 출처(지표 객체의 `id`·`value`·`status`, `source`/`sources` 관례를 따른 응답에 적용)
- 전화번호·이메일·도로명/지번 번호·층호·좌표·building_key 패턴과 식별정보 키
- 분량 상한(기본 2000자)과 같은 문장 반복

`app/ai/verified.py`의 `generate_verified()`는 검증에 실패하면 같은 요청으로 1회 다시 생성하고, 또 실패하면 `AiVerifyFailedError`(→ `AI_VERIFY_FAILED` 503)를 냅니다. 공급자 오류 `LlmError`는 그대로 전달되어 `AI_UNAVAILABLE`과 섞이지 않습니다. 호출자의 Pydantic 모델과 선택적 의미 검증/남은 예산 검사를 지원하며, AI API는 요청별 enum·전체 비교 후보 포함·중복 검사를 추가합니다. 상세 내용은 [작업 29 설계서](docs/designs/feat29-ai-verifier.md)와 #68 설계를 확인합니다.

## 공정위 브랜드 원천 수집·읽기 전용 대조 (BE-21 1단계)

[공정위 브랜드 목록 API](https://www.data.go.kr/data/15125467/openapi.do)의 기준년도별 전체 목록을 수집하고 기존 점포와 정확한 정규화 상호를 대조합니다. 이 단계는 **후보 조사**이며 가맹계약·브랜드 소속·과거 소속 판정이 아닙니다. 실제 `is_franchise/brand_id`와 공개 API·AI의 pending 상태를 유지합니다.

```powershell
uv run --locked --extra dev python -m etl.brands --year 2025 --output "<저장소 밖 새 snapshot.json>"
uv run --locked --extra dev python -m etl.brands --snapshot "<기존 snapshot.json>" --compare-local
```

- 수집은 로컬 `DATA_GO_KR_SERVICE_KEY`가 필요합니다. 명시한 연도를 순차1000행씩 수집하며 자동 연도 대체·재시도는 없습니다. 결과코드·전체/페이지 건수·브랜드/본부 관리번호 복합키 중복·연도를 검사하고 마지막에 첫 페이지를 다시 대조합니다. 중간 페이지의 동시 변경까지 검출하거나 공급자의 단일 시점 일관성을 증명하는 것은 아닙니다.
- 원문 body/base64·페이지SHA256·정규화content hash·규칙·실제 전체 수집 완료 UTC시각을 BE/FE 저장소 밖 파일에 보존합니다. 관리번호는 영문 접두사·구분자·앞0를 보존하는 문자열입니다. snapshot의 완료시각은 기존 인허가 collected_at이나 원천 갱신일과 별개입니다. 기존 파일을 덮지 않으며 실패/Ctrl+C 때 이번 생성 파일만 정리합니다. 강제 종료나 정리 실패 시 불완전 파일이 남을 수 있고 replay에서 거절합니다.
- snapshot에는 공식 공개 대표자·사업자정보가 포함될 수 있습니다. 로컬에만 보관하고 커밋·로그·Claude/LLM 입력으로 보내지 않습니다. 정규화/후보 대조는 브랜드명·관리번호·기준년도·업종만 사용하며 법인명·대표자·사업자번호는 사용하지 않습니다. stdout/stderr는 고정 건수·상태·해시만 출력합니다.
- replay는 원문·페이지·hash·규칙·완료시각을 다시 검증하며 키/HTTP가 필요 없습니다. 최대100,000행·페이지5MiB·raw 합계140MiB·base64 포함 snapshot200MiB입니다. hash 일치는 공급기관 서명이나 원천 의미 검증이 아닙니다.
- `--compare-local`만 기존 로컬대상/head0011 검사를 통과한 DB에 READ ONLY REPEATABLE READ·SQL60초/잠금5초로 연결합니다. 지원5업종·삭제없음·검토대기아님 점포를 스트리밍 대조하며 좌표/날짜/영업 상태로 한정하지 않습니다. 현재 지도/과거 조회의 실제 점포 수와 다른 모집단입니다. 점포 상호는 외부로 전송하지 않습니다.
- NFKC/casefold/공백만 정규화하고 지점명·구두점 제거/부분일치/유사도 판정은 하지 않습니다. 전체 업종 목록 기준 유일한 외식 이름이 정확히 일치해도 `exact_name_candidate`일 뿐입니다. 기존판정보존→상호결측→약한이름→반복브랜드번호→동명모호→비외식→정확후보→미일치 순의 배타건수이며 합계는 total과 같습니다. 3자 미만/숫자만인 이름은 약한 이름입니다. 미일치를 비프랜차이즈 수로 사용하지 않습니다.
- 원천은 `(기준년,브랜드관리번호,가맹본부관리번호)` 행으로 보존합니다. 같은 브랜드번호·다른 본부의 모든 행을 유지하며 그 번호와 관련된 이름은 유일해도 `repeated_brand_id`로 격리합니다. 원천 반복의 이유나 브랜드 소속은 추론하지 않습니다. v2 content hash/첫페이지 재확인은 복합키 순서이며 이전 규칙 snapshot은 거절합니다. `rows`는 원천 행 수, `unique_brand_ids/repeated_brand_ids/repeated_rows`는 번호·행 건수입니다. `ambiguous_names`는 정규화명이 복수 원천 행에 있는 그룹 수로 반복번호 행도 포함할 수 있습니다. 이 요약들을 합산해 실제 브랜드/점포 수로 쓰지 않습니다.
- 성공0·고정 JSON오류1·인자오류2·Ctrl+C130입니다. `request_count`는 성공한 실행의 HTTP시도 수이며 replay는0입니다. 원천 파일 저장 뒤 DB 대조가 실패하면 exit1·`snapshot_saved=true`·stage=prepare를 출력하고 파일을 보존하므로 `--snapshot`으로 재실행합니다. `snapshot_saved`는 이번 실행이 완료 파일을 저장했는지 뜻합니다.

위 단계는 후보 조사 기능입니다. 실제 추정 조회는 아래 명시 적용 실행기로 수행하며 같은 보수적 규칙을 사용합니다. [원천 기반 설계](docs/designs/feat57-brand-catalog-foundation.md)를 따릅니다.

## 브랜드명 기반 프랜차이즈 추정 적용 (BE-21)

```powershell
# 기본은 READ ONLY 계획입니다. snapshot은 저장소 밖 검증된 파일입니다.
uv run --locked --extra dev python -m etl.brands.apply --snapshot "<snapshot.json>"
uv run --locked --extra dev python -m etl.brands.apply --snapshot "<snapshot.json>" --write
```

- migration0011의5개 테이블에 catalog/브랜드 원천/매핑run/정확 일치 근거/활성 포인터를 보존합니다. **stores 원본·is_franchise/brand_id·updated_at·배치·스키마는 바꾸지 않습니다.** 외부 분류가 우선이며 현재 source/license_no/name/category/sub_category가 활성run의 근거와 같을 때만 자동true로 조회합니다. 상호 변경은 조회에서 미확인이고 같은 원문이 복귀하면 근거가 다시 적용될 수 있습니다.
- 동일snapshot/점포입력/규칙은UUID·loaded_at·근거를재사용하고포인터가같으면무변경입니다. 다른명시catalog의run으로전환할수있고이전run은보존합니다. writer는READ COMMITTED·apply간advisory lock/unique·SQL60초/잠금5초로새테이블만원자적으로씁니다. 원천변경과경합해도읽기시점대조로오래된양성은노출하지않습니다. 데이터가있으면downgrade를거절합니다.
- history/nearby/snapshot행에franchise_basis와franchise_reference_year, snapshot에는franchise도추가합니다. 자동값은catalog_exact_name/현재2025, 기존외부값은external_classification/년도null, 미확인은둘다null입니다. 실제가맹계약·직영구분·과거소속은확인하지않았으며false/independent를자동생성하지않습니다.
- **프랜차이즈만 조회하려면 franchise=franchise와include_unknown_franchise=false를함께전달**합니다. unknown기본true는미확인도포함합니다. independent는외부false만선택하며현재0건을실제독립점포부재로해석하지않습니다.
- 5조회API의meta는미적용pending 또는estimate/partial·기준년도·R7·계약/업종대응미검증을명시합니다. data_version.brand_mapping은마지막적용의catalog/run/입력hash/규칙이며화면이나AI입력에UUID/hash를표시하지않습니다. 기존인허가as_of/collected_at=null은유지합니다. 가맹필터의과거폐업률/생존율은목록이름으로선택한인허가참고비율이며역사적가맹코호트가아닙니다.
- AI입력은상태/년도/고정한계만추가하고이름·번호·UUID/hash는전송하지않습니다. 내부버전hash·DB snapshot cache·prompt risk-interpret-v5로이전판정을분리하고실제계약/과거소속으로문장을바꾸지않습니다.

현재2025원천11,167행·정확이름근거6,839건을명시적용했습니다. 실제DB의원래14테이블전체행/공간hash·원본snapshot은동일하고모델차이0입니다. localhost8000에서도추정응답을확인했습니다. 실제LLM추가송신/최신원천수집·자동일정·공개배포는하지않습니다. [판정 적용 설계](docs/designs/feat57-franchise-classification.md)와 [FE 변경 요청서](docs/fe-franchise-classification-api-request.md)를따르며FE/CLAUDE.md 반영은담당자대기입니다.

## 개인정보 없는 운영 로그

API·ETL·LLM의 추가 운영 이벤트는 한 줄 JSON으로 **stderr**에 기록합니다. 기존 ETL stdout 결과와 API 본문·헤더는 유지합니다. 원문을 마스킹해 저장하는 방식 대신 고정 필드·허용 건수만 선택하며 주소·좌표·건물/층호·헤더/IP·원자료·프롬프트/출력·키를 기록하지 않습니다.

| event | 의미 |
|---|---|
| api_request | UTC 시각·고정 경로·실제 전송 상태·처리시간·서버 UUID·ASGI 응답 완료 여부 |
| etl_run / etl_stage | 7개 실행기의 독립 run_id·단계 시작/완료/실패·시간, 완료 결과의 허용 건수/품질 집계·실제 batch/version UUID |
| etl_quality | 생활인구 입력 읽기 후 원천일 전체의 비공개·빈 셀·실제0·미좌표 행 수와 복수행정동 그룹/행 수. 인구값·코드 없음 |
| llm_http_attempt | 애플리케이션의 client.post 시도1건과 HTTP200 관측 여부. 파싱/최종 AI 검증 성공률과 다름 |

- 모르는 경로는 `unmatched`이며 원문 URL/query를 복사하지 않습니다. 헤더 관측 전 실패/취소는 status_code=null, 전송 중 중단은 response_complete=false입니다. 완료는 ASGI 전송 기준이며 사용자의 다운로드 완료 보장이 아닙니다. request_id는 입력 헤더를 무시하고 새로 만들며 응답 헤더에 추가하지 않습니다.
- ETL은 실제 commit context 종료 후 persist 완료를 기록하고 원래 오류·취소를 전파합니다. run_id와 DB batch_id/version_id를 구분하며 없는 건수를0으로 채우지 않습니다. quality_flags는 겹칠 수 있으므로 합산해 최종 제외 수로 표시하지 않습니다. 인허가 CLI의 잘못된 인자는 입력을 echo하지 않는 고정 메시지·exit2입니다.
- brands의 파일 저장 완료는 별도 `save_snapshot` 단계입니다. DB commit을 뜻하는 persist와 구분하며 대조는 prepare의 읽기 전용 동작입니다. 원천 저장 후 대조 실패 시 save_snapshot completed 뒤 import failed가 올 수 있습니다.
- 생활인구 `etl_quality`의 completed는 입력 요약 성공이며 적재 완료·원천 완전성·공간 검증 성공이 아닙니다. DB 준비 전에 기록하므로 이후 import failed가 올 수 있습니다. 6개 카운터 중 하나라도 유효하지 않거나 계산에 실패하면 counts 없이 failed/quality_summary_unavailable을 기록합니다. 로그 실패는 적재 성공 조건이 아니며 원래 실행 결과를 바꾸지 않습니다.
- 쓰기/직렬화/ID 생성 실패는 주 작업을 바꾸지 않으며 로그 오류를 다시 출력하지 않습니다. 한 줄은 최대4096 UTF-8 bytes이고 프로세스 내 thread 쓰기를 묶습니다. 느린 stderr의 지연이나 여러 프로세스 간 원자성은 보장하지 않습니다. 기존 서버 시작/오류 메시지는 같은 stderr에 있을 수 있으므로 수집기는 event가 있는 JSON을 구분합니다.
- 기본 앱에서 uvicorn.access를 비활성화하고 기존 `--no-access-log` 실행 안내도 유지합니다. 별도 로그 재설정·reload/gunicorn·프록시/제3자 DEBUG 전체의 개인정보 처리를 대신하지 않습니다.
- **원본의30일 보관·삭제 요구는 아직 미충족**입니다. 앱에 파일/DB 저장을 추가하지 않았으며 실제 배포 로그 수집기의 보관 설정·삭제 검증이 후속입니다. [설계·Claude 검토·검증](docs/designs/feat72-private-operation-logs.md)을 확인합니다. FE 응답 계약은 바뀌지 않습니다.

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

2026-11-12 [전체 시스템 점검·수정 기록](docs/designs/feat58-system-audit-cleanup.md): 일반893개·격리 PostGIS92개 통과. 실제 DB head0009·모델차이0·조회 API5개와 카카오 주소 검색/이력 연결을 확인했습니다. LLM 전체/요청별 시간 예산·비정상 Retry-After·과도한 지번 숫자·CSV 수집시각 이후 분기 검증을 보완했습니다. FE lint/build/format은 통과했지만 nullable/복합 식별자 등 실제 화면 연동은 기존 FE 요청 보고서 반영 대기입니다. 유료 LLM 실제 호출·미구현 분석 API·브라우저 전체 시연을 검증한 것은 아닙니다.

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
  `0010`·PostGIS·유일 제약을 다시 검사하고 원천별 한 트랜잭션으로 점포와 배치 출처를 적재합니다.
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

## 상권별 추정매출 원천 적재 (BE-18)

출처는 서울특별시·서울신용보증재단 [상권분석서비스(추정매출-상권), OA-15572](https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do), 공공누리 1유형 출처표시입니다. 금액 단위는 원입니다. 원천 `당월_매출_금액`을 분기 합계나 월평균으로 확정하지 않고 그대로 저장합니다. 월·분기 환산, 반경 매출·점포당 매출 계산과 공개 매출 API 활성화는 하지 않습니다.

```powershell
uv run --locked --extra dev python -m etl.market_sales `
  --zip "<저장소 밖 공식 연간 ZIP 경로>" `
  --expected-sha256 "<ZIP SHA256>" `
  --source-year 2025 --source-file-date 2026-05-18 `
  --code-check-boundary-version "<대조 경계 버전 UUID>" `
  --code-check-store-version "<대조 점포 통계 버전 UUID>"
# 기본 REPEATABLE READ READ ONLY dry-run. 확인 후 같은 명령에 --write 추가.
```

- 검증한 2025년 ZIP은 14,035,292 bytes, SHA256 `c907f3d386d62b89f45781e6e6172328ee91b1b8dd2c621e4171e437bee1c6b2`, CP949 CSV 39,698,674 bytes입니다. 첨부 수정일은 2026-05-18이며 통계 분기·포털 갱신일·loaded_at과 구분합니다. 현재 최신 API 분기를 보장하지 않습니다.
- 55개 원천 헤더와 전체 85,732행의 48개 수치 필드를 검증하고 지원 5종 **14,391행**(분기별 3,617/3,596/3,597/3,581)을 적재 대상으로 선택합니다. 미지원 71,341행은 제외합니다. 원천 시간대 건수 헤더의 특이 표기도 허용 목록 그대로 검사합니다.
- `est_sales`는 원천 금액, `source_sales_count`는 원천 건수이며 BIGINT nullable입니다. 32bit 초과·최대 BIGINT를 float 변환 없이 다룹니다. 빈 셀은 null, 실제 0은 0, 없는 조합은 행 없음으로 보존합니다. 55개 허용 필드의 원문 hash를 남기되 나머지 세부 수치를 재합산하지 않습니다.
- 두 대조 버전을 명시하며 점포 통계와 같은 연도·같은 대조 경계인지 검사합니다. 두 기준의 실제 DB hash·행 수를 확인하고 코드/유형/명칭 및 지원 조합 차이를 기록합니다. 차이는 건수로 보고하고 없는 매출 행을 0으로 생성하지 않습니다.
- `market_sale_versions`·`market_sales`는 원본/규칙/두 기준 버전별 불변 버전입니다. dry-run은 같은 키의 기존 버전 재사용 여부도 검사하며, --write는 한 연도의 버전·행을 한 트랜잭션으로 저장합니다. advisory lock·저장 내용 재조회 hash 검사·실패 전체 rollback을 적용하고 replay는 UUID/loaded_at/hash를 유지합니다. 적재된 매출이 있으면 downgrade는 실패합니다.
- `currency=KRW`, `amount_basis=source_reported`, **`amount_period_status=unverified`**, **`boundary_compatibility=unverified`**를 유지합니다. 집계 기간·경계 적용일·통계/인허가 모집단 동일성은 추가 확인 대상입니다. BE-17 공통화 전후 hash·실행 결과 회귀와 실제 원본 replay를 검증하며 FE·API·Docker·환경설정은 변경하지 않습니다.

상세 설계·검증·미확인 사항은 [이슈 51 기록](docs/designs/feat51-market-sales-import.md)을 확인합니다.

## 250m 생활인구 원천 적재 (BE-19)

서울특별시·KT 추계 [생활인구 공식 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do), [내국인 OA-22784](https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do)·[장기외국인 OA-22785](https://data.seoul.go.kr/dataList/OA-22785/S/1/datasetView.do)·[단기외국인 OA-22786](https://data.seoul.go.kr/dataList/OA-22786/S/1/datasetView.do)를 사용합니다. 일별 원천은 공공누리 1유형 출처표시입니다. 실제 방문객 수·하루 고유 인구가 아닌 시각별 추계이며 원천별 행정동 차원을 보존합니다.

세 일별 ZIP과 공식 격자 SHP ZIP은 저장소 밖에 두고, 아래 구조의 로컬 manifest를 만듭니다. hash는 파일별 실제 SHA256, file_date는 확인한 원천 첨부 수정일입니다. 실제 `.env`나 인증키는 넣지 않습니다.

```json
{
  "observation_date": "2026-11-07",
  "grid": {"path": "<공식 격자 ZIP 경로>", "sha256": "<SHA256>"},
  "sources": {
    "local": {"path": "<내국인 ZIP 경로>", "sha256": "<SHA256>", "file_date": "2026-11-11"},
    "long": {"path": "<장기외국인 ZIP 경로>", "sha256": "<SHA256>", "file_date": "2026-11-11"},
    "short": {"path": "<단기외국인 ZIP 경로>", "sha256": "<SHA256>", "file_date": "2026-11-11"}
  }
}
```

```powershell
uv run --locked --extra dev python -m etl.living_pop --manifest "<로컬 manifest JSON 경로>"
# 기본은 REPEATABLE READ READ ONLY dry-run입니다. 확인 후 같은 명령에 --write 추가.
```

- manifest의 상대 경로는 manifest 파일 위치 기준입니다. 날짜와 세 원천을 모두 명시하며 자동 백필·기간 전체 다운로드는 하지 않습니다. 현재 검증 범위는 **2026-11-07 하루**입니다.
- 격자는 EPSG:5179의 원본 250m 사각형을 검증해 MULTIPOLYGON4326·GIST로 저장합니다. 원본 hash와 변환 저장 hash를 구분하며 내부 파일 시각을 적용일로 바꾸지 않습니다. `grid_as_of=null`, `spatial_compatibility=unverified`입니다.
- 내국인 253,400·장기 137,137·단기 141,385, 합계 **531,922행**입니다. 관측은 `(version_id,source,hour,admin_code,grid_id)`로 구분하며 같은 격자·시각의 복수 행정동 행을 제거하거나 합산하지 않습니다. 전체 geometry는 셀 도형이며 행정동별 부분 도형/면적 배분을 만들지 않습니다.
- `population`은 Numeric(20,5) 원천 총계, `value_status`는 observed/suppressed/missing입니다. `*`는 suppressed/null, 빈 값은 missing/null, 실제0은 observed/0이며 행 없음과 구분합니다. 후행 소수점 정수 표기를 포함한 명시적 ASCII 십진수만 받으며 원문 표기는 hash와 집계로 추적합니다. 세부 성별/연령/국적 숫자는 검사·hash만 하고 별도 적재하거나 총계를 복원하지 않습니다.
- 사용자가 확정한 기준대로 공식 격자에 없는 내국인 1개 격자의 **24개 비식별 행**을 원문 코드·unlocated/null 참조로 보존합니다. 가짜 좌표·격자 행을 생성하지 않습니다. located 행은 복합 FK로 공식 격자와 연결하고 공간 inner join은 unlocated를 제외합니다. 전역 source/date 범위 미확인 수를 반경 내 missing_grid_count로 표시하지 않습니다.
- 원본/규칙별 불변 버전과 실제 저장 hash를 검증하며 --write는 격자 및 세 원천 전체를 한 트랜잭션으로 처리합니다. replay는 기존 UUID·loaded_at·내용을 유지하며, 실패 시 이번 신규 버전/행을 모두 rollback합니다. 자료가 있으면 downgrade는 실패합니다.
- 사용자 운영 규칙상 복수 행정동 행은 공식 답변 전 임의 합산하지 않고 원천 파일·행정동별 불변 관측·원문 행 hash로 보존합니다. 행이 없는 조합은 no_data이며 0으로 보정하거나 임의 행을 만들지 않습니다. 이 정책은 공급기관의 합산 가능성 확인을 대신하지 않습니다. 현재 SHP와2026-11-07 관측의 공식 버전 대응 자료 전에는 공간 집계 API와 주야간 인구비를 계속 보류합니다. 원천 수집·정제·적재는 가능합니다.
- 별도 `etl_quality` 이벤트의 `suppressed_rows`는 비공개, `missing_value_rows`는 **실제 행의 빈 합계 셀(행 부재 미포함)**, `observed_zero_rows`는 실제 관측0, `unlocated_rows`는 좌표 미확인 행 수입니다. `multi_admin_groups`는 같은 원천·시각·원천 격자의 서로 다른 행정동2개 이상 그룹 수, `multi_admin_rows`는 그 그룹의 전체 행 수입니다. 미좌표 그룹도 포함할 수 있습니다. 플래그는 겹치므로 합산 제외 수·인구·완전성/제공률로 해석하지 않습니다. 없는 조합의 공식 기준이 없어 행 부재 수는 만들지 않습니다. scope=source_day_all_sources·spatial_compatibility=unverified·aggregation_status=pending을 유지합니다. [설계·Claude 검토·검증](docs/designs/feat90-population-quality-logs.md)을 따릅니다.

실행·검증·원천 특이사항과 선택 근거는 [이슈 53 설계](docs/designs/feat53-living-population-import.md)를 확인합니다. 생활인구/반경 API·주야간 비율·FE 연동과 다일 누적·파티셔닝은 후속 범위입니다.

## 공식 상권변화 유형 적재 (BE-20)

서울신용보증재단 제공·서울특별시 저작권의 [공식 OA-15576](https://data.seoul.go.kr/dataList/OA-15576/S/1/datasetView.do) 자료를 사용합니다. 공공누리1유형 출처표시 대상입니다. 포털의 **내려받기(CSV)**에서 전체 파일을 받아 저장소 밖에 보관합니다. 미리보기 1,000행을 전체로 사용하거나 ZIP으로 다시 포장하지 않습니다.

```powershell
# 기본: 파일 전체 검증 + 로컬 DB 읽기 전용 dry-run
uv run --locked --extra dev python -m etl.market_changes `
  --csv "<전체 CSV 경로>" --expected-sha256 "<실제 SHA256>" `
  --source-year 2025 --retrieved-at "<다운로드 완료 ISO 시각, timezone 포함>" `
  --code-check-boundary-version "<검증된 market_area_versions UUID>"
# 위 명령에 --write를 추가하면 선택 연도를 한 트랜잭션으로 저장합니다.
```

- 실제 전체36,300행(2021년1분기~2026년2분기)을 검사하고 **2025년6,600행**, 분기별1,650행을 적재했습니다. 나머지29,700행은 선택 연도 밖입니다. 업종 제외 수가 아니며 출력의 `excluded_scope=outside_selected_year`로 구분합니다. 자동 최신 선택·전체 기간 백필은 하지 않습니다.
- `market_change_versions`/`market_changes`에 LL=다이나믹·LH=상권확장·HL=상권축소·HH=정체와 원천 평균 영업 개월4개를 보존합니다. 평균 빈 셀은null·실제0은0·행 없음은누락이며 0으로 채우지 않습니다. 평균으로 유형을 재계산하거나 자체 점수/좋음·나쁨 판정을 만들지 않습니다.
- 원천에는 업종 필드가 없습니다. 카페/음식점으로 복제하거나 업종 필터를 적용하지 않습니다. 평균의 모집단·산정 기간을 자체 점포 이력과 같다고 가정하지 않습니다.
- `retrieved_at`은 다운로드 완료시각을 재실행 때도 그대로 전달합니다. 파일 자체 수정일은 미확인 `source_file_date=null`이며 포털 갱신일로 채우지 않습니다. 같은 bytes/연도/규칙/경계는 같은 UUID를 재사용하고, 다른 provenance나 저장 내용 훼손은 실패합니다. 다른 bytes는 같은 내용이어도 별도 버전이며 `same_content_versions_before`는 참고 건수입니다.
- 경계 코드·유형 차이는0개, 명칭 차이는 분기별3개입니다. 실제 적용시점 일치는 미확인이므로 `boundary_compatibility=unverified`를 유지합니다. 실제 조회 API·FE 변경은 없습니다.

원천·Claude 검토·실제 검증과 한계는 [이슈55 설계](docs/designs/feat55-market-change-import.md)를 따릅니다.

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

주소검색 결과부터 이력·월범위·주변/과거·활동/Risk·AI·지원링크까지 연결하는 검사는 `tests/integration/test_analysis_flow.py`입니다. 합성 snapshot을 실제 ETL 실행기로 임시 DB에 적재하고, 외부 지오코딩/모델만 모의 처리합니다. CI는 고유 시나리오10종·총22개 연결 검사의 실행을 확인하며 필수 시나리오가 빠지면 실패합니다. 실제 카카오+개발 DB 읽기 결과·API별 모집단 차이·FE 대기는 [BE API 검증 보고서](docs/be-api-verification.md)를 확인합니다. FE 화면이나 전체 프로젝트 완료를 뜻하지 않습니다.

현재 기능별 실원천 dry-run·실제 모델·FE 브라우저 결과는 [전체 시스템 감사](docs/be-system-audit.md)를 확인합니다. FE결함5종·일반음식점 원천 API지연이 남아 전체 정상 판정은 보류했습니다. 지도 기본 연결과 아래 출처 조회 인덱스의 적용 범위는 각각의 최신 검증 결과를 확인합니다. FE 변경은 [수정 요청 보고서](docs/fe-system-audit-request.md)로 전달하며 BE에서 FE를 직접 수정하지 않습니다.

## 출처 조회 인덱스와 대량 인허가 적재 후 관리

현재 migration head는 `0010`입니다. `ix_stores_provenance`는 `(batch_id, source, category, sub_category)`의 partial B-tree이며 삭제·검토대기 행을 제외합니다. 기존 출처 검증 SQL과 API 계약을 유지하면서 전역 출처 조회의 heap 읽기를 줄입니다. ETL의 DB 준비 검사는 `0010`을 요구합니다.

일반 CREATE INDEX는 생성 중 쓰기를 대기시킬 수 있습니다. downgrade의 DROP INDEX는 읽기도 대기시킬 수 있으므로 migration·롤백은 트래픽을 정리한 시점에 실행합니다. 두 방향 모두 트랜잭션의 `lock_timeout=5s`를 사용하며, 잠금 실패 시 전체 트랜잭션 롤백을 확인한 뒤 재실행합니다. 이 값은 인덱스 생성 시간이나 API SQL3초 제한을 늘리는 설정이 아닙니다.

**대량 인허가 재적재 시에는 분석 조회를 중지하고**, ETL 커밋 후 테이블 소유자 또는 적절한 유지관리 권한을 가진 계정의 **별도 autocommit 세션**에서 다음을 실행한 뒤 API 정상 응답을 확인하고 조회를 재개합니다.

```sql
VACUUM (ANALYZE) public.stores;
```

VACUUM은 ETL·migration의 트랜잭션 블록 안에서 실행할 수 없습니다. ETL 커밋과 원자적이지 않으며, 실패해도 이미 적재한 데이터가 롤백되지는 않습니다. 완료 전에는 조회500이 발생할 수 있어 조회 중지를 유지하고 원인을 확인합니다. migration과 동시에 실행하지 않습니다. 자동 VACUUM이나 자동 조회 차단 기능을 추가한 것은 아니며 운영자가 수행하는 절차입니다.

합성 전체 재적재 직후에는 이 인덱스에서도 배치조회가3초를 초과했습니다. 현재 정적 데이터의 읽기 개선과 이 제한을 구분하며, 비용·회귀·실제 검증은 [설계 및 Claude 검토](docs/designs/feat82-store-provenance-index.md)를 확인합니다.

로컬 개발 DB는 다음 전용 명령으로 대상·소유권 점검과 유지보수를 실행할 수 있습니다. **읽기·대량 writer·migration 중지와 ETL 커밋을 먼저 확인합니다.** 실행기는 트래픽을 자동 중지하거나 ETL을 실행하지 않습니다.

```powershell
# 기본: 읽기 전용 대상·head·소유권 확인만
uv run --locked --extra dev python -m etl.localdata.maintenance

# 명시적 실행: 별도 autocommit VACUUM → 새 읽기 전용 출처 검증
uv run --locked --extra dev python -m etl.localdata.maintenance --execute
```

loopback의 `spoton_dev`·비슈퍼유저 `spoton_app`·head0011과 정확한 `public.stores` 소유자만 허용합니다. 실행 SQL은 `VACUUM (ANALYZE, TRUNCATE FALSE) public.stores`로 고정하며 FULL·테이블명/URL 옵션은 제공하지 않습니다. 잠금 대기5초·명령60초를 적용하고, 후속 출처 검증은 기존 SQL별 제한(기본3초)을 사용합니다.

결과는 stdout JSON 한 건입니다. 정상0·실패1·Ctrl+C130이며 `--help`는 도움말/0입니다. 오류는 `localdata_maintenance:` 뒤 고정 코드만 반환합니다. `vacuum_completed=true`는 명령이 정상 반환했다는 뜻이고 `provenance_checked=true`는 그 뒤 출처 검사가 통과했다는 뜻입니다. 기본 dry-run은 두 값이 false입니다. VACUUM 후 검증이 실패하면 첫 값은 true인 채 실패로 종료합니다. 실패/중단 시 일부 물리 정리가 반영됐을 수 있으며 앞선 ETL 커밋을 되돌리지 않습니다.

오래된 snapshot이 있으면 VACUUM이 반환해도 회수가 제한될 수 있습니다. 성공 결과가 모든 API·부하/SLA 검증을 대신하지 않으므로 **실제 API 정상 응답까지 확인한 뒤 조회를 재개합니다.** DB 설정·사용법과 검증 범위는 [유지보수 설계·Claude 검토](docs/designs/feat86-localdata-maintenance.md)를 따릅니다.

## 생활인구 원자료 상태 진단

내부 진단 CLI는 명시한 관측 버전의 원천별·시간별 **행과 격자 개수**를 확인합니다. 먼저 읽기 전용 조회로 사용할 버전 UUID와 관측일을 확인합니다. 자동 최신 버전 선택이나 다른 날짜 대체는 하지 않습니다.

```sql
SELECT version_id, observation_date, grid_version_id
FROM living_population_versions
ORDER BY observation_date, version_id;
```

저장소 루트에서 `.env`의 로컬 개발 DB 설정을 사용해 실행합니다. 아래 UUID는 실제 조회한 값으로 바꿉니다. `--radius`는300/500/1000m이며 기본500m입니다.

```powershell
uv run --locked --extra dev python -m etl.living_pop.quality --population-version <UUID> --lat 37.5665 --lng 126.9780 --radius 500
```

기존 로컬 `spoton_dev`·앱 계정·head0011 검사를 통과한 DB만 READ ONLY REPEATABLE READ로 조회합니다. SQL별3초 제한을 유지하며 데이터나 결과 파일을 쓰지 않습니다. 성공은 stdout JSON 한 건/종료코드0, 실패는 `living_pop_quality:arguments|version|counts|configuration|database|operation_failed` 중 고정 오류 코드/종료코드1입니다. 입력 좌표·격자/행정동 코드·인구 값·DB URL은 출력하지 않습니다.

원천 중심점 속성(EPSG5179)을 기준으로 타원체 거리≤반경인 격자를 선택합니다. 72개 원천·시각 칸에서 `observed_zero`, `observed_nonzero`, `suppressed`, `missing` 행과 행이 있는/없는 격자를 구분합니다. 미좌표 행은 버전 전체 통계로만 별도 표시합니다. 저장 건수와 metadata를 대조하지만 content hash를 재검증하는 도구는 아닙니다.

**행 없음은0명이 아닙니다.** 복수행정동 행의 합산 의미·행정동 구성 완전성·격자의 관측일 적용 여부가 미확인이므로 인구 합계·완전성·제공률로 해석하지 않습니다. 공개 activity/Risk의 인구 pending 상태도 유지합니다. [설계·Claude 검토·실행 결과](docs/designs/feat84-population-quality-diagnostic.md)를 확인합니다.
