# 검색 위치에 연결되는 매출·생활인구·주야간 자료 표시 설계 (#186)

작성 2026-11-16. BE 기준 `85c51ce`, FE develop 기준 `5959752c`. 이번 결과물은 **현재 시스템 비교 분석·설계·실제 Claude Code 검토·Codex 재검토**다. 기능 구현, 새 자료 적재, migration 적용 및 공개 배포는 후속 작업이며 이 문서의 완료와 구분한다.

## 1. 사용자 목적과 확정할 방향

검색 좌표를 포함하는 구역 또는 요청 반경과 실제로 겹치는 구역에 공개값이 있으면 표시한다. 가장 유사한 지역을 찾는 문제로 확장하지 않는다. 구역 전체의 값을 해당 점포·도로·반경 자체의 값으로 바꾸지 않고 **실제 자료 단위·구역명·자료 날짜**와 함께 제공한다.

이번 설계의 기본 경로는 다음과 같다.

1. 매출: 보유 상권 도형과 검색 위치/반경의 관계로 후보를 정하고, 같은 상권 코드·유형·업종의 원자료 금액을 상권별로 표시한다.
2. 생활인구: 검색 좌표를 포함하는 **원천과 일치하는 행정동 도형**을 찾고, 제공기관이 이미 행정동별로 집계한 **내국인 생활인구**를 우선 연결한다.
3. 주야간: 위 행정동의 같은 관측일·같은 내국인 구성 24시간 자료로 주간/야간 평균과 비율을 계산한다.
4. 기본 화면은 `latest_reference`로 실제 이용 가능한 참고자료를 표시한다. 점포 분석 기준일과 다른 자료 날짜를 숨기지 않는다. 과거 시점 일치를 요구하는 `analysis_period`는 별도 명시 모드다.

행정동으로 표시하면 기존 제목 `전체 생활인구 (250m 격자)`는 `검색 위치가 속한 행정동 생활인구`로, 대표 숫자는 `내국인 시간대 평균 생활인구`로 바꾼다. 주야간 제목도 `주야간 생활인구 비교 (행정동·내국인)`로 맞춘다. 기존 공개 격자 부분비교는 별도 상세 자료로 유지할 수 있다. 세 대표 블록을 서로 다른 모집단의 숫자로 조합하지 않는다.

### 1.1 이전 설계와 달라지는 범위

[#156](feat156-market-applicability.md), [#174](feat174-analysis-foundations.md), [#176](feat176-reference-activation.md)의 원천 보존·가짜0 방지·전체 인구 산정 원칙은 유지한다. 다만 사용자의 최신 요구에 따라 **구역의 원자료 참고값 표시**를 공식 역사 통계의 검증 완료와 분리한다. #176의 제안8표/승인 publication/전체 인구 구성 증명을 이번 참고 표시의 일괄 선행조건으로 두지 않는다.

기존 불변 버전의 `unverified`를 UPDATE로 바꾸거나 `source_validation_performed`를 true로 승격하지 않는다. 역사적 적용성이 미확인인 경계를 사용하면 `공개 도형 기준으로 포함/교차하는 상권`이라는 뜻이다. 그 도형이 선택한 과거 분기의 공식 경계였다고 주장하지 않는다. 실제 도형·코드 연결 자체가 확인되지 않은 후보는 숫자와 결합하지 않는다.

## 2. 현재 시스템과의 차이

### 2.1 코드에서 확인한 상태

| 영역 | 현재 구현 근거 | 필요한 변경 |
|---|---|---|
| 활동 API | `app/schemas/market_activity.py`의 `sales: None`, `living_pop: None`; `app/services/market_activity.py`의 항상 null 반환·고정 pending 사유 | 기존 null 계약을 억지로 채우지 않고 새 위치 참고 API 제공 |
| 상권 공간 조회 | `app/services/market_judgement.py`는 명시 boundary version의 `ST_Covers`와 도형의 geography 거리 조회가 있음 | 공간 선택 로직을 재사용하되 특정 상권 하나를 primary로 확정하는 기능과 분리 |
| 매출 기반 | `market_sale_versions`/`market_sales`, 원문 금액 BIGINT·분기·상권·업종·hash 보존 | 같은 경계 FK의 코드 연결 검증 후 실제 읽기 service 구현 |
| 매출 산술 helper | `app/analysis/market_reference.py`의 `project_sales`는 확인된 period basis만 받음 | 미확정 필드를 `quarter_total`로 속여 넣지 않고 원자료 전용 typed projection 추가 |
| 격자 인구 | `living_grid_versions`/`living_grids`, `living_population_versions`/관측 행 | 유지. 격자 관측을 행정동 전체값으로 역산하지 않음 |
| 전체 인구 조립 | `population_totals.py`는 독립 기대 구성·3원천/24시간을 요구 | 전체 산정 함수는 보존. 새 행정동 내국인 경로가 이 함수를 호출하거나 통과했다고 주장하지 않음 |
| 공개 부분 인구 API | `/api/v2/population-reference`; 요청 월 안의 관측일≤T; 격자 **중심점** 거리 기준 | 기존 요청·응답·중심점 규칙 보존. 새 경로는 행정동 포함 판정/명시 자료 날짜 사용 |
| 주야간 계산 | `day_night.py`의 06~17시/00~05·18~23시, Decimal 평균/비율 | 행정동 local의 완전한24시간 입력이면 순수 산술 재사용 |
| AI | `app/schemas/ai_population.py`, `app/ai/population_context.py`가 같은 분석월·최소 문맥을 검증 | 1차 구현에서는 새 참고자료를 자동 AI 문맥에 넣지 않음. 기존 AI/GET의 날짜 검증 완화 금지 |
| FE 매출 | `ConditionalBlocks.tsx`의 상권별 `SalesBody`, 비합산 표시가 존재 | 새 응답으로 연결하고 실제 금액 의미·구역 관계·기준일 표시 추가 |
| FE 인구 | `src/types/market.ts`는 `total/grid_count/missing_grid_count`의 격자 전용 타입 | 행정동용 타입/뷰 추가. grid_count에 행정동 수를 넣지 않음 |
| FE 주야간/보고서 | 기존 `PopulationReferenceView`와 전용 query/hook가 분석·종합·보고서에서 사용됨 | 새 참고자료 전용 hook/view와 보고서 대기·오류·취소 처리. 기존 격자 비교는 보조 상세로 분리 |
| FE AI 정합성 | `src/api/interpretationContext.ts`는 AI 관측일이 분석월 안이고≤분석일임을 검사 | 별도 참고카드 데이터 때문에 기존 검증기를 느슨하게 바꾸지 않음 |

### 2.2 이번 로컬 DB 읽기 전용 확인

2026-11-16 실제 로컬 설정으로 READ ONLY REPEATABLE READ, statement timeout8초를 사용해 버전·집계 메타만 조회했다. 쓰기/적재/원문 출력은 하지 않았다. 공개 운영 DB를 이번에 재검증했다는 뜻은 아니다.

| 항목 | 확인 결과 |
|---|---|
| migration head | 0012 |
| 상권 경계 | 1버전, 1,650개, `boundary_as_of=null` |
| 매출 | 20251:3,617 / 20252:3,596 / 20253:3,597 / 20254:3,581, 합14,391행. 추가 READ ONLY 확인에서 각 분기의 distinct version_id는1개 |
| 생활인구 관측 | 2026-11-07, 1버전, 531,922행 |
| 격자 | 1버전, 10,125개, `grid_as_of=null` |
| 행정동 전용 집계·도형 테이블 | 없음 |

따라서 지금 보이는 2023-11-30의 빈 값은 키 누락만의 문제가 아니다. 매출/전체 인구의 **공개 반환 구현 부재**, 선택 월의 **적재 자료 부재**, 행정동 집계용 **모델/ETL 부재**가 각각 있다. 새 API 키만 추가하면 해결되는 상태가 아니다.

## 3. 사용할 공식 자료와 아직 확인할 것

확인일 2026-11-16. 아래는 공개 웹페이지의 목록·설명 확인이며, 새 ZIP 내려받기/실제 필드·내용 검증과 구분한다. 공개 설명을 길게 전재하지 않고 구현 결정에 필요한 사실만 요약한다.

| 자료 | 확인된 사항 | 구현 시 확보/확인 |
|---|---|---|
| [추정매출-상권 OA-15572](https://data.seoul.go.kr/dataList/OA-15572/F/1/datasetView.do) | 원 단위, 분기 갱신, 2023·2025 연도 파일 목록 존재. 공간 단위 제공 기준 변경 공지도 있음 | 보유ZIP과 현재 제공판의 차이, `당월_매출_금액`의 기간 해석. 우선 원문 금액 그대로 제공 가능 |
| [현재 행정동 내국인 OA-23016](https://data.seoul.go.kr/dataList/OA-23016/S/1/datasetView.do) | 제공기관이250m 자료를 행정동으로 집계. 현재 확인한 최신 월별 파일은202610. API 최근2개월 제공 안내 | 실제 최신 일자/파일 범위·열명·행정동 코드 체계·24시간 총계·마스킹/부재·도형 연결 |
| [과거 행정동 내국인 OA-14991](https://data.seoul.go.kr/dataList/OA-14991/S/1/datasetView.do) | 202311 ZIP 목록 존재. 구계열은2026-07-31 이후 생산 종료 안내 | 2023년 조회 필요 시 별도 계열로 적재. FAQ상2016 행정동 코드를 쓰므로 현대 행정동과 이름으로 연결하지 않음 |
| [생활인구 아카이브](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingArchive.do) | 구계열 집계구 아카이브와 행정동 내국인/장기·단기 외국인 링크 제공 | 구계열 원천에는 같은2016 코드/도형을 사용. 현재계열과 자동 혼합 금지 |

현재계열 행정동의 **같은 코드 체계 도형**을 우선 확보한다. 카카오 행정동명만으로 원천 코드에 연결하지 않는다. 도형의 기준시점/관측일 대응이 불명확하면 metadata/UI에 표시하며, 코드 체계 자체가 미확인이면 그 코드는 공간미대응이다. 다른 지역/유사지명으로 대신하지 않는다.

### 3.1 경계 확보의 첫 산출물과 일치 판정

A단계의 첫 산출물은 **후보 dataset ID·실제 도형 artifact URL/형식·코드 체계 설명 출처·기준일·코드 대조표**다. 후보 출발점은 서울시 [영역-행정동 OA-22160](https://data.seoul.go.kr/dataList/OA-22160/S/1/datasetView.do)과 공공데이터포털 연결ID [15147263](https://www.data.go.kr/data/15147263/fileData.do)이다. 공개 설명상 주민등록 행정기관코드를 사용하지만 CSV의 중심좌표/면적만으로 경계 포함 판정을 할 수는 없다. **같은 출처의 실제 polygon artifact를 확보해야 후보가 된다.** 이번에 파일을 확보했거나 생활인구와 동일 코드임을 확인한 것은 아니다.

후보가 부적합하면 서울시 생활인구 공식 페이지의 코드정보/경계 안내에서 원천 계열에 맞는 polygon을 찾고, 그 dataset ID/artifact ID를 A산출물에 추가한다. 구계열은2016기준으로 별도 처리한다. 좌표 하나로 동 경계를 만들어내거나 숫자 일부를 잘라 코드 체계를 변환하지 않는다.

판정은 선택 관측일의local 코드 집합P와 실제 도형 코드 집합G를 **정확한 문자열**로 비교해 `P∩G`, `P-G`, `G-P`의 코드별 목록과 건수를 남긴다. 원천 계열의 공식 코드 설명도 일치해야 한다. 전체 연결 완료는 `P-G=∅`이고 유효/유일 도형을 갖는 경우다. 미대응이 있으면 해당 코드만quarantine하고 일치하는 나머지 동은 제공한다. 같은 코드의 복수 동/도형 손상은 그 코드만 제외한다. 기존 격자 관측의admin_code와 후보 도형/중심점의 공간 관계도 집계로 보조 대조하되, 격자 중심점은 경계에 걸칠 수 있어 이검사만으로 공식 코드 동일성이나 인구값을 증명하지 않는다.

어떤 동도 연결하지 못하면 인구/주야간은 `pending/admin_boundary_unmatched`이며 그때는 **매출만 독립적으로 공개 가능**하다. 세값 완료로 표시하지 않고 A의 구체적인 미확보 artifact/권한을 보고한다. 이조건은 별도 통계 승인이나 전동100%대응을 요구하는 무기한 게이트가 아니다.

장기/단기 외국인은 후속 source별 블록으로 추가할 수 있다. **첫 공개의 필수 입력은 내국인 행정동 자료+그 도형**이며 외국인 완전성이 내국인 숫자를 막지 않는다. 내국인만 있는데 내외국인 전체라고 표시하지 않는다.

새 인증키는 우선 요청하지 않는다. 기존 설정 또는 공개 ZIP으로 가능한 범위에서 수집한다. 공식 다운로드가 실제로 인증/접근권한을 요구하거나 경계 artifact를 확보할 수 없을 때만 해당 자료·정확한 제한을 특정해 요청한다. 이 문서 단계에서는 수집/API 인증 성공을 주장하지 않는다.

## 4. 실제 공간 연결 규칙

### 4.1 매출

- 경계는 선택한 매출 원천 버전의 `code_check_boundary_version_id`로 고정한다. 최신 경계 UUID를 임의 선택하지 않는다.
- WGS84 점 `P`와 저장 MULTIPOLYGON의 `ST_Covers(geom,P)`로 경계선 포함 판정한다.
- 반경 후보는 도형과 점의 geography 최소 거리≤요청 radius인 상권이다. 기존 `ST_DWithin` 사전 필터+정확 거리 검사를 활용한다. 단순 상권 중심점 거리나 bounding box만으로 포함시키지 않는다.
- 기존`judge_market`는 포함상권이없을때만nearby를조회하므로통째로호출하지않는다. 공간술어만재사용하는새loader에서포함유무와무관하게양쪽후보를구한다. 같은경계버전/코드가포함목록에있으면교차목록에서는제외하고`classify_markets`의primary선택을사용하지않는다.
- 응답은 `contains_point`와 `intersects_radius`를 구분한다. 포함 상권을 먼저 표시하고 반경 교차 상권도 별도 목록으로 제공한다. 포함 상권에 해당 업종 값이 없다는 이유로 전체 조회를 종료하지 않는다.
- 같은 버전·상권 코드·유형·업종을 대조한다. 이름은 불일치 검출에 쓰며 이름 유사도로 연결하지 않는다. 코드/유형/명칭 충돌은 해당 행을 `mapping_conflict`로 제외한다.
- 기존 ETL의 유형표 `A→alley`, `D→developed`, `R→traditional_market`, `U→tourism_zone`을 재사용한다. C산출물은 보유 version의 `code_check`와 실제 상권/매출 코드 교집합·양방향 차집합·유형/명칭 불일치 건수다. 제외 사유는 `excluded_counts`로 나눈다. 코드 매칭 여부를 역사적 경계 승인과 혼동하지 않는다.
- 중첩 상권·관광특구도 관계를 표시해 각각 반환한다. primary1개로 압축하거나 합산하지 않는다. 지도상 경계/행정동/상권 사이에 공유 도로가 있다는 설명만으로 값의 배분률을 만들지 않는다.
- 도로 단위 자료를 추후 쓸 경우에도 도로 도형·공식 도로 식별자·해당 값이 직접 연결되어야 한다. 현재 도로 매출 원천은 없으며 새 도로 API를 이번의 필수 요구로 추가하지 않는다.

### 4.2 생활인구·주야간

- 원천 관측 버전이 참조하는 행정동 도형 버전의 `ST_Covers`로 실제 검색 점을 포함하는 행정동을 조회한다.
- 반경이 다른 동에 걸쳐도 행정동 전체값을 서로 합치지 않는다. 대표값은 점 포함 행정동의 값이다. 이 경우 radius는 점포 분석 맥락이고 인구 집계 범위가 아님을 표시한다.
- 경계선에서 두 행정동이 모두 포함하면 각각 카드/행으로 반환한다. 서로 다른 행정동의 12시간씩을 결합하거나 임의의 코드순1개를 선택하지 않는다.
- 점 포함 도형이 없거나 포함 동의 완전한local일이 없으면, 실제 반경과 교차하는 다른 행정동의 값을 별도 `intersects_radius` 목록으로 제공한다. 포함 동의 결측/공간미대응 상태도 남긴다. 교차 동을 검색 점의 소속 동이나 반경 자체의 값으로 승격하지 않고 여러 동은 각각 표시한다. 반경 밖 최근접 동을 대신 쓰지 않는다.
- 행정동교차도매출과같이geography `ST_DWithin` 사전필터+`ST_Distance(polygon,point)≤radius`를쓴다. 포함목록의동은교차목록에서제외한다. `area_ref`는경계내용지문과코드로만든opaque키로동일경계의같은구역을가리킨다. 도형이미확보인코드를특정검색점의소속동이라고단정하지않고, 미대응건수는그원천전체진단과공간선택결과를구분한다.
- 격자 부분비교를 유지하는 경우 그 규칙은 여전히 중심점 기준이다. 새 행정동 자료의 `contains_point`와 혼동하지 않는다. 격자 도형 교차로 바꾸는 일은 별도 규칙 버전/검증 대상이다.
- 서울 밖/공식 대상 밖은 `no_data/outside_coverage`이며 실제 공개값이 없는 위치까지 수치 제공률100%를 보장하지 않는다.

## 5. 날짜 선택: 점포 분석일과 참고자료일 분리

기존 인허가 기반 `effective_date`, Risk/활동, 기존 공개 인구 GET/AI의 T를 바꾸지 않는다. 새 API만 다음 모드를 지원한다.

| 모드 | 자료 선택 | 의미 |
|---|---|---|
| `latest_reference` (새 카드 기본) | 실제 공간 후보·요청 업종에 연결되는 저장 자료 중 최신 이용 가능 값 | 점포 분석일보다 뒤의 관측일도 허용. 반드시 실제 기준일과 `temporal_relation` 표시 |
| `analysis_period` | 매출은 분석일이 속한 분기, 인구는 해당 월1일~분석일까지 | 다른 월/분기로 조용히 대체하지 않음. 그 기간 미적재면 `no_data/no_data_in_analysis_period` |

`analysis_as_of`는 점포 분석의 서버 확정 T이고 `requested_as_of`는 원 요청을 보존한다. 매출의 `source_quarter`/인구의 `observation_date`가 실제 자료 기준이다. `temporal_relation`은 `same_period|earlier_reference|later_reference`다. 분기 자료가 분석일을 포함하더라도 그 분기 전체가 종료되지 않았다면 `period_end_after_analysis=true`를 별도로 표시한다. 과거 의사결정 시점에 공개됐던 자료라는 의미는 아니다. `published_at`을 모르면 null이며 관측일로 대신 채우지 않는다.

첫 구현의 적재 범위가 최신local1개월/매출2025년이면, 2023년의`analysis_period`는 `no_data/no_data_in_analysis_period`가 정상이다. 기본`latest_reference`의 값 표시와 구분한다. 2023년 OA-14991은 별도 code_system/2016 도형을 확보한 후에만 추가 적재한다.

### 5.1 구체적 선택 순서

1. 서버가 허용한 원천 계열과 공간 버전의 catalog를 RR에서 읽는다. 사용자에게 version ID/verified 플래그를 받지 않는다.
2. 실제 공간 후보를 먼저 정한다. 전역 최신 날짜에 그 동/업종 값이 없다는 이유로 모든 값을 없는 것으로 처리하지 않는다.
3. 매출은 상권·업종별로 금액이 존재하는 가장 최근 분기를 선택한다. 최신 분기에 null/행 부재이고 이전 분기값을 쓰면 `selection_reason=latest_numeric_row`와 실제 분기를 남긴다. `analysis_period`에서는 이 대체를 하지 않는다.
4. 인구는 행정동별 **local24시간이 모두 observed**인 가장 최근 관측일을 선택하고 대표 인구와 주야간에 같은 관측일/버전을 사용한다. 최신 완전일보다 뒤에 불완전일이 있다면 `selection_reason=latest_complete_day`로 알린다. 동마다 날짜가 다를 수 있으므로 날짜를 카드별로 표시한다.
5. 같은 원천 계열·날짜에 복수 개정판이 있으면 명시한 catalog **내용 지문**으로 개정판을 해석한다. 선택 정보가 없거나 지문에 맞는 버전이 복수이면 `pending/ambiguous_source_version`이다. catalog대상 미적재0건은 `no_data/source_not_loaded`, 같은 지문으로 연결된 실제 내용/행수 손상은500이다. UUID순으로 고르지 않으며 최신계열과 구계열을 한 자료로 합치지 않는다.

`latest_reference`에서 2023년 점포 분석과2025년 매출/2026년 인구를 함께 보일 수 있으나, 각각의 실제 날짜와 차이를 본문 가까이 표시한다. 최신 행정동 자료가 지금 DB의 격자 관측일2026-11-07과 같을 것이라고 가정하지 않는다. 현재 확인된 월별 후보는202610이며 ZIP 검증 후 실제 가능한 날짜를 정한다.

## 6. 숫자의 의미와 결측 처리

### 6.1 매출

`market_sales.est_sales` 원문 정수를 변환 없이 사용한다. `source_quarter=20254`, `source_field=당월_매출_금액`, `currency=KRW`, `amount_basis=source_reported`, `amount_period_status=unverified`를 반환한다. 첫 표시는 **`2025년 4분기 자료 · 원자료 추정매출 금액`**으로 한다. 분기 코드와 금액 집계기간 의미는 별개이므로 `월매출`, `분기 총매출`, `KRW/quarter`를 임의로 붙이지 않는다. 3으로 나누거나 곱하지 않는다. 공식 정의가 확보되면 새 원천/표시 규칙에서 명시 basis를 추가한다.

이열 이름의 근거는 보유ZIP을 검증하는 `etl/market_sales/fields.py`의 기존 allowlist다. 현재 웹 제공판의 실제 열을 이번에 다시 다운로드해 확인한 것은 아니다.

업종은 기존5개 코드의 명시 매핑(한식/중식/일식/양식/커피·음료)을 사용한다. category=restaurant이고 sub_category 미지정이면4개 업종을 별도 행으로 반환한다. 한 업종 행이 없다고 다른 업종 숫자를 그 업종의 값으로 표시하지 않는다. 브랜드·체인·면적·상호 제외 필터는 통계 매출에 적용할 수 없으며 `store_filters_applied=false`로 표시한다. 이 필터가 있는 화면에서도 참고자료의 범위는 동일하다.

BIGINT를 JavaScript number로 손실 전송하지 않도록 API `value`는 정확한 십진 정수 문자열, `display`는 서버 표시 문자열이다. 반올림 여부와 단위는 별도 필드다. 실제0은 numeric0이고 null/행 부재와 다르다. 상권 전체 금액을 점포당 평균·반경 금액·도로 금액으로 나누지 않는다.

### 6.2 생활인구·주야간

제공기관 **행정동 총계 열**을 사용하고 성·연령 세부 열을 다시 합쳐 총계와 중복시키지 않는다. 원천 내국인24시간의 값이 `p[h]`이면:

- 대표값: `mean_24h = Σp[h]/24`, 명칭 `내국인 시간대 평균 생활인구`.
- 주간: `mean_day = Σp[6..17]/12`.
- 야간: `mean_night = (Σp[0..5]+Σp[18..23])/12`.
- 주야간 비: `mean_day/mean_night`. 야간이 실제0이면 비율은 null이며 `zero_night_population`을 표시한다.
- 기존 산술의 비중을 쓸 때는 `day_sum/(day_sum+night_sum)`이다. 12시간씩이므로 평균 비중과 같다. 시간 구분은 **Spot:ON 기준**이며 서울시 공식 대시보드의 시간 구분이라고 쓰지 않는다.

Decimal50자리 연산, 원천 소수 자릿수 보존, 대표/평균은 소수1자리·비율5자리 ROUND_HALF_UP 표시를 사용한다. 정확 값은 십진 문자열이며 화면 반올림0과 실제0을 구분한다. 시간별 합계는 고유 방문객 수가 아니므로 24시간 합을 `하루 방문객`으로 제공하지 않는다.

원천값은 기존 산술과 같은 Numeric(20,5) 범위/최대소수5자리로 제한하고 초과 입력은 importer가 **반올림하지 않고 거부**한다. 실제 원천 소수 자릿수는 A에서 확인한다. `mean_24h`는 현재`day_night.py`에 없으므로 동일 입력검사/Decimal context를 사용하는 별도 순수함수로 추가한다. 무한소수 평균/비율은 Decimal50자리 내부 연산값과 표시 반올림을 구분한다.

local의24시간 완전성만 local 평균/비율의 조건이다. long/short가 빠져도 local 결과는 제공한다. 실제0=`observed/0`, 별표=`suppressed/null`, 빈 셀=`missing/null`, 행 부재=`absent`를 구분한다. 중복 source/date/admin/hour는 importer가 거부한다. 같은 raw total이 grid/admin 차원에 반복된 데이터를 행정동 총계로 합치지 않는다.

모든 수집일에 local24시간이 불완전하다면 가짜평균을만들지않고`no_complete_day`를표시하며주야간비율도산정하지않는다. 특정시각의`observed_hour`보조항목은첫구현범위에서제외한다. 비공개값을0/보간값으로채우지않으며실제수집검증에서완전한local일을확보하는것이세숫자표시의필수확인이다.

내외국인 전체 수치는 첫 배포 범위 밖이다. 이후 같은 구역·날짜·시간·상호 배타적 원천/공식 합산 정의가 확인된 경우에만 별도 전체 지표를 추가한다. 행정동 local의 산술 성공을 기존 전체 인구 승인으로 표시하지 않는다.

## 7. 후속 데이터 모델·ETL

현재0012에는 행정동 전용 저장이 없어 후속 migration이 필요하다. 번호는 구현 시작 시 최신 head에서 정하며, #176의 미구현0013/8표가 이미 적용돼 있다고 가정하지 않는다.

### 7.1 최소 추가4테이블

| 후보 테이블 | 핵심 필드와 제약 |
|---|---|
| `admin_boundary_versions` | UUID, source_dataset/source_url, code_system, source_crs, source_file_date, boundary_as_of nullable, input/content SHA256, row_count, loaded_at. UNIQUE(boundary_version_id,code_system) |
| `admin_areas` | PK(boundary_version_id,admin_code), admin_name, valid한 MULTIPOLYGON4326, geometry hash, GiST. 같은 이름으로 코드 통합 금지 |
| `admin_population_versions` | UUID, source 계열/개정판, boundary_version FK, observation_date, source(local/long/short), code_system, 파일/hash·행수·규칙·상태 집계·loaded_at. UNIQUE(version_id,boundary_version_id,observation_date,source) |
| `admin_population_hours` | PK(version_id,admin_code,hour0~23), boundary_version_id/observation_date/source, population Numeric(20,5) nullable, value_status, source_row_sha256. version/date/source/boundary 복합FK와 `(boundary_version_id,admin_code)→admin_areas` 복합FK·nonnegative/상태CHECK |

하나의 population version은 한 날짜·한 source·한 경계 버전이다. 월ZIP에서 날짜별 version을 생성하며 파일 SHA를 공유해도 날짜별 content SHA는 구분한다. source별 버전 분리로 외국인 지연이 local 공개를 막지 않는다. 경계 미매칭 행은 삭제/0채움 대신 importer 진단으로 보존하고 API의 공간 수치에서 제외한다. 저장 방식은 bounded quarantine artifact+건수이며 매칭하지 못한 코드를 다른 행정동으로 바꾸지 않는다.

`admin_population_versions`는`(boundary_version_id,code_system)`복합FK로경계버전을참조한다. 코드형식만같은구계열2016/현계열을섞으면DB가거부한다. 버전/행정동FK는미매칭코드의DB삽입도막고해당원문은별도quarantine에보존한다.

`code_system`은 임의의8자리 형식이 같다는 뜻이 아니라 예를 들어 `seoul-living-legacy-2016`과 현재계열 확인값을 구분하는 식별자다. 코드의 선행0·문자열을 보존한다. 기존 격자/원천 불변 CHECK와 stores는 변경하지 않는다.

### 7.2 수집·적재·개정판 선택

새 ETL 후보 `etl.admin_population`은 **미구현 이름**이다. 원천 다운로드와 DB 쓰기를 분리하고 기본 preview/read-only, 명시 write만 새 버전을 추가한다. 실제 열/인코딩·날짜 범위·시간·총계·중복·마스킹·코드 교집합·도형 관계를 검증한다. 키/원문/개인위치가 로그·Claude 입력·커밋에 들어가지 않게 한다.

기존 ETL의 대상/역할/head guard를 완화하지 않는다. clone에서는 별도 대상·프로세스 설정으로 기존 guard에 맞춰 검증하고 원본 설정을 바꾸지 않는다. 원격/운영 적재는 별도 백업·관리 실행 절차로 수행하며 앱 시작 시 migration/ETL을 하지 않는다.

명시 원천 catalog는 BE 배포에 포함하는 작은 **metadata JSON**으로 충분하다. 대상은 기존 매출/상권 경계와 새 행정동 집계/도형 전부다. 환경마다 달라지는 UUID를 catalog key로 쓰지 않고 `source_dataset, source_series, source, observation_date/source_year, rule_version, input_sha256, content_sha256, row_count`와 **경계content_sha256/코드체계**로 개정판을 지정한다. source_series는 고정된 규칙 식별자다. 해당 모델에 없는항목은 그kind에서 생략한다.

같은RR에서 지문에 맞는DB버전을 찾고 그환경의UUID/FK로 해석한다. 0건은`source_not_loaded`, 복수는`ambiguous_source_version`이며 UUID정렬로 고르지 않는다. 실제FK의 경계지문도catalog와 같아야 한다. 실제선택판의 행수/내용확인 수준·hash 검증시점도 기록한다. 매 요청 전체 원천hash를 재계산하지 않고, 적재/적용시 전체hash대조와 읽기시 선택행/메타대조를 구분한다. 원천이 바뀌면 새버전+새catalog를 배포한다. 별도 승인8표나 자동최신UUID선택은 추가하지 않는다.

매출kind는`code_check_store_version_id`가참조하는`market_store_versions`의내용지문(dataset/rule/input/content/row_count)도포함한다. 기존UNIQUE의store버전차이를잃지않고, 환경별UUID는위지문으로해석한다. 이참조는원천판선택근거이며점포필터를매출에적용하는것이아니다.

**매출전용0012릴리스:** catalog에행정동kind가없으면인구/주야간은`pending/population_source_not_released`를DB조회없이반환한다. 없는`admin_*`표를조회하고예외를삼키는방식은금지한다. 인구릴리스는새head와행정동catalog를함께배포한다. catalog에는있지만대상버전이없는`source_not_loaded`, 수집진단상코드미대응`admin_boundary_unmatched`와구분한다. 매출응답을인구테이블부재로500처리하지않는다.

자료량은 clone에서 새4표의 heap/index/TOAST와 DB 전체 증가분을 실측한다. 1차는 최신 local1개월·필요한 도형1계열만 적재한다. 2023 자료와 외국인 전체 월을 처음부터 모두 적재하지 않는다. 계획상 예상량을 실제 운영 저장량·허용 여유 확인으로 대신하지 않는다. 자원이 부족하면 우선 적재 일수를 명시적으로 줄이고 사용 가능 날짜를 응답에 표시하며 무단 증설/원천 삭제를 하지 않는다.

## 8. 새 API 계약

새 GET 후보 **`/api/v2/location-reference`**를 추가한다. 아직 구현된 URL이 아니다. 기존 `/market/activity`, `/population-reference`, Risk/AI 응답의 의미를 바꾸지 않으므로 구 FE/구 BE와의 이행이 쉽다. 새 FE는 이 응답으로 기존 세 대표 블록의 데이터 공급원을 교체한다.

### 8.1 요청

- `lat,lng`: 기존 유한 좌표 검증/서울 공간 적용 범위 사용. 응답/로그/AI에 좌표를 복사하지 않는다.
- `radius`: 기존300/500/1000m.
- `category,sub_category`: 기존 지원 업종 검증. 매출에만 적용하고 인구는 필터하지 않음.
- `as_of`: 기존 점포 분석의 요청월. 서버의 동일 effective T를 metadata로 반환.
- `time_mode`: `latest_reference|analysis_period`, 새 카드 기본 `latest_reference`.
- 알 수 없는 인자·중복 query·브랜드/면적/임의 source UUID/verified 인자는422. 같은 요청 취소·세션/deadline·no-store 방식을 재사용한다.

### 8.2 응답 구조

기존 `ApiResponse` 외피를 사용한다. 아래는 **필드 계약이며 실행 결과/시연 숫자가 아니다**.

```text
data:
  requested_as_of, analysis_as_of, time_mode
  sales:
    status, reason, items[], excluded_count, excluded_counts
    items[]: market_code, market_name, market_type, spatial_relation,
      source_quarter, period_end_after_analysis, temporal_relation,
      industry_code, industry_name, metric{value,display,unit,rounded,exact_zero},
      amount_basis, amount_period_status, selection_reason, provenance_ref
  living_population:
    status, reason, items[]
    items[]: area_ref, area_name, spatial_relation, spatial_unit=admin_dong,
      observation_date, temporal_relation, population_scope=local,
      mean_24h{value,display,unit,rounded,exact_zero}, status, reason,
      selection_reason, completeness, provenance_ref
  day_night:
    status, reason, items[]
    items[]: area_ref, observation_date, population_scope=local,
      mean_day, mean_night, day_night_ratio,
      day_share_pct, night_share_pct, hour_rule=spoton_06_18_v1,
      status, reason, provenance_ref
meta:
  format_version, rule_version, requested_scope,
  source_catalog_digest, source_refs[], reference_snapshot_token,
  store_filters_applied=false, population_filter_applied=false,
  historical_boundary_compatibility=unverified,
  population_total_validated=false, is_demo=false
```

`source_refs[]`는 공개용 키·공식 dataset명/URL·실제 관측일/분기·취득일·공개일nullable·경계 정보/미확정 사항을 연결한다. 각 `provenance_ref`가 정확히 하나의 source_ref로 해석되는지 검증한다. UUID/SHA는 내부 지문과 공개 opaque token으로 제한하며 비밀키/주소/개별 점포 식별자·관측 원문은 공개하지 않는다.

metric의 `unit`은 인구 평균=`estimated_people_hourly_mean`, 비율=`ratio`, 구성비=`pct_of_local_hourly_population`, 매출=`KRW_source_reported`다. 원천 소수 정밀도를 보존하고 값/표시 문자열/반올림 상태를 독립 검증한다.

블록과 행의 `status`는 `ready|partial|no_data|pending|not_supported`다. 수치가 있는 행과 결측 행이 함께 있으면partial, 모두 결측이면no_data, 개정판 선택 모호성은pending, 상한 초과는not_supported다. DB 손상/내부 불일치500과 deadline503을no_data로 숨기지 않는다. 행별 이유와 출처를 보존하고 외국인 결측이local을pending으로 만들지 않는다.

최초reason허용목록을다음과같이고정하며FE문구/시험은이표를사용한다. `metric`에도필요시reason을두고비율미정의의`value/display=null`, `exact_zero=false`, `rounded=false`를보존한다.

| reason | 허용 status / 위치 | 의미 |
|---|---|---|
| null | ready인블록/행, 유효metric | 해당범위의값존재 |
| `partial_source_rows` | partial블록 | 유효행과결측/제외행혼재. 각행별사유/카운터별도 |
| `population_source_not_released` | pending인구/주야간블록 | catalog에인구kind없음. 인구SQL없음 |
| `admin_boundary_unmatched` | pending인구/주야간블록·공간미대응진단 | 도형/코드연결미완료. 특정동소속을추측하지않음 |
| `source_not_loaded` | no_data블록/행 | catalog대상버전미적재 |
| `ambiguous_source_version` | pending블록/행 | 선택지문에복수버전/개정판선택미확정 |
| `outside_coverage` | no_data블록 | 서울/해당원천대상범위밖 |
| `no_spatial_overlap` | no_data블록 | 적용가능도형중점포함/반경교차없음 |
| `no_source_rows` | no_data행 | 해당구역/업종의공개숫자행없음 |
| `no_data_in_analysis_period` | no_data블록/행 | analysis_period에해당기간자료없음 |
| `no_complete_day` | no_data인구/주야간행 | local의완전한24시간관측일없음 |
| `zero_night_population` | partial주야간행·비율metric | 평균은유효하지만야간0으로비율미정의 |
| `mapping_conflict` | no_data행·제외사유카운터 | 코드/유형/이름연결충돌 |
| `scope_too_large` | not_supported블록 | 후보/버전/행상한초과 |

수치없는대상행도어느구역인지확인가능하면상태와함께보존한다. source전역진단과요청반경의제외카운터를섞지않고각각scope를붙인다. pending/not_supported가다른수치행과혼재한경우도블록은partial이고행별원래상태를보존한다.

### 8.3 일관된 읽기와 상한

같은 READ ONLY RR에서 인허가T→catalog/버전→공간 후보→대상 행→typed 계산을 수행한다. 요청 중 외부 수집/ETL/쓰기는 없다. Risk/AI와 별도 요청이므로 참고자료 snapshot token과 점포 분석 token의 일치를 요구하지 않고 각자의 의미/날짜를 표시한다.

초기 후보 상한은 상권100개/행정동50개, 매출 명세500행, 참조 관측 version400개, 가져온 hour행50,000개다. limit+1로 초과를 검출하고 상위N개를 완전한 결과처럼 반환하지 않는다. 반경 안 후보가 상한을 넘으면 `not_supported/scope_too_large`다. 날짜 선택/집계는 bounded SQL로 처리하며 전체 관측표를 Python으로 스캔하지 않는다. 실제 쿼리 계획/지연을 clone에서 측정해 상한을 확정한다.

경계GiST·admin/version/hour 키와 version/date/source 인덱스를 사용한다. 기존 Free의 pool/SQL/LLM/ready 예산은 바꾸지 않는다. 새API의 warm15회 각≤6초를 초기 합격선으로 삼고 페이지 병렬GET으로 기존 업무에 생기는 영향도 비교한다. 초기에는 새 수치 캐시가 필요 없다. 도입하면 catalog+원천content+공간선택+time_mode+자료날짜+표시규칙을 포함하고 오래된 캐시로 현재 원천 검사를 생략하지 않는다.

## 9. FE 표시와 기존 AI의 정합성

### 9.1 기존 구성을 활용

매출/인구 두 열과 주야간 블록, 분석/종합/보고서의 배치는 유지한다. 디자인 개편은 필요 없다. 새 query key에time_mode와 기존6입력을 넣고 조회 중/취소/재검색·오류/재시도를 기존 패턴에 맞춘다.

기존매출카드의 모양은 활용하되 `SalesMarket.est_sales:number`·`KRW/quarter`·`formatKrwApprox(number)` 경로는 새값에 재사용하지 않는다. 새전용타입으로 서버`display`를 표시하고 `value`문자열을 Number로 변환하지 않는다.

| 블록 | 값 가까이에 필요한 표시 |
|---|---|
| 매출 | 상권명·포함/반경교차·업종·원자료분기·원자료금액·기간해석미확정 |
| 인구 | 행정동명·포함/반경교차·내국인·관측일·24시간평균·실방문객이 아님 |
| 주야간 | 같은 행정동/관측일/local·SpotON 시간구분·주야간 평균/비율·야간0이면 비율미정의 |

검색 기준일과 다르면 `점포 분석:2023년11월 / 매출 참고:2025년4분기 / 인구 참고:실제 관측일`로 구분한다. API가 반환한 날짜만 사용하고 기존 격자의2026-11-07을 새 행정동 관측일로 고정하지 않는다. 여러 지역은 행별 날짜를 붙이고 업종/브랜드/면적 필터가 인구에 적용된 것처럼 표시하지 않는다.

인구 평균과 주야간은 같은 `area_ref/date/population_scope/provenance_ref`를 요구한다. 주야간은local과 같은출처를 참조한다. 위치관계 등을 중복 저장하지 않으므로FE는 같은area/date의 인구item에서 이름/공간관계를 찾는다. 한쪽만 다른 관측일이면 결합을 거절하고, 이전 요청의 결과를 새 조건 카드에 남기지 않는다.

기존 격자 부분비교를 상세에 남기면 독립적인 `격자 공개 부분자료` 제목과 관측일/중심점 규칙을 표시한다. 행정동 값과 같은 분모/날짜로 보이게 하지 않는다. 구BE에서 새route404이면 기존pending카드로 돌아가는 호환 동작을 둔다. 보고서/PDF도 같은 새 자료를 사용하며 조회 대기/페이지 나눔/여러 상권 행을 검증한다.

404호환은 `새endpoint가 없는 구서버`로 한정한다. FastAPI 기본404형태/공통API오류코드부재 등 정해진 응답만 식별하고, 새BE의 정상no_data/오류와500/503을 구서버호환으로 숨기지 않는다.

### 9.2 첫 구현의 AI 계약 유지

기존AI는 격자 부분비교를 같은 분석월로 검증하므로 새 행정동/최신 참고자료를 자동 설명하지 못한다. 첫 구현은 새카드에 `AI 집계 대상 밖의 참고자료`를 표시하고, AI의 기존 인구 문장을 새카드의 설명으로 배치하지 않는다. 화면/PDF에서 AI 분석일/기존 관측일과 새 참고자료일을 구분한다.

후속AI연결은 같은RR에서 새service 재계산, 날짜/공간단위/local/원자료의미를 담은 새allowlist·서버문장·근거ID·prompt/cache버전·FE evidence검증을 함께 변경한다. 최신 참고값을2023년 당시 사실이나 창업 유불리에 사용하지 않는다. 이AI변경은 세블록 표시의 필수 선행조건이 아니다.

## 10. 구현 순서와 기능별 커밋

이번 MD/README/CLAUDE/작업계획은 `docs(be): 위치에 연결되는 참고자료 표시 설계` 한커밋으로 묶는다. 후속 구현에서는 이설계를 다시 반복하지 않고 아래를 실행한다.

| 순서 | 변경 단위 | 구현/검증 완료 조건 |
|---|---|---|
| A | 공식 행정동local/경계 확보·artifact진단 | §3.1의dataset/artifact목록·코드차집합·실제 열/날짜/정밀도/24시간·점포함. 격자 임의집계로 대체하지 않음 |
| B | 4표·인덱스·조회권한/ETL·catalog | 별도clone에서migration/원문보존·날짜별적재·중복/결측/재실행 검증 |
| C | 매출 참고loader/projection·시험 | A/B와 독립실행가능. 분기별버전수·환경독립catalog·코드/유형차집합·실제금액일치·원자료basis/중첩비합산/정밀도 |
| D | 행정동local평균/주야간·새GET·시험 | 같은24시간/구역/날짜·모드선택·오류/성능. 새계약으로 세블록 응답 |
| E | FE전용타입/hook/카드·보고서연결 | 분석/종합/보고서·날짜/범위·취소/404호환·모바일/PDF |
| F | 실제적용·공개확인 | 매출은schema0012로 먼저독립공개가능. 인구4표는 §10.1 유지보수 전환·복구 검증후적용. 실제commit/DB판/관측일·결과기록 |

새GET의FE404호환을 준비하고, 기본은 자료/BE API 확인후FE를 연결한다. 매출만 먼저제공할때는0012를 유지하고 미적재인구는명시pending이다. 이후 인구릴리스에서head를전환한다. 기존AI의 FE선행배포#184와 구분한다.

### 10.1 head 검사와 인구 릴리스/복구

실제코드확인: `app/core/config.py`의기대revision기본값은0012다. `app/services/readiness.py:ReadinessProbe._probe`는 `/ready`에서현재head와기대값의정확일치를검사한다. 성공TTL10초/실패TTL1초이며 mismatch는500이다. `app/main.py` lifespan에는기동시head검사가없고 `app/db/dependencies.py`의업무세션에도head검사가없다. 따라서새DDL뒤구BE의업무읽기가가능해보여도 `/ready`는실패하므로무중단이라고가정하지않는다.

인구4표릴리스는 **최대15분 유지보수 단위**로정한다. 실제작업전clone에서예상시간/rollback시간이이범위안인지확인한다. 범위를넘으면전환을시작하지않고새절차를정한다. 작업순서는:

1. 새BE/FE호환빌드·고정artifact/catalog·백업복원·downgrade재현을사전완료한다. 기존LLM/키/CORS/pool설정은보존한다.
2. 쓰기/수집을중지하고읽기트래픽을유지보수상태로전환한다. 새4표는별도migration소유역할로생성하고앱reader에는SELECT만부여한다. 앱역할이표소유자/쓰기역할이되면안된다. 새DDL/권한적용뒤관리CLI로local자료/catalog지문을검증한다.
3. 새릴리스의모델/ETLguard와기대revision을새head에맞춘다. 프로세스설정에명시된기대revision도있으면동시에맞추되원래값을복구기록에보관한다. 원래.env는덮어쓰지않는다.
4. 새BE전환뒤성공TTL10초가지난새probe에서90초안에`/ready`3회성공과기존GET/새GET일치를확인한다. staging/production의`owns_objects/table_write/schema_create`등이없어`unsafe_role`이아닌지도검사한다. 전체15분을넘거나readiness/자료검증실패면FE공개를진행하지않고아래복구를실행한다. 실제종료시간은기록하며이계획이실제중단시간보장은아니다.
5. 새FE연결/브라우저검증을수행하고트래픽을재개한다.

복구는 한 가지 기본 절차로 고정한다: FE의 새 카드 사용 중지→새 BE/reader 정지→새4표의 version/hash/재적재 artifact 보존 확인→**이번 migration의 downgrade로 새4표/그 인덱스·부여 권한만 제거**→0012 확인→기대 revision 설정 원복/구 BE 재시작→TTL 후 `/ready`·기존 GET 확인→트래픽 재개. Alembic 관리 revision 이외의 기존 업무표·인허가·브랜드·원천 행은 변경하지 않는다. 재시도는 reupgrade/동일 artifact 재적재 hash 일치를 확인한 뒤 한다. 전체 DB 백업 복원은 이 기본 절차가 실패한 경우의 별도 사고 복구 수단이며 자동 실행하지 않는다.

#115는 전체인구/원천의미 검증, #78은 전체감사로 열린상태를 유지한다. 새 참고카드 구현으로 이둘을 전체완료 처리하지 않는다.

## 11. 필수 검증과 수용 기준

### 11.1 시험표

| 시험 | 필수 사례 |
|---|---|
| 실제PostGIS | 점내/경계상/완전외, 구멍·MULTIPOLYGON, 중복포함, 300/500/1000m내·접촉·직외, 중심점은 밖이나 도형교차상권, 떨어진 유사지명 미채택 |
| 공간/코드 | 동명별코드, 2016/현행코드차이, 다른boundary판의동일코드, code/type/name충돌, unlocated, 모르는경계시점표시 |
| 매출 | 원문int/API문자열일치, 2^53초과, 실제0/null/행부재, 중첩상권/관광특구비합산, 음식점4업종, 점포필터미적용, 미확정period를quarter_total로바꾸지않음 |
| 날짜 | 2023분석+2025/2026참고표시, 엄격월/분기결측, 구역별최신유효값, 완전일대체이유, 복수개정판모호성, 공개일unknown |
| 인구 | 행정동local24시간일치, 외국인결측에도local정상, 별표/빈칸/행부재/실제0, 중복거절, 24시간합을방문객으로사용하지않음, local/전체명칭구분 |
| 평균/비율 | Decimal정밀도, 주야간각12시간, 평균/구성비, 야간0/모두0, 반올림0, 대표인구와주야간area/date/source일치 |
| API/성능 | DB접근전입력검증422, read-only/RR·deadline/취소/연결반환, 손상catalog500/대상미적재no_data, 유효결측200, 상한not_supported, 허용외query거절, warm15회각≤6초·기존GET영향비교 |
| FE/보고서 | 세화면일치, 자료날짜/지역/내국인/범위, 긴상권명/복수행, 390/360px, 조건변경/취소/이전응답지연/재시도, 구BE404, PDF대기/페이지나눔, AI별도범위 |
| 운영 | 신구head/readiness비호환, migration/권한·적재hash/기존표불변, 실제복원/구BE복귀, Free공간·기존환경/키보존 |

추가필수사례: 포함동이있지만자료없을때실교차동표시/소속동승격금지, UUID가다른두clone의catalog지문해석일치, 소수6자리원천거부, FE에서2^53초과문자열보존, route부재404와정상오류구분, `새head→downgrade→구BE/ready정상→reupgrade/재적재hash일치`의실제clone검사와15분전환/90초readiness합격선실측.

매출전용0012DB/catalog에서매출ready/partial·인구와주야간`population_source_not_released`/인구SQL0/전체500없음을검사한다. 포함/교차목록중복제거·원천store지문차이·code_system복합FK거절·전reason/status조합과staging/production의비소유/SELECT전용역할도검증한다.

### 11.2 실제 자료 수용 검사

합성시험 통과만으로 표시완료 처리하지 않는다. 이전 검증과 같은 종류의15지점을 **주소/좌표를 공개하지 않는 검증artifact**로 다시 조회해 점포함·raw행→API→FE값 일치를 검사한다. 이번에 새15지점 검증을 실행한것은 아니다. 서로 다른행정동, 상권내/밖의반경교차, 중첩/경계, 지원업종/결측을 포함한다.

기준은 `공간상 해당하고 공개값이 있는 지점에서 세대표블록이 나온다`이다. 실제자료가 있는 대상점과 자료범위밖/원문미공개점을 나눠 제공률을 기록한다. 근거없이15/15를목표/실적으로 고정하지 않는다. 미표시이유는 `미구현/미수집/공간미대응/원자료비공개/기간없음/상한/버그`로 구분하고 수정가능한미연결을 장기pending으로 남기지 않는다.

## 12. 이번 실행과 Claude 검토 기록

- Codex: BE/FE코드 비교, 최신develop확인, 로컬DB READ ONLY메타, 공식4페이지 설명/파일목록을 확인했다.
- 실제Issue#186/독립worktree에 설계를 작성했다. FE/앱/DDL/DML/환경·기존서버/운영배포는 변경하지 않는다.
- Claude Code에는 이MD Read/Edit만 허용하고 필요한 **코드발췌·집계메타**를 전달한다. 관측원문·env/키/주소/좌표·DB/셸/네트워크/MCP/하위에이전트를 사용하지 않는다.
- 아래에는 실제 검토결과만 기록한다. PASS는 설계판정이며 미구현API/화면/자료제공·시험·배포의 성공이 아니다.

### 12.1 Claude Code 첫 검토

**판정: REVISE** (2026-11-16, Claude Code. 근거 범위는 이 MD 본문, 전달받은 코드 발췌(`market_activity`·`market_judgement`·`market_reference`·`market_sale`/`living_population` 모델·`population_reference`·`day_night`·`ai_population`·`population_context`·`etl/market_stores/archive` 일부·FE `market.ts`/`population.ts`/`ConditionalBlocks.tsx`/`optionalData.ts`/`interpretationContext.ts`), Codex가 전달한 로컬 읽기 전용 메타와 Codex가 확인했다고 한 공식 페이지 사실이다. Claude는 DB 조회, 다운로드, 시험, 배포, 공식 페이지 재확인을 하지 않았다. head guard·readiness·ETL 코드 원문은 받지 못했으므로 해당 동작은 본문 서술을 근거로 판단했다. 첫 검토이므로 처리할 이전 지적은 없다.)

사용자 우선순위(점 포함/반경 실교차 구역의 실제값 표시, 유사·비교차 최근접 지역 금지, 최신 참고자료는 실제 날짜·범위와 함께 표시, 8표 승인 게이트와 외국인 완전성 선행조건을 다시 두지 않음)는 §1·§1.1·§4·§5·§6에 맞게 반영되어 있다. 매출 원자료 금액을 월/분기 총액으로 표시하지 않는 처리(§6.1, 모델 CHECK `amount_period_status='unverified'`와 일치), `project_sales`에 `quarter_total`을 넣지 않는 원칙, `day_night.py` 재사용 조건(24시간 전부 non-None, 소수 5자리 이하), 기존 AI/FE 검증기(`interpretationContext.ts`의 분석월 안 관측일 검사, `ContextPopulationReference`)를 완화하지 않고 새 참고자료를 분리하는 처리, 행정동 공식 집계를 쓰고 격자를 역산하지 않는 처리, 결측과 0을 구분하는 상태 처리는 타당하다. 다만 아래 세 항목은 구현·배포 단계에서 실제로 막히거나 운영 오류가 날 수 있는 누락이므로 보완이 필요하다.

#### 차단(Blocking)

**B1. 행정동 도형·코드 체계 확보가 구체적인 판정 기준 없이 무기한 조건으로 남아 있다** (§3 마지막 단락, §10 A).
- 근거: 첫 공개의 필수 입력은 "내국인 행정동 자료+그 도형"(§3)인데, 어떤 경계 자료를 후보로 볼지, 무엇을 '코드 체계 일치'로 판정할지, 실패하면 어떤 상태로 출시할지가 정해져 있지 않다. "이미 포함 관계를 확인한 다른 실제 구역 자료를 사용할 수 있는지 검사한다"도 대상이 정해지지 않아 사용자가 금지한 막연한 게이트이거나 대체 구역 사용으로 읽힐 수 있다. 로컬 메타상 행정동 도형 테이블은 없다(`admin_tables: []`).
- 필요한 수정:
  1. §3/§10 A에 후보 경계 artifact를 **dataset ID 단위로 명시**하는 산출물을 둔다. 지금 특정하지 못하면 "A의 첫 산출물은 후보 dataset ID 목록과 각 코드 체계 설명 출처"라고 적고, 이 문서에서는 이를 확인된 사실로 쓰지 않는다.
  2. 일치 판정 기준을 수치로 정의한다. ① 선택한 관측일 OA-23016 local의 행정동 코드 집합과 도형 코드 집합의 차이(양방향)를 목록으로 남긴다. ② 일치로 인정하는 조건은 "원천 코드 전부가 도형에 정확한 문자열로 존재"하는 것이다. 차이가 있으면 해당 코드만 quarantine하고 `공간미대응`으로 표시하며, 나머지 동은 공개한다. ③ 보조 대조로 기존 격자 관측 행의 `admin_code`(CHECK `^11[0-9]{6}$`)와 격자 도형/중심점이 후보 행정동 도형에 실제로 포함되는지를 집계로만 비교한다. 같은 제공기관 코드가 같은 체계인지 확인하는 증거로 쓰되, 격자값을 행정동값으로 바꾸지 않는다.
  3. 실패 시 결과를 확정한다. 일치하는 도형을 확보하지 못하면 생활인구·주야간 블록은 `pending/admin_boundary_unmatched`로 출시하거나 출시를 보류한다. 이때 다른 구역 자료로 대체하지 않으며 "다른 실제 구역 자료 검사" 문장은 삭제한다. **매출 경로(C)는 A/B와 독립적으로 출시할 수 있다**고 §10에 명시해 인구 경계 문제로 매출 표시가 막히지 않게 한다.

**B2. 배포 순서와 고정 head guard가 충돌하며 rollback 절차가 불명확하다** (§10 F와 마지막 단락).
- 근거: 본문은 "구BE의 head가 0012 고정"이라고 쓰면서 F 순서를 "새DDL/권한→local자료/catalog→BE→FE"로 둔다. 구BE가 readiness나 요청 시점에 head 일치를 검사한다면 DDL 적용 순간부터 새 BE가 뜰 때까지 운영 BE가 비정상 상태가 된다. 복구도 "필요하면 … 관리 복원으로 호환head를 회복"으로만 적혀 있어 구체적이지 않다. Claude는 guard 코드를 받지 못해 검사 시점을 확인하지 못했다.
- 필요한 수정:
  1. guard가 실제로 검사하는 시점(기동 시/readiness/요청별)을 코드 위치와 함께 §10에 기록한다.
  2. 그 결과에 따라 "DDL+새 BE 전환을 하나의 유지보수 단위로 실행하고, 허용 중단시간과 readiness 실패 시 판단 기준을 둔다" 또는 "구BE가 기동 시에만 검사함을 확인했으므로 DDL을 먼저 적용해도 된다" 중 하나를 확정한다.
  3. rollback을 단일 절차로 확정한다. 권장안은 새 migration의 downgrade가 **새 4표와 그 인덱스·권한만** 제거하는 방식이다. 기존 표는 건드리지 않고, 재적재는 hash가 기록된 artifact로 다시 수행할 수 있다. 백업 복원을 택한다면 대상, 예상 시간, 복원 후 head·행수 검증 항목을 적는다. 이 절차를 clone에서 "새head→downgrade→구BE readiness 정상→재upgrade·재적재 hash 일치" 순서로 시험하는 항목을 §11.1 운영 행에 추가한다.

**B3. catalog가 환경별로 달라질 수 있는 version UUID에 의존한다** (§7.2 세 번째 단락, §5.1-1·5).
- 근거: catalog를 "BE 배포에 포함하는 JSON"으로 두고 "허용 version UUID"를 기록한다. version_id가 적재 시 생성되는 값이라면 local, clone, 운영의 UUID가 서로 달라 같은 BE 빌드가 운영에서 catalog 불일치(500 또는 pending)를 일으킨다. 기존 `market_sale_versions`, `market_area_versions`도 같은 문제가 있다. 로컬 메타의 매출은 분기별 행수만 있고 분기별 version 수는 확인되지 않았다.
- 필요한 수정: catalog 항목을 환경에 의존하지 않는 지문으로 정의한다. 예를 들어 `source_dataset, rule_version, input_sha256, content_sha256, row_count`와 경계의 `content_sha256`을 쓰고, RR 안에서 이 지문으로 UUID를 찾는다. 결과가 0건이면 `no_data/source_not_loaded`, 2건 이상이면 `pending/ambiguous_source_version`으로 처리하며 UUID 순서로 고르지 않는다. 또는 결정적 UUID(예: 지문 기반 uuid5)로 바꾸는 방안을 택하고 근거를 적는다. catalog 대상에 기존 매출·상권경계 version도 포함한다고 명시한다. A/C 단계에서 분기별 매출 version이 1개인지 집계로 확인하는 항목을 추가한다.

#### 비차단(Nonblocking) — 구현 전 반영 권장

- **N1 (§7.1 FK)**: `admin_population_hours`에 `boundary_version_id`를 두고 `(boundary_version_id, admin_code)→admin_areas` 복합 FK를 명시한다. 그러면 미매칭 코드는 DB에 들어올 수 없고 quarantine artifact에만 남는다는 규칙이 스키마로 보장된다. `admin_population_versions`에는 `(version_id, boundary_version_id, observation_date, source)` UNIQUE를 두고 hours가 이를 참조하게 한다(기존 `living_population_observations` 패턴과 동일).
- **N2 (정밀도)**: `Numeric(20,5)`와 `day_night.py`의 소수 5자리 제한에 맞춰, 원천 값의 소수가 5자리를 넘으면 importer가 반올림하지 않고 **거부**한다고 명시한다. 원천의 실제 소수 자릿수는 A 진단에 기록한다. `mean_24h`는 `day_night.py`에 없는 새 산술이므로 같은 Decimal context와 입력 검사를 쓰는 함수로 추가한다고 적는다.
- **N3 (포함 동 자료가 없을 때)**: §4.2는 "점 포함 도형이 없을 때만" 반경 교차 동을 제공한다. 포함 동이 존재하지만 완전한 local 날짜가 없거나 quarantine된 경우, 포함 동 행은 그 상태로 표시하고 실제 반경과 교차하는 동 중 값이 있는 동을 `intersects_radius`로 별도 표시할지 정해서 적는다. 사용자 우선순위상 표시하는 쪽을 권장한다. 이 경우에도 합산하거나 대표값으로 승격하지 않는다.
- **N4 (매출 코드·유형 대응)**: `MarketArea.market_type` 값(예: `tourism_zone`)과 `market_sales.market_type_code`(A/D/R/U)의 명시 대응표를 §4.1에 둔다. OA-15572의 "공간 단위 제공 기준 변경" 공지가 있으므로, 2025 매출 코드와 고정 경계 코드의 교집합/차집합(`code_check` JSON 근거)을 C 단계 산출물로 기록하고 그 차집합을 `excluded_count`의 사유별 건수로 노출한다.
- **N5 (FE 금액 표시)**: 기존 `SalesMarket.est_sales: number`, `unit` 예시 `"KRW/quarter"`, `formatKrwApprox(number)` 경로를 새 매출 카드에서 **재사용하지 않는다**고 §9.1에 명시한다. 새 카드는 서버 `display`만 표시하고 `value` 문자열을 Number로 바꾸지 않는다. 2^53 초과 값이 FE에서 그대로 유지되는지 확인하는 FE 시험을 §11.1에 추가한다.
- **N6 (analysis_period의 첫 출시 결과)**: 첫 출시는 최신 local 1개월과 2025 매출만 적재하므로 2023 분석의 `analysis_period`는 매출·인구 모두 `no_data/no_data_in_analysis_period`가 된다. 이것이 정상 결과임을 §5에 적고, 구계열(OA-14991, 2016 코드)은 별도 code_system과 도형을 확보하기 전까지 적재하지 않는다고 같은 위치에 연결한다.
- **N7 (404 호환 범위)**: "새 route 404 → 기존 pending 카드" 처리를 **route 부재**로 한정한다. 예를 들어 FastAPI 기본 404 본문이거나 ApiResponse error code가 없는 경우만 해당한다. 새 BE가 정상 응답으로 돌려주는 오류나 500/503을 구BE 호환으로 숨기지 않는다.
- **N8 (시험표 보완)**: §11.1에 ① 포함 동 존재 시 교차 동 처리(N3 결정대로), ② 환경별로 UUID가 다른 clone에서 catalog 지문 해석(B3), ③ head 전환 중 readiness(B2), ④ 소수 6자리 원천 거부(N2)를 추가한다. "DB전입력422"는 의미가 불명확하므로 "DB 접근 전 입력검증 실패 422"처럼 풀어 쓴다.
- **N9 (증거 구분 표현)**: §3 표와 §5.1 끝의 `202610`, `2023·2025 연도 파일`, `2016 코드`는 Codex가 공개 페이지 목록/FAQ로 확인한 사실이고 파일 내용은 확인하지 않았다는 점이 §3 첫 문단에 이미 적혀 있다. 다만 §1.1과 §6.1에서 "당월_매출_금액" 열 이름을 확정 사실처럼 쓰므로, 보유 ZIP의 열 이름(기존 ETL 근거)인지 현재 제공판의 열 이름인지 출처를 한 줄 덧붙인다.

#### 재검토 시 PASS 조건

B1~B3이 위 기준대로 본문(§3, §5.1, §7, §10, §11)에 반영되면 설계 판정을 PASS로 바꿀 수 있다. N 항목은 Codex가 채택하거나 근거를 남겨 보류할 수 있다. 이 판정은 설계 문서에 대한 것이며 구현·자료 적재·시험·배포 성공을 뜻하지 않는다.

### 12.2 Codex 보완·재검토

실제첫검토는10:51:41Z~10:54:21Z, exit0/is_error=false/3turns, 대상MD직접변경확인, 전달소스16개SHA보존, 권한거절0이다. REVISE차단3건과권고9건을읽고다음과같이처리했다.

- B1채택: §3.1에후보OA-22160/15147263과실제polygon확보의구분, A의첫산출물, 정확한코드교집합/양방향차집합·동별quarantine/부분공개를명시했다. 후보의공개설명/CSV형식을추가공식페이지조회로확인했으나polygon/코드동일성은아직미확보다. 격자보조대조는경계에걸친중심점만으로동일성을증명하지않도록제한했다. 인구자료와무관한매출독립구현/공개를명시했다.
- B2채택: 실제readiness/main/dependencies/config를추가로읽고기동/업무세션이아닌`/ready`의head검사와TTL을확인했다. 최대15분유지보수·90초probe검사와새4표만downgrade하는단일복구·reupgrade재적재실증을정했다. 이시간은향후clone합격선이며이미달성한실측이아니다.
- B3채택: catalog를환경별UUID에서불변내용지문으로바꾸고같은RR에서그환경의UUID/FK를해석하도록했다. 미적재/중복/손상상태를구분했다. 실제로컬READ ONLY를추가실행해각매출분기distinct version1개를확인했고§2.2에반영했다.
- N1~N2채택: hours의행정동/관측복합FK, 정밀도초과거부, mean_24h신규순수함수를명시했다.
- N3~N4채택: 포함동결측시실반경교차동을별도표시하고소속동으로승격하지않는다. 실제ETL의A/D/R/U유형표와코드차집합/제외사유를명시했다.
- N5~N7채택: 새매출은서버display/문자열타입을쓰고Number변환을금지했다. 최초2023엄격모드결측을명시하고404호환범위를route부재로한정했다.
- N8~N9채택: 추가시험과명확한422문구를반영했다. `당월_매출_금액`근거는실제로읽은기존ETL의fields.py이며현재웹파일을재다운로드한것이아님을명시했다.

위수정은설계본문보완이며원천추가수집/관측값검증/구현/배포를수행한기록이아니다. 보완본의실제Claude재검토를이어진행한다.

### 12.3 Claude Code 재검토

**판정: PASS (설계 판정)**, 2026-11-16, Claude Code.

**검토 근거와 한계.** 이번 판정은 다음 자료만 대조한 결과다.
- 이 MD 본문 전체(§1~§12.2)
- 재검토용으로 전달받은 코드 발췌: `market_activity` 스키마/서비스, `market_judgement`, `market_reference`, `market_sale`·`market_area`·`living_population` 모델, `population_reference`, `day_night`, `ai_population`, `population_context`, `readiness`, `main`, `db/dependencies`, `core/config`, `routers/health`, `etl/market_sales/fields.py`, `etl/market_areas/archive.py`, `etl/market_stores/archive.py` 일부, FE `market.ts`·`population.ts`·`ConditionalBlocks.tsx`·`optionalData.ts`·`interpretationContext.ts`
- Codex가 전달한 로컬 읽기 전용 메타: head 0012, 경계 1버전/1,650개, 매출 4개 분기 각 1버전, 관측 2026-11-07 1버전, 격자 1버전/10,125개, 행정동 표 없음
- Codex가 확인했다고 전달한 공개 페이지 사실(OA-15572, OA-23016, OA-14991, 아카이브)

Claude는 DB 조회, 다운로드, 공식 페이지 재확인, 시험, 배포, 승인 처리를 하지 않았다. `population_totals.py`, 매출 ETL 적재기, FE `PopulationReferenceView`/보고서 코드는 받지 않았으므로 이 부분은 본문 서술을 근거로 판단했다. PASS는 이 설계가 구현을 시작할 수 있는 수준이라는 뜻이다. API, 화면, 자료 적재, 시험, 배포의 성공이나 #115/#78 완료를 뜻하지 않는다.

#### 이전 지적(§12.1)의 처리 확인

| 항목 | 판정 | 확인 근거 |
|---|---|---|
| B1 경계·코드 체계 | **해소** | §3.1에 다음이 모두 있다: 첫 산출물(dataset ID·polygon artifact·코드 설명 출처·대조표), 후보 OA-22160/15147263과 "polygon을 확보해야 후보가 된다"는 구분, 정확한 문자열 기준 `P∩G`/`P-G`/`G-P`, 코드별 quarantine 후 나머지 동 공개, 실패 시 `pending/admin_boundary_unmatched`, 매출 독립 공개. "다른 실제 구역 자료" 문장은 삭제됐다(§3 끝은 대체 금지). 격자 보조 대조를 동일성 증명으로 쓰지 않는다는 제한도 있다. 무기한 게이트나 전체 동 100% 일치 요구로 남지 않았다. |
| B2 head guard·rollback | **해소** | §10.1의 서술이 전달 코드와 일치한다. ① `readiness._probe`가 `revisions != [database_expected_revision]`이면 `revision_mismatch`를 반환한다. ② TTL은 성공 10초/실패 1초다. ③ `/ready` 실패는 `INTERNAL_ERROR`다. ④ `main.lifespan`과 `read_only_session`에는 head 검사가 없다. ⑤ config 기본값은 `"0012"`다. 15분 유지보수 단위, 90초 readiness 확인, 새 4표만 제거하는 단일 downgrade 복구, reupgrade·재적재 hash 일치 확인, §11.1 운영 시험 추가도 반영됐다. |
| B3 catalog UUID 의존 | **해소** | §7.2·§5.1-5에서 catalog를 환경에 의존하지 않는 내용 지문(+경계 content/코드 체계)으로 정의했다. RR 안에서 UUID를 해석하고, 0건은 `source_not_loaded`, 복수는 `ambiguous_source_version`, 손상은 500으로 처리하며 UUID 정렬로 고르지 않는다. 기존 매출·상권 경계도 대상에 포함했다. 분기별 1버전은 전달 메타(각 분기 `versions:1`)와 §2.2가 일치한다. |
| N1 복합 FK/UNIQUE | 반영 | §7.1 hours의 version/date/source/boundary 복합 FK, `(boundary_version_id,admin_code)→admin_areas`, versions UNIQUE. 기존 `living_population_observations` 패턴과 같다. |
| N2 정밀도 | 반영 | §6.2: Numeric(20,5)·소수 5자리 초과 거부(반올림 없음). `day_night.py`의 `exponent < -5` 거부, `_INPUT_LIMIT=1e15`와 일치한다. `mean_24h`는 별도 순수함수로 둔다. |
| N3 포함 동 결측 시 교차 동 | 반영 | §4.2 네 번째 항목. 소속 동으로 승격하거나 합산하지 않는다. |
| N4 유형표·코드 차집합 | 반영 | §4.1. 표가 `market_areas` CHECK와 `etl/market_areas/archive.MARKET_TYPES`의 A/D/R/U 대응과 일치한다. |
| N5 FE 금액 경로 | 반영 | §9.1에서 `SalesMarket.est_sales:number`·`KRW/quarter`·`formatKrwApprox`를 재사용하지 않는다. §11.1에 2^53 초과 문자열 보존 시험이 있다. |
| N6 2023 엄격 모드 | 반영 | §5 표 아래 단락. |
| N7 404 호환 범위 | 반영 | §9.1 마지막 단락. |
| N8 시험 보완 | 반영 | §11.1 "추가필수사례"와 422 문구. |
| N9 열 이름 출처 | 반영 | §6.1 둘째 단락. 전달된 `fields.py`에 `당월_매출_금액`이 실제로 있다. |

사용자 우선순위와도 충돌이 없다. 다음 조건을 각각 확인했다.
- 점 포함 구역과 반경에 실제로 교차하는 구역만 사용하고, 유사 지역이나 반경 밖 최근접 지역은 금지했다.
- `latest_reference`는 실제 분기/관측일과 `temporal_relation`을 함께 표시한다.
- 8표 승인 게이트를 다시 두지 않았고, 외국인 완전성은 선행조건이 아니다.
- 매출 원자료 금액에 월/분기 총액 단위를 붙이지 않는다(`amount_period_status='unverified'` CHECK와 일치).
- local 24시간이 완전하지 않으면 평균/비율을 만들지 않고, 결측과 0을 구분한다.
- 기존 AI/FE 검증기(`ContextPopulationReference`의 분석월 범위, `populationContractMatches`)는 완화하지 않는다.

#### 남은 차단(Blocking)

없음.

#### 남은 비차단(Nonblocking): 해당 구현 단계(C/D/B/F) 착수 전에 반영해야 하며, 설계 판정을 막지는 않는다

- **N1. 매출만 먼저 공개(0012)할 때 인구 블록의 상태와 쿼리 경로가 정해져 있지 않다** (§10 F, §5.1-5, §3.1).
  - 근거: 0012에는 새 4표가 없다. 같은 빌드의 새 GET이 인구 블록에서 `admin_*` 표를 조회하면 `read_only_session`이 SQLAlchemyError를 500으로 바꾸고, 매출 응답도 함께 실패한다. 또한 본문 안에서 상태가 서로 다르다. §10은 "명시 pending", §5.1은 "catalog 미적재 = `no_data/source_not_loaded`", §3.1은 `pending/admin_boundary_unmatched`다.
  - 수정:
    1. catalog에 행정동 kind가 없으면 인구·주야간 블록이 DB 조회 없이 하나의 고정 상태를 반환한다고 명시한다. 예: `pending/population_source_not_released`.
    2. 이 상태를 `source_not_loaded`(catalog에는 있으나 DB에 없음)와 `admin_boundary_unmatched`(적재했으나 코드 미대응)와 구분한다.
    3. §11.1에 "0012 DB + 매출 전용 catalog에서 매출 ready/partial, 인구 고정 pending, 500 없음" 시험을 추가한다.
- **N2. reason 코드가 본문 여러 곳에 흩어져 있다** (§3.1, §4, §5, §6.2, §8.2).
  - 수정: §8.2에 블록·행별 `reason` 허용 목록을 한 표로 고정한다. 대상은 `outside_coverage`, `admin_boundary_unmatched`, `source_not_loaded`, `ambiguous_source_version`, `no_data_in_analysis_period`, `no_complete_day`, `zero_night_population`, `scope_too_large`, `mapping_conflict`, N1의 신규 코드다. 각 코드가 허용하는 `status`도 함께 적는다. FE 문구 매핑과 시험이 이 표를 기준으로 한다.
- **N3. `observed_hour` 보조 항목이 응답 계약에 없다** (§6.2 마지막에서 둘째 단락과 §8.2).
  - 수정: `living_population.items[]`에 `observed_hour{hour,value,display,...}` nullable 필드를 정의하거나, 첫 구현 범위에서 이 보조 항목을 제외한다고 적는다. 정의하는 경우 같은 날짜 안의 단일 시각임을 표시하고, 주야간 블록에는 사용하지 않는다고 명시한다.
- **N4. 공간 술어와 목록 중복 규칙을 보완해야 한다** (§4.1, §4.2).
  - 근거: 행정동 `intersects_radius`의 술어가 적혀 있지 않다. 매출 쪽은 `ST_Covers` 결과도 거리 0이므로 반경 목록에 다시 잡힌다. 기존 `market_judgement`는 covering이 없을 때만 nearby를 계산하므로 그대로 재사용하면 두 목록을 동시에 얻을 수 없다.
  - 수정:
    1. 행정동 반경 교차도 매출과 같은 `geography ST_DWithin` 사전 필터 + `ST_Distance(polygon,point)≤radius`(도형 기준, 중심점 아님)로 명시한다.
    2. 두 경우 모두 `intersects_radius`에서 `contains_point`로 이미 반환한 코드를 제외한다.
    3. 매출은 covering 여부와 관계없이 두 목록을 함께 조회하는 새 함수로 구현하며, `classify_markets`의 primary 판정은 사용하지 않는다.
- **N5. 코드 체계 일치를 스키마로 보장하지 않는다** (§7.1).
  - 근거: `admin_population_versions.code_system`과 참조 경계의 `code_system`이 다를 수 있다.
  - 수정: `admin_boundary_versions`에 `UNIQUE(boundary_version_id, code_system)`을 두고 population versions가 `(boundary_version_id, code_system)` 복합 FK로 참조하게 한다. 구계열 2016과 현재 계열을 섞는 적재는 DB에서 거부된다.
- **N6. 매출 catalog 지문에 store 버전이 빠져 있다** (§7.2).
  - 근거: `market_sale_versions` UNIQUE에는 `code_check_store_version_id`도 들어 있다. 같은 입력/규칙의 매출 버전이 서로 다른 store 버전을 참조하면 지문이 같은 복수 버전이 되어 `ambiguous_source_version`으로 막힐 수 있다.
  - 수정: 매출 kind의 지문에 참조 store 버전의 내용 지문을 포함하거나, 이 필드를 의도적으로 제외한 근거와 복수일 때의 처리를 적는다.
- **N7. readiness의 운영 역할 검사를 §10.1에 추가해야 한다**.
  - 근거: staging/production의 `_probe`는 앱 역할에 `owns_objects`, `table_write`, `schema_create` 등이 있으면 `unsafe_role`을 반환한다.
  - 수정: §10.1 2단계에 다음을 명시한다. 새 4표는 앱 역할이 아닌 migration 소유 역할로 생성하고 앱 역할에는 SELECT만 부여한다. 4단계 readiness 3회 성공에는 `unsafe_role`이 아님도 포함한다. §11.1 운영 행에 해당 검사를 추가한다.

#### 증거 구분 확인

- §3 표의 `202610`, `2023·2025 파일`, `2016 코드`, `2026-07-31 생산 종료`는 Codex가 공개 페이지의 목록/FAQ로 확인한 사실이다. §3 첫 문단과 §5.1 끝에 "ZIP 미다운로드·내용 미검증"이 명시되어 있어 내려받은 파일 증거와 혼동되지 않는다.
- §11.2의 15지점 검증과 §10.1의 15분/90초는 미실행 합격선으로 적혀 있으며, 실적으로 기술되지 않았다.

#### 결론

B1~B3은 본문에서 구체적인 기준으로 해소됐고 새 차단 항목은 없다. N1~N7은 해당 단계(N1·N2·N4: C/D, N3: D, N5·N6: B, N7: F) 착수 전에 Codex가 본문에 반영하거나 보류 근거를 §12.4에 남긴다. 이 PASS는 설계 문서에 대한 판정이다. 공식 자료 내용, 경계 코드 동일성, 구현, 시험, 배포는 아직 확인되지 않았다.

### 12.4 Codex 최종 확정·검증

실제재검토는10:56:52Z~10:58:35Z, exit0/is_error=false/4turns, MD직접변경·소스24개SHA보존·권한거절0으로**PASS/차단0**이었다. 1차차단3건해소에이견없다.

2차권고N1~N7도모두채택했다. 인구kind미공개시SQL없이`population_source_not_released`, reason/status표, observed_hour첫범위제외, 양쪽공간술어/중복제거·새loader, code_system복합FK, 매출의참조store내용지문, migration소유자/reader역할을본문에반영했다. 이마지막세부반영은Codex최종검토이며Claude가또다시검토한것으로기록하지않는다.

이번에는문서4개만변경한다. UTF-8/LF·상대링크·미완료검토표식·비밀값미포함·diff공백·범위를검사하고정확한문서head의PR/CI결과를연결한다. 앱/FE기능시험을새로통과했다고쓰지않으며기존배포/로컬서버/DB0012·원자료/환경과사용자미추적파일은유지한다.

**다음실행시작점:** C의매출전용API구현과A의행정동local/실제polygon확보를독립진행한다. A에서코드/24시간자료가확인되면B/D로이어가고, 세값출력완료는실제자료→새API→FE/보고서검증후판정한다. 이문서의완료는기능활성화완료가아니다.
