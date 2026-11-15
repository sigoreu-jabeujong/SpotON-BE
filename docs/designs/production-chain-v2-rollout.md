# 운영 브랜드·체인 v2 전환 (2026-11-15)

사용자는 FE PR60 병합/배포 완료 뒤 제안한 다음 단계인 운영 BE v2 배포와 공개 FE v2 활성화를 승인했다. 로컬 .env·원본 자료·기존 로컬 서버·유료 자원은 유지한다. 검수된 BE a0626f3/schema0012와 FE3c09867의 계약을 실제 운영에 반영한다. 앱 시작 시 migration이나 ETL을 추가하지 않는다.

## 사전 확인

Render spoton-be-free/srv-dbri09k9v7es73clfpl0, spoton-db-free/dpg-dbrhh4rm8hqs73d2mlgg-a, Singapore/Free를 명시 검사했다. 현재 live05790fa, schema0011, DB761124531 bytes, stores689440, public21표, 쓰는 세션0, 조회 역할21표 SELECT, 기존 환경17개/LLM 연결/풀1이다. 운영 소유 계정은 spoton_owner이고 앱은 spoton_api 조회 역할이다. 이 값과 이전 live/환경 전체 hash를 작업 가드로 쓴다. 자격증명·외부 IP·점포 원문은 저장소/Claude/표준출력에 넣지 않는다.

## 백업과 오프라인 판정

1. 운영에서 원천 ETL을 실행하지 않는다. READ ONLY REPEATABLE READ snapshot을 export하고 같은 snapshot의 public 전 표 행 hash와 custom pg_dump를 저장소 밖에 보관한다. 행은 PostgreSQL md5(row(t.*)::text), 클라이언트 ASCII 정렬 후 SHA256으로 비교한다. geometry 출력의 EWKB도 행에 포함되므로 좌표 변경을 놓치지 않는다. 인덱스·제약·기존 트리거·시퀀스를 별도 보존한다. 서버에서 대규모 정렬/임시 파일을 만들지 않는다.
   - (검수 보완) `row(t.*)::text`는 세션 설정에 따라 문자열이 달라진다. 운영·복원본·운영 트랜잭션 재대조의 **모든 hash 세션**에서 첫 snapshot 전에 `SET LOCAL TimeZone='UTC'`, `DateStyle='ISO, YMD'`, `IntervalStyle='postgres'`, `extra_float_digits=1`, `bytea_output='hex'`를 같은 값으로 고정하고 그 값을 증거 JSON에 기록한다. 고정하지 않은 비교의 일치/불일치는 증거로 쓰지 않는다.
   - (검수 보완) `pg_export_snapshot()`을 내보낸 트랜잭션은 pg_dump 종료까지 열려 있어야 한다(현재 backup.py는 `with` 안에서 dump하므로 충족). 운영 서버의 `idle_in_transaction_session_timeout`·`statement_timeout`이 hash/dump 시간보다 짧지 않은지 preflight에서 읽어 기록한다. 실행 중 autovacuum은 행 내용을 바꾸지 않으므로 허용한다.
   - (검수 보완, 차단 조건) 덤프 이미지의 pg_dump 메이저 버전은 운영 server_version 이상이어야 한다(`postgis/postgis:17-3.7` 고정). 운영이 18 이상이면 같은 메이저의 고정 digest 이미지로 바꾸기 전에는 진행하지 않는다. 운영 PostGIS 버전과 복원본 PostGIS(3.7)도 기록하고, 다르면 아래 3·6단계의 운영 재계산 대조를 필수로 한다.
2. 운영과 다른 새 이름 spoton_it_UUID 로컬 DB를 만들고 PostGIS를 준비한 뒤 --single-transaction/--no-owner/--no-privileges/role spoton_app으로 실제 복원한다. 21표 전체 행 hash가 snapshot과 같아야 한다. 원래 로컬 spoton_dev는 바꾸지 않는다.
   - (검수 보완) 관리자가 미리 만든 PostGIS의 `spatial_ref_sys`는 관리자 소유라 spoton_app 역할 복원에서 사용자 추가 SRID 행 INSERT나 `COMMENT ON EXTENSION`이 권한 오류로 중단될 수 있다. `--exit-on-error`로 실패가 드러나는 것은 정상 동작이며, 우회하려고 복원 역할을 superuser로 바꾸거나 오류 무시 옵션을 쓰지 않는다. 실패 시 원인 항목만 기록하고 설계를 다시 검수한다.
   - (검수 보완) PostGIS 버전 차이로 `spatial_ref_sys` hash만 다를 수 있다. 이 경우 해당 표를 조용히 비교에서 빼지 않고 차이 행 수·원인을 기록한 뒤 진행 여부를 재검수한다. 나머지 20표는 반드시 일치해야 한다.
3. 복원본에 검수된0012를 적용하고 기존 registry·소진공202609 snapshot으로 publication 계획/쓰기를 수행한다. 기존 로컬 CLI guard를 변경하거나 무력화하지 않는다. 별도 단발 작업은 loopback·격리 clone 이름·spoton_app·0012·source revision0·빈 publication을 명시 확인한 뒤 기존 `publication.apply`의 계획/expected fingerprint/active none/verify 로직을 쓴다. publication 생성은 오직 복원본에서 수행한다. 새5표 외 기존 표 hash는 그대로여야 한다. clone은 재현 증거로 보존한다.
   - (검수 보완, 차단 조건) 이 단발 작업 스크립트의 원문은 이번 검수 입력에 없었다. `run()`의 `validate_local_target`을 건너뛰고 `apply()`를 직접 부르는 구조라면 `locked()`/`check_local_database()`를 **수정 없이 그대로** 호출해야 하며, 그 함수가 DB 이름 spoton_dev 등을 요구해 clone에서 거절되면 guard를 monkeypatch하지 말고 동등 이상의 명시 검사(loopback·`spoton_it_[0-9a-f]{12}`·current_user=spoton_app·head0012·revision0·state/publication 0행)를 별도 함수로 둔 뒤 실제 Claude 코드 재검수를 받는다. 재검수 전에는 실행하지 않는다.
   - (검수 보완) registry/소진공 snapshot 파일 SHA256, 결과 generation·fingerprint·plan_sha256·store_sha256·row_count·known_count·status별 건수를 기록한다. 운영 원본은 로컬 spoton_dev(#104 위치 보정 등)와 다를 수 있으므로 #151 로컬 수치(추정8778 등)와 같다고 가정하거나 검증 기준으로 하드코딩하지 않는다.
   - (검수 보완) clone에서 새4표+chain_source_state의 `pg_total_relation_size` 합(TOAST·인덱스 포함)과 publication 쓰기 전후 `pg_database_size` 차이를 측정해 7단계 공간 판정 입력으로 쓴다.
   - (검수 보완) 롤백 수단 사전 검증: 이 0012 clone에 **이전 BE 05790fa**를 `DATABASE_EXPECTED_REVISION=0012`·조회 전용 역할로 로컬 실행해 ready/v1 주요 조회가 정상인지 확인한다. 확인 전에는 9단계의 "05790fa 재배포 복구"를 검증된 롤백으로 표기하지 않는다. 같은 clone에서 새 BE a0626f3의 ready/v2 status도 확인한다.

## 운영 적용의 한 트랜잭션

4. 작업 스크립트는 Render DB ID/Free/이름·외부 verify-full·DB/소유자·head0011·백업/복원 성공·기존 환경/live 일치를 다시 확인한다. 운영에서 기존 CLI의 local guard를 우회 실행하지 않는다. 복원본에서 검증한 새 테이블 내용만 운반하는 별도 명시 운영 절차다.
5. SQLAlchemy 한 Connection/transaction에 Alembic connection을 주입한다. REPEATABLE READ 설정 뒤 첫 snapshot 전에 기존 업무 표에 SHARE 잠금을 걸어 원천 쓰기를 막고, 운영 기존21표 hash와 백업을 재대조한다. lock timeout5초, 작업 SQL180초를 쓰고 원래 앱 SQL10초와 구분한다. 일반 조회의 ACCESS SHARE는 계속 허용된다. 경합이면 전체 중단하며 무조건 재시도하지 않는다.
   - (검수 보완) 순서를 고정한다: ① `execution_options(isolation_level="REPEATABLE READ")` 또는 첫 문장 `SET TRANSACTION ...` ② `SET LOCAL` statement/lock timeout·hash GUC ③ 기존 업무 표 전체(alembic_version 제외 20표, 이름을 명시 목록으로 고정하고 preflight 표 목록과 일치 확인)에 `LOCK ... IN SHARE MODE` ④ 그 뒤 첫 SELECT(=snapshot)로 격리 수준·head0011·hash 재대조 ⑤ Alembic. LOCK·SET·SHOW는 snapshot을 만들지 않지만 SELECT·Alembic의 alembic_version 조회는 만든다. SQLAlchemy 연결 초기화 문장이 같은 트랜잭션 안에서 먼저 실행되지 않았는지(`connection.in_transaction()` 직전 확인) 기록한다.
   - (검수 보완) Alembic은 주입된 외부 트랜잭션이면 자체 commit을 하지 않는다(`migrations/env.py`가 `context.begin_transaction()` 사용). 작업 스크립트는 `command.upgrade(cfg,"0012")` 후에도 같은 Connection이 transaction 상태인지 확인하고, commit은 7단계 검증을 모두 통과한 뒤 작업 스크립트가 한 번만 한다.
   - (검수 보완) migration의 CREATE TRIGGER/ENABLE ALWAYS는 stores에 SHARE ROW EXCLUSIVE를 요구한다. 자기 트랜잭션의 SHARE에서 상향되므로 조회(ACCESS SHARE)와 충돌하지 않지만 실행 중 autovacuum(SHARE UPDATE EXCLUSIVE)과 충돌한다. 시작 직전 `pg_stat_progress_vacuum`에 대상 표가 없음을 확인하고, lock timeout이면 중단 후 원인 기록·사람 판단으로만 재시도한다.
   - (검수 보완) stores 소유자가 spoton_owner인지(CREATE TRIGGER 권한) preflight에서 확인한다. 아니면 중단한다.
6. 같은 트랜잭션에서0011→0012, ALWAYS source trigger·revision0 확인, clone의 chain_publications→chain_publication_brands→store_chain_classifications→chain_publication_state를 COPY한다. migration이 만든 chain_source_state(id1/revision0)는 재삽입하지 않는다. 판정은 source/인허가/전 입력 hash가 포함된 불변 snapshot이며 source 전 표 hash가 같을 때만 운반한다. stores/legacy 내용은 쓰지 않는다.
   - (검수 보완) COPY는 양쪽 모두 **명시 컬럼 목록**을 쓰고 `created_at`/`activated_at`을 포함해 clone 값을 그대로 옮긴다(서버 기본 now()로 새로 찍지 않음). `chain_publication_state.validated_source_revision`은 0이어야 하며 운영 revision0과 같아 source_drift=false가 된다. clone의 4표 행 수·GUC 고정 행 hash를 COPY 전에 계산하고 운영 COPY 후 같은 방식으로 재계산해 일치해야 한다.
   - (검수 보완) 판정 입력 동일성은 "원본20표 hash 동일 + 같은 registry/snapshot 파일"로 보장되지만, PG/PostGIS 버전이 clone과 다르면 계획 함수 결과가 같다는 보장은 없다. 버전이 다르거나 확인되지 않으면 같은 트랜잭션에서 운영 연결로 `publication_plan`을 **읽기 계산만** 수행해 fingerprint가 clone과 같음을 확인한 뒤에만 commit한다(쓰기는 COPY뿐). 그 계산의 운영 부하/시간은 clone에서 먼저 측정하고 180초 SQL 제한 안이어야 한다.
7. 새5표 SELECT만 spoton_api에 부여한다. 기존 권한/default privileges·역할 멤버십·DB URL은 유지한다. publication 무결성(전체 새 행 재조회 또는 테이블 hash)·generation/fingerprint·state revision0·원본20표(알렘빅 제외) hash/기존 인덱스/제약/시퀀스 불변을 commit 전에 확인한다. ~~새 표는 최대128MiB, 전체 DB800000000 bytes 이내, 추가 임시/WAL 여유900MB 기준을 지킨다.~~ (검수 정정) 원 기준은 서로 모순이다. 현재 DB가 761,124,531 bytes이므로 800,000,000 bytes 상한 아래 여유는 약 38.9MB뿐이라 128MiB 허용과 양립하지 않고, Free 1GB 저장소에서 "추가 여유900MB"는 확보할 수 없다. 정정 기준: (a) clone 측정 새 표 크기 S(TOAST·인덱스 포함)에 대해 `761,124,531 + S×1.5 ≤ 800,000,000`이어야 시작한다. (b) commit 전 같은 트랜잭션에서 `pg_database_size` ≤ 800,000,000을 확인한다(미커밋 새 파일 포함). (c) 앱 코드의 128MiB 상한은 별도 상한으로 유지한다. (d) WAL/임시 공간은 Render가 관리하므로 별도 수치를 주장하지 않고, 작업 중 대규모 정렬·임시 파일·VACUUM FULL을 만들지 않는다. 기준을 넘으면 시작하지 않는다(공간 확보를 위한 기존 데이터 삭제/인덱스 제거는 이 작업 범위가 아니다). 실패하면 DDL·COPY·GRANT 전부 rollback한다. 다운그레이드/원본 복원 덮어쓰기/자동 prune을 하지 않는다.
   - (검수 보완) 권한: GRANT 후 commit 전에 spoton_api의 새5표 SELECT=true, INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER=false, `spoton_chain_source_changed()` EXECUTE 비부여, 새 객체 소유자=spoton_owner를 `has_table_privilege`/`pg_class.relowner`로 확인한다. readiness의 `table_write`/`owns_objects` 검사가 새 표에도 적용되므로 쓰기 권한이 하나라도 있으면 새 BE가 unsafe_role로 실패한다. 함수가 SECURITY DEFINER(owner 권한)이므로 정의의 `search_path=pg_catalog, pg_temp`·`prosecdef`·PUBLIC EXECUTE 회수를 `source_revision()`과 같은 조건으로 재확인한다.
   - (검수 보완) 구조 불변 비교는 backup.py `structure()`와 같은 질의(새 트리거 제외)를 commit 전에 재실행해 이전 값과 동일해야 한다. 운영 전용 인덱스2개(ops_free_risk_cover/ops_free_risk_name_v1)도 포함된다.

## BE 배포와 검증

8. 운영 기존17개 환경 중 DATABASE_EXPECTED_REVISION만0012로 바꾸고 다른 값은 전후 동일 hash/직접 비교한다. 관리자 자격증명은 앱에 넣지 않는다. Free·자동 배포off·풀1/SQL10초/기존 LLM·CORS는 보존하고 검수된 develop commit을 명시해 수동 배포한다. migration commit과 새 프로세스 live 사이 구버전 ready가 잠깐 실패할 수 있으므로 commit 직후 배포를 시작하고 시간을 기록한다. 기존 v1 FE를 이 구간에 v2로 바꾸지 않는다.
   - (검수 보완) 순서: commit → 환경값 1개 변경(자동 배포off이므로 이것만으로 재시작되지 않음을 Render 이벤트로 확인) → 지정 commit 수동 배포. 환경값을 migration 전에 바꾸면 그 사이 인스턴스 재시작 시 구버전이 0012를 기대해 ready가 실패하므로 하지 않는다. commit~새 live 구간에는 구버전의 v1 업무 조회는 정상이고 ready만 revision_mismatch(500)일 수 있다. Render health check 경로가 ready인지 preflight에서 기록하고, 그렇다면 구 인스턴스 재시작 위험을 이 구간의 알려진 위험으로 기록한다.
   - (검수 보완) 배포 대상 commit의 develop CI/CodeQL 성공을 배포 전에 확인한다(a0626f3은 문서 commit이며 코드는 #150 병합본과 같아야 한다).
   - (검수 보완) migration 전에 v1 주요 GET(카페/한식 nearby·snapshot·activity·risk·history·data-range)의 응답 data digest를 저장하고, 새 BE live 후 같은 요청이 data 동일인지 비교한다(stores 불변이므로 v1 data는 같아야 하며 meta/버전 차이는 항목별로 기록).
9. live commit·health/ready·v2 status/source_drift=false·CORS/no-store, 카페/음식점 필터별 nearby/snapshot/activity/risk 개수 일치와 무브랜드 history, legacy 오류422를 확인한다. 실제 AI는 카페/음식점 최소2건의4문단/숫자 검증/프롬프트chain-risk-interpret-v1/동일 Risk 조건을 확인한다. 기존 v1 조회도 검증한다. 실패 시 FE는 v1을 유지하고 원인을 해결한다. 필요하면 이전 BE05790fa를 기대 head0012 환경으로 재배포해 v1을 복구한다. 비어 있지 않은0012 downgrade는 거절되며 롤백 수단으로 사용하지 않는다.
   - (검수 보완) 05790fa+기대0012 복구는 3단계의 clone 사전 검증이 통과한 경우에만 사용한다. FE v2 활성화 이후에는 BE를 05790fa로 되돌리면 v2 endpoint가 사라지므로 **FE를 먼저 v1로 되돌린 뒤** BE를 되돌린다. 데이터 측 비상 수단은 publication 정리 명령(#149)의 pending 복귀이며 기존 테스트된 절차·expected 가드를 그대로 쓰고, 운영에서의 실제 실행은 별도 승인 범위로 둔다.

## FE 공개 전환

10. 운영 BE 검증 후 FE 별도 PR에서 Vercel buildCommand를 저장소에 명시한다. `VERCEL_ENV=production`이면 VITE_ANALYSIS_API_VERSION=v2, preview/development면v1로 빌드하는 작은 실행 스크립트를 사용한다. 일반 npm run build/로컬 프로필 기본v1은 유지한다. 프로젝트 비밀값·원래.env를 읽어 출력하거나 수정하지 않는다. 모르는/누락된 VERCEL_ENV는 실패로 드러내 공개 환경을 조용히 잘못 바꾸지 않는다. preview는 기존 목업v1을 유지한다.
   - (검수 보완) 스크립트는 프로젝트 대시보드에 같은 이름(VITE_ANALYSIS_API_VERSION)이 설정돼 있어도 production에서 v2를 명시적으로 덮어써야 하며, 빌드 산출물에서 실제 선택 값을 확인할 수 있는 비밀 아닌 표식(예: 빌드 로그 1줄)을 남긴다. VITE_ 값은 빌드 시점 고정이다.
   - (검수 보완) FE PR 병합이 곧 production 배포를 일으키는 브랜치(Vercel production branch)인지 확인하고, 병합은 9단계 BE 검증 통과 후에만 한다. 운영 BE의 CORS가 공개 origin의 v2 경로 GET/POST preflight를 허용하는지 병합 전에 확인한다.
11. 이 방식은 Vercel 공식 문서의 저장소 buildCommand override와 VERCEL_ENV 시스템 변수에 근거한다: https://vercel.com/docs/project-configuration/vercel-json , https://vercel.com/docs/environment-variables/system-environment-variables . 공개 전환 권한은 이번 사용자 진행 지시로 제공됐다. 실제 Claude 검수/단위/양 프로필 빌드/PR CI 후 develop에 병합한다.
12. 공개 브라우저에서 v2 endpoint만 분석에 쓰는지, 독립 브랜드·소속 미확인/면적 조건·이력 보존·AI 수동 생성/4문단/보고서 재사용·조건 변경/취소·모바일390/360/키보드를 확인한다. 실제 장애를 DB 쓰기로 재현하지 않는다. 공개 전환 회귀 시 FE 활성화 PR만 revert해v1로 되돌리고 BE0012/데이터는 보존한다. (검수 보완) revert는 새 빌드를 거치므로, 즉시 복구가 필요하면 먼저 Vercel의 직전 production 배포로 되돌린(Instant Rollback) 뒤 revert PR로 저장소 상태를 맞춘다. 두 경로 모두 실제로 쓴 것만 결과에 기록한다. Render 운영 문서2종·이 기준·FE 배포 안내에 현재 상태와 실제 결과를 동기화한다.

## 검수 기록

실제 Claude Code 설계 검수와 작업 코드 재검수를 이어서 기록한다. 아직 운영 DB 쓰기/BE 새 배포/FE v2 활성화는 수행하지 않았다.

### 실제 Claude Code 운영 설계 검수 1차 (2026-11-15) — 판정: **REVISE**

검수 범위와 한계: 이 MD만 Read/Edit했다. 입력으로 받은 원문 `migrations/versions/0012_chain_publications.py`, `etl/chains/publication.py`, `app/services/readiness.py`, `app/services/chains.py`, `migrations/env.py`, 운영자 `ops.py`(preflight), `backup.py`를 정적으로 대조했다. shell/git/DB/네트워크/테스트는 실행하지 않았고, 어떤 백업·복원·hash·배포도 이 검수에서 실행하거나 관측하지 않았다. 위 사전 확인 수치는 작업자 기록이며 이 검수가 재확인하지 않았다.

타당하다고 확인한 점(정적 판단):
- 0012 migration은 stores를 다시 쓰지 않고 새 표·statement trigger만 추가하며, 외부 트랜잭션 주입 시 Alembic이 commit하지 않는 구조라 DDL·COPY·GRANT 단일 원자 적용이 가능하다. 비어 있지 않은 downgrade 거절도 원문과 일치한다.
- LOCK이 snapshot을 만들지 않으므로 "SHARE 잠금 → 첫 SELECT" 순서로 잠금 대기 중 낡은 snapshot 문제가 없다(publication.py의 기존 주석과 같은 원리). 조회 ACCESS SHARE는 SHARE·SHARE ROW EXCLUSIVE와 충돌하지 않는다.
- 판정 유효성은 요청 시 CHAIN_FIELDS 동등성과 source revision으로 재검증되므로, 원본20표가 snapshot과 같다는 증명 하에서 clone 산출물을 옮겨도 의미가 유지된다. revision0→state 0 일치로 drift=false가 된다.
- backup.py: 내보낸 snapshot 트랜잭션 안에서 hash와 pg_dump를 함께 수행하고, 비밀번호는 docker `--env KEY` 상속으로 명령행에 노출되지 않으며, 실패 stderr를 비공개 파일로만 남긴다. md5 행 hash를 클라이언트에서 정렬해 서버 정렬/임시 파일을 피한다. geometry는 hex EWKB 텍스트로 행 hash에 포함된다.
- readiness는 production에서 새 표를 포함한 public 전 표의 쓰기 권한·소유를 거절하므로 GRANT 실수가 배포 단계에서 드러난다.

이번에 MD를 직접 수정한 항목: hash 세션 GUC 고정, pg_dump/PostGIS 버전 차단 조건, 비superuser 복원 실패 처리, 단발 publication 스크립트 guard 원칙과 재검수 요구, 운영 수치 하드코딩 금지, 잠금/첫 snapshot/Alembic/commit 순서, autovacuum 충돌, stores 소유자 확인, COPY 컬럼·타임스탬프 보존과 4표 hash 재대조, 버전 차이 시 운영 읽기 재계산 fingerprint 대조, **모순된 공간 기준 정정**, 권한·SECURITY DEFINER 재확인, 환경값 변경/배포 순서, CI 확인, v1 응답 data digest 비교, 05790fa@0012 롤백 사전 검증과 FE→BE 롤백 순서, Vercel 덮어쓰기·production branch·CORS·Instant Rollback.

현재 차단 조건(모두 해소 전 운영 쓰기 금지):
1. **공간 기준**: 원 기준(800,000,000 bytes 상한·128MiB·900MB 여유)이 모순이었다. 정정 기준(현재 + 측정 S×1.5 ≤ 800,000,000, commit 전 재확인)을 clone 실측 S로 충족해야 한다. 미측정.
2. **미검수 스크립트**: clone publication 단발 스크립트와 운영 단일 트랜잭션 스크립트(잠금·hash 재대조·Alembic 주입·COPY·GRANT·검증·commit) 원문이 검수 입력에 없었다. 실제 Claude 코드 재검수 PASS 전에는 실행하지 않는다.
3. **버전 호환**: 운영 server_version ≤ pg_dump 17 확인과 운영/clone PostGIS 버전 기록이 필요하다. 다르면 운영 읽기 재계산 fingerprint 대조를 운영 스크립트에 포함해야 한다.
4. **hash 결정성**: backup.py `fingerprints()`는 현재 TimeZone 등 GUC를 고정하지 않는다. 실행 전 운영·복원본 양쪽 고정으로 수정하고 재검수한다(이미 실행된 결과가 있다면 GUC가 같았다는 증거 없이 재사용하지 않는다).
5. **롤백 미검증**: 05790fa를 0012 clone에서 기대 0012로 실행한 결과가 없다. 확인 전에는 BE 롤백 경로를 "검증됨"으로 표기하지 않는다.

비차단 권고: preflight의 `writers` 정규식 검사는 참고용일 뿐이며 실제 보장은 SHARE 잠금이다. `backup.py`의 `dump.read_bytes()` 전체 적재 대신 스트리밍 SHA256을 권한다. Render health check 경로와 DB 만료일(2026-12-13)을 결과 기록에 함께 남긴다.

다음 검수 조건: 위 1~5의 실측 증거와 두 운영 스크립트 원문을 첨부해 재검수를 요청한다. PASS 판정은 그 재검수에서만 기록한다.


### 1차 지적 보완 및 단계별 코드 검수 요청 (Codex)

백업은98,109,104 bytes이며 SHA256 앞자리c85e5ef584a4다. 새 격리 DB에 실제 복원해21표 전 hash가 일치했다. 최초 격리 복원은 미리 만든 PostGIS 확장의 COMMENT 소유권에서 거절됐고 단일 트랜잭션이 rollback됐다. 새 clone으로 다시 복원할 때만 --no-comments와 spatial_ref_sys COPY 권한을 주어 해결했다. 운영 권한이나 원래 로컬 DB는 바꾸지 않았다.

- hash 함수에 UTC/ISO,YMD/postgres/extra_float_digits1/hex를 고정했다. 최초 운영 세션의 기본값은 UTC/ISO,MDY/postgres/1/hex이고 timeout 둘 다0이다. ISO 날짜 출력은 MDY/YMD 입력 순서에 영향을 받지 않는다. 그래도 고정한 clone hash와 잠금 안의 운영 hash가 각자 최초 baseline과 같아야만 쓰도록 추가했다. 다르면 중단한다.
- pg_dump17·운영PG17.11을 확인했다. clone PostGIS3.7/운영3.6.2 차이가 있어 운영에서 동일 publication_plan을 READ ONLY로 재계산한다. 이 fingerprint=clone fingerprint를 검사하고, 쓰기 트랜잭션에서 잠근 전체 원천 hash가 같은 백업과 같아야만 COPY한다. 계획은 CHAIN_FIELDS의 비공간 필드만 사용하므로 PostGIS 공간 계산에 의존하지 않으며, 이 원천 동등성 가드로 읽기 재계산과 COPY 사이 변경도 차단한다. 운영 읽기 재계산을 쓰기 트랜잭션 안에서 중복 실행하지 않는다.
- 공간 예측은 현재+clone 실측S×1.5≤800000000으로 정정했다. 작업 시작 직전 실제 DB 크기로 다시 검사하고 commit 전 실제800MB/새 표128MiB를 확인한다. 여기서900MB는 추가 여유900MB가 아니라 임시/WAL 포함 추정 총량의 경계였다. 새 기준이 더 엄격하며 유료 증설은 하지 않는다.
- clone/production_apply/release 코드가 준비됐다. 먼저 clone 전용 코드 검수 PASS 뒤 clone을 실행해 S를 측정하고, 이전 BE05790fa를 clone의0012/조회 역할에서 실제 실행해 rollback을 확인한다. 그 결과와 원격 읽기 재계산 증거를 붙인 최종 PASS 전에는 운영 쓰기를 하지 않는다.

### 실제 Claude Code 운영 검수 2차 — 단계별 판정 (2026-11-15)

검수 범위와 한계: 이번에도 이 MD만 Read/Edit했다. 입력으로 받은 원문(0012 migration, publication.py, readiness.py, chains.py, migrations/env.py, ops.py, backup.py, resume_restore.py, clone_apply.py, production_apply.py, remote_plan.py, release.py)과 Codex 결과 JSON(preflight·backup-proof·session-gucs)을 정적으로 대조했다. shell/git/DB/네트워크/테스트/스크립트는 하나도 실행하지 않았다. 아래 수치는 작업자 기록이고 이 검수가 재측정하지 않았다. 특히 `C:\Users\horim\spoton\SpotON-BE`(REPO)의 실제 checkout commit은 확인하지 못했다.

| 단계 | 판정 | 요약 |
|---|---|---|
| 백업·실제 복원 증거 | **수용** | 아래 1절 |
| clone_apply.py (clone 실행) | **PASS** (실행 전 조건2개, 코드 수정 불요) | 아래 2절 |
| remote_plan.py (운영 READ ONLY) | **PASS** (비차단 권고) | 아래 3절 |
| production_apply.py (운영 쓰기) | **REVISE** | 아래 4절 — 최종 검수 전 수정 필요 |
| release.py (환경값·배포) | **REVISE** | 아래 5절 |
| 운영 쓰기 전체 | **차단 유지** | 아래 6절 |

#### 1. 백업·복원 증거 수용 근거

- 1차 차단3(버전): preflight 운영 PG17.11 ≤ pg_dump17 고정 digest 이미지로 해소. PostGIS 운영3.6.2/clone3.7 차이는 기록됐고, 운영 READ ONLY 재계산 fingerprint 대조(remote_plan)가 운영 스크립트의 전제 조건으로 들어가 1차 6단계 요구를 충족한다. 21표 hash 일치 기록상 spatial_ref_sys도 이번 데이터에서는 차이가 없었다.
- 1차 차단4(hash 결정성): 현재 backup.fingerprints가 5개 GUC를 `SET LOCAL`로 고정한다. baseline(source-before.json)이 고정 이전 코드로 계산됐더라도 기록된 기본값 차이는 DateStyle 두 번째 항목(MDY↔YMD)뿐이며, 이는 입력 해석과 비ISO 출력 순서에만 영향을 주고 ISO 출력 문자열은 같다. TimeZone·IntervalStyle·extra_float_digits·bytea_output은 동일 값이다. 따라서 baseline과 고정 hash는 비교 가능하다고 판단한다. 운영 잠금 안 재대조도 고정 hash로 같은 baseline과 일치해야 하므로 실제로 다르면 fail-closed다.
- 첫 복원 실패 뒤 재시도(--no-comments, clone 전용 `GRANT ALL ON spatial_ref_sys TO spoton_app`)는 1차의 "superuser 복원/오류 무시 금지"를 위반하지 않는다. 복원 역할은 여전히 spoton_app이고 --single-transaction/--exit-on-error가 유지되며, COMMENT는 행 hash·structure() 비교 대상이 아니고 GRANT는 폐기 가능한 clone에만 적용됐다. 이 clone에는 COMMENT가 없다는 차이를 결과 기록에 남긴다.
- idle_in_transaction/statement timeout 0 기록으로 snapshot 유지 조건도 충족한다.

#### 2. clone_apply.py — **PASS**

정적으로 확인한 점:
- 대상 고정: 로컬 URL이 loopback·spoton_dev인지 확인한 뒤 DB 이름만 `spoton_it_[a-f0-9]{12}` clone으로 바꾸고, 트랜잭션 안에서 `current_database()=clone`·`current_user=spoton_app`을 재확인한다. 원래 spoton_dev·운영에 닿는 경로가 없다. 기존 `validate_local_target`/`locked()`를 monkeypatch하지 않고 별도 명시 검사로 대체해 1차 3단계 조건(loopback·이름·역할·head·revision0·빈 publication)을 충족한다. chain_publication_state 빈 행은 `expected_active='none'` 경로로 강제된다.
- 트랜잭션: 첫 문장 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ`, `SET LOCAL` 후 첫 SELECT로 snapshot. SQLAlchemy 최초 연결의 dialect 초기화 문장은 연결 직후 rollback되므로 같은 트랜잭션에 섞이지 않는다(기존 publication.run과 같은 패턴). Alembic은 외부 트랜잭션에서 commit하지 않는다. upgrade→revision0/publication0 확인→기존 `apply` dry-run→같은 expected fingerprint로 write→기존 verify·128MiB 검사→원본20표 hash 불변→새5표 hash/크기 측정 후 단일 commit이다. 실패 시 전부 rollback되고, 재실행은 head0011 검사에서 막힌다.
- `fingerprints()`의 `SET LOCAL`은 이후 Alembic/apply에도 유지되지만, apply는 타입 바인딩 파라미터로 쓰므로 DateStyle/TimeZone 영향이 없다.
- 덤프 SHA256·restore 증거·snapshot 파일 SHA256을 확인/기록한다. 측정 S는 clone 실행의 산출물이며 이 PASS의 전제가 아니다.

실행 전 조건(코드 수정 없이 운영자가 확인·기록):
1. REPO(`C:\Users\horim\spoton\SpotON-BE`)의 HEAD가 a0626f3(또는 코드 동일 commit)이고 작업 트리가 깨끗함을 실행 직전 기록한다. migration·publication·registry 기본 경로를 이 REPO에서 import하므로 다르면 clone 결과가 배포 코드와 어긋난다.
2. `python -O`/`PYTHONOPTIMIZE`로 실행하지 않는다(모든 가드가 `assert`다). clone에서는 피해가 격리되지만 같은 규칙을 운영 스크립트에도 적용한다(4절).

비차단 권고: proof에 registry 파일 SHA256·plan_sha256·store_sha256·row_count·known_count·status별 건수와 publication 쓰기 전후 `pg_database_size`를 함께 기록한다(1차 3단계 권고; clone이 보존되므로 사후 재조회로 보완 가능). `engine.dispose()`를 finally로 옮긴다.

clone 실행 뒤 롤백 시험의 주의(최종 검수 입력): clone 표는 spoton_app 소유라 05790fa/a0626f3를 `APP_ENV=production`으로 spoton_app 접속하면 readiness가 unsafe_role로 거절한다. (a) clone 전용 SELECT-only·default_transaction_read_only 역할을 만들어 production 모드로 시험하거나, (b) development 모드로 revision·v1/v2 조회만 시험하고 역할 검사는 운영 GRANT 직후 검사로 대체한다. 어느 쪽을 썼는지 기록한다. 로컬 클러스터에 새 역할을 만들면 spoton_dev 데이터는 바뀌지 않지만 클러스터 전역 객체이므로 시험 후 정리 여부도 기록한다.

#### 3. remote_plan.py — **PASS** (운영 READ ONLY 계산)

`SET TRANSACTION ... READ ONLY`가 첫 문장이고 DML이 없으며 `publication_plan`만 호출한다. fingerprint가 store_sha256·registry·plan을 포함하므로 clone과 같으면 PostGIS 버전 차이와 무관하게 같은 판정이며, 운영 원천이 백업과 다르면 mismatch로 fail-closed다. 비차단 권고: `SHOW transaction_read_only='on'`을 assert해 proof의 `read_only:true` 하드코딩을 실제 값으로 바꾸고, Free DB에서의 소요 시간(180초 제한 대비)과 그 동안의 앱 응답 지연 관측을 기록한다. 실행 전 2절 조건1·2를 동일하게 적용한다.

#### 4. production_apply.py — **REVISE** (운영 쓰기 전 수정 필수)

구조는 1차 설계와 일치한다: 단일 SQLAlchemy 트랜잭션, `SET TRANSACTION RR`→`SET LOCAL`→20표 SHARE 잠금(spatial_ref_sys 제외, alembic_version 포함 — 자기 트랜잭션의 UPDATE와 충돌 없음)→첫 SELECT→DB/역할/head/stores 소유자/공간 재예측→21표 hash=baseline→structure=백업 시점→Alembic→명시 컬럼 COPY(state 포함, chain_source_state 제외)→GRANT→새5표 hash=clone→원본 hash/구조 불변→trigger ALWAYS·revision0·generation→크기 검사→commit. migration의 잠금(SHARE ROW EXCLUSIVE)은 ACCESS SHARE 조회와 충돌하지 않는다.

수정 필수:
1. **`assert` 의존**: 운영 가드 전부가 `assert`라 `-O`에서 사라진다. 시작 시 `if sys.flags.optimize: raise SystemExit` 또는 명시 `raise`로 바꾼다.
2. **권한 검사 불완전**: readiness `table_write`는 `INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER` 중 하나라도 있으면 unsafe_role이다. 스크립트는 REFERENCES/TRIGGER를 검사하지 않아, default privileges가 이를 자동 부여하면 commit 후 새 BE ready가 실패한다. commit 전 검사에 REFERENCES·TRIGGER, 새5표 `relowner=spoton_owner`, `has_function_privilege('spoton_api','public.spoton_chain_source_changed()','EXECUTE')=false`, 함수 `prosecdef`·`proconfig=search_path=pg_catalog, pg_temp`를 추가한다(1차 7단계 권한 보완과 동일).
3. **트랜잭션 상태 확인**: `creator=free_ops.owner_connection`이 반환하는 연결이 autocommit=False인 psycopg Connection인지, LOCK 직전 `c.in_transaction()`과 `raw.autocommit is False`, 첫 SELECT 후 `SHOW transaction_isolation='repeatable read'`를 명시 검사한다. autocommit이면 LOCK이 오류로 끝나 fail-closed이긴 하지만, 실패 원인을 분명히 하고 Alembic이 자체 트랜잭션을 열 가능성을 배제한다. Alembic upgrade 직후에도 `c.in_transaction()`을 확인한다.
4. **코드 버전 고정**: 2절 조건1을 스크립트가 직접 확인하게 한다(REPO `git rev-parse HEAD` 결과를 기대 SHA와 비교, 실패 시 중단). clone·remote_plan 실행 시 기록한 SHA와 같아야 한다.
5. **commit 결과 불명 처리**: COMMIT 중 네트워크 단절이면 반영 여부를 알 수 없다. 스크립트 실패 시 재실행 전에 READ ONLY로 head·chain_publication_state를 먼저 조회하는 절차를 문서화한다. 현재 head0011 assert 덕분에 이미 반영된 DB에 재적용되지는 않는다(fail-closed). `production-applied.json` 부재를 미적용 근거로 쓰지 않는다.

비차단 권고: jsonb를 Python 객체로 읽어 `Jsonb()`로 다시 쓰면 고정밀 숫자 표현이 바뀔 수 있다(이 경우 hash 재대조가 실패해 rollback되므로 안전성 문제는 아님). 원천 jsonb 컬럼을 `::text`로 읽어 그대로 COPY하면 재시도 위험이 줄어든다. 공간 조건은 `<`라 설계의 `≤`보다 엄격하므로 그대로 둔다. `engine.dispose()`를 finally로.

#### 5. release.py — **REVISE**

순서(production-applied 확인→env hash/live/동시 배포 없음/기대0011 확인→env 1개 변경 검증→지정 SHA 수동 배포)는 8단계와 일치하고 이전 env는 DPAPI로 비공개 보관한다. 수정 필수:
1. 배포 대상 a0626f3의 develop CI/CodeQL 성공 확인을 스크립트 또는 실행 기록의 선행 조건으로 넣는다(8단계 보완).
2. **이전 env 복원 금지 명시**: `environment-before.dpapi`는 기대0011이다. DB commit 이후 이 파일로 env를 되돌리면 구·신 BE 모두 ready revision_mismatch가 된다. BE 롤백은 env를 0012로 유지한 채 05790fa 재배포만 한다는 것을 스크립트 주석/rollback 함수에 명시하고, 그 경로는 2절 clone 롤백 시험 통과 후에만 "검증됨"으로 쓴다. 현재 rollback 함수가 없으므로 최종 검수 전에 추가하거나 수동 절차를 이 MD에 고정한다.
3. env PUT 후 Render 이벤트에 자동 재시작/배포가 생기지 않았는지, 그리고 Render health check 경로를 기록한다(commit~새 live 구간의 알려진 위험).

#### 6. 현재 차단 조건 (1차 목록 대체)

1차 2·3·4는 위 1~3절로 해소, 1차 1·5와 아래가 남는다. 모두 해소된 최종 검수 PASS 전에는 운영 쓰기·env 변경·배포를 하지 않는다.
1. clone 실행 실측 S와 `761,124,531(또는 직전 실측) + 1.5S < 800,000,000` 충족 증거.
2. 05790fa·a0626f3를 clone 0012에서 실제 실행한 ready/v1(구) 및 ready/v2 status(신) 결과와 사용한 역할/모드(2절).
3. remote_plan 실제 READ ONLY fingerprint = clone fingerprint 증거와 소요 시간.
4. 4절 수정1~5, 5절 수정1~3 반영본 원문.
5. REPO commit SHA 기록(clone·remote_plan·운영 공통).

clone_apply와 remote_plan은 위 실행 전 조건을 지키면 지금 실행해도 된다. 이 판정은 실행 결과를 보증하지 않는다.


### 운영 쓰기 전 최종 보완·실측 (Codex)

clone 코드 PASS 후 실제 실행했다. backend a0626f3/추적 파일 변경0·Python 최적화off를 확인한다. 최초 baseline과 GUC 고정 clone21표 hash가 같고,0012/publication 후에도 기존20표 hash가 같다. 추정8778/미확인347057, 브랜드2074, generation366fdaa8-c678-50fb-bf47-d67f0ca60d56이다. 운영 READ ONLY 계획도 동일 fingerprint이며121.312초가 걸렸다. raw 공간 함수가 아닌 CHAIN_FIELDS 비공간 값만 계획에 쓰고, COPY 직전 잠금 하의 전체 원천 hash도 백업과 같아야 한다.

새5표 실측 S=7,241,728 bytes, 현재761,124,531+1.5S=771,987,123으로800MB 기준을 충족한다. 최종 실제 크기도 commit 전에 검사한다. clone의 전용 비소유/읽기 역할로 실제 이전 BE05790fa와 새 BEa0626f3를 각각 production·기대0012로 실행했다. 양쪽 health/ready/nearby/activity/risk 5개 모두200이다. rollback 가능성은 이 실행으로 확인했으며 실제 운영 롤백은 아직 하지 않았다.

운영 스크립트 보완: sys.flags.optimize면 명시 RuntimeError, 실제 REPO SHA와 추적 clean 검사, LOCK 전과 Alembic 후 열린 비autocommit 트랜잭션 확인, reader의 INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER 전부 부재·SELECT5표/비소유 확인, trigger 함수 SECURITY DEFINER/search_path/소유자와 reader EXECUTE 부재 검사를 추가했다. release는 실제 Backend CI/CodeQL 성공을 다시 조회하고 healthCheckPath·환경값 변경 전후/배포 후 events의 id/type/timestamp만 기록한다. event details·키는 출력하지 않는다.

COMMIT 통신 실패로 결과가 불명확하면 applied JSON 유무로 판단하거나 같은 작업을 즉시 재실행하지 않는다. 새 READ ONLY 소유 세션으로 head/새5표 전체 hash·state/revision·reader 권한과 기존20표 hash/구조를 먼저 대조한다. 모두 목표면 이미 commit된 것으로 증거를 복구하고 배포 단계로 간다.0011/새 표 없음이면 rollback된 것으로 확인한 뒤 새 계획을 검토한다. 중간/모호 상태면 운영 쓰기와 배포를 멈춘다.

BE 복구 수동 절차: FE v2가 활성화됐다면 먼저 FE를 이전v1 배포/revert로 복구하고 v1 요청을 확인한다. DB0012와 publication은 그대로 두며 Render DATABASE_EXPECTED_REVISION=0012를 유지한다. Free/자동배포off/기타 환경 동일 확인 후 Render의 기존 수동 deploy API에서 검증된 이전 SHA05790fa7d71f6010b0174960863e4c9ceba77e25만 지정한다. live·ready·v1 조회를 확인한다. environment-before.dpapi는 증거 보관용으로만 쓰고0011 값을 복원하지 않는다. 비어 있지 않은0012 downgrade나 원본 DB 덮어쓰기는 하지 않는다.

v1 회귀는 배포 전11개 실제 GET200을 비공개 baseline으로 보관했다. #140으로 의도된 공식 지표2개 제거·추이2010 이전 제거·정책/프롬프트 버전 변경은 허용 차이로 명시 비교하고, 보존된 nearby/snapshot/history/data-range·4개 참고지표/집계 수치를 대조한다. 모든 data가 byte 단위 같아야 한다는 앞선 일반 문구는 이 알려진 계약 변경에 한해 정정한다.

FE 활성화 코드는 PR62 Draft에 있으며 기존159+배포구분4개, lint, Production(v2)/Preview(v1) 실제 빌드와 모르는환경 실패를 확인했다. 새 스크립트·package/vercel/eslint 원문을 최종 검수에 첨부한다. 운영 BE 실제 API/AI를 검증한 뒤에만 Draft를 해제하고 사용자 승인 범위 안에서 병합한다.

### 실제 Claude Code 운영 최종 검수 3차 (2026-11-15) — 판정: **조건부 PASS** (실행 전 필수 보완 1건)

검수 범위와 한계: 이번에도 이 MD만 Read/Edit했다. 첨부 원문(0012 migration, publication.py, readiness.py, chains.py, migrations/env.py, ops.py, backup.py, resume_restore.py, clone_apply.py, production_apply.py, remote_plan.py, release.py, FE scripts/vercel-profile.mjs·build-vercel.mjs·vercel-profile.check.mjs·package.json·vercel.json·eslint.config.js·docs/production-chain-v2.md)과 Codex 결과 JSON을 정적으로 대조했다. shell/git/DB/네트워크/테스트/빌드/스크립트는 하나도 실행하지 않았다. 아래 실측값(S, 121.312초, rollback-proof, fe-validation 등)은 작업자 기록이며 이 검수가 재현하지 않았다. 사용자 승인 범위(운영 BE v2 배포·공개 FE v2 활성화)는 이미 주어졌으므로 새 승인 절차는 추가하지 않는다.

| 대상 | 판정 |
|---|---|
| 2차 차단 조건 1~5 (공간 실측·clone 롤백 실행·원격 fingerprint·스크립트 수정 반영·SHA 고정) | **해소**(증거 수용, 아래 1절) |
| production_apply.py | **조건부 PASS** — 필수 보완 1건(아래 2절 A) |
| remote_plan.py | PASS(이미 실행, 비차단 기록 1건) |
| release.py | **PASS** (비차단 권고) |
| BE 수동 롤백 절차 | PASS(수동 절차 고정 수용, 실제 운영 롤백은 미수행) |
| **FE 운영 전용 활성화 코드 (PR62)** | **PASS** — 병합은 운영 BE 실제 API/AI 검증 후(기존 조건 유지) |

#### 1. 2차 차단 조건 해소 근거

1. 공간: S=7,241,728(TOAST·인덱스 포함 5표 합). 761,124,531+1.5S=771,987,123 < 800,000,000. 스크립트가 잠금 후 실제 `pg_database_size`로 재예측하고 commit 전 실제 크기를 다시 검사한다. 충족.
2. 롤백: rollback-proof/current-clone-proof상 05790fa·a0626f3 모두 clone 0012·production 모드·격리 읽기 역할에서 health/ready/nearby/activity/risk 200. 수용한다. 단 범위는 이 5개 경로이며 snapshot/history/data-range/interpret는 이 증거에 없다(BE 롤백 후 확인 항목으로 둔다). clone 역할의 권한 상태는 운영 default privileges와 다를 수 있다(2절 A와 관련).
3. 원격 계획: remote fingerprint=clone fingerprint(`dc7d7b16…`), store/registry/plan sha·8778/2074 일치, 121.312초 < 180초. 수용.
4. 스크립트 수정: ops.py import 시 `sys.flags.optimize` 거절로 모든 하위 스크립트의 `assert`가 유지된다. SHA·추적 clean 검사, LOCK 전/Alembic 후 `in_transaction()`·`not raw.autocommit`, REFERENCES/TRIGGER 포함 권한·소유자·함수 SECURITY DEFINER/search_path/EXECUTE 검사, release의 CI/CodeQL 재조회·healthCheckPath·events 기록이 반영됐다. 2차 4절 1~5·5절 1~3 충족(5절 2는 rollback 함수 대신 이 MD의 수동 절차 고정으로 충족).
5. SHA: ops.py가 a0626f3를 실제 `git rev-parse`로 강제한다.

#### 2. production_apply.py

정적으로 다시 확인한 점: SET TRANSACTION RR이 트랜잭션 첫 문장이 아니면 PostgreSQL이 오류를 내므로 격리 수준은 fail-closed로 보장된다. LOCK(20표 SHARE, `spatial_ref_sys`는 SELECT 권한만으로는 SHARE 잠금 불가하므로 제외 타당)→첫 SELECT 순서, 잠금 하 21표 hash=백업 baseline, 구조=백업 시점, Alembic 외부 트랜잭션, FK 순서대로 명시 컬럼 COPY(created_at/activated_at 보존, chain_source_state는 migration의 (1,0)과 clone 행 hash 동일), 새5표 hash=clone, 기존20표 hash·구조 불변, trigger `A`·revision0·generation, 크기 2종 검사 후 단일 commit. jsonb 재직렬화 차이는 hash 재대조에서 rollback되는 fail-closed다. migration 잠금(SHARE ROW EXCLUSIVE)과 새 표 FK는 조회 ACCESS SHARE와 충돌하지 않는다. autovacuum과의 잠금 경합은 lock_timeout 5초 내 PostgreSQL의 autovacuum 자동 취소 또는 fail-closed다.

**A. 필수 보완(실행 전): 새 시퀀스 권한 검사 누락.** 0012의 `chain_source_state.id`·`chain_publication_state.id`는 단일 SmallInteger PK이고 `autoincrement`를 끄지 않았으므로 SQLAlchemy PostgreSQL DDL에서 SMALLSERIAL로 생성되어 public 시퀀스 2개가 생길 가능성이 높다(정적 판단, 미실측). readiness는 public 전 시퀀스의 `has_sequence_privilege(current_user, oid,'USAGE,UPDATE')`와 시퀀스 소유를 `sequence_write`/`owns_objects`로 거절한다. 그런데 스크립트는 (1) 새 표의 table 권한만 검사하고 (2) 구조 비교에서 `after['sequences']`를 기존 이름으로 걸러 새 시퀀스를 보지 않는다. 운영에 spoton_owner의 시퀀스 default privileges가 spoton_api에 USAGE 등을 주고 있다면, commit 후 **구 05790fa와 신 a0626f3 모두** ready가 unsafe_role이 되어 롤백 경로까지 막힌다. clone 롤백 증거는 격리 역할이라 이 운영 default privileges를 대표하지 않는다.
- 수정: commit 전 같은 트랜잭션에서 readiness와 같은 조건을 spoton_api 기준으로 public **전체** 객체에 평가해 모두 false여야 한다 — `relkind IN ('r','p','v','m')`의 `has_table_privilege('spoton_api',oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')`, `relkind='S'`의 `has_sequence_privilege('spoton_api',oid,'USAGE,UPDATE')`, `relowner=spoton_api`(r,p,v,m,S). 새 시퀀스 소유자=spoton_owner와 생성된 시퀀스 이름 목록도 proof에 남긴다. 시퀀스에는 GRANT하지 않는다(현 스크립트대로).
- 이 assertion 추가 외 다른 변경이 없으면 추가 Claude 재검수 없이 Codex의 diff 자체 확인 후 실행해도 된다. 다른 로직이 바뀌면 재검수한다.

비차단 권고: ops.py의 clean 검사가 `--untracked-files=no`라 REPO의 미추적 파일(특히 `migrations/versions/`·REPO 루트의 모듈 이름 충돌)은 보지 않는다. 실행 직전 `git status --porcelain -- migrations app etl`(미추적 포함) 0줄을 기록한다. `engine.dispose()`를 finally로. 잠금 직후 `SHOW transaction_isolation`을 proof에 남긴다.

#### 3. remote_plan.py

이미 실행됐다. `SET TRANSACTION ... READ ONLY`는 autocommit 연결에서는 경고만 내고 무효가 되므로 proof의 `read_only:true`는 하드코딩 값이다. 다만 `publication_plan`은 읽기만 하고, 운영 쓰기의 안전성은 production_apply의 잠금 하 hash 대조가 보장하므로 결과 수용에 영향이 없다. 결과 기록에 "read_only는 미검증 표기"로 남긴다.

#### 4. release.py — PASS

순서(applied 확인→CI/CodeQL 재조회→env hash·live·비진행 배포·기대0011→env 1개 변경 검증→지정 SHA 배포)와 기록 범위가 설계와 일치한다. commit 이후 env를 0012로 바꾸면 구 05790fa도 rollback-proof상 ready 정상이므로 env 변경 이후 구간 위험은 오히려 줄어든다. 남는 알려진 구간은 commit~env 변경 사이의 구 인스턴스 ready revision_mismatch(업무 조회는 정상)이며, health check 경로가 ready라면 이 구간을 짧게 유지한다.
비차단 권고: (1) POST deploy 응답을 `assert dep['commit']['id']==SHA` **전에** deployment.json에 저장한다(현재는 assertion 실패 시 배포는 생성됐지만 기록이 없어 `status`를 못 쓴다; 재실행은 env hash 불일치로 막히므로 중복 배포 위험은 없다). (2) env PUT 직후 deploys에 비종료 상태가 생기지 않았는지 assert한다(현재는 events 기록만). (3) PUT은 전체 env 교체이므로 결과 동일성 검증이 이미 있음을 유지한다.

#### 5. FE 운영 전용 활성화 코드 — **PASS**

- `analysisVersionForVercel`: production→v2, preview/development→v1, 누락·빈 값·대소문자 다름·기타는 throw. 조용한 오설정 없음. 4개 검사가 이 분기를 모두 덮는다.
- `build-vercel.mjs`: 버전 결정을 빌드 전에 수행해 잘못된 VERCEL_ENV면 빌드 실패. `npm_execpath`로 같은 npm을 재사용하고 `{...process.env, VITE_ANALYSIS_API_VERSION}`로 대시보드 값을 덮는다. Vite는 실행 시 이미 있는 process.env 값을 .env 파일보다 우선하므로 의도대로다. 로그 1줄은 VERCEL_ENV와 버전만 출력해 비밀이 없다. 신호 종료(status null)도 1로 실패 처리.
- `vercel.json` buildCommand가 대시보드 Build Command보다 우선하며 SPA rewrite를 유지한다. 일반 `npm run build`·로컬 프로필은 변경 없음. `.check.mjs` 이름은 vitest 기본 수집에 걸리지 않고 `node --test`로 별도 실행된다. eslint는 scripts에 Node globals만 추가.
- 롤백 방향이 안전하다: override가 어떤 이유로 적용되지 않으면 결과는 v1(기존 상태)이다.
- 남은 조건(기존 설계 10·12단계, 새 승인 아님): fe-validation 증거는 종료코드만 담고 있으므로, production 빌드 산출물/빌드 로그에서 실제 `analysis API v2` 표식을 확인해 기록한다. FE의 Vercel production branch가 병합 대상 브랜치인지 확인한다. 운영 BE CORS가 공개 origin의 v2 GET/POST preflight를 허용하는지 확인한다. **병합은 운영 BE의 실제 API·AI 검증(9단계) 통과 후에만** 한다.

#### 6. 현재 차단 조건

1. (필수, 운영 쓰기 전) 2절 A의 public 전체 readiness 동등 권한 검사(시퀀스 포함) 추가.

이 1건 외 운영 쓰기·env 변경·배포를 막는 차단은 없다. 운영 실행 후에는 9단계(실제 v1 회귀·v2·AI 2건)와 FE 병합 전 5절 조건을 따른다. 이 판정은 실행 결과를 보증하지 않으며, 실제 수행한 것만 결과에 기록한다.


Codex 조건부 PASS 보완: production_apply에 실제 PROBE_SQL을 spoton_api 대상으로 실행하는 검사를 추가했다. commit 전에 public 전체 table_write/sequence_write/owns_objects와 특권·쓰기멤버십·스키마/DB/TEMP CREATE 전부 false, 연결 한도8을 요구한다. owner 세션의 default_read_only 값은 앱 역할 설정을 뜻하지 않으므로 그 한 필드는 이 owner 검사에서 판정하지 않으며 기존 앱 역할/설정은 변경하지 않는다. 지적된 새2시퀀스까지 같은 쿼리가 포함한다. 요청된 한 검사만 추가했고 자체 diff/문법 검사를 완료했다. Claude가 이 보완에 한해 추가 재검수 없이 실행 가능하다고 명시한 조건을 충족했다. FE 빌드 로그의 production=v2/preview=v1 문구, develop Production 배포와 PR62 Preview 빌드 성공을 확인했다.


## 운영 실행 결과와 음식점 Risk 시간 초과 보완

운영0012·publication·SELECT5표 적용을 완료했다. 기존20표 데이터/구조 불변, stores689440 보존, source revision0/ALWAYS trigger, DB769160883 bytes를 검증했다. 첫 시도는 권한 검사에서 geometry_dump 타입에 시퀀스 함수를 호출하는 오류로 전부 rollback됐으며0011/새 표 없음 확인 뒤 CASE로 객체 종류를 먼저 검사하도록 보완했다. 소스/판정에 쓰지 않은 검사 SQL만 수정한 뒤 전체 검증을 다시 수행해 commit했다.

Render a0626f3/dep-dbslc9jbc2fs73bt2epg는2026-11-15 UTC06:51:16 live다. 환경17개 중 기대 schema만0012로 변경했고 나머지·LLM·CORS·SQL10초/풀1·Free/자동배포off를 보존했다. v1 11개 응답은7개 data 완전 동일,4개는 #140 공식 지표2개/2010 이전 추이 제거만 달랐으며 남은4개 참고지표 전 값이 같았다. FE PR62는 계속 Draft/공개v1이다.

v2 카페12조합을 통과했지만 음식점 non_chain/include/include_estimates Risk에서 HTTP500을 재현했다. 원격 읽기 전용 진단의 SQLSTATE57014이며 서울 전체 wide anti join이10초를 넘었다. 별도 진단 세션만60초로 두어 기준 응답을 얻은 결과 해당 SQL21.297초/전체31.469초였다. 앱 SQL10초·AI20초·역할/인덱스/원본은 바꾸지 않는다.

보완 설계/현재 코드:

- 집계용 추정 점포는 활성 generation의 estimated 증거에서 시작하고 (source,license_no) 유일 키로 현재 stores를 LATERAL LIMIT1 조회한다. 기존 uq_stores_source_license_no 유일성이 있으므로 LIMIT1이 점포를 생략하지 않는다. 모든 CHAIN_FIELDS의 IS NOT DISTINCT FROM과 drift 시 소진공 근거 제외를 그대로 적용한다. Risk의 같은 업종만 사전 제한한다.
- 이 작은 현재 유효 점포 집합을 MATERIALIZED CTE로 만들고 원래 cohort/면적/좌표/기간 조건과 count 표현식을 ClauseAdapter로 같은 열에 적용한다. 알려진 점포의 좌표 없음 수와 위치 확보 참조 count는 한 SQL/CTE에서 함께 구해 검증 스캔 중복을 피한다.
- non_chain/include/include_estimates는 기존 NOT estimated와 같은 집합이다. 각각의 정수 count를 전체-유효추정으로 계산한다. 양쪽에 같은 temporal/면적/위치 조건을 적용하므로 분자·분모·cohort_size 모두 정확한 여집합이다. 음수가 되면 실패한다. 나눗셈/반올림/표본 기준은 기존 reference_indicators 그대로이며 이름·분류·미확인 의미를 바꾸지 않는다.
- all/chain+미확인 제외의 추정 양성 집계도 같은 작은 CTE를 쓴다. 나머지 조건과 반경 내 조회·v1·AI 계약/프롬프트·publication/ETL/DB schema·운영 인덱스는 유지한다. v2 AI도 같은 get_risk를 재사용하므로 개선을 공유한다.
- 운영 READ ONLY 진단에서 보완본은 각 SQL 최대4.406초/전체17.141초에 성공했다. 내부망의 실제 HTTP 시간 보장은 아니며 배포 후 다시 검증한다. 기존 정상 완주 기준과 보완본의 전체 data/meta가 각각 정확히 같았다. 플랜은 유일키 index lookup의 작은 집합과 기존 ops_free_risk_name_v1 Index Only Scan을 사용한다.
- 새 통합 검증3개는 pending/published/원본 입력 변경 상태에서 업종2·브랜드12조합·면적2조건을 비교한다. 원래 행 predicate의 직접 지역/서울 count로 만든 지표 전 값과 excluded_no_coord가 모두 같다. 원본/운영 DB에서 테스트 쓰기는 하지 않는다. 추가로 전체 일반·격리 PostGIS·정적 검사를 수행한다.

이 보완을 실제 Claude에 코드/테스트/실측과 함께 검수받고 PR/CI/develop 병합 후 수동 배포한다. 실제 운영24조합/AI/공개 FE 전환은 그 뒤 재개한다. 이번 승인 범위의 발견된 차단 문제 해결이며 운영 v2 활성화에 별도 재승인을 요구하지 않는다.

### 실제 Claude Code 음식점 Risk 성능 보완 검수 4차 (2026-11-15) — 판정: **PASS** (코드 동등성), 병합·배포 전 조건 3건

검수 범위와 한계: 이번에도 이 MD만 Read/Edit했다. 첨부된 `app/services/risk.py`·`app/services/chains.py`(`aggregate_estimates`)·`app/models/store.py`·`store_cohort.py`·`spatial_stores.py`·`tests/integration/test_chain_risk_aggregation.py` 원문과 perf 결과 JSON을 정적으로 대조했다. shell/git/DB/네트워크/테스트를 실행하지 않았다. 4.406초/17.141초·data/meta 동일·통합3개 통과는 작업자 기록이며 이 검수가 재현하지 않았다. `SUPPORTED_STORES`·`CHAIN_FIELDS`·테스트 helper `prepared()`의 원문은 입력에 없어 해당 부분은 사용처로부터 추정했다. 이미 완료된 운영 schema 작업은 이 판정의 대상이 아니다.

#### 1. 집합 동등성 (정적 판단)

- **분기 선택**: `estimates`는 include_estimates일 때 (a) non_chain+include(여집합) 또는 (b) all/chain+exclude(양성)만 참이다. 나머지 조합의 `predicate()`는 `true()`/`false()`/`~false()`라 anti join이 없고 기존 경로를 그대로 쓴다. confirmed_only의 positive=`false()`와도 일치한다. chain=None(v1)은 항상 기존 경로이고 v1 캐시 경로도 바뀌지 않는다.
- **양성 집합 = 기존 `estimated()`**: 기존 EXISTS는 store마다 `valid(Store) ∧ estimated`인 Evidence 행이 있는지 확인한다. 새 CTE는 Evidence에서 시작해 `valid(matched) ∧ estimated`인 store를 만든다. 같은 `valid()` 함수에 alias만 넘기므로 generation·source·license_no 식별, 모든 CHAIN_FIELDS의 `IS NOT DISTINCT FROM`(nullable 포함), drift 시 `semas_address_corroborated` 제외가 그대로 같다. Evidence PK(generation,source,license_no)와 stores 전체 UniqueConstraint(source,license_no, partial 아님 → 삭제 행 포함 유일) 때문에 양쪽 모두 1:1이라 중복이나 누락이 없다. 정렬 없는 `LIMIT 1`도 후보가 최대1행이라 결정적이다.
- **`Evidence.category == category` 사전 제한**: `base`가 `Store.category == query.category`를 요구하고 `valid()`가 Evidence.category와 Store.category의 동일성을 요구한다(CHAIN_FIELDS에 category 포함으로 추정, 마이그레이션 컬럼과 일치). 따라서 제외되는 행은 어차피 base에서 빠지는 행뿐이다. 설령 category가 CHAIN_FIELDS 밖이어도 Evidence.category ≠ query.category이면서 store.category = query.category인 행만 차이가 나는데, 이는 입력 변경(stale)이 아니면 생길 수 없는 경우다. 원문 확인을 위해 아래 3절의 권고로 둔다.
- **시간·속성·삭제 조건**: `base=[*cohort, area, open_date<=target]`만 CTE 열에 적용하고 `predicate`(attributes[1])는 넣지 않는다. 삭제·검토 대기·이름 제외(`SUPPORTED_STORES`)·한시·날짜 플래그·기간 조건이 store 열에 대해 원래대로 평가되므로, 삭제되었거나 이름이 제외된 점포에 Evidence가 남아 있어도 걸러진다.
- **여집합 정수 계산**: `NOT EXISTS`는 NULL이 되지 않으므로 `base∧¬E`와 `base∧E`는 `base`의 정확한 분할이다. 각 열은 `count(*) FILTER(cond)`이고 cond가 양쪽에 같게 적용되므로 `total − positive`가 cohort_size/active/closure/survival 분자·분모 모두에서 정확하다. excluded_no_coord도 `count(base∧geom IS NULL) − count(E∧base∧geom IS NULL)`로 같다. 음수 검사는 excluded에만 명시돼 있지만, seoul 필드가 음수가 되면 `reference_indicators`의 local≤seoul 검사(local≥0)에서 ValueError→안전한 500으로 fail-closed가 된다.
- **로컬(반경) 집계**: `located`에 원래 predicate가 포함된 기존 SQL을 그대로 쓴다. 반경 안 후보에서만 EXISTS를 평가하므로 비용이 제한되고 의미 변화가 없다.

#### 2. SQL 구성

- **ClauseAdapter 열 계보**: CTE는 `select(aliased(Store, lateral))`이고, 그 열은 lateral 열 → `stores` 열로 proxy가 이어진다. 따라서 `corresponding_column`이 Store 열(geom 포함)을 CTE 열로 바꾼다. 대응을 찾지 못한 열이 남으면 `stores`가 암묵적 FROM으로 들어가 카티전 곱이 생기는데, 이는 통합 검증(다점포 fixture에서 지표 전 값과 excluded 비교)과 운영 기준 응답 data/meta 동일성에서 바로 불일치로 드러난다. 두 증거가 모두 통과로 기록돼 있어 수용한다.
- **스칼라 서브쿼리 상관**: `add_columns(unlocated_query(base, records=records).scalar_subquery())`는 외부와 같은 CTE를 FROM으로 쓴다. SQLAlchemy 자동 상관은 내부 FROM이 2개 이상일 때만 적용되므로, 여기서는 상관되지 않고 CTE 전체를 센다(의도대로). 다만 이 동작에 의존하는 구조라 아래 권고로 둔다.
- **`MATERIALIZED`**: `.cte().prefix_with("MATERIALIZED")`는 PostgreSQL에서 `AS MATERIALIZED (...)`로 렌더링되어 CTE를 1회만 계산한다. 작업자가 기록한 플랜(유일키 index lookup·ops_free_risk_name_v1 Index Only Scan)과도 맞는다.
- `assert chain is not None`은 mypy narrowing용이고 바로 앞의 `estimates` 조건이 이미 보장하므로 `-O`에서도 의미가 바뀌지 않는다.

#### 3. 비차단 권고

1. 여집합 분기에서 `seoul`의 모든 필드에 대해 `< 0`이면 명시 ValueError를 낸다. 지금은 local≤seoul 검사에 간접적으로 의존한다.
2. 스칼라 서브쿼리에 `.correlate(None)`을 명시해 SQLAlchemy 자동 상관 규칙에 의존하지 않게 한다.
3. 통합 검증 보강: (a) drift 상태에서 `semas_address_corroborated` 근거가 실제로 포함된 fixture(입력의 `prepared()`가 소진공 근거를 만드는지 확인하지 못했다), (b) Evidence는 남아 있고 store가 `deleted_at`/검토 대기/이름 제외 키워드로 바뀐 경우, (c) Evidence.category와 store.category가 다른 stale 행. 현재 3상태×24조합은 stale(floor_unit 변경)과 pending/published를 덮는다.
4. `CHAIN_FIELDS`에 category·sub_category가 포함돼 있는지 원문을 검수 기록에 남긴다.

#### 4. 병합·배포 전 조건 (새 승인 아님, 기존 절차)

1. perf 결과의 `full_checks: in_progress` — 전체 일반·격리 PostGIS·ruff/format·mypy와 PR CI/CodeQL 통과를 실제로 확인한 뒤에만 develop에 병합한다. 통과하지 않았으면 통과로 기록하지 않는다.
2. **시간 예산**: 보완본의 원격 진단 전체 17.141초는 v2 AI의 전체 예산 20초(Risk+활동+이력 재계산+LLM)에 거의 닿는다. Render 내부망에서는 더 짧을 수 있지만 보장되지 않는다. 배포 후 음식점 v2 Risk 24조합의 실제 HTTP 시간과 함께, 특히 non_chain/include/include_estimates **음식점 v2 AI**가 20초 안에 200·검증 통과하는지 확인한다. 503 AI_UNAVAILABLE이 나오면 성공으로 표시하지 않고 결과에 그대로 기록한 뒤 별도 판단한다. 앱 SQL10초·AI20초 설정은 바꾸지 않는다(기존 방침).
3. 배포 후 v1 회귀(기존 11개 baseline)를 다시 비교한다. 이 변경은 chain 경로만 바꾸므로 data가 같아야 한다. FE PR62 병합은 이 검증과 카페·음식점 v2 API/AI 검증이 통과한 뒤에만 한다(5절 조건 유지).

이 판정은 코드 동등성에 대한 정적 판단이며 실행 결과를 보증하지 않는다. 실제로 수행한 검사만 결과에 기록한다.


Codex 최종 검사: 일반1957·격리 PostGIS298(기존295+새3), ruff/format·mypy112파일 통과. 실제 Claude 성능 검수 UTC 2026-11-15T07:13:35.748345+00:00~2026-11-15T07:15:29.149906+00:00, 3 turns, exit0/권한 거절0, 코드 동등성 PASS다. 검수 전 MD SHA256 `255df3b230e19170be0084211b63edfd6d207d9ffe0fd7901b7edab59eaa435a`, 직후 `80a9145c3c9dc27d4c15b37eef051d76a9b280a44d5d9d599fc514418257d85b`이며 이후 실행 결과만 추가했다. 검수 후 앱 코드는 바꾸지 않았다. 배포 후 v1 재대조와 음식점 non_chain AI20초 예산 확인은 반드시 이어서 수행한다.


## 최종 공개 적용·검증 완료

BE #154 병합 `71eaef9c276ed5b2c70d761e47a9d2eeb7bdcd69` / `dep-dbslqv5ckfvc73dbu6a0`를 수동 배포했다. DB0012·활성 세대1·추정8778/미확인347057·source revision0, 원본689440행/기존20표·정의 보존, 전체 DB768,825,011 bytes를 확인했다. Free/자동배포off/환경17개 중 기대 schema 외 값은 그대로다. FE PR62 `93099f1bea68384b360ce16ac230aef5630eda22`의 Production v2 배포가 성공했고 실제 공개 화면의 v2 요청으로 프로필을 확인했다. Preview 빌드는v1을 유지했다. 원래.env/사용자 미추적 파일/로컬 서버는 보존했다.

24필터×4종 수 일치·이력10건 불변·7종 오류422·CORS/no-store·동시 Risk3건을 확인했다. 실제 카페/음식점 AI2건·캐시 replay, 별도 음식점 non_chain AI는19.031초/4문단/숫자50개/불일치0으로 통과했다. 이 시간은 관측값이고 Free 인스턴스의 시간 보장이 아니다. v1 11개 기준 응답 재대조도 통과했다.

공개 브라우저에서 분석/체인·미확인 독립 선택/이력 보존·모바일390/360·키보드/팝오버·실제 AI·보고서 재사용/조건 변경·취소와 브라우저 전용503/다세대/AI 불일치 차단을 확인했다. 검증 원문/그림은 저장소 밖에 보관한다. 실제 DB에 장애 데이터를 쓰거나 publication을 삭제/disable하지 않았다.

실제 Claude 검수는 설계 REVISE→clone 코드PASS→운영 조건부PASS(전체 reader 권한 검사 보완)→성능 코드PASS를 수행했고, 검사/실행 기록을 위 절에 남겼다. 검수자가 테스트를 실행한 것은 아니며 실행은 Codex가 수행했다. 성능 검수의 남은 CI·배포 후 v1·비체인 AI 확인 조건도 실제로 충족했다.
