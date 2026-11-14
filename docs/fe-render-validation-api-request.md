# FE 전달: Render 무료 BE 연결

- 확인일: 2026-11-14
- BE 배포·대표 API 검증 완료. FE 저장소·환경변수·배포는 수정하지 않았다.
- 상세 검증: [현재 무료 환경 안내](render-free-validation.md). 기존 유료 BE·DB는 삭제됐으며 이전 URL을 사용하지 않는다.

## 1. 연결 설정

검증 환경의 API base URL은 `https://spoton-be-free.onrender.com`이다. FE 담당자가 사용할 검증 환경에 다음 값을 설정하고 변경 사항을 반영해 실행한다.

```dotenv
VITE_API_BASE_URL=https://spoton-be-free.onrender.com
VITE_USE_MOCK=false
```

현재 FE 클라이언트가 `/api`를 붙이므로 값 끝에 `/api`를 추가하지 않는다. API 문서는 https://spoton-be-free.onrender.com/docs 이다. 실제 API 검증에서는 목업 모드를 끈다.

무료 BE는15분 무요청 후 절전한다. 최초 배포 검증의 첫 health 요청은22.593초였고 당시 FE 기본 요청 제한15초를 넘었다. 최신 FE develop `dcf8af1`에는 일반 요청45초·초기 health/주소 검색60초·느린 로딩 안내·제한된 재시도가 반영돼 있다. 30초나60초 이내 성공을 보장하지 않으므로 최종 실패 시 사용자 재시도 경로를 유지한다. Free의 SQL 제한10초·풀 대기15초는 전체 HTTP 시간 상한이 아니며, AI503은 계속 별도로 처리한다. 이 BE 작업에서는 FE 코드를 수정하지 않았다.

현재 허용된 브라우저 origin은 다음 세 개다. 기존5173을 유지하고 FE 담당자가 요청한 로컬5180·배포 도메인을 추가했다.

- `http://localhost:5173`
- `http://localhost:5180`
- `https://spot-on-fe.vercel.app`

Vercel production 도메인만 허용하며 preview 배포 URL·추가 도메인·다른 포트는 자동 허용하지 않는다. 필요하면 정확한 origin을 전달하고 BE의 CORS_ORIGINS에 추가한 뒤 재배포해야 한다. 경로·와일드카드·DB 주소를 FE 설정에 넣지 않는다. 브라우저는 BE만 호출한다. 이 설정은 Render BE에 적용하며 로컬 BE의 `.env`·코드 기본값은 별도로 유지한다.

2026-11-14 Render 재배포 후 세 origin 각각의 GET/POST preflight와 실제 GET200·Access-Control-Allow-Origin 정확 일치를 확인했다. 미허용 도메인·유사 도메인·localhost5181은 preflight400과 실제 GET의 허용 헤더 부재를 확인했다. `/api/ready`도200이다. FE 담당자는 위 base URL과 목업 해제 설정으로 브라우저 통합을 확인한다.

## 2. 적용 범위

- 주소 검색, 이력, 월 범위, 주변/과거 점포, 활동/Risk, 지원 링크는 기존 API 계약을 따른다. 공개24개 비교 및 실제 주소 검색·CORS 검증을 통과했다.
- AI 해석은 #127에서 활성화했다. Render의 LLM 키·공급자·모델 누락을 보완하고 실제 카페·한식 query-only POST의200·검증 통과를 확인했다. 공급자/한도/시간 초과503 AI_UNAVAILABLE과503 AI_VERIFY_FAILED 처리는 계속 유지한다. 키는 BE 비밀 환경변수에만 두며 FE에 추가하지 않는다.
- 공식 창업위험도는 기존 link_only·value=null·copy_text=null을 유지한다. 공식 market_change 등 pending 항목은 배포로 수치가 활성화된 것이 아니다.
- 최소·최대 조회 월은 `/api/meta/data-range`를 먼저 조회한다. 요청 as_of=YYYY-MM, 실제 적용일 meta.as_of=YYYY-MM-DD, 오류 meta={} 및 error의 code/message 계약을 유지한다.
- `/api/ready`는 Render 운영 검사이며 FE 업무 호출의 선행 조건으로 추가할 필요가 없다. 기존 `/api/health`도 유지한다.

## 3. FE 담당 검증

이 base URL을 사용해 주소 선택 → 건물/상세 위치 이력 → 주변/과거/활동/Risk 화면과 기존 오류·결측 표시를 확인한다. 브라우저 지도는 별도 Kakao 브라우저 키와 해당 FE 도메인 등록이 필요하다. BE 주소 검색200으로 FE 지도 연결 완료를 대신하지 않는다.

FE 담당자는 배포 화면의 실제 데이터 연결을 확인했다고 전달했다. 이를 모든 화면·오류·지도·출력의 전체 수용 검사 완료로 확대하지 않는다. BE 실모델 연결은 #127에서 확인했으며 FE 브라우저의 해석 표시와 운영 전환은 별도 확인 대상이다. API 계약에 관한 기존 BE 측 수정 요청 문서도 함께 적용한다.

## 4. FE 후속 제보 점검 (#122)

설계와 실제 Claude Code 검토·Codex 실행 근거는 [FE 후속 점검 설계](designs/feat122-fe-feedback.md)를 따른다.

### 결과 화면 동시 조회 — 최적화 배포 완료

풀만2개로 늘리면 최초 조회가 오히려 느려져 원래1개로 복구했다. 대신 이미 검증·병합된 출처 조회 최적화(#118)를8958ba7로 배포했다. 한식·2026-10·300/500/1000m에서 GET5개 동시 묶음의 최초/반복30요청은 모두200·기존 성공 본문과 완전히 같았다. 최초 묶음 중앙값16.5→9.7초, 반복15.2→6.1초였다. SQL10초·풀 대기15초·API 계약은 유지한다.

이는 준비된 서버의 이번 측정 결과이며 절전에서 깨어나는 시간을 포함한 보장이 아니다. FE의 초기60초·일반45초·로딩/재시도 처리를 유지하고, 동일 조건으로 배포 브라우저의 결과 화면을 다시 확인한다. BE는 이번 작업에서 FE 파일이나 배포를 변경하지 않았다.

### 한식의 제외 업종 혼입 — B안 BE 구현·배포 전 검증 (#128)

2026-11-14 Render DB689,440행을 전수 대조한 결과 원본 업태와 현재 ETL 저장 분류의 불일치는0건이다. 명동길14·500m·최신·한식의 nearby454개는 모두 원본 업태가 `한식`이다. 비비큐치킨 명동스타점·인생주점 등 상호 키워드로 찾은13개 검토 후보도 원본 한식이다. 이13개를 확정 제외 건수나 제보18개 전체 대조로 보지 않는다.

사용자가 B안을 선택해 BE는 원본을 유지하고 **음식점4종의 상호 키워드로 분석에서 제외**하는 정책을 구현했다. 치킨·통닭·호프·주점·포차·맥주·분식·김밥·떡볶·피자·카페·커피·cafe·coffee·베이커리·제과·빵집·bakery가 부분 일치하면 제외한다. 영문 ASCII 대소문자를 무시하며 cafe 업종과 null/빈 이름은 유지한다. "카페 M" 같은 실제 음식점도 제외될 수 있고, 내부 공백·분해 한글·전각·키워드 없는 상호는 남을 수 있다. 실제 업종 확정 보정이나 제보18곳 전체 해결로 안내하지 않는다.

이력·주변·과거·활동·Risk의 local/서울 분모/미좌표·월 범위와 AI 서버 계산에 같은 제외 집합을 쓴다. 원본 행과 전역 기준일·배치·브랜드 입력은 유지한다. 정책은 `meta.name_exclusion`, 버전은 `meta.data_version.name_exclusion_version=store-name-keywords-v1`으로 제공하며 입력/data 구조는 유지한다. 과거 이력에도 현재 이름 정책을 적용하므로 역사적 실제 업종 확정이 아니다. 제외된 가장 오래된 기록 때문에 `min_month`가 늦어져 이전 월 요청이422가 될 수 있으므로 `/api/meta/data-range`를 다시 읽는다.

실제 Free의 배포 전 후보는 위454→434곳으로20곳을 제외하고 남는 marker 전체가 독립 키워드 오라클과 일치했다. 카페 응답 data는 동일했다(이력은 교차 업종이므로 음식점이 함께 빠진다). 운영 코드 배포는 CI/병합 후 진행하며 FE 파일은 수정하지 않는다. [설계·Claude 실제 검토2회·검증](designs/feat128-name-keyword-exclusion.md)

FE [PR #52](https://github.com/sigoreu-jabeujong/SpotON-FE/pull/52)는 세부 업종이 인허가 신고 업태 기준이라 실제 메뉴와 다를 수 있다는 안내를 주변/활동/음식점 진단서에 반영했다. 최신 소스로 반영을 확인했으며 실제 점포 제외·집계 보정 완료를 뜻하지 않는다.

### AI 시연 — Render 연결·실모델 응답 확인 (#127)

2026-11-14 사용자 요청에 따라 기존 로컬 키의 실제 생성 성공을 확인하고 Render에 LLM_API_KEY·LLM_PROVIDER=google·LLM_MODEL=gemini-3.5-flash-lite를 등록했다. 같은 검증 commit7d4846c를 재배포한 `dep-dbs51tk9v7es73bn89tg`가live다. 카페·한식 query-only POST와 카페 재호출이 모두200·verification.passed=true·불일치0·재생성false였고 no-store와배포 FE origin의CORS 헤더도 확인했다. 이번 최초 두 조건의 응답은3.047/7.625초였으며 시간 보장은 아니다.

FE는 같은 배포 주소에서 화면을 새로 열고 "AI 해석 보기"를 눌러 실제 문장이 표시되는지 확인한다. BE 키를 FE에 추가하거나 직접 Gemini를 호출하지 않는다. 기본 해석 한도는 프로세스별5회/분·50회/일·동시2개이며 공급자 quota는 별도다. 503 실패 안내와 사용자의 명시적 재시도를 유지한다. 기존 코드의25초 해석 timeout을 유지했고 FE 파일/배포는 변경하지 않았다. API 성공은 FE 브라우저 전체 수용 검사나 실제 공급자 장애/한도 소진 화면 검증 완료를 뜻하지 않는다.

### FE CI — 담당자 반영 완료

FE [PR #53](https://github.com/sigoreu-jabeujong/SpotON-FE/pull/53)이 develop `4d27ab7`에 병합됐다. CI의 Lint 뒤·Build 앞에 다른 단계와 같은 조건으로 `npm run test --if-present`가 추가됐고, 해당 CI Unit test 로그의 **13파일98개 통과**를 직접 확인했다. 기존 로컬 checkout의78개는 이전 브랜치 결과다. 이 BE 작업에서는 FE CI/저장소를 직접 수정하지 않았으며 같은 요청을 반복하지 않는다.

```yaml
- name: Unit test
  if: steps.check.outputs.ready == 'true'
  run: npm run test --if-present
```

테스트 수를98개로 고정하는 검사를 추가하지 않고 최신 브랜치에서 실제 통과하는지 확인한다.

## 5. 현재 FE 확인 요청

- 같은 배포 주소에서 주소 선택→결과 화면을 새로 열고, 최초/반복 조회·반경300/500/1000m·과거월 변경이 정상인지 확인한다. 실패하면 API경로·HTTP상태/오류코드·시각을 전달한다. 키나Authorization 헤더는 공유하지 않는다.
- B안 배포 후 같은 조건의 주변 목록과 활동/Risk·과거월 수치를 함께 확인한다. BE가 공통 제외하므로 FE에서 별도로 상호를 숨길 필요는 없다. 원본 업태 안내를 유지하고 이름 추정의 오탐/미탐은 구분한다. 추가 사례는 source/license_no·API경로·월/반경/필터·기대 근거로 전달한다.
- `/api/ready`는 BE 운영 검사다. #124 동시 검사 실패 수정은 PR125/7d4846c로 Render에 배포됐고 ready24건·업무30건200/본문 동등성을 확인했다. FE 업무 호출의 선행 조건으로 추가하지 않는다. 현재 배포 상태와 한계는 [Render 안내](render-free-validation.md)를 따른다.
- AI 시연은 Render 실모델 연결을 완료했다. 화면을 새로 열어 해석 버튼→결과 표시를 확인하고, 503 실패 안내·수동 재시도를 유지한다. 키 설정이나 FE 재배포는 이번 BE 설정 변경의 추가 요구사항이 아니다.
