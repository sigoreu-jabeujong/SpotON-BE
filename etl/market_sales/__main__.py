import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from app.core.config import Settings
from app.db.session import create_db_engine
from etl.localdata.runner import check_local_database, validate_local_target
from etl.market_sales.archive import SalesImportError, load_archive
from etl.market_sales.repository import inspect_import, save, set_limits


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise SalesImportError("market_sales:arguments")


def run_import(
    path: Path,
    expected_sha256: str,
    source_year: int,
    source_file_date: date,
    boundary_id: UUID,
    store_id: UUID,
    *,
    write: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    archive = load_archive(path, expected_sha256, source_year, source_file_date)
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    engine = create_db_engine(config)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            set_limits(connection)
            check_local_database(connection)
            expected, existing = inspect_import(connection, archive, boundary_id, store_id)
            report = expected["code_check"]
            connection.rollback()
        version = None
        reused = False
        if write:
            with engine.connect() as connection, connection.begin():
                check_local_database(connection)
                version, reused, report = save(connection, archive, boundary_id, store_id)
        return dict(
            mode="write" if write else "dry_run",
            source_rows=archive.source_rows,
            rows=len(archive.rows),
            excluded_rows=archive.source_rows - len(archive.rows),
            version_id=str(version) if version is not None else None,
            reused=reused,
            inserted=len(archive.rows) if write and not reused else 0,
            boundary_compatibility="unverified",
            amount_period_status="unverified",
            currency="KRW",
            amount_basis="source_reported",
            would_reuse=existing is not None,
            code_check=report,
        )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Import a verified local OA-15572 annual ZIP")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-year", required=True, type=int)
    parser.add_argument("--source-file-date", required=True, type=date.fromisoformat)
    parser.add_argument("--code-check-boundary-version", required=True, type=UUID)
    parser.add_argument("--code-check-store-version", required=True, type=UUID)
    parser.add_argument("--write", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = run_import(
            args.zip,
            args.expected_sha256,
            args.source_year,
            args.source_file_date,
            args.code_check_boundary_version,
            args.code_check_store_version,
            write=args.write,
        )
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        reason = (
            str(error) if isinstance(error, SalesImportError) else "market_sales:operation_failed"
        )
        print(json.dumps({"error": reason}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
