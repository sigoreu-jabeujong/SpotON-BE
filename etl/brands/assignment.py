"""Atomic evidence generations; application never writes the original stores table."""

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Brand as DBBrand
from app.models import BrandCatalogVersion as CV
from app.models import BrandMappingRun as Run
from app.models import BrandMappingState as State
from app.models import Store
from app.models import StoreBrandMatch as Match
from app.models.brand import MAPPING_RULE
from app.services.store_scope import SOURCE_SUPPORTED_STORES
from etl.brands.catalog import Catalog, canonical, digest, fail
from etl.brands.matching import PARTITIONS, Matcher


@dataclass(frozen=True, repr=False)
class Plan:
    input_sha256: str
    counts: dict[str, int]
    targets: tuple[dict[str, Any], ...] = field(repr=False)


def limits(c: Connection) -> None:
    c.exec_driver_sql("SET LOCAL statement_timeout = '60s'")
    c.exec_driver_sql("SET LOCAL lock_timeout = '5s'")


def plan(c: Connection, catalog: Catalog) -> Plan:
    matcher = Matcher(catalog)
    counts = {key: 0 for key in PARTITIONS}
    targets = []
    h = hashlib.sha256(b"store-brand-input-v1\n")
    query = (
        select(
            Store.source,
            Store.license_no,
            Store.name,
            Store.category,
            Store.sub_category,
            Store.is_franchise,
            Store.brand_id,
        )
        .where(SOURCE_SUPPORTED_STORES)
        .order_by(Store.source.collate("C"), Store.license_no.collate("C"))
        .execution_options(stream_results=True, yield_per=2000)
    )
    result = c.execute(query)
    try:
        for row in result.mappings():
            values = dict(row)
            row_hash = digest(canonical(values))
            h.update(row_hash.encode("ascii") + b"\n")
            reason, brand = matcher.classify(values)
            counts[reason] += 1
            if brand is not None:
                targets.append(
                    dict(
                        **{
                            key: values[key]
                            for key in ("source", "license_no", "name", "category", "sub_category")
                        },
                        input_sha256=row_hash,
                        source_key=(brand.management_no, brand.headquarter_no),
                    )
                )
    finally:
        result.close()
    return Plan(h.hexdigest(), {"total": sum(counts.values()), **counts}, tuple(targets))


def _catalog(
    c: Connection, catalog: Catalog, input_hash: str
) -> tuple[UUID, dict[tuple[str, str], int], bool]:
    expected = dict(
        input_sha256=input_hash,
        content_sha256=catalog.content_sha256,
        catalog_rule=catalog.summary()["rule_version"],
        reference_year=catalog.year,
        collected_at=catalog.collected_at,
        row_count=len(catalog.rows),
    )
    stored = (
        c.execute(
            select(CV.__table__).where(
                CV.input_sha256 == input_hash, CV.catalog_rule == expected["catalog_rule"]
            )
        )
        .mappings()
        .one_or_none()
    )
    reused = stored is not None
    if stored is None:
        version = uuid4()
        c.execute(insert(CV).values(catalog_version_id=version, **expected))
        values = [
            dict(
                catalog_version_id=version, **{k: v for k, v in asdict(row).items() if k != "year"}
            )
            for row in catalog.rows
        ]
        for offset in range(0, len(values), 1000):
            c.execute(insert(DBBrand), values[offset : offset + 1000])
    else:
        if any(stored[key] != value for key, value in expected.items()):
            fail("catalog_metadata")
        version = stored["catalog_version_id"]
    rows = (
        c.execute(
            select(DBBrand.__table__)
            .where(DBBrand.catalog_version_id == version)
            .order_by(DBBrand.management_no.collate("C"), DBBrand.headquarter_no.collate("C"))
        )
        .mappings()
        .all()
    )
    source_values = [
        {
            k: r[k]
            for k in (
                "management_no",
                "headquarter_no",
                "name",
                "normalized_name",
                "industry",
                "sub_industry",
            )
        }
        for r in rows
    ]
    expected_values = [
        {k: v for k, v in asdict(row).items() if k != "year"} for row in catalog.rows
    ]
    if source_values != expected_values:
        fail("catalog_content")
    return version, {(r["management_no"], r["headquarter_no"]): r["brand_id"] for r in rows}, reused


def _verify_matches(
    c: Connection, run_id: UUID, version: UUID, targets: list[dict[str, Any]]
) -> None:
    rows = (
        c.execute(
            select(Match.__table__)
            .where(Match.run_id == run_id)
            .order_by(Match.source.collate("C"), Match.license_no.collate("C"))
        )
        .mappings()
        .all()
    )
    keys = ("source", "license_no", "name", "category", "sub_category", "input_sha256", "brand_id")
    if (
        len(rows) != len(targets)
        or any(row["catalog_version_id"] != version for row in rows)
        or [{k: r[k] for k in keys} for r in rows] != [{k: t[k] for k in keys} for t in targets]
    ):
        fail("mapping_content")


def save(c: Connection, catalog: Catalog, input_hash: str, prepared: Plan) -> dict[str, Any]:
    version, brands, catalog_reused = _catalog(c, catalog, input_hash)
    expected = dict(
        catalog_version_id=version,
        rule_version=MAPPING_RULE,
        store_input_sha256=prepared.input_sha256,
        row_count=prepared.counts["total"],
        matched_count=len(prepared.targets),
        counts=prepared.counts,
    )
    stored = (
        c.execute(
            select(Run.__table__).where(
                Run.catalog_version_id == version,
                Run.rule_version == MAPPING_RULE,
                Run.store_input_sha256 == prepared.input_sha256,
            )
        )
        .mappings()
        .one_or_none()
    )
    reused = stored is not None
    targets = [
        dict(
            **{k: v for k, v in row.items() if k != "source_key"},
            brand_id=brands[row["source_key"]],
        )
        for row in prepared.targets
    ]
    if stored is None:
        run_id = uuid4()
        c.execute(insert(Run).values(run_id=run_id, **expected))
        values = [
            dict(match_id=uuid4(), run_id=run_id, catalog_version_id=version, **row)
            for row in targets
        ]
        for offset in range(0, len(values), 1000):
            c.execute(insert(Match), values[offset : offset + 1000])
    else:
        if any(stored[key] != value for key, value in expected.items()):
            fail("mapping_metadata")
        run_id = stored["run_id"]
    _verify_matches(c, run_id, version, targets)
    current = c.execute(
        select(State.run_id, State.catalog_version_id).where(State.id == 1)
    ).one_or_none()
    switched = current is None or tuple(current) != (run_id, version)
    if switched:
        statement = pg_insert(State).values(id=1, run_id=run_id, catalog_version_id=version)
        c.execute(
            statement.on_conflict_do_update(
                index_elements=[State.id],
                set_={
                    "run_id": statement.excluded.run_id,
                    "catalog_version_id": statement.excluded.catalog_version_id,
                },
            )
        )
    return dict(
        version_id=str(version),
        mapping_run_id=str(run_id),
        catalog_reused=catalog_reused,
        reused=reused,
        state_changed=switched,
    )
