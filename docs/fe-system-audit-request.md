# 전체 시스템 점검에 따른 FE 수정 요청

- 작성일: 2026-11-12
- 대상: FE 담당자
- 관련 BE 이슈: [#78](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/78)
- 검사 기준: FE develop `21ec13fb59d1eed456c150b2c99300d9fe755d5a`, BE develop `45a6bbf` 이후
- 상태: **실제 브라우저 재현 완료 / FE 수정·검증 요청**

FE lint·build는 통과했지만 실제 BE 연결과 유효한 결측 응답에서 아래 문제가 재현됐습니다. BE의 공개 응답은 기존 요청서 계약에 맞으며, FE에 맞추기 위해 서버 검증을 완화하거나 결측을 가짜 값으로 채우지 않습니다. FE 파일·설정·문서·이슈·PR은 이번 작업에서 직접 수정하지 않았습니다.

정상 표본에서는 실제 이력5행과 요약 PNG 생성·인쇄 버튼·PDF메모리 렌더1페이지가 동작했습니다. 이를 결측/오표시 문제의 해결로 보지는 않습니다. 아래 실패는 정상값만 있는 화면과 별도로 재현한 결과입니다.

브라우저는 headless Chrome, 데스크톱1440×1100, VITE_USE_MOCK=false로 실행했습니다. 서버만 테스트용 주소/CORS 설정 복사본을 사용했고 실제 .env는 수정하지 않았습니다. 브라우저의 AI 공급자는 강제로 모의 처리하고 실제 LLM 송신은0회였습니다. 별도 BE 실모델 검사는2회200·서버검증 통과였습니다.

## 1. AI 요청이422로 거절됨 — P1

**실제 BE와 브라우저에서 재현했습니다.** 종합 진단 화면에서 `AI 해석 보기`를 누르면 `/api/risk/interpret`가422 INVALID_PARAM으로 끝납니다. 이후 Risk GET은200을 유지하지만 AI 결과는 표시되지 않습니다.

현재 `AiInterpretation.tsx`는 Risk **응답**의 query와 market/indicators/flags/context를 본문에 넣습니다. BE는 서버 재계산을 위해 **원래 조회조건만 담은 query-only 본문**을 받습니다. 응답 query의 `radius_m`·일 단위 as_of·중첩 filters도 요청 형식과 다릅니다.

수정 요청:

- `src/types/risk.ts`의 `RiskInterpretRequest`를 원래 요청용 조건의 `{query: ...}`로 변경해 주세요.
- `src/components/summary/ai/AiInterpretation.tsx`에서 전달받은 원래 `params`로 본문을 만들고 market/indicators/flags/context는 보내지 마세요.
- `radius`와 `as_of=YYYY-MM`을 사용합니다. building_key·floor_unit·주소·화면 수치는 보내지 않습니다.
- AI 실패 후 자동 재호출을 반복하지 않고 지표는 유지합니다. 현재응답조립시각/generated_at·현재요청재생성/regenerated 의미도 기존 요청서를 따릅니다.

```json
{
  "query": {
    "lat": 37.5,
    "lng": 127.0,
    "category": "cafe",
    "radius": 500,
    "as_of": "2026-11",
    "include_unknown_area": true,
    "include_unknown_franchise": true
  }
}
```

위 좌표는 형식 설명용 합성값입니다. 상세 계약은 [AI 요청서](fe-risk-interpret-api-request.md)를 따릅니다.

## 2. 미확인 상권을 상권 밖으로 표시함 — P1

**실제 BE와 브라우저에서 재현했습니다.** 서버 `market.status=unverified` 응답에 종합 화면이 `서울시 지정 상권 밖 주소예요`를 표시합니다. 현재 `MarketCard.tsx`가 in_market이 아닌 모든 상태를 outside로 처리하고, `ReportPage.tsx`도 같은 분기를 사용합니다.

- `src/types/risk.ts`에 현행 `unverified` 상태와 nullable 필드를 반영해 주세요.
- `src/components/summary/MarketCard.tsx`와 `src/pages/ReportPage.tsx`에 미확인 분기를 명시해 주세요.
- 미확인을 상권 안/밖으로 확정하지 말고 상권 적용 기준을 확인 중임을 표시해 주세요.
- spatial_candidate가 있더라도 파일 형상 후보이며 공식 적용이 확정된 상권명/수치로 대입하지 않습니다.

상세 계약은 [Risk 요청서](fe-risk-reference-api-request.md)를 따릅니다.

## 3. open_date=null에서 이력 표·진단서가 깨짐 — P1

**BE 스키마 검증을 통과한 합성 응답으로 브라우저에서 재현했습니다.** 실제 데이터 일부 표본에서 null이 없더라도 허용된 API 경계입니다. 날짜가 null인 행과 날짜가 있는 행을 함께 주면 `b.open_date.localeCompare(a.open_date)`에서 TypeError가 발생합니다. 이력 표는 사라지고 출력용 진단서의 main.report도 렌더되지 않았습니다.

- `src/components/analysis/history/HistoryTable.tsx`와 `src/pages/ReportPage.tsx`의 정렬을 null 안전하게 변경해 주세요.
- 최근 개업 순 표시를 유지하되 날짜 미확인을 마지막에 두고, 같은 날짜는 source·license_no로 순서를 고정해 주세요.
- 서버/React Query 캐시 배열은 복사한 뒤 정렬하고 날짜를 임의로 생성하지 마세요.
- `src/types/stores.ts`의 HistoryStore에 nullable 날짜·상호·기간 및 source·기간상태/사유를 반영해 주세요.

## 4. 다른 source의 같은 license_no가 React key 충돌 — P2

**BE 스키마 검증을 통과한 합성 두 행으로 재현했습니다.** 관리번호는 같고 source가 다른 두 행을 전달했을 때 두 행은 보이지만 React의 중복 key 경고가 발생했습니다. 이후 정렬/갱신 때 행 재사용 문제가 생길 수 있습니다.

- 이력 표·진단서 및 중복 제거의 식별값을 `${source}:${license_no}`로 변경해 주세요.
- 두 원천의 같은 관리번호를 하나로 합치지 않습니다.
- 이번 브라우저 재현은 이력 표 기준입니다. nearby/snapshot 등 다른 목록도 기존 요청서에서 source가 추가됐으므로 같은 식별 원칙을 검토해 주세요.

## 5. nullable 상호·기간이 빈칸으로 표시됨 — P2

**BE 스키마 검증을 통과한 합성 응답으로 재현했습니다.** open_date는 유효하지만 name=null·operating_months=null인 폐업 기록을 주면 표의 상호와 기간 셀이 빈칸이 됩니다. format 함수의 null 반환만으로는 정보 없음/미산정 사유가 표시되지 않습니다.

- 상호·날짜·기간 결측은 `정보 없음`으로 표시하고 기간은 operating_period_reason을 함께 보여 주세요.
- 폐업일이 없는 폐업 기록의 상태는 유지하고 `폐업일 정보 없음`을 구분해 주세요.
- operating_months=0/fact는0개월, null/no_data는 미산정으로 구분합니다.
- 표와 출력용 진단서에 같은 기준을 적용해 주세요.

3~5번의 상세 필드/문구/합성 예시는 [이력 요청서](fe-store-history-api-request.md)를 따릅니다.

## 6. 지도 검증 선행 설정

최초 검사 시 FE의 `VITE_KAKAO_JS_KEY`가 설정되지 않아 지도 SDK·마커/정보창·표 선택 연동 검증을 중단하고 사용자에게 로컬 설정을 요청했습니다. BE의 KAKAO_REST_API_KEY와 다른 JavaScript 키입니다. 키/카카오 지도 사용 설정·허용 웹 도메인이 준비된 뒤 검증해야 하며, 표/API 성공으로 지도 성공을 대신하지 않습니다.

나머지 화면 검사는 지도 SDK 성공을 전제로 하지 않았습니다. 설정 이후 후속 결과는 [전체 기능 감사 보고서](be-system-audit.md)의 지도 항목을 확인합니다. 이번 문서에 실제 키나 개인 주소는 기록하지 않습니다.

## 완료 기준

- [ ] 실제 주소 검색 결과로 이력 표·활동·Risk·지원기관 화면 연결
- [ ] AI query-only 본문으로200 및 검증된 해석 표시, 입력/공급자실패 시 지표 유지
- [ ] unverified를 상권 밖으로 표시하지 않음, 출력용 진단서도 동일
- [ ] nullable 날짜가 있어도 표/진단서가 깨지지 않고 미확인 날짜가 마지막
- [ ] 같은 license_no·다른 source 두 행 유지, React key 경고 없음
- [ ] null 상호/기간·폐업일 결측 사유와 실제0개월을 구분
- [ ] 지도 SDK·반경/마커/표 선택·정보창 동작 확인
- [ ] FE lint/build·관련 회귀 및 실제 BE 브라우저 연결 확인
- [ ] FE 타입/계약/결정문서/CLAUDE.md 반영 후 BE에 변경 내용 전달

BE API/응답 형식은 이번 감사에서 바꾸지 않았습니다. FE 담당자가 수정하고 검증 결과를 전달하기 전에는 위 항목을 완료로 표시하지 않습니다.
