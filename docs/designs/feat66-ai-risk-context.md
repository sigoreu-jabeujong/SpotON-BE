# BE-28 AI 해석용 Risk 집계 추출 (#66)

- 기준 develop `27e7c8a`, `feat#66-ai-risk-context`, 2026-11-12
- 상태: Codex 설계 → Claude 실제 MD 수정 → Codex 최종 점검·구현·로컬 검증 완료. CI 후 develop 일반 Squash 병합하며 실제 상태는 #66 연결 기록을 따른다.
- 이번 범위: 서버 재계산→명시적 허용 집계→불변 context/직렬화/해시→기존 프롬프트 준비. 실제 LLM 호출·공개 POST /api/risk/interpret는 후속이다.

## 1. 근거와 선행 조건

원본 API v1.2 §4-8(11쪽) 규칙25~29와 통합 작업계획8절은 클라이언트 지표를 신뢰하지 않고 서버가 Risk를 다시 계산하며 외부에는 집계만 전달하도록 한다. #64/PR65의 Risk 참고지표가 준비됐으므로 BE-28을 독립 진행한다. 브랜드57·공식 분기/경계·조건부 수치 대기를 가짜 숫자로 우회하지 않는다.

공개 준비 함수는 `(session, validated RiskQuery, settings)`만 받고 서버 get_risk를 호출한다. 사전 계산된 클라이언트 Risk/indicators/context를 입력받는 인자는 만들지 않는다. 순수 추출 함수는 내부 private로 두고 테스트한다. 향후 BE-32의 query-only 본문·이력/활동 요약은 별도 설계다. 이번에는 이력·상호·점포 정보를 조회하지 않는다.

## 2. 외부 허용 context

엄격한 Pydantic frozen 모델·tuple만 사용한다. context에는 아래만 명시 생성하며 raw `model_dump()` 결과/딕셔너리 merge/extra 키 전체를 복사하지 않는다.

- category/sub_category·radius_m·선택 area/franchise/독립 unknown 토글: 검증된 query의 enum/범위만
- as_of=T/data_updated_at=D·collected_at=null·collection_reason 고정 코드
- indicators: id/type/value/unit/numerator/denominator/seoul_avg/동일비교분모·상태/사유·source 배열·space·기간만. source_url/link/copy_text는 전부 제외한다.
- flags의 insufficient_sample/missing·market_status=unverified·franchise_classification=pending
- 방법론: 고정 개업 주년·기간 분모·최소표본10/5·반올림·좌표확보 서울 비교·불확실성/지위승계/과거 재구성 한계 고정 토큰

명시 제외: query 전체, lat/lng·주소/건물/층호·상호/license_no·market 전체/상권명/코드·spatial_candidate/geometry·UUID/배치ID/raw data_version/raw meta·URL/link/copy_text·자유 형식 프롬프트 문장. 반경은 집계 해석에 필요하므로 허용하지만 원 좌표/장소를 복원하는 값은 주지 않는다.

## 3. 필드 이름뿐 아니라 값도 제한

현재 Risk의 reason/seoul_avg_reason/period는 자유 string이라 단순 필드 추출만으로는 값에 섞인 주소/지시문을 막지 못한다. AI 모델은 id/type/status/source/space/reason을 명시 Literal/enum으로 제한한다. 사유는 현재 서버의 known codes만 허용하고 알 수 없는 값은 실패한다. 기간은 T와 지표 id에서 기존 달력 규칙으로 생성하고 기존 Risk period가 그 값과 일치하는지 확인한다. 문자열을 임의 정제/요약하여 통과시키지 않는다.

숫자는 유한·음수거절·정수 count/분모, 비율1자리/0~100, fact/소표본/분모/비교 불변식을 검증한다. 서버 재계산이 신뢰 경계이며 임의 객체의 `model_construct`나 재할당으로 검증을 우회한 값은 수용하지 않도록 전체 Risk와 query도 재검증한다. 값/분자/분모의 Decimal HALF_UP 일치도 확인하여 수치 필드에 정밀 좌표를 넣거나 수치를 바꾸는 경우 실패한다. source는 현행 지표별 R1/R2/R4/R5/R6 배열만 허용한다.

raw metadata는 전송하지 않는다. 필요한 D/T/수집일/방법론/rule_version은 알려진 타입/값을 검증하고 별도 필드로 만든다. 현재와 다른 rule_version/수집일 의미는 조용히 추정하지 않고 실패한다. map/batch provenance는 내부 data_version_hash로만 보존하며 외부 context에는 넣지 않는다.

## 4. 준비 결과·기존 모듈 연결

`PreparedRiskInterpretation`은 repr에서 context/request를 숨기는 frozen dataclass다. context는 nested frozen/tuple, request는 기존 frozen LlmRequest, context_hash=SHA256(기존 serialize_context의 정렬 JSON)이며 data_version_hash/prompt_version/prompt_sha256는 내부 메타다. 원본 context를 반환할 때마다 안전한 모델에서 새 JSON dict를 만들고 해시와 프롬프트 문자열은 같은 스냅샷으로 구성한다. 데이터버전/프롬프트 정보를 context_hash 하나로 대체해 캐시해도 된다고 주장하지 않는다. BE-34의 조건/버전 캐시는 후속이다.

기존 build_interpret_request/serialize_context의 금지 키 마지막 관문을 재사용한다. API/DB/LLM 호출은 이 준비 함수에서 추가하지 않으며 기존 읽기 전용 세션의 get_risk만 호출한다. 준비 실패는 원문/식별값/예외 context 없는 안전한 INTERNAL_ERROR다. AppError의 조회 오류는 기존대로 전파한다.

기존 프롬프트는 generic pending/no_data만 설명하므로 link_only/unverified·고정 주년 vs 현재잔존·좌표선택 비교 한계를 반영한다. 프롬프트 버전/지문 이력을 갱신하고 기존 packaging/버전 테스트를 통과시킨다. verifier의 unavailable 값 판정에도 link_only/unverified를 추가한다. 공식 안내만 있는 지표를 알려진 숫자/임의 등급으로 활성화하는 회귀를 막는다. 전체 AI 결과 스키마·숫자-지표 의미 검증·실제 공급자 검증 완료는 BE-32 후속이다.

새 app/ai/context.py와 내부 모델, tests/ai·격리 PostGIS 테스트·BE 문서가 주 대상이다. 기존 API/입력응답 형식·DB 모델/migration·의존성·Docker/.env·FE는 수정하지 않는다. 공개 계약 변경이 없어 이 단계의 새 FE 요청서는 만들지 않는다.

## 5. 검증·완료

일반: 실제 Risk 타입의 합성 출력에서 허용 키/값만 추출·표본/0/null/고정 주년 의미/요청항목 유지·서버 재계산 호출·동일직렬화/해시·입력/중첩불변성·날짜/산식/원문문자/타입/metadata 변조 차단·repr/오류/로그 비노출·prompt 버전/파일지문·link_only/unverified 값 차단.

차단용 합성 canary를 query 위치/가상 주소·market 후보/상권명/URL/UUID/raw meta 등 제외 경로에 넣어도 프롬프트에 나오지 않아야 한다. 허용 reason/period/source/숫자에 넣으면 거절한다. 예상 입력의 extra 키는 거절하며 raw meta의 비허용 키는 복사하지 않는다. 실제 비밀값을 테스트/LLM에 넣지 않는다.

격리 PostGIS: source준비/미준비·과거/빈/필터·명시 경계 후보·실제 READ ONLY 세션·두 다른 좌표라도 동일집계면 동일 context·Risk 데이터/준비분모 일치. 공급자 adapter는 httpx MockTransport 또는 FakeClient로 최종 전송 payload를 확인하고 외부 통신/키/실제 LLM은 사용하지 않는다.

실제 개발 DB: 5개 이상 조회조건의 재계산→허용context→프롬프트/해시·공급자 mock 확인, 기존 API 회귀·head0009/모델차이0·14테이블 전체 hash/건수 보존. 전체일반/격리PostGIS/ruff/format/mypy·실제비밀값 검사·CI/CodeQL 후 develop 일반 Squash 병합한다.

커밋: 설계/Claude검토→입력 모델/추출/준비+테스트→프롬프트/검증기 보정+회귀→실제검증/문서. PR `feat: AI 해석용 집계 추출과 식별정보 차단 구현`, close #66. 실제 외부 AI API·FE 통합·공식지표/브랜드 승인을 완료로 표시하지 않는다.

## 6. Claude 검토 요청

이 MD만 Read/Edit한다. 코드/다른문서/Git/DB/네트워크/.env 접근 금지. 허용 필드/값·클라이언트수치불신/서버재계산·상권/URL/metadata 유출·숫자/기간 검증·불변성/해시·link_only/방법론의 연결·과도한 스코프/누락 테스트를 검토하고 이유/보류를 직접 기록한다. 실제 코드/원본/DB를 읽지 않은 한계를 남긴다. 통상 선택은 최선안을 제시하고 Codex가 실제 코드와 최종 대조한다.

## 7. Claude 검토 결과 (2026-11-12)

검토 범위: 이 MD 한 파일만 Read/Edit했다. 코드·원본 API 문서·통합 작업계획·DB·Git 이력·네트워크는 보지 않았다. 아래 내용은 설계 문장의 내부 일관성과 일반적인 위험 패턴만 근거로 하며, 함수·모델·코드 이름(`get_risk`, `serialize_context`, `build_interpret_request`, `LlmRequest`, R1~R6, head0009, 14테이블 등)이 실제로 존재하는지와 의미는 확인하지 못했다. Codex가 실제 코드와 대조해 최종 판단한다.

### 7.1 유지 (타당하다고 본 결정)

- **서버 재계산만 신뢰하는 경계(§1)**: 준비 함수 인자를 `(session, RiskQuery, settings)`로 고정하고 사전 계산된 indicators/context 인자를 아예 두지 않는 방식이 "클라이언트 지표 불신"을 타입 수준에서 보장한다. 유지한다.
- **필드뿐 아니라 값까지 Literal/enum으로 제한하는 방식(§3)**: 자유 string(reason/period)에 주소나 지시문이 섞이는 경로를 정제하지 않고 거절하는 fail-closed 방식이 프롬프트 인젝션·유출 방지에 가장 확실하다. 유지한다.
- **raw metadata 미전송과 data_version_hash 내부 보존(§3)**: 재현성과 비노출을 둘 다 만족한다. 유지한다.
- **context_hash 하나로 캐시 키를 대체하지 않는다고 명시한 점(§4)**: 프롬프트/데이터 버전이 바뀌면 같은 context라도 결과가 달라지므로 맞는 판단이다.
- **verifier에 link_only/unverified 추가(§4)**: 기존 모듈 수정이지만 이를 빼면 공식 안내만 있는 지표가 숫자로 해석되는 회귀가 생기므로 이번 범위에 넣는 것이 맞다. 과도한 스코프로 보지 않는다.

### 7.2 보정 요청 (근거 포함)

1. **`area` 토글과 `space` 값 정의를 명확히 해야 한다(§2·§3).** §2는 "선택 area"를 허용하고 §2 제외 목록은 "상권명/코드"를 금지한다. area나 indicator의 space 값이 상권 코드/이름이면 두 문장이 충돌한다. → area/space는 `radius`·`market_polygon` 같은 **공간 유형 enum만** 허용하고, 상권 식별자는 어떤 경로로도 넣지 않는다고 명시할 것을 권고한다.
2. **reason/source Literal과 서버 코드 집합의 동기화 테스트가 필요하다(§3).** 알 수 없는 사유를 실패 처리하면, 이후 Risk에 사유 코드가 추가될 때 AI 준비 전체가 운영 중에 INTERNAL_ERROR로 깨진다. → Risk 쪽 known reason/source 집합과 AI Literal 집합이 같은지 확인하는 테스트를 추가해 드리프트를 CI에서 먼저 잡도록 한다. fail-closed 자체는 유지한다.
3. **bool/정수 혼동과 특수 부동소수 차단을 명시해야 한다(§3).** Python에서 `bool`은 `int`의 하위 타입이므로 strict 설정 없이는 `True`가 count=1로 통과할 수 있다. → count/분모는 `StrictInt`(또는 strict 모델)로 받고, NaN/Infinity/`-0.0` 거절 테스트를 §5에 넣는다.
4. **seoul_avg는 분자/분모가 없어 HALF_UP 대조가 적용되지 않는다(§3).** "수치 필드에 정밀 좌표 삽입 차단"은 분자/분모가 있는 value에만 성립한다. seoul_avg는 0~100·소수 1자리 범위 제한만 받으므로 정보량은 작지만, 문서에 이 차이를 적어 과대 보증을 피한다.
5. **소표본 지표의 숫자 노출 기준을 정해야 한다(§2).** 작은 반경에서 insufficient_sample인 분자(예: 폐업 1~4건)는 특정 점포 추정 단서가 될 수 있고, 외부 LLM 공급자는 공개 API 응답과 신뢰 범위가 다르다. → 권고안: 공개 Risk 응답이 이미 같은 숫자를 노출한다면 의미 일치를 위해 그대로 두되, insufficient_sample일 때는 프롬프트가 수치를 단정하지 못하도록 flag와 함께 전달한다. 공개 응답에서 이미 null 처리한다면 context도 null을 유지한다. Codex가 실제 Risk 동작을 보고 둘 중 하나로 확정한다.
6. **`as_of=T`의 출처를 고정해야 한다(§2·§4).** T가 요청 시각/서버 오늘 날짜라면 같은 데이터라도 날짜가 바뀔 때마다 context_hash가 달라지고, 테스트도 시계에 따라 흔들린다. → T는 데이터 기준일(또는 주입 가능한 clock)에서 결정하고 테스트에서는 고정값을 주입한다고 명시한다.
7. **직렬화 결정성 조건을 구체화해야 한다(§4).** "정렬 JSON"만으로는 float 표현, `ensure_ascii`, separators, tuple→list 변환, Decimal 처리 방식이 바뀌면 해시가 달라질 수 있다. → 기존 `serialize_context`의 옵션을 그대로 쓰는지 확인하고, 동일 입력의 dict 삽입 순서만 다르게 한 경우 해시가 같은지 테스트한다.
8. **`PreparedRiskInterpretation`의 dataclass 부작용(§4).** frozen dataclass라도 dict 필드가 있으면 `__hash__` 호출 시 TypeError가 나고, 기본 `__eq__`/`__str__`이 context를 비교하거나 노출할 수 있다. → `field(repr=False, compare=False)`처럼 repr뿐 아니라 eq/hash 대상에서도 context/request를 제외하고, `str()`/`f"{obj!r}"`/로그 포매팅 비노출 테스트를 함께 둔다.
9. **AppError 전파 경로의 메시지 점검(§4).** "조회 오류는 기존대로 전파"는 공개 엔드포인트가 없는 이번 단계에서는 위험이 낮다. 다만 후속 BE-32에서 AppError detail에 좌표/주소가 들어가면 그대로 새어 나갈 수 있으므로, 기존 AppError 메시지에 query 원문이 없는지 Codex가 확인하고 결과를 기록한다.

### 7.3 누락 테스트 보강 (§5에 추가 권고)

- franchise 토글이 unknown/pending일 때 브랜드명·브랜드57 관련 문자열이 context/프롬프트에 나오지 않음.
- radius_m가 허용 enum/범위 밖일 때 거절(좌표 소수부를 반경으로 위장하는 경로 차단).
- denominator=0 → value null, 분자 0 → 0.0 유지(0과 null 의미 구분).
- reason/source Literal ↔ 서버 코드 집합 동기화 테스트(7.2-2).
- StrictInt/bool/NaN/Infinity/-0.0 거절(7.2-3).
- dict 삽입 순서만 다른 동일 context의 해시 동일성(7.2-7).
- `str()`·`==`·`hash()`·로그 포매팅에서 context 비노출·예외 없음(7.2-8).

### 7.4 스코프 판단

- 실제 LLM 호출·공개 POST·BE-34 캐시·BE-32 결과 스키마를 후속으로 미룬 것은 적절하다. 추가로 줄일 부분은 없다.
- 실제 개발 DB 검증 중 "14테이블 전체 hash/건수 보존"은 읽기 전용 경로라 비용 대비 효과가 작을 수 있지만, READ ONLY 세션 보장을 실측으로 확인하는 의미가 있어 **보류 없이 유지**를 권고한다.

### 7.5 한계

- 실제 Risk 모델의 필드명·reason 코드 목록·period 달력 규칙·R1~R6 지표 대응·기존 `serialize_context` 금지 키 목록을 확인하지 못했다. 7.2의 1·5·6·7·9항은 모두 "실제 코드 동작에 따라 결정"이 필요하다.
- 원본 API v1.2 §4-8 규칙25~29의 원문을 대조하지 못했으므로 §1 근거 인용의 정확성은 검증하지 않았다.
- 보안상 판단(소표본 재식별 위험 등)은 일반 원칙에 따른 것이며, 실제 반경 범위와 데이터 밀도에 따른 정량 평가는 하지 않았다.

## 8. Codex 최종 점검

Claude 실제 MD 수정 diff 전체와 JSON(is_error=false,3 turns,permission_denials=[])을 읽었다. 서버 재계산·명시 필드/값 제한·typed 불변 입력·공급자 payload canary·직렬화 결정성·repr/eq/hash 비노출·link_only 값 차단은 채택한다. 실제 AppError는 고정 ERROR_SPECS 문구이며 조회 원문을 담지 않는 것을 확인했다.

코드를 읽지 않은 제안2개를 바로잡는다. area는 상권 식별자가 아니라 기존 **면적 구간** all/lt33/33to66/66to99/gte99이며 그대로 허용한다. space만 radius_300m/500m/1000m/market/grid enum이다. 현재 Risk는 seoul_numerator/seoul_denominator를 제공하므로 서울 비율도 Decimal HALF_UP으로 대조할 수 있다. 둘 다 원문/좌표가 되는 자유문자 경로를 만들지 않는다.

소표본은 현재 Risk대로 value/numerator=null·실제 denominator 유지로 확정한다. 원본 개별 점포/추정 가맹명·이슈번호/URL은 전달하지 않고 가맹 미확인 상태만 보존한다. T는 서버 Risk의 effective date이며 오늘 날짜/clock을 새로 쓰지 않는다. 직렬화는 기존 ensure_ascii=False/sort_keys=True/separators=(',',':')/allow_nan=False와 모델의 tuple→JSON list·date→ISO를 사용한다. raw query를 재검증할 때 변환 완료된 legacy include_unknown을 제외해 개별 플래그와의 충돌을 피한다.

dataclass의 context/request는 repr=False,compare=False,hash=False로 두고 내부 값 객체는 frozen/tuple로 고정한다. context_hash와 데이터/프롬프트 hash는 별개이며 실제 캐시를 구현하지 않는다. 기존 검증기는 알려진 숫자 집합/structured pending 검사 수준으로 지표 간 숫자 바꿔치기·자유문장 의미 전체를 보증하지 않는다. 이번 결과를 공개 AI API/실제 모델 안전성 검증 완료로 표시하지 않는다.

## 9. 구현·검증 결과 (2026-11-12)

- `app/ai/context.py`의 공개 `prepare_risk_interpretation(session,query,settings)`는 query를 재검증하고 서버 get_risk를 호출한다. 위치·상권 후보·raw meta/버전·URL을 제외한 `app/schemas/ai_context.py`의 명시 필드/값만 새로 구성한다. 원본 Risk/query를 다시 검증하고 사유/출처 enum·기간/공간·로컬/서울 비율·방법론/기준일을 대조한다. 검증 우회 객체의 직렬화 경고도 원문을 출력하지 않고 오류로 처리한다.
- nested frozen 모델/tuple, context/request repr·비교·hash 제외, 새 JSON 복사본·정렬 직렬화의 SHA256, 내부 data_version_hash/prompt_version/sha256를 구현했다. context_hash만으로 실제 캐시를 구현하거나 요청 조건/버전을 대체하지 않는다. 기존 AppError는 고정 코드를 전파하고 추출/프롬프트 실패는 원문/context 없는 안전한500이다.
- `risk-interpret-v2`와 실제 파일 지문을 이력에 추가했다. link_only/unverified·고정 개업 주년·현재 잔존과의 차이·서울/좌표 선택·가맹 미확인을 시스템 규칙에 반영하고 verifier의 미산정 값 차단에도 두 상태를 추가했다. 기존 v1 지문 이력은 보존했다.
- 새 일반 **26개**(입력 준비24·기존 검증기 보강2), 격리 통합 **4개**를 포함해 전체 일반 **1,018개**, 격리 PostGIS **115개** 통과. ruff check/format·mypy app/etl/migrations **123 files** 통과. 기존 Starlette/httpx deprecation 경고1건은 그대로다.
- 가상 식별 문자열을 raw meta/URL/버전/상권 후보에 넣어도 전송 본문에 없음을 확인했다. 허용 사유/기간/출처/정밀 숫자·NaN/Infinity/bool/음수0·잘못된 metadata/산식/반경·조회조건 불일치는 거절했다. 동일 집계의 다른 좌표·dict 삽입 순서에 같은 context_hash, 데이터 버전 변경 시 별도 hash 변경·deep 불변성·repr/str/hash 비노출을 확인했다. 처음 실패한 legacy query 동등성 테스트는 include_unknown 변환 후 개별 플래그의 의미를 비교하도록 바로잡았으며 구현 변경은 없었다.
- 격리 PostGIS는 실제 get_risk 재계산과 값/분모/상태/출처 일치, 과거 T·빈 업종·원천 미준비 구분, 이름이 있는 경계 후보/UUID 제외, READ ONLY·REPEATABLE READ를 확인했다. 공급자 어댑터는 httpx MockTransport와 합성 키/응답으로 실제 요청 JSON의 본문을 점검했으며 실제 키/외부 LLM은 사용하지 않았다.
- 실제 개발 DB **6조합**(두 업종/선택항목·과거월·다중 세부업종/반경·면적·가맹 미확인 제외의 빈 결과)에서 서버 재계산값·허용 입력·SHA256·최종 모의 공급자 본문·첫 생성 검증을 모두 대조했다. 명시 UUID 공간 후보가 있는 경우도 별도로 제외를 확인했다. 본문은 UTF-8 약2,821~3,543bytes였으며 본문/개별 원자료는 파일에 저장하지 않았다.
- 준비 시간 관측은 첫 요청 **5.995초**, 이후 **0.565~0.760초**였다. 최초 지연의 원인은 확정하지 않았으며 동시 통합 테스트가 실행 중이었다는 조건만 기록한다. 별도로 실제 history_session의 READ ONLY·REPEATABLE READ·문장3초 설정에서도 준비 **0.608초**와 정상 결과를 확인했다. 이는 콜드 캐시/동시부하·전체 AI API SLA 보장이 아니다.
- head0009·모델차이0·기존14테이블 전체 행/geometry hash·건수 동일을 확인했다. 개발 DB는 조회만 했고 파괴적 suite는 별도 임시 DB에서 실행했다. 기존 health/activity/risk 실제 앱/개발 DB 조회3개200·공개 /api/risk/interpret 미추가도 확인했다. 기존 API/모델/migration·의존성·원본·Docker/.env·FE 변경은 없다.
- 아직 실제 LLM/공개 AI API·전체 응답 스키마·자유문장 의미 검증·이력/활동 추가 문맥·캐시는 구현하지 않았다. 미확인 공식/조건부 지표와 브랜드57·FE 통합도 후속이다. 공개 계약 변경이 없어 이번 단계의 FE 요청서는 만들지 않았다.
