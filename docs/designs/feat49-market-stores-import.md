# BE-17 공식 상권 점포·개폐업 통계 적재

- 이슈: #49, 브랜치: feat#49-market-stores-import
- 작성: 2026-11-12, Codex 설계 → Claude MD 직접 검토 → Codex 최종 점검
- 범위: 공식 연간 ZIP의 지원 업종 통계 적재·검증. 공개 API/FE/지표 계산 변경 없음.

## 1. 확인한 원천과 의미

[서울시 상권분석서비스(점포-상권), OA-15577](https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do), 서울특별시·서울신용보증재단, 공공누리 1유형 출처표시. 2025년 공식 첨부(seq20, 수정일 2026-05-21)는 2,119,809 bytes, SHA256 `133bfc6ce79e13ee5b289490e4667dfba46a0af5d0d71df360a0d324e030a4e6`이다. ZIP 안 CSV 1개·CP949·영문 소문자 필드 14개·304,775행·20251~20254다. 대용량 원본은 저장소 밖에 보관한다.

공식 출력 명세에 따르면 SIMILR_INDUTY_STOR_CO는 전체 점포 수, STOR_CO는 일반 점포 수, FRC_STOR_CO는 가맹 점포 수다. 원본 304,775행 모두 전체=일반+가맹을 만족한다. OPBIZ_RT/CLSBIZ_RT는 원천 제공 비율(퍼센트)로 다시 계산하지 않는다. 전체 파일 최대 폐업률 450, 지원 업종에도 100 초과 24행이 있어 0~100 제약/임의 수정/비율 평균을 적용하지 않는다. [공식 개폐업 정의](https://golmok.seoul.go.kr/fixedAreaAnalysis.do)는 참고 근거이며 CSV를 인허가 점포와 같은 모집단으로 가정하지 않는다.

지원 업종은 CS100001/2/3/4(한/중/일/양식)와 CS100010(커피-음료)이다. 전체 원본의 형식·중복·수치·관계·코드/라벨 일관성을 먼저 검증한 뒤 5종만 24,810행 적재한다. 나머지 279,965행은 미지원 업종으로 집계한다. 커피-음료 통계가 인허가 cafe와 동일한 점포 집합이라는 보장은 없다. 원천 업종 코드/명칭을 보존하고 새 category 판정이나 합산은 하지 않는다.

공식 포털은 2024년부터 공간 단위 변경 및 2021년 이후 제공 안내가 있다. 연간 파일 2025는 현재 최신 API 분기를 뜻하지 않는다. 기존 경계 1,650개와 각 분기 전체 통계의 코드/유형은 일치하지만 경계 적용일 미확인이므로 시간적 호환은 계속 미확인이다. 코드 일치로 지표 제공을 활성화하지 않는다.

원천에 없는 `(상권, 분기, 업종)` 조합은 "점포 0"이 아니라 "원천 행 없음"이다. 적재·후속 조회 모두 이를 0으로 채우지 않으며, 후속 지표(BE-24)는 해당 조합을 null/no_data로 다룬다. 원천 헤더 14개는 고정 허용 목록(분기·상권 구분 코드/명·상권 코드/명·서비스 업종 코드/명·점포 수·유사 업종 점포 수·개업률/개업 점포 수·폐업률/폐업 점포 수·프랜차이즈 점포 수)과 명시적 대응표로 매핑하며, 실제 원본 헤더 문자열과 대응표는 구현 기록에 남긴다. 대응표에 없는 필드는 저장하지 않는다.

## 2. 모델과 migration 0006

- market_store_versions: UUID PK, source_dataset(`OA-15577`)/source_url, source_file_date(운영자가 포털에서 확인한 첨부 수정일), source_year, input_sha256/input_bytes(ZIP), member_name/member_sha256/member_bytes/member_modified(ZIP 내부 CSV의 이름·해제 byte hash·크기·ZIP 내부 수정 시각, 내부 시각은 참고값), source_encoding(`cp949`|`utf-8-sig`), rule_version(예: `market-stores-oa15577-annual-v1`), source_rows/row_count/excluded_rows, content_sha256, code_check, loaded_at(timestamptz).
- 버전 CHECK: `source_rows = row_count + excluded_rows`, 세 값 0 이상, `row_count > 0`, sha256 64자리 소문자 hex, `source_file_date > make_date(source_year, 12, 31)`(4분기 필수이므로 연말 이전 첨부는 불가). 잘못된 행을 건너뛰지 않으므로 rejected_rows 컬럼은 두지 않는다(항상 0, 오류 시 전체 실패).
- code_check_boundary_version_id: market_area_versions FK RESTRICT, NOT NULL. 이것은 코드 대조에 사용한 경계 버전이며 통계의 유효 경계로 확정한 FK가 아니다. market_stores에서 market_areas로의 FK는 **두지 않는다**(시간적 호환 미확인·불일치 코드 보존). `(input_sha256, rule_version, code_check_boundary_version_id)` unique. 같은 파일에 다른 기준 경계를 명시하면 다른 검증 버전으로 보존한다.
- 같은 unique 키로 재실행했는데 source_year/source_file_date/source_url/member hash/encoding 등 manifest가 기존 버전과 다르면 재사용하지 않고 고정 오류로 거절한다(같은 파일의 메타데이터 덮어쓰기·이중 버전 방지).
- code_check: JSONB, 분기별 전체 행 수/고유 상권 수/통계에만 있는 코드 수/경계에만 있는 코드 수/유형 불일치 수/이름 불일치 수/분기 간 상권 명칭·유형 변경 수/지원 행 수와 대조 경계의 version_id·data digest를 기록한다. JSON 키·타입은 고정 스키마로 검증하고 코드·명칭 원문은 넣지 않는다(건수만). **boundary_compatibility=unverified**만 허용한다. 상권 코드/유형 불일치는 거절하지 않고 집계하며 잘못된 경계 자체(FK 대상 없음/행 수·content digest 훼손)는 거절한다. 이름 차이도 시점·표기 차이일 수 있어 보존·집계한다.
- market_stores: 복합 PK `(version_id, market_code, quarter, induty_cd)`, 버전 FK RESTRICT(ON DELETE/UPDATE 모두), 원천 market_name/market_type_code/market_type_name/induty_name, total_stores/general_stores/franchise_stores/open_stores/closed_stores, opening_rate/closure_rate nullable Numeric(14,6), source_row_sha256.
- 점포 수 정수 0~2,147,483,647, 모두 NOT NULL, 전체=일반+가맹 CHECK(ETL에서도 먼저 검사). 원천 비율 0 이상, null은 정보 없음·0과 구분. 폐업 수가 현재 일반 점포 수보다 클 수 있으므로 단순 부등식으로 거절하지 않는다. 비율과 개폐업 수의 산술 관계도 검사·재계산하지 않는다. 비율 6자리 초과 정밀도는 반올림 없이 거절한다.
- 7자리 숫자 상권 코드, YYYYQ(2000~2099, 분기1~4), 지원 업종 5종, A/D/R/U, 비어 있지 않은 명칭/hash CHECK. 분기의 연도=버전 source_year는 테이블 간 CHECK가 불가하므로 ETL 사전 검사와 commit 전 재조회 검사로 보장한다. `(version_id, quarter, induty_cd)` 인덱스.
- downgrade는 신규 두 테이블만 삭제하며 기존 stores/배치/경계·geometry를 보존한다. 적재된 통계가 있으면 조용히 삭제하지 않도록 downgrade는 두 테이블이 비어 있지 않을 때 실패한다. 개발 DB에서는 downgrade를 실행하지 않고 격리 DB에서만 검증한다. 기존 ETL head guard(인허가·경계)와 migration 테스트는 0006으로 갱신.

## 3. 입력과 트랜잭션

`python -m etl.market_stores --zip PATH --expected-sha256 HASH --source-year 2025 --source-file-date 2026-05-21 --code-check-boundary-version UUID [--write]`

- 로컬 ZIP만 읽고 네트워크 다운로드는 하지 않는다. `--expected-sha256` 불일치 시 내용을 해석하기 전에 거절한다. 저장소 작업 트리 내부 경로의 원본은 실수 커밋 방지를 위해 거절한다.
- 완료된 연도만 허용(실행일은 Asia/Seoul 기준, 테스트에서는 주입 가능한 clock), 4분기 모두 필수, 미래 첨부일/분기와 source_year 밖 분기 거절. 지원 업종 5종 × 4분기 20개 조합 각각에 최소 1행이 있어야 하며, 빈 조합·중복 키·잘못된 행은 전체 실패다. 0행을 생성해 누락 조합을 메우지 않는다.
- ZIP 16MiB, 실제 해제 64MiB, 원본 1,000,000행, 필드 4096자 한도(명명 상수). 해시·CRC·중복 member명/절대·상위 경로/심볼릭 링크/암호화·압축 방식·단일 CSV(디렉터리·기타 파일 거절) 검사. 선언 크기를 신뢰하지 않고 실제 해제 byte 한도를 스트리밍으로 확인하며 디스크 추출하지 않는다.
- 인코딩은 추측하지 않는다. UTF-8 BOM이 있으면 utf-8-sig, 없으면 CP949로만 엄격(strict) 디코딩하고 실패 시 거절, 사용 인코딩을 버전에 기록한다. 헤더 14개는 대응표의 정확한 소문자 문자열로 중복/누락/추가/대소문자 변형 없이 검사하며 순서만 달라도 허용한다. 열 개수·NUL/제어문자·빈 줄·따옴표 오류를 검사한다.
- 값 형식: 코드·수치의 앞뒤 공백은 잘라내지 않고 거절한다. 정수는 `0|[1-9][0-9]*`만 허용(부호·천 단위 구분자·소수점 거절). 비율은 부호 없는 십진 표기만 허용하고 지수 표기·NaN·Infinity·음수·쉼표를 거절, 빈 값만 null이다. 점포 수 결측은 거절한다. 명칭은 원문 그대로 보존하되 공백만인 값은 거절한다.
- 라벨 일관성: 업종 코드→업종명은 파일 전체에서 하나여야 한다. 상권 코드→상권명/유형 코드/유형명은 **같은 분기 안에서** 하나여야 하고(위반 시 미지원 행 포함 거절), 분기 간 변경은 시점 차이일 수 있으므로 거절하지 않고 code_check에 건수로 기록한다. 같은 `(quarter, market_code, induty_cd)` 중복은 미지원 행까지 거절한다.
- 해시 정의: source_row_sha256은 **정규화 전** 디코딩된 원천 허용 필드 14개 문자열의 canonical JSON(고정 키 정렬, UTF-8, `ensure_ascii=False`, 구분자 고정)이다. content_sha256은 지원 행을 `(quarter, market_code, induty_cd)`로 정렬한 정규화 값(정수, 비율은 고정 6자리 문자열/null)의 canonical JSON에 rule_version을 포함한 digest다. 두 정의와 예시 벡터를 테스트로 고정한다.
- DB identity·앱 계정 권한(superuser 아님)·PostGIS·head 0006 검사 재사용. 기본 dry-run은 `SET TRANSACTION READ ONLY` 트랜잭션에서 검증만 하고 rollback하며 insert·lock 획득이 없다. 코드 대조 경계의 행 수·data digest를 DB에서 재계산해 해당 버전 기록과 일치하는지 확인한다.
- 쓰기에서는 전체 1년을 한 트랜잭션에 저장한다. `lock_timeout`/`statement_timeout`을 설정하고, #47과 같은 namespace의 별도 key(17)로 `pg_advisory_xact_lock(namespace, key)`를 **존재 확인 전에** 획득해 writer를 직렬화한다. 순서: lock → 경계 버전 존재·digest 재검사 → 같은 unique 키 버전 조회 → (있으면) 저장 행을 재조회해 content digest·행 수·manifest를 대조하고 일치하면 inserted=0으로 재사용, 불일치하면 훼손으로 거절 → (없으면) 버전·행 insert → 저장 행 재조회로 digest·분기별 건수·분기 연도·버전 집계 검증 → commit. lock 밖의 동시 실행이나 수동 insert로 unique 위반이 나면 rollback 후 고정 오류로 끝내며 재시도로 덮어쓰지 않는다.
- 입력/검증 버전 재실행은 UUID/loaded_at/행 불변 재사용. 새로운 파일/규칙/대조 경계는 별도 버전, 기존 수정/삭제·최신/active 자동 선택 없음. 커밋 후 실패(예: 출력 단계)는 적재 결과를 되돌리지 않으므로 commit은 마지막 단계로 둔다.
- 출력은 수집/지원/제외/분기/코드 대조 건수·버전 UUID·삽입 수·replay 여부만, 원본 행·이름·코드·키·경로·접속 정보는 출력하지 않는다. 오류는 고정 코드와 0이 아닌 종료 코드로만 반환하고 원시 예외·SQL·행 내용을 노출하지 않는다.

## 4. 검증·커밋 계획

1. docs(be): 설계와 실제 Claude diff 기록.
2. feat(db): 두 모델·migration·head guard와 제약/모델 비교·downgrade 보존 검사.
3. feat(etl): ZIP/CSV·공식 통계·코드 대조·멱등/원자적 CLI 및 테스트.
4. docs(be): 실제 원본/DB 검증·출처·미확인 기준·작업계획/README/BE CLAUDE 갱신.

일반 검사는 합성 연간 CSV로 인코딩/헤더/크기/ZIP/해시·누락/중복/정수/비율/null·미지원 행 오류·출력 비노출을 확인한다. 격리 PostGIS에서는 제약/모델·migration·정상 쓰기/replay/새 규칙·동시 실행·저장 후 오류 전체 rollback·DB 훼손 거절·코드 불일치 기록·실제 READ ONLY dry-run을 확인한다.

필수 사례(위에 더해):
- 입력: expected hash 불일치가 해석 전 거절, BOM 없는 UTF-8 거절·BOM UTF-8 허용·CP949 허용, 헤더 대소문자 변형/중복/누락/추가 거절·순서 변경 허용, ZIP 다중 member·디렉터리·경로 탈출·암호화·선언 크기 위장(실제 해제 초과)·CRC 오류, 저장소 내부 경로 거절.
- 값: 앞뒤 공백·부호·천 단위 구분자·지수/NaN/Infinity·음수·소수 7자리 비율 거절, 빈 비율 null 저장(0과 구분), 점포 수 빈 값 거절, 전체≠일반+가맹 거절, 폐업률 100 초과·폐업 수>일반 점포 수 저장.
- 완결성: 지원 업종×분기 20개 중 한 조합 누락, 한 분기 전체 누락, source_year 밖 분기, 미래 분기, 미완료 연도(clock 주입), source_file_date ≤ 연말 거절. 미지원 행만의 오류(중복 키·같은 분기 라벨 충돌)도 전체 실패. 분기 간 상권명/유형 변경은 성공하며 code_check 건수에 반영.
- 해시: source_row_sha256·content_sha256 고정 예시 벡터, 행 순서만 바꾼 CSV의 content digest 동일·source_row hash 동일, 비율 `12.5`/`12.500000` 정규화 digest 동일·source_row hash 상이.
- DB: CHECK 각 위반 직접 insert 거절, 버전 FK RESTRICT로 삭제 거절, market_areas FK 부재, 같은 unique 키 + 다른 manifest(source_file_date 등) 거절, replay 시 저장 행 1건 수정 후 재실행 거절, 두 프로세스 동시 write에서 버전 1개·행 중복 없음·나머지 replay, lock_timeout 초과 시 고정 오류, insert 후 검증 실패 주입 시 두 테이블 0행, 비어 있지 않은 테이블의 downgrade 실패·빈 테이블 downgrade 후 기존 경계/stores 보존.
- 출력/로그 캡처에서 상권명·코드·원본 행·ZIP 경로·DATABASE_URL이 나타나지 않음.

실제 개발 DB는 사전 전체 stores·배치·경계/version hash와 수를 보관하고 일반 계정으로 0006 적용 후 dry-run→write→replay, 분기별 건수(6219/6215/6191/6185), 전체=일반+가맹·0/100초과·결측, 원자료 표본20행·stored digest·기존 API200·기존 자료 hash 보존을 대조한다. 파괴적 suite는 개발 DB에 실행하지 않는다. ruff/format·mypy app etl migrations·일반/격리 전체 검사와 비밀값 검사를 통과한 뒤 지정 양식 PR·CI·일반 Squash 병합한다. FE 수정과 지표API·현재 분기 보장·경계 적용일 확정은 하지 않는다.

## 5. Claude 검토

이 문서만 Read/Edit로 검토·직접 수정하고 변경 이유·보류 사항을 이 절에 기록한다. 코드·다른 문서·Git 수정은 금지한다.

2026-11-12 Claude Code가 이 파일만 Read/Edit로 검토·직접 수정했다. 원천 수치(304,775/24,810/279,965행, 분기별 6219·6215·6191·6185, 합계 24,810)는 문서 내부 산술 일치만 확인했고 원본 자체는 열람하지 않았다.

### 5.1 수정 내용과 이유

1. **누락 조합 의미(1절)**: 원천에 없는 조합을 0으로 해석하면 공식 폐업률 no_data 원칙(작업계획 7절)과 충돌하므로 "원천 행 없음"으로 명시했다. 헤더는 명시적 대응표 허용 목록으로만 매핑해 허용 필드 원칙을 지키도록 했다.
2. **원천 보존(2·3절)**: ZIP hash만으로는 같은 CSV를 다시 압축한 경우를 구분하지 못하므로 내부 CSV member의 이름·hash·크기·내부 수정 시각과 실제 사용 인코딩을 버전에 추가했다. #47처럼 첨부 수정일과 내부 파일 시각을 구분한다. 유형명(market_type_name)도 원천 라벨로 보존한다. source_row_sha256은 정규화 **전** 원문 기준으로 정의해 `12.5`와 `12.500000` 같은 원문 차이를 추적할 수 있게 하고, content_sha256은 정규화 값·rule_version 기준으로 분리했다.
3. **스키마 불변식(2절)**: `source_rows=row_count+excluded_rows`, `row_count>0`, hash 형식, 첨부일>연말을 CHECK로 추가했다. 분기 연도=source_year는 테이블 간 CHECK가 어려워 ETL과 commit 전 재조회로 보장한다고 명시했다. market_areas FK를 두지 않는 이유(경계 시간 호환 미확인·불일치 코드 보존)를 명시했다. code_check는 양방향 미일치와 분기 간 변경 건수를 담되 원문은 넣지 않게 했다.
4. **같은 키·다른 manifest(2절)**: 기존 unique 키만으로 재사용하면 같은 파일에 다른 source_year/첨부일을 넣은 실행이 조용히 기존 버전으로 처리되거나 메타데이터가 어긋날 수 있어 고정 오류로 거절하도록 했다.
5. **라벨 일관성 범위(3절)**: 원안은 같은 상권 코드에 다른 라벨이면 전체 거절이었다. 연간 파일은 4개 분기를 포함하므로 분기 사이 상권명/유형 변경은 정상 원천 변화일 수 있다. 같은 분기 안에서만 거절하고 분기 간 변경은 건수로 기록하도록 바꿨다. 업종 코드→업종명은 파일 전체 일관성을 유지했다.
6. **완결성(3절)**: "빈 지원 분기" 검사만으로는 한 업종만 통째로 빠진 분기를 놓치므로 5종×4분기 20개 조합 각각의 존재를 요구했다. 실행일 기준 시간대(Asia/Seoul)와 테스트 clock 주입을 명시했다.
7. **입력 엄격성(3절)**: BOM 없는 파일은 CP949로만 해석해 인코딩 추측을 없앴다. 공백 자동 trim·천 단위 구분자·지수 표기·NaN 등 암묵적 변환을 거절 대상으로 명시했다. 원본이 저장소에 커밋되는 사고를 막기 위해 저장소 내부 경로를 거절한다.
8. **동시성·원자성(3절)**: lock을 존재 확인보다 먼저 잡아야 check-then-insert 경쟁이 없어진다. 순서를 단계별로 고정하고 replay에서도 저장 행 digest를 재계산해 훼손을 거절하게 했다. lock/statement timeout, unique 위반 시 rollback·비재시도, commit을 마지막 단계로 두는 규칙을 추가했다. dry-run은 lock을 잡지 않는다.
9. **downgrade 안전(2절)**: 적재된 공식 통계를 migration downgrade가 조용히 삭제하지 않도록 비어 있지 않으면 실패하게 하고, 개발 DB에서는 실행하지 않도록 했다.
10. **테스트(4절)**: 위 규칙별 경계 사례, 해시 고정 벡터, 직접 insert CHECK 위반, 같은 키·다른 manifest, 동시 write, 검증 실패 주입 rollback, downgrade 보호, 출력·로그 비노출 사례를 추가했다.

### 5.2 보류·확인 필요

- **원천 헤더 실명·대응표**: 1절의 의미 목록은 공식 명세 기준 요약이다. 실제 소문자 헤더 문자열과 대응표는 Codex가 원본과 대조해 구현 기록에 남겨야 한다.
- **분기 간 라벨 변경 실제 건수**: 원본에 분기 간 상권명/유형 변경이 있는지 확인하지 못했다. 원안의 전체 거절 규칙으로 실제 원본이 통과했다면 결과 차이는 없지만, 수정 규칙으로 구현·재검증해야 한다.
- **source_file_date 검증 한계**: 첨부 수정일은 ZIP에서 증명할 수 없는 운영자 입력값이다. 포털 화면 확인 근거를 구현 기록에 남기고, 내부 member 시각과 큰 차이가 있으면 보고한다(거절 기준으로 쓰지 않음).
- **downgrade 실패 규칙**: #47 migration 0005의 downgrade 관례와 다를 수 있다. 일관성을 위해 0005에도 같은 보호가 필요한지는 이번 범위 밖이며 별도 판단한다.
- **저장소 내부 경로 거절**: 기존 #47 CLI에 같은 규칙이 없다면 이번에는 market_stores CLI에만 적용하고 공통화는 보류한다.
- **해제 크기 한도**: 64MiB는 약 30만 행 CP949 CSV에 충분할 것으로 보이나 실제 해제 크기를 확인해 여유를 기록한다. 초과 시 상수 조정은 rule_version과 무관한 안전 한도 변경으로 기록한다.
- **커피-음료 ↔ cafe, 비율 정의, 경계 적용일, 최신 분기**: 원안대로 미확인 유지. 이번 적재로 지표 API·FE·공식 폐업률 매칭(BE-24)을 활성화하지 않는다.

### Codex 최종 점검

Claude의 실제 파일 diff를 읽고 원천 필드·기존 경계/ETL과 대조했다. member 출처·20조합 완결성·분기 내 라벨 일관성/분기 간 변경 허용·bounded 입력·downgrade 보호·시간 제한을 채택한다. 원본 해제 크기는 31,051,537 bytes로 64MiB 이하다. content digest는 저장 행의 source_row_sha256까지 포함해 원문 이력 훼손도 검출한다. 따라서 비율 12.5/12.500000은 계산용 정규화 값은 같지만 원문 hash 및 전체 content digest는 달라야 한다(위 테스트의 '전체 digest 동일' 제안은 이 기준으로 정정). ASCII만 있는 BOM 없는 UTF-8은 CP949와 바이트상 구분 불가하므로 'BOM 없는 UTF-8 전부 거절'은 보장하지 않고 CP949 strict 디코딩 규칙만 보장한다. ZIP의 같은 CSV 재압축은 ZIP hash가 달라 별도 버전이며 member hash는 원자료 비교 근거다. 출력 이후 실패로 이미 commit된 결과를 되돌릴 수 없다는 한계는 재실행 멱등성으로 처리한다. 경계 적용일/현재 분기/인허가와 통계 모집단 동일성은 계속 미확인이다.
