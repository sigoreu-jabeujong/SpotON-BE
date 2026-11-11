"""BE-14 / API v1.2 §4-5; amendments: designs/feat43-data-range-api.md."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Store
from app.schemas.common import ApiMeta, ApiResponse
from app.schemas.data_range import DataRange, DataRangeQuery
from app.services.store_cohort import current_provenance, provenance_meta, temporal_cohort

RULE_VERSION = "store-data-range-valid-license-v1"


def get_data_range(session: Session, query: DataRangeQuery) -> ApiResponse[DataRange]:
    batches, reference = current_provenance(session)
    minimum = session.scalar(
        select(func.min(Store.open_date)).where(*temporal_cohort(query, reference))
    )
    meta: ApiMeta = {
        **provenance_meta(batches, reference, RULE_VERSION),
        "as_of": reference.isoformat(),
        "space": "seoul",
        "denominator": None,
    }
    return ApiResponse(
        data=DataRange(
            min_month=minimum.strftime("%Y-%m") if minimum is not None else None,
            max_month=reference.strftime("%Y-%m"),
            max_date=reference,
            data_updated_at=reference,
            collected_at=None,
        ),
        meta=meta,
    )
