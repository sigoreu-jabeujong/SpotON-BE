# Spot:ON BE 개발 기준 및 작업계획

이 문서 하나에서 BE의 범위·개발 순서·데이터 규칙·API 보완·작업 방식을 관리한다. 공통 기준 변경은 해당 절을 수정한다. 기능별 설계·Claude 검토·커밋 계획은 `docs/designs/`에 별도로 기록하되 공통 규칙을 복제하지 않는다.

## 1. 적용 기준과 현재 상태

- 사용자 결정과 기존 BE 기준을 우선한다. PDF 등 외부 참고 자료와 충돌하면 현재 결정을 유지한다.
- FE·BE는 별도 저장소로 유지하며 작업 대상은 `SpotON-BE`다. 모노레포로 합치지 않는다.
- 2026-11-12 사용자 지시: BE 작업 중 FE 코드·설정·문서를 직접 수정하거나 FE 이슈·PR을 만들지 않는다. 호환 변경은 [FE 수정 요청 보고서](fe-store-history-api-request.md)로 정리하고 사용자가 담당자에게 전달한다. FE·BE CLAUDE.md 동기화도 담당자 반영 전에는 완료로 표시하지 않는다.
- `develop`은 GitHub 기본·개발 통합 브랜치이고 `main`은 최종 반영용이다. **개발 전 이슈를 만들고 해당 작업 브랜치에서 구현한 뒤 PR로 `develop`에 병합한다.**
- 이슈 제목은 어떤 기능인지 알 수 있는 한국어로 짓고, 브랜치는 `feat#{작업 순번}-{영문-kebab-case}` 형식을 사용한다. 첫 작업은 `feat#1-initialize-fastapi`다. GitHub 실제 이슈 번호는 PR과 번호를 공유하므로 작업 순번과 다를 수 있으며 PR에서 실제 이슈를 연결한다. 셸에서는 `#`가 포함된 브랜치명을 따옴표로 감싼다.
- 기본 절차는 이슈 → 작업 브랜치 → Codex 설계 MD → Claude Code 검토·MD 직접 수정 → Codex 구현·기능별 커밋 → 로컬 테스트·실패 수정·재검증 → 푸시·develop 대상 PR → CI 확인 → Squash 병합이다. 2026-11-12 사용자가 이후 BE PR의 자동 승인·머지를 요청했다. CI·저장소 조건을 만족하면 develop에 자동 병합하며, 본인 승인 제한·보호 규칙을 우회하지 않는다. main 반영·수동 브랜치 삭제·강제 푸시는 별도 요청 없이 하지 않는다.
- 2026-11-12 추가 지시: 데이터 처리 등 유사한 선택은 Claude Code와 실제 설계 검토 후 가장 적절한 안을 선택하고 근거를 남긴다. 통상 선택마다 사용자에게 재확인하지 않는다. 필수 자료·키·권한이 없어 진행할 수 없는 경우의 요청/중단 원칙은 유지한다. BE-19 미매칭 격자 1개/24개 비식별 행은 사용자가 좌표 미확인 보존·공간 집계 제외로 확정했다.
- API 명세서 v1.2가 FE↔BE 계약이다. 원본은 저장소에 커밋하지 않는다. 이슈 #36에서 로컬의 API·데이터 활용 v1.2 및 분석 정의 원본을 확보·대조했다. 현행 사용자 결정과 다른 부분은 별도 기록하며 보완안을 외부 문서 수정 완료로 간주하지 않는다. 확인 대기는 9절에서 관리한다.
- BE-00~20 기반·조회·원천 적재, #58/PR59 시스템 점검·#60/PR61 기본 활동·#62/PR63 상권 판정·#64/PR65 Risk 참고지표가 develop에 반영됐다. BE-21은 #57에서 공정위 브랜드 인증 승인 대기다. 현재 #66은 BE-28 서버 재계산 기반 AI 허용 집계 입력을 구현한다. 전체 공통 meta·DataVersion 정리, 브랜드·공식 분기/업종 연결·조건부 수치·실제 AI API는 미완료다. 자료의 집계 의미/적용 시점은 적재 사실과 구분하며 필수 자료·키·권한이 없으면 해당 기능을 중단하고 요청한다.
- 이슈 #34 작업 브랜치에서는 실제 응답 코드·ISO 날짜/시각과 적재 실행기를 보완했다. 사용자 제공 검증 CSV(2026-11-09 검증, 원천 기준일 미확인)로 개발 DB에 일반음식점 541,169건·휴게음식점 148,271건, 합계 689,440건을 적재하고 재적재·20건 원자료 자동 대조를 통과했다. 현재 API의 최신 전체 수집 완료나 BE-12 구현 완료를 뜻하지 않는다. develop 반영은 이슈 #34의 PR 상태를 따른다.

핵심 흐름은 `공공데이터 → ETL → DB → BE 계산 → API → FE 표시 → AI 해석`이다. 주소 검색만 명세에 따라 실시간 외부 호출을 허용한다. 앞 단계를 임시 수치로 우회하지 않는다.

이슈 #34/PR #35 적재, #36/PR #37 이력, #38/PR #39·#40 설계, #41/PR #42 주변, #43/PR #44 월 범위, #45/PR #46 snapshot, #47/PR #48 경계, #49/PR #50 공식 점포 통계, #51/PR #52 추정매출, #53/PR #54 생활인구, #55/PR #56 공식 상권변화 유형, #58/PR #59 시스템 점검·#60/PR #61 기본 활동·#62/PR #63 상권 판정·[#64/PR #65 Risk 참고지표](designs/feat64-risk-reference-api.md)는 develop에 병합됐다. 현재 [#66 AI 집계 입력](designs/feat66-ai-risk-context.md)은 `feat#66-ai-risk-context`에서 Claude 실제 검토·Codex 최종 점검·구현·로컬 검증을 마쳤다. CI·저장소 조건 통과 후 일반 Squash 병합하며 실제 상태는 GitHub 기록을 따른다. FE 저장소는 수정하지 않으며 조회/활동/Risk 반영과 계산 보완안 합의는 담당자 대기다.

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
| BE-22 | F-06 활동 분석·연도별 추이·조건부 데이터 결합. #60은 기본 집계·선택 항목 pending까지이며 조건부 수치는 후속 |
| BE-23 | F-07 Risk·상권 판정·공식/참고 구분. #62 공간 기반·#64 참고지표 API, 공식 지표 연결은 후속 |
| BE-24 | 공식 폐업률의 상권·업종·분기 매칭 |
| BE-25 | 참고 폐업률과 분모 계산. #64 기간 분모10 기준·BE 계약안/FE 합의 대기 |
| BE-26 | 1년·3년 생존율·최소 표본 판단 보류. #64 고정 주년/진입 코호트 보완안·FE 합의 대기 |
| BE-27 | 주야간 인구비, 데이터 확보 후 활성화 |
| BE-28 | AI에 필요한 집계·출처·상태만 추출. #66 Risk 재계산/허용 입력·모의 공급자 검증, 공개 AI API는 후속 |
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
| market_sales | `version_id`, `market_code`, `quarter`, `induty_cd`, `est_sales`, `source_sales_count`; KRW 원천값·집계 기간 미확인, 환산·반경 매출·합산 금지 |
| living_population_observations (living_pop) | `version_id`, `source`, `hour`, `admin_code`, `grid_id`, `located_grid_id`, `population`, 상태; 원천·행정동 차원 보존, 250m geometry는 living_grids 참조 |
| market_changes | `version_id`, `market_code`, `quarter`, `change_code`, `change_name`, 평균 영업 개월4개; 업종 없는 서울시 원천 분류, 임의 점수화 금지 |
| brands | `brand_id`, `brand_name`, `normalized_name`; 공정위 원천과 점포 상호 정규화 비교 |

브랜드 판정은 `franchise`, `independent`, `unknown`을 구분하고 화면에는 프랜차이즈(추정)로 표시한다. 원천 브랜드 정보만으로 확정 가맹 여부를 단정하지 않는다.

이슈 #47의 경계 기반은 market_area_versions의 원본 hash/규칙별 불변 버전과 `(version_id, market_code)` 경계를 사용한다. EPSG:5181·UTF-8 원본의 면적/속성·보정 여부를 보존하고 유효 MULTIPOLYGON 4326으로 저장한다. 원본의 5자리 구 코드와 점포 관청 코드(7자리)를 혼동하지 않는다. source_file_date(첨부 수정일)·loaded_at과 boundary_as_of(실제 적용일, 현재 null)를 구분하며 새 적재를 최신/active로 자동 선택하지 않는다. 후속 분기별 공식 통계와 상권 코드/경계 호환을 확인하기 전에는 이 버전으로 지표를 자동 계산하지 않는다.

이슈 #49의 공식 점포 통계는 별도 불변 버전·`(version_id,market_code,quarter,induty_cd)`로 구분한다. 전체=SIMILR_INDUTY_STOR_CO, 일반=STOR_CO, 가맹=FRC_STOR_CO다. 개폐업 수·원천 비율을 보존하고 100 초과 값을 자르거나 null/없는 행을 0으로 바꾸지 않는다. 지원 업종만 적재하며 커피-음료 통계와 인허가 cafe의 모집단 동일성은 미확인이다. 지정 경계와 코드·유형·명칭을 대조하지만 boundary_compatibility=unverified로 유지한다. source_year/quarter·첨부 수정일·내부 파일 시각·loaded_at은 서로 다른 기준이며 최신 통계/유효 경계를 자동 선택하지 않는다. 공식 폐업률 매칭·지표 API는 BE-23/24에서 별도 검증한다.

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
| BE-14 / F-05 | `GET /api/meta/data-range` | category 필수·sub_category 선택. min_month(nullable)·max_month·max_date·data_updated_at·collected_at |
| BE-15 / F-05 | `GET /api/stores/snapshot` | total_at_as_of·still_open·closed_since·other·stores[] |
| BE-22 / F-06 | `GET /api/market/activity` | recent_12m·yearly_trend·by_sub_category·sales·living_pop·flags |
| BE-23 / F-07 | `GET /api/risk` | 7절의 공식·참고 지표 및 상태·근거 |
| BE-32 / F-08 | `POST /api/risk/interpret` | 서버 Risk 재계산 → 집계 입력 → LLM → 검증 → 캐시 → 응답 |
| BE-33 / F-10 | `GET /api/support-links` | 서울시 자영업지원센터·소상공인아카데미·서울시 지원사업·소상공인24 등 설정/DB 관리 |

- 이력은 지원 업종 전체의 자리 변화를 보여주는 방향으로 보완한다. category는 진단 맥락으로 유지하고 타 지원 업종 제거 필터로 쓰지 않는다. 이는 외부 명세 동기화 대기 사항이며 제외 업종까지 포함하는 전 업종 이력을 뜻하지 않는다.
- 이슈 #36 구현 계약은 source+license_no 식별, nullable 상호·개폐업일·기간, operating_period_status=fact|no_data 및 operating_period_reason을 사용한다. 날짜가 부족해도 이력은 유지하며 기간을 0으로 만들지 않는다. 기간은 달력상 완료 개월 수이고 영업 중 종료점은 검증된 배치들의 DAT_UPDT_PNT 최대 날짜다. 층만 동일하면 same_spot이 아니다. FE CLAUDE.md·타입·표·진단서의 호환은 요청 보고서에 따라 FE 담당자가 반영하고 BE는 해당 결과를 확인한다. 오류는 현행 422/500 및 공통 외피를 유지하며 원본 400/504·geocode 구조·전체 meta 일괄 변경은 별도 동기화 대상으로 둔다.
- 주변 점포는 PostGIS `ST_DWithin`으로 검색하고 최종 `distance <= radius`를 검증한다. 반경 경계를 포함한다.
- 조회 가능 최소 월은 검증된 개업일과 실제 원천 조회 범위로 정한다. 이상 날짜·원천 기본값으로 달력을 확장하지 않는다. 유효 표본이 없으면 날짜를 만들어내지 않는다.
- #43의 data-range는 nearby와 공통 출처·날짜 cohort를 사용하며 좌표·반경·면적·가맹 조건을 최소 월에 섞지 않는다. 보관된 인허가 날짜 구간을 재구성하며 원천 변경 이력 API의 시작일로 자르거나 과거 전체 현황 관측을 보장하지 않는다. D가 확인된 빈 업종은 min_month=null, max_month/max_date는 실제 D이고 출처 미준비는 500이다. FE nullable·세부 업종·최신 일자는 [FE 요청 보고서](fe-data-range-api-request.md)에 따라 담당자가 반영한다.
- 시점 T의 영업 조건은 `open_date <= T AND (close_date IS NULL OR close_date > T)`다. snapshot은 항상 `total_at_as_of = still_open + closed_since + other`를 만족해야 한다.
- #45 snapshot은 nearby와 같은 공간 조회·입력 파서를 쓰고 as_of만 필수다. 같은 목록의 최신 상태를 분해하며 N은 목록 길이와 같다. source+license_no 식별, nullable 상호/기간·기간 상태/사유, 전체 기간 latest_data, 서울 비공간 좌표 미확보 수를 반환한다. 중복/불변식·응답 검증 실패는 안전한 500/no-store이며 FE 반영은 [snapshot 요청 보고서](fe-store-snapshot-api-request.md)를 따른다.

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

PR은 develop을 대상으로 생성한다. 2026-11-12 최신 사용자 지시에 따라 제목은 FE PR 예시처럼 **`타입: 한국어 작업 설명`** 형식(예: `feat: 조회 가능한 데이터 월 범위 API 구현`, `fix: 잘못된 시점 처리 수정`)을 사용하고 본문에서 실제 이슈를 연결한다. 커밋의 `타입(영역): 한국어 요약` 형식은 유지한다. 본문은 사용자 지정 양식([PR 템플릿](../.github/pull_request_template.md))을 따른다. 2026-11-11 사용자 지시에 따라 확인 사항 네 문구를 변경하지 않고 체크한다(아래 FE 범위 정정이 우선). 로컬 실행·비밀정보 검사는 실제 수행하며, 코드 이해 항목은 사용자가 작업을 보며 확인하고 체크를 명시적으로 요청한 내용을 반영한다. 검사를 실행하지 않고 실행했다고 쓰지는 않는다. 2026-11-12 이후 BE PR은 로컬 검사·CI 통과와 실제 병합 조건을 확인하면 추가 확인 없이 develop에 Squash로 통합하고 이슈 종료를 확인한다. GitHub 본인 PR 승인 등록은 불가하므로 이를 우회·대리 승인하지 않는다. 필수 외부 리뷰가 남아 있으면 조건을 낮추지 않고 상태를 보고한다. PDF의 24시간 리뷰 응답은 참고 제안이며 main 반영·수동 소스 브랜치 삭제는 별도 요청 시 진행한다.

### 기능별 검증

2026-11-12 FE 업무 범위 정정이 위 체크 지침보다 우선한다. FE 담당자가 CLAUDE.md·계약·화면을 아직 반영하지 않았다면 관련 PR 확인 항목은 문구를 유지하되 미체크로 두고 담당자 반영 대기를 명시한다. 양쪽 수정 완료를 대신 주장하지 않는다.

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

## 13. BE-13 주변 점포 설계 진행

아래는 #38 설계 작업 당시 기록이며 PR #39·#40으로 반영됐다. 이후 #41 구현 결과는 14절과 구현 기록을 따른다.

2026-11-12 사용자 지시에 따라 설계는 BE 범위로 작성하고 FE 영향은 요청 보고서로 전달한다. FE 코드·설정·문서·이슈·PR을 직접 수정하거나 생성하지 않는다.

- [이슈 #38](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/38), 브랜치 `feat#38-nearby-api-design`, 최신 develop `1e7a2a6`에서 분리한 설계 전용 작업이다.
- [BE 설계](designs/feat38-nearby-api-design.md)와 [FE 변경 검토 요청](fe-nearby-api-request.md)을 작성한다. Codex 설계 → Claude MD 직접 수정 → Codex 최종 점검 → 문서 PR·CI 순서다.
- 선행 [PR #37](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/37)은 검토 중 develop에 병합됐고, 최신 develop `2160e64`를 설계 브랜치에 반영했다. 기존 작업 폴더를 유지한 별도 worktree를 사용한다. 사용자를 대신해 PR을 병합한 것은 아니다.
- #38 당시에는 설계만 진행했다. 주변 조회 API·migration·인덱스·DB 데이터 변경과 FE 구현은 완료로 표시하지 않았으며 후속 #41에서 BE 구현을 진행했다.
- 좌표 누락 건수는 반경 소속을 알 수 없어 서울 비공간 조건 기준 수와 집계 범위 meta를 제안한다. FE 표시 계약 확인 전 확정하지 않는다. 공간 후보 검색의 수치 경계 문제와 검증 계획은 설계 문서에 기록한다.
- 추가 읽기 전용 확인에서 지원 업종의 면적 0㎡가 6,316건이었다. 사용자는 0㎡를 정보 없음으로 처리하도록 확정했다. 설계는 DB 원본 0 보존·응답 area_m2=null·정보 없음 토글 동일 제어이며, 0을 확인된 33㎡ 미만으로 분류하지 않는다. 이번 문서 작업에서 실제 DB 값이나 코드는 변경하지 않는다.

## 14. BE-13 주변 점포 구현·검증 (#41)

- [구현 계획·Claude 검토·검증 기록](designs/feat41-nearby-api.md), 브랜치 `feat#41-nearby-api`. 최신 develop `2bb8f5d`에서 시작했다. 기존 문서 PR #40은 사용자 자동 머지 지시에 따라 일반 Squash로 병합했으며 본인 승인 등록 제한을 우회하지 않았다.
- `GET /api/stores/nearby`에 거리·시점·업종·면적·가맹 조건, 독립 unknown 토글과 legacy 호환, 기간·출처·좌표 누락 범위 meta를 구현했다. 0㎡는 원본 보존·출력 null이며 한시 true와 신뢰할 수 없는 날짜는 주변 시점 후보에서 제외한다. 이력 조회의 결측 보존은 유지했다.
- 개발 DB migration `0004`·689,440건. 인덱스 적용 전후와 읽기 검증 후 전체 행·geometry 해시 일치, 기존 내용 해시 일치, 앱 모델 비교 차이 0건이다. 실제 파괴적 suite는 별도 임시 DB에서만 실행했다.
- 일반 테스트 670개·격리 PostGIS 32개, ruff/format/mypy 65 files를 통과했다. 1,440개 공간 함수 조합의 후보 누락 0건, 실제 요청의 원자료 20건 대조·독립 WGS84 거리 재계산·실제 ORM EXPLAIN 반경 인덱스 조건·로컬 HTTP 응답을 확인했다.
- [FE 변경 요청 보고서](fe-nearby-api-request.md)를 현재 BE 계약에 맞췄다. FE 저장소는 변경하지 않았으며 지도·표·진단서와 FE CLAUDE.md는 담당자 반영 대기다. 좌표 누락 수의 서울 범위 표시 합의도 대기다.
- 로컬 검증 후 지정 양식 PR·CI 확인을 거쳐 develop에 자동 Squash 병합한다. 실제 PR·CI·병합 상태는 #41의 GitHub 연결 기록을 따른다. 원천 최신 전체 수집, 브랜드 분류, data-range·snapshot API는 이번 범위에 없다. 다음 BE 작업은 BE-14의 데이터 범위·시점 조회 설계다.

## 15. BE-14 데이터 조회 가능 월 범위 (#43)

- 최신 develop `61380a8`에서 `feat#43-data-range-api`를 만들었다. [Codex 설계·Claude 직접 검토·최종 점검·검증 기록](designs/feat43-data-range-api.md)을 따른다.
- `GET /api/meta/data-range`와 category/sub_category 검증·출처·날짜 후보·출처 meta 공통화를 구현했다. 기존 nearby의 출처/후보 함수 본문은 AST 비교로 같은 로직임을 확인했고 history/nearby 회귀를 통과했다. DB·migration·Docker·로컬 설정 변경은 없다.
- `uv run --locked --extra dev` 환경에서 ruff/format·mypy 70 files, 기본 693개·격리 PostGIS 43개를 통과했다. 실제 API 9개 업종/세부 업종 조합을 독립 SQL과 대조하고 원자료의 최소 날짜 표본 20건·전체 CSV 갱신일 최대값을 확인했다. data-range와 nearby의 최소 월 허용·직전 월 거절, 실제 HTTP·실제 SQL 실행 계획을 검증했다.
- 실제 개발 DB 0004·689,440건, API 읽기 확인 후 전체 행·geometry 해시가 기존 검증과 동일하다. 출처·최소 날짜의 세 SQL 실행은 관측값 약 0.036~376.281ms였으며 전체 요청 SLA 검증은 아니다.
- [FE 월 범위 요청 보고서](fe-data-range-api-request.md)에 nullable 최소 월·sub_category·max_date·달력/빠른 선택·과거 자료 한계를 요청했다. FE CLAUDE.md와 화면 반영은 대기다.
- PR 제목은 사용자 예시의 `feat: 조회 가능한 데이터 월 범위 API 구현` 형식으로 작성하고, 본문은 기존 양식을 유지한다. CI·병합 조건 확인 후 develop에 자동 Squash 병합하며 실제 상태는 #43 GitHub 기록을 따른다. 다음 BE 작업은 **BE-15 `GET /api/stores/snapshot`**이다.

## 16. BE-15 과거 시점 점포 상태 분해 (#45)

- 최신 develop `e1af8d2`에서 `feat#45-store-snapshot-api`를 만들었다. [설계·Claude 직접 검토·Codex 최종 점검·검증](designs/feat45-store-snapshot-api.md)을 따른다.
- `GET /api/stores/snapshot`을 구현했다. nearby의 공간 조회·기간 계산·입력 파서를 추출해 두 API의 같은 집합을 보장한다. N=A+B+C=목록 길이와 source+license_no 중복 없음을 검사하고, 응답 검증 실패는 부분 목록 없는 500/no-store로 처리한다.
- ruff/format·mypy 75 files, 일반 718개·격리 PostGIS 47개를 통과했다. 필터/시점/반경 조합·기간/결측·거리 경계·최신 상태·합계·같은 관리번호/다른 원천·빈 결과·오류와 기존 조회 회귀를 확인했다.
- 실제 DB 20개 조합의 목록·순서·집계를 독립 SQL/거리와 대조하고, 추출 전후 nearby 전체 JSON 두 경우·원자료 20건의 날짜/상태/기간·실제 HTTP·공간 인덱스 사용을 확인했다. 기존 사전 nearby 1회 실패는 재진단과 최종 조합에서 재현되지 않았으며 원인을 확정하지 않았다. 콜드 캐시/운영 SLA는 검증 완료로 표시하지 않는다.
- DB 0004·689,440건은 읽기 검증만 수행한다. 최종 해시 보존 결과는 구현 기록을 따른다. 모델·migration·원본·Docker·환경설정·FE 저장소 변경은 없다.
- [FE snapshot 요청](fe-store-snapshot-api-request.md)에 복합 식별자·결측·최신 상태/전체 기간·실제 기준일·집계/서울 범위 표시를 전달한다. FE·CLAUDE.md 반영과 문구 합의는 대기다. CI·저장소 조건 통과 후 자동 Squash 병합하며 실제 상태는 #45 GitHub 기록을 따른다.
- 다음 순서는 **BE-16 상권 경계 Polygon 적재 기반**이다. 필요한 원천·기준 시점·권한이 없으면 자료 요청 지점에서 중단하고 후속 실행 큐를 우회하지 않는다.

## 17. BE-16 상권 경계 버전 적재 (#47)

- 사용자 승인으로 공식 OA-15560 공개 ZIP을 직접 확보했다. 원본은 저장소 밖에 두고 hash로 검증했다. [설계·Claude 직접 검토·Codex 최종 점검·검증](designs/feat47-market-areas-import.md)을 따른다.
- market_area_versions/market_areas·migration 0005, pyshp 기반 ZIP 검증·읽기 전용 dry-run·PostGIS 보정/변환·advisory lock을 이용한 원자적/멱등 적재를 구현했다. 기존 인허가 ETL head guard도 0005로 갱신했다.
- 일반 742개·격리 PostGIS 54개·ruff/format·mypy 82 files를 통과했다. 실패 rollback·같은 버전 재사용·새 규칙 공존·동시 실행·훼손 거절·ZIP/CRS/geometry/면적·hole/multipart·FK/CHECK/GIST·기존 조회 회귀를 검증했다.
- 실제 개발 DB 0005에 1,650개 고유 상권·25개 구·4유형·버전 1개를 적재했다. 6개 보정 후 무효/빈 도형 0건이며 replay는 같은 버전·loaded_at·digest를 유지하고 inserted=0이다. 원자료 20건·독립 좌표 변환·hole/multipart·경계 포함·반경 교차·실제 GIST 사용·앱 관리 모델 차이 0건을 확인했다. 기존 점포/배치 및 원본 ZIP 보존 결과는 구현 기록을 따른다.
- 공식 첨부 수정일은 2023-10-23(내부 파일 2023-10-20)이며 포털 갱신일 2026-09-11을 적용일로 사용하지 않는다. boundary_as_of=null로 유지하고 최신/과거 분기의 경계라고 주장하지 않는다. 공개 API와 FE·Docker·환경설정은 변경하지 않았다.
- 지정 제목/본문의 PR·CI 후 develop에 일반 Squash 병합하며 실제 상태는 #47 연결 기록을 따른다. 다음은 **BE-17 점포-상권 공식 통계 적재**로, 원천·기준 분기·경계 코드 호환을 먼저 확인한다. 자료/권한이 없으면 사용자에게 요청하고 후속 큐를 우회하지 않는다.

## 18. BE-17 공식 점포·개폐업 통계 적재 (#49)

- #47/PR #48 경계 기반은 develop에 병합됐다. [#49 설계·Claude 직접 수정·Codex 최종 점검·검증](designs/feat49-market-stores-import.md)을 거쳐 market_store_versions/market_stores·migration 0006과 공식 연간 ZIP 실행기를 구현했다.
- 공식 OA-15577 2025년 ZIP(첨부 수정일 2026-05-21·CP949 CSV)을 확보하고 전체 304,775행을 검증했다. 지원 5종 **24,810행**(분기별 6,219/6,215/6,191/6,185), 미지원 279,965행 제외다. 누락 조합을 0으로 채우지 않고 전체/일반/가맹·개폐업 수와 원천 비율을 보존한다.
- 일반 **775개**, 격리 PostGIS **62개**, ruff/format·mypy **88 files**를 통과했다. 실제 DB 0006 dry-run→write→replay, 원자료 20행·저장 hash/모델 일치·기존 조회 API200을 검증했다. 기존 점포 689,440건·경계 1,650건·배치/버전의 전체 hash/건수와 원본은 보존됐다.
- 분기별 코드·유형 차이는 0개, 경계와 명칭 차이는 1개다. 이것을 적용 시점 일치로 간주하지 않으며 boundary_compatibility=unverified·boundary_as_of=null을 유지한다. 원천 폐업률 100 초과 24행도 그대로 보존했다. 공식/참고 비율 계산·지표 API·FE·Docker/환경설정 변경은 없다.
- 지정 PR·CI 후 develop에 일반 Squash 병합하며 실제 상태는 #49 연결 기록을 따른다. 다음은 **BE-18 상권별 추정매출 적재**로, 원천·사용 조건·기준 분기·업종/경계 호환부터 확인한다. 자료/권한이 없으면 사용자에게 요청하고 후속 큐를 우회하지 않는다.

## 19. BE-18 상권별 추정매출 원천 적재 (#51)

- #49/PR #50 공식 점포 통계는 develop에 병합됐다. [#51 설계·Claude 직접 수정·Codex 최종 검토·검증](designs/feat51-market-sales-import.md)을 거쳐 market_sale_versions/market_sales·migration 0007·원천 적재 CLI를 구현했다. ZIP/provenance/경계 대조 공통화의 BE-17 hash·출력 회귀와 실제 원본 replay를 확인했다.
- 공식 OA-15572 2025년 ZIP(첨부 수정일 2026-05-18·55개 한글 헤더·CP949)의 **85,732행**을 검증하고 지원 5종 **14,391행**(3,617/3,596/3,597/3,581)을 적재했다. 미지원 **71,341행** 제외다. 금액/건수 BIGINT를 환산하지 않고 null/실제0/누락 행을 구분한다.
- 일반 **798개**, 격리 PostGIS **72개**, ruff/format·mypy **97 files** 통과. 실제 DB 0007 dry-run→write→replay(동일 UUID/시각/hash·삽입0), 원자료 20행·모델 차이0·기존 API200을 확인했다. 기존 점포 689,440건·경계 1,650건·점포 통계 24,810행 및 전체 배치/버전 hash·원본은 보존됐다.
- 매출 금액 단위는 원이지만 `당월_매출_금액`의 분기 합계/월평균 의미는 미확인이다. amount_period_status/boundary_compatibility=unverified·boundary_as_of=null을 유지하며 매출 API 활성화·월/분기 환산·반경 합산·점포당 계산은 하지 않았다. 점포 통계에만 있는 지원 조합은 분기별 2,602/2,619/2,594/2,604개이며 0으로 채우지 않았다.
- 지정 PR·CI 후 develop에 일반 Squash 병합하며 실제 상태는 #51 연결 기록을 따른다. 다음은 **BE-19 생활인구 250m 격자·시간별 적재**로, 공식 제공 범위·권한·용량/기간·좌표계부터 확인한다. 키/자료가 없으면 사용자에게 요청하고 후속 큐를 우회하지 않는다. FE·Docker·환경설정 변경은 없다.

## 20. BE-19 생활인구 격자·시각별 원천 적재 (#53)

- #51/PR #52는 develop에 병합됐다. #53/브랜치 feat#53-living-population-import에서 사용자 1번 결정(좌표 미확인 보존·공간 집계 제외)을 반영했다. [Codex 상세 설계·Claude 실제 수정·Codex 점검](designs/feat53-living-population-import.md)을 거쳐 4개 테이블·migration 0008·일별 3개 원천/격자 manifest 실행기를 구현했다.
- 공식 2026-11-07 내국인 253,400행·장기 137,137행·단기 141,385행과 EPSG5179 격자 10,125개를 검증했다. 합계 **531,922행**이며 행정동/시각/원천 차원·원문 hash·비식별/결측/실제0을 보존한다. 미매칭 **1개 격자/24개 비식별 행**은 located_grid_id=null·unlocated로 보존하고 공간 inner join에서 제외한다. 전역 source/date 미확인 수를 반경 내 missing_grid_count로 표현하지 않는다.
- 후행 소수점 숫자 표기와 참조 무결성·메모리 등 선택은 사용자 추가 지시에 따라 Claude와 재검토 후 결정했다. Numeric(20,5)·명시적 문법·고정 소수 포맷·복합 FK·streaming/hash·일별 전체 트랜잭션을 적용했다. 통상 선택을 반복 질문하지 않고 근거를 남기며 필수 자료·키·권한 부재는 계속 요청한다.
- 일반 **844개**, 격리 PostGIS **82개**, ruff/format·mypy **107 files**를 통과했다. 실제 개발 DB 0008에서 dry-run 무삽입→격자10,125개/관측531,922행 적재→replay 삽입0을 확인했다. 원자료20행·좌표20개 대조·실제 GIST·모델차이0·기존 API5개200, 기존8개 테이블 전체 행/geometry hash·원본 ZIP4개 보존도 확인했다. 실행 비용과 검증 한계는 설계의 구현 기록을 따른다.
- API/FE·주야간 비율·반경 집계·다일 백필·Docker/환경설정 변경은 없다. grid_as_of=null·spatial_compatibility=unverified이며 사용자 결정만으로 격자의 실제 적용 시점이나 행정동 분할 합산 의미를 확정하지 않는다. CI 후 일반 develop Squash 병합하며 실제 상태는 #53 연결 기록을 따른다. 다음은 **BE-20 공식 상권변화지표 원천 적재**로, 제공 범위·기준 분기·원천 유형부터 확인한다.

## 21. BE-20 공식 상권변화 유형 원천 적재 (#55)

- #53/PR #54 생활인구는 develop에 병합됐다. [#55 설계·Claude 실제 Read/Edit·Codex 최종 점검](designs/feat55-market-change-import.md)을 거쳐 market_change_versions/market_changes·migration0009·전체 CSV 검증/완료 연도 적재 CLI를 구현했다.
- 공식 OA-15576 전체 CSV **36,300행**(2021년1분기~2026년2분기)을 검증하고 기존 점포/매출 자료와 같은 **2025년6,600행**(분기별1,650행)을 적재했다. 나머지29,700행은 선택 연도 밖이며 업종 제외가 아니다. 업종 필드를 추가하지 않고 원천4유형·공식 명칭·평균 정수개월을 보존한다.
- 기본 READ ONLY dry-run·연간 원자성·동시 writer 직렬화·hash 재검증/불변 버전·provenance 충돌 거절을 구현했다. 수집 시각은 재실행 시에도 최초값을 전달하고 source_file_date=null을 유지한다. 공통 boundary audit은 Protocol 타입만 변경했고 기존 동작·hash·lock key를 유지한다.
- 일반 **870개**, 격리 PostGIS **92개**, ruff/format **220 files**·mypy **113 files** 통과. 실제 DB0009에서 dry-run→write→같은 UUID/loaded_at/hash replay 삽입0·원자료20행·모델차이0·기존 API5개200을 확인했다. 기존12개 테이블 전체 행/geometry hash·건수와 원본 CSV SHA256도 보존됐다. 상세 결과는 설계의 구현 기록을 따른다.
- 경계 코드/구분 차이0·명칭 차이 분기별3개, boundary_compatibility=unverified다. 평균의 모집단·산정 기간/경계 적용일은 미확인이며 평균으로 분류를 재계산하지 않는다. 공개 API/FE·Docker/로컬 환경설정·의존성 변경은 없다. 지정 PR·CI 후 develop 일반 Squash 병합하며 실제 상태는 #55 연결 기록을 따른다. 다음은 **BE-21 브랜드 정규화·프랜차이즈 추정 매핑**으로, 공정위 공식 원천·권한·매칭 기준부터 확인한다.

## 22. 전체 시스템 점검·오류/중복 코드 정리 (#58)

- 사용자 요청으로 [Codex 점검·Claude 실제 MD 수정·최종 점검](designs/feat58-system-audit-cleanup.md) 후 오류4건을 재현·수정했다. LLM 실제 전체/개별 요청 timeout, 비유한 Retry-After fallback, 과도한 카카오 지번 숫자의 안전한 기존 주소 오류 처리, CSV 수집시각 기준 분기 검증을 보완했다. 회귀23개를 추가했으며 수정 전15실패→관련106통과를 확인했다.
- 같은 결과의 중복 법정동 조건2줄과 오래된 package 설명2개만 정리했다. 기존 주소42개 회귀를 재사용했으며 의도된 빈 예외/모델·ORM 등록 import/noqa·namespace·후속 AI 모듈·이유가 있는 주석은 보존했다. API/응답 계약·migration·원천·로컬 환경설정·FE 구현 변경은 없다.
- 전체 일반 **893개**, 격리 PostGIS **92개**, ruff/format **221files**, mypy **113files** 통과. 직접 의존성14개는 설치/uv.lock/pyproject 버전이 일치한다. 실제 head0009·모델차이0·일반 앱 계정 권한·정상API6개(외부 카카오 포함)·주소검색→이력200·잘못된 입력3개422·CORS를 확인했다. 기존 원본의 ETL7개 dry-run이 정상 종료했고 기존14개 테이블 전체 행/geometry hash·건수는 동일했다. 기록 범위와 상세 결과는 설계의 구현 기록을 따른다.
- FE는 읽기 점검과 lint/build/format을 통과했지만 HistoryTable null 정렬·source 없는 식별자 등의 반영이 대기다. 새 요청으로 중복 작성하지 않고 기존 [이력](fe-store-history-api-request.md)·[주변](fe-nearby-api-request.md)·[월 범위](fe-data-range-api-request.md)·[snapshot](fe-store-snapshot-api-request.md) 요청을 따른다. 이력 요청서의 BE PR 상태만 GitHub 병합 사실에 맞췄다. FE 파일/이슈/PR은 수정하지 않았다.
- 유료 LLM 실제 호출·미구현 activity/risk/AI API·브라우저 전체 시연·FE 통합 완료는 검증 범위가 아니다. 기존 Starlette/httpx deprecation 경고1건을 숨기지 않았고 의존성 대규모 교체는 하지 않았다. BE-21 인증 대기는 #57에서 유지한다. 지정 PR·CI/CodeQL 후 develop 일반 Squash 병합한다.

## 23. BE-22 기본 상권 활동 분석 (#60)

- 시스템 점검 PR #59 이후 develop `b9584c3`에서 `feat#60-market-activity-api`를 만들었다. 원본 API v1.2 §4-6·데이터 활용 v1.2 §3.9·분석 정의 §4-6을 대조하고, [Codex 설계·Claude 실제 MD 수정·Codex 최종 규칙/검증](designs/feat60-market-activity-api.md)을 기록했다. 브랜드는 선택 자료이므로 #57 승인 대기와 독립적인 기본 인허가 집계를 먼저 구현한다. 미확인 가맹을 개인 매장으로 바꾸지 않는다.
- `GET /api/market/activity`는 폐업 기록도 보존해 최근 12개월 개폐업·같은 월일까지의 실제 연도별 YTD·T 시점 세부 업종별 점포 수/평균 완료 개월을 반환한다. 평균은 버림·0분모 null이며 latest 전체 기간이나 수명 평균과 구분한다. 기존 거리/날짜/속성 필터·읽기 전용 세션·안전한 오류/no-store를 재사용한다.
- `sales`/`living_pop`은 항상 null이고 요청된 항목만 missing·pending/사유에 넣는다. 가맹 분류 pending, denominator=null·폐업 포함 cohort_size·서울 동일 비공간 조건의 좌표 미확보 수·출처 D/T/collected_at=null을 명시한다. 기존 API 형식·모델·migration·의존성·Docker/환경설정 변경은 없다.
- 전체 일반 **924개**, 격리 PostGIS **99개**, ruff/format **227 files**, mypy **116 files**를 통과했다. 새 일반31개·통합7개로 날짜 경계/윤년/YTD/폐업 보존/평균/거리·필터12조합/입력·DB오류·실제 READ ONLY 세션을 확인했다. 실제 개발 DB **10조합**을 독립 SQL과 대조했고 head0009·모델 차이0·기존14개 테이블 전체 행/geometry hash·건수 보존을 확인했다. API+독립 SQL 관측 시간은 SLA 검증이 아니다.
- [FE 활동 분석 요청](fe-market-activity-api-request.md)에 기간·평균·미요청과 pending 구분·가맹 미확인·출처/시점을 요청한다. FE 코드/CLAUDE.md·이슈/PR은 수정하지 않았고 반영 대기다. 브랜드 승인·조건부 수치 활성화·BE-22 전체 결합·Risk/AI는 후속이다. CI/CodeQL·저장소 조건 통과 후 develop 일반 Squash 병합하며 실제 상태는 #60 연결 기록을 따른다.

## 24. BE-23 선행 상권 공간 판정 (#62)

- 활동 API PR61 이후 develop `408e32b`에서 `feat#62-market-judgement`를 만들었다. [Codex 설계·Claude 실제 MD 수정·Codex 최종 점검](designs/feat62-market-judgement.md)을 거쳐 명시 버전의 내부 공간 판정 서비스와 엄격한 모델을 구현했다. 공개 Risk 경로·공식 수치 연결은 후속이며 기존 API 형식·FE 계약은 바꾸지 않았다.
- ST_Covers의 경계 포함·hole/multipart, 세부 상권 우선/관광특구 병기, 동순위 중첩의 ambiguous 후보, 상권 밖의 반경 교차 목록을 제공한다. 최신 버전 자동 선택이나 가까운 상권 대체는 하지 않으며 빈/부분 버전은 안전하게 실패한다. 적용성은 unverified로 고정하고 원천 수정일을 적용일로 바꾸지 않는다.
- 전체 일반 **957개**, 격리 PostGIS **103개**, ruff/format **233 files**, mypy **118 files** 통과. 새 일반33개·통합4개로 경계/구멍/분리 영역/유형·중첩/거리/버전 격리/미확인 상태/읽기 전용 호출을 확인했다. 실제 **135조합**을 독립 SQL과 대조해 일치했고 모델차이0·head0009·무효 도형0을 확인했다. 기존 경로 검사 최초1회 실패 후 재확인은 모두200이며 원인 미확정·SLA 미검증이라는 한계도 남겼다.
- 실제 개발 DB 기존14테이블 전체 행/geometry hash·건수 보존을 확인했다. PR·CI/CodeQL을 확인하고 develop 일반 Squash 병합하며 실제 상태는 #62 연결 기록을 따른다. DB 모델/migration·의존성·원본·Docker/로컬 설정·FE 변경은 없다. 이 내부 기반에는 FE 보고서가 필요한 공개 계약 변경이 없으며 후속 Risk 계약 때 요청서를 작성한다. 브랜드 승인 #57·경계 적용 분기 확인·공식/참고 지표·Risk API·FE 통합은 대기다.

## 25. BE-23/25/26 Risk 참고지표 (#64)

- 상권 기반 PR63 이후 develop `1cb88e2`에서 작업했다. [Codex 설계·Claude 실제 MD 수정·Codex 최종 결정/검증](designs/feat64-risk-reference-api.md)을 거쳐 GET /api/risk를 구현했다. 참고 폐업률은 기간 중 영업 기록 분모10, 생존율은 개업 코호트의 고정1/3주년·분모5로 계산한다. 원본의 모호한 시점과 FE mock을 보완한 BE 계약안이며 현재 잔존과 구분하고 원본/FE 합의 완료로 표시하지 않는다.
- 동종업체 수와 같은 필터/좌표 확보 서울 비교값·분모/출처 배열·Decimal HALF_UP·소표본/0분모/실제0·미요청 구분을 제공한다. 경계 UUID는 서버가 명시한 경우에만 후보로 읽고 market.status=unverified를 유지한다. 공식 폐업률/상권변화·인구비는pending, 공식 창업위험도는link_only다. 기존 API·모델/migration·의존성·Docker/.env·FE 변경은 없다.
- 전체 일반 **992개**, 격리 PostGIS **111개**, 최종 ruff/format **240 files**, mypy **121 files** 통과. 새 일반35·통합8로 기간/코호트 양끝·주년/윤년·현재 폐업과 고정기간 생존 차이·표본/비율/서울 비교·12개 독립 unknown 조합·거리·미확인 후보·실제 읽기 전용 세션을 확인했다.
- 실제 **10조합**을 독립 SQL·다른 달력/정수 반올림식과 대조했고 실제 표본5건 주년·명시 UUID 후보·모델차이0·head0009·14테이블 전체 행/geometry hash·건수 보존을 확인했다. 단일 요청 관측0.492~0.680초(별도최초1.802초)·서울 aggregate 관측35.632ms는 운영/동시부하 SLA 보장이 아니다. 데이터 선택/지위승계/과거 재구성 한계는 설계에 기록했다.
- [FE Risk 요청서](fe-risk-reference-api-request.md)에 배열 출처·기간 분모 기준·고정 주년 의미·unverified·0/null/서울 비교·지표 상태/문구 검토를 요청한다. FE/원본/CLAUDE.md 반영은 대기다. 공식 분기/업종 매칭·조건부 수치·브랜드57·AI/캐시는 후속이며 CI/CodeQL 후 develop 일반 Squash 병합한다. 실제 상태는 #64 연결 기록을 따른다.

## 26. BE-28 AI 해석용 허용 집계 입력 (#66)

- Risk PR65 이후 develop `27e7c8a`에서 `feat#66-ai-risk-context`를 만들었다. [Codex 설계·Claude 실제 MD 수정·Codex 최종 점검](designs/feat66-ai-risk-context.md)을 거쳐 query-only 서버 재계산→typed allowlist→불변 입력/안전한 직렬화·해시→기존 프롬프트 준비를 구현했다. 주소/좌표/상권/점포·URL/raw meta/UUID를 전송하지 않으며 사유·출처·기간·비율·방법론도 검증한다.
- 프롬프트 v2와 지문 이력을 추가해 미산정/안내 전용·고정 주년·서울 비교·가맹 미확인을 유지한다. verifier도 link_only/unverified 값 생성을 차단한다. 원문을 repr/오류에 남기지 않고 데이터/프롬프트 버전은 context_hash와 구분한다. 실제 공급자/공개 AI API·전체 응답/의미 검증·캐시는 후속이다.
- 전체 일반 **1,018개**, 격리 PostGIS **115개**, ruff/format·mypy **123 files** 통과. 새 일반26·통합4로 필드/값 canary·위조 모델 재검증·직렬화 경고/원문 비노출·상태/숫자·동일 hash/중첩 불변성·실제 서버 재계산/읽기 전용을 확인했다. 실제 DB **6조합**과 별도 명시 경계 후보에서 추출값·해시·모의 공급자 본문을 대조했고 실제 LLM 호출은0이다.
- head0009·모델차이0·14테이블 전체 행/geometry hash·건수 보존, 기존 health/activity/risk 실제 조회200·공개 AI 경로 미추가를 확인했다. 최초 준비5.995초·이후0.565~0.760초, 별도 실제 문장3초 세션 준비0.608초를 관측했으나 원인/콜드캐시·운영 SLA는 확정하지 않았다.
- API/DB 모델/migration·의존성·원본·Docker/.env·FE 변경은 없고 공개 계약 변경이 없어 새 FE 요청서는 만들지 않았다. 현재 Risk 보고서의 FE 반영과 브랜드57·공식/조건부 지표·실제 AI/FE 통합은 대기다. CI/CodeQL 후 develop 일반 Squash 병합하며 실제 상태는 #66 연결 기록을 따른다.
