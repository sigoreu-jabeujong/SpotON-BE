from collections import Counter
from typing import Any, cast
from uuid import UUID, uuid4

from geoalchemy2.elements import WKBElement
from sqlalchemy import Connection, func, insert, select, text

from app.models import LivingGrid as G
from app.models import LivingGridVersion as GV
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V
from etl.living_pop.data import RULE_VERSION, SOURCES, fail, observations_hash
from etl.living_pop.grid import GRID_URL, PreparedGrid
from etl.living_pop.input import DailyInput
from etl.market_areas.archive import digest

LOCK_NAMESPACE = 0x53504F54
LOCK_KEY = 19
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 60000
BATCH_SIZE = 5000


def limits(c: Connection) -> None:
    for name, value in (
        ("lock_timeout", LOCK_TIMEOUT_MS),
        ("statement_timeout", STATEMENT_TIMEOUT_MS),
    ):
        c.execute(select(func.set_config(name, str(value), True)))


def grid_expected(grid: PreparedGrid) -> dict[str, Any]:
    return dict(
        input_sha256=grid.source.sha256,
        input_bytes=grid.source.input_bytes,
        rule_version=grid.rule_version,
        source_url=GRID_URL,
        source_crs=5179,
        grid_as_of=None,
        source_metadata=grid.source.metadata,
        row_count=len(grid.rows),
        raw_content_sha256=grid.source.raw_content_sha256,
        content_sha256=grid.content_sha256,
    )


def _verify_grid(c: Connection, grid: PreparedGrid, grid_id: UUID, *, lock: bool) -> None:
    q = (
        select(
            *(col for col in G.__table__.c if col.name not in {"grid_version_id", "geom"}),
            func.encode(func.ST_AsEWKB(G.geom, "NDR"), "hex").label("geom_hex"),
        )
        .where(G.grid_version_id == grid_id)
        .order_by(G.grid_id.collate("C"))
    )
    if lock:
        q = q.with_for_update(read=True)
    rows = [dict(r) for r in c.execute(q).mappings()]
    if len(rows) != len(grid.rows) or digest(rows) != grid.content_sha256:
        fail("stored_grid_content")


def _grid_state(c: Connection, grid: PreparedGrid, *, lock: bool) -> UUID | None:
    q = select(GV.__table__).where(
        GV.input_sha256 == grid.source.sha256, GV.rule_version == grid.rule_version
    )
    if lock:
        q = q.with_for_update()
    existing = c.execute(q).mappings().one_or_none()
    if existing is None:
        return None
    if any(existing[k] != v for k, v in grid_expected(grid).items()):
        fail("grid_metadata")
    gid = cast(UUID, existing["grid_version_id"])
    _verify_grid(c, grid, gid, lock=lock)
    return gid


def population_expected(daily: DailyInput, grid_id: UUID, rule: str) -> dict[str, Any]:
    content = (
        daily.content_sha256
        if rule == RULE_VERSION
        else observations_hash(
            (r.payload() for r in daily.rows),
            daily.manifest.day,
            daily.grid.sha256,
            len(daily.rows),
            rule,
        )
    )
    return dict(
        grid_version_id=grid_id,
        observation_date=daily.manifest.day,
        input_sha256=daily.input_sha256,
        rule_version=rule,
        sources=daily.sources,
        row_count=len(daily.rows),
        content_sha256=content,
        spatial_compatibility="unverified",
    )


def _verify_observations(
    c: Connection, daily: DailyInput, grid_id: UUID, version_id: UUID, rule: str
) -> None:
    q = (
        select(O.__table__)
        .where(O.version_id == version_id)
        .order_by(O.source.collate("C"), O.hour, O.admin_code.collate("C"), O.grid_id.collate("C"))
        .execution_options(stream_results=True, yield_per=2000)
    )
    known = {g["grid_id"] for g in daily.grid.features}
    counts: Counter[str] = Counter()
    states: dict[str, Counter[str]] = {s: Counter() for s in SOURCES}
    unlocated: Counter[str] = Counter()
    n = 0

    def payloads(result: Any) -> Any:
        nonlocal n
        for row in result.mappings():
            n += 1
            if row["grid_version_id"] != grid_id or row["observation_date"] != daily.manifest.day:
                fail("stored_identity")
            located = row["grid_id"] in known
            if (row["located_grid_id"] is not None) != located or row["geometry_status"] != (
                "located" if located else "unlocated"
            ):
                fail("stored_location")
            counts[row["source"]] += 1
            states[row["source"]][row["value_status"]] += 1
            unlocated[row["source"]] += not located
            yield row

    result = c.execute(q)
    try:
        content = observations_hash(
            payloads(result), daily.manifest.day, daily.grid.sha256, len(daily.rows), rule
        )
    finally:
        result.close()
    expected = population_expected(daily, grid_id, rule)
    if n != len(daily.rows) or content != expected["content_sha256"]:
        fail("stored_population_content")
    for source in SOURCES:
        meta = daily.sources[source]
        if (
            counts[source] != meta["rows"]
            or unlocated[source] != meta["unlocated_rows"]
            or any(
                states[source][s] != meta["statuses"][s]
                for s in ("observed", "suppressed", "missing")
            )
        ):
            fail("stored_statistics")


def _population_state(
    c: Connection, daily: DailyInput, grid_id: UUID, rule: str, *, lock: bool
) -> UUID | None:
    q = select(V.__table__).where(
        V.input_sha256 == daily.input_sha256, V.rule_version == rule, V.grid_version_id == grid_id
    )
    if lock:
        q = q.with_for_update()
    existing = c.execute(q).mappings().one_or_none()
    if existing is None:
        return None
    if any(existing[k] != v for k, v in population_expected(daily, grid_id, rule).items()):
        fail("population_metadata")
    vid = cast(UUID, existing["version_id"])
    _verify_observations(c, daily, grid_id, vid, rule)
    return vid


def inspect_import(
    c: Connection, daily: DailyInput, grid: PreparedGrid
) -> tuple[UUID | None, UUID | None]:
    gid = _grid_state(c, grid, lock=False)
    return gid, _population_state(
        c, daily, gid, RULE_VERSION, lock=False
    ) if gid is not None else None


def save(
    c: Connection, daily: DailyInput, grid: PreparedGrid, *, rule: str = RULE_VERSION
) -> tuple[UUID, UUID, bool, int]:
    if not c.in_transaction():
        fail("transaction_required")
    limits(c)
    c.execute(text("SELECT pg_advisory_xact_lock(:n,:k)"), {"n": LOCK_NAMESPACE, "k": LOCK_KEY})
    gid = _grid_state(c, grid, lock=True)
    inserted_grids = 0
    if gid is None:
        gid = uuid4()
        inserted_grids = len(grid.rows)
        c.execute(
            insert(GV).values(
                grid_version_id=gid, **grid_expected(grid), postgis_version=grid.postgis_version
            )
        )
        for start in range(0, len(grid.rows), BATCH_SIZE):
            values = []
            for row in grid.rows[start : start + BATCH_SIZE]:
                value = {k: v for k, v in row.items() if k != "geom_hex"}
                values.append(
                    {
                        **value,
                        "grid_version_id": gid,
                        "geom": WKBElement(bytes.fromhex(row["geom_hex"]), extended=True),
                    }
                )
            c.execute(insert(G), values)
        _verify_grid(c, grid, gid, lock=True)
    vid = _population_state(c, daily, gid, rule, lock=True)
    if vid is not None:
        return gid, vid, True, inserted_grids
    vid = uuid4()
    c.execute(insert(V).values(version_id=vid, **population_expected(daily, gid, rule)))
    for start in range(0, len(daily.rows), BATCH_SIZE):
        values = []
        for observation in daily.rows[start : start + BATCH_SIZE]:
            value = observation.payload()
            value["population"] = observation.population
            values.append(
                {
                    **value,
                    "version_id": vid,
                    "grid_version_id": gid,
                    "observation_date": daily.manifest.day,
                }
            )
        c.execute(insert(O), values)
    _verify_observations(c, daily, gid, vid, rule)
    return gid, vid, False, inserted_grids
