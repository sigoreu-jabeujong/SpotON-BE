"""Bounded, atomic local publication. Never writes stores or legacy brand mappings."""

import argparse
import re
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Connection, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import create_db_engine
from app.models.chain import (
    CHAIN_FIELDS,
    PUBLICATION_RULE,
)
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
from app.services.chains import source_revision
from etl.chains.common import ChainsError, digest, fail, safe_json
from etl.chains.compare import prepare
from etl.chains.registry import BrandSpec, load_registry
from etl.chains.semas import Snapshot
from etl.chains.snapshot import load_snapshot
from etl.localdata.runner import check_local_database, validate_local_target

MAX_GENERATIONS = 3


def validate_write(
    expected_plan: str | None, expected_active: str | None, *, activate: bool = False
) -> None:
    if not activate and (not expected_plan or not re.fullmatch(r"[0-9a-f]{64}", expected_plan)):
        fail("expected_plan_and_active_required")
    if expected_active != "none":
        try:
            if expected_active is None or str(UUID(expected_active)) != expected_active:
                fail("expected_active_invalid")
        except ValueError:
            fail("expected_active_invalid")


def locked(connection: Connection, write: bool) -> None:
    connection.exec_driver_sql(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" + ("" if write else " READ ONLY")
    )
    connection.exec_driver_sql("SET LOCAL statement_timeout='60s'")
    connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
    # LOCK does not establish an RR snapshot; waiting writers cannot stale the plan.
    if write:
        connection.exec_driver_sql("LOCK TABLE public.chain_publication_state IN EXCLUSIVE MODE")
        connection.exec_driver_sql(
            "LOCK TABLE public.stores, public.store_import_batches, "
            "public.brand_mapping_state, public.brand_catalog_versions, public.brands, "
            "public.store_brand_matches IN SHARE MODE"
        )
    check_local_database(connection)


def revision(connection: Connection) -> int:
    with Session(bind=connection) as session:
        return source_revision(session)


def publication_plan(
    connection: Connection, seeds: tuple[BrandSpec, ...], snapshot: Snapshot | None
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    summary, plan, brands = prepare(connection, seeds, snapshot, include_inputs=True)
    catalog = summary["legacy_catalog"]
    manifest = {
        "schema": PUBLICATION_RULE,
        "classification_rule": summary["rule_version"],
        "policy": summary["policy_version"],
        "sources": {
            "catalog_year": catalog["reference_year"] if catalog else None,
            "catalog_id": catalog["catalog_id"] if catalog else None,
            "legacy_run_id": catalog["run_id"] if catalog else None,
            "semas_month": snapshot.reference_month if snapshot else None,
            "semas_observed_at": snapshot.observed_at.isoformat() if snapshot else None,
            "semas_sha256": snapshot.content_sha256 if snapshot else None,
        },
    }
    fingerprint = digest(
        {
            "manifest": manifest,
            "store": summary["store_sha256"],
            "registry": summary["registry_sha256"],
            "plan": summary["plan_sha256"],
        }
    )
    generation = uuid5(NAMESPACE_URL, "spoton:chain-publication:" + fingerprint)
    used = {p["brand_key"] for p in plan}
    brand_rows = [
        {
            "generation": generation,
            "brand_key": b.canonical_id,
            "name": b.name,
            "evidence": b.model_dump(mode="json"),
        }
        for b in brands
        if str(b.canonical_id) in used
    ]
    rows = []
    for p in plan:
        rows.append(
            {
                "generation": generation,
                **{k: p["inputs"][k] for k in CHAIN_FIELDS},
                "classification_status": p["status"],
                "reason": p["reason"],
                "brand_key": UUID(p["brand_key"]) if p["brand_key"] else None,
                "semas_id": p["semas_id"],
                "input_sha256": p["input_sha256"],
            }
        )
    publication = dict(
        generation=generation,
        fingerprint=fingerprint,
        plan_sha256=summary["plan_sha256"],
        store_sha256=summary["store_sha256"],
        registry_sha256=summary["registry_sha256"],
        rule_version=PUBLICATION_RULE,
        row_count=summary["total"],
        known_count=len(rows),
        manifest=manifest,
        summary=summary,
    )
    return publication, rows, brand_rows


def verify(
    connection: Connection,
    publication: dict[str, Any],
    rows: list[dict[str, Any]],
    brands: list[dict[str, Any]],
) -> None:
    generation = publication["generation"]
    actual = (
        connection.execute(
            select(Publication.__table__).where(Publication.generation == generation)
        )
        .mappings()
        .one()
    )
    if any(actual[k] != v for k, v in publication.items()):
        fail("publication_integrity")
    actual_rows = list(
        connection.execute(
            select(Evidence.__table__).where(Evidence.generation == generation)
        ).mappings()
    )
    actual_brands = list(
        connection.execute(select(Brand.__table__).where(Brand.generation == generation)).mappings()
    )
    if sorted(
        (dict(p) for p in actual_rows), key=lambda p: (p["source"], p["license_no"])
    ) != sorted(rows, key=lambda p: (p["source"], p["license_no"])) or sorted(
        (dict(p) for p in actual_brands), key=lambda p: str(p["brand_key"])
    ) != sorted(brands, key=lambda p: str(p["brand_key"])):
        fail("publication_integrity")


def apply(
    connection: Connection,
    seeds: tuple[BrandSpec, ...],
    snapshot: Snapshot | None,
    *,
    write: bool = False,
    expected_plan: str | None = None,
    expected_active: str | None = None,
) -> dict[str, Any]:
    if write:
        validate_write(expected_plan, expected_active)
    source = revision(connection)
    publication, rows, brands = publication_plan(connection, seeds, snapshot)
    active = connection.scalar(select(State.generation).where(State.id == 1))
    generation = publication["generation"]
    result = dict(
        mode="write" if write else "dry_run",
        generation=str(generation),
        active=str(active) if active else "none",
        plan_sha256=publication["plan_sha256"],
        expected_plan_sha256=publication["fingerprint"],
        fingerprint=publication["fingerprint"],
        summary=publication["summary"],
    )
    if not write:
        return result
    if publication["fingerprint"] != expected_plan:
        fail("plan_changed")
    existing = connection.scalar(
        select(Publication.generation).where(Publication.generation == generation)
    )
    if (str(active) if active else "none") != expected_active and active != generation:
        fail("active_changed")
    if existing is None:
        if (
            connection.scalar(select(func.count()).select_from(Publication)) or 0
        ) >= MAX_GENERATIONS:
            fail("generation_capacity")
        connection.execute(insert(Publication), publication)
        for table, values in ((Brand, brands), (Evidence, rows)):
            for offset in range(0, len(values), 500):
                connection.execute(insert(table), values[offset : offset + 500])
        connection.exec_driver_sql(
            "ANALYZE public.chain_publications, public.chain_publication_brands, "
            "public.store_chain_classifications"
        )
    verify(connection, publication, rows, brands)
    total_bytes = connection.scalar(
        text("""
        SELECT sum(pg_total_relation_size(name::regclass)) FROM unnest(ARRAY[
          'public.chain_publications','public.chain_publication_brands',
          'public.store_chain_classifications']) AS names(name)
    """)
    )
    if total_bytes is None or total_bytes > 128 * 1024**2:
        fail("publication_storage_capacity")
    connection.execute(
        pg_insert(State)
        .values(id=1, generation=generation, validated_source_revision=source)
        .on_conflict_do_update(
            index_elements=[State.id],
            set_=dict(
                generation=generation, validated_source_revision=source, activated_at=func.now()
            ),
        )
    )
    return {**result, "unchanged": active == generation, "active": str(generation)}


def activate(
    connection: Connection,
    generation: UUID,
    seeds: tuple[BrandSpec, ...],
    snapshot: Snapshot | None,
    *,
    expected_active: str,
) -> dict[str, Any]:
    candidate, rows, brands = publication_plan(connection, seeds, snapshot)
    if candidate["generation"] != generation:
        fail("activation_inputs_changed")
    verify(connection, candidate, rows, brands)
    active = connection.scalar(select(State.generation).where(State.id == 1))
    if (str(active) if active else "none") != expected_active:
        fail("active_changed")
    return apply(
        connection,
        seeds,
        snapshot,
        write=True,
        expected_plan=candidate["fingerprint"],
        expected_active=expected_active,
    )


def run(
    settings: Settings,
    seeds: tuple[BrandSpec, ...],
    snapshot: Snapshot | None = None,
    **options: Any,
) -> dict[str, Any]:
    if options.get("write"):
        validate_write(
            options.get("expected_plan"),
            options.get("expected_active"),
            activate=options.get("activate_generation") is not None,
        )
    elif options.get("activate_generation") is not None:
        fail("activation_write_required")
    validate_local_target(settings)
    engine = create_db_engine(settings)
    try:
        with engine.begin() as connection:
            locked(connection, bool(options.get("write")))
            target = options.pop("activate_generation", None)
            if target is not None:
                if not options.get("write") or options.get("expected_active") is None:
                    fail("activation_write_and_expected_active_required")
                return activate(
                    connection, target, seeds, snapshot, expected_active=options["expected_active"]
                )
            return apply(connection, seeds, snapshot, **options)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--activate", type=UUID)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expected-plan")
    parser.add_argument("--expected-active")
    args = parser.parse_args()
    try:
        if args.write:
            validate_write(
                args.expected_plan, args.expected_active, activate=args.activate is not None
            )
        elif args.activate is not None:
            fail("activation_write_required")
        snapshot = load_snapshot(args.snapshot) if args.snapshot else None
        print(
            safe_json(
                run(
                    Settings(),
                    load_registry(args.registry),
                    snapshot,
                    write=args.write,
                    expected_plan=args.expected_plan,
                    expected_active=args.expected_active,
                    activate_generation=args.activate,
                )
            )
        )
        return 0
    except (AppError, ChainsError, SQLAlchemyError, ValueError, OSError):
        print(safe_json({"status": "error", "reason": "publication_rejected"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
