from typing import Any, cast
from uuid import UUID, uuid4

from geoalchemy2.elements import WKBElement
from sqlalchemy import Connection, func, insert, select, text

from app.models import MarketArea, MarketAreaVersion
from etl.market_areas.archive import RULE_VERSION, SOURCE_URL, MarketImportError, digest
from etl.market_areas.geometry import PreparedArchive

IMPORT_LOCK = 0x53504F54


def _verify(connection: Connection, prepared: PreparedArchive, version_id: UUID) -> None:
    table = MarketArea.__table__
    cols = [col for col in table.c if col.name not in {"geom", "version_id"}]
    rows = (
        connection.execute(
            select(
                *cols, func.encode(func.ST_AsEWKB(MarketArea.geom, "NDR"), "hex").label("geom_hex")
            )
            .where(MarketArea.version_id == version_id)
            .order_by(MarketArea.market_code)
        )
        .mappings()
        .all()
    )
    values = []
    for r in rows:
        value = dict(r)
        value["area_m2"] = format(value["area_m2"], ".2f")
        values.append(value)
    if len(values) != len(prepared.areas) or digest(values) != prepared.content_sha256:
        raise MarketImportError("market:stored_content_mismatch")


def save(
    connection: Connection, prepared: PreparedArchive, *, rule_version: str = RULE_VERSION
) -> tuple[UUID, bool]:
    """Caller owns the transaction; all supported writers serialize and verify before commit."""
    if not connection.in_transaction():
        raise MarketImportError("market:transaction_required")
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:namespace,16)"), {"namespace": IMPORT_LOCK}
    )
    archive = prepared.source
    repaired = sum(a.geometry_repaired for a in prepared.areas)
    expected: dict[str, Any] = dict(
        source_dataset="OA-15560",
        source_url=SOURCE_URL,
        source_file_date=archive.source_file_date,
        boundary_as_of=None,
        input_sha256=archive.input_sha256,
        input_bytes=archive.input_bytes,
        source_crs=5181,
        rule_version=rule_version,
        row_count=len(prepared.areas),
        repaired_count=repaired,
        content_sha256=prepared.content_sha256,
    )
    existing = (
        connection.execute(
            select(MarketAreaVersion.__table__).where(
                MarketAreaVersion.input_sha256 == archive.input_sha256,
                MarketAreaVersion.rule_version == rule_version,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        if any(existing[k] != v for k, v in expected.items()):
            raise MarketImportError("market:version_metadata_mismatch")
        version_id = cast(UUID, existing["version_id"])
        _verify(connection, prepared, version_id)
        return version_id, True
    version_id = uuid4()
    connection.execute(
        insert(MarketAreaVersion).values(
            **expected, version_id=version_id, postgis_version=prepared.postgis_version
        )
    )
    values = []
    for area in prepared.areas:
        value = area.payload()
        value["area_m2"] = area.feature.area_m2
        geom = value.pop("geom_hex")
        values.append(
            {
                **value,
                "version_id": version_id,
                "geom": WKBElement(bytes.fromhex(geom), extended=True),
            }
        )
    connection.execute(insert(MarketArea), values)
    _verify(connection, prepared, version_id)
    return version_id, False
