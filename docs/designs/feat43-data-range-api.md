# BE-14 조회 가능한 데이터 월 범위 API

- 작성일: 2026-11-12
- 이슈: [#43](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/43), 브랜치 `feat#43-data-range-api`, develop `61380a8` 기반
- 원본: 로컬 API 명세서 v1.2 8쪽 §4-5와 3쪽 §2-1·2-2를 직접 확인했다. 원본 PDF는 커밋하지 않는다.
- 선행: BE-13 주변 점포 API #41/PR #42 병합 완료. 실제 개발 DB 0004·689,440건, 검증된 전역 기준일 D=2026-11-08을 읽기 전용으로 확인했다.
- D는 검증된 배치들의 DAT_UPDT_PNT 최대 날짜(원천 갱신일)다. 사용자 제공 CSV의 검증일(2026-11-09)이나 미확인 상태인 원천 공표 기준일과 같은 값으로 간주하지 않는다.

## 1. 범위와 입력

`GET /api/meta/data-range`는 FE 달력의 조회 가능 월 범위를 제공한다. 이번 작업은 BE-14만 포함하고 BE-15 `/api/stores/snapshot`, 원천 재적재·브랜드 분류·DB/migration·Docker·로컬 환경 변경은 포함하지 않는다. FE는 직접 수정하지 않고 BE 저장소의 변경 요청 보고서로 전달한다.

| 입력 | 처리 |
|---|---|
| category | 필수 cafe/restaurant |
| sub_category | 선택 쉼표 구분. restaurant는 korean/chinese/japanese/western, cafe는 cafe |

미지원·중복 query key, 빈/중복/업종 불일치 세부 업종은 422 INVALID_PARAM이다. category 누락·잘못된 업종은 다른 입력 오류보다 먼저 422 CATEGORY_REQUIRED다. 좌표·반경·as_of·면적·가맹·unknown 토글은 이 API의 입력이 아니며 전달하면 거절한다. 공통 외피와 오류 meta={}를 유지한다. 원본의 일부 400·504 HTTP 변경과 전체 API meta 일괄 정리는 기존 합의대로 별도 범위다. 요청 원문을 오류·로그에 되울리지 않으며 입력 검증은 DB 연결보다 먼저 수행한다. category/sub_category 검증은 2절의 공통 모델을 쓰므로 오류 코드·우선순위가 현행 nearby와 같아야 한다. 이 문단과 현행 nearby 동작이 다르면 nearby를 바꾸지 않고 구현 전 차이를 이 문서에 기록한다.

## 2. 범위 계산과 재사용

현재 nearby가 사용하는 `current_provenance`, `temporal_cohort`를 공통 모듈로 옮겨 nearby와 data-range가 같은 함수를 호출한다. category/sub_category 입력 검증도 공통 모델로 추출한다. nearby에는 가짜 좌표를 넣어 data-range를 호출하지 않는다. 기존 nearby 요청·응답·조건·반경·면적·가맹 동작은 그대로 유지하고 기존 테스트 전부로 회귀를 확인한다. history의 불완전 이력 보존은 변경하지 않는다.

- 전역 출처 준비: 현재 지원 점포들의 batch/source 연결과 갱신일 품질을 모두 검사한다. 요청 업종의 부분 배치만 골라 D를 만들지 않는다. 검증된 배치들의 전역 최대 갱신일 D를 사용한다. 출처 누락·불일치·미준비·잘못된 기준일은 500 INTERNAL_ERROR이며 정상 빈 범위로 바꾸지 않는다.
- 최소 월 cohort: deleted NULL, 지원 원천/업종/세부 업종, review not true, 한시 영업 true 제외(NULL은 포함), 유효 open/close/date_flag, open>=1960-01-01, open<=D. 원본이 말하는 flag_old_date=false는 현행 ETL의 날짜/플래그 검증에 대응한다. 날짜 플래그(date_flag)가 오류·미확인(unknown)인 행은 제외한다. 이 제외는 날짜 플래그에만 적용하며 is_temporary NULL·면적 0/미상·가맹 미확인은 제외 사유가 아니다(아래 좌표·속성 항목). is_temporary NULL을 포함해도 값을 false로 바꾸지 않는다.
- 폐업일이 없는 closed, 폐업일이 있는 open, 날짜 역전·미래·오류 등 nearby와 같은 제외 조건을 사용한다. 유효한 closed·other도 날짜 구간이 신뢰할 수 있으면 포함한다. 현재 open 상태만으로 최소 월을 계산하지 않는다.
- **최소 월에는 특정 시점 T의 영업 조건을 추가하지 않는다.** 과거에만 존재한 점포도 시점 조회 범위를 제공하기 때문이다. nearby가 effective_date 전에 최소 개업일을 계산하는 동일 cohort를 공유한다.
- 좌표 유무·반경·면적·가맹과 무관하다. 좌표가 없거나 면적 0/가맹 미확인인 신뢰할 수 있는 점포도 최소 월에 기여한다. min_month는 이 cohort의 min(open_date)가 속한 월이다. sub_category 지정 시 그 선택 집합만 사용한다.
- max_month는 D의 월, max_date와 data_updated_at은 D다. 오늘·적재일·CSV 검증일·원천 이력조회 지원 시작일로 대체하지 않는다.
- 원천 Open API의 `/history`(변경 이력 조회, 지원 시작 2026-01-01)는 BE의 `/api/stores/history`와 다르다. 현재 원천 파일도 과거 개업·폐업일을 가진 인허가 행을 제공하므로 원천 `/history` 시작일로 서비스 달력 최소 월을 임의로 자르지 않는다. 작업계획 6절의 "실제 원천 조회 범위"는 여기서 보관된 인허가 행의 검증된 날짜 구간으로 해석한다. 이번 기능은 보관된 인허가 날짜 구간을 재구성하며 과거 현황 전체 관측(수집 전 원천에서 사라진 점포 포함)을 보장하지 않는다.

## 3. 응답과 빈 범위

성공 data의 다섯 키는 항상 존재한다.

| 키 | 타입 | 의미 |
|---|---|---|
| min_month | YYYY-MM 또는 null | 검증된 최소 개업 월. 유효 표본이 없으면 null |
| max_month | YYYY-MM | 전역 D가 속한 월 |
| max_date | ISO date | 최신 월을 선택할 때 실제 사용할 D |
| data_updated_at | ISO date | 원천 갱신일 D |
| collected_at | ISO date 또는 null | 실제 수집 완료일. 현 CSV는 미확인으로 null |

원본 §4-5에는 유효 표본이 없는 경우의 타입이 명시되지 않았다. 기존 작업계획의 "날짜를 만들어내지 않는다"와 nearby의 빈 category 동작을 적용해 **min_month=null, max_month/max_date는 검증된 실제 D**로 반환한다. 1960-01이나 max_month를 최소 월로 채우지 않는다. FE 보고서에는 min_month=null이면 과거 시점 선택·빠른 선택을 비활성화하고 정보 없음으로 표시하도록 요청한다(FE 담당자 반영 대기). nearby는 해당 category에서 기본/최신 월만 정상 0건, 다른 월은 AS_OF_OUT_OF_RANGE로 유지한다. FE 미합의 확장은 보고서에 표시하며 반영 완료로 주장하지 않는다.

공통 meta는 source=[R5,R6], as_of=D, space=seoul, denominator=null(지표 분모가 아님), data_updated_at=D, collected_at=null, collection_reason=source_completion_time_not_recorded, is_demo=false, data_version과 원천별 배치 정보를 포함한다. 범위 규칙 버전은 `store-data-range-valid-license-v1`이다. 이 값을 담을 meta 필드는 nearby의 기존 규칙 버전 표현이 있으면 같은 필드를 쓰고, 없으면 구현 전 필드명을 이 문서와 FE 보고서에 기록한다. 새 meta 구조를 임의로 만들지 않는다. 성공 응답의 캐시 헤더는 nearby의 현행 정책을 따른다. 출처·DataVersion 생성 코드를 두 endpoint에서 공유하되 nearby의 기존 필드 값·배치 순서를 보존한다.

## 4. 일관성·운영

기존 READ ONLY REPEATABLE READ 요청 세션을 사용한다. 한 요청의 출처·D·최소 개업일은 같은 스냅샷이며 연결/DB/SQL 문장 timeout은 상세 없는 500·no-store다. 3초 statement timeout을 전체 요청 SLA로 주장하지 않는다. category/sub_category와 데이터·매핑 버전(stores_batch_ids/map_version)이 같으면 해당 응답 최소 월·max_month와 nearby의 허용 최소·최대 월이 일치해야 한다. endpoint별 rule_version 이름은 다르므로 data_version 객체 전체가 동일해야 한다는 뜻은 아니다. 서로 다른 요청 사이 배치 교체 가능성은 기존 data_version으로 구분하며 cross-request 고정 스냅샷을 추가하지 않는다.

원문·주소·관리번호·키·접속 정보는 출력/로그/PR에 포함하지 않는다. 실제 검증은 집계·월·성공 여부만 남긴다. 개발 DB는 읽기 검증만 하고 파괴적 fixture는 별도 임시 PostGIS 컨테이너에서 실행한다. DB 미연동 또는 필요한 자료 누락 시 실행 큐를 멈추고 사용자에게 요청한다.

## 5. 검증·커밋 계획

1. 이 설계 MD → Claude Read/Edit 직접 검토 → Codex 실제 diff 최종 확인 후 설계 커밋.
2. category/sub_category 스키마·출처·날짜 cohort/meta 공통 추출 및 data-range 서비스·라우터·응답 구현. 기존 nearby 회귀와 신규 입력/응답/통합 테스트를 기능 커밋에 포함한다. DB와 history 로직은 바꾸지 않는다.
3. 테스트는 다음 동작을 실제로 검증한다.
   - 입력 누락/오류 우선순위·세부 업종·중복/미지원 key·원문 비노출·DB 연결 전 거절·OpenAPI.
   - min 월에 기여하는 과거 폐업·유효 other·좌표 없음·0㎡·가맹 unknown·is_temporary NULL과 날짜 오류·date_flag unknown·1960 이전·한시 true·검토/삭제 제외. 1960-01-01 당일 포함, open_date=D 포함·D+1 제외 경계.
   - 전역 D가 업종마다 바뀌지 않음·윤년/연말·sub_category 선택 집합·min 없을 때 null·출처/기준일 준비 실패 500.
   - data-range 최소 월은 nearby에서 허용되고 그 이전 월은 AS_OF_OUT_OF_RANGE. 좌표·반경·속성 조건으로 이 최소 월이 바뀌지 않음. 빈 category의 기본/최신 월 0건과 이전 월 거절.
   - 기존 history/nearby 테스트 전체 통과·세션 read only/timeout·연결 정리·no-store.
4. 실제 DB 원천·개업일/날짜 조건을 독립 SQL 및 CSV 표본으로 대조하고 각 업종/4개 세부 업종·조합을 조회한다. 0004·689,440건·모델/마이그레이션 미변경·읽기 후 데이터 보존을 확인한다. 새 endpoint가 실행하는 SQL과 실제 HTTP 응답을 검증한다. 전역 출처 검사·최소 개업일 쿼리의 실제 DB 실행 계획과 소요 시간을 확인한다. timeout 등 실제 실패가 있으면 범위 내 쿼리 수정을 우선하고, 인덱스·migration 변경이 필요하면 범위 확대 전에 보고한다. 대표 공개 중심점에서 nearby 최소 월 허용/이전 월 거절도 확인한다.
5. `uv run --locked --extra dev` 기준 `ruff check .`, `ruff format --check .`, `mypy app etl migrations`(작업계획 4절 `mypy app migrations`의 상위 범위), 일반 pytest·격리 PostGIS integration·실제 비밀값 검사·diff check 후 BE 계약(CLAUDE.md의 BE 계약 절 포함)/README/작업계획/FE 보고서 커밋. 코드 최종 상태로 검사하고, 결과 문구만 갱신한 뒤 같은 테스트를 반복하지 않는다. 이후 코드 변경·실패·미해결 우려가 있으면 해당 검사를 다시 수행한다. FE 범위 정정에 따라 FE CLAUDE.md 완료 확인은 미체크.
6. PR 제목은 최신 사용자 요청의 **`feat: 조회 가능한 데이터 월 범위 API 구현`** 형식을 사용한다. 커밋 형식 `타입(영역): 한국어 요약`은 기존 기준을 유지한다. PR 본문에서 실제 이슈 #43을 연결한다. 지정 PR 본문·CI 확인 후 develop 일반 Squash 병합, 이슈 종료·로컬 최신화까지 진행한다. GitHub 본인 PR 승인 제한·보호 규칙은 우회하지 않는다.

## 6. 사전 읽기 검증

| 업종/세부 업종 | 유효 cohort 행 수 | 최소 월 |
|---|---|---|
| restaurant 전체 | 315,112 | 1960-05 |
| korean | 223,321 | 1960-05 |
| chinese | 17,456 | 1962-03 |
| japanese | 22,051 | 1966-08 |
| western | 52,284 | 1965-10 |
| cafe | 40,651 | 1967-10 |

D=2026-11-08. 현 nearby 공통 후보 함수로 계산한 사전 결과이며 구현 후 독립 SQL·API로 다시 대조한다. 과거 특정 월의 실제 전체 점포 수를 검증한 것은 아니다.

## 7. 검토 기록

Codex: 원본 §4-5의 sub_category와 max_date를 확인했다. 기존 FE는 category만 전송하고 min_month 필수 string·max_date 없음으로 가정하므로 FE 보고서에 nullable 최소 월·세부 업종 전달·최신 기준일 표시를 요청한다. 현재 자료·DB가 준비되어 추가 인증키 없이 BE 구현이 가능하다.

### Claude Code 검토 (2026-11-12)

검토 범위는 이 MD 한 파일이며 Read/Edit만 사용했다. 코드·DB·다른 문서·Git·외부 서비스는 확인하거나 수정하지 않았다. 아래 판단의 근거는 이 문서의 원본 대조 기록과 작업계획·CLAUDE.md의 현행 정책뿐이다.

직접 수정한 사항과 이유:

1. **D의 의미 명시(머리말)**: 작업계획에서 CSV는 "2026-11-09 검증, 원천 기준일 미확인"이다. D=2026-11-08을 원천 공표 기준일이나 CSV 검증일로 오해하지 않도록 이력 API 계약과 같은 "검증된 DAT_UPDT_PNT 최대 날짜"로 정의했다.
2. **unknown 제외 범위 모순 해소(2절)**: "unknown 플래그는 제외한다"와 "면적 0/가맹 미확인 점포도 기여한다"가 충돌할 수 있었다. 제외 대상을 date_flag 오류·미확인으로 한정하고, is_temporary NULL 포함이 false 변환이 아님을 적었다(작업계획 5절).
3. **원천 `/history` 표현 정리(2절)**: BE `/api/stores/history`와 혼동될 수 있어 원천 Open API의 변경 이력 조회로 명시했다. 작업계획 6절 "실제 원천 조회 범위"를 이 설계가 어떻게 해석하는지도 적었다.
4. **입력 검증 일관성(1절)**: 공통 모델을 추출하면서 nearby의 기존 오류 코드·우선순위가 바뀌지 않아야 한다. 문서의 CATEGORY_REQUIRED 우선 규칙이 현행 nearby와 다르면 nearby를 유지하고 차이를 기록하도록 했다.
5. **FE 관련 표현(3절)**: "FE는 ~해야 한다"를 보고서를 통한 요청과 담당자 반영 대기로 바꿨다. 2026-11-12 FE 범위 정정 지시에 맞춘 것이다.
6. **meta 위치(3절)**: 범위 규칙 버전 문자열이 어느 필드에 들어가는지 정해지지 않았다. 작업계획 6절의 "필드 구조를 임의로 만들지 않는다"에 따라 nearby의 기존 필드를 재사용하고, 없으면 구현 전에 기록하도록 했다. 성공 응답 캐시 정책도 nearby를 따르도록 적었다.
7. **일관성 조건(4절)**: 최소 월만이 아니라 max_month도 nearby의 허용 범위와 같아야 하며, data_version이 같은 경우로 한정했다.
8. **검증 보강(5절)**: 날짜 경계(1960-01-01 포함, open_date=D 포함·D+1 제외), date_flag unknown, 가맹 unknown과 is_temporary NULL 사례를 추가했다. 실제 DB 실행 계획·소요 시간을 확인하고, timeout에 근접하면 migration 없이 중단해 보고하도록 했다. 이번 범위에서 DB/migration 변경은 제외되어 있다. 검사 명령에 `uv run --locked --extra dev`를 붙였고, CLAUDE.md BE 계약 절 갱신, 문서 커밋 후 재검사, PR 본문의 #43 연결을 추가했다.

확인한 정합 사항: 6절 표의 세부 업종 합계(223,321+17,456+22,051+52,284)는 restaurant 전체 315,112와 일치한다. restaurant 최소 월 1960-05도 korean 최소 월과 일치한다. PR 제목 `feat: 한국어 설명`, develop 자동 Squash 병합, 본인 승인 제한 비우회, FE 미수정은 사용자 지시 및 CLAUDE.md와 일치한다. 새 승인 절차는 추가하지 않았다.

보류 사항:

- **과거 월 완전성**: 수집 전에 원천에서 사라진 점포는 재구성할 수 없다. 그래서 min_month 이후 과거 월의 점포 수가 과소일 수 있다. 응답 meta로 이를 표시할지와 FE 안내 문구는 정하지 않았으며 FE 보고서의 확인 대기 항목으로 둔다.
- **min_month=null 및 max_date·sub_category 확장**: 원본 §4-5에 명시되지 않았거나 기존 FE 가정과 다른 부분이다. FE 담당자 합의 전에는 반영 완료로 표시하지 않는다.
- **입력 오류 우선순위**: 현행 nearby 구현과 1절 규칙이 같은지는 이 검토에서 확인하지 않았다. 구현 단계에서 기존 테스트로 확인한다.
- **규칙 버전 meta 필드명**: 구현 전 확정이 필요하다(위 6번).
- **원본 400·504 및 전체 meta 일괄 정리**: 기존 합의대로 별도 범위로 남긴다.

### Codex 최종 점검

Claude의 실제 MD diff를 원본 §4-5·현행 코드와 대조했다. 날짜 unknown은 비어 있지 않은 date_flag의 오류/미지원 토큰이며 NULL/빈 문자열은 오류 없음으로 유지한다. meta 규칙 버전은 기존 `meta.data_version.rule_version`에 기록한다. endpoint별 rule_version이 다르므로 cross-endpoint 일치 검사는 배치 ID·매핑 버전을 비교하도록 정정했다. 주변 입력 오류 우선순위는 현행 코드와 일치한다. Claude의 날짜 경계·원천과 BE history 구분·수집일 구분은 채택한다. 측정만으로 새 중단/승인 절차를 추가하거나 문서 변경 후 같은 테스트를 반복하는 제안은 채택하지 않고, 실제 실패는 범위 내 수정·재검증한다. nullable 최소 월·과거 데이터 완전성의 FE 표시는 요청 보고서로 넘기며 반영 완료로 표시하지 않는다.
