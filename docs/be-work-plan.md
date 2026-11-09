# Spot:ON BE 개발 작업 계획서

> 이 문서는 SpotON-BE의 **최상위 작업 기준 문서**다. 작업 방식은 [be-work-instructions.md](be-work-instructions.md)를 따른다.
> API 필드명·enum·endpoint는 **API 명세서 v1.2**가 FE↔BE 계약이다.

## 1. 개발 목표

Spot:ON BE는 사용자가 입력한 서울 주소와 업종을 기준으로 다음 데이터를 제공한다.

1. 주소 검색 및 좌표화
2. 과거 점포 이력
3. 주변 동일 업종 점포
4. 과거 시점 조회
5. 개·폐업 및 상권 활동 분석
6. 공식·참고지표 계산
7. AI 해석
8. 공공 상담·지원 정보 제공

FE에서는 지표를 직접 계산하지 않고, **BE가 계산 및 판정한 결과를 API 명세서 형식 그대로 반환**한다.

---

# 2. 최종 개발 범위

## 지원 지역

서울특별시

## 지원 업종

### 1차 업종

- 카페
- 음식점

### 음식점 세부 업종

- 한식 `korean`
- 중식 `chinese`
- 일식 `japanese`
- 양식 `western`

카페는 별도 세부 업종을 두지 않는다.

### 제외

- 키즈카페
- 라이브카페
- 분식
- 치킨
- 주점
- 기타 음식점
- 제과점

---

# 3. 구현 지표 범위

## 구현

- 동종업체 수
- 최근 12개월 개업 수
- 최근 12개월 폐업 수
- 연도별 개·폐업 추이
- 평균 영업 기간
- 공식 폐업률
- Spot:ON 참고 폐업률
- 1년 생존율
- 3년 생존율
- 추정매출
- 생활인구
- 상권변화지표
- 주야간 인구비

## 구현 제외

- LQ

---

# 4. 전체 BE 작업 순서

```text
PHASE 0  레포·개발환경 세팅
   ↓
PHASE 1  DB 구조 + 공통 API 구조
   ↓
PHASE 2  ETL / 인허가 데이터 적재
   ↓
PHASE 3  주소·점포 핵심 API
         /geocode
         /stores/history
         /stores/nearby
         /meta/data-range
         /stores/snapshot
   ↓
PHASE 4  상권·분석 데이터 적재
         market_areas
         market_stores
         market_sales
         living_pop
         상권변화지표
         brands
   ↓
PHASE 5  분석 API
         /market/activity
         /risk
   ↓
PHASE 6  AI
         /risk/interpret
   ↓
PHASE 7  상담·캐시·보안·테스트·문서화
```

---

# 5. PHASE 0 — BE 프로젝트 기반 세팅

## BE-00 프로젝트 기본 구조

### 작업

FastAPI 프로젝트 구조 생성.

```text
SpotON-BE/
├─ app/
│  ├─ main.py
│  ├─ core/
│  ├─ db/
│  ├─ models/
│  ├─ schemas/
│  ├─ routers/
│  ├─ services/
│  ├─ analysis/
│  └─ ai/
├─ etl/
├─ tests/
├─ data/
│  └─ sample/
├─ docs/
├─ .env.example
├─ .gitignore
├─ requirements.txt 또는 pyproject.toml
└─ README.md
```

### 완료 기준

```text
uvicorn app.main:app --reload
```

실행 성공.

---

## BE-01 공통 개발 설정

### 작업

- Python 3.11
- FastAPI
- ruff
- mypy
- pytest
- PostgreSQL driver
- SQLAlchemy
- Alembic
- GeoAlchemy2
- PostGIS

### CI

```text
ruff check
ruff format --check
mypy
pytest
```

통과.

---

## BE-02 환경변수

`.env.example`

```env
DATABASE_URL=

DATA_GO_KR_SERVICE_KEY=

KAKAO_REST_API_KEY=

JUSO_SEARCH_KEY=
JUSO_COORD_KEY=

LLM_PROVIDER=google
LLM_MODEL=
LLM_API_KEY=
```

실제 `.env`는 Git에 올리지 않는다.

---

## BE-03 기본 Health API

```http
GET /api/health
```

응답:

```json
{
  "status": "ok"
}
```

### 목적

FE↔BE 연결 및 배포 상태 확인.

---

# 6. PHASE 1 — 공통 API·DB 기반

## BE-04 공통 응답 Schema

API 명세서 기준:

```json
{
  "data": {},
  "meta": {},
  "error": null
}
```

### 공통 객체

- `ApiResponse<T>`
- `ApiMeta`
- `ApiError`
- `DataVersion`

### 반드시 여기서 먼저 구현

다른 API마다 응답 구조를 따로 만들면 안 된다.

---

## BE-05 공통 Error Handler

구현 코드:

```text
INVALID_PARAM
CATEGORY_REQUIRED
ADDRESS_NOT_FOUND
OUT_OF_SEOUL
AS_OF_OUT_OF_RANGE
UPSTREAM_ERROR
AI_UNAVAILABLE
AI_VERIFY_FAILED
INTERNAL_ERROR
```

FastAPI exception handler에서 공통 형식으로 변환.

---

## BE-06 DB 연결 및 Migration

### PostgreSQL + PostGIS

확인:

```text
DB 연결
PostGIS extension 활성화
Alembic migration 성공
```

---

# 7. PHASE 2 — 핵심 데이터 모델 및 ETL

이 단계가 BE 개발의 핵심이다.

**API부터 만드는 것이 아니라 먼저 `stores`를 정상적으로 만들고 검증해야 한다.**

---

## BE-07 stores 테이블

주요 컬럼:

```text
license_no
source
gu_code
name

address_road
address_jibun

building_key
floor_unit
location_level

open_date
close_date
status
status_code

bzstat_nm

category
sub_category
seoul_induty_cd

area_m2

lat
lng
geom

coord_source

is_franchise
brand_id

deleted_at

batch_id
updated_at
```

### 인덱스

```text
geom GIST
building_key
(category, status)
open_date
close_date
```

---

# 8. BE-08 인허가 ETL

## 원천

- 일반음식점
- 휴게음식점

## 처리 순서

```text
Open API 수집
↓
서울 25개 구 필터
↓
관리번호 중복 제거
↓
상태 분류
↓
주소 정제
↓
좌표 변환
↓
업종 매핑
↓
building_key 생성
↓
DB upsert
```

---

## 업종 매핑

### 카페

```text
category = cafe
sub_category = cafe
```

### 음식점

```text
한식 → korean
중식 → chinese
일식 → japanese
양식 → western
```

그 외 이번 서비스 대상이 아닌 업태:

```text
excluded
```

처리.

---

# 9. BE-09 building_key 생성

기준:

```text
지번주소
```

형식:

```text
{자치구}-{법정동}-{본번}-{부번}
```

예:

```text
마포구-서교동-123-4
```

산:

```text
마포구-상암동-산12-3
```

부번 없음:

```text
마포구-서교동-123-0
```

### 테스트 필수

같은 건물을:

- 도로명주소로 검색
- 지번주소로 검색

했을 때 동일한 `building_key`가 나와야 한다.

---

# 10. BE-10 floor_unit 추출

도로명주소 등에서:

```text
1층
2층 201호
B1
```

등을 추출.

확인 불가:

```text
null
```

`location_level = unverified`

---

# 11. PHASE 3 — 핵심 기능 API

데이터가 정상 적재된 후 API 개발 시작.

---

# BE-11 F-01 주소 검색

## API

```http
GET /api/geocode
```

## 처리

```text
query
↓
카카오 로컬 API
↓
서울 여부 확인
↓
lat/lng
↓
지번주소
↓
building_key
↓
floor_unit
```

### 조건

서울 외:

```text
422 OUT_OF_SEOUL
```

검색 없음:

```text
404 ADDRESS_NOT_FOUND
```

복수 후보:

```text
candidates[]
```

---

# BE-12 F-02 과거 점포 이력

## API

```http
GET /api/stores/history
```

## 입력

```text
building_key
floor_unit
category
```

## 처리

```text
building_key 일치
↓
시간순 정렬
↓
영업 기간 계산
↓
location_match 계산
```

### 위치 판정

```text
same_spot
same_building
unverified
```

### 완료 기준

표본 20건 원자료 대조.

---

# BE-13 F-03/F-04 주변 점포

## API

```http
GET /api/stores/nearby
```

## 조건

```text
lat
lng
radius
category
sub_category
as_of
area
franchise
```

## 공간 검색

PostGIS:

```text
ST_DWithin
```

최종 거리 확인.

```text
distance ≤ radius
```

경계 포함.

### 반환

```text
center
radius
count
markers[]
excluded_no_coord
```

---

# BE-14 F-05 데이터 조회 가능 범위

```http
GET /api/meta/data-range
```

반환:

```text
min_month
max_month
data_updated_at
collected_at
```

FE에서 조회 불가능한 월을 비활성화하는 데 사용.

---

# BE-15 F-05 시점 조회

```http
GET /api/stores/snapshot
```

기준 시점 T:

```text
open_date ≤ T
AND
(close_date IS NULL OR close_date > T)
```

반환:

```text
total_at_as_of
still_open
closed_since
other
stores[]
```

항상:

```text
N = A + B + other
```

성립해야 함.

---

# 12. PHASE 4 — 상권 데이터 적재

핵심 점포 API가 정상 동작한 후 진행한다.

---

# BE-16 market_areas

D-05 상권 Polygon 적재.

주요 컬럼:

```text
market_code
market_name
market_type
gu_code
area_m2
geom
```

### 작업

- EPSG 변환
- Polygon 유효성 보정
- GIST 인덱스

---

# BE-17 market_stores

서울시 점포-상권 데이터 적재.

```text
market_code
quarter
induty_cd
total_stores
open_stores
closed_stores
closure_rate
```

공식 폐업률에 사용.

---

# BE-18 market_sales

추정매출 적재.

```text
market_code
quarter
category
est_sales
```

주의:

**반경 매출로 계산하지 않는다.**

상권별 값을 반환한다.

---

# BE-19 living_pop

250m 격자 생활인구 적재.

```text
grid_id
date
hour
local_pop
long_foreign
short_foreign
geom
```

사용:

- 생활인구
- 주야간 인구비

---

# BE-20 상권변화지표

서울시 원자료 기준으로 적재.

원 지표의:

```text
상권코드
기준분기
상권변화 유형
```

을 그대로 사용.

Spot:ON에서 임의 점수화하지 않는다.

---

# BE-21 brands

공정거래위원회 브랜드 정보.

```text
brand_id
brand_name
normalized_name
```

점포 상호 정규화 후 비교.

결과:

```text
franchise
independent
unknown
```

단 화면에는:

```text
프랜차이즈(추정)
```

으로 표시.

---

# 13. PHASE 5 — 분석 API

---

# BE-22 F-06 상권 활동 분석

## API

```http
GET /api/market/activity
```

## 기본 계산

### 최근 12개월 개업

```text
open_date ∈ (T - 12개월, T]
```

### 최근 12개월 폐업

```text
close_date ∈ (T - 12개월, T]
```

### 반환

```text
recent_12m
yearly_trend
by_sub_category
sales
living_pop
flags
```

---

## 추정매출

반경과 겹치는 상권을 구하고:

```text
market_code
```

로 `market_sales` 연결.

각 상권별 값을 반환.

합산 금지.

---

## 생활인구

반경에 포함되는 250m 격자를 집계.

결측값:

```text
0으로 변환 금지
```

`missing_grid_count` 반환.

---

# 14. BE-23 F-07 Risk 분석

## API

```http
GET /api/risk
```

## 반환 지표

### 공식

```text
official_closure_rate
official_risk
```

### Spot:ON 참고

```text
closure_rate_12m
survival_rate_1y
survival_rate_3y
competitor_count
market_change
day_night_ratio
```

### 제외

```text
lq
```

---

# 15. BE-24 공식 폐업률

조건:

```text
market_code
+
seoul_induty_cd
+
quarter
```

일치.

값이 없으면:

```text
value = null
status = no_data
```

가까운 분기로 대체 금지.

---

# 16. BE-25 참고 폐업률

산식:

```text
최근 12개월 폐업 점포
───────────────── × 100
기간 내 영업 점포
```

서버에서만 계산.

FE 계산 금지.

---

# 17. BE-26 생존율

구현:

```text
1년
3년
```

판단 보류 조건은 설정값으로 관리.

예:

```python
MIN_SURVIVAL_SAMPLE = 5
```

---

# 18. BE-27 주야간 인구비

```text
주간 생활인구 합
────────────
야간 생활인구 합
```

데이터 없음:

```text
status = pending
value = null
```

---

# 19. PHASE 6 — AI

AI는 마지막 단계에서 붙인다.

지표 계산보다 먼저 AI를 구현하지 않는다.

---

# BE-28 AI 입력 Builder

`/risk` 결과에서 AI에 필요한 정보만 추출.

### AI에 전송

- 업종
- 반경
- 기준일
- 지표
- 분모
- 출처
- 상태
- missing_items

### 미전송

- 주소
- lat/lng
- building_key
- floor_unit
- 상호
- license_no

---

# BE-29 LLM Client

환경변수:

```text
LLM_PROVIDER
LLM_MODEL
LLM_API_KEY
```

모델 공급자와 API 로직 분리.

---

# BE-30 Prompt

```text
app/ai/prompts/
```

버전 관리:

```text
PROMPT_VERSION
```

---

# BE-31 AI Verifier

검사:

1. JSON Schema
2. 숫자
3. 지표 의미
4. 출처
5. status
6. 공식/참고 혼동
7. 금지 표현
8. 위치·개인정보
9. 분량/중복

실패:

1회 재생성.

또 실패:

```text
503 AI_VERIFY_FAILED
```

---

# BE-32 F-08 AI 해석 API

```http
POST /api/risk/interpret
```

처리:

```text
요청
↓
risk 서버 재계산
↓
AI 입력 생성
↓
LLM
↓
Verifier
↓
캐시
↓
응답
```

---

# 20. PHASE 7 — 보조 기능

# BE-33 F-10 상담 API

```http
GET /api/support-links
```

설정 파일 또는 DB에:

- 서울시 자영업지원센터
- 소상공인아카데미
- 서울시 지원사업
- 소상공인24

저장.

---

# BE-34 캐시

대상:

```text
risk
AI interpret
```

캐시 키:

- 분석 조건
- data_version
- prompt_version
- model
- context_hash

데이터 버전 변경 시 이전 캐시 재사용 금지.

---

# BE-35 로그

기록:

```text
시간
API path
HTTP status
처리시간
AI 성공/실패
```

기록 금지:

```text
사용자 주소
lat/lng
building_key
floor_unit
AI 입력/출력 원문
API key
```

---

# 21. 테스트 작업

각 기능 개발 시 테스트도 같이 만든다.

## BE-T01 Geocode

- 정상 주소
- 없는 주소
- 서울 외
- 복수 주소

## BE-T02 History

- 이력 있음
- 이력 없음
- 같은 건물 다른 층
- 상세 위치 미확인

## BE-T03 Radius

- 499m
- 500m
- 501m

## BE-T04 Snapshot

개업·폐업 월 경계.

## BE-T05 Filters

- 업종
- 시설 규모
- 프랜차이즈
- 정보 없음

## BE-T06 Market

- 개·폐업 수
- 추정매출
- 생활인구 결측

## BE-T07 Risk

- 공식 폐업률
- 참고 폐업률
- 생존율
- 상권 밖
- 표본 부족

## BE-T08 AI

- 없는 숫자 생성
- 잘못된 출처
- pending 지표 오용
- 금지 표현
- 개인정보 포함
- malformed JSON

---

# 22. GitHub Issue 작업 목록

실제로 GitHub Issues에는 아래처럼 올리면 된다.

| 순서 | Issue | 작업 |
|---:|---|---|
| 1 | BE-00 | FastAPI 프로젝트 초기화 |
| 2 | BE-01 | ruff·mypy·pytest·CI 설정 |
| 3 | BE-02 | PostgreSQL/PostGIS 연결 |
| 4 | BE-03 | 공통 API Response/Error |
| 5 | BE-04 | stores DB 모델 |
| 6 | BE-05 | 인허가 데이터 ETL |
| 7 | BE-06 | 업종 매핑 |
| 8 | BE-07 | building_key·floor_unit |
| 9 | BE-08 | `/geocode` |
| 10 | BE-09 | `/stores/history` |
| 11 | BE-10 | `/stores/nearby` |
| 12 | BE-11 | `/meta/data-range` |
| 13 | BE-12 | `/stores/snapshot` |
| 14 | BE-13 | 상권 Polygon ETL |
| 15 | BE-14 | 점포-상권 ETL |
| 16 | BE-15 | 추정매출 ETL |
| 17 | BE-16 | 생활인구 ETL |
| 18 | BE-17 | 가맹정보 ETL |
| 19 | BE-18 | 상권변화지표 ETL |
| 20 | BE-19 | `/market/activity` |
| 21 | BE-20 | 공식 폐업률 |
| 22 | BE-21 | 참고 폐업률·생존율 |
| 23 | BE-22 | 주야간 인구비 |
| 24 | BE-23 | `/risk` |
| 25 | BE-24 | AI input builder |
| 26 | BE-25 | LLM client |
| 27 | BE-26 | AI verifier |
| 28 | BE-27 | `/risk/interpret` |
| 29 | BE-28 | `/support-links` |
| 30 | BE-29 | 캐시·로그 |
| 31 | BE-30 | 통합 테스트·Swagger 검증 |

> 참고: 본문 섹션 번호(BE-00~BE-35)와 이 Issue 번호(BE-00~BE-30)는 체계가 다르다. 작업 보고 시 어느 번호인지 명시한다.

---

# 23. 개발 우선순위

## P0 — 반드시 먼저

```text
프로젝트 세팅
DB
공통 API
stores
ETL
```

이게 안 되면 아무 API도 정확하게 만들 수 없다.

---

## P1 — 핵심 차별 기능

```text
/geocode
/history
/nearby
/data-range
/snapshot
```

Spot:ON의 핵심 기능.

---

## P2 — 분석 기능

```text
market data ETL
/market/activity
/risk
```

---

## P3 — AI

```text
/risk/interpret
```

지표가 완성된 후 진행.

---

## P4 — 안정화

```text
캐시
로그
QA
Swagger
README
```

---

# 24. 첫 개발 시작 순서

현재 바로 시작한다면 다음 10개만 먼저 진행한다.

```text
1. BE 레포 초기 설정 확인
2. develop 브랜치 생성
3. FastAPI app/main.py
4. /api/health
5. PostgreSQL + PostGIS
6. 공통 response/error schema
7. stores 모델
8. Alembic migration
9. 인허가 ETL
10. stores 데이터 검증
```

여기까지 완료한 후에:

```text
/geocode
→ /history
→ /nearby
```

순서로 API 개발을 시작한다.

---

# 25. 개발 원칙

### 1. API를 먼저 임의로 만들지 않는다

API v1.2가 계약이다.

변경 필요 시:

```text
API 명세 수정
→ FE·BE 합의
→ 코드 수정
```

---

### 2. FE에서 지표 계산하지 않는다

모든 계산:

```text
BE
```

에서 수행.

---

### 3. ETL과 API를 분리한다

공공데이터:

```text
사용자 요청 → 외부 API
```

방식이 아니라:

```text
공공데이터
→ ETL
→ DB
→ API 조회
```

방식.

---

### 4. AI는 가장 마지막

AI는 분석 엔진이 아니다.

```text
BE 계산
→ 결과 JSON
→ AI 해석
```

순서를 지킨다.

---

# BE 완료 판단

다음 조건을 모두 만족하면 BE 구현 완료로 본다.

- 모든 필수 API Swagger 확인 가능
- 공통 `{data, meta, error}` 형식 준수
- 원자료 표본과 점포 데이터 일치
- 반경 경계 테스트 통과
- 시점 조회 경계 테스트 통과
- 공식/참고 지표 분리
- LQ 응답 없음
- AI 숫자·출처 오류 0건
- `.env` 및 API key GitHub 노출 0건
- CI 통과
- README 실행 방법 작성 완료
