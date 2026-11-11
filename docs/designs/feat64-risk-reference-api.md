# BE-23/25/26 Risk 참고지표 API (#64)

- 기준 develop `1cb88e2`, `feat#64-risk-reference-api`, 2026-11-12
- 상태: Codex 설계 → Claude 이 MD 실제 Read/Edit → Codex 원본 대조·최종 결정 후 구현
- 범위: GET /api/risk의 인허가 참고 폐업률·동종업체 수·고정 기간 생존율 및 같은 조건 서울 비교. 공식/조건부 수치·AI·FE 통합은 후속.

## 1. 원본 대조와 확정할 선택

로컬 API v1.2 §4-7(10쪽)·분석 정의 §4-7을 읽었다. 폐업률은 기간 중 영업한 인허가 기록을 분모로 하며 실제 폐업률·창업 성공확률로 확대하지 않는다. 원본 API는 표본10/5를 적었고 분석 초안/현 작업계획은 세부 기준 확인 대기다. 사용자 지시에 따라 아래 통상 선택은 Claude 검토 후 Codex가 근거를 기록하고 정한다.

**폐업률 선택안:** 기간은 (L=T의 전년 같은 월일,T], 윤년 불가능 날짜만 clamp. 분모는 open<=T AND(close IS NULL OR close>L), 분자는 L<close<=T다. 같은 날 개폐업 인허가는 활동 API와 같이 해당 기간의 기록1건으로 센다. close=L이면 분모/분자 모두 제외하고 close=T이면 분모/분자 포함·T active 제외다. 현재 active 수가 아니라 이 지표의 실제 **기간 분모10건**을 최소 표본으로 삼는다. 현재 FE mock은 active10건을 기준으로 해 계약 보완 요청이 필요하다.

**생존율 선택안:** API의 '(t-n)년 신규 중 t년까지 생존'은 달력 연도/진입 구간/관측 종료가 모호하다. FE mock은 1년=12~24개월 전,3년=36~48개월 전 개업 코호트이고 현재 폐업해도 n개월 이상 운영했으면 생존으로 센다. 이를 명시적 고정 관측기간 참고지표로 보완한다. n=1/3의 개업 코호트는 (T-(n+1)년,T-n년], 각 점포의 n주년<=T를 확인하고 폐업일이 없거나 **close>개업 n주년**이면 생존이다. n주년 당일 폐업은 그날 영업 중이 아니므로 제외한다(기존 시점의 close>T 규칙). n주년을 넘긴 뒤 T 전에 폐업했어도 고정 n년 생존에는 포함된다. 전체 현재 잔존율/성공률이 아니며 원본의 모호한 문장을 보완하는 이번 제안임을 명시한다. 최소 코호트5건, 소수 첫째 자리 ROUND_HALF_UP이다. 년 단위 이동은 실제 달력이며 윤년 clamp를 쓴다. 원본 확정 사실인 것처럼 숨기지 않고 FE 요청서에 차이를 전달한다.

서울 비교는 같은 인허가 출처/날짜/업종/세부업종/면적/가맹 unknown 필터의 **좌표 확보** 점포에 같은 산식/기준을 적용한다. 좌표 미확보를 서울에만 넣어 모집단을 달리하지 않는다. 서울은 점포 비율(분자 합/분모 합)이지 구별 비율의 평균이 아니다. 비교 표본 부족/0분모는 별도 사유와 null이며 로컬 값까지 숨기지 않는다.

## 2. API·입력·구조

GET /api/risk, nearby와 같은 필수 lat/lng/category 및 반경/시점/필터. include는 market_change,day_night_ratio만 쉼표로 허용한다. LQ·임의 UUID·주소·중복/빈/미지원 토큰 거절, 기존422/500·no-store·DB 접속전 검증을 유지한다.

data={query,market,indicators,flags}. query는 좌표/업종/반경/실제 적용일/정규화 필터이고 주소는 받거나 되돌리지 않는다. 좌표는 응답에만 필요하며 repr/로그/LLM 입력에 남기지 않는다. indicators는 official_closure_rate,official_risk,closure_rate_12m,survival_rate_1y,survival_rate_3y,competitor_count 순서 + 요청 선택항목 순서다. source는 원본 v1.2대로 string[]이며 현 FE의 string 가정은 요청서로 수정 요청한다.

지표 필드: id,type,value(nullable),unit,seoul_avg/seoul_avg_reason,seoul_numerator/seoul_denominator,numerator/denominator,space,period,source[],status/reason,link,copy_text. 비율은0~100·분자<=분모·표본 부족/0분모면 pending/null, 실제0은 fact/0. competitor_count는 active(T) 수·0도fact·분모없음이다. 공식 위험 링크 외 link/copy_text는null, 미산정 상태에 수치를 넣지 않는다. 값/분자/분모·계산 결과 불변식을 모델로 검사한다.

flags.insufficient_sample은 로컬 반환 비율 중 최소 표본 미만(0포함)이 하나라도 있을 때 true. flags.missing에는 표본 부족만으로 항목을 넣지 않는다. 필수 공식 폐업률에 필요한 검증 경계 미확보와 요청된 선택 지표의 미확인 자료만 넣는다. 미요청 선택 항목은 indicators/missing 양쪽에 없다.

## 3. 미확인 공식/조건부 지표와 경계

RISK_BOUNDARY_VERSION_ID: UUID|None 서버 설정만 추가한다(기본None, 실제 .env/로컬 설정은 변경하지 않음). 설정이 있으면 #62 judge_market에 명시 UUID를 전달해 공간 후보를 얻고 없으면 자동 최신 선택하지 않는다. 잘못 지정한/누락/부분 버전은 안전500이지 정상pending으로 숨기지 않는다.

market.status는 **unverified**로 고정하고 market_code/name/type=null·also_in/nearby_markets=[]다. 선택 버전의 결과는 spatial_candidate: BoundaryJudgement|null에 따로 둔다. reason=boundary_period_not_verified 또는 boundary_version_not_selected. 후보가 단일/밖이어도 현재/과거 적용일을 확인한 판정으로 승격하지 않는다. FE의 in_market/outside enum에 unverified와 후보 미리보기 구분이 필요하다.

official_closure_rate는 null/pending·reason=boundary_period_not_verified(선택없음도같은필수자료미확보)·source R2. 공식 통계 DB를 자동 최신/가까운 분기로 조회하지 않는다. official_risk는 value=null,status=link_only,link=https://golmok.seoul.go.kr/stateDistrict.do,copy_text=null,source R1. 2026-11-12 공식 안내 페이지 동작을 확인했으며 등급은 수집/인용/스크래핑하지 않는다.

요청 market_change는 official/null/pending·boundary_period_not_verified, day_night_ratio는 reference/null/pending·population_aggregation_and_grid_time_unverified다. market_change를 기존 초안처럼 반경 자체 유형으로 계산하지 않는다. 잘 모르는 공식 수치·브랜드 분류를 만들어내지 않는다. 가맹 분류 pending은 activity와 동일 meta로 알린다.

## 4. 계산·DB·메타

기존 temporal_cohort/attribute_filters/effective_date/provenance·거리 규칙을 재사용한다. 폐업 이력을 버리는 nearby active 목록을 재사용하지 않는다. DB에서 공간/서울별 aggregate count만 조회해 점포 식별값/원본 행은 읽지 않는다. 고정 n주년은 PostgreSQL 달력 interval의 clamp를 쓰고 경계는 순수 날짜 함수와 교차 검증한다.

기존 요청별 READ ONLY REPEATABLE READ/문장3초 세션을 재사용한다. DB/모델 실패는 원문/부분 응답 없는500·no-store다. meta.denominator=null(지표별로다름), as_of=T, data_updated_at=D, collected_at=null, source R5/R6(계산 근거)·공식 안내는 지표별source, trdar_quarter=null. 기준·cohort 기간·최소 표본·반올림·서울 좌표 확보 기준·가맹 분류pending을 명시한다. excluded_no_coord는 서울 동일 비공간 조건/T이전개업 전체 기록이며 인허가 반경 누락 수가 아니다.

새 schemas/risk.py·services/risk.py·routers/risk.py, Settings 선택 UUID/최소표본 상수, main 라우터 등록·FE 보고서·BE 문서를 추가한다. 모델/migration/의존성·Docker·.env·FE 저장소 변경 없음. 활동 API 등 기존 응답은 변경하지 않는다.

## 5. 검증·절차

일반: 폐업 기간 양끝·같은날개폐업·0분모/표본9/10·실제0/100·독립 서울 부족·비율 반올림·생존 코호트 양끝/4/5·n주년 당일/이후 폐업·T이전폐업도고정기간생존·윤년/미래차단·source 배열·모델 불변식·선택 항목/오류 비노출·설정/입력·OpenAPI.

격리 PostGIS: 499/500/501/500.001m·폐업 보존·시점/필터unknown독립·SQL 달력 n주년·서울 분모/로컬 차이·same source identity uniqueness·미확인/명시 경계후보/invalid UUID·원천 미준비·실제READ ONLY·기존activity/nearby 집계 일치. 개발 DB에서 파괴적인 suite를 실행하지 않는다.

실제 개발 DB: 기본/과거/필터·빈 결과10조합 이상을 독립 SQL로 대조, 표본 지표 수기5건, 기존조회회귀·head0009·모델차이0·14테이블 전체 행/geometry hash보존. 전체일반/격리·ruff/format/mypy·실제비밀값검사·PR/CI/CodeQL을 통과 후 일반 develop Squash 병합한다.

커밋: 설계/Claude → 지표 모델/계산+테스트 → API/DB/통합테스트 → 실제증거·FE요청·BE문서. 제목 `feat: Risk 참고 폐업률과 생존율 API 구현`, close #64. BE-24 공식 분기매칭/조건부수치·BE-21·AI/캐시·FE통합 완료로 표시하지 않는다.

## 6. Claude 검토 요청

이 MD만 Read/Edit한다. 코드/다른문서/Git/DB/네트워크/키 접근 금지. 폐업 최소표본의 분모·고정 n주년 생존 코호트/시점/윤년·서울 비교·필터/메타·정직한pending·서버명시경계/FE 계약 차이·테스트 누락을 검토하고 필요한 보정을 직접 기록한다. 이 문서에 인용한 원본 요약 외 원본 PDF를 읽지 않은 한계를 남긴다. 통상 선택은 최선안을 제시하고 Codex가 실제 원본/코드와 최종 대조한다.

## 7. Claude 검토 결과 (2026-11-12)

이 MD만 Read/Edit했다. 코드·다른 문서·원본 PDF·Git·DB·네트워크에는 접근하지 않았다. 아래 내용은 §1~§6의 서술만 근거로 한 검토이므로, Codex가 원본/코드와 대조한 뒤 확정한다.

### 7.1 결정 (제안안 유지)

- **폐업률 기간/분모:** (L,T] 반개구간, 분모 `open<=T AND (close IS NULL OR close>L)`, 분자 `L<close<=T`를 유지한다. close=L 제외, close=T 포함, 같은 날 개폐업은 1건으로 센다는 규칙이 서로 모순 없이 맞는다. 최소 표본은 현재 active 수가 아니라 **기간 분모>=10**으로 하는 것이 맞다. 지표 의미와 일치하고, 원본의 표본 10과도 충돌하지 않는다.
- **생존율 코호트:** (T-(n+1)년, T-n년] 개업 코호트와 `close IS NULL OR close > open+n년` 조건을 유지한다. 이 구간은 FE mock의 12~24/36~48개월 구간과 일치한다. n주년 당일 폐업을 비생존으로 보는 것도 기존 `close>T` 규칙과 일관된다. 최소 코호트는 5건이다.
- **윤년:** PostgreSQL `date + interval 'n year'`와 Python `relativedelta`는 모두 2/29를 2/28로 clamp한다. 이 규칙을 쓴다. `open<=T-n년`이면 `open+n년<=T`가 clamp의 단조성으로 항상 성립하므로, 'n주년<=T 확인'은 필터가 아니라 **불변식 assert/테스트**로 둔다. T=2/28과 T=2/29(윤년)이 같은 L·코호트를 가지는 것은 허용되는 결과로 문서화한다.
- **서울 비교:** 좌표가 확보된 동일 모집단, 점포 비율(분자 합/분모 합), 독립된 표본 부족 사유를 유지한다. 서울 최소 표본은 로컬과 같은 10/5로 둔다.
- **경계:** `RISK_BOUNDARY_VERSION_ID`는 명시된 경우에만 사용하고 자동으로 최신 버전을 고르지 않는다. 결과는 `market.status=unverified`와 `spatial_candidate`로 분리한다. 이 방향을 유지한다.
- **official_risk:** link_only로 두고 등급을 수집하지 않는다. 이 결정을 유지한다.

### 7.2 필수 보정

1. **반올림 범위 명시:** ROUND_HALF_UP 소수 첫째 자리 규칙이 §1에서는 생존율에만 적혀 있다. 이를 `closure_rate_12m`·`survival_rate_*`·`seoul_avg` 전체에 적용한다. 계산은 정수 분자/분모로 `Decimal(numerator*100)/denominator`를 구한 뒤 quantize한다. float와 SQL `round(double)`은 금지한다(12.25→12.3 확인).
2. **pending일 때 분자/분모:** "미산정 상태에 수치를 넣지 않는다"와 지표의 numerator/denominator 필드의 관계가 정해져 있지 않다. 제안은 다음과 같다. 표본 부족이면 `value=null`, `numerator=null`, `denominator=실제 분모`(0 포함)로 둔다. FE가 "표본 n건"을 표시할 수는 있되, 소표본 비율을 역산할 수는 없게 하려는 것이다. 서울도 같은 규칙(`seoul_numerator=null`)을 따른다. 이 규칙을 모델 불변식에 넣는다.
3. **competitor_count의 서울 비교:** 반경 내 개수에는 서울 평균이 정의되지 않는다. `seoul_avg=null`, `seoul_avg_reason=not_applicable`(신규 사유값), `seoul_numerator/denominator=null`로 고정한다. 이를 명시하지 않으면 구현자가 "서울 전체 수"를 채울 위험이 있다.
4. **insufficient_sample 대상 한정:** 플래그 계산 대상은 `closure_rate_12m`, `survival_rate_1y`, `survival_rate_3y`의 **로컬** 값뿐이다. 공식/선택 지표의 pending과 서울의 표본 부족은 이 플래그를 켜지 않는다고 명시한다.
5. **데이터 이상 처리 규칙 추가:** `close<open`, `open IS NULL`, T 이후 개업은 분모·코호트에서 제외한다. 제외 건수를 메타에 남길지는 Codex가 기존 activity 규칙과 맞춰 정한다. 기본안은 activity와 동일하게 처리하는 것이다. 이 규칙이 없으면 같은 날 개폐업 규칙과 섞여 분모가 흔들린다.
6. **휴업/상태코드:** 인허가의 휴업, 직권말소, 영업자 지위승계(양수도로 인한 폐업+신규 개업)를 어떻게 다룰지 정해야 한다. 기본안은 기존 activity/temporal_cohort의 정의를 그대로 따르는 것이다. 지위승계 때문에 폐업률이 과대 계상되고 생존율이 과소 계상될 수 있다는 점을 `meta`/FE 요청서의 한계 문구로 반드시 남긴다. 임의로 중복을 제거하지 않는다.
7. **T 상한:** `T>D(data_updated_at)`이면 기간이 관측되지 않은 날짜를 포함한다. 그래서 기존 effective_date 규칙과 같이 422를 내거나 D로 제한하는 방식 중 하나를 명시하고 테스트한다. 기본안은 기존 규칙을 재사용하는 것이다.
8. **excluded_no_coord 의미:** 이 값 하나로는 지표마다 다른 모집단(기간, 코호트)을 설명하지 못한다. 메타 설명에 "T 이전 개업·비공간 조건 기준 전체 좌표 미확보 수이며, 지표별 모집단 제외 수가 아님"을 그대로 노출한다. 지표별 제외 수가 필요해지면 후속 이슈로 넘긴다(이번 계약 확장 없음).
9. **include 출력 순서:** "요청 선택항목 순서"를 `include=day_night_ratio,market_change`처럼 역순으로 요청한 경우의 동작으로 명시하고 테스트한다. 고정 순서를 원하면 그 순서를 지금 확정해야 한다. 권장안은 고정 순서(`market_change`, `day_night_ratio`)다. 이렇게 하면 캐시와 FE 렌더링이 안정적이다.
10. **경계 설정 오류의 범위:** UUID 형식 오류는 Settings 로드 단계에서 거절한다(기동 실패). 존재하지 않는 버전이나 부분 버전만 요청 시점에 안전한 500으로 처리한다. 오설정 하나로 모든 /api/risk가 500이 되므로, 로그에 원인 코드를 남긴다(좌표 제외).
11. **FE 계약 차이 목록화:** FE 요청서에는 다음을 한 표로 정리한다. ① 최소 표본 기준(active→기간 분모) ② source string→string[] ③ market.status의 unverified와 spatial_candidate ④ n주년 경계("n개월 이상 운영"과 "n주년 당일 폐업 제외"의 차이) ⑤ competitor_count의 seoul_avg=null ⑥ pending일 때 numerator=null.

### 7.3 테스트 보강 (§5 누락분)

- 코호트 경계: open=T-(n+1)년(제외), open=T-n년(포함). open=2/29인 코호트의 n주년 clamp. T=2/29와 T=2/28 비교.
- `close<open`·`open NULL`·T 이후 개업 제외. 휴업/지위승계 레코드를 기존 정의대로 처리하는지 확인.
- ROUND_HALF_UP 경계(x.x5). Decimal 경로가 float를 거치지 않는지 확인.
- pending일 때 numerator=null/denominator 유지. 서울만 부족하거나 로컬만 부족한 경우를 독립적으로 확인. competitor_count의 seoul not_applicable.
- insufficient_sample이 공식/선택/서울 pending에는 켜지지 않는지 확인.
- include 역순·빈 토큰·대소문자·공백. flags.missing의 include 유무별 내용.
- T>D 처리. 잘못된 UUID 형식의 Settings 거절.
- 로그/repr/예외 메시지에 좌표가 남지 않는지 확인(caplog).
- 실제 개발 DB: 서울 전역 aggregate의 EXPLAIN과 응답 시간을 측정해 문장 제한 3초 안에 들어오는지 확인.

### 7.4 한계

- 원본 API v1.2와 분석 정의 PDF는 읽지 않았다. 이 MD의 요약만 근거로 삼았다. "표본10/5"가 각각 폐업률/생존율에 대응한다는 해석도 요약에 의존한다.
- 기존 `temporal_cohort`, `attribute_filters`, `effective_date`, activity 집계 코드는 보지 않았다. 따라서 7.2의 "기존 규칙 재사용" 항목(휴업, 데이터 이상, T 상한)은 Codex가 실제 코드와 대조해 확정해야 한다.
- 지표 해석상의 한계:
  - 과거 T 조회도 현재 스냅샷을 쓴다. 따라서 폐업일 소급 등록 때문에 과거 값이 바뀔 수 있다.
  - 폐업 점포는 좌표 확보율이 낮을 수 있다. 그러면 폐업률이 과소, 생존율이 과대 추정될 수 있다. 개발 DB에서 상태별 좌표 미확보율을 측정해 문서에 남기기를 권장한다.
  - 지위승계로 인한 폐업+개업이 실제 폐업과 구분되지 않을 수 있다.
  - 이 값들은 인허가 기록 기반의 참고지표이며, 실제 폐업률·창업 성공확률이 아니다.
- 서울 비교는 "좌표 확보 점포"라는 모집단 기준이다. 공식 서울 통계와 수치가 다를 수 있다.
- 서울 전역 aggregate를 요청마다 계산할 때의 성능은 검증되지 않았다(캐시는 후속 범위).

## 8. Codex 최종 결정

Claude 실제 MD 수정 diff 전체와 JSON(is_error=false,3 turns,permission_denials=[])을 읽었다. 기간 분모10/생존 코호트5·Decimal HALF_UP·pending 분자null/실제분모유지·좌표확보 서울 비교·선택항목 고정순서·미확인 경계 분리를 채택한다. 최소 표본/고정 관측기간은 원본의 모호한 부분과 FE mock을 명시적으로 보완하는 **이번 BE 계약안**이다. 특히 개업 n주년까지의 생존은 원본의 'T까지 현재 잔존'과 동일하지 않다. 현재 잔존과 고정기간 생존을 혼용하지 않도록 후자를 선택하고 rule_version/메타/FE 요청에 명시한다. 원본 문서/FE 합의 완료로 주장하지 않는다.

실제 temporal_cohort는 날짜 결측/오류/미래·close<open·상태 모순·한시 영업을 제외하고 기타 상태는 유효 날짜 구간이면 유지한다. 지위승계 추정 제거는 하지 않는다. as_of는 기존 latest=D/과거월말/범위밖422다. 좌표 미확보 수는 T이전개업 전체 비공간코호트이며 지표별 누락 수가 아니다. 반환 순서는 market_change,day_night_ratio로 고정한다. UUID형식은 Settings에서 거절, 존재/행수 오류는 안전500이며 원문/좌표를 로그에 추가하지 않는다(운영로그는별도BE-35).

Claude의 윤년 서술 중 'T=2/28과2/29는 같은 L'은 일반화하지 않는다. 전년도도 윤년인지/이동 년수에 따라 달라지므로 실제 같은 월일 clamp 함수와 PostgreSQL 날짜 interval을 테스트로 대조한다. 새 의존성 relativedelta는 필요하지 않다. 실제 코드·DB를 읽지 않은 검토의 한계와 새 계산안의 원본 차이는 유지한다.
