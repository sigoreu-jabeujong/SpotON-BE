# AI 해석 OpenAI 전환

2026-11-17 사용자 요청으로 활성 공급자를 OpenAI, 기본 모델을 gpt-4.1-mini로 변경한다. Responses REST API의 구조화 출력(text.format/json_schema/strict)과 store=false를 사용한다. 기존 httpx 의존성·제한된 REST 전송의 시간 예산/요청 한도/실제 시도 계수를 재사용하고, OpenAI의 인증 헤더·요청·응답/사용량·거절/불완전/할당량 오류를 별도로 처리한다. Google 호환 코드는 복구용으로 보존하며 활성 공급자는 서버 설정으로 결정한다.

보고서 신규 생성은 이점·유의점·종합 해석의 3호출이며 공급자/검증 재시도는 없다. 같은 RR·baseline 대조·문장 ID 선택·서버 수치 검증·필수 한계·체크리스트·캐시를 유지한다. 공급자/모델이 캐시 키에 포함되므로 이전 공급자의 결과와 섞이지 않는다. 서버 준비35초/전체60초/FE75초는 유지한다.

FE는 AI 결과의 metrics 수치·출처 카드 전체를 제거한다. 접기/참고/인쇄로도 노출하지 않는다. 이점·유의점·해석 문단·기존 계약 전 확인사항은 유지하며 metrics는 서버 내부 근거와 응답 검증에만 사용한다. 다른 분석 화면의 지표/카드는 변경하지 않는다.

LLM_PROVIDER/LLM_MODEL/LLM_API_KEY만 서버에서 변경하며 나머지 환경값을 대조한다. 제공 키는 숨김 입력으로 메모리에만 전달하고 코드·문서·파일·로그·FE 환경에 저장하지 않는다. 운영 전 직접 OpenAI 구조화 출력 probe200을 확인했다. 어댑터/기존 전송 테스트58건, ruff/mypy129파일, FE lint/production v2 빌드를 확인했다. 배포 이후 실제 보고서·UI 결과는 릴리스 PR에 기록한다.

공식 계약: [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create), [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
