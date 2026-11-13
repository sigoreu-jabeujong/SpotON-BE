# Render 무료 검증 환경 전환

- 요청일: 2026-11-13 (Asia/Seoul)
- 이슈: [#109](https://github.com/sigoreu-jabeujong/SpotON-BE/issues/109)
- 설계·실제 Claude 검토·최종 결정: [설계 문서](designs/feat109-render-free-migration.md)
- 완료 확인: **2026-11-14 (Asia/Seoul), 카드 없는 Free DB·BE 생성·데이터/API 검증·이전 유료 자원 삭제 완료.**

## 1. 카드 없는 상태에서의 생성 확인

사용자가 Billing에서 카드 삭제 완료를 확인했다. API에는 카드 등록 여부 조회 기능이 없어 이 확인과 실제 리소스 생성 결과를 구분한다. 이후 plan=free로 PostgreSQL17 생성 요청을 보내 성공했다. 유료 플랜으로의 재생성·카드 재등록·유료 리소스 재개는 수행하지 않았다.

| 항목 | 실제 상태 |
|---|---|
| 신규 DB | spoton-db-free / dpg-dbrhh4rm8hqs73d2mlgg-a |
| DB plan | free |
| 리전 | Singapore, 기존과 같은 workspace |
| PostgreSQL | 17 |
| 생성 | 2026-11-13 23:02:59 KST |
| 만료 | **2026-12-13 23:02:59 KST** |
| DB 이름 | spoton_free_check |
| 신규 BE | spoton-be-free / srv-dbri09k9v7es73clfpl0 / free |
| API | https://spoton-be-free.onrender.com |
| 배포 commit | d449c5f0e86778a15fddac28722d0d6833fe8779 |
| 현재 DB 크기 | 721,131,187 bytes, 약721MB |
| 이전 유료 BE/DB | 모두 삭제, 기존 두ID 조회404 |
| 남은 자원 | 무료 BE1·무료 DB1, 유료 컴퓨팅0·지속 디스크0·Key Value0 |

기존 BE와 DB는 사용자 설명과 달리 API상 삭제가 아닌 user suspended 상태였다. BE의 유료→free 직접 변경 요청은 Render가400 `cannot change between free and paid plans`로 거절했다. 따라서 새 무료 웹 서비스를 생성하고 검증 뒤 이전 자원을 삭제하는 방식을 사용한다.

## 2. 데이터 보존과 복원

보존 덤프97,881,270 bytes의 SHA256 `dad8925acc3479cf4755aaba3fa00034f8037a98f47c0c038ba755e05b117b56`와 새 작업 디렉터리 사본의 SHA가 일치했다. `pg_restore --list`에서20개 TABLE DATA 항목을 확인했다. 로컬 개발DB의20테이블 전체 비공간 행/geometry 지문이 이 덤프의 검증 baseline과 일치했다.

사용자가 중지한 유료 DB는 재개하지 않았다. 중지 이후의 새 원격 지문은 조회하지 못했으며, 선행 [유료 DB 복원 검증](render-postgres-restore-validation.md)·보존 덤프·일치하는 로컬 원본을 기준으로 사용한다. 서로 다른 물리 디스크에 분산된 재해 백업은 보장하지 않는다.

새 DB의 빈 스키마·대상·버전을 확인한 뒤 PostGIS3.6.2를 설치했다. 원래 검토한 TOC로 앱 스키마·데이터·인덱스·제약·시퀀스를 외부 TLS verify-full, single-transaction/exit-on-error로 복원했다. 복원1068.92초·20개 테이블 VACUUM/ANALYZE를 완료했고 크기는675,092,147 bytes다. 데이터나 인덱스를 줄이지 않았고 새로운 가상 수치를 만들지 않았다.

전체 행/geometry 해시 계산은120초 유지보수 제한을 초과했고,600초로 확대한 서버 정렬은 임시 디스크 공간 부족으로 중단됐다. 원본 데이터는 변경되지 않았고 DB 상태도 available을 유지했다. 이를 해결하기 위해 같은 PostgreSQL 행별 MD5와 EWKB별 MD5를 named cursor/10,000행 단위로 스트리밍해 로컬에서 ASCII(C) 순서 정렬·연결 MD5를 계산했다. 원문 행을 전송하지 않고 해시만 전송했으며, 원래 baseline의20테이블 전체 count/rows_md5/NULL 수/EWKB MD5와 정확히 일치했다. 원래 baseline·덤프는 수정하지 않았다.

원래50인덱스·110제약·3시퀀스·head0011과 모델 차이0을 확인했다. PostGIS3.7→3.6 CHECK 표현15개는 원래 복원 시험과 같이 대상에서 재파싱한 정의의 동등성을 검증했다. reader의 SELECT20개 및 READ WRITE 상태의 INSERT/CREATE/TEMP/소유 역할 SET ROLE 거절4개도 확인했다. 기본READONLY·jit off·SQL10초·연결8 설정이며 새 비밀번호는 별도 Windows DPAPI에만 보관했다.

Free에서 기존 SQL3초로 snapshot/Risk 요청이500을 반환했고 실제 SQLSTATE57014를 확인했다. JIT off만으로 해소되지 않았다. **무료 검증 서버만 SQL10초·API 풀1·overflow0·pool 대기15초**로 설정하고 전체 API를 다시 검증한다. 워커1·별도 ready1·교체2배 상한4개는 예산/역할 제한8 안이다. 로컬 .env·기본3초·데이터·응답 형식은 유지한다. readiness의2.5초/750ms 제한은 그대로다.

## 3. 조회 최적화와 최종 검증

SQL10초에서도 음식점 Risk가57014로 실패했다. 실제 실패 SQL의 서울 전체 비교 집계가 기존 ix_stores_provenance Index Scan으로 원본 heap을 많이 읽는 것을 확인했다. JIT off만으로 해결되지 않았다.

Claude의 추가 문서 검토 후 SQL 원문·predicate·컬럼을 직접 확인하고, 사전 용량 추정 및 실제 EXPLAIN ANALYZE/BUFFERS를 확인했다. [운영 인덱스 SQL](sql/render-free-risk-cover.sql)의 ops_free_risk_cover를 이 Free 복제본에만 추가했다. 실제 인덱스45,883,392 bytes이고 생성21.88초, 생성 후 전체 DB 약721MB로800MB 게이트를 통과했다.

| 동일 집계의 단일 관측 | 이전 | 추가 후 |
|---|---:|---:|
| 실행 시간 | 12,588.909ms | 2,777.128ms |
| 계획 | 기존 Index Scan | ops_free_risk_cover Index Only Scan |
| shared read blocks | 65,665 | 3,327 |
| Heap Fetches | heap 접근 필요 | 0 |

데이터·계산식·API SQL·앱 모델·migration head는 변경하지 않았다. 원래50개 인덱스와 별도 운영1개, 총51개다. catalog의 key3/include6·partial predicate·valid/ready/live를 검증했다. 모델 비교에서 이 정확한 운영 인덱스1개만 예상 차이로 제외하면 예상하지 않은 차이는0개다. 이 Free DB를 autogenerate 대상으로 사용하면 drop_index가 생성될 수 있으므로 사용하지 않는다. 향후 컬럼/타입 변경 때 운영 인덱스를 재검토한다. 새 Free DB는 원래 덤프 복원·기준 정합성 확인 후 이 운영 SQL을 별도로 적용한다. 효과 없음·용량 초과·응답 회귀 때의 DROP 롤백은 SQL 파일 주석과 설계를 따른다.

| 공개 검증 | 실제 결과 |
|---|---|
| API24건 | 정상22건200·오류2건422, 로컬 DB API와 전체 JSON 일치 |
| 반경 경계3건 | 499.999/500m 포함, 500.001m 제외, 로컬과 일치 |
| 동시 요청 | 동시3으로 카페 Risk6건, 모두200·동일 결과, 최장6.985초 |
| 절전 후 첫 health | 22.593초,200 |
| 준비 후24개 중 health 제외 최장 | 8.656초, 단일 관측이며 SLA 아님 |
| 실제 주소 검색 | 서울시청 주소200 |
| CORS | localhost5173 허용200, 미허용 origin400 |
| 준비 검사 | /api/ready200 |
| 내부 API DB 연결 | spoton_api·내부 대상·TLSv1.3, 풀 연결1개 확인 |
| AI | LLM 키 생략, 실제503 AI_UNAVAILABLE·모델 호출 없음 |

검증 후 이전 BE srv-dbrh4tutlv9c738h2ku0와 DB dpg-dbrgd70u01pc73b653sg-a만 삭제했다. 삭제 직전 백업SHA·새 DB/BE Free·내부 reader 대상·전체 지문·공개 API 결과를 검사했고, 삭제 후 두ID404와 남은 무료 웹1/DB1·지속 디스크0·Key Value0을 확인했다. 유료 자원을 중지 상태로 방치하지 않았다. 과거 리소스의 연결정보는 유효한 현재 설정이 아니다.

실행·데이터 검증 증빙과 암호화된 자격증명은 저장소 밖 비공개 디렉터리에 보존했다. 비밀번호·DB URI·인증 토큰·외부 IP 원문은 저장소에 포함하지 않았다. 앱 코드·로컬 .env·개발DB·FE 파일은 변경하지 않았다. 선행 코드의 일반1595건·PostGIS251건 검증에 더해 이번 전환의 실데이터/실제 HTTP 검증을 수행했다.

## 4. 무료 한계와 복구

무료 BE는15분 무요청 시 절전하고 다음 접속 때 시작 지연이 있다. workspace 전체 무료 웹750시간 한도를 공유한다. 무료 DB는1GB 고정·생성30일 후 만료이며 관리형 자동 백업이 없다. [Render 무료 정책](https://render.com/docs/free)

카드가 없는 무료 계정은 포함량 초과 시 서비스나 새 빌드가 중단될 수 있다. 기존에 발생한 요금은 무료 전환으로 취소되지 않는다. API로 Billing/청구 내역을 확인할 수 없어 미납0·과거 요금 환불을 주장하지 않는다. [과금 안내](https://render.com/docs/faq), [결제 약관](https://render.com/terms)

만료 전에 검증을 종료하거나 보관 덤프에서 새로운 무료 검증 DB를 만들고 동일한 복원·권한·API 검증을 반복해야 한다. 자동 재생성/예약/영구 무료 운영은 구현하지 않았다. 로컬 개발DB와 .env는 계속 로컬을 사용하며 FE 저장소는 수정하지 않는다. LLM 키는 검증 서버에서 생략한다.

현재 FE 기본 요청 제한은15초인데 이번 절전 후 첫 요청은약23초였다. 무료 검증 환경에서는 첫 호출을60초 정도 기다리거나 오류/재시도 안내를 제공하도록 FE 담당자가 조정해야 한다. FE 연결·공개 도메인 CORS 추가는 [FE 전달 문서](fe-render-validation-api-request.md)를 따른다. SQL10초·pool 대기15초는 전체 HTTP 요청 시간의 상한이 아니며 동시 요청이 많으면 지연/오류가 발생할 수 있다.
