# 주소 상세정보 보존·동일 주소 범위/층 이력 매칭 설계

- 작성일: 2026-11-16 (Asia/Seoul)
- 사용자 요청: `서울특별시 마포구 양화로 45 2층`의 층·세부주소 보존, 복수 후보 선택 뒤 추가 입력, 동일 건물·층 이력 구분
- 관련 이슈: #195. 개발 결과 보고서 #193에 이번 진단을 반영한다.
- 기준: BE develop `67737fa79dfd19ceb69ada6094fd2ac4fc265f1a`, FE develop `80aaba21d21ea9cac86d007d767594c302312d41`; FE 공개 release `3842d636469e42e6aa58a9cc4fc77a774237d5a7`과 develop의 파일 차이는 없다.
- 범위: **현재 동작 재현과 구현 설계**. 앱/FE/DB/환경/공개 배포는 변경하지 않는다. 아래 제안은 아직 구현되지 않았다.

## 1. 확인 결과

문제는 서로 다른 세 경로다.

1. BE는 주소 기본값과 `floor_unit`을 분리하며 층을 버리지 않는다. 실제 요청도200·후보2개·`floor_unit="2층"`이었다. 기본 주소에 층이 없는 것은 계약상 정상이다.
2. FE는 첫 이동의 URL `floor`에는 층을 보존하지만, 재입력 화면이 기본 `address`만 복원한다. 다시 검색하면 층 없는 주소를 보내므로 **그때 실제로 상세정보가 없어진다**. 일부 출력도 기본 주소만 쓴다.
3. 후보 목록에는 층이 없고 후보 선택 즉시 이동한다. 선택한 건물에 `2층 201호`를 확인·추가하는 단계가 없다. 별도로, 검색 중 주소를 바꾸어도 이전 응답으로 이동하는 경합도 재현했다.

동일 층의 판정은 표시 문제와 별개다. 현재 `location_match`는 `same_spot/same_building/unverified`만 제공하며 같은 층만으로는 `unverified`다. 이를 같은 자리로 승격하는 방식은 사용하지 않고, 층 일치와 호수 일치를 분리한다.

## 2. 실제 검사와 한계

### 2.1 BE 기존 검사

다음 기존 pytest **120개 통과**, 실패/skip0. 새 기능을 구현하거나 미래 수용 조건이 통과한 것으로 보지 않는다.

```powershell
python -m pytest tests/test_geocode.py tests/services/test_kakao_local.py tests/test_geocode_place_names.py tests/etl/test_floor_unit.py tests/test_store_history.py -q
```

### 2.2 실제 공개 BE 표본

사용자가 제시한 주소와 category=cafe로 `/api/geocode`를 1회 호출했다. HTTP200, 후보2개, 최상위 `floor_unit="2층"`, 기본 도로명 주소에 층 없음이었다. 실제 좌표·후보별 지번·응답 원문·키는 이 문서에 저장하지 않는다. 카카오가 층의 존재나 임차 공간을 검증했다는 뜻은 아니며, 층은 사용자 입력에서 추출한 값이다.

### 2.3 합성 BE 계약 검사

MockTransport로 만든 서로 다른 건물키의 후보2개에 대해 각각 HTTP200과 모든 후보의 상세값을 확인했다.

| 입력 상세 | 최상위/각 후보의 floor_unit | 판정 |
| --- | --- | --- |
| 2층 | 2층 | 보존 |
| 2층 201호 | 2층 201호 | 보존 |
| 지하2층 | B2 | 정규화 |
| 201호 | 201호 | 호만 보존, 2층으로 추정하지 않음 |
| 1~2층 | null | 모호한 범위, 단일 층으로 만들지 않음 |

### 2.4 실제 FE 브라우저 재현

설치된 Chrome의 headless 브라우저로 공개 FE를 열고 API를 합성 응답으로 대체했다. FE 코드를 실행한 검사이며 실제 카카오 후보 내용·운영 DB 조회 검증은 아니다. 결과 조회 API는 고정 오류 응답으로 격리했다.

| 사례 | 관찰 | 결론 |
| --- | --- | --- |
| 단일 후보→결과 | address는 기본 주소, floor는2층. 조건 바는2층 표시 | 최초 URL에는 보존됨 |
| 결과 조건을 가지고 입력 화면 재방문 | 주소 입력칸에서2층 누락 | 복원 누락 |
| 위 상태에서 재검색 | 요청 query에2층 없음, 다음 결과 floor=null | 실제 상세정보 유실 재현 |
| 합성 복수 후보 | 후보 문구에2층 없음, 주소 입력칸1개, 후보 클릭 즉시 이동 | 후보 후 편집/확정 단계 없음 |
| 복수 후보의 두 번째 선택 | 선택 후보의 building_key와 floor=2층은 유지 | 선택 자체가 항상 층을 지우는 것은 아님 |
| 응답을1.2초 지연하고 주소를 다른 건물·3층으로 수정 | 이전 건물·2층으로 이동 | 오래된 응답 이동 경합 재현 |

브라우저 및 BE 재현 스크립트/안전한 요약은 이번 작업의 로컬 임시 검증 artifact로 보관한다. 저장소 의존성이나 FE 파일에는 추가하지 않는다. 팀 재현은 이 절의 단계·합성 응답 조건과 아래 수용 시나리오를 따른다.

## 3. 원인과 수정 지점

| 위치 | 현재 동작 | 필요한 변경 |
| --- | --- | --- |
| FE `src/pages/InputPage.tsx` | goToResult는 address에 기본 주소, floorUnit에는 상세값. initialAddress는query.address만 | 입력/결과/재입력에서 기본 주소·상세값을 같은 상태 모델로 취급 |
| FE `components/input/CandidateList.tsx` | 기본 주소만 표시, onSelect 즉시 이동 | 후보 선택→상세주소 확인·편집→진단 확정으로 분리 |
| FE `components/input/DiagnosisForm.tsx` | 주소 문자열1개. 입력 변경 시 `onChange`만 호출 | 상세 입력칸·선택 상태와 검색 세대 관리 |
| FE `pages/InputPage.tsx` `onChange`, `hooks/useGeocode.ts` | `geocode.data \|\| geocode.error`일 때만 `reset()`하므로 **대기 중(pending)에는 아무것도 무효화하지 않음**. `useMutation({ mutationFn: getGeocode })`에 세대·취소 신호 없음. 응답 후 `candidates.length <= 1`이면 즉시 `goToResult` | 대기 중 수정·재제출·unmount 때 이전 요청의 이동 권한 제거(세대 검사 필수) |
| FE `hooks/useDiagnosisQuery.ts` | address/floor를 별도 파라미터로 저장 | 구 URL 유지, 복원·직접 링크·공유 시 상세값 보존 |
| FE `components/layout/ConditionBar.tsx` | address 뒤에floorUnit 추가 | 공용 주소 표시 함수로 전환, 중복 부착 방지 |
| FE `pages/ReportPage.tsx`, `components/share/` | 일부 주소 줄은query.address만 사용 | 보고서·요약 이미지·조건 요약의 동일 표시 계약 |
| BE `services/kakao_local.py` | query에서 상세 추출 후 각 후보에 전달 | 기존 보존 유지. 새 UI의 원문/정규값 구분과 최종 확인 계약 검증 |
| BE `services/store_history.py` | 같은 층만으로는unverified | 기존 enum과 새 층 관계를 독립적으로 제공 |
| BE `etl/address/building_key.py` | 시군구·법정동·지번 기반 key | 물리 건물 고유번호로 잘못 설명하지 않음 |

## 4. 선택한 입력 UX와 상태 설계

### 4.1 입력 상태

기본 주소와 상세주소를 논리적으로 분리한다. 최초 한 칸에 `…45 2층 201호`를 붙여 입력한 사용자는 기존 방식으로 검색할 수 있게 유지한다.

| 상태 | 의미 |
| --- | --- |
| searchText | 현재 기본 주소 검색 입력. 사용자의 편집 중 문자열 |
| selectedCandidate | 사용자가 확정할 기본 주소·building_key·좌표·행정구 후보 |
| detailDraft | 사용자가 확인·수정할 상세주소 원문. 예:2층 201호 |
| floorUnit | BE가 해당 검색 입력에서 정상화한 층/호. 검증 전 원문과 구분 |
| searchGeneration | 주소/업종 변경 때 증가. 이전 응답의 선택/이동을 차단 |
| selectionGeneration | 기본 후보 선택이 어떤 검색 결과에 속하는지 식별 |

새 상세 입력은 후보 목록의 각 항목 안에 여러 개 만들지 않고 선택 카드 아래 하나만 둔다. 후보를 고르면 상세 입력에 포커스를 옮긴다. 기본 주소·층/호를 함께 보여 준 뒤 `이 주소로 진단하기`로 확정한다. 후보 선택만으로 이동하지 않는다. 단일 후보도 기존 층/호가 보이는 확인 단계를 제공한다.

### 4.2 상태 전이

1. 입력→주소 검색: 제출한 검색문자열/업종/세대를 고정한다.
2. 응답: 현재 세대와 다르면 버린다. 주소나 업종 수정, 새 검색, 취소, unmount는 이전 응답의 이동 권한을 없앤다. AbortSignal과 세대 검사를 함께 사용한다.
3. 후보 선택: 해당 후보의 주소·키·좌표를 묶어서 선택한다. 다른 후보의 키나 좌표와 섞지 않는다. 같은 검색 결과의 상세 초안은 후보 선택을 바꾸어도 유지하고, 별도 주소 검색을 시작하면 이전 상세를 자동 적용하지 않는다.
4. 상세 확인: 기존 `floor_unit`으로 상세 입력을 채운다. 검증된 값과 수정 초안은 구분한다. 비어 있으면 층/호 미입력으로 명확히 표시한다.
5. 최종 확정: 선택 후보·상세·업종이 같은 세대인지 확인한 후에만 URL을 만든다. 요청 중 버튼 연타와 이전 응답의 이중 이동을 막는다.
6. 재입력: 저장된 기본 주소와 상세를 두 칸에 복원한다. 기본 주소만 편집하면 이전 후보 선택/좌표/키의 확정을 해제한다.

### 4.3 상세 수정 후 BE 확인

초안이 직전 BE 정규화 입력과 같으면 확인된 floorUnit을 재사용한다. 달라지면 최종 확정 때 기존 `/api/geocode`로 `선택한 기본 주소 + 상세 초안`을 한 번 확인하고, **기존 선택 building_key에 대응하는 후보만** 사용한다. 후보가 없어지거나 다른 건물로 바뀌면 재선택을 요구하며 임의의 첫 후보로 이동하지 않는다. 매 키 입력마다 카카오를 호출하지 않는다.

이는 새 정규화 전용 API 없이 기존 계약으로 시작하는 1차안이다. 후보 identity는 **같은 후보 객체에서 나온 `building_key` + `address_jibun` 정확 일치**로 대조하고, 좌표는 부동소수 재계산 차이가 있을 수 있으므로 동일성 키가 아니라 선택 후보의 값을 그대로 유지하는 용도로만 쓴다(§9.2 B3). 조건을 만족하는 후보가 0개 또는 2개 이상이면 재선택한다. 응답은 후보가1개이면 `candidates=[]`이고 최상위 객체가 그 후보이므로 최상위와 `candidates`를 같은 규칙으로 함께 검사한다. 이 대조는 층 존재 검증이 아니다. 추후 주소 제공자 재호출이 부담이면 별도 상세 정규화 API를 설계할 수 있지만 이번 설계의 선행 구현은 아니다.

`1~2층`, 복수 호수, 반지하·중층 등 기존 파서가 단일 위치로 인정하지 않는 값은 원문을 지우지 않는다. 판정용 floorUnit은null·사유를 표시하며, 수정하거나 **상세 위치 미확인으로 계속**을 명시적으로 선택하게 한다. `201호→2층`처럼 호 번호로 층을 추론하지 않는다. 임의 자유 텍스트는 표시용 상세 원문이며 검증된 층/호로 취급하지 않는다.

## 5. URL·공유·API 호환 설계

- 기존 `address`는 기본 주소, `floor`는 기존 정상화 층/호로 유지한다. 기본 주소 뒤에 층을 중복 저장해 `2층 2층`이 생기게 만들지 않는다.
- 새 표시 원문 `detail`은 길이100·제어문자 제한의 선택 파라미터로 제안한다. 기존 URL은 floor에서detail 초깃값을 복원하고, 새 URL에서는 표시 원문과 판정값을 구분한다. 모호한 원문은detail에만 있고floor에는 없다.
- `formatDiagnosisAddress(base, detailOrFloor)` 같은 공용 포매터를 입력 복원·조건 바·요약·PDF·이미지에 사용한다. React plain text로 출력하고 HTML로 삽입하지 않는다.
- `detail`/`floor`가 충돌하거나 중복 파라미터가 있으면 자동으로 더 강한 일치를 채택하지 않는다. 명시 재확인을 요구한다. 최종 BE 요청의 정상화 결과를 우선하며 원문은 표시용으로 남긴다.
- 이력 GET의 building_key/floor_unit, AI POST의history.building_key/floor_unit은 동일하게 전달한다. 자유 원문detail은AI에 전송하지 않는다. 현재 query-only+history 분리를 유지한다.
- 주소·층/호·건물키가 들어가는 브라우저 요청 캐시 및 해석 캐시는 상세 변경을 새 조건으로 구분한다. 공용 서버 캐시/로그에 원문을 추가하지 않는다.
- URL에 주소를 담는 현재 서비스 특성상 공유 링크 자체에 위치 정보가 있다는 점은 유지한다. 보고서/로그 증빙에는 사용자별 URL·원문 후보를 수집하지 않는다.

## 6. 건물·층·자리의 판정 설계

### 6.1 건물 범위의 의미

현재 building_key는 물리 건물 고유번호가 아니라 **시군구·법정동·지번 기반 주소 범위 키**다. 같은 지번 안의 여러 동/상가를 언제나 구분하는 키가 아니다. 따라서 새 UI의 엄밀한 기본 용어는 `같은 건물 주소 범위`로 한다. 실제 동일 물리 건물 보증이 필요하면 공식 건물 식별자나 검증된 동 구분 근거가 추가로 필요하며, 기존 지번키만으로 보증하지 않는다.

동/복수 건물 정보가 모호하거나 충돌하면 같은 층·같은 자리로 승격하지 않는다. 지원하지 않는 동 문자열을 삭제해 일치시키거나 호수에서 층을 추론하지 않는다. 기존 원본을 변경·자동 백필하지 않는다.

### 6.2 비교 단위와 우선순위

새 `location_relation`을 이력 행의 **추가 선택 정보**로 설계한다. 기존 location_match의3개 enum과 AI의집계는 1차 구현에서 보존한다. 새 FE는 추가 필드가 없으면 기존 표시로 동작한다. 이력 rule_version은 실제 도입 시 새 버전으로 구분한다.

| 항목 | 상태/근거 |
| --- | --- |
| building | matched_address_scope / different / ambiguous / unknown. 근거 canonical_jibun_key, 물리 건물 확정 여부 별도 |
| floor | match / different / unknown. 요청과 원본에 명시된 단일 층, B1/1층 정규화 |
| unit | match / different / unknown. 호 원문에서 명시된 값만 사용 |
| relation_level (가칭) | same_spot / same_floor / same_building_scope / unverified. 기존 DB 열 `location_level`과 이름이 겹치지 않게 `level` 단독 이름을 쓰지 않는다(§9.2 B6) |
| reason | floor_missing, unit_missing, different_floor, different_unit, ambiguous_detail, building_identity_ambiguous, source_location_unverified 등 고정 코드 |

`same_floor`는 같은 주소 범위와 명시된 층의 일치이고, 같은 점포 자리의 확정이 아니다. 표현은 `같은 주소 범위 · 2층 일치(호수 미확인)`처럼 근거와 한계를 함께 표시한다. 물리 건물의 동 구분이 불명확한 사례는same_floor 대신unverified로 둔다.

| 주소 범위 | 요청 | 저장값/근거 | 새 관계 | 기존 location_match |
| --- | --- | --- | --- | --- |
| 같음·복수동 모호성 없음 | 2층 | 2층, 신뢰 가능한 단일 층 | same_floor / unit unknown | unverified 유지 |
| 같음·복수동 모호성 없음 | 2층 | 2층201호, 신뢰 가능한 위치 | same_floor / unit unknown | unverified 유지 |
| 같음·복수동 모호성 없음 | 2층201호 | 2층202호, 신뢰 가능한 위치 | same_floor / unit different | same_building 유지 |
| 같음·복수동 모호성 없음 | 2층201호 | 2층201호, 기존same_spot 신뢰 근거 | same_spot | same_spot 유지 |
| 같음 | 2층 | 3층 | same_building_scope / floor different | same_building 유지 |
| 같음 | 상세 없음 | 2층 | same_building_scope / floor unknown | unverified 유지 |
| 다름 | 2층201호 | 2층201호 | different scope / unverified. 동일 층 호수로 건물 연결 금지 | 조회 대상 밖 |
| 같은 지번·동 불일치/모호 | 2층201호 | 다른 동2층201호 | unverified / building_identity_ambiguous | 현재 값 승격 금지 |
| 같음 | 2층 | 저장 위치 신뢰 미확인/1~2층 | unverified | unverified 유지 |

새 추가 필드의 building status와 level은 함께 검증한다. different/ambiguous/unknown인 건물 근거에서same_floor/same_spot을 반환하지 않는다. floor match 없이same_floor/same_spot을 반환하지 않고, unit match·기존신뢰 근거가 없으면same_spot이 될 수 없다.

### 6.3 조회·정렬·AI

- 기본 건물 이력은 현재처럼 지원 업종 전체를 유지한다. 층 입력만으로 다른 층 이력을 조용히 없애지 않는다.
- FE에서 `같은 층 우선` 또는 `같은 층만 보기`를 별도 명시 선택으로 제공할 수 있다. 기본은 전체이며 전체/일치/미확인을 구분한다. 최신순 정렬은 같은 그룹 안에서 유지한다.
- 같은 층 집계를 같은 자리 폐업 건수·운영 개월 범위로 바꾸지 않는다. 1차에서는 기존 AI의same_spot/전체 이력 문맥·분모·검증 규칙을 유지한다. 새 층 설명을 AI에 연결하려면 별도 typed allowlist/프롬프트·캐시·검증과 후속 동시 변경이 필요하다.
- 호만 일치, 층 누락, B1/1층 차이, 지번 일치만으로 지점 동일성·임대차/현재 입점·층 실제 존재를 추정하지 않는다.

## 7. 구현 순서와 수용 테스트

### 7.1 구현 순서

1. FE 주소 상태/표시 공통화·재입력/공유 복원과 오래된 응답 이동 차단
2. 후보 선택 후 상세 편집·최종 확인, 상세 수정 후 같은 후보 재검증
3. BE 순수 관계 비교기·추가 응답 스키마·원본 신뢰/지번 범위 한계
4. FE 같은 층/같은 자리/다른 층 표시와 보고서·이미지 일치
5. 새 기능 회귀·실제 API/브라우저·합성 경합·구버전 호환 검증 후 별도 배포

### 7.2 수용 시나리오

| ID | 시나리오 | 구현 후 통과 조건 |
| --- | --- | --- |
| A01 | 사용자가 제시한 기본 주소+2층, 단일 후보 | 확인 카드·결과·재입력·PDF·이미지에서2층 보존 |
| A02 | 같은 입력, 후보2개 | 선택한 후보 키/좌표와2층 보존. 후보 클릭만으로 이동하지 않음 |
| A03 | 후보 선택 후201호 추가 |2층201호로 확인·재선택/키 일치 후이동, 입력 칸에서수정가능 |
| A04 | 후보를다른 후보로변경 |상세 초안은유지하되새기본주소/키/좌표를세트로사용 |
| A05 | 다른주소새검색 |이전상세·후보 자동승계없음,새제출문맥만사용 |
| A06 | 입력화면재방문→바로재검색 |floor/detail유실없음, 기존URL도호환 |
| A07 | 검색대기중주소/업종수정·뒤로가기·unmount |이전응답이후보/키/층을덮거나이동시키지않음 |
| A08 | 지하2층 / B2 / 2층 |B2둘은정규화일치,지상2층과불일치 |
| A09 | 같은층·호누락/다른호 |same_floor로만표시,같은자리/AIsame_spot집계로승격금지 |
| A10 | 같은층·같은호·다른건물/다른동 |동일자리·동일층판정금지 |
| A11 |201호만 / 1~2층 / 원본신뢰미확인 |층추론·비공개보완·원문삭제없음,사유표시 |
| A12 |상세수정/취소/이중클릭·느린구응답 |한번만확정,상세가다른캐시/AI를재사용하지않음 |
| A13 |구BE추가필드없음·구FE |기존세enum/보고서동작보존,새기능없음은명시 |
| A14 |스크립트문자·중복URL키·긴상세·키/층충돌 |plain text/상한/명시재확인,주입/누출없음 |
| A15 |키보드·360/390px·인쇄 |후보선택→상세입력→확정포커스,레이블/오류연결·넘침/층누락없음 |

## 8. 완료 판정과 남은 일

현재는 기존 BE120개, 합성 BE5종, 실제 공개 BE1회, 공개 FE+합성API 브라우저3종으로 원인과 현재 계약을 확인한 상태다. 미래 수용시나리오A01~A15가 모두 통과한 상태는 아니다. FE/BE 구현·새 계약·DB 보정·운영 반영은 후속이며, 현재 공개 화면의 상세 유실과 오래된 응답 이동 결함이 해결됐다고 표시하지 않는다.

## 9. 실제 Claude Code MD 검토

### 9.1 검토 범위와 근거

- 읽은 BE 파일: `app/routers/geocode.py`, `app/services/kakao_local.py`, `app/schemas/geocode.py`, `etl/address/floor_unit.py`, `etl/address/building_key.py`, `app/schemas/stores.py`, `app/services/store_history.py`, `app/schemas/interpret.py`, `app/routers/interpret.py`, `app/services/risk_interpret.py`(앞부분 200줄).
- 읽은 FE 스냅샷(`80aaba2`): `src/pages/InputPage.tsx`, `src/components/input/DiagnosisForm.tsx`, `src/components/input/CandidateList.tsx`, `src/hooks/useDiagnosisQuery.ts`, `src/hooks/useGeocode.ts`, `src/api/geocode.ts`, `src/components/layout/ConditionBar.tsx`, `src/types/diagnosis.ts`, `src/types/stores.ts`.
- 읽은 안전한 요약 2개: `spoton-address-probe.json`(합성 geocode 5종, 현재 매칭 6종, 실제 사용자 주소1회의 집계값만), `spoton-address-browser/results.json`(공개 FE+합성 API 3종).
- 검토자는 명령·네트워크·테스트를 실행하지 않았다. 아래의 "코드 판독"은 코드를 읽고 내린 판단이며 실행으로 확인한 것이 아니다. `ReportPage.tsx`, `components/share/`, `api/client.ts`(취소 신호 지원 여부)는 이번에 다시 읽지 않았으므로 §3의 해당 행은 작성자 진단으로만 남긴다.

**§1~§2 사실 대조 결과:** 요약 파일과 일치한다. 실제 호출 `status=200`, `candidate_count=2`, `floor_unit="2층"`, `base_address_has_floor=false`이다. 합성 5종의 `preserved_on_each=true`와 `1~2층→null`, `지하2층→B2`도 같다. 브라우저 3종 결과(재방문 뒤 `second_floor=null`, 후보 문구에 층 없음·입력칸1개·즉시 이동, 대기 중 수정했는데 이전 건물·2층으로 이동)도 §2.4 표와 일치한다. 현재 매칭 6종은 `store_history.location_match` 코드 판독 결과 및 §6.2의 "기존 location_match" 열과 같다. 단 요약의 `level`은 저장 원천의 `Store.location_level`이며 새 관계 단계가 아니다.

### 9.2 구현 전 반드시 설계에 반영할 사항(blocker)

| ID | 근거(코드 판독/실측) | 문제 | 설계 결정 |
| --- | --- | --- | --- |
| B1 오래된 응답 | InputPage `onChange`는 data/error가 있을 때만 `reset()`. pending 중에는 무효화 없음. 브라우저 `stale_response_navigated=true` | 대기 중 수정한 주소 대신 이전 건물·층으로 이동 | **세대(generation) 검사를 필수**로 한다. 취소 신호(AbortSignal)는 `apiGet` 지원 여부를 확인한 뒤의 보조 수단이다. 이동·후보 표시·상세 채우기는 모두 "응답 세대 = 현재 세대"일 때만 한다. 단일 후보 자동 이동(`candidates.length <= 1`)도 같은 검사를 거친다 |
| B2 층 유실 | `initialAddress={query.address}`만 전달. `floorUnit`은 입력 화면에 복원하지 않음. 실측 `detail_lost_after_resubmit=true` | 재방문 뒤 재검색하면 층이 없어짐 | 재입력 화면은 `floor`(기존 URL) 또는 `detail`(새 URL)을 상세 칸에 반드시 복원한다. 상세 칸이 비지 않았는데 최종 요청의 `floor_unit`이 null이면 조용히 진행하지 않고 §4.3의 "상세 위치 미확인으로 계속"을 명시적으로 선택하게 한다 |
| B3 재검증 identity | `floor_unit`은 Kakao가 아니라 BE `parse_floor_unit(query)`가 **검색 문자열 전체**에서 뽑는다. 모든 후보에 같은 값을 복사하고, usable은 최대5개, 후보1개면 `candidates=[]` | 상세만 바꿔 다시 geocode하면 후보 집합이 달라져 다른 건물로 바뀔 수 있음. 층 "검증"이 아니라 파서 실행일 뿐 | §4.3을 수정했다. 동일성은 `building_key`+`address_jibun` 일치로 판정한다. 좌표·키는 처음 선택한 후보의 값을 유지하고 재검증 응답으로 덮어쓰지 않는다. 재검증 응답은 `floor_unit`을 얻는 용도로만 쓴다. 일치하는 후보가 0개 또는 2개 이상이면 재선택한다. 재검증 query의 기본 주소에는 FE가 저장하는 `address_road \|\| address_jibun`이 아니라 **선택 후보의 `address_jibun`**을 쓰도록 고정한다(키가 지번 기반이므로 identity 대조가 단순해진다). 이 결정은 아직 실측하지 않았다 |
| B4 동 표기 시 층 소실 | `floor_unit.py`의 `_SINGLE_BUILDING_RE`(`101동`, `A동`)가 AMBIGUOUS가 되어 **전체 floor_unit이 null** | `…45 A동 2층`을 입력하면 BE 단계에서 층이 null이 됨(코드 판독, 미실측). 현재 FE는 이를 알리지 않음 | B2와 같은 규칙을 적용한다. 원문은 상세 칸에 남기고, 판정용 floor는 null로 두며 사유는 `ambiguous_detail`로 표시한다. 동을 지워서 층을 살리는 보정은 금지한다(§6.1과 일치) |
| B5 URL `floor` → 422 | `HistoryQuery.canonical_detail`은 파싱 실패 시 오류이고, AI `InterpretRequest`도 같은 `HistoryQuery`를 만든다. FE `parseDiagnosisQuery`는 `floor`를 형식 검사 없이 받는다 | 직접 고친 URL·`1~2층` 등이 `floor`에 들어가면 이력 GET과 AI POST가 모두 422 | `floor`에는 BE가 정규화한 값만 쓴다. 422가 나도 **floor를 빼고 자동 재시도하지 않는다**(조용한 범위 확대 방지). 대신 조건 재확인을 안내한다. 모호한 원문은 `detail`에만 둔다 |
| B6 이름 충돌·불변식 | DB `Store.location_level`은 저장 원문에 층과 호가 모두 있으면 `same_spot`, 아니면 `same_building`(`FloorUnitValue.location_level`). 물리적 자리를 검증한 값이 아님 | §6.2의 "기존 same_spot 신뢰 근거"가 이 열을 뜻하는데, 새 `level`과 혼동됨 | 새 필드 이름은 `relation_level`(가칭)로 바꿨다. "기존 신뢰 근거" = `Store.location_level == "same_spot"`이라고 명시한다. 불변식: building ∉ {matched_address_scope}이면 relation_level ∈ {unverified}. floor≠match이면 same_floor·same_spot 불가. same_spot은 floor match ∧ unit match ∧ location_level=same_spot일 때만. **호만 일치하고 층이 unknown이면 same_spot·same_floor 불가**(예: 요청`201호`, 저장`2층 201호` → 기존 unverified, 새 관계 same_building_scope 이하). `B1`≠`1층` |
| B7 기존 AI enum | `HistoryFactId = "building_history" \| "same_spot_history"`, `HistoryStore.location_match`는 3값 Literal, `InterpretHistory`는 `extra="forbid", strict=True` | 새 관계를 AI에 섞으면 same_spot 집계·분모가 바뀜. detail을 body에 넣으면 422 | 1차에서 `same_spot_history`의 집계 기준은 기존 `location_match=="same_spot"`으로 고정한다. AI body에는 `building_key`/`floor_unit`만 보내고 `detail`은 보내지 않는다(§5와 일치). 코드 판독상 AI 캐시 키에는 history 문맥이 들어간 payload가 포함되므로 층이 바뀌면 키도 달라진다. 이 동작은 별도 회귀 확인 대상이다 |
| B8 URL 충돌 | `parseDiagnosisQuery`는 `address`/`floor`/`bk`를 `params.get`(첫 값)으로 읽고, 중복 검사는 brand 키에만 한다. `bk`·`floor`·`address`·`lat/lng`는 서로의 정합성을 검사하지 않음 | 중복 키, `floor`는 있는데 `bk`가 없는 URL, 손으로 섞은 URL을 조용히 하나로 해석함 | 새 상세 관련 키(`address`,`floor`,`detail`,`bk`)에 중복이 있거나, `detail`의 정규화 결과와 `floor`가 다르면 이력·AI를 호출하지 않고 재확인을 요구한다. 기존 URL(`detail` 없음, `floor`만 있음)은 충돌이 아니며, `floor`를 상세 칸 초깃값으로 쓴다 |

### 9.3 상태 모델 정합성 확인

§4.1~4.2 상태는 다음 불변식을 지켜야 서로 맞는다. 문서 본문에 이미 있는 내용과 충돌하지 않는다.

1. `confirmed = {selectedCandidate(키·지번·도로명·좌표·gu 한 묶음), floorUnit(BE 정규화값 또는 null+사유), detailDraft(원문), category, generation}`. URL은 이 묶음에서만 만든다.
2. `detailDraft` 편집은 선택 후보를 해제하지 않는다. 상세가 마지막 BE 정규화 입력과 다르면 확정할 때 B3 재검증을 한 번 한다.
3. `searchText`(기본 주소) 편집과 업종 변경은 세대를 올리고 `selectedCandidate`를 해제한다. `detailDraft`는 같은 화면 안에서는 지우지 않는다(사용자 입력 보존). 다만 새 검색 결과에 자동으로 확정 적용하지는 않는다. §4.2의 3번 "별도 검색에서 이전 상세를 자동 적용하지 않음"은 **확정값에 넣지 않는다는 뜻**이고, 칸의 문자열을 지운다는 뜻이 아니다.
4. 이동은 확정 버튼 한 번에서만 일어난다. 단일 후보도 확인 카드를 거친다. 요청 중에는 버튼을 막고, 이전 세대의 응답은 무시한다.

### 9.4 "같은 주소 범위" vs 물리 건물

`building_key`는 `{구}-{법정동}-{산?}{본번}-{부번}`이다(`building_key.py`). 같은 지번의 여러 동, 그리고 하나의 건물이 여러 필지에 걸친 경우를 구분하지 못한다. Kakao 후보도 지번 주소 `address`가 없으면 버린다. 따라서 §6.1의 "같은 건물 주소 범위" 용어는 코드와 맞다. FE의 현재 문구("같은 건물", `EMPTY_HISTORY_MESSAGE`의 "이 건물")를 바꿀지는 선택 사항이지만, 새 same_floor 표시는 반드시 "같은 주소 범위"로 표기한다. 도로명이 같고 지번이 다른 후보(B3의 2후보 상황)를 같은 건물로 합치지 않는다.

### 9.5 선택(optional) 사항 — 1차 필수가 아님

- `detail` URL 파라미터: B2·B5를 지키려면 모호한 원문을 새로고침·공유 뒤에도 보존할 곳이 필요하므로 **권장**한다. 대안은 "미확인으로 계속"을 명시적으로 고른 뒤 원문을 보존하지 않는 것이다. 이때도 조용한 유실은 아니어야 하므로 화면에 "상세 위치 미확인"을 표시한다.
- AbortSignal 취소(세대 검사가 필수이고 취소는 부가 기능), 별도 상세 정규화 API, `같은 층 우선/만 보기` 필터, 새 관계를 AI 문맥에 연결하는 일, 기존 "같은 건물" 문구 교체, `rule_version` 상향(새 필드를 실제로 도입할 때는 필수).

### 9.6 수용 시나리오 보강(미실행 설계 항목)

§7.2에 다음을 추가한다. 모두 **아직 구현·실행되지 않았다**.

| ID | 시나리오 | 통과 조건 |
| --- | --- | --- |
| A16 | `…45 A동 2층` 또는 `101동 2층 201호` | 원문은 상세 칸에 보존. floor=null+`ambiguous_detail`. 명시 선택 없이 진행 불가. 동 제거 보정 없음 |
| A17 | URL `floor=1~2층`(직접 수정)·`floor` 중복·`bk` 없이 `floor`만 | 이력·AI 422를 floor 제거 재시도로 숨기지 않음. 재확인 안내 |
| A18 | 상세 재검증 응답이 단일 후보(`candidates=[]`)·다른 키·같은 키 2개 | 최상위/목록을 같은 규칙으로 대조. 0개 또는 2개 이상이면 재선택. 처음 선택한 좌표·키 유지 |
| A19 | 요청 `201호`(층 없음), 저장 `2층 201호`(location_level=same_spot) | 기존 unverified 유지. 새 관계에서 same_spot·same_floor 아님 |
| A20 | 단일 후보 응답이 pending 중 주소 수정 뒤 도착 | 자동 이동 없음(B1). 현재 브라우저 재현 사례의 반대 조건 |
| A21 | 기존 URL(`detail` 없음, `floor=2층`) 재방문 | 상세 칸에 `2층`이 채워지고, 재검색 query에 포함됨 |

### 9.7 판정

- 설계의 방향(기본 주소/상세 분리, 후보 선택과 최종 확정 분리, 세대로 오래된 응답 차단, 기존 `location_match` 3값과 AI `same_spot_history` 보존, 새 관계를 별도 필드로 추가, "주소 범위" 용어)은 BE·FE 실제 계약과 맞다.
- 구현에 들어가기 전에 B1~B8을 설계로 확정해야 한다. 이번 검토에서 §3(pending 무효화 원인 행), §4.3(identity 대조 규칙), §6.2(`relation_level` 이름)를 직접 수정했다.
- 현재 결함(재방문 층 유실, 후보 뒤 상세 확인 단계 없음, 오래된 응답 이동)은 **해결되지 않았다**. 기존 BE 120개 통과는 현재 계약의 회귀 확인일 뿐이며, A01~A21 중 실행된 것은 없다.

## 10. Codex 최종 설계 결정

검토 B1~B8을 모두 채택해 구현 기준으로 확정한다. 다음 사항은 선택안으로 남기지 않는다.

1. 세대 검사는 필수다. AbortSignal 지원은 기존 `src/api/client.ts`의 options.signal과 별도 AbortController 연결에서 확인했다. mutation에도 신호를 전달하되 취소 성공에만 의존하지 않는다. 후보 표시·상세 채우기·단일 후보·최종 이동 모두 세대를 확인한다.
2. 선택과 이동을 분리하며, 기본 주소 편집 때 키/좌표 선택을 무효화한다. 입력 중 상세 초안은 지우지 않지만 새 건물에 자동 확정 적용하지 않는다. 새 검색 결과의 상세 칸을 확인해야 한다.
3. 기존 URL의floor는 상세 칸에 복원한다. 새detail 파라미터는 **채택**해 모호한 원문도 재방문/공유 때 보존한다. `detail`과`floor` 충돌/중복·bk누락·손으로 섞은 조건은 이력/AI 자동조회 전에 재확인을 요구한다. 422에floor제거 재시도는 하지 않는다.
4. 수정한 상세의 BE 파서 재실행은 §4.3/B3처럼 처음 선택한 지번을 사용한다. 단일 후보는 최상위data, 복수 후보는candidates에서 정규화된key+지번이 유일하게 대응해야 한다. 키/좌표/행정구 등 선택 객체를 재검증 응답과 부분 혼합하지 않는다. 동일 지번 내 물리 건물 구분을 새로 보증하는 절차는 아니다.
5. 기존floor_unit=null만으로는 ambiguous/invalid/no_detail을 구분할 수 없다. 실제 구현에서는 **공통meta에 선택적detail_parse 상태/고정 사유/규칙버전**을 추가하는 호환 확장을 함께 검토·구현한다. 기존파서결과를 투영하며 원문을 추가로 반환하거나 로그에 남기지 않는다. 구BE의 해당메타부재는unknown으로 처리하고 확정값으로 가정하지 않는다. 상세 입력은 기존100자 상한과 맞추며 지원하지 않는 문자는 필드 오류로 보여 준다.
6. 한 칸에 붙여 넣은 전체검색어에서 파싱이 실패했다면, BE의기본주소만 보고 상세가없었다고 결론내리지 않는다. 원래검색어를 입력폼에보존하고 선택후사용자가상세를확인/분리할수있게한다. 신뢰할수없는문자열자르기로동/층을없애지않는다. 명시한단일층/호로정상화된경우는canonical값과원래입력표시를구분한다.
7. 새응답은 `location_relation.relation_level`로명명해저장열location_level과분리한다. 같은지번범위/같은층/같은호는독립항목이다. 물리건물ID가없는범위는주소범위임을표시하고,동모호/불일치·층불명에서는same_floor/same_spot을허용하지않는다. 기존location_match와AI same_spot집계는바꾸지않는다.
8. A01~A21과새meta부재/파서실패사유·100자상한·원문보존수용검사를실제구현의완료조건으로둔다. 기본이력전체모집단·연도추이·Risk계산·원본DB를바꾸지않는다. 새관계필드가실제도입될때이력규칙/응답캐시버전을구분한다.

현재 작업의 완료는 **원인 재현·120개 기존 검사·설계/실제 Claude 검토·최종 결정 기록**이다. 코드 수정/미래 수용 검사/화면 개선/운영 배포 완료는 별도 후속이다.

## 11. Claude 최종 재검토(§4~§7, §10, B1~B8)

### 11.1 범위와 근거

- 다시 읽은 파일: 이 문서, `app/schemas/geocode.py`, `app/schemas/stores.py`, `app/schemas/common.py`, `app/routers/geocode.py`, `app/services/kakao_local.py`, `etl/address/floor_unit.py`. FE 파일과 `store_history.py`, `interpret` 계열은 이번에 다시 읽지 않았다. 해당 부분은 §9의 코드 판독을 그대로 따른다.
- 명령·네트워크·테스트는 실행하지 않았다. 새 검사를 추가하거나 통과시킨 것은 없다. A01~A21은 여전히 실행되지 않았다.

### 11.2 B1~B8 반영 확인

| 항목 | §10 반영 | 판정 |
| --- | --- | --- |
| B1 세대 검사 | §10.1에서 필수로 정했고 AbortSignal은 보조 수단 | 해소 |
| B2 층 복원 | §10.3에서 floor→상세 칸 복원, detail 채택 | 해소 |
| B3 재검증 identity | §10.4에서 선택 지번 query, key+지번 유일 대응, 선택 객체를 섞지 않음, 처음 고른 좌표 유지 | 규칙은 해소. 실패할 때의 경로는 11.3 R2 참고 |
| B4 동 표기 | §10.6 "동/층을 문자열 자르기로 없애지 않음", A16 | 해소 |
| B5 floor 422 | §10.3 "floor를 빼고 재시도하지 않음" | 해소 |
| B6 이름 | §10.7 `location_relation.relation_level`, 저장 열 `location_level`과 분리 | 해소. 11.4의 표기 정리 참고 |
| B7 AI enum | §6.3·B7·§10.7에서 `location_match` 3값, `same_spot_history`, `InterpretHistory` body를 바꾸지 않음 | 해소. 서로 모순되는 곳 없음 |
| B8 URL 충돌 | §10.3에서 채택 | 판정 방법이 정해지지 않음. 11.3 R1 참고 |

스키마 대조:
- `ApiResponse.meta`는 `dict[str, JsonValue]`이고 `extra="forbid"`는 외피에만 걸려 있다. 따라서 §10.5의 선택 필드 `meta.detail_parse`를 추가해도 기존 BE 스키마와 호환된다.
- `GeocodeCandidate`/`GeocodeData`는 `extra="forbid"`라서 상태를 meta에 두기로 한 결정이 맞다.
- `FloorUnitFailure`(empty/no_detail/ambiguous/invalid)가 실제 파서 상태의 원천이다.
- detail 100자 상한은 `HistoryQuery.floor_unit max_length=100`과 같다.
- 원문을 meta에 다시 내보내지 않는다는 결정은 `NO_STORE_HEADERS`, 그리고 원문을 로그에 남기지 않는 현재 서비스 방침과 맞다.

### 11.3 남은 실제 blocker(구현 착수 전 문서로 확정)

| ID | 근거 | 문제 | 필요한 결정 |
| --- | --- | --- | --- |
| R1 URL detail↔floor 정합 판정 방법 | 상세 파서는 BE `parse_floor_unit`뿐이다. FE에는 같은 파서가 없다. B8/§10.3은 "detail의 정규화 결과와 floor가 다르면 재확인"이라고 했지만 URL을 불러올 때 그 정규화를 누가 하는지 정하지 않았다 | 이대로면 FE가 파서를 따로 복제하게 되어 규칙이 어긋날 위험이 있다. 반대로 비교를 생략하면, 손으로 고친 URL(`detail=3층`, `floor=2층`)이 3층으로 표시되면서 2층 이력을 조회하게 된다. `지하2층`/`B2`처럼 글자는 달라도 같은 값인 경우는 단순 문자열 비교로 판정할 수 없다 | 둘 중 하나를 고정한다. (a) URL을 불러올 때 FE는 정규화하지 않는다. 이력·AI 판정에는 `floor`만 쓰고, 화면에서는 판정값(`floor`)과 입력 원문(`detail`)을 서로 다른 레이블로 함께 표시한다. 이 경우 B8의 "정규화 비교" 문구는 중복 키, `bk` 누락, 형식 오류 검사로 축소한다. (b) 불러올 때 기존 geocode로 재확인하고, 그 결과가 오기 전에는 이력·AI를 호출하지 않는다. 어느 쪽이든 FE에서 파서를 복제하는 방식은 쓰지 않는다. A14/A17의 통과 조건도 선택한 방식으로 고친다 |
| R2 재검증 실패 시 막다른 경로 | `kakao_local.geocode`는 query 전체를 Kakao에 보낸다. 선택 지번+상세 query는 실측하지 않았다(B3). 결과가 0건이면 `ADDRESS_NOT_FOUND`/`OUT_OF_SEOUL` 오류가 나며, 오류 응답에는 meta `detail_parse`도 없다 | §4.3/§10.4는 0개, 2개 이상, 오류일 때 "재선택"만 정했다. 같은 후보를 다시 골라도 같은 query가 만들어지므로 상세를 확정할 방법이 없다 | 재검증이 실패하면 처음 선택한 후보(키·좌표·지번)를 유지한다. 그 상태에서 사용자에게 두 가지만 허용한다. ① 상세를 고친다. ② 명시적으로 "상세 위치 미확인으로 계속"을 고른다(floor=null, detail 원문 보존). 이 두 경로를 문서로 고정한다. 오류 응답이나 meta가 없는 응답은 `detail_parse=unknown`으로 처리한다. 다른 후보로 자동 전환하거나 이전 floorUnit을 재사용하는 것은 금지한다. 이 경우를 A18에 추가한다 |

### 11.4 blocker가 아닌 문서 내부 표기 정리(구현 의미는 §10이 우선)

- §4.3 첫 문단의 "선택한 기본 주소 + 상세 초안"은 B3/§10.4에 따라 **선택 후보의 `address_jibun` + 상세 초안**으로 읽는다. FE 표시용 `address_road || address_jibun`으로 읽지 않는다.
- §4.1 `floorUnit` 설명과 §4.3의 "확인된/검증된 floorUnit"은 층이 실제로 있는지 검증했다는 뜻이 아니다. **BE 파서가 정규화한 값**이라는 뜻이다(B3).
- §6.2 표 아래 문단의 "building status와 level"은 `relation_level`로 읽는다. 표의 "different scope"는 building=`different`, relation_level=`unverified`를 뜻한다. 새 enum 값이 아니다.
- §6.2의 "복수동 모호성 없음"은 BE가 확인할 수 있는 사실이 아니다. building_key와 저장 원문에 동 표기가 없다는 뜻일 뿐이며, 단일 물리 건물이라는 증거가 아니다. 따라서 이 행의 same_floor도 반드시 "같은 주소 범위" 표기를 쓴다(§9.4와 일치).
- `detail_parse`의 고정 사유(`FloorUnitFailure` 투영)와 §6.2 reason 코드(`ambiguous_detail` 등)의 대응표는 구현할 때 하나로 고정한다. 한 칸 입력에서는 파싱 상태가 query 전체에 대한 것이다. 그러므로 상세 부분만의 상태로 해석하지 않는다(§10.6과 일치).

### 11.5 판정

- §4~§7과 §10은 B1~B7과 서로 모순되지 않는다. 확인한 결정은 다음과 같다: 세대 검사 필수, 선택과 확정 분리, detail 채택, key+지번 재검증과 처음 고른 좌표 유지, 주소 범위의 보수적 한계, 선택 meta `detail_parse`, 원문 보존, 기존 AI enum 보존. 이 결정들은 위에서 읽은 BE 스키마와도 맞다.
- **남은 blocker는 R1과 R2 두 개다.** 둘 다 설계 문구를 확정하면 해소된다. 구현 방향을 바꾸는 문제는 아니다. 둘을 확정하기 전에 B8 URL 처리와 상세 재검증 UI를 구현하지 않는다.
- 현재 결함(재방문하면 층 유실, 후보 선택 뒤 상세 확인 단계 없음, 오래된 응답으로 이동)은 여전히 해결되지 않았다. 이번 재검토에서는 실행하거나 추가한 검사가 없다.

## 12. 재검토 후 최종 확정: URL 검증과 실패 복구

11.3의R1/R2는 다음과 같이 결정한다. 재검토 당시의 미결 기록과 이 최종 결정을 구분하며, 미래 수용 검사를 이미 실행한 것으로 표시하지 않는다.

### 12.1 R1: BE 재확인 뒤 이력·AI 허용

**R1의(b)를 채택한다.** FE에서 층/호 파서를 복제하거나 단순 문자열 비교로 `지하2층`과`B2`를 판정하지 않는다. 새로고침·직접/공유 링크에서 상세가 있는 경우, BE 재확인 완료 전에는 해당 위치의 이력·AI 조회/이전을 허용하지 않는다.

- 중복address/bk/floor/detail, 키 없는floor, 길이/제어문자 오류는 네트워크 요청 전에 재확인을 요구한다.
- 한 세션에서 이미 확정한 동일 조건 묶음은 화면 이동마다 카카오를 다시 호출하지 않는다. 주소·상세·건물키·업종이 바뀌거나 새 URL을 불러오면 새 세대로 검증한다.
- 직접 링크의 기본 주소를 BE로 조회해 URL의building_key와 유일하게 대응하는 후보를 찾는다. 주소키/후보가 맞지 않거나 복수 대응이면 입력 화면에서 재선택한다. URL의좌표·키를 새후보와 부분 혼합하지 않는다. 직접링크는 아직 신뢰된선택객체가아니므로 최초선택을다시확정하며,좌표/주소가달라지면사용자가확인한다.
- 같은 UI에서 이미 선택한 후보의 상세만 편집하는 경우는 B3대로 해당후보지번을 사용하고 기존선택좌표를 유지한다. 두 경로를 구분한다.
- 재확인에서 얻은 정상화 floorUnit과 URL의floor가 다르면 자동조회하지 않고 상세 확인 화면을 연다. 같다면 해당세대의확정묶음을만든다. 구URL에detail이없으면floor를상세초안으로쓴다.
- 원문detail만있고floor가없다면자동으로버리지않는다. BE정규화결과를확인한뒤사용자가확정한다. 파싱실패나미제공이면아래R2경로를쓴다.

### 12.2 R2: 후보/원문 보존과 명시적 범위 선택

상세를 붙인 조회가404/502/timeout이거나 meta미제공/대응후보0·복수이면, 마지막으로선택한기본후보와상세초안은보존한다. 선택을지우고같은검색을강제하는막다른흐름을만들지않는다. 사용자는둘중하나를선택한다.

1. 상세를 수정하고 다시 확인한다. 다른건물로바꾸려면별도로기본주소를다시검색한다.
2. **상세 위치 미확인으로 계속**을 직접 선택한다. floor=null, detail원문보존, `detailMode=unverified`를확정묶음/URL에명시하고 `입력한 상세:… / 판정:상세위치미확인·건물주소범위전체`를표시한다. 같은층필터·같은자리집계에는넣지않고이력/AI의floor_unit은null이다.

미확인모드URL은문자열unverified만허용하며floor와함께있으면재확인을요구한다. 공유/재방문때도해당안내를유지한다. 기본주소/건물후보의확인은필요하지만미확인상세를끝없이재검증하지않는다. 이marker는물리위치검증증명이나권한토큰이아니며,해당상세가미확인이라는표시다. 자동실패복구에서이모드로바꾸거나이전floorUnit을재사용하지않는다.

### 12.3 추가 수용 검사

- A22: `detail=지하2층&floor=B2`는BE정규화후일치, `detail=3층&floor=2층`은이력/AI없이재확인. 새정규화파서를FE에만들지않음.
- A23: 직접링크의잘못된key/좌표/복수후보는자동전환없음. 기존선택의상세수정은그선택을보존함.
- A24: 상세재검증404/502/timeout/구BE meta미제공에서원문·기본후보를유지. 수정또는명시적미확인계속모두도달가능.
- A25: 미확인모드공유/재방문/보고서/이미지는원문과미확인범위를함께표시하고floor_unit=null을유지. conflicting floor·중복키는재확인.

최종산출물은원인/근거·두차례실제ClaudeMD검토·작성자결정·A01~A25수용설계다. 기존120개검사외의미래수용검사·구현·공개수정은후속이다.
