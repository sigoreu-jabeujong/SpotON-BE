# 로컬 테스트 BE 반영 (#151)

기준 develop cdc5513. 사용자는 테스트 DB 백업→0012→브랜드 판정 적재/공개→새 BE의 v2 조회/필터/AI 확인→FE 전달 문서를 승인했다. 이번 범위는 PC의 로컬 spoton_dev/테스트8001이다. Render·FE 저장소·원본 .env·기존8000은 변경하지 않는다. 별도 기능/모델/스키마 설계 변경 없이 이미 검수된0012와 publication을 적용한다.

## 1. 대상과 순서

사전 확인은 loopback5432·DB spoton_dev·spoton_app/비슈퍼유저/PostGIS·stores 소유spoton_app·head0011·점포689440행이다. 원격 접속/다른 DB는 거절한다. 현재8000은 health200/ready404,8001은health/ready200이며 두 프로세스는 reload가 없다. 키 존재/provider/model만 확인했고 비밀값은 출력하지 않았다.

0. **쓰기 정지 구간(사전 조건).** 백업 직전부터 공개 검증 종료까지 stores·legacy 브랜드 표를 쓰는 ETL(localdata·floor_backfill·brands.apply·maintenance --execute 등)을 실행하지 않는다. 8000/8001은 조회만 하지만 같은 spoton_app(쓰기 가능 소유자)으로 접속하므로, 기존 public 업무 표의 `pg_stat_user_tables` n_tup_ins/upd/del 합계를 백업 전·복원 대조 후·0012 후·공개 후에 기록해 쓰기 0을 보조 증빙한다(통계 카운터는 보조이며 hash 대조가 주 근거다).
1. **기준 hash H0 → 백업 → 복원 대조.** 먼저 원본에서 READ ONLY REPEATABLE READ 한 트랜잭션으로 H0(대상 표별 행수·PK 정렬 전 필드 hash, geometry는 EWKB 문자열 직접 hash — #57 QA의 to_jsonb(geometry) 시간초과 회피)를 구한다. 대상은 alembic_version·spatial_ref_sys(확장 소유)를 제외한 public 기본 표 전체이며, 시퀀스 last_value와 `pg_get_indexdef`/제약/트리거 정의 목록도 함께 기록한다. 이 대조용 세션의 statement_timeout은 앱 3초가 아닌 명시 상한을 쓴다. 이어 저장소 밖 새 custom pg_dump 백업(서버와 같거나 높은 pg_dump 버전)과 SHA256/bytes를 기록하고 폐기용 **새 이름의** DB(spoton_dev가 아님)로 실제 복원해 H1=H0을 확인한다. spoton_app은 DB 생성 권한이 없으므로 복원 DB 생성/PostGIS 확장 생성은 로컬 컨테이너 관리 역할로만 수행하며, 그 자격증명은 출력·기록하지 않고 원격/다른 클러스터는 대상이 아니다. 백업 검증 실패면 원본 DDL을 진행하지 않는다. 백업/증빙을 저장소·클라우드 동기화 폴더에 넣지 않고 자동 삭제하지 않는다(원천 점포 원문 포함).
2. 원래 인허가·브랜드 ETL이 사용한 spoton_app(해당 객체 소유·비슈퍼유저) 연결로 Alembic0011→0012를 한 트랜잭션에서 적용한다. statement/lock timeout은 .env를 바꾸지 않고 해당 프로세스의 접속 옵션(예: PGOPTIONS)으로만 정하며, 실행 전 Alembic env가 단일 트랜잭션(transaction_per_migration 미사용)인지 확인한다. 실패 시 전체 rollback한다. 0012의 CREATE TRIGGER/ENABLE ALWAYS는 stores에 SHARE ROW EXCLUSIVE 잠금이 필요하다. 이 잠금은 8000/8001의 조회(ACCESS SHARE)와는 충돌하지 않고, stores writer(ROW EXCLUSIVE)·VACUUM/ANALYZE·autovacuum(SHARE UPDATE EXCLUSIVE)·CREATE INDEX(SHARE) 등과 충돌하므로 이들이 있으면 lock timeout으로 실패할 수 있다. 이때는 재시도 전 원인만 확인한다(5.4 정정). 새5테이블·ALWAYS statement trigger/SECURITY DEFINER 함수(PUBLIC 실행 회수) 외의 기존 업무 객체·행을 수정하지 않는다. 기존 stores 소유자가 새 표·함수도 소유하므로 로컬 ETL 접근을 유지한다. 이 로컬 계정은 Render의 조회 전용 역할과 다르다. 0012 이후 공유 ETL guard(check_local_database)는 0012만 허용하므로 0011 코드의 ETL은 거절된다.
3. 원본 stores/legacy/전체 기존 업무 표 hash H2가 H0과 같고(새5테이블·alembic_version 제외), 기존 객체의 스키마 정의 차이는 stores의 `spoton_chain_source_changed` 트리거(tgenabled='A') 하나뿐이고, 추가 객체는 새5테이블·그 제약/인덱스·SmallInteger PK에 따른 새 시퀀스2개·SECURITY DEFINER 함수1개뿐인지 확인한다. chain_source_state.revision=0을 확인한다. 기존 검증 registry와 외부 소진공137173행/202609 snapshot(파일 SHA256 기록)으로 실제 publication.run의 로컬 guard를 교체하지 않고 READ ONLY 계획 → 출력의 `expected_plan_sha256`(=fingerprint, plan_sha256 아님)과 `--expected-active none`을 사용한 명시 쓰기 → **dry-run 재계획**에서 같은 generation/fingerprint·active=그 generation을 확인한다. 같은 입력의 두 번째 `--write`는 행을 추가하지 않고 unchanged=true를 반환하지만 state의 activated_at(및 같은 값의 validated_source_revision)을 갱신하므로 완전한 no-op이 아니다. 멱등 근거는 dry-run 재계획으로 하고, 재쓰기를 수행하면 activated_at 변경을 그대로 기록한다. publication은 stores를 쓰지 않으므로 공개 후에도 revision=0·validated_source_revision=0이어야 하며, 이후 검증 종료까지 revision이 0으로 남는 것을 stores 무쓰기의 추가 증빙으로 쓴다. 삭제/prune/disable이나 source 원문 갱신은 하지 않는다. 공개 후 stores에 어떤 DML/TRUNCATE라도 실행되면(no-op UPDATE 포함, VACUUM 제외) revision이 증가해 source_drift가 켜지고 소진공 주소 근거는 재검증 전 unknown으로 내려가므로 FE 전달 문서에 이 운영 경계를 적는다.
4. 최신 BE를 임시8002/loopback에서 띄운다. 기존 .env를 읽되 파일은 바꾸지 않고 app_env=test·head0012·필요한 localhost5180 CORS만 프로세스 설정에 반영한다. **기존 .env에 DATABASE_EXPECTED_REVISION 등 0011 고정값이 있는지 값 출력 없이 키 존재만 확인**하고, 있으면 프로세스 환경으로 0012를 덮어쓴다(그렇지 않으면 새 서버 ready가 revision_mismatch). 기존 LLM 설정·한도·DB SQL3초를 유지한다. 구버전8001은 migration 이후 ready가 실패할 수 있어 그 시간을 기록하고 검증된 새 프로세스로 교체한다.8000은 건드리지 않는다(구버전이므로 0012 DB에서의 동작을 정상으로 보고하지 않는다).
5. 임시 서버의 v2 검증을 통과한 뒤, 기존8001 프로세스가 사전 확인한 PID/소유 관계와 같을 때만 종료하고 최신 BE를8001에 기동한다. health/ready와 v2·실제 AI를 최종 확인한다.8002는 종료한다. 서버를 숨김으로 실행하고 stdout/stderr는 저장소 밖에 둔다. PID/포트/commit만 공개하고 URL 비밀·원문 주소/점포·인허가·key를 로그/Claude에 넣지 않는다.

## 2. 실행 검증

- H0=H1(복원본)=H2(0012 후)=H3(공개 후)의 기존 테이블 전체 hash·시퀀스·인덱스/제약 정의 일치(차이는 새 트리거·새 함수·새5테이블과 그 시퀀스2개·alembic_version뿐. H1의 CHECK 정의는 복원 재파싱으로 문자열이 달라 5.2대로 H0과 H2/H3는 원본끼리만 문자 단위 비교), stores689440·legacy5 불변·.env SHA 동일, 쓰기 통계 카운터 무변화, chain_source_state.revision=0 유지
- schema0012·ALWAYS trigger(tgenabled='A')·publication 활성/validated_source_revision=현재 revision·확정 아닌 추정의 범위, status no-store
- cafe/restaurant의 all/chain/non_chain × include/exclude × include_estimates/confirmed_only 조합(업종별 최대12)에서 nearby count=snapshot total_at_as_of=activity open_count 합=risk competitor_count. 같은 as_of/반경/모집단을 사용하고 브랜드 필터 전/후 분모를 섞지 않는다. v2 계약([FE 계약](../fe-chain-v2-api-request.md))이 거절하는 조합은 등식 대상에서 빼고 기대한 422/no-store로 따로 기록하며, 실제 수행한 조합 수를 그대로 적는다.
- 실제 같은 building_key의 history는 브랜드와 무관하게 전체 지원 이력을 유지한다. 출력에는 원문을 내보내지 않고 건수/성공 여부만 기록한다.
- legacy/unknown 생략 등 잘못된 요청422/no-store, CORS localhost5180·기존 origin, health/ready200
- 최종8001에서 실제 Gemini2건(cafe/restaurant chain) HTTP200/4문단/verification.passed/동일조건 Risk 수 일치와 별도 prompt version을 확인한다. 새 provider/가짜 성공/추가 한도 확장은 하지 않는다.
- 기존 일반1957/PostGIS295·CodeQL 증거는 같은 코드 cdc5513에 대한 것이다. 새 실행 환경 검증을 기록하고 문서 PR CI를 확인한다. 앱 코드 변경이 생기면 별도 필요한 테스트·실제 재검토를 수행한다.

## 3. 실패와 복구

0012 적용 실패는 DDL 트랜잭션 rollback이며 공개 실패도 publication 트랜잭션 rollback이다.0012에 publication이 있으면 downgrade를 거절하는 기존 가드를 우회하지 않는다. 공개 후 문제라면 명시 maintenance 계획/가드로 pending 복귀하거나 백업을 별도 DB에 복원해 이전 서버를 해당 복원본에 연결하는 운영 판단이 필요하다. 원본 DROP/overwrite/자동 downgrade·백업 자동 삭제는 하지 않는다. 0011 상태로 되돌리려면 maintenance로 모든 세대를 정리해 네 표를 비운 뒤에만 기존 downgrade가 허용되며, 이는 이번 범위 밖의 별도 사용자 결정이다. 백업은 0011 시점이므로 복원본에는 공개 세대·트리거가 없고, 복원본을 spoton_dev에 덮어쓰는 방식은 쓰지 않는다. 복원본은 이름이 spoton_dev가 아니므로 ETL guard(validate_local_target)의 쓰기 대상이 될 수 없다.

기존8001을 종료한 뒤 새 기동이 실패하면 비공개 보존한 이전 기동 인자/작업 디렉터리·환경 설정을 참고하되,0011을 기대하는 옛 실행 파일을0012 DB의 정상 서버로 보고하지 않는다.0012 호환 신버전의 준비 상태를 복구하며 해결 전 완료로 표시하지 않는다. 새 표의 읽기 권한은 실제 서버 역할로 확인한다. app_env=test에서 readiness는 revision만 검사하고 역할 권한(쓰기 금지·객체 소유 금지)은 검사하지 않으므로, 8001의 ready200은 spoton_app(소유자·쓰기 가능)으로도 성립하며 조회 전용 역할의 증빙이 아니다. 이 검증은 로컬 test 환경이므로 production readiness의 조회 전용 역할 검증이나 Render 배포 완료를 뜻하지 않는다.

## 4. FE 전달 자료와 완료 범위

BE 저장소의 로컬 테스트 연결 문서에 http://localhost:8001/docs·status·예제 query/body·필터 진리표/한계·AI 한도·오류/CORS·검증 commit/시각/집계·백업 존재 여부/시각/SHA256 앞자리(절대 경로·사용자 폴더명·덤프·비밀 제외 — 경로는 사용자만 보관)·공개 후 stores 쓰기 시 source_drift 경계를 정리하고 기존 v2/AI 계약 문서를 연결한다. FE 연결 코드를 바꾸지 않고 외부 메시지/담당자 통보도 하지 않는다. 사용자가 파일을 전달할 수 있게 제공한다.

## 5. 실제 Claude 검수와 실행 기록

실제 Claude 설계 검수와 Codex 실행 전 대조를 아래에 기록한다. 실행 결과는 수행 후 별도로 추가한다.

### 5.1 Claude Code 운영 설계 검수 (2026-11-15, Read/Edit만 사용)

범위: 이 MD와 요청에 첨부된 0012 migration·etl/chains/publication.py·etl/localdata/runner.py·app/services/readiness.py 원문의 정적 대조. 셸/DB/Git/네트워크 실행, 테스트 실행, 다른 파일 열람은 하지 않았다. 아래는 실행 결과가 아니며 어떤 단계도 수행되었다고 기록하지 않는다. app/services/chains·etl/chains/compare·maintenance·Alembic env·Settings 기본값은 원문을 받지 않아 검토하지 않았다.

판정: **REVISE → 본 MD에 직접 수정 반영 후 조건부 PASS.** 차단 결함은 남기지 않았으나, 아래 실행 전 확인(G1~G4)이 충족되지 않으면 해당 단계를 진행하지 않는다.

수정 반영 항목:
1. 백업 증빙: 원본 hash를 덤프 이후에만 비교하면 덤프 시점 상태와의 동일성이 보장되지 않아 백업 전 READ ONLY RR 기준 H0과 쓰기 정지 구간·통계 카운터를 추가했다. geometry는 EWKB 직접 hash, 시퀀스·인덱스/제약/트리거 정의 대조를 추가했다.
2. 복원 권한: spoton_app은 DB 생성 권한이 없으므로 폐기용 DB·PostGIS 확장 생성은 로컬 관리 역할이 필요함을 명시하고, 복원 DB 이름을 spoton_dev와 다르게 했다.
3. migration: 단일 트랜잭션 확인, timeout을 .env가 아닌 프로세스 옵션으로 지정, stores SHARE ROW EXCLUSIVE 잠금 충돌 가능성을 추가했다.
4. publication: 쓰기 인자는 `expected_plan_sha256`(fingerprint)이며 plan_sha256이 아님을 명시했다. 같은 입력의 재쓰기는 unchanged=true이나 activated_at을 갱신하는 코드이므로 멱등 근거를 dry-run 재계획으로 바꿨다. 쓰기 경로는 state EXCLUSIVE·stores/legacy SHARE 잠금 후 revision을 읽어 계획과 같은 스냅샷이므로 validated_source_revision 경합은 정적으로 보이지 않는다.
5. 트리거: ALWAYS statement 트리거는 no-op UPDATE·TRUNCATE에도 revision을 올리므로 공개 후 stores 쓰기가 세대를 무효화한다는 운영 경계와, revision=0 유지를 무쓰기 증빙으로 쓰는 검증을 추가했다.
6. readiness: test 환경은 revision만 검사하므로 ready200을 역할 안전성 증빙으로 쓰지 않도록 명시했다. .env의 0011 고정 기대 revision 존재 여부 확인을 추가했다.
7. 진리표: 계약상 거절 조합을 등식 대상에서 분리하고 실제 수행 수를 기록하게 했다.
8. FE 전달: 백업 절대 경로는 사용자 폴더명을 포함할 수 있어 존재/시각/SHA 앞자리만 적도록 바꿨다.
9. 롤백 한계: 0011 복귀는 세대 정리 후에만 downgrade가 가능하며 이번 범위 밖임을 명시했다.

실행 전 확인(Codex):
- G1. 백업 직전~공개 검증 종료까지 stores/legacy 쓰기 ETL·예약 작업이 없음.
- G2. Alembic env가 0011→0012를 한 트랜잭션으로 실행함(원문 미확인).
- G3. 새 코드의 기대 revision이 0012이고 .env에 0011 고정 덮어쓰기가 없거나 프로세스 환경으로 대체됨.
- G4. 8001 종료 대상 PID의 명령줄·작업 디렉터리가 사전 기록과 일치함(reload 없음, 단일 프로세스).

남는 한계: 로컬 test·소유자 역할 검증이며 Render/production 조회 전용 역할·운영 배포를 뜻하지 않는다. 실제 Gemini 2건은 공급자 quota를 소비하며 결과는 그 시점 관측이다. FE 반영은 담당자 몫이다.

### 5.2 Codex 실행 전 확인

실제 Claude 설계 검수 UTC05:03:56~05:05:54, exit0·8turns·is_error=false·denial0. MD SHA326a00496d4657d3e924ef94a628e04f736492516db68cd711c419bb8c860c53→59be7cbbb227ad316c5963b9bd8203acfebc7f7ee4f2d3376ad00b58f208830e. 설계 조건부 PASS이며 실행 검증을 대신하지 않는다.

G1: 활동 중인 ETL 프로세스0·SpotON 이름의 예약 작업0을 확인했고 이 작업에서 원천/legacy DML은 수행하지 않는다. 외부 사용자의 미래 실행을 완전히 차단했다고 주장하지 않으며 전체 hash·쓰기 카운터·새 revision으로 변화 여부를 검사한다. G2: migrations/env.py의 injected connection/run_with_connection은 context.begin_transaction으로 같은 전달 트랜잭션을 사용한다. engine.begin 안에서 command.upgrade(0012)를 실행하고 같은 트랜잭션에서 확인한다. timeout은 PGOPTIONS 대신 해당 트랜잭션의 SET LOCAL lock5초/statement60초로 한정한다. G3: Settings 실제 기대0012를 확인했고 새 프로세스의 typed Settings에서도0012를 지정한다. G4: 기존8001의 listener140760과 부모148452, 실행 파일/명령줄을 비공개 기록에 보관하고 종료 직전 재대조한다.

백업은 **기준 hash를 구한 동일 READ ONLY RR 트랜잭션의 pg_export_snapshot()을 pg_dump에 전달**했다. 따라서 덤프와 표별 전체 행 hash는 같은 시점이다. 21개 public 표(확장 표·alembic_version도 포함)의 원본→복원본→원본 재확인이 모두 같았고 stores689440행이다. custom dump97,875,726bytes, SHA256 a0b4276c75ebbbc8…이고96.985초에 복원 대조까지 완료했다. 덤프·절대 경로·원문은 저장소 밖에 둔다.

추가로 migration 전 원본과 복원본의 직접 ST_AsEWKB 좌표 digest·시퀀스 last_value/is_called·인덱스·기존 비내부 트리거가 같음을 확인했다. 제약 이름/FK/PK/UNIQUE는 같으나 CHECK15개의 pg_get_constraintdef 문자열은 복원 재파싱 후 AND 괄호/ARRAY cast 표기가 달랐다. 이를 문자 단위 동일로 보고하지 않는다. 기존 원본 정의는 별도 보관해 migration/publication 후 **동일 원본끼리 정확히** 비교한다. 쓰기 카운터는 migration 전부터 추가 수집한 보조 증빙이며 백업 직전 값을 소급해 만들지 않았다. 이 실제 일관 snapshot 방식과 보조 증빙의 수집 시점을1~2절 일반 계획보다 우선하는 실행 기록으로 구분한다.


### 5.3 실제 로컬 적용·HTTP 검증 결과

Codex가 사용자 승인 범위에서 실제 수행했다. migration0012를 기존 spoton_app 소유자 연결의 단일 트랜잭션으로 적용하고 ALWAYS trigger·revision0을 확인했다. 기존5종 브랜드 자료와 소진공137173행/202609 snapshot을 재사용해1세대 공개했다. 추정8778·미확인347057(지원 인허가355835행)이며 실제 지점 전수/계약/정확도 확정을 뜻하지 않는다. 소진공 파일 SHA c4b4f3cb00d3d96e75e8d31c6aa1241f6dd7d276985954553deed91ea26a34c9. 공개 후 dry-run은 같은 generation/fingerprint를 반환했고 재쓰기는 생략해 activated_at을 불필요하게 갱신하지 않았다. 공개/재계획124.953초다.

기존20개 표(alembic_version만 제외)의 전 필드/좌표 hash는 migration·공개·최종 HTTP 검증 후 모두 같고 stores689440행이다. 직접 EWKB·기존 시퀀스·인덱스/제약/비내부 트리거 정의도 보존됐다. 새 state 표에 따른 SERIAL 시퀀스2개는 새 객체로 구분했고 기존 시퀀스 변화로 보고하지 않았다. 기존 표 쓰기 카운터와 새 source_revision/validated_source_revision=0도 유지됐다. 새 표5개 SELECT 권한은 실제 로컬 서버 역할로 확인했다. .env SHA도 적용 전과 같다.

임시8002에서 카페/음식점 각각12조건, 총24조건의 nearby=snapshot=활동=Risk count를 확인했다. 잘못된 입력7종은422/no-store, 같은 건물의 업종 조건별 history10건이 같았다. localhost/127.0.0.1의5180 CORS preflight도 통과했다. 종료 직전 기존8001 PID/부모/실행파일/명령줄을 기록과 재대조한 뒤 교체했다. UTC05:10:48에 새8001 ready200을 기록했다. 기존8000 listener3284는 유지했고, 검증 후 임시8002는 종료했다. DB0012 적용부터 새8001 교체 사이에는 기존0011 기대 서버의 ready가 불일치할 수 있는 로컬 작업 구간이 있었으며 무중단 배포라고 주장하지 않는다.

최종8001에서도 동일24조건/네 endpoint 수 일치, history10건 불변, 잘못된 입력7종422/no-store, CORS, health/ready200, Risk 동시3건200/본문동일을 통과했다. 최종 검증 GET113회 중 최대0.859초였다(이 PC·해당 조건에서의 관측이며 운영 성능 보장이 아님).

실제 Gemini HTTP 전송2건/성공2건을 서버의 llm_http_attempt 집계로 확인했다. cafe/restaurant chain 해석은 각각4문단·verification.passed=true·숫자39/42개 검사·불일치0·regenerated=false, Risk 동종업체18/21과 일치했다. 음식점에는 실제 근처 건물의 전체 history10건도 포함했다. prompt는 chain-risk-interpret-v1, model은 gemini-3.5-flash-lite다. 원문 주소/점포/인허가/좌표/내부 세대·식별자가 outbound evidence에 없는 것도 대조했다. 동일 요청 재호출은200/본문·evidence·context hash가 같고, 추가 provider 호출이 없어 선택 캐시 재사용도 확인됐다.

최초 실행 검증 스크립트가 재호출의 generated_at까지 전체 data 동등 비교해 단언에 실패했다. 실제 AI 요청들은200이었으며 render_interpretation이 매 응답 generated_at을 새로 만드는 기존 계약임을 대조했다. 검증 스크립트만 수정해 본문/근거/context와 검증 통과를 비교한 뒤 최종 검증 전체가 통과했다. 앱 코드는 변경하지 않았고, 공급자 실호출은 전체2건 그대로다. 테스트 성공을 만들기 위해 모델/한도/DB SQL3초를 바꾸지 않았다.

FE 전달 자료는 [로컬 연결 안내](../fe-local-chain-test-connection.md)다. localhost는 이 PC에 한정되며 FE/Vercel/Render 배포·다른 PC의 원격 접속·production 읽기 전용 역할은 별도다. 외부 담당자에게 메시지를 보내지 않았다. 백업/복원 DB/비공개 실행 증빙은 저장소 밖에 보존한다.

최종 집계 표(현재 관측 기준, radius500m):

| 업종 | 전체 | 체인 추정만 | 확인 비체인만 | 확인 체인만 |
|---|---:|---:|---:|---:|
| cafe | 150 | 18 | 0 | 0 |
| restaurant | 566 | 21 | 0 | 0 |

기록 시각 UTC 2026-11-15T05:14:07.134075+00:00. 실제 최종 Claude 재검수와 문서 PR/CI 결과는 후속 절에 기록한다.

### 5.4 Claude Code 운영 적용 재검수 (2026-11-15, Read/Edit만 사용)

범위: 이 MD와 요청에 함께 첨부된 0012 migration·etl/chains/publication.py·etl/localdata/runner.py·app/services/readiness.py·app/services/chains.py·migrations/env.py·app/core/config.py·docs/fe-local-chain-test-connection.md 원문, Codex 실행 결과 JSON을 정적으로 대조했다. 셸/DB/Git/네트워크/테스트는 실행하지 않았고 이 MD 외 파일은 열거나 수정하지 않았다. 아래 실행 수치는 모두 Codex가 기록한 결과의 인용이며 이 검수가 재현한 값이 아니다. etl/chains/compare·maintenance·create_db_engine 원문은 받지 않아 검토하지 않았다.

판정: **PASS (차단 결함0).** 기록된 실행 절차·결과가 코드 동작과 모순되지 않는다. 아래 정정3건은 MD에 직접 반영했고, 권고는 완료 조건이 아니다.

정적 대조 결과:
1. 백업 증빙: hash를 계산한 READ ONLY RR 트랜잭션의 pg_export_snapshot()을 pg_dump에 넘겼다면 덤프와 H0은 같은 MVCC 시점이므로, 5.1 설계(백업 전 H0+쓰기 정지)보다 강한 근거다. 복원본 21표 전체 hash 일치로 데이터 복원 가능성이 확인된다. 다만 CHECK15개 정의 문자열이 달라 **복원본 스키마의 CHECK 의미 동등성은 기계적으로 증명되지 않았다**. 롤백에 복원본을 실제 사용할 경우 정규화 비교나 폐기용 DB 거절 사례로 먼저 확인할 것을 권고한다(데이터 hash 결론에는 영향 없음).
2. G2 확정: env.py는 주입 connection에 context.begin_transaction()을 쓰고, 이미 외부 트랜잭션(engine.begin) 안이면 Alembic이 별도 commit하지 않으므로 SET LOCAL timeout·0012 DDL·사후 확인이 한 트랜잭션에 묶인다. transaction_per_migration 설정도 없다. G3: Settings 기본 기대 revision이 0012이고 연결 예산 기본값(2×1×(3+0+1)=8≤8)도 맞다. .env 값은 보지 않았다.
3. 잠금(정정): CREATE TRIGGER/ENABLE ALWAYS의 SHARE ROW EXCLUSIVE와 publication 쓰기의 stores SHARE·state EXCLUSIVE는 모두 ACCESS SHARE와 충돌하지 않는다. 따라서 조회 서버는 migration/공개를 막지 않고, 반대로 막히지도 않는다. 충돌 상대는 writer·(auto)vacuum/analyze·인덱스 생성이다. 1절 2단계 서술을 이에 맞게 고쳤다.
4. 트리거·revision: source_revision의 tgtype=60(AFTER STATEMENT, INSERT|DELETE|UPDATE|TRUNCATE)·prosecdef·proconfig 검사는 0012 정의와 일치한다. 트리거 함수 EXECUTE 권한은 CREATE TRIGGER 시점에만 검사되므로 PUBLIC 회수가 다른 writer의 트리거 발화를 막지 않는다. 공개 후 revision=validated_source_revision=0이면 drift=false이며 기록과 맞다.
5. publication: 쓰기 인자 expected_plan=fingerprint, expected_active=none, 재계획 동일 generation(uuid5(fingerprint))은 코드와 일치한다. 재쓰기를 생략해 activated_at을 갱신하지 않은 판단은 5.1 권고와 같다. estimated8778+unknown347057=355835이므로 conflict는0이며, known_count=8778·row_count=355835로 해석된다.
6. 스키마 차이(정정): chain_source_state/chain_publication_state의 SmallInteger 단일 PK는 시퀀스를 만들므로 "차이는 트리거 하나뿐"은 기존 객체 기준으로만 성립한다. 3단계와 2절 첫 항목에 새 함수·시퀀스2개를 추가 객체로 명시했다(5.3의 시퀀스2개 구분과 일치).
7. 진리표: 24조건 모두 unknown을 명시해 계약상 거절 조합이 없었으므로 등식 대상 24·제외0이다. 수치 패턴(chain/include=전체, non_chain/include/confirmed_only=전체, non_chain/include/include_estimates=전체−추정, */exclude/confirmed_only=0)은 ChainSelection.predicate()와 일치한다.
8. readiness/역할: app_env=test는 revision만 검사하므로 ready200과 "새 표 SELECT 권한" 확인은 소유자 spoton_app에서 자명하게 성립하며 조회 전용 역할 증빙이 아니다. 3절·FE 문서가 이미 구분해 둔 것을 확인했다.
9. FE 전달 문서: 절대 경로·덤프·키·원문 점포 없음, SHA 앞16자만 공개, 필터 진리표·source_drift/stale_input 경계·v1/v2 공유 한도·generated_at 비교 제외가 코드와 맞다. 이 검수에서는 수정하지 않았다.

권고(비차단):
- R1. 8001은 .env 밖의 프로세스 설정(app_env=test·CORS5180·필요 시 기대 revision0012)으로 숨김 실행 중이므로 PC 재부팅/종료 후 자동 복구되지 않는다. 비공개 보관한 기동 인자로 재기동하고 health/ready·brands/status를 다시 확인해야 한다는 점을 FE 전달 시 함께 안내하는 것이 좋다.
- R2. 기존8000(구버전)은 0012 DB를 읽기만 하므로 트리거 영향은 없지만, 이번 v2 검증 대상이 아님을 유지한다.
- R3. 복원본 DB는 이름이 spoton_dev가 아니어서 ETL 쓰기 대상이 될 수 없다. 보관 중에도 원문 점포 자료를 포함하므로 백업 파일과 같은 비공개 보관 원칙을 적용한다.

남는 한계: 로컬 test·소유자 역할 검증이며 Render/production 읽기 전용 역할·운영 배포·FE 반영 완료가 아니다. 쓰기 카운터는 migration 전부터의 보조 증빙이다. 문서 PR/CI 결과는 이 검수 범위 밖이며 수행 후 별도로 기록한다.

### 5.5 Codex 최종 대조·검수 증빙

실제 Claude 최종 검수 UTC05:14:07~05:16:20, exit0·6turns·is_error=false·denial0. MD SHA ece5fffb7258757b0c6357844206552169b42f5037405c135b44c373a89e8d37→0ecc852659bf201e80ed76c9e4aa4f4730b6b59d6e332b5b69d01db015844b2f. PASS/차단 결함0이며 Claude가 DB/테스트/배포를 수행한 기록이 아니다.

최종 HTTP 성공 후 원본20표 전 필드 hash·직접 EWKB·기존 시퀀스/정의·쓰기 카운터·revision0·.env 보존을 다시 확인했다. Claude의 잠금/시퀀스/CHECK 정정을 대조하고 FE 안내에 PC 재시작 후 기동/재확인을 명시했다. 실제 실행/검수 범위는 이 문서대로 로컬이며 운영 환경 적용이나 담당자 통보를 완료했다고 표시하지 않는다. 앱/ETL/테스트 소스는 develop cdc5513과 같으며 이번 PR은 적용 기록과 BE 전달 문서만 바꾼다. develop PR의 최종 커밋 CI/CodeQL을 확인한 뒤 저장소 절차에 따라 병합한다.
