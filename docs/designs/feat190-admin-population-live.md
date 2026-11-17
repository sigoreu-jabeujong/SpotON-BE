# 행정동 생활인구·주야간 실제 연결과 FE 반영 (#190 / FE #81)

검수된 #186의 B/D/E/F를 구현한다. 최신 사용자 “진행하자”가 자료 적재·API/FE 연결·테스트 서버 반영을 승인했다. 기존 로컬 원본 DB/환경/8000·8001·5173과 사용자 파일을 보존하고 별도 복제 DB와 프로세스 설정으로 검증한다.

## 1. 구현 결정

- migration0013은 행정동 경계/경계행/관측버전/시간행의4표만 추가한다. code_system 복합FK, 원천/일자/구역/시간 유일키, 상태/Decimal(20,5)·유효 MULTIPOLYGON4326·GiST를 적용한다. 기존 원천 행/불변CHECK/브랜드 publication은 변경하지 않는다.
- OA-23016의202610 ZIP과 OA-22160 실제 polygon을 사용한다. 425개 도형 중 인구와 정확히 일치하는422코드만 인구를 적재하고, 인구에만 있는5코드는 별도 quarantine artifact/건수로 보존한다. 다른 동으로 치환하지 않는다. 경계의 역사적 적용시점은미확정으로표시한다.
- 최초 활성화는2026-10-31 하루를 우선 적재한다. 원본1개월317688행은 그대로 보존하고 선택일10248행 중10128행(422×24)만 저장한다. 작은 적재로 실제 세카드 연결을 먼저 완료하며 응답은 실제 관측일을 표시한다. 이후 같은 불변 구조로 날짜 버전을 추가할 수 있다.
- 내용catalog는환경UUID가아닌input/content/규칙/행수·관측일·code_system·경계지문으로정한다. geometry의source content는고정source좌표/속성의canonical지문, 저장도형은PostGIS에서유효성/동일성검사를수행한다. 해시동일성으로역사적경계승인을주장하지않는다.
- CSV는같은월/선택일의비어있지않은파일·정확header/복수구분자·중복/24시간·숫자정밀도/마스킹/행부재를검증한다. 성연령열을총계에재합산하지않는다. total별표/빈칸은각각suppressed/missing/null, 실제0만observed/0이다.
- 기본미리보기는DB쓰기없음이다. localCLI write는기존localhost/spoton_dev/spoton_app/head가드를유지한다. 실제clone/원격적용은별도검증된관리절차로실행하며일반CLI가드를원격허용으로완화하지않는다.
- API의새인구블록은같은RR에서공개도형의ST_Covers·도형geography거리≤radius만사용한다. 포함동이있으면우선반환하고, 없거나포함동자료가없을때실제교차동을별도로보여준다. 여러동은합산하지않고동일공간/관측일/local24시간으로24시간평균·주야간평균/비율을계산한다.
- Decimal50자리산술, 평균소수1자리·비율5자리/비중1자리표시, 실제0/반올림0/야간0의비율null을구분한다. 날짜·동·출처키가평균/주야간에서같아야한다. 기존day_night.py산술을재사용한다.
- 현재latest_reference는실제2026-10-31을2023년점포분석과구분해표시한다. analysis_period는그월안/분석일이전날짜만허용한다. 기존AI/Risk/격자부분GET의같은월검증과전체인구미확정은유지한다.
- FE는기존배치/스타일을유지하며새참고API로매출·행정동내국인평균·주야간을분석/종합/보고서에연결한다. 미적용점포필터·실제자료일/구역·AI집계대상밖임을표시한다. 이전격자부분비교는독립상세자료로분리한다. 인쇄대기/취소/이전응답/구BE404/금액문자열을검증한다.

## 2. 적용·복구

현재 운영0012와새0013은readiness의정확head검사때문에그대로혼용할수없다. 원래17환경중기대revision만0013으로맞추며키/DB연결/LLM/CORS/풀/자동배포설정은보존한다. 원래.env는수정하지않는다.

먼저새복제DB에서0012→0013→원천적재/GET→downgrade0012/구readiness→reupgrade/동일자료재적재의전체결과를검증한다. 운영은실제전체백업/복원증거와원천artifact를보존한뒤,명시유지보수단위로새4표/SELECT권한→적재→BE/기대revision→readiness/기존GET/새GET→FE순서로반영한다. 새표는관리소유자, API는SELECT전용이다. clone소요시간/실제DB여유를확인하고최대15분/새probe90초기준을충족하지못하면전환을시작하지않거나복구한다.

기본복구는새카드미사용/FE복구→새BE중지→4표artifact보존→새4표만downgrade→기대revision0012/구BE→readiness/기존GET확인이다. 저장원본·기존업무표는되돌리는DML을하지않는다. 전체DB복원은기본downgrade실패시의별도관리절차다.

## 3. 필수검사와 커밋

①4모델/migration/공통기대revision·회귀와적재/재실행/불일치/rollback시험, ②새인구산술/schema/loader·범위/일자/결측/중첩/야간0시험, ③FE타입/요청/3화면/보고서·모바일/PDF, ④실제Claude검수·전체검사·CI/운영기록을기능별로커밋한다. 구체자료15지점의원자료→DB→API→화면일치를비공개위치artifact로확인한다. 구현/모의/실제파일/실제DB/공개배포의증거를구분한다.

## 4. 실제 Claude 검토

검토후실제결과와Codex처리를기록한다. 검수는이MD Read/Edit만허용하며설정/비밀값/원천레코드/실제위치는입력에포함하지않는다.

### 4.1 Claude 검토 (claude-opus-5-5, 2026-11-16)

- 범위: 이 MD 본문만 Read/Edit로 검토했다. 코드·DB·원천파일·서버·Git은 열거나 실행하지 않았으며, 아래 내용은 문서 결정의 정합성 판단이지 실행 검증이 아니다. #186의 기존 8표 승인 요건은 다시 열지 않는다.
- 판정: **REVISE** — 방향(실제 포함/교차동만 사용, 합산·유사동 대체 없음, masked≠0, 2026-10-31 하루 적재, 0013 4표 한정, 17환경 중 기대 revision만 변경)은 타당하다. 행수도 맞다(427×24=10248, 422×24=10128, 427×24×31=317688, 422×24×31=313968). 다만 아래 B1–B7은 구현 전에 문서에 명시해야 한다.

#### 차단 수정사항

- **B1 경계 원천 좌표계/인코딩/코드 정합**: 1절에 OA-22160 원천이 EPSG:5181·UTF-8임을 명시하고, 적재는 `.prj` 확인 후 `ST_Transform(5181→4326)`으로만 변환(SRID 추정·재지정 금지)하도록 적는다. 도형 425개의 행정동 코드 유일성, 변환 후 `ST_IsValid`/MakeValid 결과 유형이 MULTIPOLYGON인지, 0 면적 도형 없음을 검사 항목에 넣는다. 경계에만 있고 인구가 없는 3코드(425−422)의 처리(경계행은 저장하되 해당일 상태 `no_data`, 다른 동 대체 없음)와 건수를 5개 quarantine 코드와 별도로 기록한다.
- **B2 시간행 FK가 quarantine을 DB에서 강제해야 함**: 시간행은 관측버전 FK와 함께 `(경계버전, code_system, 행정동코드)` 복합FK로 같은 경계버전의 경계행을 참조해야 한다. 그래야 경계에 없는 5코드가 로더 버그로도 삽입되지 않는다. 관측버전에는 사용한 경계버전 FK를 고정한다(catalog 지문만으로 연결하지 않음).
- **B3 부분시간→전체 금지 명시**: 한 동의 해당일 24시간 중 suppressed/missing이 하나라도 있으면 24시간 평균은 null(사유 포함)이며, 주간/야간 평균도 각 시간집합에 결측이 있으면 null이다. 존재하는 시간만으로 평균을 내거나 결측 시간을 0으로 채우지 않는다. 시험 ②에 "23시간 관측+1시간 masked" 케이스를 추가한다.
- **B4 경계선 위 지점의 포함동 처리**: `ST_Covers`는 경계선 위 지점에서 2개 이상 동을 반환할 수 있다. 이 경우 임의 1개 선택·합산 없이 모두 포함동으로 각각 표시(또는 `ambiguous_boundary` 상태)하는 결정적 규칙과 정렬키(코드)를 명시한다.
- **B5 포함동 자료없음 시 교차동 표시 라벨**: 포함동이 있으나 자료가 없을 때(B1의 3코드 등) 교차동을 보여주는 경우, 응답과 FE에 "포함동 ○○: 자료 없음"을 먼저 표시하고 교차동은 "반경 내 교차 행정동(대체값 아님)"으로 분리한다. 교차동 값을 포함동 값처럼 표시하지 않는다.
- **B6 날짜 대체 금지**: 15행 analysis_period 규칙을 명확히 한다. 적재되지 않은 날짜(2026-10의 다른 날 포함)를 요청하면 가장 가까운 날짜로 대체하지 않고 명시 상태(`not_loaded`)를 반환한다. 기본(latest_reference) 응답은 항상 `observed_date=2026-10-31`, `source_month=202610`, 단위 "추정 생활인구(명, 내국인)", `boundary_period=unverified`를 필드로 포함한다.
- **B7 운영 용량 기준의 수치화**: 현재 운영DB(rev 0012, 768,825,011 bytes, Free 요금제)에 대해 "실제DB여유"를 수치 기준으로 적는다: 제공자 화면의 실제 Free 한도, 4표+인덱스+GiST+425 도형의 복제DB 실측 크기(`pg_total_relation_size`)와 적재 중 WAL/임시 여유를 더한 값이 한도 대비 정한 여유율을 넘으면 전환을 시작하지 않는다. 복제DB 검증은 운영 Free 할당량을 쓰지 않는 별도 위치에서 한다는 점도 명시한다. 1개월 전체(313968행) 적재는 이 기준을 다시 통과해야 한다.

#### 비차단 확인 (구현 시 유지)

- 재실행: 같은 catalog 키·같은 내용은 no-op, 같은 키·다른 내용은 오류로 거부하고 부분 적재가 남지 않도록 단일 트랜잭션(+advisory lock)으로 처리한다.
- 권한/롤백: 새 4표 GRANT SELECT는 0013 upgrade에서 부여하고 downgrade는 4표와 그 권한만 제거한다. 기존 원천/업무표·불변 CHECK·publication은 downgrade 대상이 아니다. 복구 후 readiness는 기대 revision 0012로 통과해야 한다.
- FE 호환: 구BE 404·타임아웃·이전 응답 도착 시 카드가 "참고자료 미제공"으로 표시되고 기존 AI/Risk/격자 카드와 보고서는 영향이 없어야 한다. 기존 AI/Risk/격자 GET의 엄격한 날짜 검증은 그대로 유지한다.

#### Codex 처리

- B1채택: 원천EPSG5181/UTF-8 CPG를정확히확인하고5181→4326변환만사용한다. 코드유일성/425행·MakeValid뒤MULTIPOLYGON/유효/비어있지않음/면적양수를검증한다. 경계에만있는3코드는도형행을저장하되인구no_data로표시한다.
- B2채택: 시간행은관측version/date/source/boundary/code_system복합FK와영역의boundary/code_system/admin_code복합FK를함께갖는다. 5개미매칭코드는별도artifact에만남는다.
- B3채택: 대표평균·고정주야간비교는동일동/일자의local24시간완전성을요구한다. 1시간이라도masked/missing이면그동의평균/비율은null이며다른동까지막지않는다. 일부시간의합을24시간평균으로쓰지않는다. 23observed+1masked를시험한다.
- B4채택: 경계선의복수포함동은모두개별표시하고코드순정렬하며임의선택/합산하지않는다.
- B5채택: 포함동자료없음행을먼저남기고실제반경교차동을별도라벨로표시한다. 교차동을포함동의값으로승격하지않는다.
- B6구체화: 기존입력as_of는월(YYYY-MM)이고일자입력은없다. analysis_period는해당월1일~서버분석T안에적재된관측일만선택하며다른월로대체하지않는다. 따라서2023-11/2026-11은no_data, 2026-10은적재된10월31일이다. latest_reference는10월31일을실제관측일·source_month=202610·내국인·미확정경계시점과함께표시한다. 일자입력을임의추가하지않는다.
- B7채택: 운영은768825011bytes에서시작한다. 별도PC복제DB에서새4표/인덱스/TOAST를실측한다. 공식Free1GB한도보다보수적인900000000bytes상한을쓰고`현재DB크기+신규4표실측+64MiB WAL/임시예약≤900000000`을만족해야적용한다. 운영DB안에검증clone을만들지않는다. 1개월확장은별도재측정한다.

위처리는실제11:48:27Z~11:49:36Z/exit0/is_error=false/3turns의MD직접검토결과를반영했다. 구현정적검토에서다시대조하며현재이를구현/운영검증PASS로표시하지않는다.

### 4.2 Claude 구현 정적 검토 (claude-opus-5-5, 2026-11-16)

- 범위: 요청 본문에 붙여 넣어 받은 코드(`app/models/admin_population.py`, `app/schemas/location_reference.py`, `app/services/admin_reference.py`·`location_reference.py`·`spatial_stores.py`, `app/analysis/day_night.py`, `etl/admin_population/*`, `migrations/versions/0013_admin_population.py`, 통합/ETL 시험, FE 타입·API·View·Section·ActivitySection·SummaryPage·useReportData·PDF 블록)와 이 MD만 정적으로 읽고 판단했다. 그 밖의 파일은 Read로 열지 않았고, 쉘·Git·DB·서버·네트워크는 실행하지 않았다. 시험·배포는 내가 실행하지 않았다. 5절의 clone 실행 결과(0013, 경계425, 시간행10128, 제외120, 유효하지 않은 도형0/수정0, 재실행 no-op, 6,905,856bytes, PostGIS 11개·FE 193+4개 통과)는 Codex가 보고한 증거로만 인용하며 재현하지 않았다. 전체 회귀는 아직 진행 중이다. 받지 못한 코드(`load_catalog`, readiness/기대 revision 설정, `PopulationReferenceQuery`, `useLocationReference`, 기존 격자 API·AI)는 판정 대상이 아니다.
- 판정: **REVISE** — 차단 1건(C1). 나머지 구조·마이그레이션·provenance·FE는 문서 결정과 B1–B7 처리에 부합한다. C1 수정과 해당 시험을 추가하면 구현 정적 검토는 PASS로 본다(운영 검증 PASS는 별도).

#### B1–B7 처리 대조

- **B1 충족**: `source.inspect_boundary`가 `.cpg`=UTF-8, `.prj`→`to_epsg()==5181`, 필드 집합, 코드 정규식·유일성, shapeType 5, 좌표 유한성을 확인한다. `repository.NORMALIZED`는 검증된 5181을 `ST_SetSRID` 후 `ST_Transform(…,4326)`→MakeValid→`CollectionExtract(3)`→`ST_Multi`로 변환한다. CHECK `ST_IsValid AND NOT ST_IsEmpty AND ST_Area>0`와 `geometry_repaired` 기록으로 수정 여부를 숨기지 않는다. 경계에만 있는 코드 수(`boundary_without_observations`)와 미매칭 코드 수(`unmatched_code_count`)를 따로 집계해 `quality`와 `source_refs`에 각각 노출한다.
- **B2 충족**: `admin_population_hours`에 관측버전 5열 복합FK와 `(boundary_version_id, code_system, admin_code)`→`admin_areas` 복합FK가 함께 있고, 관측버전→경계버전 FK도 있다. 시험이 존재하지 않는 코드와 다른 일자로의 갱신이 IntegrityError로 거부됨을 확인한다.
- **B3 충족**: `complete = len(values)==observed==24 and set(values)==set(range(24))`일 때만 평균을 계산하고(`/24`), 주야간 값은 `complete`일 때만 낸다. `calculate_day_night`는 None이 있으면 숫자를 내지 않는다. suppressed/missing/행 부재 시험이 있고, 행 부재는 카탈로그 행수 불일치로 500 fail-closed가 된다.
- **B4 충족**: `ST_Covers` 결과를 `(not covers, admin_code)` 순으로 정렬하고 포함동을 모두 남긴다. 합산은 없다. 경계 공유 시험으로 두 포함동이 각각 표시됨을 확인한다.
- **B5 충족**: 준비된 포함동이 있을 때만 교차동을 제거하고, 포함동이 `no_data`이면 그 행을 먼저 둔 뒤 교차동을 `intersects_radius`로 남긴다. FE 라벨은 "선택 반경과 겹침 (대체값 아님)"이다. 이 경우를 시험이 다룬다.
- **B6 충족**: `effective_date`는 미래 월을 422 `AS_OF_OUT_OF_RANGE`로 거부하고 다른 월로 옮기지 않는다(시험 있음). `analysis_period`는 `target.replace(day=1) ≤ 관측일 ≤ target`만 허용하므로 2023-11, 2026-09, 2026-11은 `no_data_in_analysis_period`이다. 응답에는 `observation_date`, `source_month`, `population_scope=local`, 단위, `boundary_period=unverified`가 들어 있다.
- **B7**: 코드 대상이 아니다. 5절 수치(842,839,731 < 900,000,000)는 산술상 맞다. 적용 직전 재측정 조건은 유지한다.

#### 차단 수정사항

- **C1 주야간 비중의 반올림값을 원값·정확0으로 표시함(정밀도/계약 위반)**: `calculate_day_night`는 `day_share_pct`를 미리 `quantize(0.1)`해서 돌려주고, `night_share_pct`는 `100.0 − 반올림값`이다. `admin_reference._number`는 이 값을 그대로 `value`로 써서 `rounded=False`가 된다. 따라서 33.333…%는 `value="33.3", rounded=false`로 정확값처럼 나오고, 주간 비중이 0.04%이면 `value="0.0", exact_zero=true`가 된다. 야간 인구가 0보다 크지만 매우 작을 때 `night_share_pct`도 `exact_zero=true`가 된다. 이는 1절 14행의 "실제0/반올림0 구분"과 `PopulationNumber`의 의미(`value`=정확값, `rounded`=표시 반올림)를 어긴다. 수정: `day_night.py`는 그대로 두고, `admin_reference`에서 `summary.day_total`·`night_total`로 `Decimal` 50자리 컨텍스트에서 반올림하지 않은 `day*100/total`과 `night*100/total`을 다시 계산해 `_number(…,1)`에 넘긴다(합계가 0이면 지금처럼 null+`zero_population_total`). 시험: (a) 주간:야간=1:2이면 `value`가 33.333…이고 `display` "33.3%", `rounded=true`, (b) 야간이 0보다 크지만 작아 야간 비중이 "0.0%"이면 `exact_zero=false`, `rounded=true`, (c) 야간이 실제 0이면 `night_share_pct.exact_zero=true`이고 비율은 null+`zero_night_population`.

#### 비차단 (기록·후속)

- 날짜가 여러 개 적재되면 `selected`는 동마다 가장 최근의 완전한 날을 고른다. 그래서 항목마다 관측일이 다를 수 있다(각 항목에 표시되고, 평균과 주야간은 같은 버전을 써서 B3은 지켜진다). 1일 적재에서는 영향이 없지만, 날짜를 추가할 때 "최신일 masked → 이전 완전일" 시험과 FE 문구를 함께 추가한다.
- 카탈로그 관측일 중 하나라도 DB에 없으면 블록 전체가 `source_not_loaded`가 된다. fail-closed로 허용하되 날짜를 추가할 때 운영 절차에 적어 둔다.
- 0013의 GRANT는 `spoton_api`가 없으면 조용히 건너뛴다. 5절대로 운영 전환 전에 실제 API 역할로 4표 SELECT를 확인하는 probe를 필수 게이트로 유지한다. 권한이 없으면 응답이 500이 되어 매출 카드까지 함께 사라진다.
- admin 메타데이터 drift(ValueError)는 매출을 포함한 `/v2/location-reference` 전체를 500으로 만든다. 이는 선택 참고 엔드포인트의 명시적 fail-closed로 받아들이며 기존 AI/Risk/격자 GET에는 영향이 없다. FE의 분석/종합 화면은 이때 일반 ErrorState를 보여 준다. 4.1의 "참고자료 미제공" 문구 정렬은 후속 과제로 둔다(PDF 블록은 이미 별도 문구가 있다).
- FE `AdminReferenceItem` 타입에 `source_month`가 없다. 표시에는 지장이 없지만 응답 계약과 맞추는 것을 권한다.
- 운영 readiness의 기대 revision 변경(17환경 중 그 값만)과 `/ready` 일시 불일치 측정은 받은 코드에 없어 판정하지 못했다. 5절 기록으로 확인한다.

#### 다시 열지 않는 사항

- #186의 8표 게이트, 외국인·전체 격자 원천 요구, 유료 플랜 변경은 범위 밖이다. 1일·내국인(local) 우선 적재, 합산·면적가중·최근접 대체 금지, 기존 격자 API와 AI의 분리는 코드에서 유지되고 있음을 확인했다.

### 4.3 Claude 구현 정적 재검토 — C1 이후 (claude-opus-5-5, 2026-11-16)

- 범위: 4.2와 같다. 요청 본문에 붙여 넣어 받은 현재 코드(모델, schema, `admin_reference`·`location_reference`·`spatial_stores`, `day_night.py`, `etl/admin_population/{source,data,repository,runner,__main__}.py`, 0013 migration, 통합·ETL 시험, FE 타입·API·View·Section·ActivitySection·SummaryPage·useReportData·PDF 블록)와 이 MD만 정적으로 읽었다. 쉘·Git·DB·서버·네트워크·다른 파일은 열거나 실행하지 않았다. 시험·배포도 내가 실행하지 않았다. clone 결과(0013, 경계425, 시간행10128, 제외120, 유효하지 않은 도형0/수정0, 재실행 no-op, 6,905,856bytes, 새 PostGIS 시험 통과, FE 193+4 통과)는 Codex가 보고한 증거로만 인용한다. 전체 회귀는 아직 끝나지 않았다. 4.1·4.2 기록은 바꾸지 않았다.
- 판정: **PASS (구현 정적 검토 한정)** — 새 차단 사항은 없다. C1은 해결됐다. 이 판정은 배포·운영 PASS가 아니다. 백업/복원 증거, 실제 API 역할의 SELECT probe, 기대 revision 전환과 `/ready` 측정, 용량 재측정, 전체 회귀는 아직 남아 있는 게이트다.

#### C1 확인

- `admin_reference`가 `calculate_day_night`의 반올림된 `day_share_pct`/`night_share_pct`를 더 이상 쓰지 않는다. 같은 동·같은 관측일·local 24시간이 `complete`일 때만, 50자리 `Decimal` 컨텍스트에서 `summary.day_total*100/total`과 `summary.night_total*100/total`을 각각 계산해 `_number(…,1)`에 넘긴다. 기존 격자용 `day_night.py`는 바뀌지 않았다.
- `_number`가 `value`=반올림하지 않은 값, `display`=소수 1자리, `rounded=(shown≠value)`, `exact_zero=value.is_zero()`로 만들고, `PopulationNumber` validator가 80자리에서 다시 확인한다. 따라서 1:2는 `value≈33.333…`, `"33.3%"`, `rounded=true`가 된다. 작은 양수는 `"0.0%"`, `rounded=true`, `exact_zero=false`가 된다. 실제 야간 0은 `night_share=0`, `exact_zero=true`가 되고, 비율은 null+`zero_night_population`이다. 합계가 0이면 두 비중 모두 null+`zero_population_total`이다.
- 자리수 범위: 입력 상한은 Numeric(20,5)(<1e15, 소수 5자리)이다. 가장 작은 양수 비중은 대략 1e-20 크기이고, 이때 50자리 유효숫자를 고정소수로 쓰면 소수 약 70자리다. 이는 schema의 소수 80자리 제한 안에 든다. 비율이 가장 클 때(약 1.2e21)도 5자리 quantize가 50자리 정밀도 안에 든다. 시험에 극단값 `0.00001 : 999999999999999.99999`가 들어 있다.
- 시험 `test_share_preserves_unrounded_value_and_distinguishes_rounded_zero`가 (a) 1:2와 (b) 주간/야간 각각의 작은 양수, 그리고 극단값을 다룬다.

#### 그 밖의 재확인 (차단 없음)

- **정밀도/결측**: 평균은 24시간이 모두 `observed`일 때만 `/24`로 계산한다. 주야간 평균과 비율도 같은 `complete` 조건과 같은 버전·동을 쓴다. masked/missing은 null+사유로 남기고 0으로 바꾸지 않는다. 행이 빠지면 카탈로그 행수가 맞지 않아 500 fail-closed가 된다. FE는 `display`가 없으면 "자료 없음"을 보여 준다.
- **공간**: `ST_Covers`와 geography 거리 ≤ radius만 쓴다. 최근접 선택, 면적 가중, 합산은 없다. 준비된 포함동이 있으면 포함동만 남긴다(경계선 위면 여러 동을 코드 순으로 모두 남긴다). 포함동에 자료가 없으면 그 행을 먼저 두고, 교차동은 "대체값 아님" 라벨로 따로 표시한다.
- **기간**: `as_of`는 월 단위다. 미래 월은 422 `AS_OF_OUT_OF_RANGE`다. `analysis_period`는 그 월 1일부터 분석일까지의 관측일만 받고 다른 월로 옮기지 않는다. `latest_reference`는 2026-10-31을 실제 관측일, `source_month`, `later_reference`와 함께 보여 준다. 기존 격자 GET과 AI 경로는 이 변경과 섞이지 않는다.
- **provenance/재실행**: 원천 SHA를 다시 확인한 바이트만 읽는다. 모든 일자를 같은 월로 확인하고 5자리 정밀도를 다시 검사한다. 경계 지문과 정규화한 도형을 `ST_Equals`로 비교하고 관측 지문도 다시 비교한 뒤 같으면 no-op, 다르면 거부한다. advisory lock과 단일 트랜잭션을 쓴다. quarantine 파일은 배타적으로 만들고 같은 내용만 재사용한다. `quality`에서 경계에만 있는 코드 수(3)와 미매칭 코드 수(5)를 따로 기록한다.
- **migration**: 0013은 새 4표, GiST, 복합 FK, CHECK, 조건부 SELECT GRANT만 추가한다. downgrade는 이 4표만 지운다. 기존 표는 건드리지 않는다.
- **FE**: `source_month` 타입을 추가했고, 가맹·브랜드·면적 필터를 적용하지 않는다는 고지와 반올림 표시(`(표시 반올림)`)가 있다. 구BE 404나 오류가 와도 다른 카드에 영향이 없고, PDF는 별도 문구로 표시한다. 인쇄는 `isFetching`이 끝날 때까지 기다린다.

#### 비차단 권고 (기록·후속)

- **시험 (c) 명시화**: 실제 야간 0의 `night_share_pct.exact_zero=true`, `rounded=false`, `display="0.0%"`는 코드상 맞다. 하지만 받은 `test_zero_night_and_zero_total_keep_valid_means_without_ratio`(`all_zero=False`)는 `mean_night`와 비율만 확인한다. 이 세 값을 확인하는 assert 한 줄을 추가하기를 권한다.
- **`geometry_repaired`의 판단 대상**: 지금은 변환 전 5181 원도형의 `ST_IsValid`만 본다. 변환 뒤 생긴 무효성이나 `CollectionExtract(3)`가 선/점 성분을 버리는 경우는 이 플래그에 잡히지 않는다. 이번 clone 증거(유효하지 않은 도형0/수정0)로 볼 때 이번 적재에는 영향이 없다. 다음 경계 버전부터는 변환한 도형 기준으로 판정하거나, 정규화 전후의 면적·성분 수가 같은지도 함께 기록하기를 권한다.
- **비중 표시 합계**: 주간·야간 비중은 각각 반올림하므로 표시값 합계가 99.9%나 100.1%가 될 수 있다(예: 12.25/87.75). 값은 정확하고 `(표시 반올림)`이 함께 표시되므로 계약 위반은 아니다. 필요하면 FE에 "각각 반올림" 문구를 덧붙인다.
- **기록 정합**: 5절에는 새 PostGIS 시험 수가 "11개"(C1 이전)와 "18개"(C1 이후)로 함께 적혀 있다. 최종 기록에서는 두 수가 각각 언제 실행된 것인지 구분해 적는다.
- 4.2의 비차단 항목 중 다음은 그대로 유지한다: 여러 날짜를 적재할 때 동별 관측일이 달라질 수 있는 점, 일부 카탈로그 날짜만 빠져도 `source_not_loaded`가 되는 점, GRANT가 조건부라 실제 역할 probe가 필수 게이트인 점, 메타 drift가 생기면 참고 엔드포인트 전체가 500이 되는 점(분석/종합 화면은 ErrorState를 보여 줌).

#### 남은 게이트 (이 PASS에 포함되지 않음)

- 전체 회귀·CI 결과
- 운영 전체 백업과 복원 증거(원격 TEMP DiskFull 이후 클라이언트 쪽 정렬로 해시를 다시 확인하는 것 포함)
- 실제 API 역할의 4표 SELECT probe
- 17환경 중 기대 revision만 0013으로 바꾸고 `/ready` 일시 불일치를 측정한 기록
- 적용 직전 용량 재측정(현재 크기 + 6,905,856 + 64MiB ≤ 900,000,000)
- 90초 probe와 15분 롤백 기준
- 15지점에 대해 원자료→DB→API→화면이 일치한다는 비공개 artifact

이 항목들이 실제로 끝나기 전에는 배포·운영 PASS를 주장하지 않는다.

## 5. 실제 실행 기록

### Claude C1 처리

기존 격자 day_night 산술은 유지하고 새 행정동 서비스에서 원래 주/야간 합계로 50자리 Decimal 비중을 각각 계산한다. 1:2의33.333…/표시33.3%, 작은 양수의표시0.0%/exact_zero=false, 실제0의exact_zero=true를 구분한다. Numeric(20,5) 극단값도 포함한 새 PostGIS 집중18개가 통과했다. FE는 서버 display 문자열을 그대로 사용하며 반올림 여부를 표시한다. 전체 인구로 승격하거나 기존AI에 입력하지 않는다.

원자료 검사(source.py)가 이미 수행하던 PRJ/CPG·숫자 정밀도 검증을 구현 검수에 함께 제공했고, prepare에서도 5자리 소수 상한을 재검사한다. quarantine은 트랜잭션 실패 후에도 원천증거로 보존할 수 있으며 동일 내용만 재사용하고 덮어쓰지 않는다. 행정동 메타/행수 오류는 선택 참고 API 전체500의 fail-closed이며 기존 업무 GET/AI와 분리한다. source_month 타입과 가맹·브랜드·면적 필터 미적용 고지도 추가했다.

- 로컬 원본 rev0012 전체 26표의 snapshot dump(99,044,434bytes)와 복원 clone의 전체 행 해시 일치를 확인했다. 원본은 유지했다.
- clone rev0013: 경계425, 시간행10128, 제외120행. 유효하지 않은 도형0/수정도형0. 동일 원천 재실행 no-op. 새4표/인덱스/TOAST 실측6,905,856bytes.
- 용량 예상: 768,825,011 + 6,905,856 + 67,108,864 = 842,839,731bytes < 900,000,000bytes. Free 한도는 [Render 공식 문서](https://render.com/docs/free)의 1GB를 확인했다. 적용 직전 운영 크기를 다시 확인한다.
- C1 보강 전의 초기 PostGIS 집중검사11개 통과. FE Vitest193개 + 배포프로필4개 통과. 실제 clone GET에서 매출/생활인구/주야간 모두 제공됨을 확인했다. 전체 회귀/검수/공개 배포 결과는 완료 시 추가한다.
- 운영 전환은 기존 쓰기를 멈추었다고 주장하지 않는다. 새4표만 추가하며 기존 업무 GET은 계속 동작한다. 기대 revision과 새 BE 전환 사이 `/ready`의 일시 불일치는 측정·기록한다. 새 배포가 live가 된 뒤90초 안에 연속 정상 probe가 확인되지 않거나 전체 전환15분을 넘으면 롤백한다.


### 5.1 최종 공개 반영·검증 (2026-11-16)

| 항목 | 실제 결과 |
| --- | --- |
| BE 코드/CI | PR #191 Squash→develop, `0ac3bf6c905fe217139116f39bbd5e5f16d91a07`. CI 전체 단위2572 통과/OS권한2제외, PostGIS341 통과/제외0, Windows199 통과, lint/format/mypy/CodeQL 성공 |
| FE 코드/CI | 기능PR #86, 병행된 브랜드 필터 #87을 보존한 기존 릴리스PR #88→main `3842d636469e42e6aa58a9cc4fc77a774237d5a7`. 최종 통합 Vitest198/프로필4 통과, production빌드·lint·CI/CodeQL/Vercel 성공 |
| DB/원자료 | migration0013, 경계425/유효하지 않은 도형0, 내국인2026-10-31 시간행10128. 미매칭5코드/120행 별도보관, 경계에만 있는3코드는 자료 없음. 재실행no-op |
| 실제 백업/복원 | 운영26표의99,052,369bytes dump를 별도 로컬DB에 실제 복원하고 전체행해시 일치. SHA256 `f0b85bd8e3b38c8dd95fa20508cee31730dc1131d4150033be94ecea137eb6a6` |
| 원본 보존 | 배포 후 기존25개 데이터표의 전체행해시 동일. 기존 인덱스/제약/트리거/소유자/ACL 동일. alembic_version 행만0012→0013. 원래 로컬DB/.env/기존 서버는 유지 |
| 용량/권한 | 실제775,804,595bytes +64MiB예약 <900,000,000. 실제API역할 `spoton_api`는 기본READ ONLY이며 새4표 SELECT만 허용, INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER 없음 |
| 환경/BE 공개 | 원래17환경 중 `DATABASE_EXPECTED_REVISION`만0013. LLM/CORS/연결/풀/Free/자동배포설정 보존. Render `dep-dbtfdhu7bikc73cg7uh0`, live12:28:32.779583Z |
| 실제 수치 대조 | 공개15지점에서 매출212개·생활인구15개·주야간15개를 원자료/DB/API와 대조. 같은15지점의 실제 FE 세 값도 서버display와 일치 |
| 실제 화면/인쇄 | 분석/종합/보고서3경로,360/390px 가로넘침 없음, JS오류0. 실제Chromium PDF 생성. 검증지점 PDF5쪽(전체상권 목록 포함), 선택범위에 따라 쪽수 증가 |
| 기존 업무API | v2 activity/risk/기존격자3GET 최종200, 배포 전후 data해시 동일. 새 참고값은 기존AI에 넣지 않음 |

외부 준비 API는 **`/api/ready`**다. 앞 절의 `/ready`는 router-relative 표기다. 초기 확인도구에 `/api`를 빠뜨린404 기록은 무효로 분리·보존했고 이를 준비장애 측정으로 사용하지 않았다. 올바른 경로의 첫200은 새 배포live 후29.03초였다. 올바른 경로로 전체 원본 해시/공개API 검증을 함께 수행하는 중500이1회 관찰됐고, 이후 연속 정상 및 최종3회200을 확인했다. 정확한 전체 중단시간이나 무중단·무오류를 주장하지 않는다. 원본 해시대조 중 기존GET 첫 재검사도1회 실패했으나, 대조가 끝난 뒤 재검사3GET의200·원래data해시 일치를 확인했다.

공개 화면: https://spot-on-fe.vercel.app / BE: https://spoton-be-free.onrender.com . API/파일의 날짜·인구범위와 미확정경계/매출집계기간 고지를 유지했다. 운영반영 시간과 최종probe 분포는 비공개 `rollout-finished.json`, 원자료/위치/DB접속 정보는 비공개 증거에 보관하고 저장소에 올리지 않았다.
