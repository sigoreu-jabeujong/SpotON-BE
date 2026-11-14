-- #128: analysis-name policy v1, alongside the legacy rollback index.
-- Model/migration/head0011 and original rows remain unchanged.
-- Verify capacity, exact predicate/generic plan and old API data before deployment.
CREATE INDEX ops_free_risk_name_v1
ON public.stores (category, sub_category, open_date)
INCLUDE (close_date, status, date_flag, is_temporary, source, area_m2)
WHERE deleted_at IS NULL
  AND category_review_flag IS NOT TRUE
  AND geom IS NOT NULL
  AND (
    category <> 'restaurant'
    OR name IS NULL
    OR name = ''
    OR name !~ '(치킨|통닭|호프|주점|포차|맥주|분식|김밥|떡볶|피자|카페|커피|[cC][aA][fF][eE]|[cC][oO][fF][fF][eE][eE]|베이커리|제과|빵집|[bB][aA][kK][eE][rR][yY])'
  );

-- Roll back application code first; preserve ops_free_risk_cover/ix_stores_provenance.
-- DROP INDEX public.ops_free_risk_name_v1;
