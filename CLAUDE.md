# SpotON-BE 작업 기준

BE의 범위·계획·API·ETL·개발 규칙은 다음 통합 문서 하나에서 관리한다. 작업 전에 읽고 필요한 기준 변경도 통합 문서에 반영한다.

@docs/be-work-plan.md

[BE 개발 기준 및 작업계획](docs/be-work-plan.md)

## 점포 이력 API 계약 (BE #36)

`GET /api/stores/history`는 building_key로 지원 업종 전체 이력을 조회한다. category는 선택 진단 맥락이며 필터가 아니다. 각 항목에 source를 반환하고 식별자는 source+license_no다. name/open_date/close_date/operating_months는 null을 허용한다. 기간은 달력상 완료 개월 수, `operating_period_status=fact|no_data`, `operating_period_reason=사유 코드|null`이며 미산정을 0으로 만들지 않는다. 영업 중 종료점은 검증된 DAT_UPDT_PNT 최대 날짜, 폐업 종료점은 확인된 폐업일이다. 층만 같으면 same_spot이 아니다. 일반 입력 오류는 현행 422 INVALID_PARAM, 공통 외피와 오류 meta={}는 유지한다. 상세 설계는 docs/designs/feat36-store-history-api.md를 따른다.

2026-11-12 사용자 지시에 따라 FE 저장소를 직접 수정하거나 FE 이슈·PR을 생성하지 않는다. FE 타입·화면·CLAUDE.md 동기화는 [FE 수정 요청 보고서](docs/fe-store-history-api-request.md)로 전달하고 담당자 반영을 기다린다. 현재 FE 연동은 미완료다.
