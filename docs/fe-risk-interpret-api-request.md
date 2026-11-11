# AI 해석 API 연동을 위한 FE 변경 요청 보고서

- 작성일: 2026-11-12
- 관련 작업: BE-32 핵심 / F-08, [BE #68](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/68)
- 상태: **BE 구현·검증 / FE 계약 검토·반영 대기**

## 1. 요청 본문을 query-only로 변경

`POST /api/risk/interpret`를 실제 연결해 주세요. 기존 FE `RiskInterpretRequest`의 market/indicators/flags/context를 전송하지 않습니다. 서버가 Risk를 다시 계산하므로 FE에서 받은 수치나 화면에 남아 있는 오래된 응답을 신뢰하지 않습니다.

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

위 좌표는 형식 설명용입니다. 실제로는 주소 검색 결과로 Risk를 요청할 때 사용한 원본 조회조건을 사용합니다. Risk **응답**의 query를 그대로 전송하면 radius_m/일 단위 as_of 때문에422가 될 수 있습니다. 입력은 radius와 YYYY-MM이며, sub_category는 허용 코드 배열 또는 쉼표 문자열입니다. include는 market_change/day_night_ratio만 허용합니다.

첫 버전은 building_key/floor_unit을 지원하지 않으며 전송하면422입니다. 원본의 선택 이력 문맥은 후속입니다. 이 필드를 받았다가 무시하지 않습니다. 사용자 주소·상호·프롬프트·숫자·상권 후보·경계 UUID도 보내지 않습니다. POST URL의 쿼리 인자, 중복 JSON 키·NaN·추가 필드·16KiB 초과 본문도 거절합니다.

## 2. 이번 AI의 역할과 응답 의미

모델이 자유롭게 설명 문장을 만드는 방식은 아닙니다. 서버가 검증된 집계에서 사실·비교·현장 확인 후보를 작성하고, 모델은 유리/불리 비교를 **빠짐없이 정렬**하며 체크리스트를 선택합니다. 최종 숫자·문장·지표 ID·출처·상태는 서버가 조립합니다.

label은 기존 계약의 `AI 해석`을 유지하고 method=`server_sentences_model_ordering`을 추가했습니다. 화면 도움말에는 **“AI가 서버에서 검증한 설명의 순서와 현장 확인 항목을 정리합니다.”**처럼 역할을 밝혀 주세요. 새 사실을 조사하거나 성공/실패를 예측하는 기능으로 표현하지 않습니다. 이 제한된 해석 방식은 BE 계약안이며 FE/원본 합의가 이미 끝났다는 뜻이 아닙니다.

| 필드 | 표시 기준 |
|---|---|
| official_values | 서버의 확인된 계산값을 모두 반환. 참고지표도 있으므로 전체를 공식 통계로 제목 붙이지 않음 |
| favorable / unfavorable | 같은 필터의 서울 비교가 가능한 비율만. 후보 누락 없이 서버 문장을 모델이 정렬 |
| missing_data | 모델 선택과 무관한 필수 미확인/소표본/자료 한계. 숨기거나 빈 상태를 수치0으로 채우지 않음 |
| checklist | 서버의 일반 현장 확인 후보 중 모델이 고른1~3개 |
| verification | 선택 형식/문장 안전성 검사 통과 표시. 사실 정확도·신뢰도 점수가 아님 |
| model / generated_at | 최종 채택 모델명·서버 UTC 생성시각 |

official_values의 각 항목은 text/indicator_ids, favorable/unfavorable은 text/indicator_ids/sources, missing_data는 text/reason, checklist는 item/why를 유지합니다. sources는 배열입니다. 이력·문구·원인·방향을 FE에서 다시 생성하지 않습니다.

정상 verification은 passed=true, mismatches=[], regenerated=검증 실패 후1회 재생성 여부입니다. checked_numbers는 보이는 문장의 숫자 출현 횟수이며 점수로 표시하지 않습니다.

## 3. 계산·미확인 상태 유지

Risk의 최근 기간 폐업률·고정 개업 주년 생존율과 같은 필터의 좌표 확보 서울 비교를 사용합니다. 생존율은 현재 잔존율이 아니며 현재 폐업했어도 주년 이후 폐업이면 해당 주년 생존에 포함됩니다. [Risk 요청서](fe-risk-reference-api-request.md)의 계산 보완안을 함께 검토해 주세요.

소표본/0분모·공식 지표/상권 적용/가맹 분류/수집일 미확인은 그대로 안내합니다. 서울 비교값이 같으면 유리/불리 후보를 만들지 않으며, 동종업체 수에 임의로 많음/적음 등급을 붙이지 않습니다. 유리/불리 구역이 비어도 설명을 임의로 채우지 않습니다.

반경 내 인허가·기간·지위승계·좌표 선택·현재 스냅샷으로 과거를 재구성한 한계를 유지합니다. 상권 후보나 지역명을 확정 사실로 추가하지 않습니다. 주소·좌표·점포 식별값은 모델에 전달하지 않습니다.

## 4. 호출·실패 처리

- 사용자가 AI 해석을 요청했을 때만 호출합니다. 기존 GET /risk 결과는 AI 실패와 무관하게 유지합니다.
- 서버 예산은 기본20초이며 DB 준비·생성·최대1회 검증 재생성을 포함합니다. FE의 기존20초 timeout과 경계가 같아 네트워크 여유가 없으므로, 서버 오류 표시를 받도록 FE transport timeout을 예컨대25초로 조정하는 방안을 검토해 주세요. 시간은 SLA 보장이 아닙니다.
- 입력 오류422 INVALID_PARAM은 본문을 수정해야 합니다. 서버 DB/준비/템플릿 오류500 INTERNAL_ERROR, 공급자·한도·전체예산 실패503 AI_UNAVAILABLE, 검증2회 실패503 AI_VERIFY_FAILED를 구분해 주세요.
- 서버가 이미1회 검증 재생성을 수행하므로 FE가 자동 재호출을 반복하지 않습니다. 명시적 사용자 재시도만 제공해 주세요.
- 앱 기본 한도는 유효 요청5회/분·50회/일·동시2개이며 프로세스별입니다. 서버 한도 실패도503 AI_UNAVAILABLE입니다. 공급자/다중 프로세스 전체 한도와 같다고 표시하지 않습니다.
- 모든 응답은 no-store이며 AI 응답 캐시는 아직 구현하지 않았습니다. 이전 조건의 AI 결과를 새 조건에 표시하지 않도록 진행 중 요청/응답을 구분해 주세요.

meta는 T/D/수집일null·반경·분모null·입력/데이터/프롬프트 hash·버전을 제공합니다. hash는 사용자 화면에 직접 표시할 필요가 없으며 수집일을 오늘/생성시각으로 대체하지 않습니다. 해석 결과에서 source 배열은 원래 지표와 연결해 표시합니다.

## 5. 수정 검토·완료 기준

검토 대상은 src/types/risk.ts, src/api/risk.ts, AI 호출 hook/해석 구역·ReportPage, mock·상태 문구·api-contract/decisions·FE CLAUDE.md입니다. FE 저장소 파일/이슈/PR은 담당자가 관리합니다. 기존 실제 API 경로 설정에 `/risk/interpret`를 추가할 수 있고 백엔드 키는 FE에 전달하지 않습니다.

- [ ] 원본 조회조건으로 query-only 본문 구성, Risk 응답/수치 전송 제거
- [ ] method 설명·공식/참고 구분·비어 있는 비교/미확인 항목·출처 배열 유지
- [ ] 표본/고정 주년 의미·숫자 검사 수를 정확도 점수로 표시하지 않음
- [ ] 과거/필터 변경 시 오래된 AI 결과 숨김·요청 취소/응답 순서 처리
- [ ] 422/500/503 두 오류·수동 재시도·GET /risk 화면 유지
- [ ] 자동 중복/재호출 방지·전송 timeout 여유 검토
- [ ] FE lint/build·실제 BE 연결·계약/CLAUDE.md 반영 후 결과 전달
