# 위치 참고 API 1차 구현·행정동 원천 확보 (#188)

검토·병합된 [#186 설계](feat186-location-reference-display.md)의 **C: 매출 API 연결 + A: 행정동 원자료·경계 확보/대조**를 실행한다. 사용자의2026-11-16 “진행하자” 요청은 검수된 설계의 구현 진행이다. 설계를 반복 작성하는 단계가 아니다.

## 1. 이번 구현 단위

- 새 GET `/api/v2/location-reference`는 기존0012 DB의 상권·매출·점포통계 불변 버전을 내용 지문으로 해석해 같은 READ ONLY RR에서 실제 상권 도형과 검색 점/반경의 관계를 조회한다.
- API 입력은 기존6항목+`time_mode`이며 점포 필터/임의버전/중복인자는 거절한다. 점포 분석 T와 실제 자료분기를 구분한다.
- 금액은 원문 정수의 십진 문자열과 서버표시 문자열이며 월매출/분기총액으로 의미를 바꾸지 않는다. 실제0/null/행부재/코드충돌·중첩상권을 구분한다.
- `latest_reference`는 해당 상권/업종의 최신 유효 숫자행, `analysis_period`는 정확한 분석분기만 사용한다. 예전분기의 충돌행은 제외하되 다른 분기의 유효값까지 버리지 않는다.
- 이번 catalog는 보유2025년 매출1개연도판이다. 새연도판을 추가할 때는 catalog의 복수연도 선택 계약을 확장한다. 구계열/다른개정판을 자동 혼합하지 않는다.
- 아직 없는 행정동 DB표를 조회하지 않고 인구/주야간은 `pending/population_source_not_released`다. 세항목의 화면활성화완료와 구분한다. 행정동 최소4표/ETL/실제공개와 FE카드 연결은 후속구현이다.

## 2. 실제 공식 자료 확보

공개 다운로드를 통해 OA-23016의202610 ZIP과 OA-22160의경계 ZIP을 작업공간 밖 새파일로 확보했다. 원천은커밋하지 않는다. 파일/전체내용은로컬에서만검사하고Claude입력에는형식과집계만전달한다.

| 항목 | 실제 확인 |
|---|---|
| 행정동 내국인 인구 | ZIP35,923,265bytes, 일별CSV31개, 풀림96,006,256bytes |
| 기간/행 | 2026-10-01~31, 317,688행, 하루10,248행, 427코드 |
| 완전성 | 427×31=13,237개 동·날짜에서24시간 observed. 총계의별표/빈칸없음. 전체인구/외국인완전성승인아님 |
| 실제숫자/형식 | 총계소수최대2자리. cp949 CSV, 쉼표header/세미콜론data파일과 쉼표data파일이혼재 |
| 경계 | ZIP1,676,539bytes, shp/shx/dbf/prj/cpg, EPSG5181, UTF-8 DBF, 425도형 |
| 코드대조 | 정확일치422, 인구에만5코드, 도형에만3코드. 차집합을진단에보존 |

공식 [생활인구FAQ](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do)는 행안부10자리의마지막00을제외한8자리코드를설명한다. [경계OA-22160](https://data.seoul.go.kr/dataList/OA-22160/S/1/datasetView.do)도 주민등록행정기관코드를사용한다고설명한다. 같은코드문자열을공간참고연결의근거로삼되, 경계가2026년10월의정확한역사판이라고승격하지않는다. 이번단계는PostGIS의행정동도형유효성/적재검증까지완료한것은아니다.

`python -m etl.admin_population`은 원천2개와각SHA를받아 오프라인검사만한다. 키/DB/환경설정/HTTP/쓰기옵션이없다. ZIP크기/행/필드/정밀도/날짜/중복/코드·유한도형좌표·공식CRS/CPG를검사하고 날짜/코드/상태/차집합만출력한다. 별표/빈칸/실제0을구분하고 세부성연령값을총계에더하지않는다. 부적합파일은고정사유만반환한다.

## 3. 호환성과 구현 파일

새schema/router/service/catalog·실제PostGIS시험·입력검증시험·오프라인원천검사/시험을추가한다. 기존 활동API의null계약, Risk/AI/격자부분비교의날짜규칙, 기존원천행/인덱스/head0012·환경/실행서버는보존한다. 새API는아직없는인구SQL을실행하지않는다.

내용catalog에는입력/content/hash/규칙/행수·참조경계와store내용지문이있고환경별UUID/키/주소/관측원문은없다. 매요청기존세버전의행수/FK/메타와선택행을검사한다. 전체content hash재계산/원천파일재대조는하지않으므로`global_content_rechecked=false`·`source_validation_performed=false`다. 실제원천hash의전수대조/운영원천과의일치와일반API계산검증은구분한다.

커밋단위는①새API+관련시험, ②행정동원천검사+시험/실자료검사, ③문서/실제Claude검토·최종검증기록이다. FE실제변경이나새인구migration을이커밋에몰래포함하지않는다.

## 4. 검증 계획

1. DB전입력검증·실제0/2^53초과문자열·엄격분기·최신유효분기·공간중첩/포함/도형거리·미대응/상한/개정판모호·캐시token/출처·인구SQL0을검사한다.
2. 실제임시PostGIS DB에기존writer로합성버전을적재해catalog를만든다. 현재환경UUID와다른DB에서도지문/FK해석을확인한다. 기존원본에는쓰지않는다.
3. 새원천검사는합성ZIP에서마스킹/누락/0/혼합구분자/정밀도/중복/날짜/부정형·압축/크기·DB미접속/고정오류를검사한뒤실제2개파일과대조한다.
4. 실제로컬DB READ ONLY에서매출결과와DB행을대조하고날짜/공간선택·성능을확인한다. 이는운영배포/FE수치표시성공이아니다.
5. 변경에맞는ruff/format/mypy·전체일반/실제PostGIS검사와정확한head CI를확인한다. 구현후실제Claude MD Read/Edit검토와Codex처리결과를아래에기록한다.

## 5. 실제 Claude 구현 검토

PASS는구현정적검토이며Claude가직접DB/시험/네트워크/배포를수행한것은아니다.

### 5.1 첫 구현 검토

**판정: REVISE** (Claude Opus 5.5, 2026-11-16, 이 MD의 Read/Edit와 사용자가 제공한 소스·시험 본문만으로 한 정적 검토. Claude는 시험·DB·원천 ZIP 검사·네트워크·CI를 실행하지 않았다. §2/§6의 수치는 Codex 보고를 그대로 옮긴 것이며 Claude가 재현하지 않았다.)

**이전 처리 확인:** 이번이 #188 구현에 대한 첫 검토라 §5.2에 확인할 이전 처리 기록이 없다. #186 설계 PASS는 설계 검토였고, 그 PASS로 이 구현 PASS를 대신하지 않는다.

**정적으로 맞다고 확인한 항목(비차단):**
- 입력: 범주 확인 → 알 수 없는 인자/중복 인자 거절 → 모델 검증이 `reference_session`(RR 세션)보다 먼저 실행된다. 잘못된 입력 13종과 중복/누락 시험이 `get_engine` 미호출을 단언한다. OpenAPI 인자 집합이 모델 필드와 같다.
- 버전 해석: catalog 내용 지문(dataset/rule/input/content/row_count) → boundary → store(boundary FK) → sales(boundary·store FK) 순서로 묶이고, content/row_count 불일치·연도·`source_reported`/`unverified`/KRW 메타 불일치·실제 행수 불일치는 고정 500(no-store, 내부 문구 미노출)로 끝난다. 환경 UUID를 catalog/응답에 넣지 않는다.
- 공간: 도형별 `ST_Covers`(점 포함)와 geography `ST_Distance <= radius`(도형거리)를 쓰고 중심점이나 가장 가까운 상권 대체는 없다. 겹치는 상권은 각각 별도 item이고 합산하지 않는다. 구멍이 있는 도형도 PostGIS 술어 의미상 구멍 안의 점은 `contains_point`가 아니다(다만 시험은 없음, B3).
- 금액: 정수형 확인, 0~2^63-1 범위, 십진 문자열, `exact_zero`, `원` 표시가 서로 맞는지 schema가 확인한다. 2^53 초과값과 실제 0이 PostGIS 시험에서 그대로 유지된다. 월/분기 환산은 없다.
- 시간: `analysis_period`는 `S.quarter == desired`만 사용한다. `latest_reference`는 분기 내림차순으로 정렬한 뒤 일치하고 숫자인 첫 행을 고르므로, null인 최신분기는 건너뛰고 충돌행은 제외하면서 다른 분기의 유효값은 유지한다(코드상).
- 인구: `UnreleasedPopulation` 고정 placeholder이고 인구 SQL이 0건임을 statement 관찰 시험으로 확인한다. 0012 밖 표를 참조하지 않는다.
- 상한: 상권 100 / 상권×업종 500 / 원천행 50,000(+1 조회)이 있고 모두 `scope_too_large`로 끝난다. 응답·meta에 좌표/UUID/원천 레코드가 없다. token은 응답 직렬화 hash이고 `global_content_rechecked=false`로 전체 hash 재계산을 주장하지 않는다.
- 오프라인 검사기: SHA 확인 뒤 ZIP 크기 상한, 선언 압축해제 총량, 암호화/디렉터리/중복 이름 거절, 파일명 fullmatch(경로 이탈 차단), 행 단위 날짜·시간·코드·중복키·정밀도 확인, 별표/빈칸/0 구분, 부분 행을 전체 인구로 세지 않음(`population_total_validated=false`), `geometry_validated_by_postgis=false`. 키·DB·HTTP 경로가 없다.

**차단 지적**

- **B1 — null/행부재/충돌 사유를 구분한다는 계약이 실제 응답에서 지켜지지 않는다.** §1은 "실제0/null/행부재/코드충돌을 구분한다"고 쓰지만 `_sales`의 item 사유는 (a) 일치 행은 있으나 `est_sales`가 null인 경우와 (b) 행이 없는 경우를 모두 `no_source_rows`(latest) 또는 `no_data_in_analysis_period`(strict)로 같게 낸다. `Reason`에 null 전용 값이 없다. 블록 사유도 모든 item이 `mapping_conflict`거나 섞여 있어도 항상 `no_source_rows`/`no_data_in_analysis_period`가 된다. 고칠 것: `source_value_null` 같은 사유를 추가해 item·블록에 반영(블록은 원인이 섞이면 대표 사유와 `excluded_counts`/사유별 개수로 표시)하고 null-only/행부재/전부충돌 시험을 추가한다. 아니면 §1 문구를 실제 동작에 맞게 줄인다. 계약을 넓히는 쪽을 권장한다.
- **B2 — "부적합파일은 고정사유만 반환" 주장이 경계 파서에서 성립하지 않는다.** `inspect_boundary`는 `CRS.from_wkt`의 `pyproj.exceptions.CRSError`(RuntimeError 계열), 잘린 shp/shx/dbf를 읽을 때 pyshp가 낼 수 있는 `struct.error`/`IndexError`/`AttributeError`/`TypeError`를 잡지 않는다. CLI도 `SourceInspectionError`/`OSError`만 잡는다. 이런 오류가 나면 traceback과 원천 일부(WKT 등)가 들어간 예외 문구가 stderr로 나가고 고정 JSON이 출력되지 않는다. 인구 경로의 `_bounds`처럼 IndexError가 의도한 분류 밖으로 나갈 수 있는 곳도 같다. 고칠 것: 검사 함수 경계에서 파싱 예외를 모두 `fail()`로 바꾸고(최소한 CRSError, struct.error, IndexError, TypeError, AttributeError 포함), CLI는 마지막 방어선으로 모든 예외를 고정 JSON으로 바꾼다. 깨진 .prj와 잘린 .shp/.dbf 합성 시험을 추가한다.
- **B3 — §4.1·§4.3에서 검사한다고 적은 핵심 경로에 시험이 없다.** 제공된 34+5 시험에 다음이 없다. (a) `mapping_conflict`: 최신분기 충돌행은 제외하고 이전 분기 유효값은 유지하는 경우와 전부 충돌하는 경우(§1의 핵심 주장). (b) 개정판 모호(`ambiguous_source_version`, 같은 지문 2행). (c) 버전 메타는 맞지만 실제 행이 빠진 경우의 행수 불일치(현재 시험은 version.row_count만 바꿔 `_resolve` 경로만 탐). (d) 겹치는 두 상권과 구멍 있는 도형(구멍 안 점은 `intersects_radius`이고 `contains_point`가 아님). (e) 한 ZIP 안에서 `;` 파일과 `,` 파일이 섞인 경우(현재는 단일 파일만 매개변수화). 고칠 것: 위 시험을 추가하거나, 추가하지 못한 항목은 §4/§6에서 "미검사"로 정정한다. 코드를 읽으면 (a)(c)(d)는 맞게 동작할 가능성이 높지만, 실행으로 확인한 것은 아니다.

**비차단 지적**

- **N1** §3 "첫실행은…검사"는 실제와 다르다. `_versions`는 **매 요청** 세 버전의 메타·FK·`COUNT(*)`를 검사한다(더 강한 쪽). 문구를 고치고, `source_validation_performed=false` 이름이 이 요청별 검사와 헷갈리지 않게 의미(원천 파일 hash 재대조 아님)를 문서화한다.
- **N2** `_bounds`가 `int(quarter[4])`를 길이 확인보다 먼저 실행한다. 길이 5 미만이면 IndexError가 나며, 이는 `get_location_reference`가 잡는 예외 종류 밖이다. 길이와 형식을 먼저 확인한다.
- **N3** catalog JSON 원문은 이번 검토에 제공되지 않아 2025 지문 내용은 확인하지 못했다. `Path(__file__).with_name(...)` 방식이라 wheel/Docker 패키지 데이터에 JSON이 포함되는지 확인해야 하고, 파일이 없을 때의 `FileNotFoundError`(OSError)는 고정 500/no-store 경로 밖이다. 패키징 포함 확인이나 `importlib.resources` 사용, OSError 매핑을 권장한다.
- **N4** `latest_reference`의 상한이 서버 로컬 `date.today()`에 의존한다. KST 기준 clock을 주입하면 시험 가능성과 재현성이 좋아진다(현재 단일 2025판에서는 결과 영향 없음).
- **N5** item 단위로 "이 쌍에서 충돌행이 제외됐다"는 표시가 없다(블록 `excluded_count`만 있음). 겹치는 상권 item을 합산하면 안 된다는 meta(예: `items_additive=false`)를 두면 FE의 오용을 막는다.
- **N6** `ST_Covers`(geometry 4326 평면)와 geography 거리(구면)가 경계 근처에서 드물게 다르게 판정할 수 있다. 또 `A.geom::geography` 캐스트 때문에 geometry GIST 인덱스를 쓰지 못할 수 있다. 현재 규모(0.235s)는 괜찮지만 bbox 사전필터 또는 geography 식 인덱스를 고려한다.
- **N7** 검사기의 범위를 명시할 것: 성·연령 28열은 길이 외에는 검사하지 않음(문서의 "필드 검사" 범위), 31개 파일 날짜가 같은 월이고 연속인지는 출력만 하고 강제하지 않음, shp 도형 수·dbf 레코드 수 일치·고리 닫힘/방향·EPSG5181 서울 좌표 범위는 미검사. PostGIS 적재 전 단계(B/D)에서 보완한다.
- **N8** 같은 (version, market, industry, quarter) 중복 행이 없다는 가정에 기대므로 0012의 유일 제약을 확인하거나 중복을 `mapping_conflict`로 처리한다.
- **N9** OpenAPI에 500(no-store, 고정 코드) 응답이 문서화되어 있지 않다.

**범위 확인:** 행정동 4표/적재/FE 연결과 외국인 포함 전체 인구 완전성을 이번 단계에 요구하지 않는다. 부분 원천 행을 전체 인구로 세지 않은 점, 인구 migration/SQL이 0건인 점은 범위에 맞다. B1~B3을 처리하고 §5.2에 처리 내용을 기록하면 재검토(§5.3)에서 PASS를 판단한다.

### 5.2 Codex 처리

실제첫구현검토는11:22:16Z~11:24:57Z/exit0/is_error=false/3turns였다. 대상MD직접변경·전달소스보존·권한거절0을확인했다. REVISE의차단3건을다음과같이채택했다.

- B1: `source_value_null`/`no_source_rows`/`mapping_conflict`를분리하고블록에`reason_counts`와혼합결측사유를추가했다. 충돌원천행수는item에, 영향을받은상권·업종쌍수는블록에구분했다. 원자료null전용/행부재/전부충돌/유효이전분기보존을실제PostGIS로확인했다.
- B2: CRSError/struct/IndexError/TypeError/AttributeError/압축파싱예외를고정사유로바꾸고CLI최외곽도Exception을고정JSON으로처리한다. 손상prj/shp/dbf와의도적최외곽예외의원문/traceback미노출시험을추가했다. KeyboardInterrupt/SystemExit같은BaseException은삼키지않는다.
- B3: 실제중첩/구멍도형, 동지문중복(폐기용DB에서만UNIQUE제거), 버전메타를유지한실제행삭제, 최신분기충돌/이전유효값, ZIP내쉼표/세미콜론파일혼재시험을추가했다. 보완후새단위47개/실제PostGIS10개가통과했다.

권고 N1~N5: 매요청검사와플래그뜻을수정했고분기형식을인덱싱전에검사한다. catalog읽기OSError도고정500이다. 실제wheel을빌드해JSON포함을확인했고Dockerfile은app을복사한뒤동일wheel로설치한다. KST기준주입가능`_today()`를사용하고`items_additive=false`와item별제외행수를추가했다.

N6은이번인덱스변경을보류했다. 기존1650개/실제로컬최대0.235초로현재합격선을만족하며geometry/geography술어의근접경계차이와캐스트의GiST효과는향후자료증가시측정한다. DDL/새인덱스로이번범위를확장하지않는다. 반경최소300m이며양쪽술어의실제의미를그대로표시한다.

N7: 성연령값은총계와합산/재검증하지않고`age_fields_validated=false`다. `coverage_basis=file_members_only`로연속월완전성을증명하지않는다. SHP/DBF개수일치는추가검사했고고리/서울좌표범위/역사경계·PostGIS위상검증은후속적재단계의검증이다.

N8: 실제폐기용DB에서market_sales의4열PK를확인했다. N9: 기존공통`VALIDATION_ERROR_RESPONSES`에500선언이이미있으므로OpenAPI응답500회귀를추가해확인했다. API코드를중복수정하지않았다.

전체PostGIS첫실행은317통과/경로목록검사1실패였다. 새route를기존통합시험의ENDPOINTS에추가했고보완본전체검사를다시진행한다. 초기일반2551통과/권한3skip수치는보완전실행이며최종결과와구분한다.

### 5.3 재검토

**판정: PASS** (Claude Opus 5.5, 2026-11-16, 구현 정적 재검토. 근거는 이 MD의 Read/Edit와 사용자가 제공한 보완 후 소스·시험 본문뿐이다. Claude는 시험·DB·PostGIS·원천 ZIP 검사·wheel 빌드·네트워크·CI를 실행하지 않았다. 47/10개 시험 통과, 실제 15지점·212값 대조, 0.235초, wheel의 catalog 포함, 공식 ZIP 수치는 모두 Codex 보고를 옮긴 것이며 Claude가 재현하지 않았다. 이 PASS는 진행 중인 보완 후 전체 일반/전체 PostGIS 시험과 정확한 head CI 통과를 대신하지 않는다. 그 실제 결과가 §6에 기록되기 전에는 병합 완료로 보지 않는다.)

**§5.2 처리 확인(제공 소스 기준)**

- **B1 — 해소.** `Reason`에 `source_value_null`/`mixed_unavailable_reasons`가 추가되었다. item 사유는 전부 충돌하면 `mapping_conflict`, 선택된 행이 있으면 None, 일치 행이 있지만 숫자 행이 없으면 `source_value_null`, 아니면 모드에 따라 `no_data_in_analysis_period`/`no_source_rows`로 갈린다. 블록은 사유가 하나면 그 사유, 여럿이면 `mixed_unavailable_reasons`를 쓰고 `reason_counts`의 합이 사유 있는 item 수와 같음을 schema가 확인한다. `test_null_value_and_absent_row_have_distinct_reasons`와 `test_latest_conflict_preserves_older_matching_value_and_all_conflicts_have_reason`이 null만 있는 경우/행부재/전부충돌/이전분기 유효값 유지를 실제 PostGIS 경로로 단언한다.
- **B2 — 해소.** `inspect_boundary`/`inspect_population`이 CRSError·struct.error·IndexError·TypeError·AttributeError·RuntimeError·zlib error·BadZipFile·csv.Error를 `fail()`로 바꾼다. CLI 최외곽은 `Exception`을 고정 JSON으로 바꾸고 BaseException은 통과시킨다(적절하다). 손상된 prj(canary 문자열 포함)/shp/dbf와 최외곽 RuntimeError 시험이 고정 사유, 빈 stderr, canary 미노출을 단언한다.
- **B3 — 해소.** (a) 최신분기 충돌 시 20253을 고르고 `excluded_source_rows=1`이며 전부 충돌하면 `mapping_conflict`, (b) 폐기용 DB에서만 UNIQUE를 지운 뒤 같은 지문의 boundary 2행이면 `pending/ambiguous_source_version`, (c) 메타는 그대로 두고 실제 행만 지운 경우 고정 500/no-store, (d) 겹치는 두 도형과 구멍 도형(구멍 안 점은 `intersects_radius`, 고리 안 점은 둘 다 `contains_point`), `items_additive=false`, (e) 한 ZIP 안의 `;` 파일과 `,` 파일 혼재. 제공된 시험 수를 세면 단위 47개(16+8+18+5), 통합 10개(5+5)로 §5.2의 수와 같다.
- **N1 해소:** §3이 매 요청 검사로 고쳐졌고 두 false 플래그의 뜻이 적혀 있다. **N2 해소:** `_bounds`가 인덱싱 전에 fullmatch로 확인하고 6가지 잘못된 형식 시험이 있다. **N3 해소(일부 보고 의존):** OSError/ValidationError가 고정 500/no-store로 연결되고 canary 시험이 있다. wheel 포함과 Dockerfile 설치 경로는 Codex 보고이며 Claude는 확인하지 않았다. catalog JSON 원문은 이번에도 제공되지 않았다. **N4 해소:** KST `_today()`가 있다. 다만 별도 인자 주입이 아니라 monkeypatch 가능한 함수이고, 미래 분기 제외 시험은 없다(N3' 참조). **N5 해소:** item별 `excluded_source_rows`, 블록 `excluded_counts_scope`, `items_additive=false`가 있다. **N6 보류 수용:** 현재 규모와 측정치로 보아 DDL을 추가하지 않는 판단은 범위에 맞다. **N7 해소:** `age_fields_validated=false`, `coverage_basis=file_members_only`, `numRecords == numShapes` 검사가 있다. **N8 해소:** 시험에서 4열 PK를 단언한다. **N9 해소:** 공통 응답에 500이 있고 OpenAPI 회귀 시험이 있다.

**이번에 다시 정적으로 확인한 항목**

- 참조 지리·날짜·통화·업종: 금액은 `KRW_source_reported`, `amount_period_status=unverified`, 월/분기 환산 없음, 업종은 고정 5코드와 원문 업종명 일치를 요구한다. 상권 유형 코드와 이름이 도형 행과 맞지 않으면 충돌로 제외한다. 경계 호환성은 `unverified`로 표시한다.
- 공간: 도형별 `ST_Covers`와 geography 도형거리 `<= radius`만 쓴다. 중심점, 가장 가까운 상권 대체, 합산은 없다. 상권이 없으면 `no_spatial_overlap`과 빈 items를 낸다.
- 시간: strict는 `quarter == desired`만 쓰고, latest는 KST 현재분기 이하에서 분기 내림차순으로 일치하는 숫자 행 중 첫 행을 고른다.
- 버전 바인딩: content/row_count/FK/연도/basis/currency 메타와 세 표의 실제 COUNT를 매 요청 확인하고, 불일치하면 고정 500/no-store로 끝난다. 응답 meta에는 UUID, 좌표, 원천 레코드가 없고 token은 응답 직렬화 hash이며 `global_content_rechecked=false`다.
- 입력 검증 → RR READ ONLY 세션 순서, 상권 100/상권×업종 500/원천행 50,000 상한, statement_timeout이 있다. 인구는 0012 밖 표를 조회하지 않는 placeholder다.
- 오프라인 검사기: SHA → 크기 → 선언 압축해제 총량 → 행 단위 검사 순서다. 별표/빈칸/0을 구분하고, 5자리 넘는 정밀도는 반올림 없이 거절하며, 중복 키는 거절한다. 부분 행을 전체 인구로 세지 않고 PostGIS 도형 검증을 했다고 주장하지 않는다.

**차단 지적:** 없음.

**비차단 지적(후속 또는 병합 전 문서 정리)**

- **N1' — 블록 `partial` 의미가 넓다.** 모든 item이 `ready`여도 어느 쌍에서 충돌행이 하나라도 제외되면 블록이 `partial/partial_source_rows`가 된다. 선택에 영향을 주지 않은 더 오래된 분기의 충돌도 그렇다(시험도 이를 기대값으로 고정함). FE가 "일부 값 없음"으로 오해할 수 있으므로, 후속에서 `source_rows_excluded` 같은 별도 사유를 두거나 이 의미를 계약 문서에 명시한다.
- **N2' — 헤더만 있는 CSV 파일이 조용히 통과한다.** 데이터 행이 없는 일별 파일은 실패하지 않고 `dates`에서 빠질 뿐이다(`coverage_basis=file_members_only`이므로 거짓 주장은 아니다). 후속 적재 단계에서는 빈 파일, 31일 연속성, 같은 월 여부를 실패 조건으로 둘 것을 권장한다.
- **N3' — 다음 분기 경로는 시험이 없다(코드 읽기로는 맞음):** `MAX_DETAILS`/`MAX_SOURCE_ROWS` 상한, store·sales 단계의 개정판 모호, `_today()` 기준 미래 분기 제외, `analysis_period`에서의 충돌. 인구 SQL 0건 시험은 표 이름 문자열 관찰에 의존하므로 표 이름이 바뀌면 약해진다.
- **N4' — 매 요청 COUNT(*) 세 번:** 점포통계 표가 커지거나 연도판이 늘면 비용이 선형으로 늘어난다. N6과 함께 자료가 늘 때 측정하고, 필요하면 같은 RR 안에서 버전별 캐시로 바꾼다(정확성 근거는 유지할 것).
- **N5' — 매핑 밖 예외 몇 가지:** `_resolve`에서 같은 지문 2행 중 하나만 content가 다르면 `ambiguous`가 아니라 500이 된다(fail-closed라 수용 가능). `source_file_date`/`loaded_at`이 nullable이면 AttributeError가 고정 매핑 밖으로 나가 공통 미처리 오류 middleware에 맡겨진다. 모델 정의는 이번에 제공되지 않아 확인하지 못했다.
- **N6' — 문서 정리:** §6은 아직 "일차검사 34/5"와 "Claude검수 진행중"이라고 적혀 있다. 보완 후 47/10, 이 재검토 PASS, 그리고 보완본 전체 일반/전체 PostGIS/CI의 **실제** 결과(실패가 있으면 그대로)로 갱신해야 한다. 행정동 경계의 기간 판본과 PostGIS 도형 유효성은 여전히 미검증 상태로 남겨 둔다.

**범위 확인:** 행정동 4표/적재/조회, FE 카드, 외국인 포함 전체 인구 완전성, 새 migration은 이번 단계에 요구하지 않으며 완료로 표시하지도 않았다. 인구/주야간은 `pending/population_source_not_released`이고 인구 SQL은 0건이다. 부분 원천 행을 전체 인구로 세지 않았다. 매출 수치 API(C)와 행정동 원천 확보·오프라인 대조(A)라는 이번 구현 단위에 대해 정적 PASS다.

## 6. Codex 검증 결과와 다음 경계

최종Claude재검토는11:31:00Z~11:33:11Z/exit0/is_error=false/3turns, MD직접변경·전달소스17개SHA보존·권한거절0으로PASS/차단0이었다. 차단해소에이견없으며권고를다음처럼정리했다.

- N1': 모든item이ready여도과거충돌행제외로블록partial일수있음을FE계약에명시했다.
- N2': 오프라인검사는빈일별파일/일자누락을coverage완전성으로승격하지않는다. 후속실제적재는빈파일/기대기간·일자완전성을추가검사해야한다.
- N3': MAX_DETAILS/원천행상한·store/sales모호·미래분기필터·엄격분기충돌의추가개별분기시험은후속보강이다. 현재지원범위100상권×4업종·단일연도4분기에서는정상유일키로각각최대400명세/1600원천행이다. 기존상한과DB유일키방어를유지하며기존시험/실측범위를넘어검증했다고쓰지않는다.
- N4': 자료가커지면COUNT비용/공간계획을다시측정한다. 현재정확성검사를캐시로생략하지않는다.
- N5': 실제0012모델의source_file_date와loaded_at은NOT NULL이다. 정상스키마에서는없을수없는값이며모델/제약손상은정상결측으로취급하지않는다.
- N6': 아래결과로초기34/5·검수진행중표기를최종보완본실행과구분했다.

| 검사 | 보완본 실제 결과 |
|---|---|
| 새단위/API/원천 | 47통과 |
| 새실제PostGIS | 10통과 |
| 전체일반 | 2564통과/Windows권한기존3skip, 통합323deselected |
| 전체실제PostGIS | 323통과/no skips |
| ruff/format/mypy | 통과/474files/196sourcefiles |
| 실제원천/로컬읽기 | 15지점모두수치존재·212금액/공간관계일치. 보완뒤재실행warm15회최대0.218초 |
| 엄격과거분기 | 2023년11월분기의자료없음정상. 최신참고의실제2025분기는분리표시 |
| 실제2개ZIP | 새검사기로재검증, 317688행/13237완전동·날짜/422정확코드일치 |
| 패키지 | 실제wheel안catalogJSON포함확인, Docker설치경로검토 |
| 운영사전읽기 | 원천지문/0012/기존reader SELECT일치, 기존17환경SHA보존확인. 배포성공을뜻하지않음 |

위성능은현재로컬상태측정이며공급자/콜드/운영SLA보장이아니다. 검수PASS·원천확보·로컬검증과정확한head CI/실제운영배포는구분한다. 실제CI/통합·운영반영기록은연결PR/이슈에추가한다. 이번단계에서DB DDL/DML·FE·로컬.env/키·기존로컬서버/원천/사용자파일을바꾸지않았다.

원천확보·수치API구현과FE표시·행정동인구DB연결은구분한다. 인구/주야간의대표값을제공하려면후속B/D(행정동4표/적재/조회)가필요하다. 이번결과를세항목화면활성화완료로표시하지않는다.
