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
| DB 크기 | #128 운영 인덱스 생성 후761,124,531 bytes, 약761MB |
| Migration | 0011 |
| 배포 commit | 05790fa7d71f6010b0174960863e4c9ceba77e25 (#118·#124·#128 및 #130 AI 문단) |
| 자동 배포 | off, 검증한 commit을 수동 배포 |

현재 BE 배포는 `dep-dbs5t55g1s2s73e8vorg`(2026-11-14 22:14:36 KST live)다. FE [PR55](https://github.com/sigoreu-jabeujong/SpotON-FE/pull/55)는 `4bf012fe231e0f3108aaf43521d6acc9b97a41d6`으로 develop에 병합돼 [공개 화면](https://spot-on-fe.vercel.app)에 반영됐다. Vercel 배포는 `GWN6ZJMbFMQVDdJ8Ns7mKxYhUF7F`다. 아래 #134는 실제 공개 브라우저 검증 결과이며, 과거 절의 배포 ID와 검증 수치는 당시 이력으로 구분한다.

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
CORS_ORIGINS=http://localhost:5173,http://localhost:5180,https://spot-on-fe.vercel.app
LLM_PROVIDER=google
LLM_MODEL=gemini-3.5-flash-lite
```

`DATABASE_URL`은 **새 DB의 내부 호스트·spoton_api 조회 역할·sslmode=require**로 구성해 Render 비밀 환경변수로 주입한다. 내부 TLS는 암호화를 요구하며 서버 인증서 검증을 보장하지 않는다. 외부 관리자 검증/복원은 verify-full과 CA를 사용하고, 외부 DB 접근은 검증 PC /32만 허용한다. 비밀번호·실제 DB URI·인증 토큰·외부 IP는 문서나 저장소에 넣지 않는다.

주소 조회용 `KAKAO_REST_API_KEY`, `JUSO_SEARCH_KEY`, `JUSO_COORD_KEY`와 AI용 `LLM_API_KEY`를 Render 비밀 환경변수로 별도 설정한다. #127에서 기존 로컬 Gemini 키의 실제 생성 성공을 확인한 뒤 Render에 연결했다. 키 값은 FE·이미지·로그·저장소에 넣지 않는다. DB 소유 계정·정부 ETL 키는 BE에 전달하지 않는다. AI는 프로세스별 기본5회/분·50회/일·동시2개·전체20초 예산을 사용하며 공급자 quota는 별도다. 한도·공급자·시간 초과의503 AI_UNAVAILABLE과 선택 검증 실패의503 AI_VERIFY_FAILED 처리를 유지한다.

브라우저 CORS는 로컬5173·5180과 배포 FE `https://spot-on-fe.vercel.app`의 세 origin을 명시적으로 허용한다. Vercel preview·다른 포트·추가 도메인은 자동 허용되지 않으며 정확한 origin을 별도로 추가해야 한다. 이 목록은 Render 서비스 환경변수이며 로컬 `.env`나 코드 기본값을 바꾸지 않는다.

`/api/health`는 프로세스 검사다. Render health check는 `/api/ready`로 지정한다. 준비 검사는 head0011·조회 역할 권한을 확인하며 API 풀과 별도 연결1개, HTTP2.5초·SQL750ms·성공10초/실패1초 캐시를 사용한다. #124부터 동시 요청은 단일 검사의 실제 결과를 제한시간 안에서 공유한다. 미완료나 만료된 성공을 정상으로 반환하지 않으며 실패는 기존 INTERNAL_ERROR500/no-store다. 로그는ready 고정 경로와readiness_probe 고정사유/시간을 구분한다. probe ok가 해당HTTP200을 보장하지는 않는다.

인스턴스1·워커1에서 교체 상한은 `2 * workers * (pool + overflow + 1 readiness) = 4`로 예산/reader 제한8 안이다. 외부 reader 도구·추가 인스턴스는 따로 합산한다. Free는 맞춤 maxShutdownDelaySeconds 설정을 지원하지 않아 플랫폼 기본 종료 대기를 사용한다.

## 3. 운영 인덱스와 스키마

앱19개 테이블과 alembic_version을 합쳐20테이블이다. 기준50인덱스·110제약·3시퀀스·head0011을 유지하며, Free DB에만 [ops_free_risk_cover](sql/render-free-risk-cover.sql)와 [ops_free_risk_name_v1](sql/render-free-risk-name-v1.sql) 운영 인덱스2개를 두어 총52개다. 원본 행·계산식·앱 모델/migration은 유지한다. #128 이름 정책은 분석 SQL predicate와 메타/캐시를 바꾼다.

기존 cover는 서울 전체 Risk 집계를 커버한다. 크기45,883,392 bytes이며 도입 당시 단일 집계가12.589→2.777초로 줄었다. 새 이름 인덱스는 같은 key/include에 고정 이름 predicate를 추가한39,993,344 bytes다. 코드 배포 전에 생성했고 기존 모든689,440행 composite/EWKB hash·기존 인덱스·API 본문이 같았다. 새 코드의 실제 Free 쿼리에서 direct1.798초/generic2.683초·Index Only Scan·Heap Fetches0·name heap Filter 없음과 한식454→434의 정확한 marker 대조를 확인했다. 이 관측은 시간 보장이나 전체 HTTP 상한이 아니다.

이 Free DB를 `alembic revision --autogenerate` 대상으로 쓰면 운영 인덱스 삭제가 제안될 수 있으므로 사용하지 않는다. 모델 비교에서 예외를 둘 때는 이름뿐 아니라 정확한 key/include·predicate·valid/ready/live를 확인하고 이2개만 구분한다. 컬럼/타입 변경이나 새로운 migration을 적용할 때 운영 인덱스도 재검토한다.

새 이름 인덱스의 효과가 없거나 정의 불일치·생성 후800MB 초과·API 회귀가 확인되면 먼저 검증된 이전 코드를 배포하고 필요할 때 `DROP INDEX public.ops_free_risk_name_v1;`만 실행해 기존51개 상태를 확인한다. 기존 cover/provenance를 롤백용으로 유지하며 다른 행·인덱스를 줄여 맞추지 않는다. 키워드/패턴 수정은 정책 버전과 새 운영 인덱스를 함께 검토한다.

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

6. 인덱스 생성 전에 행 수·avg_width로 최종/임시 크기를 추정하고 여유를 확인한다. 현재 기준은 최종 DB800MB 이내, temp/WAL 포함 추정900MB 이내다. 원래 [cover SQL](sql/render-free-risk-cover.sql)과 #128의 [이름 정책 부분 인덱스 SQL](sql/render-free-risk-name-v1.sql)은 소유자 연결에서 일반 CREATE INDEX, lock_timeout5초·maintenance_work_mem16MB·statement_timeout1200초로 실행한다. 앱 모델50개와 별개인 운영 인덱스2개이며 autogenerate 대상이 아니다. 전체 해시 검사와 동시에 실행하지 않는다. 추가 후 크기·UTF-8 리터럴/정의·유효성·generic 계획·API를 검증하고 이름 정책 코드보다 새 부분 인덱스를 먼저 준비한다. 롤백은 이전 코드 배포 후 필요하면 새 이름 인덱스만 제거하며 기존 cover/provenance는 유지한다.
7. Render의 DATABASE_URL만 새 내부 reader 연결로 갱신하고 다른 환경변수를 지우지 않는다. 검증한 develop commit을 명시해 수동 배포한다. migration이 필요하면 소유자의 별도 세션에서 수행하며 reader나 앱 시작 시 실행하지 않는다. head가 바뀌면 DATABASE_EXPECTED_REVISION도 맞춘다.
8. /api/ready, 대표 API 전체 JSON, 경계·동시 요청, 주소 검색/CORS와 실제 AI 해석200·검증 통과·오류 처리를 검증한다. 대체 DB의 복원·권한·연결을 확인하기 전에 유일한 유효 사본을 삭제하지 않는다. 새 ID·만료일·검증 결과를 이 문서에 갱신한다.

새 DB 자동 생성이나 예약은 구현하지 않았다. 복원·데이터 대조는 Free의 CPU/디스크 제한 때문에 오래 걸릴 수 있다. 로컬 개발DB는 기존 Docker를 계속 사용하며 로컬 .env를 Render용으로 바꾸지 않는다.

## 5. 검증된 범위

| 검사 (2026-11-14) | 결과 |
|---|---|
| 20테이블 전체 행/geometry 지문 | 원본과 일치 |
| API24건 | 정상22건200·오류2건422, 로컬과 전체 JSON 일치 |
| 반경 경계3건 | 499.999/500m 포함, 500.001m 제외 |
| 카페 Risk 동시3·총6요청 | 모두200·동일 결과, 최장6.985초 |
| 주소 검색 | 200 |
| CORS 추가 검증 | 세 origin의 GET/POST preflight6건·실제 GET3건200, 미허용 origin3개 preflight400·GET 허용 헤더 없음 |
| 내부 DB 연결 | reader·TLSv1.3, 풀1 확인 |
| AI (#127) | 카페·한식·카페 재호출3건200, 실모델gemini-3.5-flash-lite·검증 통과·불일치0·재생성false |

기존 코드 검증은 일반1595건·PostGIS251건을 통과했다. 이전·Claude 설계 검토 원문은 [PR #110](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/110)과 Git 이력에 남아 있다. 현재 기준에는 과거 유료 설정을 적용하지 않는다.

2026-11-14 FE 요청의 CORS 두 주소를 추가하고 같은 commit으로 재배포했다. 배포 `dep-dbrisp4ipgvc73fojbt0`의 live·기존 commit 유지·ready200을 확인했다. CORS 이외 환경변수와 키 목록은 변경 전후 일치하며 Free 요금제·자동 배포 off를 유지한다. preflight는 Content-Type·GET/POST·Vary: Origin을 확인했고 credentials 허용은 추가하지 않았다. 이번에는 앱 코드·DB·로컬 `.env`·FE 저장소를 변경하지 않았으며 FE 브라우저 전체 통합 완료를 의미하지 않는다.

### LLM 연결과 실제 AI 해석 검증 (#127, 2026-11-14)

Render에 LLM_API_KEY·LLM_PROVIDER·LLM_MODEL이 모두 없어 실제 POST가503 AI_UNAVAILABLE로 실패했다. 로컬 키/모델 조회200·실제 JSON 생성1회 성공 후 세 설정을 추가하고 같은 검증 commit7d4846c를 수동 재배포했다. 배포 `dep-dbs51tk9v7es73bn89tg`는21:16:24 KST에live가 됐다. 기존14개 환경값·DB/schema/인덱스·Free·자동 배포off·로컬.env·FE 파일은 보존했다. 변경 전 환경은 사용자 전용 증빙 폴더에 DPAPI 암호화로 보관했다.

실제 `/api/risk/interpret`에 시청 인근 카페500m와 홍대 인근 한식500m를 query-only로 전송해 각각3.047/7.625초에200을 확인했다. 두 응답 모두 verification.passed=true·검사53개·불일치0·재생성false·공식/참고 문장6개이며 interpretation_method=server_sentences_model_ordering이다. 카페 재호출도2.437초에200·검증 통과였다. no-store·배포 FE의 정확한CORS 헤더·세 허용origin POST preflight200·잘못된 업종422 INVALID_PARAM·ready200을 확인했다. 응답 시간은 이번 관측값이며 보장이 아니다. FE 브라우저의 버튼/표시·실제 공급자 장애나 quota 소진 시 화면은 별도 확인 대상이다. 키 값·공급자 원문은 증빙/문서에 기록하지 않았다.

## 6. 무료 제한과 FE 연결

### AI 문단 개편 공개 반영 (#134, 2026-11-14)

사용자 승인에 따라 검증된 BE05790fa를 먼저 Render에 수동 배포하고 실제 API 성공을 확인한 후 FE PR55를 병합했다. 기존17개 환경값의 전체 지문이 일치하고 LLM 키·모델·CORS·풀1/SQL10초·워커1·Free·자동 배포off를 유지했다. DB/schema/인덱스·로컬.env·Vercel 환경변수를 바꾸지 않았다. API는 기존 배열을 호환용으로 유지하며 body/paragraphs/used_indicator_ids/evidence를 추가한다.

공개 BE의 카페500m·2025-11 및 최신 한식500m query-only 요청은 각각3.703/10.063초에200·본문4문단·verification.passed=true·검사47개·불일치0·재생성false·prompt_version=risk-interpret-v8을 반환했다. 정확한 FE origin의CORS와no-store·ready200을 확인했다. 관측 응답 시간은 보장이 아니다.

이후 Vercel의 해당 commit 배포 성공과 공개 JS 자산 변경을 확인하고 실제 공개 페이지에서 DB+Gemini 해석을 다시 생성했다. 본문4문단·기존 번호형 구역/근거 칩 없음·실제 조건 표시·ⓘ의클릭/외부 클릭/Esc/포커스 복귀,1440px 및390/360px에서가로 넘침 없음, 조건 변경 후 이전 해석 제거·자동POST 없음, 브라우저에서만 주입한503에도지표 보존을 확인했다. 공개 AI도200·검사47개·불일치0·재생성false였다. 실제 공급자 장애나quota를 강제로 소진한 검사는 아니다.

공개 분석 화면의 Kakao SDK/실제 지도 타일, 이력·주변·시점·활동·Risk·월 범위는200이며 브라우저 실행 오류는0건이었다. Vercel의 기존 공개 지도 키와 허용 도메인을 그대로 사용했다. 이 검증은 지정한 주소·조건과화면 범위이며 전체 사용자 부하·절전 복귀·모든 조건의 시간 보장은 아니다. 증빙은 사용자 전용 `SpotON-private-backups/ai-narrative-20261114/release`에 보관하며 키·환경값 원문은 기록하지 않았다.

Free BE는15분 무요청 후 절전하며 workspace 전체의 무료 웹750시간을 공유한다. Free DB는1GB 고정·생성30일 후 만료이고 관리형 자동 백업은 없다. [Render 무료 정책](https://render.com/docs/free)

최초 복원 검증에서 절전 후 첫 health는22.593초, 준비 후24건 중 health 제외 최장은8.656초였다. 단일 관측이며 SLA가 아니다. SQL10초·풀 대기15초는 HTTP 전체 시간의 상한이 아니고, 동시 요청이 많으면 지연/오류가 발생할 수 있다. 최신 FE develop dcf8af1은 일반45초·초기60초와 대기/재시도 안내를 적용했다. [FE 연결 설정](fe-render-validation-api-request.md)

### FE 동시 조회 후속 검증 (#122, 2026-11-14)

현재 풀은 **1개를 유지**한다. 풀1은 Free의 강제 제한이 아니다. 기존 d449c5f에서 풀만2로 늘렸을 때30건은200이었으나 최초 묶음 중앙값16.515→18.500초로 악화돼 풀1로 복구했다. 되돌린 설정·기존 commit·ready/CORS/AI503을 확인한 후, 별도 단계에서 이미 검증·병합된 #118의8958ba7만 배포했다. 다른 환경변수·키·Free·자동 배포off·SQL10초·DB/schema/인덱스는 유지했다.

이때 live 배포는 `dep-dbs37aek1f9s73858g6g`(19:11:42 KST)였다. 이력·월 범위·주변·활동·Risk GET5개 동시 묶음을 한식·2026-10·300/500/1000m 각각 최초/반복으로 비교했다. 최종30건 모두200·성공 본문 전체 JSON 동일, 최초 중앙값16.515→9.688초·반복15.219→6.110초였다. 풀1 복구 직후 별도 기준과도 동등성/개선을 확인했다. 실제 Free DB에서 고아 검사 기존1.72~2.83초→후보0.097~0.166ms와 필수 인덱스의 유효 정의·순서 스캔을 확인했다.

최종 health/ready200·허용 세 origin의 preflight6/실제GET3·미허용origin3차단·AI503을 확인했다. 이30건의 성공은 모든500·절전 복귀·여러 사용자 부하 해결을 뜻하지 않는다. 별도 운영 로그의 unmatched500 두 건은 경로/원인 미확정 후속으로 남긴다. 이 검증에서 DB 내용·인덱스·로컬 .env·FE 파일은 바꾸지 않았고 AI도 활성화하지 않았다. [설계·실제 Claude 검토2회·전후 검증](designs/feat122-fe-feedback.md)

### 운영 ready 후속 수정 배포 (#124, 2026-11-14)

당시 live는 `dep-dbs3norl550s73fbvskg` / `7d4846c61291897993a1146e16945c06ca1255b1`(19:46:35 KST)였다. 이후 #127에서 LLM 설정을 추가했고 현재는 그 설정을 유지한 #128 배포를 사용한다. PR125의CI/CodeQL 성공·develop병합·검증한실행코드동등성을확인한뒤수동배포했다. Free·자동배포off·모든환경값/키목록해시·풀1/대기15초·SQL10초·워커1·예산8을보존했다. DB/schema/인덱스·로컬.env·FE는변경하지않았다.

진행중인정상DB검사에합류한ready가즉시500을반환하던결함을재현/수정했다. 현재는실행별결과를같이기다리며닫힘/취소/시간초과/예외시에도추가검사나오래된성공으로우회하지않는다. 실패는500/no-store이며원시예외/URI를공개하지않는다. 과거두unmatched500의원인이같았다는증명은아니다.

배포후동시ready24건·업무GET30건모두200·기존8958ba7업무본문SHA256완전일치, health200·CORS preflight6/실제GET3·미허용origin3차단·AI503을확인했다. 검증구간서버ready이벤트28건(플랫폼요청포함)·실제probe4회모두ok·수집된HTTP500이벤트0이었다. 업무묶음중앙값은최초8.428/반복5.520초였으며추가ready요청이있는이번관측값이다. 시간보장·물리절전·대량부하·모든오류해결로확대하지않는다. [설계·실제Claude검토2회·검증/한계](designs/feat124-readiness-followup.md)

카드 없는 무료 계정은 포함량 초과 시 서비스/새 빌드가 중단될 수 있다. 과거 발생 요금은 무료 전환으로 취소되지 않으며, 미납0이나 영구 무료를 보장하지 않는다. [과금 안내](https://render.com/docs/faq)


### 이름 키워드 제외 배포 검증 (#128, 2026-11-14)

사용자가 B안을 선택해 원본 인허가 분류는 유지하고 음식점4종의 이름18개 키워드를 분석에서 제외한다. 정책은 `store-name-keywords-v1`이며 cafe 업종·null/빈 이름은 유지한다. ASCII 영문 대소문자를 무시하는 부분 일치이고 실제 업종 확정이 아니다. 실제 음식점 오탐, 내부 공백/분해 한글/전각/키워드 없는 이름의 미탐을 수용한다. 점포/집계 성공 메타에 정책·버전을 표시하고 Risk/AI 캐시와 AI 문맥 버전을 함께 구분한다. AI 공개 메타는 기존 data_version_hash 계약을 유지한다.

[PR131](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/131)의 일반1,718개·PostGIS270개·CodeQL 성공 후 develop c4de3ed802c220d80fdd03040e53004e3620e515를 수동 배포했다. `dep-dbs5fus9v7es73boe6dg`는21:46:27 KST에live가 됐다. 검증한 코드와 병합 실행 트리가 같았고, #127의 LLM 설정을 포함한17개 환경값 전체 hash·Free/autoDeploy off·원본689,440행 전체 composite/EWKB hash·기존 인덱스/head0011을 보존했다. 새 부분 인덱스는 코드보다 먼저 생성·검증했으며 앱 모델50개와 운영2개를 구분한다.

- 같은 명동 최신 한식500m nearby454→434: 독립 키워드 오라클의 전체 남은 marker와 일치하며 기존13후보도 모두 제외됐다. 제보18개 전체 명단 검증이나 실제 업종 확정이 아니다.
- 이력·월 범위·주변·활동·Risk의 실제10개 GET200과 배포 전 후보의 전체 JSON 일치, 카페 data 동등(교차 업종 이력 제외), 원천 D/배치 목록 불변을 확인했다.
- 2026-10 snapshot455→435: 전체 목록과 still_open/closed_since/other 합계가 동일 이름 필터와 일치했다.
- 한식2026-10·300/500/1000m·최초/반복의 동시5 GET×6묶음30건 모두200·반복 본문 동일·nearby 수=활동 open_count 합=Risk competitor_count였다. 묶음 중앙값 최초10.380/반복7.410초다. 추가 이름 조건과 서버/캐시 상태가 포함된 관측이며 이전 검증과 동일 부하 통제 비교나 시간 보장이 아니다.
- 동시ready24건·health200, 세 origin preflight6/실제GET3·미허용origin3차단을 확인했다. LLM 키를 보존한 실제 한식+건물 이력 POST는9.783초에200, 숫자57개 검증 통과·불일치0·재생성false였다.
- 검증 구간 수집된 API 로그111건에서 HTTP500 이상0건이었다. 절전/여러 사용자/공급자 장애·quota 소진·전체 오류 해결로 확대하지 않는다. FE 파일·로컬.env·데이터 DML은 변경하지 않았다.

상세 정책·실제 Claude Code 검토2회·원천/분석 자격 분리·롤백과 잔여 한계는 [#128 설계](designs/feat128-name-keyword-exclusion.md)를 따른다.
