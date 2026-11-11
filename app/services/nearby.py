"""BE-13 / API v1.2 §2-2, §4-3; amendments in designs feat38/feat41."""

from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import Store
from app.models.store import STORE_GEOGRAPHY
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.nearby import Center, NearbyMarker, NearbyQuery, NearbyStores
from app.services.store_cohort import current_provenance, provenance_meta, temporal_cohort
from app.services.store_history import operating_period

PREFILTER_MARGIN_M = 0.01
AREA_33, AREA_66, AREA_99 = Decimal("33"), Decimal("66"), Decimal("99")
RULE_VERSION = "store-nearby-geography-zero-unknown-v1"
EMPTY_MESSAGE = "조건에 맞는 점포가 없어요"
NO_COORD_SCOPE = "seoul_nonspatial_cohort"


def effective_date(reference: date, minimum: date | None, month: str | None) -> date:
    """API v1.2 §2-2: latest month uses source date, past months use month end."""
    if month is None:
        return reference
    requested = date(int(month[:4]), int(month[5:]), 1)
    latest = reference.replace(day=1)
    if (
        requested > latest
        or (minimum is None and requested != latest)
        or (minimum is not None and requested < minimum.replace(day=1))
    ):
        raise AppError(ErrorCode.AS_OF_OUT_OF_RANGE, headers=NO_STORE)
    return (
        reference
        if requested == latest
        else requested.replace(day=monthrange(requested.year, requested.month)[1])
    )


def attribute_filters(query: NearbyQuery) -> list[ColumnElement[bool]]:
    """Zero area is unknown, independently from the franchise unknown toggle."""
    area_ranges = {
        "all": Store.area_m2 > 0,
        "lt33": and_(Store.area_m2 > 0, Store.area_m2 < AREA_33),
        "33to66": and_(Store.area_m2 >= AREA_33, Store.area_m2 < AREA_66),
        "66to99": and_(Store.area_m2 >= AREA_66, Store.area_m2 < AREA_99),
        "gte99": Store.area_m2 >= AREA_99,
    }
    area = area_ranges[query.area]
    if query.include_unknown_area:
        area = or_(area, Store.area_m2.is_(None), Store.area_m2 == 0)
    franchise: ColumnElement[bool] = (
        Store.is_franchise.is_not(None)
        if query.franchise == "all"
        else Store.is_franchise.is_(query.franchise == "franchise")
    )
    if query.include_unknown_franchise:
        franchise = or_(franchise, Store.is_franchise.is_(None))
    return [area, franchise]


def get_nearby(session: Session, query: NearbyQuery) -> ApiResponse[NearbyStores]:
    batches, reference = current_provenance(session)
    cohort = temporal_cohort(query, reference)
    minimum = session.scalar(select(func.min(Store.open_date)).where(*cohort))
    target = effective_date(reference, minimum, query.as_of)
    conditions = [
        *cohort,
        *attribute_filters(query),
        Store.open_date <= target,
        or_(Store.close_date.is_(None), Store.close_date > target),
    ]
    excluded = int(
        session.scalar(
            select(func.count()).select_from(Store).where(*conditions, Store.geom.is_(None))
        )
        or 0
    )
    point = cast(func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326), STORE_GEOGRAPHY)
    geography = cast(Store.geom, STORE_GEOGRAPHY)
    distance = func.ST_Distance(geography, point, True)
    rows = session.execute(
        select(Store, distance.label("distance_m"), func.ST_Y(Store.geom), func.ST_X(Store.geom))
        .where(
            *conditions,
            Store.geom.is_not(None),
            func.ST_DWithin(geography, point, query.radius + PREFILTER_MARGIN_M, True),
            distance <= query.radius,
        )
        .order_by(distance, Store.source, Store.license_no, Store.id)
    ).all()
    batch_map = {batch.batch_id: batch for batch in batches}
    markers: list[NearbyMarker] = []
    for store, raw_distance, lat, lng in rows:
        months, reason, opened, closed = operating_period(
            store, reference, batch_map.get(store.batch_id)
        )
        markers.append(
            NearbyMarker.model_validate(
                {
                    "source": store.source,
                    "license_no": store.license_no,
                    "name": store.name,
                    "sub_category": store.sub_category,
                    "lat": lat,
                    "lng": lng,
                    "distance_m": float(
                        Decimal(str(raw_distance)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                    ),
                    "open_date": opened,
                    "close_date": closed,
                    "operating_months": months,
                    "operating_period_status": "no_data" if reason else "fact",
                    "operating_period_reason": reason,
                    "current_status": store.status
                    if store.status in {"open", "closed"}
                    else "other",
                    "franchise": "unknown"
                    if store.is_franchise is None
                    else ("franchise" if store.is_franchise else "independent"),
                    "area_m2": float(store.area_m2)
                    if store.area_m2 is not None and store.area_m2 > 0
                    else None,
                }
            )
        )
    meta: ApiMeta = {
        **provenance_meta(batches, reference, RULE_VERSION),
        "as_of": target.isoformat(),
        "space": f"radius_{query.radius}m",
        "denominator": len(markers),
        "excluded_no_coord_scope": NO_COORD_SCOPE,
        "operating_period_basis": "latest_data",
    }
    return ApiResponse(
        data=NearbyStores(
            center=Center(lat=query.lat, lng=query.lng),
            radius_m=query.radius,
            as_of=target,
            count=len(markers),
            excluded_no_coord=excluded,
            markers=markers,
            message=None if markers else EMPTY_MESSAGE,
        ),
        meta=meta,
    )
