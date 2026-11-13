# Render 무료 검증 환경 안내

마지막 구성·데이터·API 검증일은 **2026-11-14 (Asia/Seoul)**이다. 현재 Render 기준은 이 문서와 [FE 연결 안내](fe-render-validation-api-request.md)에서 관리한다.

## 1. 현재 구성

| 항목 | 설정 |
|---|---|
| API | https://spoton-be-free.onrender.com |
| API 문서 / 준비 상태 | [/docs](https://spoton-be-free.onrender.com/docs) / [/api/ready](https://spoton-be-free.onrender.com/api/ready) |
| BE | spoton-be-free / Free / srv-dbri09k9v7es73clfpl0 |
| DB | spoton-db-free / Free / dpg-dbrhh4rm8hqs73d2mlgg-a |
| 리전 | 같은 workspace의 Singapore |
| DB 버전 / 이름 | PostgreSQL17·PostGIS3.6.2 / spoton_free_check |
| DB 생성 / 만료 | 2026-11-13 23:02:59 / **2026-12-13 23:02:59 KST** |
| DB 크기 | 검증 당시721,131,187 bytes, 약721MB |
| Migration | 0011 |
| 배포 commit | d449c5f0e86778a15fddac28722d0d6833fe8779 |
| 자동 배포 | off, 검증한 commit을 수동 배포 |

검증 당시 남은 자원은 Free BE1개·Free DB1개이며, 유료 컴퓨팅·별도 지속 디스크·Key Value는0개다. 카드 삭제는 사용자가 확인했고, 이후 Free BE·DB 생성이 실제 성공했다. API로 카드나 청구 내역을 조회한 것은 아니다. DB를 새로 만들면 ID·내부 호스트·접속정보·만료일이 바뀐다.

## 2. BE 실행과 환경변수

Docker 이미지는 `docker build -t spoton-be .`로 만든다. 고정 Python·uv digest와 uv.lock, 비root UID10001을 사용하며 `python -m app.runtime`으로 실행한다. `.env`·덤프·Git·개발 의존성은 이미지에 포함하지 않는다. 시작 시 migration/ETL은 실행하지 않는다.

Render 환경변수에는 아래 Free 전용 값을 명시한다. 로컬 `.env`와 코드 기본 SQL3초·풀3/대기2초 설정은 그대로 둔다.

```dotenv
APP_ENV=staging
PORT=10000
WEB_CONCURRENCY=1
DATABASE_STATEMENT_TIMEOUT_MS=10000
DATABASE_POOL_SIZE=1
DATABASE_MAX_OVERFLOW=0
DATABASE_POOL_TIMEOUT=15
DATABASE_CONNECTION_BUDGET=8
DATABASE_EXPECTED_REVISION=0011
CORS_ORIGINS=http://localhost:5173
```

`DATABASE_URL`은 **새 DB의 내부 호스트·spoton_api 조회 역할·sslmode=require**로 구성해 Render 비밀 환경변수로 주입한다. 내부 TLS는 암호화를 요구하며 서버 인증서 검증을 보장하지 않는다. 외부 관리자 검증/복원은 verify-full과 CA를 사용하고, 외부 DB 접근은 검증 PC /32만 허용한다. 비밀번호·실제 DB URI·인증 토큰·외부 IP는 문서나 저장소에 넣지 않는다.

주소 조회용 `KAKAO_REST_API_KEY`, `JUSO_SEARCH_KEY`, `JUSO_COORD_KEY`만 별도로 설정한다. DB 소유 계정·정부 ETL·LLM 키는 BE에 전달하지 않는다. 현재 AI 해석은503 AI_UNAVAILABLE이다.

`/api/health`는 프로세스 검사다. Render health check는 `/api/ready`로 지정한다. 준비 검사는 head0011·조회 역할 권한을 확인하며 API 풀과 별도 연결1개, HTTP2.5초·SQL750ms·성공10초/실패1초 캐시·단일 실행 잠금을 사용한다. 실패는 기존 INTERNAL_ERROR500/no-store다.

인스턴스1·워커1에서 교체 상한은 `2 * workers * (pool + overflow + 1 readiness) = 4`로 예산/reader 제한8 안이다. 외부 reader 도구·추가 인스턴스는 따로 합산한다. Free는 맞춤 maxShutdownDelaySeconds 설정을 지원하지 않아 플랫폼 기본 종료 대기를 사용한다.

## 3. 운영 인덱스와 스키마

앱19개 테이블과 alembic_version을 합쳐20테이블이다. 기준50인덱스·110제약·3시퀀스·head0011을 유지하며, Free DB에만 [ops_free_risk_cover](sql/render-free-risk-cover.sql) 운영 인덱스1개를 추가해 총51개다. 데이터·계산식·API SQL·앱 모델을 변경하지 않는다.

이 인덱스는 서울 전체 Risk 집계에 필요한 컬럼을 커버한다. 실제 크기45,883,392 bytes이며 동일 집계의 단일 측정이12.589초에서2.777초로 줄었다. Index Only Scan·Heap Fetches0을 확인했다. 성능 보장이나 전체 HTTP 시간 상한은 아니다.

이 Free DB를 `alembic revision --autogenerate` 대상으로 쓰면 운영 인덱스 삭제가 제안될 수 있으므로 사용하지 않는다. 모델 비교에서 예외를 둘 때는 이름뿐 아니라 정확한 key/include·predicate·valid/ready/live를 확인하고 이1개만 구분한다. 컬럼/타입 변경이나 새로운 migration을 적용할 때 운영 인덱스도 재검토한다.

효과가 없거나 정의가 다름·생성 후800MB 초과·API 응답 회귀가 확인되면 소유 계정으로 `DROP INDEX public.ops_free_risk_cover;`를 실행하고 기준50개 상태를 확인한다. 다른 데이터·인덱스를 임의로 줄여 맞추지 않는다.

## 4. DB 복원·만료 대응

검증 PC의 백업은 `%USERPROFILE%\SpotON-private-backups\render-free-20261113\`에 보관한다. source.dump, baseline.json, 검토된 toc.reviewed.list와 검증 증빙이 있으며 자격증명은 Windows 사용자 DPAPI로 암호화돼 있다. 다른 PC에서는 운영자로부터 접근 가능한 백업 사본을 확보한다. 이 보관을 서로 다른 물리 디스크의 재해 백업으로 간주하지 않는다.

현재 검증 덤프는97,881,270 bytes이며 SHA256은 `dad8925acc3479cf4755aaba3fa00034f8037a98f47c0c038ba755e05b117b56`이다. 이 값은 해당 검증 스냅샷의 기준이지 미래 데이터의 최신성을 뜻하지 않는다.

1. 만료 전에 검증을 종료하거나 새 Free PostgreSQL17 DB를 같은 workspace·리전에 만든다. 빈 대상·Free plan·DB/소유자·실제 확장 버전·저장공간을 확인한다. 유료 자원을 자동 생성하거나 증설하지 않는다.
2. 덤프 SHA와 `pg_restore --list`를 확인하고 대상에 맞는 PostGIS를 설치한다. 검토한 TOC에서 public 스키마 중복 생성과 확장 내부 객체를 제외한다. 소유자·확장·ACL을 무조건 덮어쓰지 않는다.
3. 소유 계정의 별도 연결에서 아래 방식으로 앱 스키마/데이터를 복원한다. PGHOST/PGPORT/PGUSER/PGPASSWORD/PGSSLMODE/PGSSLROOTCERT를 대상 Free DB와 외부 verify-full 연결에 맞게 설정하고 기존 로컬 연결을 상속하지 않는다. 암호는 명령행에 넣지 않는다. 유지보수 시간 제한은 대량 복원에 맞추고 API 제한과 구분한다.

   ```text
   pg_restore --single-transaction --exit-on-error --no-owner --no-privileges --use-list=toc.reviewed.list --dbname=spoton_free_check source.dump
   ```

4. 소유 계정으로 VACUUM/ANALYZE 후20테이블 전체 행·좌표 지문, 기준50인덱스·110제약·3시퀀스·모델·head0011을 대조한다. Free에서 서버 해시 정렬은 임시 공간을 넘길 수 있다. 검증한 방법은 PostgreSQL 행별/EWKB별 MD5를 named cursor10,000행씩 받아 로컬에서 ASCII(C) 순서 정렬·연결 MD5를 계산해 원래 baseline과 비교하는 것이다. baseline이나 비교 규칙을 결과에 맞춰 바꾸지 않는다.
5. 별도 조회 역할을 설정한다. 아래는 소유자 psql 세션용 예시다. 비밀번호는 `\password`의 숨김 입력으로 설정하고 안전하게 보관한다. 기존 역할이 있으면 덮어쓰지 말고 먼저 정의·멤버십을 확인한다.

   ```sql
   CREATE ROLE spoton_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
     NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8;
   \password spoton_api
   REVOKE CREATE, TEMPORARY ON DATABASE spoton_free_check FROM PUBLIC;
   REVOKE CREATE ON SCHEMA public FROM PUBLIC;
   GRANT CONNECT ON DATABASE spoton_free_check TO spoton_api;
   GRANT USAGE ON SCHEMA public TO spoton_api;
   SELECT format('GRANT SELECT ON TABLE public.%I TO spoton_api', tablename)
   FROM pg_tables WHERE schemaname = 'public'
   \gexec
   ALTER ROLE spoton_api SET default_transaction_read_only = on;
   ALTER ROLE spoton_api IN DATABASE spoton_free_check SET statement_timeout = '10s';
   ALTER ROLE spoton_api IN DATABASE spoton_free_check SET jit = off;
   ```

   복원한 앱 테이블과 spatial_ref_sys의 SELECT를 확인한다. READONLY/NOINHERIT만을 권한 경계로 삼지 않고, 소유자 역할의 멤버가 아니며 READ WRITE 상태에서도 INSERT/CREATE/TEMP/SET ROLE이 거절되는지 검증한다. 향후 테이블에 SELECT를 자동 부여하는 default privileges는 설정하지 않았다.

6. 인덱스 생성 전에 행 수·avg_width로 최종/임시 크기를 추정하고 여유를 확인한다. 현재 기준은 최종 DB800MB 이내, temp/WAL 포함 추정900MB 이내다. [운영 SQL](sql/render-free-risk-cover.sql)은 소유자 연결에서 일반 CREATE INDEX, lock_timeout5초·maintenance_work_mem16MB·statement_timeout1200초로 실행한다. 전체 해시 검사와 동시에 실행하지 않는다. 추가 후 크기·정의·실행 계획·API를 다시 검증한다.
7. Render의 DATABASE_URL만 새 내부 reader 연결로 갱신하고 다른 환경변수를 지우지 않는다. 검증한 develop commit을 명시해 수동 배포한다. migration이 필요하면 소유자의 별도 세션에서 수행하며 reader나 앱 시작 시 실행하지 않는다. head가 바뀌면 DATABASE_EXPECTED_REVISION도 맞춘다.
8. /api/ready, 대표 API 전체 JSON, 경계·동시 요청, 주소 검색/CORS/AI503을 검증한다. 대체 DB의 복원·권한·연결을 확인하기 전에 유일한 유효 사본을 삭제하지 않는다. 새 ID·만료일·검증 결과를 이 문서에 갱신한다.

새 DB 자동 생성이나 예약은 구현하지 않았다. 복원·데이터 대조는 Free의 CPU/디스크 제한 때문에 오래 걸릴 수 있다. 로컬 개발DB는 기존 Docker를 계속 사용하며 로컬 .env를 Render용으로 바꾸지 않는다.

## 5. 검증된 범위

| 검사 (2026-11-14) | 결과 |
|---|---|
| 20테이블 전체 행/geometry 지문 | 원본과 일치 |
| API24건 | 정상22건200·오류2건422, 로컬과 전체 JSON 일치 |
| 반경 경계3건 | 499.999/500m 포함, 500.001m 제외 |
| 카페 Risk 동시3·총6요청 | 모두200·동일 결과, 최장6.985초 |
| 주소 검색 / CORS | 200 / localhost5173 허용200·미허용 origin400 |
| 내부 DB 연결 | reader·TLSv1.3, 풀1 확인 |
| AI | LLM 키 생략,503 AI_UNAVAILABLE |

기존 코드 검증은 일반1595건·PostGIS251건을 통과했다. 이전·Claude 설계 검토 원문은 [PR #110](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/110)과 Git 이력에 남아 있다. 현재 기준에는 과거 유료 설정을 적용하지 않는다.

## 6. 무료 제한과 FE 연결

Free BE는15분 무요청 후 절전하며 workspace 전체의 무료 웹750시간을 공유한다. Free DB는1GB 고정·생성30일 후 만료이고 관리형 자동 백업은 없다. [Render 무료 정책](https://render.com/docs/free)

절전 후 첫 health는22.593초, 준비 후24건 중 health 제외 최장은8.656초였다. 단일 관측이며 SLA가 아니다. SQL10초·풀 대기15초는 HTTP 전체 시간의 상한이 아니고, 동시 요청이 많으면 지연/오류가 발생할 수 있다. FE의 현재15초 제한에 대해 무료 검증에서는 첫 요청60초 정도 대기 또는 재시도 안내가 필요하다. [FE 연결 설정](fe-render-validation-api-request.md)

카드 없는 무료 계정은 포함량 초과 시 서비스/새 빌드가 중단될 수 있다. 과거 발생 요금은 무료 전환으로 취소되지 않으며, 미납0이나 영구 무료를 보장하지 않는다. [과금 안내](https://render.com/docs/faq)
