"""Explicit, local development imports. Default mode never creates a DB engine."""

import argparse
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import Connection, Engine, text

from app.core.config import Settings
from app.db.session import create_db_engine, normalize_database_url
from etl.localdata.client import LocalDataClient, LocalDataError
from etl.localdata.constants import Source
from etl.localdata.csv_source import CSVSourceError, load_validated_csv
from etl.localdata.pipeline import transform_rows
from etl.localdata.provenance import import_batch
from etl.localdata.repository import upsert_records
from etl.localdata.snapshot import SnapshotError, load_snapshot, save_snapshot

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REQUEST_BUDGET = 9500


class ImportConfigurationError(ValueError):
    pass


def validate_local_target(settings: Settings) -> None:
    if settings.database_url is None:
        raise ImportConfigurationError("import:missing_database")
    url = normalize_database_url(settings.database_url.get_secret_value())
    if (
        url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.database != "spoton_dev"
        or url.username != "spoton_app"
    ):
        raise ImportConfigurationError("import:wrong_target")


def check_local_database(connection: Connection) -> None:
    identity = connection.execute(
        text(
            "SELECT current_database(), current_user, "
            "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user), "
            "EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')"
        )
    ).one()
    if tuple(identity) != ("spoton_dev", "spoton_app", False, True):
        raise ImportConfigurationError("import:database_identity")
    if list(connection.scalars(text("SELECT version_num FROM alembic_version"))) != ["0008"]:
        raise ImportConfigurationError("import:migration")
    definition = connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='stores'::regclass AND conname='uq_stores_source_license_no' "
            "AND contype='u'"
        )
    )
    if definition != "UNIQUE (source, license_no)":
        raise ImportConfigurationError("import:constraint")


def run_import(
    source: Source,
    *,
    settings: Settings | None = None,
    write: bool = False,
    workers: int = 1,
    from_snapshot: Path | None = None,
    from_csv: Path | None = None,
    validation: Path | None = None,
    save: bool = False,
    max_requests: int = DEFAULT_REQUEST_BUDGET,
    progress: Callable[[Source, str, int, int], None] | None = None,
) -> dict[str, Any]:
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ImportConfigurationError("import:workers")
    if from_snapshot is not None and save:
        raise ImportConfigurationError("import:snapshot_options")
    if (
        from_csv is not None
        and (write or from_snapshot is not None or validation is None)
        or validation is not None
        and from_csv is None
    ):
        raise ImportConfigurationError("import:csv_options")
    config = settings if settings is not None else Settings()
    engine: Engine | None = None
    try:
        if write:
            validate_local_target(config)
            engine = create_db_engine(config)
            with engine.connect() as connection, connection.begin():
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                check_local_database(connection)
        if from_snapshot is not None:
            collection = load_snapshot(from_snapshot, source)
        elif from_csv is not None and validation is not None:
            collection = load_validated_csv(from_csv, validation, source)
        else:
            if (
                config.data_go_kr_service_key is None
                or not config.data_go_kr_service_key.get_secret_value().strip()
            ):
                raise ImportConfigurationError("import:missing_key")
            with httpx.Client(
                timeout=httpx.Timeout(60.0, connect=5.0),
                follow_redirects=False,
                limits=httpx.Limits(max_connections=workers, max_keepalive_connections=workers),
            ) as transport:
                with LocalDataClient(
                    config.data_go_kr_service_key,
                    client=transport,
                    workers=workers,
                    max_requests=max_requests,
                    progress=progress,
                ) as client:
                    collection = client.collect(source)
        snapshot_path = save_snapshot(collection, ROOT / "datasets" / "localdata") if save else None
        batch_id = uuid4()
        transformed = transform_rows(
            source, collection.rows, batch_id=batch_id, today=collection.collected_at.date()
        )
        affected = 0
        if engine is not None:
            batch = import_batch(collection, batch_id)
            with engine.connect() as connection:
                affected = upsert_records(
                    connection,
                    source,
                    transformed.records,
                    before_write=check_local_database,
                    batch=batch,
                )
        report = asdict(transformed.report)
        update_types: Counter[str] = Counter()
        for value, count in transformed.report.update_types.items():
            update_types[value if re.fullmatch(r"[A-Z0-9]", value) else "other"] += count
        report["update_types"] = dict(update_types)
        return {
            "event": "result",
            "source": source.value,
            "mode": "write" if write else "dry_run",
            "batch_id": str(batch_id),
            "reference_date": collection.collected_at.date().isoformat(),
            "authorities": len(collection.authorities),
            "request_count": collection.request_count,
            "expected_pages": (
                sum(stat.page_count or 0 for stat in collection.authorities)
                if collection.input_kind == "api"
                else None
            ),
            "input_kind": collection.input_kind,
            "input_sha256_prefix": collection.input_sha256[:12]
            if collection.input_sha256
            else None,
            "as_of_basis": collection.as_of_basis,
            "affected": affected,
            "snapshot": snapshot_path.name if snapshot_path else None,
            **report,
        }
    finally:
        if engine is not None:
            engine.dispose()


def _progress(source: Source, authority: str, page: int, total: int) -> None:
    if authority == "all":
        print(
            json.dumps({"event": "plan", "source": source.value, "expected_pages": total}),
            flush=True,
        )
        return
    print(
        json.dumps(
            {
                "event": "collection",
                "source": source.value,
                "authority": authority,
                "page": page,
                "total_count": total,
            }
        ),
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect or import a complete Seoul source")
    parser.add_argument("--source", required=True, choices=[source.value for source in Source])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Write only to local spoton_dev")
    mode.add_argument("--dry-run", action="store_true", help="Default; never create a DB engine")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--from-snapshot", type=Path)
    inputs.add_argument("--from-csv", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--save-snapshot", action="store_true")
    args = parser.parse_args(argv)
    if args.from_snapshot is not None and args.save_snapshot:
        parser.error("--from-snapshot and --save-snapshot cannot be combined")
    if (
        args.from_csv is not None
        and (args.write or args.validation is None)
        or args.validation is not None
        and args.from_csv is None
    ):
        parser.error("--from-csv requires --validation and permits dry-run only")
    try:
        result = run_import(
            Source(args.source),
            write=args.write,
            workers=args.workers,
            from_snapshot=args.from_snapshot,
            from_csv=args.from_csv,
            validation=args.validation,
            save=args.save_snapshot,
            progress=_progress,
        )
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return 0
    except Exception as error:
        result = {"event": "error", "kind": type(error).__name__}
        if isinstance(
            error, LocalDataError | SnapshotError | ImportConfigurationError | CSVSourceError
        ):
            code = str(error).split(" ")[0]
            if re.fullmatch(r"[a-z_]+:[a-z_0-9]+", code):
                result["code"] = code
        print(json.dumps(result), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
