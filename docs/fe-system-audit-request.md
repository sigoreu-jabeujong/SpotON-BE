# 전체 시스템 점검에 따른 FE 수정 요청



## 2026-11-14 현재 확인 — 구현 중복 요청 대신 남은 경계 확인

최신 FE develop `4bf012f`와 BE `02b5288`을 대조했다. FE는 읽기/단위 검사만 수행했고 파일·설정·문서·이슈·PR은 수정하지 않았다. 이번 FE 단위14파일108개가 통과했다.

| 최초 문제 | 최신 소스 확인 | 남은 확인 |
|---|---|---|
| F1 AI 구형 본문422 | toRiskInterpretRequest가 원래query와 선택history만 전송, 자동 재시도 없음. #134는 공개 실제AI200/4문단 검증 완료 | 이번 실모델 호출은0회, #134 근거와 구분 |
| F2 unverified→outside | MarketCard·ReportPage에명시적인unverified 분기·안내가 있음 | 최초 반례의 브라우저 표시 재주입 |
| F3 null 개업일 정렬 | HistoryTable·ReportPage의sortHistoryRecentFirst와null/복합식별 단위 검사 | 최초 결측 표·진단서 브라우저 경계 재주입 |
| F4 source별 같은번호 충돌 | 표·Map선택/콜백/find·React key가storeKey(source,license_no)를 사용 | 다른 좌표 두 원천·조건변경·언마운트의 실제 지도 정리 |
| F5 nullable 상호·기간 | storeName/storePeriod/사유·실제0 단위 검사와 표·지도·진단서 공통 사용 | 최초 결측 표본 전체 화면/인쇄 확인 |

위 구현을 다시 추가해 달라는 요청은 하지 않는다. 아래1~5절은2026-11-12의 최초 재현 기록이며 그 당시의 "현재 코드/미해결" 서술과 이번 판정을 구분한다. 이력 선택 문맥은 현재 #98 계약의 `history={building_key,floor_unit}`를 허용하고 주소·수치·점포 목록을query에 넣지 않는다. 원본 업태에 더해 #128의이름 키워드 분석 제외가 적용되므로 FE에서별도상호필터를 추가하지 않는다.

새 BE 검증은 로컬160건/Render60건+snapshot4건 모두200·목록/집계/날짜·버전 일치, ready/CORS 통과다. 실제 배포는05790fa/dep-dbs5t55g1s2s73e8vorg를 유지했고 병합본의 기본대기10초는 운영의명시15초를 바꾸지 않는다. 외부 일반음식점100행 지연·운영/공식근거·과거unmatched500은 #78에남긴다. [최신 BE 감사](be-system-audit.md)·[실제 검증 설계](designs/feat122-concurrency-final-audit.md)를 따른다.

---

- 작성일: 2026-11-12
- 대상: FE 담당자
- 관련 BE 이슈: [#78](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/78)
- 최초 실행 검사 기준: FE develop `21ec13fb59d1eed456c150b2c99300d9fe755d5a`, BE develop `1f81baf` / 2026-11-12 재점검
- 최초 후속 문서 대조 기준: BE develop `135ec63`(PR #93·migration0011), 로컬 FE `21ec13f` / 2026-11-12
- 최초 상태(2026-11-12): **5종 재현·수정 요청 / 당시 지도 복합 식별 수정 대기**

FE lint·build는 통과했지만 실제 BE 연결과 유효한 결측 응답에서 아래 문제가 재현됐습니다. BE의 공개 응답은 기존 요청서 계약에 맞으며, FE에 맞추기 위해 서버 검증을 완화하거나 결측을 가짜 값으로 채우지 않습니다. FE 파일·설정·문서·이슈·PR은 이번 작업에서 직접 수정하지 않았습니다.

정상 표본에서는 실제 이력5행과 요약 PNG 생성·인쇄 버튼·PDF메모리 렌더1페이지가 동작했습니다. 이를 결측/오표시 문제의 해결로 보지는 않습니다. 아래 실패는 정상값만 있는 화면과 별도로 재현한 결과입니다.

브라우저는 headless Chrome, 데스크톱1440×1100, VITE_USE_MOCK=false로 실행했습니다. 서버만 테스트용 주소/CORS 설정 복사본을 사용했고 실제 .env는 수정하지 않았습니다. 브라우저의 AI 공급자는 강제로 모의 처리하고 실제 LLM 송신은0회였습니다. 별도 BE 실모델 검사는2회200·서버검증 통과였습니다.

## 현재 전달 기준

이하 브라우저·Claude 검토·성능 측정은 각 절에 기록된 당시 실행의 근거입니다. 현재 문서 대조를 브라우저 전체 재검사나 FE 수정 완료로 해석하지 않습니다. 최신 가맹 계약 및 공통 전달 기준은 아래 안내를 함께 적용해 주세요.

- 기본 타입·식별·결측·필터: [이력](fe-store-history-api-request.md)·[주변](fe-nearby-api-request.md)·[시점](fe-store-snapshot-api-request.md)·[조회 가능 월](fe-data-range-api-request.md)을 함께 검토합니다.
- 집계·해석·지원: [상권 활동](fe-market-activity-api-request.md)·[Risk](fe-risk-reference-api-request.md)·[AI 해석](fe-risk-interpret-api-request.md)·[상담·지원기관](fe-support-links-api-request.md)을 따릅니다.
- 가맹 관련 필드·상태·필터·표시는 [프랜차이즈 추정 추가 계약](fe-franchise-classification-api-request.md)이 공통 기준입니다. 현재 개발DB는2025년 목록을 적용해estimate/partial이며 미적용DB만pending입니다. history/nearby/snapshot은franchise_basis·franchise_reference_year를 반환하고 snapshot에는franchise도 추가됐습니다. 원본 is_franchise=null만 보고 전체 미확인으로 처리하지 않습니다.
- 가맹 전용 필터는franchise=franchise와include_unknown_franchise=false를 함께 전달합니다. 이름 일치를 실제 계약·과거 소속으로 확정하거나 미일치를 개인 매장으로 바꾸지 않습니다. AI의franchise_name_match_estimate 한계 안내도 유지합니다.
- 현재 공통 기준일은meta.as_of입니다. 오류 응답은data=null·meta={}·error={code,message}이며error.detail은 반환하지 않습니다. AS_OF_OUT_OF_RANGE의최소/최대월을error.detail에서만 찾지 말고data-range응답을 사용합니다. collected_at=null을 현재 날짜로 대체하지 않습니다.
- 현재 문서 검수에서는 JSON 예시의 BE 스키마·관련 상대 링크와 실제 로컬HTTP11건(정상8·입력 오류3)을 확인했습니다. AI는 잘못된 본문의422만 실제 호출했으며, 정상 AI 생성·전체 브라우저/지도·FE build를 이번 검수에서 재실행한 것은 아닙니다.

## 1. AI 요청이422로 거절됨 — P1

**실제 BE와 브라우저에서 재현했습니다.** 종합 진단 화면에서 `AI 해석 보기`를 누르면 `/api/risk/interpret`가422 INVALID_PARAM으로 끝납니다. 이후 Risk GET은200을 유지하지만 AI 결과는 표시되지 않습니다.

현재 `AiInterpretation.tsx`는 Risk **응답**의 query와 market/indicators/flags/context를 본문에 넣습니다. BE는 서버 재계산을 위해 **원래 조회조건만 담은 query-only 본문**을 받습니다. 응답 query의 `radius_m`·일 단위 as_of·중첩 filters도 요청 형식과 다릅니다.

수정 요청:

- `src/types/risk.ts`의 `RiskInterpretRequest`를 원래 요청용 조건의 `{query: ...}`로 변경해 주세요.
- `src/components/summary/ai/AiInterpretation.tsx`에서 전달받은 원래 `params`로 본문을 만들고 market/indicators/flags/context는 보내지 마세요.
- `radius`와 `as_of=YYYY-MM`을 사용합니다. building_key·floor_unit·주소·화면 수치는 보내지 않습니다.
- 최신 조회의 `as_of`는 원래 요청처럼 생략합니다. 응답 날짜를 자르거나 오늘 월을 임의로 넣지 않습니다.
- Risk GET에 `include`가 있으면 AI 본문에도 동일하게 넣습니다. 공통 `params`에 Risk용 include가 자동으로 들어 있다고 가정하지 않습니다. 현재 SummaryPage와 ActivitySection은 `useRisk(params)`로 include를 생략합니다.
- 현재 FE의 단일 `include_unknown`도 지원합니다. 이를 유지하거나 두 개의 개별 unknown 플래그로 바꾸되 두 형식을 혼용하지 않습니다.
- AI 실패 후 자동 재호출을 반복하지 않고 지표는 유지합니다. 현재응답조립시각/generated_at·현재요청재생성/regenerated 의미도 기존 요청서를 따릅니다.
- query-only 전환 후 `INVALID_PARAM`은 입력 형식 오류입니다. 기존의 '서버 지표 값 불일치' 주석과 지표 재조회 처리를 함께 검토하고 AI 재시도는 사용자 버튼으로 진행합니다.

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
- 같은 파일의 `MetricIndicator.source`도 실제 응답의 `string[]`에 맞춰 주세요. 현재 MetaLine은 배열도 받으므로 이 항목은 새 화면 장애로 분류하지 않고 타입 보완 요청으로 둡니다.
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

## 4. 다른 source의 같은 license_no가 key·지도 선택 충돌 — P2

**BE 스키마 검증을 통과한 합성 두 행으로 재현했습니다.** 관리번호는 같고 source가 다른 두 행을 전달했을 때 두 행은 보이지만 React의 중복 key 경고가 발생했습니다. 이후 정렬/갱신 때 행 재사용 문제가 생길 수 있습니다.

- 이력 표·진단서 및 중복 제거의 식별값을 `${source}:${license_no}`로 변경해 주세요.
- 두 원천의 같은 관리번호를 하나로 합치지 않습니다.
- 최초 브라우저 재현은 이력 표였으며, 도메인 등록 후 실제 지도 SDK에서도 아래 합성 경계를 확인했습니다. nearby/snapshot 등 다른 목록도 같은 식별 원칙을 적용해 주세요.

### 지도에서 확인한 영향

BE `ApiResponse[NearbyStores]` 검증을 통과한 합성2행(source 다름·license_no 같음)을 실제 지도 SDK에 전달했습니다. 마커 DOM은2개지만 내부 선택 관리 대상은1개였고, 두 번째 표 행을 누르면 두 행이 함께 선택되고 첫 번째 점포 정보창이 표시됐습니다. 이는 실제 자료에서 중복을 발견했다는 뜻이 아니라 허용된 원천 간 식별 경계를 재현한 결과입니다.

- `src/components/map/NearbyMap.tsx`: overlaysRef의 Map 키, 마커 클릭 콜백, 선택 강조 및 정보창 점포 find에 복합 식별자를 함께 사용해 주세요.
- `src/components/analysis/NearbySection.tsx`: selectedId와 표/지도 간 콜백이 같은 식별 규칙을 사용하도록 변경해 주세요.
- `src/components/analysis/nearby/NearbyTable.tsx`: React key뿐 아니라 선택 비교·행/버튼 클릭 인자도 변경해 주세요.
- `src/types/stores.ts`의 NearbyMarker에도 BE 필수 필드인 `source`를 추가해 주세요. 이력·주변·시점 목록에 같은 복합 식별 규칙을 사용하고, 공통 식별 함수의 구체적 구성은 FE 담당자가 결정해 주세요.
- 두 번째 점포를 누르면 그 점포만 선택되고 그 점포 정보가 나오는지, 반경·필터 변경/재마운트 뒤 이전 마커가 남지 않는지도 확인해 주세요. key 속성만 바꾸는 것으로 완료 처리하지 않습니다.
- 수정 후에는 서로 다른 좌표의 합성2행으로 첫째/둘째 표 행과 각 마커를 각각 선택해 정보창 상호·위치·강조가 해당 점포와 일치하는지 확인해 주세요. 변경·언마운트 뒤 마커 정리도 회귀 기준입니다. 고아 마커의 실제 잔존은 아직 브라우저에서 확정하지 않았습니다.

## 5. nullable 상호·기간이 빈칸으로 표시됨 — P2

**BE 스키마 검증을 통과한 합성 응답으로 재현했습니다.** open_date는 유효하지만 name=null·operating_months=null인 폐업 기록을 주면 표의 상호와 기간 셀이 빈칸이 됩니다. format 함수의 null 반환만으로는 정보 없음/미산정 사유가 표시되지 않습니다.

- 상호·날짜·기간 결측은 `정보 없음`으로 표시하고 기간은 operating_period_reason을 함께 보여 주세요.
- 폐업일이null인 폐업 기록의 상태를 유지하고 아래의사유별문구를구분해 주세요. null만으로 원본 폐업일이 없었다고 단정하지 않습니다.
- `missing_close_date`는 폐업일 정보 없음, `invalid_close_date`는 폐업일 확인 필요, `invalid_date_order`는 개업일·폐업일 확인 필요로 구분해 주세요. null만 보고 원자료가 없었다고 확정하지 않습니다.
- operating_months=0/fact는0개월, null/no_data는 미산정으로 구분합니다.
- 표와 출력용 진단서에 같은 기준을 적용해 주세요.
- 주변 표·지도 정보창에도 기존 [주변 API 요청서](fe-nearby-api-request.md)의 nullable 상호·기간/사유 계약을 적용해 주세요. 지도 title/버튼 안내에 문자열 `null`이 나오거나 정보창 제목이 빈칸이 되지 않도록 검증해 주세요. 이 주변 결측 항목은 이번 Claude 소스 대조의 보완 요청이며 별도 브라우저 재현을 완료한 것으로 표시하지 않습니다.

3~5번의 상세 필드/문구/합성 예시는 [이력 요청서](fe-store-history-api-request.md)를 따릅니다.

## 6. 지도 검증 선행 설정

최초 검사 시 FE의 `VITE_KAKAO_JS_KEY`가 설정되지 않아 지도 SDK·마커/정보창·표 선택 연동 검증을 중단하고 사용자에게 로컬 설정을 요청했습니다. BE의 KAKAO_REST_API_KEY와 다른 JavaScript 키입니다. 키/카카오 지도 사용 설정·허용 웹 도메인이 준비된 뒤 검증해야 하며, 표/API 성공으로 지도 성공을 대신하지 않습니다.

재점검에서는 JavaScript 키가 BE 로컬 환경 파일에 있음을 확인하고 테스트용 Vite 자식 프로세스에만 전달했습니다. FE 환경 파일은 바꾸지 않았습니다. Chrome SDK 로딩은 `KAKAO_SCRIPT_ERROR`·`net::ERR_BLOCKED_BY_ORB`, SDK 직접 HTTPS 응답은401·도메인 제한이었습니다. 해당 키의 JavaScript SDK 도메인에 `http://localhost:5173` 등록을 요청하고 실제 지도 검증은 중단했습니다. 설정 경로는 [카카오 공식 지도 가이드](https://apis.map.kakao.com/web/guide/)를 따릅니다. 키 존재만으로 지도 연동 완료라고 표시하지 않습니다.

**도메인 등록 후 최신 결과:** 사용자의 등록 완료 답변 후 SDK200·지도 타일 응답45건200을 확인했습니다. 실제500m 마커152개·300m 마커44개가 API count와 같았고, 표→마커/해당 정보창·마커 DOM click 이벤트→표 선택·정보창 닫기/선택 해제가 동작했습니다. 반경은 실제 화면의300m 선택 후 조회 버튼으로 변경했습니다. 이번 실행의 BE GET13건200·SQL 오류0·pageerror0·실LLM0입니다. 테스트용 자식 프로세스의 키 전달이며 FE 환경 파일을 영구 설정하지 않았습니다. 모바일·확대/이동·모든 마우스 hit test는 이번 확인 범위 밖입니다.

지도 도메인 차단은 해소됐지만4번의 복합 식별 경계에서는 잘못된 점포 정보가 표시되므로 지도 전체 완료로 표시하지 않습니다.

나머지 화면 검사는 지도 SDK 성공을 전제로 하지 않았습니다. 설정 이후 후속 결과는 [전체 기능 감사 보고서](be-system-audit.md)의 지도 항목을 확인합니다. 이번 문서에 실제 키나 개인 주소는 기록하지 않습니다.

## 완료 기준

- [ ] 실제 주소 검색 결과로 이력 표·활동·Risk·지원기관 화면 연결
- [ ] AI query-only 본문으로200 및 검증된 해석 표시, 입력/공급자실패 시 지표 유지
- [ ] unverified를 상권 밖으로 표시하지 않음, 출력용 진단서도 동일
- [ ] nullable 날짜가 있어도 표/진단서가 깨지지 않고 미확인 날짜가 마지막
- [ ] 같은 license_no·다른 source 두 행 유지, React key 경고 없음
- [ ] null 상호/기간·폐업일 결측 사유와 실제0개월을 구분
- [x] 등록한 테스트 도메인에서 SDK·실제 타일·500m/300m 마커 건수 및 정상 표본 선택/정보창 확인
- [ ] 다른 source·같은 관리번호에서도 표/지도 단일 선택·정확한 정보창·변경 후 마커 정리 확인
- [ ] FE lint/build·관련 회귀 및 실제 BE 브라우저 연결 확인
- [ ] FE 타입/계약/결정문서/CLAUDE.md 반영 후 BE에 변경 내용 전달

BE API/응답 형식은 이번 감사에서 바꾸지 않았습니다. FE 담당자가 수정하고 검증 결과를 전달하기 전에는 위 항목을 완료로 표시하지 않습니다.

## BE 재점검과 FE 작업 순서

재점검 중 이력·주변·활동·Risk의 동시 조회가 약3초 뒤500으로 실패한 실행도 있었습니다. 이후 순차5건·동시10건은200이었으며 초기 실패의 SQLSTATE를 확보하지 못했습니다. FE만의 오류로 일괄 처리하지 않고 BE #78에서 별도로 추적합니다. 출처 쿼리의 임시 최적화안은 과거 배치 누적 시 회귀 위험 때문에 적용하지 않았습니다. 상세 근거는 [재점검 설계·Claude 검토·최종 판단](designs/feat78-audit-recheck.md)에 남겼습니다.

도메인 등록 후의 별도 출력 재검사에서도4개 API500이 재발했고, 같은 시각 PostgreSQL ERROR와 동일 backend PID의 STATEMENT를 대조해 **출처 연결 배치 조회4건의 statement timeout**을 확인했습니다. SQL/파라미터 원문은 보고서에 남기지 않았습니다. 이번 실패의 직접 원인은 DB 쿼리 제한시간 초과로 좁혔지만, 과거 모든500이 같은 원인이라는 뜻은 아닙니다. 근본 성능 개선은 미적용이며 BE 후속으로 유지합니다. 그 실행의 PNG 생성은 계속 미확인이고 진단서main·인쇄 이벤트·메모리 PDF1페이지는 확인했습니다.

**#82 후속 결과:** 출처 조회 인덱스와 migration0010을 적용한 현재 데이터에서 실제동시15건200·SQL오류0과 전후응답일치를 확인했습니다. 출력PNG생성·인쇄이벤트·메모리PDF1페이지도통과했습니다. 대량재적재직후에는수동VACUUM·조회확인전까지500위험이남으며 전체운영SLA를보장하지않습니다. API/FE계약변경은없으므로 본문의FE5종수정방향은유지합니다.

FE 작업 순서는 ① HistoryStore 타입·공통 정렬/결측 표시·복합 식별자로 이력/진단서 복구 ② unverified 분기·Risk 타입 ③ 원래 query-only AI 본문·include 일치·오류 처리 ④ 지도/표의 복합 식별자 수정 및 변경 후 정리 검증 ⑤ 실제 검색부터 진단서까지 연결 검증입니다. 수정 완료 전에는 수정 항목의 체크리스트를 체크하지 않습니다. 기본 지도 통과와 복합 식별 미완료를 구분합니다. 이번 재점검에서 실제 LLM은 추가 호출하지 않았습니다.

## 부록. Claude Code 재검토 근거와 한계 (#78)

### 검토 방법과 한계

- BE 소스만 Read로 대조했습니다: `app/routers/interpret.py`, `app/schemas/interpret.py`, `app/schemas/risk.py`, `app/schemas/nearby.py`, `app/schemas/store_filters.py`, `app/schemas/stores.py`, `app/services/store_history.py`, `app/services/spatial_stores.py`, `app/services/store_cohort.py`, `app/models/store.py`.
- **FE 소스(`SpotON-FE/src/...`)는 이번 도구 권한이 BE 작업 폴더로 제한되어 읽지 못했습니다.** 1~5번의 FE 현재 동작(응답 query 전송, outside 분기, `localeCompare`, license_no 단독 key, 빈칸 표시)은 Codex의 브라우저 재현과 기술 내용을 근거로 하며, Claude Code가 FE 코드에서 직접 확인한 것은 아닙니다.
- 브라우저·DB·네트워크는 사용하지 않았습니다. 아래 판단은 BE 계약 측면의 타당성입니다.

### 요청별 판단

| # | 판단 | BE 근거와 보완 |
|---|---|---|
| 1 query-only | 타당 | `InterpretRequest`는 `query: RiskQuery` 하나만 받고 `extra="forbid"`입니다. 응답 echo(`RiskQueryEcho`)의 `radius_m`·date형 `as_of`·`filters`는 입력 모델에 없으므로 그대로 보내면 422입니다. |
| 2 unverified | 타당, 영향은 요청서보다 큼 | 현재 `RiskMarket.status`는 `Literal["unverified"]` 하나뿐이고 market_code/name/type은 항상 null입니다. 따라서 in_market이 아니면 outside로 처리하는 분기라면 **모든 Risk 응답**이 상권 밖으로 표시됩니다. `spatial_candidate`는 nullable이며 null이면 reason=`boundary_version_not_selected`입니다. |
| 3 open_date null | 타당 | `HistoryStore.open_date`는 `date \| None`입니다. 원본 null뿐 아니라 1960년 이전·미래·기준일 이후 개업일도 `operating_period`에서 null로 바뀌므로 실제 데이터에서도 발생할 수 있습니다. BE 정렬은 (null 마지막, 날짜, source, license_no)라 FE의 최근순+미확인 마지막+source·license_no 동률 고정과 일관됩니다. |
| 4 복합 key | 타당 | DB에 `UNIQUE(source, license_no)`가 있어 `${source}:${license_no}`는 한 응답 안에서 유일합니다. source는 콜론이 없는 고정 값이라 구분자 충돌도 없습니다. nearby 마커도 source를 반환하므로 같은 원칙이 맞습니다. |
| 5 nullable 상호·기간 | 타당, 문구 보완 필요 | 스키마가 `operating_months=null ⇔ no_data+reason`, `값 ⇔ fact+reason null`을 강제하므로 0개월과 미산정을 구분할 수 있습니다. |

### 입력 형식 보완 (1번)

- 원래 Risk GET 조건을 그대로 옮깁니다: `lat`/`lng`(JSON number), `category`, `radius`(300·500·1000), 선택 `sub_category`·`area`·`franchise`·`include`(market_change/day_night_ratio)·unknown 플래그.
- `as_of`는 원래 요청에 있을 때만 `YYYY-MM`으로 보냅니다. 생략(또는 null)은 최신 기준이므로, 최신 조회에 오늘 월을 임의로 넣지 않습니다.
- `include_unknown`과 `include_unknown_area`/`include_unknown_franchise`를 함께 보내면 422입니다. 한쪽 형식만 사용합니다.
- 내부 RiskQuery는 문자열 radius·boolean을 일부 허용하지만 이를 전제로 하지 말고 숫자·불리언 JSON 타입으로 보냅니다.

### 결측 표시 보완 (5번)

- `store_status=closed`이고 `close_date=null`이어도 원인이 항상 "정보 없음"은 아닙니다. `operating_period_reason`이 `missing_close_date`(원본 없음), `invalid_close_date`(원본 있으나 무효), `invalid_date_order`(개폐업 순서 오류로 BE가 폐업일을 비움)일 수 있습니다. `폐업일 정보 없음`은 `missing_close_date`에만 쓰고, 나머지는 사유 문구로 표시해 주세요.
- 개업일 null도 `missing_open_date`/`invalid_open_date`를 구분합니다.

### 범위 밖 확인

- nearby `NearbyMarker.open_date`는 non-null이므로 nearby에는 open_date null 정렬 수정이 필요하지 않습니다. 다만 `close_date`·`operating_months`·`name`·`area_m2`는 nullable입니다.
- 이번 재검토에서 BE 계약 변경이 필요한 항목은 찾지 못했습니다.

## 부록 2. FE 소스 2차 대조 결과 (#78)

위 부록의 "FE 소스를 읽지 못했다"는 1차 한계 기록은 그대로 유지합니다. 2차에서는 FE 읽기 경로가 추가되어 아래 파일을 **Read로만** 확인했고, FE는 수정하지 않았습니다. 브라우저·DB·네트워크는 사용하지 않았으므로 실행 결과가 아닌 정적 소스 대조입니다.

- 읽은 FE 파일: `src/components/summary/ai/AiInterpretation.tsx`, `src/components/summary/MarketCard.tsx`, `src/components/analysis/history/HistoryTable.tsx`, `src/pages/ReportPage.tsx`, `src/types/risk.ts`, `src/types/stores.ts`, `src/api/params.ts`, `src/utils/format.ts`
- 함께 대조한 BE 파일: `app/schemas/interpret.py`, `app/schemas/risk.py`
- 읽지 않은 파일: `src/types/api.ts`(CommonQueryParams), `src/hooks/useRisk*`, `app/schemas/nearby.py` 등. 이에 의존하는 판단은 "미확인"으로 표시했습니다.

### 요청별 소스 대조

| # | 요청서 주장 | FE 소스 확인 | 판단 |
|---|---|---|---|
| 1 | 응답 query와 market/indicators/flags/context를 본문에 넣음 | `AiInterpretation.tsx:61-68`이 `risk.query`·market·indicators·flags와 캐시 기반 `context`를 보냄. `risk.ts:86-92,109-116`의 `RiskQuery`/`RiskInterpretRequest`도 `radius_m`·`as_of`·`filters` 응답형 | 일치 |
| 2 | in_market이 아니면 outside | `MarketCard.tsx:11,35-37`, `ReportPage.tsx:360-362` 모두 그렇게 분기. `risk.ts:9`의 `MarketStatus`에 `unverified`가 없고 `reason`·`spatial_candidate` 필드도 없음 | 일치. BE는 항상 `unverified`라 현재 **모든** 응답이 상권 밖으로 표시됨(1차 부록 판단 확인) |
| 3 | `b.open_date.localeCompare` TypeError | `HistoryTable.tsx:36`, `ReportPage.tsx:181`에 그대로 있음. 둘 다 `[...stores]`로 복사 후 정렬하므로 캐시 변경 문제는 현재 없음 | 일치. `stores.ts:24-36` `HistoryStore`는 open_date·name·operating_months non-null, source·기간상태·사유 필드 없음 |
| 4 | license_no 단독 key | `HistoryTable.tsx:59`, `ReportPage.tsx:212` 모두 `key={s.license_no}`. `stores.ts`의 History/Nearby/Snapshot 타입에 `source` 필드가 없음 | 일치. 요청서의 "중복 제거" 코드는 읽은 파일에서 찾지 못함(다른 파일 여부 미확인) |
| 5 | null 상호·기간이 빈칸 | `formatOperatingMonths(null)`·`formatDate(null)`이 null 반환(`format.ts:11-27`) → 표/진단서 셀이 빈칸. `s.name`도 그대로 출력 | 일치. 추가로 close_date null은 표에서 `—`+sr-only `noCloseDate`, 진단서에서 `—`라서 영업 중과 폐업일 결측이 구분되지 않음 |

### 틀린 주장·누락

- 1~5번에서 FE 소스와 **틀린 주장은 찾지 못했습니다.**
- 누락①(1번 예시): 요청서 예시는 `include_unknown_area`/`include_unknown_franchise`를 쓰지만 현재 FE `params.ts:26`은 단일 `include_unknown`만 만듭니다. 1차 부록 기준 BE는 한쪽 형식만 쓰면 수용하므로 `params`를 그대로 옮기는 것이 가장 작은 변경입니다. 두 형식을 섞어 보내지 않도록 명시가 필요합니다.
- 누락②(1번 include): `RiskQuery`는 `include`(market_change/day_night_ratio)를 받고, `Risk.complete_result`는 지표 목록이 include에 따라 달라집니다. `params.ts`의 공통 파라미터에는 Risk용 `include`가 없습니다. Risk GET이 include를 붙인다면 AI 본문에도 같은 값을 넣어야 지표 화면과 AI 재계산 조건이 일치합니다(Risk GET 훅은 읽지 않아 미확인).
- 누락③(1번 형식): `params.sub_category`는 배열, `as_of`는 `query.asOf`가 있을 때만 들어갑니다(`params.ts:28-31`) — 생략=최신 규칙과 일치. 다만 배열 sub_category와 `area`/`franchise`의 JSON 값 형식을 BE `NearbyQuery`(strict)가 받는지는 이번에 `nearby.py`를 읽지 않아 미확인이며, FE 수정 후 실제 200 확인이 필요합니다. `undefined` 값은 JSON 직렬화에서 빠지지만 `null`을 넣지는 않도록 해야 합니다.
- 누락④(1번 실패 처리): `onError`가 `INVALID_PARAM`이면 `onReloadIndicators()`를 호출합니다(`AiInterpretation.tsx:74-78`). AI 자동 재호출은 아니지만, query-only 전환 후 422는 "지표 값 불일치"가 아니라 입력 형식 오류이므로 지표 재조회 트리거가 의미에 맞지 않습니다. 재시도는 사용자 버튼으로만 두는 것을 권장합니다.
- 누락⑤(타입): `risk.ts:50` `MetricIndicator.source`는 `string`이지만 BE `RiskIndicator.source`는 `list[str]`입니다. 이번 요청 범위 밖이나 타입 반영 시 함께 맞추기를 권장합니다. `verification.passed !== false` 판정은 BE `Literal[True]`와 충돌하지 않습니다.

### 결론

FE 소스 2차 대조로 1~5번 요청의 근거가 모두 실제 코드에서 확인됐습니다. query-only 본문은 기존 `params`(단일 `include_unknown`)를 그대로 쓰면 되고, Risk GET과 같은 `include`를 포함해야 합니다. 이 결론은 정적 대조이며, 200 응답과 화면 표시는 FE 수정 후 실제 연결로 확인해야 합니다.
