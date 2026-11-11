# BE-16 상권 경계 버전 관리·PostGIS 적재

- 작성일: 2026-11-12
- 이슈: [#47](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/47), 브랜치 `feat#47-market-areas-import`, develop `098b3a7` 기반
- 사용자 승인: 공식 공개 ZIP 직접 다운로드·진행. FE 직접 변경 금지, 자료/권한이 추가로 필요하면 요청, 검사·CI 후 develop 자동 Squash 병합.
- 원본 계약: 데이터 활용 명세 v1.2 D-05/R15·상권 영역, 작업계획 BE-16. 공식 [OA-15560](https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do)은 EPSG:5181·비정기·공공누리 1유형(출처표시)을 안내한다.

## 1. 확보한 자료와 범위

공식 페이지의 공개 다운로드 폼(infId=OA-15560, infSeq=3, seq=5)으로 ZIP을 직접 받았다. 외부 `Downloads/ax/data/raw`에 보관하고 원본은 Git에 넣지 않는다. 2,123,078 bytes, SHA256 `38bb8fab4e45a1171af4989cd7fa1275f68e5d644aa770f5431ce7ccc38384dd`다. SHP/SHX/DBF/PRJ/CPG 각 1개, UTF-8, EPSG:5181, 1,650개 고유 7자리 상권·25개 자치구다. 원본 타입은 A 골목 1,090·D 발달 249·R 전통시장 305·U 관광특구 6개다. multipart 89개·단일 Polygon 내 hole 36개, OGC 무효 6개이며 사전 ST_MakeValid 결과는 모두 유효한 면 도형이었다.

**시간을 섞지 않는다.** 공식 첨부파일 수정일 2023-10-23, 내부 파일 날짜 2023-10-20, 포털 데이터 갱신일 2026-09-11은 서로 다르다. 파일이 최신/과거 어느 분기에 적용되는지는 확인되지 않았다. source_file_date에 첨부 수정일을 기록하고 boundary_as_of=null로 둔다. 업로드/적재 시각을 경계 적용일로 사용하지 않는다. 세 날짜의 의미는 다음으로 고정한다.

| 필드 | 의미 | 이번 값 |
|---|---|---|
| source_file_date | 공식 포털 첨부파일 수정일(관측된 출처 메타데이터) | 2023-10-23 |
| boundary_as_of | 경계가 공식적으로 적용되는 기준일. 출처로 확인될 때만 기록 | null |
| loaded_at | DB 적재 트랜잭션 시각(`timestamptz`, DB 기준). 데이터 시점 아님 | 실행 시 |

ZIP 내부 파일 날짜와 포털 갱신일은 별도 컬럼으로 만들지 않고 이 문서에 관측 기록으로만 남긴다. 어느 값도 boundary_as_of나 분기로 추론하지 않는다. 이번 CLI는 boundary_as_of 입력을 받지 않는다. 이번 작업은 확보된 파일 버전의 경계 기반이며 최신 경계 자동 선택·과거 공식 통계와의 코드 호환·지표/API 구현 완료가 아니다. BE-17/23에서 선택 분기와 상권 코드/경계 호환을 별도 검증해야 한다.

이번 범위: 경계/출처 모델·migration 0005, 로컬 ZIP 검증→공간 정규화→dry-run/원자적·멱등 적재, 실제 개발 DB 검증이다. 기존 stores·공개 API·FE·Docker·로컬 환경설정은 변경하지 않는다. FE 응답 변경이 없어 요청 보고서를 새로 만들지 않는다.

## 2. 저장 구조·버전

`market_area_versions`: version_id UUID PK, source_dataset/source_url, source_file_date DATE, boundary_as_of DATE nullable(이번 실행은 null), input_sha256, input_bytes, source_crs(5181), rule_version, row_count, repaired_count, content_sha256, postgis_version, loaded_at. UNIQUE(input_sha256,rule_version)이며 같은 원본/규칙은 같은 불변 버전을 재사용한다. 같은 해시라도 날짜 등 출처 설명이 충돌하면 덮어쓰지 않고 실패한다. 원본 hash는 제공기관 전자서명을 뜻하지 않는다.

`market_areas`: 복합 PK(version_id,market_code), version FK, market_name, market_type(alley/developed/traditional_market/tourism_zone), market_type_code(A/D/R/U), gu_code(원본 SIGNGU_CD 5자리), area_m2(원본 RELM_AR), source_feature_sha256, geometry_repaired, geom(MULTIPOLYGON,4326). GIST(geom)와 버전/구·유형 조회 인덱스, 면적 양수·타입 대응·유효/비어 있지 않은 geometry 제약을 둔다. 구 코드가 stores의 7자리 관청 코드와 다르므로 직접 같다고 조인하지 않는다.

- 타입: market_code는 숫자형이 아닌 7자리 문자열(CHECK `^[0-9]{7}$`), gu_code는 5자리 문자열이다. A/D/R/U ↔ 원본 라벨 ↔ market_type 대응은 명명된 상수 하나로 관리하고 미지 코드·라벨은 실패한다.
- version FK는 `ON DELETE RESTRICT`다. CASCADE로 버전 삭제 시 경계가 조용히 사라지지 않게 한다. version 행에는 row_count>0, 0≤repaired_count≤row_count, input_sha256/content_sha256 64자리 소문자 hex CHECK를 둔다.
- rule_version은 문자열 상수(예: `market-areas-makevalid-linework-v1`)로 관리한다. 필드 선택·라벨 대응·보정 방법·면적 허용 오차·bbox·hash 직렬화 중 하나라도 바뀌면 값을 올린다.
- source_feature_sha256: 원본 허용 속성(정해진 순서·정규화된 문자열)과 보정 전 원본 CRS 도형 WKB의 hash다. 행별 원본 추적용이다.
- content_sha256: market_code 오름차순으로 최종 허용 속성·geometry_repaired·최종 geom의 `ST_AsEWKB`(NDR) hex를 canonical JSON으로 직렬화한 SHA256이다(키 정렬·고정 구분자·UTF-8). 면적은 Decimal 소수 둘째 자리 문자열로 정규화한다. source_feature_sha256도 같은 직렬화 함수로 허용 속성과 보정 전 원본 CRS EWKB hex를 묶는다. 쓰기 직후·재실행 비교 모두 **DB에서 다시 읽은 값**으로 같은 함수가 계산한다.

기하 면적을 원본 area_m2에 덮어쓰지 않는다. geometry는 Polygon/MultiPolygon·hole·분리 영역을 보존해 MultiPolygon으로 통일한다. 같은 원본의 재실행은 기존 행·버전·loaded_at을 변경하지 않는다. 기존 버전이 훼손되어 행/속성/geometry가 다르면 재실행으로 수리하지 않고 실패한다. 새 ZIP/규칙은 새 버전으로 공존시키며 최신/active로 자동 승격하거나 다른 버전을 삭제하지 않는다. 상권 간 중첩·틈(예: 관광특구와 골목상권의 겹침)은 원본 그대로 보존하며 dissolve·clip·우선순위 정리를 하지 않는다. 우선순위 판정은 7절 기준에 따라 후속 BE-23에서 다룬다.

같은 원본·rule_version이라도 PostGIS/GEOS 버전 차이로 보정·변환 결과가 달라져 content_sha256이 다르면 재사용하지 않고 실패한다(수리·덮어쓰기 없음). 이 경우 원인을 보고하고 rule_version 변경 여부는 사용자 판단 없이 자동 결정하지 않는다.

## 3. 입력·기하 정규화

새 의존성은 MIT의 `pyshp==3.1.8`을 잠그며 기존 pyproj·PostGIS를 재사용한다. [공식 PyShp 문서](https://github.com/GeospatialPython/pyshp)는 ZIP/file-like 및 geo interface를 지원한다. typed stub 없는 import만 좁게 처리하고 실제 런타임 데이터는 명시적으로 검증한다.

- ZIP 크기 최대 32MiB, 압축 해제 합계 최대 64MiB, ZIP CRC·암호화·중복/경로 탐색·sidecar 일치·UTF-8 CPG·PRJ EPSG:5181·SHP Polygon type·DBF/SHP 전체 건수 일치를 검사한다. 디스크 extractall을 하지 않는다. 필수 파일은 shp/shx/dbf/prj/cpg이고 모호한 여러 layer는 거절한다. 압축 해제 크기는 헤더 선언값만 믿지 않고 실제로 읽은 바이트를 누적해 상한을 넘는 즉시 중단한다. 디렉터리·심볼릭 링크·절대 경로·`..`·대소문자만 다른 중복 이름·허용 목록(필수 5종) 밖의 파일은 거절한다.
- PRJ의 EPSG:5181 판정은 pyproj로 WKT를 해석해 EPSG:5181과 동등(CRS 동등 비교 또는 충분한 신뢰도의 EPSG 식별)할 때만 통과한다. 식별 실패나 다른 중부원점 변형(가산값 차이 등)은 5181로 가정하지 않고 실패한다.
- 기대 SHA256은 CLI 필수 인자로 받아 실제 바이트와 대조한다. source_file_date도 필수 ISO 날짜이며 Asia/Seoul 기준 오늘보다 미래인 값은 거절한다. source_dataset/source_url은 고정된 공식 출처다. 원본/숫자/코드/행을 오류·로그로 내보내지 않는다.
- DBF의 실제 절단 필드 TRDAR_SE_C/TRDAR_SE_1/TRDAR_CD/TRDAR_CD_N/SIGNGU_CD/RELM_AR만 업무 필드로 사용한다. 빈 이름/코드·타입/라벨 불일치·중복 상권·지원 밖 구 코드·비유한/0/음수 면적·부적절한 shape/좌표·삭제 DBF 행·라이브러리의 ring 경고는 전체 실패다. 서울 25개 구 전체 집합을 확인해 부분 자료를 적재하지 않는다.
- 허용 유효 좌표/면적과 바인딩된 GeoJSON만 사용한다. ST_IsValidDetail(...,0)으로 OGC 기준을 검사하고 무효이면 [ST_MakeValid](https://postgis.net/docs/ST_MakeValid.html)의 linework 보정을 적용한다. 결과가 Polygon/MultiPolygon 아닌 collection/선/점·빈 면이면 전체 실패한다. CollectionExtract로 잔여 차원을 조용히 버리지 않는다. 보정은 OGC 무효 도형에만 적용하고 유효 도형은 바이트를 바꾸지 않는다(geometry_repaired=false). ST_SnapToGrid·ST_ReducePrecision·단순화·버퍼(0) 등 위상을 바꿀 수 있는 다른 처리는 하지 않는다. 보정 방식은 기본 linework이며 실행 환경의 PostGIS 전체 버전(GEOS 포함)을 버전 행에 남긴다.
- 원본 CRS에서 보정한 뒤 MultiPolygon·EPSG:4326으로 변환하고 비어 있지 않음·최종 유효성·서울권 bbox(126.70~127.25,37.35~37.80)를 다시 검사한다. bbox는 정밀 행정경계 포함 판정이 아니다. 변환 후 무효이면 이번 범위에서 재추정하지 않고 실패한다.
- 보정 여부와 무관하게 모든 행에 대해 보정 후 원본 CRS 면적과 RELM_AR의 상대 차이 1% 초과는 전체 실패다(상수로 관리). 보정된 행은 보정이 면적 일부를 버렸는지를 이 검사로 함께 확인한다. 실제 사전 차이는 최대 약 0.0174%다. 이 검사는 면적 출처 동등성을 주장하지 않는다. 원본 면적/속성·기하 hash·보정 여부를 비교할 수 있게 한다.

## 4. 실행·트랜잭션·안전

예정 명령은 `python -m etl.market_areas --zip PATH --expected-sha256 HASH --source-file-date 2023-10-23 [--write]`다. 기본은 dry-run이며 DB 공간 함수 읽기를 사용하지만 insert하지 않는다. dry-run은 `READ ONLY` 트랜잭션에서 실행하고 끝에 rollback해 쓰기 불가를 DB 수준에서도 보장한다. 성공은 종료 코드 0, 검증·DB 실패는 0이 아닌 코드다. 로컬 .env 설정은 출력하지 않는다. 실제 import/공간 품질 처리는 DB가 필요하므로 연결이 실패하면 후속 큐를 멈춘다.

쓰기 전 기존 validate_local_target/check_local_database로 localhost spoton_dev·spoton_app·일반 권한·PostGIS·head 0005와 stores 유일 제약을 검증한다. 기존 인허가 ETL head guard도 0005로 갱신한다. 모든 원본·기하를 검증한 후 버전과 전체 경계를 한 트랜잭션으로 적재한다. 버전 고유 제약 충돌은 동시 실행/재실행을 조정하고, commit된 버전의 행 수·모든 허용 속성·기하 digest가 일치할 때만 재사용한다. 중간 오류는 버전/행 모두 rollback한다. 라이브 데이터 삭제·임의 부분 성공은 없다.

쓰기 트랜잭션 순서는 다음으로 고정한다.

1. 트랜잭션 시작 → 상권 적재 전용 `pg_advisory_xact_lock` 획득(동시 실행 직렬화).
2. (input_sha256, rule_version)으로 기존 버전 조회. 있으면 출처 설명(source_file_date·source_dataset/url·input_bytes·source_crs) 일치, 행 수, DB 재계산 content_sha256 일치를 확인해 변경 없이 `reused`로 종료한다. 하나라도 다르면 실패한다.
3. 없으면 버전 행 insert → 정규화·변환 결과를 insert. 적재 geometry는 dry-run과 같은 검증을 통과한 바로 그 결과여야 하며, 쓰기 경로에서 검증 없이 별도로 다시 만든 도형을 넣지 않는다.
4. commit 전 DB에서 행 수·보정 수·content_sha256을 다시 계산해 버전 행 값과 대조한다. 불일치는 rollback.
5. 고유 제약/DB 오류는 rollback 후 실패한다. 모든 지원 쓰기 경로는 같은 advisory lock을 사용한다. 락 프로토콜 밖의 경쟁을 숨기기 위한 자동 재시도는 추가하지 않으며 아래 재실행 절차를 따른다.

commit 응답 전 연결이 끊겨 결과가 불명확하면 같은 명령을 재실행한다. 버전이 commit됐다면 2단계 검증으로 재사용되고, 아니면 처음부터 적재된다. 이번 작업에 기존 버전의 UPDATE/DELETE 경로는 만들지 않는다.

출력은 mode·버전 ID/해시 prefix·입력/보정/적재 건수 등 집계만 제공한다. 경계명·코드·원문 좌표·SQL·접속 정보·키를 출력하지 않는다. 광역 geometry는 원본으로 추적하고 버전/라이브러리(실제 PostGIS 전체 버전)를 기록한다. 기존 API의 source/as_of/data_version은 이번 버전을 사용하지 않으므로 바꾸지 않는다.

## 5. 검증·기능별 커밋

1. 설계 MD → Claude Read/Edit 직접 검토 → Codex 실제 diff 확인 후 설계 커밋.
2. 모델·0005·head guard와 모델/스키마/upgrade/downgrade 보존 테스트를 DB 기능 커밋으로 묶는다. 0004 DB에서 ETL write가 거절되는지 확인한다.
3. ZIP·유효성/변환·repository/CLI 및 해당 단위·격리 PostGIS 테스트를 ETL 기능 커밋으로 묶는다. ZIP hash/sidecar/CRC/CRS/삭제·중복/부분 구/잘못된 좌표·shape/ring·면적·속성 실패, Polygon/hole/multipart·bowtie 보정·차원 붕괴 거절·경계 포함/반경 교차·GIST·원자성/멱등/동시 적재·훼손 버전 거절·dry-run 비쓰기·출력 비노출을 검증한다. 합성 작은 원본은 테스트에서 생성한다. 다음 실패·경계 사례도 포함한다.
   - 시간: 미래 source_file_date 거절(Asia/Seoul 경계), 같은 해시·다른 source_file_date 충돌 실패, boundary_as_of=null 유지, loaded_at이 재실행으로 바뀌지 않음.
   - 버전: rule_version만 다른 실행은 새 버전 공존·기존 버전 불변, 버전 삭제 시 FK RESTRICT, CHECK 제약 위반 거절.
   - 원자성: 행 insert 도중 강제 예외 주입 시 버전·행 0건, commit 전 digest 불일치 주입 시 rollback, 두 연결 동시 write에서 버전 1개·두 번째는 reused.
   - ZIP: 선언 크기와 다른 실제 해제 크기(압축 폭탄형), 디렉터리/절대경로/`..`/대소문자 중복/허용 밖 파일, 5181 아닌 PRJ·식별 불가 PRJ.
   - 기하: 유효 도형 바이트 불변, 보정 후 면적 1% 초과, 변환 후 bbox 밖, 빈/NULL shape.
   - 출력: 고유 sentinel 상권명·코드를 넣은 fixture로 stdout/stderr/로그에 노출되지 않음을 확인, 실패 시 0이 아닌 종료 코드.
   - head guard 0005 갱신 후 기존 인허가 ETL이 0005 DB에서 정상 동작하고 0004 DB에서는 거절.
4. 실제 dev identity·0004/689,440건을 확인한 뒤 0005 적용, 원본 dry-run → write → 같은 ZIP replay를 수행한다. dry-run 후 상권 테이블 0건, replay 후 버전 1개·version_id·loaded_at·content_sha256 불변과 `reused` 결과를 확인한다. 0005 downgrade는 격리 DB에서만 검증하고 실제 dev에서는 실행하지 않는다. 예상 1,650행·버전 1개·6개 보정·25개 구·4유형·유효 MultiPolygon4326·면적·unique/FK/GIST·모델 차이 없음을 확인한다. 원본 20건의 속성·좌표/hole·multipart를 독립 pyproj/PostGIS로 대조한다. ST_Covers 경계 포함·ST_Intersects 반경 및 실제 index EXPLAIN을 확인하되 후속 상권 선택 API 구현으로 주장하지 않는다.
5. 원본 불변·원천 ZIP/실제 비밀값 Git 비추적, stores 전체 행/geometry 해시·689,440건과 store_import_batches 출처 보존·기존 API 실동작·회귀를 확인한다. 실제 dev에 파괴적 fixture를 실행하지 않고 별도 임시 컨테이너를 사용한다.
6. 잠긴 의존성의 ruff/format/mypy·기본 pytest·격리 integration·diff/비밀값 검사를 통과한 뒤 BE README/CLAUDE/작업계획·실제 검증 결과를 문서 커밋에 담는다. 문구만 바꾼 뒤 같은 테스트를 반복하지 않는다. 이후 코드 변경/실패가 있으면 해당 검사를 재실행한다.
7. PR 제목 `feat: 상권 경계 버전 관리와 PostGIS 적재 기반 구현`, 지정 본문 close #47. API 변경이 없어 FE·BE CLAUDE 조건부 항목은 해당 없음으로 설명하고 체크한다. CI·병합 조건 후 develop 일반 Squash 병합, 이슈 종료·로컬 최신화. 보호 규칙/본인 승인 제한을 우회하지 않는다.

## 6. 확인 대기·검토 기록

경계 적용 시점과 후속 분기별 통계의 코드/경계 호환은 미확인이다. 이 버전으로 최신/과거 지표를 자동 계산하지 않으며, 공식 출처의 적용 버전 정보가 추가로 필요해지는 지점에서 사용자에게 요청한다. 이번 작업 자체는 작업계획의 D-05 기존 파일 활용 범위에 해당한다. BE-17 이후 원천은 아직 확보한 것으로 표시하지 않는다.

Codex: 실제 공개 ZIP·원본 사전 구조/품질, 기존 모델/migration/검증 규칙을 확인했다. source_file_date와 boundary_as_of를 구분하고 불변 버전 적재만 구현한다. 공개 API와 FE 계약을 바꾸지 않는다.

### Claude Code 검토 (2026-11-12)

검토 범위: 이 MD 한 파일만 Read/Edit로 읽고 직접 수정했다. 코드·DB·원본 ZIP·Git·외부 서비스는 열지 않았다. 1절의 ZIP 크기·SHA256·건수·유형·무효 6개·면적 차이 0.0174% 등 원본 사실은 Codex의 문서 기재를 근거로만 사용했으며 Claude가 독립 검증하지 않았다. 사용자 승인 범위(공개 ZIP 직접 확보, BE 범위, CI 후 develop 자동 일반 Squash 병합)는 유지했고 새 승인 절차나 범위를 추가하지 않았다.

수정 내용과 이유:

1. **버전/시간 의미** — source_file_date·boundary_as_of·loaded_at의 의미를 표로 고정하고 loaded_at을 DB 기준 timestamptz로, 미래 날짜 판정을 Asia/Seoul 기준으로 명시했다. 내부 파일 날짜·포털 갱신일은 컬럼 없이 문서 관측으로만 남기고 어느 값도 적용일로 추론하지 않게 했다. 기존 문서는 세 날짜를 구분했지만 시간대와 CLI 입력 범위가 비어 있어 구현마다 해석이 달라질 수 있었다.
2. **hash·rule_version 정의** — "content_sha256 일치"가 멱등 판정의 핵심인데 직렬화 정의가 없었다. 정렬 키·EWKB 바이트·실수 표현·DB 재조회 기준을 명시하고 source_feature_sha256과 역할을 구분했다. rule_version을 올려야 하는 조건을 적었다.
3. **원자성/멱등** — "고유 제약 충돌은 동시 실행/재실행을 조정"이 구체적 절차 없이 남아 있었다. advisory lock → 기존 버전 검증 재사용 → insert → commit 전 DB 재계산 대조 → 충돌 시 1회 재확인의 순서와, commit 결과 불명 시 재실행 동작을 명시했다. 적재 도형이 검증을 통과한 결과와 같아야 한다는 조건을 추가했다. dry-run은 READ ONLY 트랜잭션으로 DB 수준에서도 쓰기를 막게 했다. version FK는 RESTRICT로 정해 버전 삭제 시 경계가 조용히 사라지는 경로를 없앴다.
4. **PostGIS 버전 차이** — 같은 원본·규칙이라도 GEOS/PostGIS 차이로 MakeValid·변환 결과가 달라질 수 있다. 이 경우 훼손과 같이 실패시키고 덮어쓰지 않게 했다. 재현성 범위는 버전 행의 PostGIS 전체 버전으로 추적한다.
5. **공간 보정 안전** — 보정은 무효 도형에만 적용하고 유효 도형은 바이트 불변, snap/정밀도 축소/단순화/buffer(0)은 금지했다. 면적 1% 검사를 모든 행에 적용해 보정이 면적을 버리는 경우를 잡게 했다. 상권 간 중첩·틈은 보존하고 우선순위 판정은 BE-23으로 남겼다. PRJ 판정이 WKT 문자열 비교·EPSG 자동 추정에 의존하면 다른 중부원점 변형을 5181로 오인할 수 있어 pyproj 동등 비교와 식별 실패 시 거절로 명시했다.
6. **ZIP 안전** — 선언 크기 대신 실제 해제 바이트 누적 상한, 디렉터리·링크·경로 탐색·대소문자 중복·허용 밖 파일 거절을 추가했다.
7. **실패/테스트 누락** — 시간(미래 날짜·같은 해시 다른 날짜), 버전 공존·FK·CHECK, 예외 주입 rollback·digest 불일치 rollback·동시 write, 압축 폭탄형·PRJ 변형, 유효 도형 불변·bbox·빈 shape, sentinel을 이용한 출력 비노출과 종료 코드, head guard 갱신 후 기존 인허가 ETL 회귀를 추가했다. 실제 dev에서는 replay 불변(version_id·loaded_at·hash)과 dry-run 0건을 확인하고 downgrade는 격리 DB에서만 하도록 했다.

보류·확인 대기:

- boundary_as_of와 분기별 공식 통계의 상권 코드/경계 호환은 여전히 미확인이며 BE-17/23에서 판단한다. 이 문서에서 값을 추정하지 않는다.
- ST_MakeValid의 명시적 `method=linework` 파라미터 사용 여부는 실제 dev PostGIS/GEOS 지원 여부에 달려 있어 구현 시 Codex가 확인한다. 기본 호출도 linework이므로 결과 의미는 같으며, 어느 쪽이든 PostGIS 전체 버전을 기록한다.
- 면적 허용 오차 1%·서울권 bbox 값은 설계 상수로 유지했다. 근거는 문서상 사전 최대 차이 약 0.0174%이며 Claude는 원본으로 재확인하지 않았다.
- PR 확인 항목 중 FE·BE CLAUDE 조건부 항목의 "해당 없음" 처리는 API 변경이 없다는 현재 설계 전제에 따른다. BE CLAUDE.md는 6단계 문서 커밋이 실제 반영된 뒤에만 완료로 표시해야 하며, 코드 이해 항목은 기존 작업계획 10절의 사용자 확인 기준을 따른다.
- 포털 갱신일·내부 파일 날짜를 DB 컬럼으로 저장할지는 이번 범위에서 추가하지 않았다. 필요해지면 새 rule/스키마 변경으로 별도 다룬다.

### Codex 최종 점검

Claude의 실제 diff를 기존 코드·공식 문서·사전 DB 검사와 대조했다. 시점 구분·FK RESTRICT·DB 재조회 해시·읽기 전용 dry-run·advisory lock·실제 크기 검사·공간/버전 불변성 테스트는 채택한다. 해시는 길이 접두 대신 canonical JSON으로 모호성 없이 고정하고 DB Numeric(18,2)/NDR EWKB를 같은 함수로 검증한다. 지원 쓰기 경로가 advisory lock으로 직렬화되므로 락 밖 경쟁을 위한 숨은 자동 재시도는 채택하지 않는다. PostGIS 3.7은 linework를 지원하며 source CRS 보정→4326 변환 후 1,650개 모두 유효함을 추가 확인했다. pyshp의 ring 정리 함수(return_errors)를 사용해 경고를 출력하지 않고 모호한 winding/고아 hole을 거절한다. 유효 도형의 원본 CRS 점 배열은 보정하지 않지만 타입 통일/CRS 변환으로 최종 바이트는 바뀌므로 '유효 도형 바이트 불변' 검사는 같은 변환 결과에 추가 수정이 없다는 뜻이다. 라이브러리/엔진 변경으로 결과가 달라지면 실패·진단하며 이번 범위의 필요한 규칙 변경은 근거를 기록해 처리한다. 적용일·후속 분기 호환은 계속 미확인이다.
