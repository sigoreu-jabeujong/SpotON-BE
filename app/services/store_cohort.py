"""API v1.2 §2-2/§4-3/§4-5: shared provenance and reliable license intervals."""

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, exists, literal, or_, select, true, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import Store, StoreImportBatch
from app.schemas.common import ApiMeta, ErrorCode
from app.schemas.store_filters import CategoryFilters
from app.services.store_scope import (
    NAME_EXCLUSION_VERSION,
    SOURCE_SUPPORTED_STORES,
    SUPPORTED_STORES,
    name_exclusion_meta,
)

MIN_OPEN_DATE = date(1960, 1, 1)


def temporal_cohort(query: CategoryFilters, reference: date) -> list[ColumnElement[bool]]:
    """Before T, attributes or geometry; closed historical rows can set min_month."""
    sub = query.sub_category or (
        ("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western")
    )
    return [
        SUPPORTED_STORES,
        Store.category == query.category,
        Store.sub_category.in_(sub),
        Store.is_temporary.is_not(True),
        Store.open_date >= MIN_OPEN_DATE,
        Store.open_date <= reference,
        # Every nonempty date flag denotes an unreliable date (unknown tokens too).
        or_(Store.date_flag.is_(None), Store.date_flag == ""),
        or_(
            Store.close_date.is_(None),
            and_(Store.close_date >= Store.open_date, Store.close_date <= reference),
        ),
        or_(Store.close_date.is_not(None), Store.status != "closed", Store.status.is_(None)),
        or_(Store.close_date.is_(None), Store.status != "open", Store.status.is_(None)),
    ]


def orphan_exists() -> Select[tuple[bool]]:
    """Issue #118: is any supported store unlinked from store_import_batches?

    Same meaning as the former anti-join over every supported store, but it walks only the
    distinct (batch_id, source) keys of supported stores with ix_stores_provenance (skip scan),
    so the cost follows the key count instead of the row count. NULL batch_id never matches
    a row comparison, so it is checked separately.
    """
    first = (
        select(Store.batch_id, Store.source)
        .where(SOURCE_SUPPORTED_STORES, Store.batch_id.is_not(None))
        .order_by(Store.batch_id, Store.source)
        .limit(1)
    )
    keys = first.cte("provenance_keys", recursive=True)
    following = (
        select(Store.batch_id, Store.source)
        .where(
            SOURCE_SUPPORTED_STORES,
            tuple_(Store.batch_id, Store.source) > tuple_(keys.c.batch_id, keys.c.source),
        )
        .order_by(Store.batch_id, Store.source)
        .limit(1)
        .lateral("next_provenance_key")
    )
    keys = keys.union_all(
        select(following.c.batch_id, following.c.source).select_from(keys).join(following, true())
    )
    unlinked_key = exists(
        select(literal(1))
        .select_from(keys)
        .where(
            ~exists(
                select(literal(1)).where(
                    StoreImportBatch.batch_id == keys.c.batch_id,
                    StoreImportBatch.source == keys.c.source,
                )
            )
        )
    )
    null_batch = exists(select(Store.id).where(SOURCE_SUPPORTED_STORES, Store.batch_id.is_(None)))
    return select(or_(unlinked_key, null_batch))


def current_provenance(session: Session) -> tuple[list[StoreImportBatch], date]:
    batches = list(
        session.scalars(
            select(StoreImportBatch)
            .where(
                exists(
                    select(Store.id).where(
                        SOURCE_SUPPORTED_STORES,
                        Store.batch_id == StoreImportBatch.batch_id,
                        Store.source == StoreImportBatch.source,
                    )
                )
            )
            .order_by(StoreImportBatch.source, StoreImportBatch.batch_id)
        )
    )
    missing = session.scalar(orphan_exists())
    if (
        missing
        or not batches
        or any(
            b.data_updated_at is None
            or b.update_reason is not None
            or b.data_updated_at < MIN_OPEN_DATE
            or b.data_updated_at > b.recorded_at.astimezone(ZoneInfo("Asia/Seoul")).date()
            for b in batches
        )
    ):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
    reference = max(b.data_updated_at for b in batches if b.data_updated_at is not None)
    return batches, reference


def provenance_meta(batches: list[StoreImportBatch], reference: date, rule_version: str) -> ApiMeta:
    versions = sorted({batch.map_version for batch in batches})
    return {
        "source": ["R5", "R6"],
        "data_updated_at": reference.isoformat(),
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "is_demo": False,
        "name_exclusion": name_exclusion_meta(),
        "data_version": {
            "stores_batch_ids": [str(b.batch_id) for b in batches],
            "trdar_quarter": None,
            "map_version": versions[0] if len(versions) == 1 else None,
            "rule_version": rule_version,
            "name_exclusion_version": NAME_EXCLUSION_VERSION,
        },
        "store_batches": [
            {
                "source": b.source,
                "batch_id": str(b.batch_id),
                "data_updated_at": b.data_updated_at.isoformat() if b.data_updated_at else None,
                "update_reason": b.update_reason,
            }
            for b in batches
        ],
    }
