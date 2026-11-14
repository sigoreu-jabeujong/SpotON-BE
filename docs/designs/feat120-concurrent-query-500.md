# 간헐 동시 조회 500 원인 분석 및 수정 (#120)

- 이슈: [#120](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/120) `간헐 동시 조회 500 원인 분석 및 수정`
- 브랜치: `feat#120-concurrent-query-500` (develop `8958ba7`, #118 병합 후, head 0011)
- 선행: #78 재점검의 "실제 FE 동시 조회에서 약 3초 후 500" 관측, #82·#118 출처 조회 개선
- 목적: 최신 develop에서 FE와 같은 동시 조회를 재현해 500의 원인을 분류하고, 확인된 원인만 최소 수정한다.

## 1. 기존 관측과 질문

#78에서는 이력·주변·활동·Risk 동시 조회가 약 3초 후 500이 됐고, 한 실행에서 PostgreSQL 로그로 출처 연결 배치 조회 statement_timeout 4건을 확인했다. 이후 #82(인덱스)·#118(고아 검사 skip scan)로 그 SQL은 실제 개발 DB에서 수 ms 이하가 됐다. 남은 질문은 (Q1) 최신 코드에서도 동시 500이 나는가, (Q2) 난다면 SQL 시간 초과인가 다른 원인인가, (Q3) 배포 Render에서도 같은가이다.

## 2. 재현 방법

- 요청 묶음: FE 결과 화면이 동시에 부르는 5개 GET(이력·월 범위·주변·활동·Risk). FE `src/hooks/use*.ts`·`src/api/*.ts` 기준. 좌표·건물키는 공개 랜드마크 주소(마포구 양화로 160)를 BE `/api/geocode`로 한 번 변환해 입력으로만 썼고 출력·기록하지 않았다.
- "화면 N개" = 묶음 N개를 동시에 보냄(5N개 동시 요청).
- 콜드: 로컬 개발 DB 컨테이너 재시작 + Docker VM OS 캐시 비우기 직후 첫 묶음. 웜: 직후 회차.
- 분류: (1) 같은 시간대 PostgreSQL 로그의 `canceling statement due to statement timeout` 건수(문장 원문 미출력), (2) 커밋하지 않는 진단 실행기에서 `read_only_session`의 500 직전 예외 클래스와 SQLSTATE만 stderr에 기록. 실제 개발 DB는 읽기 전용 API만 호출했다.

## 3. 측정 결과 (단발 측정, SLA 아님)

### 3.1 로컬(코드 기본: 풀 3·overflow 0·풀 대기 2초·SQL 3초, `.env`에 풀 설정 없음)

| 조건 | 결과 | PG statement timeout |
|---|---|---|
| 콜드·화면1(5동시)·6회차 | 모두 200, 첫 회차 최대 2,317ms | 0 |
| 콜드·화면2(10동시) | 첫 시행 Risk 1건 500(2,077ms), 이후 3시행 모두 200(최대 1.7~2.2초) | 0 |
| 콜드·화면3(15동시)·5시행 | 3시행에서 500 총 7건(2,106~2,137ms, 이력·월 범위·활동·Risk 모두 해당) | 0 |
| 웜·화면3(15동시)·3회차 | 모두 200(최대 274~488ms) | 0 |

진단 실행기 기록 7건 모두 `TimeoutError sqlstate=None`(SQLAlchemy `sqlalchemy.exc.TimeoutError`, QueuePool 연결 대기 초과)이다. 실패 시간이 풀 대기 2초 직후에 몰리고 SQL 시간 초과는 0건이다.

### 3.2 설정 비교(같은 DB·같은 콜드 절차·각 3시행)

| 설정 | 묶음 | 500 | 최대 응답 |
|---|---|---|---|
| 풀3·대기2초·SQL3초(현재 로컬) | 화면3 | 3시행 중 2시행, 6건(모두 풀 대기 초과) | 2.0~2.3초 |
| 풀3·대기10초·SQL3초 | 화면3 | 0 | 2.0~2.2초 |
| 풀1·대기15초·SQL10초(Render 값) | 화면1 | 0 | 2.1~2.3초 |
| 풀2·대기15초·SQL10초 | 화면1 | 0 | 1.7~2.0초 |
| 풀3·대기15초·SQL10초 | 화면1 | 0 | 1.9~2.2초 |

로컬 DB는 빨라서 풀 1에서도 화면 1개가 약 2초 안에 끝난다. 따라서 Render 쪽 풀 크기 효과는 이 로컬 비교로 증명되지 않는다.

### 3.3 배포 Render(`spoton-be-free`, 현재 배포 commit, Free·풀1/대기15초/SQL10초)

절전 해제(health 22.9초) 후 화면1(5동시)×3회차: 회차별 최대 19,939 / 9,880 / 16,168ms, 3회차에 주변 점포 1건 500(15,538ms). 15초 풀 대기 직후 실패라 같은 풀 대기 초과로 추정한다(Render 로그·예외 클래스는 직접 보지 못했다). 풀 1에서는 5개 요청이 한 연결을 차례로 쓰므로, 느린 Free DB에서 화면 하나의 마지막 요청이 15초를 넘는다. FE GET 기본 제한도 15초(`SpotON-FE/src/api/client.ts` `TIMEOUT_MS`)라 BE가 500을 내지 않아도 FE가 먼저 끊을 수 있다.

### 3.4 결론

- **Q1**: 최신 develop에서도 콜드 동시 조회 500이 재현된다.
- **Q2**: 이번 재현의 500은 모두 **DB 연결 풀 대기 초과**였다. SQL statement_timeout은 0건이다. #78 당시 한 실행에서 본 SQL 시간 초과는 #82·#118 이후 이번 측정에서 재현되지 않았다(해소를 증명한 것은 아니며 대량 재적재 직후 경계는 #82/#118 기록대로 남는다). 남은 간헐 500은 풀 대기 한도 2초가 콜드 요청의 연결 점유 시간보다 짧아 줄 선 정상 요청을 떨어뜨리는 설정 문제다. 한 요청은 세션 준비 2문장(`SET TRANSACTION READ ONLY`·`set_config`) 외에 SQL 여러 문장(#96 기록상 활동 6문장 등)을 문장마다 최대 3초까지 쓸 수 있으므로 대기 2초는 구조적으로 부족하다.
- 분류 근거의 한계: 진단 실행기는 예외 클래스·SQLSTATE만 기록했다. `sqlalchemy.exc.TimeoutError`는 QueuePool 대기 초과에서만 발생하고 접속 실패(connect_timeout)는 `OperationalError`, SQL 시간 초과는 SQLSTATE 57014를 가진 `OperationalError`라 구분은 타당하다. 다만 모든 측정은 단발·소수 시행이며 Render 쪽 원인은 로그 없이 시간 분포로만 추정했다.
- **Q3**: Render에서도 화면 하나로 500과 15초 초과가 관측됐다. 원인은 풀 1개 직렬 처리와 느린 Free DB의 조합으로 추정한다. Render는 대기를 늘려도 FE 15초 제한에 걸리므로 병렬 연결 수가 핵심이다.

## 4. 변경 설계

### 4.1 포함 (코드·저장소)

1. `app/core/config.py`의 `database_pool_timeout` 기본값을 **2초 → 10초**로 바꾼다. 상한 30초·하한 0.1초 검증은 유지한다.
   - 근거: §3.2에서 대기 10초는 같은 조건의 500을 없앴고 최대 응답을 늘리지 않았다(줄 선 요청이 실제로는 2초 남짓 안에 연결을 받았다는 뜻). 10초는 FE GET 제한 15초보다 짧아, **풀 대기 초과로 실패하는 경우에는** BE 500이 FE 중단보다 먼저 도착한다. 연결을 9초대에 받은 요청은 이후 SQL 시간이 더해지므로 BE가 항상 15초 안에 응답한다는 보장은 아니다(상한 = 풀 대기 + 세션 준비·본문 문장 수 × 문장 제한 3초). Render 값 15초(SQL 10초)와 같은 방향의 비율이다.
   - 값 선택: 측정에서 실패는 2.08~2.14초에 몰렸고 10초에서 0건이었다. 5초 등 더 짧은 값은 측정하지 않았으므로 측정된 10초를 채택하고, 대기를 FE 15초 쪽으로 더 늘리지 않는다(아래 FE 재시도·스레드 점유 때문에 상한을 두는 쪽이 낫다).
   - 오류 은폐·시간 연장 여부: SQL 제한·오류 응답·실패 경로는 그대로이고 "다른 요청이 연결을 반납하기를 기다리는 시간"만 실제 점유 시간에 맞춘다. 진짜 과부하·DB 장애는 여전히 최대 10초 뒤 500으로 드러난다.
   - FE 상호작용: FE `queryClient.ts`의 `shouldRetry`는 status ≥ 500과 TIMEOUT(status=null)을 1회 재시도한다. 따라서 풀 대기 500 한 건은 곧바로 같은 요청 1건을 더 만든다. 대기 증가로 500이 줄면 이 재시도 부하도 줄어든다. 반대로 FE가 15초에 중단해도 BE의 동기 처리 스레드는 끝까지 실행되므로(FE 중단은 BE 작업을 취소하지 않음) 중단+재시도는 중복 부하가 된다. 이것이 대기를 15초 이상으로 늘리지 않는 이유다.
   - 스레드 점유: 조회 라우터·세션 의존성은 동기 `def`라 AnyIO 기본 스레드 한도(40)를 공유하며, 풀을 기다리는 동안 스레드 1개를 점유한다. 대기 10초에서는 40개를 넘는 동시 버스트 시 AnyIO 대기열에서 보내는 시간이 생기고 이 시간은 `pool_timeout`에 포함되지 않는다. 이번 측정(최대 15동시)은 한도 아래였고 단일 사용자 검증 규모에서는 문제되지 않으나 부하 상한을 검증한 것은 아니다. `/api/ready`는 `asyncio.to_thread`(이벤트 루프 기본 executor)와 API 풀 밖 별도 연결을 써서 이 대기의 영향을 받지 않는다. AI 해석의 준비 단계도 `asyncio.to_thread`로 같은 `read_only_session`을 쓰므로 풀 대기가 LLM_TIME_BUDGET(기본 20초) 안에서 최대 10초까지 소비할 수 있다(예산 초과 시 기존 503 경로).
   - 바뀌지 않는 것: SQL 문장별 3초 제한, 풀 크기 3·overflow 0, 연결 예산 검증(2×워커×(풀+overflow+1) ≤ 예산, `pool_timeout`과 무관), 오류 코드·응답(풀 대기 초과는 여전히 500 INTERNAL_ERROR/no-store, `read_only_session`이 `SQLAlchemyError`로 매핑). 진짜 과부하는 10초 뒤 실패로 끝나며 무한 대기하지 않는다. API 응답 schema·오류 코드 목록 변경이 없어 FE 계약 변경·FE 요청서는 필요 없다.
2. `.env.example`의 `DATABASE_POOL_TIMEOUT=2` → `10`과 설명 주석(풀 연결 대기 초, SQL 문장 제한과 별개, FE GET 15초보다 짧게).
3. 문서: 저장소에서 "대기2초"를 서술한 곳은 `docs/render-free-validation.md` 27행("코드 기본 SQL3초·풀3/대기2초") 하나뿐이다(README·`fe-render-validation-api-request.md`·작업계획·CLAUDE.md에는 2초 서술 없음). 이 행은 코드 기본값과 같은 커밋(§8 커밋 2)에서 "대기10초"로 고친다. Render 권장 사항(§4.3)은 "권장·미적용"으로 명시해 커밋 3에서 추가하고, 작업계획(새 절)·BE CLAUDE.md(#120 요약)도 커밋 3에서 갱신한다. Render 실제 값(풀1/대기15초)을 서술한 작업계획·CLAUDE.md·FE 연결 안내의 문구는 사용자가 Render 값을 실제로 바꾸기 전에는 수정하지 않는다.
4. 테스트(§6).

### 4.2 제외

- SQL statement_timeout 확대, 오류 은폐(500을 200/빈 값으로 바꾸기), 재시도 루프, 결과 캐시 추가는 하지 않는다.
- 풀 대기 초과를 503 등 별도 상태·오류 코드로 바꾸는 것은 API 계약(오류 코드 목록) 변경이라 FE 합의가 필요하다. 이번에는 하지 않고 후속 후보로만 기록한다.
- 기본 풀 크기 증가: 기본 연결 예산 8에서 워커1·overflow0이면 풀 3이 상한(2×1×(3+0+1)=8)이라 코드 기본 풀 크기는 바꾸지 않는다.
- Render 환경변수·배포, FE 코드·타임아웃·재시도, 실제 DB 데이터는 변경하지 않는다. 사용자 로컬 `.env`도 수정하지 않는다(현재 풀 키가 없어 새 기본값이 적용된다).

### 4.3 Render 권장(문서화만, 적용은 사용자 결정)

- `DATABASE_POOL_SIZE` 1 → **2**를 권장한다. 교체 상한 2×1×(2+0+1)=6으로 예산/reader 8 안이며 외부 검증 도구용 여유 2를 남긴다. 3은 상한이 8로 예산과 같아 여유가 없다.
- `DATABASE_POOL_TIMEOUT`은 FE 15초보다 짧게(예: 12초 이하) 두는 것을 함께 검토한다.
- 근거는 §3.3의 실제 관측(풀1 직렬로 화면 하나 최대 약 20초·15.5초 500)뿐이며, 풀 2에서 Free DB가 실제로 빨라지는지는 측정하지 않았다(Free DB의 CPU·I/O 한계, Free 웹 인스턴스 CPU도 함께 제한). 두 연결이 같은 DB 자원을 나눠 쓰면 문장별 시간이 늘어 이득이 절반에 못 미칠 수 있고, 반대로 SQL 10초 제한에 걸리는 문장이 생길 수 있다. 적용 후 같은 화면1 묶음으로 응답 시간·500·PG statement timeout 건수를 재측정해야 한다. 배포는 자동 배포 off라 수동 재배포가 필요하다.
- 적용 전 확인: (a) 연결 예산 검증은 6 ≤ 8로 통과한다. (b) staging 준비 검사는 조회 역할의 `rolconnlimit ≥ DATABASE_CONNECTION_BUDGET(8)`을 요구하므로 예산을 바꾸지 않으면 영향이 없다. (c) Free DB 서버 전체 `max_connections`와 관리자·외부 검증 연결 수는 이 문서에서 확인하지 않았으므로 적용 시 함께 확인한다. (d) FE는 TIMEOUT·500을 1회 재시도하므로, 대기를 15초 이상으로 두면 FE 중단 뒤에도 BE가 계속 처리하는 동안 재시도가 겹친다. 대기를 12초 이하로 두는 것은 이 겹침을 줄이기 위한 것이며 15초 안 응답을 보장하지는 않는다.
- 이 권장안은 **미적용**이며 현재 Render 값(풀1/대기15초/SQL10초)은 그대로다. 문서에 쓸 때도 현재 구성 표와 권장안을 분리하고, 적용 여부·재측정 결과는 사용자 확인 후 별도 기록한다.

## 5. 보안·개인정보·외부 API·DB

로그·문서에 주소·좌표·건물키·SQL 원문·DB 접속 정보를 남기지 않는다(상태 코드·시간·예외 클래스·건수만). 진단 실행기와 측정 스크립트는 저장소에 커밋하지 않는다. 실제 개발 DB는 재시작·캐시 비우기 외에 데이터 변경이 없고 API는 읽기 전용이다. Render 호출은 읽기 GET 묶음 3회(15건)와 health·geocode 각 1회뿐이다.

## 6. 테스트 계획

일반(단위):
- `Settings(_env_file=None)`의 `database_pool_timeout` 기본값이 10이고, 기본 SQL 제한(3초)보다 크며, 기본 연결 예산 검증을 통과하는지 확인한다.
- 테스트 시 `DATABASE_POOL_TIMEOUT` 등 환경변수가 남아 있으면 기본값 단언이 깨지므로 기존 `test_llm_limit_defaults`처럼 `monkeypatch.delenv(..., raising=False)`로 지운 뒤 `Settings(_env_file=None)`을 만든다. 위치는 `tests/test_config.py`(또는 예산 검증이 있는 `tests/test_render_runtime.py`).
- `.env.example`의 `DATABASE_POOL_TIMEOUT` 값이 코드 기본값과 같은지 확인한다(문서-코드 불일치 방지). 파일 위치는 기존 `test_env_example_lists_llm_limit_settings`와 같이 `Path(__file__).resolve().parents[1] / ".env.example"`로 찾고, 주석이 아닌 `DATABASE_POOL_TIMEOUT=` 행이 정확히 1개인지 확인한 뒤 `float(값) == Settings.model_fields["database_pool_timeout"].default`로 비교한다(환경변수 영향 없음).

격리 PostGIS(`tests/integration/test_render_deployment.py` 확장):
- 풀 1개·대기 2초 엔진에서, 주 스레드가 첫 연결을 잡은 상태로 `ThreadPoolExecutor(1)`에 두 번째 `engine.connect()`+`SELECT 1`을 제출한다. 제출 직후 약 0.3초 동안 future가 끝나지 않았음(실제로 대기 중)을 확인하고 첫 연결을 반납한 뒤, future가 `TimeoutError` 없이 1을 반환하고 대기 시간이 반납 이후·한도(2초) 안임을 확인한다. `sleep`으로 "대기 진입"을 가정하는 대신 "반납 전 미완료"를 단언하므로 느린 CI에서도 통과 방향으로만 흔들린다. future 결과 대기에는 `timeout`을 둬 교착 시 테스트가 멈추지 않게 하고 `finally`에서 `engine.dispose()`한다.
- 기존 대기 초과 → `TimeoutError`·반납 후 회복 테스트(`test_pool_capacity_timeout_and_return_recovery`)는 유지한다.
- 시간 임계값은 넉넉하게 두고 성능 단언은 하지 않는다. 이 테스트는 SQLAlchemy QueuePool 동작 회귀 확인이며 새 기본값 10초 자체를 검증하지는 않는다(기본값은 단위 테스트가 담당).

전체: `ruff check .`, `ruff format --check .`, `mypy app migrations`, 일반 `pytest`, 일회용 DB의 `pytest -m integration`.

실제 개발 DB 재검증: 새 기본값(코드 변경 후, 진단 실행기 없이 일반 uvicorn)으로 §3.1과 같은 콜드 화면3 묶음 3시행, 500 0건·PG statement timeout 0건을 확인한다.

## 7. 중단·완료 조건

- 중단: 새 기본값에서도 같은 조건의 풀 대기 500이 재현되거나, 대기 증가로 최대 응답이 FE 15초에 근접하면 설정만으로 해결된다고 쓰지 않고 보고한다. 실제 개발 DB 재검증을 할 수 없으면 PR 전에 멈춘다.
- 완료: 원인 분류 근거 기록, 설계·Claude Code 재검토, 테스트·로컬 검사·CI/CodeQL 통과, 실제 DB 재검증, Render 권장안 문서화(적용 여부는 사용자 확인).

## 8. 기능별 커밋 계획

1. `docs(be): 동시 조회 500 재현·원인 분석과 설계·Claude 검토 기록` — 이 MD.
2. `fix(be): DB 연결 풀 대기 기본값을 콜드 동시 조회에 맞게 조정` — `config.py`, `.env.example`, 단위·격리 테스트, `render-free-validation.md` 27행의 "대기2초"→"대기10초"(설정 변경과 그 설정 서술을 같은 변경에서 맞춘다).
3. `docs(be): 동시 조회 500 수정 결과와 Render 권장 설정 기록` — 재검증 결과, `render-free-validation.md`의 Render 권장안(미적용) 절, 작업계획, BE CLAUDE.md.

중간 커밋 안전성: 기존 테스트 중 `database_pool_timeout` 기본값 2를 단언하는 것은 없다(`test_render_deployment.py`는 0.1을 명시, `test_render_runtime.py`의 예산 검증은 `pool_timeout`과 무관). 따라서 커밋 1(문서)·커밋 2(코드+테스트) 각각에서 기존 테스트가 깨지지 않을 것으로 본다. 각 커밋 후 일반 `pytest`를 실행해 확인한다.

## 9. Claude Code 검토 기록

### 9.1 검토 범위

- 대상 MD 전체와 `app/core/config.py`(풀 기본값·검증·연결 예산 validator·SQL 3초), `app/db/session.py`(`create_db_engine`의 `pool_timeout` 전달), `app/db/dependencies.py`(`read_only_session`의 `SQLAlchemyError`→500 INTERNAL_ERROR/no-store), `app/core/exception_handlers.py`, `app/services/readiness.py`(API 풀 밖 별도 연결), `app/routers/*`(동기 `def` 라우터·세션 의존성, `health.ready`의 `asyncio.to_thread`), `app/services/risk_interpret.py`(AI 준비의 `asyncio.to_thread`+`read_only_session`), `.env.example`, `docs/render-free-validation.md`, `docs/fe-render-validation-api-request.md`, BE `CLAUDE.md`·`docs/be-work-plan.md`의 Render 절과 §3 큐 규칙, `tests/integration/test_render_deployment.py`, `tests/test_config.py`, `tests/test_render_runtime.py`, FE `src/api/client.ts`(GET 15초)·`src/api/queryClient.ts`(재시도 정책)를 읽었다.
- Read·Grep·Glob과 이 MD에 대한 Edit만 사용했다. 명령·테스트·DB·네트워크·Git은 실행하지 않았고 `.env`는 열지 않았다. §3의 측정값은 검토자가 재현하지 않았으며 원문 기록을 그대로 두었다.

### 9.2 종합 판단

**조건부 진행 가능.** 원인 분류(풀 대기 초과, SQL 시간 초과 아님)는 예외 클래스·실패 시각 분포·PG 로그 0건이 서로 맞아 근거가 충분하고, 2초→10초 변경은 오류 경로·SQL 제한을 유지한 채 대기 한도를 실제 연결 점유 시간에 맞추는 것이어서 오류 은폐로 보지 않는다. 조건은 아래 수정 내용(특히 "BE가 FE보다 먼저 응답" 과장 정정, FE 재시도·스레드 점유 한계 명시, 테스트 결정성)을 구현·문서에 그대로 반영하고 §6의 실제 DB 재검증을 통과하는 것이다. 차단 이슈는 없다.

### 9.3 발견 사항과 수정 내용

1. **FE보다 먼저 응답한다는 서술의 과장(§4.1)**: 대기 10초 < FE 15초는 "풀 대기 실패" 경로에만 성립한다. 9초대에 연결을 받은 요청은 SQL 시간이 더해져 15초를 넘을 수 있다. 실패 경로로 한정하고 상한식을 추가했다.
2. **FE 재시도 영향 누락(§4.1·§4.3)**: FE `shouldRetry`는 500과 TIMEOUT을 1회 재시도하므로 풀 대기 500은 곧바로 중복 요청을 만들고, FE 중단 뒤에도 BE 동기 스레드는 계속 실행된다. 대기 증가가 500·재시도를 줄이는 근거이자 15초 이상으로 늘리지 않는 근거로 기록했다.
3. **스레드 점유·준비 검사·AI 예산(§4.1)**: 동기 라우터가 AnyIO 기본 40 스레드를 쓰며 풀 대기 중 스레드를 점유하고, 그 대기열 시간은 `pool_timeout` 밖이라는 한계를 명시했다. `/api/ready`는 별도 executor·별도 연결이라 영향이 없고, AI 준비는 LLM_TIME_BUDGET 안에서 풀 대기를 소비할 수 있음을 적었다.
4. **원인 서술의 단정 완화(§3.4)**: "#82·#118로 해소"를 "이번 측정에서 재현되지 않음"으로 바꾸고, 예외 클래스로 구분한 근거(풀 대기 `TimeoutError` vs 접속/SQL `OperationalError`)와 단발 측정·Render 로그 미확인 한계를 추가했다. 세션 준비 2문장도 문장 수에 포함했다.
5. **값 선택 근거(§4.1)**: 10초는 측정된 값이고 더 짧은 값은 측정하지 않았음을 명시했다. 다른 값을 권하지 않는다(근거 없는 값 도입 방지).
6. **Render 권장(§4.3)**: 예산 계산(6 ≤ 8)은 맞다. 준비 검사의 `rolconnlimit ≥ 예산` 조건, Free DB `max_connections`·외부 검증 연결 미확인, Free 웹 CPU 제한, 병렬화 이득이 불확실하고 SQL 10초에 걸릴 수 있음, 12초 이하 권장의 의미(겹침 감소, 15초 보장 아님)와 **미적용** 상태를 추가했다.
7. **문서 범위(§4.1 3항·§8)**: 저장소 Grep 결과 "대기2초" 서술은 `render-free-validation.md` 27행뿐이다. 설정 변경과 같은 커밋에서 고치도록 커밋 2로 옮기고, Render 실제 값 문구는 적용 전에는 바꾸지 않도록 했다. API schema·오류 코드 변경이 없어 FE 요청서가 필요 없음을 명시했다.
8. **테스트 실행 가능성(§6)**: 기본값 단위 테스트에 환경변수 제거(`monkeypatch.delenv`)를 추가하고, `.env.example`은 기존 테스트와 같은 `parents[1]` 경로·단일 행 확인·`model_fields` 기본값 비교로 구체화했다. 격리 테스트는 sleep 가정 대신 "반납 전 미완료" 단언·future timeout·dispose로 결정성을 높였고, 이 테스트가 10초 값 자체를 검증하지 않음을 적었다.
9. **커밋 중간 안전성(§8)**: 기존 테스트가 기본값 2를 단언하지 않음을 확인해 기록했다.

### 9.4 남은 제한·구현 시 확인할 점

- 모든 개선 근거는 로컬 단발 측정(콜드 화면3 각 3~5시행)이다. 구현 후 §6의 실제 DB 재검증(일반 uvicorn, 진단 실행기 없음)에서 500 0건·PG statement timeout 0건과 최대 응답이 FE 15초에 근접하지 않음을 확인해야 하며, 실패 시 §7 중단 조건을 따른다.
- 40개 초과 동시 요청·여러 사용자 부하에서의 스레드 대기열 시간, QueuePool 대기 순서의 공정성은 검증 범위 밖이다.
- 풀 대기 초과를 503 등으로 구분하거나 운영 로그에 고정 사유로 남기는 것은 API 계약·로그 필드 변경이라 후속 후보로만 둔다.
- Render는 권장안만 기록하며 적용·재배포·재측정은 사용자 결정이다. Free DB `max_connections`와 실제 원인(Render 로그)은 적용 시 확인한다.
- `.env` 사용자 로컬 파일에 풀 키가 없다는 서술은 설계자 확인을 따랐으며 검토자는 `.env`를 열지 않았다.

## 10. 구현·검증 결과

- 구현: `database_pool_timeout` 기본값 2→10초(`app/core/config.py`), `.env.example` 값·주석, `render-free-validation.md`의 코드 기본값 서술(대기10초)과 Render 권장안 7절(미적용). SQL 문장 제한·풀 크기·연결 예산·오류 코드·응답은 바꾸지 않았다.
- 테스트: 단위 2개(환경변수 제거 후 기본값 10·SQL 제한 초과·풀3/overflow0, `.env.example` 값=코드 기본값). 격리 1개(풀1·대기2초에서 반납 전 미완료 → 반납 후 TimeoutError 없이 성공). 기존 대기 초과 테스트 유지.
- 로컬 검사: ruff check·ruff format --check(345 files)·mypy app migrations(99 files) 통과. 일반 **1,657 passed**(기준 1,655+신규 2), 일회용 PostGIS 17-3.7 격리 **264 passed**(기준 263+신규 1). 기존 Starlette 경고 1건.
- 실제 개발 DB 재검증(일반 uvicorn, 설정 덮어쓰기·진단 실행기 없음, `.env`에 풀 키 없음 → 새 기본값): §3.1과 같은 콜드 화면3(15동시)+웜 1회차 × 3시행, 총 90요청 모두 200·앱 500 이벤트 0·PG statement timeout 0. 콜드 회차 최대 1,907~2,156ms, 웜 203~288ms. 같은 조건의 기존 기본값은 5시행 중 3시행에서 500 7건이었다(§3.1). 단발 측정이며 SLA·부하 상한 검증이 아니다.
- Render: 코드 기본값 변경은 Render에 영향이 없다(Render는 `DATABASE_POOL_TIMEOUT=15`를 명시). 풀1 직렬 문제는 환경변수 권장안(§4.3, 문서 7절)으로만 남겼고 적용·재배포·재측정은 사용자 결정이다.
