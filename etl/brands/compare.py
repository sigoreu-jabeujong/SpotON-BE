from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import and_, or_, select

from app.core.config import Settings
from app.db.session import create_db_engine
from app.models import Store
from etl.brands.catalog import Catalog, fail
from etl.brands.matching import PARTITIONS, Matcher
from etl.localdata.runner import check_local_database, validate_local_target


def compare_rows(catalog: Catalog, rows: Iterable[Mapping[Any, Any]]) -> dict[str, int]:
    matcher = Matcher(catalog)
    counts = {key: 0 for key in PARTITIONS}
    total = 0
    for row in rows:
        total += 1
        reason, _ = matcher.classify(row)
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
