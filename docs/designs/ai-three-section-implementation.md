# AI 해석 3영역 구현 기록

작성일: 2026-11-17. [검수된 설계](ai-three-section-interpretation.md)를 BE `8ce7dcb` / FE `374f36c` 기준의 별도 worktree에서 구현한다. 원래 사용자 작업 폴더의 미커밋 변경은 보존한다.

## 현재 구현

- 새 POST `/api/v2/risk/interpret/sections`: 이점·유의점·수치 해석 3역할. 기존 v1/v2 해석 API와 응답은 유지한다.
- 모델은 역할별 허용된 문장 ID만 반환한다. 후보 전부/그룹별 정확히1개를 검증하고 수치·설명은 서버가 조립한다. 모델에 주소·좌표·점포명·건물키·서명 context를 보내지 않는다.
- 공급자 재시도0/검증 재생성0, 정상 신규3회·cache/PDF0회·실패최대3회. 기존 공급자 limiter/동시 용량을 공유하고 새 보고서 동시1개로 제한한다.
- Risk/활동/위치 참고/격자/선택한v3이력을 같은 읽기 전용 RR에서 재조회하고 현재 화면 baseline과 대조한다. 실제 SQL/원천/운영 성능 검증을 수행했다는 뜻은 아니다.
- GET의 신규 `meta.ai_report_basis_token`은 내용/판본·정규화 조건을 기존 persistent signing key에서 HKDF로 파생한 HMAC 키로 서명한다. MVCC/request timestamp를 사용하지 않는다. location의 source_catalog_digest/source_refs와 격자 판본/지문, 주소 이력의 배치/정책 판본을 포함한다.
- v3 address-context는 좌표·업종이 바인딩된 context_version2를 발급하고 기존1도 GET에서 계속 허용한다. 새 보고서에 옛 토큰을 넣으면 주소 재확인용409를 반환한다. 새 생성 중 Kakao/context 발급은 하지 않는다.
- 이력은 과거 Risk 분석일이 아닌 최신 원천의 주소 이력임을 표시한다. 평균 영업기간은 선택 전체 통합값, 음식점 매출은 기존 합산/상위3 일치조건을 사용한다.
- FE v2는 상단 좌 이점·우 유의점, 아래 수치 해석/자료 카드와 기존 체크리스트3개로 표시한다. 모바일 한 단, 결과별 체크 초기화, 자동 POST/자동 retry/reload 없음. v1 로컬/Preview는 기존 해석을 유지한다.

## 실제 정적 검사 (테스트 묶음 미실행)

BE ruff check/format·mypy app(128 source files)·앱 import와 OpenAPI 경로 생성, FE TypeScript/Vite 일반 빌드·Vercel production v2 빌드·ESLint를 실행했다. 최신 보완본의 최종 결과는 아래에 정리한다. 단위/통합 테스트·실제 DB/모델/브라우저 확인은 사용자 지시에 따라 실행하지 않았고, 성공 건수나 수치 일치를 주장하지 않는다.

## Claude Code 실제 구현 검수

### 1차

claude-opus-5-5, 도구 없는 정적 검수1turn, 264.91초, exit0/is_error=false, 제공 파일 지문 보존. 판정 NEEDS_CHANGES.

- B1 필수 한계 문구가 cautions 실패 시 사라짐 → 응답의 독립 필수 limitations로 이동하고 실패 카드 안에도 항상 표시, FE가 별도 검증한다.
- N1 취소 시 provider 슬롯 반환 위험 → await 이전 용량 복구와 shield 알림.
- N2 준비 cleanup으로 응답이 예산 밖에서 대기 → 별도 소유 cleanup task가 admission/DB를 유지하고 HTTP는 즉시 종료. 스레드 진입 전 대기는 취소한다.
- N3 category의 context/GET/report 기본값 차이 → 동일 category를 세곳에서 명시 사용.
- N4 판본 필드 누락 → 실제 location meta의 source_catalog_digest/source_refs 및 이력 정책/인덱스 판본 추가.
- N5 이력 날짜 혼동 → 최신 원천 기준을 명시.
- N6 그룹 대안1개 → 같은 근거의 수치 우선/기간 우선 대안 두개를 제공한다.
- N7 인쇄 직전 숨겨짐 → 새 보고서 hook들의 인쇄 시 요청 비활성화, 부모의 인쇄 대기에 grid 요청도 포함.
- N8 체크리스트 원문 → BE 기존3개와 FE 상수가 동일함을 소스에서 대조했다(실행 테스트 아님).
- N9 분석일 → 두 서비스가 같은 current_provenance/effective_date 기준을 사용함을 소스에서 대조했다. 실제 DB 대조는 미실행이다.
- N10 종료 flight의 짧은 재사용 → done 콜백에서 즉시 제거.
- N11 오류 no-store → 기존 InterpretRoute 적용.

### 재검수

2차 claude-opus-5-5, 도구 없는 정적 검수1turn, 248.38초, exit0/is_error=false, 제공 파일 지문 보존. PASS(차단 없음). 카페 업종 경로·실제 판본 키를 부속 소스로 추가 확인하고 배경 GET 중 결과/체크 유지, 생성 중 자료 변경 안내, 모델에 전달하지 않는 행정동 표시 이름을 보완했다.

3차 최종 claude-opus-5-5, 도구 없는 정적 검수1turn, 185.00초, exit0/is_error=false, 제공 파일 지문 보존. PASS(차단 없음, 비차단7건). [실제 최종 검수 원문](../reviews/ai-sections-implementation-claude.md)을 보존한다. 실제 Gemini/DB/브라우저·배포 검증을 하지 않았으며 PASS는 정적 판단이다.

최종 검수 이후 비차단 권고 처리는 Codex가 수행했고 Claude 4차 검수는 실행하지 않았다.

- N1: basis에서 data_version.stores_batch_ids를 정렬해 주소 이력의 SQL 행 순서가 토큰을 바꾸지 않도록 했다. Risk/활동의 current_provenance는 source/batch_id ORDER BY가 있음을 소스로 확인했다.
- N2: ai-sections-v1의 FE 캐시 보관을 기존 해석과 같은30분으로 명시했다.
- N3: 인쇄/주소 이동 경로는 ROUTES 상수를 사용한다. 실제 report 경로는 기존 문자열과 같음을 확인했다.
- N4: 정상 응답 시 재조회 횟수를 초기화하고 반복409에는 조건 재확인 링크를 제공한다. 자동 재생성/페이지 reload는 없다.
- N5: 역할/캐시 로그를 기본 logger.info 대신 operations의 고정 JSON 진단 이벤트로 옮겼다. 역할/상태/시간만 허용하고 원문·주소·키는 쓰지 않는다. 기존 llm_http_attempt가 실제 발송 수를 기록한다. 신규 진단 이벤트의 장기 보관기 지원이나 운영 수집 완료를 주장하지 않는다.
- N6: 예상 밖 TaskGroup 오류는 검증된 부분 결과로 오인시키지 않고500으로 전파한다는 주석을 추가했다.
- N7: 이 재검수 기록과 최종 원문을 저장했다.

추가로 aggregate meta.source에 모든 지표 출처를 포함했고, 그 목록의 JsonValue 정적 타입 cast를 보완했다. 실제 값은 동일하다. 누락 분기/관측일은 None 문자열 대신 안내 문구로 표시한다. 숫자 정밀도·exact_zero/rounded를 보존한다.

최종 Codex 정적 검사: ruff check 전체 통과, ruff format --check 전체496파일 통과, mypy app128파일 통과, DB/환경 없이 앱 import/OpenAPI 새 경로 존재 확인. FE ESLint와 Vercel production v2의 TypeScript/Vite 빌드도 통과했다. 테스트 묶음은 실행하지 않았다.

## 배포 순서와 미완료

BE 새 API/GET token/context2 발급을 먼저 반영한 뒤 FE develop→main을 배포한다. 기존 AI API가 공존하므로 FE를 먼저 이전 릴리스로 복구할 수 있다. DB 마이그레이션·원천 적재·환경 파일 수정은 없다. 현재 Render 설치·연결은 사용자 진행 중이며 앱 연결을 확인하지 않고 배포했다고 표시하지 않는다. 실제 Gemini 호출은 아직0회다.
