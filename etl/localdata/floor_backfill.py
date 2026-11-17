"""Verified, source-wide location repair. Default: read-only; never INSERT stores."""

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Table, bindparam, func, insert, select, text, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_db_engine
from app.models import Store, StoreImportBatch
from etl.address.floor_unit import parse_floor_unit
from etl.localdata.collection import CollectedSource
from etl.localdata.constants import Source
from etl.localdata.pipeline import StoreRecord, transform_rows
from etl.localdata.provenance import ETL_RULE_VERSION, MAP_VERSION, import_batch
from etl.localdata.runner import (
    ImportConfigurationError,
    SafeParser,
    check_local_database,
    validate_local_target,
)
from etl.localdata.snapshot import SnapshotError, load_snapshot

RULE_VERSION = "floor-location-backfill-v1"
MUTABLE = frozenset({"floor_unit", "location_level", "batch_id", "updated_at"})
BATCH_FIELDS = (
    "source",
    "data_updated_at",
    "update_reason",
    "recorded_at",
    "collection_basis",
    "input_kind",
    "input_sha256",
    "rows_sha256",
    "row_count",
    "map_version",
)
RECORD_FIELDS = tuple(
    f.name
    for f in fields(StoreRecord)
    if f.name not in {"floor_unit", "location_level", "batch_id"}
)
SCAN_FIELDS = tuple(c.name for c in Store.__table__.columns)
ZERO_UUID = UUID(int=0)


class BackfillError(ValueError):
    """Only fixed, non-sensitive error codes cross the CLI boundary."""


def _encoded(value: object) -> bytes:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


@dataclass(frozen=True, repr=False)
class PreparedSource:
    collection: CollectedSource
    records: tuple[StoreRecord, ...]
    batch_values: dict[str, Any]


@dataclass(frozen=True, repr=False)
class Plan:
    source: str
    batch_id: UUID
    sha256: str
    state_sha256: str
    protected_sha256: str
    row_count: int
    changes: tuple[dict[str, Any], ...] = field(repr=False)
    counts: dict[str, int]
    districts: dict[str, int]

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "plan_sha256": self.sha256,
            "state_sha256": self.state_sha256,
            "protected_sha256": self.protected_sha256,
            "row_count": self.row_count,
            "changed_rows": len(self.changes),
            "counts": self.counts,
            "districts": self.districts,
            "rule_version": RULE_VERSION,
        }


def prepare_source(path: Path, source: Source) -> PreparedSource:
    collection = load_snapshot(path, source)
    result = transform_rows(
        source, collection.rows, batch_id=ZERO_UUID, today=collection.collected_at.date()
    )
    batch = import_batch(collection, ZERO_UUID)
    return PreparedSource(
        collection, result.records, {name: getattr(batch, name) for name in BATCH_FIELDS}
    )


def expected_geometry(record: StoreRecord) -> str | None:
    if record.lat is None or record.lng is None:
        return None
    # Same 2D POINT(lng lat), SRID 4326 as repository._payload; compare NDR EWKB bytes.
    return struct.pack("<BII2d", 1, 0x20000001, 4326, float(record.lng), float(record.lat)).hex()


def location_change(stored: str | None, level: str | None, record: StoreRecord) -> bool:
    if record.building_key is None and record.location_level != "unverified":
        raise BackfillError("backfill:location_conflict")
    if stored is None and level in {None, "unverified"}:
        return record.floor_unit is not None
    if stored is not None and (stored, level) == (record.floor_unit, record.location_level):
        return False
    raise BackfillError("backfill:location_conflict")


def _rows(connection: Connection, source: str) -> Iterator[RowMapping]:
    statement = (
        select(
            *[c for c in Store.__table__.columns if c.name != "geom"],
            func.encode(func.ST_AsEWKB(Store.geom, "NDR"), "hex").label("geom"),
        )
        .where(Store.source == source)
        .order_by(Store.license_no.collate("C"))
    )
    with connection.execute(
        statement.execution_options(stream_results=True, yield_per=2000)
    ) as result:
        yield from result.mappings()


def _batch(connection: Connection, prepared: PreparedSource) -> RowMapping:
    source = prepared.collection.source.value
    ids = list(connection.scalars(select(Store.batch_id).where(Store.source == source).distinct()))
    if len(ids) != 1 or ids[0] is None:
        raise BackfillError("backfill:active_batch")
    batch = (
        connection.execute(
            select(StoreImportBatch.__table__).where(
                StoreImportBatch.batch_id == ids[0], StoreImportBatch.source == source
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        batch is None
        or any(batch[name] != prepared.batch_values[name] for name in BATCH_FIELDS)
        or batch["rule_version"] not in {"localdata-normalization-v1", ETL_RULE_VERSION}
        or batch["map_version"] != MAP_VERSION
    ):
        raise BackfillError("backfill:provenance")
    return batch


def _check_resolution(connection: Connection) -> None:
    public = connection.scalar(
        text(
            "SELECT to_regclass('stores')='public.stores'::regclass "
            "AND to_regclass('store_import_batches')='public.store_import_batches'::regclass"
        )
    )
    if public is not True:
        raise BackfillError("backfill:target")


def _target(connection: Connection) -> list[object]:
    row = connection.execute(
        text("SELECT current_database(),current_user,inet_server_port(),pg_postmaster_start_time()")
    ).one()
    url = connection.engine.url
    return [url.host, url.port or 5432, url.database, url.username, *row]


def inspect_source(connection: Connection, prepared: PreparedSource) -> Plan:
    """Inspect within the caller's stable read-only view or acquired writer locks."""
    _check_resolution(connection)
    batch = _batch(connection, prepared)
    expected = {record.license_no: record for record in prepared.records}
    if len(expected) != len(prepared.records) or not expected:
        raise BackfillError("backfill:keys")
    protected = hashlib.sha256()
    state = hashlib.sha256()
    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    districts: Counter[str] = Counter()
    seen = 0
    for row in _rows(connection, prepared.collection.source.value):
        seen += 1
        record = expected.get(row["license_no"])
        if record is None or row["batch_id"] != batch["batch_id"]:
            raise BackfillError("backfill:keys")
        if any(row[name] != getattr(record, name) for name in RECORD_FIELDS):
            raise BackfillError("backfill:non_location")
        if row["geom"] != expected_geometry(record):
            raise BackfillError("backfill:geometry")
        state.update(_encoded([row[name] for name in SCAN_FIELDS]) + b"\n")
        protected.update(
            _encoded([row[name] for name in SCAN_FIELDS if name not in MUTABLE]) + b"\n"
        )
        if not location_change(row["floor_unit"], row["location_level"], record):
            continue
        parsed = parse_floor_unit(record.floor_unit).value
        if parsed is None:
            raise BackfillError("backfill:location_conflict")
        changes.append(
            {"key": record.license_no, "floor": record.floor_unit, "level": record.location_level}
        )
        counts[
            "floor_and_unit"
            if parsed.floor and parsed.unit
            else "floor_only"
            if parsed.floor
            else "unit_only"
        ] += 1
        counts["level_" + record.location_level] += 1
        if record.building_key is None:
            counts["no_building_key"] += 1
        supported = (record.category == "cafe" and record.sub_category == "cafe") or (
            record.category == "restaurant"
            and record.sub_category in {"korean", "chinese", "japanese", "western"}
        )
        if supported and not record.category_review_flag and row["deleted_at"] is None:
            counts["supported"] += 1
        districts[record.gu_code] += 1
    if seen != len(expected):
        raise BackfillError("backfill:keys")
    state_hash, protected_hash = state.hexdigest(), protected.hexdigest()
    # Hash the ordered change list; raw identifiers and addresses never leave this process.
    payload = {
        "rule": RULE_VERSION,
        "normalization": ETL_RULE_VERSION,
        "map": MAP_VERSION,
        "batch": dict(batch),
        "source": prepared.collection.source.value,
        "original": prepared.batch_values,
        "target": _target(connection),
        "state": state_hash,
        "protected": protected_hash,
        "changes": digest(changes),
    }
    return Plan(
        prepared.collection.source.value,
        batch["batch_id"],
        digest(payload),
        state_hash,
        protected_hash,
        seen,
        tuple(changes),
        dict(counts),
        dict(districts),
    )


def _sequence(connection: Connection) -> tuple[int, bool]:
    row = connection.execute(text("SELECT last_value,is_called FROM public.stores_id_seq")).one()
    return int(row[0]), bool(row[1])


def _write_changes(connection: Connection, plan: Plan, new_id: UUID) -> None:
    table = cast(Table, Store.__table__)
    statement = (
        update(table)
        .where(
            table.c.source == plan.source,
            table.c.license_no == bindparam("key"),
            table.c.batch_id == plan.batch_id,
            table.c.floor_unit.is_(None),
        )
        .values(floor_unit=bindparam("floor"), location_level=bindparam("level"))
    )
    affected = 0
    for offset in range(0, len(plan.changes), 1000):
        result = connection.execute(statement, list(plan.changes[offset : offset + 1000]))
        affected += result.rowcount
    if affected != len(plan.changes):
        raise BackfillError("backfill:affected_rows")
    result = connection.execute(
        update(table)
        .where(table.c.source == plan.source, table.c.batch_id == plan.batch_id)
        .values(batch_id=new_id, updated_at=func.now())
    )
    if result.rowcount != plan.row_count:
        raise BackfillError("backfill:affected_rows")


def apply_source(
    connection: Connection, prepared: PreparedSource, expected_plan: str
) -> dict[str, Any]:
    """Caller owns commit/rollback. Acquire locks before comparing current source state."""
    if re.fullmatch(r"[0-9a-f]{64}", expected_plan) is None:
        raise BackfillError("backfill:arguments")
    if connection.scalar(text("SHOW transaction_isolation")) != "read committed":
        raise BackfillError("backfill:isolation")
    _check_resolution(connection)
    connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "spoton:localdata:" + prepared.collection.source.value},
    )
    connection.exec_driver_sql(
        "LOCK TABLE public.stores,public.store_import_batches IN SHARE ROW EXCLUSIVE MODE"
    )
    plan = inspect_source(connection, prepared)
    if plan.sha256 != expected_plan:
        raise BackfillError("backfill:stale_plan")
    if not plan.changes:
        return {**plan.summary(), "status": "no_op"}
    sequence = _sequence(connection)
    new_id = uuid4()
    connection.execute(
        insert(StoreImportBatch).values(
            **prepared.batch_values, batch_id=new_id, rule_version=ETL_RULE_VERSION
        )
    )
    _write_changes(connection, plan, new_id)
    after = inspect_source(connection, prepared)
    if (
        after.changes
        or after.row_count != plan.row_count
        or after.batch_id != new_id
        or after.protected_sha256 != plan.protected_sha256
        or _sequence(connection) != sequence
    ):
        raise BackfillError("backfill:postcheck")
    return {
        **plan.summary(),
        "status": "applied",
        "new_batch_id": str(new_id),
        "after_state_sha256": after.state_sha256,
    }


def run_backfill(
    source: Source,
    snapshot: Path,
    *,
    settings: Settings | None = None,
    write: bool = False,
    expected_plan: str | None = None,
) -> dict[str, Any]:
    if (
        type(write) is not bool
        or (write and expected_plan is None)
        or (
            expected_plan is not None
            and (not write or re.fullmatch(r"[0-9a-f]{64}", expected_plan) is None)
        )
    ):
        raise BackfillError("backfill:arguments")
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    prepared = prepare_source(snapshot, source)
    engine = create_db_engine(config)
    try:
        isolation = "READ COMMITTED" if write else "REPEATABLE READ"
        with engine.connect().execution_options(isolation_level=isolation) as connection:
            with connection.begin():
                if not write:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql("SET LOCAL statement_timeout='300s'")
                check_local_database(connection)
                if write:
                    assert expected_plan is not None
                    return {"mode": "write", **apply_source(connection, prepared, expected_plan)}
                plan = inspect_source(connection, prepared)
                return {
                    "mode": "dry_run",
                    **plan.summary(),
                    "status": "ready" if plan.changes else "no_op",
                }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser: argparse.ArgumentParser = SafeParser(allow_abbrev=False)
    parser.add_argument("--source", choices=[s.value for s in Source], required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expected-plan")
    args = parser.parse_args(argv)
    try:
        result = run_backfill(
            Source(args.source), args.snapshot, write=args.write, expected_plan=args.expected_plan
        )
    except BackfillError as exc:
        result = {"status": "error", "error": str(exc)}
    except (SnapshotError, ImportConfigurationError):
        result = {"status": "error", "error": "backfill:configuration_or_source"}
    except SQLAlchemyError:
        result = {"status": "error", "error": "backfill:database"}
    except (Exception, KeyboardInterrupt):
        result = {"status": "error", "error": "backfill:operation_failed"}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
