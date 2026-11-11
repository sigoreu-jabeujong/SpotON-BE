"""API v1.2 §2-2/§4-3/§4-5: shared provenance and reliable license intervals."""

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import Store, StoreImportBatch
from app.schemas.common import ApiMeta, ErrorCode
from app.schemas.store_filters import CategoryFilters
from app.services.store_history import SUPPORTED_STORES

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


def current_provenance(session: Session) -> tuple[list[StoreImportBatch], date]:
    batches = list(
        session.scalars(
            select(StoreImportBatch)
            .where(
                exists(
                    select(Store.id).where(
                        SUPPORTED_STORES,
                        Store.batch_id == StoreImportBatch.batch_id,
                        Store.source == StoreImportBatch.source,
                    )
                )
            )
            .order_by(StoreImportBatch.source, StoreImportBatch.batch_id)
        )
    )
    linked = exists(
        select(StoreImportBatch.batch_id)
        .where(StoreImportBatch.batch_id == Store.batch_id, StoreImportBatch.source == Store.source)
        .correlate(Store)
    )
    missing = session.scalar(select(exists(select(Store.id).where(SUPPORTED_STORES, ~linked))))
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
        "data_version": {
            "stores_batch_ids": [str(b.batch_id) for b in batches],
            "trdar_quarter": None,
            "map_version": versions[0] if len(versions) == 1 else None,
            "rule_version": rule_version,
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
