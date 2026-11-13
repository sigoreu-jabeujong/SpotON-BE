# Render BE 검증 배포 결과

> 이 문서는 최초 유료 검증 당시 기록이다. 2026-11-14 무료 전환·전체 데이터/API 검증 후 기존 유료 BE와 DB를 삭제했다. 현재 API는 https://spoton-be-free.onrender.com 이며 [최신 무료 전환 결과](render-free-validation.md)를 따른다.

- 확인일: 2026-11-13 (Asia/Seoul)
- 결과: **공개 HTTPS 배포, 내부 조회 전용 DB 연결, API 대조 통과**
- API 문서: https://spoton-be-check.onrender.com/docs
- 준비 상태: https://spoton-be-check.onrender.com/api/ready
- 구현: [이슈 #106](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/106), [PR #107](https://github.com/sigoreu-jabeujong/SpotON-BE/pull/107)
- 설계·실제 Claude 검토·최종 결정: [#106 설계](designs/feat106-render-validation-deploy.md)

## 1. 배포 구성

| 항목 | 실제 설정 |
|---|---|
| 서비스 | `spoton-be-check`, `srv-dbrh4tutlv9c738h2ku0` |
| 리전 | DB와 같은 계정·싱가포르 |
| 실행 | Docker / 0.5 CPU·512MB / 인스턴스1 |
| 소스 | GitHub develop, 자동 배포 off |
| 배포 commit | `56e174e79fdd14a1fe4cbb67a8be4d9de68ed7fc` |
| 배포 ID | `dep-dbrh4uetlv9c738h2mhg` |
| 배포 성공 시각 | 2026-11-13 22:37:47 KST |
| 진입점 | app.runtime / PORT10000 / 비root UID10001 |
| 종료 대기 | Uvicorn30초 / Render45초 |
| DB | 기존 검증용 `spoton-db-check`, PostgreSQL17.11·PostGIS3.6.2 |
| DB 연결 | 내부 주소 / 조회 전용 spoton_api / sslmode=require |
| 관측 TLS | 실제 내부 API 풀 연결2개 모두 TLSv1.3 |
| 배포 시 자동 적재 | migration·ETL 없음 |

Render는 CI 이미지 자체를 재사용하지 않고 이 commit에서 Docker 이미지를 다시 빌드했다. Python·uv base digest와 uv.lock을 고정했다. 이후 문서만 추가된 develop commit은 자동 배포하지 않으므로 실제 배포 버전은 위 SHA로 확인한다.

## 2. 연결 예산과 준비 검사

WEB_CONCURRENCY=1, DATABASE_POOL_SIZE=3, DATABASE_MAX_OVERFLOW=0, DATABASE_POOL_TIMEOUT=2, DATABASE_CONNECTION_BUDGET=8이다. 정상 API 풀3개와 별도 준비 연결1개, 교체 중 구/신 인스턴스를 포함한 상한은 `2*(3+0+1)=8`이다. 인스턴스 추가·별도 reader 도구는 이 계산에 자동 반영되지 않는다.

`/api/health`는 기존 프로세스 검사다. Render는 `/api/ready`로 DB·migration0011·조회 역할 권한을 검사한다. 준비 검사는 단일 실행 잠금, 성공10초/실패1초 캐시, connect_timeout1초·SQL750ms·HTTP2.5초를 적용한다. HTTP 취소 후 남은 스레드도 자기 연결을 닫을 때까지 잠금을 유지한다. 실패는 기존 INTERNAL_ERROR500·공통 외피·no-store다.

처음에는 소유 계정의 pg_stat_ssl에서 다른 역할의 정보가 제한돼 관측하지 못했다. 권한을 추가하지 않고 배포가 live인 뒤 조회 역할로 외부 감사 연결1개를 열었다. 이 역할의 내부 API 연결2개에서 ssl=true·TLSv1.3을 확인했고 당시 감사 포함 reader 세션은3개였다. 감사 연결은 종료했다. 배포 중 외부 reader 연결은 사용하지 않았다.

sslmode=require는 TLS 암호화를 요구하지만 서버 인증서 검증을 보장하지 않는다. 외부 감사 연결은 verify-full과 CA를 사용했다. DB 외부 허용 목록은 기존 검증 PC /32 한 개를 유지했다.

## 3. 검증 결과

| 검사 | 실제 결과 |
|---|---|
| ruff check·format / mypy | 통과 |
| 일반 pytest | 1,595건 통과 |
| CI PostGIS 통합 | 251건 통과, skip 없음 |
| GitHub CI·CodeQL | PR #107 전체 통과 후 일반 Squash 병합 |
| Docker 실실행 | 0.5CPU/512MB, UID10001, health/ready/Risk200 |
| Docker 메모리 | 단일 관측82.97MiB, 최대 부하 보장 아님 |
| 이미지 분리 | runtime .env/.git/pytest 없음, 애플리케이션 비밀 ENV 없음 |
| 공개 API24건 | 로컬 DB API와 전체 JSON 일치: 정상200 22건·오류422 2건 |
| 반경 경계3건 | 499.999m·500m 포함, 500.001m 제외; 로컬과 일치 |
| 동시 요청 | 동시3으로6건 실행, 모두200·동일 결과 |
| 주소 검색 | 실제 Kakao 기반 서울시청 주소 요청200 |
| CORS | localhost5173 preflight200, 미허용 origin400 |
| AI 키 미설정 | 실제 요청503 AI_UNAVAILABLE, 공급자 호출 없음 |
| 내부 연결 | 조회 역할·내부 대상·sslmode=require 설정 및 TLSv1.3 관측 |

공개24건은 health, 카페/음식점/중식 월 범위, 두 업종의300/500/1000m 주변, 과거 월·면적·가맹·세부 업종 필터, snapshot, activity, Risk, 기준월 오류·중복 include 오류, 상세 위치 이력을 포함한다. 공개 조회의 최장 단일 관측은0.562초다. 네트워크 포함 응답 시간이며 운영 SLA·최대 부하·장애 복구 시험을 의미하지 않는다. 기존 SQL별3초 제한은 유지했다.

일반/통합 테스트에는 기존 Starlette/httpx deprecation 경고1건이 있다. 로컬 통합에서는 신규 ready 경로 때문에 기존 OpenAPI 기대 목록1건이 실패했고 목록 수정 후 해당 검사와 CI 전체251건을 통과했다.

## 4. 비밀 설정과 남은 범위

DB 비밀번호는 기존 Windows DPAPI에서 메모리로 읽어 Render 환경변수로 전달했다. 주소 조회용 Kakao REST·Juso 키만 전달하고 LLM·정부 ETL·DB 소유 계정 키는 전달하지 않았다. `.env`·비밀번호·DB 접속 URL·인증 토큰·외부 IP 원문은 변경·커밋·문서화하지 않았다.

현재는 유료 검증용 서비스이며 유지 중에도 비용이 발생한다. 정식 운영 전환, FE 배포/공개 origin 연결, 실제 LLM 활성화와 사용량 제한, 원격 월별 ETL, 최대 부하·장애 복구·모니터링 보관 정책은 후속 작업이다. 기존 pending 지표를 임의 수치로 채우지 않았다. FE 안내는 [연결 요청서](fe-render-validation-api-request.md)를 따른다.

새 배포는 CI가 통과한 commit을 명시해 수동으로 실행한다. readiness나 대표 API가 실패하면 Render의 이전 성공 배포로 되돌리고 원인을 확인한다. 초기 성공 배포만 있는 상태에서 이전 버전이 없으면 검증 서비스를 중지하고 기존 로컬 개발 환경을 유지한다. DB 원자료·권한을 임의로 되돌리거나 로컬 `.env`를 운영 DB로 바꾸지 않는다.

선행 DB 데이터 대조·인덱스·제약·조회 역할 검증은 [복원 보고서](render-postgres-restore-validation.md)를 따른다. 복원 및 이번 검증의 원문 증빙은 저장소 밖 비공개 백업/검증 디렉터리에 보관한다.
