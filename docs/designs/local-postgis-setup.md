# 로컬 개발 DB 연동: Docker PostgreSQL·PostGIS

## 범위와 상태

- 사용자 요청(2026-11-11): Docker로 실제 로컬 개발 DB 구성.
- 기존 BE-06 연결·세션과 migration `0001`·`0002`를 재사용한다.
- 관련 이슈: [#31 Docker 기반 로컬 PostgreSQL·PostGIS 개발 환경 구성](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/31).
- 작업 브랜치: `feat#31-docker-postgis-dev`.
- 초기 로컬 구성은 `chore/local-postgis-setup`에서 준비했고, 사용자 요청으로 지정된 작업 브랜치에서 커밋·푸시·develop 대상 PR을 진행한다. 병합은 사용자가 수행한다.
- Docker 컨테이너 실행·실제 백엔드 연결·migration 검증 완료. 원천 적재와 후속 API 구현은 별도 작업이다.

## 구성

- CI와 같은 digest의 PostgreSQL 17·PostGIS 이미지를 사용한다.
- Compose 프로젝트 이름은 `spoton-dev`, DB는 `spoton_dev`다.
- 포트는 `127.0.0.1`에만 공개하고 기본값은 5432다.
- named volume에 데이터를 유지한다. 일반 재시작·중단은 데이터를 삭제하지 않는다.
- `spoton_admin`은 컨테이너 초기화에만 사용한다. 백엔드는 별도 `spoton_app` 계정으로 연결한다.
- 앱 계정은 로그인·DB 접속·public 스키마 사용/객체 생성 권한만 받는다. superuser·DB/role 생성 권한을 주지 않는다.
- 초기화 스크립트는 빈 볼륨에서만 실행된다. 기존 볼륨에서 `.env`의 암호를 바꿔도 DB 암호는 자동 변경되지 않는다.
- 임의 비밀번호는 로컬 `.env`에만 저장하고 출력·커밋하지 않는다.

## 검증 순서

1. Docker Desktop Linux engine과 Compose 실행 확인.
2. `docker compose config --quiet`로 비밀값을 출력하지 않고 구성 검증.
3. `docker compose up -d --wait db`로 실행·health 대기.
4. 앱 계정으로 `SELECT 1`, `PostGIS_Version()`과 공간 함수 확인.
5. 대상이 `spoton_dev`인지 확인하고 `alembic upgrade head` 실행.
6. revision `0002`, stores 테이블·공간 인덱스·앱 계정 권한 확인.

## 포함하지 않는 작업

원천 전체 적재, 점포 조회·분석 API 구현, 실제 개발 DB를 대상으로 하는 파괴적 통합 테스트는 이 작업에 포함하지 않는다.

## 설치 직후 기록: 재부팅 전 (2026-11-11)

- Docker Desktop 4.99.0과 WSL 3.0.5 설치 완료.
- WSL 2용 Windows `VirtualMachinePlatform` 활성화 완료. Windows가 `RestartNeeded = true`를 반환했다.
- 임의 관리자/앱 암호와 앱 접속 URL을 로컬 `.env`에 생성했다. `git check-ignore .env`로 제외 상태를 확인했다.
- `docker compose config --quiet`, `git diff --check` 통과.
- Docker 엔진은 아직 stopped 상태다. 컨테이너 생성·DB 접속·migration은 실행하지 못했으며 실제 개발 DB 연동은 미완료다.
- PC 재부팅 후 Docker Desktop을 실행하고 Linux engine 준비 상태를 확인한 뒤 검증 순서 3번부터 재개한다. Python 3.11·uv 실행 환경도 확인해야 한다.
- 자동 재부팅·원천 적재·후속 API 구현·커밋·푸시는 수행하지 않았다.

### 재부팅 후 연결 검증 완료 (2026-11-11)

- Docker Linux engine 29.9.3 실행 확인. `docker compose up -d --wait db` 성공, `spoton-dev-db-1` healthy.
- 앱 계정의 TCP 인증, `SELECT 1`, PostGIS 3.7과 geography 거리 계산 확인. `rolsuper`·`rolcreatedb`·`rolcreaterole`은 모두 false.
- uv 0.13.7 설치. Python 3.11.18과 `uv.lock` 의존성을 설치했다.
- 한글 경로의 editable `.pth`를 Python 3.11이 cp949로 읽어 시작에 실패했다. UTF-8 실행 옵션으로도 해결되지 않아 해당 파일은 `.pth.disabled`로 보존하고 `uv sync --locked --extra dev --no-editable`로 일반 설치했다. 새 실행에서도 `UV_NO_EDITABLE=1` 또는 `--no-editable`을 유지해야 한다.
- 백엔드 `create_db_engine()`과 실제 `.env`로 `127.0.0.1:5432/spoton_dev`에 `spoton_app` 접속 성공. 접속 비밀값은 출력하지 않았다.
- `.venv/Scripts/python.exe -m alembic upgrade head`, `alembic current` 성공. revision `0002 (head)`.
- stores 테이블·공간 GIST 포함 인덱스 5개와 SQLAlchemy ORM 조회 확인. 원천 적재 전 `stores`는 0건이다.
- 일반 `alembic check`는 PostGIS 확장 내부 테이블을 모델 차이로 보고해 실패했다. 앱 모델 소유 테이블만 포함한 `compare_metadata` 검사는 차이 없이 통과했다. 확장 테이블 삭제나 migration 변경은 하지 않았다.
- `ruff check`, `ruff format --check`, `mypy app etl migrations` 통과. `pytest`: 473 passed, integration 12 deselected. 기존 Starlette testclient deprecation 경고 1건.
- 실제 개발 DB를 대상으로 파괴적인 integration suite는 실행하지 않았다. 브랜치 push CI는 로컬 실행 검증과 별도로 확인한다.
- CI와 동일한 `mypy app migrations`도 통과했다(37 files).
- Claude Code 별도 설계 검토는 이번 로컬 환경 구성에서 수행하지 않았다.
