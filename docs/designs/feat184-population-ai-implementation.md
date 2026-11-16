# 공개 부분자료 AI 실제 연결·FE 호환 선배포 (#184 / FE #76)

2026-11-16 사용자가 #182 설계 다음 단계 진행을 요청했다. [검수된 설계](feat182-population-ai-integration.md)를 반복하지 않고 구현한다. FE 수정·운영 배포는 기존 사용자 지시와 이번 후속 요청 범위다. 과거 설계 전용 문구는 #182 당시 이력이다.

## 1. 실제 구현

- `app/schemas/ai_population.py`: v2 전용 frozen/strict allowlist. 원천별 부분 상태·허용 metric5필드(display/zero/rounded/unit/reason)·최소 quality/한계·관측일이다. value·24시간·합계/평균·위치/격자/행정동 식별자·원천 UUID/hash는 outbound에 없다. 모든 승인 플래그는false다.
- `app/ai/population_context.py`: 공개 API의 typed 결과와6필드 query·T/관측월/scope를 대조하고 명시적으로 투영한다. 내부8개 metadata digest와 projection rule만 data_version_hash에 추가한다. 원문 provenance는 모델/응답에 보내지 않는다.
- `prepare_chain_interpretation`: Risk·활동과 같은 READ ONLY RR 세션에서 기존 `get_population_reference`를 직접 호출한다. 새HTTP/별도세션/FE값을 사용하지 않는다. SQL직전 deadline과 기존 연결 반환·오류 의미를 유지한다.
- v2 네 번째 문단에 내국인 비중·관측일·부분성·필터와 무관한 모집단·외국인 별도 상태·제외 편향/공식 기준 미확인을 서버가 넣는다. 문장만의 최소 evidence로 `verify_output`을 먼저 실행하고 후보 자신은 whitelist에 넣지 않는다. 기존 전체 본문 검사와4그룹·모델의ID만선택을 유지한다.
- 전체 생활인구 미확보 문구는 v2만 구분한다. partial을 `official_values`/유리/불리 후보/Risk fact에 넣지 않는다. 새 근거ID는 `population_public_subset`, partial이 사용된 v2 meta만R4를 추가한다. v1 프롬프트/본문/키 의미는 보존한다.
- 독립 chain prompt v2·불변 지문 이력과 선택 캐시 rule v2를 추가한다. 현재 문맥/원천 digest/프롬프트 변화가 캐시를 바꾸며 현재 문맥의 재검증은 계속 수행한다.
- FE #76: optional typed evidence·별도 상태/관측일 정보·동적인 미확보 안내·이동 없는 근거 이름·보고서의 AI 관측일을 추가한다. 이전 BE 응답에 새 필드가 없어도 기존 설명을 유지한다.

## 2. 지킨 경계

DB0012·원문/기존 원천 hash·전체 생활인구/Risk pending·원천 unverified·키/환경파일·17개 Render 환경변수·Vercel 설정·기존 로그 Task/runtime·사용자 파일을 유지한다. 새 DDL/적재·공식 가산성/격자 기간 승인·외부 문의 제출은 하지 않는다. #115/#78은 열린 상태다. 본문의 부분 비교는 전체 인구·방문객/고객 수·수요·수익성을 뜻하지 않는다.

이번 구현의 원천 조회는 현재 공개 API와 같고 관측 전체 COUNT/스캔을 추가하지 않는다. 유효 pending/no_data/not_supported는 숫자 없는 해석으로 이어지고, 손상·스코프 불일치500이나 deadline503을 유효 결측으로 숨기지 않는다.

## 3. 검증 계획과 실제 결과

| 검사 | 현재 실제 결과 |
|---|---|
| AI/새 인구 단위·라우터 회귀 |최종보완408개 통과. 새 projection/문장/제로/숫자변조·메타드리프트와 기존 v1/v2 검증 포함 |
| 새 실제 PostGIS |최종보완8개 통과. 같은RR/read-only·연결반환·GET/AI/필터일치·결측·source digest cache miss·손상/deadline·두업종 기본/최초월/그직전/빈cohort·실제SQL직전worker stop listener |
| FE |최종보완188개+profile4개 통과, lint/build 통과. 실제브라우저는 아래 실행 기록에 추가 |
| 전체 BE 회귀/정적검사 |일반2516통과/Windows symlink권한3skip/통합312deselected, 실제PostGIS312통과/no skips, ruff 및mypy189files 통과 |
| 복제DB prepare 성능 |baseline/feature 각 warm15회. baseline최대0.172초·feature최대0.265초·증가최대0.140초로 각≤6초/증가≤3초 충족. 모델0회·읽기전용이며 cold보장이 아니다 |
| Claude Code |실제 정적 구현 검토 후 판정·지적·Codex 처리 기록. 사전PASS로 적지 않음 |
| CI/배포/공개검증 |정확한 head의 실제 검사·commit/deployment·모델/브라우저 결과를 PR/이슈에 기록. 그 전에는 완료로 표시하지 않음 |

로컬 Docker 엔진이 꺼져 있어 처음 실행은 연결되지 않았다. 설치된 Docker Desktop CLI로 엔진을 시작해 기존 컨테이너가 healthy임을 확인했다. 원본 spoton_dev에 migration/적재/SQL쓰기·설정변경을 하지 않았다. DB 단위 검사는 새 폐기용 DB이며 실자료 검증은 앞선 #180에서 별도 복원·전체 지문 확인한 clone을 읽는다. 모의 공급자 검증과 실제 모델 호출은 구분한다.

설계 검토 당시 발췌에 없던 FE `interpretationMatches`에서 prompt v1만 허용하는 조건을 실제 소스로 확인했다. v1의 필드 없는 응답과 v2의 인구 계약이 있는 응답만 각각 허용하도록 바꾸고 날짜/상태/원천 순서·승인 플래그를 확인한다. 미지원 버전·새 버전의 인구 근거 부재·다른 날짜는 거절한다. 이 호환 변경도 FE 선배포에 포함한다.

## 4. 배포·복구 순서

1. 구현/실제 clone·모의 모델 브라우저·Claude·회귀/CI를 완료한다.
2. FE feature→develop 정상 PR, develop→main release 정상 PR로 호환 FE를 먼저 배포한다. 정확한Vercelcommit과 공개 도메인에서 기존BE의 필드 없는 응답/안내를 확인한다.
3. BE PR을 정상 Squash해 정확한 commit으로 기존 Render Free를 배포한다. 이전 live/commit을 기록하고 기존17개환경값hash·DB0012/조회권한/원천 metadata를 보존한다. 자동배포off/기존LLM/CORS/풀/timeout을 바꾸지 않는다.
4. 공개 실제 모델은 partial과 유효 no_data 각1회 이내로 확인하고 검증·4문단·근거ID/출처·관측일을 확인한다. 모바일·정보팝오버·보고서/PDF·오류/취소·기존GET을 확인한다. 기존API응답을 새원천공식승인으로 바꾸지 않는다.
5. 문제가 있으면 먼저 이전BEcommit으로 복구한다. 필요하면 이전BE응답을 확인한 뒤 FE도 이전deployment로 복구한다. DB변경이 없어downgrade하지 않는다. 실제복구를 하지 않았다면 계획으로만 기록한다.

## 5. 실제 Claude 검토와 Codex 최종 판단

실행 후 아래에 실제 검토를 추가한다. 앱/FE 소스 편집 권한은 주지 않고 이 MD만 Read/Edit한다. 제공한 소스와 실제 검사 근거를 정적으로 대조하며 테스트를 대신 실행했다고 쓰지 않는다. 키·.env·실원천 행·실제 위치/주소/식별자는 검토 입력에 넣지 않는다.

### 5.1 Claude Code 실제 정적 구현 검토 (initial, 2026-11-16)

**판정: PASS. 차단 결함은 없고 비차단 지적 6건이 있다.**

검토 범위와 한계: 요청 메시지에 들어 있던 BE 소스(`ai_population.py`, `ai_context.py`, `population_context.py`, `chain_context.py`, `narrative.py`, `interpretation.py`, chain `system.md`/`chain_version.py`, `builder.py`, `verifier.py`, `risk_interpret.py`, `population_reference.py`, `interpret.py`), 테스트 두 파일, FE 소스(`interpretationContext.ts`, `aiPopulation.ts`, `AiPopulationInfo(.test).tsx`, `AiInfoPopover.tsx`, ReportPage/messages/risk.ts 일부)만 정적으로 읽었다. 코드·테스트·shell·Git·DB·네트워크는 실행하지 않았다. §3의 수치(AI407, BE2516+3skip, PostGIS312, FE185+4, ruff/mypy189, 벤치마크)는 Codex가 제공한 근거이며 이 검토에서 재현하지 않았다. 다음 사항은 확인하지 않았고 이 검토로 주장하지도 않는다: 원래 15개 위치의 정확도, 공식 인구 승인, 배포 성공, 실제 LLM 호출. 소스에 없는 `PopulationModel`, `PublicSourceReason`, `PublicNumber`, `PopulationReferenceQuery`의 기본값·확장 규칙, `load_chain_prompt_bundle`, ReportPage `FooterBlock`의 출처 매핑, FE `interpretationMatches`의 테스트 파일은 보지 못했다.

#### 체크 항목별 대조

| 항목 | 판단 | 근거(정적) |
|---|---|---|
| outbound 필드 투영의 엄격성 | 충족 | `project_population`이 dict를 명시적으로 만든다. metric은 `exclude={"value"}`, quality는 `include=QUALITY`로 거른다. `ContextPopulationReference`/`Metric`(PopulationModel, extra 금지로 추정)에 다른 필드가 들어오면 ValidationError(ValueError)→500으로 닫힌다. 테스트가 top-level 12키와 metric 5키 집합을 고정한다. |
| 원천 ID·좌표·원값·시간별 합계 없음 | 충족 | VERSION_FIELDS 8개(UUID/sha)는 digest 계산에만 쓰이고 context에 들어가지 않는다. `population_snapshot_token`·`grid_as_of`·`hourly_source_sums`·`value`는 투영되지 않는다. lat/lng는 population query 안에서만 쓰인다. `builder.FORBIDDEN_CONTEXT_KEYS`가 마지막 관문으로 `input_sha256` 등을 막는다. |
| 같은 RR·6필드 scope·관측월 | 충족 | `prepare_chain_interpretation`이 같은 `session`으로 `get_population_reference`를 호출한다. query는 lat/lng/radius/category/sub_category/as_of 6필드만 쓴다. `analysis_date == Risk data.query.as_of`를 `project_population`과 `ChainRiskInterpretContext` 두 곳에서 확인한다. 관측일 범위는 서비스 SQL, `ContextPopulationReference` validator, FE 세 곳 모두 `[T월1일, T]`로 같다. PostGIS 테스트가 RR/read-only를 확인한다. |
| 원천별 부분 계산의 독립성 | 충족 | 문장에는 내국인 day/night 비중만 숫자로 나온다. 외국인 두 원천은 상태 문구만 쓰고, 원천 간 합산·대체·배수(ratio)는 문장에 없다. 테스트가 `"2.00000"` 부재를 확인한다. |
| 서술: 내국인/외국인·null·반올림0 | 충족(비차단1) | local=내국인, long/short=장기/단기체류 외국인으로 BE와 FE NAMES가 같다. metrics 없음, display null(`zero_total`), 정확한 0, 반올림 0이 각각 다른 문장으로 나간다. validator가 `zero ∧ ¬exact_zero ⇒ rounded`를 강제한다. → N2 참고 |
| 4그룹·모델은 ID만 선택 | 충족 | NarrativeCatalog 4그룹×2변형 구조, `selection_schema` enum, `selection_valid`는 그대로다. 인구 문장은 group 3 서버 문단 안에만 들어간다. |
| 인구 문장만의 별도 검증 | 충족(비차단1) | `population_sentence`가 문장 자신을 뺀 최소 evidence(날짜, local display/rounded/reason)로 `verify_output`을 먼저 돌린다. 숫자 변조 테스트가 있다. 이후 기존 전체 본문 검사는 approved_narrative 자기 whitelist를 유지한다(기존 설계). → N3 참고 |
| v1 prompt·본문 불변 | 충족 | 문장 치환, 인구 문장, missing 문구 모두 `isinstance(c, ChainRiskInterpretContext)` 분기 안에 있다. `CHAIN_PROMPT_HISTORY`가 v1 지문을 보존한 append-only 구조다. 비chain `SELECTION_CACHE_RULE`과 meta source R5/R6도 그대로다. |
| Risk 유리/불리 partial 추론 없음 | 충족 | favorable/unfavorable은 `c.indicators`의 TITLES 지표에서만 만든다. population은 indicators/official_values에 들어가지 않는다. Risk `day_night_ratio`는 pending으로 남는다. 단위 테스트가 catalog facts/fav/unfav에 ID가 없음을 확인한다. |
| 캐시 무효화(현재 문맥·내부 digest) | 충족 | key에 `CHAIN_SELECTION_CACHE_RULE` v2, `data_version_hash`(population_digest 포함), `context_hash`, payload, prompt version/sha가 모두 들어간다. cached selection도 매번 현재 catalog로 `selection_valid`를 다시 확인한다. PostGIS 테스트가 `content_sha256`만 바뀐 경우 miss와 evidence 동일을 확인한다. |
| source R4 | 충족(비차단1) | partial이 하나라도 있으면 `response_meta.source=[R5,R6,R4]`, 아니면 [R5,R6]이다. 통합 테스트에서 이전 월 no_data는 [R5,R6]이다. → N1 참고 |
| 상태별 오류와 deadline | 충족(비차단1) | 서비스 내부 ValueError/TypeError/OverflowError는 AppError 500(no-store)이 되고, `prepare_chain`은 AppError를 삼키지 않는다. 투영/scope 불일치는 ValueError→500이다. `before_cursor_execute`의 LlmError(TIMEOUT)는 잡히지 않고 올라가 503이다. 유효 pending/no_data/not_supported는 숫자 없는 문장이 된다. → N4 참고 |
| FE OLD v1(필드 없음)·NEW v2(typed)·불일치 거절 | 충족(비차단1) | `populationContractMatches`: v1은 `p===undefined`일 때만, v2는 객체·as_of 일치·승인 플래그 false·상태별 reason/observation/sources 일관성·원천 순서·partial↔metrics일 때만 통과한다. 그 밖의 버전은 거절한다. `&&` 단락 평가 순서 때문에 `analysis_date.slice` 호출 전에 meta.as_of가 truthy임이 보장된다. → N5 참고 |
| 이전/새 안내 문구·보고서 날짜 | 충족 | Popover가 population 유무에 따라 `unavailableText`↔`populationUnavailableText`, `excludedRule`↔`populationRule`을 바꾼다. ReportPage AiBlock이 POST evidence의 분석일/관측일을 표시하고 GET 카드 날짜와는 독립이다. |
| source UI | 비차단 | → N1 참고 |
| 운영 순서 FE 먼저, 복구 BE 먼저 | 충족 | 이전 FE는 v1만 허용하므로 BE v2가 먼저 나가면 거절된다. 따라서 §4의 FE 선배포, BE 선복구 순서가 맞다. 캐시 rule v2라서 이전 BE 선택 캐시와 섞이지 않는다. 신규 키·0013 없음. |
| 범위 | 충족 | 전체 생활인구는 pending/unverified로 남는다. 승인 플래그는 Literal False로 고정이다. DDL·적재 없음. |

#### 비차단 지적 (Codex가 처리 여부를 기록할 것)

- **N1 출처 표기·근거 칩이 데이터 사용과 어긋남.** (a) `preparation_ids=["population_public_subset"]`는 상태(no_data/pending/not_supported, 모든 원천 no_data)와 관계없이 항상 붙는다. 그래서 meta.source에 R4가 없어도 FE 칩 "공개자료 주야간 비교 (부분)"가 보인다. 권고: partial이 하나라도 있을 때만 ID를 붙이거나, 칩 라벨을 상태 중립적으로 바꾼다. (b) Popover의 출처 줄 `T.source`는 인허가 자료만 적고, R4가 meta에 있어도 인구 원천 이름을 보여주지 않는다. ReportPage FooterBlock이 AI meta의 R4를 매핑하는지는 소스에서 확인하지 못했다. 브라우저 검증 때 확인할 것.
- **N2 반올림 100.0% 표시.** night가 반올림 0.0%이면 day는 반올림 100.0%가 될 수 있다. 문장은 "영으로 보이는 비중"만 반올림이라고 설명하고 100.0%의 반올림 여부는 말하지 않는다. 사실 왜곡은 아니지만 `rounded=True`인 100.0%에도 같은 보조 문구를 쓰는 편이 일관적이다.
- **N3 전체 검증 whitelist 확대.** `prepared.json_context()`에 population_reference가 들어가면서 기존 visible text 검사와 LLM 출력 검사의 허용 숫자에 quality 건수, 표시 비율, `06-17`/`00-05,18-23`의 6/17/0/5/18/23, 관측일 숫자가 추가된다. 모델은 ID만 고르므로 위험은 낮다. 다만 Risk fact 문장의 숫자 드리프트 검출력이 약간 떨어진다. 인구 문장은 별도 검증이 있으니 기록만 권고한다.
- **N4 fail-closed 경로의 예외 타입.** `population_sentence`/`_sentence`는 `REASONS[...]` (KeyError)와 `assert` (AssertionError, `-O` 실행 시 제거됨)에 의존한다. 이 함수는 `build_catalog` 단계에서 호출되고, `interpret_risk`는 ValueError/TypeError만 INTERNAL_ERROR로 바꾼다. KeyError/AssertionError는 전역 핸들러로 빠지므로 no-store 헤더가 보장되는지 소스로 확인하지 못했다. `project_population`의 `response.meta[key]`도 같다(현재 `_response`가 항상 모든 키를 채우므로 실제 발생 가능성은 낮다). 권고: `REASONS` ⊇ `ReferenceReason ∪ (PublicSourceReason − {public_subset_only})`를 확인하는 테스트를 추가하고, assert/KeyError를 ValueError로 바꾼다.
- **N5 FE 계약 검사 범위와 테스트 근거.** `populationContractMatches`는 metric 모양(display/unit), non-partial source의 reason, partial↔`public_subset_only`를 확인하지 않는다(본문은 서버가 검증하므로 비차단). 제공된 FE 테스트(`AiPopulationInfo.test.tsx`)는 렌더링만 다룬다. `interpretationMatches`의 v1 필드없음 허용, v1 필드있음 거절, v2 필드없음 거절, 미지원 버전, as_of 불일치, 월 밖 관측일, 승인 플래그 true 거절 케이스가 FE185 안에 실제로 있는지 이 검토에서는 보지 못했다. 테스트 파일명과 케이스명을 기록할 것.
- **N6 테스트 강도(정보).** (a) 단위 `test_new_population_context_invalidates_ai_cache`는 `context_hash` 문자열만 바꾼다. 실제 digest 경로는 PostGIS 테스트가 덮는다. (b) `test_projection_rejects_mismatched_scope`는 `project_population`에 같은 query를 넘기므로 운영 경로에서 sub_category/radius 비교는 자기 일치 검사다. 실질적인 교차 검증은 `analysis_date == Risk T` 비교다. (c) deadline 통합 테스트는 monkeypatch로 LlmError를 던지며 실제 listener 시점을 재현하지 않는다(기존 listener 동작에 의존).

#### 기존 지적·Codex 처리 대조

- 이 MD §5에는 이번 구현에 대한 이전 Claude 지적이 없다. 이 검토가 initial이다.
- #182 설계 검토 두 번의 개별 지적 원문은 이번 입력에 없어서 항목별로 대조하지 못했다. 대신 사용자가 지정한 체크 목록(위 표)으로 구현을 대조했고, 모두 충족 또는 비차단이다.
- §3 마지막 문단의 Codex 처리(FE `interpretationMatches`의 v1 전용 조건을 v1/v2 분기로 수정)는 소스와 일치한다. 미지원 버전, v2의 인구 근거 부재, 날짜 불일치를 거절하는 것을 정적으로 확인했다(테스트 존재 여부는 N5).
- 이번 검토는 CI, 배포, 공개 검증, 실제 모델 호출, 브라우저 확인을 수행하거나 확인한 것이 아니다. §3/§4의 해당 행은 계속 미완료로 둔다.

### Codex 1차 권고 처리와 최종 재검토 입력

실제 초기검토는09:49:08Z~09:51:54Z exit0/is_error=false/3turns, MD 직접수정·제공source SHA보존·권한거부0으로 PASS였다.

- N1: #182의 명시적 결정대로 상태 안내에도 ID를 붙인다. 대신 근거 이름을 “공개자료 주야간 비교 상태”로 중립화했다. partial을 표시하는 정보창/보고서의 별도 구역에 서울시 생활인구250m 공개자료(R4)를 명시해 인허가 출처 줄과 구분했다.
- N2: 반올림된0.0%뿐 아니라100.0%도 반올림 표시라는 한 문장으로 설명한다. 실제0/정확한100과 구분하며 비중/배수를 재계산하지 않는다.
- N3: 기존 전역 숫자 whitelist가 인구 문맥으로 넓어지는 한계는 유지한다. 모델은ID만 고르고 인구문장은 별도 좁은근거로 검증한다. 이것을 사실정확도/필드별 의미검증으로 과장하지 않는다.
- N4: 사유 lookup·필수 metadata·관측일 부재를 명시 ValueError로 처리한다. 닫힌 사유 집합 일치·없는사유·메타키누락의거절 검사를 추가했다. assert/KeyError에 no-store를 기대하지 않는다.
- N5: `src/api/brands.test.ts`의 실제새검사에 기존v1/새v2·v2필드누락/미지원버전/다른날짜/이전관측월/승인true/v1신규evidence거절을 추가했다. FE188개+profile4개 통과다. FE는 metric 숫자 계산/포맷터를 복제하지 않으며 BE의 typed검증을 따른다.
- N6: 캐시 검사를 실제 인구projection 비중변경·canonicalcontext hash로 바꾸고 새비중75.0%와provider2호출을 확인한다. 별도 PostGIS는실제version metadata변경때 같은 outbound라도캐시miss를 확인한다. 실제SQL직전 listener에서worker stop을 감지해503·연결반환·provider0호출인 추가PostGIS 검사도 통과했다.

로컬 브라우저는실제복제DB→BE8003→FE5181·합성ID선택공급자다. 부분자료본문/동적안내·AI관측일·390/360overflow0·SPA보고서/PDF·유효no_data200·AI전송실패의핵심지표보존·pageerror0을 확인했다. 실제모델 호출과 구분하며 최초입력화면리다이렉트는QA URL에필수bk가없어생긴테스트설정문제였다. bk를기존실제주소문맥대로보존한뒤통과했다. Production/preview 실제build:vercel도통과했고production모의fixture제거/previewfixture유지를확인했다.

이후정확한최종head의CI와실제FE선배포·기존응답호환·BE배포·새모델/브라우저 검증을각PR/이슈에기록한다. 원래15개위치의정확도개선이나전체인구승인은주장하지않는다.

### 5.2 Claude Code 실제 정적 구현 검토 (final, 2026-11-16)

**판정: PASS. 차단 결함은 없다. 1차 지적 N1~N6은 모두 처리 또는 근거 있는 유지로 닫는다. 새 비차단 지적은 3건(F1~F3)이다.**

검토 범위와 한계: 이번 최종 요청에 들어 있던 BE 소스(`ai_population.py`, `ai_context.py`, `population_context.py`, `chain_context.py`, `narrative.py`, `interpretation.py`, chain `system.md`/`chain_version.py`, `builder.py`, `verifier.py`, `risk_interpret.py`, `population_reference.py`, `interpret.py`), `tests/test_ai_population.py`, `tests/integration/test_population_ai.py`, FE 소스(`interpretationContext.ts`, `aiPopulation.ts`, `AiPopulationInfo(.test).tsx`, `AiInfoPopover.tsx`, ReportPage `AiBlock`, messages/risk.ts 일부)만 정적으로 읽었다. 코드·테스트·shell·Git·DB·네트워크·브라우저는 실행하지 않았고 이 MD만 수정했다. 요청 메시지의 수치(AI407, BE2516+3skip, PostGIS312, FE185+4, ruff/mypy189, warm15 벤치마크)와 §3·§5 Codex 기록의 최종 수치(AI408, PostGIS 신규8, FE188+4)는 모두 Codex가 제공한 근거이며 재현하지 않았다. 두 숫자 세트가 다른 이유는 N4·N5 보완 테스트 추가로 보이지만, 이 검토로 확인한 사실은 아니다(F3). 원래 15개 위치의 정확도, 전체 생활인구 공식 승인, 배포 성공, 실제 LLM 호출, 브라우저 결과, prompt v2 SHA와 `system.md` 실제 바이트의 일치는 확인하지 않았고 주장하지 않는다. `src/api/brands.test.ts`, ReportPage `FooterBlock`, `PopulationModel`/`PublicSourceReason`/`SOURCES` 정의, 실제 `assemble_public_subset`는 이번 입력에 없었다.

#### 1차 지적·Codex 처리 대조

| 지적 | Codex 처리 | 정적 대조 결과 |
|---|---|---|
| N1 근거 칩·출처 | ID 유지(#182 결정), 칩 이름 중립화, partial일 때 R4 별도 표기 | 닫힘. `evidenceChip('population_public_subset')` 테스트가 `'공개자료 주야간 비교 상태'`·`target:null`을 고정한다. `AiPopulationInfo`는 partial이 하나라도 있을 때만 "서울시 생활인구 250m 격자 공개자료(R4)"를 인허가 출처 줄과 따로 보여준다. 이 컴포넌트를 Popover와 ReportPage `AiBlock`이 같이 쓰므로 보고서에도 같은 규칙이 적용된다. BE meta R4 조건(partial 존재)과 FE 표기 조건이 같다. FooterBlock 매핑은 소스로 보지 못했고, Codex의 로컬 브라우저 기록에 의존한다. |
| N2 반올림 100.0% | 0.0%/100.0% 반올림을 한 문장으로 설명 | 닫힘. `rounded and display in ("0.0%","100.0%")`일 때 "끝값도 반올림 표시값이며 정확한 영이나 전부를 뜻하지 않습니다"를 붙인다. 새 숫자는 넣지 않는다. 테스트 `("0.00001","100")`가 이 문장을 확인한다. |
| N3 전역 whitelist 확대 | 한계로 유지, 과장하지 않음 | 수용. 모델은 ID만 고르고 인구 문장은 날짜·local display만 담은 좁은 evidence로 먼저 검증한다(`test_sentence_is_verified_without_its_own_numbers_or_quality_counts`). 전역 검사를 필드별 의미 검증으로 쓰지 않는다는 Codex 기록도 맞다. |
| N4 예외 타입 | 명시적 ValueError와 닫힌 집합 테스트 | 닫힘. `_reason_text`(None/미지 사유), `VERSION_FIELDS` 누락, ready의 `observation_date` 부재가 모두 ValueError다. `_sentence`에 assert와 직접 `REASONS[...]`가 남아 있지 않다. `build_catalog` 단계의 ValueError는 `interpret_risk`에서 INTERNAL_ERROR+NO_STORE가 된다. `test_all_public_unavailable_reasons_have_closed_explanations`가 `REASONS == (PublicSourceReason ∪ ReferenceReason) − {public_subset_only}`, 없는 사유, `content_sha256` 누락을 확인한다. `local, long, short = context.sources` 언패킹은 ready에서 validator가 `SOURCES` 3개 순서를 보장하므로 안전하다. |
| N5 FE 계약 테스트 | `src/api/brands.test.ts`에 8개 거절·허용 케이스 추가 | Codex 기록으로 수용, 파일 자체는 보지 못함. 기록된 케이스(v1 필드없음 허용, v2 허용, v2 필드누락, 미지원 버전, 다른 날짜, 이전 관측월, 승인 true, v1+새 evidence 거절)는 `populationContractMatches`의 분기와 하나씩 대응한다. 정적으로 보면 각 분기가 기대대로 false/true를 돌려준다. metric 모양을 FE가 다시 검사하지 않는 것은 BE strict validator에 맡기는 결정으로 수용한다. |
| N6 테스트 강도 | 캐시 단위 검사 강화, 실제 SQL listener 검사 추가 | 닫힘. (a) 단위 캐시 검사는 `projected(day="3")`로 실제 projection을 바꾸고 `serialize_context`로 canonical `context_hash`를 다시 계산한다. 그다음 `75.0%`와 `provider.calls == 2`를 확인한다. (b) scope 교차 검증의 실질은 `analysis_date == Risk T`라는 1차 판단을 유지한다. 운영 경로의 query는 같은 `checked`에서 만든다. (c) `test_real_sql_listener_checks_worker_stop_during_population_lookup`는 원래 `get_population_reference` 호출 직전에 `stop`만 세운다. 그러면 첫 SQL의 실제 `before_cursor_execute` listener가 LlmError(TIMEOUT)를 낸다. 이 예외는 서비스의 ValueError/TypeError/OverflowError catch와 `prepare_chain`의 catch를 지나 `interpret_risk`에서 503이 된다. 테스트는 이와 함께 `reached`, `provider.calls == 0`, `pool.checkedout() == 0`도 확인한다. 기존 monkeypatch deadline 케이스는 보조로 남는다. |

#### 최종 체크 항목 재확인 (1차 표에서 바뀐 부분만)

- outbound 투영·식별자 없음·RR/6필드/관측월·원천별 독립 계산·4그룹 ID 선택·v1 불변·Risk 유리/불리에 partial 미포함·캐시 rule v2와 digest·deadline/오류 상태: 1차 판단(충족)을 유지한다. 1차 이후 바뀐 소스는 위 N1/N2/N4/N6 처리 범위 안에 있다. 이 변경으로 outbound 키, 숫자 출처, 문단 구조가 넓어지지 않았다.
- 인구 문장 자체 검증: 새 N2 문장과 ValueError 경로 모두 숫자를 추가하지 않는다. 날짜 표기 `07`은 Decimal 7로 evidence와 맞는다. 외국인 원천 두 문장은 접두("장기체류"/"단기체류")가 달라 REPETITION 검사에 걸리지 않는다. 통합 테스트의 `["partial","no_data","no_data"]` 경로가 이를 덮는다.
- 서술 정합: 내국인 수치만 나오고, 외국인은 상태만 나온다. `display None`은 "합이 모두 영", 정확한 0.0%는 그대로 표시, 반올림 끝값은 보조 문장으로 처리한다. 유효 pending/no_data/not_supported는 "%" 없는 문장이 되고 테스트로 고정되어 있다.
- FE OLD/NEW: v1은 `population_reference === undefined`일 때만, v2는 typed 계약일 때만 허용하고, 그 밖의 버전은 거절한다. Popover와 보고서 문구는 population 유무로 old/new가 바뀐다. 보고서는 POST evidence의 분석일·관측일을 쓴다. 따라서 FE 선배포(기존 v1 BE 응답 호환)와 BE 선복구(이전 FE가 v2를 거절) 순서가 계속 맞다.
- 범위: 신규 키, migration 0013, DDL/적재가 없다. 승인 플래그 3개는 BE Literal False와 FE false 검사로 고정되어 있다. 전체 생활인구는 미확정 문구가 유지된다. 원천 공식 검증은 계속 unverified다.

#### 새 비차단 지적 (최종; 배포 차단 아님)

- **F1 `preparation.replace` 무음 실패 가능성.** v2의 "전체 생활인구와 매출의 적용 기준…" 치환은 `str.replace`라서 원문 문구가 나중에 바뀌면 조용히 no-op이 된다. 그러면 v2 본문에 이전 v1 문구가 남는다. 숫자나 승인 주장이 생기지는 않으므로 차단은 아니다. 권고: 치환 전에 포함 여부를 확인하고 없으면 ValueError를 내거나, v2 본문에 새 문구가 있는지 단위 테스트로 고정한다(기존 테스트에 이미 있다면 테스트 이름을 기록).
- **F2 100.0% 반올림 여부의 상류 의존.** `ContextPopulationMetric` validator는 0 표시만 exact/rounded 조합을 강제하고, `100.0%`가 정확한 전부인지 반올림인지는 상류 `rounded` 값에 맡긴다. 상류 계산(`assemble_public_subset`)은 이번 입력에 없어 확인하지 못했다. 정보 기록용이다.
- **F3 검사 수치 표기 일관성.** 요청 메시지의 수치(AI407, FE185+4)와 §3/§5의 최종 수치(AI408, FE188+4, PostGIS 신규8)가 다르다. 최종 head PR/이슈에는 정확한 commit에서 실제로 실행한 개수 한 세트만 적고, 사전 수치와 구분할 것. `AiPopulationInfo.test.tsx`의 ready fixture(원천 2개, partial인데 `metrics:null`)는 BE 계약상 나올 수 없는 렌더 전용 형태다. FE 계약 거절 테스트(`brands.test.ts`)와 혼동하지 않도록 기록해 둘 것.

#### 결론과 남은 미완료

- 정적 대조 결과, 이번 구현은 #182 설계 범위와 사용자 체크 목록을 충족한다. 1차 지적 N1~N6의 Codex 처리도 제공된 소스와 일치한다(N5는 테스트 파일을 보지 못해 Codex 기록에 의존한다). 최종 판정은 **PASS**다.
- 이 검토는 CI, FE/BE 배포, 공개 도메인 확인, 실제 모델 호출(partial/no_data 각 1회 이내), 모바일·PDF 브라우저 확인, 복구 실행을 수행하거나 확인한 것이 아니다. §3의 "CI/배포/공개검증" 행과 §4의 2~5단계는 실제 결과가 PR/이슈에 기록될 때까지 미완료로 둔다. 전체 생활인구 공식 근거는 계속 미검증이다.

### 5.3 Codex 최종 대조

최종실제검토는09:57:29Z~09:59:04Z exit0/is_error=false/3turns·MD수정·제공source SHA보존·권한거부0으로 PASS였다. N1~N6의 처리에는 이견이 없다. F1은 `test_v2_actual_render_provider_payload_and_source_meta`에 v2의 새 고정 문장이 반드시 존재한다는 회귀로 고정했다. F2는 기존 `_number`의 정확한 유리수 반올림/상보비중과 상류 단위검사·projected helper 대조를 따른다. F3의 FE 렌더 fixture는 실제계약의3원천·partial metrics·quality로 수정하고 R4 표기도검사한다. 해당 테스트상세보완을 Claude가 다시검토했다고표시하지않는다.

이번 최종head의새검사숫자와원격CI는 각PR기록을따른다. 초기407/185, 보완408/188·새PostGIS8 및 전체회귀312(마지막추가전)는실행단계가다른이력이다. 공개배포/모델/브라우저는실제성공기록전까지미완료다.
