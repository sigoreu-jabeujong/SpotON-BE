# BE-13 주변 점포 API 구현 계획

- 이슈: #41, 브랜치 feat#41-nearby-api, develop 2bb8f5d 기반.
- 기준 계약: [Claude 검토·Codex 점검을 마친 설계](feat38-nearby-api-design.md). 이번 요청으로 설계 다음 단계인 BE 구현·테스트·PR·머지를 수행한다.
- FE 저장소·이슈·PR은 변경하지 않고 [요청 보고서](../fe-nearby-api-request.md)를 갱신한다.

## 구현 결정

1. nearby 전용 요청·마커 스키마와 원시 query 검증을 추가한다. category 우선 오류(누락 시 CATEGORY_REQUIRED가 다른 인자 오류보다 앞섬)·엄격 bool(`true`/`false` 외 거절)·중복/미지원 인자·쉼표 세부 업종(cafe에 음식점 세부 업종 거절)·legacy unknown 혼합 거절을 검증한다. legacy 표현과 새 독립 unknown 토글이 한 요청에 함께 오면 어느 쪽도 우선하지 않고 422 INVALID_PARAM으로 거절한다. 일반 입력 오류는 현행 422 INVALID_PARAM·공통 외피·오류 meta={}를 유지하며, 오류 message에 입력값(특히 lat/lng)을 되울리지 않는다(FastAPI 기본 검증 상세의 `input` 노출 금지).
2. 요청별 READ ONLY REPEATABLE READ 세션은 기존 DB 의존성을 재사용한다. 먼저 현재 지원 점포의 모든 batch_id/source 연결·갱신일(DAT_UPDT_PNT) 품질을 검사하고 전역 최대 D를 선택한다. D는 요청의 category·필터·반경과 무관한 **global** 값이며 영업 중 기간 종료점과 as_of 상한에 같은 D를 쓴다(history와 동일한 기준일 의미). 출처·기준일 준비 검사는 후보 조회보다 먼저, 같은 스냅샷 안에서 수행한다. 누락·불일치한 출처·기준일은 일부 결과로 응답하지 않고 500 INTERNAL_ERROR(공통 외피·meta={}·원인 상세 비노출)로 처리한다.
3. 시점 후보는 지원 업종·선택 업종·한시 true 제외·유효 날짜 조건이다. 한시 여부 미확인(NULL)은 false로 바꾸지 않으며 처리 방식은 기준 설계를 따른다. min_month는 category/sub_category 기준이며 면적·가맹·반경 조건에 따라 바꾸지 않는다. 시점 T의 영업 조건은 `open_date <= T AND (close_date IS NULL OR close_date > T)`이고 월 입력은 해당 월말(최신 월은 D) 기준이다. min_month 이전·D 이후는 AS_OF_OUT_OF_RANGE, 유효 표본이 없는 category의 "데이터 없음"과 범위 내 "정상 0건"(count=0, markers=[])을 응답에서 구분한다. 날짜를 만들어내지 않는다.
4. 날짜 필터는 기존 ETL의 세미콜론 date_flag 여섯 종류(Codex 확인 기준)를 해석하고 누락·역전·미래·1960년 이전·closed 폐업일 누락·open 폐업일 존재를 시점 후보에서 제외한다. 알 수 없는 flag 토큰이 나오면 유효로 간주하지 않고 제외한다(fail closed). 유효 other는 원본 날짜 구간으로 포함하고 기간은 no_data/other_status다. 기간은 달력상 완료 개월 수이며 미산정을 0으로 만들지 않는다. history의 불완전 이력 보존 동작(날짜 결측 이력도 반환)은 변경하지 않으며 nearby 전용 필터를 공통 기간 함수에 섞지 않는다.
5. 사용자 결정: 0㎡와 NULL은 정보 없음(unknown)이다. DB 원본 0은 수정하지 않고 응답 area_m2는 null, 알려진 면적 범위(33㎡ 미만 포함)에서는 제외하며 면적 unknown 토글을 켰을 때만 포함한다. 가맹 true/false/NULL 및 면적·가맹 두 unknown 토글은 서로 독립이며 한 토글이 다른 축의 unknown을 포함·제외하지 않는다. 면적 범위 미지정 시 기본 동작과 토글 기본값은 기준 설계를 따른다.
6. `CAST(geom AS geography)`와 같은 표현식의 부분 GIST 인덱스(`WHERE geom IS NOT NULL` 계열)를 migration 0004로 추가하고 downgrade로 인덱스만 제거한다. GeoAlchemy Geography는 typmod 없는 타입을 사용해 DDL과 query의 캐스트 표현식이 문자 그대로 일치하게 하며, query WHERE에 인덱스 부분 조건을 함께 넣어 planner가 인덱스를 고를 수 있게 한다. 모델·DDL·query의 컴파일 표현식과 실제 EXPLAIN Index Cond를 검사한다. migration head 변경에 따라 ETL runner의 head guard(DB revision이 코드 head와 다르면 적재 거부)와 기존 head 검사 테스트를 0004로 갱신하고, 0003 상태 DB에서 ETL이 거부되는지 확인한다.
7. 후보 검색은 `ST_DWithin(geography, 중심, radius + 0.01)`, 최종 조건은 같은 geography·같은 spheroid 설정의 `ST_Distance <= radius`(요청 반경 그대로, 여유 없음)다. 따라서 500.001m는 후보일 수 있어도 최종 제외된다. 반올림 전 거리 → source → license_no 순으로 결정적 정렬하고 출력만 Decimal HALF_UP 소수 첫째 자리로 변환한다(예: 500.004m는 제외되므로 표시 500.0 충돌 없음, 499.96m는 포함·표시 500.0 허용). coords는 geom의 X/Y(lng/lat)를 반환한다. 중심 좌표의 서울 판정 여부는 기준 설계를 따르며 여기서 새로 정하지 않는다.
8. excluded_no_coord는 반경을 뺀 동일 비공간 조건(업종·세부 업종·as_of·한시·날짜·면적·가맹 필터)의 서울 적재 데이터에서 geom NULL 수다. meta.excluded_no_coord_scope=seoul_nonspatial_cohort로 범위를 명시한다. FE 표시 검토가 남아 있으며 반경 내 누락 수라고 주장하지 않는다. geom은 있으나 coord_flag가 이상인 행의 취급은 기준 설계를 따르고, 기준 설계에 없으면 보류로 남긴다. history 응답·동작은 변경하지 않는다.
9. source+license_no 식별, nullable 상호·기간·면적, 기간 상태/사유, current_status·최신 데이터(global D) 기준 운영 기간을 반환한다. 기존 기간 계산을 재사용하고 nearby 전용 규칙 버전과 배치 출처를 meta에 기록한다.
10. 새 API와 인덱스 외 데이터 적재·보완·외부 API 호출·data-range/snapshot·FE 구현은 제외한다. DB 원문·주소·좌표·건물/층호·비밀값을 로그/오류로 노출하지 않는다. 요청 query에 좌표가 있으므로 개발 실행은 `--no-access-log`를 유지하고, 앱 로그에는 경로·상태·소요 시간만 남긴다. DATABASE_URL 등 접속 정보는 테스트 출력·PR 본문에 쓰지 않는다.

## 검증·커밋 순서

각 단계는 기능과 해당 테스트를 한 커밋에 담고 `타입(영역): 한국어 요약` 형식을 쓴다.

- 입력/기간·필터 함수 및 해당 단위 검사: category 우선 오류, 엄격 bool, 중복/미지원 인자, cafe 세부 업종, legacy 혼합 거절, 오류 message의 좌표 미노출, date_flag 여섯 종류·미지 토큰, 0㎡/NULL/양수 면적과 두 unknown 토글의 독립 조합, 가맹 true/false/NULL.
- geography 인덱스·revision guard·모델/스키마와 migration 검사: upgrade/downgrade, 컴파일 표현식 일치, ETL head guard의 0003 거부·0004 통과.
- SQL 서비스·라우터·응답·오류 및 격리 PostGIS 통합 검사. 499/500/501m, 500.001m(후보 포함·최종 제외), 다방향 후보 누락 없음, 결정적 정렬, 월 경계·개폐업일 직전/당일/이후, AS_OF_OUT_OF_RANGE·데이터 없음·정상 0건 구분, 필터 조합·0㎡·출처/기준일 누락 500, 좌표 미확보 수와 scope, EXPLAIN Index Cond, 로그(caplog)에 좌표·주소 미포함을 포함한다. history 기존 테스트가 변경 없이 통과해야 한다.
- 실제 개발 DB는 migration 전후 행/geometry 해시·건수(689,440) 보존을 확인하고 index migration 및 읽기 전용 표본 20건·독립 거리 재계산·EXPLAIN을 검증한다. 실제 개발 DB 연결이 불가하면 3절 큐 중단 규칙을 적용하고 mock·CI DB로 대체하지 않는다. 파괴적 fixture는 별도 임시 컨테이너에서만 실행한다.
- FE 요청 보고서(fe-nearby-api-request.md)를 실제 구현 응답 필드에 맞춰 갱신한다. PR 확인 항목 중 FE·BE CLAUDE.md 동기화는 FE 담당자 반영 전이므로 문구를 유지한 채 미체크로 두고 대기를 명시한다.
- ruff/format/mypy/pytest·CI 통과 후 일반 보호 규칙에 따라 develop에 Squash 머지한다. 로컬 검사 실패 시 PR을 만들지 않는다. GitHub 본인 승인 제한을 우회하거나 보호 규칙을 낮추지 않는다. main 반영·브랜치 삭제·강제 푸시·직접 FE 수정은 하지 않는다.

## 검토 기록

Codex: 기존 설계·코드·migration·실제 DB 0003/689,440건을 확인했다. 기존 설계의 FE 미합의 항목은 요청 보고서에 명시하고 BE 응답의 scope로 오해를 방지한다. 사용자 확정 사항은 0㎡ 정보 없음과 자동 PR 진행·머지이며, FE 반영 완료는 아니다.

Claude Code (2026-11-12): 이 MD 한 파일만 Read/Edit로 검토·수정했다. feat38 설계·코드·migration·ETL·DB는 읽지 않았으므로 아래는 이 문서 내부의 누락·모순 보완이며, 기존 구현과의 일치는 Codex가 실제 diff와 코드로 확인해야 한다.

검토 이유:
- 입력: legacy·새 unknown 표현이 함께 올 때의 처리가 "혼합 거절"로만 적혀 있어 422 INVALID_PARAM 거절과 우선순위 없음을 명시했다. FastAPI 기본 422 상세가 입력값을 되울려 좌표가 노출될 수 있어 금지를 추가했다.
- 기준일: D가 요청 필터별인지 전역인지 모호해 global로 고정하고, 출처·기준일 검사를 같은 스냅샷에서 후보 조회보다 먼저 수행하며 일부 결과 없이 500으로 끝내도록 했다.
- 날짜: 시점 영업 조건식, 범위 밖·데이터 없음·정상 0건 구분, 미지 date_flag 토큰의 fail closed, 기간 0 금지와 history 기간 함수 비오염을 추가했다. "여섯 종류"는 Codex 확인 기준으로 표기했다.
- 면적·가맹: 0㎡가 33㎡ 미만 범위에 들어가지 않음과 두 unknown 토글이 서로 다른 축을 건드리지 않음을 명시했다.
- 인덱스: 부분 인덱스는 query에 같은 부분 조건이 있어야 사용되므로 이를 추가했고, downgrade와 ETL head guard의 0003 거부 검사를 넣었다.
- 거리: 후보 여유 0.01m와 최종 엄격 거리의 spheroid 설정 일치, 결정적 정렬 키, 반올림 표시 예시를 추가했다.
- 좌표 누락 수: 반경을 뺀 동일 비공간 조건의 범위를 열거했다.
- 운영·검증: access log의 좌표 노출 방지, 접속 정보 비노출, 테스트 항목 확장, history 회귀, 실제 DB 미연결 시 큐 중단 규칙, 커밋 형식, PR의 FE 동기화 항목 미체크를 추가했다.

보류:
- 한시 여부 NULL, 면적 범위 미지정 기본값, 중심 좌표 서울 판정, geom은 있으나 coord_flag 이상인 행의 처리는 이 문서에 근거가 없어 새로 정하지 않고 기준 설계를 따르도록 했다. 기준 설계에도 없으면 Codex가 구현 전에 보고한다.
- 음수 면적 등 0 이외 이상 면적값은 사용자 결정 범위(0㎡) 밖이므로 정하지 않았다. 실제 DB에 존재하면 보고한다.
- excluded_no_coord_scope의 FE 표시와 기타 FE 미합의 항목은 요청 보고서를 통한 담당자 반영 대기이며 완료로 표시하지 않는다.

Codex 최종 점검: Claude의 실제 MD 수정본과 기존 코드·기준 설계를 대조했다. 기본 면적 all·두 unknown true, 한시 NULL 포함, 서울 판정은 geocode 흐름, 유효 geom/coord_flag 확인 0건은 feat38 기준을 따른다. 실제 DB 음수 면적 0건이며 데이터 재해석을 추가하지 않는다. 출처·기준일 미준비는 500, 기준일이 있고 유효 category 표본이 없으면 기본 현재 조회 200·0건으로 구분한다. 구현 계획 보완은 채택하고 새 승인 절차나 FE 직접 변경은 추가하지 않는다.
