# Spot:ON BE 개발 작업 계획서

> 이 문서는 SpotON-BE의 **최상위 작업 기준 문서**다. 작업 방식은 [be-work-instructions.md](be-work-instructions.md)를 따른다.
> API 필드명·enum·endpoint는 **API 명세서 v1.2**가 FE↔BE 계약이다.
> 개발 전 보완 사항과 외부 명세 동기화 목록은 [be-contract-amendments.md](be-contract-amendments.md)를 따른다. 이 문서의 보완안을 외부 API 명세에 이미 반영된 것으로 간주하지 않는다.
> 실무 규칙 보완은 [be-development-rules.md](be-development-rules.md)를 참고한다. 기존 BE 문서를 우선하며 FE·BE 별도 저장소를 유지한다.

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

분식·기타 음식점 등을 제외한 것은 의도된 서비스 범위다. 동종업체 수는 지원 업종에 한정된 수치임을 표시한다.

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

추정매출·생활인구·상권변화지표·주야간 인구비는 데이터 확보 후 활성화하는 조건부 범위다. 출처·이용 조건·공간 단위·갱신 주기를 검증하기 전에는 필수 적재·수치 제공 일정에서 제외한다. 그동안 API는 `value = null`, `status = pending`과 미확보 사유를 제공하도록 계약을 보완한다. 확보된 자료에서 특정 조건의 값만 없는 경우는 `no_data`로 구분한다.

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
├─ pyproject.toml
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

Python 의존성은 `pyproject.toml` 하나로 선언하고 실행·개발 의존성을 구분한다. 로컬·CI 모두 같은 선언을 설치한다. PostGIS 서버 확장은 Python 패키지 설치와 별도로 검증한다.

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
LLM_MODEL=gemini-3.5-flash-lite
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
  "data": {
    "status": "ok"
  },
  "meta": {},
  "error": null
}
```

Health API도 다른 API와 동일한 공통 응답 형식을 사용한다.

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

공급자 호출 한도 초과(429)는 기존 `AI_UNAVAILABLE`로 매핑한다. 원문 오류를 노출하지 않고 재시도 가능 여부와 대기 안내를 제공한다. 분당 15회 같은 고정 한도를 가정하지 않고 실제 모델·프로젝트 한도를 설정으로 관리한다.

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

raw_x
raw_y
raw_crs

coord_source
coord_flag
date_flag
is_temporary
category_review_flag

is_franchise
brand_id

deleted_at

batch_id
updated_at
```

`raw_x`, `raw_y`는 원본 표현을 보존하며 보완 좌표로 덮어쓰지 않는다. `raw_crs`는 확인된 원천 좌표계만 기록하고 불명이면 미확인으로 둔다. 원천 주소·날짜·업태와 변환 이력은 접근을 제한한 원본 보관 계층에 배치 단위로 보존한다.

보관 계층에도 허용 필드 목록을 적용하고 대표자명·연락처·상담 원문은 적재하지 않는다. 원천 응답 전체를 무차별 저장하지 않는다.

플래그는 검증 완료·오류·미확인 상태를 구분할 수 있게 설계한다. `is_temporary`는 미확인을 `false`로 바꾸지 않는다. 날짜별 오류 사유를 기록해 개업일 오류와 폐업일 오류를 구분한다. 확정 enum은 모델 구현 전에 원자료와 대조해 정의한다.

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
원본 좌표·좌표계 및 원천 필드 보존
↓
상태 분류
↓
주소 정제
↓
좌표계 확인·좌표 변환·이상치 판정
↓
좌표 누락·오류 시 행안부 API 좌표 보완 시도 및 재검증
↓
날짜 이상치·한시적 사업장 플래그
↓
업종 매핑·업태 오기 검토 플래그
↓
building_key 생성
↓
DB upsert
```

보완 실패·원천 좌표계 미확인은 플래그로 남기고 유효 좌표인 것처럼 취급하지 않는다. 공간 집계에서는 제외하고 제외 건수를 기록한다. 주소가 일치하는지 확인한 보완 결과만 채택하며 `coord_source`와 배치 이력을 남긴다. 외부 API의 실제 필드·좌표계·사용 조건은 연계 구현 전에 확인한다.

1960년 이전 날짜, 파싱 실패, 미래 개업일, 폐업일이 개업일보다 이른 경우는 검토 대상으로 둔다. 원본 레코드는 보존하되 신뢰할 수 없는 날짜가 필요한 조회 범위·시점 판정·기간 지표의 계산에서는 제외하고 제외 건수를 남긴다. 한시적 사업장은 구분 보관하고 기본 장기 입지 분석 집계에서 제외한다.

---

## 업종 매핑

### 카페

```text
category = cafe
sub_category = cafe
```

위 `sub_category = cafe`는 DB 내부 분류다. FE에서 카페 세부 업종을 선택하거나 요청 필터로 보낼 필요는 없다.

원천 업태가 명확한 카페만 기본 포함한다. 기타 업태에서 상호 키워드로 발견한 카페 후보와 업태 오기는 `category_review_flag`로 검토 대기 처리하고 자동으로 경쟁점 수에 포함하지 않는다. 검토 확정 시 매핑 버전과 근거를 남긴다.

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

법정동 뒤 지번의 본번·부번·산 여부만 파싱하고, 뒤따르는 건물명·층·호수를 지번에 붙이지 않는다. `외 n필지`가 있으면 명시된 대표 지번을 사용하고 부가 필지 정보는 원본에 보존한다. 대표 지번이 불명확하거나 복수 건물로 해석되면 임의로 결합하지 않고 위치 미확인으로 처리한다. 카카오의 구조화된 법정동·본번·부번에도 같은 정규화 규칙을 적용한다.

### 테스트 필수

같은 건물을:

- 도로명주소로 검색
- 지번주소로 검색

했을 때 동일한 `building_key`가 나와야 한다.

---

# 10. BE-10 floor_unit 추출

도로명주소와 지번주소의 상세 부분 모두에서:

```text
1층
2층 201호
B1
162C호
```

등을 추출.

확인 불가:

```text
null
```

`location_level = unverified`

도로명·지번 상세 위치가 충돌하거나 호수만으로 같은 자리를 확정할 수 없으면 `same_spot`으로 판정하지 않는다.

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

이력은 같은 건물·자리의 변화를 보여주기 위해 서비스가 지원하는 업종 전체(카페 및 음식점 4종)를 대상으로 한다. `category`는 진단 맥락이며 이력에서 타 지원 업종을 제거하는 필터로 사용하지 않는 방향으로 계약을 보완한다. 제외 업종까지 전 업종 이력을 제공하는 것은 범위에 포함하지 않는다. 위치 일치 수준은 별도로 표시한다.

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

`min_month`는 검증된 개업일과 원천 자료의 실제 조회 가능 범위로 산정한다. 이상 날짜나 원천의 임의 기본값으로 범위를 확장하지 않는다. 유효 표본이 없으면 날짜를 만들어내지 않고 명세에 정의할 자료 없음 응답으로 처리한다.

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

`market_change`는 공식 영역에서 제공한다. 적용 상권은 BE-23, 기준 분기 선택은 BE-24를 따르되 이 데이터 자체의 공표·검증 이력을 사용한다. 업종별 자료가 아닌 경우 업종 조건을 임의로 추가하지 않는다.

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
market_change
```

### Spot:ON 참고

```text
closure_rate_12m
survival_rate_1y
survival_rate_3y
competitor_count
day_night_ratio
```

## 상권 판정

- 좌표를 포함하는 세부 상권을 우선하고 관광특구는 별도 병기한다(R-13). 관광특구를 세부 상권 값에 중복 합산하지 않는다.
- 같은 우선순위의 상권이 중첩되어 하나로 확정되지 않으면 후보와 미확인 사유를 제공하고 임의로 선택하지 않는다.
- 상권 밖이면 상권 단위 공식 수치는 `value = null`, `status = no_data` 및 상권 밖 사유로 구분하고, 반경과 겹치는 상권 목록을 별도로 제공한다(R-14). 가까운 상권 수치로 대신하지 않는다.
- 반경 기반 참고 지표는 상권 밖이어도 유효 표본이 있으면 계산한다.
- 실제 반환 필드·사유 enum·경계 포함 판정은 API 명세와 원천 Polygon 기준에 맞춰 확정한다.

## 공식 창업위험도 안내

공식 수치 수집 경로가 확인되기 전에는 값을 추정하거나 화면을 스크래핑하지 않고 외부 안내 링크로 제공한다. `value = null`, `status = link_only`, 공식 링크와 상권명·업종명 복사 안내를 반환하는 보완안은 [be-contract-amendments.md](be-contract-amendments.md)에 기록한다. FE·API 명세 동기화 전에는 새 enum을 배포하지 않는다.

### 제외

```text
lq
```

---

# 15. BE-24 공식 폐업률

기준 분기는 다음과 같이 선택한다.

1. 현재 조회: 해당 데이터셋에서 공표 확인과 적재·검증이 완료된 최신 분기를 선택한다. 특정 상권·업종에 값이 없다는 이유로 더 오래된 분기를 찾지 않는다.
2. 과거 조회: 요청한 과거 기준 시점이 속한 분기를 선택하며 값이 없으면 `no_data`로 둔다.
3. 요청 기준일과 실제 적용 분기를 구분해 반환한다. 최신 공표 분기는 특정 연도·분기로 하드코딩하지 않는다.
4. 점포·반경 지표의 기준 시점을 공식 통계 분기에 맞춰 과거로 이동시키지 않는다. 지표별로 출처·분기를 표시한다.

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

선택 분기 자체를 정할 자료가 미확보이면 `pending`, 선택된 분기의 해당 상권·업종 값이 없으면 `no_data`다. 상권변화지표에도 같은 현재/과거 선택 원칙을 적용한다.

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

기본 모델은 `gemini-3.5-flash-lite`로 두되 환경변수로 변경 가능하게 유지한다. 무료 이용 가능 여부와 모델 수명은 AI 연계 시 공식 문서·프로젝트 계정에서 다시 확인한다. 모델명이 바뀌면 기존 해석 캐시를 재사용하지 않는다.

호출 제한은 요청 수·토큰 수·일일 한도를 고려한다. 공급자 429에는 제한된 횟수의 지수 백오프와 지터를 적용하고, 요청 시간 예산을 넘기거나 일일 한도 소진 시 `AI_UNAVAILABLE`로 종료한다. 지표 API는 AI 한도 초과와 독립적으로 동작한다.

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

## BE-T00 ETL 정제

- 원본 좌표·좌표계 보존 및 보완 결과 출처 추적
- 좌표 누락·이상치·보완 실패의 공간 집계 제외
- 1960년 이전·날짜 파싱 실패·개폐업일 역전과 조회 가능 범위
- 한시적 사업장 및 카페 키워드 후보 기본 집계 제외
- 건물명·영문 호수·산 지번·외 n필지 파싱

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
- 카페와 음식점이 같은 자리를 거쳐 간 이력 및 미지원 업종 제외

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
- 현재 조회 최신 검증 분기와 과거 조회 해당 분기 선택
- 선택 분기에 해당 업종 값이 없을 때 이전 분기 대체 금지
- 세부 상권·관광특구 중첩, 복수 세부 상권 후보
- 상권변화지표 공식 분류 및 창업위험도 링크 전용 응답
- 미확보 `pending`과 조건별 결측 `no_data` 구분

## BE-T08 AI

- 없는 숫자 생성
- 잘못된 출처
- pending 지표 오용
- 금지 표현
- 개인정보 포함
- malformed JSON
- 공급자 429·백오프 상한·일일 한도 소진 및 지표 API 독립 동작

---

# 22. GitHub Issue 작업 목록

실제로 GitHub Issues에는 아래처럼 올리면 된다.

| 순서 | Issue | 작업 |
|---:|---|---|
| 1 | BE-I01 | FastAPI 프로젝트 초기화 |
| 2 | BE-I02 | ruff·mypy·pytest·CI 설정 |
| 3 | BE-I03 | PostgreSQL/PostGIS 연결 |
| 4 | BE-I04 | 공통 API Response/Error |
| 5 | BE-I05 | stores DB 모델 |
| 6 | BE-I06 | 인허가 데이터 ETL |
| 7 | BE-I07 | 업종 매핑 |
| 8 | BE-I08 | building_key·floor_unit |
| 9 | BE-I09 | `/geocode` |
| 10 | BE-I10 | `/stores/history` |
| 11 | BE-I11 | `/stores/nearby` |
| 12 | BE-I12 | `/meta/data-range` |
| 13 | BE-I13 | `/stores/snapshot` |
| 14 | BE-I14 | 상권 Polygon ETL |
| 15 | BE-I15 | 점포-상권 ETL |
| 16 | BE-I16 | 추정매출 ETL |
| 17 | BE-I17 | 생활인구 ETL |
| 18 | BE-I18 | 가맹정보 ETL |
| 19 | BE-I19 | 상권변화지표 ETL |
| 20 | BE-I20 | `/market/activity` |
| 21 | BE-I21 | 공식 폐업률 |
| 22 | BE-I22 | 참고 폐업률·생존율 |
| 23 | BE-I23 | 주야간 인구비 |
| 24 | BE-I24 | `/risk` |
| 25 | BE-I25 | AI input builder |
| 26 | BE-I26 | LLM client |
| 27 | BE-I27 | AI verifier |
| 28 | BE-I28 | `/risk/interpret` |
| 29 | BE-I29 | `/support-links` |
| 30 | BE-I30 | 캐시·로그 |
| 31 | BE-I31 | 통합 테스트·Swagger 검증 |

> 본문 작업 번호는 `BE-00`~`BE-35`, Issue 작업 식별자는 `BE-I01`~`BE-I31`로 구분한다. GitHub 자체 Issue 번호(`#번호`)와도 별개다.

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
2. 최신 develop에서 작업별 기능 브랜치 생성
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

조건부 데이터 4종의 수치 제공 완료는 출처 확보·검증 후 별도로 판단한다. 미확보 시에는 `pending` 상태와 미확보 사유를 정확히 반환하는지 검증한다.

## PHASE 7 제출 준비 — 공공 GitLab 이관

- 대상 GitLab 프로젝트와 권한을 확인하고 코드·태그·필요 브랜치의 이관 범위를 확정한다.
- 현재 FE·BE 별도 저장소 구조를 유지해 이관한다. PDF의 모노레포 구성 제안으로 기존 저장소를 합치거나 폴더를 재배치하지 않는다.
- 비밀값과 원천 대용량 자료가 커밋 이력에도 없는지 검사하고, CI 변수는 별도로 등록한다.
- GitHub Actions 검사를 GitLab CI로 옮겨 같은 검사 결과를 확인한다. Issue·PR·문서는 Git 미러만으로 이관되지 않으므로 별도 이관 대상을 정한다.
- 대상 저장소에 기존 자료가 있으면 덮어쓰는 미러 푸시를 하지 않는다. 이관 실행 전 대상과 변경 범위를 확인한다.
- 이관 후 커밋·태그·브랜치와 새 환경의 빌드·실행을 검증하고 README의 제출 주소를 갱신한다.
