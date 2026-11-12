# 생활인구 반경별 원천 품질 진단기 (#84)

- 기준: develop `69d13b3`, DB head0010
- 범위: 생활인구 의미 검증/제공률 조사에 앞선 내부 읽기 전용 진단 CLI. 브랜드 #57 승인 답변 대기와 독립적으로 진행한다.

## 1. 준비 상태와 확인 경계

기존 관측 버전은2026-11-07 하루/531,922행·격자10,125개다. 행정동 분할 합산 의미·행 부재 의미·격자 적용시점은 미확인이다. 공개 activity/Risk의 인구 pending을 유지한다. 수치/주야간 비중·공식 완전성/제공률을 활성화하는 작업이 아니다.

[공식 내국인 안내](https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do)는 격자 단위 시간별 추계와 소규모 값 비공개를 설명한다. [2026-11-09 소급 공지](https://data.seoul.go.kr/together/notice/datasetNoticeView.do?seq=1b68433233ce9c1df838a4f63df84ca0&bbsCd=10008&ditcCd=&pageIndex=1)의 수정 대상은2025년 일부 날짜여서 현재 관측일2026-11-07은 그 공지 범위 밖이다. 이 사실만으로 현 관측일의 모든 정의·품질이 확인된 것은 아니다. 원본 재다운로드/적재는 하지 않는다.

## 2. 제공 기능

- `python -m etl.living_pop.quality --population-version UUID --lat ... --lng ... --radius 300|500|1000`.
- 명시적 관측UUID만 사용한다. 자동 최신/다른 날짜 대체 없음. 해당 버전의 저장된 EPSG5179 중심점을4326 geography로 변환해 반올림 전 거리<=반경인 격자를 선택한다. 진단용 공간 기준이며 인구 집계 API의 확정 계약이 아니다. 1만 격자 전체 중심점 거리 비교로 근사 bbox의 false negative를 피한다.
- 원천local/long/short×24시각마다 반환행의 observed/suppressed/missing/실제0 행 수, 행이 있는/없는 선택 격자 수, 비공개·결측이 포함된 격자 수, 복수행정동 행이 있는 격자 수를 출력한다.
- 행 없음은0명으로 바꾸지 않는다. 행이 모두 숫자여도 행정동 구성 누락 여부를 알 수 없으므로 인구 완전성·합계·API 제공률을 선언하지 않는다. 복수행정동도 합산하지 않고 현황만 센다.
- 좌표미확인 행은 선택 격자 통계에 넣지 않는다. 별도 원천별 전역 건수와 `observation_version_global` 범위를 명시한다. 반경의 missing_grid_count로 재사용하지 않는다.
- 결과에는 관측일·관측/격자버전·grid_as_of·기존 spatial_compatibility와 진단기준/한계를 남긴다. 좌표·격자코드·행정동코드·점포·원자료/인구 값·키는 출력하지 않는다.
- 저장행 수는 관측/격자 버전metadata 및 원천별 rows와 대조한다. full content hash 재검증은 하지 않았다고 명시한다. 데이터 삭제/부분 적재를 완성된 진단으로 처리하지 않는다.

## 3. 구조와 보존

`app/analysis/population_quality.py`에 query/결과 모델·순수 상태 집계·Session 조회를 둔다. `etl/living_pop/quality.py`는 설정/명시적 local target/head0010 검사와 READ ONLY REPEATABLE READ 세션·자원해제·안전CLI만 담당한다. 기존 DatabaseResources/read_only_session과 ETL target guard를 재사용한다. DB/원천/모델/migration·공개API/FE·환경설정·실LLM 호출 변경 없음.

입력은UUID/유한좌표/지원반경을 DB 연결 전에 검증한다. 오류는 고정 코드만 출력하고 argparse/SQL 예외에 입력이나 URL을 노출하지 않는다. 진단은 한 snapshot에서 수행하고 기존SQL3초를 유지한다. 전체table content hash 조사는 별도검증 세션에서만 수행한다.

## 4. 검사·완료 기준

순수집계: source/hour/격자 구분, 실제0/비공개/결측/행없음/복수행정동, 빈공간, 잘못된수/중복그룹 거절,72원천시각 정렬,인구값·좌표 비출력. CLI: 잘못된값·한도·없는버전·DB오류의 고정 안전코드와 자원정리.

격리PostGIS: 실제 적재 fixture로 중심점/반경 선택·다른버전미혼합·행/metadata 누락 거절·좌표미확인 전역범위, READ ONLY RR/쓰기거절·예외후해제. 소규모 합성에서 경계거리의 반올림/공간기준을 독립계산으로 대조한다. 실제dev는명시UUID/공개고정점 300/500/1000m 조사와 행보존만하며 새적재/DDL을실행하지않는다.

일반/격리·ruff/format/mypy·비밀값검사 후 지정PR·CI/CodeQL/develop Squash. 브랜드/인구정의/주야간API 전체 완료로 표시하지 않는다. FE 요청서·FE CLAUDE는 공개 계약 변경이 없어 대상이 아니다.

## 5. Claude 검토 요청

이 MD와 지정한 BE 소스만 Read, 이 MD §6만 Edit한다. .env·DB·Bash·네트워크·Git·FE는 접근/수정하지 않는다. 품질통계와 의미검증/완전성 구분·행없음/행정동미확인·공간/시각·민감정보·버전완전성·읽기전용·SQL비용을 검토한다.

## 6. Claude 검토 결과

검토 범위: 이 MD와 `app/models/living_population.py`, `app/db/dependencies.py`, `etl/living_pop/__main__.py`, `etl/living_pop/repository.py`, `tests/etl/living_pop_helpers.py`를 정적으로 Read만 했다. 실제 DB·원천·dev 데이터를 재검증하지 않았고, 테스트·쿼리·EXPLAIN도 실행하지 않았다.

**판정: 조건부 타당.** 생활인구 합산 의미가 미확인인 상태에서는 값을 합산하지 않고 상태별 행·격자 수만 세는 진단 CLI가 적절한 범위다. 공개 API/FE와 pending 상태를 바꾸지 않는다는 경계도 맞다. 단, 아래 보완을 구현 조건으로 둔다.

1. **행 없음과 0명**: `observed`이면서 0인 행과 0이 아닌 행을 서로 겹치지 않는 별도 칸(`observed_zero`/`observed_nonzero`)으로 센다. 행 없음은 (source,hour,격자)에 행정동 행이 하나도 없는 경우만 뜻하며, 0으로 바꾸거나 `missing`으로 합치지 않는다. 72개 원천·시각 칸은 빈 칸도 항상 출력한다.
2. **반환행 관측 ≠ 전체 완전성**: 격자에 행이 있어도 해당 격자에 걸친 행정동 행이 모두 있는지는 원천 구조상 알 수 없다. 결과명은 `grids_with_rows`/`grids_without_rows`/`grids_with_nonobserved_rows`처럼 개수만 담는다. `coverage`·`complete`·`available`·`rate`·`ratio`·`total`·`sum`·`population`이 들어간 키와 비율은 출력하지 않는다.
3. **복수행정동**: (source,hour,격자)마다 서로 다른 admin_code가 2개 이상이면 `grids_with_multi_admin_rows`로 센다. 이것이 분할인지 중복인지는 판정하지 않고, 값 합산도 하지 않는다.
4. **전역 미좌표와 반경 범위**: 미좌표 행에는 `located_grid_id`가 없으므로 반경 안에 있는지 알 수 없다. 원천별 전역 건수는 `scope="observation_version_global"`로 따로 두고 반경 통계와 섞지 않는다. 한계 문구에 "반경 안에 물리적으로 있는 미좌표 행이 빠졌을 수 있음"을 남긴다.
5. **중심/거리 기준**: 현재 설계는 원천 속성 `center_x/center_y`(EPSG5179 정수)를 쓴다. 이 값은 저장된 `geom`(4326 MULTIPOLYGON)의 중심과 같다고 검증되지 않았다(헬퍼의 `width` 인자로 두 값이 어긋나게 만들 수 있음). 결과에 `selection_basis="source_center_attr_5179_to_4326_geography_dwithin"`을 남기고, 중심 판정을 ST_Centroid로 바꾸지 않는다. 거리는 `ST_DWithin(geography, geography, r)`(spheroid)로 한 번만 정의한다. 1만 행 변환 전체 스캔 비용은 허용 범위로 본다.
6. **명시 UUID와 동일 snapshot**: 버전 행 조회, 그 버전의 `grid_version_id`로 한정한 격자 선택, `version_id`와 `grid_version_id`를 모두 조건으로 건 관측 조회, metadata 대조를 한 READ ONLY REPEATABLE READ 트랜잭션에서 수행한다. 최신 버전 대체, 날짜 대체, 다른 격자 버전과의 join은 금지한다.
7. **민감정보**: 입력 좌표·UUID 외의 식별자, 격자/행정동 코드, 인구 값, 그리고 행 단위 정보를 stdout, 로그, 예외에 남기지 않는다. `read_only_session`은 `AppError`로 감싸므로 CLI가 이를 고정 코드(예: `living_pop_quality:database`)로 바꿔야 한다. `logged_import`류 데코레이터로 인자가 로그에 남지 않게 한다. `DatabaseResources.close()`는 cache까지 닫으므로 finally에서 반드시 호출한다.
8. **보존/SQL 비용**: 반경 조회는 `ix_living_population_located(version_id, located_grid_id, hour)`를 탈 수 있다. 반면 전역 원천별 건수와 상태별 행 수 대조는 해당 버전 약 53만 행을 훑어야 하므로 3초 timeout에 걸릴 수 있다(측정하지 않음). 전역 집계는 `GROUP BY source, value_status, geometry_status` 한 번으로 끝내고, timeout이 나면 고정 코드로 실패한다. timeout을 임의로 늘리거나 인덱스/DDL을 추가하지 않는다. 쓰기·임시 테이블·결과 파일 저장은 없다.
9. **metadata 검사 범위**: `sources`의 원천별 `rows`, `statuses{observed,suppressed,missing}`, `unlocated_rows`, 버전 `row_count`, 격자 `row_count`와 실제 저장 건수를 대조한다. 키가 빠지거나 더 있거나 타입이 틀리면 거절한다. 이 대조는 건수 일치만 보여 주므로 결과명은 `stored_counts_match_metadata`로 하고, content hash를 재검증하지 않았다는 사실을 한계에 남긴다(`verified`라는 표현은 쓰지 않음).

**결과 한계 문구(필수 출력)**: 품질 진단 전용 / 인구 합계·완전성·제공률이 아님 / 행 없음은 0이 아님 / 행정동 분할 의미 미확인 / 미좌표 행은 반경 판정 불가 / 격자 적용 시점 미확인(`grid_as_of=null`, `spatial_compatibility=unverified`) / content hash 미재검증.

**필수 회귀**: 실제0·비공개·결측·행없음이 서로 다른 칸에 들어가는지, 72칸 고정 출력, 복수행정동 격자 계수, 금지 키 부재(스키마 키 allowlist 단언), 인구 값·코드·좌표가 출력/로그에 없는지, 중심 속성과 geom이 어긋난 합성 격자에서 선언 기준대로 선택되는지, 경계 거리(r±0.01m)를 pyproj Geod로 독립 계산해 대조, 다른 버전·다른 격자 버전 행 미혼합, 미좌표 행이 반경 통계에서 빠지는지, metadata 건수 불일치·키 누락·버전 없음·부분 적재 시 실패하는지, READ ONLY 쓰기 거절, timeout/DB 오류 시 고정 코드와 자원 해제, 반경 내 격자 0개일 때 `selected_grid_count=0`으로 끝나고 0명으로 표기하지 않는지.

**차단 조건**: 위 금지 키나 비율 출력, 행 없음의 0 치환, 복수행정동 합산, 자동 최신/대체 버전, 다른 격자 버전 혼합, metadata 불일치를 성공으로 처리, 좌표·코드·값 노출, timeout 상향·DDL·쓰기, 공개 API/FE/pending 상태 변경, 실제 dev 조사 결과를 원천 의미 검증이나 완전성 확인으로 기록하는 것.

## 7. Codex 최종 결정·검증

Claude의 품질 현황/인구 완전성 구분·행 없는 격자의 비치환·72칸·전역미좌표 범위·고정 안전오류·건수 metadata 대조를 채택한다. 결과 키에는 population/complete/coverage/rate 등 수치 제공으로 오해할 표현을 쓰지 않는다. 실제0과 observed_nonzero는 겹치지 않게 센다.

격자는 source center 속성을 쓰고 selection_basis에 명시한다. 선택은 구면 근사 prefilter 없이 geography spheroid ST_Distance<=radius로 정의한다. 이는 기존 설계의 반올림 전 거리 기준을 유지하고 경계 근처 DWithin 후보 오차를 피하기 위한 선택이다. pyproj Geod의 독립 r±0.01m 검사를 한다.

metadata는 원천명3개·statuses3개의 정확한 키와 양의 rows·비음수 unlocated counters를 검증하고 실제 건수와 대조한다. sources의 해시/파일일자 등 기존 추가 metadata 키는 그대로 허용하되 결과에 전달하지 않는다. 이를 전체 metadata schema 또는 full hash 검증으로 표현하지 않는다. global 집계는 원천별 상태/미좌표 카운트를 한 SQL로 계산하고3초를 넘으면 안전하게 실패시킨다.

### 구현 및 실행 결과

- `app/analysis/population_quality.py`에 명시 버전 조회·저장 건수 대조·원천 중심점 반경 선택·상태별 순수 집계를 구현했다. `etl/living_pop/quality.py`는 기존 로컬 대상 검사·head0010·READ ONLY REPEATABLE READ·SQL3초 제한을 재사용한다. 결과는 stdout JSON 한 건이며 실패는 고정 코드만 출력한다.
- 새 단위30개·격리 통합18개를 포함해 전체 일반 **1,196 passed**, 격리 PostGIS **173 passed**. 기존 Starlette testclient deprecation 경고1건만 있다. ruff check/format(290파일)·mypy app/etl/migrations(138파일) 통과. CLI 전용 timeout 지연 테스트를 새로 만들지는 않았으며 기존 공통 세션의 timeout 회귀를 재실행했다. 신규 CLI DB 오류 검사는 실제 READ ONLY 쓰기 거절·고정 오류·해제를 확인한다.
- 통합 검사는 3개 반경 각각 r±0.01m를 Geod로 독립 대조하고, polygon 중심과 source center 불일치·다른 관측/격자 버전 분리·데이터/metadata 누락 거절을 검증했다. 비공개·결측·실제0·행 부재·복수행정동을 구분하며 72개 원천·시각 칸과 전역 미좌표 범위를 확인했다.
- 실제 개발 DB의 **2026-11-07 관측 버전 UUID를 명시**해 공개 고정점3곳×300/500/1000m 총9개를 읽었다. 총 실행은1.672~1.906초였고 SQL 제한은 바꾸지 않았다. 선택 격자는4~51개였으며 선택 격자 내 행 부재·비공개 행이 있는 사례를 확인했다. 이는 사람 수·누락 인구·완전성·제공률을 뜻하지 않는다. 모든 반환 행이 숫자인 경우도 행정동 구성 완전성을 보장하지 않는다.
- 별도 읽기 전용 QA에서 생활인구 관련 **4개 테이블의 전체 행/공간 hash와 건수 보존**, head0010을 확인했다. 이 QA는 CLI의 `content_hash_rechecked=false`를 바꾸지 않는다. 실제 개발 DB DML/DDL·재적재·VACUUM은 실행하지 않았다.
- Claude는 §6 설계 MD를 직접 수정했고 Codex가 해당 변경과 소스 대조 후 구현했다. 공개 API/FE/pending 상태·모델/migration·설정/비밀값·실LLM 호출은 변경하지 않는다. 공정위 브랜드 #57은 승인 여부 답변 전까지 보류한다.
