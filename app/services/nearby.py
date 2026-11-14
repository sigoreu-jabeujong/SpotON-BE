from sqlalchemy.orm import Session

from app.schemas.common import ApiResponse
from app.schemas.nearby import Center, NearbyQuery, NearbyStores
from app.services.chains import ChainSelection
from app.services.spatial_stores import effective_date as effective_date
from app.services.spatial_stores import get_spatial_stores

RULE_VERSION = "store-nearby-geography-zero-unknown-v1"
EMPTY_MESSAGE = "조건에 맞는 점포가 없어요"


def get_nearby(
    session: Session, query: NearbyQuery, *, chain: ChainSelection | None = None
) -> ApiResponse[NearbyStores]:
    selected = get_spatial_stores(
        session, query, rule_version=RULE_VERSION, **({"chain": chain} if chain else {})
    )
    return ApiResponse(
        data=NearbyStores(
            center=Center(lat=query.lat, lng=query.lng),
            radius_m=query.radius,
            as_of=selected.as_of,
            count=len(selected.markers),
            excluded_no_coord=selected.excluded_no_coord,
            markers=selected.markers,
            message=None if selected.markers else EMPTY_MESSAGE,
        ),
        meta=selected.meta,
    )
