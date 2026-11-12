from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import and_, or_, select

from app.core.config import Settings
from app.db.session import create_db_engine
from app.models import Store
from etl.brands.catalog import Brand, Catalog, fail, normalize_name
from etl.localdata.runner import check_local_database, validate_local_target

PARTITIONS = (
    "existing_classification",
    "missing_name",
    "weak_name",
    "repeated_brand_id",
    "ambiguous_name",
    "non_food_name",
    "exact_name_candidate",
    "no_exact_candidate",
)


def compare_rows(catalog: Catalog, rows: Iterable[Mapping[Any, Any]]) -> dict[str, int]:
    names: dict[str, list[Brand]] = defaultdict(list)
    for item in catalog.rows:
        names[item.normalized_name].append(item)
    identifiers = Counter(item.management_no for item in catalog.rows)
    repeated_names = {
        item.normalized_name for item in catalog.rows if identifiers[item.management_no] > 1
    }
    counts = {key: 0 for key in PARTITIONS}
    total = 0
    for row in rows:
        total += 1
        if row["is_franchise"] is not None or row["brand_id"] is not None:
            reason = "existing_classification"
        else:
            name = normalize_name(row["name"]) if row["name"] is not None else ""
            candidates = names.get(name, [])
            if not name:
                reason = "missing_name"
            elif sum(c.isalnum() for c in name) < 3 or not any(c.isalpha() for c in name):
                reason = "weak_name"
            elif name in repeated_names:
                reason = "repeated_brand_id"
            elif len(candidates) > 1:
                reason = "ambiguous_name"
            elif not candidates:
                reason = "no_exact_candidate"
            elif candidates[0].industry != "외식":
                reason = "non_food_name"
            else:
                reason = "exact_name_candidate"
        counts[reason] += 1
    if sum(counts.values()) != total:
        fail("comparison_partition")
    return {"total": total, **counts}


def compare_local(catalog: Catalog, settings: Settings) -> dict[str, int]:
    validate_local_target(settings)
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '60s'")
            connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            check_local_database(connection)
            query = (
                select(Store.name, Store.is_franchise, Store.brand_id)
                .where(
                    Store.deleted_at.is_(None),
                    Store.category_review_flag.is_not(True),
                    or_(
                        and_(Store.category == "cafe", Store.sub_category == "cafe"),
                        and_(
                            Store.category == "restaurant",
                            Store.sub_category.in_(("korean", "chinese", "japanese", "western")),
                        ),
                    ),
                )
                .execution_options(stream_results=True, yield_per=2000)
            )
            result = connection.execute(query)
            try:
                return compare_rows(catalog, result.mappings())
            finally:
                result.close()
    finally:
        engine.dispose()
