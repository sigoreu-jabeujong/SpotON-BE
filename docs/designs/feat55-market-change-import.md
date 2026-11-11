# BE-20 공식 상권변화지표 원천 적재

- 이슈 #55 / feat#55-market-change-import / 2026-11-12
- 상태: Codex 설계 작성 → Claude Code가 이 MD를 실제 Read/Edit로 검토·수정함(7.1절). Codex 최종 점검 후 구현한다.
- 범위: OA-15576 전체 CSV 검증·완료 연도 선택·불변 버전 적재. 지표 API/FE·임의 점수·판정·반경 합산은 별도다.

## 1. 공식 자료와 실제 확보 결과

[서울시 상권분석서비스(상권변화지표-상권)](https://data.seoul.go.kr/dataList/OA-15576/S/1/datasetView.do)는 서울신용보증재단 제공·서울특별시 저작권·공공누리1유형(출처표시, 상업적 이용/변경 가능)이다. 공식 설명은 운영/폐업 평균 영업기간을 서울 평균과 비교하는 4유형이다. 설명의 창업 조언은 BE 자체 성공/위험 판정으로 재생성하지 않는다.

첨부 ZIP은 없으며 공식 Sheet 화면의 CSV 다운로드 form을 그대로 사용했다. POST `https://datafile.seoul.go.kr/bigfile/iot/sheet/csv/download.do`, infId=OA-15576, srvType=S, serviceKind=1, 조건 없음, STDR_YYQU_CD DESC다. preview 1,000행을 전체로 오인하지 않았다. **공식 전체 CSV 3,124,101 bytes / CP949 / 36,300행**, 2021년1분기~2026년2분기 22개 분기 각1,650행을 확보했다. SHA256은 `0a2ea421607c167fe3a5005719a3118e064fef74d8a4513d030eecc29719a128`이다. 원본은 저장소 밖에 두며 `.env`·원본·조사 스크립트는 커밋하지 않는다.

공식 포털의 갱신일은 2026-09-11, 안내에는 2026-07-03부터 2021년 이후 자료만 제공한다고 되어 있다. 이 날짜를 CSV 자체 수정일·개별 분기 공표 완료일·경계 적용일로 바꾸지 않는다. 파일 수정일은 확인되지 않아 `source_file_date=null`, 실제 다운로드 완료 UTC `retrieved_at`을 별도로 기록한다. ZIP이 아니므로 가짜 ZIP/member 수정일을 만들지 않는다.

초기 대상은 기존 점포/매출 자료와 같은 **완료 연도2025년, 4개 분기 총6,600행**이다. 2026년 자료도 전체 입력 검증에는 포함하되 선택 연도 밖으로 집계하고 적재하지 않는다. 2025년을 최신이라고 주장하거나 특정 상권 누락 시 과거 분기로 대체하지 않는다. 제공 전체 기간의 자동 적재는 후속이다.

### CSV 11개 헤더와 보존 필드

| 원문 | 저장 |
|---|---|
| 기준_년분기_코드 | quarter (YYYYQ) |
| 상권_구분_코드 / 상권_구분_코드_명 | market_type_code / market_type_name |
| 상권_코드 / 상권_코드_명 | market_code / market_name |
| 상권_변화_지표 / 상권_변화_지표_명 | change_code / change_name |
| 운영_영업_개월_평균 | operating_months_avg |
| 폐업_영업_개월_평균 | closed_months_avg |
| 서울_운영_영업_개월_평균 | seoul_operating_months_avg |
| 서울_폐업_영업_개월_평균 | seoul_closed_months_avg |

실제 코드/명칭은 LL=다이나믹, LH=상권확장, HL=상권축소, HH=정체다. 2025년 HH2,167·LL2,061·LH994·HL1,378행이다. 원천에 업종 필드가 없으므로 induty_cd/category를 추가하거나 5업종으로 복제하지 않는다. 기간 평균은 원천 정수개월 그대로이며 자체 이력 API의 달력 완료 개월 계산과 모집단이 같다고 가정하지 않는다. 반올림된 평균으로 코드를 재계산하지 않는다.

전체36,300행에서 중복(분기,상권)·빈 셀·실제0은0건이다. 네 수치는 모두 음이 아닌 정수이며 관측 범위는 각각3~351/20~226/94~118/49~54개월이다. 이 범위는 탐색 결과이며 허용 상한으로 사용하지 않는다.

## 2. 구조·migration 0009

`market_change_versions`:

- UUID version_id PK, source_dataset=OA-15576, source_url 고정, source_year(완료 선택 연도).
- source_file_date nullable Date(현재 null), retrieved_at timezone datetime(실제 전체 다운로드 완료시각, 미래 금지).
- input_sha256/input_bytes/source_encoding, rule_version, source_rows/row_count/excluded_rows, content_sha256.
- code_check_boundary_version_id RESTRICT FK, code_check JSONB, boundary_compatibility=unverified, loaded_at 서버시각.
- unique(input_sha256,source_year,rule_version,code_check_boundary_version_id). CSV가 여러 연도를 포함하므로 source_year도 반드시 식별자에 포함한다.
- source_rows=row_count+excluded_rows, row_count>0/excluded_rows>=0, 소스/인코딩/hash/연도/metadata CHECK. source_rows는 파일 전체 데이터 행 수(현재 36,300), excluded_rows는 선택 연도 밖 행 수(2025 선택 시 29,700)다. 미지원 업종 제외가 없는 자료이므로 excluded_rows의 의미가 BE-17/18과 다르다는 점을 컬럼 주석·출력에 명시한다.
- retrieved_at은 실행일로 갱신하지 않는다. 동일 bytes 재실행 시 최초 provenance를 유지한다. CLI는 원본 다운로드시각을 그대로 받아야 하며, 동일 unique 식별자의 기존 버전과 retrieved_at·input_bytes·source_encoding·content_sha256 중 하나라도 다르면 조용히 재사용하지 않고 `market_changes:provenance_conflict`로 거절한다(dry-run도 같은 판정을 보고).
- 같은 내용을 다른 시각에 다시 내려받아 bytes가 달라지면(서버 정렬·갱신 반영 등) input_sha256이 달라 별도 버전이 된다. 이는 의도된 동작이며, dry-run/write 출력에 같은 source_year·rule_version·content_sha256을 가진 기존 버전 수를 정보로만 보고하고 자동 병합·최신 선택은 하지 않는다.

`market_changes`:

- 복합 PK(version_id,market_code,quarter), version RESTRICT FK.
- 원문 상권 구분/명칭·변화 코드/명칭, 평균4개 nullable Integer, source_row_sha256.
- 변화 코드/명칭은 위 실제4쌍 CHECK, 상권7digits/분기20YY[1-4]/구분A,D,R,U/비공백명칭, 수치null 또는0이상 CHECK. source_row_sha256 64hex.
- index(version_id,quarter,change_code). geometry/industry 열 없음.
- migration은 고정 Alembic op로 작성, 기존 migration 수정 금지. downgrade는 해당2테이블 ACCESS EXCLUSIVE lock(5s) 후 데이터 존재 시 거절, 빈 경우만 삭제. 기존 head guard와 관련 테스트는0009로 갱신.

## 3. 입력·정규화 정책

- `python -m etl.market_changes --csv PATH --expected-sha256 HEX --source-year 2025 --retrieved-at ISO_WITH_ZONE --code-check-boundary-version UUID [--write]`.
- 저장소 내부 입력 거절, 8MiB bounded read·SHA256·strict CP949 또는 UTF8 BOM, 셀4,096자·최대100,000행, NUL/control/빈행/잘못된 quote·열/중복헤더 실패. 헤더 집합 정확히11개이며 순서 변경 허용, 원문 map을 canonical hash한다.
- 전체 파일의 모든 행을 검사한다. 선택 연도 밖의 잘못된 행도 실패한다. 분기 문법/미래 분기(Seoul 현재 분기 초과)/7자리 상권/구분코드명칭/변화코드명칭/비공백길이/중복(분기,상권) 검사.
- 네 평균의 `""`만 null, 실제`0`은0, 나머지는 ASCII `0|[1-9][0-9]{0,9}` fullmatch 및 <=2147483647. 부호/공백/천단위/지수/소수/NaN/비ASCII 거절한다. 더 넓은 문법은 실제 원천 확인·규칙 검토 후 버전업한다.
- (분기,상권) 중복은 실패이므로 같은 분기 안의 구분/명칭 일관성은 중복 검사로 보장된다. 분기 간 상권 구분/명칭 변경은 원천 사실일 수 있어 실패로 만들지 않고 원문 그대로 저장하며, 선택 연도 안의 변경 상권 수를 code_check에 정보로 기록한다. 누락 행을 만들거나 1,650개를 코드 상수로 요구하지 않는다.
- 완료 연도 정의: `source_year < 서울 현재 연도`이고 파일에 해당 연도 1~4분기가 각각 1행 이상 있어야 한다. 둘 중 하나라도 아니면 `market_changes:incomplete_year`로 거절한다(현재 2026은 거절, 2025는 허용). 분기별 행 수가 서로 다른 것은 실패가 아니며 출력에 분기별 행 수를 보고한다.
- 파싱 결과는 기존 `AnnualArchive`를 재사용하지 않고 CSV 전용 dataclass(`MarketChangeInput`: provenance + rows/markets/quarter_rows)로 둔다. ZIP 전용 필드에 null·가짜 값을 채우는 것을 피하기 위함이다. 공통 boundary audit은 필요한 속성만 가진 narrow Protocol을 타입 힌트로 받도록 넓히며, 기존 점포/매출의 hash·보고서·출력·lock key와 동작은 바꾸지 않는다. 이 변경이 타입 힌트 이상(로직·키 이름·hash 입력 변경)을 요구하면 공통 함수는 그대로 두고 geometry hash 검증 부분만 호출하는 얇은 adapter를 새로 만든다.
- CLI는 네트워크 다운로드를 하지 않고 이미 내려받은 로컬 파일만 읽는다. 원본 URL은 provenance 상수로만 저장한다.
- content hash는 rule_version/source_year와 정렬(quarter,market_code)된 모든 저장 행을 canonical JSON으로 계산한다. null/0·원천 코드/명칭/원문 행hash를 포함한다. UUID/loaded_at/retrieved_at은 내용 hash에서 제외하고 metadata로 대조한다.
- 원천 분류는 그대로 저장하고 평균 간 부등식으로 수정하지 않는다. 서울 평균이 분기별 항상 같다는 추가 CHECK도 근거 없이 만들지 않는다.

## 4. DB 실행·무결성

기존 로컬 spoton_dev/spoton_app 일반계정 guard·head0009를 재사용한다. DB 접속 전 파일 전체 검증한다. 기본 REPEATABLE READ READ ONLY에서 경계 manifest/전체 geometry hash·상권별 코드/구분/명칭 차이·기존 버전/전체 내용 hash를 확인하고 rollback한다. head guard·계정/대상 확인은 write 직전 다시 수행한다.

write는 advisory transaction lock namespace0x53504F54/key20, lock_timeout5s/statement_timeout60s. key20은 기존 ETL lock key와 겹치지 않아야 하며 구현 시 기존 상수와 대조하고 모든 ETL lock key의 유일성을 테스트로 고정한다(겹치면 사용하지 않은 다음 번호를 쓰고 이 문서를 갱신). 경계 참조 행/manifest는 FOR SHARE, 동일 버전은 FOR UPDATE 잠금으로 다시 확인한다. 신규 manifest→행500개 batch→저장 내용 재조회·건수/hash 확인 후 caller가 전체 연도 commit한다. 실패/불일치 시 버전·모든 행 rollback. 동일 원본/연도/규칙/경계는 같은 UUID/loaded_at을 재사용하고 삽입0, metadata/저장 내용 훼손을 조용히 수정하지 않는다. 새로운 규칙/연도는 별도 버전이다.

경계 대조는 기존 `etl.market_csv_repository.check_boundary`의 전체 geometry hash 검증을 재사용하고 분기별 code/type/name 차이 건수를 기록한다. 열 이름 supported_rows는 이 자료에서는 선택된 전체 상권행 수라는 점을 문서화한다. 코드 일치를 실제 적용시점의 일치로 간주하지 않으며 boundary_compatibility=unverified다. 점포/매출을 참조 FK로 강제하지 않는다(원천 자체에 업종 차원이 없고 독립 데이터셋).

출력은 mode/counts/version UUID/reused/would_reuse/code_check/선택 연도와 고정 상태만이며 원본 경로·키·행/좌표를 출력하지 않는다. 예외는 고정 오류코드 `market_changes:*`만 출력, 실패exit1·engine dispose 보장. dry-run은 실제DB 쓰기/row lock을 하지 않는다.

## 5. 검증 계획

- 일반: 모든4유형/평균null·0/원문 보존·헤더순서·고정 hash 벡터·year별hash·4분기완전성·중복·분기/코드명칭·잘못된 수치·선택 밖 오류·CSV/한도/hash·시각timezone/미래·저장소입력·오류 비노출/DB접속 전 거절. 추가로 선택 연도 밖 행이 저장되지 않고 excluded_rows로만 집계되는지, 미완료 연도(현재 연도·분기 누락) 거절, 선택 연도 밖의 미지원 변화코드도 전체 실패, 분기 간 명칭 변경 보존·보고, source_file_date=null 유지, 공통 audit 변경 전후 BE-17/18 code_check·content hash·출력의 고정 벡터 동일성, ETL lock key 유일성을 검사한다.
- 격리 PostGIS: upgrade/downgrade·CHECK/FK/index·모델차이0·null/0보존·연간rollback·replay/새규칙/다른연도·같은 bytes 다른 retrieved_at의 provenance_conflict·동일 content 다른 bytes의 별도 버전·동시writer·manifest/저장행/참조경계 훼손 거절·READ ONLY·안전출력·기존stores보존. 테스트 데이터는 합성만 사용한다.
- 전체 ruff check/format·mypy app etl migrations·일반/격리 전체 테스트. 의미 있는 경계·원자성 테스트에 집중한다.
- 실제 개발 DB: 기존12개 테이블(기존8개+생활인구4개) 전체행/geometry 포함 hash/건수 baseline을 먼저 기록한다. migration0008→0009·dry-run무삽입·2025년6,600행 write·replay 동일UUID/loaded_at/hash·삽입0·원자료20행 독립대조·앱 모델차이0·기존API200·기존12테이블 hash/원본CSV 보존. 파괴적 통합/downgrade는 개발DB에서 실행하지 않는다.
- API/FE 변경이 없으므로 FE 저장소나 요청 보고서를 새로 만들지 않는다. 로컬 Docker/환경설정은 변경하지 않는다.

## 6. 커밋·PR

설계/Claude 실제 diff 검토 기록 → 모델·migration → 적재/테스트 → 실제검증·BE문서 순서로 기능별 커밋한다. PR 제목은 `feat: 공식 상권변화 유형 원천 적재 구현`, close #55, 기존 지정 양식/체크문구를 유지한다. 사용자 직접 확인 체크는 기존 지시에 따르며 API 변경 조건은 해당 없음이라고 명시한다. 실제 비밀값 검사·CI/CodeQL 및 병합 조건 통과 후 develop에 일반 Squash 병합한다.

## 7. Claude 실제 검토 요청

이 MD만 Read/Edit로 실제 수정하고 이유·보류를 이 절에 남긴다. 코드·다른 문서·Git·네트워크·DB·`.env`는 읽거나 수정하지 않는다. 특히 CSV provenance와 replay, 독립 업종 없는 원천, 2025년 초기범위, 평균/분류 보존, 공통 audit 타입 변경 회귀, 연도식별자 누락·원자성·테스트 허점을 점검한다. 사용자가 통상 선택을 위임했으므로 기술적 선택은 가장 타당한 안으로 확정하되 자료 없는 의미를 추정하지 않는다.

### 7.1 Claude Code 검토 결과 (2026-11-12, 이 MD만 Read/Edit)

수정·확정한 사항과 이유:

1. **replay provenance 충돌 규칙 구체화(2절)**: 기존 문구는 "최초 provenance 유지"와 "다른 provenance 거절"이 함께 있어 판정 대상이 모호했다. unique 키가 같은데 retrieved_at·input_bytes·source_encoding·content_sha256 중 하나라도 다르면 `provenance_conflict`로 거절하도록 확정했다. 운영자가 다른 시각을 입력해 조용히 재사용되거나 덮어써지는 경로를 막기 위함이다.
2. **동일 내용·다른 bytes(2절)**: 공식 Sheet CSV는 첨부 파일이 아니라 요청 시 생성되는 export이므로 다시 내려받으면 bytes가 달라질 수 있다. BE-17/18과 같이 input_sha256 기반 식별을 유지하고, 동일 content_sha256 버전은 정보로만 보고한다. 내용 hash로 자동 병합하면 provenance가 다른 두 다운로드를 하나로 합치게 되므로 채택하지 않았다.
3. **excluded_rows 의미(2절)**: 이 자료의 제외는 미지원 업종이 아니라 선택 연도 밖 행이다. 같은 컬럼명이 다른 의미를 가지므로 주석·출력에 명시하도록 했다.
4. **분기 내 일관성 검사 중복 제거(3절)**: (분기,상권) 중복이 이미 실패이므로 "같은 분기 일관성"은 별도 검사가 필요 없다. 실제로 의미 있는 것은 분기 간 명칭/구분 변경인데, 이는 원천 사실일 수 있어 실패가 아닌 보존·보고로 정했다.
5. **완료 연도 정의(3절)**: "완료 연도만 허용"의 판정 기준이 없었다. `source_year < 서울 현재 연도` + 4개 분기 존재로 확정했다. 원천 공표 완료 여부 자체는 확인할 수 없으므로 이 판정은 "파일상 4분기 존재"까지만 의미하며 최신·공표 완료를 주장하지 않는다.
6. **`AnnualArchive` 재사용 철회(3절)**: ZIP 전용 구조를 재사용하면 ZIP/member 수정일 등에 null·가짜 값을 채우게 되어 1절의 "가짜 ZIP 수정일을 만들지 않는다"와 충돌한다. CSV 전용 dataclass + narrow Protocol로 바꾸고, Protocol 변경이 타입 힌트를 넘어서면 공통 함수를 건드리지 않는 adapter로 우회하도록 정해 BE-17/18 회귀 위험을 줄였다.
7. **lock key 유일성(4절)**: key20이 기존 ETL key와 겹치지 않는지 문서만으로 확인할 수 없어 구현 시 대조·유일성 테스트를 요구했다.
8. **테스트 허점 보완(5절)**: 선택 연도 밖 행 비저장, 미완료 연도 거절, 연도 밖 오류 전체 실패, provenance_conflict, 동일 내용 다른 bytes, 공통 audit 변경 전후 BE-17/18 고정 벡터 동일성, lock key 유일성을 추가했다.
9. **CLI 네트워크 없음 명시(3절)**: 원본은 수동 확보 파일만 읽으며 CLI가 POST 다운로드를 재현하지 않는다.

그대로 유지한 판단(검토 결과 타당):

- source_year를 unique 식별자에 포함(한 CSV에 여러 연도 존재), 업종 차원 추가·5업종 복제 금지, 평균 정수 원천값 보존과 평균으로 유형 재계산 금지, 서울 평균 상수 CHECK 미도입, 관측 범위를 허용 상한으로 쓰지 않음, 2025년 초기 범위와 2026년 비적재, 점포/매출 FK 미강제, boundary_compatibility=unverified, 연간 단일 트랜잭션·재조회 hash 검증 후 commit.

한계·보류(자료 없이 확정하지 않음):

- retrieved_at은 운영자 입력값이며 DB가 실제 다운로드 시각을 검증할 수 없다. 검증 가능한 기준은 input_sha256뿐이다.
- 포털 갱신일 2026-09-11, 2021년 이후 제공 안내는 개별 분기 공표일·경계 적용일이 아니며 source_file_date=null을 유지한다.
- 상권변화지표 4유형의 산정 기간·평균 영업개월의 모집단(업종 범위·폐업 기간 창)은 원천 설명 외 근거가 없어 자체 이력 API·참고 지표와 비교 가능하다고 보지 않는다.
- 2023-10 첨부 경계 버전과 2025년 상권 코드가 일치해도 실제 적용 경계의 동일성은 미확인이다.
- 2021~2024년·2026년 적재, 지표 API(market_change)·FE 표시·분기 선택 규칙은 후속 범위다.
- 이 검토는 문서만 대상으로 했으며 기존 코드(`check_boundary`, `AnnualArchive`, lock key 상수)의 실제 시그니처는 읽지 않았다. Codex가 구현 전 실제 코드와 위 조건을 대조해야 한다.

### 7.2 Codex 최종 점검

Claude JSON의 is_error=false·9turns·permission_denials=0과 실제 파일 diff 전부를 확인했다. narrow Protocol은 rows/markets/quarter_rows 읽기 속성만 추가하면 되므로 기존 함수 본문·출력·hash는 변경하지 않는다. 기존 2정수 advisory lock key는 경계16·점포17·매출18·생활인구19이며 이번20과 중복되지 않는다(인허가의 별도 bigint hash lock과도 방식이 다르다). 최초 수집 시각을 재사용하고 같은 bytes의 다른 provenance는 실패시키며 동일 내용·다른 bytes 버전 수는 정보로만 반환한다. 2025년 선택·정수/null/0·분기 변경 보존·업종 없음 정책을 채택했다. 포털의 의미 미확인 항목은 추정하지 않고 위 한계를 유지한다.
