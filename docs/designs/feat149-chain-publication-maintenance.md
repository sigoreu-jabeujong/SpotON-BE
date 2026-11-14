# 브랜드 공개 세대 관리 명령 (#149)

기준 develop2abda89. 사용자의 다음 BE 구현 지시와 #145 실제 Claude 검수의 운영 후속(3세대 한도·prune/pending 복귀 부재)을 따른다. FE·.env·기존 서버·원본/운영 DB·Render는 변경하지 않는다. head0012·테이블/공개 API 계약을 유지한다.

## 1. 범위와 명령

`python -m etl.chains.maintenance --action list|disable|prune`를 추가한다. 기본은 READ ONLY RR 계획이다. list는 상태/보관 세대/건수·현재 물리 용량만 보여주고 쓰기 옵션을 받지 않는다. disable은 active state만 삭제해 정상 guard 아래 pending으로 돌리며 세대/판정은 보존한다. prune은 `--generation UUID`로 지정한 비활성 세대만 삭제한다. 자동 최신/오래된 세대 선택·자동 삭제·암묵 disable·TRUNCATE·CASCADE·상한 확대는 없다.

쓰기에는 `--write --expected-plan <dry-run expected_plan_sha256> --expected-active <UUID|none>`이 모두 필요하다. prune 대상은1~3개·정규 UUID·중복 불가이고 활성 세대가 하나라도 포함되면 전체 거절한다. disable/list에는 대상 인자를 받지 않는다. 인자/해시/활성 UUID·지원 action 검증은 DB 연결 전에 끝낸다. 기존 `validate_local_target`/`check_local_database`의 loopback spoton_dev/spoton_app·비슈퍼유저·PostGIS/head0012를 유지한다. 관리용 HTTP API는 만들지 않는다.

## 2. 계획과 실행 가드

계획은 action·정렬된 대상·현재 state의 generation/validated_source_revision/activated_at·모든 보관 publication의 전체 메타·prune 대상의 브랜드/판정 전체 내용과 실제 행수의 digest를 묶는다. raw 이름/주소·registry 내용·license/semas ID는 출력하지 않고 내부 streaming hash에만 사용한다. UUID/date/datetime은 UTC/ISO로 정규화하고 JSON 키를 정렬한다. publication의 기대 known_count와 실제 행수 차이는 보고하되 손상된 비활성 세대도 명시 계획 아래 정리할 수 있다. 대상이 없거나 활성 포인터가 가리키는 publication이 없으면 계획을 거절한다.

write가 hash/active 모두 일치할 때만 실행한다. 활성 UUID만 보는 CAS와 달리 activated_at까지 지문에 포함해 같은 UUID로 돌아온 ABA 전환을 감지한다. 보관 세대/대상 내용이 바뀌면 계획도 바뀐다. 물리 bytes는 VACUUM 등에 따라 변할 수 있어 표시만 하고 지문에서는 제외한다. 대상/포인터가 이미 바뀐 오래된 쓰기는 no-op으로 둔갑시키지 않고 거절한다. 재계획 뒤 이미 pending이면 disable은 DML 없는 no-op이다.

## 3. 잠금·원자성·읽기 보존

write는 RR 설정/timeout 뒤 **어떤 SELECT보다 먼저** chain_publication_state EXCLUSIVE → chain_publications·chain_publication_brands·store_chain_classifications SHARE ROW EXCLUSIVE를 잡는다. #145 publish/activate가 state를 먼저 잠그므로 직렬화된다. metadata 직접 writer도 후자 잠금으로 차단한다. source stores/원천·legacy 표에는 쓰기/SHARE 잠금을 추가하지 않는다. 초기 가드는 잠금 뒤 수행한다. lock_timeout5초/statement_timeout60초다.

ORM의 비한정 테이블명이 잠근 public 표와 다른 임시/다른 스키마 표로 해석되지 않도록 SELECT 전에 LOCAL search_path=pg_catalog,public,pg_temp로 고정한다. 임시 동명 표가 존재하는 연결에서도 public 대상만 삭제하고 임시 표는 보존하는 실제 DB 검사를 추가한다.

disable은 state 한 행만 삭제한다. prune은 각 명시 대상의 Evidence→Brand→Publication 순서로 같은 트랜잭션에서 삭제하고 state/source-state는 보존한다. 각 실제 삭제 행수를 계획과 대조한다. 실패/누락/외부 FK/중간 예외는 전체 rollback이다. 활성 세대는 자동 전환/삭제하지 않는다. 중도 실패를 주입한 테스트로 이전 포인터와 모든 대상이 남음을 확인한다.

EXCLUSIVE/SHARE ROW EXCLUSIVE는 일반 SELECT의 ACCESS SHARE와 호환된다. 기존 RR reader는 자기 snapshot의 state/이전 판정 행을 계속 읽고 새 reader만 disable 후 pending을 본다. active archive와 기존 publisher가 경합하면 잠금 뒤 재계산으로 오래된 계획을 거절한다. new v2 AI는 매번 재계산하고 snapshot/private version이 달라져 이전 선택 캐시와 섞이지 않는다.

근거: [PostgreSQL17 잠금 표](https://www.postgresql.org/docs/17/explicit-locking.html), [MVCC와 일반 VACUUM](https://www.postgresql.org/docs/17/routine-vacuuming.html). 이 해석은 해당 문서를 바탕으로 한 설계 판단이며 실제 PostGIS 동시성 테스트로 확인한다.

## 4. 보존·용량·복구 한계

정리는 비활성 증거를 삭제하는 운영 동작이다. 사용 전 운영자가 DB 백업·원천 snapshot/registry를 보관하고 출력 계획/결과를 외부 실행 기록에 남겨야 한다. 이번 구현 검증에서는 원본/기존 실제 검증 DB의 세대를 삭제하지 않고 폐기 가능한 새 복제 DB/합성 DB만 사용한다. 관리자 동의 없이 운영 DB 정리를 실행하지 않는다.

DELETE는 논리 행을 제거할 뿐 파일/인덱스 물리 bytes 감소를 보장하지 않는다. 기존3세대/128MiB 제한을 유지하며 통계는 신규 세대 적재 때 기존 ANALYZE를 따른다. 필요하면 별도 운영 절차에서 일반 VACUUM으로 공간을 재사용한다. 이 명령은 VACUUM FULL/REINDEX/물리 축소/자동 VACUUM을 실행하지 않는다. 물리 용량이 계속 한도 이상이면 다음 publication은 여전히 거절하며 숫자만 낮춰 통과시키지 않는다.

disable은 잘못된 판정의 공개 포인터를 내리는 동작이며 guard/trigger 손상을 고치지 않는다. trigger 비활성이면 v2는 기존대로500이고 guard 복구/전체 재검증이 필요하다. 재활성화는 기존 publication --activate 또는 재공개를 통해 registry/snapshot·현재 원천 hash를 재검증해야 한다. 과거 세대 삭제를 자동 복원하거나 과거 데이터로 rollback한다고 주장하지 않는다.

## 5. 검증·진행 기준

새 관리 CLI 외 API/FE/migration을 변경하지 않는다. 단위 검사: DB 전 인자 거절·순서/정규화/계획 변조·정적 고정 SQL. PostGIS:3세대 채움→4번째 거절→inactive prune→4번째 성공, active 포함/잘못된 plan·active 거절, target 내용/ABA 변경 감지, pending/no-op/재활성화, 실패 주입 rollback, 오래된 RR reader와 새 reader, 잠금 대기 뒤 stale plan 거절, 원본/legacy/원천 revision 보존.

일반1944/PostGIS286 회귀·ruff/format/mypy를 완료하고, 필요 시 새 폐기용 실자료 복제에서 해시/행수/원래 활성 보존·용량/재공개 검증을 수행한다. Claude 추가 검수는 현재 사용 한도가 남아 있으므로 실제 시도/결과만 기록한다. 설계/코드 PASS를 만들지 않고, 검수가 미완료이면 구현 초안과 테스트를 리뷰 가능한 Draft PR로 남겨 병합과 구분한다.

## 6. 실제 검수·검증 기록

설계 초안. #145 검수된 state 잠금·보존 상한의 운영 후속에서 출발했으며 새 세부 설계의 Claude 검수/완료 판정은 아직 없다.

### 6.1 Claude 설계 검수 시도와 Draft 제한

실제 Claude Code Read/Edit 전용 검수를 UTC2026-11-14 19:01:56~19:01:59에 시도했다. exit1·is_error=true·1turn·denial0, 메시지 `You've hit your 5-hour limit · resets 5:10am (Asia/Seoul)`으로 끝났다. MD 입력/출력 SHA는 모두d5228950b2dae93a2af6a6b1fe78cb457cb6ef3f5c75401c4167bde6b74352dc다. 새 설계/코드가 Claude 검수를 통과했다고 표시하지 않으며 한도 우회·다른 계정/키 전환을 하지 않았다.

[BE 작업계획](../be-work-plan.md)의 기본 순서는 “Codex 설계 MD → Claude Code 검토·MD 직접 수정 → Codex 구현”이다. 따라서 아래 작업은 검수 가능한 **구현 초안/격리 검증**이며 정식 검수 완료나 병합/운영 적용이 아니다. 사용자에게 추가 승인이나 같은 키를 요청하지 않고 코드/실제 증거를 Draft PR에 준비한다. 한도 해제 후 이 설계와 코드를 실제 Claude로 검수하고 발견 사항을 수정·검증한 뒤 병합 조건을 판단해야 한다.

### 6.2 Codex 구현 초안·실제 격리 검증

- 신규 CLI1파일과 단위/통합 테스트2파일, 설계/관리 문서만 추가했다. 기존 API·FE·DB 모델/migration·head0012·.env·기존 서버·원본/운영 DB를 변경하지 않았다. Codex가 내용/활성 포인터/ABA 가드, 부모/자식 삭제 순서, state 잠금 직렬화와 실패 rollback을 직접 대조했다.
- 일반 전체1957개 통과(기존1944+신규13). PostGIS 전체293개 통과 뒤 외부 FK 검사를 포함한 신규 통합8개와 첫 PR CI의294개가 통과했다. 이후 임시 테이블의 대상 가림을 보강해 관리 통합9개를 다시 통과했다(최종 검증 집합295개, 마지막 CI에서 재확인). ruff/format·mypy183파일 통과. 단순 SQL 호출 문자열을 재현하는 테스트 대신 실제 DB의 대기/읽기 동시성 검사를 유지했다.
- 통합8개:3세대→4번째 거절→inactive prune→4번째 성공, 활성 API 응답 보존과 source/원천 revision 동일, pending/no-op/동일 입력 재활성화, active/missing/plan/CAS 거절, 실제 자식 내용 변경 지문, disable→activate 같은 UUID의 ABA 감지, 자식 삭제 후 실패 주입 rollback, 기존 RR reader의 퇴역 행 조회와 새 reader pending, publisher 잠금 대기 후 새 포인터 검사, 외부 FK23503에서 자식까지 rollback을 확인했다. 출력에 원문 점포명/주소/인허가·URL이 없음을 단언했다.
- 기존 실자료 검증 DB를 템플릿으로 새 폐기용 DB spoton_it_98fd63d39b62를 생성해 별도 실행했다. 비활성 publication1개·브랜드2074개·판정8778개만 정리하고 원래 활성 포인터를 보존했다. 그다음 disable은 state1행만 내렸고 재계획 후 재실행은 no-op이었다. v2 엄격 chain 조회200/pending/0건을 확인했다.
- 점포689440행의 모든 필드/좌표·legacy 브랜드5테이블의 전체 행 hash와 원천 revision이 정리/disable 전후 동일했다. 기존 실자료 검증 DB의 활성 포인터·세대 수·원천/legacy hash도 그대로여서, 삭제는 새 폐기용 복제본에만 한정됨을 확인했다. 기존 원본 spoton_dev/이전 검증 DB는 삭제하지 않았다.
- 실제 복제 실행25.672초. 세 publication 표의 physical bytes는14,852,096→14,852,096으로 같았다. 논리 정리와 물리 공간 회수를 구분하고 FULL/자동 VACUUM·용량 상한 완화를 하지 않았다. 생성한 폐기용 DB 식별자/검증 보고서는 저장소 밖 비공개 검증 폴더에 보관했다.
- 마지막 자체 대조에서 임시/다른 스키마의 동명 표가 비한정 ORM 질의를 가릴 수 있어 LOCAL search_path를 pg_catalog,public,pg_temp로 고정했다. public 표4개를 임시 표로 복사한 연결에서도 public 비활성 세대만 삭제되고 임시 표는 그대로임을 검증했다. 기존 API/연결 환경은 수정하지 않는다.

상태: 코드/검증 자료 준비, **Claude 새 설계·코드 검수 대기**. Draft PR의 CI/CodeQL을 확인하되 CI 성공을 Claude 검수/병합 완료로 대체하지 않는다.
