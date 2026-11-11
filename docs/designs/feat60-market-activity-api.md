# BE-22 기본 상권 활동 분석 API (#60)

- 기준 develop b9584c3 / feat#60-market-activity-api / 2026-11-12
- 상태: Codex 설계 작성 → Claude 실제 MD 수정 완료(7절 기록) → Codex 최종 점검 후 구현한다.
- 이번 범위: 인허가 기반 기본 집계와 요청 선택항목의 정직한 미산정 상태. 조건부 수치 활성화는 후속이며 BE-22 전체 조건부 결합 완료로 표시하지 않는다.

## 1. 다음 작업과 실제 의존관계

사용자가 시스템 점검 PR59 이후 다시 다음 작업을 요청했다. BE-21 #57의 공정위 API는 재확인해도403/오류30이므로 적재·브랜드 매핑을 계속 대기한다. 누락 자료로 그 기능을 구현하거나 개인매장으로 대체하지 않는다.

독립적인 다음 작업으로 BE-22 기본 지표를 진행한다. 로컬 원본 `06_API명세서_SpotON_v1.2_최종.pdf` **9쪽 §4-6**, `07_데이터활용명세서_SpotON_v1.2_최종.pdf` **8쪽 §3.9**·선택 자료 정의, `08_분석로직정의서_SpotON.pdf` **4쪽 §4-6**을 실제 읽었다. 브랜드 D-13은 선택이며 미구현 시 is_franchise=null이라고 되어 있다. 따라서 브랜드가 필요한 매핑/확정 구분은 중단하되, 현재 unknown과 독립 토글을 보존하는 기본 개폐업 집계는 브랜드 원천 없이 수행 가능하다. 원천 없는 숫자로 앞 단계를 우회하는 것이 아니다. 이 판단은 Claude에게 검토받는다. 원본/추출문/실데이터/키는 커밋하지 않는다.

**Claude 검토 반영(브랜드 독립성):** 기본 요청(가맹 필터 미지정·unknown 포함)의 집계는 is_franchise 값을 읽지 않으므로 BE-21과 독립이다. 단, 가맹/개인 값을 고르는 필터는 BE-21 미완료로 is_franchise가 대부분(또는 전부) null인 상태에서 사실상 빈 집합을 만들 수 있고, 그 결과의 0은 "점포 없음"이 아니라 "분류 원천 없음"이다. 따라서 이번 릴리스는 nearby와 같은 필터 의미를 그대로 유지하되(필터 의미를 새로 만들지 않음), 응답에 `meta.franchise_classification={status:"pending",reason:"brand_mapping_blocked"}`를 BE-21 완료 전까지 상수로 항상 제공하고 FE 요청서에 가맹 필터 사용 시 0을 사실로 표시하지 않도록 요청한다. 브랜드 매핑·추정 가맹 판정·unknown의 independent 재분류는 하지 않는다. nearby가 이미 같은 목적의 표시를 갖고 있으면 Codex는 새 키 대신 그 표현을 재사용한다.

## 2. 원본·현재 계약 대조

| 항목 | 적용 |
|---|---|
| endpoint | GET /api/market/activity, 공통 {data,meta,error} |
| 입력 | NearbyQuery의 lat/lng/category/radius/sub_category/as_of/area/franchise/unknown 토글 전체 + include 선택 |
| 입력 오류 | 현재422 INVALID_PARAM·category 누락/부적합 CATEGORY_REQUIRED 우선, no-store |
| 날짜 | 최신 월은 전역 검증 갱신일D, 과거 월은 월말T. data-range와 같은 최소 월·범위 검사 |
| 거리 | 현재 geography ST_DWithin(radius+0.01) 후보·반올림 전 ST_Distance<=radius 최종 |
| 최근12개월 | 인허가/폐업일 각각 `(T-12calendar_months,T]`. 같은 월일에서 존재하지 않는 날짜만 clamp |
| 연도별 | 원본v1.2의 각연도1월1일~T와 같은 월일까지, T 이후 기록 제외. 연간 전체와YTD 혼동 금지 |
| 업종별 | T에 유효한 인허가 점포 수·T까지 평균 영업개월. 최신 상태와 과거T를 혼동하지 않음 |
| 선택 자료 | sales/living_pop 키는 항상 존재. 요청하지 않았거나 미산정이면null. flags.missing은 **요청했으나 미산정인 것만** |

원본의 지원 업종 확대·공통meta 전체 동기화·일반504 등은 이 작업에서 일괄 반영하지 않는다. 현재 사용자/BE 규칙이 우선이다. 현 FE는 src/types/market.ts·api/market.ts·ActivitySection 경로를 읽기만 했다.

## 3. 코호트와 계산

### 공통 모집단C

current_provenance(session)의 검증된 전체배치와D를 사용한다. temporal_cohort(query,D)는 지원 원천/업종·review/deleted 제외·is_temporary 제외·유효한 개폐업일·미래/역전/모든 날짜 플래그 거절을 재사용한다. minimum은 같은 업종의 비공간 코호트에서 계산해 effective_date(D,minimum,as_of)로T를 정한다.

C는 위 조건+attribute_filters(query)+open_date<=T+유효 geom의 반경 조건이다. **현재 get_spatial_stores 결과를 재사용해 집계하면 안 된다.** 해당 함수는 T에 이미 폐업한 점포를 제거하므로 폐업 수/개업 추이가 사라진다. 조건 함수만 재사용하고 Store.id/source/license_no/open_date/close_date/sub_category 최소 열을 조회한다. source+license_no 중복/날짜·업종 불변식 위반은 안전한500(no-store), 부분 결과 없음.

- 최신 영업상태는 집계에 필터하지 않고 날짜 구간을 따른다. T에 active는 open_date<=T AND (close_date IS NULL OR close_date>T)이며 현재other/과거시점 후폐업도 동일 규칙이다. 이것은 인허가상 유효 집합이며 실제 현장 영업을 확정하지 않는다.
- 면적0은unknown·가맹null은unknown, 개별 토글과legacy 혼합 거절도NearbyQuery와 같다. unknown 제외 시 미확인 점포는 제외되지만 independent로 재분류하지 않는다.
- 좌표 미확보 수는 같은 비공간 조건+open_date<=T의 서울 전체 행 수이며 meta.excluded_no_coord_scope=seoul_nonspatial_cohort로 표시한다. C와 합산하거나 반경 내 누락으로 표현하지 않는다. 이 수는 T 이전 폐업 행을 포함하므로 nearby/snapshot(T 시점 유효 집합)의 excluded_no_coord와 값이 다를 수 있다. 같은 키 이름이라도 코호트가 다름을 `meta.excluded_no_coord_cohort=opened_by_as_of`로 구분하고 FE 요청서에 적는다.
- 날짜 검증 코호트의 한계: 개업일이 없거나 플래그된 행, 폐업일만 플래그된 행은 C에서 빠지므로 개업·폐업 **사건 수도 함께 빠진다**. 따라서 사건 수는 "검증된 날짜를 가진 보관 인허가 기록의 사건 수"이며 전체 실제 개폐업 수가 아니다. `meta.event_basis=validated_license_dates`로 표시하고 제외 건수를 사건 수에 더하거나 추정하지 않는다.
- meta.denominator는 **null**이다. 이 응답에는 비율 지표가 없고 len(C)는 어떤 지표의 분모도 아니므로 분모로 표기하면 오해를 만든다(data-range와 같은 처리). 평균의 분모는 업종별 open_count이며 `meta.avg_operating_months_denominator=open_count`로만 설명한다. 내부 불변식 검사에는 len(C)를 쓰되 공개 필요 시 별도 이름(cohort_size)으로만 제공한다.

### 최근12개월

하한 lower는 **1년 전 같은 월일**이며 그 날짜가 없을 때만 clamp한다. T=2025-02-28→2024-02-28, T=2024-02-29→2023-02-28이다. Codex 최종 점검에서 원본의 T-12개월과 PostgreSQL interval의 같은 월일 의미를 따른다. 윤년을 가로지르는 달력1년이366일인 것은12개월+1일이라는 뜻이 아니다. 전체 월 묶음을 세는 별도 월말 정렬은 추가하지 않는다. Claude의 월말 제안과 다른 최종 결정은7.3절에 기록한다.

C에서 lower<open_date<=T, lower<close_date<=T를 따로 센다. 개업일이 lower 이전이고 폐업일이 구간 안인 점포는 폐업 1건으로 센다. 같은 날 개업·폐업(open_date=close_date, 역전 아님)은 개업·폐업 사건 모두 세고 어떤 T에도 active가 아니다. 폐업 당일은 active에서 제외한다(close_date>T 규칙). `period="(YYYY-MM-DD, YYYY-MM-DD]"`로 실제 lower/T를 명시한다.

### yearly_trend

C의 개업/폐업 사건을 연도별로 보되 각 Y마다 [Y-01-01, cutoff_Y]인 사건만 세고 Y<=T.year다. cutoff_Y는 원본 v1.2의 "같은 월일" 문구를 그대로 따라 Y-(T.month)-(T.day)이며, Y에 그 날짜가 없을 때(2/29)만 Y의 2/28로 clamp한다. T=Y년이면 cutoff는 T 자신이고 T 이후 사건은 제외한다. 12/31은 연간 전체다.

- 연간 전체와 YTD를 혼동하지 않도록 `meta.yearly_comparison_basis=same_month_day_ytd`, 각 연도의 실제 cutoff를 `meta.yearly_periods`로 제공한다.
- 알려진 1일 비대칭: T가 윤년 2/29이면 그 해만 다른 해보다 1일 길고, T=비윤년 2/28이면 윤년 Y는 2/29 하루가 빠진다. 원본 문구(같은 월일)를 임의로 월말 규칙으로 바꾸지 않고 이 한계를 기록한다. 최근12개월의 월말 규칙과 다른 이유는 최근12개월은 "12개월 길이"가, 연도별은 "같은 월일 비교"가 원본 정의이기 때문이다.
- 반환 연도는 **C의 T 이하 개업/폐업 사건이 실제 있는 연도만** 오름차순으로 반환한다. 해당 연도에 사건은 있지만 YTD cutoff 뒤에만 있으면0/0도 가능하다. 사건 자체가 없는 중간 연도·현재 연도를 생성하지 않는다. 원본 §4-6의 "데이터가 있는 연도만"을 우선하며 FE는 없는 연도를 관측0으로 채우지 않는다. C가 비면[]이다. Claude의 연속 연도 제안과 다른 최종 결정은7.3절에 기록한다.
- 이른 연도의 한계: 보관 인허가 자료가 오래전 폐업 점포를 모두 보존한다는 근거는 확인되지 않았다(data-range 문서와 같은 한계). 과거 연도 수치는 "보관 기록 기준"이며 실제 당시 전체 개폐업 수라고 주장하지 않는다. 원본 §4-6에 반환 연도 수 제한이 명시되어 있으면 Codex가 그 값을 따르고, 없으면 위 연속 범위를 사용한다.

### by_sub_category

선택 업종 순서는 cafe 또는 korean/chinese/japanese/western의 고정순서이고 선택된 항목을 모두 반환한다(sub_category 지정 시 그 항목만). C 중 active at T인 점포를 업종별로 센다. 각 점포의 경과기간은 기존 complete_months(open_date,T)이며 과거 T 이후 기간을 넣지 않는다. open_count=0이면 avg=null, 실제 0개월은 0이다.

- 평균은 **완료 달력 개월 합//open_count**인 정수 개월로 반환한다. 원본 분석 정의서 §2의 기간 소수점 버림·§5의 n년 m개월 표시, 기존 달력 완료 개월 규칙을 우선해 HALF_UP/소수1자리로 새 표시 기준을 도입하지 않는다. 완료 개월 평균을 정수로 다시 버리므로 원래 경과 일수의 평균보다 짧아질 수 있다는 한계를 명시한다. 부동소수점 연산은 쓰지 않으며 `meta.avg_operating_months_rounding=floor_mean_of_completed_months`다. Claude 제안과 다른 최종 결정은7.3절에 기록한다.
- 의미 한계: 이 값은 **T 시점 영업 중 점포의 경과 개월 평균**(우측 절단)이며 폐업 점포의 실제 영업 수명 평균이나 생존 기간이 아니다. 오래 살아남은 점포 위주로 길어지는 생존 편향이 있다. `meta.operating_period_basis=elapsed_months_of_active_at_as_of`로 명시하고, 폐업 점포 수명 평균·생존율은 BE-26 범위로 남긴다. 기존 history/nearby의 latest_data 기간은 변경하지 않는다.
- 불변식: Σ open_count = C의 T 시점 active 수 = 같은 입력의 nearby/snapshot 행 수(같은 공간·속성·날짜 조건일 때).

## 4. 선택 항목과 미확인 조건

현재 매출14,391행·생활인구531,922행은 적재되어 있으나 수치 활성화의 의미/시점 근거는 아직 부족하다. BE-18은 amount_period_status/boundary_compatibility=unverified·집계기간미확인, BE-19는 grid_as_of=null·spatial_compatibility=unverified·동일 격자의 복수행정동 합산 의미 미확인이다. 파일 존재만으로 이 API의 분기 매출이나 하루 고유 인구 합계를 만들지 않는다.

- include는 sales/living_pop의 쉼표목록, 중복/빈토큰/미지원 값은422, 미제공이면빈목록. 대소문자·앞뒤 공백은 정규화하지 않고 정확한 소문자 토큰만 허용한다(기존 목록 파라미터 파서가 있으면 그 규칙을 따른다). include는 기본 집계 수치에 영향을 주지 않는다.
- data.sales/data.living_pop은 이번 릴리스에서항상null이다. requested∩미산정만 flags.missing에정해진 순서(sales,living_pop)로 넣는다.
- meta.optional_data는 요청항목만 포함하고 `{status:"pending",reason:...}`를 제공한다. sales reason=source_period_and_boundary_unverified, living_pop reason=population_aggregation_and_grid_time_unverified. 원천구조 검증대기와 특정코호트결측no_data를 혼동하지 않는다.
- 이 릴리스의 Pydantic sales/living_pop 타입은 None으로 고정하고 상세 수치모델을 가짜로 구현하지 않는다(Claude 검토로 확정). 키는 항상 존재해 응답 형태는 원본의 동일 스키마를 유지하고, 기존 FE의 object|null은 실제 null과 호환된다. 후속 활성화에서 `Block|None`으로 넓히는 것은 FE가 이미 object|null을 처리하므로 추가 호환 변경이다. 지금 빈 블록 모델을 미리 정의하면 미확인 원천 의미(매출 기간·인구 합산)를 스키마로 선점하게 되므로 하지 않는다. OpenAPI 설명에 "이번 릴리스는 항상 null, meta.optional_data 참조"를 적는다.
- pending은 "원천은 적재되었으나 이 API 집계 의미가 미검증"이라는 뜻이며 no_data(검증된 집계에서 특정 코호트 결측)나 원천 미확보와 구별한다. 미요청 항목은 null이지만 pending/missing으로 표시하지 않는다(요청하지 않은 것은 결측이 아님).
- flags.missing에미요청 항목까지 넣는 현FE mock은 원본v1.2와차이가있으므로 수정요청에기록한다. flags.missing 자체를 바꾸거나 mock숫자를BE에넣지않는다.

## 5. 구현·응답·실패 계약

- schemas/market_activity.py: ActivityQuery(NearbyQuery확장), RecentActivity/YearlyActivity/SubCategoryActivity/ActivityFlags/MarketActivity strict 모델. 숫자0이상·중복년/업종/플래그·분모/nullable 불변식 검증.
- services/market_activity.py: 날짜/순수집계함수+공통조건기반DB조회+meta/검증. 데이터 행은외부로그/응답에내보내지않는다. 공개값은집계뿐이다.
- routers/market.py: parse_spatial_query와history_session을재사용해입력검증후DB연결, REPEATABLE READ READ ONLY/timeout/500 no-store·CORS유지. PARAMETERS의복사본+include만OpenAPI에추가한다.
- main.py에router등록. migration/기존모델·DB head0009/기존조회API행동변경없음. service의ValidationError/불변식위반은 AppError(INTERNAL_ERROR,NO_STORE)이며 원문노출없음.
- 새 rule_version=market-activity-license-ytd-v1, 출처R5/R6·배치목록·D와실제T·collected_at=null을사용한다. sales/living_pop 수치가없는데R3/R4의실측집계처럼topmeta.source를섞지않는다.

## 6. 검증과 완료 기준

일반: 12개월양끝·윤년clamp·같은월일YTD/미래차단·같은날개폐업·active평균/0분모/0개월·선택업종·include미요청/중복/문법·반환불변식·실패비노출·DB접속전422·OpenAPI.

추가 필수 사례(7.3 최종 결정): T=2025-02-28→lower2024-02-28, T=2024-02-29→2023-02-28,3/31→전년3/31,월중3/15→전년3/15. lower 당일 제외·T 포함, lower 이전 개업+구간 안 폐업, open=close 개폐업 모두1·active0. yearly cutoff의2/29비대칭·실제 사건 연도만/사건은있지만YTD0인연도·빈C. 평균0.5버림·0분모null/실제0개월. 요청항목과pending·missing순서, denominator=null·franchise_classification=pending, 필터별 nearby active집합 일치.

격리PostGIS: 499/500/501m·rounding전경계·폐업이벤트보존/과거T노미래기간·필터/unknown독립성·excluded좌표서울범위·source복합식별·배치미준비500·READ ONLY·모델오류안전500·nearby/snapshot와동일active집합. 합성데이터만사용한다.

실제DB: API기본/과거/필터10조합의독립SQL대조,기존API회귀·모델차이0·head0009·기존14테이블hash/건수보존. 파괴적suite는임시DB,개발DB는조회만. ruff/format·mypy·전체일반/격리테스트·CI/CodeQL을통과한다.

FE는BE저장소에 docs/fe-market-activity-api-request.md로계약/기간/평균/선택항목사유를요청하고코드/문서/이슈/PR은수정하지않는다. 이슈60범위완료는기본집계·선택상태까지이며BE-21/조건부수치전체활성화/FE통합은대기다. 지정양식의정확한4체크문구·사용자확인/조건부해당없음설명은기존지시를따른다. FE·BE CLAUDE.md양쪽동기화는미완료라고명시한다.

커밋은 설계/검토→모델/순수집계+일반테스트→라우트/DB조회+통합테스트→실제검증/FE요청·BE문서다. PR제목 `feat: 인허가 기반 상권 활동 분석 API 구현`, close #60, develop일반Squash자동병합이다.

## 7. Claude 실제 검토 요청

이MD만Read/Edit로직접수정하고근거/보류를남긴다. 다른파일·코드·Git·DB·네트워크·.env는접근하지않는다. 브랜드대기와독립기본집계의범위,폐업행보존/YTD/과거평균/분모·unknown,조건부null과pending이정직한지,고정None스키마vs미래블록,기존계약호환·테스트허점을검토한다. 원천미확인값을추정하지않고통상설계선택은최선안으로결정한다. 실제코드를읽지않은한계를명시하고Codex최종검토로연결한다.

### 7.1 Claude 검토 결과(2026-11-12, 이 MD만 Read/Edit)

| # | 검토 항목 | 판단 | 반영 |
|---|---|---|---|
| 1 | BE-21 대기와 독립성 | 기본 집계는 is_franchise를 읽지 않으므로 독립 진행이 타당하다. 그러나 가맹/개인 필터는 분류 원천이 없어 빈 결과의 0이 사실처럼 보일 위험이 있다. | 1절: 필터 의미는 nearby와 동일 유지, `meta.franchise_classification=pending` 상수, FE 요청. 브랜드 매핑·재분류 금지 유지 |
| 2 | 최근12개월 하한 | 기존 "1년 전 같은 월일+2/29 clamp"는 월말 T=비윤년 2/28일 때 12개월+1일이 된다. | 3절: 월말 T는 12개월 전 월말, 월중 D는 같은 월일+clamp |
| 3 | YTD cutoff | 원본 v1.2 "같은 월일" 문구를 따르는 기존안 유지. 2/29 관련 1일 비대칭은 원본 정의상 불가피하다. | 3절: 비대칭을 한계로 명시, 월말 규칙으로 임의 변경하지 않음 |
| 4 | 연도별 반환 범위 | "사건 있는 연도만"은 중간 연도의 실제 0을 지워 추이를 왜곡한다. | 첫 사건 연도~T.year 연속, 중간 0 포함, 이전 연도 생성 금지 |
| 5 | 사건 수의 모집단 | 날짜 플래그 제외가 사건 수에도 적용된다는 점이 드러나지 않았다. | `meta.event_basis=validated_license_dates`, 전체 실제 개폐업 수 주장 금지 |
| 6 | 평균 영업개월 반올림 | `합//n`은 내림된 완료 개월을 다시 내림해 편향된다. | Decimal 평균+ROUND_HALF_UP, 정수/소수1자리는 원본 타입 확인 후 고정 |
| 7 | 평균 영업개월 의미 | T 시점 영업 중 점포의 경과기간(우측 절단·생존 편향)이며 수명 평균이 아니다. | `operating_period_basis=elapsed_months_of_active_at_as_of`, 수명·생존율은 BE-26 |
| 8 | meta.denominator=len(C) | 비율 지표가 없는데 분모로 표기하면 오해된다. | null로 변경, 평균 분모는 별도 meta |
| 9 | excluded_no_coord | 활동 코호트는 T 이전 폐업 포함이라 nearby 값과 다르다. | `excluded_no_coord_cohort=opened_by_as_of`로 구분 |
| 10 | 선택 자료 null/pending | 적재됨≠집계 의미 검증이라는 pending 사유가 정직하다. 미요청 항목을 missing에 넣지 않는 것도 원본과 맞다. | 유지, pending/no_data/미요청 구분 문장 보강 |
| 11 | None 고정 스키마 vs 미래 블록 | 키 항상 존재+None 고정이 최선. 빈 블록 모델은 미확인 의미를 선점한다. 후속 Block\|None 확장은 FE object\|null과 호환. | 4절 확정 |
| 12 | 테스트 허점 | 월말 하한·하한 당일·구간 이전 개업 후 구간 내 폐업·연속 0 연도·반올림 경계·미요청 null 사례가 없었다. | 6절 추가 |

### 7.2 보류·한계

- Claude는 코드·원본 PDF·FE·DB를 읽지 않았다. temporal_cohort/attribute_filters/complete_months/effective_date의 실제 시그니처와 동작, nearby가 가맹 분류 미확보를 이미 표시하는지, 현재 is_franchise non-null 건수, 원본 §4-6의 평균 필드 타입·연도 수 제한·필드명은 **Codex가 최종 점검에서 실제 확인**해야 한다. 확인 결과가 이 MD와 다르면 원본·현행 계약을 우선하고 차이를 이 절에 기록한다.
- open_date=close_date 행이 temporal_cohort에서 역전으로 거절되는지 확인하지 못했다. 거절된다면 같은 날 개폐업 사례는 사건 수에서 빠지며 그 사실을 event_basis 설명에 추가한다.
- 보관 인허가 자료의 과거 폐업 기록 완전성, 개폐업일의 실제 의미(인허가일=실제 개점일 여부)는 미확인이며 추정하지 않는다.
- 매출 집계 기간·생활인구 합산 의미·격자 적용 시점이 확인되기 전까지 sales/living_pop은 null/pending으로 유지한다. 이번 이슈를 BE-22 조건부 결합 완료로 표시하지 않는다.
- 새 meta 키(franchise_classification, event_basis, excluded_no_coord_cohort, avg_operating_months_rounding)는 FE 합의 전 BE 제안이며 FE 요청서에 함께 적는다. 공통 meta 전체 정리는 별도 작업이다.

### 7.3 Codex 최종 점검·최종 규칙

Claude JSON is_error=false·11turns·permission_denials0과 실제 diff 전부를 확인했다. 브랜드 미확보 독립성·unknown 유지·필터0의 분류 미확인 안내·평균의 우측 절단/생존 편향·denominator=null·사건/좌표미확인 코호트 구분·선택 항목 None/pending을 채택했다. 실제 DB의 is_franchise/brand_id non-null은 각각0건이며 nearby에는 별도 분류 상태meta가 없어 이번 endpoint에 명시한다. temporal_cohort는 close_date>=open_date를 허용하므로 당일 개폐업 사례는 유지된다.

원본을 읽지 않은 검토의 조건부 제안3개는 실제 원본/현재 규칙 대조 후 조정했다. ① T-12개월은 같은 월일 clamp이며 윤년을 끼는1년은366일일 수 있다. ② 원본은 데이터가 있는 연도만 반환하므로 무사건 중간 연도를 생성하지 않는다. ③ 기간의 소수점 버림·n년 m개월 표시를 유지해 정수 개월 평균을 버린다. 세 항목은 본문의 최종 규칙과 테스트 기대값에 반영했으며7.1은 검토 이력이다. FE 변경 요청에 기준·분모·YTD0과미존재연도·내림 한계를 전달한다. 규칙을 임의의 시연 수치로 맞추지 않는다.
