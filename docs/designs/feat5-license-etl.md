# 작업 5: 인허가 데이터 수집·정제 ETL 기반

## 상태와 범위

- 이슈: [#15 인허가 데이터 수집·정제 ETL 기반 구현](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/15)
- 브랜치: `feat#5-license-etl`, 대상 브랜치: `develop`
- 공식 원천:
  - [지방행정 인허가 일반음식점 API](https://www.data.go.kr/data/15154916/openapi.do)
  - [지방행정 인허가 휴게음식점 API](https://www.data.go.kr/data/15154921/openapi.do)
- 이번 작업은 BE-08의 수집·정제·변환·멱등 upsert 기반과 검증까지 구현한다.
- 실제 운영·개발 DB에 원천 전체를 적재하지 않는다. 단위 테스트는 합성 응답을 사용하고 DB 검증은 CI의 폐기되는 임시 PostGIS에서만 수행한다.
- BE-09 `building_key`와 BE-10 `floor_unit`, 주소·좌표 보완 API, 삭제 동기화, 스케줄러, API/FE 변경은 제외한다.
- `DATA_GO_KR_SERVICE_KEY`가 없는 로컬 환경에서도 import·단위 테스트·정적 검사가 모두 동작해야 한다. 실제 키가 필요한 실원천 호출은 이번 완료 조건이 아니다.
- 중단 규칙: 아래 「중단 조건」 중 하나라도 해당하면 PR과 이후 큐를 진행하지 않는다. 영구 개발 DB 적재가 필요해지는 단계에서도 멈추고 실제 개발 DB 연동 작업을 별도로 먼저 수행한다.
- 상위 계약 우선: `stores` 컬럼명·타입·nullable·enum 값·유일 제약은 작업 4에서 확정된 모델과 migration이 기준이다. 이 설계의 필드명이 그와 다르면 이 설계를 따르지 않고 작업 4 계약에 맞춘다. 이번 작업에서 migration을 추가·수정하지 않는다.

## 원천 계약 확인 결과와 변경 대응 규칙

2026-11-10 구현 전 공식 자료를 확인했다.

- 두 data.go.kr API의 내장 Swagger 1.0.0에서 HTTPS host, `/info`, `serviceKey`·`pageNo`·`numOfRows`·`returnType`, `cond[OPN_ATMY_GRP_CD::EQ]`, 최대 100건, `response.header/body`, 허용 목록 필드와 날짜 형식을 확인했다.
- 공공데이터포털 공식 공지 `NOTICE_0000000004824`의 `개방자치단체코드_영업상태코드_행정체제개편반영_20260702.xlsx`에서 서울 25개 구 코드와 영업상태 코드 01~06을 확인했다.
- 공식 공지 `NOTICE_0000000004566`의 `지방행정 인허가정보_업종별 업태구분명_20260727신규.xlsx`에서 일반·휴게음식점의 공식 업태명을 확인했다.
- 두 API 상세 설명이 원 좌표계를 `EPSG:5174`로 명시하므로 이번 구현은 해당 CRS를 사용한다.
- 공공데이터포털 공통 결과 코드표의 `00`만 성공으로 인정한다. HTTP 200이어도 다른 코드나 XML 오류 본문이면 실패한다.

확인한 문서명·버전·갱신일과 URL은 `constants.py` 상단 주석과 커밋 2 본문에 기록한다. 이후 공식 계약이 바뀌면 아래 원칙을 적용한다.
- 단위 테스트 fixture는 공식 문서의 출력 예시 구조를 그대로 본뜬 합성 데이터로 만든다. 실제 응답을 fixture로 커밋하지 않는다.
- 공식 문서로 확정되지 않는 항목은 임의 값으로 확정하지 않고 다음 중 하나로 처리한다.
  - 해석 보류: 값을 `None`으로 두고 결정적인 플래그를 남긴다(상태·업종·날짜·좌표).
  - 계약 검증: 런타임에서 가정이 깨지면 고정 분류 코드의 계약 오류로 중단한다(envelope·페이지네이션·관청 필터).
  - 중단: 위 두 방식으로 안전하게 처리할 수 없으면 해당 커밋 전에 멈추고 사용자에게 보고한다.
- 문서상 필수 필드(최소 `MNG_NO`, `OPN_ATMY_GRP_CD`)가 페이지의 모든 행에서 키 자체가 없으면 개별 행 거절이 아니라 스키마 변경으로 보고 계약 오류로 중단한다. 허용 목록 밖의 추가 필드는 무시한다.

## 설계 원칙

### 1. 공식 API 클라이언트

- 일반음식점은 고정 호스트 `https://apis.data.go.kr/1741000/general_restaurants`, 휴게음식점은 `https://apis.data.go.kr/1741000/rest_cafes`의 `/info`를 사용한다. 엔드포인트는 코드 상수이며 환경변수·인자로 바꿀 수 없다.
- 사용자 입력 URL은 받지 않는다. `serviceKey`, `pageNo`, `numOfRows=100`, `returnType=JSON`과 관청 필터만 요청에 사용하고 서울 25개 인허가 관청 코드를 `cond[OPN_ATMY_GRP_CD::EQ]`로 각각 조회한다. `numOfRows`가 공식 최대값을 넘지 않는지 확인한다.
- `httpx`를 런타임 의존성으로 이동하고 동기 클라이언트를 주입 가능하게 만들어 `httpx.MockTransport` 기반의 네트워크 없는 단위 테스트를 지원한다. `follow_redirects=False`, HTTPS 고정으로 서비스 키가 다른 호스트로 전달되지 않게 한다.
- 서비스 키는 디코딩된 값 하나만 받아 httpx가 1회만 인코딩하게 한다(이중 인코딩 금지). 키는 설정 객체에서 `SecretStr` 등 repr 마스킹 타입으로 보관하고, 키가 없으면 import 시점이 아니라 수집 실행 시점에 고정 메시지의 설정 오류를 낸다.
- connect/read/write/pool timeout을 유한하게 설정한다. 429와 일시적 5xx(502·503·504)·전송 오류만 최대 3회 재시도하며 지수 지연 상한(예: 30초)과 전체 재시도 예산을 둔다. `Retry-After`는 상한 이내에서만 따른다. sleep 함수는 주입 가능하게 해 테스트에서 실제 대기하지 않는다.
- 인증·계약·기타 4xx 오류와 일일 트래픽 초과 결과 코드는 재시도하지 않는다. 공식 결과 코드 `00`만 성공으로 보고, 표에 없거나 알 수 없는 결과 코드는 재시도 없이 계약 오류로 처리한다.
- data.go.kr은 HTTP 200이면서 XML 오류 본문(인증키 미등록 등)을 반환할 수 있다. JSON 파싱 실패·`Content-Type` 불일치·XML 본문은 원문을 남기지 않고 고정 분류 코드(`non_json_response`)로 중단한다.
- 예외·로그·테스트 실패 메시지에 요청 URL 전체, query string, 서비스 키, 원문 응답, 행 단위 상호·주소·관리번호를 포함하지 않는다. 오류에는 source, 관청 코드, page, 고정 분류 코드, HTTP 상태만 남긴다.
  - httpx/httpcore 로거는 INFO에서 요청 URL(쿼리 포함)을 기록하므로 ETL 실행 중 해당 로거를 WARNING 이상으로 제한하고, 테스트에서 DEBUG 수준 caplog로 키 비노출을 검증한다.
  - `httpx.HTTPStatusError`·`RequestError`의 문자열에는 URL이 포함되므로 그대로 전파하지 않고 ETL 예외로 감싸며 `raise ... from None`으로 원인 체인을 끊는다.
- HTTP 상태와 공식 응답 header 결과 코드를 모두 확인한다. 예상 envelope·rows·totalCount·pageNo 형식이 아니면 고정된 ETL 계약 오류로 중단한다. `totalCount`·`pageNo`는 음이 아닌 정수 또는 정수 문자열만 허용한다. rows가 단일 객체로 오는 경우는 공식 문서가 그 형태를 명시할 때만 1건 리스트로 정규화한다.

#### 페이지네이션 종료 규칙(관청 코드 × source 단위)

- 1페이지의 `totalCount`를 기준값으로 고정하고 `max_pages = ceil(totalCount / numOfRows)`를 계산한다. `totalCount=0`이면 빈 결과로 정상 종료한다.
- 정상 종료는 누적 행 수가 `totalCount`와 정확히 같아진 때뿐이다.
- 다음 경우는 모두 계약 오류로 중단하며 일부 수집 결과를 성공으로 반환하지 않는다.
  - `totalCount`에 도달하기 전에 빈 페이지가 오거나, 마지막이 아닌 페이지의 행 수가 `numOfRows`보다 적음
  - 한 페이지 행 수가 `numOfRows` 초과, 누적 행 수가 `totalCount` 초과
  - 응답 `pageNo`가 요청 값과 다름, 수집 중 `totalCount` 변경
  - 요청 페이지가 `max_pages`를 넘음(무한 반복 방지 상한)
  - 응답 행의 `OPN_ATMY_GRP_CD`가 요청한 관청 코드와 다름(필터가 무시된 것으로 보고 전국 데이터 순회를 막기 위해 즉시 중단)
- 한 source의 25개 관청을 모두 성공적으로 수집·검증한 뒤에만 DB 쓰기 단계로 넘어간다. 수집 중 하나라도 실패하면 해당 실행은 DB에 아무것도 쓰지 않는다.

### 2. 입력 허용 목록과 개인정보 최소화

- 원천 JSON 전체를 저장하지 않고 아래 필드만 불변 DTO로 읽는다.
  - 식별·관청: `OPN_ATMY_GRP_CD`, `MNG_NO`
  - 상호·주소: `BPLC_NM`, `ROAD_NM_ADDR`, `LOTNO_ADDR`
  - 상태: `SALS_STTS_NM`, `SALS_STTS_CD`, `DTL_SALS_STTS_NM`, `DTL_SALS_STTS_CD`
  - 업태·면적: `BZSTAT_SE_NM`, `SNTTN_BZSTAT_NM`, `LCTN_AREA`, `FCLT_TOTAL_SCL`
  - 날짜: `LCPMT_YMD`, `CLSBIZ_YMD`
  - 좌표: `CRD_INFO_X`, `CRD_INFO_Y`
  - 증분 판정 보조: `DAT_UPDT_SE`, `DAT_UPDT_PNT`, `LAST_MDFCN_PNT`
- 전화번호, 홈페이지, 대표자 등 서비스에 불필요한 필드는 DTO·로그·DB·리포트 어디에도 보존하지 않는다. DTO는 원천 dict를 필드로 보관하지 않고, 파싱 직후 원천 dict 참조를 버린다.
- 상호(`BPLC_NM`)는 개인 이름일 수 있으므로 DB 컬럼 외에는 로그·예외·리포트에 쓰지 않는다.
- 문자열은 양끝 공백과 빈 문자열만 정규화한다. 주소·상호의 의미를 임의로 고치지 않는다. 숫자·문자열 혼용 응답(예: 숫자로 온 관리번호)은 문자열로 받아 동일하게 정규화한다.

### 3. 서울 필터와 중복 제거

- 공식 첨부자료에서 확인한 서울 25개 인허가 관청 코드와 자치구 매핑(종로구 `3000000`부터 강동구 `3240000`까지의 실제 구별 목록)을 코드 상수로 관리하고 출처를 주석으로 남긴다.
- 상수 무결성은 테스트로 고정한다: 정확히 25개, 코드·자치구명 모두 중복 없음, 모든 값이 확인된 형식(자릿수·숫자)과 일치.
- 작업 4의 `stores.gu_code`는 별도 enum·외래키 계약이 없는 nullable 문자열이므로 이번 범위에서는 공식 `OPN_ATMY_GRP_CD`를 그대로 저장한다. 향후 행정동·법정동 코드가 필요하면 별도 컬럼·migration 계약으로 다루며 이번 ETL에서 암묵 변환하지 않는다.
- 요청 필터와 별개로 응답의 `OPN_ATMY_GRP_CD`를 허용 목록과 다시 대조한다. 요청 코드와의 불일치는 위 페이지네이션 규칙대로 계약 오류이고, 허용 목록 밖 코드는 `rejected_non_seoul`로 집계한다(서울시 본청 등 자치구가 아닌 서울 관청 코드도 이번 범위에서는 거절).
- 주소 문자열에 `서울`이 들어 있는지만으로 서울 여부를 판단하지 않는다.
- `MNG_NO`가 없으면 적재하지 않고 거절 건수로 집계한다.
- 중복 키는 `(source, MNG_NO)`이다. 중복 제거는 DB 쓰기 전에 source 전체(25개 관청 수집 결과 합계)에 대해 수행한다. 같은 INSERT 문에 동일 키가 두 번 들어가면 PostgreSQL `ON CONFLICT DO UPDATE`가 실패하므로 chunk 분할 전에 반드시 끝낸다.
- 선택 규칙(결정적): ① 해석 가능한 `DAT_UPDT_PNT`가 최신인 행 ② 다음으로 해석 가능한 `LAST_MDFCN_PNT`가 최신인 행 ③ 해석 불가 시각은 가장 오래된 것으로 취급 ④ 그래도 같으면 정제된 행의 정규 직렬화 문자열이 사전순으로 가장 큰 행. API 응답 순서는 실행마다 같다는 보장이 없으므로 수집 순번을 결정 기준으로 쓰지 않는다.
- 시각 문자열은 공식 문서에 명시된 형식만 엄격히 파싱하고 타임존이 없으면 `Asia/Seoul`로 해석한다. 형식을 확정할 수 없으면 ①②를 건너뛰고 ④만 적용한다.
- `DAT_UPDT_SE`(갱신 구분)의 의미는 해석하지 않는다. 삭제를 뜻하는 값처럼 보여도 행을 제외하거나 `deleted_at`을 바꾸지 않고, 값별 건수만 리포트에 집계한다.
- 서로 다른 source의 동일 관리번호는 서로 다른 점포 레코드로 허용한다.

### 4. 날짜·상태·면적 정제

- 공식 Swagger에 명시된 `YYYYMMDD`만 엄격히 파싱한다. 여러 형식을 관대하게 추측 파싱하지 않는다.
- 빈 값은 `None`(플래그 없음), 형식 오류·존재하지 않는 날짜(예: `20230230`, `00000000`)는 `None`과 `open_date_invalid`/`close_date_invalid` 플래그로 변환한다.
- 해석 가능한 개업일이 `1960-01-01`보다 이르면 원 날짜를 유지하되 `open_before_1960` 플래그를 부여한다(`1960-01-01`은 플래그 없음).
- 미래 날짜 판정 기준일은 주입 가능한 clock의 `Asia/Seoul` 기준 오늘이다. 테스트는 고정 clock을 사용한다. 미래 개·폐업일은 `open_date_future`/`close_date_future`, 폐업일이 개업일보다 빠르면 `close_before_open` 플래그를 남긴다.
- 플래그는 고정된 코드 집합(상수 enum)에서만 생성하고 중복 제거 후 사전순으로 정렬해 저장한다. 플래그 저장 컬럼과 형식은 작업 4 `stores` 계약을 따른다.
- `/meta/data-range`에서 이상 날짜를 제외하는 처리는 후속 API 작업의 책임이며 이번 ETL은 판별 근거를 제공한다.
- 상태는 공식 `SALS_STTS_CD` 표에 따라 `01`(영업/정상) → `open`, `03`(폐업) → `closed`, `02`(휴업)와 `04`~`06` → `other`로 매핑한다. 상세영업상태 코드는 업종마다 체계가 달라 단독 판정 근거로 쓰지 않는다.
- 상태 코드와 상태명이 대응표와 모순되면 `other`와 `status_mismatch` 플래그, 코드가 없으면 `other`와 `status_missing` 플래그를 남긴다. 알 수 없는 상태를 영업 중으로 추정하지 않는다.
- 원 상태 코드는 `status_code`에 보존한다(작업 4 계약에 상세 코드 컬럼이 없으면 상세 코드는 저장하지 않는다).
- `closed`인데 폐업일이 없거나 `open`인데 폐업일이 있으면 `status_date_inconsistent` 플래그를 남긴다. 상태를 날짜로 덮어쓰지 않는다.
- 면적은 음수가 아닌 유한 Decimal만 `area_m2`로 사용한다. `LCTN_AREA`를 우선하고 없을 때만 `FCLT_TOTAL_SCL`을 사용하며 해석 실패·음수·NaN·Infinity는 `None`과 `area_invalid` 플래그로 둔다. `0`은 유효 값으로 보존하되 의미 해석은 하지 않는다. 컬럼 정밀도를 넘는 값은 DB 오류가 나기 전에 정제 단계에서 `None`과 플래그로 처리한다.
- 한시적 사업장 여부를 공식 필드에서 확정할 수 없으므로 `is_temporary=None`으로 둔다. 근거 없이 `False`로 만들지 않는다. 작업 4 계약상 이 컬럼이 NOT NULL이면 임의 값을 넣지 않고 중단한다.

### 5. 업종 매핑

- 매핑 입력은 공식 Swagger와 업태 첨부자료가 정의한 `SNTTN_BZSTAT_NM`(위생업태명) 하나로 고정한다. `BZSTAT_SE_NM`은 업태 판정에 사용하지 않고 `bzstat_nm`에도 `SNTTN_BZSTAT_NM`을 저장한다.
- 비교는 양끝 공백 제거 후 완전 일치만 사용한다. 부분 문자열·키워드·상호명 기반 추정은 하지 않는다.
- `category`/`sub_category` 값은 작업 4 `stores` 계약의 허용 값과 일치해야 하며, 아래 값이 그 계약에 없으면 새 값을 만들지 않고 중단한다.
- 일반음식점은 정확히 확인된 원천 업태명만 매핑한다.
  - `한식` → `restaurant` / `korean`
  - `중국식` → `restaurant` / `chinese`
  - `일식` → `restaurant` / `japanese`
  - `경양식` → `restaurant` / `western`
- 휴게음식점의 `커피숍`만 `cafe` / `cafe`로 매핑한다.
- 분식·치킨·주점·제과점·기타 및 키워드 후보는 자동 포함하지 않는다.
  - 명시적 제외 목록(상수)에 있는 업태: `category=None`, `sub_category=None`, `category_review_flag=False`
  - 명시적 검토 목록(`기타` 등)에 있는 업태, 매핑·제외·검토 어느 목록에도 없는 미지의 업태, 업태 누락: 두 category를 `None`, `category_review_flag=True`
  - 세 목록은 서로 겹치지 않음을 테스트로 고정한다.
- 대상 외 업태 행도 점포 원천 레코드로 upsert한다(category만 `None`). 대상 업종만 적재하도록 거르는 것은 이번 범위가 아니다.
- `seoul_induty_cd`는 공식 서울 상권 업종 코드 대응표가 확정되기 전까지 `None`으로 둔다. 임의 코드를 만들지 않는다.

### 6. 좌표 보존과 변환

- 원본 `CRD_INFO_X/Y`는 양끝 공백만 제거한 문자열 그대로 `raw_x`, `raw_y`에 보존하고 둘 중 하나라도 있으면 `raw_crs`를 기록한다.
- 두 공식 API 상세 설명이 원 좌표계를 `EPSG:5174`로 명시하므로 `SOURCE_CRS="EPSG:5174"`로 고정하고 출처 URL을 코드 주석에 남긴다.
- 변환은 `Transformer.from_crs(SOURCE_CRS, "EPSG:4326", always_xy=True)`를 사용한다. PROJ 네트워크 그리드 다운로드는 끄고(`pyproj.network` 비활성) 결과가 실행 환경에 따라 달라지지 않게 한다. `pyproj` 버전은 의존성에 하한을 고정한다. Transformer는 스레드 간 공유하지 않는다.
- 변환 정확도는 공식 문서·공공 기준점 등 출처가 있는 대응 좌표 1개 이상으로 허용오차(예: 5m 이내) 테스트를 둔다. 출처 있는 기준 좌표를 확보하지 못하면 「단순히 서울 경계 안에 들어온다」는 테스트만으로 정확도를 주장하지 않고, 이를 잔여 위험으로 PR에 명시한다.
- 두 값이 모두 유효한 유한 숫자인 경우에만 변환한다. 변환값이 서울 검증 경계 안이면 `lng`, `lat`, SRID 4326 `POINT`, `coord_source="localdata"`를 채운다.
- 서울 검증 경계는 행정 경계가 아니라 오탐을 거르는 거친 사각형 상수(경도 약 126.76~127.19, 위도 약 37.41~37.72에 소폭 여유)이며, 자치구 일치 여부는 검사하지 않는다.
- 아래 경우는 원본만 유지하고 `lng`/`lat`/`geom`/`coord_source`는 `None`, `coord_flag`에 고정 코드 하나를 기록한다: `coord_missing`(둘 다 없음), `coord_partial`(하나만 있음), `coord_non_numeric`, `coord_non_finite`(NaN·Infinity), `coord_zero`(x 또는 y가 0 이하), `coord_transform_failed`(예외 또는 비유한 결과), `coord_out_of_seoul`. 판정 순서는 이 나열 순서로 고정한다.
- 좌표 보완은 후속 작업이다. 이번 작업에서 카카오·행안부 주소 API를 호출하지 않는다.

### 7. Store 변환과 upsert

- `source`는 `general_restaurant` 또는 `rest_cafe`(작업 4 계약의 source 값과 일치 확인), `license_no`는 `MNG_NO`, `gu_code`는 검증된 관청 코드 또는 3절의 대응표로 변환한 값으로 고정한다.
- `building_key`, `floor_unit`, `location_level`, 가맹 관련 필드와 `deleted_at`은 이번 변환에서 채우지 않으며, upsert의 갱신 대상에서도 제외해 후속 작업이 채운 값을 덮어쓰지 않는다.
- 배치 시작 때 생성한 UUID를 모든 레코드의 `batch_id`에 사용한다.
- `ON CONFLICT (source, license_no)`는 작업 4 migration에 해당 유일 제약(또는 유일 인덱스)이 있을 때만 사용한다. 없으면 이번 작업에서 migration을 추가하지 않고 중단한다. 통합 테스트로 제약 존재를 확인한다.
- PostgreSQL `INSERT ... ON CONFLICT (source, license_no) DO UPDATE`를 사용한다. 갱신 컬럼은 코드 상수 허용 목록(정제 컬럼, `batch_id`, `updated_at=now()`)으로만 구성한다. PK와 생성 시각, 위의 후속 작업 컬럼은 덮어쓰지 않는다.
- 모든 값은 바인드 파라미터로 전달하고 SQL 문자열에 값을 이어 붙이지 않는다. 컬럼명은 상수 허용 목록에서만 온다.
- geom은 `ST_SetSRID(ST_MakePoint(lng, lat), 4326)`으로 만든다(경도, 위도 순서). 좌표가 `None`이면 geom도 `NULL`로 쓴다(이전 실행의 geom을 남기지 않는다).
- 쓰기는 source 단위로 하나의 트랜잭션에서 chunk(예: 1,000행) 단위 실행한다. 중간 실패 시 해당 source 전체를 롤백한다. 동시 실행은 지원하지 않으며 `pg_advisory_xact_lock`으로 같은 source의 동시 쓰기를 막는다.
- 멱등의 정의: 같은 입력을 두 번 적재해도 행 수와 정제 컬럼 값이 같다. `batch_id`·`updated_at`은 마지막 실행 값으로 바뀌는 것이 정상이다.
- repository는 연결(엔진/세션)을 반드시 인자로 주입받는다. 기본 `DATABASE_URL`이나 개발 DB 설정을 스스로 읽어 쓰는 경로를 만들지 않으며, 이번 작업에는 실제 DB에 쓰는 CLI·엔트리포인트를 만들지 않는다.
- 원천에서 사라진 레코드를 즉시 삭제·soft delete하지 않는다. 삭제 의미와 전체 스냅샷 완결성이 공식적으로 확인되기 전에는 `deleted_at`을 변경하지 않는다.
- 실행 결과는 source별 fetched, accepted, rejected_missing_key, rejected_non_seoul, duplicates, transformed, inserted_or_updated, `DAT_UPDT_SE` 값별 건수, flag별 건수를 포함하되 상호·주소·관리번호·원문을 포함하지 않는 리포트로 반환한다. `fetched = accepted + rejected_missing_key + rejected_non_seoul`, `accepted = transformed + duplicates` 관계를 단위 테스트로 검증한다.

## 모듈 구조

```text
etl/
├─ localdata/
│  ├─ __init__.py
│  ├─ client.py       # 안전한 HTTP·pagination·응답 계약
│  ├─ constants.py    # source·endpoint·서울 25개 코드
│  ├─ dto.py          # 허용 목록 원천 DTO
│  ├─ normalize.py    # 날짜·상태·업종·면적·좌표 정제
│  ├─ pipeline.py     # 수집→필터→dedupe→Store row 변환
│  └─ repository.py   # PostgreSQL 멱등 upsert
tests/
├─ etl/
│  ├─ test_localdata_client.py
│  ├─ test_localdata_normalize.py
│  ├─ test_localdata_pipeline.py
│  └─ test_localdata_security.py
└─ integration/
   └─ test_localdata_upsert.py
```

구현 중 책임이 더 명확해진다면 파일은 합치거나 나눌 수 있지만, HTTP·순수 정제·DB 쓰기 경계는 유지한다. CLI와 스케줄러는 이번 범위가 아니다.

## 테스트 계획

### 단위 테스트

- 모든 단위 테스트는 `MockTransport`와 주입 sleep/clock을 사용하며 실제 네트워크·실제 대기·실제 DB에 접근하지 않는다. 서비스 키 환경변수가 없는 상태에서 import와 전체 단위 테스트가 통과해야 한다.
- 두 source의 endpoint와 고정 page size, 요청 query에 허용된 파라미터만 있는지, 2페이지 이상 수집, `totalCount=0`, 정확히 `numOfRows` 배수인 totalCount 종료를 검증한다.
- 계약 오류 종료: totalCount 도달 전 빈 페이지, 중간 짧은 페이지, 행 수 초과, pageNo 불일치, totalCount 변경, max_pages 초과, 요청과 다른 관청 코드 응답, 필수 키 전체 누락이 각각 고정 분류 코드로 실패하고 요청 횟수가 상한 이내인지 검사한다.
- 429·502/503/504·전송 오류의 제한 재시도(횟수·지연 상한·Retry-After 상한)와 401/403·기타 4xx·트래픽 초과·미지 결과 코드·계약 오류의 즉시 실패(재시도 0회)를 검증한다.
- HTTP 200 + XML 오류 본문, 깨진 JSON, 단일 객체 rows(문서 명시 여부에 따른 처리), 정수 문자열 totalCount를 검사한다.
- 서비스 키·query·원문 개인정보가 예외 문자열, `repr`, `__cause__`/`__context__` 체인, traceback 문자열, caplog(httpx/httpcore 포함 DEBUG 수준)에 노출되지 않는지 고유 canary 값으로 검사한다. 리다이렉트 응답을 따라가지 않는지도 확인한다.
- 서울 관청 상수 무결성(25개·중복 없음·형식), 25개 요청, 응답 재검증, 비서울 거절, 누락 관리번호 거절, source 전체 기준 중복 제거와 최신 갱신 선택, 시각 동률·해석 불가 시 결정적 선택(입력 순서를 섞어도 같은 결과)을 검사한다.
- 날짜 경계(1959-12-31/1960-01-01, 고정 clock 기준 미래, 역전, 존재하지 않는 날짜, malformed), 상태 대응표·미지 코드·코드명 모순·상태와 폐업일 불일치, 면적 음수·0·비수치·NaN/Infinity·정밀도 초과를 검사한다.
- 지원 업태와 제외·검토·미지 업태가 계획대로 매핑되고, 두 업태 필드 불일치 시 검토 처리되며, 카페 키워드·상호 기반 추정이 일어나지 않는지 검사한다. 매핑·제외·검토 목록이 겹치지 않음을 검사한다.
- 좌표 원본 보존, EPSG:5174 정상 변환(출처 있는 기준점 허용오차), 일부 누락, 비수치, 0, NaN, 변환 후 서울 밖, 플래그 판정 순서, (lng, lat) 순서를 검사한다.
- raw DTO·변환 결과·리포트에 전화번호·홈페이지·대표자 필드가 존재하지 않고, 리포트에 상호·주소·관리번호가 없는지 검사한다. 리포트 건수 항등식을 검사한다.

### 실제 PostGIS 통합 테스트

- 기존 임시 DB 안전장치와 migration fixture를 재사용한다. 안전장치가 임시 DB임을 확인하지 못하면 skip이 아니라 실패한다. 개발·운영 DB URL로는 실행되지 않아야 한다.
- `(source, license_no)` 유일 제약 존재와, 이번에 `None`으로 쓰는 컬럼의 nullable 여부를 확인한다.
- 같은 `(source, license_no)`를 두 번 적재해 행 수가 늘지 않고 정제 값·batch_id·updated_at이 갱신되는지 확인한다. 미리 채워 둔 `building_key`·`floor_unit`·`deleted_at`·생성 시각이 upsert 후에도 유지되는지 확인한다.
- 좌표가 있던 행을 좌표 없는 값으로 재적재하면 geom이 `NULL`이 되는지 확인한다.
- 같은 license_no라도 source가 다르면 두 행이 존재하는지 확인한다.
- chunk 경계를 넘는 입력과 중간 실패 시 source 단위 롤백을 확인한다.
- 변환한 geom의 SRID가 4326이고 `ST_X=lng`, `ST_Y=lat`인지 확인한다.
- 테스트는 skip·xfail 없이 실제 실행되어야 한다. CI junit 검사는 전체 1건 이상이 아니라 `test_localdata_upsert.py`의 테스트가 설계된 개수 이상 실행되었고 그중 skipped/failure/error가 0인지 확인한다(작업 4의 기존 통합 테스트만으로 게이트가 통과하지 않게 한다). CI에서 DB 환경변수가 없으면 skip이 아니라 실패해야 한다.

## 기능별 커밋 계획

| 순서 | 커밋 | 범위와 게이트 |
|---|---|---|
| 1 | `docs(be): 인허가 ETL 설계와 Claude 검토 기록` | 본 설계 MD, Claude 직접 검토·수정 완료 |
| 2 | `feat(etl): 지방행정 인허가 API 수집기 구현` | runtime 의존성, 상수·DTO·안전한 pagination/retry, 클라이언트·보안 단위 테스트 통과 |
| 3 | `feat(etl): 인허가 데이터 정제와 점포 변환 구현` | 서울 필터·dedupe·날짜·상태·업종·면적·좌표 정제, 순수 단위 테스트 통과 |
| 4 | `feat(etl): stores 멱등 upsert 구현` | repository와 실제 PostGIS 통합 테스트, 기존 migration 검증 포함 |
| 5 | `docs(be): 인허가 ETL 검증 결과 정리` | 실행법·범위·검증 SHA/CI 기록, 전체 로컬 검사와 branch CI 성공 |

- 각 기능 커밋 전에 해당 범위의 테스트를 통과시킨다.
- 원천 계약·서울 코드·상태 코드·업태 필드·좌표계는 위 공식 자료로 확인했다. 커밋 4 전에 작업 4 `stores` 계약(유일 제약·nullable·enum)을 코드와 migration에서 다시 확인한다.
- 커밋 4 push 후 branch CI의 `lint-and-test`, `postgis-integration`을 확인하고 실패·skip이면 수정 후 재검증한다.
- 커밋 5 push 후 최신 head의 모든 필수 CI가 성공해야만 지정 양식으로 develop 대상 PR을 만든다. 성공 확인은 최신 head SHA 기준이어야 하며 이전 커밋의 성공 결과를 재사용하지 않는다.

## 중단 조건

아래 중 하나라도 해당하면 해당 단계에서 멈추고 PR·이후 큐를 진행하지 않으며 사용자에게 사유를 보고한다.

1. 구현 중 실제 공식 계약이 위 확인 결과와 달라 안전한 계약 검증으로 처리할 수 없다.
2. 공식 서울 25개 관청 코드가 변경되었거나 응답 관청 필터가 무시되는 것이 확인된다.
3. 작업 4 `stores` 계약에 `(source, license_no)` 유일 제약이 없거나, 이번에 `None`으로 둘 컬럼이 NOT NULL이거나, source·category 허용 값이 이 설계와 맞지 않아 migration 변경이 필요하다.
4. EPSG:5174 변환의 출처 있는 기준점 검증을 통과하지 못하거나 변환 결과가 서울 경계를 체계적으로 벗어난다.
5. CI `postgis-integration`이 실패하거나, `test_localdata_upsert.py` 테스트가 skip·xfail·미실행이거나, junit 게이트가 이 파일의 실행을 확인하지 못한다.
6. 검증에 실제 개발·운영 DB 쓰기나 원천 전체 적재가 필요해진다.
7. 키·URL·원문·개인정보 비노출 테스트를 통과시킬 수 없다.

## 완료 조건

1. Codex 설계 후 Claude Code가 이 MD만 직접 검토·수정했고 검토 기록이 남아 있다.
2. 공식 두 source를 안전하게 페이지 수집하고 허용 목록 밖 개인정보를 보존하지 않는다.
3. 서울 필터·중복 제거·정제 플래그·업종·좌표 변환이 결정적이며 단위 테스트가 통과한다.
4. 임시 실제 PostGIS에서 stores upsert가 멱등이고 geom이 정확하며 `test_localdata_upsert.py` skip이 0이다.
5. ruff check, ruff format --check, mypy, 기본 pytest와 최신 head 기준 branch CI 두 job이 모두 성공한다.
6. 실제 개발 DB에 적재하지 않았고 실원천 전체 호출을 하지 않았음을 문서와 PR에 명시한다.
7. 검증 근거를 기록한 뒤에만 PR을 생성한다. PR 확인 사항 네 항목은 사용자 확인 원칙에 따라 `[x]`로 작성하되, 각 항목이 실제로 검증된 경우에만 작성하며 검증되지 않은 항목이 있으면 PR을 만들지 않고 중단한다.

## Claude Code 검토 기록

- 검토일: 2026-11-10
- 검토 범위: 이 파일만 읽고 직접 수정했다. 코드·다른 문서·Git·셸은 읽거나 실행하지 않았다. 따라서 작업 4 `stores` 모델·migration, 공식 활용가이드와의 대조는 하지 않았고 구현 단계의 확인 항목으로 남겼다.

### 주요 수정

1. **원천 계약 확정 규칙 신설**: 필드명·필터 문법·envelope·결과 코드·날짜 형식·상태 코드표·좌표계를 공식 확인 전까지 후보 계약으로 보고, 확인 불가 항목은 해석 보류(None+플래그)·계약 검증(오류 중단)·중단 중 하나로 처리하도록 했다. 필수 키 전체 누락은 스키마 변경으로 보고 중단한다.
2. **페이지네이션 종료 규칙 강화**: 기존의 "다음 페이지가 비어 있으면 종료"는 totalCount 미달 상태의 잘린 수집을 성공으로 받아들일 수 있어, 정상 종료를 "누적=totalCount"로만 한정했다. 빈/짧은 페이지·pageNo 불일치·totalCount 변경·max_pages 초과·요청과 다른 관청 코드 응답(필터 무시 시 전국 순회 방지)을 계약 오류로 지정했고, source 전체 수집 성공 전에는 DB에 쓰지 않도록 했다.
3. **API 키 비노출 보강**: httpx/httpcore INFO 로그의 URL 노출, `HTTPStatusError` 문자열과 예외 체인의 URL 노출, 리다이렉트를 통한 키 전달, 이중 인코딩, HTTP 200+XML 오류 본문을 명시적으로 차단·검증하도록 했다. 성공 결과 코드는 추정 하드코딩 금지, 트래픽 초과·미지 코드는 재시도하지 않도록 했다.
4. **서울 관청 코드**: 코드 값은 공식 출처로만 채우고 25개·중복 없음·형식 무결성 테스트를 추가했다. `stores.gu_code` 체계와의 대응표 필요성, 서울시 본청 등 비자치구 코드의 거절을 명시했다.
5. **중복 제거 결정성**: 실행마다 달라질 수 있는 "수집 순번" 타이브레이커를 정규 직렬화 비교로 바꾸고, 중복 제거를 chunk 분할 전 source 전체에서 수행하도록 했다(`ON CONFLICT` 동일 키 2회 오류 방지). `DAT_UPDT_SE`는 해석하지 않고 집계만 한다.
6. **날짜·상태·업종·면적**: 날짜는 문서상 단일 형식만 엄격 파싱, 미래 판정은 주입 clock(Asia/Seoul), 1960 경계를 명확히 했다. 상태는 업종별로 체계가 다른 상세 코드 대신 공식 영업상태 코드표 기반으로 바꾸고 휴업 등은 `other`, 모순·누락·미확인 플래그를 추가했다. 업종은 입력 필드 고정·완전 일치·미지 업태는 검토 플래그·목록 상호 배타성으로 정리했다. 면적 0·정밀도 초과 처리를 추가했다.
7. **좌표계**: EPSG:5174와 EPSG:2097 안내가 혼재해 수백 m 오차 위험이 있으므로 공식 확인 전에는 geom을 적재하지 않는 보류 모드를 두었다. PROJ 네트워크 비활성, 출처 있는 기준점 허용오차 테스트, 서울 경계 수치, 고정 플래그 코드와 판정 순서를 명시했다.
8. **upsert 안전성**: 유일 제약 존재 확인(없으면 migration 추가 없이 중단), 후속 작업 컬럼·`deleted_at` 비갱신, 바인드 파라미터, geom NULL 재적재, source 단위 트랜잭션·advisory lock, 멱등의 정의, repository의 연결 주입(기본 DB 쓰기 경로·CLI 금지)을 추가했다.
9. **CI 게이트**: junit 검사를 "전체 1건 이상"에서 "`test_localdata_upsert.py`가 설계 개수 이상 실행, skip/failure/error 0"으로 좁혀 작업 4 통합 테스트만으로 통과하는 구멍을 막았다. CI에서 DB 환경변수 누락·임시 DB 미확인은 skip이 아니라 실패하게 했다. 최신 head SHA 기준 성공만 인정한다.
10. **완료 조건 7**: PR 확인 항목 `[x]`는 실제 검증된 경우에만 작성하도록 단서를 추가했다.

### 잔여 중단 조건(구현 전·중 확인 필요)

- 공식 원천 계약·서울 25개 코드·영업상태 01~06·업태명·EPSG:5174는 2026-11-10에 공식 Swagger와 최신 공지 첨부자료로 확인했다. 구현 중 이 계약과 다른 응답을 만나면 임의 호환하지 않고 중단한다.
- EPSG:5174 변환은 독립된 출처의 기준 좌표와 허용오차 검증이 필요하다. 이를 확보하거나 검증하지 못하면 geom 활성화 전에 중단한다.
- 작업 4 `stores`의 `(source, license_no)` 유일 제약, nullable, source·category 허용 값 → 불일치 시 migration 변경 없이 중단
- CI `postgis-integration`에서 `test_localdata_upsert.py` 실제 실행·skip 0 → 미충족 시 PR 중단
- 실원천 전체 수집 시 일일 트래픽 한도(약 25개 관청 × 다수 페이지) 초과 가능성은 이번 완료 조건 밖의 잔여 위험이며, 실제 개발 DB 연동 작업에서 다시 검토한다.

### Codex 공식 계약 재확인

- 확인일: 2026-11-10
- Claude 검토가 남긴 구현 전 게이트를 공공데이터포털 두 API의 Swagger 1.0.0과 최신 공식 공지 첨부자료로 재확인했다.
- 확정: 두 `/info` endpoint, `cond[OPN_ATMY_GRP_CD::EQ]`, `numOfRows` 최대 100, `response.header/body`, 성공 코드 `00`, `YYYYMMDD` 날짜, 서울 25개 관청 코드, 영업상태 코드 01~06, `SNTTN_BZSTAT_NM` 업태명, 원 좌표계 EPSG:5174.
- 작업 4 코드도 재확인했다. `(source, license_no)` 유일 제약이 있고 이번 ETL이 비워 두는 컬럼은 nullable이며 category/source enum 제약은 없다. `gu_code`에는 공식 관청 코드를 그대로 저장한다.
- 실원천 호출 키가 없으므로 실제 응답 샘플은 커밋하지 않으며, Swagger 계약을 본뜬 합성 fixture로 검증한다. 실제 개발 DB와 실원천 전체 적재는 계속 제외한다.

## 구현·검증 결과

- 구현 커밋:
  - `7269266`: 고정 HTTPS endpoint, 키 비노출, 제한 재시도, 계약 검증, 안전한 페이지네이션과 공식 서울 25개 코드
  - `57e9e3e`: 날짜·상태·업종·면적 정제, 결정적 중복 제거, EPSG:5174 원본 보존과 EPSG:4326 변환
  - `3ecb022`: 연결 주입형 stores upsert, 유일 제약 검증, advisory lock, source 단위 트랜잭션과 실제 PostGIS 테스트
  - `d289ee2`: psycopg의 신뢰할 수 없는 `ON CONFLICT rowcount` 대신 사전 유일성 검증을 통과한 payload 수로 처리 건수 계산
- 로컬 DB 없는 검증: ruff check·ruff format --check·mypy 통과, 단위 테스트 165개 통과, 통합 테스트 8개는 CI 전용으로 분리.
- 최초 실제 PostGIS run `42794393323`에서 정상 upsert의 `rowcount=0` 동작을 발견해 반환 건수 계산을 수정했다. 테스트를 완화하지 않고 수정 커밋 후 전체를 재실행했다.
- 최신 검증 head: `d289ee21452403d3482cdb6eed1f86332a5318e9`.
- [GitHub Actions run 42794557263](https://github.com/sigoreu-jabeujong/SpotON-BE/actions/runs/42794557263): `lint-and-test` 성공, `postgis-integration` 성공.
- 실제 PostGIS 통합 테스트 8개가 실행됐고 skip·xfail·failure·error는 0이다. 그중 `test_localdata_upsert.py` 4개 실행을 JUnit 게이트가 별도로 강제한다.
- 실제 개발 DB·운영 DB에는 접속하거나 적재하지 않았고, 실원천 API도 호출하지 않았다. CI의 계정과 임시 DB는 run 종료 시 폐기된다.
- GitHub Actions의 Node.js 20 deprecation 및 Ubuntu runner 전환 안내는 이번 코드·테스트 실패가 아닌 runner 공지이며 필수 job 결과는 모두 success다.
