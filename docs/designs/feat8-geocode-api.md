# 작업 8: 서울 주소 지오코딩 API

## 상태와 범위

- 이슈: [#21 서울 주소 지오코딩 API 구현](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/21)
- 브랜치: `feat#8-geocode-api`, 대상 브랜치: `develop`
- canonical 작업: BE-11 / F-01
- 목적: 사용자가 입력한 서울 도로명·지번 주소를 카카오 로컬 API로 조회해, 이후 조회 API가 공통으로 사용할 좌표·지번 `building_key`·명시적 `floor_unit`을 제공한다.
- 포함:
  - `GET /api/geocode`
  - 카카오 주소 검색 API 호출, 응답 형식 검증, 실패 격리
  - 서울 후보 판정, 최대 5개 후보 반환, `ADDRESS_NOT_FOUND`·`OUT_OF_SEOUL`·`UPSTREAM_ERROR` 매핑
  - 기존 순수 `building_key`·`floor_unit` 정규화 모듈의 응답 전용 재사용
  - FastAPI 라우터·서비스·스키마와 mock transport 단위·라우터 테스트
- 제외:
  - `stores` 조회·저장·갱신, migration, ETL 변경, 실제 개발 DB 연결
  - 카카오 키워드·장소 검색, 역지오코딩, 결과 정렬 재정의, 캐시·재시도
  - API v1.2 원본 계약의 부재를 보완하는 계약 변경
  - 실제 카카오 호출 검증. `KAKAO_REST_API_KEY`가 있어도 이 작업의 자동 검증은 mock만 사용하며, 라이브 호출은 별도 수동 확인으로 기록한다.

원본 API v1.2 문서는 현재 두 저장소 모두에 없다. 따라서 이번 구현 계약은 현행 [BE 작업계획](../be-work-plan.md) 6절과 FE의 `src/types/geocode.ts`, `src/pages/InputPage.tsx`, `src/api/mocks/geocode.ts`를 대조한 작업 계약이다. v1.2 확보 시 필드·enum·오류 상태를 다시 대조해야 하며, 이 문서만으로 원본 계약 동기화 완료를 주장하지 않는다.

## 1. HTTP 계약

```text
GET /api/geocode?query={주소}&category={cafe|restaurant}
```

- `query`는 필수 문자열이며 공백 제거 후 비어 있거나 1,000자를 넘으면 기존 요청 검증 규칙에 따라 `422 INVALID_PARAM`이다. 원문은 오류 응답·로그·예외 메시지에 넣지 않는다. FastAPI 기본 검증 오류의 `input`·`ctx` 값이 공통 오류 외피로 새지 않는지 테스트로 확인한다.
- `category`가 없거나 `cafe`, `restaurant` 이외이면 `422 CATEGORY_REQUIRED`다. 이 코드는 전역 검증 핸들러의 `INVALID_PARAM`과 다르므로 라우터 수준에서 category를 먼저 판정해 명시적으로 발생시킨다. `query`와 `category`가 동시에 잘못되면 `CATEGORY_REQUIRED`를 우선하고 카카오를 호출하지 않는다. 주소 검색 결과 자체를 업종으로 필터하지 않지만, 이후 화면과 API가 같은 진단 맥락을 유지하도록 대표 결과와 모든 후보에 그대로 넣는다.
- 성공은 기존 공통 외피 `{data, meta, error}`를 쓴다. `meta`는 BE-04에서 이미 정의된 `ApiMeta` 필드만 사용한다. 현행 FE 출처 식별자에 맞춰 `source=["R8"]`, `space="point"`를 넣고, 날짜·분모·데이터 버전·시연 여부를 추정해 채우지 않는다.
- 오류는 공통 외피로만 반환한다. 공급자의 HTTP 본문·상태 세부 정보·URL·인증값·주소·좌표는 외부 응답에 노출하지 않는다.
- 응답 본문에 사용자 주소·좌표가 있으므로 성공·오류 응답 모두 `Cache-Control: no-store`를 둔다. GET 쿼리 문자열에 주소가 실리는 것은 현행 FE 계약에 따른 제한이며 4절 로그 규칙으로 완화한다.

성공 `data`는 FE의 현행 `GeocodeResult`와 정확히 맞춘다.

```json
{
  "address_road": "서울 마포구 양화로 160",
  "address_jibun": "서울 마포구 동교동 162-1",
  "lat": 37.5563,
  "lng": 126.922,
  "category": "cafe",
  "is_seoul": true,
  "sigungu": "마포구",
  "building_key": "마포구-동교동-162-1",
  "floor_unit": "2층 201호",
  "candidates": []
}
```

- `address_road`는 `road_address.address_name`, `address_jibun`은 `address.address_name`을 정규화하지 않고 그대로 쓴다. 카카오 주소 검색은 보통 `서울`처럼 축약된 시도명을 반환하므로 `서울특별시`로 바꾸거나 재조립하지 않는다. `road_address`가 null이면 `address_road`는 빈 문자열이다. `building_key`에 지번 구조가 필수이므로 `address`가 null이거나 `address_name`이 비면 유효 후보가 아니다.
- `lat`·`lng`는 각각 WGS84 위도·경도 숫자다. 카카오는 문서 최상위 `x`·`y`를 **문자열**로 주므로 최상위 `y`→`lat`, `x`→`lng`를 명시적으로 float 변환한다. 변환 실패, 비유한 값, 범위(`lat -90..90`, `lng -180..180`) 밖이면 해당 문서는 공급자 형식 오류다.
- `is_seoul`은 성공 결과에서는 항상 `true`다. 서울 밖 후보를 성공 배열에 섞지 않는다.
- `sigungu`는 카카오 지번 구조의 자치구이며, 서울 25개 자치구 중 하나다.
- `building_key`는 null을 허용하지 않는다. `build_from_parts()`가 만든 `{자치구}-{법정동}-{본번}-{부번}`만 반환한다. 도로명 검색도 카카오의 같은 문서에 포함된 구조화 지번을 이 규칙으로 변환한다.
- `floor_unit`은 사용자 입력 전체에서 기존 `parse_floor_unit()`이 명시적으로 읽은 canonical 값이며, 없거나 충돌·모호·형식 오류면 `null`이다. 결과 후보의 주소에는 보통 층·호가 없으므로 후보별 주소에서 다시 추정하지 않는다. 이 API는 `location_level`을 반환하거나 저장하지 않는다.
- 카카오가 1개의 유효한 서울 후보만 주면 `candidates`는 빈 배열이다. 2~5개의 유효한 서울 후보가 있으면 대표로 반환한 첫 후보를 포함한 전체 배열을 `candidates`에 넣는다(`candidates[0]`은 대표 결과와 같은 값). 이는 FE가 후보 배열을 사용자 선택 목록으로 쓰는 현재 동작과 일치한다. 공급자 순서는 바꾸지 않고 중복 제거·재정렬도 하지 않는다.
- `candidates`의 각 원소는 위 `data`와 같은 필드에서 `candidates`만 뺀 평탄한 객체다. 중첩 `candidates`를 두지 않는다. `category`·`floor_unit`은 모든 원소에 같은 입력 기반 값을 넣는다. 구현 전에 FE `src/types/geocode.ts`의 후보 원소 타입이 이 형태와 같은지 다시 대조하고, 다르면 FE 타입을 우선해 이 절을 고친 뒤 구현한다.
- 카카오 1페이지 `size=5`만 요청하므로 `meta.is_end=false`여도 추가 후보는 조회하지 않는다. 6개 이상 매칭 시 일부 후보가 누락될 수 있다는 점은 제한으로 남긴다.

## 2. 카카오 연동과 후보 판정

서비스는 `https://dapi.kakao.com/v2/local/search/address.json`에 다음처럼 요청한다.

- `GET`, `params={"query": query, "page": 1, "size": 5}`, `Authorization: KakaoAK {REST_API_KEY}` 헤더, 명시적 짧은 timeout을 사용한다.
- 카카오 문서는 상세 주소를 검색어에서 제외하도록 권장하지만, 이번에는 입력을 임의로 제거하지 않고 그대로 전송한다. 현재 층·호 파서는 값 추출만 보장하며 주소 본문에서 안전하게 제거할 토큰 위치 계약은 없다. 상세 주소를 잘못 잘라 건물번호·지번을 바꾸는 것보다 공급자 검색 결과를 보존한다. 별도 query sanitizer는 실제 실패 표본이 생긴 뒤 독립 작업으로 검토한다.
- 키가 없으면 카카오를 호출하지 않고 `UPSTREAM_ERROR`로 처리한다. timeout·네트워크 오류·400/401/403·429·5xx 등 비성공 상태·JSON 파싱 실패·최상위 `documents` 배열 누락이 나면 `UPSTREAM_ERROR`로 처리한다. 재시도는 하지 않는다.
- 클라이언트는 공급자 응답을 외부 API 모델과 내부 후보 모델로 분리한다. 미확인 JSON을 `dict` 인덱싱으로 라우터에 전달하지 않으며, 필요한 필드의 타입과 수치 범위를 모두 검증한다. 외부 모델은 사용하는 필드만 선언하고 알 수 없는 추가 필드는 무시한다.

### 카카오 구조화 필드

주소 검색 문서는 최상위 `address_name`, `address_type`(`REGION`, `ROAD`, `REGION_ADDR`, `ROAD_ADDR`), `x`, `y`와 nullable 객체 `address`(지번), `road_address`(도로명)를 가진다. 이번 작업이 읽는 필드는 다음뿐이다.

| 객체 | 필드 | 용도 |
|---|---|---|
| 최상위 | `x`, `y` (문자열) | `lng`, `lat` |
| `address` | `address_name` | `address_jibun` |
| `address` | `region_1depth_name` | 서울 판정 |
| `address` | `region_2depth_name` | `sigungu`, building_key 자치구 |
| `address` | `region_3depth_name` | building_key **법정동** |
| `address` | `main_address_no`, `sub_address_no`, `mountain_yn` | 본번·부번(빈 문자열은 부번 없음)·산 여부(`Y`/`N`) |
| `road_address` | `address_name` | `address_road` |
| `road_address` | `region_1depth_name` | `address`가 null일 때만 서울 판정 보조 |

- `region_3depth_h_name`(행정동), `h_code`, `b_code`, `building_name`, `zone_no` 등은 이번 작업에서 사용하지 않는다. 특히 행정동을 법정동 대신 building_key에 넣지 않는다.
- `REGION`·`ROAD` 유형이나 `main_address_no`가 비어 있는 문서는 동·도로 단위 결과로 지번 필지를 특정하지 못하므로 정상 형식이지만 사용할 수 없는 후보다.
- 서울 판정은 `region_1depth_name`이 `서울` 또는 `서울특별시`와 **정확히 일치**하는지로 한다. 부분 문자열·접두 일치는 쓰지 않는다. `sigungu`는 추가로 서울 25개 자치구 목록과 정확히 일치해야 한다.
- 카카오 필드 이름·값 형식(축약 시도명, 빈 부번 표현)은 공식 문서 기준 설명이며, 키 제공 후 수동 호출에서 실제 응답과 대조해 다르면 이 절을 갱신한다.

### 문서 분류와 응답 결정

각 문서를 다음 넷 중 하나로 분류한다.

| 분류 | 조건 |
|---|---|
| `malformed` | 필드 타입 불일치, `x`/`y` 변환·범위 실패, `address`·`road_address`가 둘 다 null 등 공급자 형식을 신뢰할 수 없음 |
| `non_seoul` | 형식은 정상이고 시도명이 서울이 아님 |
| `seoul_unusable` | 서울이지만 `address` null, 지번 `address_name` 빈 값, `main_address_no` 빈 값, 자치구 목록 불일치, `build_from_parts()` 거절 등으로 canonical 후보를 만들 수 없음 |
| `usable` | 서울이며 `address_jibun`·`sigungu`·좌표·`building_key`를 모두 검증함 |

서울 문서는 `address`의 `region_2depth_name`, `region_3depth_name`, `main_address_no`, `sub_address_no`, `mountain_yn`를 `build_from_parts()`에 전달한다. 공급자가 구조화했어도 BE-09의 허용 범위를 그대로 적용하고, 불완전한 후보로 `building_key=null`을 만들거나 `address_name`·사용자 원문에서 지번을 추정하지 않는다. 도로명 검색과 지번 검색이 같은 필지를 가리키면 같은 `address` 구조에서 key를 만들므로 결과가 같아야 한다.

응답은 위에서부터 처음 맞는 규칙으로 정한다.

1. `documents`가 빈 배열 → `404 ADDRESS_NOT_FOUND`
2. `usable`이 1개 이상 → 성공. `usable`만 공급자 순서대로 최대 5개 반환하고 나머지 분류는 조용히 제외한다.
3. `malformed`가 1개 이상 → `502 UPSTREAM_ERROR` (서울 여부를 판단할 수 없는 문서가 있으므로 서울 밖·검색 실패로 단정하지 않는다)
4. `seoul_unusable`이 1개 이상 → `404 ADDRESS_NOT_FOUND` (서울 주소이지만 필지 단위까지 특정되지 않은 입력이며 공급자 장애가 아니다)
5. 나머지(모두 `non_seoul`) → `422 OUT_OF_SEOUL`

공급자 요청이 성공해도 주소가 서울인지 입력 문자열로 추정하지 않는다. `경기`, `서울` 같은 부분 문자열 대신 카카오가 반환한 구조화 지역을 사용하므로 `서울 세종대로` 같은 표현을 잘못 거절하지 않는다.

### 개인정보와 로그

- 카카오로 보내는 `query`는 F-01의 실시간 외부 호출 허용 범위에 해당한다. 그 외 외부 서비스·로그·예외 메시지·응답 오류에는 주소·좌표·`building_key`·`floor_unit`·REST 키를 남기지 않는다.
- httpx는 기본적으로 `httpx` 로거 INFO 레벨에 요청 URL(쿼리 문자열 포함)을 남긴다. 앱 로깅 설정에서 `httpx`·`httpcore` 로거를 WARNING 이상으로 고정하고, 디버그 로깅을 켜지 않는다.
- `httpx.HTTPStatusError`·`RequestError`와 Pydantic `ValidationError`의 문자열에는 요청 URL·입력값이 들어간다. 이 예외를 로그·응답·도메인 예외 메시지에 넣지 않고, 고정 메시지의 도메인 예외로 바꿀 때 `raise ... from None`으로 원인 체인을 끊어 미처리 예외 트레이스백에도 남지 않게 한다.
- uvicorn access log와 향후 BE-35 API 로그는 쿼리 문자열을 포함하므로 이 경로는 쿼리 문자열 없이 경로만 남겨야 한다. 개발 실행은 작업계획 4절 기준 `--no-access-log`를 유지하며, 배포 로그 구성은 BE-35에서 같은 규칙을 적용한다.

## 3. 모듈 경계

```text
app/routers/geocode.py       query 검증, 서비스 호출, 공통 응답 생성
app/services/kakao_local.py  HTTP 호출, 공급자 응답 검증, 후보 변환
app/schemas/geocode.py       category·후보·성공 data Pydantic 모델
etl/address/building_key.py  기존 structured building_key 생성 재사용
etl/address/floor_unit.py    기존 explicit floor/unit 추출 재사용
```

- 라우터는 카카오 URL·인증 헤더·공급자 JSON을 알지 않는다. 서비스는 FastAPI `Request`·`Response`에 의존하지 않는다.
- 서비스 생성은 dependency로 두어 테스트가 `httpx.MockTransport` 기반 클라이언트를 주입할 수 있게 한다. 실제 경로에서는 요청이 끝나면 async client를 닫는다.
- `Settings.kakao_rest_api_key`는 `SecretStr`로 계속 보관하고 값은 헤더를 만들 때만 꺼낸다. timeout은 별도 `kakao_request_timeout` 설정으로 1~10초 범위, 기본 5초로 둔다. `.env.example`에 키 이름이 이미 있으므로 timeout 예시만 추가하고 실제 값을 읽거나 출력하지 않는다.
- `create_app()`은 geocode router를 `/api` 아래에 포함한다. 별도 DB dependency, migration, store model 변경은 없다.
- OpenAPI에는 성공 모델과 404·422·502 공통 오류 외피를 명시한다. 기존 전역 검증 오류·CORS 규칙을 바꾸지 않는다.

## 4. 오류 판정

| 조건 | HTTP | error.code |
|---|---:|---|
| 빈/길이 초과 등 `query` 형식 오류 | 422 | `INVALID_PARAM` |
| `category` 누락 또는 지원하지 않는 값 | 422 | `CATEGORY_REQUIRED` |
| 카카오가 정상 응답했지만 `documents`가 비어 있음 | 404 | `ADDRESS_NOT_FOUND` |
| `usable`·`malformed`가 없고 `seoul_unusable`이 있음(동·도로 단위 등 필지 미특정) | 404 | `ADDRESS_NOT_FOUND` |
| 모든 문서가 형식 정상인 `non_seoul` | 422 | `OUT_OF_SEOUL` |
| 키 누락, timeout, 네트워크, 비성공 상태(400·401·403·429·5xx 등), 비정상 JSON·`documents` 누락, `usable` 없이 `malformed` 문서 존재 | 502 | `UPSTREAM_ERROR` |

판정 순서는 2절 "문서 분류와 응답 결정"을 따른다. `OUT_OF_SEOUL`은 카카오가 형식이 정상인 주소 후보를 실제로 반환했고 그것이 모두 서울 밖일 때만 사용한다. 공급자 장애와 검색 실패를 서울 밖으로 바꾸지 않고, 서울 주소의 정밀도 부족을 공급자 장애(502)로 바꾸지 않는다. 세부 사유를 `error.detail`에 넣지 않으므로 주소·공급자 내부 정보가 남지 않는다.

## 5. 검증 계획

- `tests/services/test_kakao_local.py`
  - mock transport가 정확한 endpoint·GET·`query/page/size`·`KakaoAK` 헤더를 받는지, 키 값 자체가 repr·예외·로그에 없음을 확인한다. 키 누락 시 transport가 호출되지 않음을 확인한다.
  - 서울 도로명·지번 후보의 문자열 x/y→float 변환, structured key 생성(부번 빈 문자열→`0`, `mountain_yn=Y`→산 지번), 행정동이 아닌 법정동 사용, 입력 층·호 canonical화, category 전파를 확인한다.
  - 같은 필지의 도로명 검색 응답과 지번 검색 응답 fixture가 같은 `building_key`를 만드는지 확인한다(BE-T01).
  - 복수 후보에서 `candidates[0]`이 대표 결과와 같고 전체가 공급자 순서로 최대 5개이며 중첩 `candidates`가 없는지, 유효 후보 1개면 빈 배열인지 확인한다.
  - 응답 결정 규칙 각각: 빈 documents(404), `REGION`/`ROAD` 유형·`address` null·빈 본번 등 서울 `seoul_unusable`만(404), 서울 밖만(422), 서울 `usable`+서울 밖 혼합(200, 서울만 반환), `usable`+`malformed` 혼합(200), `malformed`+서울 밖(502), malformed 좌표/JSON·`documents` 누락, timeout·400·401·429·5xx·키 누락(502)을 분리해 검증한다.
  - `서울`·`서울특별시`는 서울로, `서울특별시` 외의 부분 일치 값(예: 접두만 같은 가짜 값)은 서울 밖으로 판정하는지 확인한다.
- `tests/test_geocode.py`
  - 정상 공통 외피, FE 필드명·타입, 404/422/502 공통 오류 외피, query/category 검증과 둘 다 잘못된 경우의 `CATEGORY_REQUIRED` 우선, CORS, `Cache-Control: no-store`, OpenAPI 응답 모델을 검증한다.
  - 입력에 주소·좌표·층호수 canary를 넣고 `caplog`(INFO 이상, `httpx` 로거 포함)와 422 오류 외피, 502 경로의 로그·응답에 새지 않는지 확인한다.
- 기존 `tests/etl/test_building_key.py`, `tests/etl/test_floor_unit.py`는 회귀 검사로 유지한다. 재사용 모듈의 규칙을 넓히지 않는다.
- 로컬 검증은 아래 네 명령으로 한다.

```powershell
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app migrations
uv run --locked --extra dev pytest
```

DB를 읽거나 쓰지 않으므로 실제 개발 DB 연동 선행 조건은 발동하지 않는다. mock 검증은 카카오 운영 연결을 증명하지 않는다. `KAKAO_REST_API_KEY`가 제공된 뒤에만 실주소를 로그 없이 수동 호출해 정상 서울·서울 외·검색 실패를 확인하고, 그 결과를 PR에 별도로 기록한다.

## Claude Code 검토 요청

이 파일만 처음부터 끝까지 검토·수정한다. 특히 다음 결정을 확인한다.

1. FE 후보 배열이 대표 후보를 포함하는 현재 동작과 API 반환 규칙의 정합성
2. 카카오 구조화 지번만으로 `building_key`를 만들고, 불완전 후보를 추정하지 않는 정책
3. 서울 밖·검색 실패·공급자 형식 오류의 오류 코드 경계
4. 입력 상세 주소를 이번 작업에서 제거하지 않는 보수적 처리와 개인정보 로그 차단
5. 원본 API v1.2 부재를 계약 확정으로 오인하지 않는 제한

검토가 완료되면 수정된 이 파일을 기준으로 구현한다.

## Claude Code 검토 기록 (2026-11-11)

### 수정 사항과 이유

1. **후보 배열**: `candidates[0]`=대표 결과, 원소는 `candidates`를 뺀 평탄 객체, 중복 제거·재정렬 없음을 명시했다. 원소 형태가 정의되지 않아 구현이 FE와 어긋날 수 있었다. `size=5` 1페이지 제한을 명시했다.
2. **카카오 구조화 필드**: 사용 필드 표를 추가했다. 최상위 `x`·`y`가 문자열이라는 점, `region_3depth_name`(법정동)과 `region_3depth_h_name`(행정동) 구분, 빈 `sub_address_no`, `mountain_yn` 값, `REGION`·`ROAD` 유형의 필지 미특정을 반영했다. 서울 판정을 `서울`/`서울특별시` 정확 일치로 고정했다. 응답 예시의 `서울특별시`는 카카오가 실제로 주는 축약 시도명과 맞지 않아 `서울`로 바꾸고 재조립 금지를 명시했다.
3. **오류 경계**: 기존 규칙 3은 "서울 후보가 모두 구조 검증 실패 → 502"였다. 이 규칙대로면 `서울 마포구`처럼 동 단위까지만 쓴 정상 입력도 공급자 장애로 처리됐다. 그래서 `malformed`/`non_seoul`/`seoul_unusable`/`usable` 네 분류와 판정 순서를 정했다. 필지 미특정은 404, 형식 불신 문서가 있으면 502, 모두 서울 밖일 때만 422다. `CATEGORY_REQUIRED`를 전역 핸들러와 분리하고, query와 동시에 틀리면 이 코드를 우선한다.
4. **개인정보·로그**: httpx INFO 로그의 URL 노출, httpx·Pydantic 예외 문자열의 URL·입력값 노출과 `from None` 처리, access log 쿼리 문자열, `Cache-Control: no-store`를 추가했다.
5. **meta**: `source`·`space` 키를 새로 만들지 않도록 했다. BE-04 `ApiMeta`에 이미 있는 필드만 쓴다. 작업계획 6절의 "필드 구조를 임의로 만들지 않는다"를 따른 것이다.
6. **검사 명령**: 작업계획 4절 명령(`uv run --locked --extra dev ...`)으로 맞췄다.

### 보류·남은 제한

- 원본 API v1.2가 없어 필드·오류 HTTP 상태·후보 원소 형태는 FE 현행 코드 기반의 작업 계약이다. 이번 검토는 이 파일만 읽었으므로 FE `src/types/geocode.ts`와 BE `ApiMeta`·`build_from_parts()` 시그니처(예: `sub_address_no` 빈 문자열·`mountain_yn` 입력 형태 수용 여부)는 구현 시 직접 대조해야 한다.
- 상세 주소(층·호)를 카카오로 그대로 보내는 것은 데이터 최소화 관점의 제한이다. 안전한 query sanitizer가 생길 때까지 유지하며, 상세 주소 때문에 검색 실패가 늘면 별도 작업으로 다룬다.
- GET 쿼리 문자열의 주소는 브라우저 기록·프록시 로그에 남을 수 있다. 현행 FE 계약 때문에 유지하며, POST 전환은 v1.2 동기화 대상이다.
- 카카오 필드 형식은 공식 문서 기준이며 라이브 응답 대조는 키 제공 후 수동 확인으로 남긴다.
- 429를 502 `UPSTREAM_ERROR`로 처리하는 방식과 재시도 없음은 9절 확인 대기 항목으로 남긴다.

## 구현 및 검증 결과

### 구현

- `GET /api/geocode`와 `app.services.kakao_local.KakaoLocalService`를 추가했다. 카카오 주소 검색은 최대 5개만 조회하며, 키 누락·네트워크·비성공 응답·형식 오류를 `UPSTREAM_ERROR`로 격리한다.
- 카카오의 구조화 지번에서만 서울 여부, 자치구, 법정동·본번·부번·산 여부를 읽어 기존 `build_from_parts()`로 `building_key`를 만든다. 주소 원문으로 지번을 추정하지 않는다.
- 대표 후보와 후보 배열, `floor_unit`, `category`, `R8` 출처 meta는 현행 FE 타입과 맞춘다. 성공과 도메인 오류 응답은 `Cache-Control: no-store`를 보낸다.
- DB·migration·ETL에는 변경을 만들지 않았다. `KAKAO_REST_API_KEY`의 실제 값과 개발 DB는 읽거나 출력하지 않았다.

### 로컬 검증

- `py -3.11 -m uv run --locked --extra dev ruff check .` 통과
- `py -3.11 -m uv run --locked --extra dev ruff format --check .` 통과
- `py -3.11 -m uv run --locked --extra dev mypy app migrations` 통과
- `py -3.11 -m uv run --locked --extra dev pytest` 통과: 271 passed, 12 deselected (실제 PostGIS 통합 테스트)
- 신규 mock 지오코딩 테스트는 정상 서울·복수 후보·서울 외·결과 없음·공급자 오류·키 누락·입력 검증·CORS·OpenAPI를 검증한다.

### 남은 제한

- 실제 카카오 호출은 `KAKAO_REST_API_KEY` 없이 검증하지 않았다. mock 통과는 운영 키·할당량·실응답의 연동 성공을 의미하지 않는다.
- Uvicorn 접근 로그의 query string 차단과 배포 환경의 로거 정책은 BE-35에서 서버 운영 설정과 함께 확인해야 한다. 로컬 실행은 README와 작업계획의 `--no-access-log`를 유지한다.
- 원본 API v1.2 계약은 여전히 저장소에 없으므로, 확보 후 `R8`·후보 형식·상태 코드·enum을 원본과 다시 대조해야 한다.
