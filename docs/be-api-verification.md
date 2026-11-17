# BE API 연속 조회 검증 보고서

- 검증일: 2026-11-12
- 이슈: [#76](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/76)
- 기준: PR75 병합 develop `de756f0` 이후
- 설계·Claude 검토·최종 결정: [설계 문서](designs/feat76-api-flow-verification.md)
- 범위: BE 연결·격리 DB·실제 개발 DB 읽기. FE 화면/계약 반영은 담당자 대기

## 확인한 연결

`주소 검색 → 건물 이력 → 조회 월 범위 → 주변/시점 → 활동/Risk → AI → 지원 링크`

주소 검색 응답의 건물키/상세위치는 이력에, 좌표/업종은 분석에 전달한다. 월 범위 응답의 최신 월이나 명시한 과거 월을 동일하게 사용한다. API별 성공 여부뿐 아니라 후속 입력·식별 집합·시점·분모 의미가 맞는지 확인했다. 공개 API schema·앱 코드·모델/migration·프롬프트·의존성은 변경하지 않았다.

## 자동 회귀 검사

`tests/integration/test_analysis_flow.py`의 고유 시나리오10종·총22개를 기존 PostGIS integration에 추가했다. 자료는 합성 DTO/snapshot이며 실제 원자료가 아니다. 실제 정제/주소정규화/upsert 실행기와 앱을 사용하고 지오코딩 HTTP·모델 공급자만 모의 처리한다.

| 검사 | 확인한 내용 |
|---|---|
| 주소·ETL·이력 | 독립 지번 정규화의 같은 건물키, 다른 지번 제외, 두 원천 같은 관리번호 보존, 타지원업종/결측 이력 유지, 상세위치3종 |
| 연속 조회6조건 | 카페/음식점·과거 월·알려진면적만·가맹 미확인 제외·빈세부업종. nearby/snapshot 식별·순서·분해합계와 Risk/활동 영업수 일치 |
| 날짜·집합 | 원천별 갱신일이 달라도 전역 D 적용, 최신 월은 D, 윤년2월/30일 월말. 같은3건이어도 과거/최신 식별 집합이 바뀌는 음성대조 |
| 원천 재적재 | 기존 실행기로 상태/날짜를 바꾸고 API별 새 결과·버전/AI 호출 증가 확인, 저장수10건 유지 |
| 동일 자료 재적재 | 중복 없음·값 유지·배치 버전 변경·AI 재생성 확인 |
| 실패 적재 | 실제 DB 제약 위반 시 전체 rollback, 기존 값·배치/버전·API 결과 유지 |
| 미준비/잘못된 입력 | 분석500와 정상빈결과200·입력422 구분, 미준비/입력오류 때 공급자0회, health 성공의 한계 |
| AI 실패 | 공급자 실패/검증2회실패503 이후에도 주변/Risk/지원링크 정상, 오류 원문 비노출 |
| 외부 주소 실패 | 검색없음·서울외·timeout·401·429·깨진응답의 공통오류/no-store·원문 비노출 |
| AI·로그 | 서버 재계산/후보 검증·식별정보 없는 공급자 입력·공급자 전 DB 닫힘·순차2요청 공급자1회, 로그/오류 canary 비노출 |

CI의 기존 전체 no-skip/error/xfail 검사에 필수 함수10개 실행 조건을 추가했다. 파라미터 건수만 많아져 검사를 대신하지 못한다. 실제 integration XML로 통과를 확인하고, 필수 시나리오 하나를 제거한 XML을 거부하는 것도 확인했다.

최종 결과는 **일반1,166개·격리 PostGIS146개**, ruff check/format·mypy app/etl/migrations135files 통과다. 일반 검사는 이번에 늘지 않았고 통합22개가 추가됐다. 최종 좌표누락 fixture 보강 후 연결22개도 재검증했다. 기존 Starlette deprecation 경고1건은 유지한다.

## 같은 값으로 취급하면 안 되는 항목

| 항목 | 현재 계약·검증 결과 |
|---|---|
| 이력의 total | 같은 건물의 지원 업종 전체. category는 진단 맥락, 날짜 결측/폐업도 보존. 반경의 현재 영업수와 비교하지 않음 |
| nearby.count / snapshot.N | 같은 조건·T의 영업 집합. N=still_open+closed_since+other=stores.length=nearby.count |
| Risk 동종업체수 / 활동 open_count 합 | 동일 좌표·반경·업종/필터·T이면 nearby.count와 같음. 활동 전체 cohort·개폐업 수는 폐업 이력도 포함 |
| 좌표 미확보 수 | nearby/snapshot은 **T시점 영업** 비공간 조건, 활동/Risk는 **T이전 개업 전체 이력**. 같은 숫자일 필요가 없고 반경 내 누락 수가 아님 |
| D와 T | D는 지원 원천의 검증된 DAT_UPDT_PNT 전역 최대 날짜. category/subcategory는 최소월에 적용. T는 최신 월의 D 또는 과거 월말 |
| 원천 없는 이력 | 기존 이력 API는0건·as_of=null을 허용. 준비 확인 API가 아니며 분석 API의 원천미준비500와 구분 |
| generated_at / regenerated | 현재 응답 문장조립시각 / 현재 요청 재생성 여부. 캐시 hit은 새 모델 호출이나 과거 재시도 이력을 뜻하지 않음 |

처음 실제 검증에서 좌표누락 수를 전 API에서 같다고 가정해 실패했다. 위 모집단 차이는 기존 구현과 [활동 요청서](fe-market-activity-api-request.md)·[Risk 요청서](fe-risk-reference-api-request.md)에 이미 명시된 계약이었다. 앱 값을 억지로 맞추지 않고 검증 가정을 수정했다. 합성 자료에도 폐업·좌표없음 행을 추가하여 주변1건/분석2건의 차이를 고정했다. 새 API/계약 변경은 없다.

여러 HTTP 요청 사이에는 writer가 없다는 검증 전제를 둔다. 운영 중 독립 요청들이 하나의 원자적 DB snapshot을 공유한다는 보장은 추가하지 않았다.

## 실제 개발 환경 결과

실제 로컬 uvicorn HTTP로 `/docs`·OpenAPI의 API10개·health와 연결을 확인했다. 카카오 실제 주소검색 결과를 다음 API 입력으로 사용했으며 주소/좌표/건물키/상호/원본응답은 보고서에 저장하지 않았다.

| 사례 | 이력 | 반경 영업수 | 후속 계산·AI |
|---|---:|---:|---|
| 1 | 5건 | 595건 | 시점·식별/분해·Risk/활동수·버전 일치, AI2요청/모의공급자1회 |
| 2 | 2건 | 604건 | 같은 조건 일치, AI2요청/모의공급자1회 |

완료 검증은 HTTP23요청·실제 카카오2회·모의 모델2회다. 앞선 가정 확인 중 카카오2회가 추가되어 이 작업의 실제 카카오 호출은 합계4회, **실제 모델 호출은0회**다. 모의 검증을 실제 LLM 성공/안전성 검증으로 해석하지 않는다.

API 앱과 검증 세션 모두 READ ONLY이며 개발 DB에 적재/수정·migration을 실행하지 않았다. head0009·앱모델 차이0·14테이블 전체 행/geometry hash·건수 보존을 확인했다. 캐시는 메모리, 운영 로그는 stderr여서 DB hash 대상을 제외하지 않았다. 파괴적 통합 suite는 일회용 테스트 DB에서만 실행했다.

## 재현

기존 프로젝트 환경을 준비한 뒤 저장소 루트에서 실행한다. 아래 명령의 integration은 **분리된 임시 PostGIS 관리자 DB**에만 연결해야 한다. 로컬 실행에는 `TEST_DATABASE_URL`과 `SPOTON_ALLOW_DB_INTEGRATION=1`이 필요하고 `.env`의 개발 DB와 동일 대상은 거절한다. 실제 비밀값을 문서/셸 출력에 붙이지 않는다.

```powershell
uv run --locked --extra dev pytest tests/integration/test_analysis_flow.py -m integration -q
uv run --locked --extra dev pytest -m integration -rA --junitxml=integration.xml
uv run --locked --extra dev pytest
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev mypy app etl migrations
```

CI는 고정 PostGIS image와 테스트 설정을 제공하며 XML 필수 시나리오 검사를 수행한다. 개발 DB 읽기/실제 카카오 확인은 CI에서 자동 실행하지 않는다. 실제 검증 시에는 기존 서버 전용 키/자료가 필요하고 인증 실패는 중단·요청한다. 로컬 일회용 검증 helper·집계 evidence는 ignored datasets에만 두며 원본·실제 .env/Docker 설정은 커밋하지 않았다.

## FE 전달·남은 작업

FE 코드·문서·이슈·PR은 수정하지 않았다. 요청서는 [이력](fe-store-history-api-request.md)·[주변](fe-nearby-api-request.md)·[월범위](fe-data-range-api-request.md)·[시점](fe-store-snapshot-api-request.md)·[활동](fe-market-activity-api-request.md)·[Risk](fe-risk-reference-api-request.md)·[AI](fe-risk-interpret-api-request.md)·[지원링크](fe-support-links-api-request.md)를 따른다. 이번 검증은 기존 요청서의 필드/의미를 바꾸지 않는다.

FE 담당자는 실제 주소 결과로 화면을 연결하고 null/0·source+license_no·과거월/기준일·API별 모집단·AI 실패/캐시 의미를 확인한 뒤 FE 계약/CLAUDE.md와 반영 결과를 전달해야 한다. BE 검사만으로 화면/진단서 출력·브라우저 오류·FE 완료를 표시하지 않는다.

브랜드 #57 활용승인·공식/조건부 수치의 경계/기간 의미·AI 추가문맥/자유문장 의미 검증 전체·지원링크 맞춤정렬·로그30일 보관/삭제·운영성능/보안·배포/최종 제출은 별도 미완료다. 이 문서는 전체 프로젝트 완료 보고서가 아니다.
