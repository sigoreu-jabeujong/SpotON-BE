from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, insert, select, text

from app.models import MarketStore, MarketStoreVersion
from etl.market_csv_repository import check_boundary as audit_boundary
from etl.market_stores.archive import RULE_VERSION, SOURCE_URL, StatsArchive, content_digest, fail

LOCK_NAMESPACE = 0x53504F54
LOCK_KEY = 17
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 60000


def set_limits(connection: Connection) -> None:
    for name, value in (
        ("lock_timeout", LOCK_TIMEOUT_MS),
        ("statement_timeout", STATEMENT_TIMEOUT_MS),
    ):
        connection.execute(select(func.set_config(name, str(value), True)))


def check_boundary(
    connection: Connection, archive: StatsArchive, boundary_id: UUID, *, lock: bool = False
) -> dict[str, Any]:
    return audit_boundary(connection, archive, boundary_id, fail=fail, lock=lock)


def _verify(
    connection: Connection, archive: StatsArchive, version_id: UUID, rule_version: str
) -> None:
    cols = [c for c in MarketStore.__table__.c if c.name != "version_id"]
    rows = [
        dict(r)
        for r in connection.execute(
            select(*cols)
            .where(MarketStore.version_id == version_id)
            .order_by(MarketStore.quarter, MarketStore.market_code, MarketStore.induty_cd)
            .with_for_update(read=True)
        ).mappings()
    ]
    if len(rows) != len(archive.rows) or content_digest(rows, rule_version) != content_digest(
        archive.rows, rule_version
    ):
        fail("stored_content")


def save(
    connection: Connection,
    archive: StatsArchive,
    boundary_id: UUID,
    *,
    rule_version: str = RULE_VERSION,
) -> tuple[UUID, bool, dict[str, Any]]:
    """Caller must commit/rollback the complete year; never overwrites a prior version."""
    if not connection.in_transaction():
        fail("transaction_required")
    set_limits(connection)
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:namespace,:key)"),
        {"namespace": LOCK_NAMESPACE, "key": LOCK_KEY},
    )
    report = check_boundary(connection, archive, boundary_id, lock=True)
    expected = dict(
        source_dataset="OA-15577",
        source_url=SOURCE_URL,
        source_file_date=archive.source_file_date,
        source_year=archive.source_year,
        input_sha256=archive.input_sha256,
        input_bytes=archive.input_bytes,
        member_name=archive.member_name,
        member_sha256=archive.member_sha256,
        member_bytes=archive.member_bytes,
        member_modified=archive.member_modified,
        source_encoding=archive.source_encoding,
        rule_version=rule_version,
        source_rows=archive.source_rows,
        row_count=len(archive.rows),
        excluded_rows=archive.source_rows - len(archive.rows),
        content_sha256=content_digest(archive.rows, rule_version),
        code_check_boundary_version_id=boundary_id,
        code_check=report,
        boundary_compatibility="unverified",
    )
    existing = (
        connection.execute(
            select(MarketStoreVersion.__table__)
            .where(
                MarketStoreVersion.input_sha256 == archive.input_sha256,
                MarketStoreVersion.rule_version == rule_version,
                MarketStoreVersion.code_check_boundary_version_id == boundary_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        if any(existing[k] != v for k, v in expected.items()):
            fail("version_metadata")
        version_id = cast(UUID, existing["version_id"])
        _verify(connection, archive, version_id, rule_version)
        return version_id, True, report
    version_id = uuid4()
    connection.execute(insert(MarketStoreVersion).values(version_id=version_id, **expected))
    for start in range(0, len(archive.rows), 500):
        connection.execute(
            insert(MarketStore),
            [{"version_id": version_id, **row} for row in archive.rows[start : start + 500]],
        )
    _verify(connection, archive, version_id, rule_version)
    return version_id, False, report
