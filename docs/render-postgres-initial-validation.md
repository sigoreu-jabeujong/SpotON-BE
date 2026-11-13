# Render 검증용 PostgreSQL 생성·PostGIS 초기 확인

- 확인일: 2026-11-13 (Asia/Seoul)
- 범위: 사용자 승인에 따른 검증용 DB 생성, PostGIS 설치, 연결·권한·기본 공간 기능 확인
- 결과: **검증용 DB 생성 및 초기 확인 완료. 이후 덤프 복원·대표 API 대조도 완료했으며 [후속 검증 결과](render-postgres-restore-validation.md)를 따른다. 전체 운영 호환성·배포 완료를 뜻하지 않음**

## 1. 생성한 리소스

| 항목 | 실제 설정 |
|---|---|
| 이름 | `spoton-db-check` |
| Render ID | `dpg-dbrgd70u01pc73b653sg-a` |
| 상태 | `available` |
| 리전 | `singapore` |
| DB 이름 | `spoton_check` |
| 최초 소유 계정 | `spoton_owner` |
| PostgreSQL 선택 버전 | 17 |
| 유료 Compute Plan | `2c-4g` — 2 CPU, RAM 4GB |
| 저장공간 | 10GB |
| 연결 풀 서비스 | `none` |
| 외부 연결 | 생성·확인 당시 검증 PC의 IPv4 `/32` 한 개만 허용 |

[Render DB 관리 화면](https://dashboard.render.com/d/dpg-dbrgd70u01pc73b653sg-a)

해당 워크스페이스에 기존 서비스·DB가 없음을 확인하고 싱가포르를 선택했다. 향후 BE도 같은 워크스페이스·리전에 배포해 내부 연결을 사용한다. 외부 검증 PC의 IP가 달라지면 허용 목록을 갱신해야 한다.

최초 생성 요청은 결제정보 미등록으로 402였으며, 사용자 결제수단 등록 후 다시 목록을 조회해 중복 DB가 없는 상태에서 생성했다. 실제 리소스는 유료 검증용 DB 한 개다.

## 2. 실제 버전과 설치 상태

| 항목 | 로컬 개발 DB | Render 검증용 DB |
|---|---|---|
| PostgreSQL | `17.11` | `17.11` |
| PostGIS | `3.7.0` | **`3.6.2`** |
| PostGIS 설치 스키마 | `public` | `public` |
| PostGIS Topology | 로컬 설치 `3.7.0` | 제공 버전 `3.6.2`, 이번 확인에서 설치하지 않음 |

Render에서 `pg_available_extensions`를 조회했을 때 PostGIS는 미설치였고 제공 기본 버전은 3.6.2였다. 새 검증용 DB의 이름·계정·상태와 애플리케이션 테이블이 없는 것을 확인한 뒤 다음 명령으로 설치했다.

```sql
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;
```

설치 후 `pg_extension`과 `postgis_full_version()`으로 버전·스키마를 확인했다. Render의 실제 라이브러리는 GEOS `3.11.1`, 실행 시 보고된 PROJ `9.9.0`이다. 로컬과 대상의 PostGIS 버전이 다르므로 초기 함수 성공을 덤프 호환성 증거로 확대하지 않는다.

## 3. 통과한 확인

| 검사 | 결과와 범위 |
|---|---|
| 외부 PostgreSQL 접속 | TLS 사용 확인 |
| 관리 역할 | superuser=false, createdb=true, createrole=true |
| PostGIS 설치 | 현재 `spoton_owner` 계정으로 성공 |
| geography 거리 함수 | `ST_DWithin` 기본 호출 성공 |
| 좌표 변환 | EPSG:4326 → EPSG:5179 변환 및 SRID 확인 성공 |
| 도형 보정 | `ST_MakeValid`의 `method=linework` 기본 호출 성공 |
| 공간 인덱스 | 임시 geometry 컬럼 및 geography 캐스트의 GiST 인덱스 생성·유효성 확인 성공 |

인덱스 검사는 임시 테이블에서 수행하고 트랜잭션을 rollback했다. 인허가·생활인구 등 애플리케이션 스키마·데이터는 복원하지 않았다. 원격 API 조회 전용 역할은 아직 생성하지 않았으며, 소유 계정을 API 서비스 계정으로 사용하지 않는다.

연결정보는 Render에서 가져와 검사 프로세스 안에서만 사용했다. 이 문서에는 비밀번호·접속 URL·인증 토큰·외부 IP 원문을 기록하지 않는다. 이번 작업에서 기존 개발용 `.env`, 애플리케이션 코드, 로컬 개발 DB는 변경하지 않았다.

## 4. 다음 단계: 버전 차이를 포함한 복원 시험

1. 이전 대상 덤프의 생성일·SHA256·migration·테이블별 건수와 인덱스 기준을 고정한다. 과거 덤프와 현재 개발 DB의 서로 다른 시점 결과를 같은 기준으로 비교하지 않는다.
2. 덤프 TOC에서 PostGIS·Topology 확장 및 내부 객체와 애플리케이션 객체를 구별한다. 대상 3.6.2에 맞는 복원 절차·소유권·ACL 처리를 정한다. Topology가 실제 앱에 필요한지 확인하고 제외·설치 근거를 남긴다.
3. 사용자 승인 범위에 따라 이 검증용 DB에 복원하고, 실패 원문에서 비밀정보를 제외해 원인을 기록한다. 단순히 복원 오류를 무시하고 다음 단계로 진행하지 않는다.
4. 복원 후 ANALYZE, migration 0011 여부, 테이블별 건수·데이터/geometry hash·제약·시퀀스·필수 인덱스와 조회 계획을 대조한다.
5. API 조회 전용 역할과 권한을 구성하고 해당 역할로 대표 API·반경 경계·동시 요청·SQL 3초 제한을 검증한다. 초기 소유 계정의 함수 성공으로 API 계정의 권한을 대신 확인하지 않는다.
6. PostGIS 3.7.0 → 3.6.2 차이에서 복원 또는 결과 차이가 발생하면 원인과 허용 가능성을 판단한다. 호환성이 확인되기 전에는 운영 연결을 전환하지 않는다.

이 문서 1~3절은 초기 생성·확인 당시의 기록이다. 이후 사용자 지시에 따라 새 덤프 복원, 20개 테이블 대조, 조회 전용 계정, 대표 API·소규모 동시 요청 검사를 수행했다. 실제 결과와 남은 운영 전환·배포·원격 ETL 범위는 [덤프 복원·호환성 검증 결과](render-postgres-restore-validation.md)를 따른다.
