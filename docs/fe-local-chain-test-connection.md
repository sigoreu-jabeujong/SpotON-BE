# FE 담당자용 로컬 브랜드·AI API 연결 안내

## 접속 대상

이 PC에서 실행하는 최신 BE의 기준 주소는 `http://localhost:8001`이다. [Swagger](http://localhost:8001/docs), [준비 상태](http://localhost:8001/api/ready), [브랜드 준비 상태](http://localhost:8001/api/v2/brands/status)를 사용한다. localhost는 접속하는 PC 자신을 가리키므로 다른 팀원의 PC나 Vercel에서 이 주소로 접속할 수 없다. 외부 공개 접속/Render 배포는 이번 범위가 아니다.

검증 코드 기준은 BE `cdc5513`(PR150), 스키마0012다. 아래 검증은 로컬8001에서 실제 수행했다. FE 코드·설정·배포를 변경한 작업이 아니다.

## FE에서 연결할 항목

개발 FE를 `http://localhost:5180` 또는 `http://127.0.0.1:5180`에서 실행하고, 개발 프로세스의 `VITE_API_BASE_URL`을 `http://localhost:8001`로 지정한다. 실제 조회 확인 시 mock을 해제하고 모든 브랜드 조회/분석/AI를 아래 v2 계약으로 함께 전환한다. 이 작업에서 FE .env는 수정하지 않았다. 원래8000은 이전 실행본이므로 이번 기능의 검증 대상으로 사용하지 않는다.

- `GET /api/v2/brands/status`
- `GET /api/v2/stores/nearby`, `/api/v2/stores/snapshot`, `/api/v2/stores/history`
- `GET /api/v2/market/activity`, `/api/v2/risk`
- `POST /api/v2/risk/interpret`
- 조회 가능 월 범위는 기존 `GET /api/meta/data-range`를 유지

기본 요청 예:

```http
GET /api/v2/stores/nearby?lat=37.5665&lng=126.978&category=cafe&radius=500&brand_scope=chain&brand_unknown=exclude&brand_evidence=include_estimates
```

같은 query를 snapshot/활동/Risk에도 전달한다. snapshot에는 `as_of=YYYY-MM`이 필수다. 일반 조회의 `as_of`를 생략하면 검증된 최신 기준을 사용한다. history는 실제 선택한 `building_key`와 선택적인 `floor_unit/category`만 보내고 브랜드 필터를 보내지 않는다.

```json
{
  "query": {
    "lat": 37.5665,
    "lng": 126.978,
    "category": "cafe",
    "radius": 500,
    "brand_scope": "chain",
    "brand_unknown": "exclude",
    "brand_evidence": "include_estimates"
  }
}
```

위 JSON은 `/api/v2/risk/interpret`의 body다. 기존 v1 AI에 브랜드 조건을 누락해서 보내지 않는다. 실제 선택한 근처 건물의 전체 이력을 포함하려면 선택적인 `history`를 [AI 계약](fe-chain-ai-api-request.md)에 맞춰 추가한다. 클라이언트가 계산한 지표/본문/문맥/세대를 body에 추가하지 않는다.

## 필터와 표시

| 목적 | brand_scope | brand_unknown | brand_evidence |
|---|---|---|---|
| 전체 | all | include | include_estimates |
| 체인 추정만 | chain | exclude | include_estimates |
| 확인된 체인만 | chain | exclude | confirmed_only |
| 확인된 비체인만 | non_chain | exclude | include_estimates |
| 체인 추정 제외 + 미확인 포함 | non_chain | include | include_estimates |

가맹·직영·소규모 체인을 함께 포함한 **브랜드 소속 추정**이다. 확인된 체인/비체인 자료는 아직 없어 표의 엄격 확인 조건은0건이다. 미확인을 ‘개인 매장’으로 바꾸지 않는다. `chain/include`는 미확인도 포함하므로 체인만 보는 조건이 아니다. `confirmed_only/include`는 추정도 필터상 미확인으로 취급한다. 운영 형태는 `operation_type=any`, 시점은 `brand_time_basis=observed_record`만 지원하고 과거 소속을 확정하지 않는다.

scope가 all이 아니면 unknown을 명시해야 한다. v2에는 기존 franchise/include_unknown_franchise/include_unknown를 보내지 않는다. 중복/미지원 인자나 history에 브랜드 조건을 보내면422다.

`meta.brand_counts`는 **필터 전** 동일 조건의 좌표 보유 인허가 기록 수다. 목록/분석 count는 **필터 후**다. `brands/status`의 publication_counts는 저장 원천 기준이므로 현재 영업점 수나 브랜드별 실제 지점 수가 아니다. 상세는 [v2 조회 계약](fe-chain-v2-api-request.md)을 따른다.

AI는 검증된 `data.body`를 plain text로 표시하고4문단·추정/미확인/과거 소속 한계 안내를 유지한다. 조건이 바뀌면 이전 해석을 붙이지 않고 취소/재요청한다. 조회와 AI의 조건·기준 시점·generation이 같아야 한다. v1/v2 요청 한도는 기본5회/분·50회/일·동시2·20초를 공유한다.503 AI_UNAVAILABLE/AI_VERIFY_FAILED에서는 기존 지표를 유지하고 해석 실패를 표시한다. 성공/오류 응답은 no-store다.

## 데이터 변경 경계와 운영 범위

공개 후 stores에 DML/TRUNCATE(no-op UPDATE 포함)가 실행되면 source revision이 증가한다. 소진공 주소 대조 근거는 재검증 전 unknown/source_drift로 내려가고, 이름 근거도 해당 점포의 비교 입력이 바뀌면 stale_input이다. 동일 입력의 이름 근거까지 모두 사라지는 것은 아니다. status와 결과 상태를 확인하고 원천 작업 후 재계획/재공개한다. generation만 같다고 자료가 그대로라고 판단하지 않는다.

이번 서버는 로컬 test 환경의 기존 spoton_app 소유자 역할을 사용한다. 요청 DB 세션은 READ ONLY지만 production용 읽기 전용 계정 구성 완료를 뜻하지 않는다. 원래 .env와 LLM 키/모델/한도를 유지하고 키나 원문 점포/주소/인허가를 FE 설정·문서·외부 모델 입력에 넣지 않는다.

서버는 이 PC의 백그라운드 프로세스로 실행한다. PC 종료/재부팅 뒤 자동으로 재시작하지 않으므로 BE 담당자가 보관한 기동 설정(test 환경·기대0012·5180 CORS)으로 다시 실행하고 health/ready/status를 확인한다.

## 실제 검증 결과

2026-11-15 로컬8001 적용·검증 완료. health/ready200, schema0012·ALWAYS trigger·공개1세대·source_drift=false를 확인했다. 카페/음식점 각각12필터 조건(총24)에서4종 수 일치, 입력 오류7종422/no-store, 건물 전체 이력10건 불변,5180 CORS 및 Risk 동시3건200을 확인했다. 실제 Gemini 호출2건 모두 성공했고4문단/숫자39·42개/불일치0·재생성false였다. 반복 요청은 모델 추가 호출 없이 본문/근거/context가 같았다. generated_at은 응답마다 새 시각이므로 캐시 일치 비교에 쓰지 않는다. 백업은 저장소 밖에 보관했고 새 DB에 복원해 기존21표 전체 hash를 대조했다(97,875,726bytes, SHA256 앞자리 `a0b4276c75ebbbc8`). 원문이 포함된 덤프나 사용자 폴더의 절대 경로는 전달 자료에 포함하지 않는다.

동일500m·현재 기준 참고 건수(기록 단위):

| 업종 | 전체 | 체인 추정만 | 확인 비체인만 | 확인 체인만 |
|---|---:|---:|---:|---:|
| cafe | 150 | 18 | 0 | 0 |
| restaurant | 566 | 21 | 0 | 0 |

실제 점포 수/과거 브랜드 소속 확정이 아니다. 원래 점포689440행·legacy·기존 업무 표 전체 값/좌표와 .env는 보존했다. 기존표 중 alembic_version만0011→0012로 바뀌고 새 판정 표/트리거·관련 객체를 추가했다.
