# 브랜드 필터를 유지하는 BE v2 AI 해석

이슈 #147, 기준 develop42811e9. 사용자 지시는 다음 BE 작업 구현·검증, FE 수정 금지다. #145의 v2 Risk/활동/이력과 브랜드 publication을 AI까지 연결한다. migration/head0012·원본/운영 DB·기존 서버·.env·FE·Render 배포는 변경하지 않는다. 가맹·직영·소규모 체인을 포함하지만 실제 운영 형태/비체인/과거 소속 확정은 주장하지 않는다.

## 1. 요청과 범위

`POST /api/v2/risk/interpret`는 `{query: ChainRiskQuery, history?: {building_key,floor_unit?}}`만 받는다. 독립 strict request 모델로 v1 franchise/include_unknown*·클라이언트 수치/해석/context·중복 JSON 키·NaN·과대 body·query string을 DB와 모델 호출 전에422로 거절한다. 기존 strict_body/InterpretRoute를 공유한다. scope≠all의 brand_unknown 필수 규칙과 기존 history 정규화/300m 위치 확인을 유지한다.

v1 요청·응답/프롬프트 v9·Risk 캐시 규칙은 유지한다. v2는 별도 프롬프트 chain-risk-interpret-v1과 선택 캐시 namespace/rule을 사용한다. 예산·rate limiter·gate·singleflight와 모델 client는 동일 InterpretationResources를 공유해 경로별로 한도를 우회하지 못하게 한다.

## 2. 재계산·일관성

새 `app.ai.chain_context`가 READ ONLY REPEATABLE READ 세션 안에서 ChainSelection을 한 번 읽는다. 같은 객체를 get_risk/get_activity/get_history의 명시 chain 인자로 전달한다. v2 Risk 수치 캐시는 사용하지 않는다. history는 브랜드/면적/시점 필터 없이 전체 지원 이력을 재계산하고, 선택 건물 위치를 기존 check_history_location으로 검증한다.

각 결과의 날짜·source·이름 제외 정책·배치 집합/map/rule·분모·필터 echo·표본·방법을 검증한다. 활동의 영업 수=competitor, 폐업+영업=closure denominator, 최근 기간·2010년 이상 YTD·history 최신 자료 기준을 대조한다. 기존 `_indicator`, `_activity`, `_history`의 수치 검증을 재사용하되 브랜드 메타 키만 선택 인자로 구분한다. v1을 위한 fake franchise=all 문맥/가맹 추정 상태를 만들어 검증기를 통과시키지 않는다. 내부 기존 서비스 호출용 legacy query 변환은 #145의 공통 계산 어댑터로만 사용하고 최종 문맥/echo는 실제 v2 필터다.

서비스 계산 결과에 같은 Selection의 `brand_classification` 메타를 붙여 검증한다. v1 brand_mapping/franchise_classification 메타가 남으면 v2에서 실패한다. 날짜·코호트·세대/근거 상태가 어긋나거나 trigger 손상/DB 오류이면500/no-store로 종료하며 모델에 보내지 않는다.

### 2.1 설계 검수 보정(구현 필수)

- **Selection 1회 로드·history 필터 분리**: `ChainSelection.load(session, chain_query)`는 세션의 첫 업무 SQL 묶음에서 한 번만 호출한다. Risk/활동에는 그 객체를 그대로 넘기고, history에는 `dataclasses.replace(selection, query=None)`(같은 publication/drift, predicate=true)만 넘긴다. 같은 객체를 history에 넘겨 브랜드 predicate가 이력 모집단을 줄이는 것을 금지한다. 회귀: 같은 위치에서 brand_scope/evidence/unknown 조합을 바꿔도 history total·분해가 동일해야 한다.
- **snapshot token**: v2는 Risk 수치 캐시를 쓰지 않지만 선택 캐시를 위해 cache 활성 시 Selection 로드 전에 `snapshot_token(session, cache)`를 같은 RR 세션에서 얻는다. token이 없으면 선택 캐시 key를 만들지 않는다.
- **메타 검증 매개변수화**: 현재 `_extract_context`는 `franchise_classification` 정확 일치·`_DataVersion.brand_mapping`·`ContextMethodology` 전체 dump 비교를, `_activity`/`_history`는 `franchise_classification`·`brand_mapping` 키 존재/일치를 하드코딩한다. 이를 v2에서 그대로 호출하면 키 부재로 항상 실패하거나, 반대로 v2 메타를 넣으면 v1이 깨진다. 수치/기간/분모/배치 검증부만 공통 helper로 분리하고, 브랜드 메타 비교는 `(key, expected)` 인자로 받는다. v1 호출 결과·예외 경로는 바이트 단위로 유지(기존 v1 테스트 무수정 통과)한다. v2 rule_version/data_version 모델은 #145 모듈의 상수를 import해 쓰고 리터럴을 복제하지 않는다. 세 결과(Risk/활동/history)의 `brand_classification`이 Selection.meta()와 모두 같아야 하며 generation/source_drift 불일치는 500이다. (코드 검수 정정) 구현 `_brand_meta`는 서비스가 `brand_classification`을 내보내면 Selection.meta()와 정확 일치를 요구하고, 내보내지 않으면 같은 Selection 객체에서 주입한다. 이 경우 세 결과의 일치는 메타 비교가 아니라 "같은 객체를 세 서비스에 전달"이라는 구조적 보장이며, 이후 `_activity`/`_history`의 해당 키 비교는 동어반복이다. 서비스가 메타를 내보내도록 바뀌면 주입 분기는 제거 대상이다. `franchise_classification`·`data_version.brand_mapping` 존재는 항상 500이다.
- **방법론 한계**: v2 `ContextMethodology` 한계 목록은 v1의 `franchise_name_match_not_contract_or_history`를 넣지 않고 #145 meta의 `limitations`(estimated_membership_not_contract 등)를 별도 `ContextChainClassification.limitations` enum으로 옮긴다. Risk meta의 methodology 비교도 v2 기대값으로 대조한다.
- **confirmed_only**: 현재 capabilities.confirmed_chain=false이므로 scope=chain·confirmed_only·unknown=exclude는 항상 0건이다. 서버 문장은 "확인 자료가 아직 없어 0건"임을 명시하고 체인 부재·비체인으로 서술하지 않는다(pending 0건과 같은 규칙).

## 3. 외부 전송 allowlist

별도 frozen·strict `ChainRiskInterpretContext`와 `ContextChainFilters/Classification`을 만든다. 공통 수치 모델은 공유하지만 기존 가맹 필드는 상속/출력하지 않는다. category/sub_category/radius/as_of/data_updated_at, 실제 v2 필터, 검증 지표·활동·이력·근접 기록 집계와 브랜드 준비/추정·drift·기준년도/월·한계만 허용한다.

brand 소속은 observed_record, historical_membership=not_verified, operation_type=unknown, coverage=partial, policy=franchised_direct_small_chains다. pending의 엄격 체인0건을 실제 체인 부재로 설명하지 않으며 non_chain/include를 독립 점포 확정으로 부르지 않는다. confirmed_only는 추정을 필터상 미확인으로 취급하되 가맹/직영 확인 자료가 생긴 것으로 표현하지 않는다.

브랜드 시점 정보는 catalog_year(정수)·semas_month(YYYY-MM)만 허용하고 `published_at`/`semas_observed_at` 타임스탬프는 넣지 않는다. 서버 문장에 쓰는 연·월 숫자는 verifier의 숫자 근거 검사를 통과하도록 같은 표기로 문맥에 존재해야 한다. 원문 주소/이름/인허가/좌표/건물키/호수·개별 브랜드명/key·generation·snapshot/input hash·내부 publication fingerprint/registry·raw SEMAS ID는 LLM/context evidence에 넣지 않는다. history 계산 결과의 행별 `ChainBrand`(brand_key/name)는 집계에서 버리며 문맥으로 투영하지 않는다. forbidden keys 보강 대상: `generation`, `brand_key`, `brand_name`, `fingerprint`, `snapshot_hash`, `input_hash`, `published_at`, `semas_observed_at` 및 SEMAS 원천 ID 키. 문맥 키에 기존 금지어 `query`/`name`을 쓰지 않는다. 내부 data_version_hash는 배치/규칙·publication generation/fingerprint·원천 revision을 포함한 서버 digest이며 원재료는 외부 전송하지 않는다. 공개 응답 meta에는 #145의 허용 브랜드 상태/필터/세대 메타를 별도로 줄 수 있지만 evidence/prompt에는 넣지 않는다. payload 빌더의 forbidden keys도 내부 publication 식별자에 대해 보강한다.

## 4. 프롬프트·서버 문장

독립 packaged `chain_interpret` 프롬프트는 기존 후보 ID 선택/숫자 검증/4문단 규칙을 유지하고 브랜드 정책을 명시한다. loader/builder는 선택 bundle을 받되 v1 기본은 그대로다. 문맥 준비와 최종 후보 요청이 같은 bundle version/sha를 써야 한다. 현재 `risk_interpret.interpret_risk`는 `build_interpret_request(payload, ...)`를 bundle 없이 호출해 v1 bundle을 쓰므로, v2 Prepared 객체가 bundle을 보유하고 최종 요청에 그 bundle을 명시 전달한다(재로드 금지). v2 bundle의 지문 이력/패키지 포함 검사를 v1과 별도로 추가한다.

공통 catalog/narrative/render는 두 typed 문맥의 합집합을 받는다(`PreparedRiskInterpretation.context` 타입도 합집합 또는 v2 전용 Prepared). 현재 `build_catalog`의 가맹 missing은 `c.franchise_classification`에 직접 접근하므로 문맥 종류로 분기한다. 가맹 관련 missing 문장만 문맥 종류로 분기하고, v2 본문에도 서버가 만든 조건/추정·관측 시점 한계 문장을 넣는다. 4문단 그룹 수·selection schema는 바꾸지 않고 브랜드 조건 문장은 서버가 1문단(조건) 또는 4문단(준비) 텍스트와 missing_data에 결정적으로 넣는다. 수치·자유 서술은 모델이 생성하지 않고 기존 서버 후보에서 구역별 ID만 선택하게 한다. model 선택 결과와 현재 catalog를 재검증하고 body/paragraphs/used_indicator_ids/evidence를 기존 형식으로 반환한다.

## 5. 캐시·취소·개인정보

매 요청을 먼저 DB에서 재계산·검증한다. v2 선택 캐시는 별도 namespace/rule + read-only primary snapshot token + 정규화한 v2 query 부분(좌표/반경/업종/면적·brand_scope/evidence/unknown/as_of; v1 `query_parts`는 RiskQuery 전용이라 v2 전용 함수 필요) + data_version/context/prompt hash + provider/model/token/schema/payload를 묶는다. #98 규칙대로 history의 building_key/floor_unit 원문은 key에 넣지 않고 집계가 반영된 context_hash/payload로만 구분한다. key 접두는 `cache.key("ai", CHAIN_SELECTION_CACHE_RULE, ...)`로 v1 규칙 문자열과 다르게 한다(같은 ai LRU의 bytes 상한은 공유되므로 v1/v2 상호 축출은 허용·문서화). publication 또는 원천/필터/시점/문맥이 바뀌면 미스다. v1 키·프롬프트·선택과 섞지 않는다. 저장 값은 ID 선택과 model만이고 응답/집계/주소/문맥·원문을 저장하지 않는다. hit도 현재 catalog에 대조하고 현재 근거로 다시 렌더링한다.

v2 라우터는 새 InterpretationResources를 만들지 않고 `request.app.state.interpretation` 동일 인스턴스를 쓴다(limiter/gate/flights 공유 회귀 필수). ChainSelection의 AppError(500)와 위치 AppError(422)는 ValueError로 바꾸지 않고 그대로 전파한다. 동일 자원을 쓰므로 기존 한도5회/분·50회/일·동시2와 전체20초 예산·재생성 최대1회·취소 후 지연 쓰기 차단을 유지한다. 키·DB URL·원문 요청·모델 payload를 로그에 남기지 않는다. v2 경로만 운영 로그 allowlist에 추가한다. 재시도/새 외부 수집은 추가하지 않는다.

## 6. 검증·완료 기준

- 기존 v1 일반1920/PostGIS278 회귀와 strict schema·loader·prompt package/type/format 검사.
- v2 정상/pending/strict0/non_chain/confirmed_only/과거/drift/행 변경·미지원/legacy422·query/JSON 중복·클라이언트 수치 거절·이력 범위/위치 불일치·준비/DB 실패 시 provider0회.
- 실제 publication fixture의 같은 조건 Risk/활동/AI 지표·날짜·수 일치와 공개/prompt 원문 비노출, 잘못된 수치/다른 metadata 주입 시 모델 호출 전500.
- 캐시 재사용·namespace 격리·조건/시점/세대/revision 변경 미스·현재 catalog 검증·한도/gate 공유·timeout/재생성·취소와 부분 응답 부재.
- 기존 격리 복제 DB689440행/검증 publication 재사용, 실제 자료의 대표 카페/음식점·기본3초 SQL·고정 응답 테스트 provider와 기존 실제 모델의 제한적 생성 검증. 키/비밀값을 출력하지 않고 집계/상태만 기록한다. FE·기존 서버/운영 DB는 변경하지 않는다.
- 실제 Claude Code 설계 Read/Edit 검수 뒤 구현, 코드 검수/필요 수정/재검증, BE PR·CI/CodeQL 확인 후 develop Squash 병합. FE 요청 문서는 BE에만 추가한다.

## 7. 실제 검수·검증 기록

설계 검수와 구현 후 실제 결과를 순서대로 기록한다. 설계 PASS를 구현 완료로 표시하지 않는다.

### 7.1 실제 Claude Code 설계 검수 (2026-11-15)

범위: 이 MD의 Read/Edit만 수행했다. 함께 제공된 `app/ai/context.py`, `app/services/risk_interpret.py`, `app/schemas/ai_context.py`, `app/ai/interpretation.py`, `app/ai/narrative.py`, `app/routers/interpret.py`, `app/ai/prompts/builder.py`, `app/services/chains.py` 본문을 대조했다. 셸/DB/테스트/git/네트워크는 실행하지 않았으므로 테스트 통과·권한·FE/배포를 주장하지 않는다.

발견한 구체적 차단 요소와 반영(2.1·3·4·5절에 직접 수정):

1. 같은 Selection 객체를 history에 넘기면 `predicate()`가 이력 모집단을 브랜드로 줄일 수 있음 → history는 `replace(query=None)`, 필터 조합 불변 회귀 추가.
2. `_extract_context/_activity/_history`가 `franchise_classification`/`brand_mapping`/v1 methodology를 하드코딩해 v2에서 재사용 불가 → 브랜드 메타 비교 매개변수화, v1 동작 불변, #145 상수 import.
3. `interpret_risk`가 bundle 없이 `build_interpret_request`를 호출해 v1 프롬프트로 요청될 위험 → Prepared가 bundle 보유·명시 전달, 별도 지문 검사.
4. 캐시 key에 history 원문 포함 문구가 #98 규칙(건물키/층호 key 금지)과 충돌 → 집계 hash로만 구분, v2 전용 query parts, 규칙 문자열 분리.
5. v2는 Risk 캐시 미사용이라 snapshot token 획득 경로가 사라짐 → 별도 획득 명시.
6. `build_catalog`의 `c.franchise_classification` 직접 접근, verifier 숫자 근거 검사와 연·월 표기, forbidden keys 목록·타임스탬프 제외, confirmed_only 상시0건 서술, 자원 인스턴스 공유와 AppError 전파를 명시.

판정: **설계 PASS(위 보정 반영 조건)**. 구현·테스트·실제 DB/모델 검증은 아직 수행되지 않았으며 코드 단계 PASS는 별도 증거 후 판단한다.

### 7.2 실제 Claude Code 구현 검수 (2026-11-15)

범위: 이 MD의 Read/Edit만 수행했다. 제공된 `app/ai/context.py`, `app/ai/chain_context.py`, `app/services/risk_interpret.py`, `app/schemas/ai_context.py`, `app/schemas/chain_interpret.py`, `app/routers/chain_interpret.py`, `app/ai/interpretation.py`, `app/ai/narrative.py`, `app/ai/prompts/{builder,loader}.py`, `chain_interpret/{system,user}.md`, `app/services/chains.py`, `tests/ai/test_chain_interpret.py`, `tests/integration/test_chain_interpret.py` 본문과 Codex가 보고한 실행 결과를 대조했다. 셸/DB/테스트/git/네트워크는 실행하지 않았고, 아래 수치는 Codex 보고값이며 직접 재현한 것이 아니다. `chain_notices.py`, `app/core/operations.py`, `chain_version.py`, `app/main.py` 라우터 등록, `get_risk/get_activity/get_history`의 chain 인자 구현은 본문이 제공되지 않아 검수하지 못했다.

설계 PASS 조건 대조(충족 확인):

1. Selection 1회 로드, Risk/활동은 같은 객체, history는 `replace(chain, query=None)`. 통합 테스트가 12개 필터 조합에서 history total12·same_spot8 불변을 검사한다.
2. snapshot token은 Selection 로드 전 같은 RR 세션에서 획득하고, 없으면 선택 캐시 key를 만들지 않는다(`prepared.snapshot_token is not None`).
3. v1 `_activity`/`_history`는 `classification_key` 기본값으로 동작이 그대로이고, `_extract_context`는 수정되지 않았다. v2는 별도 `_checked_risk`로 기대 메타를 대조하며 `brand_mapping` 존재를 거절한다. 비공개 version hash는 `serialize_context`가 아닌 별도 canonical JSON으로 계산해 v1 hash 바이트를 유지한다(Codex 보고의 회귀 수정과 일치).
4. Prepared가 chain bundle을 보유하고 최종 요청에 명시 전달하며, version/sha 불일치는 모델 호출 전 500이다(테스트 존재).
5. 캐시 key는 `CHAIN_SELECTION_CACHE_RULE`·`chain_query_parts`(HMAC 대상, 건물키/층호 미포함)·비공개 data_version hash(generation/fingerprint/revision/drift 포함)로 v1과 분리된다. 값은 selection·model만 저장하고 hit도 현재 catalog로 재검증한다.
6. 라우터는 `app.state.interpretation`을 공유하며 limiter·gate 공유 테스트가 있다. `AppError`(Selection 500·위치 422)는 `except (ValueError, ...)`에 잡히지 않고 전파된다(통합 테스트 422/500, provider0).
7. 외부 문맥에는 v1 가맹 필드·generation·published_at·semas_observed_at·brand_key/name이 없고 builder forbidden keys가 보강됐다.

차단 결함: **발견하지 못했다.** 코드 수정 없이 다음 비차단 사항을 기록한다.

- (정정 반영) `_brand_meta` 주입 의미를 2.1절에 바로잡았다. 현재 일치 보장은 구조적이며 메타 비교는 서비스가 메타를 낼 때만 유효하다.
- `semas_month`는 manifest 값이 6자리(YYYYMM)라고 가정해 YYYY-MM으로 변환하고, 그 밖의 형식은 500이다. #145 publication manifest의 실제 형식과 fixture에서 이 경로(None이 아닌 값)가 실행되는지 근거가 없다. 실제 복제 DB publication으로 estimate 응답이 200이고 `brand_classification.semas_month`가 기대값임을 기록해야 한다.
- 2.1절 confirmed_only "확인 자료가 아직 없어 0건" 문장은 `chain_notices.py`를 보지 못해 확인하지 못했다. 통합 테스트도 confirmed_only 조합에서 해당 문구를 검사하지 않으므로 단언 1개 추가를 권고한다.
- 운영 로그 allowlist의 v2 경로 추가(5절)는 `operations.py` 본문 미제공으로 확인하지 못했다.
- 복제 DB 실행의 캐시 hit 단언 실패는 무관한 쓰기로 primary snapshot token이 바뀐 보수적 miss라는 설명이 #74 규칙과 맞고 코드 완화가 없었다. 다만 hit 재사용 근거는 현재 합성/고정 token 테스트뿐이므로, 쓰기 없는 상태에서 같은 조건 2회 호출 시 provider1회를 실제 복제 DB에서 한 번 기록해야 한다.

검증 증거 상태(Codex 보고): 일반1941 통과(신규21), 추가 집중24 통과, PostGIS286 통과/skip0(기존278+신규8), ruff·mypy182 통과. **최종 일반1944 전체 재실행, 고정 응답 provider·기존 실제 모델 제한 생성은 진행 중이며 결과 미기록**이다. v2 프롬프트 SHA는 709c65d2…5787dc5로 보고됐다. 원본 DB·FE·.env·배포 변경 없음은 보고 기준이며 직접 확인하지 않았다.

판정: **정적 코드 검수 PASS(차단 결함 0)**, **구현 단계 최종 PASS는 보류**한다. 최종 일반1944 결과, 고정 provider/실제 모델 생성 결과, 실제 publication에서의 semas_month 경로와 쓰기 없는 캐시 hit 1회가 이 절에 기록되면 확정한다. PR·CI/CodeQL·병합·FE 반영은 이 판정에 포함되지 않는다.

### 7.3 Codex 최종 실제 검증과 재검수 입력

2026-11-15 실제 실행. 원본/운영 DB·.env·기존 서버·FE·Render를 변경하지 않았다. 기존 head0012 검증 복제 DB와 publication을 재사용했고 source689440행의 전 필드/좌표 포함 hash가 읽기 검증 전후 동일하다.

- 일반 전체1944개(기존1920+신규24), PostGIS 전체286개(기존278+신규8), 마지막 신규 통합8개 재실행 모두 통과했다. ruff check/format397파일·mypy182파일 통과. 기존 v1 테스트의 기대값은 변경하지 않았다. 공통 endpoint 집합과 #145 당시 v2 AI404 기대값만 신규 경로에 맞춰 갱신했다.
- 통합8개에는12조건 진리표/같은 조건 Risk·활동·AI 수 일치, history total12/same_spot8 불변, 과거 월말, pending0/drift, 새 publication의 같은 문맥·다른 비공개 버전 캐시 미스, 수치/세대/legacy/필터 변조500·provider0, 위치422/trigger500·provider0을 포함한다.
- 단위24개에는 독립 문맥/프롬프트·지문, v1/v2 캐시 분리, 현재 문맥 재렌더, 지문/스냅샷/자료 변경, 잘못된 캐시 폐기와 최대1회 재생성, 공유 limiter/gate, timeout 부분 응답/캐시 부재, 내부 ID 차단, JSON/입력 사전 거절을 포함한다. confirmed_only·chain·unknown=exclude 본문은 “확인 자료가 아직 없어 이 조건의 결과는 0건”을 명시하고 통합 단언/숫자 검증을 통과했다.
- 실제 복제 DB·고정 provider: 카페 chain18/음식점 chain21/음식점 non_chain(include)545/2020-02 chain18건. AI와 v2 Risk의 값이 같고4문단/숫자 검증 모두 통과했다. 건물 이력은4조건 모두9건으로 유지했다. 별도 외부 수집·새 publication·DB 쓰기는 없었다.
- 실제 publication 출처는 catalog_year2025, SEMAS manifest202609이며 외부 문맥의 semas_month=2026-09 변환 경로를 실제 응답에서 단언했다. 관측/공개 시각과 generation/개별 브랜드명·ID·주소·좌표는 LLM 문맥에 없다.
- 다른 DB의 통합 테스트 쓰기 중에는 pg_current_snapshot 변화로 캐시가 미스였고 규칙을 완화하지 않았다. 쓰기 종료 후 같은 복제 DB에서4조건+마지막 조건 재호출5건이 모두200, provider4회·실제 cache hit1회를 확인했다. 저장 값은 선택 ID/model만이고 재호출도 현재 문맥을 검증한다.
- 기존 실제 Gemini gemini-3.5-flash-lite 호출2건: 카페 chain18건6.844초/음식점 chain21건5.375초(해석+대조 GET 포함), 모두200·4문단·verification.passed=true·Risk 값 일치. 새 키/API/환경 변경 없이 기존 비밀 설정을 사용했고 값·프롬프트 원문을 로그/문서에 기록하지 않았다. 실모델 테스트는 캐시 재호출 없이2건으로 제한했다. 로컬 검증 결과이며 운영 배포/FE 표시 확인은 별도다.
- wheel을 외부 검증 폴더에 빌드하고 격리 import에서 v1/v2 프롬프트 자산·기록 지문이 모두 일치함을 확인했다. v1 SHA/버전v9는 유지하며 v2 SHA709c65d2a2dd789d5cd3ddc41acf931ac786eb33dcf85f98a8efb145f5787dc5를 별도 append-only 이력으로 고정했다.
- 초기 v1 회귀2건은 내부 버전 지문에 outbound 차단기를 적용한 것이 원인이었다. 같은 canonical JSON 바이트로 비공개 hash를 계산하고, 외부 전송 차단은 보강 상태로 유지해 전체 회귀를 통과했다.

검수 증빙: 설계 UTC18:30:56~18:32:37, exit0·denial0, 입력 MD SHA59b2b6fcb9111d824e69ba61bc183d2e1e756a413b9df6a9b51f3bc12db5395c→5a389006254d1224dd7aebdf1ec0e8b025b6ebf3764ab72ea00535f54d6c54c3. 구현 검수 UTC18:44:21~18:45:50, exit0·4turns·denial0, 입력5a389006…c54c3→595764a4cd565c7973d7cb11b606c20509784d6d29d71e6bd12a2f34594b46fb. 최종 실행 결과와 누락 소스(chain_notices/operations/chain_version/main 및 공통 서비스)도 제공해 재검수한다. 실행 주체는 Codex이고 Claude는 Read/Edit로 소스/보고를 대조한다.

### 7.4 최종 증거 대조와 추가 Claude 사용 한도

추가 Claude Code 재검수 시도는 UTC18:49:05~18:49:30, exit1·2turns·is_error=true·denial0으로 끝났다. 메시지는 `You've hit your 5-hour limit · resets 5:10am (Asia/Seoul)`이다. 입력/출력 MD SHA는 모두d09daa60d538fc1abe3c0fcf183f95363951075dd0d9704a509e0dd7769d90df로 수정되지 않았다. **추가 Claude 최종 PASS를 받았다고 표시하지 않는다.** 한도 우회·다른 계정/키·유료 한도 전환은 하지 않았다.

이미 실제 Claude 설계 검수와 정적 코드 검수는 수행했다(§7.1·§7.2, 차단 결함0). §7.2의 최종 보류 사유인 전체1944 검사·고정/실제 모델·기준월·쓰기 없는 캐시 재사용 증거는 §7.3에 실제 결과로 모두 보완했다. Codex가 누락됐던 소스와 마지막 confirmed_only 문장을 직접 재대조하고 해당 통합8개/전체1944개를 재실행했다. 내부 ID 미전송, 같은 Selection/이력 분리, 현재 집계 우선 검증, 프롬프트 bundle 고정, v1/v2 자원 공유와 캐시 분리, no-store/오류 전파를 확인했다. 추가 Claude 확인 자체는 미완료로 남기며, 검증 완료된 BE 코드에 대한 PR·CI/CodeQL 절차를 진행한다. FE·배포·원본/운영 DB 변경은 포함하지 않는다.
