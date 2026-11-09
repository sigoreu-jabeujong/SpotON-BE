# CLAUDE.md — SpotON-BE

## 프로젝트 개요
- **Spot:ON**: 예비 창업자에게 창업 입지(자리)를 진단해 주는 공공서비스
- 팀: 시고르자브종 (청년공공AX서포터즈)
- 이 저장소: **백엔드(API 서버)**. 프론트엔드는 `../SpotON-FE`
- 최종적으로 공공 GitLab 등록 및 공공기관 배포 예정 → 특정 클라우드·유료 서비스에 묶이지 않게 작성

## 기술 스택
- Python 3.11, FastAPI, Uvicorn
- 검사 도구: ruff(코드 스타일), pytest(테스트)
- 생성형 AI: **무료 모델만 사용** (모델명·키는 `.env`의 `AI_MODEL`, `AI_API_KEY`)

## 폴더 구조
```
app/
├── main.py        # FastAPI 앱 생성, 라우터 등록, CORS
├── api/           # 엔드포인트(라우터). 요청 검증과 응답 반환만 담당
├── services/      # 비즈니스 로직 (입지 점수 계산, AI 호출 등)
├── data/          # 공공데이터 수집·전처리 코드
├── schemas/       # Pydantic 요청/응답 모델
└── core/          # 설정(config), 공통 에러 처리
tests/             # pytest 테스트
```
- 라우터에 로직을 넣지 말고 `services/`로 분리
- 원본 공공데이터 파일은 `datasets/`(커밋 제외)에 둠

## 자주 쓰는 명령어
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # 이후 실제 키 입력
uvicorn app.main:app --reload      # http://localhost:8000/docs
ruff check . --fix
pytest -q
```

## API 응답 형식 (FE와 반드시 동일하게 유지)
```json
// 성공
{ "success": true, "data": { ... }, "error": null }
// 실패
{ "success": false, "data": null, "error": { "code": "INVALID_REGION", "message": "지원하지 않는 지역입니다." } }
```
- 모든 엔드포인트는 이 형식을 따른다
- 형식을 바꾸면 `../SpotON-FE/CLAUDE.md`도 함께 수정한다
- API 경로는 `/api/v1/...` 으로 시작

## 코딩 규칙
- 함수·변수에 **타입 힌트 필수**, 요청/응답은 Pydantic 모델 사용
- 외부 API 호출은 `services/`에서 하고, 타임아웃과 예외 처리를 넣는다
- 새 기능에는 최소 1개 이상의 pytest 테스트 추가
- 설정값은 하드코딩하지 말고 환경변수로 읽는다
- 주석·에러 메시지는 한국어 사용 가능, 변수·함수명은 영어 snake_case

## Git 규칙
- 브랜치: `main`(최종) ← `dev`(통합) ← `feat/기능명`, `fix/버그명`, `docs/문서명`
- `main`, `dev`에 직접 커밋·push 하지 않는다. 작업은 항상 새 브랜치에서
- 커밋 메시지: `타입: 내용` (예: `feat: 상권 점수 조회 API 추가`, `fix: 좌표 변환 오류 수정`)
  - 타입: feat, fix, refactor, docs, test, chore

## 절대 하지 말 것
- `.env` 파일을 읽어서 출력하거나, 내용을 코드·로그·커밋에 넣지 않는다
- API 키를 코드에 직접 쓰지 않는다
- 유료 API나 유료 모델을 추가하지 않는다
- `git push --force`, 브랜치 삭제 등 되돌리기 어려운 명령은 사람에게 확인받기 전에 실행하지 않는다
- 개인정보(이름, 연락처 등)를 로그에 남기지 않는다
