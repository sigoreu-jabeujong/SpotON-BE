# BE-33 상담·지원기관 링크 API (#70)

- 작성일: 2026-11-12
- 기준: develop `49205fd`, `feat#70-support-links-api`
- 상태: Codex 설계 → Claude 이 MD만 Read/Edit → Codex 최종 점검·구현·검증
- PR69 AI API는 CodeQL 시작 전 GitHub 내부 오류·Backend CI queued로 보류 중이다. 이 작업은 최신 develop의 독립 기능이며 PR69 코드/계약을 가져오거나 미검증 병합하지 않는다.

## 1. 원본과 공식 링크 확인

로컬 원본 `06_API명세서_SpotON_v1.2_최종.pdf` §4-9(11~12쪽)와 `07_데이터활용명세서_SpotON_v1.2_최종.pdf` §2.3 D-08(4쪽)·출처 R17(5쪽)을 직접 읽었다. `GET /api/support-links`, 선택 sigungu/category, links의8필드와 최초4기관·서버 설정/DB 관리·분기1회 수동 점검을 확인했다. 원본 PDF는 커밋하지 않는다.

| id | 기관 | 제공 URL | type | region |
|---|---|---|---|---|
| seoulsbdc | 서울시 자영업지원센터 | https://www.seoulsbdc.or.kr/main.do | consulting | 서울 |
| seoulsbdc-edu | 소상공인아카데미 | https://edu.seoulsbdc.or.kr/main/index.jsp | support_program | 서울 |
| seoul-small-business | 서울시 소상공인 지원사업 안내 | https://news.seoul.go.kr/economy/small-business-supports | support_program | 서울 |
| sbiz24 | 소상공인24 | https://www.sbiz24.kr | support_program | 전국 |

서울시 공식 지원사업 페이지에서 센터·아카데미 주소를 교차 확인했고 아카데미/소상공인24의 기관 설명도 확인했다. 외부 검색 도구에서는 센터가 timeout이었지만 별도 실제 HTTP GET은4곳 모두200·페이지 제목 일치를 확인했다. 아카데미는 `/main/index.jsp`에서 `/main`으로 이동한다. 응답 URL은 원본의 공개 시작 주소를 유지한다. 응답의 문구는 일반 안내로 직접 작성하며 공고/자격·지원금/모집 상태를 추정하지 않는다.

확인일은 실제 확인한 **2026-11-12**로 고정한다. HTTP200/내용 확인은 당시 공개 안내의 접근 확인이며 이후 가용성·로그인 뒤 신청 완료·지원 자격 보장이 아니다. 현재 날짜/배포일을 요청마다 확인일로 넣지 않는다.

## 2. 입력 계약과 우선순위 범위

- `sigungu`: 선택, 서울25개 자치구의 정확한 구명(예: 마포구). 기존 `SEOUL_AUTHORITY_CODES.values()`를 재사용한다. 서울 밖/접두사/공백·빈값·null문자열은422다. 생략만 기본값이다.
- `category`: 선택, cafe/restaurant. 생략 가능하므로 잘못된 값은 CATEGORY_REQUIRED가 아닌422 INVALID_PARAM이다.
- 미지원 인자/동일 인자 중복은422다. 파라미터는 링크를 만들거나 외부 URL에 붙이지 않는다. 공개 API가 임의 URL을 받아 호출하는 기능은 없다.

원본은 지역/업종 관련 링크 우선 정렬을 요구한다. 현재4기관은 서울/전국 및 지원 업종 공통 안내이고 검증된 특정 구/업종별 후보가 없다. 따라서 입력은 검증하지만 네 링크를 제거하거나 맞춤 선정된 것처럼 재배열하지 않는다. 원본 목록 순서로4개를 모두 반환한다. `meta.prioritization={status:not_applied,reason:general_links_only}`로 현재 한계를 명시한다. 구별 센터/업종별 공고를 확인해 추가하는 시점에 정렬 계약을 확장하며 현재 구현을 전체 맞춤 정렬 완료로 표시하지 않는다.

## 3. 응답·설정·수명

`{data:{links:[...]},meta,error:null}` 공통 외피다. 항목은 id/org_name/title/description/url/type/region/last_checked이며 id는 FE 기존 mock과 같은 안정적인 문자열이다. type은 consulting/support_program, region은 서울/전국, last_checked는 ISO날짜다. title/description은 일반 안내이며 해당 기관이 지금 모든 요청자에게 지원을 제공한다고 단정하지 않는다.

첫 버전은 `app/core/support_catalog.py`의 서버 관리 불변 tuple을 설정으로 쓴다. 항목은 frozen Pydantic 모델·중첩 가변값 없음으로 만들고 반환 목록은 매번 새로 생성한다. url은 HTTPS·정확한4개 공식 호스트·사용자정보/포트/query/fragment 없음만 허용한다. (Claude 검토 추가) URL 필드를 Pydantic `HttpUrl`로 직렬화하면 `https://www.sbiz24.kr`이 `https://www.sbiz24.kr/`로 정규화될 수 있으므로, 응답 문자열은 `str`로 보관해 원본 그대로 내보내고 검증은 `urllib.parse` 등으로 별도 수행한다(또는 정규화 형태를 계약으로 명시하고 테스트를 그에 맞춘다). 신뢰된 배포 설정이지 클라이언트/환경변수/DB에서 받는 임의 링크가 아니다. 목록/확인일 변경 시 카탈로그 버전을 올리고 실제 확인일만 기록한다. 자동 주기 작업/네트워크 healthcheck는 만들지 않고 분기1회 수동 점검을 운영 기준으로 남긴다.

meta는 source=[R17], as_of/space/denominator/collected_at/data_version=null, is_demo=false, data_updated_at=목록 last_checked 최대 날짜, link_catalog_version=support-links-v1, 위 prioritization이다. 여기의 data_updated_at은 카탈로그 확인일 기준이며 개별 공고 공표일·모집 마감일·통계 기준일이 아니다. 원천 ETL 날짜와 섞지 않는다.

요청 중 DB·카카오·LLM·외부 사이트를 호출하지 않으며 DB URL/인증키가 없어도 응답한다. DB 모델/migration·의존성·Docker/.env·FE 저장소·기존 API 계약은 바꾸지 않는다. 모든 정상/입력/서버 오류 응답은 no-store이며 오류는 원문 없는 기존422/500을 쓴다. serialization/미처리 결함도 route wrapper에서 기존 안전한 오류 로그(type만)·500/no-store로 정리한다.

## 4. 파일과 FE 요청

- schemas/support.py: 선택 요청·불변 항목·응답 모델과 링크 안전성
- core/support_catalog.py: 검증된4곳/확인일·버전 설정
- services/support_links.py: 새 응답 목록과 meta 구성
- routers/support.py: 중복/미지원 인자·입력 검증·no-store·OpenAPI
- main.py: 새 GET router 등록. 키/DB 초기 접속이나 기존 경로 동작은 바꾸지 않는다.
- tests/test_support_links.py: 동작·계약·격리·실패/안전성 회귀
- BE README/CLAUDE.md/작업계획·docs/fe-support-links-api-request.md: 실제 연결/일반 목록/수동 확인일/외부 링크 안내 요청. FE 코드는 담당자가 관리한다.

## 5. 검증과 완료 기준

정상4기관·고유ID·날짜/출처·정확한URL/기관·기본순서, 전체25구×두업종/생략 조합에서 목록 보존, 빈/중복/미지원/서울밖/주소·악성입력422 및 원문 비노출, HTTPS/공식 호스트·frozen/응답변조 격리, 서비스/serialization 결함500/no-store·안전로그, OpenAPI 입력/응답·CORS, 외부·DB·LLM 차단 상태의 정상 동작을 검증한다. 단순 데이터 상수 복사 테스트 대신 계약과 실제 경계 동작을 확인한다. (Claude 검토 추가) 시스템 날짜를 다른 날로 고정해도 last_checked/data_updated_at이 2026-11-12로 유지되는지, 응답 URL 문자열이 끝 슬래시 추가 없이 제공 URL과 정확히 일치하는지, 대소문자 변형(`Cafe`)·NFD 분해형 구명·전각 공백 입력이 422인지도 확인한다.

전체 일반pytest·ruff/format·mypy를 실행한다. SQL/DB 모델 변경이 없으므로 새 파괴적 통합 테스트나 개발 DB 적재는 만들지 않는다. 실제 로컬 서버에서 endpoint/오류/health/docs를 HTTP 확인하고 공식4사이트 확인 결과와 구분한다. 실제 .env 비밀값/인코딩 변형·git diff check·FE 변경0을 확인한다. 지정 양식 PR·CI/CodeQL 성공 후 develop 일반 Squash 병합한다. 외부 검사 시작 오류가 지속되면 PR/이슈를 보존하며 병합·완료로 표시하지 않는다.

## 6. Claude 검토 요청

이 MD만 Read/Edit한다. 코드/다른문서/Git/DB/.env/네트워크 접근 금지. 원본/코드를 직접 보지 않은 한계를 명시하고, 공식링크/수동 확인일·맞춤정렬 한계의 정직성·설정/불변성·입력/URL안전·오류/수명·FE 호환/검증 누락을 검토한다. 결과를 §7에 직접 기록하고 필요한 본문 수정은 근거와 함께 남긴다. Codex가 실제 코드/원본/검증 결과와 최종 대조한다.

## 7. Claude 검토 결과 (2026-11-12)

### 7.1 검토 범위와 한계

- 이 MD 한 파일만 Read/Edit했다. 원본 PDF(06/07), 코드(`SEOUL_AUTHORITY_CODES`, 공통 외피·오류 핸들러·로그 wrapper), FE mock, 다른 문서, Git, DB, .env, 네트워크는 보지 않았다.
- 따라서 다음은 **문서 서술을 전제로 한 검토**이며 Claude가 독립 검증하지 않았다: 원본 §4-9 8필드·최초4기관·분기1회 점검 문구, 4개 URL의 실제 HTTP200·제목 일치·아카데미 리다이렉트, 확인일 2026-11-12, FE mock의 id 값, 기존 422/500·no-store·CORS 동작. Codex가 원본/코드/실측 결과와 대조해야 한다.

### 7.2 본문 수정 (근거 포함)

1. §3 URL 직렬화: `HttpUrl` 사용 시 호스트만 있는 `https://www.sbiz24.kr`에 끝 슬래시가 붙어 "원본 공개 시작 주소 유지"(§1)·"정확한URL"(§5) 계약과 어긋날 수 있다. 문자열 보관 + 별도 검증을 권고하는 문구를 추가했다.
2. §5 검증 보강: §1의 "요청마다 현재 날짜를 넣지 않는다"는 약속을 회귀로 고정하기 위한 날짜 고정 테스트, URL 문자열 정확 일치, 대소문자·유니코드 정규화·전각 공백 입력 422 케이스를 추가했다.

### 7.3 항목별 판단

- **공식 링크/수동 확인일 정직성: 적절.** 확인일을 실제 확인일로 고정하고, HTTP200이 가용성·자격·신청 완료 보장이 아님을 명시한 점, 검색 도구 timeout과 직접 GET 결과를 구분해 적은 점은 정직하다. 다만 "누가·어떤 도구로" GET했는지(Codex 실행 환경) 한 줄을 PR 본문에 남기면 다음 분기 점검 재현성이 높아진다. 아카데미는 리다이렉트 대상이 같은 호스트(`edu.seoulsbdc.or.kr`)인지 확인해 두는 것을 권고한다(다른 호스트면 허용 호스트 정책과 설명이 어긋남).
- **맞춤정렬 한계: 적절.** 입력은 검증하되 결과를 바꾸지 않고 `meta.prioritization=not_applied`로 표시하는 것은 "맞춤 정렬된 것처럼 보이지 않게" 하는 정직한 처리다. FE가 이 값을 무시하고 "내 지역 맞춤" 문구를 쓰지 않도록 FE 요청 문서에 명시가 필요하다. 원본이 "지역/업종 우선 정렬"을 요구하므로 PR/작업계획에 **원본 요구 부분 미충족**으로 남겨야 하며 완료로 표시하지 않아야 한다(§2 서술과 일치).
- **설정/불변성: 대체로 적절.** frozen 모델 + tuple + 매 요청 새 목록은 응답 변조 격리에 충분하다. 확인 필요: (a) 공통 meta 모델이 `link_catalog_version`·`prioritization` 추가 필드를 허용하는지(extra 금지 모델이면 별도 meta 하위 모델 필요), (b) `data_updated_at`이 date인지 datetime인지 기존 meta 타입과 일치하는지, (c) last_checked 날짜의 기준 시간대(KST)를 문서화.
- **입력/URL 안전: 적절.** 파라미터가 URL 생성에 쓰이지 않고 임의 URL 호출 경로가 없으므로 SSRF/오픈 리다이렉트 위험은 낮다. 확인 필요: `SEOUL_AUTHORITY_CODES.values()`가 정확히 25개 고유 구명인지(중복/구 명칭 혼입 시 검증 범위가 달라짐), sigungu 오류 코드가 category와 같은 INVALID_PARAM인지 명시. 호스트 비교는 소문자 정규화 후 정확 일치로 하고 `endswith` 비교는 피한다.
- **오류/수명: 적절.** 외부/DB/LLM 미호출, 키 없이 동작, no-store, type만 로깅하는 500 정리는 일관된다. CORS preflight(OPTIONS) 응답은 미들웨어가 처리하므로 no-store 대상 여부를 기존 API와 동일하게 두면 된다(새 규칙을 만들 필요 없음).
- **FE 호환: 확인 필요.** id는 FE mock과 같다고 했으나 type 값(영문)·region 값(한글 "서울/전국")·필드명(snake_case)도 mock과 일치하는지 Codex가 대조해야 한다. FE 요청 문서에 외부 링크는 `target="_blank" rel="noopener noreferrer"`로 열고, last_checked를 "확인일"로 표기하며 모집/자격 정보로 오인되지 않게 안내하도록 적을 것을 권고한다.
- **검증 누락: §7.2로 보강.** 그 외 병합은 CI/CodeQL 성공을 전제로 하고 외부 검사 오류 시 보류한다는 기준은 PR69 상황과 일관된다. 이 작업이 PR69 코드에 의존하지 않는다는 점(§서두)도 테스트/임포트 수준에서 확인하면 좋다.

### 7.4 결론

설계는 범위·정직성·안전성 측면에서 구현 진행 가능하다. 차단 이슈는 없고, URL 직렬화 정규화(§7.2-1)와 공통 meta 모델 확장 가능 여부(§7.3)는 구현 전에 Codex가 코드로 확인해야 한다.

## 8. Codex 최종 결정

Claude의 실제 MD 수정 diff 전체와 결과(JSON is_error=false,5turns,permission_denials=[])를 읽었다. url은 처음부터 str로 유지하고 별도 검증해 원본 URL을 보존한다. 기본 목록4곳/순서·맞춤 미적용·수동 날짜의 정직성과 외부 링크 표시 의견을 채택한다. 확인일은 Codex Windows 실행 환경에서 HTTP GET·제목을 확인한 KST 날짜2026-11-12다. 아카데미는 같은 공식 호스트 안에서만 이동했다.

실제 ApiMeta는 dict[str,JsonValue]라 새 meta키를 허용하며 data_updated_at은 ISO date 문자열로 보낸다. 기존25구 상수의 고유구명25개, FE의8필드/id/type/region을 직접 대조했다. 두 입력 모두 잘못된 경우INVALID_PARAM이다. 구명/업종은 자동 strip/Unicode 정규화하지 않는다. 공식 호스트는 소문자 정확 일치·ASCII로 검사하며 suffix 일치나 HttpUrl의 출력 정규화에 기대지 않는다.

현재 목록에 구/업종별 후보가 없으므로 미래용 가짜 매칭/정렬·불필요한 내부 필드는 만들지 않는다. 원본의 맞춤 우선순위 요구 부분은 미구현임을 PR/작업계획/FE 보고서에 남긴다. CORS preflight는 기존 정책을 유지한다. 날짜가 고정 설정이므로 현재 시각을 바꾼 뒤에도 고정값이 유지되는 경계 테스트는 하되 별도 시계 의존성을 제품 코드에 추가하지 않는다. PR69의 미병합 AI 모듈을 참조하지 않으며 현재 develop에서 독립 검증한다.
