import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from app.core.config import Settings
from app.core.operations import etl_phase, logged_import
from app.db.session import create_db_engine
from etl.localdata.runner import check_local_database, validate_local_target
from etl.market_stores.archive import StatsImportError, load_archive
from etl.market_stores.repository import check_boundary, save, set_limits


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise StatsImportError("market_stats:arguments")


@logged_import("market_stores")
def run_import(
    path: Path,
    expected_sha256: str,
    source_year: int,
    source_file_date: date,
    boundary_id: UUID,
    *,
    write: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    with etl_phase("read_source"):
        archive = load_archive(path, expected_sha256, source_year, source_file_date)
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    engine = create_db_engine(config)
    try:
        with etl_phase("prepare"), engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            set_limits(connection)
            check_local_database(connection)
            report = check_boundary(connection, archive, boundary_id)
            connection.rollback()
        version = None
        reused = False
        if write:
            with etl_phase("persist"), engine.connect() as connection, connection.begin():
                check_local_database(connection)
                version, reused, report = save(connection, archive, boundary_id)
        return dict(
            mode="write" if write else "dry_run",
            source_rows=archive.source_rows,
            rows=len(archive.rows),
            excluded_rows=archive.source_rows - len(archive.rows),
            version_id=str(version) if version is not None else None,
            reused=reused,
            inserted=len(archive.rows) if write and not reused else 0,
            boundary_compatibility="unverified",
            code_check=report,
        )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Import a verified local OA-15577 annual ZIP")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-year", required=True, type=int)
    parser.add_argument("--source-file-date", required=True, type=date.fromisoformat)
    parser.add_argument("--code-check-boundary-version", required=True, type=UUID)
    parser.add_argument("--write", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = run_import(
            args.zip,
            args.expected_sha256,
            args.source_year,
            args.source_file_date,
            args.code_check_boundary_version,
            write=args.write,
        )
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        reason = (
            str(error) if isinstance(error, StatsImportError) else "market_stats:operation_failed"
        )
        print(json.dumps({"error": reason}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
