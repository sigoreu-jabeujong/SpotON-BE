# BE-18 상권별 추정매출 원천 적재

- 이슈 #51 / feat#51-market-sales-import / 2026-11-12
- Codex 설계 → Claude MD 직접 검토·수정 → Codex 실제 diff 최종 점검 → 구현·검증·PR·CI·일반 Squash 병합
- 범위: 공식 연간 파일 적재 기반. API·FE·반경 매출·상권 합산·점포 예상 매출·월/분기 환산 없음.

## 1. 원천 확인과 미확인 의미

[서울시 상권분석서비스(추정매출-상권), OA-15572](https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do), 서울특별시·서울신용보증재단, 공공누리 1유형(출처표시·상업 이용/변경 가능), 단위 **원**, 갱신주기 분기다. 공개 연간 ZIP(seq51) 수정일 **2026-05-18**, 14,035,292 bytes, SHA256 `c907f3d386d62b89f45781e6e6172328ee91b1b8dd2c621e4171e437bee1c6b2`다. 내부 CP949 CSV 1개·55개 한글 헤더·39,698,674 bytes, 내부 시각 2026-05-18 09:43:56이다. 원본은 저장소 밖에 두며 커밋하지 않는다.

원본 85,732행·20251~20254, 지원 업종 CS100001/2/3/4/10 **14,391행**(3,617/3,596/3,597/3,581), 나머지 **71,341행** 제외다. 지원 업종은 공식 점포 통계와 같은 코드/라벨을 사용하지만 매출 원천과 인허가/점포 통계의 모집단 동일성은 보장하지 않는다. 금액 최대 1,148,993,825,259로 32bit 범위를 넘으며 BIGINT로 보존한다. 원본 전체 수치의 빈 값·음수·중복 키는 0건이다.

각 분기의 전체 매출 상권은 1,572/1,570/1,569/1,565개이며 기존 경계 1,650개 중 각각 78/80/81/85개는 매출 행이 없다. 매출 코드가 경계 밖인 경우/유형 차이는 0개다. 없는 `(상권,분기,업종)` 행을 0으로 만들거나 가까운 분기 값으로 대체하지 않는다. 경계 적용일은 미확인이므로 코드 일치와 시간적 호환을 구분한다.

원천 금액 필드는 **당월_매출_금액**, 분기는 **기준_년분기_코드**다. 포털 FAQ는 분기 매출을 설명하지만 별도 서울시 공개 자료에는 분기 월평균이라는 설명도 있어 이 파일의 집계 기간 의미를 확정하지 않는다. **amount_period_status=unverified**, **amount_basis=source_reported**, **currency=KRW**로 기록한다. 임의로 3을 곱하거나 나누지 않고 API도 활성화하지 않는다. 공식 FAQ는 개인·법인 매출 때문에 연령/성별 합계와 전체가 다를 수 있다고 안내하므로 분해 값 합계 일치를 강제하지 않는다.

- 컬럼명 `est_sales`는 BE 기준 문서의 market_sales 명칭을 따른 것이며 "추정 매출 확정치·분기 합계"라는 의미를 부여하지 않는다. 의미는 오직 원천 `당월_매출_금액`의 원값이고, 해석은 버전의 amount_period_status가 verified로 바뀌는 별도 이슈 이후에만 한다.
- 이 매출은 카드사 등 표본 기반 **추정치**이며 실제 점포 매출·점포당 매출이 아니다. 점포 수로 나누거나 반경/상권을 합산하는 파생값은 이번 범위와 저장 구조 모두에 두지 않는다.
- 위 원천 수치(행 수·상권 수·최대 금액·빈 값 0건)는 설계 시점의 사전 관찰이다. 구현은 이를 상수로 하드코딩해 통과 조건으로 쓰지 않고, 실행 결과로 다시 산출·보고하며 차이가 있으면 문서를 갱신한다. 단, hash·첨부일·연도는 CLI 입력으로 고정 검증한다.

## 2. 모델·버전

- market_sale_versions: UUID PK, source_dataset=OA-15572/URL, source_year/첨부 수정일, ZIP hash/bytes, member_name/hash/bytes/modified, source_encoding, rule_version, source_rows/row_count/excluded_rows, content_sha256, loaded_at. provenance 구조는 BE-17과 같고 독립 버전을 사용한다.
- code_check_boundary_version_id(FK RESTRICT), code_check_store_version_id(FK RESTRICT): **대조 기준**으로 명시하는 버전이며 적용 경계·동일 모집단 확정이 아니다. UNIQUE(input_sha256,rule_version,두 대조 UUID)에서 input_sha256은 **ZIP 파일 전체 SHA256**(CLI `--expected-sha256`과 동일)이다. 같은 키의 다른 manifest(첨부일·member hash/bytes/시각·인코딩·행 수·content_sha256·code_check 중 하나라도 다름)는 거절하고 기존 행을 갱신하지 않는다. 새 원본/규칙/대조 기준은 별도 버전, 재실행은 기존 UUID/loaded_at/행 불변 재사용.
- 대조 store 버전의 source_year는 이 버전의 source_year와 같아야 한다(DB CHECK가 아닌 적재 전 검증, 다르면 고정 오류). 대조 store 버전이 참조하는 경계 버전과 `--code-check-boundary-version`이 다르면 거절한다(두 대조 기준이 서로 다른 경계를 근거로 섞이지 않게 함). BE-17 버전에 그 참조가 없거나 의미가 다르면 구현 전 확인하고 5절에 기록한다.
- currency=KRW, amount_basis=source_reported, amount_period_status=unverified, boundary_compatibility=unverified CHECK. source_rows=row_count+excluded_rows, row_count>0, 양수 크기/hash/source_year·첨부일 CHECK.
- code_check JSONB: 검증한 두 대조 버전 digest·분기별 양방향 코드/유형/명칭 차이·지원 조합 양방향 미일치 건수. 원문 코드/이름은 보고서에 넣지 않는다. 현재 통계와 원천 분기 불일치는 고정 오류(다른 연도 대조 금지). 같은 연도의 결측 조합은 거절하지 않고 건수로 기록한다. 기준 데이터의 DB 내용 hash/행 수 훼손은 거절한다.
- market_sales: `(version_id,market_code,quarter,induty_cd)` PK, 버전 FK DELETE/UPDATE RESTRICT. 원천 market_name/market_type_code/market_type_name/induty_name 보존. est_sales BIGINT nullable(당월_매출_금액 원천값), source_sales_count BIGINT nullable(당월_매출_건수), source_row_sha256 CHAR(64) 소문자 hex(55개 허용 필드 원문 hash).
- 7자리 숫자 상권 코드·YYYYQ(Q=1~4, 연도=버전 source_year는 적재 검증)·지원 5종·A/D/R/U·빈 이름·hash 형식·`est_sales >= 0`·`source_sales_count >= 0` CHECK(null 허용), `(version_id,quarter,induty_cd)` 인덱스. market_areas/market_stores 행으로 직접 FK를 두지 않는다(누락·호환 미확인 보존). category는 현재 저장하지 않고 원천 induty_cd를 사용한다.
- **결측 3상태**: ① 원천 셀 빈 문자열 → SQL NULL(정보 없음), ② 원천 `0` → 0(실제 원천 0), ③ `(상권,분기,업종)` 행 자체 없음 → 행 미생성(missing). ①③을 0으로, ②를 null로 바꾸지 않으며 행 생성으로 ③을 메우지 않는다. 금액·건수가 모두 null인 행도 원천 행이면 보존한다.
- migration **0007**은 두 테이블·제약·인덱스만 추가하고 0005/0006과 기존 테이블은 수정하지 않는다. downgrade는 같은 트랜잭션에서 두 테이블을 `ACCESS EXCLUSIVE`로 잠근 뒤 행 존재 여부를 확인하고, 비어 있을 때만 DROP한다(확인과 삭제 사이 경쟁 차단). 행이 있으면 고정 오류로 실패한다. 공통 로컬 head guard와 관련 테스트를 0007로 갱신한다. 이 갱신으로 BE-16/17 실행기도 0007 head를 요구하게 되며, 이는 #47→#49의 기존 guard 갱신 관례와 같은 의도된 변경이다(그 외 BE-17 동작 변화 없음).

## 3. 입력·재사용·적재

`python -m etl.market_sales --zip PATH --expected-sha256 HASH --source-year 2025 --source-file-date 2026-05-18 --code-check-boundary-version UUID --code-check-store-version UUID [--write]`

- BE-17의 단일 ZIP·경로/CRC/링크/암호화·읽기 크기·해시 검사와 출처 dataclass, 경계 digest 대조 로직을 **공통 모듈로 추출**한다. 기존 공개 함수/오류 prefix/정책 상수·CLI 동작과 결과 digest를 바꾸지 않고 기존 테스트를 함께 실행한다. 새 매출 모듈에서 기존 점포용 parser/save를 호출하거나 숫자를 조작하지 않는다.
- **BE-17 불변 기준**: rule_version 문자열, content_sha256·row hash·code_check JSON 계산, advisory lock namespace/key, 한도 상수, 오류 코드/prefix·종료 코드, 출력 항목은 그대로다. 기존 모듈은 공통 함수를 re-export/위임해 기존 import 경로를 유지한다. 리팩터링 커밋에서는 0006 migration·모델·BE-17 테스트 기대값을 수정하지 않는다(기대값 수정이 필요하면 동작 변경이므로 중단·보고). 공통화 대상은 BE-16/17 양쪽에서 이미 같은 동작인 부분으로 한정하고 매출 전용 차이를 공통 함수 분기로 밀어 넣지 않는다.
- 공통 함수 매개변수의 기본값은 BE-17 값이며, 매출 전용 한도(16MiB ZIP 등)는 매출 모듈에서 명시적으로 넘긴다. 리팩터링 전 합성 fixture로 BE-17 dry-run 결과(content digest·code_check·출력)를 고정한 golden 테스트를 먼저 추가해 전후 일치를 확인한다.
- ZIP 16MiB·실제 해제64MiB·1,000,000행·4096자 필드 한도, 저장소 안 원본 경로 거절. CP949 strict 또는 BOM UTF8만, 파일명은 경로로 쓰지 않는다. source_year는 완료된 연도, 첨부일은 연말 이후~Seoul 현재일, source_year의 4분기와 지원 5종×4분기 20조합 필수.
- 헤더 **실제 55개**를 고정 허용 목록으로 검사한다. 시간대 건수 헤더는 원본의 `시간대_건수~06_매출_건수` 등 특이 표기를 그대로 사용한다. 필드 누락/중복/추가·열 수·제어문자·중복 키·코드/유형/라벨 검사, 같은 분기의 상권 라벨 충돌 거절·분기 간 변경 허용. 업종 라벨은 파일 전체 일관성/지원 매핑 확인.
- 모든 48개 수치 필드를 검증한 뒤 미지원 업종을 제외한다(미지원 행의 잘못된 수치도 파일 전체 거절). 금액·건수 2개만 값으로 저장하고 나머지는 55필드 행 hash로 출처를 추적한다. 연령/성별/요일 등 값을 재합산하지 않는다.
- **정수 파싱**: 정확히 빈 문자열 `""`만 null이다. 그 외는 ASCII 정규식 `\A(0|[1-9][0-9]{0,18})\Z`(re.ASCII)를 통과해야 하며, 변환 후 `<= 9223372036854775807`을 다시 확인한다. Python `int()`/`str.isdigit()`에 직접 맡기지 않는다(`1_000`·앞뒤 공백·`+1`·전각/아라비아-인도 숫자·위첨자를 허용하기 때문). 공백만 있는 셀, `-0`, 앞자리 0(`007`), 소수(`1.0`), 지수, 쉼표는 거절한다. float·Decimal 경유 없이 int로만 다루고, DB 바인딩도 BIGINT로 명시한다. 실제 원본에서 앞자리 0 등 정당한 원천 표기가 발견되면 규칙을 조용히 완화하지 않고 중단·보고 후 rule_version을 올린다.
- 문자열 필드(코드·이름)는 앞뒤 공백 trim 없이 원문을 비교·저장한다. 공백 차이가 있으면 라벨 충돌로 거절한다(정규화 시 rule_version 명시 필요).
- **row hash**: 헤더 55개 이름→원문 문자열(CSV 해석 후, trim 없음)의 dict를 `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)` 후 UTF-8 SHA256 소문자 hex. **content digest**: (quarter,market_code,induty_cd) 정렬 저장 행의 저장 필드 전체(정수는 JSON 정수, null은 JSON null)와 rule_version·source_year를 같은 canonical JSON으로 직렬화한 SHA256. 저장 후 재조회 digest는 DB에서 읽은 값으로 같은 함수를 다시 계산한다. BIGINT를 float로 변환하지 않는다.
- 기본 DB dry-run: `REPEATABLE READ READ ONLY` 트랜잭션 하나의 일관 스냅샷에서 로컬 identity/head/PostGIS 검사·두 기준 버전 실제 DB 내용과 비교·기존 같은 키 버전 존재 여부(재사용 예정/manifest 충돌)까지 보고 후 rollback. insert·advisory/테이블 락 없음.
- 쓰기: 한 연도/한 트랜잭션(`READ COMMITTED`, 아래 락으로 보호). 매출 전용 key18 advisory **트랜잭션** lock(`pg_advisory_xact_lock`, 공통 namespace에서 BE-16/17 key와 다른 값, 테스트로 중복 금지 확인)을 기존 버전 조회 전에 잡는다. lock_timeout 5초/statement_timeout 60초. 락 획득 순서는 advisory → market_area_versions·market_areas → market_store_versions·market_stores로 고정하고, 기준 테이블은 `SHARE` 모드로 잠가 대조 중 기준 행 변경을 막는다(SHARE끼리는 공존, BE-16/17 writer와 경합 시 lock_timeout으로 실패하며 대기 재시도는 하지 않는다). 그 뒤 두 기준 버전 행/hash/행 수 검증 → manifest 비교 → 필요 시 버전·행 일괄 insert → 저장 행 재조회 digest 검증 → commit. UNIQUE/PK 위반은 락 하에서 발생하면 안 되는 상태이므로 재사용으로 바꾸지 않고 고정 오류로 rollback한다. 실패 시 manifest/행 전부 rollback, 숨은 재시도·기존 갱신·최신 자동 선택 없음.
- 출력은 원본/지원/제외·분기/대조 집계·버전 UUID·삽입/재사용·의미 상태만, 원문 행/이름/코드·키·경로·접속 정보 비노출. 오류 고정 코드/비정상 종료.

## 4. 검증·커밋

1. docs(be): 설계·Claude 실제 수정과 Codex 최종 검토.
2. refactor(etl): ZIP/provenance/경계 대조 공통화, BE-17 회귀·digest 불변 확인.
3. feat(db): 모델·0007·head guard와 제약/모델/downgrade/기존 데이터 보존 테스트.
4. feat(etl): 매출 ZIP/CSV·대조·원자적 적재 CLI와 일반·격리 테스트.
5. docs(be): 실제 원본·DB 검증·제한·실행법/출처·BE 기준 문서. 지정 PR·CI·일반 develop Squash 병합.

합성 테스트는 32bit 초과 금액·BIGINT 경계(2^63-1 허용, 2^63 거절)·null/실제0/누락 행 3상태 보존·잘못된48수치 중 미사용/미지원 행 오류·헤더 특이 표기·ZIP/한도/인코딩·20조합 및 4분기 누락/다른 연도 분기·중복/라벨(공백 차이 포함)·hash/출력 비노출을 검증한다. 정수 파서는 `1_000`, ` 1`, `1 `, `+1`, `-0`, `007`, `1.0`, `1e3`, `1,000`, 전각 `１`, 위첨자 `²`, 공백만 있는 셀을 모두 거절하고 `""`→null, `0`→0을 확인한다. row hash/content digest는 고정 기대값 테스트와 키 순서·행 순서 무관성을 함께 둔다. BE-17 golden 테스트(리팩터링 전 고정)와 advisory key 중복 금지 테스트를 포함한다.

격리 PostGIS는 PK/unique/FK/CHECK(음수·형식)·모델 비교·downgrade 보호(행 있으면 실패, 빈 경우만 성공)/기존 자료 보존·동시 writer 2개(같은 입력: 1개 insert·1개 재사용, 동일 UUID)/멱등/새 규칙 공존·manifest 충돌 거절·저장 후 실패 주입 시 버전·행 전체 rollback·두 기준 훼손/다른 연도 store 버전/경계 불일치 거절·조합 차이 보고·BE-17 writer와 동시 실행 시 lock_timeout 실패 후 부분 저장 없음·REPEATABLE READ READ ONLY dry-run(쓰기 시도 거절)/안전한 오류를 확인한다. 기존 BE-17·경계·인허가·API 회귀를 포함해 ruff/format·mypy·일반/격리 전체를 실행한다.

실제 DB 사전 stores/배치/경계/version/공식 점포 통계/version의 전체 hash/건수 보관 → 일반계정 0006→0007 → **BE-17 2025 원본 replay(같은 UUID·loaded_at·digest·0삽입)로 리팩터링 후 동작 불변 확인** → 매출 dry-run(0삽입)→write→replay(동일 버전/시각/hash·0삽입) → 분기 건수/품질·null/0 건수·원자료 표본20행(금액·건수 정수 일치)·DB digest/모델·기존 API200·기존 전체 hash/원본 보존을 확인한다. 개발 DB에 파괴적 suite/downgrade는 하지 않는다. 미확인 매출 집계 기간·경계 적용일·원천 모집단 동일성은 남기며 FE/API/환경설정을 수정하지 않는다.

## 5. Claude 검토

해당 MD만 Read/Edit로 직접 검토·수정하고 변경 이유·보류 사항을 이 절에 기록한다. 코드·다른 문서·Git 수정은 금지한다.

2026-11-12 Claude Code가 이 파일만 Read/Edit로 직접 수정했다. 범위(백엔드 원천 적재만, API·FE·환산·합산 없음)는 유지했다.

### 5.1 수정 내용과 이유

| 위치 | 수정 | 이유 |
|---|---|---|
| 1절 | est_sales 명칭의 의미 한정, 추정치·점포 매출 아님, 사전 관찰 수치를 하드코딩 통과 조건으로 쓰지 않음 | 컬럼명이 "분기 추정매출 확정"으로 오독될 위험 차단. 관찰 수치를 상수 검증에 쓰면 원천 재배포 시 거짓 실패/거짓 확정이 생김 |
| 2절 버전 | input_sha256=ZIP 전체 hash 명시, manifest 충돌 판정 필드 열거, store 버전 연도·경계 참조 일치 검증 | 같은 키 다른 내용의 판정 기준이 모호했음. 서로 다른 경계를 근거로 한 두 대조 기준이 섞이는 것을 방지 |
| 2절 행 | 음수 CHECK를 null 허용 형태로 명시, hash 형식, **결측 3상태** 규칙 | null/0/행 없음 구분이 목적에만 있고 저장 규칙으로 정의되지 않았음 |
| 2절 migration | downgrade의 ACCESS EXCLUSIVE 후 확인·삭제, 0005/0006 불변, head guard 갱신이 BE-16/17에 주는 영향 명시 | 비어 있음 확인과 DROP 사이 경쟁 제거. guard 갱신을 숨은 동작 변경이 아닌 의도된 변경으로 기록 |
| 3절 재사용 | BE-17 불변 항목 열거, re-export 유지, 기대값 수정 금지, golden 테스트 선행, 공통 함수 기본값=BE-17 | "동작을 바꾸지 않는다"를 검증 가능한 기준으로 바꿈. 매출 전용 한도가 BE-17로 새어 들어가는 것을 방지 |
| 3절 정수 | ASCII 정규식·19자리·2^63-1 재확인, `int()`/`isdigit()` 직접 사용 금지, 앞자리 0·공백 거절 | Python `int()`는 `1_000`, 앞뒤 공백, `+`, 전각 숫자를 허용해 "부호/공백/구분자 없음" 규칙을 조용히 어김 |
| 3절 hash | canonical JSON 인자(ensure_ascii=False 등)·digest 입력 필드·null/정수 표현 고정 | 구현마다 다른 hash가 나오면 replay 멱등성·재검증이 깨짐 |
| 3절 dry-run | REPEATABLE READ READ ONLY 단일 스냅샷, 같은 키 기존 버전 보고 | 여러 조회가 서로 다른 시점을 보면 대조 결과가 일관되지 않음 |
| 3절 쓰기 | xact advisory lock·key 중복 금지, 고정 락 순서, 기준 테이블 SHARE, UNIQUE 위반을 재사용으로 바꾸지 않음 | 교착 방지·기준 행 변경 차단·실패를 성공으로 위장하는 경로 제거 |
| 4절 | 정수 파서 반례, 3상태, 동시 writer 결과, BE-17 동시 실행, 실제 DB의 BE-17 replay | 위 규칙들이 테스트로 강제되도록 함. BE-17 불변을 실제 원본으로 확인 |

### 5.2 미해결·확인 필요

1. `당월_매출_금액`이 분기 합계인지 분기 월평균인지 미확정이다. amount_period_status=unverified 유지, 해석·API 활성화는 공식 정의서/제공기관 확인 후 별도 이슈다.
2. 컬럼명 `est_sales` 유지 여부. 의미가 확정되지 않은 동안 `source_month_sales_amount` 등 원천 명칭에 가까운 이름이 더 안전할 수 있으나 BE 기준 문서 명칭과의 일치를 우선해 유지했다. Codex 최종 점검에서 결정하고 바꾸면 기준 문서도 같은 PR에서 갱신한다.
3. BE-17 market_store_versions에 대조 경계 버전 참조가 실제로 있는지, 그 의미가 이 설계의 일치 검증과 같은지 구현 전 코드로 확인한다. 다르면 검증 규칙을 조정하고 여기에 기록한다.
4. 기존 BE-16/17 advisory lock namespace/key 실제 값 확인 후 key18의 비충돌을 테스트로 고정한다. 기준 테이블 SHARE 락이 BE-16/17 writer와의 운영 경합에 문제가 되면 버전 행 `FOR SHARE` + hash 재검증 방식으로 바꿀지 검토한다(현재는 단순·안전 쪽을 선택).
5. 실제 원본에 앞자리 0·공백 등 규칙 밖 표기가 있으면 완화하지 않고 중단·보고한다(설계 시점 관찰로는 없음).
6. 상권 코드 7자리·유형 A/D/R/U가 2025 매출 원천 전체에 성립하는지는 사전 관찰 기준이며 구현 실행 결과로 재확인한다.
7. 매출 원천(카드 등 표본 추정)과 인허가·공식 점포 통계의 모집단 동일성, 경계 적용일(boundary_as_of=null)은 미확인으로 남는다. 이번 적재는 이를 해소하지 않는다.

### Codex 최종 점검

Claude의 실제 수정 diff 전체를 읽고 기존 BE-17 모델/실행기와 대조했다. 결측3상태·ASCII 정수·BIGINT·재조회 hash·기준 연도/경계 참조 일치·일관된 dry-run snapshot·downgrade lock을 채택한다. market_store_versions에는 실제 code_check_boundary_version_id가 있으므로 두 대조 기준의 경계 UUID 일치를 검사한다. 쓰기 기준 보호는 제안의 테이블 SHARE 대신 **버전/기존 행 FOR SHARE**를 사용한다. 기존 지원 writer는 이미 적재된 버전을 수정하지 않고 같은 버전의 PK/unique/FK가 보호하므로 다른 버전 적재까지 막을 필요가 없다. 수동 DB 변조를 통한 새 행 삽입까지 금지하는 DB 권한 정책은 별도 범위다. 잠금 순서는 경계→점포 통계로 고정한다.

공통화는 BE-17과 이번 매출의 동일한 ZIP/provenance/경계 대조만 대상으로 하며 BE-16 ZIP 구조는 다르므로 변경하지 않는다. BE-17 wrapper/import 경로·상수·hash·오류·lock key·출력은 유지하고 head 갱신만 별도 DB 커밋에서 수행한다. 사전 합성 BE-17 content digest는 `1edd356d6da9572639263e8e058a4c32cb43a6be8a96e09b0db16acd693514bf`, 첫 행 hash는 `f65c6b6d3d4638cec889c2d6548f95c02e9621c534b9d4367817491ea005ec08`로 확보했다. hash 저장 타입은 기존과 같은 VARCHAR(64)+형식 CHECK로 통일한다. est_sales 이름은 기준 문서를 따르되 원천값임을 명시하고 period_status를 미확인으로 고정한다. 추후 의미가 확인돼도 기존 버전을 UPDATE하지 않고 근거·새 규칙의 별도 버전으로 처리한다. 원천 FAQ/금액 단위는 공식 OA-15572 화면에서 확인했으며 집계 기간은 계속 미확인이다.
