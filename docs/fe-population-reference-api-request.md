# 생활인구 공개자료·주야간 비교 FE 연동 요청안 (#178)

2026-11-16 후속 [#180 실제 구현](designs/feat180-population-implementation.md)과 FE #73에서 이 계약을 연결했다. 사용자 최신 요청으로 FE 수정·배포가 승인됐으며 아래 “설계안/미구현”은 #178 당시 이력이다. 실제 서버 반영 여부·commit/검증은 #180 연결 PR 실행 기록을 따른다. 기존 전체 인구/AI 계약을 바꾸지 않고 새 부분자료 API·별도 카드/보고서를 사용한다.

2026-11-16 **설계안, BE endpoint 미구현/미배포·FE 미수정**. [집계·API 설계](designs/feat178-population-api-partial.md)를 따른다. 추후 BE의 실제 구현/배포 커밋·OpenAPI/테스트 결과를 이 문서에 덧붙인 뒤 담당자가 반영한다. 추가 외부 API 키 요청이 아니다.

## 현재 확인과 연결 위치

- 생활인구 요청/카드는 있지만 BE가 null을 반환한다. 주야간 요청 함수/카드는 있지만 `SummaryPage`/`ActivitySection`의 `useRisk(params)`가 include를 전달하지 않는다.
- 새 GET `/api/v2/population-reference`는 기존 활동/Risk를 대체하지 않는다. `getPopulationReference`·hook/query key·mock adapter·전용 부분자료 카드와 보고서 블록을 추가한다.
- 기존 Risk에 include=day_night_ratio만 추가하면 여전히 pending이다. 새 부분자료 응답을 구형 living_pop.total/주야간 RiskIndicator로 강제 변환하지 않는다.

## 요청·응답 핵심

프로필(v1/v2)과 상관없이 항상 `/api/v2/population-reference`를 호출하고 `lat`, `lng`, `radius`, `category`, `sub_category`, `as_of`만 보낸다. include·area·brand_*·franchise 등 다른 인자는 422로 거부된다. category는 필수(cafe|restaurant)이고, sub_category는 생략 가능(기본 빈 값)하며 category에 맞는 값만 허용한다. 이 두 필드는 인허가 기준의 허용 분석월 범위 검증에만 쓰이고 인구 자료를 거르지 않는다. 분석일 T는 점포 원천의 전역 기준일 D와 업종별 최소월로 정해진다. query key는 `['population-reference', 위 6개 인자의 canonical 값(기본값 채움·sub_category 정렬)]`이므로 브랜드/면적/프로필만 바뀌고 6개 인자가 같으면 다시 요청하지 않는다. v1용 legacy 변환 adapter는 필요 없다.

응답의 최상위 `data.status`는 `ready|pending|no_data|not_supported`이고 모두 HTTP 200이다. `ready`일 때만 sources에 [local,long,short] 3개 block이 순서대로 들어온다. 그 밖에는 sources=[]이고, 최상위 reason(`ambiguous_source_version`/`no_observation_in_period`/`scope_too_large`)을 카드 전체 사유로 보여준다. 각 block은 `partial|no_data|not_supported`와 사유, 고정 구성의 원천별 품질과 한계를 준다. 관측일·분석일은 block이 아니라 최상위 `data`에 한 번만 있다. partial은 오류가 아니라 공개된 같은 구성으로 계산한 참고값이다. 새 schema는 합/평균/비중/배수를 decimal 문자열+서버 display/exact_zero/rounded/unit로 제공한다. FE는 산식을 재계산하거나 decimal을 JS Number로 바꿔 출처 수치라고 표시하지 않는다. 숫자는 서버 `display`를 그대로 쓴다(서버는 추가 반올림 없이 천 단위 구분자와 `%`/`배` 접미사만 붙이며 합/평균에는 접미사가 없다). `exact_zero=true`이면 실제 0이고, 표시값이0이고 `exact_zero=false`이면 “0에 가까운 값”으로 표시한다. unit은 `public_source_value_sum|public_source_value_hourly_mean|pct_of_public_subset|ratio`이다. 최종 계약 필드/사유는 설계6절을 따른다.

## 표시와 동작

기본 제목은 “내국인 공개자료 주야간 비교(부분)”. 외국인 두 원천은 자기 제목으로 분리하고 local 부재를 다른 source로 대체하지 않는다. 주간06~17/야간00~05·18~23, 같은 관측일·같은 공개 구성이라는 설명을 둔다. 숫자 옆에 “공개된 동일 구성만 비교한 참고값이며 전체 인구를 대표하지 않아요”를 항상 표시한다.

기본 화면에는 배수·주야 비중·사용 구성 수/후보 구성 수를 보여준다. 합/평균은 “공개 원천값 합(인원수 아님)” 라벨을 붙여 상세 영역에만 둔다. block limitations에 `exclusion_pattern_may_bias_ratio`가 있으면 quality.excluded_by_hour_class 값으로 “주간/야간 한쪽에만 비공개·누락이 있는 구성 N개가 빠져 배수가 달라 보일 수 있어요”를 표시한다. 과대/과소 방향은 쓰지 않는다. 기존 LivingBody의 ‘생활인구 합계 …명’ 표시는 새 값에 쓰지 않는다. 원천값의 합/평균은 인원수가 아니며 배수도 반경 전체의 주야간 인구비가 아니다. 후보 구성 중 사용 수와 선택 격자 중 사용 격자 수는 분모를 구분해 표시한다. 이것을 반경 인구 제공률/대표성으로 바꾸지 않는다. 부분 값은 pending으로 숨기지 않고 no_data인 source만 해당 사유로 비운다. 실제0/반올림0/밤0으로 배수null/전체0으로 비중null을 구분한다.

서버의 날짜/공간/필터 미적용·미검증 한계를 화면과 출력 보고서에서 유지한다. 장소/반경/월/category/sub_category가 바뀌면 요청 취소·새 query key·이전 값 초기화를 사용한다. 브랜드/면적/프로필만 바뀌고 6개 인자가 같으면 재사용한다. 보고서는 같은 요청 key와 응답/token을 함께 사용하며, token만으로 같은 위치·같은 구성이라고 판정하지 않는다(다른 반경이 같은 token을 가질 수 있다). 서로 다른 원천의 D/N을 조합하지 않고, 점포 섹션과 기준일이 다르면 각각의 기준일을 표시한다. 첫 BE 구현에서 이 값은 기존 AI 해석에 포함되지 않는다.

Mock/실제 모드 각각에 새 경로를 등록한다. 다룰 시나리오: local 정상+외국인 없음, 구성 일부 비공개, 야간만 비공개로 제외(편향 경고), 사용 구성 0, 반경 선택 격자 0, 브랜드 인자 전송 시 422, 밤 0/전체 0/반올림 0, 월 내 관측 없음, 같은 날짜 복수 버전 pending, scope 상한, 422/500/503. mock는 실자료 검증이 아니다. BE 배포 전 새 endpoint가 404인 것을 키 문제로 안내하지 않는다.

## 완료 확인

BE: 설계→구현/단위·PostGIS/API 검사→clone 실증→CI/develop→실제 서버 배포를 구분한다. FE: 담당자의 adapter/타입·카드/보고서·모의모드 반영→실제 브라우저 검증을 구분한다. 이번 문서는 설계/전달 완료까지만 표시하며 FE 코드/이슈/PR은 직접 수정하지 않는다.


## 구현용 계약 보완

요청 예: `GET /api/v2/population-reference?lat={위도}&lng={경도}&radius=500&category=cafe`. sub_category와 as_of는 생략할 수 있다. 같은 key 중복, 알 수 없는 key, 빈 값(예: `sub_category=`)은 422다. source block 3개의 순서는 local, long, short로 고정한다. 최상위 ready는 block을 준비했다는 뜻일 뿐이며 개별 source의 partial이나 공식 승인과 같지 않다.

날짜: `analysis_date`는 모든 200 응답에 있다. `observation_date`는 `no_observation_in_period`일 때만 null이다. `scope`에는 radius_m·category·sub_category·as_of·`population_filter_applied=false`·grid_as_of가 오고 좌표는 오지 않는다.

block: partial의 reason은 `public_subset_only`이고 values의 8개 필드(hourly_source_sums 24개, day/night 합, day/night 평균, day/night 비중, 배수)는 모두 필수다. 각 수치 객체는 value/display/exact_zero/rounded/unit/reason을 갖는다. 유효 수치의 reason은 null, 밤 0의 배수는 `zero_night_denominator`, 전체 0의 비중은 `zero_total`이다. rounded는 숫자마다 따로 온다(day 평균과 night 평균이 다를 수 있다). no_data/not_supported source는 values=null이다.

quality: 모든 block 상태에서 다음 정수가 전부 non-null로 온다. selected_grid_count, grids_with_rows, grids_without_rows, candidate_component_count, used_component_count, excluded_component_count, used_grid_count, observed_rows, suppressed_rows, missing_rows, absent_hours_within_candidates, excluded_by_hour_class{day_only, night_only, both}, version_unlocated_rows, version_unlocated_grids. 마지막 두 값은 관측 버전 전체 기준이므로 반경 수치와 더하거나 같은 분모로 표시하지 않는다.

limitations(닫힌 목록): 항상 `not_population_total`, `admin_additivity_unverified`, `grid_period_unverified`, `hour_sums_not_unique_people`가 오고, 조건부로 `exclusion_pattern_may_bias_ratio`, `grid_as_of_unknown`이 온다. 각각에 고정 문구를 매핑한다. 배수는 구성별 배수의 평균이 아니라 공개 구성 주간 합 ÷ 야간 합이다.

원천 수치가 있어도 전체 인구가 pending인 기존 필드를 채우지 않는다. 실제 응답 계약은 [설계 6절](designs/feat178-population-api-partial.md#6-신규-get-계약-첫-구현의-완결-범위)이 우선한다.


서버 meta의 `public_subset_calculation_performed`는 local/long/short별 bool map이다. partial인 원천만 true이며 최상위가 ready가 아니면 모두 false다. 관측 버전이 없거나 복수라 선택되지 않은 응답은 V/G 식별자·SHA와 grid_as_of가 null이다. as_of=null과 빈 sub_category tuple은 URL에서 생략하며 `sub_category=`를 보내지 않는다. 기존 apiGet serializer도 이 생략을 지원한다. 구문 오류는 DB 접속 전422, 실제 허용월 범위 오류는 인허가D/M 조회 뒤422다.
