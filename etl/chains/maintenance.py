"""Explicit plans for disabling or pruning chain publications on the guarded local DB."""

import argparse
import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_db_engine
from app.models.chain import (
    ChainPublication as Publication,
)
from app.models.chain import (
    ChainPublicationBrand as Brand,
)
from app.models.chain import (
    ChainPublicationState as State,
)
from app.models.chain import (
    StoreChainClassification as Evidence,
)
from etl.brands.catalog import canonical
from etl.chains.common import ChainsError, digest, fail, safe_json
from etl.chains.publication import validate_write
from etl.localdata.runner import check_local_database, validate_local_target

PLAN_RULE = "chain-maintenance-v1"
ACTIONS = {"list", "disable", "prune"}


def validate_options(
    action: str,
    generations: tuple[UUID, ...],
    write: bool,
    expected_plan: str | None,
    expected_active: str | None,
) -> None:
    if not isinstance(action, str) or action not in ACTIONS or type(write) is not bool:
        fail("maintenance_arguments")
    if type(generations) is not tuple or any(not isinstance(g, UUID) for g in generations):
        fail("maintenance_targets")
    if action == "prune":
        if not 1 <= len(generations) <= 3 or len(set(generations)) != len(generations):
            fail("maintenance_targets")
    elif generations:
        fail("maintenance_targets")
    if action == "list" and write:
        fail("maintenance_read_only_action")
    if write:
        if type(expected_plan) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_plan):
            fail("maintenance_expected_plan")
        validate_write(expected_plan, expected_active)
    elif expected_plan is not None or expected_active is not None:
        fail("maintenance_write_flags")


def locked(connection: Connection, write: bool) -> None:
    connection.exec_driver_sql(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" + ("" if write else " READ ONLY")
    )
    connection.exec_driver_sql("SET LOCAL statement_timeout='60s'")
    connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
    # The lock names and ORM statements must address the same public tables, even
    # when the connection has temporary relations or a custom role search_path.
    connection.exec_driver_sql("SET LOCAL search_path=pg_catalog,public,pg_temp")
    if write:
        # Same coordinator and order as publication.locked, before the first SELECT.
        connection.exec_driver_sql("LOCK TABLE public.chain_publication_state IN EXCLUSIVE MODE")
        connection.exec_driver_sql(
            "LOCK TABLE public.chain_publications, public.chain_publication_brands, "
            "public.store_chain_classifications IN SHARE ROW EXCLUSIVE MODE"
        )
    check_local_database(connection)


def _json(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            fail("maintenance_timestamp")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json(v) for v in value]
    return value


def _content(
    connection: Connection, table: Any, generation: UUID, order: tuple[Any, ...]
) -> dict[str, Any]:
    h = hashlib.sha256()
    count = 0
    rows = connection.execute(
        select(table)
        .where(table.c.generation == generation)
        .order_by(*order)
        .execution_options(stream_results=True, yield_per=1000)
    )
    try:
        for row in rows.mappings():
            h.update(canonical(_json(row)) + b"\n")
            count += 1
    finally:
        rows.close()
    return {"count": count, "sha256": h.hexdigest()}


def _bytes(connection: Connection) -> int:
    return int(
        connection.scalar(
            text("""
        SELECT coalesce(sum(pg_total_relation_size(name::regclass)),0) FROM unnest(ARRAY[
          'public.chain_publications','public.chain_publication_brands',
          'public.store_chain_classifications']) AS names(name)
    """)
        )
        or 0
    )


def _plan(
    connection: Connection, action: str, generations: tuple[UUID, ...]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    state = (
        connection.execute(select(State.__table__).where(State.id == 1)).mappings().one_or_none()
    )
    publications = list(
        connection.execute(
            select(Publication.__table__).order_by(Publication.generation)
        ).mappings()
    )
    by_id = {row["generation"]: row for row in publications}
    active = state["generation"] if state else None
    if active is not None and active not in by_id:
        fail("maintenance_dangling_state")
    targets = tuple(sorted(generations, key=str))
    if active in targets:
        fail("maintenance_active_protected")
    if any(g not in by_id for g in targets):
        fail("maintenance_generation_missing")
    content: dict[str, dict[str, Any]] = {}
    for generation in targets:
        evidence, brand = Evidence.__table__, Brand.__table__
        content[str(generation)] = {
            "classifications": _content(
                connection,
                evidence,
                generation,
                (evidence.c.source.collate("C"), evidence.c.license_no.collate("C")),
            ),
            "brands": _content(connection, brand, generation, (brand.c.brand_key,)),
        }
    fingerprint = digest(
        _json(
            {
                "rule": PLAN_RULE,
                "action": action,
                "targets": targets,
                "state": state,
                "inventory": publications,
                "content": content,
            }
        )
    )
    report = {
        "action": action,
        "mode": "dry_run",
        "rule": PLAN_RULE,
        "active": str(active) if active else "none",
        "expected_plan_sha256": fingerprint,
        "generations": [
            {
                "generation": str(p["generation"]),
                "active": p["generation"] == active,
                "created_at": _json(p["created_at"]),
                "source_rows": p["row_count"],
                "classifications": p["known_count"],
            }
            for p in publications
        ],
        "targets": [
            {
                "generation": str(g),
                "classifications": content[str(g)]["classifications"]["count"],
                "brands": content[str(g)]["brands"]["count"],
                "classification_count_matches": content[str(g)]["classifications"]["count"]
                == by_id[g]["known_count"],
            }
            for g in targets
        ],
        "publication_bytes": _bytes(connection),
        "physical_space_reclaimed": False,
    }
    return report, content


def _delete(connection: Connection, table: Any, generation: UUID) -> int:
    return connection.execute(delete(table).where(table.generation == generation)).rowcount


def manage(
    connection: Connection,
    *,
    action: str = "list",
    generations: tuple[UUID, ...] = (),
    write: bool = False,
    expected_plan: str | None = None,
    expected_active: str | None = None,
) -> dict[str, Any]:
    validate_options(action, generations, write, expected_plan, expected_active)
    report, content = _plan(connection, action, generations)
    if not write:
        return report
    if report["active"] != expected_active:
        fail("maintenance_active_changed")
    if report["expected_plan_sha256"] != expected_plan:
        fail("maintenance_plan_changed")
    removed = {"publications": 0, "brands": 0, "classifications": 0, "states": 0}
    if action == "disable":
        if report["active"] != "none":
            count = connection.execute(delete(State).where(State.id == 1)).rowcount
            if count != 1:
                fail("maintenance_delete_count")
            removed["states"] = count
    else:
        for g in sorted(generations, key=str):
            for table, kind in (
                (Evidence, "classifications"),
                (Brand, "brands"),
                (Publication, "publications"),
            ):
                expected = 1 if kind == "publications" else content[str(g)][kind]["count"]
                count = _delete(connection, table, g)
                if count != expected:
                    fail("maintenance_delete_count")
                removed[kind] += count
        connection.exec_driver_sql(
            "ANALYZE public.chain_publications, public.chain_publication_brands, "
            "public.store_chain_classifications"
        )
    active_after = connection.scalar(select(State.generation).where(State.id == 1))
    expected_after = "none" if action == "disable" else report["active"]
    if (str(active_after) if active_after else "none") != expected_after:
        fail("maintenance_state_changed")
    after = [
        dict(p)
        for p in report["generations"]
        if action != "prune" or UUID(p["generation"]) not in generations
    ]
    if action == "disable":
        for p in after:
            p["active"] = False
    return {
        **report,
        "generations_before": report["generations"],
        "generations": after,
        "mode": "write",
        "active_after": expected_after,
        "removed": removed,
        "unchanged": not any(removed.values()),
        "publication_bytes_after": _bytes(connection),
    }


def run(
    settings: Settings,
    *,
    action: str = "list",
    generations: tuple[UUID, ...] = (),
    write: bool = False,
    expected_plan: str | None = None,
    expected_active: str | None = None,
) -> dict[str, Any]:
    validate_options(action, generations, write, expected_plan, expected_active)
    validate_local_target(settings)
    engine = create_db_engine(settings)
    try:
        with engine.begin() as connection:
            locked(connection, write)
            return manage(
                connection,
                action=action,
                generations=generations,
                write=write,
                expected_plan=expected_plan,
                expected_active=expected_active,
            )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=sorted(ACTIONS), default="list")
    parser.add_argument("--generation", action="append", type=UUID, default=[])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expected-plan")
    parser.add_argument("--expected-active")
    args = parser.parse_args()
    try:
        print(
            safe_json(
                run(
                    Settings(),
                    action=args.action,
                    generations=tuple(args.generation),
                    write=args.write,
                    expected_plan=args.expected_plan,
                    expected_active=args.expected_active,
                )
            )
        )
        return 0
    except (ChainsError, SQLAlchemyError, ValueError, OSError):
        print(safe_json({"status": "error", "reason": "maintenance_rejected"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
