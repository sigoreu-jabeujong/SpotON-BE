"""Code-only boundary audit; never establishes temporal compatibility."""

from collections import Counter
from collections.abc import Callable
from typing import Any, NoReturn, Protocol
from uuid import UUID

from sqlalchemy import Connection, func, select

from app.models import MarketArea, MarketAreaVersion
from etl.market_areas.archive import digest


class BoundaryAuditInput(Protocol):
    @property
    def rows(self) -> list[dict[str, Any]]: ...

    @property
    def markets(self) -> dict[str, dict[str, tuple[str, str]]]: ...

    @property
    def quarter_rows(self) -> dict[str, int]: ...


def check_boundary(
    connection: Connection,
    archive: BoundaryAuditInput,
    boundary_id: UUID,
    *,
    fail: Callable[[str], NoReturn],
    lock: bool = False,
) -> dict[str, Any]:
    manifest_query = select(MarketAreaVersion.__table__).where(
        MarketAreaVersion.version_id == boundary_id
    )
    area_query = (
        select(
            *(col for col in MarketArea.__table__.c if col.name not in {"version_id", "geom"}),
            func.encode(func.ST_AsEWKB(MarketArea.geom, "NDR"), "hex").label("geom_hex"),
        )
        .where(MarketArea.version_id == boundary_id)
        .order_by(MarketArea.market_code)
    )
    if lock:
        manifest_query = manifest_query.with_for_update(read=True)
        area_query = area_query.with_for_update(read=True)
    manifest = connection.execute(manifest_query).mappings().one_or_none()
    if manifest is None:
        fail("boundary_missing")
    areas = []
    for row in connection.execute(area_query).mappings():
        value = dict(row)
        value["area_m2"] = format(value["area_m2"], ".2f")
        areas.append(value)
    if (
        not areas
        or len(areas) != manifest["row_count"]
        or digest(areas) != manifest["content_sha256"]
    ):
        fail("boundary_content")
    by_code = {a["market_code"]: (a["market_type_code"], a["market_name"]) for a in areas}
    selected = Counter(row["quarter"] for row in archive.rows)
    reports = {}
    previous: dict[str, tuple[str, str]] = {}
    for quarter, markets in sorted(archive.markets.items()):
        common = markets.keys() & by_code.keys()
        reports[quarter] = dict(
            source_rows=archive.quarter_rows[quarter],
            supported_rows=selected[quarter],
            markets=len(markets),
            stats_only=len(markets.keys() - by_code.keys()),
            boundary_only=len(by_code.keys() - markets.keys()),
            type_mismatches=sum(markets[c][0] != by_code[c][0] for c in common),
            name_mismatches=sum(markets[c][1] != by_code[c][1] for c in common),
            changed_markets=sum(
                markets[c] != previous[c] for c in markets.keys() & previous.keys()
            ),
        )
        previous = markets
    return dict(
        boundary_version_id=str(boundary_id),
        boundary_content_sha256=manifest["content_sha256"],
        quarters=reports,
    )
