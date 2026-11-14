import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from sqlalchemy import Connection, select

from app.core.config import Settings
from app.db.session import create_db_engine
from app.models import Brand as DBBrand
from app.models import BrandCatalogVersion as CV
from app.models import BrandMappingState as State
from app.models import Store
from app.models import StoreBrandMatch as Match
from app.models.chain import CHAIN_FIELDS
from app.services.store_scope import SOURCE_SUPPORTED_STORES, excluded_by_name
from etl.brands.catalog import Brand as CatalogBrand
from etl.brands.catalog import canonical, content_hash
from etl.chains.common import POLICY_VERSION, RULE_VERSION, digest, fail
from etl.chains.linking import OutletIndex, address_keys, eligible
from etl.chains.matching import ChainMatcher
from etl.chains.registry import BrandSpec, catalog_links, extend_catalog, registry_hash
from etl.chains.semas import Snapshot
from etl.localdata.runner import check_local_database, validate_local_target

FIELDS = CHAIN_FIELDS


def store_query() -> Any:
    return (
        select(*(getattr(Store, field) for field in FIELDS))
        .where(SOURCE_SUPPORTED_STORES)
        .order_by(Store.source.collate("C"), Store.license_no.collate("C"))
        .execution_options(stream_results=True, yield_per=2000)
    )


def _rows(c: Connection) -> Iterable[Mapping[str, Any]]:
    result = c.execute(store_query())
    try:
        for row in result.mappings():
            yield dict(row)
    finally:
        result.close()


def compare_rows(
    rows: Iterable[Mapping[str, Any]],
    matcher: ChainMatcher,
    *,
    index: OutletIndex | None = None,
    local_counts: Mapping[str, int] | None = None,
    legacy_matches: set[tuple[Any, ...]] | None = None,
    include_inputs: bool = False,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    status: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    brands: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    comparisons: Counter[str] = Counter()
    temporal: Counter[str] = Counter()
    plans = []
    source_hash = hashlib.sha256()
    for row in rows:
        values = {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}
        source_hash.update(canonical(values) + b"\n")
        decision = matcher.classify(row.get("name"))
        semas_id = None
        if decision.status == "unknown" and index is not None:
            linked, semas_id = index.corroborate(row, local_counts or {})
            if linked is not None:
                decision = linked
        status[decision.status] += 1
        operating = row.get("status") if row.get("status") in {"open", "closed"} else "other"
        temporal[f"{operating}:{decision.status}"] += 1
        reasons[decision.reason] += 1
        if excluded_by_name(row.get("category"), row.get("name")):
            exclusions[decision.status] += 1
        legacy_key = tuple(
            row.get(k) for k in ("source", "license_no", "name", "category", "sub_category")
        )
        legacy_positive = row.get("is_franchise") is True or (
            row.get("is_franchise") is None
            and row.get("brand_id") is None
            and legacy_key in (legacy_matches or set())
        )
        if decision.status == "estimated":
            assert decision.brand is not None
            brands[decision.brand.key] += 1
            comparisons[
                "legacy_positive_brand_unchecked" if legacy_positive else "additional_estimate"
            ] += 1
            if row.get("is_franchise") is False:
                comparisons["legacy_false_with_chain_estimate"] += 1
        elif legacy_positive:
            comparisons["legacy_positive_now_" + decision.status] += 1
        if decision.status != "unknown":
            values = {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}
            plans.append(
                dict(
                    source=row.get("source"),
                    license_no=row.get("license_no"),
                    status=decision.status,
                    reason=decision.reason,
                    brand_key=str(decision.brand.canonical_id) if decision.brand else None,
                    input_sha256=digest(values),
                    semas_id=semas_id,
                    operation_type="unknown",
                    time_basis="observed_record",
                    **({"inputs": dict(row)} if include_inputs else {}),
                )
            )
    summary = dict(
        total=sum(status.values()),
        status=dict(sorted(status.items())),
        reasons=dict(sorted(reasons.items())),
        brands={
            b.key: brands[b.key]
            for b in matcher.brands
            if b.origin == "reviewed_seed" and brands[b.key]
        },
        catalog_only_brand_count=sum(
            1 for b in matcher.brands if b.origin == "ftc_exact" and brands[b.key]
        ),
        catalog_only_estimates=sum(
            brands[b.key] for b in matcher.brands if b.origin == "ftc_exact"
        ),
        name_excluded=dict(sorted(exclusions.items())),
        legacy_comparison=dict(sorted(comparisons.items())),
        temporal_status=dict(sorted(temporal.items())),
        rule_version=RULE_VERSION,
        policy_version=POLICY_VERSION,
        registry_sha256=registry_hash(matcher.brands),
        plan_sha256=digest([{k: v for k, v in p.items() if k != "inputs"} for p in plans]),
        store_sha256=source_hash.hexdigest(),
        operation_type="unknown",
        classification="estimate_not_contract_or_historical_membership",
    )
    if index is not None:
        summary["semas"] = dict(
            reference_month=index.snapshot.reference_month,
            observed_at=index.snapshot.observed_at.isoformat(),
            content_sha256=index.snapshot.content_sha256,
        )
    return summary, tuple(plans)


def compare_local(
    settings: Settings,
    seeds: tuple[BrandSpec, ...],
    snapshot: Snapshot | None = None,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    validate_local_target(settings)
    engine = create_db_engine(settings)
    try:
        with engine.connect() as c:
            c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            c.exec_driver_sql("SET LOCAL statement_timeout='60s'")
            c.exec_driver_sql("SET LOCAL lock_timeout='5s'")
            check_local_database(c)
            summary, plan, _ = prepare(c, seeds, snapshot)
            return summary, plan
    finally:
        engine.dispose()


def prepare(
    c: Connection,
    seeds: tuple[BrandSpec, ...],
    snapshot: Snapshot | None = None,
    *,
    include_inputs: bool = False,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], tuple[BrandSpec, ...]]:
    active = c.execute(select(State.__table__)).mappings().one_or_none()
    legacy: set[tuple[Any, ...]] = set()
    brands = seeds
    reference = None
    links: dict[str, dict[str, str | int]] | None = None
    if active is not None:
        cv = (
            c.execute(
                select(CV.__table__).where(CV.catalog_version_id == active["catalog_version_id"])
            )
            .mappings()
            .one()
        )
        raw = c.execute(
            select(DBBrand.__table__)
            .where(DBBrand.catalog_version_id == active["catalog_version_id"])
            .order_by(DBBrand.management_no.collate("C"), DBBrand.headquarter_no.collate("C"))
        )
        catalog = tuple(
            CatalogBrand(
                cv["reference_year"],
                b.management_no,
                b.headquarter_no,
                b.name,
                b.normalized_name,
                b.industry,
                b.sub_industry,
            )
            for b in raw
        )
        if content_hash(catalog) != cv["content_sha256"] or len(catalog) != cv["row_count"]:
            fail("catalog_integrity")
        links = catalog_links(seeds, catalog)
        brands = extend_catalog(seeds, catalog, cv["collected_at"].date())
        legacy = set(
            c.execute(
                select(
                    Match.source,
                    Match.license_no,
                    Match.name,
                    Match.category,
                    Match.sub_category,
                ).where(Match.run_id == active["run_id"])
            ).tuples()
        )
        reference = dict(
            reference_year=cv["reference_year"],
            catalog_id=str(cv["catalog_version_id"]),
            run_id=str(active["run_id"]),
        )
    matcher = ChainMatcher(brands)
    index = OutletIndex(snapshot, matcher) if snapshot is not None else None
    local_counts: Counter[str] = Counter()
    if snapshot is not None:
        for row in _rows(c):
            if eligible(row, snapshot.reference_month):
                local_counts.update(
                    address_keys(
                        row.get("address_jibun"),
                        row.get("address_road"),
                        row.get("building_key"),
                    )
                )
    summary, plan = compare_rows(
        _rows(c),
        matcher,
        index=index,
        local_counts=local_counts,
        legacy_matches=legacy,
        include_inputs=include_inputs,
    )
    summary["legacy_catalog"] = reference
    summary["seed_catalog_links"] = links
    return summary, plan, brands
