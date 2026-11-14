# 브랜드·체인 v2 API 연결 요청 (#145)

BE 전용 구현이다. FE 코드/설정/문서는 수정하지 않았다. 운영 Render는 기존 head0011/v1 배포를 유지하므로 운영 URL에서 아래 기능을 사용할 수 있다는 뜻이 아니다. 새 BE 배포 전에 관리 역할로 migration0012와 조회 역할 SELECT 권한, 판정 publication을 준비해야 한다.

가맹·직영·소규모 체인 모두 브랜드 소속 추정에 포함한다. 실제 가맹/직영 계약·비체인·과거 브랜드 소속은 미확인이다. 미일치 점포를 독립 점포라고 표시하면 안 된다. 전체 브랜드/지점 포함이나 판별 정확도를 보장하지 않는다.

## 호출

`GET /api/v2/brands/status`는 publication 준비 상태와 출처·기능 지원을 반환한다.

공간 조회는 `GET /api/v2/stores/nearby`, `/api/v2/stores/snapshot`, `/api/v2/market/activity`, `/api/v2/risk`다. 기존 lat/lng/category/sub_category/radius/as_of/area/include_unknown_area 검증을 유지한다. snapshot은 as_of가 필수다. activity.include=sales,living_pop, risk.include=market_change,day_night_ratio의 기존 pending 의미도 유지한다.

예: `/api/v2/stores/nearby?lat=37.5665&lng=126.978&category=cafe&radius=500&brand_scope=chain&brand_unknown=exclude&brand_evidence=include_estimates`

| 인자 | 지원 값·기본값 |
|---|---|
| brand_scope | all(기본), chain, non_chain |
| brand_unknown | include(전체 기본), exclude. scope가 all이 아니면 명시 필수 |
| brand_evidence | include_estimates(기본), confirmed_only |
| brand_time_basis | observed_record만 지원 |
| operation_type | any만 지원 |

체인 추정만 보려면 chain/exclude/include_estimates를 함께 전송한다. non_chain/exclude는 현재 확인된 비체인 근거가 없어 0건이다. non_chain/include는 미확인·충돌을 포함하며 ‘독립 점포’ 확정 목록이 아니다. confirmed_only/exclude도 현재 0건이고, confirmed_only/include는 추정 결과까지 필터상 미확인으로 포함한다. 행의 원래 estimated 표시는 유지한다.

v2는 franchise/include_unknown_franchise/include_unknown를 거절한다. v1은 새 brand_* 인자를 거절한다. 중복 인자·미지원 운영 형태/역사 소속 인자·scope별 unknown 생략은 DB 연결 전422다. 모든 성공·오류 응답은 기존 공통 포맷과 no-store를 따른다.

## 표시·분모

v2 점포 행에는 source+license_no, 기존 허용 필드, `brand`와 `operation`이 있다. legacy franchise 세 필드는 없다. brand.status는 estimated/unknown/conflict, brand_key/name/basis/reason/reference_year/reference_month가 nullable이다. brand.time_basis=observed_record, historical_membership=not_verified, operation.type=unknown이다. 원천 변경 시 stale_input 또는 source_drift가 사유가 된다.

meta.brand_classification은 pending/estimate 상태, generation, published_at, 출처 기준과 capabilities를 제공한다. pending의 엄격 체인 0건을 실제 체인 부재로 안내하지 않는다. source_drift는 저장 후 점포 원천 DML이 발생했음을 뜻하며 주소 대조 근거는 재검증 전 unknown으로 내린다. 이름 근거는 해당 점포의 당시 입력이 같을 때 유지한다.

meta.brand_counts의 estimated/conflict/stale_or_drift/unknown 합은 **브랜드 필터 전 동일 업종·면적·시점·반경에서 영업한 좌표 보유 인허가 기록** 수다. 필터 후 count/cohort_size와 다르다. 좌표 미확보 수는 기존 서울 비공간 코호트이며 이 분모에 더하지 않는다. status의 publication_counts는 폐업/분석 이름 제외를 포함한 저장 원천 기록이므로 현재 영업 점포 수가 아니다.

`GET /api/v2/stores/history`는 building_key/floor_unit/category만 받는다. 브랜드 필터 없이 지원 업종의 전체 이력을 보존하며 행별 소속 추정만 추가한다. history counts는 실제 반환 이력이 분모다. `/api/meta/data-range`는 기존 업종 기반 계약을 사용한다.

여러 요청의 generation이 다르면 같은 조회로 다시 요청한다. generation은 점포 원천 시점을 고정하는 토큰이 아니다. 과거 월 통계도 현재 관측한 브랜드 정보를 적용한 참고 집계로 표시한다.

## AI와 전환

v2 Risk/활동에 브랜드 필터를 적용한 결과를 기존 `/api/risk/interpret`로 보내지 않는다. 현재 v1 AI는 새 조건을 지원하지 않으며 `/api/v2/risk/interpret`는 제공하지 않는다. 브랜드 필터를 포함하는 AI 문맥·재계산 검증·프롬프트·캐시 연결이 별도 후속이다. v2 Risk는 v1 캐시와 섞이지 않도록 현재 캐시를 사용하지 않는다.

먼저 status와 수동 조회로 계약을 대조하고 v2 목록·동일 조건의 분석을 함께 전환한다. 기존 FE 화면을 수정하거나 배포한 상태로 표시하지 않는다.
