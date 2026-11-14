"""F-02: API v1.2 §4-2, analysis definition §2/§4-2 and issue #36 amendments."""

from datetime import date
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Store, StoreImportBatch
from app.schemas.common import ApiMeta, ApiResponse
from app.schemas.stores import HistoryQuery, HistoryStore, PeriodReason, StoreHistory
from app.services.franchise import brand_context, effective_franchise, enrich_meta, franchise_fields
from app.services.store_scope import (
    NAME_EXCLUSION_VERSION,
    SOURCE_SUPPORTED_STORES,
    SUPPORTED_STORES,
    name_exclusion_meta,
)
from etl.address.floor_unit import parse_floor_unit

HISTORY_RULE_VERSION = "store-history-calendar-months-v1"
EMPTY_HISTORY_MESSAGE = "이 건물에서 분석 대상 음식점·카페 인허가 기록이 조회되지 않았어요"


def complete_months(start: date, end: date) -> int:
    """Analysis §2 month units; issue #36 defines completed calendar months."""
    if end < start:
        raise ValueError("reversed period")
    return (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)


def location_match(
    requested: str | None, stored: str | None, level: str | None
) -> Literal["same_spot", "same_building", "unverified"]:
    if requested is None or stored is None or level not in {"same_spot", "same_building"}:
        return "unverified"
    left, right = parse_floor_unit(requested).value, parse_floor_unit(stored).value
    if left is None or right is None:
        return "unverified"
    if left.floor and right.floor:
        if left.floor != right.floor:
            return "same_building"
        if left.unit and right.unit:
            if left.unit != right.unit:
                return "same_building"
            return "same_spot" if level == "same_spot" else "unverified"
    return "unverified"


def operating_period(
    store: Store, reference: date | None, batch: StoreImportBatch | None
) -> tuple[int | None, PeriodReason | None, date | None, date | None]:
    """Keep history despite unreliable dates; never impute a missing closure."""
    flags = set((store.date_flag or "").split(";"))
    opened, closed = store.open_date, store.close_date
    if opened is not None and (
        opened < date(1960, 1, 1)
        or "open_date_future" in flags
        or (reference is not None and opened > reference)
    ):
        opened = None
    if closed is not None and (
        closed < date(1960, 1, 1)
        or "close_date_future" in flags
        or (reference is not None and closed > reference)
    ):
        closed = None
    if opened is None:
        reason: PeriodReason = (
            "missing_open_date"
            if store.open_date is None and "open_date_invalid" not in flags
            else "invalid_open_date"
        )
        return None, reason, opened, closed
    if store.status not in {"open", "closed"}:
        return None, "other_status", opened, closed
    if store.status == "closed":
        if closed is None:
            reason = (
                "missing_close_date"
                if store.close_date is None and "close_date_invalid" not in flags
                else "invalid_close_date"
            )
            return None, reason, opened, closed
        end = closed
    else:
        if reference is None or batch is None or batch.data_updated_at is None:
            return None, "missing_source_date", opened, closed
        if store.close_date is not None or "close_date_invalid" in flags:
            return None, "invalid_close_date", opened, closed
        end = reference
    if end < opened or "close_before_open" in flags:
        return None, "invalid_date_order", opened, None
    return complete_months(opened, end), None, opened, closed


def get_history(session: Session, query: HistoryQuery) -> ApiResponse[StoreHistory]:
    # Both queries share one REPEATABLE READ snapshot in the request dependency.
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
    batch_map = {batch.batch_id: batch for batch in batches}
    reference = max(
        (b.data_updated_at for b in batches if b.data_updated_at is not None), default=None
    )
    stores = list(
        session.execute(
            select(Store, effective_franchise())
            .where(SUPPORTED_STORES, Store.building_key == query.building_key)
            .order_by(Store.open_date.asc().nulls_last(), Store.source, Store.license_no, Store.id)
        )
    )
    result: list[HistoryStore] = []
    branding = brand_context(session)
    for store, franchise_value in stores:
        batch = batch_map.get(store.batch_id) if store.batch_id is not None else None
        if batch is not None and batch.source != store.source:
            batch = None
        months, reason, opened, closed = operating_period(store, reference, batch)
        result.append(
            HistoryStore.model_validate(
                {
                    "source": store.source,
                    "license_no": store.license_no,
                    "name": store.name,
                    "category": store.category,
                    "sub_category": store.sub_category,
                    "open_date": opened,
                    "close_date": closed,
                    "operating_months": months,
                    "operating_period_status": "fact" if reason is None else "no_data",
                    "operating_period_reason": reason,
                    "store_status": store.status if store.status in {"open", "closed"} else "other",
                    **franchise_fields(store, franchise_value, branding),
                    "floor_unit": store.floor_unit,
                    "location_match": location_match(
                        query.floor_unit, store.floor_unit, store.location_level
                    ),
                }
            )
        )
    result.sort(
        key=lambda row: (
            row.open_date is None,
            row.open_date or date.max,
            row.source,
            row.license_no,
        )
    )
    versions = sorted({batch.map_version for batch in batches})
    meta: ApiMeta = {
        "source": ["R5", "R6"],
        "space": "point",
        "denominator": len(result),
        "as_of": reference.isoformat() if reference else None,
        "data_updated_at": reference.isoformat() if reference else None,
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "is_demo": False,
        "name_exclusion": name_exclusion_meta(),
        "data_version": {
            "stores_batch_ids": [str(b.batch_id) for b in batches],
            "trdar_quarter": None,
            "map_version": versions[0] if len(versions) == 1 else None,
            "rule_version": HISTORY_RULE_VERSION,
            "name_exclusion_version": NAME_EXCLUSION_VERSION,
        },
        "store_batches": [
            {
                "source": b.source,
                "batch_id": str(b.batch_id),
                "data_updated_at": b.data_updated_at.isoformat() if b.data_updated_at else None,
                "update_reason": b.update_reason,
                "collection_basis": b.collection_basis,
                "etl_rule_version": b.rule_version,
            }
            for b in batches
        ],
    }
    enrich_meta(meta, branding)
    return ApiResponse(
        data=StoreHistory(
            total=len(result), stores=result, message=None if result else EMPTY_HISTORY_MESSAGE
        ),
        meta=meta,
    )
