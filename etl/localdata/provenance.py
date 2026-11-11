"""Source provenance for imports executed with these explicitly versioned rules."""

from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models import StoreImportBatch
from etl.localdata.collection import CollectedSource
from etl.localdata.dates import parse_source_timestamp
from etl.localdata.snapshot import rows_digest

MAP_VERSION = "localdata-mapping-v1"
ETL_RULE_VERSION = "localdata-normalization-v1"


def source_reference_date(collection: CollectedSource) -> tuple[date | None, str | None]:
    dates: list[date] = []
    for row in collection.rows:
        if row.update_point is None or not row.update_point.strip():
            continue
        parsed = parse_source_timestamp(row.update_point)
        if parsed is None or parsed.date() < date(1960, 1, 1):
            return None, "invalid_source_update"
        if parsed > collection.collected_at:
            return None, "future_source_update"
        dates.append(parsed.date())
    if not dates:
        return None, "missing_source_update"
    return max(dates), None


def import_batch(collection: CollectedSource, batch_id: UUID) -> StoreImportBatch:
    updated, reason = source_reference_date(collection)
    return StoreImportBatch(
        batch_id=batch_id,
        source=collection.source.value,
        data_updated_at=updated,
        update_reason=reason,
        recorded_at=collection.collected_at.replace(tzinfo=ZoneInfo("Asia/Seoul")),
        collection_basis=collection.as_of_basis,
        input_kind=collection.input_kind,
        input_sha256=collection.input_sha256,
        rows_sha256=rows_digest(collection.rows),
        row_count=len(collection.rows),
        map_version=MAP_VERSION,
        rule_version=ETL_RULE_VERSION,
    )
