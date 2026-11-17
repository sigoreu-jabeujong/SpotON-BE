# fix#100 AI 클라이언트 시간 예산 테스트의 간헐 실패

- 이슈: [#100](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/100)
- 브랜치: `fix#100-gemini-budget-flaky-test` (develop `bdd3307`)
- 범위: 테스트 파일 1개(`tests/ai/test_gemini.py`). 앱 코드·공개 계약·DB·의존성 변경 없음.

## 1. 문제

`test_overall_budget_cancels_retry_sleep`가 전체 실행 중 가끔 `entered.is_set()` 단언에서 실패하고 단독 실행에서는 통과했다(#98 PR #99에 기록).

## 2. 원인(재현)

`event_client`의 기본 `time_budget=0.01`(10ms)을 그대로 썼다. `GeminiClient.generate`는 실제 asyncio 예산(`asyncio.timeout(time_budget)`)과 별도로 `monotonic` deadline을 POST 직후(`gemini.py` 128행)와 재시도 대기 직전(147행)에 검사한다. 첫 가짜 POST(429)가 10ms를 넘기면 deadline 검사가 먼저 TIMEOUT을 내 재시도 대기에 들어가지 못한다.

임시 스크립트로 첫 응답 지연별 재시도 대기 진입을 10회씩 측정했다: 0ms 9/10, 20ms 0/10, 50ms 0/10. 앱 동작은 의도대로이며(예산 소진 시 대기 생략) 테스트의 시간 가정이 부하에 취약했다.

## 3. 수정

- `event_client`에 선택 인자 `monotonic`(기본 `time.monotonic`)을 추가해 `GeminiClient`의 기존 주입 지점으로 넘긴다. 다른 호출부의 동작은 같다.
- 대상 테스트만 deadline 시계를 `0.0`으로 고정하고 asyncio 예산을 0.5초로 둔다. 첫 응답이 얼마나 걸려도 재시도 대기에 들어가며, 막힌 대기는 실제 asyncio 예산만 끝낼 수 있다. 검증 대상(진행 중 재시도 대기의 취소·TIMEOUT·대기 정리)은 그대로다.
- 첫 응답 지연 0ms·50ms로 파라미터화해 원래 실패 조건(지연된 첫 응답)을 회귀 사례로 고정한다. 바깥 `wait_for`는 5초로 늘려 예산보다 충분히 길게 둔다.

## 4. 검증

- `tests/ai/test_gemini.py` 49 passed, ruff check·format.
- 부하 검증: 전체 일반 테스트 3개를 동시에 실행(각 1,415 passed)하는 동안 대상 테스트를 16회 반복 실행해 16/16 통과(회당 2사례). 동시 실행된 전체 테스트 안에서도 3/3 통과.
- 이전 30회 반복도 통과했으나 당시 부하 작업이 잘못된 옵션(`-n 0`)으로 실제 부하를 주지 못했을 수 있어 근거로 쓰지 않는다.

## 5. Claude Code 검토 기록

- 확인: `GeminiClient.__init__`가 `monotonic`을 이미 주입받으며(`gemini.py` 77행) deadline 계산 3곳에서만 쓴다. 테스트에서 고정해도 asyncio 예산·취소 경로는 실제 이벤트 루프 시간을 쓰므로 검증 의미가 유지된다.
- 다른 `event_client` 사용 테스트(`test_total_budget_cancels_pending_transport...` 등)는 기본값이 바뀌지 않아 영향이 없다. pending transport 테스트는 응답 자체를 막아 10ms 예산과 무관하다.
- 한계: 0.5초 예산보다 첫 가짜 POST가 오래 걸리면 여전히 실패할 수 있으나, 부하 실측 최대값보다 한 자릿수 이상 크다. 실제 시계를 완전히 없애는 방식은 asyncio 예산 자체를 검증하지 못하게 되므로 택하지 않았다.
