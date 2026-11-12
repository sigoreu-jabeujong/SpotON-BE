# BE-21 브랜드명 기반 추정 판정 적용 설계

- 관련 이슈 #57, 선행 원천 기반 PR92/develop0519869. 기존 로컬검증 snapshot(v2·2025년11,167원천행)을 명시적으로 재사용한다. 신규 원천/키 요청이나 자동 최신판 선택은 없다.
- 이번 완료: 근거/버전 모델·실제 로컬 판정 적용·재적재/직접수정 시 자동값 무효화·API/AI/캐시·BE측 FE 요청서·테스트/PR/CI. FE 저장소/.env/Docker·사용자 미추적 분석 MD는 수정하지 않는다.

**1~7절은 최초 검토안이다. Claude가 지적한 값 복사/소유권 모호성 때문에 채택하지 않았다. 최종 구현은9절의 읽기 시점 파생 A안이며 stores 변경·trigger·stores 쓰기 잠금이 없다.**

## 1. 의미와 범위

사용자가 승인한 프랜차이즈 추정은 공정위 기준년도 목록과 인허가 상호의 정확한 정규화 이름 일치라는 뜻이다. 가맹계약/직영 구분·현재 실제 소속·개업 당시/과거 소속의 증명이 아니다. NFKC/casefold/공백 정규화와 기존 3자·외식/전체목록유일 기준을 재사용한다. 부분일치·지점명 제거·유사도·LLM 판정은 없다. 반복 브랜드번호의 모든 관련 이름·일반 동명·약한 이름·미일치는 unknown이다. 별도 근거 없이 false/independent를 만들지 않는다.

기존 is_franchise/brand_id가 있는 **수동/외부 분류**는 보존한다. 자동 판정에는 별도 소유 표식 brand_match_id를 두어 외부 분류와 구분한다. 이번 실제dev의 기존 분류는0건이지만 코드/격리테스트는 수동 true/false/외부 brand_id를 보존해야 한다. 가맹 필터는 이름 일치 추정값에 대한 필터이며 과거 월에도 당시 계약을 복원한 값이 아니다. 모든 화면/AI에 기준년도·근거·한계를 표시하도록 BE측 요청서를 작성한다.

## 2. DB·원자성 (migration0011)

1. brand_catalog_versions: UUID PK, 실제 snapshot input_sha256·정규화content_sha256·catalog_rule(v2)·reference_year·collected_at·행 수·loaded_at. unique(input_sha256,catalog_rule). snapshot의 완료시각만 사용하며 인허가 collected_at은 null 유지한다.
2. brands: bigint 내부identity PK, catalog UUID FK, source 관리번호/본부번호 문자열·원문/정규화 이름·대/중분류. unique(catalog,관리번호,본부번호). 반복 source번호는 보존한다. 대표자/사업자/법인정보는 저장하지 않는다.
3. store_brand_matches: UUID PK, catalog/brand FK·원천source/license_no/name/category/sub_category 스냅샷·입력SHA256·판정규칙·created_at. **정확 추정만** 저장한다. unique(catalog,source,license_no,input_sha256,rule). 과거 근거를 보존하므로 Store FK로 cascade하지 않으며 source/license의 논리 식별을 기록한다. brand와 catalog의 복합 FK로 일치 보장한다.
4. brand_mapping_runs: UUID PK, catalog FK·매핑규칙·점포입력SHA256·검토대상/매칭 건수·고정카운터JSON·loaded_at. unique(catalog,rule,store_input_sha256). run과catalog 복합unique도 둔다.
5. brand_mapping_state: PK id=1 CHECK, 선택 catalog/run 복합FK. 최신 추정이 아닌 **명시 적용한** 버전 포인터다. catalog는 immutable하고 state만 명시 명령으로 바꾼다.
6. stores.brand_match_id nullable UUID FK(store_brand_matches). 기존 brand_id는 외부 숫자값 호환을 위해 새 FK를 추가하지 않는다. 자동 표식이 있는 행에서만 trigger가 brand_id/true/원천 입력·현재catalog 일치를 보장한다. 기존 모델·테스트의 외부 brand_id=123은 계속 허용한다.

모든 hash/년도·건수·식별자·enum/JSON 종류·source/지원업종 CHECK와 FK/unique/index를 둔다. 새 테이블은 empty migration부터 시작한다. SQL lock_timeout5초. 데이터가 있거나 자동 소유 표식이 있으면 downgrade를 고정 오류로 거절한다. 빈 downgrade는 trigger/FK/열/함수/테이블 순으로 제거하고 기존 외부 가맹필드를 보존한다. shared ETL head guard·current-head 테스트/README/BE CLAUDE를0011로 맞춘다. 과거 migration의 revision/down_revision이나 역사 기록은 바꾸지 않는다.

## 3. 자동값 무효화 trigger

public 스키마 명시·SECURITY INVOKER의 BEFORE INSERT/UPDATE stores trigger를 둔다. 오류는 고정문구/23514만 쓰고 이름/관리번호/SQL값을 노출하지 않는다. early return으로 자동 표식 없는 기존 행은 바꾸지 않는다.

- 기존 자동 표식이 유지된 채 is_franchise/brand_id를 외부에서 다른 값으로 바꾸면 표식만 해제하고 명시된 새 수동값을 보존한다.
- 기존 자동 표식이 유지되고 name/source/license/category/sub_category가 바뀌거나 삭제/검토대기/지원범위 이탈이면 자동 표식·자동 bool·자동 brand_id를 null로 지운다. 날짜/좌표/배치 갱신만이면 유지한다. 원문 공백/대소문자 변화도 보수적으로 무효화한다.
- 표식만 명시 해제하고 파생값이 그대로인 경우 파생값도 지운다. 수동 승격은 명시 분류를 별도 입력하는 경로로 다룬다.
- 새/다른 표식을 넣는 경우 근거행의 원천 입력/brand/catalog·true값·현재state가 정확히 일치하고 지원조건이어야 한다. 거짓/누락/다른 점포/다른 catalog면 고정 오류로 거절한다. FK만으로 새 표식을 신뢰하지 않는다.
- 같은 입력의 인허가 replay는 표식 유지, 상호/업종이 바뀐 upsert는 같은 원자적 원천 트랜잭션에서 자동값이 제거된다. 일반 직접 SQL 수정도 같은 보호를 받는다. 소유자/DB관리자의 trigger 우회까지 방어했다고 주장하지 않는다.

## 4. 적용 실행기

`python -m etl.brands.apply --snapshot <검증된저장소밖파일> [--write]`. 기본은 로컬대상/head0011·READ ONLY RR의 계획/건수이며 DB쓰기/외부HTTP 없음. source 파일을 한 번 읽은 같은 bytes로 parser/파일hash를 검증하도록 snapshot 공통 helper를 분리한다. 임의 경로/키/원문·예외는 출력하지 않는다. JSON1건·성공0/실패1·인자2/Ctrl+C130. source=brands 기존 operation logger를 재사용한다.

plan은 지원업종/삭제없음/검토대기아님 점포를id순 스트리밍한다. 자동 표식이 있는 행의 copied bool/brand_id는 수동판정으로 세지 않고 재평가한다. 외부 분류는 existing_classification으로 보존한다. 점포입력hash는 원천 식별/이름/업종·수동 분류 여부/값을 포함하고 자동 산출값은 제외해 최초 적용 후 동일 replay의 hash가 같아야 한다. 매칭 대상 약6,839행만 메모리에 보유하고 나머지는 배타카운터/입력hash만 누적한다. 반복번호 격리 등 기존 후보규칙을 공통화해 대조와 적용이 어긋나지 않게 한다.

--write는 새 트랜잭션의 명시 global advisory lock + stores SHARE ROW EXCLUSIVE lock으로 writer/동시적용/ETL과 직렬화한다. 잠금5초/각SQL60초, API 기본3초는 유지한다. lock 후 다시 plan을 읽어 dry-run 때의 점포를 믿지 않는다. catalog/source rows를 저장·기존버전 metadata/모든 정규화행hash를검증한다. mapping run은catalog/rule/inputhash로재사용한다. 새양성근거를준비하고state포인터를같은트랜잭션에서설정한뒤대상행의3개자동필드만갱신한다. 이전자동행중새대상에없는행은해제한다. 수동필드·원천값·updated_at/배치·다른테이블은보존한다. 저장후대상/근거/표식일치를검증하고commit한다. 중간오류/해제오류/취소시전체rollback한다.

완전같은현재run/근거/표식은쓰기없는reused로처리하고loaded_at/UUID를유지한다. 이전catalog로명시전환할때는과거run재사용과실제필드변경건수를구분한다. 원본/판정/상태를검증없이최신으로대체하지않는다. catalog/run/근거는일반경로에서수정/삭제하지않는다.

## 5. API·FE 계약

history/nearby/snapshot 행에 nullable `franchise_basis`(catalog_exact_name|external_classification|null), nullable `franchise_reference_year`를추가한다. 자동표식true는catalog_exact_name/명시년도, 기존외부bool은external_classification/년도null, unknown은둘다null이다. 기존franchise=franchise|independent|unknown·요청필터/unknown토글은유지한다. 층호·날짜·반경등기존선택조건은그대로다.

위3API와activity/risk의meta.franchise_classification은미적용시기존pending/brand_mapping_blocked, 적용시status=estimate·reason=reference_catalog_name_match·reference_year·source=[R7]·coverage=partial·historical_contract_verified=false·규칙/카탈로그/매핑run지문이다. 요청RR세션에서단일PKjoin으로상태를읽고표식행이있는데상태없음등불일치는안전한500이다. data_version에적용catalog/run/hash/규칙을추가해추적한다. 인허가meta.as_of/collected_at은덮지않는다. 매핑이적용돼도미일치/미확인은unknown이며임의false는없다.

FE는프랜차이즈를추정이라고표시하고현재목록기준·기준년도/역사한계를같이표시해야한다. unknown배제결과0을실제독립/가맹점부재로표현하지않는다. FE직접변경없고BE측별도요청보고서/BE CLAUDE만갱신하며FE CLAUDE는담당자대기로표시한다.

## 6. AI·캐시

Risk meta의새분류상태를typed allowlist로검증하고pending/estimate를구분한다. _DataVersion은brand catalog/run/hash/규칙지문을검증/해시하되outbound context에는UUID/상호/브랜드번호/원천명을보내지않는다. outbound에는분류status·기준년도·고정근거만추가하며estimate일때고정방법론한계`franchise_name_match_not_contract_or_history`를넣는다. risk/AI서로다른분류상태·지문은거절한다.

서버작성해석/진단서문구도분류미확인과명칭일치추정을구분한다. 기존모델선택후보/숫자·출처검증을유지하며새프롬프트지문/version을기록한다. 가맹계약확정·실제성공확률·새위험점수는생성하지않는다. Risk의DB MVCC snapshot cache namespace를유지하고새매핑run이data version/AI cache에반영되는지검증한다. 같은건수라도판정버전이바뀌면기존AI결과를재사용하지않는다. 실제LLM송신은추가하지않고mock검증한다.

## 7. 검증·실데이터 계획

단위: 후보/적용공통규칙·정규화/반복/동명/짧은이름·안전로그/CLI/단일파일읽기·입력hash·AI 상태/지문/문구/금지정보. 격리PostGIS:0010→0011/빈down/data존재down거절·모델일치·catalog/근거/표식의FK/trigger·수동true/false보존·유/무변경upsert·직접수정/무효화·새catalog재판정/replay/동시writer/실패rollback·5조회경로/가맹필터/unknown·AI준비/cache무효화를검증한다. 기존전체일반/격리·ruff/format/mypy·비밀검사를통과해야한다.

실제dev는사전기존14테이블/원천전부(공간EWKB포함)의입력열hash/건수/head0010·수동분류0을확인한다. migration0011·snapshot재검증·dry-run을먼저완료하고명시write로추정만반영한다. 원천입력/updated_at/배치/기존비점포13테이블은같아야하고변경은승인한3개파생필드·새5테이블뿐이다. 기존수동값은보존한다. replay UUID/loaded_at/무변경·원자료/표본·API/필터/AI mock준비확인·모델차이0·실제원본snapshothash보존을검증한다. 필요시명시maintenance실행기로commit후VACUUM/출처/API성능을확인하며인허가대량재적재/원천갱신/실LLM/자동운영은하지않는다. 일시잠금/가시성경계와검증범위를보고한다. 지정PR모든CI/CodeQL후develop정상Squash하며#57최종범위달성여부를점검해종료한다.

## 8. Claude 실제 설계 검토

이MD와지정BE소스만Read하고이절만Edit한다. .env/DB/raw/네트워크/Bash/Git/FE/다른파일/agent금지. 상태/근거/추정의미·trigger상태전환·원자성/경합/수동보존·inputhash/replay·metadata/AI/cache지문·과거소속비확정·테스트누락을검토한다. 실제실행/데이터/증거를직접확인했다고주장하지않는다.

### 8.1 검토 범위와 한계

- Read한 파일: 이 MD, `app/models/store.py`, `etl/brands/compare.py`, `etl/brands/catalog.py`, `etl/localdata/repository.py`, `app/ai/context.py`, `app/schemas/ai_context.py`, `app/services/risk_cache.py`. Edit은 이 8절만 했다.
- nearby/snapshot/history/activity/risk 서비스의 가맹 필터 SQL, 공통 spatial/cohort 함수, migration, 프롬프트, AI cache key 조립부, 테스트는 읽지 않았다. 아래 그 부분에 대한 서술은 **확인 필요 가정**이다.
- DB·명령·테스트를 실행하지 않았고 실제 데이터/성능/잠금 동작을 관측하지 않았다. 아래는 코드 정적 대조와 PostgreSQL 일반 동작에 근거한 설계 의견이다.

### 8.2 차단 사항 (현재 1~4절 그대로 구현하면 안 되는 점)

**B1. 자동값을 `stores.brand_id`에 복사하면 식별자 공간이 충돌한다.** `Store.brand_id`는 FK 없는 BigInteger 외부값이고(모델 88행), 설계는 외부 brand_id=123도 계속 허용한다(2절6). 반면 자동 판정이 넣을 값은 `brands`의 내부 identity(카탈로그마다 새로 발급)이거나, 원천 관리번호는 영숫자 문자열이라(`catalog.py` 86~91행 정규식) bigint에 들어가지 않는다. 결과적으로 같은 열의 `123`이 외부 브랜드인지 내부 행인지 `brand_match_id`를 함께 읽지 않으면 구분할 수 없고, 카탈로그를 바꾸면 같은 브랜드가 다른 숫자가 된다. brand_id만 읽는 기존/후속 코드(확인 필요)는 근거를 오해한다.

**B2. "같은 열에 자동값과 수동값을 함께 두고 trigger로 소유권을 추정"하는 상태 기계가 모호하다.** 3절 규칙으로는 다음 경우를 결정할 수 없다.
- 수동 작업자가 자동값과 **같은 값**(true·같은 brand_id)을 확정 의도로 쓰면 OLD=NEW라 표식이 남고 자동값으로 취급된다. 이후 상호 변경 시 수동 확정값이 지워진다(수동 보존 위반).
- is_franchise만 바꾸고 brand_id는 그대로 두는 등 부분 변경, 표식 해제+값 동시 변경, apply 실행기 자신의 "새 표식 설정"과 "이전 표식 해제"가 같은 trigger 분기 안에서 외부 수정과 구분돼야 한다. 행 단위 BEFORE trigger는 "누가" 썼는지 모르므로 세션 GUC 등 추가 신호가 필요해지고, 그 신호는 일반 SQL로도 위조할 수 있다.
- 3절 마지막 문장처럼 소유자 우회는 막지 못하므로, 결국 정합성은 trigger가 아니라 읽기 시점 검증에 의존해야 한다.

**B3. 4절의 "REPEATABLE READ에서 lock 후 다시 plan"은 효과가 없다.** RR 스냅숏은 트랜잭션의 첫 질의 시작 시점에 고정된다. `SELECT pg_advisory_xact_lock(...)` 자체가 첫 질의이면 대기 전에 스냅숏이 잡혀, 잠금을 얻은 뒤 읽는 plan은 대기 중 커밋된 인허가 upsert를 보지 못한다. 이후 해당 행 UPDATE는 직렬화 실패(40001)가 나거나, 수정되지 않은 행에 대해서는 오래된 상호 기준 판정이 커밋된다. 또 apply의 global advisory key는 `repository.py` 100~101행의 출처별 키(`spoton:localdata:{source}`)와 달라 advisory로는 ETL과 직렬화되지 않으며, 직렬화는 오직 SHARE ROW EXCLUSIVE에 의존한다(이 경우에도 그 잠금 문장이 스냅숏보다 먼저여야 한다).

**B4. AI 경로는 현재 분류 meta 변경을 즉시 500으로 만든다(동시 변경 필수).** `context.py` 186행은 `franchise_classification == {"status":"pending","reason":"brand_mapping_blocked"}`를 정확히 요구하고, `_DataVersion`(46~56행)은 `extra="forbid"`, `RiskInterpretContext.franchise_classification`은 `Literal["pending"]`(ai_context 100행)이다. Risk meta나 data_version에 필드/상태를 추가하는 커밋과 AI 검증·스키마·프롬프트 버전 갱신이 분리되면 매핑 적용 즉시 모든 `/api/risk/interpret`가 500이 된다. 6절은 방향은 맞지만 "같은 커밋·같은 PR의 원자적 변경 + 적용 전/후 양쪽 테스트"를 완료 조건으로 명시해야 한다.

**B5. store_brand_matches와 run의 소속 관계가 없다.** 2절3의 unique(catalog,source,license_no,input_sha256,rule)는 run을 포함하지 않아, 같은 카탈로그에서 점포 입력이 일부 다른 두 run이 근거행을 공유한다. state가 run을 가리켜도 "이 run의 양성 집합"을 SQL로 열거할 수 없고, 2절5의 run 포인터와 6절의 표식 사이 일치를 검증할 근거가 없다.

### 8.3 최소 안전 대안 (권장: A, 성능 미달 시 B)

**A. 읽기 시점 파생 — `stores`를 변경하지 않는다(권장).**
1. `stores`에 열/trigger/FK를 추가하지 않는다. `is_franchise`/`brand_id`는 외부·수동 분류 전용으로 남는다. migration0011은 새 테이블만 만들고 downgrade는 새 테이블 drop(데이터 있으면 기존 설계대로 거절)뿐이다.
2. `store_brand_matches`에 `run_id` FK를 넣고 unique(run_id, source, license_no). 근거 스냅숏으로 판정 당시 `name`·`category`·`sub_category`(원문 그대로)와 brand 복합FK를 둔다. 정확 추정 양성만 저장한다.
3. 조회 시 유효 분류 = ① `is_franchise IS NOT NULL OR brand_id IS NOT NULL`이면 `external_classification`(기존 값 그대로), ② 아니면 `brand_mapping_state.run_id`의 match 중 `source/license_no` 일치이며 `name IS NOT DISTINCT FROM`·category·sub_category가 **현재 stores 값과 정확히 같은** 행이 있으면 `franchise`/`catalog_exact_name`, ③ 그 외 `unknown`. false/independent는 외부값에서만 나온다.
4. 효과: 상호/업종 변경 시 join이 자연히 실패해 unknown이 되므로 trigger 무효화가 불필요하다(공백/대소문자 변화도 원문 비교라 보수적 무효화가 그대로 유지). 수동값은 ①이 항상 우선이므로 "같은 값 확정" 모호성이 사라진다. 인허가 ETL(`repository.py`의 UPDATE_COLUMNS는 가맹 필드를 건드리지 않음)·updated_at·배치·VACUUM 절차를 바꾸지 않는다. 삭제/검토대기/지원범위 이탈은 기존 조회 조건이 이미 제외한다(확인 필요).
5. apply 트랜잭션은 새 테이블만 쓴다. 점포 입력은 별도 READ ONLY RR에서 읽어도 되고, 그 사이 상호가 바뀐 행은 3의 정확 일치 검사로 조회 시 자동 탈락하므로 stale plan이 잘못된 양성을 만들지 않는다. 따라서 **stores SHARE ROW EXCLUSIVE 잠금이 필요 없고** ETL을 막지 않는다. 남는 직렬화는 apply 상호간 global advisory lock(첫 문장) + unique 제약이다. state 변경·run/근거 insert·건수 재검증을 한 트랜잭션에서 하고 실패 시 전체 rollback.
6. 비용: 가맹 필터를 쓰는 공통 SQL(nearby/snapshot/activity/risk 및 Risk 서울 비교 집계, history 표시)에 LEFT JOIN 1개가 추가된다. 인덱스 (run_id, source, license_no) INCLUDE(name, category, sub_category)와 state 단일행 조인으로 충분할 가능성이 높으나 **SQL 3초 제한·#82 출처 조회와의 합산 시간은 실측 전 미확인**이다. 필터 표현식은 한 공통 함수로만 만들어 5개 경로가 어긋나지 않게 한다(해당 함수 위치는 확인 필요).

**B. (A가 3초를 넘을 때만) 표식만 저장, 값은 복사하지 않음.** `stores.brand_match_id`만 추가하고 `is_franchise`/`brand_id`에는 자동값을 쓰지 않는다. 유효 분류는 A-3과 같은 우선순위로 `COALESCE`한다. trigger는 "brand_match_id가 있고 name/source/license/category/sub_category가 바뀌면 표식만 NULL" 하나로 축소하고, 수동 필드 판단·새 표식 검증 분기는 두지 않는다(새 표식 정당성은 apply가 근거행과 현재 행의 정확 일치를 같은 트랜잭션에서 확인). 이 경우 apply 쓰기 트랜잭션은 READ COMMITTED이거나, RR이면 `LOCK TABLE stores IN SHARE ROW EXCLUSIVE MODE`를 스냅숏을 잡는 어떤 SELECT보다 먼저 실행해야 한다(B3).

어느 안이든 B1에 따라 **자동 판정은 `stores.brand_id`에 쓰지 않는다**. 응답의 브랜드 식별은 노출하지 않거나, 필요 시 별도 필드로 카탈로그 범위를 명시한다.

### 8.4 그 밖의 보완 의견 (차단 아님)

- **입력 hash 결정성:** 4절의 "id순 스트리밍" 순서로 hash를 만들면 동일 내용이라도 행 재삽입 시 hash가 바뀐다. hash는 (source, license_no) 정렬의 정규 직렬화로 계산하고 스트리밍 순서와 분리한다. A안에서는 수동 분류 값이 run 결과에 영향을 주지 않으므로 store_input_sha256에서 제외해도 되고, 대신 ①로 가려진 양성 건수는 run 카운터에만 남긴다.
- **규칙 단일화:** `compare.py`의 분류 순서(외부값→결측→약한이름→반복번호→동명→미일치→비외식→후보)를 apply가 그대로 재사용해야 한다. 현재 `compare_rows`는 결과를 건수로만 반환하므로 "행별 사유를 산출하는 공통 함수 + 대조는 집계만" 구조로 리팩터링하고, 대조 건수가 리팩터링 전후 동일한지 기존 회귀로 확인한다.
- **업종 교차 오탐:** 현재 후보 규칙은 대분류 `외식`만 확인하고 점포 cafe ↔ 브랜드 중분류(예: 한식)의 불일치는 보지 않는다. 판정을 막지는 않되 근거행에 브랜드 중분류를 보존하고 run 카운터에 `category_cross_match` 건수를 기록해 후속 판단 근거를 남길 것을 권한다.
- **과거 점포·생존율 편향:** 폐업 이력까지 2025년 목록 이름으로 표시·필터하므로, Risk에서 `franchise=franchise` 필터의 생존율/폐업률은 "2025년에도 등록된 브랜드명" 쪽으로 생존 편향이 생길 수 있다. 6절의 고정 한계 enum 외에 Risk meta에 가맹 필터 사용 시 이 한계를 명시하고, history 행의 `franchise_reference_year`는 점포 개업/폐업 연도와 무관함을 FE 요청서에 적는다.
- **independent 필터:** 추정은 false를 만들지 않으므로 `franchise=independent`는 외부 false만 반환한다(실제dev 0건 예상, 실측 미확인). `include_unknown_franchise`와 결과 0의 의미를 FE 요청서에 명시해야 한다.
- **Risk 캐시:** `risk_cache.snapshot_token`은 `pg_current_snapshot()`을 포함하므로 매핑 커밋 후 새 요청은 다른 namespace가 된다. 다만 risk_key의 rule 인자는 Risk RULE_VERSION뿐이므로, 읽기 파생 규칙 문자열(매핑 규칙 버전)을 data_version/meta와 함께 key 입력에도 넣어 코드만 바뀐 재배포와 구분하는 것을 권한다(프로세스 재시작으로 cache가 비는 현재 구조상 필수는 아님).
- **AI outbound:** 추가할 것은 status(pending|estimate)·reference_year·고정 근거/한계 enum뿐이며 카탈로그/run UUID·hash는 `_DataVersion`에서만 검증·해시하고 context에는 넣지 않는다. 6절 방향과 같다. data_version에 UUID를 추가하면 5개 API meta 형태가 바뀌므로 FE 요청서 대상이다.
- **downgrade:** A안이면 stores 변경이 없어 "자동 소유 표식 존재 시 거절" 분기가 불필요하고, 새 테이블에 데이터가 있으면 거절만 남는다.

### 8.5 추가해야 할 테스트 (현재 7절 누락)

- 외부 brand_id 숫자와 내부 brand 식별이 같은 값일 때 응답 근거가 섞이지 않음(B1).
- 수동 true+같은 brand_id 확정 후 상호 변경 → 수동값 유지(B2/A-4).
- apply와 인허가 upsert 경합: apply 대기 중 상호 변경 커밋 → 바뀐 점포가 양성으로 남지 않음(B3, A에서는 조회 시 탈락).
- 매핑 적용 전/후 각각 `/api/risk/interpret` 준비 성공, 상태 불일치 시 안전한 500(B4).
- 동일 카탈로그·다른 점포 입력의 두 run이 서로의 양성을 섞지 않음, state 전환 후 이전 run 양성 비노출(B5).
- 입력 hash가 행 id 순서 변화에 불변.
- 가맹 필터 적용 Risk의 서울 비교 집계·5개 경로 결과가 공통 필터 함수와 일치하고, 3초 제한 내 실측(실측 결과는 실행 후에만 기록).

### 8.6 판단 요약

1~4절의 "소유 표식 + 값 복사 + BEFORE trigger + stores 잠금" 방식은 B1~B3 때문에 그대로 채택하지 않을 것을 권한다. 5·6절의 API/AI 방향(근거·기준년도·estimate 구분, UUID 비노출, unknown 비확대)은 유지하되 B4를 같은 커밋 조건으로 묶는다. 최소 안전안은 **A(새 테이블 + 읽기 시점 정확 일치 파생, stores 무변경)**이며, 실측에서 3초 제한을 넘을 때만 **B(표식만 저장, 단일 무효화 trigger)**로 후퇴한다. 최종 선택과 실측 근거는 9절에서 Codex가 기록한다.

## 9. Codex 최종 결정·실행 검증

Claude 지정8파일 실제 Read/§8 Edit·12턴 이내·오류/권한거절없음을확인하고소스와대조했다. B1~B5를수용해A안으로확정한다. 자동판정은원본 stores.is_franchise/brand_id와분리하고제안한stores열/FK/trigger/쓰기잠금을추가하지않는다. migration0011은새5테이블만추가한다.

### 9.1 채택한 저장·적용 구조

- catalog/version 및brands의원천보존은유지한다. mapping_run의카탈로그/매핑규칙/점포입력hash를unique로삼고store_brand_matches는run_id/catalog/brand복합FK·unique(run_id,source,license_no)와원문name/category/sub_category스냅샷을갖는다. 정확추정양성만저장한다. state는run/catalog복합FK와id=1이다.
- apply기본은READ ONLY RR의plan이다. write는READ COMMITTED의명시global advisory lock으로apply끼리직렬화하며하나의streaming SELECT에서점포plan/hash를만든다. source/license_no C정렬의입력hash에원문이름/업종·기존외부분류값을포함하고rowid/자동파생값은넣지않는다. source조회후원천이바뀌어도읽기시점정확일치검사로오래된양성이노출되지않는다. 새catalog/run/근거/state만하나의트랜잭션으로저장/검증한다. 실패/취소rollback,기존원천/updated_at/배치/수동값/행전체는변경없다.
- 같은현재run은기존UUID/loaded_at/근거를검증해무변경재사용한다. 명시이전catalog전환은기존run재사용과state변경을구분한다. 이전run의양성을현재run과섞지않는다. 데이터가있는downgrade는고정오류로거절한다.

### 9.2 공통 조회·근거

- 공통SQL은수동bool또는brand_id가있으면기존bool우선, 둘다없고현재run의(source,license,name,category,sub_category)가일치하면true, 아니면null이다. 독립false는외부값만사용한다. 인덱스(run_id,source,license_no) INCLUDE(name,category,sub_category)를두고일치집합을tuple IN/hash subplan으로구성해반복행별subquery비용을줄인다. 기존공통attribute_filters와서울비교집계에도동일표현식을쓴다. 전체+unknown포함은분류필터를true로단순화한다.
- history/nearby표시에도같은SQL표현식을선택해N+1조회가없게한다. snapshot은기존franchise필드가없으므로이번에franchise와basis/reference_year를함께추가한다(사전소스확인). nullablebasis/catalog년도와meta분류/지문은1~7절방향유지하되수동외부값의원천증빙을새로검증한것으로표현하지않는다. 역사·생존선택편향/partial coverage를명시한다.
- Risk/AI의typed 상태·지문·고정한계·서버문구·prompt버전·cache변경을같은PR에포함하고전/후양쪽을검증한다. UUID/hash는내부data_version검산에만쓰고LLM에는상태/년도/고정근거만추가한다. 신규원천/LLM송신없다.

### 9.3 검증 조정

새테이블5개/FK·빈down/데이터down거절·run격리/동시apply/replay/rollback·서로다른카탈로그전환·수동값불변·상호/업종변경직후자동unknown·과거원문복귀/수동값우선·캐시/AI지문/metadata위조거절·SQL3초를검증한다. stores열/제약/원천upsert코드는바꾸지않고기존schema계약검사를유지한다. sharedheadguard/현재head기대값만0011로갱신한다. 실제dev전후기존14테이블전체행/공간hash가모두같아야한다. B안은A안실측이실패할때만재설계하고현재승인하지않는다.

### 9.4 실제 검증 결과

- Claude Code가 지정 파일을 실제 Read하고 이 문서 8절을 수정했다(10턴, 오류·권한 거절 없음). Codex는 원본 필드 변경·trigger 방식의 문제를 수용하고 A안을 구현했다.
- 일반 테스트 1,347개, 신규 브랜드 통합 14개를 포함한 격리 PostGIS 전체 203개가 통과했다. ruff/format321파일·strict mypy154파일도 통과했다. 상호 변경 직후 unknown, 원문 복귀, 수동 분류 우선, 재적재 경합, run 전환, 동시 apply, replay, rollback, 데이터가 있는 downgrade 거절을 확인했다. 공개 risk/interpret 전후 검사는 mock 제공자를 사용하며 실제 LLM 호출은 없다.
- 실제 개발 DB에 migration0011과 새 5개 테이블만 적용했다. 2025년 브랜드 원천 11,167행·지원 업종 355,835점포 중 정확 이름 추정 6,839건이다. 독립 매장으로 자동 분류한 행은 없다. 재실행은 같은 catalog/run UUID를 재사용하고 state도 변경하지 않았다.
- 기존 14개 테이블의 전체 행·공간 EWKB hash·건수와 원본 snapshot hash가 모두 동일하며, SQLAlchemy 모델 비교 차이는 0이다. stores의 기존 is_franchise/brand_id/updated_at·배치·원문은 보존됐다.
- 실제 자료로 HTTP 41건(3개 위치·필터별 nearby/snapshot/activity/risk, history·범위·지원 링크 등), 내부 AI 준비 6건을 통과했다. 위치별 4개 API 순차 실행은 0.656~1.593초였고 기존 SQL 3초 제한을 유지했다. 따라서 B안은 필요하지 않았다. 별도 실행한 로컬 서버에서도 health와 프랜차이즈 전용 주변 조회 HTTP200·17건을 확인했다. 측정값은 SLA 보장이 아니다.
- metadata는 estimate·reference_year=2025·partial이며 계약/과거 가맹/업종 대응 검증은 주장하지 않는다. 프랜차이즈 전용은 include_unknown_franchise=false를 함께 전달해야 한다. 독립 전용 0건은 확정 분류가 없다는 의미다. 카탈로그 연도는 점포 개·폐업 당시의 계약 상태가 아니다.
- AI prompt는 risk-interpret-v5이며 분류 한계·내부 버전 지문·캐시를 함께 갱신했다. 내부 UUID/hash는 모델로 전송하지 않는다. 인허가 collected_at=null과 공식 근거 미확인 수치의 pending은 유지한다.
- BE 계약·실행 안내와 [FE 요청서](../fe-franchise-classification-api-request.md)를 갱신했다. FE 저장소·CLAUDE.md 반영은 담당자 대기이며 완료로 처리하지 않는다. 사용자 미추적 분석 문서, .env, Docker 설정과 원자료는 커밋하지 않는다.
