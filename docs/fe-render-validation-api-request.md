# FE 전달: Render 검증용 BE 연결

- 확인일: 2026-11-14
- BE 배포·대표 API 검증 완료. FE 저장소·환경변수·배포는 수정하지 않았다.
- 상세 검증: [무료 전환 결과](render-free-validation.md). 기존 유료 BE·DB는 삭제됐으며 이전 URL을 사용하지 않는다.

## 1. 연결 설정

검증 환경의 API base URL은 `https://spoton-be-free.onrender.com`이다. FE 담당자가 사용할 검증 환경에 다음 값을 설정하고 FE를 다시 실행/빌드한다.

```dotenv
VITE_API_BASE_URL=https://spoton-be-free.onrender.com
VITE_USE_MOCK=false
```

현재 FE 클라이언트가 `/api`를 붙이므로 값 끝에 `/api`를 추가하지 않는다. API 문서는 https://spoton-be-free.onrender.com/docs 이다. 실제 API 검증에서는 목업 모드를 끈다.

무료 BE는15분 무요청 후 절전한다. 이번 첫 health 요청은22.593초였고 현재 FE 기본 요청 제한15초를 넘었다. 무료 검증 환경의 첫 요청은60초 정도 대기하거나 재시도 안내를 제공하도록 담당자가 조정한다. Free의 SQL 제한10초·풀1/대기15초는 전체 HTTP 시간 상한이 아니며, AI503은 계속 별도로 처리한다. 이 BE 작업에서는 FE 코드를 수정하지 않았다.

현재 허용된 브라우저 origin은 `http://localhost:5173` 한 개다. FE를 다른 포트나 공개 도메인에 배포하면 담당자가 정확한 origin을 전달하고 BE의 CORS_ORIGINS에 추가한 뒤 배포해야 한다. 경로·와일드카드·DB 주소를 FE 설정에 넣지 않는다. 브라우저는 BE만 호출한다.

## 2. 적용 범위

- 주소 검색, 이력, 월 범위, 주변/과거 점포, 활동/Risk, 지원 링크는 기존 API 계약을 따른다. 공개24개 비교 및 실제 주소 검색·CORS 검증을 통과했다.
- AI 해석은 이번 검증 서비스에서 의도적으로 비활성화했다. LLM 키가 없어503 AI_UNAVAILABLE을 반환한다. 해석 버튼/안내는 이 오류를 처리해야 하며 더미 해석을 만들지 않는다.
- 공식 창업위험도는 기존 link_only·value=null·copy_text=null을 유지한다. 공식 market_change 등 pending 항목은 배포로 수치가 활성화된 것이 아니다.
- 최소·최대 조회 월은 `/api/meta/data-range`를 먼저 조회한다. 요청 as_of=YYYY-MM, 실제 적용일 meta.as_of=YYYY-MM-DD, 오류 meta={} 및 error의 code/message 계약을 유지한다.
- `/api/ready`는 Render 운영 검사이며 FE 업무 호출의 선행 조건으로 추가할 필요가 없다. 기존 `/api/health`도 유지한다.

## 3. FE 담당 검증

이 base URL을 사용해 주소 선택 → 건물/상세 위치 이력 → 주변/과거/활동/Risk 화면과 기존 오류·결측 표시를 확인한다. 브라우저 지도는 별도 Kakao 브라우저 키와 해당 FE 도메인 등록이 필요하다. BE 주소 검색200으로 FE 지도 연결 완료를 대신하지 않는다.

FE 통합·공개 배포·LLM 활성화·운영 전환은 아직 완료로 표시하지 않는다. API 계약에 관한 기존 BE 측 수정 요청 문서도 함께 적용한다.
