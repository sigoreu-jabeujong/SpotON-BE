# SpotON-BE 작업 기준

BE의 범위·계획·API·ETL·개발 규칙은 다음 통합 문서 하나에서 관리한다. 작업 전에 읽고 필요한 기준 변경도 통합 문서에 반영한다.

@docs/be-work-plan.md

[BE 개발 기준 및 작업계획](docs/be-work-plan.md)

## Render 무료 검증 배포 기준

2026-11-14 사용자 최신 AI 개편 요청에 따라 #130에서는 FE·BE를 함께 수정하고 모바일 대응을 포함한다. 기존 FE 직접 수정 금지는 이 요청 범위에서 대체한다. [설계·데이터 정합성 검증](docs/designs/feat130-ai-narrative.md)을 따른다. 응답의 연결 본문 body와 문단/지표 IDs/evidence를 추가하고 기존 배열은 내부 근거·호환용으로 유지한다. 모델은 검증된 문단 후보 ID만 선택하며 본문에서 건물 총건수·최신 시점 이후 사건·새 수치·예측을 생성하지 않는다. 프롬프트v8/선택 캐시v4, 기본 한도와20초 예산은 유지한다. FE 정보 팝오버·주소/필터/시점 조건 표시·조건별 캐시/취소·진단서 본문을 함께 맞춘다. 개발 구현과 현재 Render 실행 배포는 구분한다.

현재 Free 웹 spoton-be-free와 DB spoton-db-free를 같은 workspace·Singapore에서 사용한다. SQL10초·풀1/overflow0/대기15초·워커1·예산/reader8이며, 별도 ready 연결을 포함한 교체 상한은4개다. ready는 HTTP2.5초/SQL750ms·성공10초/실패1초 캐시를 유지한다. DB는 내부 TLS require/조회 역할만 사용하며 관리자/ETL 키를 BE에 넣지 않는다. AI용 LLM_API_KEY는 Render 비밀 환경변수로만 주입한다.

Docker app.runtime·PORT10000·비root 실행이며 시작 시 migration/ETL은 하지 않고, 검증한 commit을 수동 배포한다. 앱 모델/head0011·기준50인덱스와 별도 ops_free_risk_cover/ops_free_risk_name_v1 두 운영 인덱스를 구분한다. 이 Free DB를 autogenerate 대상으로 쓰지 않는다. 로컬 .env·기본3초·FE 파일은 변경하지 않는다.

Render 전용 MD는 [현재 구성·복원·만료 안내](docs/render-free-validation.md)와 [FE 연결 안내](docs/fe-render-validation-api-request.md) 두 개로 관리한다. DB 만료일은2026-12-13이다. 설정을 갱신할 때 두 문서와 이 기준의 불일치를 함께 정리한다.

2026-11-14 #122에서 실제 Claude Code 검토2회와 Free DB/동시 API 비교 후, 풀2 후보는 최초 지연 악화로1로 복구하고 검증된8958ba7(#118 출처 고아 검사 최적화)만 별도로 배포했다. 당시 live는dep-dbs37aek1f9s73858g6g이며 SQL10초·풀1/대기15초·워커1·예산8과 키/DB/인덱스는 그대로였다. 당시 동시5 GET×6묶음은30건200·본문 동일, 최초/반복 중앙값9.688/6.110초다. [설계·실제 검토·한계](docs/designs/feat122-fe-feedback.md)를 따른다. 원본 업태가 한식인 치킨/주점 상호의 실제 업종 보정·AI 활성화는 후속이며 FE를 직접 수정하지 않는다. 전체500·절전 복귀 해결로 확대하지 않는다.

#124는 ready 단일 검사의 실행별 Future 결과를 동시 요청자가 HTTP2.5초 안에서 공유한다. SQL750ms·TTL10/1초·별도 연결 최대1·실패500/no-store·닫힘/취소 안전성을 유지하며, 미완료/만료 성공을 정상으로 만들지 않는다. ready 고정 경로와 원문 없는 readiness_probe 사유 로그를 추가했다. 당시 live는7d4846c/dep-dbs3norl550s73fbvskg이며 모든 환경값·풀1·DB/인덱스는 보존했다. ready24건/업무30건200·본문 동등성·CORS/AI503·검증 구간 HTTP500로그0을 확인했다. [설계·실제 Claude 검토2회·검증](docs/designs/feat124-readiness-followup.md)을 따른다. FE PR52의 업태 안내·PR53의 CI98개 통과는 담당자 반영을 확인했다. 실제 업종 보정은 후속이며 AI 활성화는 아래 #127 결과를 따른다.

2026-11-14 #127에서 Render의 LLM 설정 누락을 확인하고 기존 로컬 Gemini 키의 실제 생성 성공 후 LLM_PROVIDER=google·LLM_MODEL=gemini-3.5-flash-lite·비밀 LLM_API_KEY를 추가했다. 당시 live는 같은7d4846c의dep-dbs51tk9v7es73bn89tg(21:16:24 KST)였다. 현재 배포는 아래 #128이다. 카페·한식 query-only POST와 카페 재호출3건이200·verification.passed=true·불일치0·재생성false였고 ready200·세 origin POST preflight200·잘못된 업종422를 확인했다. 기존14개 환경값·Free·자동 배포off를 보존했다. 기본 해석 한도는 프로세스별5회/분·50회/일·동시2이며 공급자 quota는 별도다. FE 브라우저의 해석 표시 검증은 담당자가 수행한다. [현재 운영/검증 범위](docs/render-free-validation.md)를 따른다.

## 음식점 이름 키워드 제외 정책 (BE #128)

2026-11-14 #128은 사용자가 B안을 선택해 음식점4종 이름의18개 키워드를 부분 일치로 제외한다. 원본 분류·이름·배치/D·브랜드 입력을 보존하고 이력/주변/과거/활동/Risk(local/서울/미좌표)/월 범위/AI에 같은 분석 모집단을 적용한다. cafe·null/빈 이름은 유지하며 실제 업종 확정 보정이 아니다. 점포/집계의 `meta.name_exclusion`/`data_version.name_exclusion_version=store-name-keywords-v1`과 Risk/AI 캐시를 함께 구분한다(AI 공개 메타는 기존 해시 계약 유지). 실제 Free에 새 부분 인덱스만 먼저 생성해 원본689,440행 composite/EWKB hash·기존 인덱스·기존 API 본문 보존, direct/generic index-only/Heap Fetches0과 후보454→434를 확인했다. PR131의 CI/CodeQL 통과·develop 병합 후 c4de3ed를 수동 배포해 dep-dbs5fus9v7es73boe6dg가21:46:27 KST에live가 됐다. 기존13후보 전부를 포함해20곳 제외·한식454→434·카페 data 동등·후보와 전체 응답 일치, 동시 업무30건/ready24건200·실제 AI(이력 포함)200/검증57개·불일치0·검증 구간 HTTP500로그0을 확인했다. 모든17개 환경값/LLM 설정·원본 행 지문·기존 인덱스를 보존했다. [설계·Claude 실제 검토2회·검증](docs/designs/feat128-name-keyword-exclusion.md)을 따른다.

## 상세 위치 파서 지명 오인 수정 (BE #102)

기적재 데이터의 후속 검증·개발 DB 보정은 [#104](docs/designs/feat104-floor-location-backfill.md)에서 수행했다. `python -m etl.localdata.floor_backfill --source ... --snapshot ...`은 기본 READ ONLY이며 쓰기는 `--write --expected-plan`이 필요하다. 원본·대상·계획·전체 비위치 값/EWKB가 다르면 중단하고, source별 원자적 UPDATE·새 v2 배치·과거 출처/브랜드/삭제/sequence 보존을 검증한다. stores INSERT·원문/날짜/좌표/업종 교체는 하지 않는다. 현재 PC 개발 DB는 24,738행(지원 업종 등 조건 11,468행) 복구와 재실행 no_op·API 전후 검증을 완료했다. 팀원 DB 자동 적용이나 원천 최신화·모든 NULL 복구는 아니다.

공통 층·호 파서는 `중구`·`중랑구`·`중계동`·`중앙로` 등 정상 지명을 중간층으로 거절하지 않는다. `중`/`중간`/`중층` 및 `중[간]` 뒤가 숫자·알파벳·구분자 등 한글 음절이 아니거나 알려진 층 표현으로 이어지는 모호한 입력은 계속 거절한다. 층만 같은 경우와 기존 저장 신뢰 수준이 미확인인 경우는 same_spot으로 승격하지 않는다. 새 ETL 배치는 `localdata-normalization-v2`, 기존 map version을 사용한다. 과거 v1 배치·기존 NULL 상세 위치는 자동 보정하지 않으며 별도 검증·재처리가 필요하다. API schema·FE 계약·모델·migration은 변경하지 않았다. 설계·실제 Claude 검토·검증은 [#102 설계](docs/designs/feat102-address-place-floor-parser.md), 수정 전 피드백 분석은 [분석 보고서](docs/be-fe-integration-feedback-review.md)를 따른다.

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

현재 migration head는 0011이다. `python -m etl.market_areas`는 공식 OA-15560 ZIP의 hash·첨부 수정일을 받아 기본 읽기 전용 dry-run, --write일 때 일반 로컬 앱 계정에서 원자적으로 적재한다. EPSG:5181 원본의 무효 도형만 linework 보정 후 유효 MULTIPOLYGON 4326·GIST로 저장한다. 원본 면적·hole/multipart·타입/5자리 구 코드를 보존하고 버전/데이터 digest를 검증한다. 같은 원본/규칙 재실행은 불변 버전을 재사용하며 기존 버전 수정/삭제·최신 자동 선택은 하지 않는다. source_file_date는 첨부 수정일이고 boundary_as_of는 미확인 null이다. 후속 통계 분기와의 코드/경계 호환 전에는 지표에 자동 적용하지 않는다. 현재 1,650행·6개 보정, 기존 stores 689,440건이다. 상세는 docs/designs/feat47-market-areas-import.md를 따른다. API 응답/FE 변경은 없다.

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

## AI 집계 입력 준비 기준 (BE #66)

`prepare_risk_interpretation(session,RiskQuery,settings)`는 클라이언트 지표를 받지 않고 서버 Risk를 재계산한다. 위치/상권 후보·UUID/raw meta·URL/link/copy_text 없이 업종/면적/가맹 필터·반경·T/D·지표/분모/출처/상태·고정 방법론만 typed allowlist로 구성한다. 사유/출처도 enum으로 제한하고 기간·비율·metadata 의미·조회조건을 대조한다. 소표본은 기존 Risk의 null/실제분모를 유지하며 불명확한 입력을 정제해 통과시키지 않는다.

입력은 nested frozen/tuple이며 JSON 복사본·정렬 직렬화의 context_hash와 내부 데이터/프롬프트 hash를 구분한다. 원문은 repr/로그/오류에 남기지 않는다. 호출자가 기존 읽기 전용 세션을 제공하며 준비 함수는 공급자/외부 API를 호출하지 않는다. #66 당시 프롬프트는 v2였으며 현재는 아래 #68의 v4·지문 이력을 따른다. verifier는 link_only/unverified 값 생성도 차단한다. 지표 간 숫자 바꿔치기·자유문장 의미 검증 전체나 실제 모델 안전성을 완료로 주장하지 않는다. 상세는 docs/designs/feat66-ai-risk-context.md이며 공개 AI API·캐시는 아래, 이력 추가 문맥은 후속이다.

## 검증 후보 기반 AI 해석 API (BE #68)

`POST /api/risk/interpret`는 `{query: RiskQuery}`만 받는다. 클라이언트 Risk 응답/집계·주소·building_key/floor_unit·중복 JSON키·NaN·URL query는422다. 서버가 Risk를 재계산하고 #66 허용 집계와 서버 후보만 보낸다. 모델은 모든 favorable/unfavorable 후보의 순서와 일반 checklist 1~3개만 고르고, 최종 문장은 서버 후보로 조립한다. method=server_sentences_model_ordering이며 자유문장 AI나 사업 성공/위험 판정으로 설명하지 않는다. 표시1자리 비율끼리 비교하고 같으면 방향 후보가 없다. 동종업체 수에 임의 임계값을 붙이지 않는다.

프롬프트 risk-interpret-v4와 요청별 후보 enum·후보 전체 포함·중복/방향 검증을 적용한다. 공식/참고·실제0/null·소표본·가맹 미확인·공식/조건부 pending·수집일null·인허가 한계를 유지한다. official_values에는 참고 계산도 있으며 verification은 정확도점수가 아니다. generated_at은 현재 응답의 서버 문장 조립 시각, model은 채택 선택을 생성한 모델이다. 새 모델 호출 시각을 뜻하지 않는다.

프로세스별 기본5회/분·50회/일·동시2의 새 INTERPRET 설정을 적용하고 기존 LLM 공급자 한도도 유지한다. 대기/읽기 전용 준비/생성/최대1회 재생성/조립 모두 LLM_TIME_BUDGET(기본20초) 안에 둔다. DB 세션은 공급자 호출 전에 닫고 worker취소는 Event/SQL직전 검사와 기존 문장제한으로 정리한다. 즉시 동기SQL 강제중단·전역quota·운영SLA는 보장하지 않는다. 입력422, DB/서버결함500, 한도/공급자/시간503 AI_UNAVAILABLE, 두 번의 선택검증 실패503 AI_VERIFY_FAILED이며 no-store다. 기본문장 대체는 없으며 서버 캐시는 아래 #74 기준을 따른다.

설계·Claude 실제 검토·수정/실검증은 docs/designs/feat68-risk-interpret-api.md를 따른다. FE 코드·이슈·PR·CLAUDE.md는 직접 수정하지 않고 docs/fe-risk-interpret-api-request.md로 담당자에게 요청한다. FE 반영·원본 합의·전체 BE-32 통합은 후속이다. 활동 추가문맥은 아래 #96, 선택 이력 문맥(최상위가 아닌 `history` 필드)은 #98을 따른다.

## 개인정보 없는 운영 로그 기반 (BE #72)

추가 운영 기록은 core/operations.py의 고정 필드 JSON stderr다. API는 고정 경로/unknown=unmatched·실제 send 상태/null·monotonic 시간·서버 uuid4·response_complete만 기록하며 query/body/header/IP를 읽거나 복사하지 않는다. ID 응답 헤더는 추가하지 않는다. 바깥 취소/예외를 보존하고 스트림200 뒤 실패를 완전 전송으로 표시하지 않는다. uvicorn.access는 기본 앱에서 비활성화하고 --no-access-log 안내도 유지한다.

ETL6개 run_import는 독립 run_id와 순차 coordinator 단계로 기록하며 ContextVar를 finally 복원한다. persist 완료는 commit context 종료 후다. commit 이후 dispose 실패는 persist 완료+run 실패가 될 수 있으므로 rollback 완료를 추정하지 않는다. 허용 비음수int·고정 품질사유·유효 batch/version UUID·mode만 선택하고 원문/파일/임의키/예외 문자열을 기록하지 않는다. quality_flags 중복을 합산해 최종 제외 수로 만들지 않는다. 기존 stdout·반환/exitcode·DB트랜잭션은 유지하고 인허가 argparse 오류만 고정 안전 메시지다.

LLM 이벤트는 실제 client.post 시도1·HTTP200 관측 여부다. 앱 재시도는 별개 시도지만 transport 내부 재시도·파싱/최종 AI검증 성공률로 해석하지 않는다. 키/한도에서 post 전 중단이면0건이다. stderr/직렬화/ID 실패는 작업을 실패시키지 않고 오류를 재출력하지 않는다. 최대4096bytes 단일줄·프로세스내 lock이며 느린sink/프로세스간 원자성은 보장하지 않는다.

설계·Claude 실제 MD 검토·Codex 최종 점검은 docs/designs/feat72-private-operation-logs.md를 따른다. 앱 파일/DB 로그 저장·외부수집기를 추가하지 않아 **원본30일 보관/삭제는 미구현**이며 배포 시 수집기 설정/삭제 검증이 필요하다. 제3자/프록시/커스텀 로그 전체 정화도 완료로 주장하지 않는다. 공개 API/응답·DB모델/migration·의존성·.env/Docker·FE 변경은 없다. 이번 작업에는 FE 보고서/CLAUDE.md 동기화가 필요하지 않다.

## 공식 상담·지원기관 링크와 관할 연락처 (BE #70·#88)

`GET /api/support-links`는 구 생략 시 기존4개·순서를 유지한다. sigungu는 서울25개 정확한 구명, category는 cafe/restaurant이며 생략만 기본값이다. 잘못된/빈/중복/미지원 입력은422 INVALID_PARAM이다. 구를 지정하면 중기부 제2026-576호 PDF25쪽 별표2의8센터 중 관할1개를 앞에 추가해5개다. 마포/은평/서대문은서대문센터, 성북/동대문은중부센터 등 현재 공고 매핑을 사용한다. 누락/중복 설정이면500/no-store다. category는 목록·순서에 영향이 없으며 업종/자격/모집 추천을 하지 않는다.

meta.link_catalog_version=support-links-v2는 생략/지정 모두 적용한다. 생략 prioritization={status:not_applied,reason:general_links_only}, 지정은 {status:applied,reason:district_contact_first,category_applied:false}다. applied는 구 관할 연락처 순서만 뜻한다. 지정일 때만 district_contact_source={url,published_on:2026-10-01,checked_on:2026-11-12,page:25,table:annex_2}다. 연락처 링크는 센터/예약 페이지가 아닌 공고 본문이며 description에 관할/전화/첨부25쪽 안내를 둔다.

항목8필드와 기존4개id/type/region을 유지하며 관할id는semas-seoul-{센터}, type=consulting/region=서울이다. 기존 공식4호스트 외에는 support_sources.MSS_NOTICE_URL 정확 문자열1개만 허용한다. mss호스트 전체/변형 query를 허용하거나 사용자 입력을 URL에 붙이지 않는다. last_checked=KST 수동 확인일(2026-11-12), data_updated_at=반환 링크 확인일 최대값이다. 오늘/배포일/공고일로 바꾸지 않는다. 설정/확인일 변경 시 버전을 올리고 분기1회 후속 공고/관할을 수동 점검한다. 당시 HTTP200은 이후 접속/자격/신청 성공 보장이 아니다.

요청 중 DB/LLM/외부 HTTP 미사용·인증키 불필요, R17/is_demo=false·no-store·안전한422/500을 따른다. DB 모델/migration·의존성·Docker/.env·FE 저장소는 바꾸지 않는다. 최신 설계/Claude 실제검토/검증은 docs/designs/feat88-district-support-contacts.md, 초기4기관은 docs/designs/feat70-support-links-api.md, FE 코드/CLAUDE.md 연결 요청은 docs/fe-support-links-api-request.md다. FE 반영은 담당자 대기다. FE는 배열을4개로 자르거나 첫id를 고정하지 않고 반환 순서·선택meta를 보존해야 한다.

## Risk·AI 메모리 캐시 (BE #74)

앱마다 Risk/AI bytes LRU를 분리한다. CACHE_ENABLED=true, 각 TTL 기본300초/상한7일, CACHE_MAX_ENTRIES 기본256/상한4096, CACHE_MAX_BYTES 각4MiB/상한64MiB다. Python 객체/키 overhead와 worker별 합산은 별도다. 앱 수명 난수 HMAC key에 정확한 float guard+6자리 좌표·정규화한 조건/요청 월·규칙/경계를 넣으며 Risk 값에서 query echo를 제외하고 현재 요청으로 재구성한다. 원문 query/위치/지문을 로그·repr·응답의 cache 메타로 공개하지 않는다.

primary READ ONLY REPEATABLE READ의 snapshot/DB/role/시작시각/GUC 지문으로 같은 배치·updated_at 불변 DML도 다른 namespace로 분리한다. old snapshot은 새 결과를 덮지 않는다. GET warm은 metadata1SQL, AI 준비는 같은 세션에서 Risk warm2SQL+활동 재계산6SQL(#96)이며 history가 있으면 위치 검사·이력 4SQL(#98)을 더한다. 적중에도 DB가 필요하며 SQL 오류500·원천 오류를 과거 결과로 숨기지 않는다. 무관한 쓰기/rollback은 보수적 miss이며 TRUNCATE/rewrite/복구는 요청 drain→cache 종료→변경→재시작 범위다. 일반 동시 ETL은 INSERT/UPSERT다.

AI 값은 현재 허용 후보와 검증한 선택 ID와 모델명뿐이다. snapshot/데이터/context/prompt/provider/model/max tokens/후보/schema/검증규칙을 key에 포함한다. 생성시각·이전 재생성 이력·문장/프롬프트는 저장하지 않는다. generated_at은 현재 응답 문장 조립 시각, regenerated는 현재 요청의 재생성 여부이며 hit=false다. 같은 key 생성만 single-flight로 합치고 key 대기는 semaphore 밖, 준비/공급자 실행만 gate 안이다. 전체 예산·hit의 앱 한도·miss의 공급자 한도·서버문장 실패500·no-store는 유지한다. 키 미설정/실패는 cache로 숨기지 않는다.

TTL은 hit로 늘리지 않고 만료 경계부터 miss다. lifespan의1초 sweep으로 유휴 만료 참조도 정리하며 close→task cancel/await→DB close, 늦은 저장 차단·외부 취소 전파를 지킨다. 정지/이벤트루프 지연/시계 오류의 정확한 물리 삭제·덤프/스왑 secure erase를 보장하지 않는다. 공유 캐시의 시간 차이로 최근 동일 조건 조회가 추론될 수 있어 완전 익명성도 주장하지 않는다. 설계·세 차례 Claude MD 검토와 최종 결정은 docs/designs/feat74-risk-ai-cache.md, FE에는 기존 docs/fe-risk-interpret-api-request.md로 필드 의미를 전달한다. 응답 schema는 그대로이며 FE 저장소/CLAUDE.md 반영은 담당자 대기다.

## BE API 연속 조회 검증 (BE #76)

tests/integration/test_analysis_flow.py는 합성 snapshot→기존 runner→격리 PostGIS→실제 geocode 서비스(mock HTTP)→이력/월범위/주변/시점/활동/Risk/AI(mock 모델)/지원링크를 검증한다. Settings(_env_file=None)·fixture DB 동일성 확인·pytest 제한 override로 실제 개발 DB 쓰기를 차단한다. CI XML에 필수 함수10종 실행 조건을 두고 기존 no-skip/error/xfail 검사를 유지한다. endpoint별200만 확인하거나 parametrize 수로 필수 시나리오를 대신하지 않는다.

같은 좌표/반경/업종/필터/T일 때 nearby.count=snapshot.N=Risk.competitor_count=활동open_count합이다. 이력total은 지원업종 전체/결측을 보존하여 별도다. nearby/snapshot의 좌표누락 수는 T시점영업, 활동/Risk는 T이전개업전체라 다를 수 있다. 전역D·과거월말T·현재기준상태·날짜결측과 실제0을 구분한다. 독립 HTTP 호출 사이의 원자적 snapshot은 보장하지 않는다. 원천 없는 이력0건/as_of=null은 기존 계약이며 전체 준비 완료를 뜻하지 않는다.

실제 개발 검증은 로컬 uvicorn HTTP+실제 Kakao/READ ONLY DB+모의 모델로 수행했고 head0009·앱모델차이0·14테이블 행/geometry hash를 보존했다. schema/앱코드·모델/migration·프롬프트·의존성·실제 .env/Docker·FE 변경은 없다. 재현·결과·한계는 docs/be-api-verification.md, 설계/Claude 실제 검토/최종 결정은 docs/designs/feat76-api-flow-verification.md다. FE 계약/화면·실제 LLM 안전성·공식/조건부 활성화·브랜드57·로그30일삭제·운영/최종제출을 완료로 주장하지 않는다.

## 전체 기능 감사 (BE #78)

docs/be-system-audit.md에 기능별 상태와 실제/격리·모의/정적/기존재사용 근거를 분리했다. 이번 일반1,166/격리146·실원천dry-run7회·실모델2건은 통과했으나 실제FE의 AI422·미확인상권오표시·유효null날짜파손·복합key충돌·빈결측셀을 재현했다. 수정 요청은 docs/fe-system-audit-request.md이며 FE 파일/설정/문서/이슈/PR은 직접 수정하지 않는다. 실제 지도는 JS키 설정 완료 후 검증해야 하며 일반음식점 원천API 응답지연도 미해결이다.

실제DB읽기전용·14테이블/geometry hash·인덱스·head0009·모델차이0·FE추적파일변경0을 확인했다. 원문/키/실제.env/Docker·의존성을 커밋하지 않았고 브라우저실제LLM송신0·실제별도모델2회/재생성0과 warm재사용을 구분한다. 전체정상/FE완료/외부원천최신수집을 주장하지 않는다. 감사문서PR은 Ref#78로 연결하고 CI/CodeQL 후 정상 develop Squash하되 이슈는 후속수정/지도/외부응답 추적용으로 열린상태를 유지한다.

## 출처 연결 배치 조회 인덱스 (BE #82)

현재 head0011의 ix_stores_provenance는 batch_id/source/category/sub_category 네 컬럼 key와 deleted_at IS NULL AND category_review_flag IS NOT TRUE predicate를 사용한다. SQL/공개 계약·3초 제한·고아 검증은 유지한다. ETL head guard도0011이다. 일반1166·격리155·mypy136files, 실제14테이블전체행/geometry hash·기존인덱스/응답보존과 실제동시15건200을 확인했다. 실제dev에는 인덱스 migration만 적용했고 데이터DML은 하지 않았다.

대량 인허가 재적재 직후는 미해결 경계다. 읽기를 중지하고 커밋 후 별도autocommit 세션의 수동 VACUUM(ANALYZE)stores·API확인 후 읽기를 재개한다. ETL과원자적이지 않고 자동VACUUM/자동조회차단은 없다. 생성/삭제 DDL의 잠금 영향을 고려하며 rollback은 읽기 트래픽이 없는 시점에 실행한다. 상세 Claude2회 검토·측정/쓰기비용·최종판단은 docs/designs/feat82-store-provenance-index.md, 절차는 README를 따른다. FE수정·API응답변경은 없다.

#118 이후 `current_provenance`의 고아 검사는 `orphan_exists()`의 recursive CTE skip scan이다. 지원 점포의 서로 다른 (batch_id, source) 키만 이 인덱스로 탐색하고 `batch_id IS NULL` 지원 점포는 별도 EXISTS로 검사하며, 결과 의미는 기존 anti-join과 같다. 이 인덱스가 있어야 키 수에 비례하므로 인덱스를 제거/downgrade하면 코드도 함께 되돌린다. 배치 목록 쿼리·응답·3초 제한은 그대로이고 대량 재적재 직후 첫 확인 비용과 위 운영 절차도 그대로다. 측정·검토·검증은 docs/designs/feat118-source-batch-query-perf.md를 따른다.

## 생활인구 원자료 상태 진단 (BE #84)

`python -m etl.living_pop.quality --population-version UUID --lat FLOAT --lng FLOAT --radius 300|500|1000`은 명시 관측 버전의 내부 진단이다. 기존 로컬 대상/head0011 검사·READ ONLY REPEATABLE READ·SQL3초를 재사용한다. 원천 EPSG5179 중심 속성→4326 geography 타원체 거리≤반경을 선택 기준으로 쓰며 polygon 중심으로 바꾸지 않는다.

72개 원천·시각 칸의 행/격자 수만 센다. 실제0·비공개·결측·행 부재·복수행정동을 구분하고 미좌표는 버전 전역 통계로 분리한다. 인구 합산/완전성/제공률을 선언하지 않는다. 저장 건수/metadata 대조는 full hash/의미 검증이 아니다. 출력에 좌표·격자/행정동 코드·인구 값·접속정보를 넣지 않는다. 공개 API/FE·pending·모델/migration·환경설정은 변경하지 않았다.

일반1196·격리173·ruff/format·mypy138files와 실제9개 반경 진단을 통과했다. 별도 QA로 생활인구4테이블 전체 행/공간 hash·건수와 head0010 보존을 확인했다. 설계·Claude 실제 MD 검토·Codex 최종 결정과 한계는 docs/designs/feat84-population-quality-diagnostic.md를 따른다. 브랜드 #57은 승인 답변 전까지 보류한다.

## 인허가 적재 후 로컬 유지보수 (BE #86)

`python -m etl.localdata.maintenance` 기본은 READ ONLY REPEATABLE READ의 로컬 대상/head0011/public.stores 소유권 점검이다. `--execute`만 별도 AUTOCOMMIT의 VACUUM(ANALYZE, TRUNCATE FALSE)public.stores와 새 읽기 전용 current_provenance 검증을 수행한다. 소유자 정확 일치·public 이름 해석을 요구하고 명령/잠금60초/5초, 후속 SQL 제한은 기존 설정을 쓴다. 전용 engine은 finally dispose를 시도한다.

vacuum_completed는 정상 반환 확인, provenance_checked는 후속 출처 검사 성공이다. 실패·인터럽트·해제 실패도 고정 코드/도달 단계/이미 완료한 상태만 출력한다. stdout JSON1건·성공0/실패1/Ctrl+C130, help는0이다. 명령 실패는 앞선 ETL 커밋·물리 정리를 되돌리지 않는다. 오래된 snapshot·동시 소유권/DDL·부하에 따른 회복을 보장하지 않는다. 읽기/writer/migration 중지와 실제API확인·재개는 운영자 책임이며 자동 제어/자동 일정/자동 ETL은 없다.

설계·Claude 실제 MD 검토·Codex 결정과 실행 검증은 docs/designs/feat86-localdata-maintenance.md, 사용법은 README를 따른다. 실제dev에는 dry-run만 수행하고 VACUUM/DML/DDL은 하지 않는다. 공개 API/FE·SQL/기본 설정·ETL 트랜잭션·모델/migration·.env/Docker를 변경하지 않는다. #57 승인·생활인구 공식 근거 및 #78의 자동 조회 보호 등 후속은 유지한다.

## 생활인구 미확정 정책·품질 로그 (BE #90)

사용자 답변은 운영 규칙이며 공급기관 공식 의미/버전 근거가 아니다. 같은 원천·시각·격자의 서로 다른 행정동 행은 합산하지 않고 원본 파일/행정동별 불변 관측/원문 hash로 보존한다. 행 부재는 no_data, 실제 빈 셀은 missing/null, *는 suppressed/null, 실제0만 observed/0이다. 행/좌표/0을 임의 생성하지 않는다. 현재 SHP와2026-11-07의 공식 대응 확인 전 공간 수치·주야간 비율은 pending이며 수집·정제·적재는 가능하다.

load_input·read_source 성공 뒤, 설정/DB 전에 etl_quality를1회 남긴다. 기존 stdout·metadata/내용 hash·트랜잭션·공개API는 유지한다. 원천일 전체 suppressed_rows/missing_value_rows/observed_zero_rows/unlocated_rows/multi_admin_groups/multi_admin_rows만 기록한다. missing_value_rows는 빈 셀이지 없는 조합 수가 아니며, multi_admin은 source/hour/grid 내 서로 다른 저장 admin을 그대로 비교한다. 미좌표와 그룹 건수는 겹칠 수 있고 인구 합계·제외 수·완전성/제공률을 만들지 않는다.

6개 유효 정수 카운터가 모두 있을 때 completed, 계산/검증 실패는 counts 없이 failed/quality_summary_unavailable이다. source=living_pop 유효 run UUID만 허용하고 scope=source_day_all_sources·spatial_compatibility=unverified·aggregation_status=pending을 고정한다. completed는 적재/공간 검증 성공이 아니며 뒤에 import failed가 올 수 있다. 로그는 실패해도 ETL 결과를 바꾸지 않고 취소는 전파한다. 공식 근거·30일 보관/삭제·#57/#78은 대기다. 설계·실제 Claude 검토·Codex 판단·검증은 docs/designs/feat90-population-quality-logs.md를 따른다.

## 생활인구 원천 검증과 독립 계산 기반 (BE #115)

생활인구 #115는 공식 파일 재확인 보고서·미제출 문의 초안과 독립 산술 기반만 추가했다. `app.analysis.day_night`는 검증된 동일 모집단의24시간 총계를 받는 순수 함수이며 현재 DB/API/AI/품질 진단기에는 연결하지 않는다. 06~17/나머지 구간·Decimal·비중/배수·0분모를 구분한다. None이 있으면 모든 수치가null, 잘못된 입력은고정오류다. 원천상태·완전성·날짜를 이 함수가 검증하지 않는다. 공식근거3건 미확정으로 공개pending과head0011을 유지하고 #115를열어둔다. [원천 검증·문의 초안](docs/population-source-verification.md), [설계·검토](docs/designs/feat115-population-time-basis.md)를 따른다.

후속 직접 실증에서 원자료/DB531922행·격자10125개 전수 지문과 독립 공간 산식/공식 뷰어를 대조했다. 공식 행정동 Sheet 비교가능894집계는 원자료 합과 정확히 일치했고 당일 관측쌍 기준 부재시간34046개·미매칭 비공개24행을 확인했다. 행정동별 소계 처리·현재 코드/도형 정합과 한 격자 안 행정동 간 가산성·공식 역사 버전/행정동 귀속 보장은 구분한다. 개인 비중복·모든 행 부재0은 확정하지 않고 공개pending/immutable provenance를 유지한다. 최신 근거는 [실증 설계·검토](docs/designs/feat115-population-empirical-validation.md)와 원천 보고서7절이다.

## 브랜드 원천 기반·판정 적용의 경계 (BE #57)

2026-11-12 사용자 승인 화면 및 실제 인증 성공으로 이전 브랜드 승인 대기 서술을 대체한다. `python -m etl.brands --year YYYY --output <workspace밖새파일> [--compare-local]` 또는 `--snapshot <기존파일> [--compare-local]`를 제공한다. 순차1000행·재시도/연도대체없음·페이지/전체/연도/브랜드·본부복합키 중복 검증과 첫페이지 재확인, 원문base64/hash·규칙v2·이번 실제수집완료시각을 저장한다. 브랜드번호단독반복행은보존하고모든관련이름을repeated_brand_id로격리한다. 대표자/사업자/법인명은 정규화·대조·로그/LLM에 사용하지 않는다. 기존파일 덮기/원문출력 금지이며 offline은키/HTTP 없이 재검증한다.

기본은DB미접속이며 compare-local만 로컬대상/head0011·READ ONLY RR·SQL60초/잠금5초·지원업종/삭제/검토대기 조건의 전체 점포를 스트리밍 대조한다. 정확 이름 후보도 프랜차이즈 판정이 아니며 과거 가맹계약으로 소급하지 않는다. 현재 stores/모델/migration/공개API/AI/pending/캐시/FE 계약은 유지한다. 후속 판정 활성화 때 브랜드/근거모델·외부가맹필드보존/무효화·API메타/AI검증/프롬프트/캐시·BE측FE요청을 함께 설계한다. #57은 종료하지 않는다.

brands 로그의 save_snapshot은파일저장완료이고 DBpersist와다르다. snapshot저장후대조실패는파일을보존하고exit1·snapshot_saved=true/고정stage를반환한다. source원문은공급자의단일시점일관성까지보장하지않는다. 사용법/예외/상한은 README, 실제 Claude검토/최종판단·검증은 docs/designs/feat57-brand-catalog-foundation.md를 따른다.

## 현재 브랜드 분류 기준 (BE-21 / #57 최종 단계)

현재 head는0011이다. 브랜드 원천 기반 단계(PR92)의 pending·후속 표기는 당시 상태이며 현재는 이 절을 우선한다. `python -m etl.brands.apply --snapshot PATH`는 읽기 전용 계획, `--write`만 새5테이블에 원자 적용한다. stores 원문/is_franchise/brand_id/updated_at·기존14테이블은 변경하지 않는다. 현재 run의 점포 원문 이름·업종이 일치할 때만 catalog_exact_name 추정이며 외부 분류값이 우선한다. 별도 근거 없는 independent는 생성하지 않는다.

history/nearby/snapshot 행에 franchise_basis·franchise_reference_year를 추가하고 snapshot에는 franchise도 추가한다. history/nearby/snapshot/activity/risk의 meta.franchise_classification은 적용 전 pending, 적용 후 estimate·reference_year=2025·coverage=partial이다. 계약·과거 가맹·공식 업종 대응은 검증된 것으로 표시하지 않는다. 프랜차이즈 전용 조회는 franchise=franchise와 include_unknown_franchise=false를 함께 전달한다. 기존 인허가 collected_at=null·공식 미확인 수치 pending을 유지한다.

Risk/AI는 동일 근거/버전과 추정 한계를 사용한다. #57 당시 prompt는 risk-interpret-v5였으며 현재는 #96의 v6이다. 내부 UUID/hash는 LLM에 보내지 않는다. cache는 매핑 규칙과 catalog/run/input 지문을 구분한다. 상세는 [최종 설계 9절](docs/designs/feat57-franchise-classification.md), FE 담당자 요청은 [브랜드 분류 연동 보고서](docs/fe-franchise-classification-api-request.md)를 따른다. FE CLAUDE.md·타입·화면 반영은 담당자 대기이며 직접 변경하지 않는다.

## AI 해석 상권 활동 문맥 (BE #96)

`POST /api/risk/interpret` 요청은 `{query: RiskQuery}` 그대로다. 서버는 같은 READ ONLY 세션에서 Risk 다음 `get_activity`(include 없음, legacy include_unknown 제외)를 재계산하고 최근 구간 개폐업 수·T 시점 세부 업종별 영업 수/평균 경과 개월(버림)·고정 방법론만 `context.activity`에 넣는다. 연도별 추이·cohort_size·배치 UUID·매출/생활인구는 넣지 않는다. 평균 경과 개월은 영업 중 기록의 개업 후 경과이며 수명·생존 기간이 아니다.

as_of/data_updated_at/space·배치 집합/map_version·franchise_classification/brand_mapping·cohort_size가 Risk와 같아야 하고, 활동 영업 수 합=competitor_count, 활동 period=closure_rate_12m.period, closure 분모=영업 수 합+최근 폐업, 분자가 있으면=최근 폐업이어야 한다. 하나라도 다르면 원문 없는 500/no-store다. `get_activity`의 기존 500·SQL 오류·deadline 503 경로는 그대로다. 활동 재계산은 Risk 캐시 적중 여부와 무관하게 같은 스냅샷에서 6SQL을 더한다.

`official_values`에 서버 참고 계산 문장(최근 구간 개폐업1개+선택 세부 업종마다1개)을 Risk 사실 문장 뒤에 추가한다. 문맥에 없는 숫자(12개월 등)는 쓰지 않는다. 사실 항목의 indicator_ids는 `recent_open_close`·`avg_operating_months`를 추가로 허용하며 반복될 수 있다. favorable/unfavorable의 indicator_ids는 기존 IndicatorId만 허용한다. 모델 후보·선택 구조는 그대로이며 활동 기반 유리/불리 후보는 만들지 않는다. prompt는 규칙14를 더한 risk-interpret-v6, data_version_hash에 활동 rule_version, 선택 cache rule은 selection-current-validation-v2다.

설계·Claude Code 재검토·구현 기록은 docs/designs/feat96-ai-activity-context.md, FE 칩 라벨·반복 ID 처리는 docs/fe-risk-interpret-api-request.md로 요청하며 담당자 반영 대기다. 이력 추가문맥은 아래 #98이다. 실제 개발 DB 읽기 전용 검증(6조합 일치·SQL cold15/warm8·빈 license_no 0건·행 hash 보존)은 설계 §13에 기록했다.

## AI 해석 선택 이력 문맥 (BE #98)

`POST /api/risk/interpret` 요청에 선택 필드 `history: {building_key, floor_unit?}`(strict·extra forbid)를 받는다. 생략하면 #96과 같은 동작이며 문맥 `history=null`이다. `InterpretRequest` model_validator에서 `HistoryQuery`(canonical 건물키·floor_unit 정규화, category=query.category)까지 만들어 형식 오류는 DB 접속 전 422/no-store다. 최상위 building_key/floor_unit은 계속 422다.

같은 READ ONLY 세션에서 Risk·활동 뒤 `check_history_location`(SUPPORTED_STORES·같은 건물키·좌표 확보 점포의 최소 geography 거리 ≤ 고정 300m, 좌표 점포가 없으면 생략)과 `get_history`를 실행한다. 위치 불일치는 `prepare_risk_interpretation`이 `AppError(INVALID_PARAM, NO_STORE)`를 직접 올려 422다(ValueError로 바꾸면 500이 되므로 금지). data_updated_at/as_of·배치 집합/map_version·이력 rule_version·분류/brand_mapping·total/denominator·location_match 규칙이 Risk와 맞지 않으면 원문 없는 500이다.

`context.history`는 최신 자료 기준·지원 업종 전체 집계(total·same_category·same_spot/same_building/unverified·같은 자리 영업/폐업/기타·기간 확인 폐업 수와 완료 개월 min/max·floor_unit_provided·same_spot_comparable)뿐이다. 층과 호수가 모두 있어야 comparable이다. 건물키·층호수·상호·관리번호·날짜 원문은 AI 입력·응답·로그·캐시 key에 넣지 않는다. 캐시 key는 집계(payload/context_hash)로 구분되며 값은 Risk 후보 ID뿐이다.

official_values에 `building_history`(호수 미입력이면 총계만)·`same_spot_history` 문장을, missing_data에 `history_no_records`·`history_floor_unit_missing`·`history_detail_incomplete`·`history_latest_data_basis`를 추가한다. 이력 기반 유리/불리 후보·자리 판정은 만들지 않는다. prompt는 규칙15를 더한 risk-interpret-v7, 선택 cache rule은 selection-current-validation-v3다. 설계·Claude Code 재검토·실제 DB 검증은 docs/designs/feat98-ai-history-context.md, FE 요청은 docs/fe-risk-interpret-api-request.md다. 좌표 점포가 없는 건물키(실측 약 9.9%)는 위치 검증 없이 통과하는 한계가 있다.
