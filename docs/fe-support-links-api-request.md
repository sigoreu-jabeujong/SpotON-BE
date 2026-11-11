# 상담·지원기관 링크 API 연동을 위한 FE 변경 요청 보고서

- 작성일: 2026-11-12
- 관련 작업: BE-33 / F-10, [BE #70](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/70)
- 상태: **BE 공통 목록 구현·검증 / FE 검토·연결 대기**

## 1. 실제 API 연결

`GET /api/support-links`를 기존 `getSupportLinks()`·`useSupportLinks()`·`SupportLinksSection`에 연결해 주세요. 기존 API별 mock 설정에서는 `/support-links`를 실제 경로에 추가할 수 있습니다. 다른 미구현 API까지 실제로 전환하지 않아도 됩니다. BE 주소와 `/api` 접두사는 기존 client 설정을 따릅니다.

| 인자 | 허용 값 | 처리 |
|---|---|---|
| sigungu | 서울25개 구의 정확한 이름, 예: 마포구 | 선택. 서울특별시 접두사·공백·빈값은 거절 |
| category | cafe 또는 restaurant | 선택. 대소문자/공백/다른 코드는 거절 |

생략은 허용하지만 `null` 문자열·빈 값·중복/미지원 인자는422 INVALID_PARAM입니다. 기존 client가 null/undefined/빈 문자열을 생략하는 경로를 그대로 재사용할 수 있습니다. 주소·좌표·건물 키·인증키를 추가로 보내지 않습니다.

## 2. 공통 목록과 우선순위 한계

원본 D-08의 네 기관을 같은 순서로 반환합니다. id·8개 필드·type·region은 기존 FE mock과 일치합니다. 링크 설명과 실제 확인일은 BE 값을 사용해 주세요.

| 순서 / id | 기관 | type | region |
|---|---|---|---|
| 1 / seoulsbdc | 서울시 자영업지원센터 | consulting | 서울 |
| 2 / seoulsbdc-edu | 소상공인아카데미 | support_program | 서울 |
| 3 / seoul-small-business | 서울시 소상공인 지원사업 안내 | support_program | 서울 |
| 4 / sbiz24 | 소상공인24 | support_program | 전국 |

**현재는 구/업종별 우선 정렬을 적용하지 않습니다.** 네 곳 모두 일반 안내이고 검증된 특정 구/업종 후보가 없으므로 입력에 따라 제외하거나 맞춤 선정된 것처럼 바꾸지 않습니다. `meta.prioritization={status:"not_applied",reason:"general_links_only"}`를 함께 반환합니다. 원본의 지역/업종 우선 정렬은 후속이며, 현재 목록을 “내 지역 맞춤 지원사업”이나 “신청 가능한 사업”으로 설명하지 말아 주세요. `useSupportLinks`의 기존 정렬 관련 설명·계약 문서도 이 범위로 검토해 주세요.

## 3. 항목·확인일·출처 표시

항목은 `{id,org_name,title,description,url,type,region,last_checked}`이며 모든 키가 있습니다. 현재 last_checked는 실제 수동 확인 KST 날짜 `2026-11-12`입니다. 오늘/생성일/배포일로 덮어쓰지 않습니다. 분기1회 수동 점검 기준이며 요청 시 사이트에 접속해 갱신하지 않습니다.

기존 `SupportLinksSection`의 `target="_blank" rel="noopener noreferrer"`와 확인일 표시를 유지해 주세요. 아카데미 주소는 공식 시작 URL `/main/index.jsp`이고 접속 시 같은 호스트의 `/main`으로 이동합니다. 네 기관 모두 확인 당시 HTTP200과 페이지 제목을 확인했으며 이후 접속·신청 완료·지원 자격을 보장하지 않습니다. 모집 기간·지원 조건은 연결된 공식 사이트에서 사용자가 확인하도록 안내해 주세요.

meta는 source=[R17], is_demo=false, link_catalog_version=support-links-v1입니다. as_of/space/denominator/collected_at/data_version은 null입니다. data_updated_at은 카탈로그의 last_checked 최대 날짜이며 공고 공표일·모집 마감일·통계 갱신일이 아닙니다. 공통 분석 기준일 화면에 잘못 합치지 말아 주세요.

기존 SupportLink 타입을 전면 변경할 필요는 없습니다. 선택한 meta를 타입으로 추가한다면 다른 분석 API에 필수로 강제하지 않습니다. 요청/정상 응답/오류는 no-store이며422 입력 오류·500 서버 오류를 기존 공통 외피로 반환합니다. 서버는 DB·LLM·외부 HTTP 호출 없이 목록을 제공합니다.

## 4. 검토 대상과 완료 기준

검토 대상은 `src/api/support.ts`, `src/types/support.ts`, `src/hooks/useSupportLinks.ts`, `src/components/share/SupportLinksSection.tsx`, API별 mock 설정·문구·`docs/api-contract.md`/`docs/decisions.md`/FE `CLAUDE.md`입니다. BE는 FE 코드·문서·이슈·PR을 직접 수정하지 않습니다.

- [ ] `/support-links` 실제 연결, 다른 경로 mock 설정 유지
- [ ] 구/업종 생략·변경 시4기관/출처/순서 유지 및 일반 안내 표시
- [ ] 맞춤 선정·현재 신청 가능·자격 보장 문구를 사용하지 않음
- [ ] BE 확인일 표시 및 공고/통계 날짜와 구분
- [ ] 외부 링크 새 탭/rel 속성 유지·정식 사이트 이동 확인
- [ ] 422/500/네트워크 오류에서 기존 표시와 재시도 동작 확인
- [ ] FE lint/build·실제 BE 연결·계약/CLAUDE.md 반영 후 결과 전달

BE는 새34개를 포함한 전체 일반1,052개와 로컬 실제 HTTP10개 확인을 통과했습니다. DB 변경이 없어 이번 작업에서 PostGIS 통합 suite를 재실행하지 않았습니다. FE 통합·브라우저 시연 완료는 담당자 검증 결과로 확인합니다.
