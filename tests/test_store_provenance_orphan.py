"""Issue #118: compiled shape of the skip-scan orphan check (no database needed)."""

import re

from sqlalchemy.dialects import postgresql

from app.services.store_cohort import orphan_exists


def compiled() -> str:
    statement = orphan_exists().compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return " ".join(str(statement).split())


def test_orphan_check_is_recursive_key_skip_scan_with_null_branch() -> None:
    sql = compiled()
    assert sql.startswith("WITH RECURSIVE provenance_keys(batch_id, source) AS")
    # Non-recursive term keeps ORDER BY/LIMIT inside parentheses before UNION ALL.
    assert re.search(r"AS \(\(SELECT .+? LIMIT 1\) UNION ALL SELECT", sql)
    assert "JOIN LATERAL" in sql
    assert (
        "(stores.batch_id, stores.source) > (provenance_keys.batch_id, provenance_keys.source)"
        in sql
    )
    assert "stores.batch_id IS NOT NULL" in sql
    assert "stores.batch_id IS NULL" in sql
    assert "store_import_batches.batch_id = provenance_keys.batch_id" in sql
    assert "store_import_batches.source = provenance_keys.source" in sql


def test_every_store_scan_keeps_supported_store_predicate() -> None:
    sql = compiled()
    # Three stores scans: first key, following key, NULL batch branch.
    assert sql.count("FROM stores") == 3
    assert sql.count("stores.deleted_at IS NULL") == 3
    assert sql.count("stores.category_review_flag IS NOT true") == 3
    assert sql.count("stores.source IN ('general_restaurant', 'rest_cafe')") == 3
