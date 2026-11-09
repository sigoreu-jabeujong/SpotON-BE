# CLAUDE.md — SpotON-BE

## 최상위 작업 기준 (이 파일보다 우선)
- BE 개발 작업계획서: @docs/be-work-plan.md
- BE 개발 작업 지시: @docs/be-work-instructions.md
- API 계약 보완·외부 명세 동기화: @docs/be-contract-amendments.md
- 개발 규칙 보완(PDF 분석): @docs/be-development-rules.md — 사용자 결정과 기존 BE 문서를 우선하며 FE·BE 별도 저장소를 유지한다.
- API 명세서 v1.2가 FE↔BE 계약이다. 필드명·enum·endpoint를 임의로 바꾸지 않는다.
- 아래 내용과 위 문서가 충돌하면 **위 문서가 우선**이며, 충돌 내용을 먼저 사용자에게 알린다.

## 프로젝트 개요
- **Spot:ON**: 예비 창업자에게 창업 입지(자리)를 진단해 주는 공공서비스
- 팀: 시고르자브종 (청년공공AX서포터즈)
- 이 저장소: **백엔드(API 서버)**. 프론트엔드는 `../SpotON-FE`
- 최종적으로 공공 GitLab 등록 및 공공기관 배포 예정 → 특정 클라우드·유료 서비스에 묶이지 않게 작성
- 범위: 서울특별시 / 카페, 음식점(한식·중식·일식·양식). **LQ는 구현하지 않는다.**

## 기술 스택
- Python 3.11, FastAPI, Uvicorn
- PostgreSQL + PostGIS, SQLAlchemy, GeoAlchemy2, Alembic
- 검사 도구: ruff(스타일·포맷), mypy(타입), pytest(테스트)
- 생성형 AI: **무료 모델만 사용** (`.env`의 `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`)

## 폴더 구조
```
app/
├── main.py        # FastAPI 앱 생성, 라우터 등록, CORS
├── core/          # 설정(config), 공통 에러 처리
├── db/            # DB 세션·연결
├── models/        # SQLAlchemy/GeoAlchemy2 모델
├── schemas/       # Pydantic 요청/응답 모델 (공통 ApiResponse 포함)
├── routers/       # 엔드포인트. 요청 검증과 응답 반환만 담당
├── services/      # 비즈니스 로직, 외부 API 호출
├── analysis/      # 지표 계산 로직 (폐업률·생존율 등)
└── ai/            # LLM client, prompts/, verifier
etl/               # 공공데이터 수집·정제·적재
tests/             # pytest 테스트
data/sample/       # 테스트용 소량 샘플만 커밋
docs/              # 작업계획서·지시서
```
- 라우터에 로직을 넣지 말고 `services/`, `analysis/`로 분리
- 공공데이터는 요청마다 호출하지 않는다: `ETL → DB → API 조회` (주소 검색만 실시간)
- 원천 대용량 데이터는 커밋하지 않는다 (`data/` 중 `data/sample/`만 커밋)

## 자주 쓰는 명령어
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # BE-01에서 pyproject.toml의 의존성·dev extra 구성 예정
cp .env.example .env               # 이후 실제 키 입력
uvicorn app.main:app --reload      # http://localhost:8000/docs

# 기본 검사 (CI와 동일)
ruff check .
ruff format --check .
mypy app
pytest
```

## API 응답 형식 (FE와 반드시 동일하게 유지)
```json
// 성공
{ "data": { ... }, "meta": { ... }, "error": null }
// 실패
{ "data": null, "meta": { ... }, "error": { "code": "OUT_OF_SEOUL", "message": "..." } }
```
- 모든 엔드포인트는 이 형식을 따른다 (`ApiResponse` / `ApiMeta` / `ApiError` / `DataVersion` 공통 객체 사용)
- 현재 공식 통계는 데이터셋별 최신 공표·검증 분기, 과거 조회는 해당 분기를 사용한다. 실제 적용 분기를 표시하고 선택 분기의 결측을 이전 분기로 대체하지 않는다.
- 서울시 원천 `market_change`는 공식 지표다. 미확보 데이터는 `pending`, 조건별 결측은 `no_data`로 구분한다.
- `official_risk`의 링크 전용 응답 등 새 계약은 보완 문서에서 관리하고 외부 명세·FE 동기화 후 배포한다.
- 에러 코드: `INVALID_PARAM`, `CATEGORY_REQUIRED`, `ADDRESS_NOT_FOUND`, `OUT_OF_SEOUL`, `AS_OF_OUT_OF_RANGE`, `UPSTREAM_ERROR`, `AI_UNAVAILABLE`, `AI_VERIFY_FAILED`, `INTERNAL_ERROR`
- API 경로는 `/api/...` 로 시작 (예: `/api/health`, `/api/geocode`)
- 형식을 바꾸려면 코드부터 고치지 말고 명세 변경 → FE·BE 합의 → 코드 수정 순서. `../SpotON-FE/CLAUDE.md`도 함께 수정

## 코딩 규칙
- 함수·변수에 **타입 힌트 필수**, 요청/응답은 Pydantic 모델 사용
- 외부 API 호출은 `services/`에서 하고, 타임아웃과 예외 처리를 넣는다
- 기능 구현과 동시에 pytest 테스트 추가 (경계 테스트: 거리 499/500/501m, 시점 개업·폐업일 전후)
- 설정값은 하드코딩하지 말고 환경변수로 읽는다
- 의존성은 `pyproject.toml` 하나로 관리한다.
- 원본 좌표·좌표계와 원천 날짜·업태를 보존하고 좌표 보완·정제 플래그를 남긴다.
- 원본 보존에도 허용 필드 목록을 적용한다. 대표자명·연락처·상담 원문은 적재하지 않는다. ETL 로그는 배치·단계·처리/제외 건수 중심으로 남긴다.
- 계산 함수 docstring에는 실제 분석 로직 정의서 절 번호를 적고, 원문 미확보 시 번호를 만들지 않는다.
- 기본 모델은 `gemini-3.5-flash-lite`이며 환경변수로 변경 가능하게 유지한다. 공급자 429는 `AI_UNAVAILABLE`로 처리하고 한도·백오프를 설정으로 관리한다.
- 앞 PHASE를 하드코딩 숫자로 우회하지 않는다
- 주석·에러 메시지는 한국어 사용 가능, 변수·함수명은 영어 snake_case

## Git 규칙
- 브랜치: `main`(최종) ← `develop`(통합) ← `feat/...`, `fix/...`, `docs/...`
- `main`, `develop`에 직접 커밋·push 하지 않는다. 최신 `develop`에서 새 브랜치를 만든다
- 커밋 메시지: `타입(범위): 내용`
  - 예: `feat(be): 주소 검색 API 구현`, `fix(be): 반경 경계 포함 조건 수정`, `test(be): 시점 조회 경계 테스트 추가`, `data(etl): 음식점 업종 매핑 추가`
  - 타입: feat, fix, refactor, docs, test, chore, data

## 절대 하지 말 것
- `.env` 파일을 읽어서 출력하거나, 내용을 코드·로그·커밋에 넣지 않는다
- API 키·DB 비밀번호를 코드에 직접 쓰지 않는다
- 유료 API나 유료 모델을 추가하지 않는다
- `git push --force`, 브랜치 삭제 등 되돌리기 어려운 명령은 사람에게 확인받기 전에 실행하지 않는다
- 로그에 사용자 주소, lat/lng, building_key, floor_unit, AI 입력/출력 원문을 남기지 않는다
- AI에 주소, lat/lng, building_key, floor_unit, 상호, license_no를 보내지 않는다
- Spot:ON 자체 종합 위험점수·위험등급(예: "62.4점", "고위험", "추천")을 만들지 않는다
