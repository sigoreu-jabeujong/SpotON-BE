from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, insert, select, text

from app.models import MarketChange, MarketChangeVersion
from etl.market_changes.source import (
    RULE_VERSION,
    SOURCE_URL,
    MarketChangeInput,
    content_digest,
    fail,
)
from etl.market_csv_repository import check_boundary

LOCK_NAMESPACE = 0x53504F54
LOCK_KEY = 20
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 60000


def set_limits(connection: Connection) -> None:
    for name, value in (
        ("lock_timeout", LOCK_TIMEOUT_MS),
        ("statement_timeout", STATEMENT_TIMEOUT_MS),
    ):
        connection.execute(select(func.set_config(name, str(value), True)))


def _verify(
    connection: Connection,
    source: MarketChangeInput,
    version_id: UUID,
    rule_version: str,
    *,
    lock: bool,
) -> None:
    query = (
        select(*(c for c in MarketChange.__table__.c if c.name != "version_id"))
        .where(MarketChange.version_id == version_id)
        .order_by(MarketChange.quarter, MarketChange.market_code)
    )
    if lock:
        query = query.with_for_update(read=True)
    rows = [dict(r) for r in connection.execute(query).mappings()]
    if len(rows) != len(source.rows) or content_digest(
        rows, source.source_year, rule_version
    ) != content_digest(source.rows, source.source_year, rule_version):
        fail("stored_content")


def inspect_import(
    connection: Connection,
    source: MarketChangeInput,
    boundary_id: UUID,
    *,
    rule_version: str = RULE_VERSION,
    lock: bool = False,
) -> tuple[dict[str, Any], UUID | None]:
    report = check_boundary(connection, source, boundary_id, fail=fail, lock=lock)
    expected = dict(
        **{
            k: getattr(source, k)
            for k in (
                "source_year",
                "retrieved_at",
                "input_sha256",
                "input_bytes",
                "source_encoding",
                "source_rows",
            )
        },
        source_file_date=None,
        source_dataset="OA-15576",
        source_url=SOURCE_URL,
        rule_version=rule_version,
        row_count=len(source.rows),
        excluded_rows=source.source_rows - len(source.rows),
        content_sha256=content_digest(source.rows, source.source_year, rule_version),
        code_check_boundary_version_id=boundary_id,
        code_check=report,
        boundary_compatibility="unverified",
    )
    query = select(MarketChangeVersion.__table__).where(
        MarketChangeVersion.input_sha256 == source.input_sha256,
        MarketChangeVersion.source_year == source.source_year,
        MarketChangeVersion.rule_version == rule_version,
        MarketChangeVersion.code_check_boundary_version_id == boundary_id,
    )
    if lock:
        query = query.with_for_update()
    existing = connection.execute(query).mappings().one_or_none()
    if existing is None:
        return expected, None
    if any(
        existing[k] != expected[k]
        for k in ("retrieved_at", "input_bytes", "source_encoding", "content_sha256")
    ):
        fail("provenance_conflict")
    if any(existing[k] != value for k, value in expected.items()):
        fail("version_metadata")
    version_id = cast(UUID, existing["version_id"])
    _verify(connection, source, version_id, rule_version, lock=lock)
    return expected, version_id


def same_content_versions(connection: Connection, source: MarketChangeInput) -> int:
    """Informational only: distinct input bytes may have the same selected-year content."""
    return (
        connection.scalar(
            select(func.count())
            .select_from(MarketChangeVersion)
            .where(
                MarketChangeVersion.source_year == source.source_year,
                MarketChangeVersion.rule_version == RULE_VERSION,
                MarketChangeVersion.content_sha256
                == content_digest(source.rows, source.source_year),
            )
        )
        or 0
    )


def save(
    connection: Connection,
    source: MarketChangeInput,
    boundary_id: UUID,
    *,
    rule_version: str = RULE_VERSION,
) -> tuple[UUID, bool, dict[str, Any]]:
    """One selected year per caller-owned transaction; never repairs existing versions."""
    if not connection.in_transaction():
        fail("transaction_required")
    set_limits(connection)
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:n,:k)"), {"n": LOCK_NAMESPACE, "k": LOCK_KEY}
    )
    expected, version_id = inspect_import(
        connection, source, boundary_id, rule_version=rule_version, lock=True
    )
    if version_id is not None:
        return version_id, True, expected["code_check"]
    version_id = uuid4()
    connection.execute(insert(MarketChangeVersion).values(version_id=version_id, **expected))
    for start in range(0, len(source.rows), 500):
        connection.execute(
            insert(MarketChange),
            [{"version_id": version_id, **r} for r in source.rows[start : start + 500]],
        )
    _verify(connection, source, version_id, rule_version, lock=True)
    return version_id, False, expected["code_check"]
