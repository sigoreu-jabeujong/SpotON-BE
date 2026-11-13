# #109 Render 무료 검증 환경 전환

> 사용자 후속 변경: 기존 자원을 삭제했다고 알렸으나 API상 두 자원은 user suspended 상태다. 카드 삭제 완료를 사용자가 확인했다. 유료 자원을 재개하지 않고 Free 생성만 실제 시험한다. 아래 최초 계획과 충돌하면 마지막 Codex 결정을 따른다.

- 사용자 승인: BE와 DB 모두 무료로 전환. 이전 유료 복제본의 데이터·백업 검증 후 삭제는 월별 계산·저장공간 과금 종료에 필요한 작업으로 이 범위에 포함한다. 카드 삭제는 수행하지 않는다.
- 이슈: https://github.com/sigoreu-jabeujong/SpotON-BE/issues/109
- 현재: 웹 spoton-be-check, 0.5c-512mb; DB spoton-db-check, 2c-4g/10GB. 실제 DB 약675MB. 원본 개발DB와97.9MB 덤프·지문은 별도 비공개 디렉터리에 있다.

## 1. 전환 계획

1. 현재 유료 DB의20테이블 전체 비공간 행/geometry 지문·metadata를 READ ONLY로 확인하고 보관 덤프 SHA와 기존 baseline을 대조한다. 덤프 목록을 pg_restore로 읽을 수 있는지 확인한다. 불일치하면 새 일관 덤프와 기준부터 만들고 삭제하지 않는다.
2. 같은 계정·싱가포르에 plan=free, PostgreSQL17, DB명 spoton_free_check의 새 DB를 생성한다. 기존10GB 볼륨을1GB로 축소하는 방식을 사용하지 않는다. 외부 허용은 검증 PC /32 한 개로 지정한다. 새 ID·현재 DB명/계정·빈 앱 스키마·버전·PostGIS를 검사한다.
3. 빈 대상에 public PostGIS 확장을 설치하고 원래 검증한 TOC 방식으로 앱20테이블·50인덱스·110제약·3시퀀스를 복원한다. 확장 내부/소유권/GRANT를 덮어쓰지 않는다. 외부 TLS verify-full, pg_restore single-transaction/exit-on-error, 유지보수 ANALYZE를 사용한다. 데이터나 날짜/업종을 줄여 맞추지 않는다.
4. source.dump baseline과 free DB의 전체 지문, 기존 paid DB metadata와 새 DB metadata, ORM/head0011을 대조한다. 무료0.1CPU/256MB에서3초 SQL 제한을 유지하며 주요 API·조건부 상태·공통 오류 외피를 확인한다. 복원 실패 시 유료 환경에 계속 과금되도록 방치하지 않고 비용 종료와 서비스 유지 중 충돌을 알리며 가능한 무료 대안을 검토한다.
5. 새 reader spoton_api를 LOGIN/비관리/NOINHERIT/연결8/기본READONLY/SQL3초로 만든다. public/DB CREATE·TEMP·DML·시퀀스 쓰기·소유 계정 SET ROLE을 막고 SELECT만 부여한다. 신규 암호는 별도 Windows DPAPI에 저장하며 이전 자격증명과 파일을 덮어쓰지 않는다.
6. 기존 BE를 plan=free로 변경하고 DATABASE_URL만 새 내부 TLS require/reader 값으로 교체한다. envVar 단일 갱신으로 주소 키·CORS·워커1/풀3/overflow0/예산8·LLM 미설정을 보존한다. 이전 검증 commit56e174e를 명시해 수동 deploy한다. 무료 워커 CPU 저하의 영향도 확인한다. FE와 로컬 .env·개발DB는 유지한다.
7. live/ready와 공개24API JSON 대조·경계3건·동시3의6요청·주소 검색·CORS·AI503를 확인한다. 일시적인 cold start와 정상 조회 시간 초과를 구분한다. 실패 시 SQL 제한이나 표본을 몰래 변경하지 않고 수정 근거를 남긴다.
8. 삭제 직전 old ID/이름/계정/리전, 새 free DB의 ID/plan/만료일, 현재 BE free 설정/실제 새 대상, dump hash/전체 데이터 검증/공개 API 결과를 다시 확인한다. 이전 유료 DB만 DELETE한다. API에서404, workspace의 유료 리소스0을 확인한다. 삭제 전후 source 개발DB는 변경하지 않는다.
9. 무료750시간/BE15분 절전·재시작지연, DB1GB/30일 만료/백업없음, 이미 발생한 요금과 카드 유지 시 무료 한도 초과 가능성을 기록한다. Render 공개 API에 지원되는0원 build spend 설정이 있으면 적용하고, 없으면 설정했다고 주장하지 않는다. repo 문서 PR·CI·일반 develop Squash로 완료한다.

## 2. 실패·완료 기준

- 무료 DB가 복원 또는3초 대표 조회를 통과하지 못하면 기능 성공을 주장하지 않는다. 원본 개발DB·검증 덤프는 보존한다. 새 유료 리소스를 생성/증설하지 않는다.
- 유료 DB 삭제는 원격 복제본에만 적용한다. 덤프/새 DB 검증 전에 삭제하지 않는다. 서비스 공백은 명시하고 비용을 계속 발생시키는 유료 롤백을 무단 장기 유지하지 않는다.
- 카드 해제나 이미 발생한 청구의 취소를 수행하지 않는다. 무료 plan 전환을 무제한/영구0원으로 표현하지 않는다.
- 증빙·자격증명은 저장소 밖 비공개 보관, 공개 문서에는 비밀/접속 URL/외부 IP를 포함하지 않는다.

## 3. Claude Code 검토 요청

이 MD만 읽고 직접 수정한다. 코드/DB/네트워크/Git/.env/키에는 접근하지 않는다. 문서 단독 검토임을 명시하고 무료 DB의 용량/복원/성능, 백업 검증, reader 권한, env 전환과 재배포, 삭제 게이트 및 과금 종료의 누락을 아래에 지적한다. 통상 선택은 Codex가 최종 판단한다.

### Claude 검토 결과

> **문서 단독 검토**: 이 MD 파일만 읽고 작성했다. 코드·DB·Render API·네트워크·Git·.env·키에는 접근하지 않았고 명령도 실행하지 않았다. 아래 수치나 Render 정책은 실측 결과가 아니며, "확인 필요"로 표시한 항목은 실행 전에 Render 공식 문서나 API로 확인해야 한다.

#### P1 (실행/삭제 전에 반드시 보완)

1. **무료 DB 용량 게이트가 없다(§1-2, §1-3).** 실제 DB 약675MB는 1GB 한도에 비해 여유가 작다. 측정 기준(`pg_database_size`인지, 인덱스·TOAST 포함인지)도 적혀 있지 않다. single-transaction 복원 중에는 WAL·GiST 인덱스 생성·ANALYZE 때문에 저장공간을 일시적으로 더 쓴다.
   - 보완: 유료 DB에서 `pg_database_size`와 테이블별 `pg_total_relation_size` 합계를 미리 기록한다.
   - "복원 후 크기 ≤ 약 800MB(80%)"처럼 진행 여부를 가르는 수치 기준을 명시한다.
   - 한도를 초과했을 때 Render 무료 DB가 어떻게 동작하는지(쓰기 중단/정지 등) 확인 필요.
   - 초과할 것으로 예상되면 복원을 시작하지 않고 §1-4의 실패 경로로 보낸다.
2. **유료 DB를 삭제하면 백업이 사실상 단일 사본뿐이다(§1-1, §1-8, §1-9).** 무료 DB는 백업이 없고 30일 뒤 만료된다. 따라서 삭제 뒤 복구할 수 있는 원본은 비공개 디렉터리의 97.9MB 덤프와 원본 개발DB뿐이다.
   - 보완: 삭제 게이트에 "덤프 사본을 물리적으로 다른 위치(외장/다른 디스크)에 1개 더 두고 SHA 일치 확인"을 추가한다.
   - `pg_restore -l`로 TOC 목록을 읽는 것만으로는 복원 가능성이 증명되지 않는다. §1-3에서 무료 DB에 복원·검증을 성공한 것을 덤프 복원 검증으로 간주한다고 명시하고, 그 지문 결과를 삭제 게이트 증빙으로 연결한다.
   - 유료 DB에 Render가 관리하는 백업·PITR 스냅샷이 있다면, 삭제할 때 함께 사라지는지 확인 필요. 필요하면 삭제 전에 내보내기 여부를 결정한다.
3. **무료 DB 생성 가능성의 전제가 검증되지 않았다(§1-2).** Render 무료 Postgres는 workspace당 1개로 제한되는 것으로 알고 있다(확인 필요). 이미 무료 DB가 있으면 생성이 실패한다.
   - 30일 만료는 "생성 시점" 기준이므로 만료일을 기록하고, 만료 전 조치(재생성+덤프 재복원 runbook 또는 종료)를 미리 정해야 한다. 현재 §1-9는 "기록"만 한다.
4. **reader 권한 설계에 빈틈이 있다(§1-5).**
   - `NOINHERIT`는 `SET ROLE`을 막지 못한다. 소유 계정 role의 **멤버가 아님**을 `pg_auth_members`로 확인하는 검증을 넣는다.
   - `default_transaction_read_only`와 `statement_timeout`은 클라이언트가 `SET`으로 바꿀 수 있다. 보안 경계는 GRANT/REVOKE임을 명시한다.
   - TEMP와 CONNECT는 기본적으로 PUBLIC에 부여된다. 그래서 `REVOKE TEMP ON DATABASE ... FROM PUBLIC`이 필요하다. 이것이 소유 계정·복원 절차에 영향이 없는지도 확인한다.
   - PostGIS용 `spatial_ref_sys` SELECT, schema `USAGE`, 이후 테이블에 대한 `ALTER DEFAULT PRIVILEGES` 범위를 명시한다.
   - Render 기본 사용자에게 `CREATEROLE`과 PostGIS `CREATE EXTENSION` 권한이 있는지 확인 필요. 없을 때의 대안(기본 계정 사용 금지 여부)을 정해야 한다.
   - 연결8은 앱 풀3+overflow0과 검증 세션을 합친 것이다. 무료 DB의 `max_connections` 한도 안에 드는지 확인한다.
5. **env 전환·재배포 순서에서 의도하지 않은 배포가 일어날 수 있다(§1-6).**
   - plan 변경이나 envVar 갱신이 자동 재시작·자동 배포를 일으키면, 56e174e가 아닌 브랜치 최신 commit이 배포될 수 있다. 사전에 autoDeploy 상태를 확인하고 꺼 둔다. 갱신 후 배포 이력의 commit도 확인한다.
   - Render env-vars 일괄 PUT은 전체를 덮어쓴다. 키 하나만 바꾸는 endpoint를 쓴다고 명시하고, 변경 전후 키 목록 diff(값 제외)를 증빙으로 남긴다.
   - 내부 URL은 같은 리전에서만 쓸 수 있다. BE 리전이 싱가포르인지 확인하는 항목을 넣는다.
   - 롤백 경로가 없다. 유료 DB 삭제 전까지는 이전 `DATABASE_URL`(DPAPI 보관)로 되돌리는 절차를, 삭제 후에는 덤프 재복원 절차를 명시한다.
6. **삭제 게이트의 참조 점검 범위가 BE 하나뿐이다(§1-8).** FE·다른 서비스·cron·로컬 .env·문서 등이 유료 DB 호스트를 참조하는지 확인해 "참조 0"을 게이트에 넣어야 한다. 참조 여부는 값이 아니라 호스트 식별자로 대조한다.
   - "workspace의 유료 리소스0"의 범위(웹·DB·디스크·기타 서비스)를 정의한다.
   - 과금 종료는 API 404만으로 증명되지 않는다. Render Billing 화면에서 다음 청구 예정 항목을 확인하는 수동 증빙을 추가한다(일할 계산된 최종 청구는 발생할 수 있음).

#### P2 (권장 보완)

1. **성능 검증 조건(§1-4, §1-7):** 무료 DB 0.1CPU/256MB에서는 675MB가 캐시에 다 들어가지 않는다. 첫 조회(콜드 캐시)와 반복 조회를 나눠 기록하고, 3초 판정을 어느 쪽 기준으로 할지 정한다.
   - 복원 세션에서는 `statement_timeout`을 해제하거나 따로 지정한다. 앞으로 reader에 3초를 적용하더라도 복원/ANALYZE가 끊기면 안 된다.
   - GiST 인덱스 생성 시간이 길 수 있으므로 복원 타임아웃·재시도 기준을 정한다.
2. **PostGIS/PG 버전 정합성(§1-2, §1-3):** 유료 DB와 무료 DB의 PostgreSQL 마이너 버전과 PostGIS 버전을 함께 기록한다. 덤프가 확장 버전에 의존하는 객체를 포함하지 않는지 확인한다.
3. **완료 판정 수치화(§1-7, §2):** "공개24API JSON 대조"의 비교 규칙을 명시한다(타임스탬프·정렬 등 비결정 필드 처리). cold start와 시간 초과를 가르는 기준도 수치로 둔다(예: 첫 요청 제외, 이후 N회 연속 성공).
4. **무료 웹 한도(§1-9):** 750시간은 workspace 전체의 무료 웹 서비스가 함께 쓰는 한도인지 확인 필요. 15분 절전 때문에 생기는 첫 요청 지연이 FE 타임아웃과 충돌하지 않는지 기록한다.
5. **복원 실패 시 경로(§1-4, §2):** "비용 종료와 서비스 유지 충돌을 알린다"는 문장에 결정 주체와 기한이 없다. 실패하면 유료 DB를 유지할지 즉시 삭제할지 사용자 승인 지점을 하나 두는 것을 권장한다.
6. **증빙 보관(§2):** 저장소 밖에 보관하는 증빙의 목록을 정의한다(지문 결과, 크기, 버전, 권한 검증 쿼리 결과, 배포 commit, 삭제 응답). PR 문서에는 비밀이 아닌 요약만 남긴다고 명시하면 공개 범위가 분명해진다.

#### 종합

전체 방향(검증 후 삭제, 축소 대신 신규 생성, 비밀 비공개, 무료 한계 명시)은 타당하다. 다만 실행·삭제 전에 P1의 6개 항목을 보완해야 한다. 특히 **용량 수치 게이트**, **덤프 2차 사본**, **reader의 SET ROLE/TEMP 차단 검증**, **autoDeploy·롤백 경로**를 보완한 뒤 진행할 것을 권고한다. 최종 선택은 Codex가 판단한다.

## 4. Codex 최종 결정과 변경된 전제

- Claude의 실제 문서 검토를 읽었다. 현재 old DB는 사용자 중지 상태이며 재개하면 유료 실행이 재개될 수 있으므로 새 원격 지문 조회를 위해 재개하지 않는다. 이미 완료한 전체 지문·API 대조, 보존 덤프 SHA 및 개발 원본·새 무료 복원 지문을 근거로 삼는다. 이 한계를 결과에 기록한다.
- 무료 DB를 새로 만들고 실제1GB 용량을 확인한다. 복원 전 기준675MB, 복원 후 pg_database_size800MB 이내를 진행 기준으로 둔다. 실제 저장공간 제한으로 중지되면 성공을 주장하지 않고 유료 증설하지 않는다. free 자원 외 plan은 코드에서 거절한다.
- 기존 덤프를 SHA 검증하고 별도 작업 디렉터리에 사본을 둔다. 서로 다른 물리 디스크 확보는 현재 보장할 수 없으며 개발DB/기존덤프/복원 검증된 새 무료DB로 복구 근거를 확보한다. 물리적으로 독립된 재해 백업으로 주장하지 않는다.
- 역할 멤버십 및 READ WRITE 상태의 DML/CREATE/TEMP/SET ROLE 차단을 검증한다. 새 테이블의 default privileges는 자동 부여하지 않으며 추후 migration 때 SELECT 갱신이 필요하다. 관리자 계정을 API에 사용하지 않는다.
- 기존 무료 전환은 BE plan=free 갱신 뒤 user 중지 해제와 명시적 commit 배포로 진행한다. API가 카드 없는 기존 paid→free 변경을 거부하면 새 free 웹 서비스를 생성하고 이전 suspended 유료 웹 서비스를 검증 후 삭제한다. 새 URL은 BE 측 FE 전달 문서에 기록한다. 일괄 env overwrite 대신 DB env 단일 갱신을 사용한다.
- 무료에서의 실제 SQL 시간 초과는 숨기거나 제한을 늘리지 않는다. 전체 JSON을 그대로 비교하고 단일/반복 및 동시3 요청 결과를 기록한다. first cold start의 HTTP 지연과 DB SQL3초 제한은 분리한다.
- 삭제 전 다른 workspace 서비스·Key Value·관련 disk 목록과 새 BE 대상/plan을 확인한다. 과거 local .env는 로컬DB만 가리키며 이전 원격DB를 주입한 로컬 컨테이너는 이미 삭제했다. 원격 조회 자격증명은 이전 증빙과 함께 보존하되 앱에는 사용하지 않는다.
- 사용자 승인은 무료 전환과 비용 종료를 위한 이전 유료 복제본 정리를 포함한다. 검증된 복원 전에는 이전 유료DB를 삭제하지 않는다. 카드 추가/유료 재개·새 유료 플랜/청구 취소를 수행하지 않는다. Billing의 실제 청구액/카드 상태를 API로 읽을 수 없으므로 리소스 Free/이전ID404 확인과 사용자 카드 삭제 확인을 구분한다.
- 무료 DB 실제 expiresAt을 기록하고 만료 전에 검증을 종료하거나 로컬 덤프에서 새 검증 DB를 다시 만들도록 runbook을 남긴다. 자동 재생성·예약·영구 무료 운영은 제공하지 않는다.

## 5. 실행 중 확인한 무료 환경 차이와 최종 운영 선택

- 카드 삭제 확인 후 PostgreSQL17 Free와 새 Docker Web Free 생성이 실제 성공했다. 기존 유료 웹의 Free 변경은 API400으로 거절돼 새 웹을 만들었다. Free는 maxShutdownDelaySeconds45 설정도 거절하므로 해당 필드를 생략해 플랫폼 기본 종료 대기를 사용한다. 새 웹은 당시 CI가 통과한 develop d449c5f(commit56e174e와 앱/ETL/lock/Docker 내용 동일)에서 배포했다.
- 복원1068.92초·20테이블 VACUUM/ANALYZE 완료, pg_database_size675,092,147 bytes로800MB 게이트를 통과했다. 전체 행/geometry 해시 대조는 Free에서 유지보수120초를 초과해 이 작업에만600초를 사용한다. API 실행 제한과 별개다.
- 신규 reader SELECT20개 및 READ WRITE에서 INSERT/CREATE/TEMP/소유 역할 SET ROLE 거절4개를 통과했다. 이 권한 작업과 초기 API 검증은 전체 해시 작업과 독립적으로 진행한다. **기존 유료 복제본 삭제 및 최종 성공 표시는 전체 지문 검증 완료 후에만 허용한다.**
- Free의3초 SQL 실행 제한에서 snapshot/Risk 요청이500을 반환했고, SQLAlchemy handle_error 계측으로 SQLSTATE57014를 확인했다. JIT off만으로 해소되지 않았다. Free에서는 유료 기준3초를 안정적으로 유지할 수 없다고 판단했다.
- 사용자 최우선 조건인 무료 사용과 기존 데이터/응답 유지를 위해 **무료 검증 배포만 statement_timeout10초·API 풀1·overflow0·pool 대기15초**로 변경한다. 로컬 .env/코드 기본3초/기존 유료 환경 규칙은 변경하지 않는다. 결과·FE 전달 문서에 지연과 Free 전용 설정을 명시한다. 단순히 실패를 숨겨3초 통과로 기록하지 않는다.
- 워커1·별도 ready1·교체2배 상한은4개이며 예산/reader 제한8 안이다. readiness 자체는 기존 HTTP2.5초·SQL750ms 및 캐시를 유지한다. LLM 키는 생략한다.
- 새 무료 웹은 검증용 endpoint이므로 복원·용량·권한 확인 후 먼저 생성해 배포 가능성을 검증한다. 전체 데이터 검증과 API 검증이 끝날 때까지 이전 유료 리소스 삭제와 완료 표시는 보류한다. 예외·조정 이력과 최종 재검증을 결과에 남긴다.

## 6. Free Risk 집계용 운영 인덱스 검토안

SQL10초에서도 음식점 Risk가57014로 실패했다. 실패 SQL은 서울 전체 reference aggregate이며 EXPLAIN에서 ix_stores_provenance의 Index Scan을 사용하고 heap 접근이 필요하다. estimated cost41753, JIT 사용없음을 확인했다. 시간 제한을 계속 늘리는 대신 물리적 읽기 최적화를 검토한다.

아래는 새 Free 복제본에만 추가할 운영 인덱스다. 앱 SQL·계산식·행·공간/기간 조건·기존50인덱스·head0011·모델은 변경하지 않는다. 향후 정식 공통 튜닝은 별도 migration으로 승격할 수 있다. 기본50개+운영1개를 구분해 검증하고, Alembic 모델 비교에서 이 정확한 운영 인덱스만 예상 차이로 명시한다. 원래 baseline/dump는 수정하지 않는다. 운영 인덱스 SQL을 복원 runbook에 보존한다.

```sql
CREATE INDEX ops_free_risk_cover
ON public.stores (category, sub_category, open_date)
INCLUDE (close_date, status, date_flag, is_temporary, source, area_m2)
WHERE deleted_at IS NULL
  AND category_review_flag IS NOT TRUE
  AND geom IS NOT NULL;
```

대상 aggregate의 SELECT/FILTER/WHERE 컬럼은 모두 key/include 또는 partial predicate에 포함된다. geom은 NOT NULL 판정에만 사용되므로 predicate로 충족하며 큰 geometry 자체는 INCLUDE하지 않는다. batch_id는 해당 실패 SQL에서 사용하지 않는다. 기존 source별 출처 검증은 기존 인덱스를 유지한다. VACUUM 완료된 정적 테이블에서 Index Only Scan 및 Heap Fetches, 단일 SQL 실행 시간과 동일 API 전체 JSON을 재검증한다. 신규 인덱스 추가 뒤 전체 DB800MB 게이트를 다시 검사한다.

인덱스 생성은 별도 소유자 연결에서 maintenance_work_mem16MB·단일 writer·시간 제한1200초, 고정 대상/이름/SQL로 실행한다. 실패 시 잘못된 성공이나 데이터 변경을 주장하지 않는다. 다른 Free/paid 자원으로 자동 증설하지 않는다. row/geometry 전체 지문은 이 물리적 튜닝과 무관하게 원래 기준과 같아야 한다. 추가 인덱스를 무조건 무시하지 않고 catalog의 key/include·predicate·valid/ready를 대조한 뒤 정확히1개만 모델 비교에서 별도 처리한다.

### Claude 추가 검토 결과

위 운영 인덱스 안만 문서 단독으로 검토하고 이 절에 직접 의견을 남긴다. 실제 코드/DB/네트워크는 읽지 않는다. 적용/검증 완료로 주장하지 않는다.

> **문서 단독 한계**: §6 본문만 근거로 검토했다. 실패 SQL 원문, `stores` 행 수·컬럼 타입·평균 폭, EXPLAIN 실측(ANALYZE/BUFFERS)은 이 문서에 없다. 그래서 "모든 컬럼 포함" 주장과 크기 추정을 직접 검증하지 못했다. 아래 내용은 실행 전에 확인할 조건이며, 인덱스가 효과 있다는 판정이 아니다.

#### P1 (생성 전 보완)

1. **효과 가설의 근거가 부족하다.** 현재 근거는 estimated cost 41753과 "heap 접근 필요"뿐이다. 0.1CPU에서는 heap I/O가 아니라 집계·FILTER 연산(CPU)이 병목일 수 있다. 그렇다면 Index Only Scan이 되어도 10초를 넘을 수 있다.
   - 생성 전에 유지보수 세션(제한 600초)에서 `EXPLAIN (ANALYZE, BUFFERS)`로 실제 시간, `shared read`/`hit`, 대상 행 수를 기록한다. heap 읽기가 주요 비용인지 먼저 확인한다.
2. **partial predicate 적용 조건을 명시해야 한다.** planner는 쿼리 WHERE가 predicate를 **증명 가능하게 함축**할 때만 이 인덱스를 쓴다.
   - 실패 SQL이 `deleted_at IS NULL`, `category_review_flag IS NOT TRUE`를 문자 그대로(또는 증명 가능한 형태로) 포함하는지 확인한다. 예를 들어 `= false`, `NOT flag`, `COALESCE(...)` 형태이면 함축 증명이 실패할 수 있다.
   - predicate 쪽 조건값이 bind 파라미터면 generic plan에서 함축 증명이 실패한다. 앱 드라이버의 prepared/generic plan 동작까지 고려해 **앱과 같은 방식의 바인딩**으로 검증한다.
   - "geom은 NOT NULL 판정에만 사용" 주장은 실패 SQL에 `ST_*`/`&&` 같은 공간 조건이 전혀 없을 때만 성립한다. §6에 "공간/기간 조건 유지"라는 표현이 있으므로, 서울 전체 집계에 공간 필터가 정말 없는지 SQL 원문으로 확인한다. 공간 조건이 있으면 geom이 없어서 Index Only Scan이 불가능하다.
   - JOIN이나 하위 쿼리가 `stores`의 다른 컬럼(id, batch_id 등)을 참조하지 않는지도 확인한다.
3. **용량 게이트를 생성 "후"가 아니라 생성 "전"에 둬야 한다.** 현재 675MB에서 800MB 게이트까지 여유는 약 125MB다.
   - INCLUDE 인덱스는 B-tree 중복제거(dedup)를 쓰지 않는다. 행당 약 (튜플 헤더 + key 3 + include 6개 컬럼) 바이트가 든다.
   - 생성 전에 `행 수 × pg_stats.avg_width 합 + 오버헤드`로 크기를 추정한다. 추정치가 125MB 여유를 넘으면 생성하지 않는다.
   - 생성 중에는 maintenance_work_mem 16MB를 넘는 정렬이 temp 파일로 넘어가고 WAL도 쌓인다. 그래서 순간 디스크 사용량이 최종 인덱스 크기의 약 2배 이상이 될 수 있다. 1GB 한도에서 디스크가 가득 차면 WAL 쓰기 실패로 DB가 중단·복구될 수 있다(Render Free의 실제 동작 확인 필요). `temp_file_limit` 설정도 검토한다.
4. **생성 방식을 하나로 고정해야 한다.** 일반 `CREATE INDEX`(정적 테이블, 쓰기만 잠금)는 실패 시 전체가 롤백되고 파일도 남지 않는다. `CONCURRENTLY`는 실패하면 INVALID 인덱스가 남아 DROP이 필요하다.
   - 본문의 valid/ready 점검을 보면 어느 쪽인지 모호하다. 일반 `CREATE INDEX` + `lock_timeout`을 권장하며, 어느 쪽이든 명시한다.
   - 600초 전체 해시 작업과 동시에 실행하면 0.1CPU를 나눠 쓰게 되어 두 작업 시간이 모두 왜곡된다. 순차로 실행한다.
5. **롤백 SQL과 롤백 조건이 없다.**
   - runbook에 `DROP INDEX public.ops_free_risk_cover;`를 함께 보존한다.
   - 롤백 조건을 명시한다: ① 생성 후 800MB 초과 ② 계획에서 미사용 또는 여전히 57014 ③ 어떤 API든 JSON 불일치 ④ 다른 API 시간 회귀.
   - 효과가 없으면 공간만 쓰므로 유지하지 않는다. DROP 후 인덱스 50개 상태와 크기를 다시 기록한다.

#### P2 (검증·스키마 예외 정밀화)

1. **모델 비교 예외는 이름이 아니라 정의로 제한한다.** 다음을 모두 대조해 "예외 정확히 1개"를 판정한다.
   - `pg_get_indexdef(oid)`의 전체 문자열(key/INCLUDE/predicate)이 runbook SQL과 일치하는지
   - `indisvalid/indisready/indislive`
   - `stores` 인덱스 수 = 기존+1, DB 전체 51개
2. **Alembic 위험을 문서에 남긴다.** Free DB를 대상으로 `alembic revision --autogenerate`를 실행하면 이 인덱스의 `drop_index`가 생성된다. 이 DB를 autogenerate 대상으로 쓰지 않는다고 명시한다(env.py 변경 없이 운영 규칙으로 관리).
   - 앞으로 migration에서 INCLUDE 컬럼을 DROP/타입 변경하면 이 인덱스가 조용히 삭제되거나 재작성될 수 있다는 점도 적는다.
3. **기준 오염을 막는다.** §1-3·§1-4의 "50인덱스" 및 metadata 대조 문구와 충돌하지 않도록 "기준 50 + 운영 1"로 표기를 통일한다. Free DB에서 새로 뜬 덤프를 baseline으로 쓰지 않는다고 명시한다(현재 "원래 baseline 미수정"만 있음).
4. **결과 정확성 검증 시 주의할 점:** 인덱스는 행 데이터를 바꾸지 않는다. 하지만 계획이 바뀌면 ① ORDER BY가 없는 GROUP BY 결과의 순서 ② `area_m2`가 float일 때 SUM 합산 순서에 따른 끝자리가 달라질 수 있다.
   - 전체 JSON 불일치가 나면 비교 규칙을 바꾸지 말고 원인을 기록한다(본문의 "몰래 변경 금지" 원칙과 같다).
   - `IS NOT TRUE`는 NULL을 포함하므로, 기존 SQL의 NULL 처리와 같은 의미인지 확인한다.
5. **Index Only Scan 판정 기준을 수치로 둔다.**
   - `EXPLAIN (ANALYZE, BUFFERS)`에서 `Index Only Scan using ops_free_risk_cover`, `Heap Fetches` ≈ 0을 확인한다.
   - `pg_class.relallvisible / relpages` ≈ 1(VACUUM 이후)을 확인한다.
   - 실행 시간은 콜드(유휴 후 첫 실행)와 웜으로 나눠 기록한다. 10초 대비 여유와 3초 기준 미달 여부를 함께 기록한다.
   - 측정은 reader 역할과 실제 설정(10초, 풀1)으로 수행한다.
6. **다른 쿼리의 계획 변화를 확인한다.** 새 인덱스는 Risk 외의 `stores` 조회에서도 선택될 수 있다. Risk 1건만이 아니라 공개 24API JSON·시간, 동시 3 요청을 인덱스 생성 후 다시 실행한다. 전체 행/geometry 지문은 인덱스와 무관하게 같아야 하며, 지문 쿼리가 계획 순서에 의존하지 않는지(명시적 ORDER BY) 확인한다.

#### 종합

인덱스 1개를 Free 복제본에만 운영 예외로 두는 방향 자체는 타당하다. 시간 제한을 계속 늘리는 것보다 낫고, 앱·모델·baseline을 바꾸지 않는다. 다만 실제 SQL 원문으로 확인하지 않는 한 커버링과 predicate 함축은 가설이다.

생성 전에 다음 세 가지를 먼저 갖출 것을 권고한다.
- **EXPLAIN ANALYZE로 병목 확인**
- **사전 크기 추정과 순간 디스크 여유**
- **롤백 DROP SQL과 롤백 조건**

최종 판단은 Codex가 한다.

## 7. Codex 최종 적용·검증 결과 (2026-11-14)

- Claude 추가 검토를 읽고 실제 실패 SQL을 확인했다. SELECT/FILTER/WHERE의 모든 참조는 key/include 또는 정확한 고정 partial predicate로 충족되며 이 서울 전체 집계에 ST_* 조건·다른 테이블 JOIN·id/batch_id 참조는 없다. 바인딩된 원래 SQL 그대로 계획을 측정했다.
- eligible559,972행과 실제 avg_width로 보수적 인덱스87,355,632 bytes·최종762,447,779 bytes·temp/WAL allowance218,389,080 bytes를 추정해 최종800MB/순간900MB 게이트를 통과했다. 일반 CREATE INDEX·lock5초·정적 테이블·단일 소유 세션을 사용했다. 실패/효과없음/용량 초과/JSON 회귀 시 DROP 롤백 SQL을 [SQL 파일](../sql/render-free-risk-cover.sql)에 명시했다.
- 유지보수용 원래 SQL의 EXPLAIN ANALYZE는12,588.909ms, shared read65,665블록으로 heap 읽기 병목을 확인했다. 인덱스 생성21.88초·실제45,883,392 bytes, 전체DB721,131,187 bytes다. 생성 후 같은 바인딩 SQL은2,777.128ms·Index Only Scan·Heap Fetches0·shared read3,327블록이었다. 이는 단일 관측이며 SLA나 성능 보장이 아니다.
- 전체 지문은 서버 집계 정렬 중 DiskFull을 만났다. 데이터는 READ ONLY이며 DB available 상태였다. 서버는 원래와 동일한 행/geometry MD5만 named cursor10,000행씩 전송하고 로컬에서 ASCII(C) 정렬/연결MD5를 계산하도록 변경했다. 원래 baseline을 바꾸지 않고20테이블 전체 count/행MD5/NULL 수/EWKB MD5 일치를 통과했다. 기존50인덱스·110제약·3시퀀스·모델0/head0011도 통과했다.
- 운영 인덱스의 key/include/predicate·valid/ready/live를 확인하고, 이 정확한1개만 모델 비교에서 제외하면 예상하지 않은 차이0개·총51개를 확인했다. Free DB를 migration autogenerate 대상으로 사용하지 않으며 향후 컬럼/타입 변경 때 이 인덱스도 재검토한다. 원래 dump/baseline은 그대로 보존한다.
- 무료 웹 d449c5f는live다. SQL10초·풀1/대기15초·role8·ready2.5초/750ms를 유지한다. 공개24API 전체 JSON·경계3건·동시3으로카페Risk6건을 통과했다. cold health22.593초, health 제외24건 중 최장8.656초, 동시 요청 최장6.985초다. 주소 검색200·CORS200/400·AI503·내부 풀TLSv1.3을 확인했다. Free의 cold 지연은 FE 기본15초를 넘으므로 담당자에게 전달한다.
- 삭제 게이트 통과 후 이전 유료 웹/DB만 DELETE했고 각각404를 확인했다. 현재 workspace에 Free 웹1/DB1만 남고 paid compute·persistent disk·Key Value는0이다. 카드 등록 상태는 API가 아닌 사용자 완료 확인을 근거로 하며, 과거 요금 취소나 영구0원을 주장하지 않는다.
- 최종 요약·제약·복원 runbook은 [무료 전환 결과](../render-free-validation.md), FE URL/절전 대기는 [전달 문서](../fe-render-validation-api-request.md)를 따른다. 앱 코드·로컬 .env·개발DB·FE를 변경하지 않았다.
