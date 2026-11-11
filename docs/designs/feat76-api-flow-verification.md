# BE API 연속 조회 통합 검증 (#76)

- 작성일: 2026-11-12
- 기준: develop `de756f0` / PR75 병합·이슈74 종료 확인
- 브랜치: `feat#76-api-flow-verification`
- 상태: Codex 설계 → Claude 이 MD만 Read/Edit → Codex diff 검토·구현/검증

## 1. 다음 작업 선정

BE-34까지 구현한 뒤 작업계획11절의 BE API 연속 조회를 검증한다. 기존124개 PostGIS 검사는 대부분 endpoint/서비스별이다. 주소검색 결과에서 시작해 같은 조건으로 이력·월범위·주변/과거·활동/Risk·AI를 연속 조회하는 회귀 검사가 없고, 해당 검사가 CI에서 실제 실행된다는 조건도 없다.

브랜드57은 사용자가 미신청/승인대기로 답한 상태를 유지하며 재인증하지 않는다. 공식 지표·조건부 수치는 경계/기간/집계 의미 검증 대기여서 임시 수치를 만들지 않는다. FE 직접 변경 금지·기존 FE 요청서 담당자 대기는 유지한다. 이번 검증은 BE 내부 연결이며 FE 브라우저/화면·외부 원본계약 합의·실제 LLM 안전성·운영부하 완료와 구분한다. 기존 설계36/41/43/45/60/64/66/68/74와 현행 코드·작업계획의 모집단 차이를 따른다. PDF 원본의 새 필드/계산 변경은 계획하지 않는다.

## 2. 검증 범위와 불변식

합성 원천 DTO를 기존 snapshot→run_import→정제/주소정규화/upsert/provenance로 적재하고 일회용 PostgreSQL17/PostGIS에서 API를 호출한다. 실제 통합 target 검증으로 생성한 DB만 쓴다. runner의 로컬 dev guard를 바꾸는 대신 테스트 fixture 안에서 해당 임시 DB에만 engine/guard를 주입하며 application code의 guard는 그대로 둔다. 지오코딩은 실제 KakaoLocalService+httpx.MockTransport, AI는 실제 준비/후보검증/조립+모의 공급자를 사용한다. 공개 수집 API·카카오·LLM 네트워크를 CI에서 호출하지 않는다.

1. `/api/health`200은 프로세스 상태만 뜻한다. `/openapi.json`·`/docs`에10개 API가 등록됐는지 확인한다.
2. 합성 도로명/지번 주소가 같은 building_key로 연결되고 상세위치는 입력에서만 추출되는지 확인한다. geocode의 검증 좌표·건물키/층호를 각 API에 그대로 전달한다.
3. 이력은 같은 건물의 **지원 업종 전체**이며 날짜 결측도 보존한다. category=cafe라고 restaurant를 제거하지 않는다. source+license_no 식별·same_spot/same_building/unverified를 확인하며 이력 수를 반경 점포 수와 같다고 강제하지 않는다.
4. data-range는 좌표/면적/가맹 필터 없는 업종별 시간 코호트다. 그 max_month를 nearby/snapshot/activity/Risk/AI의 같은 as_of로 쓴다. 최신 월 T는 D이며 과거 월은 월말이다.
5. 같은 조건의 nearby 식별 집합과 snapshot 식별 집합·순서가 같고 N=still_open+closed_since+other=len(stores)=nearby.count다. 날짜/면적/가맹/좌표 결측 및 과거 최신 상태를 구분한다. Risk competitor_count는 그 nearby.count이며, activity.by_sub_category의 open_count 합계도 같다. activity의 전체 cohort/개폐업은 폐업 이력을 보존하므로 nearby.count와 임의로 같게 만들지 않는다.
6. 최신 D·T·stores batch IDs·수집일null·출처는 같은 요청들의 계약에 맞게 비교한다. API 사이 독립 트랜잭션 동안 writer가 없다면 일치하지만 운영 중 여러 HTTP 응답의 원자적 snapshot을 보장하는 규칙은 만들지 않는다. raw history는 의도적으로 date cohort와 달라 동일 최소월/집계 요구를 붙이지 않는다.
7. AI는 query-only 조건으로 서버 재계산한다. 모의 공급자에 raw주소/좌표/건물키/점포ID·batchUUID가 전달되지 않고, DB 세션이 먼저 닫히며, 표시한 모든 수치가 해당 Risk와 연결되는지 확인한다. warm에서 공급자1회/2요청·선택만재사용·현재조립시각/요청별regenerated=false를 확인한다.
8. 원천 재적재는 중복을 늘리지 않고 날짜/상태 변경 후 nearby/snapshot/activity/Risk와 AI cache가 같이 새 자료를 본다. 배치만 바뀌어 결과가 같은 경우에도 데이터 버전이 바뀌고, 입력/원천/AI 실패는 성공 캐시/임시0으로 숨기지 않는다.
9. 실패 분리: 원천없는 DB에서 health·주소검색은 성공하나 DB API는500·AI공급자0회, 검색없음/서울외/외부실패는 공통오류·no-store이며 후속 값은 생성하지 않는다. AI 검증 실패/공급자 실패 뒤 Risk/주변/지원링크는 정상이다. 모든 실패를 하나의 try/except로 정상0건 처리하지 않는다.
10. 빈 반경과 category/subcategory·면적0→정보없음·unknown토글·과거월을 포함한다. 빈결과200과 원천미준비500·범위오류422를 구분한다. LQ/자체위험점수/성공확률·임의공식값은 추가하지 않는다.

## 3. 합성 자료·구현 계획

- tests/integration/analysis_flow_helpers.py: 명시적 합성 snapshot/두원천 자료, DTO/HTTP 지오코딩 응답, 모의 AI 공급자. 현재 normalizer EPSG5174 fixture 좌표를 같은 합성 HTTP 응답에 연결하며 실제 주소 후보라는 주장을 하지 않는다. 원천ID 충돌·미확인/폐업/좌표없음·면적0/알려진면적·다른지원업종을 섞는다. 임시 snapshot은 pytest tmp_path에만 쓰고 raw값을 출력하지 않는다.
- tests/integration/test_analysis_flow.py: 최소6개의 의미있는 연속조회/실패/재적재 시나리오를 구현한다. API 응답을 다음 입력으로 사용하며 고정 synthetic 기대값·기존 의미 불변식으로 검증한다. endpoint별 구현 로직을 그대로 다시 복제하는 테스트는 피한다.
- .github/workflows/ci.yml: 기존 integration XML no-skip 검사에 analysis_flow의 실행수 최소6 조건을 추가한다. 기존 ETL/migration 검사를 약화하지 않는다.
- BE 문서: docs/be-api-verification.md에 재현명령·실제 결과/검증범위·FE 담당자 체크/대기와 기존 요청서 링크를 기록하고 README/CLAUDE.md/작업계획에 연결한다. API schema가 그대로라면 새 FE계약/타입을 발명하지 않고 기존 요청서 내용을 바꾸지 않는다. 실제 계약 수정이 필요하면 먼저 이 MD에 근거·FE 요청서 대상을 정리한다.
- 커밋1 `test(api): 주소 검색부터 AI까지 연속 조회 검증`(fixture/통합검사/CI guard·실제 발견한 관련 오류는 별도 fix 커밋), 커밋2 `docs(be): API 통합 검증과 남은 작업 정리`.

## 4. 실제 개발 환경 검증

현재 .env의 DB·Kakao 키는 존재함만 확인했고 값을 출력하지 않았다. 실제 검증은 기존 local target 검증/READ ONLY 세션과 같은 앱 설정으로 수행한다. 지오코딩은 두 개의 공개 주소를 실제 카카오로 검색해 결과를 후속 입력으로 사용한다. 주소/좌표/건물키/점포명·실제응답 raw는 저장/보고하지 않고 case번호·성공/집계/불변식 결과만 남긴다. 실제 키/자료/권한이 없거나 인증이 실패하면 해당 실제 검증을 중단하고 사용자에게 요청한다.

실제 AI는 호출하지 않고 모의 공급자만 주입해 provider_calls와 서버 계산/검증을 확인한다. 실제 모델 성공/FE 브라우저 연결/수집 최신성을 검증한 것으로 보고하지 않는다. 가능하면 로컬 uvicorn HTTP로 `/docs`·OpenAPI/경로도 확인하며 로그는 기존 안전 설정을 유지한다. 실제 DB는 migration/원천적재/상태변경 없이 head0009·모델차이0·14테이블 전체행/geometry hash 보존을 확인한다. 검증용 hash 쿼리만 세션 제한120초로 쓰며 실제 .env·환경설정/로컬 Docker 기록은 변경/커밋하지 않는다.

## 5. 완료 조건·제외

새 연결 검사가 실제 격리 PostGIS/CI에서 실행되고 일반·전체integration/ruff/format/mypy·실제 .env값/변형검사·FE변경0이 통과해야 PR을 작성한다. 위 실제 인증/DB 검증을 못하면 완료로 표시하지 않는다. 기존 API가 깨지면 수정·관련회귀 후 검사한다. 지정4체크문구/한국어제목 PR을 develop에 생성하고 CI/CodeQL 모두 성공 시 정상Squash 병합·이슈종료·로컬develop ff-only를 수행한다.

DB모델/migration·새 의존성·실제 .env/Docker·FE코드/문서/이슈/PR 변경은 계획하지 않는다. 운영부하/인증·분산한도/원본전체관측·조건부활성화·브랜드57·로그30일보관삭제·AI추가문맥·FE통합은 완료로 주장하지 않는다.

## 6. Claude 검토 요청

**이 MD만 Read/Edit**한다. 코드/DB/.env/외부/다른문서/Git 접근은 금지한다. §7에 검토범위 한계, 모집단/날짜/분모·cross-source·다중 HTTP 일관성·fixture 순환검증·외부mock범위·로그/개인정보·실제검증·CI guard의 누락을 직접 기록한다. 본문 수정이 필요하면 이유를 §7에 남긴다. Codex가 실제 코드/검사결과와 대조해 최종 선택한다.

## 7. Claude 검토 결과 (2026-11-12)

### 7.1 검토 범위와 한계

- 이 MD 한 파일만 읽고 이 절만 추가했다. §1~§6 본문은 바꾸지 않았다. 아래 지적은 모두 **코드로 확인하지 않은 가정에 대한 위험 표시**이므로 Codex가 실제 코드와 대조해 채택 여부를 정한다.
- 코드·DB·.env·다른 설계(36/41/43/45/60/64/66/68/74)·CI 파일·Git에는 접근하지 않았다. 따라서 9개 API 이름, data-range/nearby/snapshot/activity/Risk의 실제 파라미터·기본값, Risk·AI 캐시 저장 위치(메모리/DB), 운영 로그 sink, 기존 conftest/runner guard 구조, 기존 CI XML 검사 방식은 검증하지 못했다.
- 테스트를 실행하지 않았고, 실제 카카오·DB 검증도 하지 않았다.

### 7.2 중요한 오류·누락 (우선순위 순)

1. **[높음] §4 실제 DB "상태변경 없음/hash 보존"과 Risk·AI 캐시·로그 쓰기 충돌 가능성.** PR75 캐시나 542bde7 운영 로그가 DB 테이블에 쓰면 실제 API 호출 자체가 14테이블 hash를 바꾸거나, READ ONLY 세션에서는 500이 난다. 캐시·로그 저장 위치를 먼저 확인하고, DB에 쓰는 구조라면 (a) 해당 테이블을 hash 대상에서 빼는 근거를 기록하거나 (b) 실제 DB 검증을 GET 조회 API로 제한해야 한다. "READ ONLY 세션"이 hash 쿼리 세션만 뜻하는지 API 앱 세션까지 뜻하는지도 본문에 명시해야 한다.
2. **[높음] 통합 fixture가 실제 .env DB로 연결되는 경로 차단.** §2는 "임시 DB에만 engine/guard 주입"이라고 하지만, settings가 .env의 DATABASE_URL을 먼저 읽는 import 순서나 dependency override가 빠진 경로(예: 백그라운드/캐시/로그 경로의 별도 engine 생성)가 있으면 합성 자료가 로컬 실제 DB에 들어갈 수 있다. fixture 시작 시 "연결된 DB 이름이 이번 실행에서 만든 임시 이름인지"를 단언하고, 앱 전체에서 engine 생성 지점이 하나인지 확인하며, teardown에서 주입을 원상 복구하는 것을 완료 조건에 넣어야 한다.
3. **[높음] 모집단 등식의 파라미터 정합.** §2.5의 `Risk.competitor_count = nearby.count`, `Σ activity.by_sub_category.open_count = nearby.count`는 아래 조건이 모두 같아야 성립한다. 하나라도 다르면 테스트가 실패하거나, 테스트를 통과시키려고 코드를 억지로 맞추게 된다.
   - 반경(Risk 기본 반경 vs nearby 요청 반경), category/subcategory 수준(Risk가 subcategory를 받지 않으면 subcategory 요청과 비교 불가), unknown 토글(Risk/activity가 토글을 받는지, 받지 않으면 내부 기본값이 무엇인지), as_of.
   - activity.by_sub_category에 subcategory 결측/기타 버킷이 포함되는지 여부. 버킷이 빠지면 합계가 작아지는 것이 정상일 수 있다.
   - 권장: 각 등식을 "Risk/activity가 실제로 받는 파라미터 조합"에서만 단언하고, 등식이 성립하지 않는 조합은 기존 설계의 모집단 차이로 명시해 별도 기대값으로 고정한다.
4. **[높음] §2.4 날짜 정의 누락.** D가 무엇인지(원천 기준일? 최신 배치 수집일? 서버 시각?) 본문에 정의가 없다. 또 data-range가 업종별이면 max_month는 **요청 category의 max_month**여야 하며 전체 최대월을 쓰면 안 된다. category마다 최신월이 다른 합성 자료를 넣어 이를 검증해야 한다. 서버 시각(`today`)에 의존하는 기본값이 있으면 clock을 주입하거나 고정해야 한다. 그렇지 않으면 2026-11 이후 실행에서 테스트가 깨지거나, 아무 문제 없이 통과해도 의미가 없게 된다.
5. **[중간] 날짜 경계 fixture 누락.** 다음 경계는 손으로 계산한 기대값으로 고정해야 한다. open_date = T, close_date = T, close_date = T+1일, 과거월의 월말이 2월(윤년 포함)·30일인 달, open_date 결측+unknown 토글 on/off, close_date만 있고 open_date가 없는 행. 이런 경계가 없으면 "과거 월은 월말" 규칙의 off-by-one 오류를 잡지 못한다.
6. **[중간] 식별·순서 비교의 결정성.** 집합 비교 키는 `(source, license_no)`이어야 한다. 두 원천에서 license_no가 같은 행이 **병합되지 않는지**(§3의 "원천ID 충돌"), 그리고 같은 물리 점포가 두 원천에 있을 때의 기존 처리(중복 계수 여부)를 기대값으로 고정해야 한다. 순서 비교는 거리가 같은 점포 2개 이상을 넣어 tie-breaker를 검증해야 의미가 있다. 동률이 없으면 순서 단언은 사실상 아무것도 검증하지 않는다.
7. **[중간] fixture 순환검증 위험.** 기대 building_key·좌표·카운트를 production normalizer/서비스 함수로 계산하면 "같은 코드끼리 일치"만 확인하게 된다. 기대값은 리터럴로 적고, mock 카카오 응답은 카카오 응답 형태의 JSON 리터럴로 둔다. building_key는 ETL 정규화 경로와 KakaoLocalService 경로가 각각 독립적으로 만들어 같아지는지 확인해야 한다. 최소 1개의 음성 대조(예: as_of를 다음 달로 바꾸면 집합이 달라짐, 지번만 다른 이웃 건물은 history에 들어오지 않음)를 넣어 단언이 실제로 무언가를 구분하는지 보인다.
8. **[중간] 개인정보 차단 검사의 범위 부족.** §2.7의 금지 목록에 **점포명·license_no·상세위치(층/호)·EPSG5174 원좌표**가 빠져 있다. 좌표는 반올림/문자열/지수 표기 등으로 형태가 바뀌어 substring 검사가 새어 나갈 수 있다. 권장:
   - fixture에 고유 canary 값(예: 점포명 `CANARY_STORE_A1`, 상세위치 `CANARY-101호`, 소수점 자리가 특이한 좌표)을 넣는다.
   - (a) 모의 공급자 payload 전체 직렬화, (b) 흐름 전체의 caplog/stdout 로그, (c) 모든 **오류 응답 body**에 canary가 없는지 확인한다.
   - 특히 FastAPI/pydantic v2의 기본 422 응답은 `input`에 원 입력값(주소)을 그대로 돌려주므로, 공통 오류 형식이 이를 실제로 막는지 확인해야 한다.
   - 주소가 포함된 geocode 성공 응답에도 no-store가 필요한지 기존 설계와 대조한다.
9. **[중간] 캐시 무효화·실패 검증의 세부.**
   - §2.8에서 재적재 후 AI·Risk 캐시가 새 버전을 보는지는 응답값만이 아니라 **provider_calls 증가**로 확인해야 한다. 결과가 같은 재적재에서도 마찬가지다.
   - 실패한/중단된 재적재(트랜잭션 롤백)가 데이터 버전을 바꾸지 않는지도 확인해야 한다.
   - §2.7 "warm에서 공급자1회/2요청"은 순차 요청 기준임을 명시해야 한다. 동시 cold 요청의 중복 호출은 이번 범위가 아니라고 적는다.
   - "선택만재사용"이라는 표현이 모호하므로 무엇을 재사용하고 무엇을 새로 조립하는지 풀어 쓴다.
10. **[중간] CI guard 실효성.** "analysis_flow 실행수 ≥6"은 다음을 보장해야 한다.
    - JUnit XML에서 classname/file이 test_analysis_flow인 testcase 중 skipped/xfail/error가 아닌 **통과 건수**를 센다.
    - parametrize로 숫자만 부풀리지 않도록 **고유 함수명 6개 이상** 또는 필수 테스트 이름 목록으로 확인한다.
    - PostGIS 서비스가 붙은 job에서 실행되는지, DB 미가용 시 conftest가 skip하지 않고 fail하는지, marker deselect로 빠지지 않는지 확인한다.
11. **[낮음] 외부 mock 범위.** 카카오 실패 케이스에 timeout, 401/429, 형식이 깨진 JSON, `documents` 빈 배열/필드 누락을 포함한다. 단, MockTransport는 현재 응답 schema 가정만 검증하며, 실제 카카오 응답 계약을 보장하지 않는다는 점을 문서에 남긴다.
12. **[낮음] §4 실제 검증의 공허 통과.** 실제 카카오 주소 2건의 건물이 로컬 DB에 없으면 history/nearby가 0건이 되어 불변식이 자명하게 통과한다. 결과 보고에 "nearby.count > 0인 case가 최소 1건"을 조건으로 넣고, 0건이면 검증 미완료로 보고한다. 실제 주소를 외부(카카오)로 보내는 것은 사용자가 고른 공개 주소에 한정하며, 그 주소 자체는 문서·로그·PR에 남기지 않는다(본문 방침 유지).

### 7.3 권장 본문 보완 (Codex 판단용, 이번에 본문은 수정하지 않음)

- §2.4에 D의 정의와 "요청 category의 max_month" 문구를 추가한다.
- §2.5의 두 등식에 "동일 반경·category 수준·unknown 토글·as_of일 때" 조건을 추가하고, 성립하지 않는 조합은 모집단 차이로 열거한다.
- §2.7 금지 목록에 점포명·license_no·상세위치·원좌표를 추가하고, 로그·오류 body canary 검사를 명시한다.
- §3 CI 항목을 "통과 상태 고유 테스트 함수 ≥6, skip/xfail 제외, DB 미가용 시 fail"로 구체화한다.
- §4에 캐시·로그 저장 위치 확인과 hash 대상 처리 방침, "nearby>0 case 최소 1건" 조건을 추가한다.

### 7.4 판단 보류 사항

- Risk의 실제 반경/category 수준, activity의 공간 단위(반경인지 행정구역인지), 캐시 저장소는 코드 확인 전에는 등식 채택 여부를 단정할 수 없다. activity가 반경 기반이 아니라면 §2.5의 activity 등식 자체를 삭제해야 한다.
- 원천 미준비 시 500을 반환하는 것은 기존 설계 결정으로 보고 재검토하지 않았다.

## 8. Codex 최종 결정

Claude의 실제 MD diff를 읽었다. 실제 코드 대조 결과 캐시는 앱별 메모리, 로그는 stderr이고 DB에 기록하지 않는다. 모든 DB API/AI 준비 세션은 기존 READ ONLY REPEATABLE READ다. 실제 검증의 별도 hash 세션만 READ ONLY로 만드는 방식이 아니다. 14테이블 hash 대상은 줄이지 않는다. integration fixture는 Settings(_env_file=None)와 fixture가 생성한 database_name/current_database 일치·engine 동일 객체를 확인하고, guard override는 pytest monkeypatch로 해당 실행기/임시 engine에만 적용한다.

§7.2.4의 "category별 최신월" 권고는 채택하지 않는다. 현재 current_provenance는 지원 업종 전체의 검증된 배치 DAT_UPDT_PNT 최대 날짜 **D**를 사용하고, category/subcategory는 최소월 후보만 바꾼다(기존43/41 계약). 카페/음식점의 source 갱신일이 다른 합성자료로 이 **전역 D** 동작을 검증한다. 오늘/서버시각은 날짜 기준으로 쓰지 않는다. Risk·activity는 NearbyQuery를 상속하고 같은 cohort/attribute_filters/geography를 사용하므로 동일 입력의 competitor_count·active 합계 등식은 채택한다. include만 API별 이름으로 분리하며 history/월범위 모집단 차이는 유지한다.

고정 합성 기대값·서로 다른 지번의 음성대조·동률좌표의 식별/순서·두원천 같은ID·면적0/결측·윤년/30일 월말을 검증한다. 최소6개 **고유 테스트 함수명**과 필수 시나리오명이 CI에 존재해야 하며 기존 no-skip/error 검사와 함께 적용한다. 일반 endpoint의 세부 파서/HTTP 오류는 기존 검사도 유지하고 새 연속흐름에 필요한 실패만 더한다.

모의 공급자는 원문 주소/점포명/관리번호/층호/원좌표/정확 WGS84/배치UUID가 없음을 확인한다. 성공 주소 응답에는 계약상 원문이 있으므로 로그·오류 body 검사와 구분한다. 로그/실패 canary 확인·순차2요청 공급자1회·변경/동일내용 재적재의 새 버전과 호출증가·실패한 적재의 값/버전 보존을 채택한다. 동시 cold 합치기/취소는 기존74 검증 범위이며 이 작업에서 완료를 확대하지 않는다. 실제 환경은 공개 주소/기존키로 확인하고 nearby>0 case를 최소1개 요구한다. 실제 외부 인증 실패 시 중단/요청 원칙도 유지한다.
