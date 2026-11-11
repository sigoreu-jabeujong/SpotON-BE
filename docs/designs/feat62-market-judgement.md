# BE-23 선행 상권 공간 판정 (#62)

- 기준: develop `408e32b`, `feat#62-market-judgement`, 2026-11-12
- 상태: Codex 설계 → Claude 실제 MD 수정 → Codex 최종 점검·구현·로컬 검증. CI 후 develop 일반 Squash 병합하며 실제 상태는 #62 연결 기록을 따른다.
- 범위: 명시한 경계 버전의 공간 후보 판정 서비스·내부 모델·검증. 공개 API/공식 지표·FE는 이번에 추가하지 않는다.

## 1. 근거와 범위

현재 BE-22 기본 활동 API는 PR61로 병합됐다. 다음 BE-23 Risk는 상권 판정이 선행되어야 한다. API v1.2 §4-7의 포함 폴리곤·세부 상권 우선/관광특구 병기·상권 밖 근처 목록, 통합 작업계획 7절 R-13/R-14를 따른다. 인허가 반경 집계와 상권 단위 공식 통계를 임의 결합하지 않는다.

현재 공식 경계 1,650행의 boundary_as_of는 null이다. source_file_date/loaded_at을 적용일로 바꾸거나 가장 최근 UUID를 자동 선택하지 않는다. 호출자가 명시적으로 지정한 UUID의 **공간 판정**과 **시점 적용 가능 여부**를 분리한다. applicability=unverified는 상수이고 후속 Risk의 공식 지표 활성화 근거가 아니다. boundary_as_of가 나중에 있어도 그 날짜 하나로 적용 종료일/분기 호환이 확정되는 것은 아니다.

## 2. 입력·출력

`BoundaryQuery`: version_id UUID, lat/lng 유한 WGS84 범위, radius 300/500/1000(기본500). 추가 키 거절·오류 입력 비노출·repr에 좌표 비노출. 미래 API의 사용자 입력으로 UUID를 받는다는 뜻이 아니라 서버가 선택 근거를 갖고 호출하는 내부 계약이다.

`MarketRef`: market_code/name/type. `BoundaryJudgement`: spatial_status=in_market/outside/ambiguous, primary nullable, candidates[], also_in[], nearby_markets[], provenance. 모든 목록은 market_code 정렬·중복 금지, 모호한데 primary를 붙이지 않는다. 결과의 공간 상태는 해당 파일 버전의 형상에 대한 것이며 적용 시점이 검증된 현재/과거 판정이 아니다.

provenance에는 version_id/source_dataset/source_url/source_file_date/boundary_as_of/input_sha256/content_sha256/rule_version을 보존하고 applicability=unverified와 reason=boundary_period_not_verified를 명시한다. 임의 상태를 fact로 바꾸지 않는다. 버전 없음/결과 모델 손상은 원문 없는 INTERNAL_ERROR이며 최신 버전으로 fallback하지 않는다.

## 3. 공간 규칙

1. 지정 version_id에 한정하여 WGS84 `ST_Covers(geom,point)`로 포함 조회한다. 외곽선·hole 경계 포함, hole 내부 제외, multipart 전체를 사용한다.
2. 관광특구 이외 A/D/R을 동일 세부 우선순위로 취급한다. 유형별 우열·면적·코드순으로 하나를 고르지 않는다.
3. 세부 1개면 primary, 관광특구는 also_in. 세부 여러 개면 ambiguous·primary=null·세부 candidates·관광특구 also_in이다.
4. 세부가 없고 관광특구 1개면 그 관광특구가 primary. 관광특구 여러 개면 ambiguous·그 특구 candidates·also_in=[]이다.
5. 포함이 하나도 없으면 outside·primary=null·candidates/also_in=[]이다. 이때만 같은 버전의 반경과 교차하는 상권 목록을 nearby_markets에 제공한다. 폴리곤 geography와 점 geography의 `ST_DWithin`+최종 반올림 전 `ST_Distance<=radius`로 구하며 중심점 거리/degree buffer로 대체하지 않는다. 목록은 가까운 상권의 공식 수치를 선택하라는 의미가 아니다.

## 4. 구조·안전

- app/schemas/market_judgement.py: 내부 입력/엄격한 결과 모델과 불변식
- app/services/market_judgement.py: 순수 후보 선택 함수 + 지정 버전 SQL 조회. 후속 Risk의 호출 전용이며 라우터/main은 변경하지 않는다.
- 기존 MarketArea/Version·Geometry/GIST 재사용, 모델/migration/의존성 변경 없음. 1,650개 대상 geography cast는 기존 geometry GIST와 다른 인덱스 조건이므로 인덱스 사용을 과장하지 않는다. 필요한 최적화는 실행 계획 근거 후 별도 변경한다.
- 서비스는 주어진 Session을 사용하고 commit/rollback/설정 변경을 하지 않는다. 호출자가 기존 요청별 READ ONLY REPEATABLE READ 세션을 제공한다. 테스트/실제 확인도 같은 경계를 사용한다.
- 좌표/원본 주소/점포/비밀값은 로그·오류·문서 예시에 남기지 않는다. FE 코드/문서/이슈/PR은 수정하지 않으며 기존 API 계약 변경도 없어 FE 요청 보고서가 필요한 단계는 아니다.

## 5. 검증·완료

일반: 유한 좌표/범위/추가 키·UUID, 세부/특구 단독/중첩/모호함/밖, 순서 고정, 중복·잘못된 유형·모순 상태·primary/목록 불변식, provenance 날짜와 unverified.

격리 PostGIS: 외곽선/안/밖, hole 내부와 경계, multipart, 세부+특구/세부 중첩/특구 단독중첩, 499/500/501m 폴리곤 최단거리, 반경이 hole 안에서 경계에 닿는 경우, 명시 UUID 격리·없는 UUID 안전 실패·날짜 미확인 유지·read-only 호출. 기존 파괴적 suite는 임시 DB만 사용한다.

실제 개발 DB: 지정 UUID 조회·독립 ST_Covers/ST_Distance SQL 대조(내부점/외곽선/밖/중첩 표본), 모델차이0·head0009·기존14테이블 hash/건수 보존. 실제 데이터에 없는 합성 경계 사례를 실데이터 검증으로 주장하지 않는다. 전체 일반/격리 PostGIS·ruff/format·mypy·비밀값 검사·CI/CodeQL을 수행한다.

커밋: 설계/Claude 검토 → 모델/순수 선택+일반 테스트 → DB공간 조회+격리 테스트 → 실제 검증/작업계획/README. PR제목 `feat: 상권 공간 판정과 중첩 후보 처리 구현`, close #62, develop 정상 Squash 자동 병합. BE-23 전체 Risk/API·공식 분기/업종 매칭·브랜드 승인·FE 통합은 후속으로 남긴다.

## 6. Claude 검토 요청

이 MD만 Read/Edit로 직접 수정하고 판단·이유·보류를 기록한다. 다른 파일/코드/Git/DB/네트워크/.env 접근 금지. 원천 적용일 미확인 상태에서 공간 판정만 제공하는 것이 정직한지, 중첩 규칙/관광특구 단독/geometry 경계/거리/명시 버전/결과 불변식/후속 연결의 허점을 검토한다. 코드/실제 DB를 읽지 않은 한계를 남긴다. Codex가 원본/코드/DB를 대조해 최종 확정한다.

## 7. Claude 검토 결과 (2026-11-12)

### 7-0. 검토 범위와 한계

- 이 MD 한 파일만 Read/Edit했다. 코드·스키마·마이그레이션·실제 DB·원천 파일·API v1.2·작업계획 문서는 읽지 않았다. 아래의 "기존 모델에 X가 있다/없다"는 모두 **가정**이며 Codex가 대조해 확정해야 한다.
- 구현·테스트·SQL 실행 결과를 확인한 것이 아니다. 어떤 항목도 "검증됨"으로 해석하지 않는다.
- 판정 표기: **수용**(설계 그대로 타당), **보정**(본문 수정 권고, 이유 포함), **보류**(Codex 대조 필요).

### 7-1. 적용일 미확인 상태에서 공간 판정만 제공하는 것의 정직성 — 수용(조건부)

- 공간 판정과 시점 적용성을 분리하고 `applicability=unverified`를 상수로 두는 것은 정직하다. 날짜 대체(source_file_date/loaded_at)와 최신 UUID 자동 선택을 금지한 점도 타당하다.
- **보정 1 (타입으로 강제)**: "상수"를 문서 약속이 아니라 타입으로 강제한다. `applicability: Literal["unverified"]`, `reason: Literal["boundary_period_not_verified"]`로 두어, 후속 코드가 실수로 `verified`를 넣으면 모델 검증에서 실패하게 한다. 이유: 이 값은 후속 Risk의 공식 지표 활성화 여부를 가르는 유일한 신호이므로 자유 문자열이면 우회가 쉽다. 나중에 검증 경로가 생기면 그때 별도 rule_version과 함께 Literal을 넓힌다.
- **보정 2 (소비 측 계약 명시)**: 후속 Risk가 지켜야 할 규칙을 이 설계에 한 줄로 고정한다. "`applicability != verified`이면 primary/candidates를 상권 단위 공식 통계(추정매출·상권변화 유형 등) 조회 키로 사용하지 않는다. 표시용 라벨로만 쓴다." 이유: §1은 "활성화 근거가 아니다"라고만 하여 금지 범위가 해석에 따라 달라진다. 특히 primary가 단일 코드라서 조인 키로 쓰고 싶은 유혹이 가장 크다.

### 7-2. 중첩 규칙과 관광특구 — 대체로 수용, 보정 3건

- §3-2~4의 "세부 유형 간 우열 없음, 다수면 ambiguous" 및 "세부가 있으면 관광특구는 also_in"은 §1의 근거(세부 우선/관광특구 병기)와 일치한다. 면적·코드순 임의 선택 금지도 타당하다.
- **보정 3 (유형 코드 allowlist, fail-closed)**: §3-2는 "관광특구 이외 A/D/R"이라고만 쓰고 관광특구 코드를 명시하지 않았다. "관광특구가 아니면 세부"라는 여집합 규칙으로 구현하면, 원천에 알 수 없는 유형 코드나 null이 들어왔을 때 조용히 세부로 승격된다. 권고: 세부={A,D,R}, 관광특구={관광특구 코드(서울 원천 관례상 U로 추정, **보류**: Codex 원천 대조)}를 명시 allowlist로 두고, 그 밖의 값은 INTERNAL_ERROR(원문 비노출)로 처리한다. §5의 "잘못된 유형" 테스트가 이 경로를 검증하게 한다.
- **보정 4 (같은 market_code 다중 행)**: 한 버전 안에서 같은 market_code가 여러 행(멀티파트를 행으로 쪼개 적재했거나 원천 중복)이면, 행 기준으로 세면 동일 상권 하나가 "세부 여러 개 → ambiguous"로 오판된다. 권고: 후보 집합은 **market_code 기준으로 중복 제거한 뒤** 개수를 센다. 다만 같은 코드에 name/type이 서로 다르면 이는 원천 손상이므로 INTERNAL_ERROR. 적재 단계에서 (version_id, market_code) 유일성이 이미 보장되는지는 **보류**(Codex가 모델/제약 확인).
- **보정 5 (관광특구 다수 + 세부 1개 조합 명시)**: §3-3은 "관광특구는 also_in"이라 했으므로 세부 1개 + 관광특구 여러 개면 in_market·also_in=특구 전부가 되어야 한다. 이 조합을 §5 테스트 목록에 명시 추가한다(현재 "세부+특구"는 특구 1개 사례로 읽힐 수 있음).

### 7-3. 결과 불변식 — 보정(현재 정의가 불완전)

§2는 "모호한데 primary를 붙이지 않는다"만 명시한다. 상태별 전체 불변식을 모델 validator로 고정할 것을 권고한다.

| spatial_status | primary | candidates | also_in | nearby_markets |
|---|---|---|---|---|
| in_market (세부 1) | 세부 | `[]` | 포함 관광특구 전부(0개 이상) | `[]` |
| in_market (특구 1, 세부 0) | 특구 | `[]` | `[]` | `[]` |
| ambiguous (세부 ≥2) | null | 세부 ≥2 | 포함 관광특구 전부 | `[]` |
| ambiguous (세부 0, 특구 ≥2) | null | 특구 ≥2 | `[]` | `[]` |
| outside | null | `[]` | `[]` | 반경 교차 상권(0개 이상) |

- 추가 불변식: primary·candidates·also_in·nearby 사이 market_code 교집합 없음; candidates의 유형은 전부 세부이거나 전부 관광특구(혼합 금지); also_in은 관광특구만; primary가 관광특구면 also_in=[].
- 이유: in_market일 때 candidates를 `[]`로 둘지 `[primary]`로 둘지가 문서에 없어 구현·테스트·후속 소비자 해석이 갈린다. `[]`를 권고한다(candidates는 "선택 못 한 후보"라는 의미로만 사용).
- **nearby_markets 항목 형태 보류**: 현재 MarketRef(code/name/type)만 있고 거리 필드가 없다. 거리 없이 market_code 정렬로 주는 것은 "가장 가까운 상권 선택"을 유도하지 않는다는 §3-5 취지와 맞으므로 **수용**한다. 단 FE/후속이 거리를 요구하게 되면 반올림 정책과 함께 별도 계약 변경으로 다룬다고 명시한다.

### 7-4. geometry 경계·좌표 — 보정 3건

- **보정 6 (축 순서·SRID 명시)**: 점 생성은 `ST_SetSRID(ST_MakePoint(lng, lat), 4326)`처럼 **경도-위도 순서**임을 본문에 명시하고, 저장 geometry의 SRID가 4326인지 Codex가 확인한다(**보류**). 이유: lat/lng 뒤바뀜은 서울 좌표에서 오류 없이 "outside"를 반환하므로 테스트 없이는 발견되지 않는다. §5 일반 테스트에 "lat/lng 교환 시 다른 결과" 사례 추가를 권고한다.
- **보정 7 (포함=planar geometry, 거리=geography 혼용의 경계 불일치)**: §3-1은 geometry(평면, degree 좌표)로 `ST_Covers`, §3-5는 geography(측지선)로 거리를 잰다. 긴 변 근처에서는 평면 직선 변과 측지선 변이 미세하게 달라, 평면 기준 outside인데 geography 거리 ≈0인 점이 있을 수 있다. 상권 크기에서 실질 영향은 매우 작으므로 혼용 자체는 수용하되, (a) 문서에 이 차이를 인정하고, (b) outside + nearby 거리 0이 나와도 모순으로 판정해 오류를 내지 않도록 불변식을 "거리 ≥ 0"으로만 둔다. 포함 판정을 geography `ST_Covers`로 바꾸는 것은 인덱스·성능 영향이 있어 이번 범위에서는 권고하지 않는다.
- **보정 8 (유효하지 않은 geometry)**: `ST_Covers`는 자기교차 등 invalid 폴리곤에서 결과가 정의되지 않는다. 적재 단계에서 `ST_IsValid` 검사가 되어 있는지 **보류**(Codex 확인). 안 되어 있다면 이번 PR에서는 판정 시 수정(`ST_MakeValid`)하지 말고, 실제 DB 검증 단계에서 대상 버전의 invalid 건수 0을 확인·기록하는 것으로 충분하다(판정 중 형상 변형은 provenance와 불일치를 만든다).
- 경계 포함 테스트 주의: "외곽선 위의 점"은 부동소수점 때문에 실데이터 임의 좌표로는 재현이 불안정하다. 합성 폴리곤의 꼭짓점/축 정렬 변 위 점으로만 검증하고, 실제 DB 대조의 "외곽선 표본"은 꼭짓점 좌표를 사용하도록 한정할 것을 권고한다.

### 7-5. 거리 판정 — 수용, 테스트 보정 1건

- polygon geography와 point geography 간 `ST_DWithin` 후 `ST_Distance <= radius`로 재확인하고 중심점/degree buffer를 금지한 것은 타당하다. hole 안의 점은 outside가 되고 거리는 hole 링까지로 계산되므로 §5의 "반경이 hole 안에서 경계에 닿는 경우"는 올바른 핵심 사례다.
- `ST_DWithin`과 `ST_Distance` 모두 geography 기본값(spheroid)을 쓰도록 **같은 use_spheroid 설정**을 명시한다. 한쪽만 sphere이면 경계 근처에서 1차 필터와 재확인이 어긋난다.
- **보정 9 (499/500/501m 테스트)**: 측지 거리 정확히 500.000m인 합성 형상을 만들기 어렵고 spheroid 계산 오차로 테스트가 flaky해질 수 있다. 권고: 499m/501m 사례는 "명확히 안/밖"으로 단언하고, 정확히 500m 사례는 형상을 만든 뒤 DB가 계산한 `ST_Distance` 값을 먼저 확인하여 `<= 500`이면 포함됨을 단언하는 방식(값 자체를 하드코딩하지 않음)으로 바꾼다.
- radius는 nearby 계산에만 쓰인다. in_market/ambiguous일 때 radius가 결과에 영향을 주지 않음을 테스트에 포함한다.

### 7-6. 명시 버전 — 보정 2건

- **보정 10 (빈 버전의 무음 outside 방지)**: version_id 행은 있으나 해당 버전의 경계 행이 0건이면, 현재 규칙상 모든 좌표가 정상적인 `outside`로 반환된다. 이는 "상권 밖"이라는 거짓 사실이 된다. 권고: 버전 존재 확인 시 경계 행 수 ≥1도 확인하고, 0이면 INTERNAL_ERROR(fallback 없음). 버전에 적재 완료/실패 같은 상태 컬럼이 있다면 완료 상태만 허용(**보류**: 컬럼 존재 여부 Codex 확인).
- **보정 11 (조회 전 구간 버전 필터)**: 포함 조회와 nearby 조회 **둘 다** version_id 조건을 걸어야 한다. §3-5에 "같은 버전"이 있으나 §5 격리 테스트에 "다른 버전에만 있는 가까운 상권이 nearby에 나오지 않음" 사례를 명시 추가한다.

### 7-7. 입력 검증·비노출 — 보정 1건

- **보정 12 (DB 예외 메시지의 좌표 유출)**: repr에서 좌표를 감춰도, SQLAlchemy/psycopg 예외 문자열에는 바인드 파라미터(lat/lng)가 포함될 수 있다. 서비스에서 DB 예외를 잡아 원문(`str(exc)`)·`exc.params`를 로그/응답에 넣지 않고 원문 없는 INTERNAL_ERROR로 바꾸며, 체인(`raise ... from`)도 로깅 경로에 노출되지 않는지 확인할 것을 권고한다.
- 좌표 범위: "유한 WGS84 범위"만으로는 서울 밖 좌표가 정상 `outside`(nearby 없음)로 반환된다. 이번 내부 계약에서는 수용하되, 후속 공개 API에서는 "서비스 지역 밖"과 "상권 밖"을 구분해야 한다는 점을 후속 항목으로 남긴다.

### 7-8. 후속 연결 시 남는 위험

1. 후속 Risk가 primary를 공식 분기 통계 조인 키로 쓰는 것 — 보정 2로 차단 문구 고정.
2. ambiguous 결과를 후속에서 "첫 번째 후보"로 축약하는 것 — 후속 설계에서 ambiguous는 공식 지표 비활성 또는 전체 후보 병기만 허용한다고 명시해야 한다.
3. 경계 버전과 통계 분기 버전의 호환 — 이번 범위 밖. boundary_as_of가 채워져도 자동 호환으로 보지 않는다는 §1 문장을 후속 설계로 그대로 승계해야 한다.
4. 인허가 반경 집계(BE-22)와 nearby_markets는 둘 다 반경을 쓰지만 의미가 다르다(점포 반경 vs 폴리곤 교차). 동일 radius 값을 공유하더라도 결과를 합쳐 하나의 "상권 지표"로 표기하지 않는다.

### 7-9. 요약

- 수용: 공간/적용성 분리, 최신 버전 fallback 금지, 세부 우선·관광특구 병기·모호 시 primary 없음, polygon-point geography 거리, 읽기 전용 Session 사용, 라우터/공개 API 미변경.
- 본문 반영 권고(보정 1~12): applicability Literal 강제, 소비 측 금지 문구, 유형 allowlist fail-closed, market_code 중복 제거, 상태별 불변식 표, 축 순서·SRID, planar/geography 차이 인정, invalid geometry 확인, 500m 테스트 방식, 빈 버전 오류, 버전 필터 테스트, DB 예외 원문 비노출.
- Codex 보류 확인: 관광특구 유형 코드 실제 값, (version_id, market_code) 유일성, SRID 4326, ST_IsValid 적재 검사 여부, 버전 상태 컬럼 존재 여부.

## 8. Codex 최종 점검

Claude 실제 수정 diff 전체와 결과 JSON(is_error=false, 3 turns, permission_denials=[])을 읽었다. Literal 상태 고정·소비 측 공식 조인 금지·유형 allowlist·상태별 불변식·축 순서·동일 spheroid·시점/공간 차이·버전 누락/빈 버전·DB 오류 비노출을 채택한다. 실제 모델은 관광특구 U, (version_id,market_code) 복합 PK, MULTIPOLYGON SRID4326, 유효/비어있지 않은 도형 CHECK를 이미 보장한다. 버전 완료 상태 컬럼은 없고 연간 원자 적재 후 row_count가 저장된다. 조회는 실제 행 수가 row_count와 같은지도 확인해 빈/부분 손상을 정상 outside로 숨기지 않는다.

중복 제거 제안은 조정한다. 한 상권의 multipart는 이미 단일 MULTIPOLYGON 행이고 중복 행은 복합 PK상 허용되지 않는다. 순수 선택 함수에서도 중복을 조용히 제거하면 손상을 숨기므로 같은 코드 중복은 동일 내용이어도 안전하게 실패한다. 적용성은 Literal unverified로 고정하며 primary/candidates를 공식 통계 조인 근거로 사용하지 않는다. geometry 포함과 geography 거리의 경계 차이는 허용하고 outside의 근처 거리가0이어도 모순으로 보지 않는다. 정확500m는 독립 DB 실측과 비교하되 499/501m는 확실한 경계 양쪽을 검사한다. 기존 좌표 정책과 달리 서울 밖을 오류로 바꾸는 새 정책은 이번 내부 서비스에서 도입하지 않는다.

## 9. 구현·검증 결과 (2026-11-12)

- `BoundaryQuery`·`MarketRef`·상태별 결과·출처 모델과 `classify_markets`·`judge_market`를 구현했다. 명시 UUID와 경계 행 수를 검사하고 ST_Covers 포함/경계 처리, 관광특구 별도 표시, 동순위 모호함, 밖에서만 spheroid 최단거리 기반 교차 목록을 반환한다. 순서는 코드 기준이며 하나를 임의 선택하지 않는다. DB/모델 실패는 원문과 예외 context가 없는 안전한 INTERNAL_ERROR다.
- 서비스는 호출자가 제공하는 읽기 전용 일관된 Session만 사용한다. 생성/commit/rollback/세션 설정 변경을 하지 않는다. provenance의 applicability는 unverified로 고정하고 경계 적용일·통계 분기 매칭을 주장하지 않는다. 기존 API·라우터/main·DB 모델/migration·의존성·원본·Docker/.env·FE 변경은 없다.
- 새 일반 **33개**, 새 PostGIS **4개**를 포함해 전체 일반 **957개**, 격리 통합 **103개** 통과. ruff/format **233 files**, mypy app/etl/migrations **118 files** 통과. 기존 Starlette/httpx deprecation 경고 1건은 그대로다.
- 합성 PostGIS는 외곽선·꼭짓점·hole 경계 포함/hole 내부 제외·multipart, 세부 1개+특구 여러 개, 세부/특구 동순위 중첩, 반경 무관 포함 결과, 다른 버전 후보 배제, 499/500/500.001/501m 최단거리, 빈/부분/없는 버전 안전 실패와 READ ONLY 호출을 확인했다. 정확500m 후보는 독립 ST_Distance의 판정과 대조했다. 일반 모델 검증은 상태/목록 불변식·유형·중복·비유한 좌표·비노출·적용성 고정을 확인했다.
- 실제 경계는 버전1개·적용일 확인0개, 골목1,090·발달249·전통시장305·관광특구6개다. 각 유형5건의 내부점/꼭짓점, 실제 세부 상권 교차3건, 추가2점에 300/500/1000m를 적용한 **135조합**을 독립 SQL(ST_Intersects 포함·직접 ST_Distance 거리)과 대조했다. 공간 상태는 in_market99·ambiguous30·outside6이며 모두 일치했다. 모델 차이0·무효/빈 도형/SRID 오류0·head0009도 확인했다. 이는 지정 버전의 공간 검증이며 현재/과거 적용성 검증이 아니다.
- 기존 health·data-range·activity의 실제 앱/개발 DB 조회는 최종 모두200이고 공개 Risk 경로는 추가하지 않았다. 최초 검증 실행은 기존 경로 검사 구간의 assertion 1회가 실패했다. 경로별 상태를 기록하지 않아 어느 요청인지 확정할 수 없으며, 개별 재확인과 전체 도구 재실행에서는 모두200이었다. 원인/timeout이라고 단정하거나 콜드 캐시·동시 부하 SLA를 통과했다고 주장하지 않는다. 검증 도구의 오래된 비편집 설치본 import 문제도 저장소 루트 명시 후 바로잡았다.
- 실제 개발 DB는 조회만 했고 기존14개 테이블 전체 행·geometry hash/건수가 이전 검증 기준과 동일함을 확인했다. 파괴적 회귀는 별도 임시 PostGIS에서만 실행했다. 검증 도구·실데이터·원본·키는 커밋하지 않는다.
- 후속은 이 결과를 소비할 Risk의 상태/후보 계약·공식 분기/업종 호환 검증과 참고지표 분모/생존 코호트 구현이다. 이번 내부 기반을 BE-23 전체 API·BE-24/25/26·브랜드 승인·FE 통합 완료로 표시하지 않는다. 공개 계약이 바뀌는 후속 단계에서 BE측 FE 변경 요청서를 작성한다.
