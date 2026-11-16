# 생활인구 공개자료 API·FE 실제 연결과 배포 (#180 / FE #73)

2026-11-16 사용자 최신 요청은 **API 구현·FE 수정·배포 진행**이다. [#178 설계](feat178-population-api-partial.md)의 설계 전용/FE 미수정 범위는 당시 작업이며 이번에는 두 저장소 구현·운영 반영이 승인됐다. 전체 인구에 대한 공식 가산성·부재·도형 적용일 검증과 별개인 공개 구성 참고 산술이다. 기존 AI 계약/프롬프트·DB0012/원문·로컬 환경파일·기존 서버·로그 Task/runtime은 유지한다.

## 1. 구현

- GET `/api/v2/population-reference`: 전용6개 입력(lat,lng,radius,category,sub_category,as_of), 구문 오류 DB 전422, 허용월은 기존 전역D/업종별 최소월로 검증한다.
- 같은 READ ONLY RR의 월내 최신 관측 버전·EPSG5179 source center 거리 선택·선택 행만 읽는다. 같은날 복수 버전 pending, 한도 초과 무절단, metadata 손상500/no-store다. HTTP/숫자 캐시를 추가하지 않는다.
- source별 U=(grid,admin) 당일 제공 후보, C=24시간 모두 observed인 동일 구성으로 고정한다. 비공개/누락이 있는 구성만 제외하고 다른 구성/원천은 유지한다. 그 집합의 D/N·비중·공개 원천값 합/평균과 명시된 품질을 제공한다. 원천을 합치거나 부족한 값을0으로 채우지 않는다.
- 기존 strict assembler는 그대로 두고 순수 `calculate_day_night`를 산술에 재사용한다. 숫자는 정확한 정수 scale/유리수 HALF_UP과 별도의50자리 Decimal 산술을 사용한다. 실제0·양수 반올림0·밤0/전체0을 분리한다.
- source/grid metadata SHA는 기록된 식별자이며 요청마다 원천 전체 hash를 재검사하지 않는다. source_validation_performed/population_total_validated/global_content_rechecked=false다. 결과 지문에 좌표·개별 구성은 포함하지 않고 FE query key를 대체하지 않는다.

## 2. FE 연결

FE `feat/73-population-reference`는 프로필과 무관한 새 경로/6개 입력 projection·canonical key·AbortSignal을 사용한다. 새 getter/hook·분석/종합진단 카드·인쇄 보고서·mock를 추가한다. 기존 v2 점포 mock 금지는 유지하고 인구 경로만 별도 허용한다. 기존 전체 생활인구 null 카드는 “전체 생활인구”로 구분하며 부분 숫자를 그 필드에 넣지 않는다.

원천별 제목/상태·분석일/관측일·같은 공개 구성의 배수/비중·사용/후보 구성 수·제외 패턴·한계를 함께 표시한다. 합/평균은 “인원수 아님” 상세 영역에만 보이고 숫자 문자열을 JS Number로 바꾸지 않는다. local 부재를 외국인 값으로 대체하지 않는다. 오류는 선택 인구 블록 안에서 처리하며 기존 점포/AI 요청을 차단하지 않는다. 보고서는 같은6개 요청의 hook/응답을 사용하고 기존 AI는 인구를 해석하지 않는다.

## 3. 현재 검증 근거

| 검증 | 확인한 범위 |
|---|---|
| 새 BE 단위/라우터 | 초기44통과, 최종 추가 사례는 아래5.2/5.4절을 따른다. 고정 구성/source 독립, 0/null/반올림/중복/잘못된 값, 422-before-DB, 응답/OpenAPI/no-store |
| 새 실제 PostGIS | 7통과. importer 원천→실제 공간조회/응답, foreign 비공개에도 local 제공, 전역 관측 COUNT 없음, 과거/미래/빈 반경, 복수버전/상한/metadata 손상, RR와 다음 요청 변경 |
| FE 단위 | 초기176통과+배포 profile4통과, 최종178+4를 확인했다. 새 표시 JSX 테스트도 실제 수집하도록 Vitest include를 추가했다. 타입·lint 수정 후 전체 검사를 다시 기록한다 |
| 운영 READ ONLY 사전 조회 | 기존0012, 관측1버전(2026-11-07)/531,922행, 격자1버전/10,125개, API 역할SELECT 확인. 데이터/권한을 바꾸지 않음 |
| 새 코드→운영 자료 READ ONLY | 실제 reader 역할/TLS로 새 TestClient에서21건. 별도5개 지점×반경300/500/1000=15표본의3원천 모두partial, 기존v2 Risk/activity6건200. 인구 조회 최장3.656초(검증 PC 왕복 포함). **공개 endpoint 배포 성공은 아님** |

전달받은 “15개 중2개”의 원래 좌표 집합은 확보하지 않았으므로 같은15곳의 개선율로 쓰지 않는다. 이번 표본에서 숫자가 나오는 것을 전체 지역의 대표성/모집단 완전성·공식 근거로 해석하지 않는다. 실제 수치/개별 위치/DB URI·키·기관 원문은 저장소/Claude 입력에서 제외한다.

## 4. 배포와 복구 계획

1. 현재 로컬 DB의 새 snapshot dump→별도 random 이름 DB 실제 복원→전체 표 건수/row hash·원본 보존 비교 후 새 코드를 확인한다. 실제 테스트DB 외 원본에는DML/DDL하지 않는다.
2. BE 전체 기존 테스트/새 PostGIS·ruff/format/mypy, FE lint/format/test/production·preview build, 실제 브라우저 모바일/요청/보고서/오류를 검증한다. Claude Code 실제 정적 코드 검토와 Codex 대조를 남긴다.
3. 검증 head의 정상 CI/CodeQL 후 BE develop 일반 squash. Render Free 기존서비스/17환경값 hash·head0012·기존 LLM/CORS/풀/auto-deploy off를 보존하고 정확한 merge commit만 수동 배포한다. 새 리소스/유료플랜/DB migration은 없다.
4. 실제 새 API/기존 점포·Risk/활동/CORS/ready를 확인한 뒤 FE develop 및 main release PR을 정상 병합한다. 최신 FE 배포 문서상 Production Branch는main이다. Vercel production=v2/preview=v1 설정과 브라우저 공개키를 유지한다. 배포가 자동 발생한 경우 중복 생성하지 않는다.
5. 운영 FE에서 실제 새 API 요청/부분 카드·원천별 결측·보고서/모바일을 확인하고 실제 BE/FE commit/deployment ID와 결과를 기록한다. 실패 시 이전 Render commit/기존 FE release로 되돌린다. DB 원문은 변경하지 않았으므로 schema downgrade나 강제 포인터 수정은 하지 않는다.

현행 운영 로그 allowlist는 보존하여 새 경로는 `unmatched`로 정규화된다. query/좌표를 로그에 넣지 않으며 고정된 기존 수집기·DPAPI/Task/runtime은 교체하지 않는다. 새 경로별 통계 확장은 별도 호환 작업이다.

## 5. 실제 검토/후속 기록

여기에 실제 Claude Code의 판단·수정 요구와 Codex의 수용/수정 및 최종 검사·통합/배포 근거를 기록한다. 아직 실행하지 않은 검토나 실제 배포를 완료로 표시하지 않는다.

### 5.1 Claude Code 정적 구현 검토 (2026-11-16, 1차)

- 범위: 이 문서 §1~4와 함께 전달된 발췌 소스만 읽었다. 대상은 BE `schemas/analysis/services/routers population_reference·population_public_subset`, 새 단위·라우터·PostGIS 테스트, 기존 `day_night.py`·`store_cohort.py` 일부, FE `api/population.ts`·hook·types·View·Section·display·mock·client·useReportData·ReportPage·ActivitySection·SummaryPage 발췌와 FE 문서다.
- 테스트·빌드·shell·DB·네트워크는 실행하지 않았다. §3의 통과 수치는 전달받은 기록이며 이 검토로 재확인한 것이 아니다.
- 이 문서에는 이전 Claude 지적이나 Codex 처리 기록이 없다. 따라서 이번 검토는 delta가 아니라 첫 판정이다(#178 설계 문서 이력은 이번 입력에 없어 대조하지 않았다).
- 아래에서 **[확인]**은 발췌 코드로 직접 확인한 사실이다. **[가정]**은 프레임워크·런타임 동작이나 발췌에 없는 코드에 기대는 판단이다.

**판정: REVISE.** BE는 PASS(차단 결함 없음)이고, FE에서 보고서 정합성 관련 결함 2건을 고쳐야 한다. 둘 다 작은 FE 수정이며 BE, API 계약, DB에는 영향이 없다.

#### 차단 결함 (FE)

**R1. 보고서 인구 블록의 로딩·캡처 정합성**
- **[확인]** `useReportData`의 `queries`에는 `population`이 없다. 따라서 `loading`, `failed`, `retry`가 인구 조회를 반영하지 않는다.
- **[확인]** `ReportPage.PopulationBlock`과 `PopulationReferenceSection`은 `isPending || isFetching`이면 같은 key의 유효한 데이터도 숨기고 "불러오는 중"을 표시한다.
- **[가정]** hook이 `staleTime: 0`이므로 React Query v5 기본값(`refetchOnMount: true`, 전역 QueryClient 기본값 미변경 가정)에서는 분석 화면 캐시가 있어도 보고서를 열 때마다 재요청한다.
- 그 결과 다른 블록은 준비 완료(`loading=false`)인데 인구 블록만 로딩 문구인 상태로 PDF·요약 이미지가 캡처될 수 있다. 이는 §2의 "보고서는 같은 6개 요청의 hook/응답을 사용"이라는 정렬 주장과 어긋난다. 캡처가 `loading`으로 gating된다는 점은 주석에 근거한 [가정]이다.
- 수정안:
  - 두 표시 컴포넌트 모두 `data`가 있으면 표시하고, 로딩 문구는 `isPending && fetchStatus !== 'idle'`일 때만 쓴다. key가 같으면 데이터가 같은 조건의 응답이므로 stale 혼입이 없다.
  - 보고서 `loading`에 `population.isLoading`을 포함한다. 오류는 지금처럼 `failed`와 분리해 다른 블록과 독립을 유지한다.

**R2. 조회 조건이 없을 때 보고서가 영구 로딩으로 표시됨**
- **[확인]** `params === null`이면 hook은 `skipToken`을 쓴다. 이때 React Query v5는 `status='pending'`, `fetchStatus='idle'`이고 `isPending`이 계속 true다.
- `PopulationReferenceSection`은 `!params`이면 `null`을 반환하지만, `ReportPage.PopulationBlock`에는 이 guard가 없다. 따라서 좌표가 없거나 `unsupported_brand`인 보고서에서 "불러오는 중"이 계속 표시된다.
- 이 경로에서 보고서가 블록을 렌더하는지는 발췌만으로 단정하지 못한다([가정]). 다만 guard는 없다.
- 수정안: `fetchStatus === 'idle' && isPending`이면 블록을 생략하거나 "조회 조건 없음"을 표시한다.

#### 권장 수정 (비차단)

- **S1. 렌더 오류 격리**
  - **[확인]** `SummaryPage`에서 다른 섹션은 `SectionErrorBoundary resetKey={search}`로 감싸져 있다. `PopulationReferenceSection`은 boundary 밖에 있다.
  - 쿼리 오류는 블록 안에서 처리된다. 하지만 렌더 예외(예: 예상 밖 응답 형태)가 생기면 페이지 전체로 번질 수 있다.
  - 수정안: 같은 boundary로 감싼다. ActivitySection 내부 위치도 boundary 여부를 확인한다([가정]: `AnalysisSection` 구현은 발췌에 없다).
- **S2. status↔reason 대응 미검증**
  - **[확인]** `PublicSource.coherent`는 `partial↔public_subset_only`만 검사한다. `not_supported↔numeric_scope_too_large`, `no_data↔그 외 reason` 대응은 검사하지 않는다.
  - 현재 assembler는 올바르게 매핑하므로 결함은 아니다. 계약 hardening을 위해 validator에 대응표를 추가하기를 권한다.
- **S3. spatial_compatibility 값 변경 시 전 요청 500**
  - **[확인]** `_metadata`는 `spatial_compatibility == "unverified"`가 아니면 500을 낸다.
  - 이는 fail-closed로 의도된 동작이다. 다만 향후 importer가 이 값을 바꾸면 이 endpoint 전체가 500이 된다. 바꿀 때 함께 처리할 호환 항목으로 기록해 둔다.
- **S4. 공간 선택 성능**
  - **[확인]** 공간 선택은 버전 내 격자 전체(운영 약 1만 개)에 대해 행마다 `ST_Transform`·`ST_Distance`를 계산하므로 인덱스를 쓸 수 없다.
  - 관측표 전역 scan은 아니며, 측정된 최장 3.656초는 검증 PC 왕복을 포함한 값이다. Render Free에서의 지연은 배포 후 실측해 기록한다. 저장 geography와 GiST 도입은 DDL이 필요하므로 이번 범위 밖이다.

#### 확인된 정합 사항

- **고정 구성**
  - [확인] source별 `(grid, admin)` 구성 중 24시간 모두 `observed`인 것만 사용한다. 비공개·누락·부재 시간이 하나라도 있으면 해당 구성 전체를 제외한다.
  - 다른 구성과 다른 원천은 유지된다. 원천 간 합산이나 대체는 없고, 0으로 채우지 않는다.
  - 중복 시간은 오류다. 행 순서와 전역 Decimal context에 영향받지 않는다.
- **숫자 산술**
  - [확인] 정수 1e-5 scale과 유리수 HALF_UP을 쓴다. 실제 0(`exact_zero`)과 양수가 반올림된 0(`rounded`)을 구분한다. 분모 0은 null+reason(`zero_total` / `zero_night_denominator`)으로 처리한다.
  - 시간별 합 상한 `HOUR_LIMIT = 10**20` 단위는 `calculate_day_night`의 입력 상한 1e15와 일치한다. 일간 합의 큰 값은 지원된다.
  - 야간 비중은 주간 비중의 보수(합 100.0)이며 이는 문서화된 의도다.
- **응답과 품질 정합**
  - [확인] `PublicQuality`의 항등식(후보 × 24 = 관측 + 비공개 + 누락 + 부재 등)이 지켜진다. `ready`이면 3원천이 고정 순서로 모두 있다.
  - status별 reason과 `observation_date`가 정합하고 `partial↔values`가 일치한다.
  - 응답과 token에 좌표가 없다. `lat`/`lng`/`PublicRow`는 `repr=False`, `hide_input_in_errors`가 적용된다. "전체 인구 아님", 원천값 합의 "인원수 아님", 한계 목록과 `*_validated=false` 메타가 있다.
- **전역 metadata와 선택 행 검증의 구분**
  - [확인] 전역 metadata는 버전 JSON의 counter와 SHA 형식만 검사하고 원천 hash는 재계산하지 않는다(문서 §1과 일치).
  - 선택 행은 버전, 날짜, `located` 상태, `grid_id` 일치를 행마다 검사한다. `version_unlocated_*`는 전역 값이며, FE도 "이 반경의 누락 수가 아님"으로 구분한다.
- **조회 경로**
  - [확인] 버전 선택은 `living_population_versions`의 MAX와 `limit(2)`로 하고 관측표 COUNT/GROUP BY가 없다. 격자와 행 조회는 limit+1로 하며 한도를 넘으면 잘라 쓰지 않고 `not_supported`로 응답한다.
  - 월 범위는 `[T의 1일, T]`이고 T는 기존 `effective_date`와 `temporal_cohort`를 재사용한다.
  - ValueError(pydantic ValidationError 포함), TypeError, OverflowError는 500+no-store로 처리된다.
- **라우터**
  - [확인] category 검사, 허용 key·중복 key 검사, 모델 검증이 세션 dependency보다 먼저 실행된다(`population_session`이 query에 의존). 422-before-DB 테스트가 있다.
  - 허용월 422는 DB 조회 뒤에 발생하며, 문서의 "구문 오류만 DB 전"과 일치한다.
- **FE 요청과 캐시**
  - [확인] FE는 6개 입력만 projection하고 `sub_category`를 정렬하며 radius 기본값은 500이다. 경로는 프로필과 무관하게 `/v2/population-reference`로 고정이다.
  - key는 같은 projection을 쓴다. `placeholderData`/`keepPreviousData`가 없어 이전 조건 응답이 섞이지 않는다.
  - signal은 fetch까지 전달된다. key 변경 시 이전 요청이 abort되는 것은 React Query v5 동작에 대한 [가정]이며 hook 수준 테스트는 없다.
- **FE 표시**
  - [확인] 숫자는 서버 `display` 문자열을 그대로 쓰며 JS Number로 변환하지 않는다. local 카드에 외국인 값이 대체되지 않는다(테스트 있음).
  - 합과 평균은 비compact `details` 안에만 있고 보고서(compact)에서는 생략된다. 모바일은 1열 기본이다.
- **mock 경계**
  - [확인] mock은 `import.meta.env.VITE_USE_MOCK === 'true'` 조건 안의 dynamic import로만 불린다. 인구 경로 외의 `/v2/` mock 차단은 유지된다.
  - production 번들에서 mock이 빠진다는 것은 Vite 정적 치환과 DCE에 대한 [가정]이다. 산출물 검사 근거는 이번 입력에 없다.
- **기존 API 호환**
  - [확인] 기존 activity의 `living_pop` null, Risk `day_night_ratio` pending, AI 입력이 바뀌지 않는다. 통합 테스트로 앞의 두 가지를 확인한다.

#### 누락 테스트 (구체)

**FE**
1. `useReportData`/`ReportPage`
   - 인구 재조회 중에도 같은 key의 데이터가 표시되는지 확인한다.
   - 인구 첫 로딩 중 보고서 `loading`이 true인지 확인한다.
   - `params=null`일 때 영구 로딩 문구가 나오지 않는지 확인한다(R1·R2).
2. hook 수준(`QueryClientProvider`)
   - lat/radius/as_of를 바꾸면 이전 요청의 signal이 aborted 되는지 확인한다.
   - 이전 응답이 새 key의 `data`로 노출되지 않는지 확인한다.
3. production 빌드 산출물(`VITE_USE_MOCK=false`)
   - `populationFixture`/`populationMock` 고유 문자열이 없는지 grep으로 확인한다. profile 테스트 4건이 이를 검사하는지는 이번 입력으로 확인하지 못했다.
4. `SummaryPage`
   - 인구 View 렌더 예외가 다른 섹션과 AI 블록을 깨뜨리지 않는지 확인한다(S1 적용 시).

**BE**
5. 라우트 경로(`population_session`)로 실제 PostGIS 요청 시 `SHOW transaction_isolation`과 `transaction_read_only`를 확인한다.
   - 기존 RR 테스트는 테스트가 직접 만든 세션으로 service를 호출하므로, `history_session`이 RR+READ ONLY라는 점은 이 발췌 범위에서 [가정]이다.
6. service의 행 검증 분기마다 500+no-store가 되는지 확인한다: `geometry_status != located`, `located_grid_id != grid_id`, 다른 `grid_version_id`/`observation_date`, 중복 `grid_id` 선택.
7. `_metadata`의 나머지 손상 사례를 확인한다: `sources` key 누락·추가, `unlocated_grids > unlocated_rows`, SHA 형식 오류, `grid_version_id` 불일치, `row_count` 합 불일치.
8. 극단 반올림 사례를 확인한다: 주간 비중이 100.0으로 반올림되고 야간이 양수일 때 야간 비중이 `"0.0"`, `exact_zero=false`, `rounded=true`인지, FE에서 "0에 가까운 값"으로 표시되는지.
9. `numeric_scope_too_large`가 `status=not_supported`, `values=None`이고 meta `public_subset_calculation_performed[source]=false`인지 확인한다. S2 validator를 추가하면 역방향 오류 사례도 확인한다.

#### 범위 외로 남긴 것

- 0013 승인·DDL, 새 API key, 원 15개 지점과의 정확도 비교는 다루지 않았다.
- 원 15개 좌표가 없으므로 개선율이나 대표성 주장은 하지 않았으며, 문서 §3도 이를 주장하지 않는다.
- 배포는 아직 실행되지 않았고 이 검토도 배포 성공을 주장하지 않는다.

### 5.2 Codex 수정·대조와 실제 브라우저 근거

실제1차 Claude 검토는08:21:47Z~08:24:49Z, exit0/is_error=false/3turns, MD 직접 수정·제공 BE/FE source SHA 보존·권한 거부0이다. BE 차단 결함0, FE 보고서 정합성2건으로 REVISE였으며 아래처럼 처리했다.

| 지적 | 처리와 근거 |
|---|---|
| R1 인구 조회 전 PDF 캡처 가능 | 수용. 핵심 결과의 loading과 별도로 captureLoading을 만들고 실제 인구 fetch가 끝나기 전 인쇄 버튼을 비활성화한다. 공개 기준일이 바뀔 수 있으므로 refresh 중 인구 숫자는 계속 숨기고 다른 결과는 표시한다. Share 요약이미지는 인구를 표시하지 않으므로 기존 호출에서 인구 조회를 하지 않는다(useReportData의 기본false, Report만true) |
| R2 disabled query의 영구 pending | 실제 Report의 선행 Navigate/unsupported guard는 최초 발췌 밖이었다. 그 사용자 경로에서 재현된 결함으로 단정하지 않는다. 추가로 populationEnabled guard를 두고 null query는 블록을 그리지 않게 했다. 실제 QueryObserver에서 skipToken→pending/idle/비로딩을 확인했다 |
| S1 렌더 오류 격리 | 새 카드와 Report의 View를 각각 SectionErrorBoundary로 감싸고 새 응답의 dataUpdatedAt으로 복구한다. 새 HTTP 실패를 만들어도 기존 Risk 카드는 정상으로 남았다 |
| S2 reason/status 대응 | 추가 validator로 numeric_scope_too_large↔not_supported를 양방향 검사한다. 단위 테스트로 모순을 거절하는지 확인했다 |
| S3/4 향후 원천·성능 | CHECK와unverified 계약을 바꾸면 호환 검토가 필요함을 유지한다. 요청당 관측 전역scan은 없고 격자 중심 계산은 실제 운영 배포 뒤 별도로 측정한다. 새DDL은 추가하지 않는다 |

추가 검증은 다음과 같다. (a) 새56개 단위/라우터/metadata 사례 통과: 극단적 양수 야간의 반올림0·counter bool/없는source/잘못된SHA·행수/좌표계/참조 손상 포함. (b) 실제 API dependency 경로에서 RR와READ ONLY를 직접 확인하는 새 PostGIS7개 통과. (c) FE178개+profile4개: 공유 queryOptions를 실제 QueryObserver에 넣어 key변경 취소·이전 결과 격리·무관필터 재조회 없음·disabled idle을 확인한다.

실제 로컬 브라우저는 복제DB→BE8002→FE5180의 HTTP를 사용했다. 화면/종합진단/보고서 숫자와관측일이 실제 응답과 같고 원천3개가 독립 표시된다. 390/360 가로넘침0, 반경변경의query/결과일치, 새endpoint만전송실패여도기존지표유지, pageerror0이다. 보고서에서 새인구요청만 실제로 보류했을 때 기존 표는 표시되고 인쇄버튼은disabled, 요청을재개한뒤enabled가됨을확인했다. 실제응답을가짜값으로교체하지않았으며 별도의운송실패/지연만주입했다. 인쇄PDF도생성했다.

Vercel의실제 build:vercel 체인으로 production/preview 모두빌드했다. 서로반대프로필환경을주어도 지정프로필이유지됐고 production 산출물에는 synthetic population fixture UUID/모듈명이없고 새API 경로/운영BE 주소가있다. preview에는fixture가있다. 브라우저·빌드·상세source행/스크린샷은비공개검증폴더에보존하며실제payload/키는Claude입력/커밋에넣지않는다.

DB복제는 새99,044,434bytes snapshot dump를별도 spoton_it DB에복원했고26개표전체row hash가일치하며원본hash도보존됐다. 해당clone의21GET은새15반경표본모두3원천partial·기존v2조회6개200이며최장0.531초다. 운영DB READ ONLY 검증21개와구분한다.

전체 회귀검사의 최초 일부실패는 검증wrapper가 DATABASE_URL을 주입해 기존 “DB미설정” fixture 전제를깨뜨린때문이다. 앱이나기존테스트를약화하지않고자식프로세스환경에서DATABASE_URL을제거했으며TEST_DATABASE_URL은기존로컬관리역할의임시DB접속만사용한다. 수정된조건의전체검사/최종CI 결과는후속기록을따른다.

### 5.3 Claude Code 정적 구현 검토 (2026-11-16, 최종·delta)

- 범위: 이 문서 전체(§5.1의 1차 지적과 §5.2의 Codex 처리)와 이번에 전달된 BE/FE 발췌 소스·테스트, 그리고 CODEX EVIDENCE 요약을 읽었다. 테스트·빌드·shell·DB·네트워크는 실행하지 않았다. 통과 수치, 브라우저·빌드·복제DB·운영 READ ONLY 결과는 **전달받은 기록**이며, 이 검토에서 다시 확인한 것이 아니다.
- 표기는 §5.1과 같다. **[확인]**은 발췌 코드로 직접 확인한 사실이고, **[가정]**은 프레임워크·런타임 동작이나 발췌 밖 코드에 기대는 판단이다.

**판정: PASS (정적 검토 기준).** BE와 FE 모두 차단 결함이 없다. R1·R2는 해소됐다. 이 판정에는 아래 조건이 있다.
- 별도로 실행 중인 BE/FE 전체 회귀검사와 CI/CodeQL이 통과해야 한다.
- §4의 배포 후 실측 결과를 기록해야 한다.
- 이 PASS는 배포 성공이나 정확도 개선을 뜻하지 않는다.

#### 1차 지적 처리 대조

| 지적 | 판정 | 근거 |
|---|---|---|
| R1 | 해소 | **[확인]** `captureLoading = loading \|\| (populationEnabled && population.isFetching)`이고 인쇄 버튼은 `disabled={data.captureLoading}`이다. 핵심 블록은 기존 `data.loading`으로만 gating되어 계속 보인다. 인구 오류 시에는 `isFetching=false`이므로 인쇄할 수 있고, 블록에 "불러오지 못했어요"가 그대로 인쇄된다. 숨기는 값이 없으므로 정직한 동작이다. 데이터가 있어도 refresh 중에는 숨긴다는 설계는 §5.2의 이유(기준일이 바뀔 수 있음)로 수용 가능하다. 1차 수정안 1번은 채택하지 않았지만 결함은 아니다. **[가정]** 최초 렌더에서 enabled query의 `isFetching`이 바로 true라는 점(React Query v5 optimistic result)은 프레임워크 동작이다. 실제 브라우저 보류·재개 근거가 이를 뒷받침한다. |
| R2 | 해소 | **[확인]** `populationEnabled = includePopulation && params !== null`이고, `PopulationBlock`은 `!populationEnabled`이면 `null`을 반환한다. Report의 선행 guard 두 개(`isDiagnosisReady` Navigate, unsupported_brand)는 hook 호출 뒤, 렌더 전에 있다. 따라서 skipToken pending이 보고서에 노출되는 경로는 남지 않는다. Share는 `useReportData()`의 기본값 false로 인구를 요청하지 않으며 인구를 표시하지도 않는다. **[확인]** `populationQuery.test.ts`의 disabled 테스트가 실제 `QueryObserver`로 idle/비로딩을 검증한다. |
| S1 | 해소 | **[확인]** Section과 Report 모두 View를 `SectionErrorBoundary resetKey={dataUpdatedAt}`로 감싼다. Section 자체(hook, ErrorState)는 boundary 밖이지만 단순 분기라 위험이 낮다. 렌더 예외 주입 테스트는 없다(아래 T3). |
| S2 | 코드 해소, 테스트 일부 | **[확인]** `PublicSource.coherent`가 `not_supported↔numeric_scope_too_large`를 양방향으로 검사한다. 다만 제공된 테스트는 `status=not_supported`이면서 reason이 다른 한 방향만 거절을 확인한다. §5.2의 "양방향…단위 테스트로 확인"은 발췌 기준으로는 절반만 입증된다(T1). |
| S3/S4 | 기록 유지 | 범위 밖 DDL은 없다. 배포 후 격자 거리 계산 지연을 실측하는 조건은 유지한다. |
| 누락 테스트 2·3·5·7·8·9 | 충족 | 각 항목의 근거는 아래와 같다. **[확인]** 2: QueryObserver 테스트로 abort, 새 key 격리, 무관 필터 비재조회를 확인한다. 3: production 산출물 검사는 전달 기록이다. 5: integration에서 route 경유 `SHOW transaction_isolation/read_only`를 확인한다. 7: metadata 9개 사례를 확인한다. 8: `test_positive_night_rounded_share_zero…`가 있고, FE 정규식 `/^0\.0+$/`가 `"0.0"`에 맞는다. 9: overflow 테스트가 있다(meta false는 `status=="partial"`에서 파생되므로 구조적으로 보장된다). |
| 누락 테스트 1·4·6 | 미충족(비차단) | 1·4는 단위 테스트 대신 실제 브라우저 근거로 대체됐다. 6(행 검증 분기의 500)은 발췌에 테스트가 없다. |

#### 이번 범위 재확인 (변경 없음, [확인])

- **고정 구성과 원천 독립**
  - fixed24h `(grid, admin)` 구성은 원천마다 독립이다. 비공개·누락·부재 시간이 하나라도 있는 구성은 통째로 제외하며, 0으로 채우거나 원천끼리 대체하지 않는다.
- **정확한 숫자 표기**
  - 정수 1e-5 scale과 유리수 HALF_UP으로 계산한다. `exact_zero`/`rounded`를 숫자마다 따로 둔다.
  - 야간 비중은 주간 비중의 보수로 만든다. 주간이 정확한 값이면 야간도 정확하므로 `rounded` 플래그가 서로 모순되지 않는다.
  - 분모가 0이면 null과 reason을 준다. `HOUR_LIMIT`는 `calculate_day_night`의 입력 상한과 같다.
- **표현의 한계**
  - "전체 인구 아님", "인원수 아님", `*_validated=false`와 limitations를 유지한다. 반경 전체 coverage나 모집단 완전성을 주장하지 않는다.
- **metadata 검증의 경계**
  - 전역 metadata는 counter와 SHA 형식만 검사한다. 선택된 행은 version, date, located, grid를 행마다 검사한다. 전역 unlocated 값은 FE에서 "이 반경의 누락 수가 아님"으로 구분한다.
- **조회 경로**
  - RR/READ ONLY 하나 안에서 버전 MAX와 `limit(2)`를 쓴다. 관측표 COUNT나 GROUP BY는 없다. 격자와 행은 limit+1이며 넘으면 잘라 쓰지 않는다. 월 범위는 `[T의 1일, T]`이고, 허용월 422(AppError)는 500으로 바꾸지 않는다.
- **응답 노출**
  - 응답과 token에 좌표나 개별 구성이 없다. token은 FE key를 대체하지 않는다.
- **FE 요청**
  - 6개 입력만 projection하고, 경로는 고정 `/v2/population-reference`다. canonical key에는 placeholder가 없다. `retry:false`는 이 query에만 적용된다.
- **mock 경계**
  - mock은 `VITE_USE_MOCK` 정적 조건 안의 dynamic import로만 불린다. production 산출물에서 fixture가 빠진 것은 전달 기록으로 뒷받침된다.
- **오류 격리와 모바일**
  - 오류는 인구 블록 안에서 처리하고 기존 Risk/AI query와 분리한다. 모바일은 1열 기본이다.
- **기존 API 호환**
  - 기존 `living_pop` null, Risk `day_night_ratio` pending, AI 입력이 바뀌지 않는다.

#### 남은 비차단 사항 (수정 제안, 코드 미수정)

- **N1. 문서 정합**
  - §3 표의 "44통과"와 "초기176"은 §5.2의 56/178보다 오래된 수치다. "초기 수치이며 최신은 §5.2"라고 표시하거나 갱신하기를 권한다.
  - 절 순서도 §5.2가 §5.1보다 앞에 있다. 이력을 보존하려면 위치는 두되 제목에 "(1차 검토 후)"를 붙이기를 권한다.
- **N2. 인쇄 우회**
  - 버튼 gating은 브라우저의 Ctrl+P나 메뉴 인쇄를 막지 못한다. 이 경우에도 인구 블록은 "불러오는 중" 문구로 인쇄될 뿐 잘못된 숫자는 나오지 않으므로 정합성 결함은 아니다.
  - 필요하면 `@media print`에서 로딩 문구를 "인쇄 시점에 조회 중이었음"으로 표기하는 정도로 충분하다.
- **N3. 터치 영역**
  - 원천 링크(`text-micro underline`)에는 `min-h-11`이 없어 모바일 터치 영역이 44px보다 작을 수 있다. 기존 Report 링크의 `max-md:min-h-11` 패턴을 적용하기를 권한다.
- **N4. [가정] FooterBlock의 R4 처리**
  - `FooterBlock`은 `metas`에 인구 meta를 받는다. 그런데 `source:["R4"]`의 FE 출처 라벨 매핑은 발췌에 없다. 브라우저 PDF에서 출처 문구가 정상이었는지 비공개 근거로 한 번 확인하기를 권한다.
- **N5. [가정] 버전 선택 기준**
  - 버전 선택은 `observation_date`만 기준으로 하며 import 완료나 활성 상태 컬럼을 보지 않는다.
  - importer `repository.save`가 완료된 버전만 커밋한다는 전제에 기대는 것이며, 기존 0012 계약에 대한 가정이다.

#### 구체적 누락 테스트 (비차단, 권장)

- **T1.** `PublicSource.model_validate`의 역방향 사례를 추가한다:
  - `status=no_data`, `reason=numeric_scope_too_large` → 거절
  - `status=partial`, `reason=no_source_rows` → 거절
  - `status=no_data`, `values≠None` → 거절
- **T2.** service 행 검증 분기를 PostGIS 또는 Mock session으로 확인한다. 각 경우 500, no-store, `data=None`이어야 한다.
  - `geometry_status≠located`
  - `located_grid_id≠grid_id`
  - `grid_version_id`/`observation_date` 불일치
  - 중복 `grid_id` 선택
- **T3.** View가 throw하도록 만들었을 때 Summary의 다른 섹션과 AI 블록이 남는지 확인한다(boundary 회귀 방지).
- **T4.** `useReportData(true)`를 대상으로 한다. 인구 fetch 중에는 `captureLoading=true`이고 `loading=false`인지, `includePopulation=false`(Share)에서는 fetch 호출이 0회인지 확인한다. 브라우저 근거를 단위 테스트로 고정하는 목적이다.

#### 결론

차단 결함이 없으므로 **PASS**이다. 1차 REVISE의 R1·R2는 코드로 해소됐고, S1·S2도 반영됐다. N1~N5와 T1~T4는 배포를 막지 않는 후속 항목이다.

배포 진행은 다음 실제 결과를 따른다.
- 전체 회귀검사, CI/CodeQL
- §4 3~5단계의 실제 Render/Vercel commit, deployment ID와 운영 확인

원래 15개 지점에 대한 개선율, 대표성, 공식 인구 근거는 이 검토에서도 주장하지 않는다.


### 5.4 Codex 최종 대조와 병합 전 상태

최종 Claude 검토는08:38:43Z~08:40:29Z exit0/is_error=false/3turns, MD 직접 수정·BE/FE source SHA 보존·권한 거부0으로 PASS였다. R1/R2와S1/S2 처리에 남은 이견은 없었다. 비차단 권고N3의 원천 링크44px 터치 영역을 적용했고, T1의 반대 status/reason·값 불일치 사례도 추가했다. 최종 새 단위/라우터/metadata59개를 확인한다. 기존 DB CHECK/FK가 막는 행 손상 분기를 검증하려고 보호를 해제하거나 운영 원문을 바꾸지 않았다.

전체 일반 검사는2496통과/Windows symlink권한3skip(새T1 추가 전 수치)였다. 실제 PostGIS 전체는304통과/1실패였고 실패는 신규 경로가 엄격한 OpenAPI 전체 목록에 없던 계약 검사다. ENDPOINTS에 새 경로만 추가해 해당 기존 흐름1개를 재검증했다. 기존 검사의 일치 비교는 유지했다. 정확한 최종head의전체숫자는CI를따른다. 이 실패를원천/환경키문제로숨기지않았다.

요청마다 전역 관측 COUNT가 없고 선택 행만 검증한다. `unverified`는 기존DB CHECK에 고정돼 있어 호환 범위를 유지했다. R4의 기존 출처명은 “서울시 생활인구250m 격자”이고 새 원천 카드에는 각각의 공식URL을 표시한다. import는 단일 transaction의 persist이며 기존 원천 파일 검증/commit 경계는 유지한다. 강제 Ctrl+P는 버튼대기를 우회할 수 있지만 그 경우 미산정은 로딩 문구로만 표시하며 숫자를 만들지 않는다.

현재는 코드·로컬/읽기 전용/브라우저 검증까지다. 이후 BE/FE PR의 CI/일반 병합·Render/Vercel 배포ID·실제 공개 API/브라우저 검증을각PR실행기록과이슈180/73에남긴다. 그 전에는 운영배포/전체기능완료로표시하지않는다. #115/#78의 공식전체인구검증은별도유지한다.
