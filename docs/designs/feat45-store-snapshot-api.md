# BE-15 과거 시점 점포와 최신 상태 분해 API

- 작성일: 2026-11-12
- 이슈: [#45](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/45), 브랜치 `feat#45-store-snapshot-api`, develop `e1af8d2` 기반
- 원본: 로컬 API 명세서 v1.2 8쪽 §4-4와 공통 조회 §2-2를 직접 확인했다. 원본 파일은 커밋하지 않는다.
- 선행: BE-13 nearby와 BE-14 data-range가 develop에 반영됐다. 실제 DB 0004·689,440건·원천 갱신일 D=2026-11-08을 읽기 전용으로 확인했다.

## 1. 범위·요청

`GET /api/stores/snapshot`에 nearby와 같은 좌표·업종·반경·세부 업종·면적·가맹·독립 unknown/legacy 필터를 적용한다. 차이는 **as_of(YYYY-MM) 필수**다. category 누락/잘못된 업종은 422 CATEGORY_REQUIRED가 우선이며 as_of 누락/형식 오류 및 중복/미지원 인자는 422 INVALID_PARAM, 허용 월 밖은 422 AS_OF_OUT_OF_RANGE다. 형식·조합 등 입력 오류는 DB 연결 전에 처리한다. 허용 월 판정은 DB의 D·유효 최소 개업일이 필요하므로 같은 요청 트랜잭션에서 nearby와 **같은 허용 월 판정 함수**로 수행하며, 빈 category(min_month=null)·D 이후 월·최소 월 직전 월의 결과도 nearby와 달라지지 않게 한다. 공통 외피·오류 meta={}·입력값 비노출을 유지한다. 원본 일부 400/504 및 전체 meta 동기화는 별도 범위다.

신규 DB 모델·migration·적재·Docker·로컬 설정·외부 API 호출은 없다. FE는 직접 수정하지 않고 BE 저장소에 변경 요청 보고서를 작성한다. 자동 PR/일반 Squash 머지 및 기존 검증 정책을 따른다.

## 2. 같은 집합을 만드는 공통 조회

원본은 S를 nearby와 같은 T 시점 영업 중 집합으로 정의한다. nearby의 실제 조회/기간 계산을 새 공통 서비스로 옮기고 두 endpoint가 한 함수를 사용한다. 내부 typed 결과는 실제 기준일 T·전역 기준일 D·검증된 배치·동일한 마커/좌표/기간·좌표 미확보 수를 제공한다. endpoint끼리 HTTP 요청하거나 서로의 공통 응답 외피를 호출하지 않는다. nearby의 기존 JSON 필드·조건·정렬·버전 값과 history/data-range 동작은 유지한다.

- 같은 요청별 READ ONLY REPEATABLE READ 안에서 전역 출처 검사 → 업종별 유효 최소 개업일 → T → 속성/날짜/좌표/반경 후보를 계산한다. 기존 store_cohort의 배치 연결·D 검증·날짜 품질 및 data-range 최소 월 규칙을 그대로 쓴다.
- T는 과거 월말, 최신 데이터 월은 D다. `open_date<=T AND (close_date IS NULL OR close_date>T)`이며 폐업 당일 제외, 개업 당일 포함이다.
- 날짜 결측/오류/역전/미래, 폐업일 없는 closed·폐업일 있는 open, 한시 true·검토/삭제/지원 밖은 기존 규칙대로 제외한다. 유효 other/NULL status는 포함 가능하며 최신 상태 other로 반환한다.
- 거리 후보는 geography ST_DWithin(radius+0.01), 최종 ST_Distance<=radius다. 정렬은 반올림 전 거리→source→license_no→id다. 공통 조회의 쿼리 조건·인덱스 표현식·정렬을 바꾸지 않는다.
- 0㎡ 원본 보존·출력 null·면적 unknown 및 가맹 3상태·독립 unknown/legacy 혼합 거절을 유지한다.
- 좌표 없는 행은 반경을 확인할 수 없어 S/N에 포함하지 않는다. excluded_no_coord는 동일 비공간 조건의 서울 전체 geom NULL 수이며 meta.excluded_no_coord_scope=seoul_nonspatial_cohort를 함께 반환한다.
- 공통 입력 파서·OpenAPI 인자 정의도 재사용하고 snapshot의 as_of만 필수로 표시한다. nearby의 as_of는 선택으로 유지한다.

## 3. 상태·기간·응답

| data 필드 | 처리 |
|---|---|
| as_of | 실제 T의 ISO 날짜 |
| total_at_as_of | N=len(stores) |
| still_open | S 중 최신 status가 open인 A |
| closed_since | S 중 최신 status가 closed인 B. 유효 폐업일>T이며 D 이하 |
| other | S 중 최신 상태가 other/미확인인 C |
| stores | 같은 순서의 전체 점포 목록. 임의 절단/별도 pagination 없음 |
| summary_text | 서버가 실제 T·최신 데이터 기준 A/B/C와 N으로 만든 요약 |
| excluded_no_coord | 서울 동일 비공간 조건의 좌표 미확보 수. N과 별개 |

A/B/C/N은 별도 COUNT SQL로 다시 세지 않고 **공통 조회가 반환한 같은 목록에서** 서비스가 계산한다. 상태 분류는 상호배타·전체포괄이다: 최신 status가 open이면 A, closed이면 B, 그 밖의 모든 값(other·NULL·미확인)은 C이며 어떤 행도 두 분류에 들어가거나 빠지지 않는다. 목록은 source+license_no 기준 중복이 없어야 한다(배치 연결 등으로 행이 중복되면 N이 부풀므로 검사 대상). 응답 모델은 **N=A+B+C=len(stores)**, 상태별 목록 집계 일치, 식별자 중복 없음을 검사하고 위반 시 부분 응답 없이 500 INTERNAL_ERROR(공통 외피·no-store)로 종료한다. 빈 결과도 200이며 네 수는 모두 0, stores=[]다. 요약은 예를 들어 `2020.01.31 기준 동일 업종 3곳 → 최신 데이터 기준 영업 1곳 · 폐업 1곳 · 기타 1곳`이다. 기타가 0이어도 표시한다. 최신 상태는 D의 기록이며 오늘 실시간 확인값으로 표현하지 않는다.

각 stores 항목은 원본의 license_no/name/sub_category/lat/lng/open_date/close_date/operating_months/current_status에 **source와 operating_period_status/reason**을 추가한다. name·operating_months는 nullable, open_date는 시점 후보 검증 때문에 유효한 필수 날짜, close_date는 nullable이다. 관리번호 단독 식별 대신 source+license_no를 사용한다. 기간은 nearby와 같은 최신 데이터 기준 전체 기간이며 T까지로 자르지 않는다. open은 D, closed는 확인된 폐업일까지 달력상 완료 개월 수를 계산하고 other는 기간 null/no_data/other_status다. 실제 0개월과 결측을 구분한다. distance/franchise/area는 필터에 쓰지만 snapshot 목록 응답에 새로 복제하지 않는다.

meta는 기존 provenance_meta를 사용해 source·전역 갱신일·배치/매핑을 유지하고 as_of=T, space=radius_{r}m, denominator=N, operating_period_basis=latest_data, excluded_no_coord_scope를 제공한다. 규칙 버전은 meta.data_version.rule_version=`store-snapshot-latest-status-v1`이다. collected_at=null과 source_completion_time_not_recorded를 유지하며 적재일/검증일/오늘로 채우지 않는다. endpoint별 rule_version은 다르므로 cross-endpoint 일치 검사는 배치 ID·매핑·필터가 같은 조건으로 한다.

## 4. FE 요청·운영

기존 FE SnapshotStore는 source가 없고 상호/기간 필수 및 license_no 단독 key로 가정한다. 타입·SnapshotTable·출력 진단서·목업의 복합 식별자/결측/기간 사유를 요청 보고서에 정리한다. snapshot 안내의 data-range 세부 업종 전달·nullable 최소 월 처리는 기존 월 범위 보고서와 함께 반영하도록 요청한다. 이번 변경만으로 FE 연결·표시·CLAUDE.md 동기화를 완료로 표시하지 않는다.

서버는 기존 no-store·안전한 오류·read-only 세션·3초 SQL 문장 timeout을 사용한다. 문장 timeout을 전체 요청 SLA로 주장하지 않는다. 개발 실행은 --no-access-log이며 실제 좌표 query·주소·관리번호·원문·접속 정보·키를 로그/PR에 내보내지 않는다. 필요한 DB/자료가 없으면 사용자 지시대로 실행 큐를 멈추고 요청한다. 현재는 기존 DB와 원천이 준비되어 신규 키가 필요하지 않다.

## 5. 검증·커밋·완료 기준

1. 이 MD를 Claude가 Read/Edit로 직접 검토하고 Codex가 실제 diff·기존 코드·원본과 대조한 뒤 설계 커밋.
2. 공통 공간 조회/입력 파서 추출과 snapshot 스키마·서비스·라우터, 해당 단위/격리 PostGIS 테스트를 기능 커밋에 담는다. 기존 nearby/history/data-range 회귀로 변경 전 동작을 확인한다.
3. as_of 필수·category 우선·중복/미지원·엄격 bool/legacy·좌표/반경/월 오류의 DB 전 거절·값 비노출·OpenAPI·500/no-store를 검사한다.
4. 같은 데이터·필터·**명시적으로 같은 as_of**(과거 월과 최신 월 D 모두)의 nearby 목록과 source/license 집합·순서·기간 일치, nearby count와 N 일치, N=A+B+C=목록 길이와 source+license_no 중복 없음(단일 사례가 아니라 필터·반경·시점 조합 매개변수 테스트), 상태 분류의 상호배타·전체포괄(open/closed/other/NULL/예상 밖 값), 불변식 위반 시 500·부분 응답 없음, 공통 조회 추출 전후 nearby 응답 JSON 동일, 과거 T 이후 폐업·폐업 당일(close_date=T) 제외·개업 당일(open_date=T) 포함·윤년/월말/최신 월 D, 유효 other의 기간 null, 0건·복합 식별자·nullable 상호·실제 0개월을 검증한다.
5. 면적 0/NULL/구간·가맹 3상태·두 unknown/legacy, 반경 300/500/1000·499/500/500.001/501m·같은 표시 거리의 실제 순서, 날짜·지원/검토/한시/삭제 제외·전역 출처 실패·빈 category의 최신 월/이전 월을 검사한다. 기존 공간 함수 경계 검사도 유지한다.
6. 실제 개발 DB는 읽기 전용으로 업종/시점/반경/필터 조합을 독립 SQL 집계·목록과 대조한다. 원자료 표본 20건의 개폐업/상태/기간과 독립 WGS84 거리를 확인하고 실제 HTTP·ORM EXPLAIN·0004/689,440건·전체 행/geometry 해시 보존을 검증한다. 목록 절단이 없으므로 큰 결과 조합(1000m·밀집 지역·최신 월·세부 업종 미지정)에서 3초 문장 timeout 안에 끝나는지 관측값으로 기록하되 SLA로 주장하지 않는다. 파괴적 fixture는 별도 임시 PostGIS 컨테이너만 사용한다.
7. 최종 코드에 ruff/format/mypy·일반/격리 integration·비밀값/인코딩 변형·diff 검사를 수행한다. 결과·BE 계약·작업계획·FE 보고서를 문서 커밋에 담으며 문구만 바꾼 뒤 같은 테스트를 반복하지 않는다. 코드 변경·실패·미해결 우려가 생기면 해당 검사를 다시 수행한다.
8. PR 제목 `feat: 과거 시점 점포 조회와 최신 상태 분해 구현`, 지정 본문에 close #45. FE CLAUDE.md 확인은 반영 전 미체크로 유지한다. CI·병합 조건 통과 후 일반 Squash로 develop에 자동 병합하고 이슈 종료·로컬 최신화를 확인한다. 보호 규칙/본인 승인 제한은 우회하지 않는다.

## 6. 검토 기록

Codex: 원본 §4-4의 S 동일성·as_of 필수·N 합계 조건을 확인했다. 신규 응답의 source/기간 상태·사유/좌표 미확보 수는 현행 BE의 정보 없음·식별자·공간 범위 원칙을 일관되게 적용하는 보완이며 FE 요청 보고서로 전달한다. 과거 수집 전 누락·폐업일 결측 등의 완전성 한계는 기존 nearby와 같고 이를 새로 추정하지 않는다.

Claude(2026-11-12, 이 MD 한 파일만 Read/Edit로 검토·직접 수정): 코드·원본 명세·DB·다른 문서는 열람하지 않았다. 아래는 문서 안의 원본 대조 기록과 CLAUDE.md·작업계획의 현행 정책 기준 판단이며, 문서 밖 사실을 검증했다는 뜻이 아니다.

- 수정 1(1절): "입력 오류를 DB 연결 전에 처리"와 AS_OF_OUT_OF_RANGE가 충돌할 수 있었다. 허용 월은 D·유효 최소 개업일이 있어야 판정되므로 형식/조합 오류만 DB 전 처리로 한정하고, 허용 월은 nearby와 같은 판정 함수를 같은 트랜잭션에서 쓰도록 명시했다. 빈 category·D 이후·최소 월 직전의 결과가 endpoint마다 갈리면 "nearby와 동일 집합" 요건이 깨지기 때문이다. 새 규칙을 만든 것이 아니라 기존 nearby 판정 재사용을 명시한 것이다.
- 수정 2(3절): 핵심 불변식 N=A+B+C=len(stores)를 구조적으로 보장하는 방법이 없었다. 수를 별도 COUNT로 세지 않고 같은 목록에서 계산, A/B/C 분류의 상호배타·전체포괄(open/closed 외 전부 C), source+license_no 중복 없음, 위반 시 부분 응답 없는 500 INTERNAL_ERROR를 추가했다. 오류 코드는 기존 6절의 미처리 예외 매핑을 그대로 쓴 것이다.
- 수정 3(5절 4항): nearby의 as_of는 선택이므로 비교 시 같은 as_of를 명시해야 한다. nearby count=N, 조합 매개변수 테스트, 예상 밖 status 값, 불변식 위반 경로, 공통 조회 추출 전후 nearby JSON 동일성, 개업 당일 포함 경계를 테스트에 추가했다.
- 수정 4(5절 6항): 목록 절단이 없으므로 큰 결과 조합의 3초 문장 timeout 관측을 추가했다. SLA 주장은 하지 않는다.
- 확인한 일관성: as_of 필수·category 우선, T=과거 월말/최신 월 D, 개업 당일 포함·폐업 당일 제외, 반경 후보+0.01m·최종 ST_Distance, 0㎡ null, 독립 unknown/legacy, 좌표 미확보 범위 meta, 기간을 T로 자르지 않는 latest_data 기준, collected_at=null, FE 직접 수정 금지·보고서 전달, PR 제목 `feat: 한국어 설명`, CI 후 develop 자동 Squash·보호 규칙 비우회는 CLAUDE.md·작업계획과 모순이 없다.
- 보류(Codex 확인 필요): (a) 빈 category·D 이후 월에 대한 nearby의 실제 허용 월 결과는 코드로 확인하고 snapshot 테스트 기대값을 그와 같게 둔다. (b) 기존 store_cohort의 배치 연결이 행 중복을 만들 수 있는지 코드로 확인한다. (c) meta.space=radius_{r}m 표기가 기존 nearby meta와 같은지 확인한다. (d) summary_text의 "동일 업종" 문구가 sub_category 지정 시에도 적절한지, 과거 수집 한계 안내가 필요한지는 FE 보고서에서 담당자 확인 대상으로 남긴다. (e) 폐업일 없는 closed 제외로 B가 실제보다 작을 수 있는 완전성 한계는 기존 nearby와 같으며 이번 범위에서 추정 보정하지 않는다.

Codex 최종 점검: 실제 Claude diff와 원본·코드를 대조했다. 같은 목록의 Counter 집계와 중복/합계 불변식, 명시적 같은 as_of 비교를 채택한다. 기존 배치 조회는 EXISTS를 사용해 공간 행을 JOIN으로 증식시키지 않는다. 빈 category는 최신 월만 0건, 이전/이후 월은 범위 오류이며 meta.space는 radius_{r}m다. 현재 전역 미처리 예외 경로에는 no-store 보장이 없으므로 snapshot의 응답 모델 검증 실패를 서비스에서 AppError(INTERNAL_ERROR, NO_STORE)로 변환한다. 전역 오류 정책을 변경하지 않고 이 경로의 부분 응답/정보 비노출/헤더를 테스트한다. 문구·자료 완전성의 FE 확인은 보고서로 전달한다.

실제 DB 사전 nearby 요청은 최초 1회 정상 응답이 아니었고 원인 코드는 그 호출에 기록되지 않았다. 오류 값 비노출 진단으로 재조회한 restaurant/cafe×2020-01/2026-10 네 경우는 모두 200이었다(각각 631/590/154/151건). 재진단 SQL은 약 0.6~1160.5ms였으며 초기 실패를 특정 원인으로 단정하지 않는다. DB 연동이 정상임을 재확인한 뒤 진행하고 최종 실데이터 검증에 이 경로를 포함한다. 성능 SLA·차가운 캐시 성공을 보장하지 않는다.
