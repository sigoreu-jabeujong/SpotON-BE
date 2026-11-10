# 작업 7: 층·호수 상세 위치 정규화

## 상태와 범위

- 이슈: [#19 층·호수 상세 위치 정규화 구현](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/19)
- 브랜치: `feat#7-floor-unit-normalization`, 대상 브랜치: `develop`
- canonical 작업: BE-10
- 목적: 도로명·지번 상세 주소에 명시된 층·호수만 정규화해 `stores.floor_unit`과 위치 신뢰도 `location_level`을 일관되게 저장한다.
- 포함:
  - 도로명주소와 지번주소 각각에서 명시적 층·호수 표기 추출
  - `1층`, `2층 201호`, `지하 1층`, `B1`, `162C호`의 canonical 표기
  - 두 주소 원천의 일치·충돌 판정과 `same_spot`·`same_building`·`unverified` 저장
  - LocalData ETL·upsert 연결, 단위 테스트와 CI 임시 PostGIS 통합 검증
- 제외:
  - 도로명주소를 지번으로 변환하는 외부 API, BE-11 `/api/geocode`
  - 점포 이력 API의 개별 레코드 간 `location_match` 계산
  - 건물명/층호 정보가 없는 주소에 대한 추측, OCR·상호명 기반 보완
  - 실제 개발 DB 적재·backfill·migration 변경

실제 개발 DB 없이 순수 파서·샘플 ETL·폐기형 CI PostGIS까지 검증한다. 실제 원천 적재 전에 플래그별 실패율과 도로명·지번 충돌률을 dry-run으로 확인해야 한다.

## 핵심 계약

### 1. 저장값과 위치 신뢰도

`floor_unit`은 사람이 읽을 수 있는 다음 canonical 문자열만 저장한다.

| 원본 예시 | `floor_unit` | `location_level` (building_key 있음) |
|---|---|---|
| `1층`, `1 층`, `1F`, `제1층`, `지상1층`, `01층` | `1층` | `same_building` |
| `지하 1층`, `지하1층`, `B1`, `B1층`, `B1F` | `B1` | `same_building` |
| `2층 201호`, `2F 201호`, `제2층 제201호`, `2층-201호` | `2층 201호` | `same_spot` |
| `162C호`, `162c호` | `162C호` | `same_building` |
| `지하1층 B101호`, `B1 b101호` | `B1 B101호` | `same_spot` |
| 층·호수 없음, 둘 이상의 상세 위치, 범위·목록(`1~2층`, `1,2층`, `1-2층`, `201~203호`), 단지 내 동 표기(`101동`, `A동`), 두 원천 충돌 | `null` | `unverified` |

- `location_level`의 저장 enum은 `LocationLevel(StrEnum)`의 `same_spot`, `same_building`, `unverified` 세 값뿐이다. ETL이 쓰는 레코드에는 항상 세 값 중 하나를 저장하고 NULL을 쓰지 않는다.
- **enum 근거**: BE 기준 문서 5절 "건물·상세 위치 정규화"가 확인 불가 시 `floor_unit = null`, `location_level = unverified`를 직접 지정하고, 상세 주소 충돌·호수만으로는 `same_spot`으로 판정하지 않도록 정한다. 나머지 두 값은 같은 절과 6절 BE-12 `location_match` 값 집합에 맞춰 추가한 것이다. 원본 API 명세 v1.2가 저장소에 없으므로 이 값 집합이 외부 계약과 일치하는지는 확인 대기다(잔여 제한 참고). 별도 이름(예: `floor_and_unit`/`floor_or_unit`/`none`)도 검토했지만, 기준 문서가 이미 `unverified`를 저장값으로 지정했고 stores 컬럼이 존재하므로 이번 작업에서 이름을 바꾸지 않는다.
- building_key가 있어도 상세 위치가 없으면 `unverified`다. 따라서 `unverified`는 "건물 미상"과 "건물은 알지만 상세 위치 없음"을 모두 포함하며, 둘의 구분은 `building_key IS NULL`로 한다.
- BE-10 이전 ETL이 쓴 기존 행은 `location_level IS NULL`일 수 있다. 재적재 전까지 읽는 쪽(BE-12 등)은 NULL을 `unverified`와 같게 취급해야 하며, 이 작업은 backfill하지 않는다.
- **이 값은 레코드 하나의 상세 위치 표기 정밀도 상한이지, 다른 레코드와 같은 자리라는 판정이 아니다.** `same_spot`은 "층과 호수가 모두 명시되어 같은 자리 비교 후보가 될 수 있음", `same_building`은 "건물 키는 있고 층 또는 호수 하나만 명시됨"을 뜻한다. 레코드 간 같은 자리 판정은 BE-12가 building_key·floor_unit 동일성으로 따로 하며 이 값을 그대로 `location_match`로 반환하지 않는다.
- `same_spot`은 층과 호수가 모두 명시된 경우에만 저장한다. 호수만으로 `same_spot`을 주장하지 않고, 호수 숫자에서 층을 추정(`301호` → `3층`)하지 않는다. 층과 호수 숫자가 어긋나 보여도(`2층 301호`) 원문대로 두고 보정하지 않는다.
- 층만 또는 호수만 명시된 경우는 건물 내부의 상세 위치를 확정할 수 없으므로 `same_building`이다.
- `building_key`가 null이면 floor_unit 파싱 성공 여부와 무관하게 `location_level=unverified`다. 건물을 특정하지 못했는데 `same_building`·`same_spot`을 주장하지 않는다. 이때 파싱된 `floor_unit`은 저장하되 위치 신뢰도로 쓰지 않는다. 이 결합은 pipeline에서 하고 순수 파서는 building_key를 알지 못한다(파서의 `FloorUnitValue.location_level`은 "building_key가 있다는 전제의 상한"이다).
- 주소 원천에 상세 위치가 없거나 모호·충돌하면 `floor_unit=null`, `location_level=unverified`로 최신 ETL 결과를 반영한다. 과거 값과 `COALESCE`하지 않는다.
- `location_level`은 후속 BE-12의 API 반환 `location_match`와 이름이 같은 값을 쓰지만, 이 작업에서는 **각 원천 레코드의 상세 위치 신뢰도**만 저장한다. 레코드 간 비교 로직은 구현하지 않는다.
- 저장값은 이 문서가 정의한 표기 변형(공백·전각/반각·대소문자·`제`/`지상` 접두·허용된 `층-호` 구분·층호 순서)에 대해 같은 결과가 되며(결정성; 정의되지 않은 표기의 의미 동등성까지 보장하지 않음), canonical 값을 다시 파싱하면 같은 값이 된다(멱등성). 주소 원문·건물명은 포함하지 않는다.

### 2. 순수 파서

`etl/address/floor_unit.py`에 외부 I/O·로그 없는 순수 모듈을 만든다.

```python
class LocationLevel(StrEnum):
    SAME_SPOT = "same_spot"
    SAME_BUILDING = "same_building"
    UNVERIFIED = "unverified"


class FloorUnitFailure(StrEnum):
    EMPTY = "empty"
    NO_DETAIL = "no_detail"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FloorUnitValue:
    floor: str | None = field(repr=False)
    unit: str | None = field(repr=False)

    @property
    def value(self) -> str: ...

    @property
    def location_level(self) -> LocationLevel: ...  # SAME_SPOT 또는 SAME_BUILDING만


@dataclass(frozen=True, slots=True)
class FloorUnitResult:
    value: FloorUnitValue | None = field(repr=False)
    failure: FloorUnitFailure | None


def parse_floor_unit(address: str | None) -> FloorUnitResult: ...
def reconcile_floor_units(
    road: FloorUnitResult,
    jibun: FloorUnitResult,
) -> FloorUnitResult: ...
```

- `FloorUnitResult`는 성공과 실패 중 정확히 하나만 가진다(`__post_init__`에서 검증). `FloorUnitValue`는 `floor`·`unit` 중 하나 이상이 non-None이어야 하며 각 값이 아래 canonical 문법을 만족하지 않으면 생성 시 값 없는 `ValueError`다.
- `None`, 빈 문자열·공백만 있는 문자열은 `EMPTY`, 상세 위치 토큰이 전혀 없는 정상 주소는 `NO_DETAIL`이다. pipeline 집계에서는 두 값을 구분해 센다. 비 `str` 입력은 입력값을 메시지에 넣지 않는 `TypeError`다. pipeline은 `str | None`만 전달하므로 정상 ETL에서 이 예외는 발생하지 않아야 한다.
- canonical `floor`는 `B` + 1~3자리 ASCII 숫자(지하) 또는 1~3자리 ASCII 숫자 + `층`(지상) 중 하나다. 층 숫자의 앞자리 0은 제거한다(`01층` → `1층`). 지상 `0층`, 지하 `B0`, 음수·소수·4자리 이상은 `INVALID`다.
- **범위·나열 판정(단일 규칙)**: 공백 없는 한 chunk가 `~`·`,`·`/`·`·`·`-`로 이어진 2개 이상의 조각이고, 마지막 조각만 층(`N층`/`NF`) 또는 호(`N호`) 토큰이며 앞 조각이 모두 같은 종류의 숫자(층은 1~3자리, 호는 canonical unit 문법에서 `호`를 뺀 형태)이면 둘 이상의 층·호실을 뜻하므로 `AMBIGUOUS`다(`1~2층`, `1,2층`, `1/2층`, `1-2층`, `1·2층`, `201~203호`, `201,202호`). **예외: 호수의 하이픈(`101-1호`)은 지번식 호실 표기일 수 있어 범위로 보지 않고 `INVALID`다.** 이 규칙에 맞지 않는 나머지 문법 불일치는 `INVALID`다. 저장 결과(null/unverified)는 같고 플래그만 다르다.
- 층 입력 형식은 `N층`, `NF`, `제N층`, `지상N층`, `지하N층`, `지하 N층`, `BN`, `BN층`, `BNF`만 인정한다. 영문 `F`·`B`는 대소문자 무관이다.
- **도로명주소의 `지하`는 건물번호 앞에도 쓰인다(예: `○○로 지하 12`).** `지하`는 바로 뒤 토큰이 `N층`/`NF`일 때만 지하층으로 결합하고, 뒤가 숫자만이면 건물번호이므로 상세 위치로 쓰지 않는다(`NO_DETAIL`).
- canonical `unit`은 1~4자리 ASCII 숫자와 `호`이며, 숫자 앞 **또는** 뒤에 영문 대문자 1자를 선택적으로 둘 수 있다(앞뒤 모두는 불가). 지하 호실 관행인 `B101호`를 `INVALID`로 버리면 reconcile에서 다른 원천의 성공값까지 무효가 되므로 접두 1자를 허용한다. 입력 영문은 ASCII `[A-Za-z]`인지 먼저 확인한 뒤 대문자로 정규화한다(비ASCII 문자에 `upper()`를 먼저 적용해 `ß`→`SS`처럼 길이·문자가 바뀌지 않게 한다). 숫자 판정은 `[0-9]`/`re.ASCII`만 쓰고 `str.isdigit()`·유니코드 `\d`를 쓰지 않는다. `162c호`는 `162C호`, `b101호`는 `B101호`가 된다. 접두 `B`는 호수 표기의 일부로만 보고 지하층으로 해석하지 않는다(`B101호` 단독은 층 없음 → `same_building`). 호수 숫자는 앞자리 0을 포함해 원문 숫자 그대로 두고(`0101호`를 `101호`로 바꾸지 않음), 숫자가 모두 0이면 `INVALID`다. `제N호` 접두는 제거한다.
- 층만·호수만 또는 양쪽을 한 주소에서 명시적으로 찾을 수 있다. `2층 201호`처럼 둘 다 있으면 값은 `{floor} {unit}` 순서로 공백 하나로 결합한다. 입력 순서가 `201호 2층`이어도 같은 값이다.
- 주소의 건물번호·지번·상가명에 있는 숫자는 suffix(`층`, `F`, `호`)가 토큰 끝에 붙지 않는 한 절대 상세 위치로 사용하지 않는다. `테스트로 101`, `테스트로 45-1`, `서교동 123-4`, `서교동 123-4번지`, `산12-3`은 `NO_DETAIL`이다.
- **구 지번식 `N번지 M호` 오인 방지**: 지번주소에서 `395번지 17호`처럼 `번지`로 끝나는 토큰 바로 뒤의 `M호`는 부번(`395-17`)일 수 있어 호실과 구분할 수 없다. 이런 토큰 배열이 도로명·지번 어느 원천에 있든 그 원천은 `AMBIGUOUS`다(뒤에 `2층` 등이 있어도 동일). `395번지17호`처럼 붙은 토큰은 바로 아래의 "suffix로 끝나지만 문법 불일치" 규칙에 따라 `INVALID`다. 건물번호 뒤 공백 후 `201호`(`테스트로 101 201호`)는 이 규칙 대상이 아니다.
- 숫자로 시작하고(`제`/`지상`/`지하`/`B` 접두 허용) `층`·`F`·`호`로 끝나지만 위 문법에 맞지 않는 토큰(`101-1호`, `1A2호`, `12345호`, `1000층`)은 `INVALID`다. suffix로 끝나지 않는 토큰(`3호선`, `1층일부`, `대호빌딩`)은 상세 위치를 만들지 않고 무시한다. `1층일부`류 손실은 dry-run 실패율로 측정하며 이 작업에서 완화하지 않는다.
- **층 수식어**: 괄호 밖에 `반지하`, `지층`, `지하층`(숫자 없는 지하), `옥탑`, `옥상`, `중층`, `중2층`, `M층`, `메자닌`이 단독 토큰이거나 층 토큰의 접두로 붙어 있으면 실제 층을 결정할 수 없으므로 `AMBIGUOUS`다. 특히 `반지하 1층`을 `1층`으로, `지층`을 무시해 다른 층 토큰만 채택하지 않는다.
- **단지 내 동 표기**: `101동`, `A동`처럼 ASCII 숫자 1~4자리 또는 영문 1자 + `동`인 토큰이 괄호 밖에 있으면 같은 지번(building_key)에 여러 건물이 있다는 뜻이므로 층·호수를 찾았더라도 `AMBIGUOUS`다. 법정동명(`서교동`)과 한글 1자 동(`가동`)은 법정동과 구분할 수 없어 이 규칙에 넣지 않는다.

### 3. 안전한 토큰화와 충돌 처리

처리 순서는 고정한다: ① 타입 확인 → ② 원문 길이 확인 → ③ 원문 문자 범주 확인 → ④ NFKC → ⑤ NFKC 후 길이·문자 범주·숫자 확인 → ⑥ 공백 정규화 → ⑦ 괄호 제거 → ⑧ 토큰화·토큰 결합 → ⑨ 토큰 분류.

- 입력 길이는 NFKC 전후 각각 1,000자 이하여야 하며 초과는 `INVALID`다. 길이 확인 전에 정규화·토큰화를 하지 않는다.
- Cc(탭·CR·LF 제외)·Cf·Cs·Co·Cn·No 문자는 NFKC 전과 후 모두에서 `INVALID`로 거절한다(원문의 `①`·`²` 같은 No 문자를 NFKC로 숫자로 바꿔 받아들이지 않기 위해 원문에서도 검사한다). NFKC 후 비ASCII Nd 숫자도 `INVALID`다. 전각 숫자·전각 공백·전각 괄호처럼 NFKC로 ASCII가 되는 문자는 허용한다.
- 정규식은 `re.ASCII`와 명시적 `[0-9]`·`[A-Za-z]`만 쓰고 `\d`·`\w`·`str.isdigit()`·`str.isnumeric()`으로 숫자를 판정하지 않는다(Python 기본 `\d`·`isdigit()`는 비ASCII 숫자·위첨자를 받는다). `int()` 변환과 `.upper()`는 ASCII fullmatch를 통과한 조각에만 적용한다. NFKC로 생긴 괄호(`㈜` → `(주)` 등)도 일반 괄호와 같이 균형·중첩 검사를 받는다.
- 공백 정규화는 탭·CR·LF·Zs를 공백 하나로 바꾸고 양끝을 제거한다. 토큰화는 2단계로 한다.
  1. 공백으로 chunk를 나눈다.
  2. chunk 안의 쉼표·슬래시·하이픈은 **나뉜 모든 비어 있지 않은 조각이 각각 완전한 층 또는 호 토큰일 때만** 구분자로 쓴다(`1층,201호`, `1층/201호`, `1층-201호`, `B1-101호`). 끝에 붙은 쉼표(`123,`)는 빈 조각으로 보고 버린다. 조각 중 하나라도 층·호 문법이 아니면 chunk를 나누지 않고 한 토큰으로 분류한다.
- 이 규칙 때문에 `1,2층`·`1/2층`·`1-2층`·`123,2층`은 한 토큰으로 남아 2절의 범위·나열 규칙으로 `AMBIGUOUS`가 되고 `2층`으로 잘못 추출되지 않는다(`123,2층`도 공백 없는 쉼표이므로 같은 규칙을 적용한다). `45-1`, `123-4`는 suffix가 없어 무시된다. 도로명주소 표준 형식 `테스트로 123, 2층 201호`는 쉼표 뒤 공백으로 chunk가 나뉘므로 정상 처리된다. 반대로 `1, 2층`(쉼표 뒤 공백)은 건물번호+층과 구분할 수 없어 `2층`이 되며, 이는 잔여 제한으로 dry-run에서 측정한다.
- NFKC로 ASCII `-`·`~`가 되지 않는 대시(`–`·`—`·`‐` 등)는 구분자로 인정하지 않으므로 해당 chunk는 `INVALID`다. 대시 변형을 구분자로 확장하는 것은 dry-run 이후 별도 설계로 한다.
- 토큰 결합은 다음 두 경우만 한다: 숫자만인 토큰 뒤 토큰이 정확히 `층`/`F`/`호`이면 합친다(`1 층` → `1층`). `지상`/`지하` 단독 토큰은 바로 뒤가 층 토큰(`N층`/`NF`)일 때만, `제` 단독 토큰은 바로 뒤가 층 또는 호수 토큰일 때만 접두로 붙인다(`지하 101호`는 결합하지 않고 `지하`를 무시해 `101호`만 남는다). 결합 순서는 숫자+suffix 결합 1회 → 접두 결합 1회로 고정하고 반복 적용하지 않는다(`지하 1 층` → `지하 1층` → `B1`). 그 외 인접 토큰은 합치지 않는다. 공백 없는 `1,2층`·`1/2층`·`1~2층`은 위 2단계 chunk 규칙과 2절 범위·나열 규칙으로 `AMBIGUOUS`이고, 도로명주소 관행인 `○○로 45, 2층`(쉼표 뒤 공백)은 건물번호와 상세 주소의 구분으로 보고 `2층`이다. 이 둘은 반드시 함께 테스트한다. 주소 전체를 대상으로 한 느슨한 숫자 검색이나 대형·역추적 정규식은 쓰지 않고, 토큰 단위의 고정 길이 정규식(`fullmatch`)만 쓴다.
- 한 원천에서 서로 다른 층 또는 서로 다른 호수가 두 번 이상 발견되면 `AMBIGUOUS`다. 같은 canonical 값의 반복은 하나로 본다.
- `1층-201호`, `1층/201호`, `1층, 201호`처럼 허용된 구분자로 분리된 같은 상세 위치는 허용한다. 단 서로 다른 값이 있으면 `AMBIGUOUS`다.
- 괄호는 NFKC 후의 `(`·`)`만 인정한다. 괄호 안의 값은 건물·법정동 부가정보로 보고 추출하지 않는다. 괄호 불균형·중첩은 `INVALID`다.
- 실패 우선순위는 한 원천 안에서 `INVALID` > `AMBIGUOUS` > 성공 > `NO_DETAIL` > `EMPTY`다. 형식 오류 토큰이 하나라도 있으면 다른 유효 토큰이 있어도 `INVALID`다.

road·jibun reconcile은 다음 표만 따른다(대칭). `v`, `w`는 성공값이며 비교는 `FloorUnitValue` 전체 동일성이다.

| road \ jibun | 성공 `w` | `NO_DETAIL`/`EMPTY` | `AMBIGUOUS` | `INVALID` |
|---|---|---|---|---|
| 성공 `v` | `v == w`면 `v`, 아니면 `AMBIGUOUS` | `v` | `AMBIGUOUS` | `INVALID` |
| `NO_DETAIL`/`EMPTY` | `w` | 둘 다 `EMPTY`면 `EMPTY`, 아니면 `NO_DETAIL` | `AMBIGUOUS` | `INVALID` |
| `AMBIGUOUS` | `AMBIGUOUS` | `AMBIGUOUS` | `AMBIGUOUS` | `INVALID` |
| `INVALID` | `INVALID` | `INVALID` | `INVALID` | `INVALID` |

- 부분 일치(`2층` vs `2층 201호`)도 값이 다르므로 `AMBIGUOUS`다. 더 구체적인 쪽을 고르거나 합치는 것은 추정이므로 하지 않는다. dry-run에서 부분 일치 비율이 높으면 별도 설계로 다룬다.
- 한쪽이 `INVALID`/`AMBIGUOUS`이면 다른 성공값이 있어도 원천 오염 가능성이 있으므로 값을 저장하지 않는다.
- 결과·`repr`·리포트·예외 메시지에 주소 원문 또는 그 일부, 토큰을 넣지 않는다. 실패 사유는 enum 값만 노출한다.
- floor_unit canonical 값도 building_key와 결합하면 층호 식별정보이므로(work plan 8절) `FloorUnitValue`·`FloorUnitResult`의 기본 `repr`에서 제외한다(`field(repr=False)`). 필드 기본값 없는 필드 뒤 순서 제약 때문에 `field(repr=False)`만 쓰고 기본값을 주지 않으며, mypy·dataclass 순서 오류가 나면 `__repr__`을 직접 정의해 실패 enum만 표시한다. pytest assertion rewrite가 값을 보여줄 수 있는 테스트 출력은 CI 로그이므로 테스트 데이터는 가상 canary만 쓴다.

### 4. ETL 및 DB 연결

- `StoreRecord`에 이미 존재하는 `floor_unit`, `location_level` 필드를 채운다. 구현 전에 두 필드와 stores 컬럼의 실제 타입·길이·nullable·CHECK 제약을 확인하고(canonical `floor_unit` 최대 11자 예: `999층 A9999호`, `location_level` 최대 13자 `same_building`), 길이가 부족하면 migration을 만들지 말고 중단 조건 3으로, `location_level` 컬럼이 위 세 값을 담을 수 없거나 DB enum이 다른 값이면 중단 조건 2로 처리한다. `transform_rows()`는 `address_road`, `address_jibun`을 각각 파싱하고 reconcile 결과를 저장한다.
- `location_level`은 reconcile 성공이고 같은 레코드의 `building_key`가 non-null일 때만 `FloorUnitValue.location_level`, 그 외에는 `unverified`다. building_key 없는 성공은 `TransformReport.flags`의 `floor_unit_ok`로 세되, 별도 보조 카운터 `location_level_unverified_no_building_key`를 남긴다(항등식에는 포함하지 않음).
- 건물 키와 마찬가지로 상세 위치 파싱 실패는 레코드를 제외하지 않는다. `TransformReport.flags`에 `floor_unit_ok` 또는 `floor_unit_<failure>`(`empty`·`no_detail`·`ambiguous`·`invalid`)로 집계한다. 리포트에는 건수만 담고 floor_unit 값·주소·license_no를 담지 않는다. 플래그 이름은 9절 플래그 enum 동기화 전까지 내부 ETL 리포트용이다.
- 변환된 모든 레코드에 대해 다음 항등식을 테스트한다.

```text
transformed = floor_unit_ok + Σ floor_unit_<failure>
```

- repository `UPDATE_COLUMNS`에 `floor_unit`, `location_level`을 추가하고 upsert의 갱신식은 `EXCLUDED` 값을 그대로 쓴다(`COALESCE`·조건부 갱신 금지). 새 결과가 null/unverified면 기존 DB 값도 null/unverified로 덮어쓴다. 이번 배치에 포함되지 않은 레코드는 건드리지 않는다.
- **소유권**: BE-10부터 LocalData 인허가 ETL이 `stores.floor_unit`, `stores.location_level`의 유일한 writer다. 구현 시 현재 코드에 다른 writer가 없음을 확인하고, 있으면 중단 조건 2로 처리한다. BE-11 `/api/geocode`는 요청 주소의 floor_unit을 응답에만 계산하며 stores에 쓰지 않는다(같은 순수 파서 재사용은 허용).
- 이후 다른 writer(수동 보정·다른 원천)가 필요해지면 출처 컬럼·우선순위를 먼저 재설계한다. 재설계 전에는 그 writer를 추가하지 않는다. 이 ETL 재실행이 다른 writer 값을 덮어쓰는 것이 현재 계약이다.
- `building_key`, `deleted_at`, 브랜드 필드는 이 작업에서 계속 보존한다. 여기서 "보존"은 각 컬럼의 기존 갱신 규칙(작업 4~6)을 바꾸지 않는다는 뜻이다. migration은 기존 nullable 컬럼을 사용하므로 추가하지 않는다.
- **building_key·location_level 일관성**: `location_level`은 같은 레코드에서 실제 DB에 저장될 `building_key`로 계산해야 한다. 구현 시 BE-09의 `building_key` 갱신식이 `EXCLUDED` 그대로인지 확인한다. `COALESCE` 등으로 새 null이 기존 non-null key를 유지하는 구조라면 DB에는 key가 남고 `location_level`만 `unverified`가 되거나 그 반대가 생기므로, 임의로 맞추지 말고 중단 조건 2로 보고한다.
- **원천 필드 누락과 빈 값 구분**: 원천 응답에서 `address_road`·`address_jibun` 필드 자체가 사라진 경우(스키마 변경·부분 응답)를 빈 주소(`EMPTY`)로 바꿔 기존 floor_unit을 null로 덮어쓰지 않는다. 구현 시 기존 ETL의 필수 필드 검증이 이를 배치 오류로 처리하는지 확인하고, 구분하지 못하면 결과 보고에 잔여 제한으로 기록한다.

## 테스트

### 순수 단위 테스트

- 지상층·지하층·`F`·`제`·`지상` 표기, `지하 1층`/`지하1층`/`B1F`, 층+호수(입력 순서 반대 포함), 숫자+영문 호수, `1층-201호`의 canonical 변환
- 경계값: `1층`·`999층` 성공, `0층`·`1000층`·`B0`·`B1000` 실패, `9999호`·`0101호` 성공(원문 숫자 유지), `B101호`·`b101호` → `B101호`, `0호`·`10000호`·`162CD호`·`AB101호`·`A101B호`·`101-1호` 실패, `01층` → `1층`, `지하 101호`의 `지하` 비결합, `지하 1 층` → `B1`, `지하1층 B101호` → `B1 B101호`
- 층만·호수만·상세 위치 없음의 `location_level`, `EMPTY`와 `NO_DETAIL` 구분
- 오인 방지: `테스트로 101`, `테스트로 45-1`, `○○로 지하 12`, `서교동 123-4`, `123-4번지`, `산12-3`, 괄호 안 `(2층)`·`(서교동)`, `3호선`, `1호점`, `대호빌딩`은 상세 위치를 만들지 않음, 구 지번식 `395번지 17호`·`395번지 17호 2층`은 `AMBIGUOUS`, `지하층 101호`는 `AMBIGUOUS`, `123,2층`은 `AMBIGUOUS`
- 구분자 비분리: `1-2층`·`1~2층`·`1,2층`·`1/2층`·`123,2층`·`201~203호`가 `2층`/`203호`가 되지 않고 `AMBIGUOUS`(범위·나열)인지, `101-1호`·`2-201호`는 `INVALID`, `1층–201호`(en dash)는 `INVALID`, 대조군 `테스트로 45, 2층`·`45-1, 1층/201호`·`테스트로 123, 2층 201호`는 정상 추출되는지
- 층 수식어: `반지하 1층`, `지층`, `옥탑 1층`, `M층`, `중2층`이 `AMBIGUOUS`
- `repr(result)`·`repr(value)`에 canonical 층호 값이 없는지
- 단지 내 동: `101동 1203호`, `A동 201호`는 `AMBIGUOUS`, `서교동 2층`은 `2층`
- 반복 같은 값, 서로 다른 층·호수, 괄호 불균형·중첩, 숫자 범위·형식 오류, 한 원천 내 실패 우선순위
- reconcile 표를 `NO_DETAIL`·`EMPTY` 분리, 성공은 같은 값/다른 값/부분 일치로 나눠 전체 조합을 매개변수화하고 `reconcile(a, b) == reconcile(b, a)` 대칭성, 부분 일치 `AMBIGUOUS`
- Unicode: NFKC 전각 숫자·공백·괄호 허용, 원문 `①`·`²`(No)·Cf(ZWSP·BIDI 제어)·Cc·서로게이트·비ASCII Nd(`١`) 거절, NFKC 후 길이가 늘어나는 문자(`﷽` 등)로 1,000자를 넘는 경우 포함 NFKC 전후 길이 1,000/1,001 경계, `㈜` 유래 괄호 처리, 비ASCII 숫자가 정규식·`int()`를 통과하지 않음
- 결정성·멱등성: 같은 입력 반복 호출 동일, `parse(result.value.value)`가 같은 값, 고정 seed 임의 `str`(최소 수천 건, Unicode 전 범주 포함)에서 어떤 예외도 없음(`FloorUnitValue`의 `ValueError`가 parse 밖으로 새지 않음), 비 `str` 입력의 값 없는 `TypeError`
- 개인정보: 결과 `repr`, 예외 메시지, `caplog`, `TransformReport`에 주소 canary 문자열·토큰이 없는지

### pipeline·PostGIS 테스트

- 정상·미확인·충돌 결과가 `StoreRecord`과 `TransformReport.flags`에 정확히 반영되는지, `location_level`이 항상 세 값 중 하나이고 NULL이 아닌지
- building_key가 null인 레코드는 floor_unit 성공이어도 `unverified`이고 보조 카운터가 증가하는지
- building_key 항등식과 floor_unit 항등식이 서로 독립적으로 유지되는지
- 실제 PostGIS(CI 임시 컨테이너)에서 같은 license_no 두 번 upsert로 `A→B`, `NULL→A`, `A→NULL`, `same_spot→unverified`, BE-10 이전 행의 `location_level NULL→unverified`를 확인하고, 같은 실행에서 building_key·deleted_at·브랜드 필드가 기존 갱신 규칙대로 유지되는지와 두 번째 배치에 없는 다른 license_no 행이 변하지 않는지 확인한다. 결과는 ORM identity map이 아닌 새 세션/연결의 SELECT로 읽는다.
- DB 테스트는 기존 작업 3~6의 통합 테스트 fixture·환경변수·marker를 그대로 재사용하고 새 DB 접속 경로를 만들지 않는다. 테스트는 `.env`의 개발용 `DATABASE_URL`을 읽지 않으며, 기존 fixture가 개발 DB 접속을 막지 못하는 구조면 구현하지 않고 중단 조건 3으로 보고한다. 로컬에서 테스트 DB가 없으면 skip될 수 있으나 그 결과를 통합 검증 완료로 보고하지 않는다.
- CI 게이트: pytest를 `--junitxml`로 실행하고, 신규 floor_unit 통합 테스트의 node id 목록이 JUnit에 모두 존재하며 각 testcase에 `skipped`·`failure`·`error`가 없음을 검사하는 단계가 실패하면 job이 실패한다. 기존 작업의 JUnit 게이트가 있으면 그 목록에 추가하고 별도 방식을 만들지 않는다.

## 기능별 커밋 계획

| 순서 | 커밋 | 범위와 게이트 |
|---|---|---|
| 1 | `docs(be): 층호수 정규화 설계와 Claude 검토 기록` | 설계 MD, Claude 직접 검토·수정 |
| 2 | `feat(etl): 주소 층호수 정규화 파서 구현` | 순수 파서·reconcile·보안 단위 테스트 |
| 3 | `feat(etl): 층호수를 인허가 ETL에 연결` | StoreRecord·pipeline·report·repository, 단위 테스트 |
| 4 | `test(etl): 층호수 PostGIS 갱신 검증` | 실제 PostGIS 갱신·보존, CI JUnit 게이트 |
| 5 | `docs(be): 층호수 구현과 검증 결과 정리` | 검증 결과·제한 기록, 최신 CI 뒤 PR |

## 중단 조건

1. 상세 위치 표기에서 층·호수를 결정적으로 분리할 수 없어 상호·건물명·주소 숫자를 추정에 사용해야 하는 경우.
2. `same_spot`·`same_building`·`unverified`의 저장 enum이 API 계약·기존 컬럼 타입과 충돌하거나 다른 writer가 이미 존재하는 경우.
3. 기존 stores 모델·migration 변경이나 실제 개발 DB 접속·적재·backfill이 완료 조건이 되거나 테스트가 실제 개발 DB에 닿을 수 있는 경우. 이때 be-work-plan 3절 큐 중단 규칙을 따른다.
4. 파서가 임의 문자열에서 예외를 내거나 주소·key가 로그·report·예외에 노출되는 경우.
5. 실제 PostGIS 통합 검증이 실패·skip·미실행이거나 CI JUnit 게이트가 새 테스트 실행을 확인하지 못하는 경우.
6. 실제 원천 dry-run 전 규칙 완화가 완료 조건으로 요구되는 경우. 실패율 측정과 별도 설계를 먼저 한다.

## 완료 조건

1. Claude Code가 이 MD만 읽고 직접 검토·수정한 기록이 남는다.
2. 명시된 층·호수만 canonical 값으로 저장하고, 모호·충돌·미확인·building_key 없음은 unverified로 남긴다(앞 셋은 floor_unit도 null).
3. parser·pipeline 단위 테스트, ruff·mypy·전체 DB 비의존 테스트가 통과한다.
4. CI 임시 PostGIS에서 floor_unit 갱신과 기존 컬럼 보존을 skip 없이 검증한다.
5. 실제 개발 DB·실원천 backfill 없이 최신 branch/PR CI·CodeQL 통과 뒤 지정 양식의 PR을 만든다.

## Claude Code 검토 기록

### 검토 범위

- 2026-11-11, Claude Code가 이 파일만 Read·Edit로 검토·수정했다. 코드·다른 문서·Git·셸은 읽거나 수정하지 않았다. 따라서 기존 `StoreRecord`·repository·CI·fixture 구조는 확인하지 못했고, 해당 전제는 구현 시 확인 항목으로 남겼다.
- 기준: 저장 enum 의미, 주소 번호 오인·원천 충돌, Unicode·개인정보·결정성·NULL 갱신·writer 소유권, 단위·PostGIS 테스트와 CI 게이트·개발 DB 미사용.

### 수정 내용과 이유

1. **위치 신뢰도 의미 과장 방지**: `LocationLevel` StrEnum 3값을 명시하고, 저장값은 레코드 단위 정밀도 상한일 뿐 레코드 간 같은 자리 판정이 아님을 명시했다. 호수→층 추정 금지, building_key 없으면 `unverified`(건물을 특정 못했는데 `same_building`을 주장하는 과장 방지), ETL 저장값 NULL 금지를 추가했다.
2. **주소 번호 오인 방지**: 초안의 "하이픈 구분자"는 `1-2층`을 `2층`으로, `45-1`을 분해할 위험이 있어 일반 구분자에서 제외하고 `{층}-{호}` 단일 토큰만 허용했다. 도로명 지하 건물번호(`○○로 지하 12`)를 `B12`로 오인하지 않도록 `지하` 결합 조건을 정했다. `101동`/`A동` 단지 내 동 표기는 같은 building_key에 여러 건물이 있어 `AMBIGUOUS`로 했다. `제`/`지상` 접두, `1 층` 토큰 결합, 층 앞자리 0, 호수 원문 숫자 유지, suffix로 끝나는 형식 오류 토큰의 `INVALID` 처리를 정했다.
3. **reconcile 모순 해소**: 초안은 "하나만 성공하면 그 값"과 "한쪽 INVALID면 AMBIGUOUS", "하나라도 INVALID면 INVALID"가 서로 충돌했다. 16개 조합의 대칭 표로 대체하고(INVALID 우선 → AMBIGUOUS → 성공 → NO_DETAIL → EMPTY), 부분 일치도 추정 없이 `AMBIGUOUS`로 했다. 초안에 정의만 있고 쓰이지 않던 `EMPTY`의 의미를 정했다.
4. **Unicode·입력 안전성**: 처리 순서를 고정하고, NFKC가 `①`·`²`를 숫자로 바꾸는 것을 막기 위해 원문에서도 범주 검사를 하도록 했다. Cs·Co·Cn 추가, 토큰 단위 `fullmatch`만 사용, 예외·repr·리포트에 토큰까지 넣지 않도록 했다.
5. **ETL·소유권**: upsert가 `EXCLUDED`를 그대로 쓰고 배치 밖 레코드는 건드리지 않음을 명시했다. 초안의 "새 writer가 생기면 ETL을 재실행하지 않는다"는 운영상 지키기 어려워 "다른 writer는 재설계 전 추가 금지, BE-11은 stores에 쓰지 않음"으로 바꿨다. 기존 컬럼 타입이 3값을 못 담으면 중단하도록 했다.
6. **테스트·CI·개발 DB**: 경계값·오인 방지·reconcile 전 조합·대칭성·멱등성 테스트를 구체화했다. PostGIS 테스트는 기존 fixture 재사용, `.env` 개발 DB URL 미사용, 로컬 skip을 검증 완료로 보고하지 않음, JUnit node id 존재·무 skip 검사 단계 실패 시 job 실패로 게이트를 정의했다.

### 잔여 제한·보류

- 실제 원천의 상세 주소 표기 분포를 보지 못했다. `1층일부`, `1층 일부`, 한글 1자 동(`가동`), 괄호 안 층호수, 부분 일치는 이 작업에서 보수적으로 null/unverified 또는 무시하며, 실원천 dry-run 실패율 측정 후 별도 설계로 다룬다(중단 조건 6).
- `floor_unit_*`·`location_level_unverified_no_building_key` 플래그명과 `location_level` 값의 FE·API 계약 반영은 be-work-plan 9절(플래그 enum·ETL·주소) 동기화 대기다.
- building_key가 없는 레코드에 floor_unit을 저장하는 것은 정보 보존 목적이며, BE-12가 building_key로만 조회하므로 같은 자리 판정에 쓰이지 않는다는 전제다. BE-12 설계에서 재확인한다.
- `StoreRecord` 필드·컬럼 타입·기존 JUnit 게이트·DB fixture의 실제 존재 여부는 이 검토에서 확인하지 못했으므로 구현 단계(Codex)가 diff와 코드로 확인해야 한다.

### 추가 검토 (2026-11-11, Claude Code 2차)

이 파일만 Read·Edit로 다시 검토했다. 검토 중 파일이 디스크에서 동시에 바뀌어 최신본을 다시 읽은 뒤 그 내용을 기준으로 수정했으며 다른 쪽 변경은 되돌리지 않았다.

수정 내용과 이유:

1. **쉼표·슬래시로 인한 번호 오인**: 위 2번 항목은 하이픈만 일반 구분자에서 뺐고 쉼표·슬래시는 여전히 일반 구분자여서 `1,2층`·`1/2층`·`123,2층`이 `1`+`2층`으로 나뉘어 `2층`이 잘못 추출될 수 있었다. 공백 chunk → "모든 조각이 완전한 층·호 토큰일 때만 분리"하는 2단계 토큰화로 바꿨다. 쉼표 뒤 공백이 있는 도로명 표준형 `○○로 123, 2층`은 계속 정상 처리된다.
2. **범위·나열 판정 통일**: 본문 일부는 범위를 `AMBIGUOUS`로, 일부는 `INVALID`로 적어 플래그 결과가 서로 달랐다. 층·호 범위·나열을 하나의 `AMBIGUOUS` 규칙으로 정하고, `101-1호`(지번식 호실일 수 있음)만 예외로 `INVALID`에 두었다. 표의 `1, 2층`(쉼표 뒤 공백)은 건물번호+층과 결정적으로 구분할 수 없어 null 예시에서 빼고 잔여 제한으로 옮겼다.
3. **층 수식어**: `반지하 1층`·`옥탑`·`지층`·`중2층`·`M층`이 있을 때 숫자 층 토큰만 채택하면 다른 층으로 단정하게 되므로 `AMBIGUOUS`로 정했다.
4. **개인정보·repr**: canonical floor_unit도 building_key와 결합하면 층호 식별정보(work plan 8절)이므로 dataclass `repr`에서 값을 빼도록(`field(repr=False)`) 했다. 이에 맞는 단위 테스트를 추가했다.
5. **Unicode 세부**: 영문 대문자화 전 ASCII 확인, `[0-9]`/`re.ASCII`만 쓰고 `isdigit()`·유니코드 `\d` 금지, NFKC로 ASCII가 되지 않는 대시(`–` 등)는 구분자로 인정하지 않고 `INVALID`로 처리하도록 명시했다.
6. **테스트 구체화**: 구분자 비분리 대조군(`123,2층` vs `123, 2층`), en dash, 층 수식어, repr 비노출 사례를 추가하고 "AMBIGUOUS/INVALID 중 설계값"처럼 기대값이 정해지지 않았던 문구를 확정값으로 바꿨다.

잔여 제한:

- `1, 2층`(쉼표 뒤 공백 나열)은 `○○로 1, 2층`과 구분할 수 없어 `2층`으로 추출된다. dry-run에서 건물번호가 1~2자리인 표본의 오추출 여부를 측정한다.
- en dash 등 대시 변형, `1층일부`, 한글 1음절 동, 괄호 안 상세 위치는 보수적으로 무효·무시 처리했다. 실원천 분포를 보지 못했으므로 완화는 dry-run 후 별도 설계로 한다(중단 조건 6).
- writer 소유권·컬럼 타입·기존 fixture·JUnit 게이트는 이번 검토에서도 코드로 확인하지 못했다. 구현 전에 확인해야 하며, 다르면 중단 조건 2·3을 적용한다.
- `same_spot`·`same_building`·`unverified` 값 집합과 BE-12 `location_match`의 의미 구분은 API 명세 v1.2 원본과 대조하지 못했다(9절 동기화 대기).

### 2차 검토(동시 수정 정합화)

- 같은 날 검토 중 파일이 별도로 수정된 것을 확인하고 전체를 다시 읽어 아래 모순을 이 파일 안에서 정리했다.
  1. **범위·나열 실패 종류**: 정합화 도중 2절이 "범위·나열 판정(단일 규칙)"으로 `AMBIGUOUS`(호수 하이픈 `101-1호`만 `INVALID`)로 확정되어, 이 검토에서 잠시 `INVALID`로 맞췄던 문구를 되돌리지 않고 최신 2절·3절·테스트의 `AMBIGUOUS` 기준을 유지했다. 남아 있던 3절 문구가 모두 같은 기준인지 다시 확인했다. 저장 결과(null/unverified)는 같다.
  2. **`1, 2층` 표기**: 표에서 null로 적었던 것을 삭제했다. 3절대로 쉼표 뒤 공백은 도로명주소 구분과 구별할 수 없어 `2층`이 되며 잔여 제한이다.
  3. **지하 호실 `B101호`**: 초안 문법에서는 `INVALID`가 되어 reconcile 시 다른 원천의 정상값까지 버리게 되므로, 숫자 앞 또는 뒤 영문 1자(둘 다는 불가)를 허용하고 접두 `B`를 층으로 해석하지 않도록 했다. 최대 길이 예시(`999층 A9999호`, 11자)를 4절 컬럼 확인과 맞췄다.
  4. **`지상`/`지하` 결합 범위**: 호수 토큰과도 결합하면 `지하101호`처럼 정의되지 않은 토큰이 생겨 `INVALID`가 되고 다른 원천의 정상값까지 버리게 되므로, `지상`/`지하`는 층 토큰과만, `제`는 층·호수와 결합하도록 좁혔다.
  5. **enum 근거 명시**: `unverified`는 기준 문서 5절이 저장값으로 직접 지정했고 나머지 두 값은 BE-12 `location_match` 값 집합과 맞춘 것임을 1절에 적었다. building_key가 있어도 상세 위치가 없으면 `unverified`라 두 의미가 섞이므로 `building_key IS NULL`로 구분함을, 그리고 BE-10 이전 행의 `location_level IS NULL`은 읽는 쪽이 `unverified`로 취급해야 함을 추가했다.
  6. **컬럼 확인 중복 제거**: 1절과 4절의 컬럼 수용 확인을 4절 하나로 합치고, 길이 부족은 중단 조건 3(migration 금지), 값/제약 충돌·다른 writer는 중단 조건 2로 나눴다.
  7. reconcile 테스트의 "16개 조합"은 `NO_DETAIL`/`EMPTY` 분리와 성공값 동일·상이·부분 일치를 반영하지 못해 "전체 조합"으로 고쳤다.
- 추가 잔여 제한:
  - 파서 규칙 버전 컬럼이 없다. 규칙이 바뀌면 일부 배치만 재적재한 경우 서로 다른 규칙의 값이 섞이므로, 규칙 변경 뒤에는 전체 재적재가 필요하다. 규칙 버전 기록은 ETL 배치 로그(BE-35) 설계에서 다룬다.
  - `same_spot`/`same_building`/`unverified` 값 집합이 원본 API 명세 v1.2와 일치하는지는 외부 원본 미보유로 확인하지 못했다(be-work-plan 9절).
  - CI 임시 PostGIS 통과는 실제 개발 DB 연동 완료가 아니다(be-work-plan 3절). 실원천 dry-run 실패율·충돌률 측정은 실제 개발 DB 연동 이후로 남는다.

## 구현 및 검증 결과

### 구현

- `etl.address.floor_unit`에 외부 I/O·로그 없는 층호수 파서와 도로명·지번 reconcile 함수를 구현했다.
- 명시적 `층`·`F`·`B`·`호` 표기만 canonical 값으로 만들며, 건물번호·지번·단지 동·범위·충돌은 추정하지 않고 failure로 처리한다.
- LocalData ETL은 `floor_unit_ok` 또는 `floor_unit_<failure>`를 집계한다. building_key가 없으면 층호수 파싱에 성공해도 `location_level=unverified`로 저장한다.
- `floor_unit`, `location_level`은 BE-10부터 LocalData ETL의 갱신 컬럼이다. `building_key`도 BE-09부터 같은 ETL의 갱신 컬럼이며, `deleted_at`, 브랜드 컬럼은 갱신하지 않는다.
- 별도 migration은 추가하지 않았다. 기존 nullable `floor_unit`(100자)·`location_level`(32자) 컬럼이 canonical 값과 세 enum을 수용한다.
- CI JUnit 게이트는 `test_floor_unit_upsert` 실제 PostGIS 통합 테스트 두 개 이상이 skip·failure·error 없이 실행됐는지 확인한다.

### 로컬 검증

- `ruff check .`, `ruff format --check .`, `mypy app migrations`를 통과했다.
- DB 비의존 전체 pytest는 251개 통과, 실제 DB 통합 테스트 12개는 기본 설정에서 제외됐다.
- 로컬의 `TEST_DATABASE_URL`과 `SPOTON_ALLOW_DB_INTEGRATION=1`은 설정하지 않았다. 개발 DB·실원천 데이터는 읽거나 변경하지 않았다.
- 병합 전에는 branch와 PR CI의 폐기형 PostGIS에서 통합 테스트·JUnit 게이트, 그리고 CodeQL이 모두 성공해야 한다. 하나라도 실패하거나 미실행이면 병합하지 않고 이 작업에서 멈춘다.

### CI 수정 기록

- 첫 branch CI의 실제 PostGIS 테스트에서 `building_key`를 보존해야 한다는 잘못된 테스트 가정이 실패했다. BE-09에서 이미 LocalData ETL의 갱신 컬럼으로 확정된 사실과 맞지 않아, 최신 ETL key로 갱신되는 것이 맞다.
- 해당 통합 테스트 기대값과 구현 결과 문구를 수정했다. `floor_unit`·`location_level`의 NULL 갱신 및 `deleted_at` 보존 정책은 변경하지 않았다. 수정 뒤 branch CI 전체를 다시 통과해야 한다.

### 3차 검토 (2026-11-11, Claude Code)

- 범위: 이 파일만 Read·Edit로 처음부터 끝까지 검토했다. 코드·다른 문서·Git·셸·웹은 사용하지 않았다. 이번 검토 중에도 파일이 외부에서 바뀌어 일부 수정이 실패했고, 최신본을 다시 읽은 뒤 남은 수정만 적용했다. 다른 쪽 변경은 되돌리지 않았다.
- 수정 내용과 이유:
  1. **enum 근거 재확인**: 기준 문서 5절이 `unverified`를 저장값으로 지정하고 "충돌·호수만이면 `same_spot`으로 판정하지 않는다"고 적어 `location_level`에 `same_spot`이 저장값으로 쓰인다는 것을 전제한다. 1절 근거는 충분하다고 보고 그대로 두었다. 레코드 단위 정밀도 상한이며 BE-12 `location_match`로 바로 반환하지 않는다는 구분도 유지했다.
  2. **구 지번식 `N번지 M호` 오인 방지(신규)**: `395번지 17호`의 `17호`는 부번일 수 있는데 기존 규칙으로는 호실로 추출돼 `same_building`/`same_spot`이 될 수 있었다. 해당 원천을 `AMBIGUOUS`로 처리하고 테스트를 추가했다. `1호점`도 오인 방지 테스트에 넣었다.
  3. **수식어 보강**: 숫자 없는 `지하층`이 있으면 층 정보가 빠진 채 `101호`만 남아 원래보다 넓은 위치를 확정값처럼 저장하게 되므로 층 수식어 목록에 추가했다.
  4. **Unicode**: `re.ASCII`/`[0-9]` 원칙에 `\w`·`isnumeric()`·`int()`의 적용 범위를 추가했다. NFKC로 길이가 늘어나는 문자(`﷽`)와 NFKC로 생기는 괄호(`㈜`→`(주)`)를 테스트·괄호 검사 대상에 넣었다. 퍼즈 테스트 기대값 "`TypeError` 외 예외 없음"은 `str` 입력에서 `TypeError`가 나올 수 없어 모순이므로 "어떤 예외도 없음, 내부 `ValueError` 누출 금지"로 고쳤다.
  5. **결정성 범위**: "같은 의미의 입력이 항상 같은 결과"는 검증할 수 없는 과장이라 "이 문서가 정의한 표기 변형에 대해"로 한정했다.
  6. **writer·null 갱신**: (a) `location_level`은 실제 저장될 `building_key`로 계산해야 하므로 BE-09의 key 갱신식이 `EXCLUDED` 그대로가 아니면(예: `COALESCE`) 불일치가 생긴다. 중단 조건 2로 보내도록 했다. (b) 원천 응답에서 주소 필드 자체가 빠진 경우를 `EMPTY`로 처리해 기존 값을 null로 지우지 않도록 확인 항목을 추가했다. (c) "보존"을 "기존 갱신 규칙 유지"로 정의해 building_key를 덮어쓰는 기존 규칙과 모순되지 않게 했다.
  7. **PostGIS 검증 보강**: BE-10 이전 행의 `location_level NULL→unverified`, 두 번째 배치에 없는 행이 변하지 않는지, ORM 캐시가 아닌 새 세션 SELECT로 확인하는 것을 추가했다.
  8. **문구 정합**: 3절의 `1,2층`·`123,2층` 결과를 2절의 `AMBIGUOUS`에 맞췄다. 토큰 결합 순서(숫자+suffix → 접두, 1회)를 확정했다. 단위 문법 경계 테스트(`AB101호`, `지하 1 층`, `지하1층 B101호`)를 추가했다.
- 잔여 제한:
  - `번지` 없이 `395 17호`처럼 지번 부번을 호로 적은 표기는 건물번호 뒤 호실(`테스트로 101 201호`)과 구분할 수 없어 성공값이 된다. dry-run에서 지번 원천의 호수 성공률·도로명과의 충돌률을 따로 측정한다.
  - `지하 101호`는 `지하`를 무시하고 `101호`(same_building)로 남는다. 다른 원천이 `B101호`면 `AMBIGUOUS`가 되며, 실원천 분포를 본 뒤 재검토한다.
  - 원천 필드 누락과 빈 값의 구분, BE-09 key 갱신식, 기존 컬럼 길이·CHECK, 다른 writer 존재 여부는 코드로 확인하지 못했다. 구현 단계에서 확인한다.
  - API 명세 v1.2 원본과 enum 값 집합을 대조하지 못했다(9절 동기화 대기). CI 임시 PostGIS 통과는 실제 개발 DB 연동 완료가 아니다.
