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

실행 후 기록한다. 현재까지 Render 설정·BE/FE 코드·실제 DB는 변경하지 않았다.
