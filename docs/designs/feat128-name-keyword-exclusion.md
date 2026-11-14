# 음식점 이름 키워드 제외 정책 (#128)

- 작성일: 2026-11-14 (Asia/Seoul), 기준 develop9dd0348, 브랜치feat#128-name-filter.
- 사용자 결정: 그림의 **B안, BE에서 이름 키워드로 제외**를 선택했다. 카페 M 같은 실제 음식점 오탐 가능성을 포함한 방식이며 이전 #122/#124의 이름 제외 보류는 이번 명시적 요청으로 대체한다. 추가 승인이나18개 전체 명단을 기다리지 않는다.
- FE 코드·설정·문서·이슈/PR은 변경하지 않는다. 원본 데이터/로컬.env·모델/head0011을 보존한다. 별도 #127 AI 활성화 작업을 덮어쓰거나 끄지 않고 배포 직전 실제 환경값을 보존한다.

## 1. 정책 v1

대상은 category=restaurant의 korean/chinese/japanese/western이다. 정상 category=cafe에는 적용하지 않는다. name=null/빈 문자열은 보존한다. 이름에 다음 리터럴 문자열이 부분 일치하면 제외하며 영문 대소문자는 구분하지 않는다.

`치킨, 통닭, 호프, 주점, 포차, 맥주, 분식, 김밥, 떡볶, 피자, 카페, 커피, cafe, coffee, 베이커리, 제과, 빵집, bakery`

이는 실제 업종 확인이나 브랜드 판정이 아닌 서비스의 이름 휴리스틱이다. 카페 M은 원본 한식이어도 제외하고, 정상 카페의 커피/카페 이름은 유지한다. 키워드 없는 브랜드·띄어 쓴 변형·다른 표기는 놓칠 수 있고 실제 음식점도 제외될 수 있다. 임의 상호 예외·브랜드 사전·메뉴 추정은 추가하지 않는다. 내부 공백/Unicode를 임의 정규화하지 않고 PostgreSQL의 대소문자 비구분 리터럴 정규식 부분 일치를 사용한다.

규칙은 코드의 고정18개 키워드와 `store-name-keywords-v1`로 관리한다. 사용자 요청에서 정규식/SQL/키워드 목록을 받지 않는다. 목록/매칭/적용범위 변경은 새 버전으로 검토·배포한다. 요청/as_of와 무관하게 현재 원본 상호를 쓰는 서비스 규칙이며 과거 실제 업종을 복원하는 기능으로 표시하지 않는다.

기존 명동길14·500m·최신·한식454개 응답의 파일을 읽어 위 규칙으로 투영한 결과20개 이름이 걸렸다. 기존13개 후보와 카페 M/커피 이름 등이 포함된다. 이 값은 사전 진단이며 새 BE/현재 DB에서 실행한 검증 결과는 아니다. 사용자 제보18개와 동일한 목록/건수라고 주장하지 않는다.

## 2. 원천 자격과 분석 모집단 분리

`SOURCE_SUPPORTED_STORES`는 기존deleted/source/review/category/sub_category 조건 그대로다. 배치 목록·전역 기준일D·고아 검사·브랜드 근거 적재/비교는 이를 사용한다. 이름 제외 때문에 최신 배치가 빠지거나 D가 과거로 이동하거나 원천 오류가 가려지지 않는다.

`SUPPORTED_STORES`는 원천 자격에 이름 정책을 더한 분석 모집단이다. history의 점포 목록·temporal_cohort를 쓰는 nearby/snapshot/data-range/activity/risk·AI의 서버 재계산/이력 위치 검사는 이 공통 조건을 따른다. history도 지원 업종 전체 이력을 유지하되 이름 정책에 걸린 음식점은 제외한다. 표시 목록만 숨기고 집계/서울비교에 남기는 구현은 하지 않는다.

원본 name/bzstat_nm/category/sub_category/review/batch/updated_at·원본 파일과 브랜드 테이블은 UPDATE하지 않는다. 재적재·상호 변경은 기존 적재 규칙대로 보존되고 조회 때 현재 이름에 정책이 적용된다. ETL/배치의 원래 mapping version은 바꾸지 않는다.

## 3. 메타·캐시·AI 일관성

성공한 점포/분석 API의 `meta.name_exclusion`에 version/basis/applies_to/match/keywords를 명시하고 `data_version.name_exclusion_version=store-name-keywords-v1`을 추가한다. 오류meta={}·공통 외피·data 구조/입력은 유지한다. 기존 알고리즘 rule_version은 수식이 그대로이므로 보존하고 별도 정책 버전으로 구분한다. source/date/batch metadata는 원천 자격 기준이다.

Risk 캐시 키는 정책 버전을 포함한다. AI의 엄격한 내부 _DataVersion은 현재 정책 버전을 요구하고 risk/activity/history의 버전 일치를 확인한다. 기존 data_version_hash와 context_hash/AI 캐시가 새 정책을 반영하도록 한다. 원본 이름·점포키·주소나 키워드별 점포 목록을 LLM에 새로 전송하지 않는다. 프롬프트에 이름 추정이 실제 업종 증명이라는 주장을 넣지 않는다.

## 4. Free 성능과 운영 인덱스

원천/provenance 쿼리는 원래 predicate/ix_stores_provenance를 유지하므로 #118 skip scan의 인덱스 전제를 깨지 않는다. 공간 조회는 후보의 실제 이름을 읽지만 서울 전체 Risk는 기존ops_free_risk_cover에 name이 없어 heap scan/SQL10초 회귀 위험이 있다.

후보는 기존 key/include를 유지하고 **고정 이름 predicate를 추가한 별도 부분 인덱스** `ops_free_risk_name_v1`이다. 정책 상수는 신뢰한 SQL literal로 렌더링해 prepared generic plan에서도 부분 predicate가 일치하도록 하며 사용자 문자열을 SQL에 삽입하지 않는다. 이름 필터를 요청 파라미터/가변 정규식으로 전달하지 않는다. repo 운영 SQL과 앱 predicate의 일치를 실제 compiled query·generic plan에서 검증한다.

이 인덱스는 Free 전용 운영 객체로 앱 모델/migration에 추가하지 않는다. 기존ops_free_risk_cover와ix_stores_provenance를 유지해 원천 쿼리/기존 코드 롤백을 보장한다. 별도 인덱스 생성 전 현재 DB 크기/남은 공간·예상 최종800MB/생성 여유900MB 기준·정의/존재를 확인한다. 조건을 넘으면 생성하지 않고 다른 동등한 방안을 재검토한다. 실제 DB의 행/스키마/역할/기존 인덱스를 임의로 삭제하거나 timeout을 늘리지 않는다.

운영 인덱스는 별도 소유자 연결에서 생성이 필요하다. 기존 배포 작업의 승인된 관리 연결이 있으면 재사용하고 비밀값은 출력하지 않는다. 쓰기 권한이 없으면 앱 코드/격리검증/실제 reader 성능 측정까지 완료하고 필요한 권한만 요청한다. 생성은 코드 배포와 분리하고 기존 앱이 계속 동작하는 것을 확인한다. 앱은 여전히reader/TLS·워커1·풀1/overflow0/대기15초·SQL10초·예산8이다.

## 5. 구현·검증·배포 순서

1. Codex 설계 → 실제 Claude Code 소스 Read/이MD Edit → Codex 결정 기록. 다른 코드/DB/Git을 Claude에 허용하지 않는다.
2. 공통 정책/원천분리·메타·캐시·AI를 구현하고 코드와 회귀 테스트를 기능별 커밋한다.
3. unit:18개 키워드·영문 대소문자·null/빈 이름·정상 카페 유지·카페 M 오탐 동작·일반 이름/내부 공백·정적 SQL literal/요청값 미사용·정책 캐시 분리.
4. 격리 PostGIS: 실제 SQL/Python 후보 판정, history/nearby/snapshot/activity/risk/data-range 모집단·서울분모·폐업/생존율·no_coord·같은 이름 다른 category, 과거월, D/배치 보존·제외 이름 고아 오류 미은폐·재적재 이름 변경/원본 보존·Risk/AI 정책 불일치 거부/무효화. generic prepared plan의 새 부분 인덱스 적격성을 확인한다.
5. Free reader로 원본/해시를 보존한 사전 투영과 실제 쿼리 성능을 측정한다. 필요한 운영 인덱스는 용량·정의·계획·행/기존 앱 응답 보존 확인 후 별도 생성한다. 생성 실패/효과 없음은 그 새 인덱스만 제거하고 원래 상태를 확인한다.
6. ruff/format/mypy·일반pytest·격리·CI/CodeQL 성공 후 develop Squash 병합. 실제 병합 코드 동등성을 확인하고 현재 live/동시 배포/전체 환경값을 다시 읽은 뒤 검증된commit만 수동 배포한다. #127의 LLM 설정이 바뀌었다면 그대로 보존하고 AI를 끄거나 새 실모델 호출을 강제하지 않는다.
7. 명동13후보·원래454 응답에 대해 실제 제거 집합/남은 집합을 대조하고 전역 원본/D 보존, 원본행/모델/head0011 불변을 확인한다. cafe는data 동등(메타 정책만 추가), 음식점은 키워드 제외를 독립 오라클로 확인한다. 5 GET 동시 묶음·ready·CORS·AI 서버 재계산(모의 공급자)/실제 현재 오류 계약을 구분한다. 새 오류/부하 회귀 시 이전 코드로 복구하며 기존 운영 인덱스는 남아 있어야 한다.
8. 실제 배포 후 운영 두 문서·BE CLAUDE/작업계획·FE 전달 문서를 현재값/버전/효과/오탐 한계와 동기화한다. FE 파일은 바꾸지 않는다. 전체 실제 업종 정답·모든18개 제보 해결·모든부하 SLA로 확대하지 않는다.

## 6. 실제 Claude Code 검토

2026-11-14 Claude Code 검토. 소스 Read와 이 MD Edit만 했다. 테스트·DB 측정·EXPLAIN·배포는 실행하지 않았고 아래 계획/쿼리 판단은 코드 대조에 근거한 예상이다. B안(이름 키워드 제외) 결정은 전제로 두고 재승인을 요청하지 않는다. 정책 자체를 반려할 차단 사유는 없고, 아래 차단 항목은 구현·병합 전에 반드시 맞춰야 하는 조건이다.

### 6.1 검토 소스

`app/services/store_history.py`, `app/services/store_cohort.py`, `app/services/risk.py`, `app/services/risk_cache.py`, `app/services/spatial_stores.py`, `app/services/market_activity.py`, `app/ai/context.py`, `app/schemas/ai_context.py`(ContextModel 부분), `app/models/store.py`, `etl/brands/assignment.py`, `etl/brands/compare.py`, `docs/sql/render-free-risk-cover.sql`, `tests/integration/test_store_provenance_index.py`, `tests/ai/context_helpers.py`. snapshot/data-range 라우터, franchise.py, AI 캐시 저장부는 읽지 않았다(→ 6.3 C1).

현재 `SUPPORTED_STORES`(store_history.py:17) 사용처(읽은 범위): history 배치 목록 :111·점포 목록 :127, store_cohort `temporal_cohort` :26·`orphan_exists` :53/:61/:83·`current_provenance` 배치 목록 :94, ai/context `check_history_location` :201, etl/brands/assignment `plan` :50, 테스트 오라클 `reference_orphan` test_store_provenance_index.py:160. compare.py:38-48은 import하지 않고 별도 inline 조건(source 조건 없음, 기존 차이)이라 이번 변경 영향이 없다.

### 6.2 차단 (구현/병합 전 필수)

- **B1. 이름 조건은 bind 파라미터 없는 단일 최상위 AND 절이어야 한다.** `Store.category != "restaurant"`, `Store.name == ""`, `.op("~*")(pattern)`처럼 ORM 비교로 쓰면 `'restaurant'`·`''`·정규식이 모두 bind 파라미터가 되어, psycopg가 prepare한 generic plan에서는 `ops_free_risk_name_v1`의 부분 predicate를 증명할 수 없다(서울 Risk가 heap/seq scan으로 떨어져 SQL10초 위험). 정책은 상수 하나를 `sqlalchemy.text()`/`literal_column`으로 렌더링한 고정 SQL 조각이어야 한다. 예: `(category <> 'restaurant' OR name IS NULL OR name = '' OR name !~* '<18단어 alternation>')`. 분석 `SUPPORTED_STORES = and_(SOURCE_SUPPORTED_STORES, NAME_POLICY_SQL)` 형태로 **최상위 conjunct**에 둔다. 기존 OR의 restaurant 분기 안에 넣으면 플래너가 인덱스 predicate를 증명하기 어렵다. SOURCE가 category를 cafe/restaurant로 제한하므로 두 형태는 의미가 같다. 운영 SQL의 인덱스 WHERE 이름 절은 이 조각과 **같은 문자열**(같은 OR 순서, 명시 cast 없음)이어야 한다. varchar 컬럼은 양쪽 모두 `(name)::text`로 같은 파싱 트리가 되어야 equal() 증명이 성립한다. NULL 이름은 `!~*` 결과가 NULL이므로 `name IS NULL`을 명시해야 보존된다.
- **B2. 원천 경로는 빠짐없이 `SOURCE_SUPPORTED_STORES`로 바꾼다.** 이름을 유지한 `SUPPORTED_STORES`의 의미가 바뀌므로 누락된 import는 오류 없이 조용히 분석 모집단으로 바뀐다. 반드시 바꿀 곳은 store_cohort.py:53/:61/:83(orphan 3곳), :94(배치 목록), store_history.py:111(history 배치 목록), assignment.py:50(브랜드 입력. 누락 시 `store_input_sha256`/row_count가 바뀌어 다음 ETL에서 새 Run과 State 전환이 생긴다), test_store_provenance_index.py:160(오라클)이다. history 배치 목록을 분석 조건으로 두면 이름 제외 행만 있는 배치가 빠지고, `ai/context.py:250`의 Risk/history `stores_batch_ids` 집합 비교가 실패해 AI가 500을 낸다. 분석 조건이 남아야 하는 곳은 history 점포 목록 :127, `temporal_cohort` :26, `check_history_location` :201뿐이다.
- **B3. Risk meta와 AI `_DataVersion`은 한 커밋에서 같이 바꾼다.** `ContextModel`은 `extra="forbid", strict=True`(ai_context.py:33)이므로 `data_version.name_exclusion_version`만 추가되고 `_DataVersion`(context.py:65)에 필드가 없으면 모든 AI 해석이 500이 된다. 필드는 `Literal["store-name-keywords-v1"]`, 기본값 없음(필수)으로 둔다. `_history`(:246-255)·`_activity`(:320-329)에 `version.get("name_exclusion_version") == risk_version.get(...)` 비교를 추가한다. `version_json`(:429)에 들어가므로 data_version_hash가 자동으로 바뀌는지 테스트로 고정한다. `meta.name_exclusion` 객체도 정책 상수와 같은지 `expected_meta`(:398)에서 확인한다.
- **B4. 배포 순서: 인덱스 먼저 만들고 코드는 나중에 배포한다.** 새 코드가 `ops_free_risk_name_v1` 없이 뜨면 서울 Risk가 회귀한다. 새 인덱스는 이름 절이 없는 기존 쿼리가 쓸 수 없으므로 현재 앱에 무해하다. 순서는 (1) 용량 확인 → (2) 인덱스 생성 → (3) `indisvalid`·정의 일치 확인, 기존 앱 응답 불변 확인 → (4) 코드 배포로 고정한다. (3)이 실패하면 배포를 중단한다. 롤백은 코드를 먼저 되돌린 뒤 필요하면 새 인덱스만 DROP한다. `ops_free_risk_cover`·`ix_stores_provenance`는 건드리지 않는다.

### 6.3 주의

- **C1 미확인 사용처.** snapshot·data-range 라우터, `franchise.py`, AI 캐시 키 구성은 읽지 않았다. 구현 시 저장소 전체에서 `SUPPORTED_STORES` import와 `category_review_flag`가 들어간 inline 조건(compare.py 같은 복제)을 전수 조사하고 사용처마다 SOURCE/분석 중 무엇인지 PR에 표로 남긴다. compare.py의 기존 source 조건 누락은 이번 범위가 아니므로 고치지 않는다.
- **C2 대소문자 비구분의 로캘 의존.** PostgreSQL `~*`의 비ASCII case folding은 DB 인코딩·로캘을 따른다. 예를 들어 Kelvin 기호 U+212A를 `k`로 볼 수 있어 `baKery`가 매칭될 수 있다. Python `re.IGNORECASE`도 다르게 동작할 수 있다. 결정적으로 만들려면 영문 단어를 `[Cc][Aa][Ff][Ee]`처럼 ASCII 클래스로 펼치고 `!~`(대소문자 구분)를 쓰는 형태를 권장한다. 의미는 "영문 대소문자 비구분"과 같고 로캘과 무관하다. 어느 쪽을 쓰든 Python 오라클은 SQL 결과로 검증하고 Python에서 정규식을 재구현하지 않는다.
- **C3 Unicode 미정규화의 실제 결과.** NFD(자모 분해) 한글 상호, 전각 `ＣＡＦＥ`, 단어 중간 공백(`치 킨`)은 모두 통과(미제외)한다. 설계상 수용된 한계이므로 문서·FE 전달에 오탐과 미탐을 함께 적는다.
- **C4 기간 하한 이동.** `temporal_cohort`의 `min(open_date)`(risk.py:224, spatial_stores.py:79, market_activity.py:133)가 분석 모집단 기준이 되므로 가장 오래된 restaurant이 이름으로 제외되면 restaurant의 과거 월 하한이 늦어진다. 이전에 유효했던 `as_of`가 `AS_OF_OUT_OF_RANGE`가 될 수 있다. data-range도 같은 cohort를 쓰면 일관되지만 C1에서 확인해야 한다. 전역 D(`reference`)는 B2를 지키면 이동하지 않는다.
- **C5 history 빈 메시지.** 이름 제외로 건물 이력이 0건이 되면 `EMPTY_HISTORY_MESSAGE`("확인된 음식점·카페 인허가 기록이 없어요", store_history.py:16)가 사실과 어긋난다. FE를 수정할 수 없으므로 문구 변경은 별도 결정으로 미루고 `meta.name_exclusion`으로만 알린다. 제외 건수나 상호를 응답·LLM에 새로 노출하지 않는다.
- **C6 인덱스 용량.** 새 인덱스는 제외 행이 적어 `ops_free_risk_cover`와 크기가 거의 같다(사실상 2배). 생성 중 정렬 임시파일이 `maintenance_work_mem`을 넘으면 디스크를 일시적으로 더 쓴다. 900MB 피크 판단에 기존 cover 크기 × 2 이상의 여유를 넣는다. CONCURRENTLY는 실패하면 invalid 인덱스가 남으므로 정적 데이터·reader 전용 앱에서는 일반 `CREATE INDEX`를 권장한다(쓰기만 잠기고 읽기는 유지된다).
- **C7 index-only 여부.** PG의 부분 인덱스 predicate가 증명되면 name을 INCLUDE에 넣지 않아도 index-only scan이 가능할 것으로 예상한다. 실제 Free DB의 EXPLAIN에서 `Index Only Scan using ops_free_risk_name_v1`, Filter에 name 없음, Heap Fetches가 작음을 확인해야 한다. 증명되지 않으면 B1 형태부터 다시 본다. key/include를 바꾸는 방안은 그다음에 검토한다.
- **C8 migration/autogenerate.** 새 인덱스는 모델에 없으므로 Free DB에 autogenerate를 실행하면 DROP 제안이 나온다. 기존 원칙대로 autogenerate 대상에서 제외한다. 격리 테스트는 repo SQL 파일을 읽어 생성한다.
- **C9 Risk 캐시.** `risk_key`(risk_cache.py:57-69)에 정책 버전 인자를 추가한다. 캐시가 프로세스 메모리라면 배포 재시작으로 비워지지만 키 분리는 버전 변경에 대비해 그대로 필수다. AI 캐시는 data_version_hash가 B3로 바뀌는지만 확인한다.

### 6.4 동의

- 원천 자격(배치·D·고아·브랜드)과 분석 모집단의 분리, 원본 행/모델/head0011/ETL mapping version 불변.
- cafe 비적용·null/빈 이름 보존·18단어 고정 상수·요청 입력 미사용·임의 예외/사전 미추가.
- 기존 `rule_version` 유지와 별도 `name_exclusion_version` 추가. 오류 meta={} 유지.
- 기존 `ops_free_risk_cover`·`ix_stores_provenance`를 롤백용으로 유지하고 Free 전용 부분 인덱스를 따로 둔다. timeout·풀·예산은 바꾸지 않는다.
- #127 LLM 설정과 실제 환경값을 보존한다. 프롬프트에 업종 증명 주장을 넣지 않는다.

### 6.5 필수 회귀

1. unit: 18단어 각각 부분 일치(앞·중간·끝), 영문 대/소/혼합, `null`·`''` 보존, cafe+`커피`/`카페` 보존, restaurant `카페 M` 제외, 키워드 없는 이름·`치 킨` 보존, 정책 SQL 조각에 bind 파라미터가 0개이고 문자열이 운영 SQL 파일 WHERE 이름 절과 같음, 요청 필드로 정책을 바꿀 수 없음.
2. 원천 분리(격리 PostGIS): 최신 배치의 supported 행이 모두 이름 제외 대상이어도 `current_provenance` 배치 목록과 D가 그대로임. history `stores_batch_ids`가 Risk와 같음. 이름 제외 대상 restaurant이 고아(`batch_id` NULL/미등록/source 불일치)여도 500. `reference_orphan` 오라클을 SOURCE로 바꾼 뒤 기존 12개 시나리오 + 이름 제외 고아 시나리오 동치. `test_actual_service_queries_are_eligible_for_provenance_index`에 캡처 SQL에 `name`이 없다는 단언 추가.
3. 브랜드: 같은 fixture에서 `assignment.plan()`의 `input_sha256`·counts가 변경 전과 같음. compare.py 결과도 같음.
4. 분석 일관성: 같은 fixture에서 nearby·snapshot·activity·risk(local/서울 분모, 폐업률/생존율, `excluded_no_coord`)·history·data-range가 모두 같은 제외 집합을 씀. 과거 월과 C4 하한 이동. 같은 이름의 cafe/restaurant 쌍에서 restaurant만 제외. 재적재로 이름이 바뀌면(키워드 추가/제거) 다음 조회부터 반영되고 원본 행 불변. `check_history_location`이 history 목록과 같은 집합을 씀.
5. meta/AI: 성공 응답 전부에 `meta.name_exclusion`과 `data_version.name_exclusion_version`. 오류는 meta={}. `_DataVersion`이 버전 누락/다른 값을 거부. history/activity 버전 불일치를 거부. data_version_hash가 정책 버전에 따라 바뀜. context_helpers fixture(`response()`의 data_version)에 버전 추가. LLM 요청 본문에 이름·키워드·점포키 없음(기존 canary 유지).
6. 캐시: 정책 버전만 다른 `risk_key`가 서로 다름. 구버전 키 payload를 재사용하지 않음.
7. 계획: 격리 DB에 repo SQL로 `ops_free_risk_name_v1`을 만들고 `plan_cache_mode=force_generic_plan`에서 실제 캡처한 서울 Risk/min 쿼리의 stores 스캔이 새 인덱스를 쓰고 Filter에 name이 없음(작은 데이터라 적격성만 확인, 지연 시간 단정 금지). `ix_stores_provenance` 기존 단언 유지.
8. 운영(B4 순서): 생성 전 DB/여유 용량, 생성 후 `indisvalid`·`pg_get_indexdef` 정의 일치, 기존 앱 응답 불변, 배포 후 명동 restaurant 454→제거 집합/남은 집합 대조, cafe data 동등(meta만 추가), 5 GET 동시 묶음/ready/CORS 회귀 없음.

## 7. Codex 최종 판단·실행 결과

### 7.1 구현 결정

- B1/B2/B3/B4를 반영한다. 상수 predicate를 최상위 AND로 합성하고 batch/D/orphan/브랜드 ETL은 기존 SOURCE 자격, 목록/이력/시간 cohort/AI 위치 검사는 분석 자격을 쓴다. brand compare와 franchise 자동 분류의 증거 자격, 원본 ETL/floor backfill은 변경하지 않는다.
- C2를 채택해 영문을 ASCII 문자 클래스로 펼친 `!~`를 쓴다. 공백/Unicode 정규화·상호 예외·브랜드 사전은 추가하지 않는다. `카페 M` 오탐을 사용자 선택에 따른 의도된 결과로 테스트한다.
- C5는 구현 시 재검토했다. BE가 보내는 빈 이력 문구와 AI의 해당 고정 문장만 "분석 대상 … 조회되지 않음"으로 바꿔 제외된 원본이 존재하지 않는다고 오해하지 않게 한다. 새 입력·FE 작업·상호 공개는 없다. AI 내부 문맥/정책 버전 hash가 바뀌어 과거 캐시를 재사용하지 않는다.
- AI strict 데이터 버전뿐 아니라 Risk/history/activity의 정책 메타도 일치해야 한다. 분석 한계를 허용된 고정 limitation으로 AI에 전달하며 키워드 목록·이름·주소를 프롬프트에 넣지 않는다.
- Free 생성 전 최초 조회 DB721,131,187 bytes, 기존 cover45,883,392 bytes, 최종 상한778,485,427/일시851,839,667 bytes로 gate 안이다. 실행 직전에 재측정하며 코드 배포보다 새 인덱스를 먼저 검증한다.
- #127/PR129가 별도로 완료되어 LLM 키가 연결된 상태를 확인했다. 이 작업은 환경값 전체 hash를 보존하며 AI를 비활성화하지 않는다.
- 브랜드 회귀 fixture는 음식점 `Unique Cafe`를 키워드 없는 `Unique Bistro`로 바꿔 기존 브랜드 기능 검증을 유지한다. 별도 새 테스트가 제외 대상 `Unique Cafe`까지 원래 브랜드 입력 hash/건수에 포함되는 것을 독립 계산으로 확인한다.

### 7.2 검증 진행

새 정책 일반 회귀37개, 기존 AI345개 및 전체 일반1,716개 통과. ruff/format·mypy159 files 통과. 격리 전체와 실제 Free 실행 결과는 완료 후 갱신한다. 현재 운영 코드 배포는 하지 않았다.

## 8. 실제 구현 Claude Code 검토

2026-11-14 Claude Code 검토. 작업 디렉터리의 미커밋 구현을 Read로만 대조했고 이 MD만 Edit했다. 명령·테스트·DB·EXPLAIN·Git·네트워크는 실행하지 않았다. 아래 계획/동작 판단은 코드와 테스트를 대조한 결과다. B안 결정과 알려진 오탐(`카페 M` 등)은 전제로 두고 다시 묻지 않는다. 전달받은 상태: 일반1,716·AI 집중382·mypy159·ruff 통과, 격리 전체와 실제 Free 검증 진행 중, Free 미배포, 기존 LLM 설정 보존.

### 8.1 검토 범위

`app/services/store_scope.py`, `store_cohort.py`, `store_history.py`, `risk.py`, `risk_cache.py`, `app/ai/context.py`, `app/ai/interpretation.py`, `app/schemas/ai_context.py`, `etl/brands/assignment.py`, `docs/sql/render-free-risk-name-v1.sql`, `tests/test_store_scope.py`, `tests/integration/test_store_name_scope.py`, `tests/integration/test_store_provenance_index.py`, `tests/integration/test_brand_assignment.py`, `tests/ai/context_helpers.py`. `spatial_stores.py`·`market_activity.py`·data-range/snapshot 라우터·`franchise.py`·AI 결과 캐시 저장부는 읽지 않았다. 이들의 집합 일치는 `test_store_name_scope.py:97-205`의 HTTP 통합 테스트(nearby/snapshot/activity/risk/data-range/history/AI)로 확인되는 것을 근거로 삼았다.

### 8.2 6.2 차단 항목 반영 확인

- **B1 충족.** `store_scope.py:54-59`의 `NAME_SCOPE`는 `'restaurant'`·`''`·정규식을 모두 `literal_column`으로 렌더링한다. `test_store_scope.py:54-57`이 bind 파라미터 0개를 고정한다. `SUPPORTED_STORES = and_(SOURCE_SUPPORTED_STORES, NAME_SCOPE)`(:72)이므로 이름 절은 최상위 conjunct다. 렌더링은 `stores.category != 'restaurant' OR stores.name IS NULL OR stores.name = '' OR stores.name !~ '<pattern>'`이다. PG는 `!=`를 `<>`로 파싱하고, varchar 컬럼은 앱/인덱스 양쪽 모두 `(name)::text`·`'…'::text`로 같은 트리가 된다. 따라서 `render-free-risk-name-v1.sql:10-15`의 OR 절과 equal() 증명이 가능하다. OR 순서가 달라도 PG predtest의 OR⇒OR 팔 단위 증명으로 성립하지만 현재 순서도 같다. `SOURCE_SUPPORTED_STORES`의 기존 bind(`source IN`, `category = 'cafe'` 등)는 인덱스 predicate에 없는 조건이므로 증명에 영향이 없다. 실제 캡처한 서울 집계 SQL을 `force_generic_plan`으로 PREPARE해 stores 스캔이 모두 `ops_free_risk_name_v1`이고 Filter에 name이 없음을 단언한다(`test_store_name_scope.py:263-304`). 이 테스트는 repo SQL 파일 자체로 인덱스를 만들므로 파일과 앱 predicate의 의미 일치도 실행 수준에서 고정된다.
- **C2(ASCII 클래스) 충족.** `_pattern`(:43-45)이 `a-z`만 `[cC]`로 펼치고 `!~`(대소문자 구분)를 쓴다. Kelvin 기호·전각 문자·NFD 한글이 SQL/Python 양쪽에서 미제외로 일치함을 단위(`test_store_scope.py:34-51`)와 실제 PostGIS(`test_store_name_scope.py:62-94`)에서 확인한다. 생성 패턴과 SQL 파일 문자열은 `[cC][aA][fF][eE]` 순서까지 같다(`test_store_scope.py:61`).
- **B2 충족.** SOURCE 사용: orphan 3곳(`store_cohort.py:58/:66/:88`), 배치 목록(:99), history 배치 목록(`store_history.py:105`), 브랜드 입력(`assignment.py:50`), 오라클(`test_store_provenance_index.py:163`). 분석 사용: `temporal_cohort`(`store_cohort.py:31`), history 점포 목록(`store_history.py:121`), `check_history_location`(`context.py:203`). 이름 제외 고아가 500을 유지하고(`test_store_name_scope.py:208-222`), 최신 배치가 전부 제외돼도 D·배치 목록·브랜드 입력 hash가 원천 기준으로 유지되며(:225-252), 재적재 이름 변경이 다음 조회에 반영된다(:255-260). provenance 캡처 SQL에 `stores.name`이 없음을 단언한다(`test_store_provenance_index.py:126`).
- **B3 충족.** `_DataVersion.name_exclusion_version`이 기본값 없는 `Literal`(`context.py:71`)이다. `_history`(:244-260)·`_activity`(:322-339)가 `meta.name_exclusion` 객체와 버전의 상수/Risk 일치를 모두 검사한다. `expected_meta`(:408-420)가 Risk의 `name_exclusion`과 `limitations` 순서(4개 기본 + 이름 한계 + 추정 시 ESTIMATE_LIMIT)를 `ContextMethodology` 기본값(`ai_context.py:82-88`)과 비교하며 `risk.py:329-342`의 순서와 맞다. `version_json`(:440)에 버전이 들어가 `data_version_hash`가 바뀜을 `test_store_scope.py:90-115`가 재구성으로 고정한다. 누락/구버전/미래버전 거부도 테스트한다(:78-87).
- **캐시.** `risk_key`(`risk_cache.py:58-71`)에 `NAME_EXCLUSION_VERSION`이 들어가고 버전만 다른 키가 분리된다(`test_store_scope.py:65-75`). AI 쪽은 `data_version_hash`와 `context_hash`(methodology limitation 추가로 변경) 양쪽이 바뀌어 구 캐시를 재사용하지 않는다.
- **LLM 전송.** 키워드 목록·상호는 문맥에 없고 limitation 식별자만 추가된다(`test_store_name_scope.py:194-200`). 기존 `PRIVATE-NAME` canary 경로도 유지된다(`context_helpers.py:204-210`).

### 8.3 실제 결함

차단(정책/데이터 무결성/성능 계약 위반) 결함은 찾지 못했다. 아래 하나는 사용자에게 보이는 사실 서술 오류라 병합 전 수정을 권한다.

- **D1. AI 건물 이력 문장이 "전체"라고 서술한다(병합 전 수정 권장, 소규모).** 빈 이력 문구는 "분석 대상"으로 바뀌었지만(`store_history.py:22`, `interpretation.py:136-145`), 비어 있지 않을 때의 고정 문장은 그대로다. `interpretation.py:192-199`의 "건물 이력은 … **지원 업종 전체 기록입니다**"는 이름 정책 적용 후 사실이 아니다. 카테고리와 무관하게 history는 음식점을 포함하므로 cafe 질의에서도 틀린다. `:147-156`의 "이 건물의 음식점·카페 인허가 기록은 N건"도 빈 문구와 기준이 달라 같은 화면에서 모순된다. 수정: `:195`를 "…최신 자료 기준이며 이름 키워드 제외를 적용한 분석 대상 음식점·카페 기록입니다."처럼 숫자 없는 고정 문장으로 바꾸고, `:148`/`:154`에 "분석 대상"을 넣는다. 숫자를 추가하지 않으므로 `verify_output`의 숫자 대조에는 영향이 없을 것으로 예상하며, 문구를 단언하는 기존 AI 테스트만 갱신한다. 새 입력·상호·키워드·FE 변경은 필요 없다.

### 8.4 선택적 개선(병합을 막지 않음)

- **E1 LLM 측 basis 라벨.** `ContextHistory.basis = "latest_data_all_supported_categories"`(`ai_context.py:148`)는 LLM 문맥 라벨이라 출력은 서버 문장만 쓰므로 사용자 노출은 없다. 이번 릴리스에서 이미 `context_hash`가 바뀌므로 D1과 함께 `latest_data_analysis_scope_supported_categories` 등으로 바꾸면 추가 캐시 비용이 없다. 미루면 다음 변경에서 다시 hash가 바뀐다.
- **E2 사용자 노출 한계 문장.** 이름 한계는 meta와 LLM 문맥(limitation 식별자)에만 있고 렌더링된 AI 결과(`interpretation.py:253-277`의 고정 missing 목록)에는 없다. 필요하면 숫자·키워드 없는 고정 `MissingItem`(예: reason `restaurant_name_keyword_scope`, "음식점은 이름 키워드 기준으로 일부 기록을 분석에서 제외해 실제 음식점이 빠질 수 있습니다.")을 추가한다. 설계 요구 사항은 아니다.
- **E3 버전 고정 golden 테스트.** 캐시·AI 무효화는 버전 문자열에만 의존한다. 키워드/패턴만 바꾸고 버전을 올리지 않으면 Risk 캐시와 `data_version_hash`가 구 결과를 그대로 재사용한다. `sha256(NAME_EXCLUSION_PATTERN)`을 `store-name-keywords-v1`과 함께 고정하는 단위 테스트를 추가하면 버전 미변경을 CI에서 잡을 수 있다. 같은 이유로 `_DataVersion`의 `Literal["store-name-keywords-v1"]`(`context.py:71`)과 `ai_context.py:28`의 limitation 리터럴이 상수와 따로 적혀 있으므로 `get_args(...) == (NAME_EXCLUSION_VERSION,)` 단언을 추가한다.
- **E4 키워드 문자 집합 가드.** `_pattern`은 소문자 ASCII만 펼치고 나머지는 `re.escape`에 맡긴다. 향후 대문자·`%`·정규식 메타문자·공백이 들어오면 Python/PG 정규식 방언 차이나 psycopg `%` 해석 문제가 생길 수 있다. 키워드가 한글 음절 또는 `[a-z]`로만 이루어졌음을 단언하는 테스트를 추가한다.
- **E5 테스트 가독성.** `test_store_scope.py:46-47`, `test_store_name_scope.py:73-74`의 `"baKery"`·`"치킨"`은 시각적으로 ASCII/NFC 값과 같아 보이지만 Kelvin 기호·NFD 자모로 미제외를 기대한다(그렇지 않다면 :47이 실패해야 하므로 그렇게 추정한다). `"baKery"`, `unicodedata.normalize("NFD", "치킨")`처럼 명시적으로 쓰면 이후 편집기 정규화로 테스트 의미가 바뀌는 것을 막는다.
- **E6 index-only 단언.** generic plan 테스트는 Index Name과 Filter만 단언한다. 작은 데이터에서는 visibility map 때문에 Index Scan이 나올 수 있어 격리에서는 현재 수준이 적절하다. 대신 Free EXPLAIN(ANALYZE, BUFFERS)에서 `Index Only Scan using ops_free_risk_name_v1`과 낮은 Heap Fetches를 확인한다(6.3 C7).
- **E7 위치 검사 범위.** `check_history_location`이 분석 범위를 쓰므로 300m 밖 건물의 점포가 모두 이름 제외 대상이면 이제 거부되지 않고 0건 이력으로 통과한다(`context.py:195-209`). 설계 2절대로 history 목록과 같은 집합을 쓰는 것이 일관적이고 결과는 "조회되지 않음"이라 오해 위험은 작다. 더 엄격히 하려면 위치 검사만 SOURCE 범위로 둘 수 있다(INVALID_PARAM만 반환하므로 상호 노출은 없다). 현재 구현을 유지해도 된다.

### 8.5 잔여 위험(검증으로 닫아야 함)

- **R1 운영 인덱스 정의 동일성.** repo 파일과 앱 패턴의 일치는 테스트되지만, 실제 Free에 만들어진 인덱스는 실행 클라이언트 인코딩에 좌우된다. Windows psql이 콘솔 코드페이지(UHC/CP949)로 UTF-8 파일을 읽으면 한글 리터럴이 깨지거나 다른 문자열로 생성되어 predicate 증명이 조용히 실패한다(인덱스는 만들어지지만 쓰이지 않음). 생성 시 `PGCLIENTENCODING=UTF8`과 `ON_ERROR_STOP`을 쓰고, 생성 후 `pg_get_expr(indpred, indrelid)`/`pg_get_indexdef`에 `NAME_EXCLUSION_PATTERN`이 그대로 들어 있는지와 `indisvalid`/`indisready`를 확인한다. 이 확인이 통과하기 전에는 코드를 배포하지 않는다(B4).
- **R2 배포 순서.** 새 코드는 `ops_free_risk_name_v1` 없이 뜨면 서울 Risk가 기존 cover의 index-only를 잃어 heap 접근으로 떨어진다(SQL10초 위험). 인덱스 생성·검증 → 기존 앱 응답 불변 확인 → 코드 배포 순서를 지킨다. 롤백은 코드 먼저, 새 인덱스 DROP은 그다음이다. 일반 `CREATE INDEX`는 생성 중 stores 쓰기를 막으므로 ETL/브랜드 적용과 겹치지 않게 한다. 소유자 연결의 `statement_timeout`이 생성 시간보다 짧지 않은지도 확인한다(앱 timeout은 바꾸지 않는다).
- **R3 다른 Seoul 범위 쿼리.** generic 적격성 테스트는 서울 집계 1개만 캡처한다(`test_store_name_scope.py:276`). `min(open_date)`(`risk.py:225`)와 `excluded_no_coord` 카운트(:228-233)는 `geom IS NOT NULL`이 없거나 반대라 원래부터 어느 부분 인덱스도 쓸 수 없다. 이미 heap을 읽는 경로라 name 비교 추가 비용은 작을 것으로 예상하지만, data-range/activity의 전역 min 쿼리를 포함해 Free에서 기존 대비 지연/계획을 같이 측정한다.
- **R4 하한 이동(6.3 C4).** 가장 오래된 restaurant이 이름 제외되면 restaurant의 `min_month`가 늦어지고 이전에 유효한 `as_of`가 422가 될 수 있다. 통합 테스트(:174, :182-183)가 이 동작을 의도로 고정한다. FE 전달 문서에 적는다.
- **R5 정책 한계.** 오탐(`카페 M` 등 실제 음식점 제외)과 미탐(띄어쓰기·전각·NFD·키워드 없는 브랜드)은 사용자 결정대로 수용한 결과다. 명동 13후보·454 대조(5절 7단계)는 제거/잔여 집합을 독립 오라클로 기록만 하고 "18개 제보 해결"로 확대하지 않는다.
- **R6 LLM 설정.** 이 변경은 LLM 클라이언트·설정 코드를 건드리지 않는다(읽은 범위). 배포 시 환경값 전체 hash 보존 확인은 5절 6단계대로 실제 값으로 다시 한다.

### 8.6 결론

원천/분석 분리(배치·D·고아·브랜드 입력 보존), API 간 집합·날짜·provenance 일치, Risk/AI 캐시와 strict 버전 검사, bind 없는 고정 리터럴과 ASCII 클래스로 만든 부분 인덱스 generic plan 적격성은 설계와 6.2 차단 조건대로 구현되었다. 차단 결함은 없다. D1(AI 이력 문장의 "전체" 서술)은 문자열만 바꾸면 되므로 병합 전에 고치는 것을 권한다. E1은 같은 커밋에 넣는 것이 가장 저렴하다. 나머지 E 항목은 선택이다. D1을 반영(또는 명시적으로 보류 결정)하고 진행 중인 격리 전체·CI/CodeQL·Free 실측과 R1/R2의 운영 인덱스 정의·유효성 확인이 모두 통과하면 코드는 5절 순서대로 진행해도 된다.

## 9. 구현 검토 후 Codex 판단

실제 Claude Code 2차는 exit0/is_error=false, 18턴, 권한 거절0건으로 완료했다. D1/E1을 반영해 빈/비어 있지 않은 AI 이력 문장과 내부 history basis를 분석 대상 기준으로 맞췄다. E3/E4도 반영해 v1 패턴 SHA256 golden·AI Literal 동기화·키워드 문자 범위를 테스트한다. E5의 분해 한글은 normalize 호출로 명시했다. E2의 새 AI 결과 항목은 추가하지 않는다(이미 메타와 안전 문맥에 한계가 있고 기존 결과 구조를 유지한다). E6은 실제 Free 계획으로 검증하며 E7은 이력 목록과 같은 분석 범위를 유지한다.

검토 수정 후 일반1,718개, ruff/format·mypy159 files가 통과했다. 격리 전체270개와 검토 전후 관련26개 통과, 추가 문구 변경의 관련 회귀를 다시 확인한다. 실제 Free의 기존 응답은 한식454곳이고 고정 키워드로20곳이 제외될 것으로 사전 대조했다. #127의 LLM 설정·기존 live/전체 환경 hash를 기록했다. 전체 행의 JSON/text 직렬화 감사는 owner의90초 제한으로 취소되어 네이티브 composite hash(geom은 EWKB)로 바꿔689,440행 감사 기준을 확보했다. 앱의 SQL10초·풀 설정은 바꾸지 않았다.
