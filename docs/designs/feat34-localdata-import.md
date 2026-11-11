# 작업 34: 인허가 ETL 실응답 호환 및 개발 DB 적재

## 범위와 현재 상태

- 이슈: [#34](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/34), 브랜치 `feat#34-localdata-import`, PR 대상 `develop`.
- BE-08의 실제 원천 적재·검증을 마무리한다. BE-12 이력 API는 후속 작업이다.
- 2026-11-11 Windows 개발 DB `spoton_dev`, migration `0002`, stores 0건을 확인했다. Docker 설치·로컬 `.env`는 이번 커밋에 포함하지 않는다.
- 일반음식점·휴게음식점의 종로구 첫 100건씩을 실제 호출했다. 정상 resultCode는 `0`, 개업/폐업일은 `YYYY-MM-DD`, 갱신시각은 `YYYY-MM-DD hh:mm:ss`였다. 기존 코드는 `00`·compact 날짜만 가정해 모든 개업일을 오류로 처리했다.
- 두 API 인증과 카카오 주소 검색은 성공했다. 키·원문 행은 출력하지 않았다. 별도 JUSO_COORD_KEY는 이번 작업의 선행 조건이 아니다.
- 기존 모델·migration·주소/좌표 정규화·upsert와 source 단위 advisory lock을 재사용한다. API 계약·삭제 동기화·스케줄러·LLM 생성은 변경하지 않는다.

## 1. 실제 응답 호환

- 성공 코드는 허용 목록 비교로만 판정한다. 허용값은 문자열 `"0"`, 정수 `0`(bool 제외, `isinstance(v, bool)` 선검사), 기존 fixture의 문자열 `"00"`이다. `"000"`·`" 0"`·`"0.0"`·`0.0`·`None`·빈 문자열·`False`는 거절한다. `int(v) == 0` 같은 광범위 변환을 쓰지 않는다. `"00"`은 실응답에서 관측되지 않았으므로 fixture 호환 근거를 코드 주석에 남긴다.
- 날짜는 `[0-9]{8}`, `[0-9]{4}-[0-9]{2}-[0-9]{2}`의 ASCII `fullmatch`만 후보로 삼는다(`\d`·`str.isdigit`는 전각·기타 유니코드 숫자를 허용하므로 사용하지 않는다). 후보를 `date`로 만든 뒤 같은 형식으로 다시 출력해 원문과 일치할 때만 채택한다(round-trip). `2024-1-05`·`2024/01/05`·`2023-02-29`·`2024-01-05 00:00:00`·`2024-01-05T..`·timezone 접미사는 파싱 실패로 기존 날짜 오류 플래그에 기록하고, 시각을 잘라 날짜로 만들지 않는다. 빈 문자열·공백만 있는 값은 결측으로 처리하며 그 외 앞뒤 공백 처리는 기존 정규화 규칙을 그대로 따른다. 1960 이전·미래·역전 플래그 규칙은 변경하지 않는다.
- 중복 제거용 갱신시각은 `[0-9]{14}`, `[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}`만 허용하고 같은 round-trip 검증을 적용한다. 소수 초·`T` 구분자·timezone·24시는 거절한다. 두 형식 모두 같은 naive datetime으로 비교하며 타임존을 추정하지 않는다. 파싱 실패 갱신시각은 유효 시각보다 앞선 것으로 취급하는 기존 규칙(없으면 이 규칙을 명시)과 canonical_values tie-breaker를 유지해 입력 순서와 무관하게 같은 행이 선택되어야 한다.
- 응답 외피는 header/body·resultCode·totalCount·pageNo·rows 위치를 고정해 검사한다. totalCount·pageNo는 bool이 아닌 0 이상 정수 또는 ASCII 숫자 문자열만 허용한다. rows가 list가 아니거나 행이 dict가 아니면 schema contract 오류다.
- 필수 원천 키 MNG_NO·OPN_ATMY_GRP_CD가 비어 있지 않은 페이지의 모든 행에서 키 자체가 없으면 schema contract 오류로 source 전체를 중단한다. 일부 행 누락·빈 값은 기존 거절 집계로 처리한다. 응답의 OPN_ATMY_GRP_CD가 요청 관청 코드와 다르면 schema contract 오류다.

## 2. 수집·호출량

- 기본 라이브러리 호출은 현재처럼 순차 처리한다. 실행기는 `workers`(1~4, 라이브러리 함수에서도 범위 밖 값을 `ValueError`로 거절)를 받아 **실행 전체 기준** 동시 요청 수를 workers 이하로 제한한다. 관청 간 병렬을 하지 않고 한 관청 안의 페이지를 최대 workers개 묶음으로 조회한다. 묶음의 모든 future가 끝난 뒤 다음 묶음을 예약하며, 오류가 나면 남은 묶음을 예약하지 않고 이미 시작된 요청이 끝날 때까지 기다린 뒤 종료한다(백그라운드 스레드를 남기지 않음).
- HTTP 클라이언트는 연결 한도를 workers 이하로 두고 요청별 timeout을 유지한다. 기존 최대 3회 제한 재시도는 유지하되 추가 재시도 정책은 만들지 않는다. 실제 HTTP 시도마다 실행 한도를 차감한다. 실행기 read timeout은 유한한 60초로 두며, 기본 workers는 원천 지연을 고려해 1이다.
- 첫 페이지에서 totalCount와 max_pages를 확정한다. 모든 페이지의 pageNo 일치·totalCount 불변·관청 일치·행 수(마지막 페이지 외에는 정확히 page_size)·누적 수·조기 빈 페이지를 검사하고 결과는 완료 순서가 아닌 페이지 번호 순으로 합친다. 관청별 최종 누적 행 수는 totalCount와 같아야 하며, 수집 중 원천 갱신으로 totalCount가 바뀌면 부분 결과를 쓰지 않고 실패로 처리한다. 25개 서울 관청 코드 집합이 기대 집합과 정확히 같고 모두 성공해야 source 수집이 완료된다.
- 전체 실행 동안 httpx/httpcore 로거를 WARNING 이상으로 유지해 키 포함 URL 로그를 막고 `try/finally`로 원래 수준을 복원한다. 이 조치만으로 충분하지 않으므로 httpx 예외의 `str()`/`repr()`(요청 URL·query의 키 포함 가능)는 어떤 출력·예외 메시지·결과 객체에도 넣지 않고 예외 클래스 기반 고정 분류로만 변환한다. 변환 시 `raise ... from None`으로 원인 체인 출력도 막는다.
- 진행 출력은 source·관청 코드·페이지 번호·누적 건수·totalCount 등 집계만 사용한다. 각 관청 첫/마지막 페이지 및 일정 페이지 간격으로 출력한다. URL·query·응답 본문·행 값은 출력하지 않는다.
- 키 누락·인증 오류·할당량 소진·timeout/네트워크·원천 형식 변경은 고정 분류(`missing_key`, `auth_failed`, `quota_exceeded`, `network_error`, `schema_contract`, `page_inconsistent`)로 중단한다. 사용자가 필요한 키/자료를 설정하기 전 다른 후속 기능으로 우회하지 않는다.
- 첫 페이지 25개를 재사용하며 전체 예상 호출 수(관청별 ceil(totalCount/page_size) 합)를 계산한다. 기본 실행 한도 9,500회에는 재시도도 포함한다. 예상 수집량이 실행 한도를 넘으면 나머지 페이지를 호출하지 않는다. 사용자가 공유한 일반음식점 개발계정 일일 한도는 10,000회지만 다른 호출의 소비량·휴게음식점 잔여 한도는 단정하지 않는다.

## 3. 실행기와 DB 보호

- `python -m etl.localdata --source general_restaurant|rest_cafe`는 기본 dry-run이다. `--write`를 명시해야 쓰며 `--dry-run`과 동시 사용은 거절한다. `--workers`는 argparse에서 1~4 정수만 허용하고 기본 1이다. 한 실행은 하나의 source만 처리한다. 입력은 API 수집(기본) 또는 `--from-snapshot PATH` 중 하나이며 `--save-snapshot`은 API 수집에서만 허용한다.
- **dry-run 보장**: 공통 Settings로 API 키를 읽되 DATABASE_URL 속성을 사용·검증하지 않고 엔진·세션을 생성하지 않는다. 테스트에서 엔진 생성 함수를 호출 시 실패하도록 대체해 검증한다. dry-run에서 허용되는 부수효과는 `--save-snapshot`의 로컬 파일 쓰기뿐이다.
- **write 대상 보호(수집 전 정적 검사)**: SQLAlchemy `make_url`로 DATABASE_URL을 파싱해 드라이버가 기존 PostgreSQL 드라이버이고, host가 정확히 `localhost`/`127.0.0.1`/`::1`, database가 `spoton_dev`, username이 `spoton_app`일 때만 허용한다. libpq가 연결 대상을 바꿀 수 있는 query 인자(`host`, `hostaddr`, `service`, `dbname`, `user`, `options`, `target_session_attrs` 등)가 있으면 거절한다(query 허용 목록 방식). 거절 메시지는 위반 항목 이름만 출력하고 URL·비밀번호는 출력하지 않는다.
- **write 대상 보호(수집 전 연결 preflight)**: API 할당량을 쓰기 전에 읽기 전용 트랜잭션으로 `current_database() = 'spoton_dev'`, `current_user = 'spoton_app'`, 해당 role의 `rolsuper = false`, `alembic_version`이 정확히 `0002` 한 행, PostGIS 확장 존재, stores의 source+license_no 유일 제약(실제 이름은 migration 기준) 존재를 확인한다. 하나라도 다르면 수집하지 않고 고정 오류로 종료한다.
- **source 단위 원자성**: source 전체 수집(25개 관청 완료) → 전체 transform_rows → 단일 DB 트랜잭션 upsert 순서다. 기존 upsert는 이미 단일 connection.begin()과 pg_advisory_xact_lock을 사용한다. lock 뒤에 주입 가능한 before_write 검증을 추가해 실제 대상 조건을 같은 트랜잭션에서 다시 확인한다. 어느 단계든 예외가 나면 rollback하여 해당 source의 행이 하나도 바뀌지 않아야 한다. write 사전 검사용 엔진은 수집 전에 생성될 수 있으나 수집·정제 실패 시 쓰기는 없고 반드시 dispose한다. 별도 실행에서 이미 commit된 다른 source와의 교차 원자성은 주장하지 않는다.
- 삭제·truncate·테이블 재생성·migration 변경은 없다. 기존 브랜드·deleted_at 등 비ETL 필드는 보존한다.
- 결과에는 batch_id, source, 기준일, fetched/accepted/rejected/duplicates/transformed/affected와 품질 플래그 집계만 담는다. affected는 성공한 payload 처리 수이며 실제 변경 행 수라는 뜻이 아니다. 갱신 구분은 제한된 코드만 표시하고 미지 문자열은 other로 집계한다.
- 오류 출력은 예외 분류·허용한 고정 오류 코드만 사용한다. 설정 ValidationError·SQL/HTTP 예외·원문 repr/traceback·주소·상호·관리번호·비밀번호는 출력하지 않는다.

## 4. 로컬 원천 보관과 재실행

- 25개 관청 수집과 페이지 검증을 모두 통과한 경우에만 허용 DTO 필드를 Git에서 제외된 `datasets/localdata/`에 보관한다. 같은 커밋에서 `.gitignore`에 해당 경로가 포함됐는지 확인한다. 키·요청 URL·응답 전체·전화번호·대표자 필드는 저장하지 않으며 저장 필드는 허용 목록으로 직렬화한다(DTO 전체 `asdict` 후 제외 방식 금지).
- snapshot 내용: `format_version`, `source`, `collected_at`(수집 시작 시각, 초 단위 naive KST로 명시), 관청별 `{gu_code, total_count, page_count, row_count}`, `row_count` 합계, rows, rows의 정규 JSON(정렬 키·UTF-8·`ensure_ascii=False`·구분자 고정) SHA-256. 관청별 row_count는 total_count와 같아야 한다.
- **원자적 기록**: 같은 디렉터리의 임시 파일에 쓰고 flush·fsync 후 최종 이름으로 바꾼다. 최종 이름은 source·수집시각·batch_id로 유일하게 만들고, 이미 존재하면 덮어쓰지 않고 실패한다(`os.replace`의 덮어쓰기 대신 존재 검사 후 이동하거나 배타적 생성 사용). 임시 파일 접미사는 로더가 절대 읽지 않으며, 실패 시 임시 파일을 삭제한다.
- `--from-snapshot`으로 같은 수집 결과를 재생해 재적재 검증에 API 할당량을 다시 쓰지 않는다. 로더는 `json.load`의 NaN/Infinity를 거절하고 다음을 모두 검증한다: 알려진 format_version, 요청 source와 일치, 관청 코드 집합이 기대 25개와 정확히 일치·중복 없음, 관청별 row_count = total_count, 행의 관청 코드 분포가 관청별 row_count와 일치, 전체 행 수, SHA-256 일치, 각 행의 키 집합이 허용 DTO 키와 정확히 일치, 값은 `str` 또는 `None`만 허용. 하나라도 실패하면 정제·DB 단계 전에 거절한다.
- **재생 결정성**: 재생 시 미래 개업일 등 기준일 의존 판정은 실행 당일이 아니라 snapshot의 `collected_at` 날짜를 기준일로 사용한다. 따라서 같은 snapshot의 두 번 정제 결과는 batch_id·updated_at을 제외하고 동일해야 한다. API 수집 직후 정제도 같은 `collected_at` 기준을 사용한다.
- 원천 기록은 저장소 밖 로컬 자료이며 PR·이슈·로그에 첨부하거나 내용을 인용하지 않는다.

## 5. 테스트와 실제 검증

모든 테스트는 합성 fixture·가짜 transport만 사용하며 실제 키·네트워크·원문 행을 쓰지 않는다. 각 항목은 "통과해야 할 입력"과 "거절해야 할 입력"을 모두 포함한다.

**파서(단위)**
- 성공 코드: `"0"`·`0`·`"00"` 통과, `False`·`True`·`"000"`·`" 0"`·`0.0`·`None`·`""`·`"INFO-200"`류 거절을 parametrize로 검사한다.
- 날짜: 두 허용 형식 통과, 윤년 `2024-02-29` 통과·`2023-02-29` 거절, `2024-1-05`·`2024/01/05`·`2024 01 05`(내부 공백)·전각 숫자·`2024-01-05 00:00:00`·`2024-01-05T00:00:00+09:00` 거절과 기존 날짜 오류 플래그 기록을 검사한다.
- 갱신시각: 두 형식이 같은 시각이면 동등 비교, 소수 초·`T`·timezone·`24:00:00` 거절, 혼합 형식 중복에서 최신 행 선택이 입력 순서를 뒤집어도 동일한지 검사한다.
- 응답 외피: 필수 키가 페이지 전체에서 사라진 경우 schema_contract, 일부 행만 누락이면 거절 집계, 관청 코드 불일치·rows 타입 오류·bool totalCount 거절.

**수집(가짜 transport)**
- 순차(workers=1)와 병렬(workers=4) 결과가 행 순서까지 동일하다. transport가 응답 순서를 뒤섞어도 페이지 순 결합이 유지된다.
- transport의 동시 진입 카운터 최댓값이 workers 이하임을 단언한다. workers 0·5·bool 거절.
- 특정 페이지 오류 시 이후 묶음 요청이 0건 발생하고(호출 기록으로 단언) 미완료 스레드가 남지 않는다.
- totalCount 변경·pageNo 불일치·중간 빈 페이지·짧은 중간 페이지·누적 수 불일치·관청 하나 실패를 각각 거절하고, 이때 transform·upsert·snapshot 기록 함수가 호출되지 않는다.
- 비밀 비노출: 가짜 키 문자열(예: 고유 마커)을 넣고 httpx DEBUG 로그를 유발하는 경로와 예외 경로를 실행한 뒤 caplog·capsys 전체 출력과 발생 예외의 `str`/`repr`/`__cause__`/`__context__`에 마커가 없음을 단언한다. 실행 후 로거 수준이 원래대로 복원됨을 확인한다.

**실행기·보호**
- 인자: 기본 dry-run, `--write --dry-run` 거절, `--save-snapshot`과 `--from-snapshot` 동시 사용 거절.
- dry-run: DATABASE_URL 미설정 환경에서도 성공하고, 엔진 생성 함수를 호출 시 실패하도록 대체해도 성공한다.
- URL 정적 검사: 원격 host, `spoton_test` 등 다른 DB, 다른 계정, sqlite, query의 `host`/`hostaddr`/`service`/`options` 인자를 각각 거절하고 오류 출력에 비밀번호 마커가 없음을 단언한다. 정적 검사 실패 시 transport 호출 0건.
- preflight 실패(가짜 결과로 DB·계정·superuser·revision·PostGIS·제약 각각 불일치) 시 수집 호출 0건.
- 결과·오류 출력에 주소·상호·관리번호 마커가 없고 갱신 구분 미지 문자열이 `other`로 집계된다.

**snapshot**
- round-trip 후 rows·해시·관청 집계가 동일하고 두 번 정제 결과가 batch_id/updated_at 외 동일하다(기준일이 collected_at임을 실행일을 바꿔 확인).
- 거절: 잘린 JSON, NaN, 해시 불일치, 관청 누락·중복·추가, row_count≠total_count, 추가/누락 필드, 비문자열 값, 다른 source, 알 수 없는 format_version.
- 기록: 같은 이름 존재 시 덮어쓰지 않음, 기록 중 예외 시 최종 파일 미생성·임시 파일 삭제, 임시 파일 경로를 로더에 주면 거절.
- 저장 내용에 허용 목록 외 필드(전화번호·대표자 등 fixture에 넣은 마커)가 없음을 단언한다.

**CI PostGIS 통합(격리된 테스트 DB)**
- 실행기 write 경로에서 payload 중간에 강제 예외를 주입하면 stores 행 수와 기존 행 값이 실행 전과 같다(source 원자성).
- 같은 payload 2회 적재 시 행 수 불변, 비ETL 필드(brand_id·deleted_at 등) 보존.
- 이 테스트는 CI 임시 DB에서만 실행하며 개발 DB 연동 완료의 근거로 쓰지 않는다.

**실제 개발 DB 검증(구현 후 수행, 결과는 집계만 기록)**
1. 정적 검사·preflight만 수행하는 경로로 대상이 spoton_dev/spoton_app/0002임을 확인하고 기존 stores source별 건수를 기록한다. 기존 행이 있으면 비ETL 필드 대조용 집계(예: brand_id 비null 수, deleted_at 비null 수)를 함께 기록한다.
2. source별 API dry-run + `--save-snapshot`으로 전체 수집하고 관청별 total/row 일치, 예상·실제 호출 수, 정제 집계를 기록한다.
3. 같은 snapshot으로 `--write`를 실행한다(dry-run 결과와 DB 입력이 같은 자료임을 보장하고 할당량 재사용 방지).
4. source별 DB count = 정제 후 고유 키 수, (source, license_no) 중복 0, geometry 비null 행의 SRID 4326·유효성·서울 경계 상자 내 여부, 좌표 제외 건수·날짜/한시/업종 검토 플래그 집계가 실행 결과와 일치하는지 확인한다.
5. 같은 snapshot을 재적재하고 batch_id·updated_at을 제외한 ETL 필드·geometry의 행별 해시 집계가 이전과 같고 1단계의 비ETL 집계가 보존됐는지 확인한다.
6. 두 source·영업/폐업·플래그 유무를 섞은 최소 20건을 원천 허용 필드 → 정제 예상값 → DB 값으로 대조한다. 식별값은 출력하지 않고 성공 건수·검사 항목만 기록한다. 불일치가 1건이라도 있으면 완료로 표시하지 않는다.

- ruff check/format, mypy app etl migrations, 전체 pytest를 실행한다. 개발 DB에는 파괴적인 integration suite를 실행하지 않으며, 통합 테스트용 DB URL이 spoton_dev를 가리키면 테스트가 스스로 건너뛰지 말고 실패하도록 한다. branch push의 lint-and-test 및 격리된 postgis-integration success 이후 PR을 생성한다.

## 6. 기능별 커밋

1. `docs(be): 인허가 실데이터 적재 설계와 Claude 검토 기록`
2. `fix(etl): 실제 응답 코드와 날짜 형식 지원` — 파서·중복 정규화·해당 회귀 검사
3. `feat(etl): 개발 DB 적재 실행기와 원천 재생 추가` — 제한 병렬 수집·dry-run·대상 보호·snapshot·검사
4. `docs(be): 인허가 실제 적재와 검증 결과 기록` — README 명령·실제 집계·제한·작업계획 현재 상태

## Claude Code 검토 기록

검토일 2026-11-11. Claude Code는 이 파일만 Read·Edit했고 코드·다른 파일·Git·셸·외부 호출은 사용하지 않았다. 따라서 아래 내용은 설계 문서 수정이며 구현·테스트·실제 적재가 수행됐다는 뜻이 아니다. Codex는 실제 diff와 기존 코드를 대조한 뒤 구현한다.

### 수정 내용과 이유

1. **원천 형식 엄격화(1절)**: 성공 코드를 허용 목록 비교로 고정하고 Python에서 `bool`이 `int`의 하위형이라 `False == 0`이 성공으로 통과하는 문제를 명시했다. 날짜·갱신시각은 `\d`/`isdigit`가 전각·유니코드 숫자를 허용하므로 ASCII 패턴 `fullmatch` + round-trip으로 바꿨다. 시각 포함 문자열을 잘라 날짜로 쓰지 않도록 거절 사례를 열거했다. 응답 외피·관청 코드 일치 검사를 추가해 다른 관청 자료가 섞이는 경우를 막았다.
2. **제한 병렬·비밀 보호(2절)**: "최대 4"가 관청별이 아닌 실행 전체 기준임을 명시하고 라이브러리 단에서도 범위를 검증하게 했다. 오류 후 진행 중 요청 처리와 스레드 정리 규칙을 넣었다. 로거 수준 조정만으로는 httpx 예외 메시지(요청 URL 포함)와 예외 체인으로 키가 새는 경로를 막지 못하므로 고정 분류 변환과 `from None`을 요구했다. 자동 재시도는 할당량 소모와 부분 성공 판단을 복잡하게 하므로 이번 범위에서 제외했다.
3. **source 단위 원자성(3절)**: 기존 문구는 "실패 source에는 쓰기 없음"만 있어 upsert 도중 실패 시 부분 commit 여부가 불명확했다. 단일 트랜잭션·트랜잭션 내 advisory lock·단일 commit·rollback 보장으로 바꾸고, 기존 upsert의 commit 경계를 구현 전 확인하도록 했다.
4. **dry-run·DB 보호(3절)**: dry-run이 설정·엔진을 만들지 않음을 테스트로 강제하게 했다. URL 정적 검사에 libpq query 인자(`host`, `service` 등)로 연결 대상을 우회하는 경로를 막는 허용 목록을 추가했다. preflight를 API 수집 **전에** 수행해 잘못된 대상이면 할당량을 쓰지 않게 했고, superuser 거절과 revision 정확 일치를 추가했다. 쓰기 직전 같은 트랜잭션에서 재확인한다.
5. **snapshot 완결성·원자성(4절)**: 관청별 total/row 수와 정규 JSON 해시로 잘림·변조·관청 누락을 판별하게 했다. 임시 파일 + fsync + 이동, 덮어쓰기 금지를 명시했다. 직렬화를 허용 목록 방식으로 바꿔 DTO에 새 필드가 생겨도 민감 필드가 자동 저장되지 않게 했다. "같은 실행일 조건"이 모호해 재생 결과가 실행 날짜에 따라 달라질 수 있으므로 기준일을 `collected_at`으로 고정했다.
6. **테스트(5절)**: 기존 항목은 "검사한다" 수준이라 통과 기준이 불분명했다. 동시 진입 카운터, 오류 후 호출 0건, 비밀 마커 부재(로그·출력·예외 체인), 엔진 생성 함수 차단, 원자성 실패 주입 등 실패할 수 있는 단언으로 구체화했다.
7. **실제 검증(5절)**: dry-run으로 저장한 snapshot을 그대로 `--write`에 쓰게 해 검증 대상과 적재 대상이 같은 자료임을 보장했다. count·유일성·geometry·플래그·재적재 해시·비ETL 보존·20건 대조의 판정 기준과 "불일치 시 완료 표시 금지"를 넣었다.

### 남은 확인 사항·차단 요소

- **기존 코드 미확인**: 이 검토는 코드를 읽지 않았다. 기존 upsert의 commit 경계, advisory lock 종류(세션/트랜잭션), stores 유일 제약 이름, 파싱 실패 갱신시각의 기존 정렬 규칙, DTO 필드 목록, DB 모듈의 엔진 생성 위치는 Codex가 구현 전 확인해야 한다. 기존 upsert가 청크 commit 구조라면 원자성 요구를 만족하도록 설계를 먼저 보완한다.
- **원천 할당량·규모 미확인**: 서울 전체 일반음식점·휴게음식점의 페이지 수와 키별 일일 호출 한도가 확인되지 않았다. 할당량 소진 시 `quota_exceeded`로 중단하고 다음 날 재실행하거나 사용자 조치를 기다리며, 이를 우회하지 않는다.
- **수집 중 원천 갱신**: totalCount 변동을 실패로 처리하므로 원천이 자주 갱신되면 반복 실패할 수 있다. 실제로 발생하면 허용 정책(재수집 등)을 사용자와 정한 뒤 바꾼다. 임의로 완화하지 않는다.
- **`00` 성공 코드**: 실응답에서 관측되지 않았고 fixture 호환용으로만 유지한다. 원천 명세 확인 시 제거 여부를 다시 판단한다.
- **localhost 보호의 한계**: Docker 포트 매핑상 localhost가 다른 컨테이너/DB로 연결될 수 있으므로 URL 검사만으로는 충분하지 않고, 연결 후 `current_database`·`current_user`·revision 확인이 실제 보호 수단이다.
- **snapshot 내 상호·주소**: 허용 필드라도 상호·주소를 포함하므로 로컬 보관 위치의 Git 제외(`.gitignore`) 반영 여부를 같은 커밋에서 확인해야 한다. 이 검토에서는 다른 파일을 열 수 없어 확인하지 않았다.
- **외부 명세**: 날짜 플래그 enum·좌표 보완 정책 등 작업계획 9절의 확인 대기 항목은 이 작업에서 확정하지 않는다.

## Codex 최종 점검 (2026-11-11)

- Claude의 실제 Read/Edit 결과와 수정 문서를 확인했다. upsert는 `connection.begin()` 하나로 전체 청크를 처리하며 제약 이름은 `uq_stores_source_license_no`, lock은 트랜잭션 단위다.
- dry-run의 공통 Settings 사용과 DB 속성 미사용을 구분하고, write 사전 검사와 수집 전 엔진 생성 금지 사이의 모순을 수정했다.
- 기존 제한 재시도는 보존한다. 사전 25개 관청 동시 조회에서 ReadTimeout이 발생해 기본 병렬 수는 1로 낮췄으며, 실제 수집은 bounded timeout·시도 한도 아래 검증한다. 인증·원천 자료가 부족하면 멈춘다.
- `.gitignore`의 datasets/ 제외를 확인했다. 실제 표본은 해당 로컬 경로에만 보관했으며 Git에 포함하지 않는다.
- live 응답 0·ISO 날짜·ISO 갱신시각은 두 원천에서 확인했다. 회귀 검사는 합성 값으로 작성한다. 문자열 00의 기존 호환은 유지한다.
- 전체 수집·적재·20건 대조·최종 CI는 아직 실행 전이며 완료로 표시하지 않는다.
