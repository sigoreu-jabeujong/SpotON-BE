# SpotON-BE 작업 기준

BE의 범위·계획·API·ETL·개발 규칙은 다음 통합 문서 하나에서 관리한다. 작업 전에 읽고 필요한 기준 변경도 통합 문서에 반영한다.

@docs/be-work-plan.md

[BE 개발 기준 및 작업계획](docs/be-work-plan.md)

## 점포 이력 API 계약 (BE #36)

`GET /api/stores/history`는 building_key로 지원 업종 전체 이력을 조회한다. category는 선택 진단 맥락이며 필터가 아니다. 각 항목에 source를 반환하고 식별자는 source+license_no다. name/open_date/close_date/operating_months는 null을 허용한다. 기간은 달력상 완료 개월 수, `operating_period_status=fact|no_data`, `operating_period_reason=사유 코드|null`이며 미산정을 0으로 만들지 않는다. 영업 중 종료점은 검증된 DAT_UPDT_PNT 최대 날짜, 폐업 종료점은 확인된 폐업일이다. 층만 같으면 same_spot이 아니다. 일반 입력 오류는 현행 422 INVALID_PARAM, 공통 외피와 오류 meta={}는 유지한다. 상세 설계는 docs/designs/feat36-store-history-api.md를 따른다.

2026-11-12 사용자 지시에 따라 FE 저장소를 직접 수정하거나 FE 이슈·PR을 생성하지 않는다. FE 타입·화면·CLAUDE.md 동기화는 [FE 수정 요청 보고서](docs/fe-store-history-api-request.md)로 전달하고 담당자 반영을 기다린다. 현재 FE 연동은 미완료다.

## 주변 점포 API 계약 (BE #41)

`GET /api/stores/nearby`는 lat/lng/category 필수, radius=300/500/1000m(기본 500)다. category/sub_category는 실제 업종 필터이며 날짜가 유효한 점포를 선택 월말(최신 월은 전역 원천 갱신일) 기준으로 조회한다. 후보는 geography 거리 반경+0.01m, 최종은 반올림 전 ST_Distance<=반경이며 출력만 소수 첫째 자리로 표시한다. `source+license_no`로 식별하고 최신 상태·전체 운영기간을 반환한다. 0㎡는 원본 보존·응답 null·면적 unknown이며 면적/가맹 unknown 토글은 독립적이다. legacy include_unknown은 단독 사용만 허용한다. 좌표 미확보 수는 서울 전체의 같은 비공간 조건이며 meta.excluded_no_coord_scope=seoul_nonspatial_cohort로 명시한다. 이력 API의 결측 이력 보존은 변경하지 않는다. 상세는 docs/designs/feat41-nearby-api.md, FE 변경은 docs/fe-nearby-api-request.md를 따른다.

2026-11-12 사용자 지시에 따라 BE PR은 로컬 검사·CI 및 저장소 조건 확인 후 develop에 자동 Squash 병합한다. GitHub 본인 승인 제한·보호 규칙을 우회하지 않으며 main 반영·수동 브랜치 삭제·강제 푸시는 별도 요청 범위다.
