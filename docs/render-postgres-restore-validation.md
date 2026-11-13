# Render PostgreSQL 덤프 복원·호환성 검증 결과

- 확인일: 2026-11-13 (Asia/Seoul)
- 대상: `spoton-db-check` / `spoton_check`, 싱가포르, 유료 2 CPU·4GB·10GB
- Render ID: `dpg-dbrgd70u01pc73b653sg-a`
- 결과: **복원·데이터 대조·조회 전용 계정·대표 API 검증 통과**
- 범위: 검증용 DB 이전 시험. 운영 연결 전환·BE 배포·원격 ETL 활성화는 수행하지 않음

## 1. 이전한 데이터와 버전

기존 Downloads의 2026-11-12 덤프 이후 로컬에 #104 층·호수 정보 보정이 반영돼 있었다. 이 보정까지 포함하도록 현재 로컬 `spoton_dev`의 새로운 일관 스냅샷에서 덤프를 생성했다. 과거 덤프와 현재 데이터를 섞어 대조하지 않았다.

| 항목 | 실제 결과 |
|---|---|
| PostgreSQL | 원본·대상 모두 17.11 |
| PostGIS | 로컬 3.7.0 → Render 3.6.2 |
| 덤프 형식 | PostgreSQL 17 `pg_dump` custom archive |
| Migration | `0011` |
| 테이블 | 앱 19개 + `alembic_version` 1개 = 20개 |
| 덤프 크기 | 97,881,270 bytes |
| 덤프 SHA256 | `dad8925acc3479cf4755aaba3fa00034f8037a98f47c0c038ba755e05b117b56` |
| 복원 시간 | 62.27초 — 이번 단일 실행 관측값 |
| 복원 후 앱 모델 차이 | 0개 — 확장 내부 객체 제외 |

| 주요 테이블 | 원본·대상 공통 행 수 |
|---|---:|
| stores | 689,440 |
| store_import_batches | 4 |
| market_areas | 1,650 |
| market_stores | 24,810 |
| market_sales | 14,391 |
| market_changes | 6,600 |
| living_grids | 10,125 |
| living_population_observations | 531,922 |
| brands | 11,167 |
| store_brand_matches | 6,839 |

## 2. 복원 전에 확인한 사항

- Render API의 리소스 ID·이름·리전·DB·소유 계정을 검사하고, 대상에 앱 테이블이 없는 상태임을 확인했다. 이 인스턴스에는 별도 앱 DB가 없고 시스템 DB와 `spoton_check`만 있었다.
- 원본에서 `REPEATABLE READ READ ONLY` 스냅샷을 내보내고 같은 스냅샷으로 `pg_dump`를 실행했다. 덤프 전후 스키마·시퀀스 상태를 확인했다.
- 앱의 비공개 스키마 관계 객체, 처리하지 못하는 large object, topology 타입 앱 컬럼이 없음을 확인했다.
- 원본 `spatial_ref_sys` 전체 지문이 같은 PostGIS 3.7.0의 기본 `template_postgis`와 일치했다. 사용 중인 4326·5179·5181 정의도 Render와 일치했다.
- 앱 제약·인덱스·기본값에서 직접 참조하는 PostGIS 함수 시그니처 3개가 대상에 존재했다.
- 원본·대상은 UTF8이며 libc locale provider를 사용한다. 로케일 이름 표기는 `en_US.utf8` / `en_US.UTF8`로 달라 별도 기록했다. 지문 정렬은 명시적인 `COLLATE "C"`를 사용했다.

## 3. 실제 복원 방식

덤프는 `public`의 앱 객체와 데이터를 포함하고 확장 관리 참조 테이블 `spatial_ref_sys`는 제외했다. TOC 118개 항목을 검사해 대상에 이미 있는 public 스키마 생성·스키마 주석 2개만 제외하고 116개 항목을 복원했다. 앱 테이블 정의·TABLE DATA·SEQUENCE SET 항목의 누락이 없음을 확인했다.

Render가 제공하는 PostGIS 3.6.2 확장을 유지했다. 로컬의 3.7 확장 객체·바이너리·Topology를 가져와 덮어쓰지 않았다. 앱이 Topology에 의존하지 않는 것을 확인했고 Topology는 설치하지 않았다.

복원은 `--single-transaction --exit-on-error --no-owner --no-privileges`로 실행했다. `--clean`, DB 재생성, DROP/TRUNCATE를 사용하지 않았다. 앱 객체 소유자는 `spoton_owner`로 생성됐다.

암호는 명령 인자·로그·`.env`에 쓰지 않고 이름만 지정한 Docker 환경변수로 전달했다. 외부 연결은 `sslmode=verify-full` 및 CA 파일을 사용해 TLS와 서버 인증서를 검증했다. 복원 세션의 문장 제한을 별도로 관리하고 복원 성공 후 앱 20개 테이블에서 `VACUUM (ANALYZE)`를 수행했다.

참고: [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html), [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html). 일반 문서의 복원 절차를 PostGIS 하위 버전 호환 보장으로 해석하지 않고 아래 실제 대조 결과로 판정했다.

## 4. 무결성 대조 결과

| 검사 | 결과 |
|---|---|
| 20개 테이블 전체 행 수 | 일치 |
| 일반 컬럼 전체 행 지문 | 일치 |
| geometry 컬럼의 NULL 수·EWKB 지문 | 일치 |
| 컬럼·타입·NULL·identity·기본값 | 일치 |
| 인덱스 정의·valid/ready | 50개 일치·유효 |
| 제약 이름·종류·유효성·식 | 110개 보존, 아래 재파싱 차이 검증 |
| 시퀀스 정의·last_value·is_called | 3개 일치 |
| migration / 앱 모델 | `0011` / 차이 0개 |
| 로컬 원본 사후 전체 지문·스키마·시퀀스 | 보존 |
| 로컬 앱 테이블 DML 통계 | 검사 전후 변경 없음 |

공간 컬럼은 버전별 JSON 표현의 영향을 피하도록 일반 행 JSON에서 제외하고 `ST_AsEWKB`로 별도 확인했다. 일반 데이터는 동일한 세션 날짜·시간대·숫자·bytea 설정 아래 행별 MD5를 정렬·집계했다. 덤프 파일 자체는 SHA256으로 확인했다. 정렬 순서와 NULL 처리를 동일하게 적용했다.

CHECK 제약 15개는 덤프 SQL을 다시 파싱하면서 AND 괄호와 배열 형변환의 출력 표현이 달라졌다. 단순 문자열 정리로 같다고 처리하지 않았다. **각 원본 CHECK 식을 Render 임시 테이블에서 다시 파싱한 결과가 실제 복원된 제약 식·유효성과 동일한지 확인**했다. 임시 객체는 rollback했고 나머지 제약은 직접 일치했다. 원본 제약을 변경하거나 제거하지 않았다.

최초 덤프 검사의 스키마 출력 명령에서 `--file=-` 인자가 누락된 오류가 있었다. 대상 복원 전에 명령을 수정하고 새 덤프·기준을 다시 생성했다. 실제 Render `pg_restore` 실행은 종료 코드 0으로 한 번 성공했다. 제약 출력 형식 차이도 별도 검증 후 판정했으며 실패를 무시하지 않았다.

## 5. 조회 전용 계정

`spoton_owner`와 분리한 `spoton_api` 로그인을 생성했다.

- superuser / CREATEDB / CREATEROLE / INHERIT / REPLICATION / BYPASSRLS: 모두 false.
- 연결 제한 8개, 기본 트랜잭션 읽기 전용, 해당 DB의 SQL 문장 제한 3초.
- DB CONNECT, public 스키마 USAGE, 앱 20개 테이블 및 PostGIS 참조 테이블 SELECT만 부여.
- 대상 DB의 PUBLIC CREATE/TEMP와 public 스키마의 PUBLIC CREATE를 제한. 다른 DB의 ACL은 변경하지 않음.
- 모든 앱 테이블 SELECT 성공. 읽기·쓰기 트랜잭션으로 명시 전환해 검사해도 INSERT·영구 테이블 생성·임시 테이블 생성·`SET ROLE spoton_owner`가 각각 42501로 거절됨.
- 미래 테이블에 대한 광범위한 default privileges는 부여하지 않음. 새 migration 도입 시 필요한 읽기 권한을 검토해야 함.

계정 암호는 클라이언트에서 SCRAM-SHA-256 verifier를 만든 뒤 verifier로 등록했다. 실제 로그인 정보는 현재 Windows 사용자에 묶인 DPAPI로 암호화해 `%USERPROFILE%/.render/spoton-db-check-api.dpapi`에 보관했다. 평문 접속정보를 저장소나 문서에 남기지 않았다. 이 암호화 파일은 다른 PC/사용자의 배포용 비밀 저장소를 대신하지 않는다.

## 6. 실제 앱·API 비교

현재 FastAPI 코드를 변경하지 않고 설정 복사본·독립된 앱 인스턴스로 로컬 DB와 Render의 `spoton_api`를 각각 연결했다. `.env` 파일을 변경하지 않았다. 검사 설정은 파일 로딩 없이 명시적으로 구성하고 애플리케이션의 LLM·주소 API 키를 비활성화했다. 외부 주소 검색·앱 LLM 해석은 이 검사 대상이 아니다.

| 검사 | 결과 |
|---|---|
| health·data-range·nearby·snapshot·activity·risk·history 및 입력 오류 | **24건 전체 상태·응답 내용 일치** |
| 성공 / 정상 입력 오류 응답 | 22건 200 / 2건 422, 각 원본과 동일 |
| 카페·음식점, 300/500/1000m, 과거 월·세부 업종·면적·프랜차이즈 필터 | 비교 통과 |
| 같은 조건의 nearby/snapshot/Risk/활동 점포 수 | 카페 150·음식점 590, 네 API 및 두 DB 모두 일치 |
| 실제 점포 기준 499.999 / 500 / 500.001m 경계 | 포함 / 포함 / 제외, 전체 응답도 양쪽 일치 |
| Render 동시 요청 3개, 총 6개 Risk 요청 | 6개 모두 200·응답 일치 |
| 공간 조회 실행 계획 | `ix_stores_geography_gist` 사용, 단일 실행 26.876ms |

API 비교는 실제 Render DB에 접속한 로컬 TestClient 검사다. Render에 BE를 배포한 상태의 인터넷 HTTP·FE 브라우저 시험은 아니다. 캐시는 껐고 각 앱의 연결 풀은 3개·overflow 0으로 제한했다. 이 풀 설정은 검사 인스턴스에만 적용했으며 현재 제품 코드의 풀 설정을 변경하지 않았다.

원격 DB를 쓰는 정상 API 응답은 이번 관측에서 약 0.594~3.281초였다(무DB health 제외). 3초는 **각 SQL 문장의 제한**이며 전체 HTTP 응답 제한이 아니다. 동시 요청 관측은 약 1.000~2.703초였다. 한국 PC→싱가포르 DB 왕복과 쿼리 수의 영향을 포함하며 운영 SLA·장시간 부하 결과로 일반화하지 않는다. 기존 Starlette TestClient/httpx 경고는 유지했다.

## 7. 검토·증거 보관

Claude Code에 복원 계획을 전달해 실제 검토를 받았고 결과는 `is_error=false`, 조건부 GO였다. 공간/일반 데이터 지문 분리, SCRAM verifier, 복원 후 VACUUM, 권한 검사, TLS·덤프 보관 보완을 반영했다. 검토자는 전달한 계획을 근거로 판단했으며 실제 DB·코드·공식 문서를 직접 검증한 것으로 주장하지 않았다. 실제 적용 여부와 결과는 위 실행으로 확인했다.

처음 최소 모드로 실행했을 때 인증을 읽지 못한 실패가 있었고, 정상 인증을 사용하는 모드로 다시 실행해 실제 검토를 받았다. 해당 실패를 검토 완료로 취급하지 않았다. 검토 원문과 실행 스크립트·SQL·대조 JSON·비공개 로그·새 덤프는 다음 비공개 로컬 경로에 보관했다.

```text
%USERPROFILE%/SpotON-private-backups/render-check-20261113-dad8925a/
```

보관 디렉터리는 현재 사용자·SYSTEM·Administrators만 접근하도록 Windows ACL을 제한했다. 파일별 복사 지문과 덤프 SHA256을 대조한 후 컨테이너와 일반 임시 디렉터리의 중복 덤프를 제거했다. 원본 다운로드 덤프는 그대로 보존했다. 원자료·덤프·비밀정보를 Git에 추가하지 않았다. 이 로컬 보관은 별도 원격 백업·재해 복구 정책을 대신하지 않는다.

## 8. 후속 작업과 적용 한계

**이 덤프와 현재 검사 범위에서는 PostGIS 3.7.0 → 3.6.2 이전이 통과했다.** 모든 PostGIS 함수·미래 데이터·원격 ETL 재처리의 일반 호환성을 보장하는 결과는 아니다. 특히 GEOS/PROJ 차이를 포함한 원격 재처리는 별도 검증이 필요하다.

다음은 BE의 운영 연결·풀 크기·워커 수를 명시한 검증 배포다. 이번에 만든 조회 계정의 연결 제한과 실제 워커별 `(pool_size + max_overflow)`를 함께 맞추고, 같은 리전의 내부 URL·내부 TLS 정책·비밀정보 설정을 적용해야 한다. 현재 제품 코드의 기본 풀 값을 그대로 운영 확정한 것은 아니다.

그 후 배포된 BE→관리형 DB→FE의 실제 흐름·대표 부하를 확인하고 운영 전환을 판단한다. 원격 ETL 보호장치 변경·쓰기 계정·월별 적재·관리형 백업 복구 훈련은 별도 후속 작업이다. 이번 단계에서 FE 코드·운영 URL·개발용 `.env`·애플리케이션 코드·migration은 변경하지 않았다.
