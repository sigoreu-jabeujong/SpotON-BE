# 브랜드 공개 세대 관리 CLI 초안 (#149)

**Claude 검수 전 Draft 구현이다.** 기존 [#145 설계](designs/feat145-chain-publication-api.md)의 후속이며, 신규 세부 설계/코드의 실제 Claude 검수가 사용 한도로 미완료다. [#149 설계·실제 검증](designs/feat149-chain-publication-maintenance.md)을 먼저 확인한다. FE·API·head0012·.env·기존 서버·원본/운영 DB·Render를 변경하지 않았다. 아래 쓰기는 실제 운영 DB에서 실행한 기록이 아니며 폐기용 DB로만 검증했다.

## 읽기 전용 계획

```powershell
uv run --locked --extra dev python -m etl.chains.maintenance
uv run --locked --extra dev python -m etl.chains.maintenance --action disable
uv run --locked --extra dev python -m etl.chains.maintenance --action prune --generation "<보관된 비활성 UUID>"
```

기본은 READ ONLY RR이다. list는 보관 세대·활성 여부·메타 건수·현재 물리 bytes만 반환하고 쓰기 옵션을 받지 않는다. disable/prune은 예상 내용과 포인터를 묶은 expected_plan_sha256을 반환한다. prune 대상은1~3개이며 --generation을 반복한다. 활성 세대를 포함하면 전체 거절한다. 출력에 점포명·주소·인허가·registry 원문·비밀값은 없다.

## 명시 쓰기

쓰기 전 DB 백업과 재현용 snapshot/registry를 보존하고 계획/결과를 저장소 밖 실행 기록에 남긴다. 쓰기 대상은 기존 ETL과 같은 loopback spoton_dev·spoton_app·비슈퍼유저/PostGIS/head0012로 제한된다. 원격/Render/조회 역할을 위한 관리 API는 없다.

```powershell
uv run --locked --extra dev python -m etl.chains.maintenance --action disable --write --expected-plan "<disable 계획 hash>" --expected-active "<계획의 active 또는 none>"
uv run --locked --extra dev python -m etl.chains.maintenance --action prune --generation "<같은 비활성 UUID>" --write --expected-plan "<prune 계획 hash>" --expected-active "<계획의 active 또는 none>"
```

disable은 포인터만 내리고 모든 세대/판정을 보존한다. 정상 guard 아래 v2가 pending을 반환하며 엄격 체인0건을 체인 부재로 설명하지 않는다. guard/trigger 손상을 수리하는 명령은 아니다. prune은 명시한 비활성 세대의 판정→브랜드→세대만 원자적으로 삭제한다. 원본 stores·legacy 브랜드5테이블·원천 revision은 수정하지 않는다.

expected plan/active가 모두 맞아야 한다. 같은 UUID로 되돌아온 포인터도 활성 시각이 달라지면 오래된 계획은 거절된다. 이후 세대/대상 내용 변경·중간 실패·외부 FK는 전체 rollback이다. 삭제 후 같은 옛 계획을 다시 실행하면 대상 없음/변경 오류이며, 성공했다고 추측하지 말고 list와 새 계획으로 확인한다. 이미 pending인 disable도 새 계획을 확인하면 DML 없는 no-op이다.

결과의 generations_before는 실행 전, generations와 active_after는 실행 후다. removed는 실제 삭제 건수다. 3세대가 찼을 때 이전 세대를 명시 정리하면 다음 publication이 가능하지만 자동 정리·상한 확장은 하지 않는다. source ETL·publication·관리 쓰기는 순차 실행한다.

## 공간과 재공개

DELETE는 파일 크기를 줄이지 않으며 publication_bytes_after가 그대로일 수 있다. 아래는 별도 관리 작업의 예이며 이 CLI가 자동 실행하지 않는다. publication/정리와 순차 실행하고 원본 stores/legacy 표를 대상으로 바꾸지 않는다.

```sql
VACUUM (ANALYZE, TRUNCATE FALSE) public.store_chain_classifications;
VACUUM (ANALYZE, TRUNCATE FALSE) public.chain_publication_brands;
VACUUM (ANALYZE, TRUNCATE FALSE) public.chain_publications;
```

일반 VACUUM은 공간을 재사용 가능하게 만드는 절차이며 물리 축소 보장은 아니다. [PostgreSQL17 설명](https://www.postgresql.org/docs/17/routine-vacuuming.html)을 따른다. 128MiB 물리 한도를 계속 넘으면 다음 publication은 거절된다. FULL/REINDEX·운영 DB 권한 변경·상한 조정은 이 기능에 포함하지 않는다.

pending에서 다시 공개하려면 기존 `etl.chains.publication --activate ... --write --expected-active none`에 원래 registry/snapshot을 제공하거나 새 dry-run/write를 수행한다. 현재 원천·전체 판정 내용이 맞아야 하며 과거 원천으로 자동 rollback하지 않는다. prune으로 삭제한 세대의 복원을 약속하지 않는다.
