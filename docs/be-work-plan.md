# Spot:ON BE 개발 기준 및 작업계획

## Render 무료 검증 배포 기준

2026-11-14 #134는 사용자 승인으로 #130을 공개 반영했다. BE05790fa/dep-dbs5t55g1s2s73e8vorg의 API 검증 후 FE PR55/4bf012f를 Vercel에 배포했다. 공개 AI4문단·검증 통과·ⓘ 접근성·1440/390/360px·조건 변경/오류와 실제 지도/점포 조회를 확인했다. 기존17개 환경값·키·Free·자동 배포off·DB를 유지했다. [현재 Render 안내](render-free-validation.md)의 #134가 최신 공개 배포/검증 범위다.

현재 Free 웹 spoton-be-free·DB spoton-db-free만 사용한다. SQL10초·풀1/overflow0/대기15초·워커1·reader/연결 예산8, 별도 ready 연결 포함 교체 상한4개다. ready의 HTTP2.5초/SQL750ms·캐시는 유지한다. 앱 모델/head0011·기준50인덱스와 별도 운영 인덱스2개(ops_free_risk_cover/ops_free_risk_name_v1)를 구분하며 Free DB를 autogenerate 대상으로 쓰지 않는다.

구성·환경변수·권한·데이터 검증·운영 SQL·복원과2026-12-13 만료는 [현재 Render 안내](render-free-validation.md), FE URL·CORS·절전 후 대기는 [FE 연결 안내](fe-render-validation-api-request.md)를 따른다. Render 전용 MD는 이 두 개만 유지한다. 로컬 .env·기본3초·개발DB·FE 파일은 변경하지 않는다. 시작 시 migration/ETL과 자동 배포는 실행하지 않으며 검증한 commit을 수동 배포한다.

2026-11-14 #127에서 Render의 LLM 설정3개 누락으로 발생한 AI_UNAVAILABLE을 확인하고, 실제 생성이 가능한 기존 Gemini 키를 비밀 LLM_API_KEY와 google/gemini-3.5-flash-lite 설정으로 연결했다. 당시 같은7d4846c의배포dep-dbs51tk9v7es73bn89tg에서 카페·한식·카페 재호출3건이200·검증 통과·불일치0·재생성false다. ready200·세 origin POST preflight200·잘못된 업종422를 확인했고 기존14개 환경값·Free·자동 배포off를 보존했다. BE 실모델 연결 완료와 FE 브라우저의 해석 표시 확인을 구분하며, 기본 해석 한도5회/분·50회/일·동시2와기존503 처리를 유지한다. 키 값은 FE·문서·로그·저장소에 넣지 않는다. 현재 구성은 위 Render 안내를 따른다.

이 문서 하나에서 BE의 범위·개발 순서·데이터 규칙·API 보완·작업 방식을 관리한다. 공통 기준 변경은 해당 절을 수정한다. 기능별 설계·Claude 검토·커밋 계획은 `docs/designs/`에 별도로 기록하되 공통 규칙을 복제하지 않는다.

## 1. 적용 기준과 현재 상태

- 2026-11-14 사용자 AI 개편 요청은 FE·BE 동시 구현과 모바일 대응을 명시적으로 허용한다. 이번 범위는 [#130 설계와 집계 검증](designs/feat130-ai-narrative.md)을 따른다. AI는 기존 재계산·검증을 유지하고 실제 자료로 만든 문단 후보를 선택해 body/paragraphs/used_indicator_ids/evidence를 반환한다. 기존 배열은 내부 근거/호환용이며 화면·진단서에는 연결 문단만 표시한다. 부족한 자료는 정보 팝오버로 옮기고 서울 차이는 서버 Decimal %p, 연도별 YTD와 최신/과거 상태를 구분한다. 공식 지표·매출·생활인구 pending은 유지한다. 운영 배포 완료는 별도 실제 검증을 따른다.

- 사용자 결정과 기존 BE 기준을 우선한다. PDF 등 외부 참고 자료와 충돌하면 현재 결정을 유지한다.
- 2026-11-12 디자인 대조 사용자 결정: 분식은 제외 업종 유지, 양도는 이번 구현 범위에서 제외하고 후순위로 둔다. 같은 상세 위치 정보가 일치하는 `same_spot`만 해당 호수의 확정 이력으로 표시하고, 창업위험도는 공식 링크로 제공하며 미확보 점수·등급을 사용하지 않는다. 프랜차이즈는 공정위 브랜드 목록과 점포 상호 비교 방향으로 진행한다. 데이터별 현재 상태·추정 판정의 한계·후속 구현 순서는 [디자인 데이터 기능 연결 분석](design-data-integration-analysis.md)을 따른다. 보고서의 추가 권장안은 API·FE 구현 완료를 뜻하지 않는다.
- FE·BE는 별도 저장소로 유지하며 작업 대상은 `SpotON-BE`다. 모노레포로 합치지 않는다.
- 2026-11-12 사용자 지시: BE 작업 중 FE 코드·설정·문서를 직접 수정하거나 FE 이슈·PR을 만들지 않는다. 호환 변경은 [FE 수정 요청 보고서](fe-store-history-api-request.md)로 정리하고 사용자가 담당자에게 전달한다. FE·BE CLAUDE.md 동기화도 담당자 반영 전에는 완료로 표시하지 않는다.
- `develop`은 GitHub 기본·개발 통합 브랜치이고 `main`은 최종 반영용이다. **개발 전 이슈를 만들고 해당 작업 브랜치에서 구현한 뒤 PR로 `develop`에 병합한다.**
- 이슈 제목은 어떤 기능인지 알 수 있는 한국어로 짓고, 브랜치는 `feat#{작업 순번}-{영문-kebab-case}` 형식을 사용한다. 첫 작업은 `feat#1-initialize-fastapi`다. GitHub 실제 이슈 번호는 PR과 번호를 공유하므로 작업 순번과 다를 수 있으며 PR에서 실제 이슈를 연결한다. 셸에서는 `#`가 포함된 브랜치명을 따옴표로 감싼다.
- 기본 절차는 이슈 → 작업 브랜치 → Codex 설계 MD → Claude Code 검토·MD 직접 수정 → Codex 구현·기능별 커밋 → 로컬 테스트·실패 수정·재검증 → 푸시·develop 대상 PR → CI 확인 → Squash 병합이다. 2026-11-12 사용자가 이후 BE PR의 자동 승인·머지를 요청했다. CI·저장소 조건을 만족하면 develop에 자동 병합하며, 본인 승인 제한·보호 규칙을 우회하지 않는다. main 반영·수동 브랜치 삭제·강제 푸시는 별도 요청 없이 하지 않는다.
- 2026-11-12 추가 지시: 데이터 처리 등 유사한 선택은 Claude Code와 실제 설계 검토 후 가장 적절한 안을 선택하고 근거를 남긴다. 통상 선택마다 사용자에게 재확인하지 않는다. 필수 자료·키·권한이 없어 진행할 수 없는 경우의 요청/중단 원칙은 유지한다. BE-19 미매칭 격자 1개/24개 비식별 행은 사용자가 좌표 미확인 보존·공간 집계 제외로 확정했다.
- 2026-11-12 생활인구 추가 결정: 복수 행정동 원천 행 비합산·원본/행 차원 보존, 행 부재는 no_data·0/임의 행 비생성, * 비공개와 빈 셀/실제0 구분, 좌표 비보완, 미확정 건 별도 ETL 로그를 따른다. 사용자 정책은 공급기관 공식 답변이 아니다. SHP와2026-11-07 관측의 공식 대응 확인 전 공간 수치 API는 보류하며 수집·정제·원자료 적재는 가능하다. 구현/검증은37절을 따른다.
- 2026-11-12 후속 사용자 승인: 주간06~18시미만/야간나머지를SpotON구분, 인구는요청월T이하최근검증1일, 매출은상권별분기, 공식통계는검증된2025역사자료우선, 브랜드는추정/미확인/별도근거있는비프랜차이즈를채택한다. 공식근거없는공간/기간/업종·분기수치는해당기능만보류하고전체개발은중단하지않는다. 다운로드일은인허가전체수집완료시각증빙이아니므로collected_at=null유지다. 월1회갱신·배포(FE준비대기)는운영방향이며자동갱신/최신화·비용한도검토는현재선행조건에서제외한다. 공정위브랜드API승인/실제인증완료후#57을재개했으며원천수집은38절, 추정·필터 적용은39절을따른다.
- API 명세서 v1.2가 FE↔BE 계약이다. 원본은 저장소에 커밋하지 않는다. 이슈 #36에서 로컬의 API·데이터 활용 v1.2 및 분석 정의 원본을 확보·대조했다. 현행 사용자 결정과 다른 부분은 별도 기록하며 보완안을 외부 문서 수정 완료로 간주하지 않는다. 확인 대기는 9절에서 관리한다.
- BE-00~20 기반·조회·원천 적재, #58/PR59 시스템 점검·#60/PR61 기본 활동·#62/PR63 상권 판정·#64/PR65 Risk 참고지표·#66/PR67 AI 허용 집계·#70/PR71 상담 공통 링크·#68/PR69 핵심 AI API·#72/PR73 운영 로그·#74/PR75 캐시·#76/PR77 BE연속 검증이 develop에 반영됐다. #78 감사에서 기존 BE 일반/격리·실데이터/실모델 검사는 통과했지만 FE결함5종(지도 복합 식별 포함)·BE 출처조회 SQL시간초과·일반음식점 외부API지연을 추적한다. 도메인 등록 후 지도 기본 연결은 통과했다. 전체 정상 판정은 보류하며 상세는32절을 따른다. BE-21/#57 브랜드명 추정·필터는39절에서완료하며공식/조건부 수치·지원맞춤정렬·로그30일삭제도 후속이며 AI 활동 추가문맥은40절(#96), AI 이력 추가문맥은41절(#98)이다. #102 지명 상세 위치 파서 수정·검증은42절이며 기존 DB 보정은 별도다. 필수 자료·키·권한이 없으면 해당 기능을 중단하고 요청한다.
- 이슈 #34 작업 브랜치에서는 실제 응답 코드·ISO 날짜/시각과 적재 실행기를 보완했다. 사용자 제공 검증 CSV(2026-11-09 검증, 원천 기준일 미확인)로 개발 DB에 일반음식점 541,169건·휴게음식점 148,271건, 합계 689,440건을 적재하고 재적재·20건 원자료 자동 대조를 통과했다. 현재 API의 최신 전체 수집 완료나 BE-12 구현 완료를 뜻하지 않는다. develop 반영은 이슈 #34의 PR 상태를 따른다.

핵심 흐름은 `공공데이터 → ETL → DB → BE 계산 → API → FE 표시 → AI 해석`이다. 원천 통계는 적재 후 조회하며 주소 검색은 명세에 따라 실시간 외부 조회를 허용한다. AI 해석은 명시적 요청 시 서버의 허용 집계·후보만 모델에 전송한다. 앞 단계를 임시 수치로 우회하지 않는다.

이슈 #34/PR #35 적재, #36/PR #37 이력, #38/PR #39·#40 설계, #41/PR #42 주변, #43/PR #44 월 범위, #45/PR #46 snapshot, #47/PR #48 경계, #49/PR #50 공식 점포 통계, #51/PR #52 추정매출, #53/PR #54 생활인구, #55/PR #56 공식 상권변화 유형, #58/PR #59 시스템 점검·#60/PR #61 기본 활동·#62/PR #63 상권 판정·[#64/PR #65 Risk 참고지표](designs/feat64-risk-reference-api.md)·[#66/PR #67 AI 집계 입력](designs/feat66-ai-risk-context.md)·[#70/PR71 상담 링크](designs/feat70-support-links-api.md)·[#68/PR69 AI API](designs/feat68-risk-interpret-api.md)·[#72/PR73 운영 로그](designs/feat72-private-operation-logs.md)·[#74/PR75 캐시](designs/feat74-risk-ai-cache.md)·[#76/PR77 BE연속검증](designs/feat76-api-flow-verification.md)은 develop에 병합됐다. 현재 [#78 전체 기능 감사](designs/feat78-system-functional-audit.md)를 `feat#78-system-functional-audit`에서 진행하며 FE후속/지도/외부응답 미완료를 추적한다. FE 저장소는 수정하지 않는다.

## 2. 서비스 범위

서울 주소와 업종을 기준으로 주소 검색, 점포 이력, 주변 동종업체, 과거 시점 조회, 개·폐업 분석, 공식·참고 지표, AI 해석, 상담·지원 링크를 제공한다.

| 구분 | 범위 |
|---|---|
| 지역 | 서울특별시 |
| 업종 | 카페 `cafe`, 음식점 `restaurant` |
| 음식점 세부 업종 | 한식 `korean`, 중식 `chinese`, 일식 `japanese`, 양식 `western` |
| 카페 | FE 세부 업종 선택 없음. DB 내부 분류는 `category = cafe`, `sub_category = cafe` |
| 제외 업종 | 키즈카페·라이브카페·분식·치킨·주점·기타 음식점·제과점 |
| 기본 지표 | 동종업체 수, 최근 12개월 개업·폐업 수, 연도별 추이, 평균 영업 기간, 공식·참고 폐업률, 1년·3년 생존율 |
| 조건부 지표 | 추정매출·생활인구·상권변화지표·주야간 인구비 |
| 제외 지표 | LQ, 자체 종합 위험점수·위험등급·성공률·추천/비추천 판정 |

분식·기타 음식점 제외는 의도된 범위 축소다. 동종업체 수는 지원 업종에 한정된 집계라고 안내하고 확인하지 않은 원자료 비율·건수를 사용하지 않는다.

원본 저장 분류는 인허가 업태 기준이다. #122에서689,440행의 원본 업태와 저장 매핑 불일치는0건이었지만 원본 한식에 치킨·주점 상호가 남았다. 2026-11-14 사용자가 B안을 선택해 #128에서 원본을 바꾸지 않는 `store-name-keywords-v1` 분석 제외 정책을 구현했다. 음식점4종에 치킨·통닭·호프·주점·포차·맥주·분식·김밥·떡볶·피자·카페·커피·cafe·coffee·베이커리·제과·빵집·bakery 부분 일치를 적용한다. 영문 ASCII 대소문자를 무시하며 cafe 업종과 null/빈 이름은 유지한다. "카페 M" 같은 실제 음식점의 오탐, 공백/분해한글/전각/키워드 없는 상호의 미탐을 수용한 이름 추정이며 실제 업종 확정·제보18곳 전수 해결이 아니다. 모든 목록/집계·메타·캐시는 같은 버전을 쓰고 원천 배치/D/고아 검사·브랜드 ETL 입력은 기존 자격을 보존한다. [설계·검토·검증](designs/feat128-name-keyword-exclusion.md)을 따른다. PR131에서 일반1,718개·PostGIS270개·CodeQL을 통과해 develop c4de3ed로 병합했고 dep-dbs5fus9v7es73boe6dg에 수동 배포했다(21:46:27 KST). 운영 한식454→434·13후보 전부 제외, 업무 동시30/ready24건200·AI 이력 포함200/검증57개·HTTP500로그0을 확인했다. 원본689,440행 전체 composite/EWKB hash·기존 인덱스·head0011·LLM 포함17개 환경값은 유지했다.

조건부 지표는 출처·이용 조건·공간 단위·갱신 주기 검증 후 활성화한다. 확보 전에는 필수 수치 제공 일정에서 제외하고 `value = null`, `status = pending`과 사유를 제공하도록 계약을 보완한다. 확보된 자료의 조건별 결측은 `no_data`로 구분한다.

## 3. 개발 순서와 작업 목록

2026-11-14 #115는 생활인구 공식 정의서·두 매뉴얼·SHP 재확인과 독립 주야간 산술 기반을 추가한다. [원천 검증 보고서·미제출 문의 초안](population-source-verification.md), [설계·Claude 검토](designs/feat115-population-time-basis.md)를 따른다. 합산·행 부재·관측일별 격자 적용의 공식 근거는 미확정이다. 내부 `app.analysis.day_night`는 동일 모집단의 검증된24시간 총계를 향후 입력받는 계산 기반이며 DB/API/AI에 미연결이다. 공개 인구 pending·모델/head0011과 현재 Render 배포를 유지하고 #115는 공식 근거/실제 연결 후속 추적을 위해 열어 둔다.

같은 날 사용자 요청의 후속 직접 검증에서 원자료/DB531922행과격자10125개를 전수 대조하고, 공식 행정동 Sheet 비교가능894집계의 정확한 합계 일치·당일 관측쌍 기준 부재시간34046개·미매칭 비공개24행을 확인했다. [실증 설계·Claude 검토](designs/feat115-population-empirical-validation.md)와 원천 보고서7절의 항목별 판단이 최신 근거다. 원자료의 행정동별 소계·현재 코드/도형 정합과 한 격자 안 행정동 간 가산성/개인 비중복/행 부재 의미/공식 역사 버전 보장은 구분하며 API/DB/Render는 변경하지 않는다.

| PHASE | 목표 | 작업 |
|---|---|---|
| 0 | 프로젝트 실행·검사 기반 | BE-00~03 |
| 1 | 공통 API·DB 기반 | BE-04~06 |
| 2 | stores·인허가 ETL 검증 | BE-07~10 |
| 3 | 주소·점포 핵심 API | BE-11~15 |
| 4 | 상권·분석 데이터 적재 | BE-16~21, 조건부 데이터는 확보 후 |
| 5 | 상권 활동·Risk 계산 | BE-22~27 |
| 6 | 검증된 집계 결과의 AI 해석 | BE-28~32 |
| 7 | 상담·캐시·로그·통합 검증·제출 | BE-33~35 및 11절 |

작업 식별자는 `BE-00`~`BE-35`로 통일한다. 중복된 `BE-Ixx` 계획 번호는 더 이상 사용하지 않는다. GitHub 실제 Issue `#번호`는 별도로 연결한다.

| 작업 | 구현 대상·완료 기준 |
|---|---|
| BE-00 | 프로젝트 구조, `uvicorn app.main:app --reload` 실행 |
| BE-01 | pyproject 의존성·버전 고정·CI, ruff·mypy·pytest 통과 |
| BE-02 | 환경 설정 로딩, 비밀값 없는 `.env.example` |
| BE-03 | 공통 응답 형식의 `/api/health` |
| BE-04 | `ApiResponse<T>`, `ApiMeta`, `ApiError`, `DataVersion` |
| BE-05 | 공통 예외 처리와 오류 코드 매핑 |
| BE-06 | PostgreSQL 연결·PostGIS 활성화·Alembic 검증 |
| BE-07 | stores 모델과 공간·조회 인덱스 |
| BE-08 | 인허가 수집·정제·중복 제거·upsert·적재 검증 |
| BE-09 | 지번 기준 building_key 정규화 |
| BE-10 | 도로명·지번 상세 주소의 층·호수 추출 |
| BE-11 | F-01 주소 검색·서울 판정·후보 처리 |
| BE-12 | F-02 점포 이력·위치 일치·영업 기간, 원자료 표본 20건 대조 |
| BE-13 | F-03/F-04 주변 점포·반경·필터 |
| BE-14 | F-05 검증된 데이터 조회 가능 월 범위 |
| BE-15 | F-05 과거 시점 영업 점포·현재 상태 분해 |
| BE-16 | market_areas Polygon 적재·좌표계 변환·유효성 보정·GIST |
| BE-17 | market_stores 공식 점포·개폐업·폐업률 적재 |
| BE-18 | market_sales 상권별 추정매출, 확보 후 활성화 |
| BE-19 | living_pop 250m 격자·시간별 생활인구, 확보 후 활성화 |
| BE-20 | 서울시 원천 상권변화 유형, 확보 후 공식 지표 제공 |
| BE-21 | brands 정규화·프랜차이즈 추정 매핑 |
| BE-22 | F-06 활동 분석·연도별 추이·조건부 데이터 결합. #60은 기본 집계·선택 항목 pending까지이며 조건부 수치는 후속 |
| BE-23 | F-07 Risk·상권 판정·공식/참고 구분. #62 공간 기반·#64 참고지표 API, 공식 지표 연결은 후속 |
| BE-24 | 공식 폐업률의 상권·업종·분기 매칭 |
| BE-25 | 참고 폐업률과 분모 계산. #64 기간 분모10 기준·BE 계약안/FE 합의 대기 |
| BE-26 | 1년·3년 생존율·최소 표본 판단 보류. #64 고정 주년/진입 코호트 보완안·FE 합의 대기 |
| BE-27 | 주야간 인구비, 데이터 확보 후 활성화 |
| BE-28 | AI에 필요한 집계·출처·상태만 추출. #66 Risk 재계산/허용 입력·모의 공급자 검증, 공개 AI API는 후속 |
| BE-29 | 공급자 분리 LLM client·시간 제한·한도 대응 |
| BE-30 | `app/ai/prompts/` 및 `PROMPT_VERSION` 관리 |
| BE-31 | AI JSON·숫자·출처·의미·개인정보 검증 |
| BE-32 | F-08 서버 재계산 기반 AI 해석 API |
| BE-33 | F-10 상담·지원 링크 API. #70 공통4기관, #88 구 지정 시 관할 연락처 우선/25구 대조. 업종별 추천·자격/모집 판정은 하지 않음 |
| BE-34 | #74/PR75 Risk·AI bounded 메모리 캐시·MVCC/데이터/모델/프롬프트 버전 무효화, develop 반영 |
| BE-35 | 개인정보 없는 API·ETL 운영 로그. #72 JSON stderr 기록 기반·실패/취소 보존, 외부수집기/30일 보관·삭제는 후속 |

### 실제 개발 DB 연동의 지연과 큐 중단

실제 개발용 DB 연동은 초기에는 지연했으며, 2026-11-11 Docker 로컬 개발 환경에서 연결을 완료했다. BE-06의 CI 임시 DB 검증과 실제 개발 환경의 DB 연결 완료는 별개다. 원천 전체 적재와 데이터 기반 API 검증은 아직 미완료다.

2026-11-11 사용자 요청으로 Docker Desktop·WSL 설치와 Windows 재부팅 후 `spoton_dev` DB를 실행했다. 로컬 `.env`를 사용하는 백엔드의 `spoton_app` 접속, PostGIS 공간 함수, migration `0002`, stores·공간/조회 인덱스 5개와 ORM 조회를 검증했다. 앱 계정은 superuser·DB/role 생성 권한이 없으며 원천 적재 전 점포 수는 0건이다. 상세 상태와 실행 환경 주의점은 [로컬 PostGIS 구성 기록](designs/local-postgis-setup.md)을 따른다.

| 작업 유형 | 실제 개발 DB 미연동 상태의 처리 |
|---|---|
| stores 모델·마이그레이션 설계와 CI PostGIS 검증 | 진행 가능 |
| 샘플 기반 ETL 수집·정제·매핑 로직과 단위 검사 | 진행 가능 |
| 실제 개발 DB에 원천 데이터 적재·조회·지속 저장 | 실제 DB 연동 선행 필요 |
| 개발 DB를 사용하는 API의 전체 연동 검증 | 실제 DB 연동 선행 필요 |

실행 중 실제 개발 DB가 필요해 더 진행할 수 없으면 다음 절차를 따른다.

1. 막힌 작업의 진행 내용을 보존하고 원인·필요한 접속/권한/환경 조건을 보고한다. 접속 비밀값은 출력하지 않는다.
2. 실행 큐에서 해당 작업 바로 앞에 **`실제 개발 DB 연동`** 선행 작업을 추가한다. 기존 `BE-00`~`BE-35` 번호는 바꾸지 않으며, 이미 같은 작업/이슈가 있으면 재사용한다.
3. **해당 선행 작업 이후의 모든 실행 큐를 중단한다.** DB 의존성이 없는 다른 후속 작업도 우회 실행하지 않고 다음 이슈·브랜치·구현·PR을 자동 진행하지 않는다.
4. CI 통과·mock·SQLite·테스트용 DB를 실제 개발 DB 연동 완료로 대체하지 않는다. 실패·미검증 작업의 완료 표시와 PR 생성도 하지 않는다.
5. 실제 개발 DB의 PostgreSQL/PostGIS 준비, 로컬 비밀 설정의 DATABASE_URL, 필요한 migration 권한·실행, 실제 연결·기본 쿼리 성공을 확인하고 사용자에게 결과를 보고한 뒤 중단 큐를 재개한다.

이 규칙은 지금 진행 가능한 CI·샘플 작업을 즉시 중단한다는 뜻이 아니다. 실제 개발 DB가 필요한 경계에 도달했을 때 발동하며, 발동 후에는 선행 작업 해결 전까지 뒤의 큐 전체를 유지한다.

첫 구현은 BE-00~02 → health에 필요한 최소 공통 응답과 BE-03 → BE-04~06 → BE-07~10 순서다. stores 검증 후 BE-11~15, 분석 데이터·지표 검증 후 AI로 진행한다. 한 작업 단위를 작게 유지하고 기능과 테스트를 함께 작성한다.

## 4. 기술 구조와 실행

Python 3.11, FastAPI·Uvicorn, PostgreSQL·PostGIS, SQLAlchemy·GeoAlchemy2·Alembic을 사용한다. 검사 도구는 ruff·mypy·pytest이며 black을 추가하지 않는다. 특정 유료 서비스에 종속시키지 않고 AI는 무료 이용 가능한 범위만 사용한다.

```text
SpotON-BE/
├─ app/
│  ├─ main.py       # 앱·라우터·CORS
│  ├─ core/         # 설정·공통 예외
│  ├─ db/           # 연결·세션
│  ├─ models/       # DB 모델
│  ├─ schemas/      # 공통·요청·응답 타입
│  ├─ routers/      # 요청 검증·응답
│  ├─ services/     # 비즈니스 로직·외부 호출
│  ├─ analysis/     # 지표 계산
│  └─ ai/           # client·prompts·verifier
├─ etl/
├─ tests/
├─ data/sample/
├─ docs/be-work-plan.md
├─ pyproject.toml
├─ .env.example
└─ README.md
```

의존성과 ruff·mypy 설정은 `pyproject.toml`에서 관리한다. 실행·개발 의존성을 구분하고 직접 버전을 고정하며 간접 의존성은 `uv.lock`에 잠근다. 로컬·CI는 `uv sync --locked --extra dev`로 동일한 선언을 설치한다. PostGIS 서버 확장은 Python 패키지와 별도로 검증한다.

아래 명령은 저장소 루트에서 실행한다. 최초 설치는 `.env` 없이 가능하며 설정이 필요할 때만 예시를 복사한다. 기존 `.env`를 덮어쓰지 않는다.

```powershell
py -3.11 -m pip install uv==0.13.7
uv sync --locked --extra dev
uv run --locked --extra dev uvicorn app.main:app --reload --no-access-log

uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app migrations
uv run --locked --extra dev pytest
```

환경변수 목록과 기본값은 루트 `.env.example`에서 관리한다. DB, 공공데이터·카카오·주소 API 키, LLM 공급자·모델·키, 실행 환경·CORS 설정을 포함한다. 새 변수를 추가하면 같은 변경에서 예시를 갱신하며 실제 `.env`는 읽어 출력하거나 커밋하지 않는다.

## 5. 데이터 모델과 ETL

### stores

| 구분 | 컬럼 |
|---|---|
| 식별·원천 | `license_no`, `source`, `gu_code`, `name` |
| 위치 | `address_road`, `address_jibun`, `building_key`, `floor_unit`, `location_level` |
| 영업 | `open_date`, `close_date`, `status`, `status_code`, `bzstat_nm` |
| 업종·규모 | `category`, `sub_category`, `seoul_induty_cd`, `area_m2` |
| 좌표 | `lat`, `lng`, `geom`, `raw_x`, `raw_y`, `raw_crs`, `coord_source`, `coord_flag` |
| 정제·구분 | `date_flag`, `is_temporary`, `category_review_flag` |
| 브랜드 | `is_franchise`, `brand_id` |
| 이력 | `deleted_at`, `batch_id`, `updated_at` |

인덱스는 `geom GIST`, `building_key`, `(category, status)`, `open_date`, `close_date`다. 플래그는 정상·오류·미확인을 구분하며 날짜별 오류 사유를 남긴다. 미확인 `is_temporary`를 false로 바꾸지 않는다. 실제 타입·enum·중복 키는 원자료 대조 후 확정한다.

### 인허가 ETL 흐름

원천은 일반음식점·휴게음식점이다. 다음 순서로 처리한다.

1. Open API 수집 → 서울 25개 구 필터 → 관리번호 중복 제거
2. 허용 필드의 원본 보존 → 상태 분류 → 주소 정제
3. 원천 CRS 확인 → 좌표 변환·이상치 판정 → 행안부 API 보완 시도·재검증
4. 날짜 이상치·한시적 사업장 플래그 → 업종 매핑·업태 오기 검토
5. building_key·floor_unit 생성 → DB upsert → 배치별 건수·표본 검증

- 원본 좌표 표현과 확인된 CRS를 보존하고 보완 좌표로 덮어쓰지 않는다. CRS 불명·보완 실패를 유효 좌표처럼 취급하지 않는다. 공간 집계에서 제외하고 건수를 남긴다.
- 보완 좌표는 주소 일치를 확인한 결과만 채택하고 출처·변환·배치 이력을 보존한다. 외부 API 필드·좌표계·이용 조건은 연계 전에 확인한다.
- 1960년 이전 날짜, 파싱 실패, 미래 개업일, 개폐업일 역전은 검토 대상으로 둔다. 레코드와 원본을 보존하되 신뢰할 수 없는 날짜가 필요한 조회 범위·시점·기간 지표에서 제외한다.
- 한시적 사업장은 구분 보관하고 기본 장기 입지 분석 집계에서 제외한다.
- 명확한 원천 업태만 카페·음식점 4종으로 매핑한다. 기타 업태의 상호 키워드 후보와 업태 오기는 검토 대기 처리하고 기본 경쟁점 집계에 자동 포함하지 않는다. 확정 시 매핑 버전·근거를 남긴다. 미지원 업태는 `excluded`로 처리한다.
- 원본 보존에도 허용 필드 목록을 적용한다. 대표자명·연락처·상담 원문은 적재하지 않으며 원천 응답 전체를 무차별 저장하지 않는다.

### 건물·상세 위치 정규화

`building_key`는 지번의 `{자치구}-{법정동}-{본번}-{부번}`이다. 예: `마포구-서교동-123-4`, 부번 없음 `마포구-서교동-123-0`, 산 지번 `마포구-상암동-산12-3`.

법정동 뒤 본번·부번·산 여부만 읽고 건물명·층·호수를 분리한다. `외 n필지`는 명시된 대표 지번을 사용하고 부가 정보는 원본에 보존한다. 대표 지번·건물이 불명확하면 임의 결합하지 않는다. 카카오의 구조화된 법정동·본번·부번에도 같은 규칙을 적용해 도로명·지번 검색의 키가 같아야 한다.

`floor_unit`은 도로명·지번 상세 주소 모두에서 `1층`, `2층 201호`, `B1`, `162C호` 등을 추출한다. 확인 불가면 null, `location_level = unverified`다. 상세 주소 충돌이나 호수만으로 같은 자리를 확정할 수 없는 경우 `same_spot`으로 판정하지 않는다.

### 분석 데이터

| 데이터 | 주요 필드·처리 |
|---|---|
| market_areas | `market_code`, `market_name`, `market_type`, `gu_code`, `area_m2`, `geom`; 좌표계 변환·Polygon 보정·GIST |
| market_stores | `market_code`, `quarter`, `induty_cd`, `total_stores`, `open_stores`, `closed_stores`, `closure_rate` |
| market_sales | `version_id`, `market_code`, `quarter`, `induty_cd`, `est_sales`, `source_sales_count`; KRW 원천값·집계 기간 미확인, 환산·반경 매출·합산 금지 |
| living_population_observations (living_pop) | `version_id`, `source`, `hour`, `admin_code`, `grid_id`, `located_grid_id`, `population`, 상태; 원천·행정동 차원 보존, 250m geometry는 living_grids 참조 |
| market_changes | `version_id`, `market_code`, `quarter`, `change_code`, `change_name`, 평균 영업 개월4개; 업종 없는 서울시 원천 분류, 임의 점수화 금지 |
| brands | `brand_id`, `brand_name`, `normalized_name`; 공정위 원천과 점포 상호 정규화 비교 |

브랜드 판정은 `franchise`, `independent`, `unknown`을 구분하고 화면에는 프랜차이즈(추정)로 표시한다. 원천 브랜드 정보만으로 확정 가맹 여부를 단정하지 않는다.

이슈 #47의 경계 기반은 market_area_versions의 원본 hash/규칙별 불변 버전과 `(version_id, market_code)` 경계를 사용한다. EPSG:5181·UTF-8 원본의 면적/속성·보정 여부를 보존하고 유효 MULTIPOLYGON 4326으로 저장한다. 원본의 5자리 구 코드와 점포 관청 코드(7자리)를 혼동하지 않는다. source_file_date(첨부 수정일)·loaded_at과 boundary_as_of(실제 적용일, 현재 null)를 구분하며 새 적재를 최신/active로 자동 선택하지 않는다. 후속 분기별 공식 통계와 상권 코드/경계 호환을 확인하기 전에는 이 버전으로 지표를 자동 계산하지 않는다.

이슈 #49의 공식 점포 통계는 별도 불변 버전·`(version_id,market_code,quarter,induty_cd)`로 구분한다. 전체=SIMILR_INDUTY_STOR_CO, 일반=STOR_CO, 가맹=FRC_STOR_CO다. 개폐업 수·원천 비율을 보존하고 100 초과 값을 자르거나 null/없는 행을 0으로 바꾸지 않는다. 지원 업종만 적재하며 커피-음료 통계와 인허가 cafe의 모집단 동일성은 미확인이다. 지정 경계와 코드·유형·명칭을 대조하지만 boundary_compatibility=unverified로 유지한다. source_year/quarter·첨부 수정일·내부 파일 시각·loaded_at은 서로 다른 기준이며 최신 통계/유효 경계를 자동 선택하지 않는다. 공식 폐업률 매칭·지표 API는 BE-23/24에서 별도 검증한다.

## 6. API 공통 계약과 핵심 조회

라우터는 검증·응답만 담당하고 비즈니스 로직과 계산은 services·analysis로 분리한다. 모든 경로는 `/api/...`, 공통 응답은 `{data, meta, error}`다. Health도 다음 형식을 따른다.

```json
{
  "data": { "status": "ok" },
  "meta": {},
  "error": null
}
```

실패 시 data는 null, error에는 code·message를 담는다. 공통 meta는 계약에 따라 출처·실제 기준일/분기·공간 단위·분모·데이터 버전을 표현한다. 필드 구조를 임의로 만들지 않는다.

오류 코드는 `INVALID_PARAM`, `CATEGORY_REQUIRED`, `ADDRESS_NOT_FOUND`, `OUT_OF_SEOUL`, `AS_OF_OUT_OF_RANGE`, `UPSTREAM_ERROR`, `AI_UNAVAILABLE`, `AI_VERIFY_FAILED`, `INTERNAL_ERROR`를 사용한다. 외부 원시 예외·응답·인증 정보는 사용자에게 노출하지 않는다. 공급자 429는 기존 `AI_UNAVAILABLE`로 매핑한다. 일반 요청 검증은 422 INVALID_PARAM, 라우터 404/405는 HTTP 상태를 유지한 INVALID_PARAM, 미처리 예외는 500 INTERNAL_ERROR로 제공한다. CORS 안쪽에서 응답 시작 전 예외를 처리하며 프로토콜 응답을 강제 포장하지 않는다.

| 작업·기능 | API | 입력·반환 및 처리 |
|---|---|---|
| BE-03 | `GET /api/health` | 공통 응답의 status=ok |
| BE-11 / F-01 | `GET /api/geocode` | query → 카카오 → 서울 확인 → 좌표·지번·building_key·floor_unit. 서울 외 422 OUT_OF_SEOUL, 결과 없음 404 ADDRESS_NOT_FOUND, 복수 후보 candidates[] |
| BE-12 / F-02 | `GET /api/stores/history` | building_key·floor_unit·category, 시간순 이력·영업 기간·location_match(same_spot/same_building/unverified) |
| BE-13 / F-03~04 | `GET /api/stores/nearby` | lat·lng·radius·category·sub_category·as_of·area·franchise. center·radius·count·markers[]·excluded_no_coord |
| BE-14 / F-05 | `GET /api/meta/data-range` | category 필수·sub_category 선택. min_month(nullable)·max_month·max_date·data_updated_at·collected_at |
| BE-15 / F-05 | `GET /api/stores/snapshot` | total_at_as_of·still_open·closed_since·other·stores[] |
| BE-22 / F-06 | `GET /api/market/activity` | recent_12m·yearly_trend·by_sub_category·sales·living_pop·flags |
| BE-23 / F-07 | `GET /api/risk` | 7절의 공식·참고 지표 및 상태·근거 |
| BE-32 / F-08 | `POST /api/risk/interpret` | 서버 Risk 재계산 → 집계 입력 → LLM → 검증 → 캐시 → 응답 |
| BE-33 / F-10 | `GET /api/support-links` | 서울시 자영업지원센터·소상공인아카데미·서울시 지원사업·소상공인24 등 설정/DB 관리 |

- 이력은 지원 업종 전체의 자리 변화를 보여주는 방향으로 보완한다. category는 진단 맥락으로 유지하고 타 지원 업종 제거 필터로 쓰지 않는다. 이는 외부 명세 동기화 대기 사항이며 제외 업종까지 포함하는 전 업종 이력을 뜻하지 않는다.
- 이슈 #36 구현 계약은 source+license_no 식별, nullable 상호·개폐업일·기간, operating_period_status=fact|no_data 및 operating_period_reason을 사용한다. 날짜가 부족해도 이력은 유지하며 기간을 0으로 만들지 않는다. 기간은 달력상 완료 개월 수이고 영업 중 종료점은 검증된 배치들의 DAT_UPDT_PNT 최대 날짜다. 층만 동일하면 same_spot이 아니다. FE CLAUDE.md·타입·표·진단서의 호환은 요청 보고서에 따라 FE 담당자가 반영하고 BE는 해당 결과를 확인한다. 오류는 현행 422/500 및 공통 외피를 유지하며 원본 400/504·geocode 구조·전체 meta 일괄 변경은 별도 동기화 대상으로 둔다.
- 주변 점포는 PostGIS `ST_DWithin`으로 검색하고 최종 `distance <= radius`를 검증한다. 반경 경계를 포함한다.
- 조회 가능 최소 월은 검증된 개업일과 실제 원천 조회 범위로 정한다. 이상 날짜·원천 기본값으로 달력을 확장하지 않는다. 유효 표본이 없으면 날짜를 만들어내지 않는다.
- #43의 data-range는 nearby와 공통 출처·날짜 cohort를 사용하며 좌표·반경·면적·가맹 조건을 최소 월에 섞지 않는다. 보관된 인허가 날짜 구간을 재구성하며 원천 변경 이력 API의 시작일로 자르거나 과거 전체 현황 관측을 보장하지 않는다. D가 확인된 빈 업종은 min_month=null, max_month/max_date는 실제 D이고 출처 미준비는 500이다. FE nullable·세부 업종·최신 일자는 [FE 요청 보고서](fe-data-range-api-request.md)에 따라 담당자가 반영한다.
- 시점 T의 영업 조건은 `open_date <= T AND (close_date IS NULL OR close_date > T)`다. snapshot은 항상 `total_at_as_of = still_open + closed_since + other`를 만족해야 한다.
- #45 snapshot은 nearby와 같은 공간 조회·입력 파서를 쓰고 as_of만 필수다. 같은 목록의 최신 상태를 분해하며 N은 목록 길이와 같다. source+license_no 식별, nullable 상호/기간·기간 상태/사유, 전체 기간 latest_data, 서울 비공간 좌표 미확보 수를 반환한다. 중복/불변식·응답 검증 실패는 안전한 500/no-store이며 FE 반영은 [snapshot 요청 보고서](fe-store-snapshot-api-request.md)를 따른다.

## 7. 분석·공식 지표 규칙

### 상권 판정과 기준 분기

- 좌표를 포함하는 세부 상권을 우선하고 관광특구를 별도 병기한다(R-13). 중복 합산하지 않는다. 같은 우선순위의 중첩 상권이 모호하면 후보·사유를 제공하고 임의 선택하지 않는다.
- 상권 밖이면 상권 공식 수치는 null/no_data와 상권 밖 사유를 제공하고 반경과 겹치는 상권 목록을 별도로 제공한다(R-14). 가까운 상권 수치로 대체하지 않는다. 반경 참고 지표는 유효 표본이 있으면 계산한다.
- 현재 조회의 공식 통계는 데이터셋별 공표·적재 검증이 완료된 최신 분기를 먼저 선택한다. 특정 상권·업종 결측을 이유로 더 과거 분기를 찾지 않는다.
- 과거 조회는 요청 시점이 속한 분기를 사용하고 없으면 no_data다. 요청 기준일과 실제 적용 분기를 구분한다. 점포·반경 기준일을 공식 통계 분기로 과거 이동시키지 않는다.
- 분기 자체를 정할 데이터 미확보는 pending이다. 상권변화지표에도 같은 선택 원칙을 적용하되 자체 데이터셋 공표 이력을 사용하며 업종별 자료가 아니면 업종 조건을 추가하지 않는다.

### 지표별 계산·반환

| 구분 | 지표 | 규칙 |
|---|---|---|
| 공식 | official_closure_rate | market_code + seoul_induty_cd + 선택 quarter 일치. 결측은 null/no_data, 가까운 분기 대체 금지 |
| 공식 | market_change | 서울시 원천 유형 그대로, 적용 상권·분기 표시 |
| 공식 안내 | official_risk | 수치 수집 경로 확인 전 링크 전용 보완안 사용. 추정 수치·스크래핑 금지 |
| 참고 | closure_rate_12m | 최근 12개월 폐업 점포 / 기간 내 영업 점포 × 100. 분모 정의·0 처리·대상 코호트는 원본 분석 명세 대조 후 확정 |
| 참고 | survival_rate_1y·3y | 원본 분석 정의에 따라 계산, 최소 표본 미달 판단 보류. 임계값은 설정으로 관리하며 기존 예시 5를 확정값으로 간주하지 않음 |
| 참고 | competitor_count | 지원 업종·유효 위치·시점·필터 기준의 동종업체 수 |
| 참고 | day_night_ratio | 주간 생활인구 합 / 야간 생활인구 합. 시간 구간·0분모 처리는 원본 명세 대조 후 확정 |

최근 12개월 개업·폐업은 각각 `open_date`, `close_date`가 `(T - 12개월, T]`인 건이다. 평균 영업 기간·생존율은 검증된 날짜를 사용하고 분모·결측·판단 보류 사유를 함께 제공한다.

추정매출은 반경과 겹치는 상권을 market_code로 연결해 각각 반환한다. 반경·점포 예상 매출이나 주변 평균 매출로 바꾸지 않는다. 생활인구는 반경 내 250m 격자 기준이며 실제 방문객 수가 아닌 추정치다. 결측을 0으로 바꾸지 않고 `missing_grid_count`를 반환한다.

공식 창업위험도 지표 객체의 보완안은 다음과 같다. URL 유효성은 연계 시 확인하며 최상위 응답은 공통 형식을 유지한다.

```json
{
  "id": "official_risk",
  "type": "official",
  "value": null,
  "status": "link_only",
  "link": "https://golmok.seoul.go.kr/stateDistrict.do",
  "copy_text": "상권명 · 업종명"
}
```

copy_text에는 확인된 상권·업종만 사용하고 사용자 주소·좌표를 넣지 않는다. 상권 밖·불명확한 경우 이름을 만들어내지 않는다. 링크 안내를 공식 수치 확보 완료로 보지 않는다. 새 enum은 9절의 계약 동기화 후 배포한다.

## 8. AI·캐시·운영

AI는 계산 엔진이 아니다. 서버에서 재계산한 Risk 결과 중 업종·반경·기준일·지표·분모·출처·상태·missing_items만 전달한다. 주소·좌표·building_key·floor_unit·상호·license_no 및 점포 식별정보는 외부 전송하지 않는다.

- 공급자와 API 로직을 분리한다. 기본 모델 `gemini-3.5-flash-lite`는 환경변수로 변경 가능하게 유지한다. 실제 연계 시 무료 이용 가능 여부·모델 수명을 다시 확인한다.
- 한도는 모델·프로젝트별 요청 수·토큰 수·일일 한도를 설정으로 관리하며 분당 15회를 공통 고정값으로 가정하지 않는다. 429에는 제한된 지수 백오프·지터를 적용하고 시간 예산 초과·일일 한도 소진 시 AI_UNAVAILABLE로 종료한다. 지표 API는 계속 동작해야 한다.
- 프롬프트는 `app/ai/prompts/`에서 PROMPT_VERSION으로 관리한다. Verifier는 JSON Schema, 숫자·지표 의미·출처·상태, 공식/참고 혼동, 금지 표현, 개인정보, 분량·중복을 검사한다. 실패 시 1회 재생성하고 재실패는 503 AI_VERIFY_FAILED다.
- Risk·AI 캐시는 분석 조건·data_version으로 구분하고 AI에는 prompt_version·model·context_hash를 추가한다. 데이터·모델·프롬프트가 바뀌면 이전 결과를 재사용하지 않는다.
- API 로그는 UTC 시각·고정 경로/unknown 표식·실제 HTTP 상태/null·소요 시간·서버 request_id·ASGI 전송 완료 여부를 JSON stderr에 기록한다. AI endpoint의 최종 상태와 LLM client.post 시도/HTTP200 여부를 구분한다. ETL은 독립 run_id·실제 batch/version UUID·순차 단계·허용 건수/품질사유·시간만 선택하고 겹치는 플래그를 최종 제외 수로 합산하지 않는다. 앱 파일/DB 저장·외부 수집기를 추가하지 않았으므로 원본30일 보관/삭제는 배포 수집기에서 후속 검증한다.
- 로그에는 사용자 주소·좌표·건물/층호 식별정보·원본 행·AI 입력/출력 원문·API 키를 남기지 않는다.

## 9. 외부 명세 동기화·확인 대기

아래는 개발 방향을 정리한 것이며 외부 원본 문서를 수정한 기록이 아니다. 원본 확인 → 명세 수정·FE 합의 → 구현·배포 순서로 반영한다. 기본 앱·원본 보존·정제 기반은 독립적으로 진행할 수 있다.

| 대상 | 대조·확정할 내용 |
|---|---|
| 범위 | 분식·기타 등 제외 안내, 기능 F-04·지표 M-05(LQ 제외), 서비스 개요·데이터 활용 명세 동기화 |
| 공식 분기 | 데이터셋별 공표 이력·실제 적용 분기 필드·현재/과거 선택 규칙 |
| 공식 변화지표 | market_change 공식 분류, 원천 유형·공간 단위 |
| 공식 위험 안내 | link_only enum·link·copy_text 필드와 URL, 상권 밖 안내 |
| 상권 판정 | 경계 포함 규칙·관광특구·중첩 후보·상권 밖 사유·반경 내 상권 목록 필드 |
| 데이터 상태 | pending/no_data·판단 보류 등 지표 상태와 FE 라벨 |
| 이력 | category가 진단 맥락이라는 의미와 타 지원 업종 반환 방향 |
| ETL·주소 | 원천 CRS·보완 API 필드, 플래그 enum, 모호한 대표 지번·상세 위치 처리 |
| 계산 | 참고 폐업률 분모, 생존율 코호트·표본 기준, 평균 영업 기간, 주야간 구간·0분모 |
| 필터 | 반경 선택값·시설 규모 구간·다중 선택·배열 표현과 API 인자 |
| AI | 429의 AI_UNAVAILABLE 매핑·HTTP 상태·재시도 안내·시간 예산, 무료 이용·한도 확인 |

출처 미확보 자료의 최신 분기나 원천 누락률·표본 수를 단정하지 않는다. 계산 docstring에는 실제 분석 정의서 절 번호를 쓰고 원본이 없으면 확인 대기로 남긴다.

## 10. 코드·협업·검증 규칙

### 작성·보안

UTF-8·LF·Python 4칸 들여쓰기를 사용한다. 모듈·함수·변수·JSON·DB 필드는 snake_case, DB 테이블은 복수형, 클래스·스키마는 PascalCase, 상수는 UPPER_SNAKE_CASE다. 타입 힌트와 Pydantic 요청·응답 모델을 사용하고 계산 함수는 근거 docstring을 둔다.

반경·최소 표본·시간 제한 등은 명명된 설정/상수로 관리한다. 외부 호출에는 timeout·예외 처리를 넣는다. 키·비밀번호는 서버 시크릿에서만 읽고 코드·문서·로그·단체방에 공유하지 않는다. `.env.example`의 비밀값은 비우며 비밀이 아닌 기본값은 유지할 수 있다. CORS는 개발 localhost·배포에 필요한 명시적인 origin만 허용한다.

원천 대용량 데이터는 커밋하지 않는다. `data/sample/`의 소량 샘플에는 출처·링크·기준일·실제/가상 여부·추출/생성 기준·라이선스·정제 제한을 적는다. 시연 숫자는 예시임을 표시한다.

### 작업·보고·Git

시작 전 이 문서, 현재 구현, 브랜치·미커밋 변경, CI·의존성을 확인한다. 완료된 것·없는 것·현재 PHASE·작업 번호·변경 파일·검증 방법과 한국어 이슈명을 먼저 보고한다. 다음 순서로 진행하고 완료 시 실제 이슈·브랜치·PR, 검증·남은 작업을 보고한다.

1. 이슈 생성 후 최신 develop에서 작업 순번을 넣은 브랜치를 만든다.
2. Codex가 `docs/designs/feat번호-기능명.md`에 범위·설계·테스트와 기능별 커밋 계획을 작성한다.
3. Claude Code가 해당 설계 MD를 검토하고 직접 수정한다. 검토 이유와 보류 사항을 같은 파일에 기록한다. 코드·다른 문서·Git은 수정하지 않는다.
4. Codex가 실제 수정본과 diff를 읽고 원본 계약·사용자 범위와 맞는지 확인한 뒤 구현한다. 기능과 해당 테스트를 한 커밋에 담고 독립 기능은 커밋을 나눈다.
5. PR 전에 로컬 테스트·ruff·mypy 등 해당 검사를 실행한다. 실패하면 수정·재검증하고 통과 전에는 PR을 만들지 않는다. 필요한 검사를 실행할 수 없으면 사유를 보고한다.
6. 검증 완료 후 커밋을 푸시하고 지정 양식으로 develop 대상 PR을 생성한다. CI 실패 시 수정 커밋과 재검증으로 처리한다.

Claude Code는 검토 대상 MD의 Read·Edit만 사용하도록 제한하고 UTF-8로 내용을 전달한다. 실제 파일 수정 여부를 확인하며 응답만 받고 검토 완료로 표시하지 않는다.

커밋은 `타입(영역): 한국어 요약`(50자 이내·끝 마침표 없음) 형식이다. 타입은 feat·fix·refactor·style·docs·test·chore·data를 사용하고 한 커밋에는 관련된 한 작업만 담는다. 실제 Issue는 #번호로 연결하고 상태는 To Do → Doing → Review → Done으로 관리한다.

PR은 develop을 대상으로 생성한다. 2026-11-12 최신 사용자 지시에 따라 제목은 FE PR 예시처럼 **`타입: 한국어 작업 설명`** 형식(예: `feat: 조회 가능한 데이터 월 범위 API 구현`, `fix: 잘못된 시점 처리 수정`)을 사용하고 본문에서 실제 이슈를 연결한다. 커밋의 `타입(영역): 한국어 요약` 형식은 유지한다. 본문은 사용자 지정 양식([PR 템플릿](../.github/pull_request_template.md))을 따른다. 2026-11-11 사용자 지시에 따라 확인 사항 네 문구를 변경하지 않고 체크한다(아래 FE 범위 정정이 우선). 로컬 실행·비밀정보 검사는 실제 수행하며, 코드 이해 항목은 사용자가 작업을 보며 확인하고 체크를 명시적으로 요청한 내용을 반영한다. 검사를 실행하지 않고 실행했다고 쓰지는 않는다. 2026-11-12 이후 BE PR은 로컬 검사·CI 통과와 실제 병합 조건을 확인하면 추가 확인 없이 develop에 Squash로 통합하고 이슈 종료를 확인한다. GitHub 본인 PR 승인 등록은 불가하므로 이를 우회·대리 승인하지 않는다. 필수 외부 리뷰가 남아 있으면 조건을 낮추지 않고 상태를 보고한다. PDF의 24시간 리뷰 응답은 참고 제안이며 main 반영·수동 소스 브랜치 삭제는 별도 요청 시 진행한다.

### 기능별 검증

2026-11-12 FE 업무 범위 정정이 위 체크 지침보다 우선한다. FE 담당자가 CLAUDE.md·계약·화면을 아직 반영하지 않았다면 관련 PR 확인 항목은 문구를 유지하되 미체크로 두고 담당자 반영 대기를 명시한다. 양쪽 수정 완료를 대신 주장하지 않는다.

| 테스트 | 필수 사례 |
|---|---|
| BE-T00 ETL | 원본 보존·좌표 누락/이상/보완 실패·날짜 오류·한시 사업장·카페 후보·산 지번/건물명/영문 호수/외 n필지 |
| BE-T01 주소 | 정상 서울·없는 주소·서울 외·복수 후보, 도로명/지번 building_key 일치 |
| BE-T02 이력 | 유/무·같은 건물 다른 층·상세 위치 미확인·타 지원 업종 이력·미지원 업종 제외·표본 20건 대조 |
| BE-T03 반경 | 499m 포함·500m 포함·501m 제외 |
| BE-T04 시점 | 개업/폐업일 직전·당일·이후 및 월 경계, snapshot 수 합계 |
| BE-T05 필터 | 업종·규모·프랜차이즈·정보 없음 |
| BE-T06 활동 | 개폐업 수·연도별 추이·상권별 매출 비합산·생활인구 결측과 missing_grid_count |
| BE-T07 Risk | 공식/참고·분모·생존율·표본 부족·상권 밖/중첩·관광특구·분기 선택·결측 비대체·링크·상태 |
| BE-T08 AI | 없는 숫자·잘못된 출처·pending 오용·금지 표현·개인정보·malformed JSON·429·백오프 상한·지표 API 독립 |

앱 구현 후 개발 서버 `/docs`에서 필수 API와 예시를 확인한다. 변경에 맞는 테스트와 ruff check·ruff format --check·mypy·pytest를 실행하고 실패·미실행 이유를 기록한다.

## 11. 완료 기준과 제출

필수 API·공통 응답, 원자료 표본 일치, 공간·시점 경계, 공식/참고 구분, LQ 미포함, AI 숫자·출처 검증, 비밀값 비노출, CI와 README 재현을 확인해야 완료다. 조건부 데이터는 미확보 시 pending과 사유를 검증하고 수치 제공 완료는 확보·검증 후 별도 판단한다.

이슈76의 [BE API 연속 조회 보고서](be-api-verification.md)는 격리 DB와 실제 카카오/개발 DB 읽기 검증을 다룬다. FE 화면·원본계약 합의·실제 LLM 안전성·운영/배포·조건부 활성화·전체 제출의 완료 근거로 확대하지 않는다.

이슈78의 [전체 기능 감사](be-system-audit.md)는 현재 실모델/원천dry-run·FE브라우저 결과까지 포함한다. FE결함/지도설정/외부원천응답이 남아 있어 전체 정상 판정은 보류하며 [FE 수정 요청](fe-system-audit-request.md)의 담당자 반영을 확인해야 한다.

README에는 서비스 소개·팀(시고르자브종)·역할, 환경·설치·실행, 변수명, 데이터 준비·ETL·샘플 재현, 검사 명령, 출처·라이선스를 적는다. 테스트 목록·출처표·PDF/이미지 예시를 준비하고 참고용 정보·사업주 역량 미반영·창업 성공/실패 판정 불가·예시 데이터를 명시한다.

공공 GitLab 이관은 FE·BE 별도 저장소 기준으로 진행한다. 대상·권한·브랜치·태그 범위를 확인하고 커밋 이력의 비밀값·대용량 자료를 검사한다. CI와 시크릿을 새 환경에 구성하며 Issue·PR·문서는 Git 미러만으로 옮겨지지 않으므로 별도 계획한다. 기존 대상 이력을 덮어쓰지 않고 이관 후 커밋·태그·브랜치와 실행·검사를 대조한 뒤 제출 주소를 갱신한다.

## 12. 참고 자료

개발 실행 절차는 10절을 따른다. 실제 개발 DB 연동을 지연하는 경우에는 3절의 선행 작업·큐 전체 중단 조건을 적용한다. CI 임시 DB의 통과를 실제 개발 DB 연결 완료로 간주하지 않는다.

기존 BE 문서와 사용자 결정을 통합했다. 사용자 제공 `12_개발규칙_Git코드컨벤션_SpotON.pdf`(v1.1, 2026-11-06, 5쪽)는 누락 규칙 보완에만 사용했다. 저장소 구조·브랜치·리뷰 방식은 PDF 제안보다 최신 사용자 결정을 우선한다.

AI 정보는 실제 연계 시 공식 자료와 프로젝트 계정에서 다시 확인한다. 모델 계열 전체의 자동 전환 날짜나 공통 호출 한도를 임의로 확정하지 않는다.

- [Gemini 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
- [호출 한도](https://ai.google.dev/gemini-api/docs/rate-limits)
- [모델 종료 일정](https://ai.google.dev/gemini-api/docs/deprecations)
- [요금·무료 범위](https://ai.google.dev/gemini-api/docs/pricing)

## 13. BE-13 주변 점포 설계 진행

아래는 #38 설계 작업 당시 기록이며 PR #39·#40으로 반영됐다. 이후 #41 구현 결과는 14절과 구현 기록을 따른다.

2026-11-12 사용자 지시에 따라 설계는 BE 범위로 작성하고 FE 영향은 요청 보고서로 전달한다. FE 코드·설정·문서·이슈·PR을 직접 수정하거나 생성하지 않는다.

- [이슈 #38](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/38), 브랜치 `feat#38-nearby-api-design`, 최신 develop `1e7a2a6`에서 분리한 설계 전용 작업이다.
- [BE 설계](designs/feat38-nearby-api-design.md)와 [FE 변경 검토 요청](fe-nearby-api-request.md)을 작성한다. Codex 설계 → Claude MD 직접 수정 → Codex 최종 점검 → 문서 PR·CI 순서다.
- 선행 [PR #37](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/37)은 검토 중 develop에 병합됐고, 최신 develop `2160e64`를 설계 브랜치에 반영했다. 기존 작업 폴더를 유지한 별도 worktree를 사용한다. 사용자를 대신해 PR을 병합한 것은 아니다.
- #38 당시에는 설계만 진행했다. 주변 조회 API·migration·인덱스·DB 데이터 변경과 FE 구현은 완료로 표시하지 않았으며 후속 #41에서 BE 구현을 진행했다.
- 좌표 누락 건수는 반경 소속을 알 수 없어 서울 비공간 조건 기준 수와 집계 범위 meta를 제안한다. FE 표시 계약 확인 전 확정하지 않는다. 공간 후보 검색의 수치 경계 문제와 검증 계획은 설계 문서에 기록한다.
- 추가 읽기 전용 확인에서 지원 업종의 면적 0㎡가 6,316건이었다. 사용자는 0㎡를 정보 없음으로 처리하도록 확정했다. 설계는 DB 원본 0 보존·응답 area_m2=null·정보 없음 토글 동일 제어이며, 0을 확인된 33㎡ 미만으로 분류하지 않는다. 이번 문서 작업에서 실제 DB 값이나 코드는 변경하지 않는다.

## 14. BE-13 주변 점포 구현·검증 (#41)

- [구현 계획·Claude 검토·검증 기록](designs/feat41-nearby-api.md), 브랜치 `feat#41-nearby-api`. 최신 develop `2bb8f5d`에서 시작했다. 기존 문서 PR #40은 사용자 자동 머지 지시에 따라 일반 Squash로 병합했으며 본인 승인 등록 제한을 우회하지 않았다.
- `GET /api/stores/nearby`에 거리·시점·업종·면적·가맹 조건, 독립 unknown 토글과 legacy 호환, 기간·출처·좌표 누락 범위 meta를 구현했다. 0㎡는 원본 보존·출력 null이며 한시 true와 신뢰할 수 없는 날짜는 주변 시점 후보에서 제외한다. 이력 조회의 결측 보존은 유지했다.
- 개발 DB migration `0004`·689,440건. 인덱스 적용 전후와 읽기 검증 후 전체 행·geometry 해시 일치, 기존 내용 해시 일치, 앱 모델 비교 차이 0건이다. 실제 파괴적 suite는 별도 임시 DB에서만 실행했다.
- 일반 테스트 670개·격리 PostGIS 32개, ruff/format/mypy 65 files를 통과했다. 1,440개 공간 함수 조합의 후보 누락 0건, 실제 요청의 원자료 20건 대조·독립 WGS84 거리 재계산·실제 ORM EXPLAIN 반경 인덱스 조건·로컬 HTTP 응답을 확인했다.
- [FE 변경 요청 보고서](fe-nearby-api-request.md)를 현재 BE 계약에 맞췄다. FE 저장소는 변경하지 않았으며 지도·표·진단서와 FE CLAUDE.md는 담당자 반영 대기다. 좌표 누락 수의 서울 범위 표시 합의도 대기다.
- 로컬 검증 후 지정 양식 PR·CI 확인을 거쳐 develop에 자동 Squash 병합한다. 실제 PR·CI·병합 상태는 #41의 GitHub 연결 기록을 따른다. 원천 최신 전체 수집, 브랜드 분류, data-range·snapshot API는 이번 범위에 없다. 다음 BE 작업은 BE-14의 데이터 범위·시점 조회 설계다.

## 15. BE-14 데이터 조회 가능 월 범위 (#43)

- 최신 develop `61380a8`에서 `feat#43-data-range-api`를 만들었다. [Codex 설계·Claude 직접 검토·최종 점검·검증 기록](designs/feat43-data-range-api.md)을 따른다.
- `GET /api/meta/data-range`와 category/sub_category 검증·출처·날짜 후보·출처 meta 공통화를 구현했다. 기존 nearby의 출처/후보 함수 본문은 AST 비교로 같은 로직임을 확인했고 history/nearby 회귀를 통과했다. DB·migration·Docker·로컬 설정 변경은 없다.
- `uv run --locked --extra dev` 환경에서 ruff/format·mypy 70 files, 기본 693개·격리 PostGIS 43개를 통과했다. 실제 API 9개 업종/세부 업종 조합을 독립 SQL과 대조하고 원자료의 최소 날짜 표본 20건·전체 CSV 갱신일 최대값을 확인했다. data-range와 nearby의 최소 월 허용·직전 월 거절, 실제 HTTP·실제 SQL 실행 계획을 검증했다.
- 실제 개발 DB 0004·689,440건, API 읽기 확인 후 전체 행·geometry 해시가 기존 검증과 동일하다. 출처·최소 날짜의 세 SQL 실행은 관측값 약 0.036~376.281ms였으며 전체 요청 SLA 검증은 아니다.
- [FE 월 범위 요청 보고서](fe-data-range-api-request.md)에 nullable 최소 월·sub_category·max_date·달력/빠른 선택·과거 자료 한계를 요청했다. FE CLAUDE.md와 화면 반영은 대기다.
- PR 제목은 사용자 예시의 `feat: 조회 가능한 데이터 월 범위 API 구현` 형식으로 작성하고, 본문은 기존 양식을 유지한다. CI·병합 조건 확인 후 develop에 자동 Squash 병합하며 실제 상태는 #43 GitHub 기록을 따른다. 다음 BE 작업은 **BE-15 `GET /api/stores/snapshot`**이다.

## 16. BE-15 과거 시점 점포 상태 분해 (#45)

- 최신 develop `e1af8d2`에서 `feat#45-store-snapshot-api`를 만들었다. [설계·Claude 직접 검토·Codex 최종 점검·검증](designs/feat45-store-snapshot-api.md)을 따른다.
- `GET /api/stores/snapshot`을 구현했다. nearby의 공간 조회·기간 계산·입력 파서를 추출해 두 API의 같은 집합을 보장한다. N=A+B+C=목록 길이와 source+license_no 중복 없음을 검사하고, 응답 검증 실패는 부분 목록 없는 500/no-store로 처리한다.
- ruff/format·mypy 75 files, 일반 718개·격리 PostGIS 47개를 통과했다. 필터/시점/반경 조합·기간/결측·거리 경계·최신 상태·합계·같은 관리번호/다른 원천·빈 결과·오류와 기존 조회 회귀를 확인했다.
- 실제 DB 20개 조합의 목록·순서·집계를 독립 SQL/거리와 대조하고, 추출 전후 nearby 전체 JSON 두 경우·원자료 20건의 날짜/상태/기간·실제 HTTP·공간 인덱스 사용을 확인했다. 기존 사전 nearby 1회 실패는 재진단과 최종 조합에서 재현되지 않았으며 원인을 확정하지 않았다. 콜드 캐시/운영 SLA는 검증 완료로 표시하지 않는다.
- DB 0004·689,440건은 읽기 검증만 수행한다. 최종 해시 보존 결과는 구현 기록을 따른다. 모델·migration·원본·Docker·환경설정·FE 저장소 변경은 없다.
- [FE snapshot 요청](fe-store-snapshot-api-request.md)에 복합 식별자·결측·최신 상태/전체 기간·실제 기준일·집계/서울 범위 표시를 전달한다. FE·CLAUDE.md 반영과 문구 합의는 대기다. CI·저장소 조건 통과 후 자동 Squash 병합하며 실제 상태는 #45 GitHub 기록을 따른다.
- 다음 순서는 **BE-16 상권 경계 Polygon 적재 기반**이다. 필요한 원천·기준 시점·권한이 없으면 자료 요청 지점에서 중단하고 후속 실행 큐를 우회하지 않는다.

## 17. BE-16 상권 경계 버전 적재 (#47)

- 사용자 승인으로 공식 OA-15560 공개 ZIP을 직접 확보했다. 원본은 저장소 밖에 두고 hash로 검증했다. [설계·Claude 직접 검토·Codex 최종 점검·검증](designs/feat47-market-areas-import.md)을 따른다.
- market_area_versions/market_areas·migration 0005, pyshp 기반 ZIP 검증·읽기 전용 dry-run·PostGIS 보정/변환·advisory lock을 이용한 원자적/멱등 적재를 구현했다. 기존 인허가 ETL head guard도 0005로 갱신했다.
- 일반 742개·격리 PostGIS 54개·ruff/format·mypy 82 files를 통과했다. 실패 rollback·같은 버전 재사용·새 규칙 공존·동시 실행·훼손 거절·ZIP/CRS/geometry/면적·hole/multipart·FK/CHECK/GIST·기존 조회 회귀를 검증했다.
- 실제 개발 DB 0005에 1,650개 고유 상권·25개 구·4유형·버전 1개를 적재했다. 6개 보정 후 무효/빈 도형 0건이며 replay는 같은 버전·loaded_at·digest를 유지하고 inserted=0이다. 원자료 20건·독립 좌표 변환·hole/multipart·경계 포함·반경 교차·실제 GIST 사용·앱 관리 모델 차이 0건을 확인했다. 기존 점포/배치 및 원본 ZIP 보존 결과는 구현 기록을 따른다.
- 공식 첨부 수정일은 2023-10-23(내부 파일 2023-10-20)이며 포털 갱신일 2026-09-11을 적용일로 사용하지 않는다. boundary_as_of=null로 유지하고 최신/과거 분기의 경계라고 주장하지 않는다. 공개 API와 FE·Docker·환경설정은 변경하지 않았다.
- 지정 제목/본문의 PR·CI 후 develop에 일반 Squash 병합하며 실제 상태는 #47 연결 기록을 따른다. 다음은 **BE-17 점포-상권 공식 통계 적재**로, 원천·기준 분기·경계 코드 호환을 먼저 확인한다. 자료/권한이 없으면 사용자에게 요청하고 후속 큐를 우회하지 않는다.

## 18. BE-17 공식 점포·개폐업 통계 적재 (#49)

- #47/PR #48 경계 기반은 develop에 병합됐다. [#49 설계·Claude 직접 수정·Codex 최종 점검·검증](designs/feat49-market-stores-import.md)을 거쳐 market_store_versions/market_stores·migration 0006과 공식 연간 ZIP 실행기를 구현했다.
- 공식 OA-15577 2025년 ZIP(첨부 수정일 2026-05-21·CP949 CSV)을 확보하고 전체 304,775행을 검증했다. 지원 5종 **24,810행**(분기별 6,219/6,215/6,191/6,185), 미지원 279,965행 제외다. 누락 조합을 0으로 채우지 않고 전체/일반/가맹·개폐업 수와 원천 비율을 보존한다.
- 일반 **775개**, 격리 PostGIS **62개**, ruff/format·mypy **88 files**를 통과했다. 실제 DB 0006 dry-run→write→replay, 원자료 20행·저장 hash/모델 일치·기존 조회 API200을 검증했다. 기존 점포 689,440건·경계 1,650건·배치/버전의 전체 hash/건수와 원본은 보존됐다.
- 분기별 코드·유형 차이는 0개, 경계와 명칭 차이는 1개다. 이것을 적용 시점 일치로 간주하지 않으며 boundary_compatibility=unverified·boundary_as_of=null을 유지한다. 원천 폐업률 100 초과 24행도 그대로 보존했다. 공식/참고 비율 계산·지표 API·FE·Docker/환경설정 변경은 없다.
- 지정 PR·CI 후 develop에 일반 Squash 병합하며 실제 상태는 #49 연결 기록을 따른다. 다음은 **BE-18 상권별 추정매출 적재**로, 원천·사용 조건·기준 분기·업종/경계 호환부터 확인한다. 자료/권한이 없으면 사용자에게 요청하고 후속 큐를 우회하지 않는다.

## 19. BE-18 상권별 추정매출 원천 적재 (#51)

- #49/PR #50 공식 점포 통계는 develop에 병합됐다. [#51 설계·Claude 직접 수정·Codex 최종 검토·검증](designs/feat51-market-sales-import.md)을 거쳐 market_sale_versions/market_sales·migration 0007·원천 적재 CLI를 구현했다. ZIP/provenance/경계 대조 공통화의 BE-17 hash·출력 회귀와 실제 원본 replay를 확인했다.
- 공식 OA-15572 2025년 ZIP(첨부 수정일 2026-05-18·55개 한글 헤더·CP949)의 **85,732행**을 검증하고 지원 5종 **14,391행**(3,617/3,596/3,597/3,581)을 적재했다. 미지원 **71,341행** 제외다. 금액/건수 BIGINT를 환산하지 않고 null/실제0/누락 행을 구분한다.
- 일반 **798개**, 격리 PostGIS **72개**, ruff/format·mypy **97 files** 통과. 실제 DB 0007 dry-run→write→replay(동일 UUID/시각/hash·삽입0), 원자료 20행·모델 차이0·기존 API200을 확인했다. 기존 점포 689,440건·경계 1,650건·점포 통계 24,810행 및 전체 배치/버전 hash·원본은 보존됐다.
- 매출 금액 단위는 원이지만 `당월_매출_금액`의 분기 합계/월평균 의미는 미확인이다. amount_period_status/boundary_compatibility=unverified·boundary_as_of=null을 유지하며 매출 API 활성화·월/분기 환산·반경 합산·점포당 계산은 하지 않았다. 점포 통계에만 있는 지원 조합은 분기별 2,602/2,619/2,594/2,604개이며 0으로 채우지 않았다.
- 지정 PR·CI 후 develop에 일반 Squash 병합하며 실제 상태는 #51 연결 기록을 따른다. 다음은 **BE-19 생활인구 250m 격자·시간별 적재**로, 공식 제공 범위·권한·용량/기간·좌표계부터 확인한다. 키/자료가 없으면 사용자에게 요청하고 후속 큐를 우회하지 않는다. FE·Docker·환경설정 변경은 없다.

## 20. BE-19 생활인구 격자·시각별 원천 적재 (#53)

- #51/PR #52는 develop에 병합됐다. #53/브랜치 feat#53-living-population-import에서 사용자 1번 결정(좌표 미확인 보존·공간 집계 제외)을 반영했다. [Codex 상세 설계·Claude 실제 수정·Codex 점검](designs/feat53-living-population-import.md)을 거쳐 4개 테이블·migration 0008·일별 3개 원천/격자 manifest 실행기를 구현했다.
- 공식 2026-11-07 내국인 253,400행·장기 137,137행·단기 141,385행과 EPSG5179 격자 10,125개를 검증했다. 합계 **531,922행**이며 행정동/시각/원천 차원·원문 hash·비식별/결측/실제0을 보존한다. 미매칭 **1개 격자/24개 비식별 행**은 located_grid_id=null·unlocated로 보존하고 공간 inner join에서 제외한다. 전역 source/date 미확인 수를 반경 내 missing_grid_count로 표현하지 않는다.
- 후행 소수점 숫자 표기와 참조 무결성·메모리 등 선택은 사용자 추가 지시에 따라 Claude와 재검토 후 결정했다. Numeric(20,5)·명시적 문법·고정 소수 포맷·복합 FK·streaming/hash·일별 전체 트랜잭션을 적용했다. 통상 선택을 반복 질문하지 않고 근거를 남기며 필수 자료·키·권한 부재는 계속 요청한다.
- 일반 **844개**, 격리 PostGIS **82개**, ruff/format·mypy **107 files**를 통과했다. 실제 개발 DB 0008에서 dry-run 무삽입→격자10,125개/관측531,922행 적재→replay 삽입0을 확인했다. 원자료20행·좌표20개 대조·실제 GIST·모델차이0·기존 API5개200, 기존8개 테이블 전체 행/geometry hash·원본 ZIP4개 보존도 확인했다. 실행 비용과 검증 한계는 설계의 구현 기록을 따른다.
- API/FE·주야간 비율·반경 집계·다일 백필·Docker/환경설정 변경은 없다. grid_as_of=null·spatial_compatibility=unverified이며 사용자 결정만으로 격자의 실제 적용 시점이나 행정동 분할 합산 의미를 확정하지 않는다. CI 후 일반 develop Squash 병합하며 실제 상태는 #53 연결 기록을 따른다. 다음은 **BE-20 공식 상권변화지표 원천 적재**로, 제공 범위·기준 분기·원천 유형부터 확인한다.

## 21. BE-20 공식 상권변화 유형 원천 적재 (#55)

- #53/PR #54 생활인구는 develop에 병합됐다. [#55 설계·Claude 실제 Read/Edit·Codex 최종 점검](designs/feat55-market-change-import.md)을 거쳐 market_change_versions/market_changes·migration0009·전체 CSV 검증/완료 연도 적재 CLI를 구현했다.
- 공식 OA-15576 전체 CSV **36,300행**(2021년1분기~2026년2분기)을 검증하고 기존 점포/매출 자료와 같은 **2025년6,600행**(분기별1,650행)을 적재했다. 나머지29,700행은 선택 연도 밖이며 업종 제외가 아니다. 업종 필드를 추가하지 않고 원천4유형·공식 명칭·평균 정수개월을 보존한다.
- 기본 READ ONLY dry-run·연간 원자성·동시 writer 직렬화·hash 재검증/불변 버전·provenance 충돌 거절을 구현했다. 수집 시각은 재실행 시에도 최초값을 전달하고 source_file_date=null을 유지한다. 공통 boundary audit은 Protocol 타입만 변경했고 기존 동작·hash·lock key를 유지한다.
- 일반 **870개**, 격리 PostGIS **92개**, ruff/format **220 files**·mypy **113 files** 통과. 실제 DB0009에서 dry-run→write→같은 UUID/loaded_at/hash replay 삽입0·원자료20행·모델차이0·기존 API5개200을 확인했다. 기존12개 테이블 전체 행/geometry hash·건수와 원본 CSV SHA256도 보존됐다. 상세 결과는 설계의 구현 기록을 따른다.
- 경계 코드/구분 차이0·명칭 차이 분기별3개, boundary_compatibility=unverified다. 평균의 모집단·산정 기간/경계 적용일은 미확인이며 평균으로 분류를 재계산하지 않는다. 공개 API/FE·Docker/로컬 환경설정·의존성 변경은 없다. 지정 PR·CI 후 develop 일반 Squash 병합하며 실제 상태는 #55 연결 기록을 따른다. 다음은 **BE-21 브랜드 정규화·프랜차이즈 추정 매핑**으로, 공정위 공식 원천·권한·매칭 기준부터 확인한다.

## 22. 전체 시스템 점검·오류/중복 코드 정리 (#58)

- 사용자 요청으로 [Codex 점검·Claude 실제 MD 수정·최종 점검](designs/feat58-system-audit-cleanup.md) 후 오류4건을 재현·수정했다. LLM 실제 전체/개별 요청 timeout, 비유한 Retry-After fallback, 과도한 카카오 지번 숫자의 안전한 기존 주소 오류 처리, CSV 수집시각 기준 분기 검증을 보완했다. 회귀23개를 추가했으며 수정 전15실패→관련106통과를 확인했다.
- 같은 결과의 중복 법정동 조건2줄과 오래된 package 설명2개만 정리했다. 기존 주소42개 회귀를 재사용했으며 의도된 빈 예외/모델·ORM 등록 import/noqa·namespace·후속 AI 모듈·이유가 있는 주석은 보존했다. API/응답 계약·migration·원천·로컬 환경설정·FE 구현 변경은 없다.
- 전체 일반 **893개**, 격리 PostGIS **92개**, ruff/format **221files**, mypy **113files** 통과. 직접 의존성14개는 설치/uv.lock/pyproject 버전이 일치한다. 실제 head0009·모델차이0·일반 앱 계정 권한·정상API6개(외부 카카오 포함)·주소검색→이력200·잘못된 입력3개422·CORS를 확인했다. 기존 원본의 ETL7개 dry-run이 정상 종료했고 기존14개 테이블 전체 행/geometry hash·건수는 동일했다. 기록 범위와 상세 결과는 설계의 구현 기록을 따른다.
- FE는 읽기 점검과 lint/build/format을 통과했지만 HistoryTable null 정렬·source 없는 식별자 등의 반영이 대기다. 새 요청으로 중복 작성하지 않고 기존 [이력](fe-store-history-api-request.md)·[주변](fe-nearby-api-request.md)·[월 범위](fe-data-range-api-request.md)·[snapshot](fe-store-snapshot-api-request.md) 요청을 따른다. 이력 요청서의 BE PR 상태만 GitHub 병합 사실에 맞췄다. FE 파일/이슈/PR은 수정하지 않았다.
- 유료 LLM 실제 호출·미구현 activity/risk/AI API·브라우저 전체 시연·FE 통합 완료는 검증 범위가 아니다. 기존 Starlette/httpx deprecation 경고1건을 숨기지 않았고 의존성 대규모 교체는 하지 않았다. BE-21 인증 대기는 #57에서 유지한다. 지정 PR·CI/CodeQL 후 develop 일반 Squash 병합한다.

## 23. BE-22 기본 상권 활동 분석 (#60)

- 시스템 점검 PR #59 이후 develop `b9584c3`에서 `feat#60-market-activity-api`를 만들었다. 원본 API v1.2 §4-6·데이터 활용 v1.2 §3.9·분석 정의 §4-6을 대조하고, [Codex 설계·Claude 실제 MD 수정·Codex 최종 규칙/검증](designs/feat60-market-activity-api.md)을 기록했다. 브랜드는 선택 자료이므로 #57 승인 대기와 독립적인 기본 인허가 집계를 먼저 구현한다. 미확인 가맹을 개인 매장으로 바꾸지 않는다.
- `GET /api/market/activity`는 폐업 기록도 보존해 최근 12개월 개폐업·같은 월일까지의 실제 연도별 YTD·T 시점 세부 업종별 점포 수/평균 완료 개월을 반환한다. 평균은 버림·0분모 null이며 latest 전체 기간이나 수명 평균과 구분한다. 기존 거리/날짜/속성 필터·읽기 전용 세션·안전한 오류/no-store를 재사용한다.
- `sales`/`living_pop`은 항상 null이고 요청된 항목만 missing·pending/사유에 넣는다. 가맹 분류 pending, denominator=null·폐업 포함 cohort_size·서울 동일 비공간 조건의 좌표 미확보 수·출처 D/T/collected_at=null을 명시한다. 기존 API 형식·모델·migration·의존성·Docker/환경설정 변경은 없다.
- 전체 일반 **924개**, 격리 PostGIS **99개**, ruff/format **227 files**, mypy **116 files**를 통과했다. 새 일반31개·통합7개로 날짜 경계/윤년/YTD/폐업 보존/평균/거리·필터12조합/입력·DB오류·실제 READ ONLY 세션을 확인했다. 실제 개발 DB **10조합**을 독립 SQL과 대조했고 head0009·모델 차이0·기존14개 테이블 전체 행/geometry hash·건수 보존을 확인했다. API+독립 SQL 관측 시간은 SLA 검증이 아니다.
- [FE 활동 분석 요청](fe-market-activity-api-request.md)에 기간·평균·미요청과 pending 구분·가맹 미확인·출처/시점을 요청한다. FE 코드/CLAUDE.md·이슈/PR은 수정하지 않았고 반영 대기다. 브랜드 승인·조건부 수치 활성화·BE-22 전체 결합·Risk/AI는 후속이다. CI/CodeQL·저장소 조건 통과 후 develop 일반 Squash 병합하며 실제 상태는 #60 연결 기록을 따른다.

## 24. BE-23 선행 상권 공간 판정 (#62)

- 활동 API PR61 이후 develop `408e32b`에서 `feat#62-market-judgement`를 만들었다. [Codex 설계·Claude 실제 MD 수정·Codex 최종 점검](designs/feat62-market-judgement.md)을 거쳐 명시 버전의 내부 공간 판정 서비스와 엄격한 모델을 구현했다. 공개 Risk 경로·공식 수치 연결은 후속이며 기존 API 형식·FE 계약은 바꾸지 않았다.
- ST_Covers의 경계 포함·hole/multipart, 세부 상권 우선/관광특구 병기, 동순위 중첩의 ambiguous 후보, 상권 밖의 반경 교차 목록을 제공한다. 최신 버전 자동 선택이나 가까운 상권 대체는 하지 않으며 빈/부분 버전은 안전하게 실패한다. 적용성은 unverified로 고정하고 원천 수정일을 적용일로 바꾸지 않는다.
- 전체 일반 **957개**, 격리 PostGIS **103개**, ruff/format **233 files**, mypy **118 files** 통과. 새 일반33개·통합4개로 경계/구멍/분리 영역/유형·중첩/거리/버전 격리/미확인 상태/읽기 전용 호출을 확인했다. 실제 **135조합**을 독립 SQL과 대조해 일치했고 모델차이0·head0009·무효 도형0을 확인했다. 기존 경로 검사 최초1회 실패 후 재확인은 모두200이며 원인 미확정·SLA 미검증이라는 한계도 남겼다.
- 실제 개발 DB 기존14테이블 전체 행/geometry hash·건수 보존을 확인했다. PR·CI/CodeQL을 확인하고 develop 일반 Squash 병합하며 실제 상태는 #62 연결 기록을 따른다. DB 모델/migration·의존성·원본·Docker/로컬 설정·FE 변경은 없다. 이 내부 기반에는 FE 보고서가 필요한 공개 계약 변경이 없으며 후속 Risk 계약 때 요청서를 작성한다. 브랜드 승인 #57·경계 적용 분기 확인·공식/참고 지표·Risk API·FE 통합은 대기다.

## 25. BE-23/25/26 Risk 참고지표 (#64)

- 상권 기반 PR63 이후 develop `1cb88e2`에서 작업했다. [Codex 설계·Claude 실제 MD 수정·Codex 최종 결정/검증](designs/feat64-risk-reference-api.md)을 거쳐 GET /api/risk를 구현했다. 참고 폐업률은 기간 중 영업 기록 분모10, 생존율은 개업 코호트의 고정1/3주년·분모5로 계산한다. 원본의 모호한 시점과 FE mock을 보완한 BE 계약안이며 현재 잔존과 구분하고 원본/FE 합의 완료로 표시하지 않는다.
- 동종업체 수와 같은 필터/좌표 확보 서울 비교값·분모/출처 배열·Decimal HALF_UP·소표본/0분모/실제0·미요청 구분을 제공한다. 경계 UUID는 서버가 명시한 경우에만 후보로 읽고 market.status=unverified를 유지한다. 공식 폐업률/상권변화·인구비는pending, 공식 창업위험도는link_only다. 기존 API·모델/migration·의존성·Docker/.env·FE 변경은 없다.
- 전체 일반 **992개**, 격리 PostGIS **111개**, 최종 ruff/format **240 files**, mypy **121 files** 통과. 새 일반35·통합8로 기간/코호트 양끝·주년/윤년·현재 폐업과 고정기간 생존 차이·표본/비율/서울 비교·12개 독립 unknown 조합·거리·미확인 후보·실제 읽기 전용 세션을 확인했다.
- 실제 **10조합**을 독립 SQL·다른 달력/정수 반올림식과 대조했고 실제 표본5건 주년·명시 UUID 후보·모델차이0·head0009·14테이블 전체 행/geometry hash·건수 보존을 확인했다. 단일 요청 관측0.492~0.680초(별도최초1.802초)·서울 aggregate 관측35.632ms는 운영/동시부하 SLA 보장이 아니다. 데이터 선택/지위승계/과거 재구성 한계는 설계에 기록했다.
- [FE Risk 요청서](fe-risk-reference-api-request.md)에 배열 출처·기간 분모 기준·고정 주년 의미·unverified·0/null/서울 비교·지표 상태/문구 검토를 요청한다. FE/원본/CLAUDE.md 반영은 대기다. 공식 분기/업종 매칭·조건부 수치·브랜드57·AI/캐시는 후속이며 CI/CodeQL 후 develop 일반 Squash 병합한다. 실제 상태는 #64 연결 기록을 따른다.

## 26. BE-28 AI 해석용 허용 집계 입력 (#66)

- Risk PR65 이후 develop `27e7c8a`에서 `feat#66-ai-risk-context`를 만들었다. [Codex 설계·Claude 실제 MD 수정·Codex 최종 점검](designs/feat66-ai-risk-context.md)을 거쳐 query-only 서버 재계산→typed allowlist→불변 입력/안전한 직렬화·해시→기존 프롬프트 준비를 구현했다. 주소/좌표/상권/점포·URL/raw meta/UUID를 전송하지 않으며 사유·출처·기간·비율·방법론도 검증한다.
- 프롬프트 v2와 지문 이력을 추가해 미산정/안내 전용·고정 주년·서울 비교·가맹 미확인을 유지한다. verifier도 link_only/unverified 값 생성을 차단한다. 원문을 repr/오류에 남기지 않고 데이터/프롬프트 버전은 context_hash와 구분한다. 실제 공급자/공개 AI API·전체 응답/의미 검증·캐시는 후속이다.
- 전체 일반 **1,018개**, 격리 PostGIS **115개**, ruff/format·mypy **123 files** 통과. 새 일반26·통합4로 필드/값 canary·위조 모델 재검증·직렬화 경고/원문 비노출·상태/숫자·동일 hash/중첩 불변성·실제 서버 재계산/읽기 전용을 확인했다. 실제 DB **6조합**과 별도 명시 경계 후보에서 추출값·해시·모의 공급자 본문을 대조했고 실제 LLM 호출은0이다.
- head0009·모델차이0·14테이블 전체 행/geometry hash·건수 보존, 기존 health/activity/risk 실제 조회200·공개 AI 경로 미추가를 확인했다. 최초 준비5.995초·이후0.565~0.760초, 별도 실제 문장3초 세션 준비0.608초를 관측했으나 원인/콜드캐시·운영 SLA는 확정하지 않았다.
- API/DB 모델/migration·의존성·원본·Docker/.env·FE 변경은 없고 공개 계약 변경이 없어 새 FE 요청서는 만들지 않았다. 현재 Risk 보고서의 FE 반영과 브랜드57·공식/조건부 지표·실제 AI/FE 통합은 대기다. CI/CodeQL 후 develop 일반 Squash 병합하며 실제 상태는 #66 연결 기록을 따른다.

## 27. BE-32 핵심 AI 해석 API (#68)

- PR67 이후 develop `49205fd`에서 `feat#68-risk-interpret-api`를 만들고 [Codex 설계·Claude 실제 MD 검토·Codex 최종 점검](designs/feat68-risk-interpret-api.md)을 거쳤다. `POST /api/risk/interpret`는 원래 Risk query만 받아 재계산하며 클라이언트 수치/응답·주소·building_key/floor_unit·중복키를 거절한다. 첫 버전은 이력/활동 추가문맥을 지원하지 않는다.
- 모델은 모든 유리/불리 비교의 순서와 일반 현장 질문1~3개만 선택하며, 서버가 수치/방향/최종 문장을 조립한다. method=server_sentences_model_ordering과 프롬프트v4/요청별 ID enum·후보 수 검증을 적용한다. 필수 사실·소표본/미확인·공식/조건부 pending·수집일null·자료 한계는 빠짐없이 유지한다. 자유 AI 서술·성공/위험 판정이나 원본/FE 합의 완료가 아니다.
- 프로세스 기본5회/분·50회/일·동시2, 준비/대기/생성/최대1회 재생성/조립의 전체20초 기본 예산을 적용한다. 읽기 전용 worker세션은 모델 호출 전에 닫으며 취소/timeout 후 정리한다. 동기SQL 즉시강제중단·분산 한도·운영SLA는 보장하지 않는다. 입력422/서버500/공급자·한도·시간503 AI_UNAVAILABLE/선택2회실패503 AI_VERIFY_FAILED이며 no-store다.
- 전체 일반 **1,037개**, 격리 PostGIS **117개**, ruff/format·mypy **127 files** 통과. 새 일반19·통합2로 후보/본문/예산/재생성·자원 정리/기존 API를 확인했고 소수점 문장 분리 오판도 수정했다. 실제 DB head0009·모델차이0·14테이블 전체 행/geometry hash·건수 보존·기존 API3개200을 확인했다.
- 최종 실제 Gemini API **2건200**, 재생성0·3.142초/2.569초를 관측했다. 전체 실제 생성7회(probe1·미허용ID 거절4·최종성공2)이며 최초 외부 생성 전500의 정확한 원인은 미확정이다. 미허용ID를503으로 차단한 뒤 동적 enum/후보 수를 추가해 수정했다. 원문/키 없이 집계 결과만 기록하며 모델 안전성/운영부하 전체 검증으로 확대하지 않는다.
- BE README/CLAUDE.md를 반영했고 [FE AI 요청 보고서](fe-risk-interpret-api-request.md)를 작성했다. FE 코드/CLAUDE.md·원본 합의는 담당자 대기다. DB 모델/migration·의존성·원본·Docker/.env·FE 변경은 없으며 이력/활동 추가문맥·캐시·브랜드57·공식/조건부 수치·전체 통합은 후속이다. CI/CodeQL 후 develop 일반 Squash 병합하며 실제 상태는 #68 연결 PR을 따른다.

## 28. BE-33 공식 상담·지원기관 공통 링크 (#70)

- AI PR69가 GitHub CodeQL 시작 오류/Backend CI 대기로 미병합 상태라 의존성이 없는 BE-33을 develop `49205fd`의 `feat#70-support-links-api`에서 진행했다. [원본 §4-9/D-08 대조·Codex 설계·Claude 실제 MD 수정·Codex 최종 점검](designs/feat70-support-links-api.md)을 거쳤으며 PR69 코드를 가져오지 않았다.
- `GET /api/support-links`는 서버 불변 설정4기관·고정 순서·출처R17과 KST 수동 확인일2026-11-12를 반환한다. 선택 서울25구/category는 검증하지만 현재 일반 안내만 있으므로 meta.prioritization=not_applied다. **원본의 구/업종별 우선 정렬은 미구현**이며 현재 자격/모집/맞춤 선정으로 설명하지 않는다. URL 원문을 유지하고 공식 HTTPS 호스트만 허용하며 날짜를 오늘/배포일로 바꾸지 않는다.
- 요청 중 DB/LLM/외부 HTTP를 호출하지 않고 인증키 없이 동작한다. 원본8필드/id/type/region은 FE mock과 대조했다. 422 입력·500 서비스/serialization 오류·no-store·안전 로그·공통 외피를 유지하며 DB 모델/migration·의존성·Docker/.env·FE 변경은 없다.
- 새 일반34개를 포함한 전체 **1,052 passed**, 기존 통합115개 deselected, ruff/format **252 files**·mypy **127 files** 통과. 25구×두업종/생략의78조합에서 목록 보존, 불량/중복 입력·URL·불변성·고정 확인일·외부/DB 차단·실패/출처/OpenAPI/CORS를 확인했다. 실제 로컬 uvicorn HTTP **10개** 검사도 통과했다. SQL 변경이 없어 이번 작업의 PostGIS 통합 suite 재실행/개발 DB 적재는 하지 않았다.
- 공식4곳을 Codex Windows 환경에서 실제 HTTP GET하여200·기관 제목을 확인했고 아카데미는 같은 호스트 `/main`으로 이동했다. 외부 검색 도구의 센터 timeout과 직접 HTTP 성공을 구분하며 이후 가용성/지원 자격을 보장하지 않는다. BE README/CLAUDE.md와 [FE 요청 보고서](fe-support-links-api-request.md)를 반영했고 FE 코드/CLAUDE.md·실제 화면 연결은 담당자 대기다. CI/CodeQL 성공 전에는 병합·이슈 종료로 표시하지 않는다.

## 29. BE-35 개인정보 없는 운영 로그 기반 (#72)

- 이 작업 시작 시 미병합이던 상담 PR71·AI PR69를 모두 최신 CI/CodeQL 성공 후 일반 Squash 병합했고 이슈70/68 종료를 확인했다. AI 브랜치에는 먼저 병합된 상담 기능의 앱/문서 충돌4곳을 두 기능 보존으로 정리해 일반1,071개와 원격 통합117개를 재확인했다. 새 로그 구현은 develop `e3ebddc` 기반이다.
- [원본 확인·Codex 설계·Claude 실제 MD 수정·Codex 최종 점검](designs/feat72-private-operation-logs.md) 후 API 순수 ASGI 관측·ETL6개 실행기/단계·Gemini HTTP 시도 메타데이터를 고정 필드 JSON stderr로 기록했다. 본문/주소/좌표/헤더/IP/원자료·프롬프트/출력/키는 기록하지 않고 알려지지 않은 경로는unmatched다. API 실제 상태/null·ASGI 완료·서버UUID와 ETLrun_id/실제batch/version UUID·허용 건수/품질사유를 구분한다.
- 기록 실패/ID 생성 실패는 작업을 바꾸지 않으며 취소/예외·ETL transaction/commit·stdout 결과·응답/exit code를 보존했다. 인허가 argparse 오류는 고정 메시지다. 기본 uvicorn access log를 억제했고 기존 --no-access-log 안내도 유지했다. HTTP200 관측은 파싱/AI 최종 검증 성공이 아니며 transport 내부 재시도는 미구분이다.
- 새 일반43개 포함 전체 **1,114개**, 별도 포트55472 일회용 PostGIS 전체 **117개**, ruff/format **267 files**, mypy **133 files** 통과. API 입력/경로·취소/스트림·stderr/ID 장애·동시성·ETL6개/commit 이후 기록·합성 snapshot/CLI·정제숫자·Gemini0/재시도/취소를 확인했다. 기존 Starlette 경고1건은 유지한다.
- 실제 기본 uvicorn HTTP **10건/JSON API 이벤트10개**, 합성 snapshot subprocess dry-run **6개 ETL 이벤트**와 transformed2/affected0·원래 stdout·비노출을 확인했다. 기본INFO access stdout도 비어 있었고 실모델 호출0·실제 개발 DB 쓰기0이다. 개발 DB의 파괴적 테스트 대신 일회용 컨테이너를 사용했다.
- BE README/CLAUDE.md를 반영했으며 공개 API/응답·DB 모델/migration·의존성·.env/Docker·FE 변경은 없다. 응답 계약 변경이 없어 새 FE 요청서는 만들지 않았다. **원본30일 보관/삭제·외부수집기/프록시/제3자 전체로그 정책은 미구현/미검증**이고 느린stderr/프로세스간 원자성은 보장하지 않는다. CI/CodeQL 후 일반 Squash 병합하며 실제 상태는 #72 연결 PR을 따른다. 다음 독립 개발은 **BE-34 Risk·AI 캐시와 버전 무효화**다.

## 30. BE-34 Risk·AI 캐시와 버전 무효화 (#74)

- PR73 병합 develop `542bde7`에서 [Codex 설계·세 차례 Claude 실제 MD 수정·Codex 최종 결정](designs/feat74-risk-ai-cache.md)을 거쳐 프로세스별 bytes LRU/TTL·HMAC key를 구현했다. Risk/AI 기본300초·최대7일, 각각256항목/4MiB payload이며 worker/객체 overhead는 별도다. 유휴 앱도1초 sweep으로 만료 참조를 정리하고 종료/취소·늦은 저장을 차단한다. 정확한 물리 삭제 시한/secure erase 보장은 아니다.
- primary READ ONLY REPEATABLE READ snapshot·GUC/DB/role 지문으로 동일batch/updated_at불변 DML도 무효화한다. old snapshot과 새 결과를 분리하며 unrelated 쓰기/rollback도 보수적 miss다. warm도DB가 필요하고 오류를 과거 성공으로 숨기지 않는다. 동시 TRUNCATE/rewrite/복구는 drain→cache종료→변경→재시작 대상이다.
- 좌표6자리+정확float·정규화한 조건/요청월·규칙/경계를 key에 반영하고 Risk query echo는 저장하지 않는다. AI는 snapshot/데이터/context/prompt/model/후보/schema/검증규칙별 검증 선택 ID·모델명만 저장한다. 같은key 동시생성을 합치고 대기는 gate밖이다. 앱한도/전체예산·실패미저장·no-store를 유지한다. generated_at은 현재 문장조립시각, regenerated는 현재요청 기준(hit=false)이다. 공유 cache의 시간차에 의한 최근 조회 추론 한계는 남는다.
- 새 일반52/통합7을 포함한 **일반1,166개·격리 PostGIS124개**, ruff/format273files·mypy135files 통과. TTL/유휴정리/회계·조건/버전/경계·동시성/취소/오류·실제MVCC DML/세션/원천실패를 확인했다. 기존 wrapper keyword와 짧은 hash canary 테스트 가정도 수정했다.
- 실제 개발 DB READ ONLY 검증에서 카페/음식점 cold0.6195/0.6367초·9SQL→warm0.0099/0.0080초·3SQL, uncached결과일치, AI2요청/모의공급자1회·실모델0회를 확인했다. head0009·모델차이0·14테이블 행/geometry hash·건수는 보존됐다. 유휴 snapshot61개/300초가1종이었던 관측은 운영 hit율 보장이 아니다.
- BE README/CLAUDE.md와 기존 [FE AI 요청서](fe-risk-interpret-api-request.md)를 보완했다. API schema·프롬프트·DB모델/migration·의존성·실제 .env/Docker·FE 변경은 없다. FE 반영/계약·전체 통합은 담당자 대기다. 브랜드57승인·공식/조건부 수치·AI추가문맥·지원맞춤정렬·로그30일삭제는 후속이다. CI/CodeQL 후 develop 일반 Squash 병합하며 실제 상태는 #74 연결 PR을 따른다.

## 31. BE API 연속 조회 통합 검증 (#76)

- #74/PR75 캐시는 develop `de756f0`로 병합됐다. 다음 작업으로11절의 BE API 연속 검증을 선택해 [Codex 설계·Claude 실제 MD 수정·코드 대조/최종결정](designs/feat76-api-flow-verification.md)을 수행했다. 브랜드57은 승인대기를 유지하고 재인증하지 않았다.
- 합성 snapshot→기존ETL실행기/격리PostGIS→mock HTTP 지오코딩→이력/월범위/주변/시점/활동/Risk/AI/지원링크의 연결22개·고유10시나리오를 추가했다. 모집단/식별·날짜/분해/수치·두원천충돌·면적0·과거월말·재적재/rollback·캐시변경·AI실패독립/원문비노출을 확인한다. CI는 필수함수10종·기존no-skip/error 검사를 적용하고 실제XML 통과/시나리오누락 거절을 확인했다.
- 전체 **일반1,166개·격리 PostGIS146개**, ruff check/format·mypy135files 통과. 이력빈원천0건/as_of=null과 분석500, 주변/시점의 좌표누락(시점영업)과 활동/Risk(폐업포함개업이력)의 차이를 검증 가정/회귀 fixture에 반영했다. 앱 코드·공개schema·계산규칙을 바꾸지 않았다.
- 실제 로컬 uvicorn HTTP23요청·카카오2사례에서 이력5/2건·주변595/604건·집합/분해/영업수·D/T/버전/AI수치일치·모의공급자2회/AI4요청을 확인했다. 진단중카카오2회를 포함해 실제카카오총4회·실모델0회다. 개발 DB READ ONLY·head0009·모델차이0·14테이블 행/geometry hash·건수를 보존했다.
- [BE API 검증 보고서](be-api-verification.md)·README/BE CLAUDE.md를 반영했다. FE저장소·실제.env/Docker·모델/migration·프롬프트·의존성 변경은 없다. 기존FE요청서의 계약은 그대로이며 FE브라우저/화면·원본합의·실제모델/운영·브랜드/조건부/로그삭제·최종제출을 완료로 표시하지 않는다. 지정PR·CI/CodeQL 후 develop 일반Squash 병합하며 실제상태는 이슈76 연결기록을 따른다.

## 32. 전체 시스템 기능별 감사 (#78)

- 사용자 요청에 따라 [설계·Claude 실제 MD검토·Codex 최종대조](designs/feat78-system-functional-audit.md) 후 BE/FE현재develop 기준 기능별 정상/실패·연결을 검사했다. 판정과 근거는 [전체 기능 감사 보고서](be-system-audit.md)를 따른다. FE수정금지는 유지하며 [FE결함5종 요청](fe-system-audit-request.md)을 작성했다.
- BE 일반1,166·격리PostGIS146·ruff/format·mypy135files, FE lint/build 통과. 실제API18판정/연결12조건·오류7개, 실제원천dry-run6실행기/7회 모두통과/쓰기0이다. 실모델카페/음식점 각1회200·검증통과/재생성0·warm추가호출0을 확인했다. 로그실제HTTP10/이벤트10·합성ETL6·지원URL4곳200도 재확인했다.
- 실제 DB READ ONLY·head0009·모델차이0·public인덱스동일·14테이블전체행/geometry hash/건수보존을 확인했다. 실제 .env/Docker·원본·앱코드/모델/migration·프롬프트·의존성·FE추적파일은 바꾸지 않았다. BE에서 수정할 확정결함을 발견하지 못해 가짜수정/검사를 추가하지 않았다.
- FE는 실제AI요청422·unverified를상권밖으로확정, 유효합성응답의null날짜표/진단서파손·source다른동일ID중복key·null상호/기간빈칸을 재현했다. 기존요청서계약을 서버에서 완화하지 않고 담당자수정·재검증을 요청한다. 지도는 VITE_KAKAO_JS_KEY가 없어 중단/요청했고 사용자는 설정하겠다고 답했으며 완료 확인/SDK검증은 대기다.
- 휴게음식점 실제100행200/3.91초는 확인했지만 일반음식점은100행20초 및최소1행30초 ReadTimeout이다. 키/승인 오류로 단정하거나 최신전체수집 완료로 표시하지 않는다. 브랜드57승인·공식/조건부/맞춤정렬·로그30일삭제 등 기존미완료도 유지한다.
- 전체정상판정은 보류한다. 감사문서PR은 Ref#78로 연결하고 CI/CodeQL 후 develop 정상Squash하되 이슈78은 FE/지도/외부원천 후속 추적을 위해 열린상태로 남긴다. main·FE직접수정·강제우회는 하지 않는다.

### FE 요청서 재점검 (BE develop1f81baf·FE21ec13f)

- 사용자 요청에 따라 `feat#78-audit-recheck`에서 [재점검 설계·Claude Code 실제 소스 검토·Codex 최종 판단](designs/feat78-audit-recheck.md)을 기록했다. Claude 첫 검토는 FE 접근이 거절되어 BE 계약만 확인했고, 형제 저장소 읽기 경로를 추가한 두 번째 검토에서 FE5종 근거를 직접 대조했다. FE코드/설정/문서/이슈/PR은 수정하지 않았다.
- 실제 FE AI422·unverified 오표시와 유효 합성 결측/식별3종을 재현했다. 정상 이력5행·과거월200, query-only 모의 공급자200·이번 실LLM0회다. [FE 요청서](fe-system-audit-request.md)에 include/unknown/최신시점 생략·실패처리·사유별 문구와 수정 순서를 보완했다.
- 지도 키는 BE 로컬 환경에 존재하며 자식 Vite프로세스에만 전달했다. SDK401·도메인 제한/Chrome ORB 차단으로 해당 JavaScript 키의 localhost:5173 SDK도메인 등록을 요청하고 지도 검증은 중단했다.
- 실제 브라우저 동시 조회에서 이력/주변/활동/Risk 약3초500을 관측했다. 후속 순차5·동시10은200이나 최초 SQLSTATE/원인 미확정이다. 전역 배치조회 LIMIT 후보는 현재 빨라도 과거 배치 누적 시 회귀할 수 있다는 Claude 지적을 채택해 미적용했다. BE 간헐500은 #78의 별도 미해결로 추적한다.
- 이번 변경은 문서뿐이다. BE API/앱코드·모델/migration·timeout·실제DB/.env/Docker·FE를 바꾸지 않는다. 기존 전체검사1,166/146는 최초감사 근거로 재사용하며 이번 재실행으로 표기하지 않는다. 전체정상·FE완료로 표시하지 않고 이슈78을 유지한다.

### SDK 도메인 등록 후 후속 검증

- 사용자가 FE는 기존대로 BE 검증/요청서만 보완하라고 재확인했다. 등록한 테스트 도메인에서 실제SDK200·지도 타일45응답200·500m152/300m44 API/마커일치·정상 표/마커 선택과 정보창/닫기를 확인했다. 모바일/확대/이동·전체 물리 hit test와 FE 영구 환경설정 완료는 아니다.
- 유효 Nearby 합성2행(다른 source/같은 관리번호)에서 마커DOM2/관리1·표2행동시선택·두번째선택시첫정보창을 재현했다. Claude 실제 소스/MD 검토 후 기존F4 요청에 타입source와 Map/selectedId/콜백/find 전체 복합식별·변경후정리 회귀를 보완했다. FE 직접 수정은 없다.
- 지도 실행은 브라우저 실제GET13건200·SQL오류0·실LLM0이었으나 별도출력 실행에서4개 API500이 재발했다. PostgreSQL 같은시각/동일PID 로그로 **출처 연결 배치 조회 statement_timeout4건**을 확인했다. SQLSTATE 자체·과거모든500의원인은 확정하지 않는다. PNG는미확인·PDF메모리1페이지/인쇄이벤트통과다.
- [감사보고서7절](be-system-audit.md)·[설계7~9절](designs/feat78-audit-recheck.md)·[FE 요청서](fe-system-audit-request.md)를 갱신한다. 코드/계약/실제DB/.env/migration/timeout은 바꾸지 않고 성능개선은 #78의 BE후속으로 유지한다. 전체정상 판정은 보류한다.

## 33. 출처 배치 조회 인덱스 개선 (#82)

- #78의 출처조회 statement_timeout을 다음작업으로 선택해 [Codex설계·Claude실제2회검토·최종판단](designs/feat82-store-provenance-index.md) 후 partial B-tree ix_stores_provenance를 추가했다. 키는batch_id/source/category/sub_category이며 삭제/검토대기행을제외한다. 기존서비스SQL·고아/전역기준일·3초제한·API계약은유지한다.
- migration0010·ORM·ETLhead검사와회귀를맞췄다. 일반1166·격리155(신규9)·ruff/format·mypy136files통과. 실제dev에는writer부재후indexDDL만적용했고14테이블전체행/geometry hash/건수·기존index·5API응답digest를보존했다. 실제head0010·모델차이0이다.
- 실제동시5API×3세트15건200/31~157ms·SQL오류0, 기존출처EXPLAIN0.096ms를확인했다. 정상출력PNG생성·인쇄이벤트·PDF메모리1페이지도통과했고실LLM추가호출0·FE변경0이다. 캐시warm/단발측정을포함하므로운영SLA보장은아니다.
- 합성689440행의전체재적재직후에는B에서도배치조회5.759초로3초를넘었다. 이구간은미해결이며, 인허가대량적재동안읽기중지→커밋→별도autocommit수동VACUUM(ANALYZE)stores→API확인→읽기재개를필수운영절차로README에남겼다. 자동VACUUM/자동차단·ETL원자성변경은없다. 쓰기비용/DDL잠금·과거배치누적한계도설계에기록했다.
- 코드/검증PR은#82를종료하되#78은FE5종·원천지연·대량적재후경계추적용으로유지한다. 브랜드#57승인·조건부데이터/API연결·AI추가문맥·지원맞춤정렬·로그30일삭제는후속이다. FE/.env/Docker·원본파일은수정/커밋하지않는다.

## 34. 생활인구 반경별 원자료 상태 진단 (#84)

- 브랜드 #57 승인 여부 답변을 요청하고 종속 수집은 보류했다. 독립 작업으로 [Codex 설계·Claude 실제 MD 검토·최종 결정](designs/feat84-population-quality-diagnostic.md) 후 내부 읽기 전용 진단기를 구현했다. 공개 생활인구 수치 API를 활성화하지 않는다.
- 명시 관측 UUID·원천 중심 속성·타원체 거리300/500/1000m를 사용한다. 72개 원천·시각 칸에서 실제0/비공개/결측/행 부재·복수행정동을 구분한다. 미좌표 행은 버전 전역으로 분리한다. 인구 합산·행정동 구성 완전성·반경 제공률은 판단하지 않는다. CLI는 저장 건수/metadata를 대조하며 content hash 재검증은 하지 않는다.
- 신규 단위30·통합18을 포함해 **일반1,196·격리PostGIS173**, ruff/format290파일·mypy138파일 통과. 경계r±0.01m·중심속성/도형 불일치·다른 관측/격자버전·누락건수·READ ONLY 쓰기거절·오류/해제를 확인했다. 기존 Starlette 경고1건만 있다.
- 실제2026-11-07 명시 버전·공개 고정점3곳×반경3개 총9회는1.672~1.906초였다. SQL3초는 유지하며 SLA로 주장하지 않는다. 별도 QA에서 생활인구4테이블 전체 행/공간 hash·건수와 head0010 보존을 확인했다. 실제 DML/DDL/재적재/VACUUM·실LLM 호출은 없다.
- README/BE CLAUDE에 사용법·의미 한계를 반영했다. 공개API/FE계약·pending·모델/migration·실제.env/Docker·사용자 분석문서는 수정하지 않는다. #57·#78 및 생활인구 의미/시점 검증·로그 보관/추천정렬 등 후속은 남아 있다. CI/CodeQL 후 develop 정상 Squash하며 실제 병합 상태는 #84 연결 PR을 따른다.

## 35. 인허가 적재 후 로컬 유지보수 실행기 (#86)

- 생활인구 공식 근거·브랜드 승인 대기와 독립적으로 #78/PR83의 수동 유지보수 절차를 실행기로 제공한다. [Codex 설계·Claude 실제 MD 검토·최종 판단](designs/feat86-localdata-maintenance.md) 후 `python -m etl.localdata.maintenance [--execute]`를 구현했다. 기본은 READ ONLY 대상/head/public.stores 소유권 점검이며 --execute만 별도 AUTOCOMMIT VACUUM(ANALYZE,TRUNCATE FALSE)·후속 읽기 전용 출처 검증이다.
- 기존 API/SQL·SQL별3초 기본값·ETL 트랜잭션·모델/migration·의존성/설정은 유지한다. 실행 단계만 명령60초·잠금5초를 쓴다. VACUUM 명령 정상 반환/후속 검사 통과를 분리해 실패·인터럽트·해제 오류에서 이미 완료한 상태를 보존하고 원문 없이 고정 오류를 출력한다. ETL 커밋·물리 정리를 되돌리지 않는다.
- 신규 단위17·통합7과 전체 **일반1,213·격리PostGIS180**, ruff/format294파일·mypy139파일 통과. 실제 격리 UPDATE/VACUUM·AUTOCOMMIT/세션설정·READ ONLY RR/3초·visibility 회복·비소유자/shadow schema·잠금/고아 실패·행/head/인덱스 보존을 확인했다. 기존 Starlette 경고1건 유지다.
- 실제dev는 dry-run만 수행하고 READ ONLY RR/3초를 계측했다. 별도 QA에서 stores/배치2테이블 전체행·공간 포함 hash/건수·head0010·인덱스·수동 유지보수/DML 카운터 보존을 확인했다. 실제 VACUUM/DML/DDL·원천/실LLM 호출0, FE/.env/Docker·사용자 미추적 분석문서 변경0이다.
- README/BE CLAUDE에 사용법·실패/비원자성을 기록했다. 운영자의 읽기/writer/migration 중지·실제API확인 후 재개는 계속 필요하다. 자동 조회 차단/재개·자동 일정·대량 성능/SLA를 구현/검증한 것은 아니다. #78·#57/생활인구 공식 근거·조건부 지표·로그30일보관·맞춤지원 등 후속을 유지한다. 지정PR·CI/CodeQL 후 develop 정상 Squash하며 실제 상태는 #86 연결 PR을 따른다.

## 36. 지원기관 관할 연락처 우선 안내 (#88)

- BE-33의 지역 안내를 [Codex 설계·Claude 실제 표/MD 검토·최종 대조](designs/feat88-district-support-contacts.md) 후 구현했다. 중기부 제2026-576호 공고 본문1/3/5쪽·PDF25쪽 별표2를 대조해 서울8센터/25구/전화를 확인했다. 과거7센터·블로그·서울신보 위치만으로 관할을 추정하지 않는다.
- 구 생략은 기존4개·순서를 유지하고, 지정 시 해당 관할 연락처1개+공통4개다. 업종은 목록/순서에 영향을 주지 않으며 자격/모집 판정은 하지 않는다. 기존8필드/type/region 유지·v2·지역만적용meta/공고 출처를 추가한다. URL은 검토한 공식 공고1개만 정확히 허용하며 지점/예약 URL이라고 표현하지 않는다.
- 일반1,260(지원링크81)·격리PostGIS180·ruff/format296파일·mypy140파일 통과. 새 단위47개·기존 API 연결 검사의5개/서대문센터 확인을 포함한다. 관할 누락/중복 설정의500에서no-store 누락을 발견해 수정한 뒤 전체 검사를 통과했다. 기존 Starlette 경고1건만 있다.
- 실제 로컬HTTP82건(200 응답80·의도한422 응답2)을 DB/외부전송 차단 상태에서 통과했다. 25구×업종2종/생략·구생략·health/OpenAPI/오류를 확인했고 DB/LLM 호출0이다. 실제 개발 DB를 열거나 VACUUM/DML/DDL·원천 적재를 하지 않았다. 공식 공고/첨부 HTTP200·자료hash/표 대조는 별도 검증이다.
- README/BE CLAUDE와 [FE 요청서](fe-support-links-api-request.md)를 최종 동작으로 갱신한다. FE 코드/설정/문서/이슈/PR·실제.env/Docker·사용자 미추적 분석문서는 수정하지 않으며 FE CLAUDE 반영도 담당자 대기다. 브랜드/생활인구·공식 조건부/로그 보관/FE 통합 등 남은 작업은 유지한다. 지정PR·CI/CodeQL 후 develop 정상Squash하며 실제 상태는 #88 연결PR을 따른다.

## 37. 생활인구 미확정 정책·품질 로그 (#90)

- 사용자 답변과 기존 적재를 대조해 행정동별 원문/hash·비공개/결측/실제0·미좌표 보존과 수치API pending을 유지한다. 새 staging 테이블이나 기존 원천 재적재 없이 빠져 있던 별도 품질 로그를 [Codex 설계·Claude 실제 MD Read/Edit·최종 검토](designs/feat90-population-quality-logs.md) 후 추가했다. 공식 의미/버전 근거 확보로 간주하지 않는다.
- 성공한 read_source 뒤·설정/DB 준비 전 etl_quality1건을 남긴다. 원천일 전체의 비공개·빈 셀·실제0·미좌표 행 수, source/hour/grid 내 복수행정동 그룹/행 수6개만 기록한다. 인구값/원문 코드/좌표/경로/예외는 기록하지 않는다. 전체6키 검증·source/hour순서 오류 시 counts 없는 failed를 남기며 원래 실행 결과·취소를 보존한다. 플래그끼리 겹치므로 합산 제외 수·인구·완전성/제공률을 만들지 않는다.
- 신규 단위16·격리4를 포함해 **일반1,276·격리PostGIS184**, ruff/format299파일·mypy141파일을 통과했다. 실제 합성168행·단일행정동/원천/시각 분리·상태 구분·정렬/로그 오류·설정/DB 실패·부분 적재 rollback·정상/replay의 stdout 필드/metadata/hash 보존을 확인했다. 기존 Starlette 경고1건이다.
- 실제2026-11-07 기존 manifest의 READ ONLY dry-run은531,922행·75.235초였다. 비공개57,779·빈 셀0·실제0인 행0·미좌표24·복수행정동75,360그룹/156,786행이며 독립 SQL6카운터와 일치했다. 인구 합계가 아니다. 별도 전후 QA로 원본4파일 SHA256·생활인구4테이블 전체행/공간 포함 hash·건수·head0010 보존을 확인했다. 실제 DML/DDL/새 수집/재적재/VACUUM/LLM 전송은 없다.
- README/BE CLAUDE를 갱신하며 공개API·FE 계약/FE 저장소·모델/migration·stdout·DB metadata/내용hash·.env/Docker·사용자 미추적 분석문서는 변경하지 않는다. 외부 로그수집기/30일보관·공급기관 공식 답변·#57 승인·#78 후속은 유지한다. 지정 PR·CI/CodeQL 후 develop 정상Squash하며 실제 병합 상태는 #90 연결PR을 따른다.

## 38. BE-21 브랜드 원천 수집·정규화·읽기 전용 대조 (#57 1단계)

- 사용자 승인 화면과 실제HTTP200/00·2025년11,167행 확인 후 #57을 재개했다. [Codex 설계·Claude 실제2회 MD검토·최종 판단](designs/feat57-brand-catalog-foundation.md)을 거쳐 `python -m etl.brands`의전체수집/원문snapshot/offline검증/READ ONLY점포대조를구현했다. 실제분류/판정모델·API/AI/캐시·재적재무효화는다음단계이며#57은종료하지않는다.
- 실원천에서숫자전용관리번호가정을수정했고단독번호13개반복/26행을발견했다. 입력을삭제/합산하지않고기준년·브랜드번호·본부번호의11,167복합행을보존한다. v2·복합키중복/페이지/총계·첫페이지재확인을검증하며반복번호의모든이름은repeated_brand_id로격리한다. 반복원인의공급자/법적의미는추론하지않는다. 검증실패원문은저장소밖unvalidated로보존하고완료snapshot으로받지않는다.
- 실제2025원천12페이지+재확인1회=13요청·11,167행, 고유브랜드번호11,154/반복13개·26행을수집했다. 외식8,873·서비스1,775·도소매519이며행수이지실제가맹점수아니다. 지원업종/삭제없음/검토대기아님355,835점포의READ ONLY대조는정확상호후보6,839·반복번호관련12·일반동명모호474·약한이름33,601·비외식126·미일치314,783·상호결측/기존판정보존0건이다. 좌표/날짜/영업상태로한정한화면점포수와다른모집단이다.
- offline무HTTP재실행의내용hash/대조건수·snapshot파일SHA256일치와기존14테이블전체행/공간EWKB포함hash·건수/head0010보존을확인했다. 최종수집+대조10.172초·전후보존/replay포함QA33.312초는해당실행값이며SLA아니다. 초기QA의to_jsonb(geometry)변환이60초시간초과해검증스크립트만EWKB문자열직접hash로수정했으며앱SQL/제한은유지했다.
- 신규단위55·격리5를포함해일반1,331·격리PostGIS189·ruff/format309파일·mypy147파일통과다. 복합키/반복격리·입력순서무관hash·페이지완전성/변조·원문비노출·offline무호출·기존파일/동시생성·실패정리/후속DB실패보존·READ ONLY쓰기거절·기존필드보존을확인했다. 기존Starlette경고1건유지다.
- README/BE CLAUDE·BE측활동요청서의승인대기서술을갱신한다. 분류pending·공개API/FE계약·stores.is_franchise/brand_id·모델/migration·기존.env/Docker/원본·사용자미추적문서는바꾸지않는다. FE변경0·실제dev DML/DDL/VACUUM·LLM전송0이다. source=brands/save_snapshot로그와safeCLI만추가한다. 지정Ref#57PR·CI/CodeQL후develop정상Squash하며실제병합상태는연결PR을따른다.

## 39. BE-21 브랜드명 기반 프랜차이즈 추정·필터 적용 (#57 최종 단계)

- [Codex 설계·Claude 실제 MD 검토·최종 판단](designs/feat57-franchise-classification.md)의 A안을 구현했다. 원본 stores에 자동값/trigger를 넣지 않고 새 catalog/brands/run/matches/state 5테이블에서 읽기 시점 정확 일치로 계산한다. migration0011과 shared head guard를 맞췄다. 상호·업종 변경 즉시 추정 제외, 외부 수동값 우선, 반복번호/동명/약한 이름은 미확인이다. 별칭·유사도 확장은 적용하지 않는다.
- 실제 2025년 원천11,167행·지원 점포355,835건 중6,839건을 추정 적용했다. 독립false는 생성하지 않았다. 같은 입력 재실행은 catalog/run UUID·loaded_at·state 무변경이다. 기존14테이블 전체행/공간EWKB hash·건수와 원본snapshot hash를 보존했고 모델 차이는0, head0011이다. 데이터가 있는 새테이블 downgrade는 거절한다.
- history/nearby/snapshot의 추정 근거·기준년도와 5개 API의 분류 meta·data_version, Risk 한계·AI typed context·prompt v5·cache를 함께 반영했다. 이름 일치는 계약/과거 가맹 확인이 아니며 coverage=partial·estimate다. franchise 전용은 include_unknown_franchise=false도 필요하다. 독립 전용0건은 실제 독립 매장이 없다는 의미가 아니다.
- 일반1,347·신규 브랜드 통합14건을 포함한 격리 PostGIS203개, ruff/format321파일·strict mypy154파일을 통과했다. 실제자료 HTTP41건과 내부AI준비6건·별도 로컬서버 HTTP2건도 정상이다. 실제 LLM 추가호출은0이며 전후 공개 AI API는 mock으로 검증했다. 3위치·필터별 4API 순차실행0.656~1.593초, SQL3초 제한을 유지해 B안은 채택하지 않았다. 측정은 SLA 보장이 아니다.
- [FE 요청서](fe-franchise-classification-api-request.md)와 BE CLAUDE/README·기존 요청서의 현행 분류 안내를 갱신했다. FE 저장소·CLAUDE.md 반영은 담당자 대기다. .env/Docker·원자료·사용자 미추적 분석문서는 수정/커밋하지 않는다. 로컬 API는127.0.0.1:8000에서 확인할 수 있다.
- 인허가 collected_at=null, 생활인구 공간/매출기간/공식 업종·분기·경계 미확정 수치 pending을 유지한다. FE 통합, #78 후속, 공급기관 공식 근거, 로그30일 운영, 자동갱신/배포는 별도 과제다. 이번 BE 이름 추정 v1의 기능 범위는 완료했으며 연결 PR의 CI/CodeQL 및 정상 develop Squash를 확인한 뒤 #57을 종료한다.

## 40. BE-32 후속 AI 해석 상권 활동 문맥 (#96)

- 브랜치 `feat#96-ai-activity-context`(develop `41475fa`). [Claude Code 설계·별도 Claude Code 재검토/MD 직접 수정](designs/feat96-ai-activity-context.md)을 거쳤다. 재검토에서 원안 커밋 배치가 중간 커밋의 기존 테스트를 깨뜨리는 문제·SQL 수(6문장)·응답 ID 타입 확산을 발견해 반영했다.
- 요청 형식은 그대로 두고 같은 세션에서 활동 집계를 재계산해 허용 필드만 AI 문맥에 넣는다. Risk와 기준일·배치·분류·모집단 크기·동종업체 수·폐업 분모/분자를 교차 검증하며 불일치는 안전한 500이다. official_values에 서버 참고 계산 문장과 활동 식별자 2종을 추가하고 비교 후보 ID는 기존 범위를 유지한다. prompt v6·선택 cache rule v2다.
- 일반 1,373 passed(기준선 1,347+신규 26)·ruff/format·mypy 154 files 통과. 최장 조합(음식점·1000m·include 2종·비교3·checklist3·큰 수) 서버 문장은 1,169자(활동 315자)로 verifier 2,000자 안이다. 격리 PostGIS 통합 테스트(활동 대조 1·필터 7조합·과거/빈 업종 보강)는 이 PC에 Docker가 없어 CI에서 실행한다.
- 이력 문맥(building_key/floor_unit 요청)·연도별 추이·활동 기반 판정 후보는 제외했다. FE 저장소는 수정하지 않고 [FE AI 요청서](fe-risk-interpret-api-request.md)에 칩 라벨·반복 ID 처리를 요청한다.
- 2026-11-13 이 PC에 Docker·WSL을 설치하고 팀원 덤프로 `spoton_dev`(head 0011, 기록과 같은 건수)를 복원해 실제 개발 DB 읽기 전용 검증을 마쳤다. 6조합 모두 활동 문맥=활동 API·영업 수 합=competitor, cold/warm SQL 15/8, 준비 0.082~0.713초(SLA 아님), 빈 license_no 0건, 모의 공급자 API 200·실제 LLM 0회, 20개 테이블 행 hash 보존. 상세는 설계 §13이다. PR·CI/CodeQL 후 develop Squash한다.

## 41. BE-32 후속 AI 해석 선택 이력 문맥 (#98)

- 브랜치 `feat#98-ai-history-context`(develop `bb30668`). [Claude Code 설계·별도 Claude Code 재검토/MD 직접 수정](designs/feat98-ai-history-context.md)에서 HistoryQuery 생성 위치(서비스 생성 시 500), 위치 422 경로, 반경 대신 고정 300m, 층만 입력 시 comparable, 커밋 배치·흐름 테스트 확장 방식을 바로잡았다.
- 요청 선택 필드 `history`로 같은 세션의 이력을 재계산하고 위치·Risk 교차 검증 뒤 식별정보 없는 집계와 서버 문장만 추가한다. prompt v7·선택 cache rule v3다.
- 일반 1,414 passed, 로컬 일회용 PostGIS 통합 212 passed, ruff/format·mypy 154 files 통과. 기존 `test_gemini::test_overall_budget_cancels_retry_sleep`이 전체 실행 1회 실패 후 단독 5회·전체 재실행 통과해 시간 의존 불안정 테스트로 기록한다(이번 변경과 무관한 파일).
- 실제 개발 DB 읽기 전용: 5사례 집계=이력 API 파생값, 1km 밖 422, 이력 포함 SQL cold19/warm12·준비 0.21~0.49초(SLA 아님), 모의 공급자 API 200·건물키 노출0·실제 LLM0, 테이블 hash 보존. 건물키 121,182개 중 좌표 점포 없는 키 11,988개(9.9%)는 위치 검증을 생략한다. 이후 팀 키 설정 후 실제 Kakao geocode 30건(300m 초과 0건, 최대 103.8m)과 실제 Gemini 2회(200·검증 통과·재생성 0)를 추가 확인했다.
- FE 저장소는 수정하지 않고 FE AI 요청서에 history 전송·floor_unit null·위치 422·이력 ID 칩·missing reason을 요청한다.

## 42. BE-10/11 지명으로 인한 상세 위치 누락 수정 (#102)

- 브랜치 `feat#102-floor-place-names`(develop `3ed3f2f`). [수정 전 피드백 분석](be-fe-integration-feedback-review.md)에서 확인한 `중` 접두사 파서 결함만 수정한다. [Codex 설계·Claude Code 문서 직접 수정](designs/feat102-address-place-floor-parser.md)에서 단순한 정규식 축소가 모호한 `중B1 101호` 등을 호수만으로 받아들이는 문제를 찾아 보완했다.
- `중구`·`중랑구`·`중계동`·`중앙로` 등 지명을 정상 처리하고 실제 중간층 표현의 모호 판정은 유지한다. 같은 공통 파서를 쓰는 주소 검색과 새 ETL 변환에 적용된다. 대표/후보 수는 원인이 아니며, 층만 같거나 저장 위치가 미확인이면 same_spot으로 승격하지 않는다.
- 파서와 같은 커밋에서 정규화 규칙을 `localdata-normalization-v2`로 증가시켰다. 원문 hash·기준일·기존 map version은 유지하며 과거 배치와 기존 NULL 상세 위치는 수정하지 않았다. 실제 개발 DB 보정은 원본·원래 날짜·비위치 업무 값 보존을 검증하는 별도 후속이다.
- 일반 1,548 passed(기준 1,415 + 신규 133), 최종 격리 PostGIS 218 passed(기준 212 + 신규 6, skip 0), ruff check/format·mypy 154 files 통과. 최신 앱 TestClient와 실제 Kakao의 12개 읽기 요청도 모두 200이며 축약/전체 주소의 층·호와 no-store를 확인했다. Claude 구현 재검토는 PASS였고 추가 모호 표현·ETL 충돌·DB 저장 버전 확인을 보강한 후 전체 검사를 다시 통과했다. 이는 기존 실행 서버 재시작·배포 확인이 아니며 실제 LLM은 호출하지 않았다.
- FE·API schema·모델·migration·실제 .env·로컬 Docker 설정은 변경하지 않는다. 한식 원천/상호 불일치·첫 조회 지연·공정위 미등록 브랜드는 분석 보고서의 개별 후속으로 남긴다. 구현 재검토와 PR/CI는 설계 8절에서 관리한다. 기존 개발 DB 보정의 후속 결과는43절이다.

## 43. BE-10/12 기적재 점포 상세 위치 복구 및 검증 (#104)

- 브랜치 `feat#104-floor-location-backfill`(develop `bd952e5`). [Codex 설계·실제 Claude Code 직접 검토/수정·구현 재검토 및 최종 PASS](designs/feat104-floor-location-backfill.md)를 거쳐 전용 `etl.localdata.floor_backfill`을 구현했다. 그림자 스키마 차단·1,001행 실제 청크·건물 키 신뢰 가드를 보강했다.
- 기본 READ ONLY이며 쓰기는 `--write --expected-plan`이 필요하다. 전체 원본·원래 변환 기준일·배치·키·비위치 값·EWKB를 대조하고, source 잠금 후 최신 상태를 재확인해 원천별 원자적으로 복구한다. stores INSERT 없이 sequence·id·브랜드·삭제 표시·원문 hash·D를 보존한다.
- 두 원본 전체 689,440행의 비위치 차이 0을 확인했다. 최종 코드로 전체 백업을 별도 DB에 재복원하고 적용·재실행 no_op·보호 hash·다른 17개 모델 테이블/sequence를 대조한 뒤 실제 개발 DB에 적용했다. 일반음식점 16,941·휴게음식점 7,797, 합계 **24,738행** 복구이며 그중 지원 업종·검토/삭제 제외는 **11,468행**이다. 전체 원천 배치 연결/updated_at은 v2로 갱신했고 과거 v1 배치는 보존했다.
- 일반 **1,564 passed**(신규16), 격리 PostGIS **249 passed**(신규31, skip0), ruff check/format332 files·mypy155 files 통과. 전체 1차의 기존 AI 캐시 가정 실패는 기준 코드에 무관한 MVCC commit을 주입해 재현하고, 동일 키 재사용/다른 키 miss를 구분하도록 검사만 수정했다. 제품 캐시 로직은 바꾸지 않았다.
- 실제 DB 전후 6개 조회 흐름과 원천별 복구 표본의 주소→이력→AI 문맥을 최신 TestClient로 확인했다(88요청 모두200, 실제 Kakao·모의 AI4회·실제 LLM0). 비위치 API data hash·as_of/D·collected_at=null은 같고 새 batch ids·risk 캐시 키·AI 문맥/버전 hash는 바뀌었다. 로컬 BE 재시작 후 실제 HTTP8건도 새 배치와 층·호 전달을 확인했다.
- 개발 DB는 head0011·689,440행을 유지하고 source별 새 v2 활성 배치로 연결된다. 위치 외 보호 값·다른 모델 테이블·과거 배치·브랜드 근거·sequence는 전후 동일하며 재실행은 no_op이다. 기존 명령의 커밋 후 VACUUM/ANALYZE·출처 검증도 통과했다. 백업/갱신 덤프는 저장소 밖에 보관하고 갱신 덤프 재복원본의 19개 모델 테이블 전체 내용·건수/sequence/head 동등성도 확인했다.
- 원본상 결측·모호 값은 그대로다. 다른 팀원 DB 자동 적용·원천 최신화·FE 브라우저/진단서 검증·운영 배포 완료를 뜻하지 않는다. 한식 품질·브랜드 범위·첫 조회 성능은 별도 후속이다. API schema·모델·migration·FE·실제 .env·로컬 Docker 설정은 변경하지 않았다.

## 44. 출처 배치 누적 시 조회 성능 검토 및 개선 (#118)

- #78 재점검의 BE 미해결 항목 "미사용 배치 누적까지 고려한 출처 조회 성능 검토"를 브랜치 `feat#118-source-batch-query-perf`(develop `c255ded`)에서 처리했다. [측정·설계·별도 Claude Code 재검토/MD 직접 수정·결과](designs/feat118-source-batch-query-perf.md)를 따른다.
- 일회용 PostGIS 합성 689,440행 측정에서 과거 배치 1,324개가 쌓여도 VACUUM 후 배치 목록은 1.4~3.2ms였다. 배치 누적 자체는 병목이 아니다. 재적재 직후 비용은 옛 배치 죽은 항목의 첫 확인과, 기존 고아 검사가 VACUUM 전까지 매 요청 지원 점포 전체를 확인하는 구조가 지배했다.
- `current_provenance`의 고아 검사만 같은 의미의 recursive CTE skip scan(`orphan_exists`, 지원 점포의 서로 다른 batch_id/source 키만 `ix_stores_provenance`로 탐색 + `batch_id IS NULL` 별도 검사)으로 바꿨다. 배치 목록·get_history·응답·migration·인덱스·3초 제한·고아 500 정책은 유지한다. 인덱스가 전제이므로 0010 downgrade 시 코드도 되돌려야 한다.
- 일반 1,655·격리 PostGIS 263(신규 동치 12사례·적격성 강화), ruff/format 344·mypy 99 files 통과. 실제 개발 DB READ ONLY에서 결과 동일·고아 검사 37~42ms → 0.1ms·LATERAL 인덱스 순서 스캔·5개 API 응답 digest 동일을 확인했다. 측정은 SLA가 아니다.
- 재적재 직후 첫 확인(합성 콜드 약 1초)은 남으며 #82/#86의 읽기 중지→커밋→VACUUM→확인→재개 절차를 유지한다. #78은 FE 5종·간헐 동시 조회 500 원인·외부 원천 지연 추적을 위해 열어 둔다. Render 배포·FE 변경은 없다.

## 46. FE 연결 후 동시 조회·제외 업종 제보 점검 (#122)

- [설계·실제 Claude Code 직접 검토2회·Codex 판단·실행 결과](designs/feat122-fe-feedback.md)를 따른다. 기존 #120/PR121의 로컬 기본 풀 대기 수정은 별도 작업이며 이 배포에 포함하지 않았다.
- Free 기존 commit/풀1의 동시30요청은28건200·2건500(서버 로그 약15초, SQL timeout 문구0)이었고 풀 대기 초과를 시사했다. 풀2는30건200이나 최초 중앙값16.515→18.500초로 악화되어 원래1로 복구·검증했다. 이어 기존 병합본8958ba7(#118)만 별도 배포했다. 실제 Free 고아 검사1.72~2.83초→0.097~0.166ms·인덱스/의미 동등성을 먼저 확인했다.
- 당시live는dep-dbs37aek1f9s73858g6g(2026-11-14 19:11:42 KST)이며 SQL10초·풀1/overflow0/대기15초·워커1·예산8을 유지했다. 한식·2026-10·반경3종에서 동시5 GET×최초/반복30건 모두200·전체 성공 JSON 동일, 최초/반복 중앙값9.688/6.110초다. ready/health·CORS·AI503·환경값 보존을 확인했다. DB/schema/인덱스·로컬 .env·FE 파일은 변경하지 않았다.
- 저장된 원본 업태와 분류의689,440행 전수 대조는불일치0건이었다. nearby454개와 상호 조사 후보13개도 모두 원본 한식이다. 제보18개 전체 식별자는 미확보이며 이름 규칙으로 집계를 보정하지 않는다. 실제 업종 검증/보정 정책·AI 시연 활성화·FE CI test 추가는 미해결 후속이다.
- 최신 FE dcf8af1 임시 사본의98개 테스트 통과·일반45초/초기60초·대기 안내를 확인했고 CI test 단계 추가는 담당자 전달 문서에 반영했다. BE 일반1655개 통과·기준 commit CI/격리 성공을 확인했다. #122/#78은 미해결 데이터 품질·로그 식별 후속 등을 위해 열어 두고 전체500/절전 복귀 해결로 표시하지 않는다.

## 47. 운영 ready 동시 실패 수정과 후속 근거 확보 (#124)

- [설계·실제 Claude Code 검토·구현 재검토](designs/feat124-readiness-followup.md)를 따른다. 과거unmatched500 두 건은 당시 요청 로그 부재로 경로/원인 확정이 불가하다. 별도로 정상 DB검사 진행 중 동시ready가 즉시500·로그unmatched를 반환하는 현재 코드 결함을 TestClient로 직접 재현했다.
- 실행별RUNNING Future로 한 검사의 실제 결과를 함께 기다리며 진입deadline·HTTP2.5초·SQL750ms·TTL10/1초·추가DB연결1개·실패500/no-store를 유지한다. 닫힘/취소/시간초과/예외/세대전환 때 대기자를 정리하고 추가 검사나 만료 성공으로 우회하지 않는다. 로그는ready 고정 경로와 정해진 사유/시간만 남긴다. 검사 정상과 개별 HTTP성공을 구분한다.
- FE develop4d27ab7의PR52 업태안내·PR53 CI테스트 추가와 Unit test98개 통과를 소스/실행 로그로 확인했다. 중복 요청은 제거하며 FE 파일·CI·배포는 직접 수정하지 않는다.
- 한식13후보의 Kakao 검색13건 중11개 결과·10개 치킨/술집/분식 분류를 확인해 사용자 전용 검토CSV/근거를 확보했다. 제보18개명단과 점포 동일성·과거 적용·버전/재적재/집계 일관성은 미확정이므로 자동 제외0이다. AI도 키 미설정503을 유지한다.
- 일반1,679·격리 PostGIS263(skip0)·정적 검사/CI/CodeQL 통과 뒤 PR125를 병합했고 검증한 실행 코드 동등성을 확인해7d4846c만 수동 배포했다. 현재 live는dep-dbs3norl550s73fbvskg(19:46:35 KST)이다. 모든 환경값·Free·자동 배포off·풀1/SQL10초·DB/schema/인덱스·로컬.env는 보존했다. ready24·업무30건200/본문 동등성·CORS/AI503·검증 구간 HTTP500로그0을 확인했다. 과거 두500과의 동일 원인·모든500 해결은 주장하지 않는다.
