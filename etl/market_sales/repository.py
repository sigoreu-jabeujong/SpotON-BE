from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, insert, select, text

from app.models import MarketSale, MarketSaleVersion, MarketStore, MarketStoreVersion
from etl.market_csv import AnnualArchive
from etl.market_csv_repository import check_boundary
from etl.market_sales.archive import RULE_VERSION, SOURCE_URL, content_digest, fail
from etl.market_stores.archive import content_digest as store_digest

LOCK_NAMESPACE = 0x53504F54
LOCK_KEY = 18
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 60000


def set_limits(connection: Connection) -> None:
    for name, value in (
        ("lock_timeout", LOCK_TIMEOUT_MS),
        ("statement_timeout", STATEMENT_TIMEOUT_MS),
    ):
        connection.execute(select(func.set_config(name, str(value), True)))


def _audit_stores(
    connection: Connection,
    archive: AnnualArchive,
    boundary_id: UUID,
    store_id: UUID,
    report: dict[str, Any],
    *,
    lock: bool,
) -> None:
    query = select(MarketStoreVersion.__table__).where(MarketStoreVersion.version_id == store_id)
    rows_query = (
        select(*(c for c in MarketStore.__table__.c if c.name != "version_id"))
        .where(MarketStore.version_id == store_id)
        .order_by(MarketStore.quarter, MarketStore.market_code, MarketStore.induty_cd)
    )
    if lock:
        query = query.with_for_update(read=True)
        rows_query = rows_query.with_for_update(read=True)
    manifest = connection.execute(query).mappings().one_or_none()
    if manifest is None:
        fail("store_version_missing")
    if manifest["source_year"] != archive.source_year:
        fail("store_year")
    if manifest["code_check_boundary_version_id"] != boundary_id:
        fail("reference_boundary")
    rows = [dict(r) for r in connection.execute(rows_query).mappings()]
    if (
        len(rows) != manifest["row_count"]
        or not rows
        or store_digest(rows, manifest["rule_version"]) != manifest["content_sha256"]
        or {r["quarter"] for r in rows} != {f"{archive.source_year}{q}" for q in range(1, 5)}
    ):
        fail("store_content")
    report["store_version_id"] = str(store_id)
    report["store_content_sha256"] = manifest["content_sha256"]
    for quarter, detail in report["quarters"].items():
        sales = {
            (r["market_code"], r["induty_cd"]): r for r in archive.rows if r["quarter"] == quarter
        }
        stores = {(r["market_code"], r["induty_cd"]): r for r in rows if r["quarter"] == quarter}
        common = sales.keys() & stores.keys()
        detail.update(
            sales_only_combinations=len(sales.keys() - stores.keys()),
            stores_only_combinations=len(stores.keys() - sales.keys()),
            store_type_mismatches=sum(
                sales[k]["market_type_code"] != stores[k]["market_type_code"] for k in common
            ),
            store_name_mismatches=sum(
                sales[k]["market_name"] != stores[k]["market_name"] for k in common
            ),
            store_industry_label_mismatches=sum(
                sales[k]["induty_name"] != stores[k]["induty_name"] for k in common
            ),
        )


def _verify(
    connection: Connection,
    archive: AnnualArchive,
    version_id: UUID,
    rule_version: str,
    *,
    lock: bool,
) -> None:
    query = (
        select(*(c for c in MarketSale.__table__.c if c.name != "version_id"))
        .where(MarketSale.version_id == version_id)
        .order_by(MarketSale.quarter, MarketSale.market_code, MarketSale.induty_cd)
    )
    if lock:
        query = query.with_for_update(read=True)
    rows = [dict(r) for r in connection.execute(query).mappings()]
    if len(rows) != len(archive.rows) or content_digest(
        rows, archive.source_year, rule_version
    ) != content_digest(archive.rows, archive.source_year, rule_version):
        fail("stored_content")


def inspect_import(
    connection: Connection,
    archive: AnnualArchive,
    boundary_id: UUID,
    store_id: UUID,
    *,
    rule_version: str = RULE_VERSION,
    lock: bool = False,
) -> tuple[dict[str, Any], UUID | None]:
    report = check_boundary(connection, archive, boundary_id, fail=fail, lock=lock)
    _audit_stores(connection, archive, boundary_id, store_id, report, lock=lock)
    metadata_fields = (
        "source_year",
        "source_file_date",
        "input_sha256",
        "input_bytes",
        "member_name",
        "member_sha256",
        "member_bytes",
        "member_modified",
        "source_encoding",
        "source_rows",
    )
    expected = dict(
        **{k: getattr(archive, k) for k in metadata_fields},
        source_dataset="OA-15572",
        source_url=SOURCE_URL,
        rule_version=rule_version,
        row_count=len(archive.rows),
        excluded_rows=archive.source_rows - len(archive.rows),
        content_sha256=content_digest(archive.rows, archive.source_year, rule_version),
        code_check_boundary_version_id=boundary_id,
        code_check_store_version_id=store_id,
        code_check=report,
        boundary_compatibility="unverified",
        currency="KRW",
        amount_basis="source_reported",
        amount_period_status="unverified",
    )
    query = select(MarketSaleVersion.__table__).where(
        MarketSaleVersion.input_sha256 == archive.input_sha256,
        MarketSaleVersion.rule_version == rule_version,
        MarketSaleVersion.code_check_boundary_version_id == boundary_id,
        MarketSaleVersion.code_check_store_version_id == store_id,
    )
    if lock:
        query = query.with_for_update()
    existing = connection.execute(query).mappings().one_or_none()
    if existing is None:
        return expected, None
    if any(existing[k] != v for k, v in expected.items()):
        fail("version_metadata")
    vid = cast(UUID, existing["version_id"])
    _verify(connection, archive, vid, rule_version, lock=lock)
    return expected, vid


def save(
    connection: Connection,
    archive: AnnualArchive,
    boundary_id: UUID,
    store_id: UUID,
    *,
    rule_version: str = RULE_VERSION,
) -> tuple[UUID, bool, dict[str, Any]]:
    """Caller owns the annual transaction; all supported writers lock before checking existence."""
    if not connection.in_transaction():
        fail("transaction_required")
    set_limits(connection)
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:n,:k)"), {"n": LOCK_NAMESPACE, "k": LOCK_KEY}
    )
    expected, version_id = inspect_import(
        connection, archive, boundary_id, store_id, rule_version=rule_version, lock=True
    )
    if version_id is not None:
        return version_id, True, expected["code_check"]
    version_id = uuid4()
    connection.execute(insert(MarketSaleVersion).values(version_id=version_id, **expected))
    for start in range(0, len(archive.rows), 500):
        connection.execute(
            insert(MarketSale),
            [{"version_id": version_id, **r} for r in archive.rows[start : start + 500]],
        )
    _verify(connection, archive, version_id, rule_version, lock=True)
    return version_id, False, expected["code_check"]
