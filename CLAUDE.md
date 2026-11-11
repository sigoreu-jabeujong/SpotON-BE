# SpotON-BE 작업 기준

BE의 범위·계획·API·ETL·개발 규칙은 다음 통합 문서 하나에서 관리한다. 작업 전에 읽고 필요한 기준 변경도 통합 문서에 반영한다.

@docs/be-work-plan.md

[BE 개발 기준 및 작업계획](docs/be-work-plan.md)

## 점포 이력 API 계약 (BE #36)

`GET /api/stores/history`는 building_key로 지원 업종 전체 이력을 조회한다. category는 선택 진단 맥락이며 필터가 아니다. 각 항목에 source를 반환하고 식별자는 source+license_no다. name/open_date/close_date/operating_months는 null을 허용한다. 기간은 달력상 완료 개월 수, `operating_period_status=fact|no_data`, `operating_period_reason=사유 코드|null`이며 미산정을 0으로 만들지 않는다. 영업 중 종료점은 검증된 DAT_UPDT_PNT 최대 날짜, 폐업 종료점은 확인된 폐업일이다. 층만 같으면 same_spot이 아니다. 일반 입력 오류는 현행 422 INVALID_PARAM, 공통 외피와 오류 meta={}는 유지한다. 상세 설계는 docs/designs/feat36-store-history-api.md를 따른다.

2026-11-12 사용자 지시에 따라 FE 저장소를 직접 수정하거나 FE 이슈·PR을 생성하지 않는다. FE 타입·화면·CLAUDE.md 동기화는 [FE 수정 요청 보고서](docs/fe-store-history-api-request.md)로 전달하고 담당자 반영을 기다린다. 현재 FE 연동은 미완료다.

## 주변 점포 API 계약 (BE #41)

`GET /api/stores/nearby`는 lat/lng/category 필수, radius=300/500/1000m(기본 500)다. category/sub_category는 실제 업종 필터이며 날짜가 유효한 점포를 선택 월말(최신 월은 전역 원천 갱신일) 기준으로 조회한다. 후보는 geography 거리 반경+0.01m, 최종은 반올림 전 ST_Distance<=반경이며 출력만 소수 첫째 자리로 표시한다. `source+license_no`로 식별하고 최신 상태·전체 운영기간을 반환한다. 0㎡는 원본 보존·응답 null·면적 unknown이며 면적/가맹 unknown 토글은 독립적이다. legacy include_unknown은 단독 사용만 허용한다. 좌표 미확보 수는 서울 전체의 같은 비공간 조건이며 meta.excluded_no_coord_scope=seoul_nonspatial_cohort로 명시한다. 이력 API의 결측 이력 보존은 변경하지 않는다. 상세는 docs/designs/feat41-nearby-api.md, FE 변경은 docs/fe-nearby-api-request.md를 따른다.

2026-11-12 사용자 지시에 따라 BE PR은 로컬 검사·CI 및 저장소 조건 확인 후 develop에 자동 Squash 병합한다. GitHub 본인 승인 제한·보호 규칙을 우회하지 않으며 main 반영·수동 브랜치 삭제·강제 푸시는 별도 요청 범위다.

## 조회 가능 월 범위 API 계약 (BE #43)

`GET /api/meta/data-range`는 category 필수·sub_category 선택이며 다른 조회 인자는 받지 않는다. nearby와 같은 출처·날짜 후보로 최소 개업 월을 계산하고 좌표·반경·면적·가맹 조건을 섞지 않는다. 응답은 min_month(유효 표본이 없으면 null), max_month(전역 원천 갱신일의 월), max_date/data_updated_at(전역 갱신일), collected_at(현재 null)이다. 원천/기준일 미준비는 500, 검증된 D가 있는 빈 category는 정상 응답의 min_month=null로 구분한다. meta.space=seoul, denominator=null, data_version.rule_version=store-data-range-valid-license-v1이다. FE는 docs/fe-data-range-api-request.md에 따라 담당자가 반영하며 snapshot 계약은 아래 BE #45 절을 따른다.

2026-11-12 최신 PR 제목 요청은 `feat: 조회 가능한 데이터 월 범위 API 구현`처럼 `타입: 한국어 작업 설명` 형식을 따른다. 커밋의 `타입(영역): 한국어 요약` 기준은 유지한다.

## 과거 시점 점포 조회 계약 (BE #45)

`GET /api/stores/snapshot`은 nearby와 같은 입력·집합·순서·기간을 사용하되 as_of=YYYY-MM이 필수다. N=total_at_as_of=still_open+closed_since+other=stores.length이며 같은 목록에서 최신 기록 open/closed/other를 집계한다. source+license_no 식별, nullable 상호·기간 및 기간 상태/사유를 제공한다. 기간은 T까지가 아닌 최신 데이터 기준 전체 기간이고 요약은 실제 T와 최신 데이터 기준 상태를 사용한다. excluded_no_coord는 서울 동일 비공간 조건의 좌표 미확보 수로 N과 합산하지 않는다. 중복·응답 불변식/모델 검증 실패는 부분 응답 없는 안전한 500·no-store다. 상세는 docs/designs/feat45-store-snapshot-api.md, FE 변경은 docs/fe-store-snapshot-api-request.md를 따른다.

## 상권 경계 적재 기준 (BE #47)

현재 migration head는 0009다. `python -m etl.market_areas`는 공식 OA-15560 ZIP의 hash·첨부 수정일을 받아 기본 읽기 전용 dry-run, --write일 때 일반 로컬 앱 계정에서 원자적으로 적재한다. EPSG:5181 원본의 무효 도형만 linework 보정 후 유효 MULTIPOLYGON 4326·GIST로 저장한다. 원본 면적·hole/multipart·타입/5자리 구 코드를 보존하고 버전/데이터 digest를 검증한다. 같은 원본/규칙 재실행은 불변 버전을 재사용하며 기존 버전 수정/삭제·최신 자동 선택은 하지 않는다. source_file_date는 첨부 수정일이고 boundary_as_of는 미확인 null이다. 후속 통계 분기와의 코드/경계 호환 전에는 지표에 자동 적용하지 않는다. 현재 1,650행·6개 보정, 기존 stores 689,440건이다. 상세는 docs/designs/feat47-market-areas-import.md를 따른다. API 응답/FE 변경은 없다.

## 공식 점포 통계 적재 기준 (BE #49)

`python -m etl.market_stores`는 OA-15577 공식 연간 ZIP을 hash·완료 연도·첨부 수정일·대조 경계 UUID로 검증한다. 전체 행을 검사하고 지원 업종 5종만 적재하며 source_year/quarter와 source_file_date를 구분한다. SIMILR_INDUTY_STOR_CO=전체, STOR_CO=일반, FRC_STOR_CO=가맹이다. 공식 원천 비율은 100% 초과·null·0을 그대로 보존하며 누락 조합을 0으로 채우지 않는다. 기본 READ ONLY dry-run, --write는 연간 원자적 적재·동시 writer 직렬화·저장 내용 hash 재검증을 수행한다. 원본/규칙/대조 경계별 불변 버전을 보존하며 재실행은 같은 버전을 재사용한다. code_check_boundary_version_id는 코드 대조 근거일 뿐이며 boundary_compatibility=unverified다. 현재 2025년 4개 분기 24,810행이고 최신 분기 보장·통계/인허가 모집단 동일성·경계 적용일은 미확인이다. 데이터가 있는 공식 통계 테이블의 downgrade는 실패한다. 상세는 docs/designs/feat49-market-stores-import.md를 따른다. API/FE 변경은 없다.

## 추정매출 원천 적재 기준 (BE #51)

`python -m etl.market_sales`는 OA-15572 공식 연간 ZIP의 55개 헤더·48개 수치를 검증하고 지원 업종만 적재한다. est_sales=당월_매출_금액(원), source_sales_count=당월_매출_건수의 BIGINT 원천값이며 환산·합산·점포당 매출 계산을 하지 않는다. 빈 셀 null·실제0·누락 행을 구분한다. 지정 점포 통계와 같은 연도·대조 경계인지 확인하고 두 기준의 DB 내용 hash와 조합 차이를 대조한다. amount_period_status/boundary_compatibility는 unverified, currency=KRW, amount_basis=source_reported다. 원본/규칙/두 기준 버전별 불변 적재·재조회 hash·동시 writer 직렬화·전체 rollback·replay를 제공한다. 기본 REPEATABLE READ READ ONLY dry-run이며 --write에만 저장한다. ZIP/provenance/경계 대조 공통화는 BE-17의 hash/오류/출력/lock key를 유지한다. 최신 분기·매출 집계 기간·경계 적용일·모집단 동일성은 미확인이고 공개 API/FE 변경은 없다. 상세는 docs/designs/feat51-market-sales-import.md를 따른다.

## 생활인구 적재 기준 (BE #53)

`python -m etl.living_pop --manifest PATH [--write]`는 공식 EPSG5179 SHP와 같은 날짜의 local/long/short ZIP을 검사한다. 격자는 living_grid_versions/living_grids, 관측은 living_population_versions/living_population_observations에 불변 버전으로 저장한다. 행정동·시각·원천 차원을 보존하고 총계 Decimal Numeric(20,5)의 observed/suppressed/missing, 실제0·행 없음·unlocated를 구분한다. `*`를 복원·0 변환하지 않는다. 숫자의 후행 소수점은 Claude와 검토한 명시적 v1 문법으로 처리하며 원문 hash를 보존한다. 사용자 결정대로 미매칭24행은 grid_id 유지·located_grid_id=null·공간 inner join 제외다. located 참조와 버전/날짜는 복합 FK로 보장한다. 전역 source/date 미확인 수와 반경 내 missing_grid_count를 섞지 않는다. 기본 READ ONLY, --write는 격자/세 원천을 한 트랜잭션으로 처리하며 hash/건수 검증 후 commit한다. grid_as_of=null·spatial_compatibility=unverified, 자동 백필/최신 선택·API/FE 변경은 없다. 상세는 docs/designs/feat53-living-population-import.md를 따른다.

2026-11-12 사용자 지시에 따라 유사한 데이터/설계 선택은 Claude Code의 실제 MD 검토와 Codex 최종 점검 후 적절한 안을 선택하고 근거를 남긴다. 동일한 통상 선택을 사용자에게 반복 확인하지 않는다. 필수 자료·키·권한이 없으면 기존대로 요청한다.

## 시스템 점검 보완 기준 (BE #58)

LLM 전체 await(재시도 대기 포함)와 개별 요청은 asyncio timeout으로 취소하고, 늦은 정상 응답도 monotonic deadline으로 거절한다. 바깥 취소는 전파하며 TimeoutError를 처리한 except 밖에서 안전한 LlmError를 발생시켜 원문 context를 남기지 않는다. Retry-After의 비유한 값은 제한된 기존 backoff로 처리한다. 카카오 지번 숫자는 앞0을 뗀 유효4자리 범위만 int로 변환하며 부적합 값은 기존 주소 오류 경로를 따른다. 상권변화 CSV의 분기 상한은 실행일이 아닌 retrieved_at의 Seoul 분기다. 확정 미사용이 아닌 ORM/프레임워크 등록·후속 AI 모듈·의도된 예외 타입은 정적 참조만으로 삭제하지 않는다. 점검·Claude 실제 검토·수정 근거는 docs/designs/feat58-system-audit-cleanup.md를 따른다.

## 공식 상권변화 유형 적재 기준 (BE #55)

`python -m etl.market_changes --csv PATH --expected-sha256 HEX --source-year YYYY --retrieved-at ISO_WITH_ZONE --code-check-boundary-version UUID [--write]`는 OA-15576 전체 CSV를 검사하고 선택 완료 연도만 적재한다. 업종 필드가 없으며 원천 LL/LH/HL/HH와 공식 명칭·평균 정수개월4개를 그대로 보존한다. 빈 셀null·실제0·행누락을 구분하며 평균으로 유형을 재계산하거나 점수/자체 판정을 만들지 않는다. 기본 REPEATABLE READ READ ONLY, write는 격자 등 다른 원천 없이 독립 연간 트랜잭션·advisory lock20·재조회 hash 검증을 수행한다. 같은 bytes/연도/규칙/경계는 불변 버전을 재사용하며 수집 시각 등 provenance 충돌/저장 훼손은 거절한다. source_file_date=null·retrieved_at은 최초 다운로드시각, boundary_compatibility=unverified다. 실제 2025년6,600행이고 2026년 자료나 전체 기간 백필·market_change API/FE는 후속이다. 상세는 docs/designs/feat55-market-change-import.md를 따른다.

## 기본 상권 활동 분석 계약 (BE #60)

`GET /api/market/activity`는 nearby 입력에 선택 include=sales,living_pop을 더한다. 폐업 기록을 제거하지 않는 유효 인허가 코호트에서 최근 `(T의 전년 같은 월일, T]` 개폐업 사건을 센다. 존재하지 않는 날짜만 clamp하고 연도별 추이는 실제 사건 연도만 반환하는 같은 월일 YTD다. T에 유효한 세부 업종별 점포 수와 완료 개월의 정수 평균(버림)을 반환하며 0분모는 null·실제 0개월은 0이다. latest 전체 기간·수명 평균·생존율과 구분한다. 최종 거리는 반올림 전 반경 이하다.

선택 수치는 이번 릴리스에서 항상 null이며 요청 항목만 flags.missing과 meta.optional_data의 pending/사유에 넣는다. 미요청과 원천 조건별 no_data를 섞지 않는다. 브랜드 승인 전 meta.franchise_classification은 pending이며 가맹 unknown을 개인으로 만들지 않는다. denominator=null, cohort_size는 폐업 포함, excluded_no_coord는 서울 동일 비공간·T 이전 개업 코호트라 nearby와 다를 수 있다. 출처 R5/R6·D/T/collected_at=null을 보존하며 읽기 전용 일관된 세션·no-store·안전한 오류 응답을 따른다.

상세와 Claude 검토 후 Codex 최종 규칙은 docs/designs/feat60-market-activity-api.md를 따른다. FE 타입·표시·CLAUDE.md는 docs/fe-market-activity-api-request.md로 요청하며 담당자 반영 대기다. BE-21·조건부 수치·BE-22 전체 결합·FE 통합 완료로 표시하지 않는다.

## Risk 선행 상권 공간 판정 (BE #62)

`judge_market(session, BoundaryQuery)`는 서버가 명시한 경계 UUID에만 ST_Covers를 적용한다. 세부 상권 A/D/R은 같은 우선순위이며 하나면 primary, 여러 개면 ambiguous/candidates로 보존한다. 관광특구 U는 세부와 함께 있으면 also_in이며 특구만 여러 개여도 임의 선택하지 않는다. 밖에서만 polygon-point geography 최단거리 반경 교차 목록을 제공하고 가까운 상권의 공식 수치로 대체하지 않는다. 행 수가 버전 row_count와 다르거나 버전이 없으면 안전하게 실패한다.

결과는 지정 파일의 공간 판정이며 provenance.applicability=unverified다. source_file_date/loaded_at·boundary_as_of 하나로 현재/과거 적용성·분기 호환을 확정하지 않는다. 이 상태의 primary/candidates를 공식 통계 조인의 근거로 사용하지 않는다. 호출자가 READ ONLY REPEATABLE READ 세션을 제공하며 서비스는 세션을 변경하지 않는다. #62는 내부 기반 범위이며 상세·Claude 검토·실제 검증은 docs/designs/feat62-market-judgement.md, 후속 공개 Risk 참고지표 계약은 아래 #64를 따른다.

## Risk 참고지표 API 계약 (BE #64)

`GET /api/risk`는 nearby 입력과 include=market_change,day_night_ratio를 받는다. 기간 중 영업 기록 분모10의 최근12개월 참고 폐업률, 개업 코호트 `(T-(n+1)년,T-n년]`의 고정 n주년 생존율(표본5), T의 동종업체 수를 반환한다. 생존은 close가 없거나 개업 n주년보다 뒤여야 하며 주년 후 T전에 폐업해도 포함한다. 이는 원본의 모호한 현재 잔존 서술을 보완한 BE 계약안이며 원본/FE 합의 완료가 아니다. rule_version=risk-reference-fixed-anniversary-v1·FE 요청서의 차이를 유지한다.

비율은 Decimal HALF_UP 소수1자리, 소표본/0분모는 value/numerator=null·실제 denominator 보존이다. 같은 필터·좌표 확보 서울의 분자합/분모합을 비교하며 competitor_count에는 서울 평균을 붙이지 않는다. source는 배열이고 지표별 분모를 쓰므로 공통 denominator=null이다. flags의 표본 부족은 로컬 비율에만 적용하며 missing은 필수 검증 경계/요청 선택 자료에만 쓴다.

선택 서버 설정 RISK_BOUNDARY_VERSION_ID가 있어도 후보 미리보기만 제공하며 market.status=unverified, 확정 상권 필드는null이다. 없는 설정을 최신 버전으로 대체하지 않는다. 공식 폐업률/상권변화 유형·인구비는pending이고 공식 창업위험도는link_only다. 가맹 분류 미확인·D/T/collected_at=null·좌표 범위와 인허가/지위승계/과거 재구성 한계를 보존한다. 기존 읽기 전용 세션·no-store·안전한500을 따른다. 설계는 docs/designs/feat64-risk-reference-api.md, FE 타입/문구/CLAUDE.md 반영은 docs/fe-risk-reference-api-request.md로 담당자에게 요청하며 대기다.
