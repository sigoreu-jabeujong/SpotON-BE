# 브랜드 갱신·조건부 지표 실제 연결 설계 (#176)

2026-11-16 후속 [#178 부분 공개자료·실제 API 연결 설계](feat178-population-api-partial.md)는 이 문서의 인구 gate를 **전체 인구 경로**로 한정하고, source별 고정 공개 구성의 기술 산술을 별도 GET으로 제공하는 안을 추가한다. 이 부분 참고 경로는0013/8표/전체 기대 구성 승인을 선행조건으로 삼지 않는다. 이 문서의 원천 승인·전체 인구/매출/변화·AI/브랜드 계획은 보존하며 원천/FE/앱은 이번 문서 작업에서 바꾸지 않는다. 새 부분값은 기존 living_pop.total·Risk pending에 넣지 않는다.

작성2026-11-16, 기준 develop `ec90d64`(PR175). **이 문서는 다음 구현을 위한 설계이며 실제 DB·API·AI 활성화 기록이 아니다.** FE·앱 코드·migration·.env·기존 서버/Render·Task/runtime은 이번 문서 작업에서 변경하지 않는다. RSS는 이후 문맥에서 READ ONLY REPEATABLE READ snapshot session을 뜻한다. [이전 구현/실제 검토](feat174-analysis-foundations.md), [공식 통계 감사](feat156-market-applicability.md), [생활인구 근거](../population-source-verification.md)를 이어간다.

## 1. 현재 구현과 다음 결과물

| 항목 | 현재 구현 | 다음 구현/적용의 완료 조건 |
|---|---|---|
| 브랜드 | 검토 seed17개, 혼합/세부 브랜드 오흡수 방어, 추정 규칙v2 | 같은 자료로 실제 새 publication을 만들고 v2 조회·활동·Risk·AI·캐시 일치를 확인. 점포별 정답/오탐·누락 검수는 별도 |
| 매출/상권변화 | `market_reference.py`의 분기 선택·typed 원천 투영 | 공식 도형/기간 근거를 특정 불변 버전·분기에 연결하고 실제 읽기 service·새 typed API/AI로 제공 |
| 생활인구/주야간 | `population_totals.py`의 격자별72개 source/hour 완전성 조립→기존 산술 | 독립 기대 구성/관측일 적용 근거와 실제 반경 조회를 연결하고 비공개·부재를 보존한 수치만 제공 |

PR175 실제 비교는355,835행에서 추정8,778→10,813(정확도 측정 아님), 이탈4건은 주소/인허가 유일성 부족에 따른 미확인, catalog→검토 seed 연결92건이다. 신규 public 세대/운영 배포는 미실행이다. 기존 내부 결과의 `source_validation_performed=false`·`public_activation_ready=false`는 그대로 두며 새 service가 이를 True로 덮어 승인 증거로 사용하지 않는다.

## 2. 근거 계약: 파일 hash와 공식 적용성은 별개

| 활성화 대상 | 필수 공식 근거 | 데이터/기술 검증 |
|---|---|---|
| 매출 | 해당 경계 도형의 적용 분기, 해당 ZIP의 금액·건수 기간(분기 합계/월평균/특정 월), 원천/업종/개정판 정의 | 원본/content/boundary hash, 동일 quarter·market·업종, 코드/명칭 대조,0/null/행 부재 |
| 상권변화 | 해당 경계/분기 대응, LL/LH/HL/HH와 원천 평균개월의 의미, 상권 전체/업종 비구분 정의 | source/content/boundary hash, 코드/유형/명칭·분기와 원천 행 일치 |
| 생활인구 | 행정동 구성요소의 가산성·독립 기대 구성, 없는 행의 처리 의미, 격자의 관측일별 적용 | 관측/격자 버전·hash/날짜, 기대 grid/source/hour/admin 집합, 원천 상태·중복·누락/비공개·위치 미확인 |

공식 URL·문서/답변의 bytes SHA256·확인시각·발행/효력 기간(모르면null)·명시 claim을 함께 남긴다. SHA/다운로드일·상권 코드 일치만으로 승인하지 않는다. 제공기관 답변은 비공개 원문을 외부 저장소에 보존하고 공개에는 문서 식별자와 허용 URL/요약만 제공한다. 개인 연락처·메일·파일 경로·관측 원문은 응답/로그/Claude 입력/커밋에서 제외한다. 검토된 공개 브랜드/공식 표기 목록은 registry의 허용 자료다.

자료가 없으면 해당 지표만 pending이다. 매출 기간 미확정은 경계/정의가 확인된 상권변화까지 막지 않는다. 인구도 독립이다. 문의 초안은 [통계 감사5절](feat156-market-applicability.md#5-제공기관-확인-요청-초안), [인구 보고서5절](../population-source-verification.md#5-제공기관-문의-초안--미제출)을 재사용하며 이번에 대신 제출하지 않는다. 기존 unverified CHECK/원천 행·버전을 UPDATE로 승격하지 않는다.

## 3. 승인과 공개: 별도 불변 publication

후속 migration 후보는0013이며 **이번에는 생성/적용하지 않는다**. 원천 버전은 그대로 두고 별도8테이블을 제안한다.

| 테이블 | 핵심 열/불변식 |
|---|---|
| `reference_evidence_documents` | UUID, authority_kind(official_document/provider_reply), 공개 허용 source URL 또는 비공개 locator ID, bytes SHA256, acquired_at, published_on nullable, 검토 범위. 원문 본문/개인정보는 저장하지 않음 |
| `reference_publications` | UUID, metric(sales/market_change/population), rule/manifest/content SHA, approval/구성 수, source epoch+revision vector, 생성시각. 동일 fingerprint 재사용 |
| `reference_approvals` | publication FK, 같은 metric, 정확히 하나의 sale/change/population version FK, 필요한 boundary/grid FK, input/content/공간 content SHA, quarter 또는 observation_date, 근거 적용 기간. sales만 period_basis·필요시 source_month 필수 |
| `reference_approval_documents` | approval/document FK, claim_kind(boundary_period/sales_period/change_definition/admin_additivity/absence_policy/grid_date/components 등). 필요한 claim 누락은 승인 불가 |
| `reference_component_sets` | canonical 구성 SHA PK, grid version FK/content SHA, universe SHA, 행수/규칙. 동일 구성 bytes를 여러 관측일 승인에서 재사용하되 각 날짜의 공식 적용 claim은 따로 검증 |
| `reference_population_components` | component_set FK, grid_id/source/admin_code, 명시24bit hour_mask. PK(set,grid,source,admin). 관측 행에서 기대 집합을 역생성하지 않음 |
| `reference_publication_state` | metric별 singleton active FK nullable, revision 단조 증가. 다른 metric의 세대 활성화를 거부 |
| `reference_source_state` | boundary/sales/market_change/grid/population별 epoch UUID·revision>=0. 원천 DML/TRUNCATE가 해당 revision을 증가 |

approval의 metric·원천 FK·publication.metric 조합은 복합 FK/CHECK로 일치시킨다. 매출/상권변화는 quarter가 원천 source_year 안에 있고 Q의 시작·종료일 전체가 근거 적용 범위 안이어야 한다. population은 observation_date/grid version이 관측 버전과 같도록 복합 FK를 두고 근거의 격자 적용 범위에 있어야 한다. component_set FK도 같은 grid version을 참조해야 한다. sales/change는 원천 버전의 code_check_boundary_version_id와 승인 boundary를 복합 FK로 일치시키고, 다른 도형을 쓰려면 새 원천 버전부터 검증한다. `specific_month`는 해당 분기의 월초 date, 다른 basis에는 source_month=null이다. publication 하나는 같은 metric의 여러 승인 분기/관측일을 포함할 수 있다. metric별 중복 quarter/관측일은 거부하며 승인 분기/관측일은 publication별 각각400개 이하로 제한한다. 이는 자원 상한이며 자료 보관기간이 아니다. 초과 시 자동으로 과거일을 잘라내지 않고 계획을 거절한다. 상한 변경은 별도 clone 측정과 규칙 버전 검토를 거친다. population 승인만 component_set FK를 가진다. API가 최신 UUID를 임의 선택하지 않는다.

component hour_mask는 실제 명시 시간 집합을 손실 없이 압축한 것이며 전 시간 고정 구성이라는 가정이 아니다. 0mask·24bit 초과·중복·격자/행정동/원천 오류를 거부한다. 격자별3원천×24시간 전체 구성이 있고, 동일 source/hour의 예상 admin 집합이 독립 근거와 일치해야 한다. 구성값에는 인구 숫자를 넣지 않는다. publisher가 전체 artifact/content digest를 검증하고 조회는 선택 격자에 한해 mask를 펼쳐 기존 assembler에 전달한다. 어떤 격자를 완전히 빠뜨리는 오류도 전체 승인 범위 검증에서 거절한다. universe는 grid version 전체의 격자 집합과 같아야 한다. 전역 compressed 구성은 파일/행수 상한과 스트리밍 검사로 검증하고, 반경 assembler의1,000격자/100,000component 상한을 전역 자료에 그대로 적용하지 않는다. 상한은 publisher artifact64MiB·compressed200,000행, 읽기 요청은 기존 radius 상한이다. 실제 저장량/공유 set 수는 clone에서 측정한다.

권한은 R4(a)를 채택해 실제로 분리한다. publisher/표 소유자는 기존 spoton_app이며 새 CLI의 그 사용자 guard를 유지한다. API는 별도 spoton_reference_reader(비슈퍼유저/비소유자/쓰기 역할 비멤버)를 clone과 적용 환경에 만들고 기존 조회 대상과8표의 SELECT/스키마 USAGE만 부여한다. 새 API process의 접속 설정만 바꾸며 원래 .env는 유지한다. Render의 기존 조회 전용 역할은 필요한 SELECT만 추가하고 publisher guard를 원격 허용으로 바꾸지 않는다. 준비 검사는 API 역할의 소유권/DML/TRUNCATE/CREATE·위험 함수 EXECUTE 권한이 없음을 확인한다. 같은 spoton_app 연결을 READ ONLY로 둔 것만으로 역할 분리가 완료됐다고 쓰지 않는다. 객체 소유자의 악의적 조작은 이 모델의 보장 밖이다. `reviewed=true` 같은 요청 인자/환경변수·임의 JSON만으로 활성화할 경로는 없다. 승인 입력은 실제 문서 claim을 대조한 검토 artifact와 source별 무결성 검사이며, Claude의 코드 PASS 자체도 제공기관 근거를 대신하지 않는다. 통상적인 자료 대조/검토는 기존 Codex→Claude→Codex 절차로 진행한다.

publication fingerprint는 H(schema/rule/format, metric, 정렬된 approval+기간+basis+원천/공간 SHA, component set SHA, document authority/claim/bytes SHA, 의존 source의 epoch+revision vector)로 고정한다. expected active는 지문에 넣지 않고 경합 가드로 별도 검사한다. drift 뒤 동일 내용이어도 vector가 달라 새 publication이다. 동일 지문이 이미 있으면 전 내용을 재검증하고 재사용한다. active가 같으면 포인터 no-op, 비활성 세대 재활성화는 expected active 확인 후 state.revision+1이다. 단 재활성화 대상의 저장 epoch+vector가 잠금 후 다시 읽은 현재 의존 vector와 다르면 활성화를 거부하고(즉시 `source_changed`가 될 세대를 가리키지 않음) 새 계획/publication을 요구한다.0개 approval publication은 거부한다.

epoch는 migration bootstrap 때 새 UUID를 생성해 초기화하고 publisher 계획/reader/cache에 반드시 포함한다. downgrade/re-upgrade에서는 새 epoch를 써 revision ABA를 막는다. 백업 복원 후에도 중지된 환경에서 전용 rotate_epoch 실행으로 새 epoch를 만들고 기존 승인을 stale로 둔 다음 재검증/재공개한다. source counter만0으로 돌려 cache/plan을 재사용하지 않는다.

의존 vector는 sales={boundary,sales}, market_change={boundary,market_change}, population={grid,population}으로 고정한다. boundary 변경은 두 상권 지표에 영향을 준다. 다른 kind 변경만으로 인구를 stale로 만들지 않는다.

FK를 위해 기존 market_sale_versions와 market_change_versions에 각각 `(version_id, code_check_boundary_version_id)` UNIQUE를 추가한다. source 원문/CHECK는 바꾸지 않으며0013의 허용 DDL 차이는8표/관련제약·인덱스,10 source trigger/함수,이2개 metadata UNIQUE다. population은 기존 `(version_id,grid_version_id,observation_date)` UNIQUE를 재사용한다. component_set의 `(SHA,grid_version)`도 복합 참조 가능하도록 UNIQUE를 둔다. downgrade에서는 새 FK를 제거한 다음 이 신규 UNIQUE만 제거한다.

reader role 생성/검증은 Alembic의 앱 writer 권한으로 가정하지 않고 로컬 container 관리 역할/허용된 운영 관리 절차로 별도 수행한다. 이름이 이미 있으면 권한/멤버십/소유권을 검사하고 불일치 시 중단한다. 새 역할 비밀값은 process 전용 비밀 설정으로 전달하고 문서/명령 인자/채팅/.env에 넣지 않는다. 역할의 자동 DROP/권한 확대나 기존 API process의 임의 접속 변경을 하지 않는다.

## 4. 원자적 공개·드리프트·잠금

`etl.references`(미구현)는 기본 READ ONLY 계획, 명시 publish/disable/prune만 쓰기다. publish에는 `expected_plan_sha256`과 metric별 `expected_active`가 필요하다. 입력은 제한된 로컬 artifact와 명시 source version들이며 앱 요청 중 외부 수집/파일 접근·승인 쓰기를 하지 않는다. 클라이언트는 version/approval/verified 값을 제출하지 못한다.

초기 쓰기 CLI는 기존 ETL과 같은 loopback·DB spoton_dev·spoton_app/비슈퍼유저·PostGIS·정확한 예상 head를 검사한다. 운영/원격을 허용하려고 guard를 완화하지 않는다. 정상 CLI의 clone 검증에는 원본과 **다른 임시 컨테이너/loopback port**를 쓰되 그 안의 DB/role 이름을 spoton_dev/spoton_app으로 둔다. source container와 동일 image ID/서버·확장 버전을 사용하고, 실제 대상 container ID/port가 원본과 다름을 확인한 뒤 프로세스 전용 접속 설정으로 실행한다. 앱 .env/Docker compose/원래 컨테이너를 수정하지 않는다. 원격 승인은 향후 별도 관리 실행 절차로 분리한다.

원천10표(경계/매출/변화/격자/관측 각각 version+행)에 ALWAYS statement trigger를 추가해 INSERT/UPDATE/DELETE/TRUNCATE에서 source별 revision을 증가시킨다. 고정 search_path/완전 수식 테이블명을 쓰는 SECURITY DEFINER 함수의 PUBLIC 실행은 회수한다. 큰 revision overflow는 원천 트랜잭션 자체를 실패시키며 임의0 초기화하지 않는다. 새 source 버전 추가도 같은 source kind의 기존 승인을 보수적으로 stale로 만든다. 이는 향후 최적화할 수 있으나 초기에는 부분 무효화 추측을 하지 않는다.

identity/head/role 사전 검사는 별도 트랜잭션에서 끝내고 commit한다. writer는 새 RR 트랜잭션에서 **어떤 SELECT/DML보다 먼저** publication_state를 EXCLUSIVE, 관련 원천 표를 정해진 순서로 SHARE 잠금한다. timeout 설정은 SET LOCAL이고 SELECT set_config를 쓰지 않으며 driver/ORM의 첫 SQL 순서도 검사한다. 이후 source revision/현재 active·버전/내용과 artifact를 다시 읽고 계획과 같을 때만 insert→상한 검사→포인터/revision을 한 트랜잭션으로 commit한다. source_state 자체를 먼저 EXCLUSIVE 잠가 ETL trigger와 역순 교착을 만들지 않는다. 모든 publisher/disable/prune은 control→source의 같은 잠금 순서이며, ETL과 순차 실행하고 lock_timeout5초·전체 유한 예산 초과는 고정 오류/전체 rollback이다. 40P01 deadlock·40001 serialization failure·lock_timeout은 고정된 경합 오류/전체 rollback이며 강제 재시도나 운영 트래픽 정지는 자동화하지 않는다. [PG17 RR](https://www.postgresql.org/docs/17/transaction-iso.html)·[잠금](https://www.postgresql.org/docs/17/explicit-locking.html)을 따른다.

객체 불변성은 트랜잭션 DML 규칙과 역할로 보장한다.8표의 TRUNCATE와 일반 UPDATE는 금지하고 publication_state만 active/정확히 revision+1 UPDATE를 허용한다. source_state 변경은 원천 trigger 함수 또는 권한 제한 rotate_epoch 경로만 허용한다. 소유자와 writer가 같은 spoton_app이므로 이 구분은 권한이 아니라 source_state의 guard trigger로 구현한다: revision 정확히+1·epoch 불변 UPDATE는 `pg_trigger_depth()>1`(원천 statement trigger에서 중첩 호출)일 때만 허용하고, epoch 교체 경로는 중지된 환경의 복원/migration 관리 단계로 고정한다. rotate_epoch는 정상 API/일반 publisher 동작에 노출하지 않는다. 관리 역할이 같은 트랜잭션에서 control→원천 SHARE→source_state ACCESS EXCLUSIVE를 잠근 뒤 지정 guard를 일시 해제하고 모든 kind의 epoch를 새 UUID로 교체(기존 counter는 유지)한다. 같은 트랜잭션 안에서 guard를 ENABLE ALWAYS로 복구하고 정의 hash/5kind/epoch 일치를 검증한 뒤 commit한다. 중간 오류/lock timeout은 DDL까지 rollback하며 guard 복구 없는 commit은 금지한다. API/ETL은 중지/진행 요청 종료 상태이고 외부 세션 잠금이 남으면 강제 해제하지 않고 중단한다. 이는 실수 방지이며 소유자 악의 조작 방어가 아니다. 세션 GUC로 DML 가드를 해제하는 우회는 만들지 않는다. 비활성 prune은 approval_documents→approvals→publications 순서로 삭제하고, 어떤 승인도 참조하지 않는 set의 components→component_sets, 미참조 documents를 명시 삭제한다. active/참조 중 set의 component 행 삭제는 trigger가 거부하며 FK RESTRICT를 유지한다.

잠금 순서는 publication_state→boundary(version,rows)→sales(version,rows)→market_change(version,rows)→grid(version,rows)→population(version,rows)이며 각 metric의 의존 표만 사용한다. 현재 importer는 version→행, 생활인구는 grid version→grid rows→population version→observation rows 순서로 INSERT하는 것을 소스로 확인했다. 후속 DELETE/다중 kind writer도 이 순서로 먼저 잠금하고 실제 child-first DML을 수행한다. 원천 reader의 ACCESS SHARE는 publisher SHARE와 양립하지만 ETL과의 경합/교착 rollback 검사는 별도로 필요하다.

독자는 하나의 READ ONLY RR session에서 active state→source epoch/revision→선택 approval/원천을 읽는다. source vector 불일치는 해당 지표 `pending/source_changed`이며 cache hit도 이 검사를 생략하지 않는다. hash/참조/trigger guard 손상은500/no-store이며 같은 RSS에서 pg_trigger.tgenabled='A'·함수 정의 hash·권한/대상 표를 대조한다.  승인 없음/적용 범위 없음은200 pending이다. 승인된 범위의 행 부재는 no_data로 구분한다. 요청 중 commit된 변경을 같은 snapshot에 섞지 않는다. disable은 포인터를 내리고 revision을 증가시켜 숫자/선택 cache를 무효화한다. 명시된 비활성 세대만 prune하고 활성/증거 공유 FK가 있으면 거부한다.

상한 제안은 metric별3세대, reference8표 합32MiB, 검증 대상 DB900,000,000bytes다. 기본 전체 요청은 SQL/앱 예산을 기존 설정 안에서 쓰며 publisher의 대량 검사와 분리한다. clone에서 실제 heap/TOAST/index·전후 DB 크기를 측정해 상한 안일 때만 적용한다. DELETE/VACUUM의 물리 축소를 보장하지 않으며 상한 초과 시 자동 증설/유료 전환/원천 삭제를 하지 않는다. [Render Free의 제한](https://render.com/docs/free)과 기존 배포 문서를 따르며 실제 가용 공간은 적용 직전에 확인한다.

## 5. 실제 조회 service

### 매출·상권변화

1. mode는 as_of 미지정=current, 지정=history로 한 곳에서 정한다. T는 현재 검증된 인허가 기준일 D/해당 category 최소일과 기존 effective_date를 사용해 최신 월은D·과거 월은월말로 정하며 브랜드/면적 조건으로 바꾸지 않는다. active publication의 검증된 기간 목록과 T로 기존 `select_quarter`를 호출한다. 현재 요청은 T 이하 검증된 최신 분기, 과거 월은 해당 분기만 선택하며 없으면no_data다. `latest_verified`가 최신 공표라는 뜻은 아니다. 응답에 source quarter·분석일·분기 차이 source_quarter_lag·`knowledge_basis=retrospective_revised_source`를 명시하고 당시 이용 가능했던 통계라고 표현하지 않는다.
2. **분기를 고른 뒤 그 approval의 boundary UUID로** `judge_market`를 호출한다. 전역 RISK_BOUNDARY 설정이나 현재 도형을 다른 분기에 대입하지 않는다. sales와 change가 서로 다른 승인 도형이면 판정을 각각 수행하고 결과를 공유하지 않는다. 단일 세부 상권/관광특구 병기·중첩 ambiguous·outside 판정은 기존 규칙을 유지한다. ambiguous/outside에서는 해당 수치가 없으며(`no_data/market_ambiguous`·`no_data/outside_market`, data=null) 인근 상권을 대신 고르거나 합산하지 않는다.
3. 매출은 정확한(version,quarter,market,industry) 행을 읽는다. cafe→CS100010, korean/chinese/japanese/western→CS100001/2/3/4다. restaurant의 세부 업종이 여러 개/전체이면 업종별 item을 각각 반환하고 합산하지 않는다. 원천 공식 업종과 인허가 모집단이 동일하다고 설명하지 않는다. 소수점/환산·반경합·점포당 나눗셈·분기값÷3을 하지 않는다.
4. 상권변화는(version,quarter,market)만 조회하며 업종/브랜드/면적 조건을 적용하지 않는다. LL/LH/HL/HH와 원천 평균개월을 typed 구조로 반환하고 숫자 점수로 바꾸지 않는다. null 평균은null이며 코드 존재를 수치 완전성으로 표시하지 않는다.
5. 선택 행을 기존 `project_sales/project_change`로 투영한다. 내부 false 플래그는 바꾸지 않고, 바깥 service가 approval ID·source SHA/revision·문서 claim 결과를 별도 PublicReferenceEnvelope로 구성한다. source hash는 publish 시 전수 검사하고 요청은 revision/참조/불변성 guard를 검증한다. trigger가 없거나 꺼지면 정상 수치 반환을 거부한다.

### 생활인구·주야간

1. 원래 사용자 분석 보고서의 요청 월 안 최근1일 정책에 맞춰, current/history 모두 T가 속한 달의 시작일≤관측일≤T인 **검증된** 최근1일을 고른다. 다른 달 자료를 임의 대체하지 않는다. 세 원천 local/long/short는 같은 observation version/날짜/grid version이며 다른 날짜나 버전을 섞지 않는다. 선택일과 T의 차이를 `observation_age_days`로 제공한다. 임의7일 등 새 최신성 상한은 넣지 않고 날짜를 명시한 참고 관측으로 제공한다. 해당 월에 검증된 관측이 없으면no_data/no_observation_in_period, 근거 자체가 미준비면pending이다.
2. 기존 `population_quality`와 같은 source 중심점·구면거리 정책으로 반경300/500/1000m 격자를 선택한다. 폴리곤 교차 면적 가중·인구 분할·가짜 좌표를 만들지 않는다. 선택 grid IDs를 독립 scope로 고정한다. 승인 universe에 없는 격자가 선택되면500 무결성 오류다. space_id=SHA256(grid version, 정렬 grid IDs, radius, 부호0을 정규화한 float.hex 중심점)의 canonical 직렬화이며 외부/로그로 노출하지 않는다. 요청마다 같은 실제 좌표/격자 선택을 바탕으로 만든다. 사용자 결정대로 미매칭 관측은 공간 집계에서 제외하고 전역 unlocated 건수/범위를 별도 메타로 표시한다. 이 수치를 실제 반경 안 모든 사람/완전한 공간 커버리지라고 표현하지 않는다.
3. 그 격자의 승인 component mask를 펼쳐 expected를 만든다. **실제 row/당일 나타난 admin 집합·다른 시간 관측으로 expected를 생성하지 않는다.** 기대 구성의 격자/source/hour/admin과 실제 행을 직접 대조한다. 부재·suppressed·missing·중복·예상 밖 행은 각각 보존한다. 없음/비공개를0으로 채우거나 알려진 값만 SUM하지 않는다. 동일 식별자 중복/예상 밖은 데이터 무결성 오류로 처리한다.
4. `PopulationScope`와 observations를 기존 assembler로 전달한다. 반경 요청은 명시 격자1,000·component100,000 상한 안이어야 한다. 유효 query가 이를 초과하면200 not_supported/scope_too_large이며 일부 격자만 잘라 합산하거나422 사용자 오류로 바꾸지 않는다. 선택 격자가0개이면 `no_data/no_selected_grids`이며 empty를0명으로 부르지 않는다. 한 시간이라도 불완전하면 공개 생활인구/주야간 수치는no_data이고 부분합을 내보내지 않는다. 진단 counts는 인구 수와 분리한다.
5. 완전한 경우24시간 총계와06~17/나머지 구간의 합·평균·비중/배수를 제공한다. 이는 SpotON 기준이며 공식 홈페이지의 주야간 구분과 다르다. 인시 합을 하루 고유 방문자로 부르지 않는다. 밤0이면 배수null/zero_denominator, 양쪽0이면zero_total·비중null, 실제0과 결측을 구분한다.

인구 관측일의 같은-월 제약은 사용자 분석 보고서의 명시 문구(원본155/200행)를 대조해 확정했다. 기존 작업계획의 "요청월 T 이하 최근1일"을 무제한 과거일 fallback으로 해석하지 않는다. 조회 mode는 as_of 유무로 정하되 인구의 `[T월 시작,T]` 창은 동일하다. 인허가 분석일/분기/관측일을 각각 내보내고 선택일1일을 월평균으로 바꾸지 않는다.

## 6. 새 공개 API 계약(미구현)

기존 `MarketActivity.sales/living_pop`은 None 전용이고 Risk의 조건부 항목도 pending 제약이 있다. 이를 조용히 바꾸지 않고 **새 경로**로 연결한다. 기존 v1/v2 activity/risk/interpret의 형식·숫자·프롬프트는 유지한다.

`GET /api/v2/reference-indicators`: `ReferenceQuery`는 기존 ChainQuery의 공간/시점/category/sub_category 및 브랜드/면적 맥락과, `include=sales,market_change,living_pop,day_night_ratio`의 비어 있지 않은 부분집합을 받는다. 중복/알 수 없는 인자·legacy franchise·클라이언트 수치/승인/UUID는 DB 이전422다. brand_scope≠all의 명시 brand_unknown 규칙도 유지한다. 브랜드·면적 조건은 echo만 하고 모든 reference 값에는 `brand_filter_applied=false/license_filters_applied=false`와 실제 공간·업종 적용 범위를 명시한다.

매출 projection available→reference, partial→partial, no_data→no_data로 매핑한다. restaurant 여러 업종은 item별 상태를 두고 모두no_data이면 상위no_data, 모두reference이면reference, 나머지는partial이다. 승인 gate의 pending/not_supported는 행 조회 전에 공통 적용해 부분 승인처럼 섞지 않는다.

각 항목은 `status=pending|reference|partial|no_data|not_supported`, `reason`, typed `data`, provenance를 가진다. 미요청 항목은 반환하지 않는다. pending/no_data/not_supported는 data=null이다. restaurant 전체 no_data일 때도 비숫자 coverage 메타로 업종별 행 부재/두 null을 구분한다. sales partial은 존재하는 행의 금액/건수 중 알려진 값만 그대로 제공하고 null 사유를 분리한다. 상권변화는 코드가 있으면 reference이나 평균별null을 유지한다. 인구는 부분합을 공개하지 않으므로partial이 없다. 두 인구 selector는 같은 assembly를1회 재사용하고 source gate/불완전성 사유는 공유하지만 산술 가용성까지 같다고 강제하지 않는다. living_pop은24시간·구간 합/평균·비중을, day_night_ratio는 배수만 제공한다. 밤0이면 living_pop은reference(실제0 보존), ratio는no_data/zero_night_denominator다. 전체0도 living_pop은reference·비중null/zero_total, ratio는no_data다. 밤>0이면 ratio는reference이며 낮0의 실제 배수0도 보존한다. 예상 원천 scope/ID/분기가 다르거나 모델 검증 실패 시 부분 응답 없이500/no-store다.

provenance에는 metric별 publication/approval·source/boundary/grid 버전, 선택 분기/관측일·T, source_kind와 calculation_kind, 실제 필터 적용 범위를 담는다. 주소·인허가·격자/행정동 개별코드·구성명부·키·비공개 근거 locator·파일 경로는 반환하지 않는다. 공개 market_code/market_name은 원천 상권 식별자로 반환할 수 있으며 비공개 격자/행정동 관측 코드와 구분한다. 개별 점포명은 반환하지 않는다. UUID/hash는 출처 식별자이며 공식성의 증명이라고 표시하지 않는다. 통신 추정 인구와 추정매출은 `reference`이고 원천이 공공기관이라는 이유로 공식 위험 판정/확정 매출/방문자 수로 승격하지 않는다.

BigInt 원/건수와 Decimal 인구/배수는 정밀도 손실을 피하려고 canonical 십진 **문자열**로 반환한다(지수/NaN/Infinity 금지). 정수 원천은 그대로, 시간 총계/구간합은 소수5자리 이하, 평균·배수는소수5자리 HALF_UP, 비중은소수1자리로 표시하며 `rounded`·`exact_zero`를 함께 둔다. 값이null이면 두 플래그도null이며 실제0/반올림0과 구분한다. 내부 계산은50자리 정밀도를 유지한다. 반올림0을 실제0으로 설명하지 않고 AI/FE는 서버 display 문구를 사용한다. source/candidate와 숫자 표시 규칙 버전을 출처/캐시 키에 포함한다.

## 7. AI·캐시·FE 전달(미구현)

`POST /api/v2/reference-interpret`는 `{query: ReferenceQuery, history?: InterpretHistory}`만 받는다. 서버는 query에서 include를 제외한 같은 조건으로 **include=()인 ChainRiskQuery**를 만들어 기존 core Risk/활동과 history를 계산한다. risk.py는 query.include에 있는 항목만 append하므로 include=()에서 market_change/day_night_ratio 두 placeholder가 없어지는 것을 소스로 확인했다. flags.missing도 그 두 항목에 대해 비어야 하며 실제 회귀로 고정한다. 구형 Risk와 새 reference를 중복 투영하지 않는다. FE 대응은 기존 선택 market_change→reference.market_change, day_night_ratio→reference.day_night_ratio이며 구형 endpoints 자체는pending을 유지한다. 같은 READ ONLY RR session에서 chain selection·reference state/revision/approval·원천·이력을 계산해 하나의 독립 outbound 문맥으로 만든다. 클라이언트 GET 결과/수치·source 승인·프롬프트는 받지 않는다.

새 ReferenceInterpretContext/응답 모델과 프롬프트 namespace를 쓰고 기존 v2 prompt를 수정하지 않는다. 지표 ID는 `reference.sales...` 등 독립 범위이며 typed 상태/출처/공간/기간에 맞는 서버 문장 후보만 LLM이 선택한다. 브랜드/반경 값과 상권 매출을 같은 필터 수치처럼 결합하거나 지표를 임의 점수화·성공/매출 보장·결측 복원하지 못한다. pending/no_data는 missing 문구만 허용한다. false 내부 플래그를 True로 바꿔 문맥을 만드는 대신 service의 승인 provenance를 검증한다.

기존 InterpretationResources/limiter/gate/flights를 공유해5회/분·50회/일·동시2·전체20초/재생성최대1회·취소 후 쓰기 차단을 유지한다. DB 오류/승인 손상/불일치에는 provider0회다. 테스트는 모의 공급자를 쓰고 실제 공급자 검증은 기존 비용 범위 안의 별도 유한 표본으로 구분한다.

cache key는 reference 규칙/포맷/프롬프트·canonical query(적용하지 않는 echo 필터도 포함)·실제 T·current_provenance/snapshot_token·현재 chain publication/revision·reference의 metric별 publication/state/source epoch+vector·실제 선택 버전/기간/content SHA를 포함한다. cache hit 전에도 현재 RSS의 state/revision/무결성 guard를 읽는다. disable·source drift·새세대·증거/포맷/모델/시점 변경은miss이며 pending/no_data를 fact 후보로 재사용하지 않는다. 새 cache는 기존 공용 bounded 메모리 예산을 나눠 쓰고 별도 무제한 저장소/전역 key count를 추가하지 않는다. HTTP는no-store, 응답별 독립 snapshot이며 여러 HTTP 요청의 원자성은 보장하지 않는다.

FE 코드는 건드리지 않고 BE의 `docs/fe-reference-indicators-api-request.md`(후속 작성)에 새 경로/숫자문자열·반올림0·상권/선택격자와 반경 차이·필터 미적용·새AI 선택·출처/날짜·pending/0/null·조건 변경 취소/보고서 재사용 규칙을 전달한다. FE 확인 전 공개 화면이 바뀌었다고 표시하지 않는다.

RSS를 닫은 뒤의 LLM 완료/동시 disable은 시작 시점의 snapshot 메타로 구분한다. disable 후 새로 시작하는 요청/새 cache hit에는 옛 승인을 쓰지 않는다. 이미 시작한 요청의 즉시 취소나 여러 HTTP 요청의 공통 snapshot은 보장하지 않는다. API 응답에 실제 분석일/출처 버전이 남고 다음 요청은 새 epoch/vector/state를 검증한다.

## 8. 브랜드 갱신·검수·복구

브랜드는 통계 근거와 독립적으로 진행할 수 있다. 다음 실행은 기존 [공개 관리](../chain-publication-operations.md)·[테스트 반영](feat151-local-test-chain-rollout.md)을 따른다.

1. 로컬 대상/role/head0012·현재 pointer/세대 수/DB용량·원천/registry/소진공SHA를 확인한다. writer를 순차화하고 새 custom dump→폐기용 clone 실제 복원→기존 업무 표/정의/sequence 보존 대조를 먼저 완료한다. 운영 Render/기존8000/8001을 clone 검증 때문에 전환하지 않는다.
2. clone에서17개 registry·규칙v2로 READ ONLY 계획→expected fingerprint/active를 묶은 publication→실제 v2 GET/활동/Risk/AI 모의 공급자·24필터 조합·세대 캐시 변경을 검사한다. 건수10,813은 마지막 읽기 비교 기준이며 현재 자료에서 재계산한 결과와 같을 때만 사용한다. 소진공 원천의 관측시점·operation_type=unknown/observed_record 한계를 유지한다.
3. 검수 표본은 신규 추정, 기존 추정, 미확인 후보, 혼합/동명/짧은별칭/법인 prefix, 주소 중복·원천 간 동일번호·과거/폐업·소규모 체인을 나눠 공식 점포 근거와 수동 대조한다. source+license_no로 식별하고 reviewer·판정근거·검토일·불확실을 비공개 보관한다. 독립 라벨이 없는 unknown 전체를 음성으로 두고 precision/recall을 계산하지 않는다. 사례 분포/평가 분모·오탐/누락과 미판정 수를 따로 기록한다.
4. clone 검증 후 같은 백업/가드/expected plan 절차로 로컬 테스트 대상에 반영하고 API를 대조한다. 기존 세대는 보존한다. 세대3개/물리128MiB 상한을 넘으면 자동 prune하지 않고 명시 비활성 세대 정리 계획을 만든다. source ETL·publication·VACUUM은 순차 실행한다. 운영 적용은 별도 실행 기록으로 구분한다.
5. **v2 판정 코드로 v1 fingerprint 세대를 activate할 수 있다고 가정하지 않는다.** 원래 producer 규칙·이전5개 registry/소진공과 source hash를 보존한다. 후보 구형 runtime2d6b30c의 실제 clone 재활성화가 통과하기 전에는 이를 검증된 복구로 적지 않는다. source가 바뀌었거나 옛 fingerprint 재현이 안 되면 검증된 maintenance disable로pending 복귀한다. 원천까지 복구하려면 별도 전체 DB 복원 검증이 필요하며 강제 포인터 쓰기를 하지 않는다.

소규모 seed 등록과 현재 점포 인식은 별개다. PR175에서 블루보틀 포함 이름3건은unknown, 프릳츠/앤트러사이트 포함 이름은0건이었다. 공식 매장별 운영 상호/주소와 지원 모집단을 대조한 후에만 alias 또는 주소 근거를 늘린다. 이름0건을 실제 점포 부재로 해석하거나 임의 fuzzy match로 목표 건수를 맞추지 않는다.

## 9. 작업 순서와 실행 가능 경계

| 순서/작업 단위 | 지금 가능한 내용 | 선행 조건/완료 기준 |
|---|---|---|
| A. 브랜드 새 세대 검증 | 백업/clone·새 registry publication·표본/24필터·복구 검증 | 기존 정책/자료로 진행 가능. 실제 적용 결과 기록 후 공개 반영 여부 구분 |
| B. 승인 저장/CLI | 제안0013·8모델·10trigger·기본 읽기 계획/경합/disable/prune·권한·무결성 구현 | 합성 근거는 격리 DB만. 실제 근거 없으면 실DB active=None 유지 |
| C. 실제 reference 조회/API | RSS loader·typed schema·새 GET·기존 내부 함수를 실제 source 행과 연결 | B 기반/모의 승인 fixture로 구현 가능. 실자료의 미승인 항목은pending |
| D. 실제 자료의 claim 승인 | 공식 문서/답변+불변 버전/기간/구성 대조·실제 plan/승인 publication | 2절의 공식 근거가 필요. 자료 부재를 설정/API 키 문제로 취급하지 않음 |
| E. 새 AI/FE 전달 | 새 POST·서버 재계산·문장 후보/프롬프트·cache/한도·BE측FE계약 | C의 typed 계약·정확한 승인 provenance. 실자료 활성화와 synthetic 통과 구분 |
| F. migration/테스트·운영 | 원본백업·clone0013·구버전복구·권한·빈/pending/활성 실제검증 | schema guard/ready/모든 ETL/README를0013로 함께 변경. 원래0012 서버 유지와 새코드 배포 순서를 명시 |

0013 구현은 초기8표를 비활성 상태로 만들고 source 원문/기존 version CHECK를 보존해야 한다. downgrade는 새 표 데이터/활성 포인터가 있으면 거부한다. 삭제/형식 변경으로 source 증거를 소실하지 않는다. 기존 ETL·ready는 현재0012와 미래0013을 동시에 정상 head로 허용하지 않는다. 신규 코드0013을 미적용 DB에 배포하지 않는다. migration/원천 변경 잠금·디스크/복원은 clone으로 검증한 뒤 실제 절차를 실행한다.

### 9.1 0013 실제 전환/복구의 순서

현재 문서에서는 실행하지 않는다. 후속 구현의 실제 대상에서는 (1) 대상0012 BE와 ETL 쓰기 큐 중지/고정 runtime 보존, (2) 새 custom dump·clone 복원/전체 기존표 검증, (3) 실제 별도 reader 역할 생성/기존 조회 대상(alembic_version 포함) ACL 검증, (4) lock_timeout 적용0013 upgrade(새 ALWAYS trigger DDL의 SHARE ROW EXCLUSIVE, metadata UNIQUE 추가의 ALTER TABLE 잠금 포함), (4a) upgrade 뒤에야 존재하는8표에 대한 SELECT 부여를 관리 절차로 수행하고 reader의 DML/TRUNCATE/CREATE/소유권 부재를 재검증, (5)0013 code/reader process 기동→ready0013·새 API pending/기존 API 확인, (6) 근거가 있는 metric만 별도publish→캐시/실제 source 표본 대조→조회 재개 순서다. 같은 runtime에서0012/0013을 동시에 정상 head로 허용하지 않는다. 전환의 중단 구간을 기록하며 무중단을 보장하지 않는다. 기존 .env 대신 해당 새 process의 접속/expected revision 설정을 사용한다.

되돌릴 때는 새 BE/ETL 중지 후, **근거/공개/승인/component payload가 모두0·active=None**이면 bootstrap state 행은 제외해 downgrade 가능 여부를 검사하고0013의 trigger/함수/표를 제거→0012 코드/role 재기동→ready0012를 확인한다. payload가 있으면 임의DROP/downgrade하지 않고 보존 dump→검증된0012 백업을 새 DB/컨테이너에 복원→접속 전환·기존 데이터/원래 세대 검증을 따른다.0013을 유지한 채 옛 코드를 쓰는 경로는 예상 head override만으로 검증됐다고 하지 않고 clone 증거가 있을 때만 별도 채택한다. source epoch는 재upgrade/복원 때 새로 생성/회전시키고 모든 통계 승인 재검증이 필요하다. 브랜드8절의 구형 producer 복구는0012 환경의 절차이며0013에서 옛 CLI guard가 통과한다고 가정하지 않는다.

## 10. 검증 행렬과 완료 판정

| 경계 | 필수 검사 |
|---|---|
| 근거 | hash만 정상인 가짜/다른 문서·분기/관측일/도형/업종 변경·누락 claim·잘못된 authority·비공개 locator 비노출·원문 무승격 |
| 불변/경합 | 동일 지문 멱등/다른 epoch·vector 새 세대·expected pointer/ABA·중간 실패 rollback·identity 사전 txn/SET LOCAL/driver 첫 SQL·ETL 동일 잠금 순서/deadlock rollback·payload prune/공유 set 보호·trigger 비활성/소유권/reader DML·함수권한 거절 |
| revision/cache | 같은 배치 DML/TRUNCATE·버전 추가·동시 RSS snapshot·disable·cache hit 후 stale·generation 교체·다른 query echo·구형 LLM 선택 거절 |
| 매출/변화 | 현재/과거/미존재/미래 분기·다른 승인 도형·ambiguous/outside/tourism·미지원 업종·행없음/null/0·원천값 보존·브랜드/면적 미적용 |
| 인구 | 같은 grid/hour의 복수 admin·독립 구성/격자 누락·전체72 조합·scope/날짜/버전 혼합·비공개/부재/0·빈 반경·unlocated 전역 표식·숫자 상한/DefaultContext·밤0/전체0 |
| API/AI | strict query/중복/클라이언트수치422·None/pending 경계·숫자 문자열/반올림0·같은 RSS 재계산·공간/필터/기간 혼동 주입·provider0회 오류·한도 공유/취소/검증재생성 |
| 실제 적용 | 백업 실제복원·0012 시점 기존 전체 업무 표/행/원천/trigger 정의 대조·0013 clone·새/구API/AI 모의검사·실자료 표본대조·구형runtime복구·용량/계획 변동시 중단 |

각 구현 단위는 Codex 설계→실제 Claude MD 검토→Codex 대조/구현→코드 검토/필수 보완→필요한 로컬 검사→PR CI Linux/Windows/PostGIS·CodeQL→develop 정상 Squash를 따른다. FE 직접 수정·운영 배포·외부 문의는 이 문서에서 실행한 작업이 아니다. 이슈176은 설계 완료 시 닫되, 전체 활성화/공식 근거는 #115/#78에 남긴다. 구현자는 합성 fixture/코드 PASS/문서 병합을 실제 source 승인·공개 숫자·정확도·새 세대·배포 완료로 표시하지 않는다.

CLI artifact는 Git 밖의 명시 절대 파일만 받고 symlink/reparse/중복키/잘못된 UTF-8/추가필드/과도한크기를 거부한다. claim의 URL만 보고 문서를 자동 신뢰하거나 앱 요청 중 내려받지 않는다. 외부 문서 조회와 bytes/authority/적용 claim 대조는 별도 제한된 검토 단계다.

## 11. 이번 문서 작업의 검토·검증

기존 소스/모델/라우터/실행 기록과 대조해 위 설계를 작성했다. 실제 DB/공급자 인증·원천 수집·백업 생성·migration/새 코드/공개 API·AI 실행은 하지 않았다. 변경파일의 비밀값 비포함 검사는 로컬 .env를 내부 대조하되 값을 출력/저장/검수 입력에 넣지 않으며 앱 설정 로딩/환경 변경은 하지 않는다. 다음 절에 실제 Claude의 MD 변경/판정과 Codex 수용/수정을 기록하고 상대 링크/UTF-8/비밀값·변경 범위 및 기존 환경 보존을 검사한다. 변경 없는 실행 코드의 로컬 전체 검사를 반복해 기능 활성화 근거처럼 쓰지 않는다. CI 결과/통합 SHA는176 연결 PR에 기록한다.

## 12. Claude MD 검토 1차 (2026-11-16)

범위: 이 MD와 요청에 첨부된 발췌(`market_reference.py`, `population_totals.py`, `etl/localdata/runner.py`의 guard, `market_activity.py`/`risk.py`/`routers/chains.py`/`ai/chain_context.py` 일부)만 읽었다. shell/Git/DB/네트워크/공식 페이지/다른 파일은 사용하지 않았고 실제 자료·공식 근거·PG 동작을 실행 검증하지 않았다. PG 관련 판단은 PG17 문서 기준의 설계 판단이다. 이 문서에 이전 검토 이력이 없어 1차 검토로 기록한다. 본문은 수정하지 않고 아래에 판정만 추가했다.

**판정: REVISE.** 방향(hash와 공식 적용성 분리, 불변 publication, 내부 `False` 플래그 유지, 새 경로 분리, 부분합/0 채움 금지, 합성 PASS≠승인)은 타당하다. 하지만 아래 R1–R13은 구현자가 문서대로 따르면 모순, stale 오판, 교착, 용량 초과, 의미 혼동이 생길 수 있어 B/C/F 착수 전에 반영해야 한다.

### 12.1 필수 수정

- **R1 fingerprint와 source vector 모순(3·4절).** publication에 vector를 불변 저장하면서 "동일 fingerprint 재사용"이라고만 적혀 있다. fingerprint에서 vector를 빼면 drift 뒤 같은 내용을 다시 공개할 때 옛 vector를 가진 행이 재사용되어 영구 `source_changed`가 된다. fingerprint = H(rule, manifest, content SHA, source epoch+vector, 숫자 표시 규칙 버전)로 명시하고, drift 뒤에는 항상 새 publication을 만든다고 적는다.
- **R2 revision ABA.** 0013 downgrade→0012 코드의 ETL(trigger 없음)→재upgrade 경로를 타면 revision이 0부터 다시 시작한다. 그러면 이전 plan/cache key의 vector가 다시 일치할 수 있다. `reference_source_state`에 migration 때 생성하는 epoch UUID를 두고 vector·`expected_plan_sha256`·cache key에 포함한다.
- **R3 metric→source kind 의존 표 누락.** sales={boundary,sales}, market_change={boundary,market_change}, population={grid,population}을 표로 고정한다. reader는 이 kind만 비교한다. boundary ETL은 sales와 change를 모두 stale로 만든다.
- **R4 역할 분리 주장과 현재 guard의 충돌.** runner guard는 쓰기 사용자를 `spoton_app` 하나로 고정한다. "API는 SELECT만, publisher는 별도 역할"은 현재 구성에서 성립하지 않는다. 표 소유자와 실행 role이 같으면 권한 회수/SECURITY DEFINER도 같은 role 안에서는 보호가 아니다. 다음 둘 중 하나를 명시한다. (a) 새 role·guard 변경·로컬 생성·Render 영향을 0013 절차에 포함한다. (b) 초기 보장 범위를 "단일 role, trigger 기반 실수 방지"로 축소한다. (b)를 먼저 하고 (a)는 운영 절차와 함께 진행하기를 권장한다.
- **R5 불변 trigger와 prune/disable의 통과 경로 미정.** 세션 변수 우회(예: `SET app.allow_prune`)는 API 연결도 설정할 수 있어 backdoor다. 다음 규칙을 명시한다. 7표 TRUNCATE와 일반 UPDATE는 금지한다. `publication_state`만 UPDATE를 허용하되 trigger가 revision 정확히 +1과 active publication의 metric 일치를 검사한다. `source_state`는 trigger 함수만 바꾼다. DELETE는 trigger가 현재 state를 조회해 active 참조가 없을 때만 허용하고, FK RESTRICT 순서(components→approval_documents→approvals→publications, 미참조 documents)를 따른다.
- **R6 RR snapshot이 고정되는 시점.** RR snapshot은 첫 SELECT/DML에서 고정된다. 따라서 (i) `check_local_database` 같은 identity/head SELECT는 별도 트랜잭션에서 끝내고 COMMIT한 뒤 쓰기 트랜잭션을 연다. (ii) lock_timeout은 `SET LOCAL`로 설정한다. `SELECT set_config(...)`는 snapshot을 고정하므로 쓰지 않는다. (iii) 드라이버/ORM이 BEGIN 직후 SELECT를 보내지 않음을 테스트로 고정한다. 10절 "첫 SELECT 전 잠금"에 이 세 사례를 추가한다.
- **R7 잠금 순서=ETL 쓰기 순서.** 원천 SHARE의 "정해진 순서"를 ETL의 실제 쓰기 순서(version 표→행 표, kind 순서 고정)와 같은 표로 문서화한다. 순서가 반대면 publisher(SHARE Y 보유, X 대기)와 ETL(ROW EXCLUSIVE X 보유, Y 대기)이 교착한다. 운영상 순차 실행과 별개로, deadlock(40P01)도 lock_timeout과 같이 고정 오류와 전체 rollback으로 처리한다고 적는다.
- **R8 0012→0013 배포/롤백 절차 공백(9절 F).** 지금은 "순서를 명시"라고만 되어 있다. 최소한 다음 순서를 적는다: 0012 서버/ETL 정지 → custom dump와 clone 복원 검증 → upgrade(CREATE TRIGGER는 SHARE ROW EXCLUSIVE이므로 lock_timeout 적용) → 0013 코드 기동, ready=0013 확인. 롤백은 7표가 비어 있고 active=None일 때만 downgrade(trigger·함수·표 drop)→0012 코드 재기동이다. 데이터가 있으면 dump 복원 경로를 쓴다. 0012 코드는 0013 DB에서 ready에 실패하므로 그 사이 중단 구간을 명시한다.
- **R9 인구 구성 저장 규모와 32MiB 상한.** 구성 행 수는 approval당 대략 Σ격자(3×admin 수)다. 관측일별 approval마다 같은 구성을 복제하면 날짜 수에 비례해 늘어난다. 격자 수는 이번에 확인하지 않았지만 반경 조회 대상 전역 격자라면 날짜 몇 개만으로 상한을 넘을 수 있다. content-addressed `reference_component_sets`(SHA PK, grid version FK)를 두고 approval은 set FK만 갖게 한다. 이에 맞춰 표 수, trigger, 상한을 갱신한다. clone 측정 전에는 상한을 통과한다고 가정하지 않는다.
- **R10 과거 시점 인구 의미가 매출과 다름.** 매출은 과거 월에 그 분기만 쓰는데, 인구는 "T 이하 최근"이라 과거 월 요청에 훨씬 이전 관측이 섞일 수 있다. current/history를 판정하는 Query 필드를 한 곳에 정의한다. history 요청은 요청 월 안의 검증된 관측일만 쓰고, 없으면 `no_data/no_observation_in_period`로 둔다. current 요청은 T 이하 최신 관측과 age를 쓴다.
- **R11 선택 격자와 승인 universe, 상한 초과.** publisher는 grid version 전체가 구성 universe와 같음을 검증한다. reader가 고른 격자가 universe에 없으면 무결성 500으로 처리한다. 정상 반경 입력인데 구성이 100,000을 넘는 경우는 사용자 오류가 아니므로 422가 아니라 200 `not_supported/scope_too_large`로 둘지 정하고 고정한다.
- **R12 상태 매핑 규칙 누락.** projection `available`→API `reference` 매핑 표가 필요하다. restaurant 다중 업종에서는 item별 status를 두고, 항목 status는 전부 no_data면 no_data, 전부 reference면 reference, 나머지는 partial로 집계한다. `living_pop`과 `day_night_ratio`는 같은 population assembly를 쓰므로 하나만 요청해도 같은 계산이며 status/reason이 반드시 같아야 한다.
- **R13 새 AI 문맥에서 Risk 중복 제거를 구체화.** 발췌만으로는 `ChainRiskQuery`의 include 필드 존재/의미를 확인할 수 없다. risk.py 발췌상 `market_change`(official, R2)와 `day_night_ratio`(R4)는 pending만 허용된다. `include=()`가 두 placeholder를 실제로 제거하는지 코드로 확인한다. 제거하지 않으면 ReferenceInterpretContext를 만들 때 두 id를 제외하는 단계와 테스트를 추가한다. 기존 `market_change`(official 표기)와 새 `reference.market_change`의 대응표를 FE 계약 문서에 넣는다.

### 12.2 권장(비차단)

- N1 population approval의 grid version과 observation version이 참조하는 grid version을 복합 FK로 일치시킨다. 원천 version이 boundary를 참조한다면 sales/change도 같은 방식으로 맞춘다.
- N2 같은 분기라도 sales와 change의 승인 boundary가 다를 수 있다. `judge_market`은 metric별로 호출하고 결과를 서로 재사용하지 않는다.
- N3 `select_quarter`의 입력 상한이 400이므로 publisher가 metric당 승인 분기 수 ≤400을 검사한다.
- N4 current 매출에도 `source_quarter_lag`를 두어 오래된 분기를 드러낸다(인구 age와 대칭).
- N5 FK RESTRICT 때문에 승인된 원천 version은 ETL 정리 과정에서 삭제할 수 없다. 이 점을 ETL 정리 문서에 반영한다.
- N6 `PopulationScope.space_id`의 정의(예: SHA256(grid version, 정렬된 grid IDs, 반경, 정규화된 중심))를 고정하고 응답/로그에 노출하지 않는다.
- N7 요청 시 trigger guard는 `pg_trigger.tgenabled='A'`와 함수 정의 hash 비교로 구체화하고, 같은 RSS 안에서 검사한다.
- N8 "RSS"는 처음 나올 때 READ ONLY REPEATABLE READ snapshot session으로 정의한다.
- N9 공개 상권 명칭을 반환할지(사용자 이해 목적)와 코드를 노출하지 않는 원칙을 구분해 결정한다.

### 12.3 유지 확인과 다음 판정 조건

근거 계약(2절), UPDATE 승격 금지, 행 기반 expected 금지, 부분합 금지, 숫자 문자열/반올림0, provider 0회 오류, 비공개 locator 비노출, 브랜드 v1 복구를 가정하지 않는 원칙(8절 5)은 그대로 유지할 것을 권한다. R1–R13을 본문에 반영하고 Codex 수용/수정 내역을 이 절 아래에 남기면 2차 검토에서 PASS 여부를 다시 판정한다. 이 검토의 PASS나 REVISE는 실제 원천 승인, 공식 근거 확인, 활성화 근거가 아니다.


## 13. Codex 대조와 수정 결정

실제 Claude 1차 검토는2026-11-16T01:35:50Z~01:38:46Z exit0/is_error=false/3turns, MD SHA `d98fd0d6566f43a91fdd8125a646a9c893cef9866127861edbcfee0fca24e382`→`53e479aa7eaa686f773ed77e7e1080701eb4498797467d02bb13983840921948`이었다. MD 직접 수정·제공 소스 SHA 보존·permission_denials0을 확인했고 REVISE 이유를 Codex가 실제 소스/기존 사용자 문서와 대조했다.

| 검토 지적 | Codex 반영/판단 |
|---|---|
| R1/R2 | 지문에 source epoch+vector/format을 포함하고 drift 뒤 새 publication으로 고정. 재upgrade/백업 복원 epoch 회전과 재검증을 추가 |
| R3 | metric별 의존 kind를 명시해 boundary→매출/변화, grid/population→인구의 보수적 무효화 범위를 고정 |
| R4 | 권한 축소(b) 대신 실제 분리(a) 채택. writer spoton_app guard는 유지하고 별도 비소유 API reader의 생성/검증/접속 전환을 후속 절차에 명시 |
| R5 | 세션 플래그 backdoor 없이 state UPDATE·revision/metric 검사, active/공유set 보호, 참조 없는 payload만 순서대로 prune하는 경로를 명시 |
| R6/R7 | identity/head 사전 txn 종료, SET LOCAL·driver 첫 SQL 검사, version→행/grid→관측 잠금 순서와40P01 전체 rollback 반영. importer INSERT 순서를 실제 코드로 대조 |
| R8 | 0012 중지/백업/clone→role/0013→ready/API→재개 순서와 중단 구간, payload 없는 downgrade·payload 있는 복원 경로, 옛 producer guard 제한을 명시 |
| R9 | 공유 content-addressed component_sets를 추가해8표로 수정. mask로 시간별 구성을 보존하고 재사용 자체를 새 날짜의 공식 근거로 취급하지 않음 |
| R10 | 원래 사용자 분석 보고서의 같은-요청월 기준과 대조해 current/history 모두 해당 월 안의 T이하 최신 관측으로 구체화. 기간이 없으면no_data이며 다른 달 대체 금지 |
| R11 | 전역 universe 완전 일치·선택 격자 포함 검사와scope 상한 초과200 not_supported를 명시 |
| R12 | source projection/업종별 상위 상태 매핑 수용. 단 두 인구 지표의 최종 status가 항상 같아야 한다는 제안은 밤0 반례 때문에 수정: 동일 assembly/원천 가용성은 공유하되 living_pop은 실제0을reference로, 배수만no_data로 표현 |
| R13 | 실제 risk.py의 optional append 루프를 확인해 include=()에서 두 pending placeholder가 빠짐을 확인. 새 AI context·FE 선택 ID 대응과 회귀 조건을 명시 |
| N1~N9 | 복합 FK/필요 metadata UNIQUE, metric별 별도 도형 판정,400분기 상한,분기 lag,원천 FK 삭제 제한,비공개 space_id,같은RSS trigger hash,용어·상권 식별자 공개 범위를 반영 |

도형/기간/인구 합산의 공식 근거는 여전히 미확정이며 이 수정으로 확보된 것이 아니다. 기존 소스/DB/환경/FE를 변경하지 않았고0013/새 endpoint/역할은 미구현 설계다. 확인된 다음 구현 순서는 브랜드 clone/새 세대 검증(A)과 승인 저장/CLI(B), 실제 loader/API(C)다. 공식 자료의 실제 승인(D)은2절 자료가 필요하며 설계만으로 완료 표시하지 않는다.

## 14. Claude MD 최종 검토 (2026-11-16)

범위: 이 MD, 요청에 첨부된 기존 소스 발췌(`market_reference.py`, `population_totals.py`, `etl/localdata/runner.py` guard, `schemas/market_activity.py`, `schemas/risk.py`, `services/risk.py`, `services/spatial_stores.py`, `schemas/chains.py`, `etl/living_pop/repository.py`, `routers/chains.py`, `ai/chain_context.py` 일부), Codex 증거 요약만 사용했다. shell/Git/DB/네트워크/공식 페이지/다른 파일/에이전트는 사용하지 않았다. 실제 자료, 공식 근거, PG 잠금 동작, 역할 권한을 실행해 확인하지 않았다. PG 판단은 PG17 문서에 기반한 설계 판단이다. 12절(1차)과 13절(Codex 대조)은 그대로 두었다.

### 14.1 1차 지적과 Codex 수정 대조

| 항목 | 본문 반영 위치 | 판단 |
|---|---|---|
| R1/R2 | 3절 fingerprint·epoch 단락, 9.1 | 해소. epoch+vector가 지문에 포함되고, re-upgrade/복원 때 epoch를 회전한다. 재활성화 시 stale 세대 문제는 이번 검토에서 보완했다(14.2-a) |
| R3 | 3절 의존 vector | 해소 |
| R4 | 3절 권한·reader role 단락 | 해소. (a) 실제 분리를 채택하고 소유자 악의 조작은 보장 밖으로 명시했다. 1차 권고는 (b) 우선이었지만 (a)가 더 강하고 절차도 구체적이어서 수용한다. 8표 GRANT 순서는 보완했다(14.2-d) |
| R5 | 4절 불변성 단락 | 대체로 해소. GUC 우회는 없고, prune 순서와 공유 set 보호가 있다. 동일 소유자 구조에서 source_state 경로를 구분하는 방식은 보완했다(14.2-b) |
| R6/R7 | 4절 잠금 단락 | 해소. 사전 txn 분리, SET LOCAL, driver 첫 SQL, 잠금 순서 = importer INSERT 순서, 40P01 rollback이 들어갔다. 첨부된 `living_pop/repository.py`의 grid version→grid rows→population version→observation rows 순서와 맞는다 |
| R8 | 9.1 | 해소. 중단 구간, payload 유무별 rollback 경로, 옛 producer guard 제한이 명시됐다 |
| R9 | 3절 component_sets | 해소. 저장량은 clone 측정 전까지 미확정으로 유지된다 |
| R10 | 5절 인구1, 5절 끝 단락 | 해소(수정 수용). 1차 권고(current는 T 이하 무제한)와 다르지만 사용자 분석 보고서의 같은-월 문구를 근거로 했다는 Codex 대조를 받아들인다. 그 원문은 이번에 직접 보지 않았다 |
| R11 | 5절 인구2·4 | 해소. 선택 격자0은 `PopulationScope.min_length=1` 때문에 scope를 만들기 전에 단락해야 하며, 본문의 no_selected_grids가 이와 맞다 |
| R12 | 6절 상태 매핑 | 해소(수정 수용). 밤0일 때 living_pop은 reference, ratio는 no_data인 반례가 타당하다. 동일 status를 강제하라는 1차 권고는 철회한다 |
| R13 | 7절 | 해소. 첨부 `services/risk.py`는 `query.include`에 있는 항목만 append하고, flags.missing은 append된 항목에서 계산하므로 include=()이면 두 id가 빠진다. `ChainRiskQuery.include` 기본값 `()`도 확인했다 |
| N1~N9 | 3·5·6절 | 반영됨 |

### 14.2 이번 검토에서 본문을 직접 고친 부분

- (a) 3절: 비활성 세대를 재활성화할 때 저장된 epoch+vector가 현재 값과 다르면 거부하도록 했다. 그렇지 않으면 포인터가 즉시 `source_changed`가 될 세대를 가리킬 수 있다.
- (b) 4절: 소유자와 writer가 같은 role이면 권한으로 "trigger 경로만 source_state 변경"을 강제할 수 없다. 그래서 `pg_trigger_depth()>1` guard trigger와 관리 절차 전용 rotate_epoch로 구체화하고, 이것이 실수 방지라는 점을 명시했다.
- (c) 5절: 매출/변화가 ambiguous/outside일 때의 status/reason을 `no_data/market_ambiguous`·`no_data/outside_market`으로 고정했다.
- (d) 9.1: 기존 (3)은 0013 upgrade 전에 존재하지 않는 8표의 ACL을 검증하는 순서였다. 이를 (3) 역할 생성과 기존 표·alembic_version ACL, (4a) upgrade 뒤 8표 SELECT 부여와 재검증으로 나눴다. metadata UNIQUE 추가에 따른 ALTER TABLE 잠금도 lock_timeout 범위에 명시했다.
- (e) 9절 표: "7모델"을 3절의 8표와 맞춰 "8모델"로 고쳤다.

### 14.3 남는 사항(비차단, 구현 단계에서 확인)

- population 승인 관측일 수에는 분기 400개 같은 명시 상한이 없고 32MiB 총량만 있다. 구현 때 metric별 관측일 상한을 정하고 테스트할 것을 권한다.
- writer RR 트랜잭션은 잠금을 먼저 잡으므로 40001이 나올 가능성은 낮다. 그래도 40P01/lock_timeout과 같은 고정 경합 오류로 처리하도록 테스트에 포함할 것을 권한다.
- 격자별 3원천×24시간 구성이 모두 있어야 한다는 조건 때문에, 일부 원천이 구조적으로 없는 격자가 있으면 해당 grid version 전체를 승인할 수 없다. 이는 의도된 보수적 동작이다. 실제 universe에서 어떻게 되는지는 D 단계 근거와 clone 측정으로 확인해야 한다.
- 공식 도형/기간 정의, 행정동 가산성, 격자 관측일 적용의 공식 근거는 여전히 없다. 해당 지표는 실데이터에서 pending으로 유지된다. hash 일치, 코드 PASS, 합성 fixture, 이 검토 판정은 원천 근거가 아니다.

### 14.4 판정

**판정: PASS (설계 문서 기준).** R1–R13과 N1–N9는 본문에 구체적으로 반영됐다. Codex가 1차 권고와 다르게 처리한 R4, R10, R12에는 타당한 근거가 있다. 이번에 찾은 잔여 결함(a)–(e)는 본문에 직접 고쳤다. 데이터 권위와 hash의 분리, 신뢰 경계(별도 reader, 클라이언트 승인 불가, provider0회), FK와 불변성, epoch/vector 기반 cache 격리, 잠금 순서, RSS 단일 snapshot, 0012→0013 전환과 rollback, current/history와 공간·필터 의미, 인구 완전성과 비공개 보존, 새 typed API/AI의 하위 호환, 개인정보와 상한은 B/C/F 구현에 착수할 수 있을 만큼 구체적이다. 이 PASS는 설계 검토 판정일 뿐이다. 실제 원천 승인, 공식 근거 확인, 새 세대 공개, 배포, 활성화의 근거가 아니며 14.3의 사항은 구현 PR 검토에서 다시 확인한다.


## 15. Codex 최종 대조·문서 검증

실제 Claude 최종 검토는2026-11-16T01:48:18Z~01:50:05Z exit0/is_error=false/8turns, MD SHA `6fad4361e19f00313c65ffa2c2629e4284b531eb0d455ac434c557e77eb3c5e9`→`40f97ecfc62e0fc39cea079fcd097de4c36047688c9ec88f6942329520c09026`였다. MD 직접 변경·제공 소스 SHA 보존·permission_denials0을 확인했다. Codex가14.2(a)~(e)의 실제 본문 변경과 이유를 대조해 수용했다.

관리 경로 선택을 구현자가 추측하지 않도록14.2-b의 허용안 중 복원/migration 관리 단계를 채택해 rotate_epoch의 단일 트랜잭션 잠금·guard 해제/복구/실패 rollback을 명시했다. 정상 API/publisher에서 epoch를 바꾸거나 세션 GUC로 우회하지 않는다.14.3의 비차단 사항 중 관측일400개 자원 상한과40001 전체 rollback도 고정했다. 구조적으로 기대 원천이 없는 격자의 실제 처리 가능성은 근거D 단계와 clone 측정 전까지 여전히 미검증이며 임의0/기대구성 축소로 통과시키지 않는다.

변경은 설계/README/CLAUDE/작업계획4개 Markdown뿐이다. 기존 source/application/migration·현재DB0012/공개 응답/환경/FE/서버/Render/Task/runtime은 변경하지 않았다. UTF-8·변경 범위·기존 환경 키 비포함·새 상대 링크·git diff 검사를 통과했고 기존 미해결 링크1개를 보존했다. 실행 코드의 기존 로컬2440통과는PR175 기록이며 이번 설계의 새 실행 검증으로 재사용하지 않는다. 이번 CI는 현재 문서 head의 baseline 회귀 검사이고 실제 기능 활성화 근거가 아니다. 최종 CI/통합·보존 결과는176 연결 PR을 따른다.
