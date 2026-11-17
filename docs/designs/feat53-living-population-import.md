# BE-19 생활인구 격자·시각별 원천 적재

- 이슈 #53 / feat#53-living-population-import / 2026-11-12
- 상태: **사용자 1번 결정·Claude 실제 MD 검토·Codex 최종 점검을 반영해 구현 및 로컬 검증 완료**. PR·CI 후 develop 일반 Squash 병합하며 실제 병합 상태는 이슈 #53의 연결 기록을 따른다.
- 범위: 공식 250m 격자·시각별 내국인/장기·단기 외국인 원천 적재 기반. 생활인구 API·반경 집계·주야간 비율·FE 변경은 별도 작업이다.

## 1. 실제 확보한 공식 원천

서울특별시·KT 추계 생활인구이며 실제 방문객 수/하루 고유 인구가 아니다. [공식 생활인구 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do), [내국인 OA-22784](https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do), [장기외국인 OA-22785](https://data.seoul.go.kr/dataList/OA-22785/S/1/datasetView.do), [단기외국인 OA-22786](https://data.seoul.go.kr/dataList/OA-22786/S/1/datasetView.do)를 확인했다. 세 일별 원천의 이용허락은 공공누리 1유형(출처표시·상업 이용/변경 가능)이다. 현재 공개 파일 중 세 원천 공통 최신 일자 **2026-11-07** 하루를 초기 검증 대상으로 선택했다. 2025년 연간 점포/매출과 같은 시점이라고 가정하지 않는다.

| 원천 | ZIP bytes | 해제 CSV bytes | 행 수 | 헤더 수 / 실제 열 수 |
|---|---:|---:|---:|---|
| 내국인 | 15,076,836 | 58,631,410 | 253,400 | 33 / 33 |
| 장기외국인 | 2,428,237 | 23,247,697 | 137,137 | 26 / 33 |
| 단기외국인 | 1,919,863 | 22,918,331 | 141,385 | 24 / 33 |

CSV 3개 모두 CP949, 기준일 20261107, 시각 00~23, 행정동 427개다. 원천 첨부 수정일은 2026-11-11이다. 관측 합계 **531,922행**, 중복 `(일자,시각,행정동,격자)` 0건이다. 대용량 원본과 조사 스크립트/보고서는 저장소 밖 또는 Git 비추적 경로에 보관하며 실제 행·격자 코드·좌표·인구값을 문서/로그에 넣지 않는다.

ZIP SHA256:

- 내국인: `b8a195c235d5a3925adfe4af8a7ba1fc73f4bf0ca35fcefbd8253c07ede8a1f9`
- 장기외국인: `7681dada438809d0d5b0754acadf9a801688b243b20864d525da1067148eeeee`
- 단기외국인: `7fc26597154d054be6bfc16db6aa0c814c0219826dd1225f8ea060c6af8bf35a`

## 2. 확정 설계 전 반영할 구조 차이

### 행정동 차원

앞 5개 헤더는 일자·시간·행정동코드·250M격자·생활인구합계다. 행정동 코드는 원본에서 **8자리 숫자+공백 5개**(길이13)다. 임의 일반 trim 대신 관찰한 표기를 명시적으로 처리하고 정규화 전 원문 hash를 남기는 규칙을 설계한다. 격자 코드는 10글자이며 SHP의 **CELL_ID**와 연결한다. 별도 **GID** 필드는 데이터와 일치하지 않으므로 조인 키로 사용하지 않는다.

같은 격자·시각의 여러 행정동 행이 실제 존재한다. 내국인 44,292개, 장기 15,492개, 단기 15,576개의 격자·시각 그룹이 복수 행정동을 가진다. `(grid_id,date,hour)`만 PK로 만들거나 같은 격자 행을 중복으로 제거하면 원자료가 소실된다. **행정동 차원을 보존**하고 수집 원천별 관측을 분리한다. 원천을 결합할 때 full outer join/누락 표시를 검토하며 내국인 행을 전체 원천의 완전한 기준 목록이라고 가정하지 않는다. 원천 행을 즉시 합산해 행정동 차원을 지우지 않는다.

### 외국인 파일의 빈 패딩 열

장기는 헤더 뒤 7개, 단기는 9개의 **전부 빈 추가 열**을 모든 행에서 확인했다. 헤더와 열 수가 같다는 기존 매출/점포 parser를 재사용하면 잘못 거절한다. 허용할 경우 원천·정확한 개수·모두 빈 조건을 고정하고 원본 패딩 수/전체 member hash를 보존한다. 데이터가 든 추가 열을 무시하거나 33개라고 잘못된 국적 명칭을 채우지 않는다. 장기 원천의 `인도 ` 헤더 끝 공백도 원문이다. 헤더/구조 허용 목록은 원천별로 분리한다.

### 비식별 값·결측·0

합계 `*`는 내국인 **13,857행**, 장기 **15,429행**, 단기 **28,493행**이다. 숫자 합계는 각각 239,543/121,708/112,892행이고 빈 합계·0·음수는 현재 표본에 없다. 관찰한 합계 소수 정밀도는 2자리다. 공식 안내는 추계 소수 정밀도를 설명하므로 저장 타입/허용 정밀도는 정의서를 추가 대조한 뒤 확정한다.

`*`는 **비식별 값**, 빈 셀은 **원천 결측**, 숫자0은 **원천의 실제0**, 행 없음은 **조합 미제공**으로 구분한다. 판정은 공백 제거 없이 셀 원문 그대로 한다(`" *"`, `" "`, `"-"` 등 다른 표기는 상태로 흡수하지 않고 전체 거절). 총계가 숫자이고 세부 셀이 `*`이거나 그 반대인 행도 총계 셀만으로 value_status를 정하며 세부 셀로 총계를 보정하지 않는다. 형식 위반은 해당 행만 건너뛰지 않고 적재 전체를 실패시킨다. `*`를 0이나 임의 중앙값으로 바꾸거나 성별/연령/국적 부분합에서 복원하지 않는다. 공식 안내와 개별 원천의 비식별 임계 설명에 차이가 있어 임계값으로 마스킹 여부를 추측하지 않고 원문 `*`를 보존한다. 세부 값의 합이 합계와 일치하도록 보정하지 않는다. 합계와 상태만 적재하고 세부 인구 속성을 값으로 저장할 필요가 있는지 최소 범위로 검토한다.

## 3. 공식 격자 SHP와 실제 미매칭

공식 안내의 서울 격자 파일(250m, 5179, SHP), 다운로드 `DOWNLOAD/infSeq=4/seq=37`을 확보했다. ZIP 329,428 bytes, SHA256 `5f7f95db30f1d4a433d9905b281c3fb95b59cd8200985512a897326208bf525e`, 내부 파일 시각은 2025-05-13이다. 첨부 수정일·실제 적용일은 별도 확인되지 않았으므로 현재 날짜로 채우지 않는다.

`match/` 아래 SHP/SHX/DBF/PRJ/CPG 및 QIX/QMD가 있고 **10,125개 Polygon**, EPSG:5179를 확인했다. DBF는 CELL_ID/CELL_X/CELL_Y/GID다. 사용 중인 상권 EPSG:5181과 다르다. CRS를 추측하지 않고 PRJ·실제 형상과 250m 크기/면적·좌표 범위/유효성·변환 결과를 검증하는 별도 적재 설계가 필요하다.

내국인 원천의 고유 격자는 8,566개이며 이 중 **1개가 SHP의 CELL_ID에 없다**. 해당 격자의 **24시간/24행은 모두 합계 `*`**다. 장기·단기 원천의 고유 격자는 각각 5,607/5,372개이며 미매칭은 0개다. [공식 격자 지도](https://data.seoul.go.kr/opendata/seoulStay/grid_viewer.html)의 10,125개 CELL_ID와도 대조했지만 같은 1개가 없다. 지도용 근사 사각형이나 코드에서 계산한 좌표를 공식 SHP로 대체하지 않는다.

## 4. 확정한 처리 기준

2026-11-12 사용자가 **1번(좌표 미확인 보존·공간 집계 제외)**을 선택했다. 24개 비식별 행을 모두 보존하고 공식 geometry 미확인 상태를 따로 기록한다. 원천에 없는 도형·수치0을 만들지 않으며 매칭 실패 자체를 이유로 행을 삭제하지 않는다. 서울 전체 원천의 unlocated 수와 위치를 아는 반경 내 missing_grid_count를 섞지 않는다.

같은 사용자 지시로 이후 유사한 데이터 처리 선택은 Claude Code의 실제 설계 MD 검토와 Codex 점검을 거쳐 가장 적절한 안을 선택하고 근거를 기록한다. 필수 자료·키·권한 자체가 없어 진행할 수 없는 경우는 기존대로 요청한다. 이 결정은 임의 좌표/값 생성이나 범위 밖 외부 쓰기를 허용하지 않는다.

## 5. 모델·해시·CLI

### 네 테이블과 migration 0008

- living_grid_versions: UUID PK, ZIP input_sha256/bytes, rule_version, source_url, source_crs=5179, grid_as_of nullable(현재 null), row_count, content_sha256, postgis_version, loaded_at. UNIQUE(input_sha256,rule_version). SHP 내부 시각은 metadata JSONB에 참고값으로 남기고 적용일로 바꾸지 않는다.
- living_grids: `(grid_version_id,grid_id)` PK/FK RESTRICT, source_gid, center_x/center_y BIGINT, source_row_sha256, geom MULTIPOLYGON4326·GIST. 원본 CELL_ID를 grid_id로 쓰며 GID는 속성으로만 보존한다. 격자 행/geometry는 버전별 불변이며 미매칭 관측용 가짜 격자 행은 생성하지 않는다.
- living_population_versions: UUID PK, grid_version_id FK RESTRICT, observation_date, input_sha256(세 원천의 ZIP hash+일자 canonical fingerprint), rule_version, sources JSONB(세 ZIP/member hash/크기/내부시각/첨부일/인코딩/원천·상태·미매칭 건수/허용 padding), row_count, content_sha256, spatial_compatibility=unverified, loaded_at. UNIQUE(input_sha256,rule_version,grid_version_id). 같은 입력/규칙/격자에 다른 manifest는 거절한다.
- living_population_observations(복수형 테이블 규칙, 데이터 명칭 living_pop은 문서상 별칭): `(version_id,source,hour,admin_code,grid_id)` PK, population Numeric(20,5) nullable, value_status=observed|suppressed|missing, geometry_status=located|unlocated, source_row_sha256. source=local|long|short. observed면 0 이상·유한 population 필수, 나머지면 null 필수. 시간0~23·Seoul 행정동8자리·격자 형식·hash CHECK.
- 참조 무결성(Claude 수정): 행에 grid_version_id·observation_date를 비정규화하고 `(version_id,grid_version_id,observation_date)`→living_population_versions`(id,grid_version_id,observation_date)` 복합 FK RESTRICT(대상 UNIQUE 추가)로 버전과 날짜/격자 버전 불일치를 DB에서 막는다. 원문 grid_id는 항상 NOT NULL로 보존하고 별도 nullable `located_grid_id`를 둔다. `(grid_version_id,located_grid_id)`→living_grids`(grid_version_id,grid_id)` 복합 FK는 MATCH SIMPLE(NULL이면 검사 생략)이다. CHECK: `geometry_status='located'` ⇔ `located_grid_id IS NOT NULL AND located_grid_id=grid_id`, unlocated ⇔ `located_grid_id IS NULL`. 미매칭 행은 가짜 격자 없이 보존되고 located 행은 DB FK로 보장된다. "unlocated인데 실제 격자에 존재" 여부는 CHECK로 막을 수 없으므로 write 후 재조회 검증 쿼리(0건 필수)로 확인한다.
- 인덱스: `(version_id,located_grid_id,hour)`(공간 연결용, located만) 및 PK. 행정동 단독 조회 인덱스는 소비 API가 정해질 때 추가한다.
- population에는 총계만 저장하고 성별/연령/국적의 상세 값은 저장하지 않는다. 원천 행 hash는 헤더·정규화 전 전체 원문 셀/padding을 canonical JSON으로 묶어 추적한다. 비식별 값을 부분합에서 복원하지 않는다.
- downgrade는 신규 4개 테이블 ACCESS EXCLUSIVE 후 비어 있을 때만 삭제하고 기존 모든 표를 보존한다. 실제 개발 DB에서는 downgrade를 실행하지 않는다. 공통 ETL head guard와 관련 테스트는 0008로 갱신한다.

### 파일/수치/격자 검증

- 단일 날짜의 세 원천을 모두 요구한다. manifest JSON(32KiB 이하)은 observation_date, grid{path,sha256}, sources{local,long,short:{path,sha256,file_date}}만 허용한다. 경로는 manifest 위치 기준으로 해석하며 저장소 안 원본은 거절한다. CLI는 `python -m etl.living_pop --manifest PATH [--write]`, 기본 dry-run이다. URL/키/네트워크 수집은 CLI에 넣지 않는다.
- CSV 원천별 ZIP32MiB/해제64MiB·500,000행, 전체1,500,000행·필드4096자 한도. 기존 bounded ZIP helper를 원천별 한도로 재사용한다. CP949 strict 또는 BOM UTF8. 헤더 local33/long26/short24를 정확히 검사하며 장기7/단기9개의 추가 빈 padding만 허용한다. 임의 trim/중간 열 무시/임의 이름 채우기는 하지 않는다.
- admin_code는 8자리 숫자 또는 그 뒤 공백 정확히5개인 표기만 허용하고 정규화 전 원문은 hash에 포함한다. 코드 prefix11·date==요청일자·hour 00~23·같은 source/date/hour/admin/grid 중복 거절. 원천별24시각 모두 필수이며 미제공 조합을 0으로 채우지 않는다.
- 총계와 모든 세부 숫자 셀을 검사한다. `*`는 suppressed, 정확히 빈 문자열은 missing, 그 외는 아래 **숫자 문법 v1**에 셀 전체가 일치할 때만 observed이며 나머지는 전체 거절한다. 문법 검사 후에만 Decimal로 직접 변환·고정5자리로 저장해 float/반올림을 피한다. 합계를 세부 합과 일치시키거나 낮은 숫자에서 마스킹을 추정하지 않는다.
  - 숫자 문법 v1(Claude 확정, 8절): `re.fullmatch(r"(0|[1-9][0-9]{0,14})(\.[0-9]{0,5})?", cell)`. 즉 정수부 `0` 또는 선행0 없는 ASCII 정수 1~15자리, 그 뒤 선택 소수점과 소수 0~5자리다. `12.`·`0.`처럼 **소수점 뒤 숫자 0개**는 허용하고, `.`, `.5`, `012`, `00`, 소수6자리 이상, 정수16자리 이상, 앞뒤/중간 공백·개행, 부호, 지수, NaN/Inf, `_`·`,` 구분자, 전각/비ASCII 숫자는 거절한다. `$`가 아닌 fullmatch, `\d`가 아닌 `[0-9]`를 쓴다. Decimal 생성자는 공백·`_`·유니코드 숫자·`Infinity`를 받아들이므로 문법 검사 대체로 쓰지 않는다.
  - 원문 표기 보존: 저장 population은 값만 고정5자리로 남긴다(`12.`·`12`·`12.00`→`12.00000`). 원문 표기 차이는 source_row_sha256(정규화 전 원문 셀)로 보존하고, 원천별 후행 소수점 셀 수(총계/세부 구분, 값·코드 없이 건수만)를 sources JSONB 집계에 기록한다.
- 격자 ZIP4MiB/해제16MiB/20,000행. 단일 폴더·단일 layer의 SHP/SHX/DBF/PRJ/CPG와 선택 QIX/QMD·해당 부모 directory만 허용하며 path/CRC/링크/암호화/중복/크기 검사 후 메모리에서 읽는다. DBF 삭제/행 수 불일치·중복 CELL_ID·예상 필드/형식·UTF8 CPG를 검사한다.
- 실제 PRJ는 EPSG5179 식별 신뢰도70(90에서는 미식별)이나 datum·GRS80 타원체·투영 method9807·모든 파라미터/단위가 EPSG5179와 일치한다. 식별 confidence70 이상 + datum/타원체/prime meridian/투영 파라미터/단위 일치, 비 bound·projected CRS를 요구하고 5181/5186/잘못된 datum은 거절한다. PostGIS에서는 source5179를 명시하고4326으로 변환한다.
- CRS 근거 보강(Claude 수정): identify confidence는 PROJ DB 버전에 따라 달라질 수 있으므로 **보조 근거**로만 기록하고 판정 기준은 결정적 검사로 한다. ①PRJ 원문 SHA256을 sources/grid metadata에 기록, ②파싱한 WKT의 타원체 GRS80(a=6378137, 1/f=298.257222101)·Transverse Mercator·위도원점38·중앙경선127.5·축척0.9996·false easting1,000,000·false northing2,000,000·미터 단위를 상수 허용 목록과 비교(허용오차 고정), ③CELL_X/Y 범위가 5179 서울권 투영 범위 안이고 변환한 모든 격자 중심이 서울 bbox 안인지 확인, ④대상 PostGIS의 spatial_ref_sys 5179 정의 존재 확인. pyproj가 현재 잠긴 의존성이 아니면 새 의존성을 추가하지 않고 ②를 직접 파서로 구현한다(추가가 필요하면 pyproject/uv.lock 고정과 사유를 같은 커밋에 기록). 같은 좌표를 5181로 해석하면 ③을 통과하지 못함을 부정 테스트로 확인한다.
- 부분 격자·행정동 분할(Claude 수정): living_grids geometry는 **셀 전체**이며 같은 격자의 행정동별 행이 차지하는 셀 내부 부분 도형은 원천에 없다. 행정동 경계와 교차해 부분 도형을 만들거나 면적 비율로 인구를 배분하지 않는다. 행정동 분할 행들의 합이 격자 전체 값인지는 공식 정의서 대조 전 미확인이며 적재 단계에서 합산하지 않는다. 서울 외곽에서 잘린(비정사각형) 셀은 실제 SHP에 없었으므로 허용하지 않고 발견 시 전체 거절 후 규칙 변경으로 다룬다.
- 모든 실제 도형은 250m 정사각형·한 ring·센터와 CELL_X/Y 일치였다. 5개 꼭짓점(닫힘 포함)·bbox 모서리4개·폭/높이250±0.001m·센터±0.001m·유효/비어 있지 않음·면적62500m²·Seoul권 bbox를 검사한다. 왜곡/invalid는 전체 거절하고 사각형을 재생성하거나 보정하지 않는다. GIST와 변환 전후 표본 대조를 검증한다.

### 원자성·메모리·불변성

- 기본 REPEATABLE READ READ ONLY 트랜잭션에서 identity/head/PostGIS·geometry 변환과 원천 연결·기존 버전 재사용/내용을 검사한다. 삽입/락 없이 rollback한다.
- --write는 key19/common namespace의 advisory xact lock으로 grid+하루 관측 writer를 직렬화한다. grid 버전이 없으면 격자/버전을 추가하고, 있으면 metadata와 DB 실제 geometry/속성 hash를 재검증한다. 관측 버전도 동일하게 검사하고 필요한 세 원천 전부를 한 트랜잭션으로 insert한 뒤 DB 재조회 내용 hash/건수와 대조한다. 어느 단계든 실패하면 이번 신규 grid/관측 버전·행을 모두 rollback한다. 기존 버전은 update/delete/최신 자동 선택하지 않는다.
- 원자성 보강(Claude 수정): 세 원천과 격자의 **파일 단계 검증 전체를 DB 쓰기 전에 완료**한다(원천 하나라도 실패하면 DB 연결 전 종료). lock key는 BE-16~18과 같은 namespace의 고유 정수 상수로 두고 기존 key 값이 바뀌지 않았음을 회귀 테스트한다. 관측 버전이 이미 있는데 행 수·content hash·원천별 상태 집계가 다르면 보충 삽입/수리 없이 고정 코드로 거절한다(부분 적재 버전은 원자성상 존재할 수 없으므로 존재 자체가 변조 신호). 버전 행은 FK 때문에 관측 행보다 먼저 같은 트랜잭션에서 삽입하며, 커밋은 행 재조회 hash·건수·unlocated 재검증이 모두 통과한 뒤 단 1회다.
- 출력은 버전 UUID·날짜·원천/상태/미매칭 집계와 삽입·재사용 여부만 남긴다. 원본 셀·인구값·격자/행정동 코드·좌표·경로·접속 정보를 출력하지 않는다. 예외는 고정 코드, SQL 원문은 숨긴다. lock_timeout5초·statement_timeout60초를 사용한다.
- canonical JSON/noNaN으로 원문/저장 행 hash를 정의한다. 관측 content hash는 source/date/hour/admin/grid 정렬된 각 저장 행의 SHA256(고정64자)+개행을 metadata prefix(rule_version/date) 뒤에 순서대로 누적한 SHA256이다. Decimal은 고정5자리 문자열/null이다. 전체 531,922행 JSON을 한 번에 만들지 않고 slots dataclass·배치 insert·서버 커서 DB 재조회와 incremental hash를 사용한다. 해시 정의를 고정 벡터와 순서/훼손 테스트로 검증한다.
- 해시 정확성 보강(Claude 수정):
  - canonical JSON은 `sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False`, UTF-8 bytes로 고정한다. prefix는 `{"rule_version","observation_date","grid_version_input_sha256","source_order":["local","long","short"],"row_count"}` canonical JSON+개행이다. row_count를 prefix에 넣어 행 누락/추가를 hash 수준에서도 구분한다.
  - 저장 행 canonical 필드: source, hour(정수), admin_code(정규화 8자리), grid_id, located_grid_id(null 가능), population(`format(d,"f")`로 만든 고정5자리 문자열/null), value_status, geometry_status, source_row_sha256. Python `str(Decimal)`은 `0E-5` 같은 지수 표기를 낼 수 있어 금지한다. DB 재조회 값도 같은 포매터를 통과시킨다.
  - 정렬은 source는 위 고정 순서, hour는 정수, admin_code/grid_id는 **UTF-8 bytes 순서**다. DB 재조회는 `ORDER BY ... grid_id COLLATE "C"`처럼 텍스트 키에 C collation을 명시한다. DB 기본 collation(ko_KR 등)에 의존하면 같은 내용도 hash가 달라진다.
  - 원천 행 hash(source_row_sha256)는 정규화 전 원문 셀 전체(헤더 순서 배열+padding 원문 배열)를 canonical JSON으로 만든 것이다. 성별/연령/국적 세부 값은 저장하지 않으며 hash만으로 복원 용도로 쓰지 않는다(공개 집계 자료이므로 개인정보는 아니나 저장 범위 최소화 원칙 유지).
  - 격자 버전은 두 hash를 분리한다. identity/재사용은 **원본(5179) 속성·좌표 기반 content hash**, 변조 검사는 DB 저장 geometry의 `ST_AsEWKB` 기반 stored hash이며 후자는 postgis/PROJ 버전과 함께 기록한다. PROJ 업그레이드로 변환 결과가 미세하게 달라질 때 기존 버전을 수정하지 않고 재검증 실패를 고정 코드로 보고한다.
  - input_sha256 = canonical JSON `{"observation_date","sources":{"local":zip_sha256,"long":...,"short":...}}`의 SHA256이다. manifest의 file_date(첨부 수정일)는 사람이 선언한 provenance이므로 identity에 넣지 않고 sources JSONB에 `declared`로 기록하며, 같은 identity에 다른 manifest metadata가 오면 기존 규칙대로 거절한다.
- 메모리·확장성 보강(Claude 수정):
  - ZIP member는 bytes 전체를 읽지 않고 스트림으로 열어 member SHA256을 읽으면서 갱신하고 strict CP949 `TextIOWrapper`로 csv를 행 단위 처리한다(원천당 58MiB 문자열 중복 보유 금지). ZIP당 CSV member는 정확히 1개만 허용한다.
  - 메모리에는 원문 셀이 아니라 압축된 저장 레코드(slots: source idx, hour int, admin8, grid10, Decimal|None, status int, row digest 32bytes)만 보유한다. 중복 검사는 `(source,hour,admin,grid)` 키 set, 정렬은 전 원천 로드 후 1회 수행한다. dry-run과 write가 같은 레코드 목록·같은 hash 함수를 사용한다.
  - 삽입은 고정 배치(예: 5,000행) executemany 또는 COPY를 같은 트랜잭션 안에서 사용하고, 재조회는 서버 측 커서 fetchmany로 incremental hash한다.
  - 실제 원본 기준 dry-run/write의 최대 RSS와 소요 시간을 측정해 구현 기록에 남긴다. 목표 상한은 1GiB 이하로 두고 초과하면 정렬을 원천별 외부 정렬/DB 정렬로 바꾸는 후속 판단을 기록한다. CI에서는 합성 500,000행 생성 검사를 기본 suite에 넣지 않고 hash·한도 경계는 작은 픽스처와 한도 상수 주입으로 검증한다.
  - 하루 약 53만 행이므로 일별 누적 시 연 약 1.9억 행이다. 이번 범위는 manifest에 명시한 날짜만 적재하며 자동 백필·일괄 기간 적재는 하지 않는다. 다일 적재가 필요해지면 observation_date 파티셔닝·보존 기간·source_row_sha256 BYTEA(32) 전환을 별도 결정한다.
- 관측의 위치 연결은 지정 grid 버전 기준이고 spatial_compatibility는 unverified다. grid_as_of는 현재null이며 관측일/첨부일/내부파일시각/loaded_at과 구분한다. unlocated 행은 spatial inner join에서 제외되고 전역 source/date 범위 미매칭 수만 집계한다. 주야간 비율·반경 지표·세 원천 합산 API는 후속 설계다.

## 6. 커밋·검증 계획

1. docs(be): 사용자 결정·Codex 상세 설계·Claude 실제 수정·Codex 최종 검토.
2. feat(db): 4개 모델·0008·head guard와 제약/FK/GIST/모델/downgrade 테스트.
3. feat(etl): manifest/격자/세 원천 검증·좌표/비식별 보존·원자적/멱등 CLI와 일반/격리 테스트.
4. docs(be): 실행법·출처·실제검증·상태와 사용자 자동 판단 지침, 지정 PR·CI 후 develop 일반 Squash 병합.

합성 일반 검사는 padding/고정공백·3가지 상태/누락 행·Decimal·날짜/24시각·중복·원천누락·ZIP/CRS/형상·manifest·오류 비노출·hash를 확인한다. 격리 PostGIS는 FK/CHECK/복합키·같은 격자 복수행정동/원천 보존·GIST/좌표·미매칭 보존과 공간조인 제외·동시 writer/재실행 불변/새규칙·manifest/저장 행/geometry 훼손 거절·쓰기 후 실패 전체 rollback·READ ONLY dry-run·downgrade 보호·기존 자료 보존을 검증한다. 전체 ruff/format·mypy·일반/격리 회귀를 통과해야 한다.

Claude가 추가한 필수 사례(기존 목록을 구체화하며 실패 시 원인이 하나로 특정되도록 작게 만든다):

- 상태 의미: 같은 키에서 총계 `*`/빈 문자열/`0`/`0.00`/`0.`/`12.`/`12.34`가 각각 suppressed/missing/observed0/observed0/observed0/observed(12.00000)/observed로 저장되고 `*`·빈 값의 population이 null임. `" *"`, `" "`, `"-"`, `"1e3"`, `"1,000"`, `"1_000"`, `"-1"`, `"+1"`, `"NaN"`, `"Infinity"`, `"."`, `".5"`, `"12.."`, `"012"`, `"00"`, `"12. "`, `"12.\n"`, 전각 `"１２"`, 소수6자리, 정수16자리는 전체 거절. 세부 셀의 `12.`도 허용되고 세부 셀의 거절 표기는 전체 거절. `12.`와 `12`는 같은 population이지만 source_row_sha256이 다르고, 후행 소수점 집계 수가 원천별로 맞음. 총계 숫자+세부 `*` 행은 총계 그대로 적재.
- 해시: 고정 입력→고정 hex 벡터, `Decimal("0E-5")`/`Decimal("0")`/DB Numeric 0 재조회가 같은 `"0.00000"`, `*`↔`0` 한 셀 변경 시 content/행 hash 모두 변경, 입력 행 순서 셔플 시 hash 불변, 한글/영문이 섞인 합성 키에서 Python bytes 정렬과 DB `COLLATE "C"` 재조회 hash 일치(격리 DB를 ko 계열 collation으로 만들 수 있으면 그 환경에서도 확인).
- 행정동/키: 같은 격자·시각 2개 행정동 행 보존, 같은 source 내 중복 거절, 다른 source의 같은 키 허용, 공백 4/6개·탭·전각 공백 행정동 코드 거절, 23시각·25시각 원천 거절, 날짜 불일치 거절.
- padding: 장기 7개/단기 9개 빈 열 허용, 개수 ±1 또는 공백 한 칸이 든 padding 거절, 내국인 padding 거절.
- 무결성: located 행의 존재하지 않는 grid FK 위반, unlocated 행에 located_grid_id 지정 시 CHECK 위반, 관측 행 observation_date/grid_version_id가 버전과 다르면 복합 FK 위반, 실제 SHP에 있는 격자를 unlocated로 삽입한 변조를 재검증 쿼리가 거절.
- 원자성: 세 번째 원천 삽입 후·재조회 hash 단계에서 실패 주입 시 신규 grid 버전·관측 버전·행 모두 0건, 동시 writer 2개가 같은 입력이면 하나만 삽입하고 다른 하나는 재사용, 원천 1개 누락 manifest는 DB 접속 전 거절.
- CRS/도형: 5181/5186 PRJ, false easting 변경, 타원체 변경 거절, 5179를 5181로 오해석 시 서울 bbox 검사 실패, 249.999m·회전 사각형·hole·multipart·6점 ring·중복 CELL_ID 거절, 변환 전후 표본 좌표 대조.
- 공간 제외: unlocated 행이 `located_grid_id` 기반 inner join 결과에 0건이고 전역 unlocated 수에는 포함됨.
- 메모리: 실제 원본 dry-run/write의 최대 RSS·소요 시간을 구현 기록에 남긴다(CI 단위 검사 대상 아님).

실제 DB 사전 기존 점포/배치/경계/점포통계/추정매출 버전·관측의 전체 hash/건수 확보 → 일반 앱 계정 0007→0008 → dry-run0삽입 → write → replay(같은 UUID/loaded_at/hash·0삽입), 531,922행·원천별 상태·복수행정동·미매칭24행 보존·geometry변환/원자료20행·모델·기존API200·기존 전체hash/원본 보존을 확인한다. 실제 DB에 파괴적 suite는 실행하지 않는다. 비밀키/FE/API/Docker/환경설정 변경은 없다.

## 7. Claude 검토

이 MD만 Read/Edit로 직접 검토·수정하고 이유·보류사항을 기록한다. 코드·다른 문서·Git 수정은 금지한다. 사용자 1번 결정은 확정이며 유사한 선택은 이 검토로 가장 적절한 안과 근거를 제시한다.

2026-11-12 Claude Code 검토. 이 파일만 Read/Edit로 수정했고 코드·다른 문서·Git·DB·원본 파일은 건드리지 않았다. 사용자 1번 결정(비식별 24행 보존·geometry 미확인·공간 집계 제외)은 다시 묻지 않고 그대로 반영했다. 범위는 BE 적재 전용이며 API/FE/반경·주야간 계산은 추가하지 않았다. 원천에 없는 도형이나 수치는 만들지 않는다.

### 7.1 직접 수정한 내용과 이유

| 항목 | 수정 | 이유 |
|---|---|---|
| 참조 무결성 | 원문 grid_id NOT NULL + nullable `located_grid_id`에 MATCH SIMPLE 복합 FK, 상태와 일치를 강제하는 CHECK, 관측 행→버전 `(id,grid_version_id,observation_date)` 복합 FK | 기존 초안은 미매칭 보존 때문에 격자 FK를 통째로 없애서 located 행까지 DB 무결성이 사라졌다. 이렇게 바꾸면 사용자 결정(가짜 격자 없음)을 지키면서 located 행은 DB가 보장한다. 날짜·격자 버전 불일치도 앱 코드가 아니라 DB가 막는다 |
| PK·테이블명 | 버전별로 하루이므로 PK에서 observation_date를 빼고 버전 FK로 일치를 강제. 테이블명은 `living_population_observations` | 중복 키 열을 줄이고 날짜 일치를 보장한다. 10절의 복수형 테이블 규칙을 따른다 |
| 해시 | canonical JSON 옵션, prefix에 row_count·격자 버전 identity 포함, Decimal은 `format(d,"f")`, 텍스트 정렬은 UTF-8 bytes와 DB `COLLATE "C"`, 원본 기반/저장 geometry hash 분리, input_sha256 구성과 file_date 제외 | 기존 정의대로면 ①`str(Decimal)`의 `0E-5` 표기, ②DB 기본 collation의 정렬 차이 때문에 내용이 같아도 dry-run과 DB 재조회 hash가 어긋날 수 있다. ③PROJ 버전이 바뀌면 변환 geometry hash가 달라져 identity가 흔들린다. 사람이 적은 첨부일이 identity를 바꾸면 안 된다 |
| 메모리 | member 스트리밍 hash·strict 디코딩, 압축 레코드만 보유, 배치/COPY 삽입, 서버 커서 재조회, 실측 RSS 기록과 1GiB 목표, 다일 누적 규모 기록 | 약 53만 행에 원문 셀까지 들고 있으면 메모리가 크게 늘어난다. 정렬 hash에는 전체 키가 필요하므로 압축 레코드 보유가 가장 단순하고 안전한 선택이다 |
| CRS | identify confidence는 보조 근거로만 쓰고, 상수 파라미터 비교·PRJ hash·좌표 범위/서울 bbox·spatial_ref_sys 확인을 판정 기준으로 함. 새 의존성 추가 제한 | confidence 70은 PROJ DB 버전에 따라 달라질 수 있어 재현이 안 된다. 결정적 파라미터 비교와 실제 좌표 근거를 함께 쓰면 5181 오해석도 걸러낸다 |
| 비식별·결측·0 | 셀 원문 그대로 판정, 다른 표기는 전체 거절, 총계 셀만으로 상태 결정, 행 단위 skip 금지 | `" *"`를 trim해 suppressed로 받거나 형식 오류 행만 건너뛰면 결측과 비식별 의미가 조용히 섞인다 |
| 부분 격자 | geometry는 셀 전체이며 행정동별 부분 도형·면적 배분·합산을 하지 않음 | 원천에 없는 부분 도형/배분값을 만드는 것은 금지 범위다 |
| 원자성 | 파일 검증을 DB 쓰기 전에 끝냄, lock key 상수 회귀, 기존 버전과 집계가 다르면 수리 없이 거절, 커밋 1회 | 세 원천 중 일부만 적재되는 상태와 기존 버전 "보충"을 구조적으로 막는다 |
| 테스트 | 6절에 상태·해시·collation·행정동·padding·FK/CHECK·실패 주입·CRS/도형·공간 제외 사례를 구체적으로 추가 | 기존 목록은 범주만 있어서 위 결함(지수 표기, collation, unlocated 변조)을 잡는 사례가 없었다 |

### 7.2 루틴 데이터 처리 선택(사용자 위임에 따른 결정)

- 형식 이상: 행 skip 없이 **전체 거절**한다. 부분 적재보다 재실행이 싸고 원천 의미를 보존한다.
- 숫자 표기: 실제 원본의 `정수.`(소수점 뒤 숫자 0개)는 5절 숫자 문법 v1로 허용하고 그 외 변형은 전체 거절한다(근거 8절).
- `*`/빈 값/0: 원문 표기 그대로 세 상태와 행 없음으로 구분하고 null/0으로 바꾸지 않는다. 후속 집계 API는 suppressed·missing·unlocated 수를 따로 반환해야 하며, 이 셀들을 뺀 합을 완전한 총합처럼 표시하지 않는다(후속 설계 입력 조건).
- 미매칭: 사용자 1번 결정대로 행은 보존하고 located_grid_id=null로 둔다. 가짜 격자나 근사 좌표는 만들지 않는다.
- 행정동 분할: 원천 행을 그대로 두고 합산·배분하지 않는다.
- 재배포·수정 파일: ZIP hash가 다르면 같은 날짜라도 새 버전으로 두고 최신 자동 선택은 하지 않는다.
- 적재 범위: manifest에 적힌 하루만 적재한다. 자동 백필·기간 적재는 하지 않는다.

### 7.3 미확인·보류 사항(구현에서 사실로 단정하지 않음)

1. `*`의 정확한 비식별 임계값과 원천별 설명 차이: 확정하지 않고 원문 보존.
2. 행정동 분할 행의 합이 격자 전체 생활인구인지, 세 원천 합산이 같은 모집단 정의인지: 공식 정의서 대조 전 미확인.
3. 인구값 공식 소수 정밀도: 관측은 2자리, 저장은 5자리 허용·초과 거절. 정의서 확인 후 규칙 버전으로 조정. `정수.` 표기가 원천 생성 과정의 단순 서식인지(예: 소수부 0의 생략) 또는 다른 의미인지는 공식 설명이 없어 미확인이며, 리터럴 십진값 그대로 저장하고 의미를 추정하지 않는다.
4. 격자 SHP의 첨부 수정일·실제 적용일(grid_as_of)과 미매칭 1개 격자가 신규/폐지 격자인지: 미확인, null 유지.
5. pyproj가 현재 잠긴 의존성인지: 구현 시 pyproject/uv.lock을 확인한 뒤 7.1 CRS 규칙에 따라 결정한다.
6. 실제 최대 RSS·소요 시간: 측정 전이며 1GiB는 목표값이지 검증 결과가 아니다.
7. 다일 누적 시 파티셔닝·보존 기간·hash 컬럼 타입: 다일 요구가 생길 때 별도로 결정한다.
8. 이전 작업들의 lock namespace/key 실제 값과 공통 ZIP helper의 스트리밍 지원 여부: 이 검토에서 코드를 읽지 않았으므로 Codex가 구현 전에 확인해야 한다. 스트리밍을 지원하지 않으면 helper를 바꾸지 말고 BE-17/18 회귀 hash가 유지되는 범위에서 확장한다.
9. 공간 지표 연결 시 반경과 격자 교차 기준(교차/중심 포함)과 missing_grid_count 정의: 후속 BE-22/27 설계 범위.

### 7.4 Codex 최종 점검 요청

- 7.1의 복합 FK와 MATCH SIMPLE이 Alembic/GeoAlchemy2 모델로 그대로 표현되는지, 모델 비교 테스트 차이가 0인지 확인한다.
- 해시 정의를 바꿨다면 고정 벡터를 이 문서와 함께 갱신한다.
- 위 미확인 항목을 구현 기록·PR 본문에서 완료로 표시하지 않는다.

### Codex 최종 점검

Claude의 실제 diff와 수정 이유를 기존 코드·원천 사전 검사와 대조했다. 복수형 living_population_observations·nullable located_grid_id와 두 복합 FK·날짜/격자 버전 일치·정렬 C collation·증분 hash·입력 스트리밍·일별 전체 트랜잭션을 채택한다. pyproj==3.7.2와 pyshp==3.1.8은 이미 잠긴 의존성이라 새 파서/의존성은 추가하지 않는다. EPSG 식별 confidence는 참고로 기록하고 기존 pyproj를 사용해 datum/타원체/prime meridian/투영 method·모든 파라미터·축 단위의 결정적 동등성을 검사한다.

격자 raw content hash는 정렬 원본 속성/좌표의 hash, stored hash는 변환된 geometry/속성의 hash로 분리한다. 관측 hash의 UUID·loaded_at·중복 저장 날짜/격자 UUID는 입력에서 제외하며 manifest의 date/grid ZIP hash와 각 행의 위치 연결 상태를 포함한다. 경계부 부분도형·행정동 분할 합산은 만들지 않는다. 249.999m는 ±0.001m 경계의 부동소수 오차에 걸칠 수 있어 테스트는 확실한 오차(예:249.9m)로 거절을 검증한다.

read_csv_member helper는 원문 전체 bytes를 반환하므로 BE-17/18 동작은 그대로 두고 이번 전용 스트리밍 reader를 추가한다. ZIP 압축 bytes는 해시 확인한 한정 buffer로 고정하고(현재 최대15MiB), 해제 CSV는 SHA256/실제64MiB 한도를 가진 RawIOBase·TextIOWrapper로 처리한다. source row hash는 순서가 고정된 헤더와 전체 셀/padding 원문을 hash하므로 공개된 세부 숫자를 별도 적재하지 않는다. 개인정보 복원이나 통계0 치환은 하지 않는다. 사용자 확정 정책과 이 검토 결과로 routine 선택을 확정했으며 같은 질문을 반복하지 않는다.

### 추가 실제 원본 표기 확인·처리안 검토

첫 전체 parser 실행에서 원천 숫자에 `정수.` 형태(소수점 뒤 숫자 0개)가 있음을 확인했다. 총계에 내국인 2,544행·장기 1,089행·단기 1,115행이며 세부 값에도 같은 표기가 있다. 앞뒤 공백·다른 문자·소수6자리 문제는 아니고, 관찰된 숫자 소수 정밀도는 최대2자리다. 합성 형식 예시 `12.`는 Decimal로 정확히12이며 비식별 `*`/빈 값과 다르다.

Codex 제안: 사용자 위임에 따라 `0|양의 ASCII 정수` 뒤 선택 소수점·소수0~5자리만 허용한다. 단 `.` 단독·`.5`·공백·부호·지수/NaN·천 단위 구분자는 계속 거절한다. 저장은 고정5자리 Decimal로 하되 원문 셀 hash는 후행점을 포함해 보존한다. 이 첫 적재 전 발견한 문법을 최종 v1 규칙에 명시하고 기존 버전은 아직 없으므로 소급 변경하지 않는다. Claude가 이 MD를 실제 수정해 판단·근거를 기록한 뒤 코드에 반영한다.

## 8. Claude 검토: 후행 소수점 숫자 표기 결정

2026-11-12 Claude Code가 이 MD만 Read/Edit로 검토·수정했다. 코드·다른 문서·Git·DB·원본은 건드리지 않았고 사용자 1번 결정(미매칭 격자 보존·geometry 미확인·공간 집계 제외)은 다시 다루지 않았다. 사용자 위임에 따라 routine 선택으로 확정한다.

### 8.1 결정

Codex 제안을 **채택하되 문법을 더 좁고 정확하게 고정**했다. 단일 정의는 5절 "숫자 문법 v1"이며 6절 사례·7.2·7.3을 같은 문법으로 맞췄다.

| 항목 | 결정 |
|---|---|
| 허용 | `(0\|[1-9][0-9]{0,14})(\.[0-9]{0,5})?` 셀 전체 fullmatch. `12.`, `0.`, `12`, `12.34`, `0.00000` |
| 거절(전체 적재 실패) | `.`, `.5`, `012`, `00`, `12..`, 소수6자리+, 정수16자리+, 공백·개행·탭, 부호, 지수, NaN/Inf, `_`/`,`, 전각·비ASCII 숫자 |
| 상태 판정 순서 | 원문 `*` → suppressed, 원문 `""` → missing, 문법 v1 일치 → observed, 그 외 → 전체 거절. 이 순서는 기존과 같다 |
| 저장 | `Decimal(cell)`을 고정5자리로 quantize 후 Numeric(20,5). `12.`→`12.00000` |
| 원문 보존 | 원문 셀은 source_row_sha256에 그대로 포함. 원천별 후행 소수점 건수(총계/세부)만 sources JSONB에 기록 |
| 적용 범위 | 총계와 모든 세부 숫자 셀에 같은 문법. rule_version은 v1 그대로(기존 적재 버전 없음, 소급 대상 없음) |

### 8.2 근거

- **값 손실이 없다.** `12.`는 십진수로 정확히 12이며 Decimal도 같은 값으로 읽는다. 반올림·추정·대체가 일어나지 않고, `*`/빈 값과는 문법상 겹치지 않아 비식별·결측·실제0 구분이 그대로 유지된다.
- **표기 차이도 잃지 않는다.** 저장 열은 값의 의미만 담고(`12`·`12.00`과 같은 값), 원문 표기는 이미 정의한 원천 행 hash가 보존한다. 표기 건수를 provenance에 남겨 재배포 파일에서 표기가 바뀌었을 때 감지할 수 있다. 셀 원문을 따로 저장하는 것은 저장 범위 최소화 원칙(7.1)에 어긋나고 얻는 정보가 없다.
- **거절보다 낫다.** 이 표기는 세 원천 모두에서 약 4,700개 총계 행과 세부 셀에 나온다. 거절하면 공식 원천 자체를 적재할 수 없고, 행을 건너뛰면 7.2의 전체 거절 원칙과 충돌한다.
- **문법을 넓히지 않는다.** `.5`·선행0·`.` 단독은 실제 원본에서 확인되지 않았다. 관찰된 표기만 열어야 다른 서식 이상이 조용히 통과하지 않는다. 새 표기가 나오면 전체 거절 후 이 절차로 규칙 버전을 올린다.
- **선행0 거절.** `0.`·`0.50`은 허용하지만 `012`·`00`은 거절한다. 실제 원본에 없고, 코드/식별자 형태가 숫자 칸에 들어온 이상을 잡는 데 도움이 된다.
- **정수 15자리 상한.** Numeric(20,5)의 정수부 한도를 파일 단계에서 강제해 DB 오버플로가 쓰기 도중이 아니라 DB 접속 전 거절로 나타나게 한다(7.1 원자성 원칙). 실제 인구값보다 매우 크므로 정상 자료를 막지 않는다.
- **구현 함정 고정.** Python `re`에서 `$`는 끝 개행 앞에서도 일치하고 `\d`는 유니코드 숫자와 일치한다. `Decimal()`은 앞뒤 공백·`_`·`Infinity`·전각 숫자를 받는다. 따라서 fullmatch와 `[0-9]`로 먼저 검사하고 Decimal은 그 뒤에만 쓴다. 저장 hash 포매터는 기존대로 `format(d,"f")`이며 quantize 덕분에 `12.`도 `"12.00000"`이 된다.

### 8.3 보류·확인 요청

- `정수.` 표기의 원천 측 의미(서식 생략인지)는 7.3-3에 미확인으로 남겼다. 값은 리터럴 그대로 저장한다.
- 실제 원본 기준 원천별 후행 소수점 건수(총계 2,544/1,089/1,115행 + 세부)와 거절 0건을 구현 기록에 남기고, 8.1 문법에 맞지 않는 원본 셀이 0건인지 Codex가 실제 전체 parser로 재확인한다.
- 문법 정규식을 고친다면 5절·6절·8절을 같이 고치고, 고정 hash 벡터에 `12.` 원문 행을 하나 넣어 원문 hash와 저장 hash 차이를 확인한다.

### 추가 Codex 점검

후행점에 대한 Claude의 실제 diff를 읽고 문법·집계·테스트를 반영했다. 세 원천 531,922행 전체 parser가 거절 없이 통과했다. 총계 후행점은 2,544/1,089/1,115행, 세부 후행점은 41,254/2,003/711셀로 sources JSONB에 기록했다. 원문과 고정5자리 값은 별개로 보존하며 기존 저장 버전은 없던 단계의 v1 최종 문법으로 확정했다. 동일 선택을 사용자에게 다시 묻지 않았다.

## 9. 구현·검증 결과 (2026-11-12)

생활인구 전용 모델4개·migration **0008**과 `etl/living_pop` manifest/CSV 스트리밍·격자/CRS 검사·PostGIS 변환·일별 원자적 적재 CLI를 구현했다. 새 의존성/환경변수·공개 API·FE 변경은 없다. 기존 인허가·경계·통계 실행기의 공통 head guard도0008로 갱신했다.

### 자동 검사

- ruff check·format check(**210 files**), `mypy app etl migrations`(**107 files**) 통과.
- 일반 전체 **844 passed**(격리 82 deselected), 별도 임시 PostgreSQL/PostGIS 전체 **82 passed**(일반 844 deselected). 기존 Starlette/httpx 경고1건, skip/xfail/실패는 없다.
- 신규 일반45개는 상태/후행점·명시 문법/범위·복수행정동·padding/고정공백·원천누락/날짜/24시각·ZIP/한도·CRS/변형격자·manifest·오류 비노출·내용 해시를 검증했다. 신규 통합10개는 모델/제약/복합FK·GIST·최대원자성·동시writer·replay/새규칙·저장행/manifest/geometry 훼손 거절·미확인24행 보존/공간조인 제외·위치상태 변조 거절·READ ONLY/timeout·downgrade보존과 기존 조회회귀를 확인했다.
- 고정 증분 hash 벡터(합성1행, 코드의 test_incremental_hash_fixed_vector): `8c57660c707574ee23f2bed55a9015dc5d6c2bd98ef4abae5d6a56361e0250a7`. raw 행 순서 셔플·Decimal0E-5 재조회·규칙/셀 변경은 동일/차이 기대대로 통과했다. 후행점 셀은 값과 원문 hash·집계를 따로 확인했다.
- 모든 Claude 제안별 fixture를 구현했다고 주장하지 않는다. 별도 ko 계열 DB collation 환경·모든 개별 SHP 파손/ZIP 변조 조합은 실행하지 않았으며 SQL C collation·순서/hash·실제 원본 재조회 및 기존 ZIP 회귀를 검증했다.

### 실제 개발 DB

spoton_app의 identity·superuser/DB 생성/role 생성 권한 false·기존 점포689,440건을 확인하고 **0007→0008**을 적용했다. 실제 manifest의 기본 dry-run은 4개 신규 테이블을0행으로 유지했다. write는 **격자 버전1개/10,125행·관측 버전1개/531,922행**을 저장했고 replay는 같은 두 UUID·loaded_at·전체 manifest/hash를 유지하며 **관측/격자 inserted=0**이었다.

| 원천 | 관측 | 숫자 observed | 비식별 suppressed | missing | 좌표미확인 |
|---|---:|---:|---:|---:|---:|
| 내국인 local | 253,400 | 239,543 | 13,857 | 0 | 24 |
| 장기 long | 137,137 | 121,708 | 15,429 | 0 | 0 |
| 단기 short | 141,385 | 112,892 | 28,493 | 0 | 0 |

전체 **531,922행**을 보존했으며 실제0은0건이다. 숫자0/결측/비식별/누락의 구분은 합성·격리 DB에서도 확인했다. 미매칭1개 격자의24행은 모두 suppressed/null이고 공식 도형을 생성하지 않았다. 공식 located 참조 기반 공간 inner join은 **531,898행**, unlocated의 공간 join은 **0행**이다. 복수행정동 격자·시각 그룹 **75,360개**를 보존했다.

원자료 표본 **20행**(각 원천의 숫자행6개와 미매칭 비식별2개)의 총계/상태·정규화 전 전체원문/padding hash를 독립 CSV 읽기로 대조했다. 공식 중심 좌표20개를 별도 pyproj와 PostGIS로 변환해1cm 이내 일치, 변환geometry의 유효성/타입/SRID·모델차이0건을 확인했다. 실제 ST_Covers 쿼리는 planner 강제 없이 GIST를 사용했다. 지연시간 SLA·반경 집계 API를 검증한 것은 아니다.

기존 **8개 테이블**(점포·적재 배치·상권 경계/버전·공식 점포 통계/버전·추정매출/버전)의 전체 행과 geometry를 포함한 hash/건수가 초기 기준과 일치했다. 기존 점포689,440건·경계1,650건·공식 점포 통계24,810행·추정매출14,391행을 보존했다. 원본 ZIP4개의 SHA256도 동일했다. 기존 health/history/nearby/snapshot/data-range API는 모두200이었다.

### 실행 비용과 검증 범위

Windows 로컬에서 전체 원본 검증을 포함한 최초 dry-run **54.75초**, 최초 write **138.15초**, 같은 원본 write replay **82.80초**였다. 실제 Python worker의 OS lifetime peak working set은 최초 write **345.68 MiB**였다. 적재 후 별도 READ ONLY dry-run에서 worker가 직접 측정한 값은 **347.03 MiB / 72.80초**다. venv 실행 중계 프로세스의 약3.9 MiB 값은 worker 메모리가 아니므로 제외했다. 실행 환경에 따른 관측값이며 지연시간/메모리 SLA가 아니다.

실제 검증 범위는 **2026-11-07 하루**이며 여러 날짜 자동 백필·최신 전체 자료 보장·생활인구 API를 완료한 것은 아니다. 격자 적용일은 null, 관측 시점과 경계의 호환은 unverified로 유지한다. 비식별 임계값·행정동 분할의 합산 의미·원천 간 모집단 동일성을 추정하지 않았다. 실제 개발 DB에서 파괴적 integration suite나 downgrade는 실행하지 않고 별도 임시 PostGIS DB에서 검증했다.
