# Spot:ON BE 개발 기준 및 작업계획

이 문서 하나에서 BE의 범위·개발 순서·데이터 규칙·API 보완·작업 방식을 관리한다. 공통 기준 변경은 해당 절을 수정한다. 기능별 설계·Claude 검토·커밋 계획은 `docs/designs/`에 별도로 기록하되 공통 규칙을 복제하지 않는다.

## 1. 적용 기준과 현재 상태

- 사용자 결정과 기존 BE 기준을 우선한다. PDF 등 외부 참고 자료와 충돌하면 현재 결정을 유지한다.
- FE·BE는 별도 저장소로 유지하며 작업 대상은 `SpotON-BE`다. 모노레포로 합치지 않는다.
- `develop`은 GitHub 기본·개발 통합 브랜치이고 `main`은 최종 반영용이다. **개발 전 이슈를 만들고 해당 작업 브랜치에서 구현한 뒤 PR로 `develop`에 병합한다.**
- 이슈 제목은 어떤 기능인지 알 수 있는 한국어로 짓고, 브랜치는 `feat#{작업 순번}-{영문-kebab-case}` 형식을 사용한다. 첫 작업은 `feat#1-initialize-fastapi`다. GitHub 실제 이슈 번호는 PR과 번호를 공유하므로 작업 순번과 다를 수 있으며 PR에서 실제 이슈를 연결한다. 셸에서는 `#`가 포함된 브랜치명을 따옴표로 감싼다.
- 기본 절차는 이슈 → 작업 브랜치 → Codex 설계 MD → Claude Code 검토·MD 직접 수정 → Codex 구현·기능별 커밋 → 로컬 테스트·실패 수정·재검증 → 푸시·develop 대상 PR → CI 확인이다. develop 병합은 사용자 요청 범위에 따라 수행하고 main 반영·브랜치 삭제·강제 푸시는 별도 요청 없이 하지 않는다.
- API 명세서 v1.2가 FE↔BE 계약이다. 원본은 저장소에 커밋하지 않는다. 이슈 #36에서 로컬의 API·데이터 활용 v1.2 및 분석 정의 원본을 확보·대조했다. 현행 사용자 결정과 다른 부분은 별도 기록하며 보완안을 외부 문서 수정 완료로 간주하지 않는다. 확인 대기는 9절에서 관리한다.
- BE-00~11의 앱·공통 오류·DB·stores·인허가 ETL 기반·건물/층호 정규화·주소 검색 코드가 develop에 반영됐다. 상세 meta·DataVersion과 BE-12 이후 점포 조회·분석 API는 미완료다. BE-08 실제 전체 적재는 [이슈 #34 설계](designs/feat34-localdata-import.md)에서 진행하며 코드 구현·실원천 검증·개발 DB 적재 완료를 구분한다. 필요한 자료가 없거나 실제 원천 수집이 실패하면 그 지점에서 중단하고 사용자에게 요청한다.
- 이슈 #34 작업 브랜치에서는 실제 응답 코드·ISO 날짜/시각과 적재 실행기를 보완했다. 사용자 제공 검증 CSV(2026-11-09 검증, 원천 기준일 미확인)로 개발 DB에 일반음식점 541,169건·휴게음식점 148,271건, 합계 689,440건을 적재하고 재적재·20건 원자료 자동 대조를 통과했다. 현재 API의 최신 전체 수집 완료나 BE-12 구현 완료를 뜻하지 않는다. develop 반영은 이슈 #34의 PR 상태를 따른다.

핵심 흐름은 `공공데이터 → ETL → DB → BE 계산 → API → FE 표시 → AI 해석`이다. 주소 검색만 명세에 따라 실시간 외부 호출을 허용한다. 앞 단계를 임시 수치로 우회하지 않는다.

이슈 #34는 PR #35로 develop에 병합됐다. 현재 작업인 [#36 BE-12 점포 이력 API](designs/feat36-store-history-api.md)는 작업 브랜치에서 구현·로컬 검증을 마쳤으며 PR·CI 확인 및 develop 병합 상태를 별도로 따른다. 개발 DB migration `0003`, 점포 689,440건·기존 내용 해시 보존·중복 0건, API 원자료 20건 대조를 통과했다. 배치 출처와 날짜 결측·기간 상태/사유를 추가했고 FE는 별도 이슈 #26·PR #27에서 호환한다. 기본 626개·격리 PostGIS 18개·FE 회귀 3개 검사 및 Chrome 연결 검증을 통과했다. 후속 BE-13 주변 점포부터는 아직 미구현이다. 아래 과거 진행 기록과 현재 브랜치·develop 반영 상태를 구분한다.

## 2. 서비스 범위

서울 주소와 업종을 기준으로 주소 검색, 점포 이력, 주변 동종업체, 과거 시점 조회, 개·폐업 분석, 공식·참고 지표, AI 해석, 상담·지원 링크를 제공한다.

| 구분 | 범위 |
|---|---|
| 지역 | 서울특별시 |
| 업종 | 카페 `cafe`, 음식점 `restaurant` |
| 음식점 세부 업종 | 한식 `korean`, 중식 `chinese`, 일식 `japanese`, 양식 `western` |
| 카페 | FE 세부 업종 선택 없음. DB 내부 분류는 `category = cafe`, `sub_category = cafe` |
| 제외 업종 | 키즈카페·라이브카페·분식·치킨·주점·기타 음식점·제과점 |
| 기본 지표 | 동종업체 수, 최근 12개월 개업·폐업 수, 연도별 추이, 평균 영업 기간, 공식·참고 폐업률, 1년·3년 생존율 |
| 조건부 지표 | 추정매출·생활인구·상권변화지표·주야간 인구비 |
| 제외 지표 | LQ, 자체 종합 위험점수·위험등급·성공률·추천/비추천 판정 |

분식·기타 음식점 제외는 의도된 범위 축소다. 동종업체 수는 지원 업종에 한정된 집계라고 안내하고 확인하지 않은 원자료 비율·건수를 사용하지 않는다.

조건부 지표는 출처·이용 조건·공간 단위·갱신 주기 검증 후 활성화한다. 확보 전에는 필수 수치 제공 일정에서 제외하고 `value = null`, `status = pending`과 사유를 제공하도록 계약을 보완한다. 확보된 자료의 조건별 결측은 `no_data`로 구분한다.

## 3. 개발 순서와 작업 목록

| PHASE | 목표 | 작업 |
|---|---|---|
| 0 | 프로젝트 실행·검사 기반 | BE-00~03 |
| 1 | 공통 API·DB 기반 | BE-04~06 |
| 2 | stores·인허가 ETL 검증 | BE-07~10 |
| 3 | 주소·점포 핵심 API | BE-11~15 |
| 4 | 상권·분석 데이터 적재 | BE-16~21, 조건부 데이터는 확보 후 |
| 5 | 상권 활동·Risk 계산 | BE-22~27 |
| 6 | 검증된 집계 결과의 AI 해석 | BE-28~32 |
| 7 | 상담·캐시·로그·통합 검증·제출 | BE-33~35 및 11절 |

작업 식별자는 `BE-00`~`BE-35`로 통일한다. 중복된 `BE-Ixx` 계획 번호는 더 이상 사용하지 않는다. GitHub 실제 Issue `#번호`는 별도로 연결한다.

| 작업 | 구현 대상·완료 기준 |
|---|---|
| BE-00 | 프로젝트 구조, `uvicorn app.main:app --reload` 실행 |
| BE-01 | pyproject 의존성·버전 고정·CI, ruff·mypy·pytest 통과 |
| BE-02 | 환경 설정 로딩, 비밀값 없는 `.env.example` |
| BE-03 | 공통 응답 형식의 `/api/health` |
| BE-04 | `ApiResponse<T>`, `ApiMeta`, `ApiError`, `DataVersion` |
| BE-05 | 공통 예외 처리와 오류 코드 매핑 |
| BE-06 | PostgreSQL 연결·PostGIS 활성화·Alembic 검증 |
| BE-07 | stores 모델과 공간·조회 인덱스 |
| BE-08 | 인허가 수집·정제·중복 제거·upsert·적재 검증 |
| BE-09 | 지번 기준 building_key 정규화 |
| BE-10 | 도로명·지번 상세 주소의 층·호수 추출 |
| BE-11 | F-01 주소 검색·서울 판정·후보 처리 |
| BE-12 | F-02 점포 이력·위치 일치·영업 기간, 원자료 표본 20건 대조 |
| BE-13 | F-03/F-04 주변 점포·반경·필터 |
| BE-14 | F-05 검증된 데이터 조회 가능 월 범위 |
| BE-15 | F-05 과거 시점 영업 점포·현재 상태 분해 |
| BE-16 | market_areas Polygon 적재·좌표계 변환·유효성 보정·GIST |
| BE-17 | market_stores 공식 점포·개폐업·폐업률 적재 |
| BE-18 | market_sales 상권별 추정매출, 확보 후 활성화 |
| BE-19 | living_pop 250m 격자·시간별 생활인구, 확보 후 활성화 |
| BE-20 | 서울시 원천 상권변화 유형, 확보 후 공식 지표 제공 |
| BE-21 | brands 정규화·프랜차이즈 추정 매핑 |
| BE-22 | F-06 활동 분석·연도별 추이·조건부 데이터 결합 |
| BE-23 | F-07 Risk·상권 판정·공식/참고 구분 |
| BE-24 | 공식 폐업률의 상권·업종·분기 매칭 |
| BE-25 | 참고 폐업률과 분모 계산 |
| BE-26 | 1년·3년 생존율·최소 표본 판단 보류 |
| BE-27 | 주야간 인구비, 데이터 확보 후 활성화 |
| BE-28 | AI에 필요한 집계·출처·상태만 추출 |
| BE-29 | 공급자 분리 LLM client·시간 제한·한도 대응 |
| BE-30 | `app/ai/prompts/` 및 `PROMPT_VERSION` 관리 |
| BE-31 | AI JSON·숫자·출처·의미·개인정보 검증 |
| BE-32 | F-08 서버 재계산 기반 AI 해석 API |
| BE-33 | F-10 상담·지원 링크 API |
| BE-34 | Risk·AI 캐시와 데이터/모델/프롬프트 버전 무효화 |
| BE-35 | 개인정보 없는 API·ETL 운영 로그 |

### 실제 개발 DB 연동의 지연과 큐 중단

실제 개발용 DB 연동은 초기에는 지연했으며, 2026-11-11 Docker 로컬 개발 환경에서 연결을 완료했다. BE-06의 CI 임시 DB 검증과 실제 개발 환경의 DB 연결 완료는 별개다. 원천 전체 적재와 데이터 기반 API 검증은 아직 미완료다.

2026-11-11 사용자 요청으로 Docker Desktop·WSL 설치와 Windows 재부팅 후 `spoton_dev` DB를 실행했다. 로컬 `.env`를 사용하는 백엔드의 `spoton_app` 접속, PostGIS 공간 함수, migration `0002`, stores·공간/조회 인덱스 5개와 ORM 조회를 검증했다. 앱 계정은 superuser·DB/role 생성 권한이 없으며 원천 적재 전 점포 수는 0건이다. 상세 상태와 실행 환경 주의점은 [로컬 PostGIS 구성 기록](designs/local-postgis-setup.md)을 따른다.

| 작업 유형 | 실제 개발 DB 미연동 상태의 처리 |
|---|---|
| stores 모델·마이그레이션 설계와 CI PostGIS 검증 | 진행 가능 |
| 샘플 기반 ETL 수집·정제·매핑 로직과 단위 검사 | 진행 가능 |
| 실제 개발 DB에 원천 데이터 적재·조회·지속 저장 | 실제 DB 연동 선행 필요 |
| 개발 DB를 사용하는 API의 전체 연동 검증 | 실제 DB 연동 선행 필요 |

실행 중 실제 개발 DB가 필요해 더 진행할 수 없으면 다음 절차를 따른다.

1. 막힌 작업의 진행 내용을 보존하고 원인·필요한 접속/권한/환경 조건을 보고한다. 접속 비밀값은 출력하지 않는다.
2. 실행 큐에서 해당 작업 바로 앞에 **`실제 개발 DB 연동`** 선행 작업을 추가한다. 기존 `BE-00`~`BE-35` 번호는 바꾸지 않으며, 이미 같은 작업/이슈가 있으면 재사용한다.
3. **해당 선행 작업 이후의 모든 실행 큐를 중단한다.** DB 의존성이 없는 다른 후속 작업도 우회 실행하지 않고 다음 이슈·브랜치·구현·PR을 자동 진행하지 않는다.
4. CI 통과·mock·SQLite·테스트용 DB를 실제 개발 DB 연동 완료로 대체하지 않는다. 실패·미검증 작업의 완료 표시와 PR 생성도 하지 않는다.
5. 실제 개발 DB의 PostgreSQL/PostGIS 준비, 로컬 비밀 설정의 DATABASE_URL, 필요한 migration 권한·실행, 실제 연결·기본 쿼리 성공을 확인하고 사용자에게 결과를 보고한 뒤 중단 큐를 재개한다.

이 규칙은 지금 진행 가능한 CI·샘플 작업을 즉시 중단한다는 뜻이 아니다. 실제 개발 DB가 필요한 경계에 도달했을 때 발동하며, 발동 후에는 선행 작업 해결 전까지 뒤의 큐 전체를 유지한다.

첫 구현은 BE-00~02 → health에 필요한 최소 공통 응답과 BE-03 → BE-04~06 → BE-07~10 순서다. stores 검증 후 BE-11~15, 분석 데이터·지표 검증 후 AI로 진행한다. 한 작업 단위를 작게 유지하고 기능과 테스트를 함께 작성한다.

## 4. 기술 구조와 실행

Python 3.11, FastAPI·Uvicorn, PostgreSQL·PostGIS, SQLAlchemy·GeoAlchemy2·Alembic을 사용한다. 검사 도구는 ruff·mypy·pytest이며 black을 추가하지 않는다. 특정 유료 서비스에 종속시키지 않고 AI는 무료 이용 가능한 범위만 사용한다.

```text
SpotON-BE/
├─ app/
│  ├─ main.py       # 앱·라우터·CORS
│  ├─ core/         # 설정·공통 예외
│  ├─ db/           # 연결·세션
│  ├─ models/       # DB 모델
│  ├─ schemas/      # 공통·요청·응답 타입
│  ├─ routers/      # 요청 검증·응답
│  ├─ services/     # 비즈니스 로직·외부 호출
│  ├─ analysis/     # 지표 계산
│  └─ ai/           # client·prompts·verifier
├─ etl/
├─ tests/
├─ data/sample/
├─ docs/be-work-plan.md
├─ pyproject.toml
├─ .env.example
└─ README.md
```

의존성과 ruff·mypy 설정은 `pyproject.toml`에서 관리한다. 실행·개발 의존성을 구분하고 직접 버전을 고정하며 간접 의존성은 `uv.lock`에 잠근다. 로컬·CI는 `uv sync --locked --extra dev`로 동일한 선언을 설치한다. PostGIS 서버 확장은 Python 패키지와 별도로 검증한다.

아래 명령은 저장소 루트에서 실행한다. 최초 설치는 `.env` 없이 가능하며 설정이 필요할 때만 예시를 복사한다. 기존 `.env`를 덮어쓰지 않는다.

```powershell
py -3.11 -m pip install uv==0.13.7
uv sync --locked --extra dev
uv run --locked --extra dev uvicorn app.main:app --reload --no-access-log

uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app migrations
uv run --locked --extra dev pytest
```

환경변수 목록과 기본값은 루트 `.env.example`에서 관리한다. DB, 공공데이터·카카오·주소 API 키, LLM 공급자·모델·키, 실행 환경·CORS 설정을 포함한다. 새 변수를 추가하면 같은 변경에서 예시를 갱신하며 실제 `.env`는 읽어 출력하거나 커밋하지 않는다.

## 5. 데이터 모델과 ETL

### stores

| 구분 | 컬럼 |
|---|---|
| 식별·원천 | `license_no`, `source`, `gu_code`, `name` |
| 위치 | `address_road`, `address_jibun`, `building_key`, `floor_unit`, `location_level` |
| 영업 | `open_date`, `close_date`, `status`, `status_code`, `bzstat_nm` |
| 업종·규모 | `category`, `sub_category`, `seoul_induty_cd`, `area_m2` |
| 좌표 | `lat`, `lng`, `geom`, `raw_x`, `raw_y`, `raw_crs`, `coord_source`, `coord_flag` |
| 정제·구분 | `date_flag`, `is_temporary`, `category_review_flag` |
| 브랜드 | `is_franchise`, `brand_id` |
| 이력 | `deleted_at`, `batch_id`, `updated_at` |

인덱스는 `geom GIST`, `building_key`, `(category, status)`, `open_date`, `close_date`다. 플래그는 정상·오류·미확인을 구분하며 날짜별 오류 사유를 남긴다. 미확인 `is_temporary`를 false로 바꾸지 않는다. 실제 타입·enum·중복 키는 원자료 대조 후 확정한다.

### 인허가 ETL 흐름

원천은 일반음식점·휴게음식점이다. 다음 순서로 처리한다.

1. Open API 수집 → 서울 25개 구 필터 → 관리번호 중복 제거
2. 허용 필드의 원본 보존 → 상태 분류 → 주소 정제
3. 원천 CRS 확인 → 좌표 변환·이상치 판정 → 행안부 API 보완 시도·재검증
4. 날짜 이상치·한시적 사업장 플래그 → 업종 매핑·업태 오기 검토
5. building_key·floor_unit 생성 → DB upsert → 배치별 건수·표본 검증

- 원본 좌표 표현과 확인된 CRS를 보존하고 보완 좌표로 덮어쓰지 않는다. CRS 불명·보완 실패를 유효 좌표처럼 취급하지 않는다. 공간 집계에서 제외하고 건수를 남긴다.
- 보완 좌표는 주소 일치를 확인한 결과만 채택하고 출처·변환·배치 이력을 보존한다. 외부 API 필드·좌표계·이용 조건은 연계 전에 확인한다.
- 1960년 이전 날짜, 파싱 실패, 미래 개업일, 개폐업일 역전은 검토 대상으로 둔다. 레코드와 원본을 보존하되 신뢰할 수 없는 날짜가 필요한 조회 범위·시점·기간 지표에서 제외한다.
- 한시적 사업장은 구분 보관하고 기본 장기 입지 분석 집계에서 제외한다.
- 명확한 원천 업태만 카페·음식점 4종으로 매핑한다. 기타 업태의 상호 키워드 후보와 업태 오기는 검토 대기 처리하고 기본 경쟁점 집계에 자동 포함하지 않는다. 확정 시 매핑 버전·근거를 남긴다. 미지원 업태는 `excluded`로 처리한다.
- 원본 보존에도 허용 필드 목록을 적용한다. 대표자명·연락처·상담 원문은 적재하지 않으며 원천 응답 전체를 무차별 저장하지 않는다.

### 건물·상세 위치 정규화

`building_key`는 지번의 `{자치구}-{법정동}-{본번}-{부번}`이다. 예: `마포구-서교동-123-4`, 부번 없음 `마포구-서교동-123-0`, 산 지번 `마포구-상암동-산12-3`.

법정동 뒤 본번·부번·산 여부만 읽고 건물명·층·호수를 분리한다. `외 n필지`는 명시된 대표 지번을 사용하고 부가 정보는 원본에 보존한다. 대표 지번·건물이 불명확하면 임의 결합하지 않는다. 카카오의 구조화된 법정동·본번·부번에도 같은 규칙을 적용해 도로명·지번 검색의 키가 같아야 한다.

`floor_unit`은 도로명·지번 상세 주소 모두에서 `1층`, `2층 201호`, `B1`, `162C호` 등을 추출한다. 확인 불가면 null, `location_level = unverified`다. 상세 주소 충돌이나 호수만으로 같은 자리를 확정할 수 없는 경우 `same_spot`으로 판정하지 않는다.

### 분석 데이터

| 데이터 | 주요 필드·처리 |
|---|---|
| market_areas | `market_code`, `market_name`, `market_type`, `gu_code`, `area_m2`, `geom`; 좌표계 변환·Polygon 보정·GIST |
| market_stores | `market_code`, `quarter`, `induty_cd`, `total_stores`, `open_stores`, `closed_stores`, `closure_rate` |
| market_sales | `market_code`, `quarter`, `category`, `est_sales`; 상권별 반환, 반경 매출 계산·합산 금지 |
| living_pop | `grid_id`, `date`, `hour`, `local_pop`, `long_foreign`, `short_foreign`, `geom`; 250m 격자 |
| 상권변화지표 | 상권코드·분기·서울시 원천 변화 유형 그대로 사용, 임의 점수화 금지 |
| brands | `brand_id`, `brand_name`, `normalized_name`; 공정위 원천과 점포 상호 정규화 비교 |

브랜드 판정은 `franchise`, `independent`, `unknown`을 구분하고 화면에는 프랜차이즈(추정)로 표시한다. 원천 브랜드 정보만으로 확정 가맹 여부를 단정하지 않는다.

## 6. API 공통 계약과 핵심 조회

라우터는 검증·응답만 담당하고 비즈니스 로직과 계산은 services·analysis로 분리한다. 모든 경로는 `/api/...`, 공통 응답은 `{data, meta, error}`다. Health도 다음 형식을 따른다.

```json
{
  "data": { "status": "ok" },
  "meta": {},
  "error": null
}
```

실패 시 data는 null, error에는 code·message를 담는다. 공통 meta는 계약에 따라 출처·실제 기준일/분기·공간 단위·분모·데이터 버전을 표현한다. 필드 구조를 임의로 만들지 않는다.

오류 코드는 `INVALID_PARAM`, `CATEGORY_REQUIRED`, `ADDRESS_NOT_FOUND`, `OUT_OF_SEOUL`, `AS_OF_OUT_OF_RANGE`, `UPSTREAM_ERROR`, `AI_UNAVAILABLE`, `AI_VERIFY_FAILED`, `INTERNAL_ERROR`를 사용한다. 외부 원시 예외·응답·인증 정보는 사용자에게 노출하지 않는다. 공급자 429는 기존 `AI_UNAVAILABLE`로 매핑한다. 일반 요청 검증은 422 INVALID_PARAM, 라우터 404/405는 HTTP 상태를 유지한 INVALID_PARAM, 미처리 예외는 500 INTERNAL_ERROR로 제공한다. CORS 안쪽에서 응답 시작 전 예외를 처리하며 프로토콜 응답을 강제 포장하지 않는다.

| 작업·기능 | API | 입력·반환 및 처리 |
|---|---|---|
| BE-03 | `GET /api/health` | 공통 응답의 status=ok |
| BE-11 / F-01 | `GET /api/geocode` | query → 카카오 → 서울 확인 → 좌표·지번·building_key·floor_unit. 서울 외 422 OUT_OF_SEOUL, 결과 없음 404 ADDRESS_NOT_FOUND, 복수 후보 candidates[] |
| BE-12 / F-02 | `GET /api/stores/history` | building_key·floor_unit·category, 시간순 이력·영업 기간·location_match(same_spot/same_building/unverified) |
| BE-13 / F-03~04 | `GET /api/stores/nearby` | lat·lng·radius·category·sub_category·as_of·area·franchise. center·radius·count·markers[]·excluded_no_coord |
| BE-14 / F-05 | `GET /api/meta/data-range` | min_month·max_month·data_updated_at·collected_at |
| BE-15 / F-05 | `GET /api/stores/snapshot` | total_at_as_of·still_open·closed_since·other·stores[] |
| BE-22 / F-06 | `GET /api/market/activity` | recent_12m·yearly_trend·by_sub_category·sales·living_pop·flags |
| BE-23 / F-07 | `GET /api/risk` | 7절의 공식·참고 지표 및 상태·근거 |
| BE-32 / F-08 | `POST /api/risk/interpret` | 서버 Risk 재계산 → 집계 입력 → LLM → 검증 → 캐시 → 응답 |
| BE-33 / F-10 | `GET /api/support-links` | 서울시 자영업지원센터·소상공인아카데미·서울시 지원사업·소상공인24 등 설정/DB 관리 |

- 이력은 지원 업종 전체의 자리 변화를 보여주는 방향으로 보완한다. category는 진단 맥락으로 유지하고 타 지원 업종 제거 필터로 쓰지 않는다. 이는 외부 명세 동기화 대기 사항이며 제외 업종까지 포함하는 전 업종 이력을 뜻하지 않는다.
- 이슈 #36 구현 계약은 source+license_no 식별, nullable 상호·개폐업일·기간, operating_period_status=fact|no_data 및 operating_period_reason을 사용한다. 날짜가 부족해도 이력은 유지하며 기간을 0으로 만들지 않는다. 기간은 달력상 완료 개월 수이고 영업 중 종료점은 검증된 배치들의 DAT_UPDT_PNT 최대 날짜다. 층만 동일하면 same_spot이 아니다. FE·BE CLAUDE.md·FE 타입·표·진단서를 함께 맞춘다. 오류는 현행 422/500 및 공통 외피를 유지하며 원본 400/504·geocode 구조·전체 meta 일괄 변경은 별도 동기화 대상으로 둔다.
- 주변 점포는 PostGIS `ST_DWithin`으로 검색하고 최종 `distance <= radius`를 검증한다. 반경 경계를 포함한다.
- 조회 가능 최소 월은 검증된 개업일과 실제 원천 조회 범위로 정한다. 이상 날짜·원천 기본값으로 달력을 확장하지 않는다. 유효 표본이 없으면 날짜를 만들어내지 않는다.
- 시점 T의 영업 조건은 `open_date <= T AND (close_date IS NULL OR close_date > T)`다. snapshot은 항상 `total_at_as_of = still_open + closed_since + other`를 만족해야 한다.

## 7. 분석·공식 지표 규칙

### 상권 판정과 기준 분기

- 좌표를 포함하는 세부 상권을 우선하고 관광특구를 별도 병기한다(R-13). 중복 합산하지 않는다. 같은 우선순위의 중첩 상권이 모호하면 후보·사유를 제공하고 임의 선택하지 않는다.
- 상권 밖이면 상권 공식 수치는 null/no_data와 상권 밖 사유를 제공하고 반경과 겹치는 상권 목록을 별도로 제공한다(R-14). 가까운 상권 수치로 대체하지 않는다. 반경 참고 지표는 유효 표본이 있으면 계산한다.
- 현재 조회의 공식 통계는 데이터셋별 공표·적재 검증이 완료된 최신 분기를 먼저 선택한다. 특정 상권·업종 결측을 이유로 더 과거 분기를 찾지 않는다.
- 과거 조회는 요청 시점이 속한 분기를 사용하고 없으면 no_data다. 요청 기준일과 실제 적용 분기를 구분한다. 점포·반경 기준일을 공식 통계 분기로 과거 이동시키지 않는다.
- 분기 자체를 정할 데이터 미확보는 pending이다. 상권변화지표에도 같은 선택 원칙을 적용하되 자체 데이터셋 공표 이력을 사용하며 업종별 자료가 아니면 업종 조건을 추가하지 않는다.

### 지표별 계산·반환

| 구분 | 지표 | 규칙 |
|---|---|---|
| 공식 | official_closure_rate | market_code + seoul_induty_cd + 선택 quarter 일치. 결측은 null/no_data, 가까운 분기 대체 금지 |
| 공식 | market_change | 서울시 원천 유형 그대로, 적용 상권·분기 표시 |
| 공식 안내 | official_risk | 수치 수집 경로 확인 전 링크 전용 보완안 사용. 추정 수치·스크래핑 금지 |
| 참고 | closure_rate_12m | 최근 12개월 폐업 점포 / 기간 내 영업 점포 × 100. 분모 정의·0 처리·대상 코호트는 원본 분석 명세 대조 후 확정 |
| 참고 | survival_rate_1y·3y | 원본 분석 정의에 따라 계산, 최소 표본 미달 판단 보류. 임계값은 설정으로 관리하며 기존 예시 5를 확정값으로 간주하지 않음 |
| 참고 | competitor_count | 지원 업종·유효 위치·시점·필터 기준의 동종업체 수 |
| 참고 | day_night_ratio | 주간 생활인구 합 / 야간 생활인구 합. 시간 구간·0분모 처리는 원본 명세 대조 후 확정 |

최근 12개월 개업·폐업은 각각 `open_date`, `close_date`가 `(T - 12개월, T]`인 건이다. 평균 영업 기간·생존율은 검증된 날짜를 사용하고 분모·결측·판단 보류 사유를 함께 제공한다.

추정매출은 반경과 겹치는 상권을 market_code로 연결해 각각 반환한다. 반경·점포 예상 매출이나 주변 평균 매출로 바꾸지 않는다. 생활인구는 반경 내 250m 격자 기준이며 실제 방문객 수가 아닌 추정치다. 결측을 0으로 바꾸지 않고 `missing_grid_count`를 반환한다.

공식 창업위험도 지표 객체의 보완안은 다음과 같다. URL 유효성은 연계 시 확인하며 최상위 응답은 공통 형식을 유지한다.

```json
{
  "id": "official_risk",
  "type": "official",
  "value": null,
  "status": "link_only",
  "link": "https://golmok.seoul.go.kr/stateDistrict.do",
  "copy_text": "상권명 · 업종명"
}
```

copy_text에는 확인된 상권·업종만 사용하고 사용자 주소·좌표를 넣지 않는다. 상권 밖·불명확한 경우 이름을 만들어내지 않는다. 링크 안내를 공식 수치 확보 완료로 보지 않는다. 새 enum은 9절의 계약 동기화 후 배포한다.

## 8. AI·캐시·운영

AI는 계산 엔진이 아니다. 서버에서 재계산한 Risk 결과 중 업종·반경·기준일·지표·분모·출처·상태·missing_items만 전달한다. 주소·좌표·building_key·floor_unit·상호·license_no 및 점포 식별정보는 외부 전송하지 않는다.

- 공급자와 API 로직을 분리한다. 기본 모델 `gemini-3.5-flash-lite`는 환경변수로 변경 가능하게 유지한다. 실제 연계 시 무료 이용 가능 여부·모델 수명을 다시 확인한다.
- 한도는 모델·프로젝트별 요청 수·토큰 수·일일 한도를 설정으로 관리하며 분당 15회를 공통 고정값으로 가정하지 않는다. 429에는 제한된 지수 백오프·지터를 적용하고 시간 예산 초과·일일 한도 소진 시 AI_UNAVAILABLE로 종료한다. 지표 API는 계속 동작해야 한다.
- 프롬프트는 `app/ai/prompts/`에서 PROMPT_VERSION으로 관리한다. Verifier는 JSON Schema, 숫자·지표 의미·출처·상태, 공식/참고 혼동, 금지 표현, 개인정보, 분량·중복을 검사한다. 실패 시 1회 재생성하고 재실패는 503 AI_VERIFY_FAILED다.
- Risk·AI 캐시는 분석 조건·data_version으로 구분하고 AI에는 prompt_version·model·context_hash를 추가한다. 데이터·모델·프롬프트가 바뀌면 이전 결과를 재사용하지 않는다.
- API 로그는 시간·경로·HTTP 상태·소요 시간·AI 성공/실패를 기록한다. ETL은 batch_id·단계·입력/정상/제외/보완/실패 건수·사유·소요 시간을 남긴다. 겹치는 검토 플래그 건수와 최종 제외 건수를 구분한다.
- 로그에는 사용자 주소·좌표·건물/층호 식별정보·원본 행·AI 입력/출력 원문·API 키를 남기지 않는다.

## 9. 외부 명세 동기화·확인 대기

아래는 개발 방향을 정리한 것이며 외부 원본 문서를 수정한 기록이 아니다. 원본 확인 → 명세 수정·FE 합의 → 구현·배포 순서로 반영한다. 기본 앱·원본 보존·정제 기반은 독립적으로 진행할 수 있다.

| 대상 | 대조·확정할 내용 |
|---|---|
| 범위 | 분식·기타 등 제외 안내, 기능 F-04·지표 M-05(LQ 제외), 서비스 개요·데이터 활용 명세 동기화 |
| 공식 분기 | 데이터셋별 공표 이력·실제 적용 분기 필드·현재/과거 선택 규칙 |
| 공식 변화지표 | market_change 공식 분류, 원천 유형·공간 단위 |
| 공식 위험 안내 | link_only enum·link·copy_text 필드와 URL, 상권 밖 안내 |
| 상권 판정 | 경계 포함 규칙·관광특구·중첩 후보·상권 밖 사유·반경 내 상권 목록 필드 |
| 데이터 상태 | pending/no_data·판단 보류 등 지표 상태와 FE 라벨 |
| 이력 | category가 진단 맥락이라는 의미와 타 지원 업종 반환 방향 |
| ETL·주소 | 원천 CRS·보완 API 필드, 플래그 enum, 모호한 대표 지번·상세 위치 처리 |
| 계산 | 참고 폐업률 분모, 생존율 코호트·표본 기준, 평균 영업 기간, 주야간 구간·0분모 |
| 필터 | 반경 선택값·시설 규모 구간·다중 선택·배열 표현과 API 인자 |
| AI | 429의 AI_UNAVAILABLE 매핑·HTTP 상태·재시도 안내·시간 예산, 무료 이용·한도 확인 |

출처 미확보 자료의 최신 분기나 원천 누락률·표본 수를 단정하지 않는다. 계산 docstring에는 실제 분석 정의서 절 번호를 쓰고 원본이 없으면 확인 대기로 남긴다.

## 10. 코드·협업·검증 규칙

### 작성·보안

UTF-8·LF·Python 4칸 들여쓰기를 사용한다. 모듈·함수·변수·JSON·DB 필드는 snake_case, DB 테이블은 복수형, 클래스·스키마는 PascalCase, 상수는 UPPER_SNAKE_CASE다. 타입 힌트와 Pydantic 요청·응답 모델을 사용하고 계산 함수는 근거 docstring을 둔다.

반경·최소 표본·시간 제한 등은 명명된 설정/상수로 관리한다. 외부 호출에는 timeout·예외 처리를 넣는다. 키·비밀번호는 서버 시크릿에서만 읽고 코드·문서·로그·단체방에 공유하지 않는다. `.env.example`의 비밀값은 비우며 비밀이 아닌 기본값은 유지할 수 있다. CORS는 개발 localhost·배포에 필요한 명시적인 origin만 허용한다.

원천 대용량 데이터는 커밋하지 않는다. `data/sample/`의 소량 샘플에는 출처·링크·기준일·실제/가상 여부·추출/생성 기준·라이선스·정제 제한을 적는다. 시연 숫자는 예시임을 표시한다.

### 작업·보고·Git

시작 전 이 문서, 현재 구현, 브랜치·미커밋 변경, CI·의존성을 확인한다. 완료된 것·없는 것·현재 PHASE·작업 번호·변경 파일·검증 방법과 한국어 이슈명을 먼저 보고한다. 다음 순서로 진행하고 완료 시 실제 이슈·브랜치·PR, 검증·남은 작업을 보고한다.

1. 이슈 생성 후 최신 develop에서 작업 순번을 넣은 브랜치를 만든다.
2. Codex가 `docs/designs/feat번호-기능명.md`에 범위·설계·테스트와 기능별 커밋 계획을 작성한다.
3. Claude Code가 해당 설계 MD를 검토하고 직접 수정한다. 검토 이유와 보류 사항을 같은 파일에 기록한다. 코드·다른 문서·Git은 수정하지 않는다.
4. Codex가 실제 수정본과 diff를 읽고 원본 계약·사용자 범위와 맞는지 확인한 뒤 구현한다. 기능과 해당 테스트를 한 커밋에 담고 독립 기능은 커밋을 나눈다.
5. PR 전에 로컬 테스트·ruff·mypy 등 해당 검사를 실행한다. 실패하면 수정·재검증하고 통과 전에는 PR을 만들지 않는다. 필요한 검사를 실행할 수 없으면 사유를 보고한다.
6. 검증 완료 후 커밋을 푸시하고 지정 양식으로 develop 대상 PR을 생성한다. CI 실패 시 수정 커밋과 재검증으로 처리한다.

Claude Code는 검토 대상 MD의 Read·Edit만 사용하도록 제한하고 UTF-8로 내용을 전달한다. 실제 파일 수정 여부를 확인하며 응답만 받고 검토 완료로 표시하지 않는다.

커밋은 `타입(영역): 한국어 요약`(50자 이내·끝 마침표 없음) 형식이다. 타입은 feat·fix·refactor·style·docs·test·chore·data를 사용하고 한 커밋에는 관련된 한 작업만 담는다. 실제 Issue는 #번호로 연결하고 상태는 To Do → Doing → Review → Done으로 관리한다.

PR은 develop을 대상으로 생성하고 제목·본문에 한국어 작업명과 실제 이슈를 연결한다. 본문은 사용자 지정 양식([PR 템플릿](../.github/pull_request_template.md))을 따른다. 2026-11-11 사용자 지시에 따라 확인 사항 네 문구를 변경하지 않고 모두 체크해 전송한다. 로컬 실행·비밀정보 검사·API 변경 시 FE·BE CLAUDE.md 동기화는 실제 수행하며, 코드 이해 항목은 사용자가 작업을 보며 확인하고 체크를 명시적으로 요청한 내용을 반영한다. 검사를 실행하지 않고 실행했다고 쓰지는 않는다. 병합 요청이 있는 경우에만 CI 통과와 실제 저장소 병합 조건을 확인한 뒤 Squash로 통합하고 이슈 상태를 확인한다. 승인 규칙은 우회하지 않는다. PDF의 24시간 리뷰 응답은 참고 제안이며 main 반영·소스 브랜치 삭제는 별도 요청 시 진행한다.

### 기능별 검증

| 테스트 | 필수 사례 |
|---|---|
| BE-T00 ETL | 원본 보존·좌표 누락/이상/보완 실패·날짜 오류·한시 사업장·카페 후보·산 지번/건물명/영문 호수/외 n필지 |
| BE-T01 주소 | 정상 서울·없는 주소·서울 외·복수 후보, 도로명/지번 building_key 일치 |
| BE-T02 이력 | 유/무·같은 건물 다른 층·상세 위치 미확인·타 지원 업종 이력·미지원 업종 제외·표본 20건 대조 |
| BE-T03 반경 | 499m 포함·500m 포함·501m 제외 |
| BE-T04 시점 | 개업/폐업일 직전·당일·이후 및 월 경계, snapshot 수 합계 |
| BE-T05 필터 | 업종·규모·프랜차이즈·정보 없음 |
| BE-T06 활동 | 개폐업 수·연도별 추이·상권별 매출 비합산·생활인구 결측과 missing_grid_count |
| BE-T07 Risk | 공식/참고·분모·생존율·표본 부족·상권 밖/중첩·관광특구·분기 선택·결측 비대체·링크·상태 |
| BE-T08 AI | 없는 숫자·잘못된 출처·pending 오용·금지 표현·개인정보·malformed JSON·429·백오프 상한·지표 API 독립 |

앱 구현 후 개발 서버 `/docs`에서 필수 API와 예시를 확인한다. 변경에 맞는 테스트와 ruff check·ruff format --check·mypy·pytest를 실행하고 실패·미실행 이유를 기록한다.

## 11. 완료 기준과 제출

필수 API·공통 응답, 원자료 표본 일치, 공간·시점 경계, 공식/참고 구분, LQ 미포함, AI 숫자·출처 검증, 비밀값 비노출, CI와 README 재현을 확인해야 완료다. 조건부 데이터는 미확보 시 pending과 사유를 검증하고 수치 제공 완료는 확보·검증 후 별도 판단한다.

README에는 서비스 소개·팀(시고르자브종)·역할, 환경·설치·실행, 변수명, 데이터 준비·ETL·샘플 재현, 검사 명령, 출처·라이선스를 적는다. 테스트 목록·출처표·PDF/이미지 예시를 준비하고 참고용 정보·사업주 역량 미반영·창업 성공/실패 판정 불가·예시 데이터를 명시한다.

공공 GitLab 이관은 FE·BE 별도 저장소 기준으로 진행한다. 대상·권한·브랜치·태그 범위를 확인하고 커밋 이력의 비밀값·대용량 자료를 검사한다. CI와 시크릿을 새 환경에 구성하며 Issue·PR·문서는 Git 미러만으로 옮겨지지 않으므로 별도 계획한다. 기존 대상 이력을 덮어쓰지 않고 이관 후 커밋·태그·브랜치와 실행·검사를 대조한 뒤 제출 주소를 갱신한다.

## 12. 참고 자료

개발 실행 절차는 10절을 따른다. 실제 개발 DB 연동을 지연하는 경우에는 3절의 선행 작업·큐 전체 중단 조건을 적용한다. CI 임시 DB의 통과를 실제 개발 DB 연결 완료로 간주하지 않는다.

기존 BE 문서와 사용자 결정을 통합했다. 사용자 제공 `12_개발규칙_Git코드컨벤션_SpotON.pdf`(v1.1, 2026-11-06, 5쪽)는 누락 규칙 보완에만 사용했다. 저장소 구조·브랜치·리뷰 방식은 PDF 제안보다 최신 사용자 결정을 우선한다.

AI 정보는 실제 연계 시 공식 자료와 프로젝트 계정에서 다시 확인한다. 모델 계열 전체의 자동 전환 날짜나 공통 호출 한도를 임의로 확정하지 않는다.

- [Gemini 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
- [호출 한도](https://ai.google.dev/gemini-api/docs/rate-limits)
- [모델 종료 일정](https://ai.google.dev/gemini-api/docs/deprecations)
- [요금·무료 범위](https://ai.google.dev/gemini-api/docs/pricing)
