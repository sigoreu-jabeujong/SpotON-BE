-- Free 복제본의 서울 전체 Risk 집계용 물리 인덱스.
-- 원래20테이블/50인덱스/head0011과 구분하며 앱 모델의 migration 대상이 아니다.
-- 소유 계정·정적 데이터·예상 용량/여유를 먼저 확인한다.
-- autogenerate 대상으로 이 Free DB를 사용하지 않는다.
CREATE INDEX ops_free_risk_cover
ON public.stores (category, sub_category, open_date)
INCLUDE (close_date, status, date_flag, is_temporary, source, area_m2)
WHERE deleted_at IS NULL
  AND category_review_flag IS NOT TRUE
  AND geom IS NOT NULL;

-- 효과 없음/잘못된 정의/용량 초과/응답 회귀 시 롤백:
-- DROP INDEX public.ops_free_risk_cover;
