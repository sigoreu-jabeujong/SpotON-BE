"""Reuse only results from an identical primary, read-only repeatable-read view."""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.cache import CacheResources
from app.core.config import Settings
from app.models.brand import MAPPING_RULE
from app.schemas.common import ApiResponse
from app.schemas.risk import Risk, RiskQuery

SNAPSHOT = text(
    "SELECT current_setting('transaction_read_only')='on', "
    "current_setting('transaction_isolation')='repeatable read', NOT pg_is_in_recovery(), "
    "current_database()::text, current_user::text, pg_postmaster_start_time()::text, "
    "current_setting('search_path'), current_setting('TimeZone'), "
    "current_setting('DateStyle'), current_setting('extra_float_digits'), "
    "pg_current_snapshot()::text"
)
FILTERS = {"sub_category", "area", "franchise", "include_unknown_area", "include_unknown_franchise"}


def snapshot_token(session: Session, cache: CacheResources) -> str | None:
    if not cache.enabled:
        return None
    row = session.execute(SNAPSHOT).one()
    if len(row) != 11 or tuple(row[:3]) != (True, True, True):
        return None
    if any(type(v) is not str for v in row[3:]):
        return None
    return cache.key("snapshot", list(row[3:]))


def query_parts(query: RiskQuery) -> dict[str, object]:
    sub = query.sub_category or (
        ("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western")
    )
    return {
        "lat6": round(query.lat, 6),
        "lng6": round(query.lng, 6),
        "lat_exact": query.lat.hex(),
        "lng_exact": query.lng.hex(),
        "category": query.category,
        "radius": query.radius,
        "as_of": query.as_of,
        "sub_category": sorted(sub),
        "area": query.area,
        "franchise": query.franchise,
        "include_unknown_area": query.include_unknown_area,
        "include_unknown_franchise": query.include_unknown_franchise,
        "include": sorted(query.include),
    }


def risk_key(
    cache: CacheResources, token: str | None, query: RiskQuery, settings: Settings, rule: str
) -> str | None:
    if token is None:
        return None
    return cache.key(
        "risk",
        token,
        query_parts(query),
        str(settings.risk_boundary_version_id),
        rule,
        MAPPING_RULE,
    )


def load_risk(cache: CacheResources, key: str | None, query: RiskQuery) -> ApiResponse[Risk] | None:
    try:
        encoded = cache.risk.get(key)
        if encoded is None or key is None:
            return None
        payload = json.loads(encoded)
        if set(payload) != {"data", "meta", "target"} or "query" in payload["data"]:
            raise ValueError("invalid cache payload")
        payload["data"]["query"] = {
            "lat": query.lat,
            "lng": query.lng,
            "category": query.category,
            "radius_m": query.radius,
            "as_of": payload["target"],
            "filters": query.model_dump(include=FILTERS, mode="json"),
        }
        return ApiResponse[Risk].model_validate_json(
            json.dumps(
                {"data": payload["data"], "meta": payload["meta"], "error": None}, allow_nan=False
            )
        )
    except Exception:
        if key is not None:
            cache.risk.discard(key)
        return None


def save_risk(cache: CacheResources, key: str | None, response: ApiResponse[Risk]) -> None:
    if key is None or response.data is None or response.error is not None:
        return
    try:
        data = response.data.model_dump(mode="json", exclude={"query"})
        encoded = json.dumps(
            {"data": data, "meta": response.meta, "target": response.data.query.as_of.isoformat()},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        cache.risk.put(key, encoded)
    except Exception:
        pass
