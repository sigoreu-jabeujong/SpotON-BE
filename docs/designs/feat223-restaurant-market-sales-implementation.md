# 음식점 선택 업종의 상권 합산 구현 (#223)

## 범위와 최신 사용자 승인
2026-11-17 #221 설계와 실제 Claude 3차 PASS 이후 사용자가 후속 진행을 요청했다. 이번에는 구현·검증·정상 PR/공개 반영을 진행한다. 설계 전용 단계의 제한은 당시 작업 범위이며 현재 구현 요청을 제한하지 않는다.
기준 설계: [음식점 상권 합산](feat221-restaurant-market-sales-aggregation.md). 최신 FE #118의 화면 정리와 별도 LocationReferencePrint 구성을 보존하면서 음식점만 공유 RestaurantSales를 연결한다.

## 최종 구현
기존 top3의 상권 합산·점포 수 정렬을 ranked_market_totals로 분리해 신규 market_aggregation과 공유한다. IndustrySelection은 source_order/canonical_order를 분리하여 기존 원자료 및 legacy contributions 순서를 보존한다. 서비스가 조기 반환 전 업종을 확정하고 음식점에는 빈 자료도 객체, 카페에는 null을 생성한다.
신규 DTO는 strict/frozen 구조이며 원자료 교차곱, 요청 업종, 상태·이유, 포함/제외, 분기, 합계, 선정 순위, eligible 수와 top3 항목별 금액·업종을 재계산 검증한다. JSON 배열은 JSON-mode 검증으로 immutable tuple 모델에 읽는다. DB/원자료/환경/기존 AI·생활인구 계약은 변경하지 않는다.
FE 음식점 화면/보고서는 같은 RestaurantSales로 대표 pooled 값과 실제 출처·선택 업종을 표시한다. 기본 카드 3곳, 나머지 상권 및 업종 원자료는 접힌 영역이다. 부분합은 대표값과 개별 카드에 공개하며 없으면 0원을 만들지 않는다. 큰 정수는 BigInt로 표시하고 점포당 금액은 서버 display를 사용한다. 카페는 최신 기존 화면/인쇄 구성을 유지한다.
목업은 실제 서버가 아닌 합성 fixture 18종(음식점 선택 집합 15종과 partial/no_data/cafe)으로 신규 핸들러를 등록한다. fixture는 BE에서 검증한 합성 자료이며 운영 빌드에서는 제거된다.

## 검증 기록
- BE 산식/선택/순위/결측/위조 17개 및 기존 일반 2706개 통과(Windows 권한 전용 skip 3).
- 격리 PostGIS 4상권×4업종에서 전체/부분 선택을 직접 DB 값과 대조, 순위 변경과 분자/분모 일치 통과.
- FE 화면/인쇄 합산 카드·partial/no_data/호환/카페 회귀 포함 테스트 및 type/build 검증 수행. 목업 추가 후 최종 검사 결과는 PR에 기록한다.
- 전체 통합 CI, 실제 복원본 읽기 전용 대조, 모바일·브라우저·인쇄 및 공개 검증은 아래 실행 기록과 PR 결과로 구분한다. 미실행을 통과로 주장하지 않는다.

## Claude Code 실제 검토
2026-11-17 02:24 KST 실제 CLI 실행은 5시간 사용 한도로 실패했다(exit=1, is_error=true). 안내된 해제 시각은 03:10 KST다. 설계 #221의 Claude 3차 PASS와 이번 구현 재검토 미실행을 구분한다. 코드에 대한 Claude PASS를 주장하지 않는다.

## Codex 최종 검토
Codex가 원자료 순서 보존, 동일 분기·선택 업종 교차곱, strict 숫자·사유 타입, 포함/제외 완전성, 대표값과 상권별 합계의 일치, 빈 자료·부분합 표시, Cafe 경로와 별도 Print 보존, BigInt 표시 및 목업 운영 제외를 재검토했다. 추가로 실제 0원/양수 점포와 int64 초과 합계 테스트를 보강했고 신규 단위 검증은 19개 통과했다. BE 타입/정적 검사 및 FE 251개 검증·build/lint가 통과했다. 실제 복원본 5곳×전체/두 업종/단일 업종=15회 조회가 원자료 독립 합계·순위·정확 비율과 일치했다. 공개 반영 전 필수 CI와 브라우저 검증은 별도로 확인한다.

## 사용자 최신 검토 절차와 Codex 독립 재검토
사용자가 앞으로 Claude Code의 역할을 Codex가 수행하도록 지시했다. 이에 따라 이 구현의 검토는 Codex가 맡고, Claude 사용 한도 해제를 기다리거나 구현의 선행 조건으로 삼지 않는다. 이전 설계의 실제 Claude 검토 기록은 역사적 사실로 보존한다.
Codex 2차 점검에서 개발 목업이 legacy per_store_average를 제거하면 신규 DTO의 재계산 전제와 어긋날 수 있음을 발견했다. 해당 필드를 보존한 전체 응답으로 목업을 다시 생성하고 LocationReference의 JSON 검증까지 수행하도록 보완했다. 실제 0원·양수 점포와 단일 원자료 int64를 초과하는 합계를 추가 검증했다. 화면·인쇄 공유 컴포넌트의 actual/partial/no_data/print 4경우를 360/390px와 PDF로 검증했으며 JS 오류 0건이었다.
