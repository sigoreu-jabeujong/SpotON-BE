# Claude Code 최종 구현 검수 원문

2026-11-17. claude-opus-5-5, tools 없음, 1turn, 185.00초, exit0, is_error=false, 제공 소스 지문 보존. 설계 및 구현을 읽은 정적 검수이며 테스트/DB/Gemini/브라우저/배포는 실행하지 않았다.

아래는 검수 당시 원문이다. 검수 이후 비차단 권고의 Codex 보완과 최종 정적 검사 결과는 [구현 기록](../designs/ai-three-section-implementation.md)을 따른다. Claude4차 검수는 없다.

---

# 판정: **PASS** (차단 결함 없음, 비차단 권고 7건)

## 확인 범위
- 제공된 설계, 변경 파일, 부속 소스를 읽어서만 대조했습니다.
- 테스트, DB, 브라우저, Gemini 호출, 배포, 정적 검사는 이번 검토에서 실행하지 않았습니다. 사용자가 밝힌 ruff·mypy·OpenAPI·lint·build 결과도 다시 확인하지 않았습니다.
- 다음 소스는 제공되지 않아 단정하지 않았습니다: `analysis_v2` 내부, `CategoryFilters`, `interpretation.CHECKLIST`, ROUTES, `riskBaseline`.

## 2차 지적 확인 결과 (부속 소스 기준)

**2차 N1(카페 + 주소 이력이 항상 422가 되는 문제)은 해소됐습니다. 차단으로 올리지 않습니다.**
- `closedHistoryParams`는 `q.category`가 없으면 null을 반환하고, 있으면 `category: q.category`를 그대로 넣습니다.
- `getLocationHistory`는 category가 없으면 예외를 던지고, 같은 값을 context 발급, GET, `ai_report_address_context` 세 곳에 씁니다.
- 그래서 `ReportRequest.history_baseline`의 업종 비교와 `verified_pair`의 업종 비교는 모두 같은 값을 보게 됩니다.

**2차 N4(판본 키·조회 조건 일치)도 해소됐습니다.**
- **조회 조건**:
  - FE `populationParams`는 lat, lng, radius, category, 정렬한 sub_category, as_of만 보냅니다.
  - BE `_prepare`도 같은 6개 필드만 남기고, `basis`가 sub_category를 정렬합니다.
  - location의 `time_mode`는 FE와 BE 모두 `latest_reference`입니다.
  - activity의 include는 양쪽 모두 `sales, living_pop` 순서이고, `basis`에서 include를 빼므로 토큰이 같습니다.
- **판본 키**: `stable_meta` 허용 목록이 실제 GET meta 키와 맞습니다.
  - location: `source_catalog_digest`, `source_refs`(loaded_at과 각 sha 포함)
  - grid: `observation_version_id`, `grid_version_id`, 각 sha 4종
  - address_history: `history_policy_version`, `address_index_version`, `data_version`
  - 시점마다 달라지는 `reference_snapshot_token`과 `population_snapshot_token`은 목록에서 빠져 있습니다.

**그 밖의 이전 지적(2차 N2, N3, N5)도 해소됐습니다.**
- **결과 표시(2차 N2)**: 결과는 캐시된 보고서와 현재 토큰이 일치하는지(`reportMatches`)로만 정합니다. `isFetching`·`isError`는 새 요청 버튼(`ready`)에만 씁니다. TanStack은 재조회 중에도 이전 data를 유지하므로 토큰이 그대로면 결과와 체크 상태가 남습니다.
- **요청 중 자료 변경(2차 N3)**: 응답 도착 시 `liveBaseline`과 다르면 `contextChanged`로 자료 변경 안내를 표시합니다.
- **행정동 이름(2차 N5)**: `area_label`은 `ReportMetric`에만 있습니다. 모델에 보내는 `candidates[role]`의 ReportText(text, evidence_ids, group_id)에는 들어가지 않고, 후보 문장에도 "행정동 참고자료 N" 번호만 씁니다.

**호출 수, 슬롯, 정리 작업은 이전 판단과 같습니다.** 정적 판단입니다.
- 공급자 재시도는 0, `attempts != 1`이면 검증 실패, 재생성 경로는 없습니다.
- 캐시 HIT은 슬롯을 예약하지 않고, partial 결과는 캐시에 저장하지 않습니다.
- 슬롯 반환은 await 전에 `available`을 먼저 늘립니다.
- `busy`는 준비 작업이 실제로 끝난 뒤에 풀리고, 스레드에 들어가기 전이면 준비 작업을 취소합니다.

**서버 문장 숫자 검증도 문제를 찾지 못했습니다.** 다음 숫자가 모두 근거 metric JSON이나 고정 숫자 목록에 들어 있어, 정상 입력에서 `_verify_sentences`가 500을 낼 경로를 찾지 못했습니다.
- 비율의 `.1f` 표기와 정수
- 표시용 문자열(display)
- 기간 문자열
- 라벨 안의 숫자(12개월, 1·3주년)
- 06·17·24·250

## 차단
없음.

## 비차단

**N1. 주소 이력 토큰이 이유 없이 409가 될 수 있습니다(확인 필요).**
- 문제:
  - `get_address_history`의 batches 조회에 ORDER BY가 없습니다.
  - 그런데 `meta.data_version.stores_batch_ids`의 순서가 그대로 토큰(`stable_meta`)에 들어갑니다.
  - PostgreSQL은 순서를 보장하지 않으므로 GET과 보고서 재조회의 순서가 다르면 내용이 같아도 409가 납니다.
- 수정안: `basis`에서 `stores_batch_ids`를 정렬하거나, 조회에 `order_by(batch_id)`를 추가합니다.
- risk·activity의 `data_version`도 정렬돼 있는지 `analysis_v2`에서 확인해 주세요.

**N2. PDF 화면으로 가기 전에 AI 결과 캐시가 사라질 수 있습니다.**
- 문제:
  - 새 캐시 키 `['ai-sections-v1', …]`는 `['risk','interpret']` 기본값(gcTime 30분)을 받지 못하고 5분이 적용됩니다.
  - STEP 04에서 5분 넘게 머문 뒤 PDF를 열면 AI 결과가 빠집니다. Gemini 호출은 0회 그대로입니다.
- 수정안: `queryClient.setQueryDefaults(['ai-sections-v1'], { gcTime: 30*60*1000 })`를 추가합니다.

**N3. 인쇄 화면 판정 경로를 확인해 주세요(확인 필요).**
- 인쇄 화면 판정이 `page.pathname === '/result/report'` 문자열 비교입니다. ROUTES가 제공되지 않아 실제 경로와 같은지 확인하지 못했습니다.
- 다르면 PDF 화면에서도 GET이 다시 실행되고 버튼이 보입니다. 결과는 토큰 일치일 때만 표시되므로 정합성 문제는 아닙니다.
- 수정안: `ROUTES` 상수를 쓰도록 바꿉니다.

**N4. 자료 변경 409가 한 번 더 나면 버튼이 모두 잠깁니다.**
- 문제:
  - `refreshes`는 초기화되지 않습니다.
  - risk 토큰이 그대로인 상태에서 다시 자료 변경 409가 나면 두 버튼이 모두 비활성화됩니다.
  - 이 경우 다시 마운트하기 전까지 진행할 방법이 없습니다.
- 수정안: 새 요청이 성공하면 `refreshes`를 0으로 되돌립니다. 또는 "조건을 다시 선택해 주세요" 같은 이동 안내를 함께 표시합니다.

**N5. 역할별 로그가 운영 환경에서 남지 않을 수 있습니다.**
- 역할 로그(`logger.info`)는 기본 로그 수준(WARNING)이면 출력되지 않을 수 있습니다.
- 설계의 "역할별 발송·성공·실패·캐시·시간 기록"이 실제로 남는지 확인이 필요합니다. 고정 JSON 로그(`core/operations`)로 옮기는 것을 권합니다.

**N6. 예상하지 못한 역할 예외 처리를 주석으로 남겨 주세요.**
- TaskGroup이 예외를 `ExceptionGroup`으로 감싸면 `InterpretRoute`를 거쳐 500이 됩니다.
- 결과는 안전합니다. 의도한 처리라면 주석만 남겨 주세요.

**N7. 구현 기록의 재검수 절이 비어 있습니다.**
- BE 구현 기록의 "재검수" 절은 아직 "실제 실행 후 기록"이라는 자리 표시만 있습니다.
- 이번 판정(정적 PASS, 런타임·Gemini·DB·브라우저 미검증)과 N1~N7 처리 여부를 그 절에 기록해야 합니다.

## 참고 (설계상 수용된 위험)
- 빈 후보용 `maxItems:0` 스키마를 실제 Gemini가 받아 주는지는 아직 확인되지 않았습니다.
- 논리 요청 한도는 주소 context 검증보다 먼저 차감됩니다.
- 기존 해석 요청이 슬롯 1개를 쓰는 중이면 새 보고서(슬롯 2개 필요)는 503이 됩니다.
- 이력 GET을 다시 조회할 때마다 Kakao `address-context` 요청이 생깁니다. Gemini 호출은 0회입니다.

이번 PASS는 정적 대조 결과일 뿐입니다. 런타임 정상 동작이나 배포 완료로 볼 수 없습니다. N1은 실제로 일어나면 정상 사용자에게 409가 반복되므로 배포 전에 수정하기를 권합니다.