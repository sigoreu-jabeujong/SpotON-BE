# 상담·지원기관 링크 API 연동을 위한 FE 변경 요청 보고서

- 작성일: 2026-11-12
- 관련 작업: BE-33 / F-10, [BE #70](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/70)·[지역 안내 #88](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/88)
- 상태: **BE 공통 목록·구 관할 연락처 구현·검증 / FE 검토·연결 대기**
- 현재 계약: support-links-v2. 구를 지정하면5개, 생략하면 기존4개입니다. 업종별 추천·자격/모집 상태는 판정하지 않습니다.

## 1. 실제 API 연결

`GET /api/support-links`를 기존 `getSupportLinks()`·`useSupportLinks()`·`SupportLinksSection`에 연결해 주세요. 기존 API별 mock 설정에서는 `/support-links`를 실제 경로에 추가할 수 있습니다. 다른 미구현 API까지 실제로 전환하지 않아도 됩니다. BE 주소와 `/api` 접두사는 기존 client 설정을 따릅니다.

| 인자 | 허용 값 | 처리 |
|---|---|---|
| sigungu | 서울25개 구의 정확한 이름, 예: 마포구 | 선택. 서울특별시 접두사·공백·빈값은 거절 |
| category | cafe 또는 restaurant | 선택. 대소문자/공백/다른 코드는 거절 |

생략은 허용하지만 `null` 문자열·빈 값·중복/미지원 인자는422 INVALID_PARAM입니다. 기존 client가 null/undefined/빈 문자열을 생략하는 경로를 그대로 재사용할 수 있습니다. 주소·좌표·건물 키·인증키를 추가로 보내지 않습니다.

## 2. 공통 목록과 우선순위 한계

구를 생략하면 원본 D-08의 네 기관을 기존 순서로 반환합니다. 구를 지정해도 아래 네 기관은 모두 보존하며, 그 앞에 관할 센터1개가 추가됩니다. 기존 id·8개 필드·type·region을 유지합니다. 링크 설명과 실제 확인일은 BE 값을 사용해 주세요.

| 순서 / id | 기관 | type | region |
|---|---|---|---|
| 1 / seoulsbdc | 서울시 자영업지원센터 | consulting | 서울 |
| 2 / seoulsbdc-edu | 소상공인아카데미 | support_program | 서울 |
| 3 / seoul-small-business | 서울시 소상공인 지원사업 안내 | support_program | 서울 |
| 4 / sbiz24 | 소상공인24 | support_program | 전국 |

**구 지정 시 관할 연락처를 맨 앞에 표시해 주세요.** 서버가 반환한5개 배열을 그대로 쓰고4개로 자르거나 별도로 재정렬하지 않습니다. category는 이 목록/순서에 영향을 주지 않습니다. “관할 지역센터 연락처”로 설명하고, “맞춤 지원사업”·“신청 가능한 사업”·업종 추천으로 바꾸지 말아 주세요.

| 관할 센터 id의 semas-seoul- 이후 값 | 구 |
|---|---|
| jungbu | 중구·종로구·성북구·동대문구 |
| dongbu | 광진구·성동구·강동구·중랑구 |
| seobu | 강서구·양천구·영등포구 |
| nambu | 강남구·서초구·송파구 |
| bukbu | 노원구·도봉구·강북구 |
| dongjak | 동작구·용산구 |
| gwanak | 관악구·구로구·금천구 |
| seodaemun | 서대문구·은평구·마포구 |

예를 들어 `sigungu=마포구&category=cafe`는 `semas-seoul-seodaemun` 다음 위4개 순서입니다. 새 항목도 type=consulting·region=서울이며 기존8필드를 갖습니다. title·description에 센터명·관할·전화가 들어 있습니다. **url은 개별 지점/예약 페이지가 아니라 [중기부 공식 공고](https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1071565&cbIdx=310&parentSeq=1071565)**입니다. 첨부 PDF25쪽 별표2 연락처를 확인할 수 있으며 FE에서 신청 버튼으로 바꾸거나 임의 지점 URL/전화 URI를 생성하지 않아도 됩니다.

센터별 고유 id를 key로 사용하고 URL로 항목을 합치지 않습니다. 관할8개 항목의 공고 URL은 동일하지만 응답에는 해당 구의1개만 포함됩니다. 관할은2026-10-01 공고 기준이며 가까운 거리 순서가 아닙니다. 이후 변경 가능성은 BE의 분기 수동 점검에서 확인합니다.

## 3. 항목·확인일·출처 표시

항목은 `{id,org_name,title,description,url,type,region,last_checked}`이며 모든 키가 있습니다. 현재 last_checked는 실제 수동 확인 KST 날짜 `2026-11-12`입니다. 오늘/생성일/배포일로 덮어쓰지 않습니다. 분기1회 수동 점검 기준이며 요청 시 사이트에 접속해 갱신하지 않습니다.

기존 `SupportLinksSection`의 `target="_blank" rel="noopener noreferrer"`와 확인일 표시를 유지해 주세요. 아카데미 주소는 공식 시작 URL `/main/index.jsp`이고 접속 시 같은 호스트의 `/main`으로 이동합니다. 네 기관 모두 확인 당시 HTTP200과 페이지 제목을 확인했으며 이후 접속·신청 완료·지원 자격을 보장하지 않습니다. 모집 기간·지원 조건은 연결된 공식 사이트에서 사용자가 확인하도록 안내해 주세요.

meta는 source=[R17], is_demo=false, link_catalog_version=support-links-v2입니다. 구 생략 응답에도 v2를 사용합니다. as_of/space/denominator/collected_at/data_version은 null입니다. data_updated_at은 반환 링크의 last_checked 최대 날짜이며 공고 공표일·모집 마감일·통계 갱신일이 아닙니다. 공통 분석 기준일 화면에 잘못 합치지 말아 주세요.

`meta.prioritization`은 아래 두 형식입니다. applied는 **구 관할 연락처 배열 순서**만 뜻합니다.

```json
{"status":"not_applied","reason":"general_links_only"}
```

```json
{"status":"applied","reason":"district_contact_first","category_applied":false}
```

구 지정 시에만 `meta.district_contact_source`가 추가됩니다. 타입에 반영한다면 이 필드와 category_applied는 선택 필드로 두고 다른 API에 필수로 강제하지 않습니다.

```json
{
  "url":"https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1071565&cbIdx=310&parentSeq=1071565",
  "published_on":"2026-10-01",
  "checked_on":"2026-11-12",
  "page":25,
  "table":"annex_2"
}
```

published_on은 공고일, checked_on은 BE가 자료·연락처를 확인한 날입니다. 둘을 현재 날짜나 통계 기준일로 덮어쓰지 않습니다. 구 생략 응답에는 이 필드가 없습니다.

기존 SupportLink 타입을 전면 변경할 필요는 없습니다. 선택한 meta를 타입으로 추가한다면 다른 분석 API에 필수로 강제하지 않습니다. 요청/정상 응답/오류는 no-store이며422 입력 오류·500 서버 오류를 기존 공통 외피로 반환합니다. 서버는 DB·LLM·외부 HTTP 호출 없이 목록을 제공합니다.

## 4. 검토 대상과 완료 기준

검토 대상은 `src/api/support.ts`, `src/types/support.ts`, `src/hooks/useSupportLinks.ts`, `src/components/share/SupportLinksSection.tsx`, API별 mock 설정·문구·`docs/api-contract.md`/`docs/decisions.md`/FE `CLAUDE.md`입니다. BE는 FE 코드·문서·이슈·PR을 직접 수정하지 않습니다.

- [ ] `/support-links` 실제 연결, 다른 경로 mock 설정 유지
- [ ] 구 생략(category만 지정 포함) 시 기존4개·순서 유지
- [ ] 구 지정 시 관할1개+공통4개를 순서대로 표시, 배열 길이4 고정 제거
- [ ] 마포/은평/서대문→서대문센터, 성북/동대문→중부센터 등 최신 관할 확인
- [ ] cafe/restaurant/업종 생략 간 목록이 같고 업종 추천으로 표시하지 않음
- [ ] 맞춤 선정·현재 신청 가능·자격 보장 문구를 사용하지 않음
- [ ] BE 확인일 표시 및 공고/통계 날짜와 구분
- [ ] 외부 링크 새 탭/rel 속성 유지·새 공고 링크를 지점/예약 페이지로 표현하지 않음
- [ ] meta의 applied/not_applied·구 지정 전용 선택 필드와 공고일/확인일을 구분
- [ ] 422/500/네트워크 오류에서 기존 표시와 재시도 동작 확인
- [ ] FE lint/build·실제 BE 연결·계약/CLAUDE.md 반영 후 결과 전달

이번 #88은 일반1,260개(지원링크81개)·격리 PostGIS180개, 실제 로컬HTTP82요청을 통과했습니다. HTTP 검사는 DB/외부전송을 차단한 상태였으며 DB쿼리·실LLM 호출0입니다. 공고 본문/첨부 HTTP200·PDF25쪽의8센터/25구·전화 대조는 별도로 수행했습니다. FE 통합·브라우저 시연·FE CLAUDE.md 반영은 담당자 검증 결과로 확인하며 현재 대기입니다.
