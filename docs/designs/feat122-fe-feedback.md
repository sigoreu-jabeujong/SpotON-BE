# FE 연결 후 동시 조회·제외 업종 혼입 점검 (#122)

- 작성일: 2026-11-14 (Asia/Seoul)
- 기준: BE develop `8958ba7`, 별도 작업 브랜치 `feat#122-fe-feedback`
- 요청: 설계 작성 → 실제 Claude Code 재점검·MD 직접 수정 → Codex 판단·구현·검증.
- 관련: #120 / PR #121은 로컬 풀 대기시간 수정이며 이번 변경과 구분한다.

## 1. 제보와 확인 상태

FE 담당자는 배포 화면의 실제 데이터 연결을 확인했고, 결과 화면 첫 진입의 GET 5개 동시 호출 지연과 무료 서버 절전 복귀 안내를 수정했다고 전달했다. 명동길 14·반경 500m·한식에서 비비큐치킨·인생주점 등 약 18곳의 제외 업종 혼입도 제보했다. 이는 FE 측 관측이며 전체 18곳·원본 분류·현재 배포 코드는 아직 대조하지 않았다.

현재 Render 문서 기준은 SQL 10초·풀 1·overflow 0·풀 대기 15초·워커 1·연결 예산/reader 제한 8이다. 풀 1은 요금제의 강제값이 아니라 앱 환경변수다. 절전 복귀와 DB 풀 대기·SQL 시간 초과는 구분하며 모든 500을 같은 원인으로 단정하지 않는다. 풀 증설은 절전 복귀 시간 자체를 해결하지 않는다.

로컬 FE 현재 checkout의 `npm run test`는 7파일·78개 통과다. 제보의 98개 및 대기 안내 변경은 최신 원격/담당 브랜치 대조 전까지 완료로 표시하지 않는다. FE 저장소의 기존 수정 금지 기준은 유지한다.

## 2. 범위와 보존 조건

- 작업 대상은 BE 코드·검증 도구·설계/전달 문서와 이번 요청의 Render 무료 풀 조정이다. FE 코드·CI·환경 파일·FE 이슈/PR은 수정하지 않고 담당자에게 전달한다.
- 현재 Render 서비스·Free 요금제·고정 commit·자동 배포 off·reader/TLS·CORS·SQL 10초·워커 1·overflow 0을 보존한다. 연결 URL·키·다른 환경변수는 원문 출력하지 않는다. 환경변수 변경은 해당 키만 갱신하고 다른 값의 해시 일치를 확인한다.
- 로컬 `.env`·개발 DB 내용·원본 스냅샷·스키마/head0011·운영 인덱스는 변경하지 않는다. 실데이터 조사는 읽기 전용이다. 실제 DB 보정이 필요하면 검증 가능한 별도 계획/롤백을 먼저 갖춘다.
- AI 시연 여부는 미확정이다. 기존 LLM 비활성 설정을 유지하고 준비 조건·미구현 상태만 문서화한다. 이번 조사로 키를 복사하거나 유료 자원을 생성하지 않는다.
- 사용자의 기존 checkout·untracked 문서는 보존하기 위해 별도 worktree에서 작업한다.

## 3. 동시 조회 설계

1. Render API로 현재 서비스·배포·허용된 비밀 아닌 설정만 확인한다. 첫 HTTP 대기, 준비 후 순차 기준, 이력·월 범위·주변·활동·Risk GET 5개 동시 묶음의 상태/시간/JSON digest를 수집한다. 응답·입력 원문과 비밀은 공개 증빙에 넣지 않는다.
2. 명동길 14의 geocode 응답으로 같은 건물/좌표를 선택하고 모든 비교에서 동일한 입력을 사용한다. snapshot은 필요한 월이 확정된 경우 별도로 검증한다.
3. 풀 후보는 우선 2개다. `2 * 1 * (2 + 0 + 1 ready) = 6 <= 8`이며 풀 3은 상한 8을 모두 사용하므로 바로 선택하지 않는다. reader 외부 연결·다른 인스턴스의 사용도 확인한다. 관리/검증 연결은 측정 중 닫는다.
4. 적용 전 현재 배포·설정·진행 중인 배포 부재를 재확인한다. 풀 값만 변경하고 기존 검증 commit으로 수동 재배포한다. 서비스 준비 및 CORS/AI503을 확인하고 순차/동시 묶음을 동일 조건으로 재측정한다.
5. 의미 없는 개선, 새 500/타임아웃·ready 실패·다른 설정 변경 시 원래 풀로 복구·동일 commit 재배포 후 복구를 확인한다. 단일 시점 성능 결과를 SLA나 절전 복귀 해결로 주장하지 않는다.

## 4. 제외 업종 혼입 설계

현재 ETL은 원본 `SNTTN_BZSTAT_NM`이 `한식`이면 `restaurant/korean`으로 저장한다. 원본 `통닭(치킨)`·`호프/통닭`·주점 등 명시된 제외 업종은 분류하지 않는다. API 공통 모집단은 저장된 category/sub_category·review/deleted 조건을 사용한다.

1. 제보의 실제 반경 응답과 해당 source+license_no의 저장 category/sub_category·원본 업종·현재 브랜드 추정 근거를 읽기 전용으로 대조한다. 이름이 치킨/주점처럼 보인다는 사실과 원천 업종 불일치를 구분한다.
2. 원본 제외 업종인데 지원 분류로 저장되었으면 적재/조회 결함을 수정한다. 원본부터 한식으로 등록되었으면 기존 ETL의 정확 일치 규칙상 동작이며 데이터 품질 보완으로 분리한다.
3. 상호 단순 포함 문자열로 전국 데이터를 삭제/재분류하지 않는다. 공정위 가맹 업종은 인허가 업종과 동일한 분류체계로 가정하지 않는다. 공식 브랜드 근거·명시적 제외 근거를 활용할 수 있으면 범위·오탐·비가맹/동명이인·재적재·캐시/메타 무효화를 포함해 설계한 뒤 채택한다.
4. 수정 시 history/nearby/snapshot/data-range/activity/risk가 같은 제외 정책을 사용하도록 공통 모집단에서 적용하고 AI의 재계산도 일치시킨다. 표시 목록에서만 숨기고 집계에는 남겨두지 않는다. 원본 업종·상호·식별자를 덮어쓰지 않는다.
5. 격리 PostGIS에서 지원 원본/제외 원본·같은 이름 다른 업종·브랜드 미확인·날짜/원천·history 정책을 회귀 검증한다. 실 DB 교정은 일반 조회 코드 수정과 구분한다.

## 5. AI·FE CI 전달

- AI를 보여주려면 시연 범위 결정, Render 전용 LLM 키·provider/model·한도 확인, 재배포 후 query-only POST 실제 성공·검증 실패/공급자 오류 처리가 필요하다. 모의 테스트 성공은 실모델 시연 완료가 아니다. 현재는 키 미설정 `503 AI_UNAVAILABLE`을 유지한다.
- FE CI는 `npm ci` 다음 `npm run test`를 추가하는 방향이 타당하다. 현재 workflow의 초기화 확인 조건을 테스트 단계에도 붙이고 의존성 설치 후 실행한다. 고정된 98개라는 개수 대신 최신 브랜치의 실제 실행 결과를 기준으로 한다. FE 담당자가 수정한다.
- FE 절전 복귀 안내는 적절하지만 30초·무조건 성공을 보장하지 않는다. 대기 후에도 실패하면 재시도 가능하게 유지한다. `/api/ready`를 모든 업무 요청의 선행 조건으로 추가하지 않는다.

## 6. 검증·커밋 계획

1. `docs(be): FE 연결 후 문제 점검 설계와 Claude 검토 기록`.
2. 확인된 코드 결함이 있으면 원인별 최소 구현과 의미 있는 회귀 테스트를 함께 커밋한다. 확인되지 않은 결함을 고치기 위해 필터/시간 제한을 임의 변경하지 않는다.
3. BE 변경 시 ruff/format/mypy·일반 pytest·필요한 격리 PostGIS 검사. 문서/Render 환경값만 변경하면 관련 설정 검증·5 GET 전후 비교·ready/CORS/AI503 및 문서 일치 검사를 수행한다.
4. `docs(be): 검증 결과와 FE 전달 사항 반영`. 현재 Render 안내 두 문서·BE CLAUDE.md·통합 작업계획의 현재값을 동기화한다. 설계 MD는 결정 근거이며 세 번째 Render 운영 안내로 사용하지 않는다.
5. BE develop PR·필수 CI 확인 후 기존 승인 범위에 따라 Squash 병합한다. #120/PR #121의 별도 작업을 임의 병합/수정하지 않는다.

## 7. Claude Code 검토 요청·결과

요청 조건: 실제 CLI에서 이 MD만 Edit, 필요한 BE·FE 소스는 Read로 대조한다. `.env`·비밀 백업·DB·Bash·네트워크·Git·다른 문서/코드 수정은 허용하지 않는다. FE는 최신 checkout/원격 차이를 고려하고 정적 추론과 실제 관측을 구분한다. Claude 검토 후 Codex가 diff를 직접 대조하고 적용 여부를 기록한다.

### 7.1 검토 방법과 한계 (2026-11-14, Claude Code)

- 실행한 것: 아래 소스의 Read와 이 MD의 Edit뿐이다. 테스트·Bash·Git·네트워크·DB·Render API는 사용하지 않았다. 아래 내용은 모두 **정적 대조와 추론**이고 실제 측정·DB 조회 결과가 아니다.
- Read한 BE 파일: `app/core/config.py`, `app/db/session.py`, `app/db/dependencies.py`, `app/services/readiness.py`, `app/services/store_history.py`, `app/services/store_cohort.py`, `app/services/spatial_stores.py`, `app/services/franchise.py`, `app/models/store.py`, `app/models/brand.py`, `app/ai/factory.py`, `app/services/risk_interpret.py`, `etl/localdata/normalize.py`, `etl/localdata/pipeline.py`, `etl/brands/compare.py`, `tests/etl/test_localdata_normalize.py`, `tests/test_render_runtime.py`, `docs/render-free-validation.md`, `docs/fe-render-validation-api-request.md`.
- **미확인**: `etl/brands/normalize.py`는 이 worktree에 없다(Read 시 파일 없음). 브랜드 상호 정규화는 `etl/brands/matching`·`catalog` 쪽일 가능성이 있으나 읽지 않았으므로 확정하지 않는다. ETL 적재(upsert) 모듈, `app/core/cache.py`, risk/activity/snapshot/data-range 서비스, `app/ai/gemini.py`도 읽지 않았다.
- Read한 FE 파일: `package.json`, `.github/workflows/ci.yml`, `src/api/client.ts` (로컬 checkout 기준이며 원격/담당 브랜치와 같다고 보지 않는다).
- 이 절 외 1~6절에서 수정이 필요한 사실 오류는 찾지 못했다. 1절의 FE 78개 통과는 Codex의 관측이며 이번 검토에서 재실행하지 않았다.

### 7.2 요약

| 구분 | 내용 |
|---|---|
| 차단 | (B1) 풀 변경 전 기준 측정에서 500의 원인(풀 대기·SQL timeout·기타)과 FE TIMEOUT/절전을 구분하지 못하면 개선 판정을 하지 않는다. (B2) 상호 문자열·공정위 업종으로 제외/재분류하거나 `SUPPORTED_STORES`에 새 조건을 넣는 것은 이번 범위에서 채택하지 않는다. (B3) 재배포 commit은 문서상 배포 commit `d449c5f`(검증된 commit)로 고정하며 develop `8958ba7`을 함께 배포하지 않는다. |
| 주의 | Free DB/0.1 CPU에서 병렬 2는 풀 대기를 SQL 10초 timeout으로 바꿀 수 있다. 캐시(risk/AI TTL 300초)와 재배포 후 콜드 상태가 전후 비교를 오염시킨다. AI 활성화 시 해석 요청도 같은 API 풀을 쓴다. reader 제한 8은 역할별 제한이다. |
| 동의 | 풀 2 선택(상한 6 ≤ 8), 풀 3 보류, 풀만 변경·동일 commit 수동 재배포·롤백, 원본 업종 보존, 제외 업종 정책의 공통 모집단 적용 원칙, AI 비활성 유지, FE CI에 `npm run test` 추가(담당자 수정), `/api/ready` 선행 호출 미도입. |

### 7.3 쟁점 1 — 무료 Render 풀 1→2

**소스 대조로 확인한 사실**

- `config.py:62` 검증식은 `2 * web_concurrency * (pool + overflow + 1)`이며 `peak > budget`일 때만 거절한다. 현재 Render 값(풀1)은 4, 풀2는 6, 풀3은 8로 **풀3도 검증은 통과**한다. 설계의 "풀3은 상한을 모두 사용하므로 보류"는 여유 0이라는 운영 판단으로 타당하다.
- `readiness.py:107`은 staging/production에서 `rolconnlimit >= DATABASE_CONNECTION_BUDGET`을 요구한다. 예산 8·reader 역할 CONNECTION LIMIT 8을 그대로 두면 풀 변경이 ready를 깨지 않는다. 예산을 함께 바꾸면 ready 실패로 이어지므로 **예산은 바꾸지 않는다**는 조건을 4단계에 명시하는 것이 좋다.
- `session.py:60-69`: `pool_pre_ping=True`, `pool_timeout=DATABASE_POOL_TIMEOUT`(Render 15초), 연결 timeout 5초. `dependencies.py:44-56`: 요청 하나가 세션(연결)을 **요청 처리 전체 동안** 점유하고, `SQLAlchemyError`와 `DatabaseConfigurationError`를 모두 `INTERNAL_ERROR` 500으로 바꾼다. SQLAlchemy 풀 대기 초과(`sqlalchemy.exc.TimeoutError`)와 statement timeout(`QueryCanceled` → `OperationalError`)은 둘 다 `SQLAlchemyError` 계열이라 **응답 본문만으로는 구분되지 않는다**(정적 추론).
- 풀 1에서 GET 5개가 동시에 오면 연결이 직렬화되고, 앞선 요청들의 누적 시간이 15초를 넘으면 뒤 요청이 풀 대기 초과 500이 된다. 이는 설계 1절의 "풀 대기"와 일치하며, 문서상 최장 단일 요청 8.656초·Risk 동시 최장 6.985초를 보면 5개 직렬 누적이 15초를 넘을 수 있다(관측값 조합에 의한 추정이지 측정 아님).

**세 원인 구분 (측정 설계에 추가 권장)**

| 원인 | FE에서 보이는 형태 | BE 쪽 구분 단서 |
|---|---|---|
| 절전 복귀 | 첫 요청이 FE 15초 제한(`client.ts:26`)을 넘으면 `TIMEOUT`(status null). 앱 500이 아님 | Render 이벤트/첫 health 지연. 풀 크기와 무관 |
| 풀 대기 초과 | 500 `INTERNAL_ERROR` | 요청 경과 시간이 대략 풀 대기 15초 이상 + 동시 요청이 풀 수보다 많을 때만 발생. 순차 실행에서는 재현되지 않아야 함 |
| SQL timeout | 500 `INTERNAL_ERROR` | 순차 단독 실행에서도 SQL 시간이 10초 근처에서 실패. 풀 증설로 오히려 늘 수 있음 |

`runtime`은 `access_log=False`이고 앱이 오류 종류를 로그로 남기는지는 이번에 읽지 않았으므로 **미확인**이다. 로그로 구분이 안 되면 위처럼 순차/동시·경과 시간 패턴으로만 분류하고, 분류 불가인 500은 "원인 미확정"으로 기록한다(B1).

**놓친 점·보완**

1. **병렬화 부작용**: Free DB·Free BE(공유 CPU)에서 동시 쿼리 2개는 각 쿼리를 느리게 할 수 있다. 특히 Risk 집계는 운영 인덱스로 12.589초→2.777초였으므로, 동시 실행 시 10초 SQL timeout에 다시 가까워질 수 있다. 롤백 조건에 "SQL timeout 형 500의 신규 발생"을 명시적으로 넣는다.
2. **캐시 오염**: `cache_enabled=True`, `risk_cache_ttl_seconds=300`(config 기본값, Render에서 다르게 설정했는지는 미확인). 재배포 후 프로세스 내 캐시는 비어 있으므로 "변경 전 warm vs 변경 후 cold"가 되면 비교가 왜곡된다. 전후 모두 (a) 재배포 직후 첫 묶음(cold) (b) 같은 입력 반복(warm)을 분리 기록하고, 묶음 사이 간격이 TTL 안인지 기록한다. 가능하면 각 조건 3회 이상 반복하고 단일 값으로 판정하지 않는다.
3. **판정 기준의 수치화**: "의미 없는 개선"을 사전에 정한다. 예: 동시 5 GET 묶음에서 풀 대기형 500이 사라지고 묶음 최장 시간이 기준 대비 줄었으며, 순차 기준의 개별 시간이 의미 있게 늘지 않을 때만 유지. 이 기준을 측정 전에 MD/PR에 적어 사후 조정하지 않는다.
4. **reader 제한은 역할별**: `rolconnlimit`는 `spoton_api` 역할에만 적용된다. 소유자 계정의 관리/검증 연결은 reader 제한 8에는 합산되지 않지만 DB 서버 전체 `max_connections`(Free 값 미확인)에는 합산된다. 3절 3번의 "관리/검증 연결은 측정 중 닫는다"는 유지하되, reader 역할로 여는 외부 검증 연결은 상한 6에 더해 8을 넘지 않는지 확인한다.
5. **배포 commit**: 문서상 현재 배포 commit은 `d449c5f…`이고 이 worktree 기준은 develop `8958ba7`이다. 이번 Read로 본 `config.py`가 배포 commit과 같은지는 확인하지 않았다. "동일 commit 재배포"는 Render가 보고하는 현재 배포 commit을 API로 재확인한 값으로 하고, develop HEAD를 함께 배포하지 않는다(B3). 배포 commit에서도 풀2·예산8이 검증식을 통과하는지는 같은 식이라면 자명하지만 commit 내용은 미확인이다.
6. **환경변수 보존**: 키 목록과 비밀 아닌 값의 전후 비교(해시)는 기존 CORS 변경 때의 절차(`render-free-validation.md:118`)와 같게 한다. Render API의 env 갱신이 전체 목록 덮어쓰기 방식인지 단일 키 갱신인지에 따라 다른 키가 지워질 위험이 있으므로, 단일 키 갱신 방식을 쓰고 갱신 직후 키 개수·이름 일치를 확인한다(Render API 동작은 이번에 확인하지 않음).
7. **롤백 계획**: 풀만 1로 되돌리고 같은 commit 재배포 → ready200·CORS·AI503·순차 기준 재확인 순서는 타당하다. 롤백 후에도 동일 오류가 남으면 풀 원인이 아니라는 증거로 기록한다.
8. **문서 동기화 대상**: 적용 시 `render-free-validation.md`의 dotenv 블록(풀1), 2절 "교체 상한 … = 4", 5절 "풀1 확인"과 `fe-render-validation-api-request.md:18`의 "풀1/대기15초"를 함께 갱신해야 한다. 적용하지 않으면 그대로 둔다.
9. **테스트**: 환경값만 바꾸면 코드 테스트는 필요 없다. 다만 `tests/test_render_runtime.py:22-31`의 파라미터에는 Render 실제 값(풀1/풀2·예산8)이 없다. 코드 변경 PR이 생기면 `(2, 0, 1, 8, True)`를 추가하는 것을 선택 사항으로 제안한다.
10. **PR #121과의 관계**: Render는 `DATABASE_POOL_TIMEOUT=15` 등을 명시하므로 로컬 기본값을 바꾸는 PR #121이 병합되어도 Render 동작은 바뀌지 않는다(PR #121 내용은 읽지 않았으므로 기본값만 바꾼다는 전제). 이번 작업에서 PR #121을 건드리지 않는 설계에 동의한다.

### 7.4 쟁점 2 — 명동길14·500m 한식에 치킨·주점 혼입

**소스 대조로 확인한 사실**

- `normalize.py:154-163`: `GENERAL_CATEGORIES`는 원본 업태명의 **정확 일치**(공백 정리 없음)만 매핑한다. `한식`→`restaurant/korean`. `호프/통닭`, `통닭(치킨)`, `정종/대포집/소주방`, `간이주점`, `감성주점`, `단란주점`, `룸살롱`은 `EXCLUDED_TYPES`이며 category/sub_category가 NULL, review=False가 된다. 테스트(`test_localdata_normalize.py:56-64`)가 목록 서로소·정확 일치를 고정한다.
- `pipeline.py:178-180`: 같은 원본 행에서 `bzstat_nm`(원본 업태명)과 category/sub_category를 함께 저장한다. 따라서 적재 시점 기준으로 **`bzstat_nm='한식'`이 아닌 행이 korean일 수 없다**.
- `store_history.py:17-28` `SUPPORTED_STORES`는 deleted/source/review/category·sub_category만 본다. `store_cohort.temporal_cohort`, `spatial_stores`, `current_provenance`, `orphan_exists`가 모두 이를 공유한다. 상호명은 조건에 쓰이지 않는다.

**결론(정적 추론)**: 제보된 치킨·주점 상호가 korean으로 나온다면 가능성은 (가) 원본 업태명 자체가 `한식`(일반음식점 인허가는 실제 영업 형태와 다르게 `한식`으로 신고된 경우가 흔하다고 알려져 있으나 이 저장소 데이터로 확인한 것은 아님), (나) 적재(upsert) 단계가 업태 변경 시 category를 갱신하지 않아 과거 분류가 남음, (다) 다른 배치/원천 혼합 중 하나다. (나)(다)는 적재 모듈을 읽지 않아 **미확인**이다. 현재 소스로는 "제외 원본이 한식으로 들어오는 코드 경로"는 발견하지 못했다.

**실제 DB 대조가 필요한 조건 (읽기 전용, Codex 수행)**

1. 제보 화면이 어느 응답인지(이력/주변 현재/과거 월 markers 등)와 `as_of`·필터를 확정하고, 그 응답의 `source+license_no` 목록 18건을 기준으로 한다. 상호명으로 DB를 검색해 대상을 늘리지 않는다.
2. 각 건의 `bzstat_nm`, `category`, `sub_category`, `category_review_flag`, `batch_id`, `deleted_at`을 조회한다. 판정: `bzstat_nm='한식'`이면 원본 분류대로의 동작, 그 외 값이면 결함.
3. 전체 불변식 검사: `category/sub_category`가 `normalize_category(source, bzstat_nm)`의 결과와 다른 행 수(지원 분류 전체). 0이 아니면 적재/갱신 결함으로 별도 수정한다. 이 검사는 이름 규칙 없이 코드의 매핑표만으로 판정하므로 근거가 명확하다.
4. 가능하면 같은 `license_no`의 원본 스냅샷 업태명과도 대조한다(스냅샷 변경 금지, 읽기만).

**근거 있는 수정 범위**

- 3번 불변식이 깨진 경우에만: 원인 위치(적재/갱신)를 최소 수정하고, 격리 PostGIS에서 "업태 한식→호프/통닭 변경 재적재 시 모집단에서 빠짐" 회귀 테스트를 추가한다. 이 경우 재적재/교정은 6절과 같이 실 DB 계획·롤백을 먼저 갖춘다.
- 불변식이 유지되면(원본이 `한식`): **코드 결함이 아니다**. 이름 정규식·브랜드별 업종 대응으로 제외하지 않는다(B2). FE에는 "인허가 원본의 위생업태가 한식으로 신고된 점포이며 실제 영업 형태와 다를 수 있음"을 안내 문구 후보로 전달하는 것을 권장한다.
- 공정위 브랜드 근거 검토: `brands.industry/sub_industry`가 있고 `store_brand_matches`는 이미 지원 분류 행만 담는다(`brand.py:141-146` CHECK). 그러나 매칭 규칙 `ftc-name-exact-estimate-v1`은 **상호 정확 일치 추정**이며 동명이인·비가맹·업종 체계 차이를 해소하지 못한다. 제외 근거로 쓰는 것은 이름 기반 제외와 실질적으로 같으므로 채택하지 않는다. 필요하면 "가맹 추정 업종이 치킨/주점인 korean 행 수"를 보고용 통계로만 산출한다.
- 장래에 수동 예외가 꼭 필요하면 `source+license_no`·근거·결정일·버전을 가진 별도 감사 가능 목록이 필요하며, 이번 이슈에서 만들지 않는다.

**공통 API 모집단·캐시·메타 회귀 위험 (변경 시 반드시 점검)**

- `ix_stores_provenance`는 `(batch_id, source, category, sub_category)`에 `deleted_at IS NULL AND category_review_flag IS NOT TRUE` 부분 인덱스다. #118의 skip scan(`orphan_exists`)과 Free 전용 `ops_free_risk_cover`(Risk 집계 커버링)는 현재 `SUPPORTED_STORES` 컬럼 집합에 맞춰져 있다. `bzstat_nm`·브랜드 조인 등 새 조건을 넣으면 index-only 경로가 깨져 Risk가 12초대로 돌아가 **Free SQL 10초 timeout을 넘을 위험**이 있다. 모집단 조건 변경은 실행 계획 재측정 없이는 금지한다.
- `etl/brands/compare.py:39-47`은 `SUPPORTED_STORES`를 import하지 않고 같은 조건을 별도로 복제한다. 모집단 정책을 바꾸면 이 복제본과 `store_brand_matches` CHECK, `automatic_match`의 키(category 포함)도 함께 맞춰야 한다.
- 메타: `HISTORY_RULE_VERSION` 등 rule_version 문자열과 `data_version.map_version`(배치 값)이 모집단 의미를 나타낸다. 모집단이 바뀌면 rule_version을 올려야 FE/캐시가 구분할 수 있다. risk/AI 캐시 키는 data_version_hash·context_hash를 포함하지만(`risk_interpret.py:106-120`) 코드만 바뀌고 해시 입력이 같으면 TTL 동안 이전 값이 남을 수 있다(프로세스 내 캐시라 재배포 시 비워지는 것으로 추정, `cache.py` 미확인).
- 원본 유지: `name`, `bzstat_nm`, `license_no`, `source`는 덮어쓰지 않는다는 4절 원칙에 동의한다.

### 7.5 쟁점 3 — AI·FE CI 전달

**AI**

- `factory.py:43-53`: provider가 google이 아니면 `UnavailableLlmClient`(NOT_CONFIGURED), google이면 `GeminiClient(api_key=None 가능)`를 만든다. 키 없을 때 503 `AI_UNAVAILABLE`이 되는 경로는 `risk_interpret.py:81,197`의 `LlmError` 처리와 일치한다(키 없음 → NOT_CONFIGURED 발생 지점은 `gemini.py` 미확인). 현재 비활성 유지에 동의한다.
- 시연 활성화 조건에 추가 권장:
  1. 문서 정책 변경: `render-free-validation.md:44`는 "LLM 키는 BE에 전달하지 않는다"고 명시한다. 활성화는 이 정책 변경 결정이 먼저다.
  2. 풀 경합: `_prepare`가 `read_only_session`으로 API 풀 연결을 쓰고 `interpret_max_concurrent` 기본 2다. 풀 2에서 해석 요청 2개가 동시에 DB 준비 단계에 들어가면 결과 화면 GET과 풀을 다툰다. 시연 시 동시 해석을 1로 낮추거나 시연 동시성 가정을 문서화한다.
  3. 시간: `llm_time_budget` 20초. FE `apiPost`는 기본 15초이며 `timeoutMs` 옵션으로 늘릴 수 있다(`client.ts:121-124`). 로컬 checkout에서 AI 호출이 실제 몇 초로 설정됐는지는 읽지 않아 미확인. 절전 복귀가 겹치면 20초를 넘을 수 있다.
  4. 모델 `gemini-3.5-flash-lite` 기본값의 실제 사용 가능 여부·한도·과금 형태 확인, `interpret_requests_per_day` 50 등 한도 유지, 실제 POST 성공과 `AI_VERIFY_FAILED`·공급자 오류 처리의 실측(모의 테스트로 대체 불가)은 5절 내용에 동의한다.

**FE CI (전달 내용)**

- 로컬 `ci.yml`은 Check → setup-node 20 → `npm ci` → lint → build이며 **test 단계가 없다**. `package.json`의 `test`는 `vitest run`이다. 제안: build 앞이나 뒤에 `if: steps.check.outputs.ready == 'true'` 조건으로 `npm run test` 단계를 추가. 5절 방향에 동의한다.
- 로컬 `client.ts`는 `TIMEOUT_MS = 15000` 고정이고 절전 복귀 안내·재시도 로직이 보이지 않는다. 따라서 로컬 checkout은 제보된 대기 안내 변경 전 상태로 보이며, 78개(로컬)와 98개(제보)의 차이도 브랜치 차이로 설명될 가능성이 높다(추론). 개수를 고정하지 않고 최신 담당 브랜치의 CI 실행 결과로 확인한다는 설계에 동의한다.
- 참고(미확인, 전달 시 확인 요청): CI는 Node 20을 쓰는데 Vite 8·Vitest 5의 최소 Node 요구와 Node 20 지원 종료 여부를 FE 담당자가 확인하는 것이 좋다. 이번 검토에서는 패키지 engines를 확인하지 않았다.
- FE 저장소 직접 수정 금지 유지에 동의한다.

### 7.6 Codex에 넘기는 확인 목록

1. Render 현재 배포 commit·env 키 목록·진행 중 배포 부재 재확인 → 기준(풀1) 순차/동시 묶음 cold·warm 각 3회, 500 원인 분류.
2. 사전 판정 기준 기록 → 풀2만 변경·같은 commit 재배포 → 동일 측정 → 유지/롤백 결정.
3. 제보 18건 `source+license_no`의 `bzstat_nm`·category 대조와 전체 매핑 불변식 검사(읽기 전용).
4. 불변식이 깨진 경우에만 적재 모듈을 읽고 최소 수정·격리 PostGIS 회귀 테스트. 깨지지 않으면 코드 변경 없이 FE 안내 문구로 전달.
5. FE 전달: CI test 단계 추가, 원본 업태 한계 안내, AI 503 유지.

위 1~5는 아직 실행되지 않았으며 이 절의 어떤 내용도 측정·DB 검증 완료를 뜻하지 않는다.

## 8. Codex 최종 판단·실행 결과

### 8.1 검토 채택과 사전 판정 기준

- 실제 Claude Code CLI 2.1.322의 소스 Read·MD Edit가 종료 코드0·is_error=false·권한 거절0으로 완료됐다. Codex가 수정 내용을 대조했다. B2(이름/브랜드로 임의 제외 금지)·B3(현재 배포 commit 고정)를 채택한다. B1은 이번 측정에서 500이 발생하면 로그/예외를 확보하기 전 원인을 단정하지 않는 조건으로 적용한다. 500이 관측되지 않은 경우 HTTP 지연의 전후 비교만 평가하며 기존 모든 오류 해결이라고 주장하지 않는다.
- 현재 Render API에서 `d449c5f0e86778a15fddac28722d0d6833fe8779` live·풀1/대기15초·Free·자동 배포 off·LLM 키 부재·세 CORS origin을 확인했다. reader 역할 연결 제한은8이고 조사 시 reader 연결은 조사 연결 포함2개였다. 조사 연결은 측정 전에 닫았다.
- 변경 전 최신 월 순차5건+동시5건2회는15건 모두200이었다. 첫 동시 묶음 최장18.875초, 두 번째9.859초다. HTTP200이 FE의 과거15초 제한보다 늦게 올 수 있음을 확인했지만 이번 실행에서 BE500은 재현하지 못했다.
- 풀2 유지 기준을 적용 전에 고정한다: 동일 commit·세 가지 시나리오(300/500/1000m, 한식, 2026-10)별 최초/반복 각 GET5개에서 전부200, 전체 JSON 전후 일치, 첫/반복 묶음 각각 중앙값15% 이상 감소, ready/CORS/AI503 및 나머지 설정 보존. 달성하지 못하거나 새 오류가 생기면 풀1로 복구한다. 물리 DB 콜드 상태를 강제하지 않으며 최초/반복은 시나리오별 호출 순서를 뜻한다. 첫 요청의 Risk 캐시 miss는 직접 계측하지 않으므로 확정하지 않는다.

### 8.2 업종 전수 대조·FE 최신 확인

- Render DB689,440행을 source·원본 업태명·저장 분류·review 값의62개 그룹으로 읽고 현재 `normalize_category` 매핑과 전수 대조했다. 불일치0건이다. 적재 upsert도 `bzstat_nm/category/sub_category/category_review_flag`를 모두 갱신하는 것을 소스로 확인했다. 현재 데이터에서 업태 변경 후 과거 분류 잔존 증거는 없다.
- 명동길14·500m·최신·한식의 실제 nearby454개를 source+license_no로 원본 저장값과 연결했고454개 모두 `bzstat_nm=한식`이다. 키워드 기반 조사 후보13곳(비비큐치킨 명동스타점·인생주점 등)도 원본 한식이다. 이13개는 검토 후보이며 확정 제외 건수나 FE 제보18개 전체 대조로 주장하지 않는다. 이름 검색으로 실제 집계를 변경하지 않았다. 원본 스냅샷 재대조·제보18개 명단은 미확보다.
- 최신 FE origin/develop `dcf8af1`을 별도 임시 사본에서 검사해13파일98개 테스트 통과를 확인했다. 이전 로컬 checkout 78개와의 차이는 브랜치 차이다. 최신 소스에서 일반45초·초기60초·느린 로딩 안내를 확인했고 CI test 단계는 여전히 없다. FE checkout/파일은 수정하지 않았다.
- 기준 BE develop의 일반 pytest는1,655 passed(격리263 deselected)다. 새 분류 규칙·API/ETL 코드 변경 없이 원본 업태의 한계를 전달한다. 명시적 제외 업태인 치킨/주점은 기존대로 제외되지만, 원본 한식 신고 점포를 실제 영업 형태까지 판별한다는 보장은 하지 않는다.

### 8.3 Render 풀 전후 검증

- 고정 시나리오의 변경 전30요청에서28건200·2건500을 관측했다. 실패는 data-range/nearby 각각1건이며 서버 요청 로그의 duration_ms는15,001.982/15,002.466이다. 같은15분 구간의 Web286로그·DB627로그를 pagination 종료(hasMore=false)까지 확인했고 DB ERROR/statement timeout은0건이었다. 풀 대기15초 만료와 일치해 풀 대기 초과를 강하게 시사하지만, 앱이 SQLAlchemy 예외를 안전하게 변환하여 예외 클래스가 로그에 없으므로 실제 클래스까지 확인한 것은 아니다.
- B1에 대한 Codex 판단: 기존 모든500의 원인 확정·해결 주장은 보류한다. 위 관측으로 풀1→2의 한 변수 대조 실험을 진행할 근거는 충분하다. 기존500의 동일 JSON을 비교 대상으로 삼지 않고, 각 시나리오/API에서 성공한200 본문을 오라클로 사용한다. 모든 조합에 성공 표본이 존재함을 적용 전에 확인한다. 적용 후 전부200·본문 동등성과 미리 정한 지연 기준을 통과해야 유지한다.
- 변경 전 묶음(초): 300m 최초16.515/반복15.219, 500m 최초16.078/반복19.360, 1000m 최초18.343/반복12.282. 최초 중앙값16.515·반복15.219이며 유지 기준은 각각14.038/12.936초 이하다.
- 풀 변경·재배포 후 결과는 이어서 기록한다. 아직 BE/FE 코드·실제 DB 내용은 변경하지 않았다.

## 9. 후속 설계: 풀 복구 후 검증된 출처 최적화만 별도 배포

풀2·기존 commit 재배포 `dep-dbs33fafngtc73bj7hi0`가 live가 됐다. 최초300m18.406초/500m18.500초, 반복11.157/12.000초로 관측되어 최초 중앙값은 세 번째 값과 무관하게18.406초 이상이다. 8절에서 미리 정한14.038초 기준을 넘으므로 풀2를 유지하지 않는다. 1000m 비교까지 끝내고 풀1·기존 commit으로 복구한 뒤 ready/설정/CORS/AI503을 확인한다.

다음 후보는 새 코드 작성이 아니라 **이미 develop에 병합된 #118의 출처 고아 검사 최적화 배포**다. 현재 배포 d449c5f에는 이 개선이 없다. 기준 develop8958ba7의 일반pytest1655개는 이번 작업에서도 통과했고, #118의 격리263개·실제 데이터 응답 digest 동등성은 기존 PR119/설계에 기록되어 있다. 실제 GitHub CI도 재확인한다.

- 7절 B3의 "풀 변경과 develop 동시 배포 금지"는 지킨다. 풀1 복구를 먼저 완료하고 별도 단계에서 commit만8958ba7로 바꾸어 수동 배포한다. 다른 환경값·키·DB·schema/head0011·인덱스는 그대로다. 배포를 이 설계문서의 미병합 commit으로 지정하지 않는다.
- #118은 기존 SUPPORTED_STORES를 유지하고 고아 검사를 batch_id/source의 서로 다른 키만 확인하는 recursive CTE skip scan으로 바꾼다. 필수 ix_stores_provenance 존재·유효 상태/정의와 head0011을 읽기 전용으로 확인한다. 실제 DB에 migration·VACUUM·재적재·인덱스 변경은 하지 않는다.
- 배포 전 실제 Free DB를 대상으로 후보 앱을 READ ONLY 설정으로 구동해 같은 API 성공 본문을 비교할 수 있다면 먼저 검증한다. 로컬/외부 경로 시간은 Render 내부 HTTP 시간과 혼동하지 않는다.
- 후보 배포 이후 동일30요청의 전부200·모든 성공 JSON 동일·최초/반복 중앙값 각각 원래 풀1보다15% 이상 개선·ready/CORS/AI503·나머지 환경값 보존을 만족할 때만 유지한다. 실패 시 풀1을 유지한 채 원래 d449c5f로 다시 수동 배포해 복구 확인한다. 원인별 예외 클래스 부재의 한계는 그대로 기록한다.
- 효과가 있어도 기존 전체500/절전 복귀/데이터 품질 문제가 해결됐다고 확대하지 않는다. 원본 한식의 제외 업종 보정·AI 활성화·FE CI 추가는 독립 후속으로 남긴다.

### 9.1 Claude Code 후속 재검토

이 후보는 아직 배포하지 않았다.

**방법과 한계 (2026-11-14, Claude Code 후속)**

- 이번에 실제로 실행한 것은 아래 파일의 정적 Read와 이 MD의 Edit뿐이다. pytest·Bash·Git·네트워크·DB·Render API는 사용하지 않았다. 아래 판단은 모두 소스 대조와 추론이며, 측정·DB 조회·배포 결과가 아니다.
- Read: 이 MD 전체, `app/services/store_cohort.py`, `app/services/store_history.py`, `app/models/store.py`, `app/services/readiness.py`, `tests/integration/test_store_provenance_index.py`, `docs/designs/feat118-source-batch-query-perf.md`.
- 읽지 않음: `app/models/store_import_batch.py`(PK가 `batch_id` 단독이라는 근거는 feat118 설계 기록에만 의존), 단위 컴파일 테스트 파일, `ops_free_risk_cover` 정의, d449c5f 소스. **d449c5f에 #118 개선이 없다는 점과 d449c5f..8958ba7 사이의 전체 변경 범위는 이번에 확인하지 않았다**(Codex가 git 비교로 최종 확인).
- 1~9절에서 고쳐야 할 사실 오류는 찾지 못했다. 9절 첫 문단의 "최초 중앙값 ≥18.406초"는 세 값 중 두 값이 18.406·18.500이므로 산술상 맞다. 1655개 통과·격리263개·실데이터 digest 동등성은 Codex/PR119 기록을 인용한 것이고 이번에 재실행하지 않았다.

**요약 판단: 조건부 동의.** 코드 의미는 기존과 동등하다고 판단하나, 이 배포로 성능이 좋아진다는 근거는 아직 Render DB에서 확인되지 않았다. 아래 차단 항목을 통과하기 전에는 배포하지 않는다.

| 구분 | 내용 |
|---|---|
| 차단 | (C1) d449c5f..8958ba7 변경이 #118의 `store_cohort.py`·테스트·문서뿐인지 git으로 확인. migration·모델·인덱스·config 기본값·의존성 잠금·다른 서비스 코드 변경이 있으면 한 변수 실험이 아니므로 이번 방식으로 배포하지 않는다. (C2) Render DB에서 `ix_stores_provenance` 존재·`indisvalid`·`indisready`·정의(`(batch_id, source, category, sub_category) WHERE deleted_at IS NULL AND category_review_flag IS NOT TRUE`)와 `alembic_version=0011`을 읽기 전용으로 확인. 인덱스가 없거나 무효면 새 쿼리는 재귀 단계마다 전체 스캔·정렬이 되어 기존보다 크게 느려지고 SQL 10초를 넘을 수 있으므로 배포 금지. (C3) 7절 B3 유지: 풀1 복구와 ready/CORS/AI503·환경값 해시 확인이 끝난 뒤에만 commit을 바꾼다. 풀·commit 동시 변경 금지. |
| 주의 | (W1) 기대 이득이 미확인. 개발 DB에서 기존 고아 검사는 약 37~42ms였다. Render Free DB의 기존 값이 이 정도라면 묶음당 수백 ms 이하만 줄어 15% 기준(약 2.5초)을 넘기 어렵다. (W2) 비교 표본이 작고 분산이 크다(같은 조건 12~19초). (W3) Render DB의 visibility map·통계·NULL batch 꼬리·지원 행 없는 키 규모가 개발 DB와 다를 수 있다. (W4) 로컬 후보 앱을 Free DB에 붙이는 사전 검증은 reader 연결을 추가로 쓴다. |
| 동의 | 새 코드 작성 없이 이미 병합·검증된 #118만 배포, 풀1 유지, 별도 단계 배포, 실패 시 d449c5f 재배포 복구, 다른 env/DB/schema/인덱스 보존, 효과가 있어도 기존 500·절전 복귀·데이터 품질 문제 해결로 확대하지 않는 원칙. |

**코드 정적 점검 결과**

1. **NULL batch_id**: `store_cohort.py:51-55` 첫 키는 `batch_id IS NOT NULL`이고, 재귀 분기(`:62`)의 row 비교에서 NULL은 참이 아니어서 열거되지 않는다. 대신 `:83` `null_batch`가 `SUPPORTED_STORES AND batch_id IS NULL`을 별도로 검사하므로 기존 anti-join(NULL은 배치와 매칭 불가 → 고아)과 같다. 테스트 `test_store_provenance_index.py:75`(NULL→500), `:78-80`(삭제/검토/미지원 NULL→200), `scenario_null_batch_supported/unsupported_tail`이 이를 고정한다.
2. **source 불일치**: 키는 `(batch_id, source)` 쌍으로 열거되고 `:76-79`의 NOT EXISTS가 두 컬럼을 모두 비교한다. 같은 batch_id·다른 source는 별도 키가 되어 고아로 판정된다. `store.py:51` source는 NOT NULL이며 `SUPPORTED_STORES`의 `source IN (...)`으로 지원 외 source는 빠진다. 테스트 `:77`, `scenario_same_batch_other_source`가 고정한다.
3. **recursive 종료**: 재귀 항은 `(batch_id, source) > 직전 키`의 엄격 부등호와 `ORDER BY ... LIMIT 1` LATERAL이므로 키가 단조 증가하고, 더 큰 키가 없으면 LATERAL 0행으로 종료한다. 중복·누락 없이 지원 행이 있는 non-null 키를 모두 한 번씩 방문한다. 무한 재귀 경로는 보이지 않는다.
4. **부분 인덱스 전제**: `store.py:39-46`의 정의와 `SUPPORTED_STORES`(`store_history.py:17-28`)의 `deleted_at IS NULL`·`category_review_flag IS NOT TRUE`가 일치하여 predicate 함의가 가능하다. 성능은 이 인덱스의 앞 두 키 순서 스캔에 전적으로 의존하며, 적격성은 격리 테스트(`:103-140`, `enable_seqscan=off`의 작은 데이터)로만 고정됐다. Render 실제 planner 선택은 미확인이다.
5. **쿼리 의미 동등성**: 결과는 bool 하나이고 `current_provenance`의 배치 목록 쿼리·500 정책·반환값·호출부는 바뀌지 않는다(`store_cohort.py:87-117`). 동등성은 12개 시나리오에서 테스트 내부의 기존 anti-join 기준 함수(`:153-160`)와 비교된다. 따라서 Render DB에 고아가 없으면 응답 JSON이 바뀔 코드 경로는 #118 범위 안에서는 보이지 않는다. 다만 C1에서 다른 변경이 섞여 있으면 이 결론은 성립하지 않는다.
6. **권한**: 새 SQL은 기존과 같은 `stores`·`store_import_batches`에 대한 SELECT만 쓴다. recursive CTE는 임시 테이블 권한(TEMP)이 필요 없어 readiness의 `temporary_create=false` 요구(`readiness.py:95-108`)와 충돌하지 않는다. READ ONLY 트랜잭션에서 실행 가능한 순수 SELECT다. 연결 수·풀 예산은 바뀌지 않는다.
7. **롤백 가능성**: migration·인덱스·데이터·env 변경이 없는 코드 단독 변경이므로 d449c5f 수동 재배포로 되돌릴 수 있다. 프로세스 내 캐시는 재배포 때 양방향 모두 비워진다(추정, `cache.py` 미확인). 반대로 장래 인덱스를 제거(0010 downgrade)하면 이 코드도 함께 되돌려야 한다는 feat118 §3.1 조건은 계속 유효하다.

**배포 전 필요한 사전 조건 (아직 실행 안 함)**

1. C1: `git diff --stat d449c5f 8958ba7`와 commit 목록으로 변경 파일 확인. `migrations/`·모델·config·`requirements`/lock 변경 0을 기록한다. d449c5f의 `store_cohort.py`에 `orphan_exists`가 없음을 확인한다.
2. 8958ba7 GitHub CI(일반·격리·CodeQL) 성공을 재확인한다.
3. C2: Render DB reader 역할의 READ ONLY 세션에서 인덱스 상태·정의·head0011을 확인한다. 같은 세션에서 **기존 anti-join과 새 쿼리의 `EXPLAIN (ANALYZE, BUFFERS)`를 각각 3회** 실행해 (a) 두 결과가 모두 false로 같은지, (b) LATERAL 단계가 `ix_stores_provenance` 순서 스캔(row 비교 Index Cond)인지, (c) heap fetch·`IS NULL` 분기 버퍼 수, (d) 기존 대비 절감 시간을 기록한다. 둘 다 SELECT이므로 데이터는 바뀌지 않는다. 연결은 측정 전에 닫는다. 이 단계 없이 개발 DB의 0.1ms 결과를 Render에 그대로 옮기지 않는다.
4. W1 사전 판단: 3-(d)의 절감 시간 × 묶음당 `current_provenance` 호출 수(data-range·activity·risk·nearby 등, 정확한 호출 수는 Codex가 호출부로 확인)가 15% 기준에 크게 못 미치면 배포 자체를 보류하고 그 사실을 기록한다. 이 경우 지연의 주원인은 고아 검사가 아닌 다른 쿼리(예: Risk 집계·nearby 공간 조회)일 가능성이 높다.
5. W2: 비교 기준은 8.3의 과거 값만 쓰지 말고, 풀1·d449c5f 복구 직후 같은 30요청을 다시 재서 직전 기준으로 함께 사용한다. 시나리오 순서·입력·간격(캐시 TTL 300초 안/밖)을 후보 측정과 같게 한다. 기준 자체가 흔들리면(같은 조건 반복 간 15% 이상 차이) 개선 판정을 보류한다.
6. W4: 로컬 후보 앱으로 사전 검증한다면 reader 역할·READ ONLY만 사용하고, Render 앱 피크 4 + 로컬 앱 풀/ready 연결 + 측정 연결의 합이 연결 제한 8 이하인지 확인한 뒤 끝나면 즉시 닫는다. 소유자 계정은 쓰지 않는다. 로컬→Free DB 경로 시간은 Render 내부 HTTP 시간과 비교하지 않는다.
7. 배포 후: 30요청 전부200·성공 JSON 동일·최초/반복 중앙값 각각 15% 이상 개선·ready/CORS/AI503·env 해시 보존을 9절 기준대로 확인하고, 실패 시 풀1 유지 상태에서 d449c5f로 재배포한 뒤 같은 항목으로 복구를 확인한다.

**확대 해석 금지**: 이 후속 배포는 원본이 한식으로 신고된 점포의 제외 업종 혼입(데이터 품질), AI 활성화, FE CI test 단계 추가를 해결하지 않는다. 이들은 독립 후속으로 남는다. 성능 개선도 위 측정으로 재현되기 전에는 확정하지 않는다.

### 9.2 Codex 사전 조건 대조·최종 배포 판단

- 후속 Claude CLI도 exit0·is_error=false·권한 거절0으로 종료했다. Codex가 실제 MD 수정과 소스를 대조했다.
- C1: d449c5f..8958ba7의 실행 코드 차이는 `app/services/store_cohort.py`와 새 `app/analysis/day_night.py` 두 파일이다. 후자는 #115의 독립 산술 기반으로 API/AI/DB에서 import하지 않으며 테스트에서만 import하는 것을 rg와 package init으로 확인했다. migration·모델·config·기타 서비스·ETL·Docker·pyproject/uv.lock 차이는0이다. 따라서 "전체 코드 파일이 #118 하나뿐"이라고 쓰지 않고, 배포되는 추가 미연결 모듈을 명시한다. 현재 API 요청 경로의 동작 변경은 #118 하나라는 판단으로 진행한다. 원래 배포 소스에는 `orphan_exists`가 없음을 git diff로 확인했다.
- 8958ba7의 GitHub `lint-and-test`·`postgis-integration`·CodeQL Analyze(actions)가 모두 completed/success임을 확인했다. 이번 worktree 일반pytest1655개도 통과했다.
- C2: Free reader READ ONLY로 head0011·ix_stores_provenance의 전체 정의 및 valid/ready/live·ops_free_risk_cover 존재를 확인했다. 후보 앱을 같은 Free DB에 붙인 별도 사전15 API는 모두200·기존 성공 본문 SHA256 완전 일치·SQL 오류0·실모델0이었다. 앱 종료로 준비/풀 연결을 닫았다. 후보 앱의 외부 경로 HTTP 시간은 Render 성능 비교에 쓰지 않는다.
- Free DB READ ONLY EXPLAIN ANALYZE3회에서 기존 고아 검사는2,825.046/1,720.435/1,999.757ms·shared hit624/626/628, 후보는0.166/0.097/0.105ms·shared hit15로 관측됐다. 둘 다false·heap fetch0이고 후보는 ix_stores_provenance의 LATERAL 순서 스캔을 사용한다. 쿼리4개 호출부(data-range/nearby/activity/risk)를 소스로 확인했다. 관측 중앙값 약2초의 절감을4회 사용하므로 사전 검토 W1의 효과 부족 조건에는 해당하지 않는다. 실제 전체 HTTP 개선 여부는 배포 후 별도로 판단한다.
- C3: 풀2는30건 모두200·본문 일치였으나 최초 중앙값18.500초(기준16.515), 반복12.000초(기준15.219)로 최초 유지 조건을 실패했다. 풀1/d449c5f 복구 배포dep-dbs352u7bikc73efiofg live 이후 ready/health200·CORS preflight6/실제GET3·미허용origin차단·AI503·나머지 환경값 해시 일치를 확인했다.
- 복구 직후30요청 재측정은29건200·data-range1건500이었다. 최초 묶음17.640/18.312/20.125초(중앙값18.312), 반복9.891/16.375/12.297초(중앙값12.297)다. 반복 편차가 큰 Free 환경임을 기록하고 분산이 없다는 주장은 하지 않는다. 후보는 원래 기준과 직전 복구 기준 모두에서15% 개선·30건200·전체 JSON 동등성을 확인한다. 이는 작은 관측 표본의 유지 기준이며 SLA/통계적 보장은 아니다.
- 위 조건을 확인한 후 풀1을 그대로 두고 검증된8958ba7만 수동 배포한다. 아직 미병합인 #120/PR121 기본값 변경은 포함하지 않는다.

### 9.3 최적화 배포 결과

- `8958ba737002e9969027db832f3ac6aaf45277d6` 배포 `dep-dbs37aek1f9s73858g6g`가2026-11-14 19:11:42 KST live가 됐다. 풀1·대기15초·SQL10초·워커1·overflow0·예산8과 모든 환경값/키 목록 해시·Free·자동 배포off를 보존했다. schema/head0011·DB 데이터·운영 인덱스는 변경하지 않았다.

| 구성 | 최초 묶음 중앙값 | 반복 묶음 중앙값 | 30요청 상태 |
|---|---:|---:|---|
| 기존d449c5f·풀1 최초 기준 | 16.515초 | 15.219초 | 28×200·2×500 |
| 기존d449c5f·풀2 후보 | 18.500초 | 12.000초 | 30×200, 최초 기준 실패로 복구 |
| 기존d449c5f·풀1 복구 직후 | 18.312초 | 12.297초 | 29×200·1×500 |
| 최적화8958ba7·풀1 최종 | **9.688초** | **6.110초** | **30×200** |

- 최종 각 반경 최초/반복 묶음은300m8.735/4.015초, 500m9.688/8.656초, 1000m10.500/6.110초다. 기존 최초 기준 대비 중앙값41.34%/59.85% 감소, 복구 직후 기준 대비47.09%/50.31% 감소로 두 기준 모두 사전15% 개선 조건을 통과했다. 성공 응답 전체 JSON SHA256은 두 기준의15개 시나리오/API 조합과 모두 같았다. 이 관측에 따라8958ba7·풀1을 유지한다.
- 최종 health/ready200, 세 origin GET/POST preflight6건·실제GET3건200/정확한 ACAO, 미허용·유사도메인·localhost5181차단, AI503 AI_UNAVAILABLE을 확인했다. 실제 LLM 키는 추가하지 않았고 실모델 호출도 하지 않았다.
- 최종 배포 후 조회한 Web92로그·DB71로그 구간에 DB ERROR/statement timeout 문구는0건이다. 다만 Web에는 `path=unmatched`500이2건(19:12:21/19:12:51 KST, 1.198/0.869ms) 남아 있었다. 업무5개 API의30건은 모두200이므로 이2건과 구분한다. 기존 로그의 allowlist는 ready 경로를 식별하지 못하므로 운영 probe일 가능성은 있지만 확정하지 않는다. 원인/경로 식별 개선은 #78/#122 후속이며 전체 서버500이 사라졌다고 주장하지 않는다.
- 물리 DB 캐시 초기화·15분 무요청 후 실제 절전 복귀·여러 사용자 동시 화면·전체 FE 브라우저 수용 검사는 이번에 하지 않았다. 최초/반복은 고정 시나리오의 호출 순서다. 작은 표본·Free 자원 편차·캐시 상태 때문에 위 시간이나 개선율을 SLA로 쓰지 않는다.
- 코드 변경은 기존 병합본을 배포한 것이며 이번 브랜치에는 설계·검토·실행 결과·FE 전달 문서만 추가/수정한다. 원본 한식의 실제 제외 업종 혼입, FE CI 추가, AI 시연 활성화 결정은 미해결 후속으로 유지한다. #122/#78을 이 PR로 자동 종료하지 않는다.
- 설계/검토 JSON·읽기 조사·전후 벤치마크·설정 보존/롤백·배포 검증 증빙과 실행 스크립트는 저장소 밖 `%USERPROFILE%\SpotON-private-backups\render-free-20261113\fe-feedback-20261114\`에 보관한다. 자격증명·실제 URI·원본 점포 식별자·응답 원문·프롬프트/모델 원문은 커밋하지 않는다.
