# BE-13 주변 점포 조회 API 설계

## 상태와 작업 범위

- 작성일: 2026-11-12
- 이슈: [#38 주변 점포 조회 API 공간·시점·필터 설계](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/38)
- 브랜치: `feat#38-nearby-api-design`, 대상: `develop`
- 기반: 작성 시작 시 develop `1e7a2a6`에서 분리했고, 검토 중 PR #37이 병합되어 최신 develop `2160e64`를 정상 merge로 반영했다. 기존 #36 작업 폴더는 유지한다.
- 선행: [BE PR #37](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/37)의 배치 출처·기간 계산·DB 요청 세션은 2026-11-12 develop 반영을 확인했다. nearby 구현은 이번 범위가 아니다.
- **이번 범위는 BE 설계·Claude 설계 MD 검토·Codex 점검·FE 변경 요청 보고서다. API 코드·migration·DB 데이터는 변경하지 않는다.** 구현은 선행 PR 반영 후 별도 작업으로 진행한다.
- FE 코드·설정·문서와 FE 이슈·PR은 직접 수정하거나 생성하지 않는다. [FE 요청 보고서](../fe-nearby-api-request.md)는 미구현 설계안의 검토 요청이며, FE 합의나 반영 완료를 뜻하지 않는다.

## 1. 근거와 현재 상태

로컬 `06_API명세서_SpotON_v1.2_최종.pdf` 3~4쪽 §2-2~2-4, 7쪽 §4-3과 현행 BE 작업계획을 대조했다. 원본의 분식·추가 카페 업종 범위보다 사용자 결정인 카페·음식점 4종을 우선한다. 원본 400 오류 대신 현행 BE의 422 INVALID_PARAM/CATEGORY_REQUIRED를 유지한다. 원본 PDF는 커밋하지 않는다.

공식 기술 근거:

- [PostGIS ST_DWithin](https://postgis.net/docs/ST_DWithin.html): geography 거리 인자는 미터이며 기본 spheroid 계산과 인덱스 후보 검색을 지원한다.
- [PostGIS ST_Distance](https://postgis.net/docs/ST_Distance.html): geography의 spheroid 거리와 geometry 좌표계 단위 거리를 구분한다.
- [PostgreSQL 17 표현식 인덱스](https://www.postgresql.org/docs/17/indexes-expressional.html): 조회 표현식에 맞춘 인덱스를 설계하고 쓰기 유지 비용을 고려한다.

실제 `spoton_dev`/`spoton_app`에 READ ONLY 트랜잭션으로 확인했다.

| 항목 | 확인 결과 |
|---|---|
| migration·전체 점포 | `0003`, 689,440건 |
| 지원 카페·음식점 | 카페 40,651건, 음식점 315,184건 |
| 지원 업종 geom NULL | 카페 623건, 음식점 20,282건. 시점·면적 등 적용 전 전체 수이며 반경 누락 수가 아님 |
| 원천 갱신 최대 날짜 | 일반음식점 2026-11-08, 휴게음식점 2026-11-07 |
| 브랜드·한시 여부 | 지원 업종에서 is_franchise/is_temporary 비null 각각 0건. null을 false로 추정하지 않음 |
| 공간 인덱스 | geometry GIST는 있고 geography 표현식 인덱스는 없음 |

최신 공공 API 전체 수집 여부나 CSV 관측 시점을 원천 갱신 최대 날짜와 동일시하지 않는다. 이번 확인에 원천 API 호출·새 키는 필요하지 않았다.

추가 확인: PostgreSQL 17.11 / PostGIS 3.7.0. 지원 업종에서 면적 0은 6,316건·음수는 0건, geom이 있으면서 coord_flag가 있는 행은 0건, open/other 상태이면서 close_date가 있는 행은 각각 0건이다. 실제 date_flag는 open_before_1960 56건이었다. 2026-11-12 사용자는 **0㎡를 정보 없음으로 처리**하도록 확정했다.

## 2. 요청 계약

```http
GET /api/stores/nearby
```

| 인자 | 필수·기본값 | 설계 기준 |
|---|---|---|
| lat, lng | 필수 | 유한 WGS84 숫자, lat -90..90 / lng -180..180. 중심점 생성은 lng,lat 순 |
| category | 필수 | cafe / restaurant |
| radius | 기본 500 | 정수 300 / 500 / 1000 미터 |
| sub_category | 선택 | 쉼표 구분, 중복 없는 허용 업종. 음식점 korean/chinese/japanese/western, 카페 cafe |
| as_of | 선택 | 정확한 YYYY-MM. 생략 시 검증된 데이터 기준일 사용 |
| area | 기본 all | all / lt33 / 33to66 / 66to99 / gte99 |
| franchise | 기본 all | all / franchise / independent |
| include_unknown_area | 기본 true | 면적 null 포함 여부 |
| include_unknown_franchise | 기본 true | 가맹 판단 null 포함 여부 |
| include_unknown | 선택, 기존 FE 호환 | 아래 호환 규칙에 따라 두 unknown 조건을 함께 설정 |

- category 미입력·빈 값·허용 업종 외에는 현행 geocode와 같은 `422 CATEGORY_REQUIRED`를 우선한다. 나머지 형식·범위·알 수 없는 인자·중복 query key는 `422 INVALID_PARAM`이다.
- bool 문자열은 true/false로 제한한다. radius=500.0, NaN/Infinity 좌표, cafe에 korean 세부 업종, 빈 쉼표 항목·중복 업종은 거절한다.
- 음식점 세부 업종 생략은 지원 4종, 카페 생략은 cafe다. 키즈/라이브/제외 업종을 추가하지 않는다.
- 기존 FE는 include_unknown 하나를 전송한다. 단독 사용 시 두 unknown 플래그에 같은 값을 적용한다. include_unknown과 신규 개별 플래그를 혼합하면 값이 같거나 기본값과 같아도 `422 INVALID_PARAM`으로 거절한다(“명시적으로 전송된 key의 존재”로 판정하고 값 비교로 허용하지 않는다). 이를 문서화된 호환 인자로 한정하고 다른 임의 인자는 받지 않는다.
- 세 unknown 인자가 모두 없으면 두 조건 모두 true다. 원본 v1.2 §2-2에는 신규 두 플래그가 각각 기본 true로 명시돼 있고 legacy include_unknown은 없다. legacy는 현행 FE의 단일 토글(면적·프랜차이즈 미확인 동시 포함)을 호환하기 위한 설계안이다. 원본 v1.2에 legacy 의미가 있다고 기록하지 않는다.
- 알 수 없는 인자·중복 key 거절은 FastAPI 기본 동작(추가 query 무시, 마지막 값 사용 등)과 다르므로 원시 query 목록을 검사하는 별도 의존성이 필요하다. 구현 시 geocode에 같은 정책이 있는지 확인하고 없으면 nearby에만 적용됨을 명시한다.
- 중심점의 서울 행정구역 판정은 기존 geocode 흐름에 따른다. nearby는 유효 좌표를 받아 서울 적재 점포만 조회한다. 행정구역 Polygon 없이 좌표만으로 서울 안이라고 재인증하거나 bbox를 행정 경계로 주장하지 않는다.
- 따라서 서울과 먼 유효 좌표도 오류 없이 markers=[]가 되고, §5의 excluded_no_coord는 중심점과 무관한 서울 비공간 수를 그대로 반환한다. 이 조합이 "주변에 점포 없음 + 서울 좌표 미확보 N건"으로 오해될 수 있음을 FE 요청 보고서에 남긴다. OUT_OF_SEOUL을 nearby에서 반환하려면 행정 경계 데이터가 필요하므로 이번 설계 범위가 아니다.

## 3. 비공간 필터와 시점

### 공통 대상

PR #37의 지원 업종 조건을 재사용한다. source는 general_restaurant/rest_cafe, deleted_at IS NULL, category_review_flag IS NOT TRUE, category/sub_category 지원 조합만 허용한다. 이력과 달리 nearby의 category는 실제 필터다.

한시 사업장은 기본 장기 입지 조회에서 `is_temporary IS TRUE`만 제외한다. null은 판단 미확인이며 false로 변경하지 않고 포함한다. 프랜차이즈·면적 null도 각각의 unknown 규칙에 따른다.

### 면적·프랜차이즈

| 면적 | 알려진 값 조건 |
|---|---|
| lt33 | 0 < area_m2 < 33 (0은 unknown) |
| 33to66 | 33 <= area_m2 < 66 |
| 66to99 | 66 <= area_m2 < 99 |
| gte99 | 99 <= area_m2 |
| all | 알려진 값 제한 없음 |

사용자 결정에 따라 **면적 0과 null은 정보 없음**이다. 알려진 면적은 양수이며 표의 범위를 적용한다. unknown 조건은 `(area_m2 IS NULL OR area_m2 = 0)`이고, include_unknown_area=true일 때만 알려진 범위에 OR로 포함한다. all에서도 false면 0/null을 제외한다. 응답은 저장된 0을 area_m2=null로 정규화하되 DB 원본은 바꾸지 않는다. 기존 ETL은 음수를 invalid로 정제하므로 이번 변경에 원천 재적재·DB 갱신을 추가하지 않는다.

기존 컬럼은 Numeric(12,2)다. 경계 상수 33/66/99는 명명된 Decimal 상수로 바인딩하고 float 변환 오차를 만들지 않는다.

- 면적은 DB 원본 0 보존·출력 null·unknown 필터 일치 세 가지를 함께 검사한다. 0㎡를 실제 33㎡ 미만으로 분류하지 않는다.
- 두 unknown 토글은 서로 독립이다. 면적 조건과 가맹 조건은 AND로 결합하고, 각 조건 안에서만 알려진 값 조건 OR 해당 unknown 조건을 적용한다. 면적 unknown은 0/null, 가맹 unknown은 is_franchise NULL이다.

franchise/independent는 is_franchise true/false와 일치한다. include_unknown_franchise=true면 선택 분류에 null도 포함한다. all에서도 false면 null은 제외한다. 필터에 포함된 미확인 점포의 응답 franchise는 계속 unknown이다. 현재 DB는 모두 미확인이므로 franchise 필터 결과를 확인된 가맹점 목록이라고 표시하지 않는다.

- §1 기재대로 지원 업종의 is_franchise가 전부 null이면 기본값(true)에서 franchise=franchise/independent/all의 결과가 모두 같고, include_unknown_franchise=false면 어떤 분류든 0건이 된다. 이때 0건 메시지 `조건에 맞는 점포가 없어요`만으로는 "가맹 판단 데이터 미확보"를 구분할 수 없다. meta에 가맹 판단 데이터 상태(예: 브랜드 매핑 미적용·pending)를 표시하는 안을 남은 결정으로 두고 FE 요청 보고서에 포함한다. 새 필드 이름은 계약 합의 전 확정하지 않는다.

### 기준일 T

원본 §2-2 규칙을 따른다. PR #37의 현재 점포에 연결된 검증 배치로 D=data_updated_at을 결정한다. 오늘이나 DB updated_at으로 대체하지 않는다. 관련 점포 배치의 출처·원천 갱신일을 확인할 수 없어 재현 가능한 D를 정할 수 없으면 INTERNAL_ERROR로 중단하고 0건 정상 결과로 감추지 않는다.

**D의 범위 — 원본과 PR #37을 유지한다.** API v1.2 3쪽은 점포 원천 DAT_UPDT_PNT 최대 날짜를 명시한다. D는 반경·요청 category와 독립적으로, 현재 지원 업종 점포에 연결된 검증 배치들의 전역 최대 날짜다. Claude가 제안한 원천 최소일로의 변경은 원본·PR #37과 달라 채택하지 않는다. 원천별 최대 갱신일 차이는 배치 상세로 보여 주며, 갱신 최대일을 원천 전체의 현황 관측 완료일로 주장하지 않는다.

**배치 준비 상태.** PR #37은 점포 upsert와 배치 출처 삽입을 같은 트랜잭션으로 commit하므로 별도 완료 상태 컬럼 없이도 보이는 배치 행은 commit된 출처다. 진행 중·실패한 트랜잭션의 배치는 보이지 않는다. 날짜/출처가 미확인인 배치나 현재 지원 점포의 출처 연결 누락이 있으면 준비 상태 오류로 처리한다. 여러 정상 배치 ID가 존재한다는 이유만으로 오류로 보지 않고 결과와 D에 사용한 ID를 버전에 포함한다. 단일 요청의 일관성은 §7의 REPEATABLE READ 스냅샷으로 보장한다.

**데이터 없음.** 점포·배치가 전혀 없는 DB(적재 전)는 D를 정할 수 없으므로 위 원칙대로 500 INTERNAL_ERROR다. 이는 "조건에 맞는 점포 없음"(200, 0건)과 구분된다. 현행 오류 코드에 "데이터 미준비" 전용 코드가 없어 INTERNAL_ERROR를 쓰는 것이며, 새 코드 도입은 9절 계약 동기화 없이 하지 않는다.

- as_of 생략: T=D.
- as_of가 D와 같은 월: T=D.
- 이전 월: T=그 월 말일.
- D 이후 월이나 검증된 조회 가능 최소 월 이전: `422 AS_OF_OUT_OF_RANGE`.
- 형식이 잘못된 월: `422 INVALID_PARAM`.

최소 월은 지원 업종·선택 category/sub_category·기본 제외 기준에서 **시점 판단에 사용할 수 있는 유효 날짜**로 정한다. 반경·면적·프랜차이즈 선택으로 달력 범위를 바꾸지 않는다. 이 내부 규칙은 후속 BE-14 data-range와 공유하도록 설계하며, 이번 범위에 data-range 엔드포인트 구현은 포함하지 않는다. 유효 표본이 없고 D만 확인된 경우 기본 현재 조회는 T=D와 빈 결과가 가능하지만, 과거 조회 가능 범위를 만들어내지 않는다.

- 최소 월 = 위 cohort에서 §3 날짜 품질 규칙을 통과한 open_date의 최솟값이 속한 월. 그 월의 as_of는 허용(T=월말 또는 D와 같은 월이면 D)하고 그 이전 월만 범위 밖이다.
- 유효 표본이 없을 때: as_of 생략 또는 D와 같은 월이면 T=D로 200·0건, 그 외 모든 월은 `422 AS_OF_OUT_OF_RANGE`다. 최소 월을 D의 월로 대체하거나 원천 기본값으로 확장하지 않는다.
- 원본 API v1.2 8쪽 §4-5를 재확인했다. data-range는 category 필수·sub_category 선택이며 지정 시 해당 세부 업종으로 범위를 계산한다. 작업계획 요약에 입력 인자가 생략됐다는 이유로 원본에 없다고 보지 않는다. 원본대로 category/sub_category 최소 월을 공유하고, 후속 BE-14 연결 시 FE도 같은 업종 조건으로 범위를 요청하도록 보고한다.
- 과거 as_of의 T가 D보다 늦을 수 없으므로 "이전 월"은 D의 월보다 앞선 월만 의미한다.

현재 D=2026-11-08일 때 2026-10은 10-31, 2026-11은 11-08, 2026-12는 범위 밖이다.

### 시점 영업 판정

기본은 `open_date <= T AND (close_date IS NULL OR close_date > T)`이며 폐업일 당일은 제외한다.

- 개업일 누락·파싱 오류·1960년 이전·배치 기준 미래 개업, 잘못된 폐업일·역전 날짜는 시점 대상에서 제외한다. 오류 close_date를 단순 null로 바꿔 계속 영업 중으로 간주하지 않는다.
- 현재 closed인데 close_date가 없으면 T의 영업 여부를 확정할 수 없어 제외한다. 임의 폐업일을 만들지 않는다.
- 과거 T 이후 폐업한 점포는 포함하고 current_status=closed로 반환한다. 현재 status=open만 SQL 조건에 넣지 않는다.
- 날짜가 유효한 휴업 등 기타 상태는 원본 날짜 조건으로 판단하고 현재 상태를 other로 표시한다. 이는 현재 실제 영업 중이라는 확정이 아니다. 날짜가 불확실한 경우는 위 제외 규칙이 우선한다.
- date_flag는 기존 세미콜론 구분을 해석한다. 기존 ETL의 open_date_invalid/close_date_invalid/open_before_1960/open_date_future/close_date_future/close_before_open을 날짜별로 검사하고 원본 날짜값과 함께 판단한다. 새로운 알 수 없는 날짜 플래그는 조용히 정상 통과시키지 않고 검토 대상으로 둔다.
- 미래 판정은 기존 배치 검증 플래그와 전역 D를 기준으로 한다. open_date > D 또는 close_date > D로 미래가 명확하면 시점 대상에서 제외한다.
- 현재 status=open인데 close_date가 존재하면 불일치로 제외한다. other+유효 close_date는 일괄 제외하지 않는다. 원본의 날짜 구간 조건으로 T를 판단하고 현재 상태 other·기간 no_data로 반환한다. Claude의 open/other 일괄 제외 제안은 기존 날짜 조건과 충돌해 채택하지 않는다.
- **폐업일 누락 closed의 영향:** 과거 T 조회에서 이 점포들은 실제로는 영업 중이었을 수 있어 과소 집계된다. 날짜 품질로 제외된 수는 excluded_no_coord(좌표 사유)와 섞지 않는다. 날짜 사유 제외 수를 meta에 따로 제공할지는 남은 결정이며, 제공하더라도 count·excluded_no_coord와 합산하지 않는다.
- other 판정: current_status는 T가 아닌 **최신 데이터(D) 기준 상태**다. 과거 T에서 영업 판정된 점포가 현재 휴업이면 other, 현재 폐업이면 closed로 표시한다. 같은 마커의 "T 시점 영업"과 "현재 상태"는 다른 시점의 사실이다.

## 4. 거리·인덱스·반경 경계

geometry(POINT,4326)에 미터 반경 500을 직접 전달하지 않는다. `geom::geography`와 같은 타입의 중심점으로 WGS84 spheroid 거리를 계산한다.

### 실제 함수 경계 검사

공개 좌표에 ST_Project로 동쪽 499/500/501m 점을 만들었다. 이 환경에서 500m 점은 ST_Distance=500.0이지만 ST_DWithin(...,500,true)=false였다. 입력 거리 라벨만으로 두 함수가 경계에서 동일하게 판정한다고 가정하면 누락된다.

공개 중심점 하나에서 반경 300/500/1000, 방향 24개, 오프셋 -1/0/+0.001/+1m의 288개 함수를 READ ONLY로 확인했다. ST_Distance<=radius인데 기본 ST_DWithin에서 빠진 경우 49개, 후보 검색에 0.01m를 더하면 누락 0개였다. 확장 후보 중 최종 거리 조건에서 제거할 경우는 72개였다. **이는 공간 함수 검사이며 nearby API 구현·통합 테스트가 아니다.**

Claude 검토로 구분한 점(Codex 기재 결과를 근거로 한 해석이며 Claude가 재실행하지 않음):

- **두 종류의 경계 문제를 분리한다.** (a) 후보 누락: 계약상 포함(ST_Distance ≤ r)인데 ST_DWithin(r)이 false — 이것이 결과 누락을 만드는 문제이고 0.01m 여유가 해결 대상이다. (b) 원거리 후보: 여유 때문에 ST_Distance > r인 점이 후보로 들어오는 것 — 최종 ST_Distance 조건이 제거하므로 결과 오류가 아니라 비용 문제다. "72개 제거"는 (b)이며 정상 동작이다.
- **복수 중심점으로 범위를 넓혔다.** PostgreSQL 17.11/PostGIS 3.7.0에서 서울권 합성 중심점 5개·1,440개 함수를 추가 확인했고 0.01m 확장 후보 누락은 0건이었다. 이 결과로 0.01m를 현재 설계값으로 유지한다. 모든 좌표·향후 버전의 수학적 보장을 주장하지 않으며 구현 시 고정된 PostGIS/PROJ 버전의 경계 회귀를 유지한다. 여유는 최종 계약 반경이 아닌 후보 안전값이다.
- **표시 자릿수만으로 판단하지 않는다.** Codex 검사에서는 SQL의 `ST_Distance(...)<=500` 자체가 true이고 ST_DWithin(...,500)이 false임을 함께 확인했다. 최종 조건은 측정 float값 기준이며 표시용 반올림은 이후에 수행한다.
- 버전 업그레이드로 ST_DWithin/ST_Distance 내부 구현이 바뀔 수 있으므로 이 경계 검사는 회귀 테스트로 유지한다(§8).

### 채택할 검색식

명명된 `SPATIAL_PREFILTER_MARGIN_M=0.01`은 후보 검색에만 적용한다. 최종 반경은 바꾸지 않는다.

```sql
-- 입력은 모두 바인딩하고 center는 POINT(lng lat), SRID 4326으로 만든다.
WHERE geom IS NOT NULL
  AND ST_DWithin(geom::geography, :center_geography,
                 :radius_m + :prefilter_margin_m, true)
  AND ST_Distance(geom::geography, :center_geography, true) <= :radius_m
```

- 최종 판정은 표시용 반올림 전의 ST_Distance 값으로 한다. UI에 표시한 500.0만 보고 500.001m를 포함하지 않는다.
- 이중 정밀도 함수의 최종 측정값을 계약 기준으로 삼는다. ST_Project 입력값과 측정값이 항상 수학적으로 동일하다고 가정하지 않는다. 모든 방향에서 최종 거리 조건과 결과의 일치를 확인한다.
- 응답 distance_m은 최종 판정 뒤 소수 첫째 자리로 표시용 반올림한다. 내부 정렬은 반올림 전 거리 → source → license_no → id다. 단위는 m다.
- 반올림 방식은 명시한다: Python `round()`(은행가 반올림)나 float 연산이 아니라 `Decimal.quantize(Decimal("0.1"), ROUND_HALF_UP)` 또는 DB `round(numeric, 1)` 중 하나로 고정하고 테스트한다. 최종 거리 ≤ r이면 반올림 결과도 ≤ r.0이므로 표시값이 반경을 넘지 않는다(예: 499.96 → 500.0은 정상, 500.001은 최종 조건에서 이미 제외).
- 정렬은 SQL ORDER BY의 반올림 전 거리 우선이다. 표시 거리만 같고 실제 거리가 다르면 실제 거리 순서를 유지한다. 실제 거리까지 같을 때 source → license_no → id로 결정한다. id는 응답에 노출하지 않는다.
- 응답 lat/lng는 저장된 geom 좌표를 반올림하지 않고 그대로 반환한다(거리 재계산 검증과 일치시키기 위함). 표시 자릿수는 FE가 결정한다.
- ST_DWithin과 ST_Distance는 둘 다 geography·spheroid(`true`)로 호출한다. 한쪽만 sphere(`false`)·geometry로 바뀌면 후보와 최종 판정의 기준이 달라지므로 같은 상수/헬퍼에서 생성한다.

기존 geometry 인덱스만으로 geography cast가 인덱스를 사용할 것이라고 가정하지 않는다. 향후 구현 시 동일한 표현식의 GIST 인덱스를 추가한다.

실제 READ ONLY `EXPLAIN (FORMAT JSON)`에서는 기존 ix_stores_geom_gist가 보였지만 Index Cond는 `(geom IS NOT NULL)`뿐이고 추정 후보는 652,107행이었다. 이는 반경 검색 인덱스 활용의 증거가 아니다. 새 인덱스 검증은 이름 존재뿐 아니라 반경 bounding 조건·실제 후보 수·BUFFERS를 함께 확인한다. 이번에는 계획만 확인했으며 이 질의의 ANALYZE 실행 시간은 측정하지 않았다.

```sql
CREATE INDEX ix_stores_geography_gist
ON stores USING gist ((geom::geography))
WHERE geom IS NOT NULL;
```

현재 PR #37 migration head=0003을 전제로 후속 migration 0004를 계획한다. 실제 번호는 구현 시 최신 head를 확인한다. SQLAlchemy 모델의 인덱스 표현식과 질의 cast를 동일하게 컴파일하고, 독립된 인덱스 정의 검사·EXPLAIN ANALYZE BUFFERS·관리 테이블 메타데이터 비교로 확인한다. 작은 fixture에서 Seq Scan이 선택되는 것만으로 실패시키지 않고 대표 분포/규모에서 인덱스 후보 검색이 가능한지 검증한다. 이 설계 PR에서 인덱스를 생성하지 않는다.

현재 ETL runner가 migration 0003을 검사하므로 새 head 적용 시 runner의 준비 상태 검사·관련 단위 검사도 함께 갱신해야 한다. 기존 migration 단계별 왕복 검사는 유지하고, head 검사와 표현식 인덱스 기대값은 새 스키마에 맞춰 독립적으로 검증한다.

기존 geom·ETL 원본·점포 행을 다시 쓰거나 재적재하지 않는다. 일반 인덱스 생성의 쓰기 잠금과 유지 비용은 구현 시 기록한다. downgrade는 새 인덱스만 제거하고 점포·PostGIS 확장을 삭제하지 않는다.

인덱스·cast 일치에 대한 검토 보완:

- **표현식 동일성:** planner는 인덱스 표현식과 질의 표현식이 같은 타입으로 정규화될 때만 인덱스를 쓴다. `geom::geography`와 `CAST(geom AS geography)`는 같지만, GeoAlchemy2 `Geography(geometry_type="POINT", srid=4326)`로 cast하면 `geography(Point,4326)` typmod가 붙어 인덱스 표현식(`geography`)과 달라질 수 있다. 모델의 인덱스 정의와 질의 cast는 **같은 헬퍼 하나**에서 생성하고, 컴파일된 SQL 문자열과 `pg_indexes.indexdef`를 비교하는 테스트를 둔다.
- **부분 인덱스 조건:** `WHERE geom IS NOT NULL` 부분 인덱스는 질의에 같은 조건이 있어야 사용된다. 위 검색식은 이를 포함하며, 리팩터링 시 지워지지 않도록 테스트로 고정한다.
- **중심점 타입:** `:center_geography`는 `ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography`로 만들며 lng,lat 순서를 바꾸지 않는다. 중심점을 geometry로 넘겨 암묵 변환에 맡기지 않는다.
- **immutable 확인:** 표현식 인덱스에는 IMMUTABLE 함수만 쓸 수 있다. geometry→geography cast가 대상 PostGIS 버전에서 인덱스 생성 가능한지 일회용 PostGIS에서 먼저 확인한다.
- **통계:** 인덱스 생성 후 `ANALYZE stores`를 수행해야 표현식 통계가 반영된다. migration에 포함할지, 운영 절차로 둘지는 구현 시 정한다.
- **잠금:** Alembic 기본 트랜잭션 안에서는 `CREATE INDEX CONCURRENTLY`를 쓸 수 없다. 개발 DB 규모(약 69만 행)에서 일반 생성의 쓰기 잠금 시간을 기록하고, CONCURRENTLY가 필요하면 autocommit 블록을 별도로 설계한다. 적재 실행 중에는 migration을 실행하지 않는다.
- **권한:** 작업계획상 spoton_app은 superuser가 아니다. stores 소유권이 migration 실행 계정에 있는지는 기존 migration 실행 방식에 따르며, 구현 시 확인할 선행 조건이다(새 승인 절차를 만들지 않는다).
- 실행계획 확인은 개발 DB에서 READ ONLY 트랜잭션 안의 `EXPLAIN (ANALYZE, BUFFERS)` SELECT만 사용한다. 인덱스 적용 전·후의 계획을 같은 중심점·반경 세트로 기록한다.

## 5. 좌표 누락 수의 의미

geom이 없으면 어느 반경 안에 있는지 알 수 없다. 따라서 서울 전체 좌표 누락 건수를 "이 반경에서 제외된 점포"라고 표시할 수 없다.

설계안은 기존 `excluded_no_coord: int`를 유지하고 다음 의미를 명시하는 것이다.

- 범위: **서울 데이터 전체에서 같은 업종·세부 업종·시점·면적·프랜차이즈·기본 제외 조건을 만족하지만 geom이 없는 점포 수**.
- lat/lng/radius 공간 조건은 적용하지 않는다. 주소나 다른 점포의 위치로 반경 소속을 추정하지 않는다.
- `meta.excluded_no_coord_scope="seoul_nonspatial_cohort"`로 범위를 제공한다. FE는 서울 전체 조건 일치 중 좌표 미확보라고 표시하거나 반경 수치와 분리한다. FE 검토 요청 사항이다.
- 같은 비공간 조건에서 radius만 바꾸면 이 수는 변하지 않는다. 마커 수 count와 합산하거나 지역 누락률 분모로 사용하지 않는다.
- lat/lng를 바꿔도 변하지 않는다. 같은 as_of·필터로 중심점만 이동한 두 요청의 값이 같아야 한다.
- 비공간 조건은 마커 쿼리와 **같은 cohort 함수**(지원 업종·삭제/검토/한시 제외·T 영업 판정·날짜 품질·면적·가맹 unknown 토글)를 쓰고, 마지막에 공간 조건 대신 `geom IS NULL`만 다르게 붙인다. 별도 SQL로 다시 쓰면 두 수의 기준이 어긋난다.
- "서울"은 행정 경계 판정이 아니라 **적재된 서울 25개 구 점포 테이블 범위**를 뜻한다. meta 범위명도 이 의미로 FE 보고서에 설명한다.
- 추가 READ ONLY 확인에서 지원 업종의 geom 존재·coord_flag 비null은 0건이었다. 현재 누락 수는 원본처럼 geom IS NULL로 한정한다. 추후 데이터 정제 계약에서 신뢰 불가 geom이 확인되면 이를 기존 누락 수에 임의 합치지 않고 별도로 정제·범위를 검토한다.
- 서울 전체 cohort 집계는 요청마다 지원 업종 수십만 행을 훑을 수 있다. EXPLAIN으로 비용을 확인하고, 느리면 `(category, status)` 등 기존 인덱스 활용 여부를 기록한다. 결과 캐시는 BE-34 범위이므로 이번 설계에서 도입하지 않는다.

계약이 반경 내 누락 수를 반드시 요구한다면 이 정의로 구현하지 않고 위치를 확인할 원천·표현 계약을 먼저 합의해야 한다. 현재 원본은 집계 공간 범위를 명시하지 않아 본 문서와 FE 보고서의 검토 항목으로 남긴다.

## 6. 응답 계약 설계안

공통 외피는 현행 `{data,meta,error}`다. 성공 200, 오류 meta={}를 유지한다.

| data 필드 | 타입·의미 |
|---|---|
| center | 요청 lat/lng 숫자 |
| radius_m | 300/500/1000 |
| as_of | 실제 T, YYYY-MM-DD |
| count | markers.length와 같은 정수 |
| excluded_no_coord | §5의 서울 비공간 조건 기준 수 |
| markers | 전체 조건 일치 마커, 임의 LIMIT로 자르지 않음 |
| message | 0건은 `조건에 맞는 점포가 없어요`, 그 외 null |

| marker 필드 | 타입·의미 |
|---|---|
| source, license_no | 원천+관리번호 복합 식별자. 서로 다른 원천을 병합하지 않음 |
| name | string 또는 null |
| sub_category | cafe/korean/chinese/japanese/western |
| lat, lng | 유효 geom의 ST_Y/ST_X, 숫자 |
| distance_m | 표시용 거리, 0 이상의 숫자 |
| open_date | 유효 날짜. 시점 필터에 필요하므로 성공 마커에서는 null 아님 |
| close_date | 유효 날짜 또는 null |
| operating_months | 0 이상의 정수 또는 null |
| operating_period_status/reason | PR #37과 같은 fact/no_data 및 7개 사유 코드/null |
| current_status | 최신 데이터의 open/closed/other |
| franchise | franchise/independent/unknown |
| area_m2 | 신고 면적 숫자 또는 null |

목록의 operating_months는 원본 §2-4에 따라 **현재 데이터 기준 전체 기간**이다. 과거 T는 포함 점포를 고르는 기준이며, 영업 중 종료점은 D·폐업 종료점은 유효 close_date다. 선택 과거 시점까지의 생존 기간으로 FE에서 다시 계산하지 않는다. 이 차이는 meta에 `operating_period_basis="latest_data"`로 표시하는 안이다.

검토 보완:

- 같은 마커에서 `as_of`(T)·`current_status`(D 기준)·`operating_months`(D 또는 close_date 기준)가 서로 다른 시점을 가리킨다. 예: T=2024-06, 2025-03 폐업 점포는 포함되고 current_status=closed, operating_months는 개업~2025-03이다. 이 예시를 FE 보고서에 포함한다.
- operating_months와 operating_period_status/reason은 PR #37 기간 계산 함수를 재사용한다. 확인한 현재 구현에서 other는 no_data+other_status이며 새 사유 코드를 만들지 않는다. 선행 PR 반영 후 인터페이스가 달라졌는지는 다시 확인한다.
- 영업 중 기간 종료점은 PR #37과 동일한 전역 D다. 요청 T가 과거라고 종료점을 T나 원천 최소일로 바꾸지 않는다.
- nullable 정리: name·close_date·operating_months·operating_period_reason·area_m2는 null 가능, source·license_no·sub_category·lat·lng·distance_m·open_date·current_status·franchise·operating_period_status는 null 불가. 스키마에서 이 구분을 강제한다.
- FE의 마커 key는 `source + license_no` 복합값이어야 한다. license_no 단독 key를 쓰면 원천 간 같은 관리번호가 충돌한다.

meta에는 R5/R6, as_of=T, space=radius_{radius}m, denominator=count, data_updated_at=D, 실제 확인된 collected_at 또는 null, is_demo=false, 결과·기준일 산정에 사용한 배치 IDs/매핑·규칙 버전과 §5 범위를 제공한다. 수집 완료일을 모르면 기존처럼 사유를 남기고 오늘·검증일을 채우지 않는다.

nearby의 규칙 버전은 공간·시점·0㎡ 미확인 정책을 식별해야 한다. history의 규칙 버전 문자열을 그대로 복사해 다른 정책을 같은 버전으로 표시하지 않는다.

- meta 필드 구조는 BE-04 공통 meta(DataVersion 등)가 미완료이므로 이 표는 설계안이다. 작업계획상 "필드 구조를 임의로 만들지 않는다"에 따라 excluded_no_coord_scope·operating_period_basis·원천별 기준일·가맹 데이터 상태 등 신규 meta 키는 FE 보고서의 검토 항목이며 확정 계약이 아니다.
- R5는 일반음식점, R6는 휴게음식점 원천이며 현행 BE/FE 출처 표와 일치시킨다.

## 7. 구현 계층·운영 계획

- develop에 반영된 PR #37 기반에서 지원 업종·배치 기준일·기간 계산의 공통 분리를 검토한다. history의 기존 동작을 변경하지 않는 회귀 검사가 필요하다.
- `app/schemas/nearby.py`: 요청·응답·enum·출력 일관성. `app/services/nearby.py`: 공통 cohort·시점·공간 SQL·마커 변환. `app/routers/stores.py`: 검증·응답·no-store.
- 배치 조회·최소 월·마커·좌표 누락 수는 같은 요청의 READ ONLY REPEATABLE READ 트랜잭션에서 처리한다. 서로 다른 cohort 구현으로 count가 어긋나지 않게 공통 조건을 재사용한다.
- 세션 connection 취득 시 REPEATABLE READ 실행 옵션을 적용하고 첫 데이터 조회 전에 SET TRANSACTION READ ONLY를 설정한다. autobegin 자체가 문제가 아니라 이미 조회한 뒤 격리 수준을 바꾸는 것이 문제다. 확인한 PR #37 헬퍼의 기존 설정 순서를 재사용하고 필요한 공통화만 history 회귀 검사와 함께 진행한다.
- 재사용 계층 권고: 지원 업종 cohort·검증 배치 전역 D·시점 판정·날짜 품질·기간 계산을 공통 함수/SQL 표현식으로 둔다. 단, history는 불완전한 날짜의 이력도 보존하므로 nearby의 날짜 제외 필터를 그대로 적용하지 않는다. API별 포함 정책을 분리하고 공유할 계산만 재사용한다. history의 category 비필터 의미도 유지한다.
- 단일 요청에서 마커 쿼리와 좌표 미확보 count, D·최소 월 조회가 최소 3~4회 왕복이 된다. statement timeout은 쿼리별이므로 요청 전체 소요 시간을 로그(경로·상태·소요 시간만)로 남겨 실측한다.
- DB 엔진 수명주기·문장 timeout은 PR #37 기반을 사용한다. DB 실패·timeout은 기존 500 INTERNAL_ERROR, 원시 예외·SQL·접속정보·좌표는 노출하지 않는다. 원본 504/전체 3초 SLA 일괄 도입은 별도 범위다.
- 요청마다 원천 API·geocode·LLM을 호출하거나 좌표 보완·쓰기·재적재를 하지 않는다. 응답은 Cache-Control:no-store, access log에 query 문자열을 남기지 않는다.
- BE-14 data-range, BE-15 snapshot, 반경 집계 지표·AI, 브랜드 매핑·새 데이터 수집은 제외한다.

## 8. 구현 후 검증 계획

| 구분 | 필수 사례 |
|---|---|
| 입력 | 누락/잘못된 category, NaN/Inf/범위 밖 좌표, radius 허용값, 중복 key, 잘못된 월·sub_category |
| 호환 | include_unknown 단독 true/false → 두 조건, 신규 개별 값 4조합, 혼합 전송 거절 |
| 공간 | 499m 포함·측정 500m 포함·501m 제외, 500.001m 표시 반올림의 잘못된 포함 방지, 반경 300/500/1000 |
| 공간 정밀도 | 24방향의 측정값/최종 조건 동일성, prefilter 여유로 생긴 후보의 최종 제거 |
| 시점 | 개업일 전/당일, 폐업일 직전/당일/이후, 월말·윤년·최신월 기준일·미래월·최소월 경계 |
| 날짜 품질 | 미래·1960년 이전·오류·역전·폐업일 없는 closed 제외, 유효 other의 최신 상태/기간 미산정 |
| 필터 | 업종·세부 업종 조합, 면적 33/66/99 경계, 가맹 true/false/null, unknown 독립 토글·all |
| 면적 0 사용자 결정 | 원본 0 보존·출력 null, lt33+unknown=false에서 제외, true에서 미확인으로 포함, all+false에서도 0/null 제외 |
| cohort | 삭제·검토/미지원·확인된 한시 사업장 제외, 한시 미확인 포함, 과거 영업/현재 폐업 포함 |
| 누락 좌표 | 공간 필터 없이 동일 비공간 조건으로 집계, 반경 변경 불변, 서울 범위 meta 일치 |
| 응답 | 원천 간 같은 관리번호 2건, name/기간 결측, 거리 정렬 안정성, count=markers.length, 0건 메시지 |
| DB | readonly/예외 후 세션 정리, 동시 배치 갱신 시 스냅샷 일관성, migration 왕복·새 인덱스·기존 history 회귀 |
| 경계 회귀(검토 추가) | 서울 복수 중심점×반경 3종×24방향×오프셋의 "ST_Distance≤r인데 결과 누락 0건" 검사, 측정값 전체 정밀도 기록, PostGIS 버전 기록 |
| 인덱스 일치(검토 추가) | 모델 인덱스 정의와 질의 cast의 컴파일 SQL 비교, `pg_indexes.indexdef` 확인, 부분 인덱스 조건 유지, 대표 규모에서 EXPLAIN 인덱스 사용 |
| 반올림(검토 추가) | 이진수로 정확한 x.25·x.75의 ROUND_HALF_UP(0.05처럼 float로 정확하지 않은 값은 경계 테스트로 쓰지 않음), 499.96→500.0 포함, 표시 동일 거리의 정렬 안정성, 0m → 0.0 |
| 기준일(검토 추가) | 원천별 D가 다를 때 선택 규칙, 미완료/부분 배치 무시, 점포·배치 0건 시 500 INTERNAL_ERROR와 정상 0건(200)의 구분, 유효 표본 없음 시 D 월만 허용 |
| 날짜 불일치(검토 추가) | open+close_date 제외, 유효 other+close_date의 과거 포함, close_date > D, 알 수 없는 date_flag 검토 |
| 호환(검토 추가) | include_unknown과 개별 플래그를 같은 값으로 함께 보내도 422, 세 인자 모두 없음 → 둘 다 true |
| 누락 좌표(검토 추가) | 중심점 이동 불변, geom은 있으나 신뢰 불가 좌표 처리 결정 반영 |
| 가맹 미확보(검토 추가) | 전부 null 상태에서 franchise=franchise+unknown=false → 0건과 meta 상태 표시(결정 시) |

실제 공간·migration 검사는 개발 DB가 아닌 일회용 PostGIS에서 수행한다. 의미 있는 합성 경계·코호트와 원자료 표본 20건을 별도로 대조한다. 실제 개발 DB는 읽기 전용 표본·EXPLAIN·거리 재계산으로 확인한다. 신규 인덱스 적용 시 기존 행 내용 해시/건수 보존을 확인하고 파괴적 fixture는 실행하지 않는다. ruff/mypy/pytest·CI·OpenAPI를 실제 구현 시 검사한다.

예정 커밋은 입력/필터·시점 공통 함수와 테스트 → 공간 인덱스 migration·모델·실제 SQL 검사 → 서비스/라우터·응답/오류 검사 → 실데이터 검증·최종 FE 요청 갱신 순서다. 이번 설계 PR에서는 이 구현 커밋을 만들지 않는다.

## 9. 검토와 보류

- Codex: 기존 코드·원본 API·FE 요청 경로를 대조했다. 실제 DB metadata와 공간 함수 288개는 읽기 전용으로만 확인했다.
- Claude Code: 2026-11-12 이 MD 한 파일만 Read/Edit로 검토·직접 수정했다. 원본 PDF·코드·DB·PR #37은 직접 확인하지 않았고, 원본 계약·실 DB 사실은 MD 기재 내용만 근거로 했다. 문서 검토이며 API·SQL·migration 테스트를 실행한 것이 아니다. Codex가 실제 diff를 점검한다.
- FE 확인 대기: 좌표 누락 수의 서울 범위 표시, 신규 독립 unknown UI와 호환 인자, 마커 nullable/복합 식별자, 과거 필터와 현재 운영 기간 표기.
- 구현 선행: PR #37 반영은 확인했고, 실제 구현 시 develop head 재확인과 FE 영향 검토가 필요하다. 검토 대기를 FE 합의 완료로 표시하지 않는다.

### Claude 검토 이유와 수정 내역

| 영역 | 발견한 문제 | 수정 |
|---|---|---|
| 거리·인덱스 cast | 인덱스 표현식과 GeoAlchemy2 cast의 typmod 차이, 부분 인덱스 조건, 중심점 타입, immutable·ANALYZE·잠금·권한이 빠짐 | §4 "인덱스·cast 일치" 보완, §8 인덱스 일치 검사 |
| ST_DWithin 경계 | 후보 누락(결과 오류)과 여유로 인한 원거리 후보(비용)를 구분하지 않음. 0.01m 근거가 중심점 1개뿐. 500.0 표기의 정밀도 불확실 | §4 해석 분리, 복수 중심점·버전 기록·전체 정밀도 재검사, 회귀화 |
| 정밀도·정렬 | 반올림 방식(은행가/half-up) 미지정, 좌표 반올림 여부·spheroid 인자 일치 미기재 | §4 반올림·정렬·좌표·헬퍼 규칙 |
| 기준일 D | 원천별 날짜 차이·배치 가시성·데이터 준비 상태의 설명 보완 필요 | 원본 재대조로 전역 최대 D 유지, 트랜잭션 완료 가시성 명시 |
| 최소 월 | 검토 단계에서 원본 data-range 입력을 직접 확인하지 못함, 표본 없음 시 범위 모호 | 원본 category 필수·sub_category 선택 확인 및 최소 월 정의 정리 |
| 날짜·other | 상태·close_date 불일치, close_date > D, 알 수 없는 date_flag, 폐업일 누락의 과소 집계, current_status 시점 미기재 | §3 시점 판정 보완 |
| 면적·가맹 | 토글 결합 방식 예시 없음, 0 이하 면적, 가맹 전부 null일 때 0건 메시지 오해, legacy 혼합 판정 방식(값 vs key)·원본 의미 미확인 | §2·§3 보완 |
| 좌표 미확보 수 | 중심점 불변성, cohort 함수 공유, "서울"의 의미, geom 있으나 신뢰 불가 좌표, 집계 비용 | §5 보완 |
| 응답 | T·현재 상태·기간의 시점 차이 예시, nullable 구분, FE 복합 key, 신규 meta 키의 비확정성 | §6 보완 |
| 계층·트랜잭션 | SET TRANSACTION 순서, 공통 함수 분리 대상, 요청 전체 소요 시간 | §7 보완 |

### 남은 결정 (사용자 확정 아님)

1. FE가 서울 비공간 기준 좌표 누락 수를 어떻게 표시할지. 반경 내 수가 필요하면 추가 위치 자료·별도 계약이 필요하다.
2. 날짜 품질 제외 수·가맹 데이터 상태의 추가 meta 필요 여부와 필드 이름.
3. 신규 독립 unknown UI와 legacy 호환 전환 시점. BE 설계 매핑은 §2대로 두되 FE 반영 완료로 표시하지 않는다.
4. 인덱스 일반/CONCURRENTLY 생성과 ANALYZE 실행 절차는 실제 구현 환경·쓰기 영향 측정 후 결정한다.

0㎡는 사용자 답변으로 정보 없음 처리로 확정됐다. D·최소 월·배치 완료·legacy의 출처는 아래 Codex 최종 점검으로 정리했으며 불필요한 추가 사용자 승인 항목으로 남기지 않는다.

### 구현 선행 조건

- PR #37 병합 후 develop head·migration head 재확인, 지원 업종·기간 계산·배치 출처·DB 세션 헬퍼의 실제 인터페이스 확인(READ ONLY/REPEATABLE READ 설정 시점 포함).
- PR #37의 점포·배치 동일 트랜잭션과 commit 가시성·출처 연결을 확인한다. 별도 상태 컬럼이 없다는 이유만으로 새로운 migration이나 승인 절차를 요구하지 않는다.
- date_flag 값 목록과 open/close 각각의 신뢰 불가 의미 확인.
- 읽기 전용 품질 확인은 §1에 기록했다. 구현 시 최신 데이터에서 다시 확인하고 0㎡를 사용자 결정대로 unknown에 포함한다.
- 일회용 PostGIS에서 geography cast 표현식 인덱스 생성 가능 여부와 복수 중심점 경계 검사.
- 실제 FE 반영에 영향을 주는 검토 사항을 FE 요청 보고서에 기록하고 합의 완료로 표시하지 않는다.

### Codex 최종 점검

Claude 실행 결과 is_error=false, 20턴, 권한 거절 없음과 실제 MD 수정 diff를 확인했다. 입력 충돌·정밀도·공통 cohort·nullable·트랜잭션·검증 보완은 반영했다. 원본·현재 코드와 다른 제안은 다음 근거로 정정했다.

- D: 원본 API v1.2 3쪽의 DAT_UPDT_PNT 최대 날짜 및 PR #37의 전역 최대 기준을 유지한다. 갱신 최대일은 원천 전체 관측 완료일이 아니므로 서로 다른 날짜를 최소 관측일로 해석하지 않는다.
- 최소 월: 원본 8쪽 §4-5는 category 필수·sub_category 선택을 명시한다. 요약에 없는 입력을 원본에도 없다고 간주한 검토 내용을 정정했다.
- 배치 완료: 실제 repository는 점포 upsert와 배치 삽입을 같은 begin 블록에서 commit한다. 별도 completed 컬럼은 필요하지 않다.
- 날짜: 원본 날짜 구간을 만족하는 유효 other 행은 일괄 제거하지 않는다. history에는 nearby의 엄격한 날짜 제외 정책을 이식하지 않는다.
- 면적: 실제 0㎡ 6,316건·음수 0건을 확인하고 사용자가 정보 없음 처리를 명시했다. DB 보존·출력 null·토글 동일 제어를 함께 설계한다.
- 경계: PostgreSQL 17.11/PostGIS 3.7.0에서 서울권 합성 중심점 5개로 1,440개 함수를 추가 확인했다. 확장 후보 누락 0건, 최종 거리로 제거할 후보 360건이었다. 이는 0.01m 후보 여유의 현재 근거이며 버전/경계 회귀는 실제 구현에서도 필요하다.
- 인덱스: 기존 GIST가 IS NOT NULL만으로 사용되는 실행 계획을 확인해, 단순 Index Scan 이름 검사를 성능 검증으로 사용하지 않도록 보완했다.

최종 변경은 문서뿐이다. nearby 코드·DDL·인덱스 생성·데이터 변경·FE 수정은 하지 않았다.

## 10. 이번 설계 완료 기준

BE 설계·Claude 직접 수정·Codex 최종 점검·FE 요청 보고서 작성 및 BE 설계 전용 PR로 리뷰 가능해야 한다. FE 저장소와 API·migration·DB를 바꾸지 않았는지 최종 diff를 확인한다. 문서 PR의 CI가 통과해도 nearby API 구현/테스트 완료로 기록하지 않는다.
