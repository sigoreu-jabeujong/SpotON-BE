# 위치 참고 API 1차 연동 계약 (#188)

검토된 [위치 참고 설계](designs/feat186-location-reference-display.md)와 [실제 구현/검증](designs/feat188-location-reference-implementation.md)을 따른다. 새코드의 API이며 실제 운영 반영 여부는 구현 기록을 확인한다. 이번 BE 작업에서 FE 저장소/화면을 변경하지 않는다.

`GET /api/v2/location-reference?lat=...&lng=...&radius=1000&category=cafe&as_of=2023-11&time_mode=latest_reference`

- 입력은 lat/lng/radius/category/sub_category/as_of/time_mode만 받는다. 브랜드·면적 필터는 전달하지 않는다. 원자료에는 이필터를 적용할 수 없다.
- time_mode 기본은latest_reference다. source_quarter가20254이면2025년4분기 **원자료 금액**이다. 월매출/분기총매출로 이름을 바꾸거나3으로 나누지 않는다.
- `data.analysis_as_of`와 각행의`source_quarter/temporal_relation/period_end_after_analysis`를 분리해 표시한다. 기존인허가/AI의분석기준일을 바꾸지 않는다.
- `data.sales.items`의 각행에 상권명·spatial_relation(contains_point/intersects_radius)·업종·자료분기와`metric.display`를 표시한다. 여러상권은합산하지 않는다. source별지정한공개도형의공간관계이며역사적경계공식승인이아니다.
- `metric.value`는정확한십진정수문자열이다. JavaScript Number로바꾸거나기존`formatKrwApprox(number)`에넣지않는다. 실제0은value="0"/exact_zero=true이며null/행부재와다르다.
- 상권은후보인데해당업종값이없으면행의status=no_data/metric=null이다. 블록partial이면유효숫자행을그대로표시하고결측행은그사유를표시한다.
- `source_value_null`은원자료행은있지만금액칸이비어있는경우, `no_source_rows`는행부재, `mapping_conflict`는코드/유형/명칭충돌이다. 블록의`reason_counts`는수치없는행의사유별건수이며혼합결측은`mixed_unavailable_reasons`다. `excluded_counts`는충돌행이제외된상권·업종쌍수이고각행의`excluded_source_rows`는실제제외원천행수다.
- `meta.items_additive=false`이므로값을합산하지않는다. 이계수/금액행의범위는선택된후보상권·업종쌍이며전국/전체원천품질계수와섞지않는다.
- 블록partial은일부item에금액이없거나, 모든item에값이있어도어떤분기의충돌원천행이제외된경우다. 값이있는item을숨기지말고제외진단을별도표시한다.
- `provenance_ref`는`meta.source_refs[].id`에연결한다. 원자료금액의집계기간뜻과과거경계의대응은unverified상태를표시한다.
- 이번의living_population/day_night는pending/population_source_not_released/items=[]다. 없는행정동테이블을조회하지않는다. 기존격자부분자료를이값으로교체하거나전체생활인구로포장하지않는다.
- 새route가없는구BE의기본404만이전상태카드로호환한다. 새BE의500/503/유효결측은404호환으로숨기지않는다.
- 기존AI문맥에최신참고매출값을전달하지않으며기존AI날짜검증도완화하지않는다. 새참고값은AI집계대상밖임을표시한다.

새source_year를지원하려면BEcatalog/연도선택계약을먼저확장한다. 첫릴리스는검수된2025년판1개이며2023년analysis_period의no_data는정상이다. 2023점포분석에서도latest_reference는실제2025년금액을그날짜와함께제공한다.
