# BE-32 핵심 AI 해석 API (#68)

- 기준 develop `49205fd`, `feat#68-risk-interpret-api`, 2026-11-12
- 상태: Codex 설계 → Claude 이 MD만 실제 Read/Edit → Codex 최종 점검·구현
- 범위: query-only POST /api/risk/interpret, 서버 재계산/허용 집계·검증 후보의 LLM 선택·서버 문장 조립. 이력/활동 추가 문맥·캐시·FE 통합은 후속이다.

## 1. 원본·외부 모델 확인

로컬 API v1.2 §4-8 규칙25~29는 클라이언트 숫자 불신·서버 재계산·식별정보 제외·검증 후1회 재생성을 요구한다. #66 준비 함수가 구현됐고 key 존재만 확인했다. 실제 모델 메타 조회200·generateContent 지원을 확인했다. [공식 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)과 [공식 가격 안내](https://ai.google.dev/gemini-api/docs/pricing)의 구조화 응답/무료 tier 존재를 확인했지만 현재 프로젝트 과금 tier/생성 quota를 보장하지 않는다. 키/원문은 출력하거나 커밋하지 않는다. 실제 생성은 허용 집계만 소량 확인하고 권한/키/quota 차단이면 그 지점에서 사용자에게 요청한다.

## 2. 모델 역할과 공개 계약

기존 검증기는 알려진 숫자 집합만으로 자유문장의 지표 바꿔치기/인과 추측 전체를 보장하지 못한다. 이번에는 모델 자유문장을 배포하지 않고 **서버가 만든 사실·비교·체크리스트 후보의 ID 선택/정렬**만 받는다. 서버는 선택한 후보의 문장·지표 ID·출처를 그대로 조립한다. AI는 후보의 우선순위를 정하며 숫자 계산·방향 판정·새 사실 생성은 하지 않는다. 이것은 이번 BE의 제한된 해석 방식이며 자유로운 LLM 서술/원본·FE 합의 완료로 주장하지 않는다.

요청 `{query: RiskQuery}`만 허용한다. JSON sub_category 배열/문자열은 기존 query 규칙을 따른다. FE가 보낸 indicators/market/flags/context·경계 UUID·주소는422다. **첫 버전은 building_key/floor_unit도422**이며 받았다가 무시하지 않는다. 원본의 선택 이력 문맥은 후속으로 명시한다. query.as_of는 입력 YYYY-MM·radius이며 Risk 응답 echo의 YYYY-MM-DD/radius_m를 그대로 붙여넣는 방식은 지원하지 않는다. 중복 JSON키/NaN/미지원 쿼리·과도한 본문은422로 거절한다.

응답은 공통 외피, data={label,official_values,favorable,unfavorable,missing_data,checklist,verification,model,generated_at}다. 원본 필드명을 유지하고 metadata는 서버가 채운다. label='AI 해석', generated_at=서버UTC, model=실제 공급자 결과의 model이다. verification.passed=true·mismatches=[]·regenerated=생성2회 여부·checked_numbers=문장에 인용된 숫자 출현 횟수(정확도점수 아님)다.

## 3. 서버 후보와 필수 표시

- official_values는 서버의 fact 참고지표(현재 동종업체 수/충분한 표본의 폐업·생존율)를 **모두** 표시한다. 기존 필드명이지만 모두 공식이라는 뜻이 아니므로 문장에 참고 계산임을 명시한다. 미산정·공식 안내를 fact로 바꾸지 않는다.
- favorable/unfavorable 후보는 로컬/서울 비교가 모두 준비된 참고 비율에만 만든다. 폐업률은 서울보다 낮으면 favorable·높으면 unfavorable, 고정 주년 생존은 반대다. 같은 값은 어느 방향에도 억지로 넣지 않는다. 이는 과거 인허가 집계 차이이며 사업 성과·공식 위험 판정이 아니다. 동종업체 수에 임의 '많음/적음' 임계값을 만들지 않는다.
- missing_data는 모델 선택과 무관하게 서버가 미산정 지표/공식 안내·가맹 미확인·수집일/상권 적용 미확인·자료 한계를 빠짐없이 넣는다. 소표본·0분모와 실제0을 구분한다.
- checklist는 서버의 일반 현장 확인 질문(시간대 유동/보행동선/운영조건/가시성/실제 비교점포 등) 후보 중1~3개를 모델이 고른다. 현장 사실·폐업 원인·사업주 역량을 추정하지 않는다.
- 모델 선택은 각 배열0~3개(체크리스트1~3개), 중복 없음·해당 section 후보에 속하는 ID만이다. 없는 ID/다른 방향/자유 문장/추가키는 검증 실패다. 필수 사실/미확인 항목을 모델이 삭제하는 옵션은 없다.

후보는 #66의 안전 context에서만 만들며 raw query/주소/상권 후보/URL/배치 UUID를 쓰지 않는다. 프롬프트에는 안전 context+서버 후보 목록만 넣는다. 시스템 프롬프트 v3/지문과 구조화 선택 JSON schema를 갱신한다.

## 4. 생성·검증·수명·전체 예산

기존 generate_verified에 선택적 data_validator를 추가한다. 기존 일반 숫자/개인정보/금지표현/스키마 검사 후 후보 membership/section/중복을 확인하고, 유효하지 않으면 같은 요청으로 최대1회 재생성한다. 기존 호출자는 동작을 유지한다. 2회 실패는503 AI_VERIFY_FAILED다. 공급자 오류/미설정/quota는503 AI_UNAVAILABLE다. 원문/키/프롬프트는 응답·로그·예외에 남기지 않는다.

최종 문장은 서버 후보 그대로이며 보이는 문장만 묶어 #66 context의 숫자·개인정보·금지표현·길이/반복 검사를 재확인한다. 반복되는 machine reason/id/source 코드는 문장 반복 검사에 넣지 않는다. 지표/출처 연결은 후보 membership과 서버 조립으로 보장한다. metadata(model/시각/verification)는 LLM이 생성하지 않는다.

앱당 create_llm_client 1개를 state에 만들고 프로세스내 한도 카운터를 재사용한다. 실제 설정 값은 바꾸지 않는다. 현재 한도 값이 비어 있으면 앱 자체 RPM/RPD 제한은 없다는 점을 문서에 명시하며 제공자 quota/다중 프로세스 전역 한도를 보장하지 않는다. 실제 캐시는 BE-34 후속이다.

입력 검증 후 준비·생성/재생성·조립 전체를 settings.llm_time_budget(기본20초)의 monotonic deadline으로 감싼다. DB 준비는 asyncio.to_thread의 worker에서 새 READ ONLY REPEATABLE READ 세션을 열고 **LLM 호출 전에 닫는다**. 기존 history_session 내부의 세션 부분을 read_only_session(resources) contextmanager로 추출해 재사용하되 기존 동작/timeout은 보존한다. worker는 deadline/취소 Event를 각 SQL 직전에 검사하는 connection-local listener와 전후 검사로 후속 쿼리를 중단한다. global engine listener를 달지 않는다.

async deadline/취소는 provider await를 취소하고 Event를 설정한다. 실행 중인 동기 SQL은 즉시 강제 종료할 수 없으나 기존 문장3초 제한 후 worker가 rollback/close한다. 클라이언트 취소는 전파하고 늦은 정상 응답도 deadline 이후면 거절한다. timeout은503 AI_UNAVAILABLE다. 입력/DB 오류는 기존422/500을 유지한다. 예산은 네트워크/스케줄링 전체 SLA 보장이 아니며 비정상 worker/동시 부하 한계는 검증에 남긴다.

## 5. 구조·FE 범위

schemas/interpret.py(요청/모델선택/최종응답), ai/interpretation.py(후보/조립), services/risk_interpret.py(비동기 전체흐름), routers/interpret.py, main의client/라우터, db.read_only_session 재사용, verified의선택validator·prompt v3/지문이 대상이다. DB 모델/migration·의존성·원본·Docker/.env·FE 저장소는 변경하지 않는다. FE에는 기존 'Risk 전체 응답 전송' 대신 query-only·상태/오류·제한된해석·선택 이력 미지원에 대한 요청 보고서를 BE에 작성한다.

## 6. 검증·완료

일반: strict body/중복키/위조수치·후보 집합/방향/중복/빈비교/표본/실제0·정확한서버문장/출처·필수미확인유지·1회재생성/503·총예산/취소/늦은응답·앱client재사용/한도·schema/prompt지문·no-store/비노출·기존API회귀.

격리PostGIS: 실제 재계산→AI어댑터 mock→조립·조회조건변조차단·빈/과거/선택상태·LLM 시작전 세션 종료·READONLY/statement3s·DB실패/기존조회정상·worker취소cleanup. 실제 개발 DB는조회만 하며14테이블hash/건수·모델차이0/head0009를 확인한다.

실제 키/모델: 먼저 metadata200을 확인했다. 구현/모의검사 후 식별정보 없는 실제 집계로 최대 소수 요청(정상1~2건과 필요한1회 재생성)을 확인한다. 인증/quota 차단이면 실호출 반복을 중단하고 사용자에게 요청하며 mock을 실검증으로 표시하지 않는다. 실제 응답 원문·키·프롬프트/후보는 커밋하지 않고 집계 검증만 기록한다.

전체일반/격리PostGIS·ruff/format/mypy·실제비밀값검사·지정PR·CI/CodeQL 후 develop 일반 Squash 병합. PR `feat: 서버 검증 후보 기반 AI 해석 API 구현`, close #68. 이력/활동 추가문맥·캐시·공식/조건부지표·브랜드57·FE 통합은 후속이다.

## 7. Claude 검토 요청

이 MD만 Read/Edit한다. 코드/다른문서/Git/DB/네트워크/.env 접근 금지. 후보선택 해석의 정직성/제약·요청/응답 차이·숫자/상태/방향 보장·생성재시도·전체예산/동기worker cleanup·세션/client 수명·원문비노출·scope/테스트누락을 검토하고 근거/보류를 직접 기록한다. 코드/원본을 읽지 않은 한계를 남기고 Codex가 실제 코드와 최종 대조한다.

## 8. Claude 검토 결과 (2026-11-12)

검토 근거는 이 MD 본문뿐이다. 코드·원본 API v1.2·#66 구현·외부 모델 문서·DB는 읽거나 호출하지 않았다. 아래는 문서 내부 일관성과 설계 위험에 대한 판단이며 실제 코드 동작의 확인이 아니다. [필수]는 구현 전 반영을 권고하고, [권고]는 반영을 권하며, [보류]는 Codex/사용자가 판단할 사항이다.

### 8.1 정직성·선택 편향

- **[필수] favorable/unfavorable의 선택적 생략을 막는다.** §3은 official_values·missing_data는 "모두" 표시하면서, 방향 비교는 모델이 각 0~3개를 고르게 한다. 그러면 모델이 불리 후보만 남기고 유리 후보를 모두 빼는 식으로 사실은 맞지만 한쪽으로 치우친 구성을 만들 수 있다. 서버 후보만 쓴다고 해서 이 편향까지 막을 수는 없다. 비교 후보는 비율 지표(폐업률·고정 주년 생존율)에서만 나오므로 후보 수가 적다. 따라서 방향 후보는 **서버가 전부 포함하고 모델은 정렬만** 하도록 고치길 권한다. 후보가 3개를 넘을 수 있다면 3개 상한을 없애거나 서버가 결정적으로 고정 순서로 자른다. 이렇게 하면 모델 재량은 정렬과 checklist 선택에만 남는다.
- **[필수] 'AI 해석' 라벨과 실제 역할의 차이를 드러낸다.** 모델은 새 사실을 만들지 않고 선택·정렬만 한다. label은 원본 필드라 유지하되, FE 요청 보고서(§5)에 "문장은 서버 템플릿이며 AI는 후보 선택·정렬만 수행"을 화면 문구 요구사항으로 명시한다. 이 설명을 missing_data에 넣는 것은 '자료 미확인'이라는 의미를 흐리므로 권하지 않는다.
- **[권고] verification 필드의 의미를 좁게 문서화한다.** 실패하면 503이므로 정상 응답의 passed는 항상 true이고 mismatches도 항상 []이다. checked_numbers는 서버 문장의 숫자를 센 값이라 모델 품질과 관계가 없다. FE·보고서에 "사실 검증 점수가 아니라 선택 형식과 문장 안전성 검사 통과 표시"라고 적어 오해를 막는다.
- **[권고]** model 값은 재생성이 일어나면 최종 채택 호출의 결과를 쓴다고 명시한다.

### 8.2 숫자·방향·상태 보장

- **[필수] 방향 판정은 표시 정밀도 기준으로 한다.** 원값으로 비교하면 화면에는 서울과 같은 값(예: 12.3% vs 12.3%)으로 보이는데 favorable로 분류될 수 있다. 표시와 같은 반올림 값으로 비교하고, 같으면 어느 방향에도 넣지 않는다(§3의 "같은 값" 규칙을 구체화).
- **[필수]** 방향 후보는 로컬·서울 양쪽 모두 official_values와 같은 표본 충분 기준을 통과했을 때만 만든다. 소표본·0분모 쪽이 하나라도 있으면 비교 후보를 만들지 않고 missing_data로 보낸다. 실제 0(분자 0, 분모 충분)은 비교 가능하다.
- **[권고]** checklist 후보가 항상 1개 이상 존재하도록 고정 일반 질문 풀을 둔다. 후보가 0개일 때 모델이 1~3개를 고를 수 없어 반드시 AI_VERIFY_FAILED가 나는 경로를 테스트로 막는다.
- **[권고]** 후보 ID는 요청마다 서버가 매기는 불투명 단기 ID(f1, c2 등)로 하고, 지표 코드·출처 URL을 프롬프트 ID에 싣지 않는다. 그래야 §3의 "URL 미포함" 원칙과 맞는다.

### 8.3 요청 계약·FE 영향

- **[권고]** building_key/floor_unit을 422로 처리하고, Risk 응답 echo(as_of YYYY-MM-DD, radius_m)를 지원하지 않으면 FE가 Risk 요청 객체를 재사용할 때 바로 실패한다. FE 보고서에 "Risk 요청에 쓴 원본 query에서 building_key/floor_unit을 제외해 전송"을 명시하고, 422 오류의 field 위치를 그 필드로 정확히 지정해 원인을 알 수 있게 한다.
- **[권고]** sub_category 등 사용자 문자열은 기존 query 규칙의 허용 코드로 정규화된 값만 #66 context와 프롬프트에 들어가야 한다(자유 문자열을 통한 프롬프트 주입 차단). Codex가 #66 구현에서 이를 확인한다.

### 8.4 생성·재시도·오류 분류

- **[필수] 재생성 전에 남은 예산을 확인한다.** 남은 deadline이 공급자 최소 응답 시간보다 짧으면 재생성을 시작하지 않고 503으로 끝낸다. 각 호출의 timeout은 min(호출당 제한, 남은 예산)으로 둔다.
- **[권고] 오류 원인을 구분한다.** 서버 템플릿 문장이 #66 재검사(숫자·금지표현·길이)에 걸리는 것은 모델 탓이 아니라 서버 결함이다. 이 경우를 AI_VERIFY_FAILED로 숨기지 말고 500 계열로 처리하고 내부 로그(원문 없이 코드만)를 남긴다. 아울러 전체 템플릿×경계값 조합이 재검사를 통과하는지 단위 테스트로 고정한다.
- **[보류]** 모델이 2회 실패했을 때 서버 기본 선택으로 대체하면 가용성은 높아지지만, 'AI 해석' 라벨이 사실이 아니게 된다. 현재 설계(503)가 더 정직하므로 유지를 권하되, 대체가 필요하면 label·model을 바꾸는 별도 계약이 필요하다.
- **[권고]** DB 준비 단계에서 deadline을 초과해도 AI_UNAVAILABLE이 된다. 운영 진단을 위해 내부 로그에서는 단계(prepare/generate/assemble)를 구분한다. 공개 코드는 그대로 둔다.

### 8.5 예산·worker·세션·client 수명

- **[필수] 비용 남용 위험.** 앱 자체 RPM/RPD가 비어 있고 캐시도 없으므로, 공개 POST 1회가 곧 외부 호출 1~2회가 된다. 반복 호출로 공급자 quota나 과금을 소진할 수 있다. 실제 설정 값을 바꾸지 않는다는 원칙은 유지하되, PR 본문과 운영 문서에 **배포 전 차단 이슈**로 명시하고 공급자 429/quota 응답이 503 AI_UNAVAILABLE로 즉시 매핑되는지(재시도 폭주 없음) 테스트한다. 배포 환경에서 한도를 설정하는 일은 사용자 결정이다.
- **[권고]** asyncio.wait_for/취소는 to_thread worker 스레드를 멈추지 못한다. 이벤트 검사와 statement 3초 제한이 있어도 최악의 경우 (SQL 문 수 × 3초)까지 스레드와 커넥션을 점유한다. 기본 executor와 커넥션 풀이 다른 API와 공유되므로, 동시 timeout 부하에서 다른 API가 지연될 수 있다는 점을 한계에 기록한다. 필요하면 해석 전용 소형 executor나 세마포어를 쓰는 방안은 [보류]로 둔다.
- **[권고]** connection-local listener는 세션이 쓰는 Connection 단위로 등록한다. 커넥션이 풀로 돌아가기 전에 제거되거나 Connection 객체 수명과 함께 사라지는지, 그리고 READ ONLY/REPEATABLE READ·statement_timeout이 풀 반환 후 다른 요청에 남지 않는지 테스트로 확인한다.
- **[권고]** read_only_session 추출이 history_session의 기존 timeout·격리수준·예외 매핑을 바꾸지 않는지 기존 이력 API 회귀 테스트로 확인한다.
- **[권고]** 앱 state의 LLM client는 lifespan 종료 시 닫는다(내부 HTTP 세션 정리). 다중 worker 프로세스에서는 한도 카운터가 프로세스별이라는 §4 문구를 유지한다.

### 8.6 원문 비노출

- **[권고]** 예외 체인(`raise ... from e`)과 공급자 SDK 예외 메시지에 프롬프트나 응답 원문이 담길 수 있다. 공개 오류와 로그에는 오류 유형 코드만 남기고 원 예외의 문자열/repr은 기록하지 않는다. 이를 테스트(caplog로 원문 조각 미출현 확인)로 고정한다.

### 8.7 테스트 누락 보완

§6에 다음을 추가하길 권한다.
- 방향 후보 전부 포함·모델이 순서만 바꿀 수 있음(8.1 반영 시)
- 표시 정밀도 동일값은 방향 없음
- 한쪽만 소표본이면 비교 후보 없음 및 missing_data 포함
- checklist 후보 0개 경로 부재
- 남은 예산 부족 시 재생성 미시작
- 템플릿 재검사 실패를 500으로 분류
- lifespan 종료 시 client close
- 풀 반환 커넥션의 listener·트랜잭션 설정 잔존 없음
- 동시 timeout 부하에서 다른 API 응답성
- 공급자 429의 즉시 503 매핑
- 로그·예외 원문 미출현

### 8.8 한계

- 코드·#66·원본 v1.2·외부 모델 문서를 보지 않았다. 따라서 §1의 모델 존재·가격·quota, #66 context 필드, 기존 validator 구조, history_session 세부 동작이 문서 서술과 같은지는 확인하지 못했다. Codex가 실제 코드와 대조해 맞지 않는 부분은 이 절을 고쳐야 한다.
- 8.1의 "방향 후보 전부 포함" 권고는 후보 수가 적다는 가정(비율 지표 몇 개)에 기반한다. 실제 후보가 많으면 상한 정책을 다시 정한다.
- 비용·quota 위험과 한도 설정은 설계 문서만으로 해소되지 않으며 운영 결정이 필요하다.

## 9. Codex 최종 결정

Claude 실제 수정 diff 전체와 JSON(is_error=false,3turns,permission_denials=[])을 읽었다. 방향 후보 전체 포함/모델은 정렬만·표시값 기준 비교·명확한 제한 해석 설명·소표본 제외·남은 재생성 예산 검사·worker listener 정리·템플릿 결함500·2회 실패503을 채택한다. 기존 Gemini client는 generate마다 async HTTP context를 닫으므로 존재하지 않는 aclose 메서드를 새로 호출하지 않는다. getRisk가 이미1자리 비율을 반환하므로 그 값끼리 비교한다.

비용/자원 제어는 실제 .env를 바꾸지 않고 새 서버 설정의 보수적 기본값으로 처리한다. interpret_requests_per_minute=5, interpret_requests_per_day=50, interpret_max_concurrent=2를 앱당 재사용한다. 이는 운영상 기본값이지 공급자/다중 worker 전역 한도가 아니다. 요청 한도와 semaphore 대기 모두 전체 예산 안에 있고, 기존 LLM client의 한도 설정도 유지한다. 외부 배포는 이번 작업이 아니며 프로젝트/인프라 전역 정책을 완료로 주장하지 않는다.

후보 ID는 위치 식별자 아닌 고정 의미 코드로 유지한다. 불투명 단기 ID의 보안 이점은 없고 검증/재현성은 고정 allowlist가 낫다. 오류 응답에 원문 field값을 추가하지 않고 기존 고정422 메시지를 유지한다. 최종 method=server_sentences_model_ordering을 추가해 문장이 서버 작성·모델이 정렬/체크리스트 선택임을 명시한다. 원본/FE 합의 완료는 아니다. 단순 구조화 실제 생성 probe도200/STOP·JSON형식 일치로 확인했으며 실제 Risk API 생성 검증과는 구분한다.
