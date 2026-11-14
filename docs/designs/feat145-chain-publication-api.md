# 브랜드 판정 공개 세대와 BE v2 조회 API

- 이슈 #145, 기준 develop93766d5. #138 설계·#143 기반의 다음 단계다. 사용자 요청: 필요한 BE 구현·테스트 진행, FE 저장소 수정 금지.
- 포함: 가맹·직영·소규모 체인의 브랜드 소속. 판정은 estimated/unknown/conflict이며 실제 가맹/직영·비체인·역사 소속 확정 자료는 없다.
- 변경: migration0012, 별도 불변 publication·브랜드 표시·점포 판정·active state, 명시 publish/activate CLI, `/api/v2` 상태/주변/과거/이력/활동/Risk. v1 가맹 의미·stores 원본·FE는 유지한다. v2 AI는 별도 문맥 검증 전 공개하지 않는다.

## 1. 데이터 모델

### 1.1 원천 변경 감지 보강 제안 (1차 검수 후)

배치 집합/D 비교만으로는 같은 batch_id·updated_at을 유지한 다른 점포 DML을 감지할 수 없다. #143의 `local_counts`는 주소 키별 **다른 인허가 기록**의 유무에 의존하므로 현재 점포 FIELDS 일치만으로 소진공 근거 유효성을 유지하면 잘못된 양성이 남을 수 있다.

이를 해결하기 위해 다섯 번째 소형 테이블 `chain_source_state(id=1,revision bigint NOT NULL,CHECK(id=1),CHECK(revision>=0))`와 stores의 AFTER STATEMENT INSERT/UPDATE/DELETE/TRUNCATE 변경번호 trigger(FOR EACH STATEMENT, TRUNCATE는 statement만 지원)를 채택한다. 기존 stores 업무 열/원본 값은 바꾸지 않고 별도 revision만 단조 증가시킨다. 동일값 재쓰기·0행 DML·cascade TRUNCATE·COPY도 번호를 올리는 보수적 무효화이며 원천 갱신 후 재공개(또는 아래 revision 갱신)가 필요하다.

**비교한 대안(2차 검수):** 배치/D만 비교는 같은 batch_id·updated_at의 다른 행 DML을 놓친다(차단 결함). 매 API 전체 지원 범위 재해시는 RR 일관성은 맞지만 요청마다 약 35만 행 스캔으로 SQL10초/Free 예산과 맞지 않는다. statement trigger counter는 revision 행 UPDATE가 stores DML과 같은 트랜잭션에서 커밋되므로 API RR snapshot이 읽는 revision과 stores 내용이 항상 같은 시점이다. sequence(nextval)는 비트랜잭션이라 rollback·미커밋 값이 snapshot과 어긋나므로 쓰지 않는다. 배치 집합/D는 보조 표시 메타데이터로만 남긴다.

**revision 고정 위치(멱등 보완):** revision을 불변 publication 지문에 넣으면 0행 DML만으로도 같은 내용의 세대가 새로 생겨 멱등이 깨지고, 재활성화한 오래된 세대는 영구 drift가 된다. 따라서 `publication_fingerprint`는 내용 기반(§2)으로 두고, 소진공 근거의 유효 revision은 **`chain_publication_state.validated_source_revision`**에 둔다. publish/activate/rollback은 stores SHARE 아래에서 현재 지원 범위 입력 streaming hash를 재계산해 대상 세대의 저장 입력 hash와 같을 때만 현재 revision을 기록하고, 다르면 activate는 거절한다(publish는 새 세대 생성). 같은 fingerprint 재실행은 내용 no-op이되 state의 revision 갱신만 수행할 수 있다. API는 같은 RR snapshot에서 state와 chain_source_state를 읽어 다르면 `source_drift=true`·소진공 대조 근거만 unknown이다. 이름 근거는 행 단위 NULL-safe 비교만 적용한다. 입력 hash 범위는 #143 `local_counts`가 읽는 행 집합과 정확히 같아야 하며 테스트로 확인한다.

**동시 writer 영향(필수 조건):** 모든 stores 쓰기 트랜잭션이 단일 revision 행을 갱신하므로 서로 다른 stores writer 트랜잭션은 첫 DML 문장 이후 커밋까지 직렬화된다. READ COMMITTED writer는 대기하지만 REPEATABLE READ writer는 상대 커밋 후 40001이 되고, 서로 다른 행 잠금을 교차로 잡은 두 writer는 revision 행 대기로 새 deadlock이 될 수 있다. 기존 인허가 ETL·floor_backfill·maintenance 외에 stores writer가 없는지 구현 시 코드로 열거하고, 각 writer의 격리수준을 확인한다. 동시 실행은 지원하지 않으며(기존 writer advisory lock/운영 절차로 순차화), 40001/deadlock은 기존 실패·전체 rollback 경로로만 끝나야 함을 격리 테스트한다. 단일 writer 대량 적재의 statement 수 비례 UPDATE·WAL 비용도 측정한다.

**잠금 순서:** publisher는 §2대로 state EXCLUSIVE→stores/provenance/legacy SHARE를 잡고 chain_source_state는 **읽기만** 한다(stores SHARE가 유일한 갱신 경로인 trigger를 막으므로 별도 잠금 불필요). writer는 stores 행→revision 행 순서이며 publisher와 역순 획득이 없다.

**권한·무결성:** 함수는 `SECURITY DEFINER`, `SET search_path=pg_catalog,pg_temp`, 스키마 한정 정적 UPDATE 1문장만 수행하고 소유자는 migration 실행 역할, PUBLIC EXECUTE는 회수한다. 실행 역할에 별도 DML 권한을 주지 않는다. API 조회 역할에는 chain_source_state·chain 테이블 SELECT만 필요하며 운영 DB의 grant는 배포 범위 밖 별도 작업이다. `ALTER TABLE ... DISABLE TRIGGER`·`session_replication_role=replica`는 감지를 우회한다. **구현 확정(3차 검수):** migration은 `ENABLE ALWAYS TRIGGER`로 replica 역할에서도 발화시키고, publisher와 모든 v2 요청은 `tgenabled='A'`·`tgtype=60`(AFTER STATEMENT INSERT/UPDATE/DELETE/TRUNCATE)·함수 OID/SECURITY DEFINER/search_path 고정값을 확인한다. 불일치면 publisher 거절, v2는 pending 여부와 무관하게 **fail-closed 500(no-store)**이다(소진공 근거만 unknown으로 낮추는 원안보다 보수적). pg_dump/restore는 revision 행과 stores를 함께 복원하고 trigger를 post-data에서 만들므로 일관되나, 복원 후 첫 publish/activate에서 hash 재확인으로 revision을 다시 검증한다.

**downgrade:** chain_publications 등에 자료가 있으면 거절한다. 자료가 없으면 trigger→function→chain_source_state 순서로 제거하며 counter 값 자체는 자료로 보지 않는다.

이것은 #138의 ‘trigger 미추가’ 제안을 변경하는 명시적 설계 보강이며 사용자 재승인이 필요한 별도 제품 정책은 아니다. v1 응답·stores 업무 값은 바뀌지 않지만 stores에 DDL 객체가 추가되므로 head0012 migration에 포함하고 v1 회귀 테스트로 확인한다.

5개 신규 테이블(아래 4개+chain_source_state)과 trigger/function을 ORM/migration에 명시한다. 기존 `brands`와 `stores.brand_id` namespace를 재사용하지 않는다.

| 테이블 | 키·내용 |
|---|---|
| chain_publications | generation UUID PK, 불변 입력/계획/registry 지문, 규칙/정책, source manifest, 원천 행수·판정수·집계, 생성 시각 |
| chain_publication_brands | generation+canonical UUID PK, 표시명과 원천 namespace/근거. 이름을 세대에 고정해 과거 표시가 바뀌지 않음 |
| store_chain_classifications | generation+source+license PK, estimated/conflict, brand UUID nullable, 사유, semas ref, 입력 hash와 판정 당시 원천 비교 열 |
| chain_publication_state | id1 singleton, generation FK, validated_source_revision, 변경 시각. 완성된 세대만 가리킴 |
| chain_source_state | id1 singleton, revision. stores statement trigger만 갱신(§1.1) |

희소 projection으로 양성/충돌만 저장하고 행 부재는 unknown이다. approved source link/동일명 충돌을 #143 규칙으로 보존한다. 각 판정의 입력은 #143 FIELDS(source/license/name/category/subcategory/외부분류/두 주소/building_key/floor_unit/open·close/status/date_flag/is_temporary)와 동일하다. SQL은 동일 source/license와 모든 비교 열의 NULL-safe 동등을 확인한다. 이름/주소/날짜 등이 달라지면 해당 증거는 stale→unknown이다. source 삭제/검토·지원 업종 조건도 기존 공통 코호트로 적용한다. 단일 active 세대의 기록당 판정은 하나라 join으로 점포 수를 늘리지 않는다.

원본 stores 값을 갱신하거나 pgcrypto를 추가하지 않는다. trigger는 §1.1의 revision 전용 1개만 추가한다. downgrade는 신규 테이블에 자료가 있으면 거절한다. 기존 ETL·신규 publisher 로컬 가드는 모두 정확히0012를 확인한다. readiness 기본 head와 테스트 기준은 신규 head로 정합화하며 실제 환경/운영 배포는 코드 병합과 구별한다.

**검수 보완(§6-1~3):**

- 공유 head guard는 기존 migration 관례대로 정확히0012로 올린다(0011/0012 동시 허용 금지). 코드0012를 migration 없는 DB(현재 Render0011 포함)에 배포하면 ready가 실패하므로 배포 전 migration 선행이 조건이다. 배포 자체는 이번 범위 밖이다.
- 제약: state `CHECK(id=1)`, generation FK 삭제 거절(구현은 기본 `NO ACTION`; 세대 삭제 명령이 없어 RESTRICT와 같은 효과), 판정→브랜드는 (generation, brand UUID) 복합 FK, `CHECK(status IN ('estimated','conflict'))`, `CHECK((status='estimated') = (brand_uuid IS NOT NULL))`, basis/reason은 고정 enum CHECK. publication에는 `UNIQUE(publication_fingerprint)`를 둔다.
- **typed stale guard**: `input_sha256`은 Python 직렬화 digest라 SQL에서 재계산할 수 없다. 따라서 무결성/계획 지문 전용이며, 요청 시 판정 유효성은 stores 모델과 **동일 SQL 타입**(varchar/date/numeric/bool)으로 복사한 비교 열 FIELDS 전체의 `IS NOT DISTINCT FROM`만으로 판단한다. 외부 is_franchise/brand_id 변경도 보수적으로 stale이며 이는 공개 한계로 표시한다. 타입 불일치·암묵 cast 비교는 테스트로 거절한다.
- **행 간 의존 증거**: 이름 기반 판정(seed alias/catalog exact)은 세대에 고정된 registry와 자기 행 이름만 의존한다. 소진공 대조 판정은 다른 점포의 주소 키 개수(local_counts)에 의존해 행 guard로 검출할 수 없다. ~~배치 집합/D 비교~~는 같은 배치의 다른 행 DML을 놓치므로 2차 검수에서 대체했다. 요청 시 state.validated_source_revision과 chain_source_state.revision이 다르면(§1.1) `source_drift=true`로 표시하며 **소진공 대조 근거 판정만 unknown(stale)으로 강등**한다. 배치 집합/D는 보조 메타데이터로만 저장한다. 이름 기반 판정은 행 guard 통과 시 유지한다.

## 2. 계획·공개·rollback

기본은 READ ONLY REPEATABLE READ dry-run이다. 저장소 밖 snapshot/검수 registry에서 #143 규칙으로 **현재 DB를 재계산**하고 raw plan JSON을 맹신해 DB에 적재하지 않는다. 모든 지원 원천 입력의 streaming hash(unknown 포함), 판정 계획, registry/소진공 manifest·catalog ref, publication 규칙을 묶어 expected_plan을 만든다.

write는 `--write --expected-plan <hash> --expected-active <UUID|none>`로만 가능하다. 로컬 대상/role/extension/head 가드 뒤 publication state EXCLUSIVE와 stores SHARE lock, 상태 포인터 검사를 수행한다. 원천과 기존 brand 상태의 경합을 통제하고 계획을 다시 계산해 같을 때 한 트랜잭션으로 세대·브랜드 표시·판정과 active 포인터를 공개한다. 실패/부분 insert는 rollback이며 이전 세대/원본을 유지한다. 같은 입력의 generation을 재사용하고 기존 세대의 내용 무결성을 확인한 뒤 no-op 또는 재활성화한다. 허용된 fingerprint 없는 write는 DB를 열기 전에 거절한다.

**잠금 순서(검수 보완 §6-4):** RR 트랜잭션의 snapshot은 첫 SELECT(`SELECT pg_advisory_xact_lock(...)`·가드 조회 포함)에서 고정되므로, 대기 중 고정된 오래된 snapshot으로 포인터를 검사하는 경합을 막기 위해 write 트랜잭션은 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ` 직후 **어떤 SELECT보다 먼저** `LOCK TABLE`만 실행한다: chain_publication_state `EXCLUSIVE`(publisher/activate 상호 직렬화, API ACCESS SHARE 읽기는 허용), stores·store_import_batches(provenance)·기존 brand catalog/brands/match/state 테이블 `SHARE`(ETL·brands.apply 쓰기 차단). lock_timeout 5초·실패 시 고정 오류다. 그 뒤 가드·trigger 활성 확인·state 조회(앞선 EXCLUSIVE 잠금으로 직렬화, 직렬화 오류는 실패로 종료)·`expected-active` 비교·chain_source_state 읽기·재계산·insert·포인터/validated_source_revision 갱신을 같은 snapshot에서 수행한다. stores SHARE는 VACUUM과도 충돌하므로 실행 중 유지보수를 하지 않는다. publisher는 기존 ETL처럼 `validate_local_target`의 로컬 대상만 허용하며 Render/운영 DB 공개는 별도 승인 대상이다.

**지문·멱등:** `publication_fingerprint`=digest(전체 지원 원천 입력 streaming hash(unknown 포함, (source,license) C collation 순) + 판정 계획 + registry + 소진공 manifest/content hash + legacy catalog_version/run ref + RULE/POLICY/publication 규칙 버전). source revision·배치 집합/D는 지문에 넣지 않는다(내용 동일 시 멱등 유지, §1.1). `--expected-plan`은 이 값과 정확히 일치해야 한다. 같은 fingerprint가 이미 있으면 저장 행을 정렬 재직렬화한 content hash와 행수를 검증하고, active이면 내용 no-op(현재 revision 기록만 갱신), 아니면 expected-active 일치 시 포인터와 revision만 갱신한다. 판정 행이0이어도 세대는 만들 수 있으나 status에서 그대로 표시한다.

**지원 규칙:** API 코드는 지원하는 publication rule 버전 집합을 상수로 가진다. activate/rollback 대상과 요청 시 active 세대의 규칙이 집합 밖이면 activate는 거절, API는 500(no-store)이다.

별도 activate는 저장된 generation·expected-active와 원래 registry/소진공 snapshot을 받아 전체 내용까지 재검증한 뒤 같은 입력의 포인터를 재활성화한다. 같은 잠금 순서로 현재 입력 hash가 대상 세대와 같을 때만 현재 revision을 기록하고 다르면 거절한다(§1.1). 오래된 판정도 현재 원천 비교가 통과한 기록만 읽는다. 즉시 포인터 rollback과 원천 자료 자체의 복구는 다르다. 자동 세대 삭제는 이번에 하지 않으며 row/세대/DB 용량을 측정해 무제한 성장·Free 한도 초과를 막는다. 필요하면 보존 세대 상한에서 실패하고 명시 운영 정리 대상으로 남긴다.

**구현 확정·한계(3차 검수):** 상한은 `MAX_GENERATIONS=3`과 세 publication 테이블 합 128MiB이며 초과 시 insert 후 전체 rollback이다. 정리(prune)·비활성화(pending 복귀) 명령은 없으므로 월 1회 재공개를 가정하면 4번째 새 세대부터 `generation_capacity`로 막힌다. activate는 현재 DB·코드 registry·지정 snapshot으로 재계산한 fingerprint가 대상 generation과 같아야만 통과하므로, 원천이 바뀐 뒤 과거 세대로 되돌리는 "rollback"은 실제로 불가하고 같은 입력 재활성화(=재공개 no-op)와 같다. 이 두 점은 공개 한계로 기록하며, 잠금 아래 보존 세대 정리와 pending 복귀 명령은 운영 갱신 전 후속 과제다. activate는 계획을 두 번 계산해(검증+apply) stores SHARE 보유 시간이 publish의 약 2배다.

publisher는 현재 raw인허가/연락처/키를 stdout이나 검수 입력에 보내지 않는다. 증거 테이블의 주소/명칭은 기존 인허가 사본으로 DB 내부에만 두며 공개 API는 기존 허용 점포 필드와 브랜드 표시/사유만 반환한다. API 중 수집/판별/쓰기/외부HTTP는 없다.

## 3. v2 계약

공간 공통 파라미터(lat/lng/category/sub_category/radius/as_of/area/include_unknown_area)는 v1과 동일한 검증/산식을 재사용한다. 새 파라미터는 다음이다.

- `brand_scope=all|chain|non_chain`, 기본all
- `brand_unknown=include|exclude`, 기본include
- `brand_evidence=include_estimates|confirmed_only`, 기본include_estimates
- `brand_time_basis=observed_record`, `operation_type=any`만 초기 지원. 다른 값은 기능 미지원422다.

legacy `franchise/include_unknown_franchise/include_unknown`는 v2에서 명시 거절한다. v1은 기존 엄격 파서로 새 파라미터를 거절한다. chain만 볼 때 unknown=exclude를 명시한다.

**검수 보완(§6-5):** v1의 `franchise=franchise`+기본 unknown 포함 혼동을 반복하지 않도록 `brand_scope≠all`이면 `brand_unknown`을 **필수**로 하고 생략 시 DB 접속 전 422다. 같은 키 반복·대소문자 변형·빈 값도 422다. v2 query 모델은 NearbyQuery를 상속하지 않는 별도 strict 모델(extra forbid)로 만든다.

**유효 분류(SQL 3값 논리 방지):** 판정 테이블 LEFT JOIN(active 세대·source·license) 뒤 하나의 `CASE` 식으로 각 기록의 effective class를 E/C/N/U로 계산하고 필터는 `effective IN (...)`만 쓴다. NULL 비교가 행을 탈락시키지 않게 한다.

- E: status=estimated ∧ 행 guard 통과 ∧ (basis≠semas 또는 source_drift=false) ∧ evidence=include_estimates
- U: 판정 행 없음 ∪ conflict ∪ stale ∪ drift로 강등 ∪ confirmed_only에서의 E ∪ active 세대 없음
- C/N: 현재 생성 경로 없음(항상0)

행의 표시 status는 원래 판정(estimated/conflict/unknown)과 stale/drift 사유를 보존하고 필터 class와 혼동하지 않는다. 표의 "미허용 E"는 위 U 강등 항목을 뜻한다.

| scope | unknown 제외 | unknown 포함 |
|---|---|---|
| all | 허용된 E + 향후 C/N | 모든 기록 |
| chain | 허용된 E + 향후 C | 허용된 E + 미확인/충돌/미허용 E |
| non_chain | 향후 N(현재0) | 미확인/충돌/미허용 E |

confirmed_only는 현재 E를 필터상 미확인으로 취급하며 원래 상태는 덮어쓰지 않는다. C/N 생성 경로 미활성도 meta/capabilities에 명시한다. 행의 brand는 `{status,brand_key,name,basis,reference_year,reference_month,time_basis}`, operation은 unknown이다. v1 franchise 필드를 chain 의미로 재사용하지 않는다.

공개 상태는 availability pending/ready(구현 값 `pending|estimate`), observed_record 한계, 부분 coverage, 세대 UUID/규칙 버전/published_at과 source 기준(catalog_year·semas_month·observed_at)을 제공한다. fingerprint·plan/store/registry hash와 legacy catalog/run id는 공개하지 않는다(4차 검수 정합화). active 없음은 자료 준비 안 됨이며 엄격 chain0건을 실제 체인 부재로 설명하지 않는다. state 손상/DB 오류는500이다. generation은 데이터 snapshot pinning 토큰이 아니며 여러 HTTP 응답 세대가 다르면 FE는 재조회한다.

## 4. 엔드포인트와 일관성

| 경로 | 동작 |
|---|---|
| GET /api/v2/brands/status | 상태·capabilities·출처·publication 기준 집계. 현재 영업 점포 전수 숫자로 부르지 않음 |
| GET /api/v2/stores/nearby | 기존 거리/시점/면적·업종 코호트에 같은 brand SQL 적용. typed 브랜드 행 반환 |
| GET /api/v2/stores/snapshot | 같은 필터의 시점 영업 집합·최신 상태 분해, N=배열/분해합 |
| GET /api/v2/stores/history | 기존 지원 업종·이름 제외 이력 전체 보존, 브랜드 인자422. 행별 브랜드 근거만 추가 |
| GET /api/v2/market/activity | 같은 필터로 개폐업/평균/2010년 이상 연도 추이. 현재명부를 실제 역사 소속으로 표시 금지 |
| GET /api/v2/risk | 동일 필터를 반경·서울 비교·좌표 미확보에 적용. 기존 참고 산식/표본/분모 유지 |

meta/data-range는 기존 category 기반 계약 유지(브랜드 인자 거절). v2 AI는 현재 v1 strict context로 우회하거나 필터가 빠진 결과를 모델에 넘기지 않는다. 공개 인터프리트 경로는 아직 만들지 않는다.

별도 Selection 객체를 동일 READ ONLY RR 세션에서 한 번 읽고 공통 attribute predicate에 명시 전달한다. v1 호출은 Selection=None으로 동일 코드 경로를 유지한다. v2 Risk 첫 릴리스는 기존 v1 Risk/AI 캐시를 사용하지 않아 key 혼용을 막는다. 캐시 활성화는 새 query/schema/context와 generation 검증을 갖춘 후속이다. 세대가 고정돼도 현재 입력이 바뀌면 stale라는 점을 유지한다.

새 meta의 상태 counts는 공간 API에서 **동일 업종/면적/시점/반경의 active located 기록, 브랜드 필터 적용 전**을 분모로 한다. 좌표 미확보는 기존 서울 비공간 코호트 설명을 유지하고 이 분모에 더하지 않는다. history counts는 전체 반환 이력, status endpoint counts는 publication 원천 집계라 별도로 표시한다.

**검수 보완(§6-6~8):**

- 브랜드 predicate는 `attribute_filters`(면적·필터 계층)에만 들어가며 `temporal_cohort`와 effective_date용 `min(open_date)`에는 넣지 않는다. 따라서 조회 가능 월·as_of 범위는 v1·data-range와 같다. Risk는 이 predicate가 excluded_no_coord·서울 aggregate·반경 aggregate 세 SQL에 모두 들어가 local≤Seoul 불변식이 유지되고, activity의 record_profile·cohort_size도 같은 조건이다.
- counts는 활동/Risk에서도 같은 정의(구현 키 `brand_counts_scope=active_at_as_of_located_before_brand_filter`, history는 `returned_unfiltered_license_history`)로 계산해 cohort_size(폐업 포함)와 섞지 않는다. 버킷은 estimated/conflict/stale_or_drift/unknown이며 합=분모, 필터 후 결과 수와 별도다. 추가 SQL 1문장을 허용한다.
- v1 경로는 Selection=None일 때 chain 테이블을 참조하지 않아야 하며, v1 nearby/snapshot/activity/risk의 컴파일 SQL·응답 JSON이 변경 전과 같음을 테스트한다. v2는 v1 Risk/AI 캐시를 읽거나 쓰지 않는다. 공개 행/로그에 semas_id·비교 열 원문·입력 hash·registry 원문을 넣지 않는다.
- 과거 as_of(snapshot/activity/Risk)에도 현재 세대 판정을 적용한 것이므로 meta에 `brand_time_basis=observed_record`, `historical_membership=not_verified`, catalog reference_year·소진공 reference_month를 함께 표시한다.

## 5. 구현·검증

기존 서비스에는 선택적인 Selection 전달만 추가해 v1 테스트/응답을 보존하고, v2 route/schema/행 장식은 별도 모듈에 둔다. Risk 쿼리 echo에서 legacy 필터를 제거하고 새 정규화 brand 조건을 표시한다. v2 응답에서 v1 franchise 분류 meta/필드를 chain으로 오표시하지 않는다. FE 요청 문서에 URL·예시·오류·세대/분모·AI 미지원과 전환 순서를 제공한다. FE 파일/이슈/PR은 만들지 않는다.

필수 검증: migration forward/빈 DB downgrade·자료 있으면 거절·ORM차이0, write 이전 fingerprint/포인터 가드·재실행·중도 실패·rollback, 두 publisher/activate 동시 실행 직렬화와 대기 후 오래된 snapshot 거절, 같은 배치 다른 행 INSERT/UPDATE/DELETE/TRUNCATE·0행 DML·rollback된 DML별 revision 변화/불변과 소진공 근거만 강등, 동시 stores writer의 대기/40001/deadlock 후 전체 rollback, trigger 비활성 감지, revision 기준 activate/재실행 멱등, scope≠all의 brand_unknown 생략422, v1 컴파일 SQL 동일, 원본 hash 보존, stale 입력별 unknown, 모든 필터 조합·pending·엄격C/N0·미지원/legacy혼합422 DB전 검증, v1 응답 보존, nearby=snapshotN=Risk competitor=activity openCount, 서울/좌표 미확보 동일 필터, 세대 전환중 RR 유지, 현실 데이터의 용량/EXPLAIN/동시 API 측정. 비용/정확도/기간을 추정한 수치를 완료로 쓰지 않는다.

실제 Claude 설계 검수 뒤 구현하고 코드 재검수를 수행한다. 실제 개발 DB/운영 migration 적용은 backup·복원/격리 검증 후 구분해 기록한다. 운영 Render·기존.env·FE를 임의 변경하지 않는다.

## 6. 실제 검수·실행 기록

### 6.1 Claude Code 설계 검수 (2026-11-15)

범위: 이 MD와 사용자가 전달한 소스(etl/chains/compare.py·matching.py, app/services/spatial_stores.py·risk.py·market_activity.py, app/schemas/nearby.py)만 Read로 대조했다. 셸·DB·네트워크·git·다른 파일 수정은 하지 않았고 테스트는 실행하지 않았다(결과 없음).

직접 수정한 결함:

1. head guard "0012도 허용"의 모호성 → 기존 관례대로 정확히0012, 배포 전 migration 선행 조건 명시(§1).
2. `input_sha256`은 Python digest라 SQL 재계산 불가 → 요청 시 guard는 동일 타입 비교 열의 NULL-safe 비교만 사용, 제약 CHECK/FK 명시(§1).
3. 소진공 대조는 `local_counts`로 다른 행에 의존해 행 guard로 stale 검출 불가 → 공개 시 배치 집합/D 저장, drift 시 해당 근거만 unknown 강등(§1).
4. advisory lock SELECT가 RR snapshot을 먼저 고정해 대기 후 오래된 포인터를 볼 수 있음 → SELECT 전 `LOCK TABLE` 순서, state EXCLUSIVE 직렬화, 기존 brand 테이블 SHARE, 로컬 대상 한정(§2). fingerprint 구성·멱등·지원 규칙 집합 명시.
5. scope≠all에서 unknown 기본 포함은 v1 franchise 혼동 반복 → brand_unknown 필수422, 별도 strict 모델(§3).
6. LEFT JOIN NULL로 행 탈락 위험 → 단일 CASE effective class(E/C/N/U)와 표시 status 분리(§3).
7. 브랜드 조건이 temporal_cohort/min(open_date)에 들어가면 조회 월 범위가 바뀜 → attribute_filters에만 적용, Risk 세 SQL 공통(§4).
8. 활동/Risk의 cohort_size(폐업 포함)와 counts 분모 혼동 → 공통 basis·버킷 합 정의, v1 SQL 동일성·캐시/원문 비노출·과거 시점 표시(§4).

확인한 사항: 희소 projection과 PK로 join이 점포 수를 늘리지 않음, v1 응답/stores 원본 보존, v2 AI 미공개, FE/Render/.env 미변경, 실제 가맹/직영/역사 소속 비주장.

판정: **PASS FOR DESIGN/IMPLEMENTATION** (위 수정 반영본 기준, 현재 명시 범위 한정). 구현 후 코드 재검수·실제 테스트 결과는 아래에 별도로 기록한다.

### 6.1.1 Claude Code §1.1 보강 2차 설계 검수 (2026-11-15)

범위: 이 MD만 Read/Edit. 셸·DB·네트워크·git·코드 수정 없음, 테스트 미실행(결과 없음). 설계 전용 판정이며 구현 PASS가 아니다.

판단: 1차 수정 3번(배치/D drift)은 같은 배치 다른 행 DML을 놓치는 결함이 맞다. 대안 중 statement trigger counter가 RR 일관성(커밋 원자성)과 요청 비용을 모두 만족해 채택하고, 전체 재해시는 비용, sequence는 비트랜잭션이라 기각했다.

직접 수정:

1. revision을 불변 지문에 넣으면 0행 DML로 멱등이 깨지고 재활성화 세대가 영구 drift → state.validated_source_revision으로 이동, publish/activate 시 입력 hash 일치 때만 기록(§1.1·§2).
2. 단일 revision 행으로 stores writer 직렬화·RR 40001·새 deadlock 가능성 누락 → writer 열거·격리수준 확인·동시 미지원·rollback 테스트를 필수 조건화.
3. publisher가 source-state를 잠근다는 순서 기술 → 읽기만, writer와 역순 없음.
4. 권한 모호 → SECURITY DEFINER·search_path 고정·PUBLIC EXECUTE 회수, API는 SELECT만, 운영 grant는 범위 밖.
5. DISABLE TRIGGER/replica 우회·dump 복원 → tgenabled 검사와 복원 후 hash 재검증.
6. 4개 테이블·trigger 미추가·배치/D drift 등 구식 문구 정합화, downgrade 순서 명시.

판정: **PASS FOR DESIGN (§1.1 보강, 설계 한정)**. 위 2번 writer 열거·격리 테스트와 입력 hash 범위=local_counts 범위 확인은 구현 진입 조건이며 미충족 시 구현 PASS를 줄 수 없다.

### 6.1.2 Claude Code 구현 단계 검수 (2026-11-15)

범위: 이 MD만 Read/Edit. 사용자가 전달한 소스(models/chain, services/chains·chain_api, schemas/routers chains, etl/chains/publication·compare, migration0012, spatial_stores·risk·market_activity, 두 테스트 파일)와 사용자가 보고한 예비 결과를 자료로 대조했다. 셸·DB·네트워크·git·코드 수정 없음, 테스트 직접 실행 없음.

설계 충족 확인:

- 원천 변경 감지: statement trigger·SECURITY DEFINER·search_path 고정·PUBLIC 회수, ALWAYS 발화, tgtype=60 확인, 0행/rollback DML 테스트. trigger 함수 EXECUTE는 생성 시점에만 검사되므로 ETL 역할 권한 추가 불필요.
- 입력 hash 범위: `local_counts`와 store_sha256이 같은 `_rows`(SOURCE_SUPPORTED_STORES·FIELDS 선택)를 읽어 구조적으로 일치. writer 열거(인허가 RC·floor_backfill RC·maintenance AUTOCOMMIT)와 RR 40001 전체 rollback 테스트 보고됨 → 2차 검수의 구현 진입 조건 충족.
- 원자성·멱등: LOCK(EXCLUSIVE/SHARE)이 첫 snapshot 전에 실행되고, 선행 쿼리가 있으면 `SET TRANSACTION ISOLATION LEVEL`이 오류가 나 오래된 snapshot이 구조적으로 차단됨. uuid5(fingerprint) generation·내용 재검증·expected_active·용량 실패 rollback·동시 publish 직렬화 테스트.
- 필터 진리표: `predicate()`가 §3 표와 일치(EXISTS/NOT EXISTS만 사용, NULL 탈락 없음). 8조합 nearby=snapshot N=activity openCount=Risk competitor 테스트.
- 공통 predicate: `attribute_filters`에만 적용, temporal_cohort/min(open_date) 미적용. Risk excluded/Seoul/local 세 SQL 공통, local≤Seoul ValueError 가드 유지.
- counts 분모: area만 적용한 brand 필터 전 active located radius 집합, 필터 후 수와 분리.
- v1 보존·캐시: chain=None 경로 불변, v2 Risk는 캐시 우회, v1 응답 본문 비교 보고됨. 공개 행에 semas_id/입력 hash/비교 열 원문 없음, CLI는 safe_json 집계만.

이번 검수에서 MD를 직접 수정한 사항: tgenabled 'O'→ALWAYS 'A'·fail-closed 500 정합화(§1.1), 세대 상한·prune/pending 복귀 부재·activate의 실질 rollback 불가를 공개 한계로 명시(§2).

남은 차단 항목(구현 PASS 전 필수):

1. 루트 `CLAUDE.md`와 `docs/be-work-plan.md` 상단의 #145 문단이 `???`로 깨져 있다(UTF-8 아닌 경로로 기록된 것으로 보임). UTF-8로 다시 작성해야 한다.
2. PostGIS 전체 실행이 아직 진행 중이고, 의도한 `stale_or_drift` 버킷 추가에 맞춰 기대값을 고치는 중이다. 전체 통과(skip0) 전에는 구현 PASS를 줄 수 없다.
3. v2 history meta에 v1 `franchise_classification`/`data_version.brand_mapping`이 남지 않음을 확인하는 단언이 없다(`chain_api.history`는 metadata()와 달리 pop하지 않으며 `get_history`의 chain 분기 소스는 전달되지 않았다). 단언 추가와 통과가 필요하다.
4. `app.models.chain.CHAIN_FIELDS`와 `etl.chains.compare.FIELDS`가 중복 정의돼 있다. 둘이 달라지면 stale guard와 fingerprint가 조용히 어긋나므로 동일성 테스트(또는 단일 정의)가 필요하다.

비차단 권고: `store_hash` 미사용 코드 제거; 잘못된 category 값이 v2에서 CATEGORY_REQUIRED가 되는 점과 sub_category 다중 값 처리가 v1과 같은지 확인 후 FE 요청서 반영; CLI가 ChainsError/SQLAlchemyError/ValueError 외 예외(OSError 등)에서 traceback을 낼 수 있음; `(generation, semas_id)` UNIQUE는 한 소진공 점포가 두 인허가를 뒷받침하면 publish 실패로 이어지므로 #143의 1:1 보장을 확인할 것; 매 stores ETL 뒤 소진공 근거 전체가 drift이므로 재공개(SHARE 잠금으로 ETL 차단)를 운영 절차에 넣을 것.

판정: **PASS FOR DESIGN**. **구현은 REVISE**이며 위 차단 1~4가 해소되고 전체 일반/PostGIS 결과가 실제로 기록되면 현재 명시 범위의 구현 PASS 대상이다. FE·배포·v2 AI 완료는 판정하지 않는다.

### 6.1.3 Claude Code 구현 최종 검수 (2026-11-15)

범위: 이 MD만 Read/Edit. 사용자가 전달한 최종 소스(models/chain, services/chains·chain_api·store_history·spatial_stores·risk·market_activity, schemas/routers chains, etl/chains/publication·compare, migration0012, 두 테스트 파일)와 CLAUDE.md·be-work-plan 상단, 사용자 보고 실행 결과를 자료로 대조했다. 셸·DB·네트워크·git·코드 수정·테스트 실행은 하지 않았다. 아래 수치는 사용자 보고값이며 이번 검수가 재현한 결과가 아니다.

6.1.2 차단 항목 해소 확인:

1. 두 문서 상단 #145 문단이 정상 UTF-8 한국어로 전달됨.
2. 보고: 일반1920 passed, PostGIS278 passed/skip0, ruff/format·mypy177 통과.
3. `get_history(chain=...)`가 legacy brand_context/enrich_meta·franchise 필드를 건너뛰고, 통합 테스트가 `franchise_classification`·`data_version.brand_mapping`·행 `franchise` 부재를 단언함.
4. `etl.chains.compare.FIELDS = CHAIN_FIELDS` 단일 정의. CLI도 OSError를 고정 오류로 처리.

추가 대조 결과(결함 없음): `predicate()`는 §3 진리표·12조합 기대값과 일치하고 pending 시 `valid()=false`로 모두 U가 됨. stale guard는 source/license 동등+나머지 14열 `IS NOT DISTINCT FROM`, drift 시 semas 근거만 제외. publish는 SET/LOCK만 먼저 실행해 snapshot이 잠금 뒤 고정되고, 동일 fingerprint=동일 store_sha256이므로 그때만 revision 기록이 안전함. 용량 실패·verify 실패는 전체 rollback. ANALYZE는 트랜잭션 안에서 허용되며 신규 테이블에만 적용. Risk 세 SQL·nearby excluded_no_coord·activity 모두 같은 `attribute_filters(query, chain)`. v2 Risk는 캐시 우회, AI 경로 없음(404 테스트). 공개 응답에 semas_id·입력 hash·비교 열·fingerprint 없음.

이번 MD 직접 수정: status 공개 항목을 구현(세대/규칙/published_at/source 기준, 지문 비공개)에 맞춤(§3), counts 키 이름을 구현 `brand_counts_scope`로 정합화(§4), FK RESTRICT 서술을 기본 NO ACTION 동등 효과로 정정(§1).

비차단 권고(후속·운영):

- `pg_restore --disable-triggers`나 `ALTER TABLE ... ENABLE TRIGGER ALL`은 tgenabled를 'O'로 되돌려 v2가 fail-closed 500이 된다. 안전한 방향이지만 data-only 복원 후 `ENABLE ALWAYS TRIGGER` 재실행을 운영 절차에 넣을 것.
- 단일 revision 행 때문에 두 원천 ETL의 동시 실행은 대기·lock_timeout 실패가 될 수 있다. 순차 실행 절차를 README에 명시할 것.
- CLAUDE.md의 과거 절("현재 migration head는 0011" 등)은 #145 병합 시점에 상단 문단으로만 구분된다. 병합 후 헤드 서술 정합화 권장.
- `(generation, semas_id)` UNIQUE 충돌·count SQL의 상관 서브쿼리 비용·category 오입력의 CATEGORY_REQUIRED·sub_category 반복 키 422 차이는 실패 방향이 안전하므로 FE 요청서 안내로 충분.
- prune/pending 복귀 부재(4번째 세대 차단)와 activate의 실질 rollback 불가는 §2 공개 한계 그대로 유지.

판정: **PASS FOR DESIGN/IMPLEMENTATION** (현재 명시 범위: migration0012·불변 publication/activate CLI·v2 status/nearby/snapshot/history/activity/risk, 격리 복제 DB 검증). FE 반영·Render/운영 migration·배포·v2 AI·prune 명령 완료는 판정하지 않는다.

### 6.2 구현·검증 기록

2026-11-15 Codex 실제 실행. FE·.env·원본 DB·실행 중 서버2개·Render는 변경하지 않았다. 원본 spoton_dev는689440행/head0011을 유지한다. 백업97,875,726 bytes와 별도 spoton_it_* 복제 DB에서만 migration/publication을 수행했다.

- migration0012 신규5테이블·ALWAYS statement trigger만 적용. 자동 생성에서 발견한 PostGIS 확장 테이블 삭제를 적용 전에 제거했다. 기존 stores 전 필드·좌표 hash는 적용/공개 전후 동일하다. Alembic ORM 비교는 앱 테이블 차이0이다.
- 전체 일반1920개, 전체 PostGIS278개(기존272+신규6), ruff check/format·mypy177파일 통과. 마지막 신규 통합6개 재검사도 통과했고 기존 가맹 메타 없는4행 history 단언·CLI 사전 검증4개를 포함한다. 전체 검사 로그는 비공개 외부 검증 폴더에 보관한다.
- 신규 통합6개 안에서 12필터 조합의 nearby=snapshot N=activity openCount=Risk competitor, 비공간/서울 동일 predicate, v1 본문 보존, source 14열 변경, 같은 batch 다른 행·0행 DML·전체 rollback·RR40001·동시 publication·expected plan/active·자료 있는 downgrade 거절을 검증했다. source/license 복합키는 NOT NULL 동등 비교, 나머지는 NULL-safe 비교로 index 사용과 stale 검출을 함께 유지한다.
- 실제 소진공137173행/공정위2025 자료와 지원 원천355835행을 대조해 estimated8778/unknown347057/conflict0을 저장했다. 기록 단위이며 실제 점포 수·정확도·전수 포함을 뜻하지 않는다. 최종 동일 입력 dry-run/write/replay117.66초, 멱등 true, 두 세대의 테이블/인덱스 약14.9MB(단일 세대 약7.26MB), 원본 hash 동일이다.
- 복제 복원 직후 조회 통계 미준비 상태에서 동시 SQL3초 제한 실패를 확인했다. 복제 DB ANALYZE 후 같은 제한에서33개 실제 v2 API 호출이200·8조건의4종 수 일치, Risk 동시3건은 각각0.703초/본문 동일이다. 이 측정은 현재 로컬 검증 환경이며 Render 성능 보장은 아니다. publisher는 신규 세대 적재 뒤 신규 테이블3개만 ANALYZE하며 원본 stores 통계/업무 값은 수정하지 않는다. 복원 DB는 원천 통계도 별도 준비한다.
- EXPLAIN ANALYZE의 실제 지원 음식점 브랜드 필터270.221ms, 기존 ix_stores_provenance 사용. API마다 모든 원천 hash를 다시 읽지 않는다. 공간 counts는 active located 반경·브랜드 필터 전4버킷(estimated/conflict/stale_or_drift/unknown)이다.
- source hash와 runtime stale guard는 app.models.chain.CHAIN_FIELDS 하나를 함께 사용한다(중복 정의 제거). history는 chain 분기에서 legacy brand_context/enrich_meta를 건너뛰며 기존 가맹 세 필드/메타가 없는 것을 단언한다.
- writer 조사: 인허가 runner/repository는 기본 READ COMMITTED, floor_backfill 쓰기도 READ COMMITTED/읽기는 RR, maintenance는 VACUUM AUTOCOMMIT·사전 검사 RR이고 다른 stores 업무 writer는 없다. 트리거가 순수 운영 SQL/COPY도 추적한다. 동시 ETL/보정은 순차 운영하고 오류는 전체 rollback한다.
- 원천 stores DML 뒤 소진공 근거가 drift되므로 수집·보정 후 snapshot/registry를 고정해 dry-run→새 fingerprint/active 확인→재공개한다. 변경 내용이 없으면 세대를 재사용하고 validated_source_revision만 갱신한다. 매월4번째 새 세대부터 보존 한도에 걸리므로 운영 갱신 전에 명시 prune/pending 복귀 절차가 후속으로 필요하다.
- [FE 계약 요청](../fe-chain-v2-api-request.md)을 BE 저장소에만 작성했다. 배포·운영 권한/migration·FE 전환·v2 AI 문맥/캐시는 이번 완료 범위가 아니다.

### 6.3 검수 증빙과 후속 재검토

실제 Claude Code2.1.322 Read/Edit 전용 CLI를 사용하고 대상은 이 MD만 수정하도록 제한했다. 셸/DB/네트워크/git/비밀/원천 개별 행은 검수 입력에 제공하지 않았다. 코드/검증 집계만 전달했다.

- 1차 설계: UTC17:49:10~17:52:00, exit0·8turns·denial0. 설계 PASS이며 구현 완료 판정이 아니다.
- 원천 변경 감지 보강: UTC17:54:43~17:56:36, exit0·11turns·denial0, 설계 전용 PASS.
- 코드 검수: UTC18:12:54~18:15:36, exit0·5turns·denial0, 설계 PASS/구현 REVISE. 입력 MD SHA a4a2ac2af7161c6472a05a6ad4badbee8d5ad39053d727c9dc4aaecbc40541a7, 수정 후 e3055b722c5e6fcd1ab26d7a997c34a6807a79af391cf81ccbafbd605ceceabc. §6.1.2의 차단4개를 수정하고 최종 검증 후 코드 재검토한다.
- 최종 코드 재검수: UTC18:20:39~18:22:59, exit0·6turns·denial0, **설계·구현 모두 PASS(현재 명시 범위)**. 입력 MD SHA1a6be4732ab6f3e28d6f517051582917120c7eede5b6423506fe8b1ec4fd69dc, Claude 수정 후3acf67011e20993639e7a842837e15a91ea744099bb9e51f21e13f52567c6c67. 검증 실행자는 Codex이고 Claude는 전달된 소스/결과를 대조했다. 후속 권고의 순차 writer·복원 후 ALWAYS trigger/ANALYZE 절차·현재0012와 과거0011 구분을 README/공통 기준에 반영했다.
- 기존 브랜드5테이블도 최종 복제 DB와 원본 DB의 행수·전 필드 hash가 일치함을 추가 확인했다. 다음은 BE PR의 CI/CodeQL과 develop 병합이며 FE·Render 배포는 포함하지 않는다.
