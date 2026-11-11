"""BE-15 / API v1.2 §4-4: same S as nearby, partition by latest recorded status."""

from collections import Counter

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.snapshot import SnapshotQuery, SnapshotStore, StoreSnapshot
from app.services.spatial_stores import get_spatial_stores

RULE_VERSION = "store-snapshot-latest-status-v1"


def get_snapshot(session: Session, query: SnapshotQuery) -> ApiResponse[StoreSnapshot]:
    try:
        selected = get_spatial_stores(session, query, rule_version=RULE_VERSION)
        stores = [
            SnapshotStore.model_validate(marker.model_dump(include=set(SnapshotStore.model_fields)))
            for marker in selected.markers
        ]
        counts = Counter(store.current_status for store in stores)
        total, opened, closed, other = (
            len(stores),
            counts["open"],
            counts["closed"],
            counts["other"],
        )
        data = StoreSnapshot(
            as_of=selected.as_of,
            total_at_as_of=total,
            still_open=opened,
            closed_since=closed,
            other=other,
            stores=stores,
            summary_text=(
                f"{selected.as_of:%Y.%m.%d} 기준 동일 업종 {total}곳 → "
                f"최신 데이터 기준 영업 {opened}곳 · 폐업 {closed}곳 · 기타 {other}곳"
            ),
            excluded_no_coord=selected.excluded_no_coord,
        )
        return ApiResponse(data=data, meta=selected.meta)
    except ValidationError:
        # Invariant failure must not emit partial stores, row values or cacheable errors.
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None
