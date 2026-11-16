# 브랜드 보강·조건부 지표 연결 기반 (#174)

2026-11-16 KST, 기준 develop2d6b30c. BE 전용. 사용자 요청한 세 항목을 진행하되 공식 정의의 부재를 새로운 코드나 mock으로 해소했다고 표시하지 않는다.

## 1. 범위와 완료 경계

1. 공식 브랜드/매장 안내와 기존 공정위 catalog source key를 대조해 검토 registry를 확장한다. 지점 접미를 허용하는 검토 seed가 현재5개인 것이 누락의 한 원인이다. 공정위 전체 목록은 기존처럼 exact-only이며 퍼지/부분 문자열 일괄 매칭을 추가하지 않는다. 이름 판정은 estimated이고 가맹/직영 계약이나 과거 소속을 확정하지 않는다. 미일치는 unknown이다.
2. 매출·상권변화의 검증된 기간 목록 선택 및 typed 원천 투영을 내부 순수 모듈로 구현한다. 실제 경계/기간 근거가 없으므로 DB의 immutable unverified를 변경하지 않고 공개 API/AI pending을 유지한다. 이 모듈은 향후 검증된 service caller가 쓸 기반이며 source approval이나 실제 연결 완료가 아니다.
3. 생활인구에서 명시적 기대 구성과 실제 관측을 대조해24시간 총계를 조립하고 기존 calculate_day_night에 전달하는 내부 순수 모듈을 구현한다. 기대 구성의 공식 정당성/공간·날짜 적용성은 caller가 별도로 입증해야 하며 원천 행으로 기대 구성을 추론하지 않는다. 실제 DB/API 연결과 공식 근거 확보는 미완료로 남긴다.

FE·공개 API 계약·schema0012·.env·원본/운영 DB·Render 배포·기존 수집/백업 Task/runtime을 바꾸지 않는다. 실제 로컬 자료는 READ ONLY로만 대조한다. 원천 개별 점포/관측·주소/좌표/키는 stdout/커밋/Claude 입력에 넣지 않는다. 외부 문의를 대신 제출하지 않는다.

## 2. 브랜드와 근거

기존5개를 보존하며 공식 확인 가능한 이디야커피·메가MGC커피·빽다방·할리스·블루보틀·새마을식당·한신포차·역전우동0410·롤링파스타·미정국수0410·프릳츠·앤트러사이트를 우선 추가한다. 커피리브레는 공식 매장 목록까지 확인되는 경우만 포함한다. 접근 차단/다른 브랜드와의 혼동이 해소되지 않는 후보는 추가하지 않는다. 공정위 normalized 이름도 alias에 정확히 포함해 승인 source key와 catalog 중복/충돌을 막는다. FTC ref는 같은 catalog에서 실제 확인된 쌍만 사용하고 source identity를 이름으로 추정 생성하지 않는다.

- [이디야](https://www.ediya.com/contents/find_store.html), [메가](https://www.mega-mgccoffee.com/store/find/), [빽다방](https://paikdabang.com/), [할리스](https://www.hollys.co.kr/), [블루보틀](https://kr.bluebottlecoffee.com/pages/cafe-list).
- [새마을식당](https://newmaul.com/), [한신포차](https://hanshinpocha.com/), [역전우동](https://udon0410.com/), [롤링파스타](https://rolling-pasta.com/), [미정국수](https://www.0410noodle.com/).
- [프릳츠 매장](https://fritz.co.kr/store.html?cate_no=125), [앤트러사이트 매장](https://anthracitecoffee.com/visit), [커피리브레](https://coffeelibre.kr/).

registry `source_url`은 기존 `BrandSpec.valid`가 query/fragment/userinfo를 거부하므로 query 없는 https URL만 쓴다. 프릳츠 매장 링크(`?cate_no=125`)는 그대로 넣으면 load가 `source` 오류로 실패하므로 validator를 완화하지 않고 query 없는 공식 매장/브랜드 페이지로 기록하며, 실제 검토 페이지는 이 문서의 근거 목록에 남긴다. 홈페이지 URL은 실제로 매장 안내를 확인한 경우에만 source_url로 쓴다. `reviewed_on`은 실제 검토일(미래 불가)이다.

alias 규칙: 영숫자3자 미만 alias(예: `메가`)는 `approved_short_aliases` 별도 근거 없이 추가하지 않는다. 일반 명사/독립 업소와 겹칠 수 있는 축약명(예: 0410 없는 `역전우동`·`미정국수`, `새마을`)은 공식 표기로 확인되고 동일명 독립 업소 혼동이 검토된 경우만 넣고, 아니면 공식 전체 표기만 쓴다. branch_patterns=true인 seed의 모든 alias가 prefix pattern이 되며 `_BRANCH`는 `커피 강남점` 같은 서술어+점도 받으므로, 신규 alias가 기존/신규 seed alias의 prefix가 되는 경우를 테스트에서 명시 확인한다. 공정위 normalized 이름을 alias에 넣는 것만으로는 충돌이 막히지 않는다: 해당 catalog 행의 (management_no, headquarter_no)가 `ftc_refs`로 승인돼야 `extend_catalog`가 별도 ftc_exact 항목을 만들지 않으며, 승인 없이 이름만 겹치면 `seed_catalog_name_collision` conflict가 의도된 fail-safe 결과다. 한 브랜드에 여러 catalog 행이 있으면 각 쌍을 개별 확인한 경우만 승인하고, 승인 ref의 이름이 alias에 없으면 기존처럼 `approved_catalog_alias_changed`로 실패한다. seed 간 ftc_ref 중복은 `registry_source_conflict`로 실패한다.

프릳츠의 점 없는 공식 매장명은 확인한 전체 표기를 exact alias로 추가한다. 임의 지명을 지점으로 인정하지 않는다. 현재 suffix grammar/짧은 이름 separator·법인 prefix·부정 단어·충돌 격리는 유지한다. seed의 추가 alias가 기존 generic catalog와 충돌하면 별도 source key 승인 또는 그대로 conflict로 남기며 먼저 나온 seed를 고르지 않는다. registry 변경은 다음 publication 재계산이 필요하며 기존 공개 세대를 자동 변경하지 않는다.

검증: 신규 브랜드/별칭 정상, 옆/전문/미등록 법인·혼합 브랜드·비승인 점 없는 지명·catalog identity 충돌을 검사한다. 기존 registry와 신규 registry를 실제 같은 READ ONLY snapshot/소진공 자료로 비교해 추정 증가·기존 추정 이탈/충돌 변화·원본 보존을 집계한다. 증가를 정확도 점수로 부르지 않는다. 실제 활성화는 후속 publication과 배포를 거쳐야 한다.

## 3. 매출·상권변화 기반

`app/analysis/market_reference.py`는 DB/설정/네트워크에 접근하지 않는다. 입력은 검증된 upstream caller가 넘기는 명시 기간과 typed 원천 행이다. public 요청/환경에서 verified flag를 받아 활성화하는 우회는 없다.

- `select_quarter(target: date, verified_periods: tuple[str,...], *, current: bool)`는2000~2099년의 YYYYQ(마지막1~4) 문자열을 검증한다. 중복/잘못된 타입·bool을 거부한다. current는 target 분기 이하의 검증된 최신 분기를 선택한다. 과거 조회는 target과 동일 분기만 허용하며 없으면 None이다. 미래 자료나 인접 분기를 대신 쓰지 않는다. 빈 목록은 None이다. 기간만 골랐다고 도형/업종/원천을 검증한 것이 아니다. target은 `type(target) is date`로 검사해 datetime(서브클래스)을 거부하고, target 연도도2000~2099 밖이면 고정 오류다. `current`도 `type(...) is bool`만 허용한다. current 선택 결과는 target 분기와 다를 수 있으므로 반환값(선택 분기)을 그대로 출력에 노출하고 target 분기와의 차이를 숨기지 않는다. 허용 최대 지연(staleness)은 공식/정책 근거가 없으므로 이 모듈이 정하지 않으며 caller가 별도 설계 전까지 공개하지 않는다.
- `SalesSource`는 version UUID·boundary UUID·quarter·market_code·industry_code·원천 est_sales/source_sales_count(각 int>=0 또는None)를 받는 frozen strict 모델이다. supported industry5개만 허용한다. `project_sales`는 원천 행이 있으면 원/원천 건수 그대로, 둘의 null을 보존하고 period_basis=`quarter_total|monthly_average|specific_month`를 caller가 명시한다. 행 부재는 no_data다. 표시 status=`available|partial|no_data`;0은 available이며 환산/합산/점포당 계산은 없다. 기준 분기/공간=market_industry·brand_filter_applied=false·license_filters_applied=false를 명시한다. status 규칙을 고정한다: 행 없음(None 입력)=no_data, 두 값 모두 int=available, 하나만 None=partial, 둘 다 None=no_data(row_present=true를 별도 표시). 입력은 단일 행 또는 None이며 여러 행을 합치지 않는다. 행의 quarter는 select_quarter가 선택한 분기와 같아야 하며 다르면 고정 오류다. int 검사는 `type(x) is int`로 bool을 거부한다. supported industry5개는 기존 코드의 업종 상수를 재사용하고 새 목록을 만들지 않는다. period_basis는 기본값이 없고 caller가 근거 없이 열 이름(`당월` 등)에서 추론해 넣지 않는다. `specific_month`이면 선택 분기 안의 월초 date `source_month`가 필수이고, 다른 basis에서는 source_month를 거부한다(§9 보완, 월 추론/환산 없음).
- `ChangeSource`는 version/boundary/quarter/market_code·LL/LH/HL/HH와 대응 명칭·원천 생존/폐업 평균개월(상권/서울) nullable int>=0를 받는다. `project_change`는 available/no_data이며 업종 차원 없는 market_all_industries와 필터 미적용을 명시한다. 코드/명칭 불일치와 임의 숫자 점수는 거부한다. 코드↔명칭 대응표는 기존 저장소에 근거와 함께 있는 상수만 재사용하며, 없으면 이 PR에서 명칭을 새로 지어내지 않고 원천 명칭 문자열을 보존한 채 같은 입력 안의 코드-명칭 일관성만 검사한다. quarter도 선택 분기와 일치해야 한다.
- output은 upstream 검증/공식성의 증명이 아니다. 결과에 `source_validation_performed=false`, `public_activation_ready=false`를 고정한다. 기존 API가 자동 호출하지 않는다. period basis가 미확정인 실제 자료를 이 모듈로 통과시켜 서비스하지 않는다.

공식 재확인: [OA-15572](https://data.seoul.go.kr/dataList/OA-15572/F/1/datasetView.do)의 공간 기준 변경 안내는 확인했지만2025 ZIP의 `당월` 의미를 해소하지 못했다. OA-15576은 이번 열람에서 서비스 지연103이어서 새 근거로 인정하지 않는다. [기존 감사](feat156-market-applicability.md)의 도형/기간 문의는 여전히 미제출이다. API/AI 실제 연결 전에 버전/해시/분기별 적용 근거와 caller의 무결성 검사, 캐시/typed 공개 schema/FE 계약을 별도 설계해야 한다.

## 4. 생활인구 조립 기반

`app/analysis/population_totals.py`는 `PopulationCell`(source=local|long|short,hour0~23,grid_id,admin_code)와 `PopulationObservation`(cell,total_status=observed|suppressed|missing,total=Decimal|None)를 frozen strict 모델로 제공한다. observed만 유한 Numeric(20,5) 범위0이상/소수5자리 이하의 Decimal을 허용하고 나머지는None만 허용한다.

`assemble_population(scope: PopulationScope, expected: tuple[PopulationCell,...], observations: tuple[PopulationObservation,...])`는 다음을 따른다. (scope는 1항의 비교 기준이므로 시그니처에 명시 인자로 둔다.) total은 `type(x) is Decimal`만 허용해 int/float/str/서브클래스를 거부하고 NaN/Infinity를 거부한다. `-0`은 허용하되 기존 calculate_day_night의 부호 0 정규화를 따른다.

1. caller는 동일 관측일·격자 버전·관측 버전·공간·모집단에 속하는 자료만 넘겨야 한다. 모델에 observation_date/grid_version_id/observation_version_id를 묶은 `PopulationScope`를 받고 각 관측에도 같은 scope를 요구한다. source semantics/구성의 공식 근거는 이 모듈이 만들지 않는다.
2. expected는 실제 observed row에서 파생하지 않는 명시 기대 구성이다.1~100,000키, 중복 금지, 각24시간과 source3종이 모두 포함돼야 한다. 시간별 기대 구성이 달라도 해당 시각의 명시 키 그대로 검사한다. 빈 source/hour 구성은 인구0의 증거로 쓰지 않는다. 관측도 최대100,000이고 예상 밖 키·중복·scope 불일치는 고정 오류다. 같은 grid/hour라도 admin이 다르면 별개 키다.
3. 없는 기대 키=absent, suppressed/missing은 각각 별도 집계한다. 한 시간에 하나라도 부재/비공개/누락이 있으면 그 시간 총계는None이다. 알려진 부분합은 반환하지 않는다. 온전한 시간만 50자리 Decimal context로 합산하며 Numeric(20,5) 상한을 넘으면 고정 오류다. 입력 순서나 전역 Decimal precision에 의존하지 않는다.
4. 24시간 tuple을 기존 calculate_day_night로 전달한다. 불완전 시간이 있으면 기존 incomplete/전체 수치None, 실제 모두0이면 zero_total을 유지한다. 구성3종 source 간 중복 없음/행정동 합산/격자 효력은 upstream 책임이다. 출력에는 source_validation_performed=false/public_activation_ready=false를 고정한다. 주민 고유 방문자/공식 주야간 기준으로 표현하지 않는다.

모든 모델은 repr 비노출/hide_input_in_errors, 크기·코드·날짜/UUID strict 검사와 고정 오류만 사용한다. raw validation 오류를 외부로 전달하지 않는다. 실제 입증된 기대 구성 근거가 없으므로 현재 DB에서 원천을 무조건 SUM하거나 공개 pending을 해제하지 않는다. [공식 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do)의 비공개/시간 추계와 [기존 검증](../population-source-verification.md)을 유지한다.

## 5. 테스트·검토·통합

모든 신규 내부 계산은 합성 입력으로 검사한다. 분기 말/연도 경계/미래/결측·잘못된 타입, 매출0/null/행 부재·업종/브랜드 미적용, 상권변화 코드쌍·분모, 인구 혼합 scope/중복/예상 밖/부재/비공개/0/부정 Decimal/저정밀 context·시간과source완전성을 검사한다. 기존 API pending 및 AI 수치 비유입 회귀도 실행한다. 단순 구현 복제 테스트는 만들지 않는다.

실제 Claude는 이 MD만 Read/Edit하고 제공한 소스/공식 근거 발췌만 대조한다. 소스·셸/DB/비밀/네트워크·다른 agent 도구를 허용하지 않는다. Codex가 실제 MD diff와 이유를 대조한 후 구현하고 구현 검토·필수 보완·최종 검사로 마무리한다. local pytest/ruff/mypy·CI Linux/Windows/PostGIS·CodeQL 통과 후 develop 정상 Squash·주 BE ff-only를 따른다. Ref #115/#78은 공식 근거/활성화 잔여를 위해 유지한다. 최종 보고는 브랜드 보강·연결 기반 완료와 실제 공개 활성화 미완료를 구분하고 필요한 자료를 명시한다.

## 6. Claude 설계 검토 (2026-11-16)

판정: **REVISE** (위 본문에 반영함. Codex가 diff를 대조한 뒤 구현해야 함)

범위: 이 MD와 대화에서 제공된 `etl/chains/registry.py`·`matching.py`·`registry.json`·`app/analysis/day_night.py` 발췌만 대조했다. 테스트·셸·DB·네트워크는 실행하지 않았고 공식 사이트도 직접 확인하지 않았다. 따라서 이 검토는 소스 검증, 공개 API/AI 활성화, 실제 precision/recall, 배포가 완료됐다는 의미가 아니다. 공식 정의 공백(OA-15572 `당월` 의미, OA-15576 미열람, 도형/기간 문의 미제출, 생활인구 기대 구성 근거)은 그대로 남아 있다.

REVISE가 필요한 이유와 반영 내용:
1. **프릳츠 source_url이 기존 validator와 충돌.** `BrandSpec.valid`가 `url.query`를 거부하므로 `?cate_no=125`가 있으면 registry load가 실패한다. validator를 완화하지 않고 query 없는 URL을 쓰도록 §2에 명시했다.
2. **FTC 충돌 방지 서술이 코드 동작과 불일치.** alias에 공정위 이름을 넣는 것만으로는 충돌이 막히지 않는다. `ftc_refs`로 승인돼야 `extend_catalog`가 해당 행을 건너뛰고, 승인이 없으면 `seed_catalog_name_collision`가 나는 것이 맞는 fail-safe 동작이다. 이를 §2에 명시했다.
3. **신규 alias 위험 규칙 부재.** 짧은 alias(<3자)에 쓰는 `approved_short_aliases`, 일반명 축약(0410 없는 이름 등), `_BRANCH`가 서술어+점도 허용하는 점, seed 간 prefix 중첩에 대한 테스트 요구를 추가했다. 퍼지/부분 문자열 catalog 매칭은 계속 추가하지 않는다.
4. **분기 선택 경계 모호.** datetime 서브클래스·bool 거부, target 연도 범위, 선택 분기 노출을 추가했다. staleness 상한은 근거가 없으므로 정하지 않는다고 명시했다.
5. **매출 status 미정의.** `partial`/`no_data` 조건, 단일 행, 분기 일치, 기존 업종 상수 재사용, period_basis 기본값 금지를 고정했다.
6. **상권변화 코드↔명칭 대응 근거.** 근거 없는 명칭표를 새로 만들지 않도록 했다.
7. **assemble_population 시그니처에 scope 누락.** 본문 1항이 scope 비교를 요구하는데 시그니처에 인자가 없어서 추가했다. Decimal 타입 엄격성과 -0 처리도 명시했다.

유지되는 점(적합): catalog exact-only, 이름 판정 estimated/unknown 구분, DB immutable unverified 및 API/AI pending 유지, `source_validation_performed=false`·`public_activation_ready=false` 고정, 부분합 미반환, Numeric(20,5) 상한이 `day_night._INPUT_LIMIT`(1e15)과 일치, publication 재계산 필요 명시, 증가 수치를 정확도로 부르지 않음.

## 7. Codex 대조와 구현 결정

실제 Claude 설계 검토는2026-11-16T00:52:48Z~00:54:32Z exit0/is_error=false/8turns, MD SHA `db0b27a85916c539f835637790ad66b2abf7660f727dcff5d6f76fac711244c4`→`ab243f2fcb4e0968d24a0c306cc37e8a4e471a90f9ef8a15d5e0a73f1fee60fc`였다. 실제 MD 변경·기존 소스 SHA 보존·permission_denials0을 확인했다. 판정 REVISE의7개 수정은 본문에 반영됐으며 Codex가 각각 대조/수용한 뒤 구현했다. Claude 설계 PASS로 표기하지 않고 구현 재검토로 필수 반영을 확인한다.

브랜드12개를 추가해17개로 확장했다. 커피리브레/접근 차단 후보는 이번에 포함하지 않았고 프릳츠는 branch_patterns=false로 공식 전체 표기만 사용한다. 0410 없는 역전우동/미정국수 등 모호한 축약은 추가하지 않았다. 공식 홈페이지의 전체 상호와 실제 공정위 ref를 대조했으며 법인 prefix는 확인된 더본코리아/앤트러사이트만 사용했다.

Codex가 추가한 보수적 방어2건: 검토 parent alias보다 긴 다른 catalog alias로 시작하는 후보는 parent의 지점명으로 흡수하지 않는다(긴 catalog alias 자체의 지점 인식은 여전히 추가하지 않음). 승인 seed alias와 같은 catalog 이름이 여러 ref에 걸치면 미승인 ref를 기존 중복-name 제외 뒤에 숨기지 않고 `ambiguous_reviewed_catalog_name`으로 전체 재계산을 거절한다. 새 규칙은 `chain-membership-estimate-v2`이며 기존 세대/원본은 자동 변경하지 않는다. 해당 경우와 parent 정상·exact-only subbrand·alias/source key 충돌 회귀를 포함한다.

내부 매출 투영은 원천 BigInt, 상권변화 평균은 Int32 상한까지 검사한다. 없음/두 null/부분 null/실제0을 구분하고 분기 일치·명시 period basis를 요구한다. 인구 조립은 같은 scope·72개 source/hour 조합을 모두 가진 독립 기대 구성을 요구하고, 부분 시간 총계는None으로 남긴 뒤 기존 주야간 계산기에 전달한다. 합계는50자리 context로 독립 계산한다. 실제 공식 합산/기간/도형의 승격이나 API/AI 연결은 하지 않는다.

인구의 공간 누락 방어도 추가했다. `PopulationScope.grid_ids`는 caller가 공간 선택과 공식 적용 근거로 별도 확정한 중복 없는1~1,000개 격자다. 기대 키의 (grid,source,hour) 조합이 이 격자 각각의72조합을 전부 포함해야 한다. 전역 source/hour만 검사하면 다른 격자의 자료가 누락 격자/시간을 가릴 수 있어, 전체 격자 누락과 한 격자만 특정 원천/시간이 없는 반례2개를 추가했다. 각 조합의 행정동 구성은 여전히 독립 근거가 필요하고 실제 row에서 기대 집합을 역생성하지 않는다.

1차 신규/관련 검사131통과 뒤 전체 일반2422통과·권한3skip·PostGIS298분리(89.18초)를 확인했다. 이후 위 공간 누락2개를 보완한 신규3파일 검사는88통과(0.59초)이며 최종 전체 검사를 다시 진행한다(최종 Codex 보고값은 §9 "최종 실행 결과" 참조). Windows/Linux mypy196파일·ruff check/438파일 format도 통과했다. 기존 경고1건은 Starlette/httpx다.

실제 로컬 READ ONLY 비교는 같은 새 규칙에서 이전5개 registry와 신규17개 registry를 같은 RR snapshot/기존 소진공 파일로 대조한 것이다. 대상355,835행, 추정8,778→10,780·미확인347,057→345,055, 원본 입력 hash와 소진공 파일 SHA 보존·transaction_read_only=on을 확인했다. 기존 추정4건 이탈·92건의 catalog→검토 seed canonical 재연결이 있어 이탈 원인을 추가 검사한다. 이 증가는 precision/recall 측정이나 공개 세대 갱신이 아니다. 신규 registry만 배포해 기존 publication이 달라진다고 표시하지 않는다.

## 8. Claude 구현 검토 (2026-11-16)

판정: **REVISE** (구현 결함은 발견하지 못함. 아래 필수 2건이 해소되기 전에는 브랜드 보강 완료로 표기하지 않음)

범위: 이 MD와 대화에 제공된 소스 발췌(`etl/chains/registry.py`·`matching.py`·`registry.json`·`common.py`·`linking.py`, `app/analysis/day_night.py`·`market_reference.py`·`population_totals.py`, 테스트3파일+기존 matching 테스트)와 Codex 실행 근거 요약만 읽고 대조했다. Claude는 테스트·셸·DB·네트워크를 실행하지 않았고 공식 사이트·공정위 ref·실제 snapshot도 직접 확인하지 않았다. 아래 테스트 수치·로컬 비교 수치는 Codex 보고값이며 Claude가 재현한 것이 아니다. 소스 검증, 공개 API/AI 활성화, precision/recall, 배포는 완료되지 않았다. 공식 정의 공백(OA-15572 `당월`, OA-15576, 도형/기간 문의 미제출, 생활인구 기대 구성 근거)도 그대로 남아 있다.

필수 보완(REVISE 사유):
1. **기존 추정4건 이탈 원인 미확정.** 같은 규칙 v2에서 registry만 다르므로 이탈은 registry 차이에서 생긴다. 코드상 가능한 경로는 다음 가설 3가지이며 확인된 원인이 아니다. (a) 신규 pattern alias(`이디야`·`할리스`·`블루보틀` 등)가 기존 추정의 지점 suffix에 들어가 `branch_words_allowed`가 거부함(`linking.OutletIndex`의 provider branch 검사 포함). (b) 이전에 ftc_exact로 추정되던 미승인 catalog 이름이 신규 seed alias와 같아져 `seed_catalog_name_collision` conflict로 바뀜. 이것은 의도된 fail-safe이다. (c) 새 exact alias와 기존 pattern이 함께 맞아 `ambiguous_brand`가 됨. 4건을 원천 값을 노출하지 않고 사유 코드별로 분류하고, fail-safe가 아닌 사유가 있으면 고친 뒤에 "회귀 없음/완료"를 말할 수 있다.
2. **§2가 요구한 테스트 2종 누락.** (a) seed 간 prefix 중첩 불변식: branch_patterns=true인 seed alias(정규화 후)가 다른 seed alias의 prefix가 되는 경우를 열거하고, 기존에 승인된 `본죽`/`본죽&비빔밥` 외에는 없음을 고정하는 테스트. (b) 신규 seed끼리 섞인 이름(예: `이디야커피 할리스점`, `빽다방 새마을식당점`)이 estimated가 되지 않는 회귀. 제공 소스를 읽어 보면 현재 동작은 (b)를 unknown으로 처리하는 것으로 보이지만, 설계가 명시한 검사가 테스트에 없다.

권고(비차단):
- §7 88행은 "최종 전체 검사를 다시 진행한다"로 끝나 있다. Codex 보고상 최종 Windows 전체 2424통과·3skip·PostGIS298분리(89.41초)이므로, 보고값으로 표기해 갱신한다. CI Linux/PostGIS/CodeQL은 아직 근거가 없다.
- `population_totals`의 `Context(prec=50)`는 지정하지 않은 속성을 `decimal.DefaultContext`에서 가져온다. `day_night`처럼 rounding/Emin/Emax/traps를 모두 명시하면 전역 상태와 완전히 독립된다.
- `SalesSource`/`ChangeSource`는 quarter·industry·금액·change 값이 기본 repr에 나온다. §4의 "repr 비노출"을 모든 모델에 적용하려면 숫자 필드에도 `repr=False`를 적용한다(집계 값이라 개인정보 문제는 아님).
- `ChangeProjection`은 네 평균이 모두 null이어도 `available`이다. 변화 코드 자체는 있으므로 허용 가능하지만, 향후 공개 schema에서는 평균 null을 그대로 표시해야 한다.
- `PopulationScope.observation_date`에 datetime이 들어오면 거부되는지 strict 검사 테스트를 추가한다.
- `할리스커피` 단독 표기는 현재 unknown이다(suffix가 `점`으로 끝나지 않음). 이는 recall 공백이며 오류는 아니다. 추가하려면 공식 표기와 공정위 이름을 확인한 뒤 exact alias로 넣는다.

설계와 일치 확인(적합):
- 브랜드: 기존5개 보존, 12개 추가, 커피리브레 제외, `메가`·0410 없는 축약 미추가, 프릳츠 query 없는 URL·branch_patterns=false·exact 지명 alias, 법인 prefix 한정이 모두 설계와 맞다. catalog exact-only를 유지하고 퍼지 매칭을 추가하지 않았다. 승인 ref 이름 불일치는 `approved_catalog_alias_changed`, 중복 이름은 `ambiguous_reviewed_catalog_name`으로 fail-closed된다. parent/subbrand guard는 positive를 추가하지 않는다.
- 매출·상권변화: `select_quarter`는 type/범위/중복을 검사하고, fullmatch로 개행을 거부하며, 미래·인접 분기를 대체하지 않는다. 업종(`SUPPORTED`)과 명칭(`CHANGES`)은 기존 상수를 재사용한다. status 규칙(None/양쪽 null=no_data, 한쪽=partial, 0=available), 분기 일치, period_basis 기본값 없음, false 플래그 고정이 설계와 맞다. dataclass의 init=False 기본 필드 뒤에 비기본 필드를 두는 상속은 init 인자 순서상 유효하다.
- 생활인구: 격자별 72조합 집합 일치, 예상 밖·중복·scope 불일치 거부, absent/suppressed/missing 별도 집계, 불완전 시간 None, 시간별 상한 1e15(`_INPUT_LIMIT`와 일치), -0 정규화가 설계와 맞다. 그 결과를 기존 `calculate_day_night`에 그대로 전달하고 false 플래그를 고정한다. 기대 구성을 관측 row에서 역생성하지 않으며, 그 근거는 계속 caller 책임이다.

PASS 전환 조건: 위 필수 1(4건 사유 분류와 비-fail-safe 사유 수정)과 필수 2(테스트 2종)가 반영되고, Codex의 재검사 결과가 이 문서에 기록되어야 한다. 그 뒤에도 공개 활성화·source 승인·배포는 별도 미완료 항목으로 남는다.

## 9. Codex 구현 검토 대조와 추가 보완

실제 구현 검토는2026-11-16T01:05:56Z~01:08:03Z exit0/is_error=false/3turns였다. MD SHA `dad6966ccf7972ba47aefa17de4a6d6b36acdd5065c4210e88c7fe8b558b6d83`→`952d72b56e1f57d920b717d6a923047920215332f40af9f71a2f2c5674c6e7d1`, 실제 MD 변경·제공 소스 SHA 보존·permission_denials0을 확인했다. 검토의 REVISE 사유를 대조해 모두 반영하고 최종 재검토를 진행한다.

필수1: 같은 RR READ ONLY snapshot에서 이탈4건을 별도 대조했다. 모두 이전 `semas_address_corroborated`에서 새 `multiple_outlets_or_licenses`로 바뀌었다. 새로 인식한 주소 후보 때문에 기존 단일 업소/인허가 대조의 유일성을 입증하지 못해 미확인 처리된 것이다. Claude의 a~c는 당시 가설이며 이번 실제 분류 결과가 아니다. 확대된 registry에서도 기존의 len(candidates)/local_counts 유일성 조건을 완화하지 않는다. 92건은 catalog→검토 seed canonical 변경이며 이탈/새로 발견한 정답 수가 아니다. 별도 precision/recall은 미측정이다.

필수2: 다른 seed 간 normalized prefix 중첩은 기존 본죽→본죽&비빔밥만 있다는 불변식과 신규 seed가 섞인4개 이름의 비추정 회귀를 추가했다. 추천대로 Decimal Context의 rounding/Emin/Emax/capitals/clamp/flags/traps를 전부 고정하고 DefaultContext 변조 회귀도 추가했다. 원천 모델 repr은 모든 값이 숨겨지며 scope의 datetime·중복 격자 거절을 검사했다. 상권변화 평균이 모두null인 available은 변화 코드 자체의 존재를 뜻하며 평균은 여전히null이다.

할리스커피 exact alias는 [할리스 공식 매장 안내](https://www.hollys.co.kr/store/korea/korStore.do)의 표기를 확인한 뒤 추가했다. 기존 FTC ref는 그대로이고 공식 현재명 할리스를 대체하지 않는다. Codex는 특정 월 basis가 월 식별자 없이 표현되는 모호함도 찾아, `specific_month`일 때 같은 선택 분기 안의 월초 date `source_month`를 필수로 요구하도록 했다. 분기 총액/월평균에서는 source_month를 허용하지 않으며 원천값 환산은 없다. 오류 basis/다른 분기/월중 날짜/문자열/datetime을 거절하는 회귀를 포함한다.

소규모 체인 보강은 공식 명칭을 검토 목록에 추가한 것이며 현재 자료에 모두 매칭됐다는 의미가 아니다. 별도 READ ONLY 후보 검사에서 지원 모집단의 블루보틀 포함 이름3건은 현 규칙에서 unknown이고 프릳츠/앤트러사이트 포함 이름은0건이었다. 이름이 일부 들어갔다고 자동 분류하지 않으며, 이름 후보0건을 해당 브랜드의 실제 점포 부재로 해석하지 않는다. 향후 공식 매장별 주소/명칭 대조와 근거 기반 별칭 보강이 필요하다.

보완 후 신규3파일102통과(0.86초), ruff check/438파일 format 통과다. 최종 전체 검사와 할리스 별칭 추가 후 같은 READ ONLY 비교를 다시 진행하고 최종 검수에 실제 근거를 제공한다. 실제 공식 정의를 새로 확보하거나 API/AI/공개 세대·운영 배포를 활성화한 것은 아니다.

최종 실행 결과: 전체 Windows2438통과·symlink 권한3skip·PostGIS298분리(83.88초), Windows/Linux mypy 각196파일·ruff check/438파일 format·14파일 범위/UTF-8/기존 환경 키 비포함/새 링크 검사 통과다. 기존 미해결 링크1개와 사용자 .env/미추적 파일은 보존했다.

할리스커피 별칭 반영 후 최종 실제 비교는355,835행·추정8,778→10,813(순증2,035)·미확인347,057→345,022,110.59초다. 기존 이탈4건의 사유는 위와 동일하게 semas_address_corroborated→multiple_outlets_or_licenses이며92건의 catalog→검토 seed 재연결도 같다. 동일 입력 hash·소진공 SHA·READ ONLY 트랜잭션을 확인했다. 이 비교는 같은 규칙 v2에서 registry 효과를 본 것이며 v1→v2의 독립 정확도 평가가 아니다. 새 publication을 쓰거나 운영/테스트 서버를 전환하지 않았다. 현재 검증한 source 이후 구현 변경 없이 실제 Claude 최종 검토와 PR CI를 진행한다.

## 10. Claude 최종 검토 (2026-11-16)

판정: **PASS**. 대상은 사용자가 요청한 세 BE 항목(검토 registry 확장, 매출·상권변화 분기 선택/typed 원천 투영, 생활인구 구성 완전성 조립→기존 주야간 계산)의 내부 구현 기반 범위다. 이 판정은 소스 검증, 공식 정의 확보, 공개 API/AI 활성화, 실제 precision/recall, 새 publication, 배포가 완료됐다는 뜻이 아니다.

범위와 한계: 이 MD, 대화로 제공된 소스·테스트 발췌, Codex 실행 근거 요약만 읽고 대조했다. Claude는 테스트·셸·DB·네트워크를 실행하지 않았다. 공식 사이트·공정위 ref·RR snapshot도 직접 확인하지 않았다. 테스트 통과 수(2438통과 등)와 READ ONLY 비교 수치(8,778→10,813, 이탈4건 사유)는 모두 Codex 보고값이며 Claude가 재현한 것이 아니다. 공식 별칭 표기(예: `메가커피`, `할리스커피`, 프릳츠 매장명)의 근거도 Codex가 확인했다고 보고한 것이다. CI Linux/PostGIS/CodeQL 결과 근거는 아직 없다.

§8 필수 사항 해소 확인:
1. 이탈4건: Codex 보고에 따르면 4건 모두 `semas_address_corroborated`→`multiple_outlets_or_licenses`다. 제공된 `linking.OutletIndex.corroborate`를 읽어 보면 이 사유는 `len(candidates) != 1` 또는 `local_counts != 1`에서만 나오며, 확장 registry가 같은 주소에 새 후보 점포를 색인하면 생길 수 있다. 이것은 유일성을 입증하지 못해 unknown으로 남기는 fail-closed 동작이고 오탐을 만들지 않는다. 조건을 완화하지 않은 결정이 맞다. 다만 이 4건은 recall 손실 가능성이 있으며 정답 여부는 측정되지 않았다.
2. 테스트2종: `test_reviewed_seed_prefix_overlap_is_limited_to_explicit_bonjuk_family`(branch_patterns parent의 alias가 다른 seed alias의 prefix가 되는 경우 = 본죽→본죽&비빔밥만)와 `test_mixed_reviewed_brands_do_not_become_estimates`(4개 이름)가 추가됐다. 소스를 따라가 보면 예: `이디야커피 할리스점`은 suffix에 다른 seed의 pattern alias `할리스`가 있어 `branch_words_allowed`가 거부한다. 그 결과는 unknown이다.

§8 권고 반영 확인: Decimal Context 전체 속성 고정 및 DefaultContext 변조 회귀, `ReferenceModel.__repr_args__`로 원천 repr 전부 비노출, scope datetime·중복 격자 거부 테스트가 있다. `할리스커피`는 exact alias이면서 pattern alias가 됐는데, 같은 seed 안이라 parent/subbrand guard에 걸리지 않고 같은 브랜드로 수렴한다. `specific_month`의 `source_month`를 필수로 둔 것은 월 식별자 모호성을 줄이는 보수적 보완이며 §3에 반영했다.

세 항목별 결론:
- 브랜드: 17개 seed가 `BrandSpec.valid`를 통과하는 형태다(query 없는 https URL, 3자 이상 alias, reviewed_on≤오늘 KST). ftc_ref 쌍이 서로 중복되지 않는다(더본코리아 계열은 headquarter가 같지만 management_no가 다르다). catalog exact-only를 유지하고 퍼지/부분 문자열 catalog 매칭은 없다. 미승인 동명 catalog는 conflict 또는 `ambiguous_reviewed_catalog_name`으로 fail-closed된다.
- 매출·상권변화: 분기 선택은 미래/인접 분기를 대체하지 않는다. 투영은 원천값을 그대로 두고, null/0/행 부재를 구분하며, 분기 일치와 명시 basis를 요구한다. false 플래그는 고정돼 있다. `당월` 의미는 미해결이라 실제 자료를 이 모듈로 서비스하면 안 된다는 경계가 유지된다.
- 생활인구: 격자×source×hour 72조합 집합 일치, scope 동일성, 부재/비공개/누락 별도 집계, 불완전 시간 None을 확인했다. 시간 상한 1e15가 `calculate_day_night`의 입력 계약과 일치한다. 기대 구성(행정동 구성 포함)의 공식 근거는 여전히 caller 책임이며 확보되지 않았다.

비차단 잔여(후속 처리, 현재 오탐 근거는 없음):
- 혼합 브랜드 검사는 pattern alias만 본다. branch_patterns=false인 프릳츠 alias와 ftc_exact catalog 이름은 `branch_words_allowed`의 다른-브랜드 검사에 들어가지 않는다. 그래서 소스를 읽어 보면 `이디야커피 프릳츠점` 같은 이름은 이디야 estimated가 될 수 있다. 실제 발생 가능성은 낮지만 §2의 "혼합 브랜드" 요건을 완전히 덮지 못한다. 후속으로 reviewed seed의 exact alias도 다른-브랜드 suffix 거부에 포함할지 검토하고 회귀 테스트를 추가할 것을 권고한다.
- 이탈4건과 블루보틀 포함 이름3건 unknown은 recall 공백 후보다. 공식 매장별 주소/명칭 대조 없이 규칙을 완화하지 않는다.

남은 미완료 항목(이 PASS로 해소되지 않음): OA-15572 `당월` 의미, OA-15576 미확인, 도형/기간 문의 미제출, 생활인구 기대 구성의 공식 근거, source 승인, 공개 API/AI·typed 공개 schema/FE 계약, precision/recall 측정, 새 publication 재계산, CI Linux/PostGIS/CodeQL, develop Squash 및 배포.

## 11. 최종 검토 대조와 exact seed 혼합 방어

실제 최종 검토는2026-11-16T01:12:38Z~01:14:01Z exit0/is_error=false/5turns, MD SHA `93b27d2f293d869b50240fdf9af4b16084ffb8a05e11b9544efd5f2464241a9a`→`3b313de817b5f2918a2962eaa1b3d97b09e3a0eeb877d378cc4467289d6fb9cb`였다. MD 변경·제공 소스 SHA 보존·permission_denials0을 확인했다. Codex가 §3의 source_month 요구와 §10 판정/이탈4건의 해석 한계를 대조해 수용했다.

비차단 권고 중 검토 exact-only seed의 혼합 이름 문제도 이번에 수정한다. `reviewed_aliases`에는 branch_patterns와 독립적으로 모든 reviewed_seed alias를 모으고, 다른 브랜드의 지점 suffix에 포함되면 거부한다. catalog alias 전체를 부정 단어로 쓰거나 exact-only seed의 suffix positive를 추가하지 않는다. 프릳츠의 점 없는 공식 전체 표기는 그대로 exact로만 인식한다. `이디야커피 프릳츠점`·`메가커피 하이브 프릳츠점` 회귀2개를 추가했고 신규 registry/기존 matching/linking81개가 통과(1.33초)했다. 이 구현 delta 이후 전체/실제 비교/정적 검사와 제한된 최종 재검토를 이어간다.

## 12. Claude 제한 delta 검토 (2026-11-16)

판정: **PASS** (§10 이후 matching 변경 delta에 한정). PR 진행 조건은 아래 "PR 전 필수 기록"이다. 이 판정은 소스 검증, 공식 정의 확보, 공개 API/AI 활성화, precision/recall, CI, 새 publication, 배포가 완료됐다는 뜻이 아니다.

범위와 한계: 이 MD, 대화로 제공된 `etl/chains/matching.py`·`linking.py`·`registry.py`·`registry.json`, `tests/etl/test_chain_registry_expansion.py`·`test_chains_matching.py` 발췌, Codex 실행 근거 요약만 읽고 대조했다. Claude는 테스트·셸·DB·네트워크를 실행하지 않았다. "81통과(1.33초)"는 Codex 보고값이고 Claude가 재현한 것이 아니다. §10의 전체 2438통과와 RO 10,813은 이 delta **이전** 소스의 값이므로 현재 소스의 근거로 쓰지 않는다.

delta 대조 결과:
1. **변경 범위가 negative 전용이다.** `ChainMatcher.__init__`에서 `reviewed_aliases`는 `origin == "reviewed_seed"`이면 branch_patterns와 무관하게 수집된다. 사용처는 `branch_words_allowed`의 다른-브랜드 거부 검사뿐이다. `self.exact`과 `self.patterns`의 구성은 바뀌지 않았다. 그래서 프릳츠(exact-only)나 ftc_exact catalog에 suffix positive 경로가 새로 생기지 않는다. catalog alias는 부정 단어 목록에 들어가지 않는다(`origin` 조건).
2. **실질 추가 부정어는 프릳츠 alias뿐이다.** 제공 registry.json에서 branch_patterns=false인 reviewed seed는 `fritz-kr` 하나다. 다른 16개 seed의 alias는 이미 pattern을 통해 부정어였다. 프릳츠 alias는 모두 `프릳츠`를 부분 문자열로 포함하므로, 효과는 "다른 브랜드의 지점 suffix에 `프릳츠`가 있으면 거부"와 같다. 자기 브랜드는 `brand_key` 비교로 제외된다. 다만 프릳츠는 pattern이 없어 `classify`에서 이 검사를 호출하지 않으므로, 자기 제외는 현재 `linking`에서 프릳츠 outlet branch를 검사할 때만 의미가 있다.
3. **회귀 2건의 경로가 소스와 맞다.** `이디야커피 프릳츠점`에서 exact hit는 없다. `이디야커피` pattern의 suffix `프릳츠점`과, `이디야` pattern의 suffix `커피 프릳츠점`이 모두 `프릳츠`에서 거부된다. `이디야` 경로의 parent/subbrand guard는 `이디야커피`가 같은 seed(j==i)라 건너뛰지 않는다. 결과는 unknown이다. `메가커피 하이브 프릳츠점`도 같은 방식으로 거부된다.
4. **linking 영향은 양방향이며 RO 재비교가 필요하다.** `OutletIndex`도 `branch_words_allowed(outlet.branch, …)`를 쓴다. 그래서 다른 브랜드 outlet의 branch에 `프릳츠`가 있으면 그 outlet은 색인에서 빠진다. 색인 축소는 (a) 해당 주소의 corroboration을 없앨 수 있고, (b) 이전에 후보가 2개라 `multiple_outlets_or_licenses`였던 주소를 후보 1개로 만들 수도 있다. (b)도 기존 유일성 정의(체인 추정 outlet 기준과 `local_counts`)와 alias+branch 완전 일치·층/호 호환 검사를 그대로 거치므로 규칙 완화는 아니다. 실제 영향 크기는 RO 재비교로만 알 수 있다. §9의 블루보틀3/프릳츠0 후보 검사로 보면 작을 것으로 예상하지만 확인되지 않았다.

비차단 권고:
- `test_mixed_reviewed_brands_do_not_become_estimates`는 `!= "estimated"`만 검사한다. 위 소스 경로상 6개 이름 모두 `unknown`이다. 따라서 `== "unknown"`으로 고정하면 conflict로 바뀌는 회귀도 잡을 수 있다.
- ftc_exact catalog 이름이 다른 seed 지점 suffix에 들어간 경우(예: `이디야커피 <catalog명>점`)는 계속 막지 않는다. catalog 전체를 부정어로 쓰면 과잉 거부 위험이 있어 의도적으로 제외했으며, 이는 §2의 "혼합 브랜드" 중 reviewed seed끼리만 덮는 범위로 기록한다. 후속에서 필요하면 근거 기반으로 판단한다.
- reviewed exact alias가 추가될 때마다 다른 seed의 지점 suffix 거부가 넓어진다. 앞으로 짧거나 일반적인 exact alias를 추가할 때는 이 부정 효과도 함께 검토한다.

PR 전 필수 기록(이 PASS의 조건): 현재 소스 기준 전체 Windows 검사, Windows/Linux mypy, ruff check/format, 범위/UTF-8/환경 키/링크 검사, 같은 RR READ ONLY snapshot 재비교의 실제 Codex 결과를 이 문서에 새로 기록한다. 재비교에는 §9 대비 추정/미확인 수의 변화, 이탈 사유 코드 분류, 입력 hash·소진공 SHA·READ ONLY 확인을 포함한다. 이전 값(2438, 10,813)을 이 delta의 결과로 재사용하지 않는다. 재비교에서 fail-closed가 아닌 새 이탈 사유가 나오면 PR 전에 다시 검토한다.

남은 미완료 항목(변동 없음): OA-15572 `당월` 의미, OA-15576 미확인, 도형/기간 문의 미제출, 생활인구 기대 구성의 공식 근거, source 승인, 공개 API/AI·typed 공개 schema/FE 계약, precision/recall 측정, 새 publication 재계산, CI Linux/Windows/PostGIS/CodeQL, develop Squash 및 배포.

## 13. 제한 검토 수용과 현재 소스 검증

제한 delta 실제 검토는2026-11-16T01:15:36Z~01:16:30Z exit0/is_error=false/3turns, MD SHA `b8bf511dd8cd470608a368be605466377bdf0b7ff7ee4f1c1bb9715cbcbcf6fa`→`77112dcffdfec6b39f570060fb174d7a1eeef6c3167108cb9dc1ed0f6430dc52`였다. MD 변경·제공 소스 SHA 보존·permission_denials0을 확인했고 Codex가 실제 §12의 판정/소스 경로/PR 전 필수 조건을 대조해 수용했다.

현재 소스의 전체 Windows2440통과·symlink 권한3skip·PostGIS298분리(89.24초), Windows/Linux mypy 각196파일, ruff check/438파일 format,14파일 범위/UTF-8/기존 환경 키 비포함/새 문서 링크 검사가 통과했다. 사용자 원본 .env/미추적 파일 보존도 확인했다. 기존 미해결 링크1개와 Starlette/httpx 경고1개는 유지한다.

현재 matching delta로 다시 실행한 같은 RR READ ONLY snapshot 비교는355,835행·추정8,778→10,813·미확인347,057→345,022(113.52초)다. delta 이전 §9 대비 추정/미확인 변화0, 이탈4건 사유는 여전히 semas_address_corroborated→multiple_outlets_or_licenses, canonical 재연결92건이다. 입력 hash·소진공 SHA 보존과 READ ONLY를 확인했다. 새 비-fail-safe 이탈 사유는 관측되지 않았으며 §12 PR 전 기록 조건을 충족했다. 실제 정답 판정이나 precision/recall은 측정하지 않았다.

비차단 제안의 mixed test는 `!= estimated`를 유지한다. 이 테스트의 계약은 혼합 이름을 양성으로 승격하지 않는 안전 조건이며, 추가 근거로 unknown/conflict가 달라지는 것은 허용한다. reviewed alias만 부정 검사하고 catalog 전체는 제외하는 범위도 유지한다. source 이후 추가 구현 변경 없이 PR을 진행한다. 최종 현재 head의 Linux/Windows/PostGIS·CodeQL 성공과 정상 Squash·주 BE ff-only·보존 검증은 #174 연결 PR에 기록한다. 공식 자료와 실제 공개 활성화 잔여는 #115/#78에서 계속 추적한다.
