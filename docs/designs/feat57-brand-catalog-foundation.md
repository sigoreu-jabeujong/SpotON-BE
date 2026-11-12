# BE-21 공정위 브랜드 전체 수집·정규화·점포 대조 설계

- 관련 이슈: #57, 2026-11-12 승인 확인 후 재개.
- 공식 원천: https://www.data.go.kr/data/15125467/openapi.do
- 실제1행 사전 호출: HTTP200/resultCode00, 요청2025년·전체11,167건. 키/응답 원문은 이 문서에 기록하지 않는다.

## 1. 이번 단계의 완료 경계

BE-21을 원천 기반과 판정 적용으로 나눈다. 이번 PR은 전 페이지 수집·정규화·변조 검증 가능한 원천 snapshot 및 기존 전체 점포에 대한 **읽기 전용 정확 상호 대조**를 완성한다. 이는 완전한 브랜드 원천/충돌 규모를 먼저 확보하는 실행 가능한 기능이다. 이슈57은 종료하지 않는다. brands/판정 모델·migration·별칭 검토·실제 stores.brand_id/is_franchise 갱신·분류 상태/AI/캐시/FE 계약 활성화는 이 결과를 근거로 다음 단계에서 함께 설계한다. 후보 수를 실제 프랜차이즈 수로 표시하지 않는다.

이 경계는 현재 메타/AI가 brand_mapping_blocked로 고정되고 원천 재적재가 외부 소유 가맹 필드를 보존하는 구조를 고려한다. 이름만 먼저 UPDATE하면 provenance/분류 상태·과거 유효성·재적재 보존·AI 해석이 불일치한다. 후보 대조가 신뢰 가능한 실제 점포 가맹계약/브랜드 소속 증명은 아니다. 화면/필터의 unknown을 유지한다.

## 2. 사용자 확정 사항

주간06:00이상18:00미만/야간나머지는SpotON구분, 생활인구는요청월T이하최근검증일1일, 매출은상권별분기, 공식통계2025역사자료우선, 브랜드는추정/미확인/별도근거있는비프랜차이즈, 준비된기능만활성화한다. 생활인구/경계/매출기간/공식업종·분기의 공식근거가 없으면 해당 수치만 보류하고 나머지 개발을 진행한다. 다운로드일은 전체수집완료시각의 증빙이 아니므로 기존 인허가 collected_at=null을 유지한다. 월1회갱신을 운영 방향으로 두되 자동갱신/최신화는후순위, 배포는FE준비대기·비용한도검토는현재선행조건에서제외한다.

## 3. 수집·보존 계약

신규 etl/brands 모듈. API endpoint는 고정 HTTPS /1130000/FftcBrandRlsInfo2_Service/getBrandinfo. 로컬 DATA_GO_KR_SERVICE_KEY만 사용하고 encoding키일때1회unquote, 실제요청은params로인코딩한다. 키/URL/원시예외/응답/상호/사업자·대표자정보를stdout/stderr에출력하지 않는다. 기존 httpx/httpcore URL 로그 억제를 재사용한다. 실패는 고정 코드, 숨은 재시도/연도대체/부분성공은 없다.

연도는명시2000~현재연도, pageNo1부터·numOfRows1000·resultType=json. HTTP200과resultCode00, pageNo/numOfRows/totalCount·전체건수불변·예상페이지길이/페이지수·연도·브랜드/본부복합키 중복을검증한다. 최대100,000행·페이지5MiB·snapshot200MiB로 제한한다. 미지원요청/키누락/timeout/redirect/인증오류/구조변경/빈연도/누락·중복페이지는실패한다. response JSON 중복키도거절한다. 단순HTTP200을수집완료로보지않는다.

모든페이지수집/검증후원본body를base64와SHA256으로보존하는 snapshot JSON을저장소밖지정파일에쓰기전용신규생성한다. schema/고정endpoint/연도/page_size/total_count/실제API전체수집완료UTC시각/정규화content_sha256/pages만허용한다. 원문에는공식공개대표자/사업자정보가있을수있어로컬파일로만보관하고커밋/로그/Claude/LLM에보내지않는다. 완료시각은이번실행의마지막응답검증완료시각이며원천갱신일/기준년도와구분한다. 기존인허가수집일을덮지않는다.

기존파일은덮어쓰지않는다. 실패시이번에만든미완료파일만정리하고기존파일은유지한다. 저장오류면실패이며완료로출력하지않는다. offline snapshot도크기·shape·모든페이지hash/응답/행·contenthash를같게재검증한다. 새로받은동일내용의contenthash는같고완료시각/rawhash는다를수있다. snapshot hash는인증서명/공급자의불변성을증명하지않는다.

## 4. 정규화·후보 대조

정규화행은기준년도·문자열brandMnno/jnghdqrtrsMnno(접두사/구분자/앞0보존)·brandNm원문·normalized_name·indutyLclasNm/indutyMlsfcNm만사용한다. 법인/대표자/사업자정보는정규화목록/대조에사용하지않는다. NFKC·casefold·연속공백1칸/양끝공백제거만하고지점명/구두점/법인표시삭제·부분일치·거리유사도·LLM판정은없다. 브랜드/본부복합키중복은원문이같아도실패하고브랜드번호단독반복은전부보존/격리한다(§8~9의실제원천/Claude추가검토). hash는복합키정렬의정규화명시필드/규칙v2기준이다.

정확상호후보는전체목록에서정규화명이유일하고외식대분류이며이름의문자/숫자3자이상·숫자만아닌경우다(실제공식분류값을1페이지표본으로대조). 짧은일반명/비외식/복수관리번호는검토대상또는미일치로둔다. **유일한이름이라도가맹점확정이아닌대조후보**다. 역사점포도현재브랜드목록과이름대조할뿐과거소속을확정하지않는다. 브랜드업종과SpotON세부업종이동일하다고가정하지않는다.

--compare-local만기존Settings/로컬spoton_dev·일반앱role/head0010검사후READ ONLY REPEATABLE READ로지원업종/삭제없음/검토대기아님점포를스트리밍조회한다. SQL명령60초/잠금5초의기존ETL제한을쓴다. 점포상호는외부에전송하지않는다. 원본/필드갱신·분류false생성·새DB테이블은없다. 기존판정값/brand_id가있는점포는별도보존카운터로분리한다. 결과는총대조대상·기존판정보존·상호결측·약한이름·정확후보·모호한이름·비외식/미일치등서로배타적건수만반환한다. population/매출과연결하지않는다.

## 5. CLI·검증·완료

`python -m etl.brands --year 2025 --output <저장소밖새snapshot.json> [--compare-local]`와`--snapshot <기존snapshot.json> [--compare-local]`를제공한다. snapshot모드에서는키/HTTP가필요없다. 소스완료파일은후속DB대조실패에도보존하며전체실행실패를구분한다. stdout JSON1건·성공0/실패1·고정오류/인자오류2·help0/Ctrl+C130, canary비노출. source=brands를기존ETL로그허용source에추가하되기존source이벤트형식은유지한다. collect/read_source/prepare와새save_snapshot단계를사용하며마지막은파일저장완료이고DBpersist와구분한다.

단위: mock transport실제client·인증인코딩·페이지/연도/rowcount/total/중복관리번호/공급자실패·키누락·크기·snapshot변조/재실행/기존파일/저장실패·정규화/동명충돌/단순부분일치비허용·safeCLI/로그·offline무호출. 격리PostGIS: 지원대상선택·기존판정보존·이름대조분할·READ ONLY RR·쓰기거절·전후전체행hash·오류/정리. 실제API2025전체수집·offline replay contenthash/건수일치·실제dev읽기전용전체점포대조·stores/배치/14기존테이블전체hash·원본보존·head0010·FE0변경. 기존일반/격리전체·ruff/format/mypy·staged비밀검사, Ref#57지정PR·CI/CodeQL후develop정상Squash. 이슈57의실제분류조건은미완료로유지한다.

## 6. Claude 실제 설계 검토

이문서와지정BE소스만Read하고이절만Edit한다. .env/DB/raw/네트워크/Bash/Git/FE·구현수정/다른에이전트금지. 전체BE-21의원천기반과판정적용분리가일관된지·완전수집/원문개인정보보호·snapshot실패경계·정확이름후보의과대해석·미확인보존·테스트누락을검토한다. 실행/인증을직접확인했다고주장하지않는다.

### 6.1 검토 범위와 한계

- 2026-11-12 Claude Code가 이 문서와 지정 소스 6개(etl/localdata/repository.py·client.py·runner.py, app/models/store.py, app/ai/context.py, app/schemas/ai_context.py)만 Read했다. pipeline.py(StoreRecord 필드)·snapshot.py·operations.py·nearby/risk 서비스·.gitignore·.env·DB·원천 응답은 읽지 않았다. 따라서 아래에서 그 파일에 의존하는 판단은 "미확인"으로 표시한다.
- 코드 실행·테스트·API 호출·인증·DB 조회를 하지 않았다. 1절의 실제 1행 사전 호출 결과(HTTP200·11,167건)는 Codex 기록이며 Claude가 재확인하지 않았다.
- 결론: **이번 PR을 막는 설계 결함은 없다.** 단, 6.3의 "구현 전 확정" 항목은 구현 착수 전에 문서에서 결정해야 한다.

### 6.2 단계 경계(원천 기반 vs 실제 분류)의 일관성

- 일관됨: repository.py의 UPDATE_COLUMNS에 `is_franchise`/`brand_id`가 없으므로 인허가 재적재(ON CONFLICT UPDATE)가 이 두 필드를 덮지 않는다. 1절의 "재적재가 외부 소유 가맹 필드를 보존"이라는 전제는 기존 UPDATE 경로에서 소스와 일치한다.
- 미확인: 신규 INSERT는 `asdict(StoreRecord)` 전체를 payload로 쓴다. StoreRecord에 is_franchise/brand_id가 포함되는지, 포함된다면 항상 None인지 pipeline.py를 읽지 않아 확인하지 못했다. 다음 판정 단계 설계 전 Codex가 확인해야 한다(이번 PR은 쓰기가 없으므로 차단 사유 아님).
- 일관됨: app/ai/context.py는 Risk meta의 `franchise_classification={"status":"pending","reason":"brand_mapping_blocked"}`를 정확 일치로 요구하고, RiskInterpretContext도 `franchise_classification: Literal["pending"]`이다. 이번 PR이 stores/meta/AI/캐시를 바꾸지 않으므로 이 고정값과 충돌하지 않는다. 반대로 다음 단계에서 판정을 활성화하면 Risk meta·context 검증·프롬프트·캐시 key·FE 요청서를 **같은 변경에서 함께** 바꿔야 하며, 일부만 바꾸면 AI 준비가 500(INTERNAL_ERROR)으로 실패한다. 1절의 "함께 설계" 문구가 이를 뜻함을 명시 권장.
- 다음 단계 모델 경고(이번 PR 비차단): `Store.is_franchise`는 nullable Boolean뿐이다. 2절 사용자 결정의 "추정 / 미확인 / 별도 근거 있는 비프랜차이즈"와 근거(source·rule_version·snapshot content hash)를 표현할 수 없다. 특히 "정확 후보 미일치"를 `False`로 쓰면 독립점포로 오분류된다. 다음 단계에서 상태 enum+근거 컬럼 또는 별도 판정 테이블을 설계하고, `brand_id`(현재 FK 없음 BigInteger)의 참조 대상도 함께 정해야 한다. 이번 PR의 "분류 false 생성 없음"은 올바르다.
- ContextFilters는 `franchise=franchise|independent` 필터를 이미 허용한다. 현재 판정값이 없는 상태에서 이 필터의 결과 의미는 기존 서비스(미열람) 계약을 따르며 이번 PR은 바꾸지 않는다. compare-local 결과 수를 이 필터의 기대 결과로 설명하지 말 것.

### 6.3 구현 전 확정 필요(발견 사항)

1. **재시도 정책 명시.** 3절은 "숨은 재시도 없음"이나 기존 LocalDataClient는 429/502/503/504·transport 오류를 최대 3회 재시도한다. 기존 client를 재사용/모방하면 계약과 달라진다. (a) 재시도 0회·첫 실패 즉시 고정 코드 실패, 또는 (b) 제한된 재시도를 허용하되 시도 횟수를 stdout에 공개(숨기지 않음) 중 하나를 문서에 명시한다. Claude 권장: (b) 최대 3회·Retry-After 상한 재사용·`request_count` 출력. 어느 쪽이든 동일 페이지 재요청 결과도 전체 검증을 다시 통과해야 한다.
2. **병렬 수집 금지 명시.** 기존 client는 workers 1~4 병렬이다. 원천이 요청 사이에 바뀌는 경우의 판별을 단순하게 하기 위해 브랜드 수집은 순차(workers=1) 고정을 권장한다.
3. **페이지 일관성의 남는 구멍.** totalCount 불변·관리번호 중복 거절은 삽입/삭제에 따른 행 밀림의 대부분을 잡지만, "같은 시간대에 1건 삭제+1건 추가"가 서로 다른 페이지에서 일어나면 중복 없이 건수가 맞는 **혼합 snapshot**이 될 수 있다. 완화안: 마지막 페이지 후 1페이지를 다시 받아 정규화 hash/total 일치를 확인하거나, 이 한계를 snapshot 의미(한 시점 일관성 아님)로 문서화한다. 정렬 기준이 원천에서 보장되지 않는다는 점도 같이 기록한다.
4. **응답 shape 세부.** (a) 응답의 `numOfRows`가 요청 1000과 다르면(공급자 상한 축소) 페이지 수 계산을 응답값으로 바꾸지 말고 실패. (b) 마지막 페이지 길이는 `total-(pages-1)*1000`과 정확히 같아야 하고 중간 페이지는 정확히 1000. (c) data.go.kr 게이트웨이가 인증/한도 오류를 HTTP200 XML로 돌려주는 경우를 content-type·JSON 파싱 단계에서 구조 오류로 실패(기존 client의 `non_json_response` 방식 재사용). (d) `brandMnno`가 JSON 숫자로 오면 앞 0이 이미 소실되므로 문자열 아닌 값은 변환하지 말고 구조 오류로 거절한다(실제 타입은 전체 snapshot에서 확인). (e) 요청 연도와 행의 연도 필드 불일치는 실패.
5. **외식 대분류 판정 근거.** 4절은 대분류 값을 "1페이지 표본으로 대조"한다. 1페이지는 전체 분류 값 집합을 보장하지 않는다. 전체 snapshot의 대분류/중분류 고유값별 건수(이름 없이)를 출력하고, 허용 목록 밖의 미지 대분류가 나오면 실패 또는 별도 카운터로 분리하도록 확정한다.
6. **이름 유일성의 범위.** "정규화명이 유일"은 외식 행 안이 아니라 **전체 업종 목록** 기준이어야 한다(외식+도소매 동명 브랜드를 외식 유일로 오판 방지). 문서에 명시 권장.
7. **배타 카운터의 우선순위.** 기존판정보존 > 상호결측(null·공백만·정규화 후 빈 문자열) > 약한이름 > 모호(복수 관리번호/전체 업종 중복) > 비외식 > 정확후보 > 미일치처럼 평가 순서를 고정하고 `합계 == 총 대조 대상`을 코드 불변식으로 검사한다. 순서가 없으면 같은 snapshot에서도 구현마다 수가 달라진다.
8. **output 경로 검증.** "저장소 밖"을 문서 약속이 아니라 코드로 강제한다: resolve(심볼릭 링크 포함) 후 저장소 ROOT 하위면 인자 오류. 참고로 기존 localdata runner는 `ROOT/datasets/localdata` 안에 snapshot을 저장하므로 그 패턴을 재사용하면 안 된다(해당 경로의 .gitignore 여부는 미확인).
9. **원자적 신규 생성.** Windows의 `os.replace`는 기존 파일을 덮는다. 최종 경로를 배타 생성(`x` 모드/O_EXCL)으로 직접 쓰고 실패·KeyboardInterrupt 시 이번에 만든 파일만 삭제하거나, 같은 디렉터리 임시 파일→기존 파일 존재 시 실패하는 rename을 사용한다. 강제 종료로 남은 반쪽 파일은 offline 재검증(크기/pages hash/content hash)이 거절해야 하며 이를 테스트한다.
10. **persist 단계 의미 충돌.** 기존 ETL 로그(BE #72)에서 persist 완료는 DB commit 이후다. brands에서 persist=파일 저장으로 재사용하면 같은 이름의 단계가 다른 의미가 된다. 단계명은 유지하되 brands 이벤트에 `mode`(collect_api|snapshot_replay)·`compare_local` 여부를 함께 기록하고 문서에 "DB 쓰기 아님"을 명시하거나, 허용된 단계 enum 안에서 더 정확한 이름을 쓴다.
11. **부분 성공 출력.** "snapshot 저장 성공 + compare-local 실패"는 exit1이되 stdout JSON에 `snapshot_saved=true`·snapshot content hash 앞자리·실패 단계 고정 코드를 포함해 운영자가 재수집 없이 `--snapshot` 재실행하도록 한다. 반대로 저장 실패 시 compare-local을 실행하지 않는다.
12. **replay와 규칙 버전.** content_sha256은 정규화 규칙 버전에 묶인다. offline 모드는 저장된 hash를 신뢰하지 말고 raw pages에서 재계산하며, 저장 snapshot의 rule_version이 현재 코드와 다르면 조용히 재계산하지 않고 고정 코드(`rule_version_mismatch`)로 실패한다. 크기 제한 200MiB가 base64 인코딩 후 파일 크기인지 디코딩 body 합인지도 명시한다.
13. **인증키 디코딩.** encoding 키 판별 후 `unquote`(not `unquote_plus`)를 1회만 적용한다. 판별 기준(`%` 포함 여부)을 문서에 적는다.

### 6.4 이름 대조 결과의 해석 한계(과대해석 방지)

- 정확 후보는 "현재 공정위 정보공개서 목록에 같은 정규화 상호가 하나뿐"이라는 사실만 뜻한다. 가맹계약·브랜드 소속·개업 당시 소속을 뜻하지 않는다(4절과 일치).
- **미일치는 독립점포 수가 아니다.** 지점명이 붙은 상호("○○ 강남점")는 정확 일치 규칙상 미일치가 되므로 미일치에는 실제 가맹점이 다수 섞일 수 있다. stdout 키 이름도 `independent` 같은 표현을 쓰지 말고 `no_exact_candidate` 류로 한다.
- 반대로 우연히 브랜드명과 같은 개인 상호도 후보가 된다. 3자 규칙은 이를 줄일 뿐 제거하지 않는다. 후보 수를 "프랜차이즈 점유율"로 보고·문서화하지 않는다.
- 역사 점포(폐업 포함)를 2025년 목록과 대조한 결과는 과거 소속 판정이 아니다. 카운터를 영업/폐업 상태로 나눠 보고하면 다음 단계에서 이 한계를 판단하는 데 도움이 된다(이름 없이 건수만).

### 6.5 개인정보·비밀값

- 원문 snapshot에는 공개 대표자명·사업자번호가 있을 수 있다. 저장소 밖 로컬 보관·커밋/LLM/Claude 전송 금지 계약은 적절하다.
- `corpNm`(법인/가맹본부명)은 개인사업자 가맹본부에서 사실상 개인 이름일 수 있다. 정규화 목록에 남기더라도 stdout·로그·오류·대조 결과에 절대 넣지 않고, 대조 로직에 쓰지 않는다면 정규화 행에서 제외하는 것을 권장한다.
- httpx 예외 문자열에는 serviceKey가 포함된 요청 URL이 들어갈 수 있다. 기존 runner처럼 예외 클래스명·고정 코드만 출력하고 `str(error)`/`repr`를 출력·로그하지 않는다. snapshot에도 요청 URL·params를 저장하지 않는다(3절의 고정 endpoint만).
- compare-local은 점포 상호를 메모리에서만 쓰고, SQL 오류·검증 오류 메시지에 상호가 포함되지 않도록 한다. 카운터만 출력한다.

### 6.6 테스트 누락(5절 목록에 추가 권장)

- HTTP200 + XML/비JSON 게이트웨이 오류, 응답 numOfRows≠요청값, 중간 페이지 999행, 마지막 페이지 과다/부족, totalCount 중간 변경, 요청 연도≠행 연도, brandMnno 숫자/공백/앞0.
- 삭제+추가 혼합으로 중복 없이 건수만 맞는 경우(6.3-3 완화안 채택 시 거절, 미채택 시 문서화된 한계 테스트).
- 재시도 정책(채택안) 경계: 재시도 횟수 출력, 상한 초과 실패.
- 전체 업종 기준 이름 유일성, NFKC/casefold 경계(전각 문자·`ß`·호환 자모), 공백만 있는 상호, 정규화 후 빈 문자열, 미지 대분류 값.
- 배타 카운터 합계 불변식, 기존 is_franchise/brand_id 보유 행이 다른 카운터에 중복 집계되지 않음.
- output이 저장소 내부·심볼릭 링크 경유일 때 거절, 기존 파일 존재, 동시 두 실행의 같은 output, KeyboardInterrupt 중 정리, 반쪽 파일 offline 거절.
- snapshot 저장 성공+compare-local 실패(head 불일치 등)의 exit1·snapshot_saved 출력·파일 보존, 저장 실패 시 compare-local 미실행.
- offline 모드에서 키 미설정 환경·httpx client 미생성, rule_version 불일치 거절, 저장 hash 위조(raw는 정상) 거절.
- canary 대표자명/사업자번호/corpNm/brandNm/점포 상호/serviceKey가 stdout·stderr·운영 로그·예외 출력에 없음.
- 회귀: 기존 Risk meta의 `brand_mapping_blocked`, AI context `franchise_classification=pending`, 인허가 재적재의 is_franchise/brand_id 보존(UPDATE 경로)이 그대로인지.

### 6.7 보류(이번 PR 범위 밖, 다음 단계 설계 입력)

- 판정 상태 모델(추정/미확인/근거 있는 비프랜차이즈)·근거 provenance·brand_id FK·별칭 검토 절차.
- 판정 활성화 시 Risk meta·AI context/프롬프트·캐시 key·FE 요청서 동시 변경.
- StoreRecord INSERT 경로의 is_franchise/brand_id 기본값 확인(6.2 미확인 항목).
- 연도별 목록 차이와 과거 점포 소속 판단 방법, 월1회 갱신 운영.

## 7. Codex 최종 결정·실행 결과

Claude 실제 지정 소스6개 Read/MD §6 Edit를 확인하고 소스와 최종 대조했다. 단계분리를 수용한다. 이번 PR은 원천/읽기전용 대조를 완료하고 #57 실제 분류는 다음 단계로 유지한다. 구현 전 지적은 다음처럼 확정한다.

- 재시도0회·순차1worker·연도대체없음. HTTP시도건수request_count를반환한다. 마지막에1페이지를추가호출해정규화내용/총계일치를재확인하고그응답도verification_page로보존한다. 그래도다른페이지의동시변경/원천정렬비보장은검출하지못할수있으며공급자의단일시점snapshot이라고주장하지않는다.
- snapshot에는rule_version을포함하고불일치거절한다. 최대200MiB는base64포함JSON파일기준, raw응답합계140MiB도제한한다. 원문외corpNm은정규화/후보대조에서제외한다. 전체카탈로그대분류3종(외식/서비스/도소매)을실제1,000행응답으로확인했고미지대분류는계약오류로중단한다. 업종별통계는고정대분류건수만출력하고중분류명/상호를로그에넣지않는다.
- 전체업종목록기준동명이중복이면모호후보다. 기존판정보존→상호결측→약한이름→모호→비외식→정확후보→미일치의배타우선순위를쓴다. 지원점포전체와분할합계를대조한다. 3자기준은정답판정이아닌초기후보배제규칙이다.
- 저장경로는resolve후BE/FE포함workspace안이면거절한다. 최종파일은xb로신규생성하고실패/KeyboardInterrupt에는이번생성파일만정리한다. 강제종료시미완료파일은offline검증실패로남을수있다. raw/shapshot repr를숨긴다.
- DB쓰기와혼동되는persist단계대신새Stage `save_snapshot`을사용한다. source=brands의stage명만추가하고기존이벤트형식/다른source는유지한다. stdout mode=collect_api|snapshot_replay, compare_local·snapshot_saved·request_count를반환한다. 후속DB실패는고정오류/snapshot_saved=true·실패단계를남기고수집완료파일을보존한다.
- API사전호출1,000행은중간집합관찰이며전체수집완료가아니다. 페이지/관리번호문자열·업종·연도·hash/규칙·timestamp·기존파일/보존·동시생성·후속실패·canary검사를구현하고기존메타/AI pending을유지한다. 실제검증은아래추가한다.

실제수집초기검증에서관리번호를숫자문자열로만제한한Codex가정이틀렸음을확인했다. 실제문자열은영문접두사·밑줄·숫자를포함한다. 공식필드는문자열식별자이므로정수로변환하지않고대소문자/구분자/앞0를그대로보존한다. 허용형식은ASCII영숫자로시작하는영숫자/밑줄/하이픈64자이하이며, 숫자JSON타입/공백/빈값은계속거절한다. 해당회귀를추가하고전체실행을다시검증한다.

## 8. 실제 원천의 관리번호 반복·Claude 추가 검토

전체12페이지/11,167행·첫페이지재확인을수행했으나브랜드관리번호단독중복으로완료snapshot생성을중단했다. 원문은저장소밖unvalidated형식/검증실패표시로별도보존했다. 집계만확인한결과관리번호11,154개중13개가2행씩있고,13그룹모두페이지를가로지르며jnghdqrtrsMnno가다르다. 원문완전동일그룹은0, 기존정규화필드동일그룹9, 브랜드명상이4다. 입력행을삭제/합산하거나실제소속으로확정하지않는다.

Codex제안: 정규화행에가맹본부관리번호를추가해원천(기준년,브랜드번호,본부번호)을그대로보존하고복합키중복은계속실패한다. 브랜드번호반복13개는quality카운터로분리하고그번호와관련된점포상호는이름이유일해도ambiguous_name으로둔다. 전체11,167은브랜드고유개수가아닌원천행수다. snapshot규칙은미출시v1개발중이므로정규화항목을추가하며기존API/실제분류는pending이다. 원천의단일번호가유일하다는가정을폐기하는보수적취급정책이며법적브랜드소속/본부이전등의공식해석이아니다. 별도공식답변을얻기전판정활성화에는사용하지않는다.

Claude는이MD·catalog.py·compare.py·tests/etl/brands_helpers.py·익명집계brand57-duplicate-summary.json만Read하고아래결과문단만Edit한다. 원본경로/파일·키/.env/DB/네트워크/Bash/Git/다른파일/agents금지.

추가검토결과(2026-11-12 Claude Code, 지정 5개 파일 Read·이 문단만 Edit, 코드/테스트 실행·원문 열람 없음): **조건부 수용.** 집계상 13개 반복 그룹 모두 jnghdqrtrsMnno가 다르므로 (기준년,브랜드번호,본부번호) 복합키는 이번 원천 행 11,167건을 삭제·합산 없이 구분할 수 있고, 복합키 중복은 계속 실패시키는 것이 맞다. 반복 브랜드번호의 모든 관련 이름을 정확 후보에서 빼는 것은 후보를 줄이는 방향뿐이며 compare.py는 카운터만 반환하고 쓰기가 없으므로 READ ONLY 기반에서 안전하다. 현재 compare.py에서도 정규화 필드 동일 9그룹은 같은 이름이 2행이 되어 이미 ambiguous_name이 되지만, 브랜드명이 다른 4그룹은 각 이름이 1행이라 격리 규칙 없이는 exact_name_candidate가 될 수 있다. 따라서 명시적 격리가 필요하다. 반복 사실은 원천 행의 관찰일 뿐이다. 공급자 의미(본부 변경·공동 운영·입력 오류·수집 중 변경 등)나 실제 브랜드 소속은 추정하지 않는다. 13그룹이 모두 페이지를 가로지른다는 점도 원천 측 반복과 수집 중 변경을 구분하지 못하며, 격리는 두 경우 모두에 보수적이다.

- 차단(구현 전 필수): (1) catalog.py의 `len({management_no}) != total` 검사를 복합키 집합 크기 검사로 바꾸고, 복합키 중복은 기존처럼 실패시킨다. (2) jnghdqrtrsMnno는 brandMnno와 같은 엄격 계약을 적용한다(문자열·허용 형식·빈값/공백/JSON 숫자 거절). null·누락을 허용하면 복합키가 (번호,null) 중복을 숨기므로 실패로 둔다. (3) 정규화 정렬·content_hash·첫 페이지 재확인 비교를 모두 `(management_no, 본부번호)` 복합 정렬로 바꾼다. 현재 management_no 단독 정렬은 반복 번호에서 입력 순서에 의존하므로 같은 원천이 다른 hash가 될 수 있다. (4) 정규화 행 구조가 바뀌므로 RULE_VERSION을 올린다(예: `-v2`). 완료 v1 snapshot이 없다는 사실에만 기대어 같은 버전명에 두 가지 hash 의미를 두지 않는다. (5) 저장소 밖에 보존한 unvalidated 실패 원문은 `--snapshot` offline 모드가 완료 snapshot으로 받아들이지 않도록 형식/표시로 거절한다.
- 조건: (a) 격리는 반복 번호의 **모든 행의 정규화명 집합**으로 계산하고, 그 이름과 일치하는 점포는 다른 후보 유무와 무관하게 정확 후보에서 제외한다. (b) 배타 순서를 고정한다. 권장: 기존판정보존→상호결측→약한이름→`repeated_brand_id`(신규 배타 칸)→ambiguous_name→비외식→정확후보→미일치. ambiguous_name에 합치려면 비배타 보조 카운터라도 분리해 "동명 다른 번호"와 "같은 번호 반복"이 섞이지 않게 한다. 합계=총 대상 불변식은 유지한다. (c) summary/stdout에는 rows(원천 행 수)·unique_brand_ids·repeated_brand_ids·repeated_rows만 넣는다. 11,167을 브랜드 수로 표기하지 않으며 브랜드번호·본부번호·이름·brno/crno/corpNm은 출력·로그에 넣지 않는다. 기존 `ambiguous_names` 요약은 반복 번호의 동명 행 때문에 늘어날 수 있으므로 의미를 문서화하거나 고유 번호 기준으로 분리한다. (d) 본부번호는 키/격리에만 쓰고 이름 대조·판정 근거로 쓰지 않는다. 대표자·사업자번호는 계속 제외한다. (e) 격리 대상 수와 정확 후보 감소분은 실제 프랜차이즈 판정이 아니며 다음 단계의 판정 활성화 근거로 쓰지 않는다(본문 제안과 일치).
- 테스트(brands_helpers.item에 본부번호 필드 추가 후): 같은 브랜드번호·다른 본부번호 2행 허용과 페이지 간 배치. 같은 복합키 2행 실패. 본부번호 누락/null/빈값/공백/숫자 타입 실패. 페이지 순서를 바꿔도 같은 content_hash. 같은 번호·같은 정규화명(9그룹형)과 같은 번호·다른 이름(4그룹형) 모두 정확 후보 0과 지정 칸 집계. 반복 번호 이름이 외식/비외식에 걸친 경우의 순서. 반복 번호 이름과 무관한 유일 이름의 정확 후보 유지. 파티션 합계 불변식. 요약 카운터 값과 식별자/이름 canary 비노출. 이전 rule_version snapshot 거절과 unvalidated 파일 offline 거절.
- 권고: 위 차단 5개를 반영하면 이 READ ONLY 기반에 채택해도 된다. 반복 원인의 공식 확인 전에는 격리를 해제하거나 반복 번호를 하나로 고르는 규칙을 만들지 않는다. 다음 수집에서도 반복 수가 달라질 수 있으므로 수치를 고정 기댓값으로 테스트하지 말고 계약 동작만 검증한다.

## 9. 최종 실행 검증

Claude 추가검토7턴·오류/permission_denials0를확인하고5개필수조건을수용했다. 정규화행의본부문자열식별자·복합키유일성/정렬/첫페이지대조·규칙v2·실패원문의완료snapshot거절을구현한다. 반복브랜드번호이름은별도배타칸repeated_brand_id로분리하고기존판정/상호결측/약한이름다음에판정한다. 전체업종범위의일반동명모호와구분하며원천행수/고유브랜드번호수/반복번호수/해당행수만보고한다. 공급자정의/법적소속은추론하지않는다.

### 9.1 실행 결과

- 신규단위55·격리5와전체일반1,331·격리PostGIS189를통과했다. ruff check/format309파일·strict mypy147파일이통과했고기존Starlette경고1건만남았다. 실제source키형식오판수정·복합키/반복격리·원천/숫자/페이지/중복/변조·원본순서무관hash·파일동시신규생성/실패정리·후속DB실패보존·safeCLI/로그·offline무HTTP·READ ONLY쓰기거절·지원대상/기존분류필드보존을검사했다.
- 2025원천11,167행을12페이지+첫페이지재확인1회=13HTTP요청으로수집했다. 고유브랜드번호11,154·반복13개/26행, 정규화동명그룹44개다. 외식8,873·서비스1,775·도소매519행이며고유브랜드/가맹점수가아니다. 실제완료시각은2026-11-12T06:51:54.212366+00:00이며원천공표/업데이트시각과구분한다.
- 지원업종355,835점포대조: 기존판정보존0·상호결측0·약한이름33,601·반복번호관련12·일반동명모호474·비외식126·정확상호후보6,839·미일치314,783이다. 분할합계일치, source의반복번호13개가실제점포13개를뜻하지않는다. 후보6,839도브랜드소속/현재영업가맹점/과거가맹계약판정이아니다.
- 실제무HTTPoffline replay의카운터/contenthash와snapshot파일SHA256이같다. 별도전후QA에서기존14테이블전체행·공간NDR EWKB포함hash/건수/head0010이같았다. 초기QA의to_jsonb(geometry)는60초시간초과로실패해검증script만공간열EWKB문자열직접hash로고쳤고, 최종수집+대조10.172초·전후QA/replay포함33.312초를통과했다. 특정실행결과이며API/운영SLA가아니다. 앱SQL/기본3초·기존ETL60초는바꾸지않았다.
- 정규화snapshot/검증실패unvalidated원문은저장소밖로컬파일로보존하며키/원문/개인정보/환경/검증helper·결과는커밋하지않는다. 실제DB에DML/DDL/migration/VACUUM·새브랜드판정·실LLM전송을하지않았다. FE변경0·사용자미추적분석문서변경0이다. 테스트용별도PostGIS만작업소유container/UUID DB로격리했다.

### 9.2 현재 완료와 후속

원천기반CLI/원문보존·재검증·품질분리·읽기전용대조는완료다. source의단일시점일관성/반복원인의공식의미·실제점포소속/역사적유효성은확정하지않는다. 다음단계에서모델/판정근거·alias검토·기존외부필드보존/무효화·API/AI/캐시·FE요청서를함께설계한다. currentAPIfranchiseunknown/pending을바꾸지않으며#57은열린상태로유지한다. README/BE CLAUDE/작업계획/BE측활동요청서의승인상태를동기화하고Ref#57PR·모든CI/CodeQL성공후develop정상Squash한다. 실제병합상태는연결PR을따른다.
