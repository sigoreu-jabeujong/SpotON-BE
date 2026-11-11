import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from app.core.config import Settings
from app.db.session import create_db_engine
from etl.localdata.runner import check_local_database, validate_local_target
from etl.market_changes.repository import inspect_import, same_content_versions, save, set_limits
from etl.market_changes.source import ChangeImportError, load_source


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ChangeImportError("market_changes:arguments")


def run_import(
    path: Path,
    expected_sha256: str,
    source_year: int,
    retrieved_at: datetime,
    boundary_id: UUID,
    *,
    write: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    source = load_source(path, expected_sha256, source_year, retrieved_at)
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    engine = create_db_engine(config)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            set_limits(connection)
            check_local_database(connection)
            expected, existing = inspect_import(connection, source, boundary_id)
            equivalent = same_content_versions(connection, source)
            report = expected["code_check"]
            connection.rollback()
        version = None
        reused = False
        if write:
            with engine.connect() as connection, connection.begin():
                check_local_database(connection)
                version, reused, report = save(connection, source, boundary_id)
        return dict(
            mode="write" if write else "dry_run",
            source_year=source_year,
            source_rows=source.source_rows,
            rows=len(source.rows),
            excluded_rows=source.source_rows - len(source.rows),
            excluded_scope="outside_selected_year",
            quarter_rows=source.quarter_rows,
            version_id=str(version) if version else None,
            reused=reused,
            inserted=len(source.rows) if write and not reused else 0,
            would_reuse=existing is not None,
            same_content_versions_before=equivalent,
            boundary_compatibility="unverified",
            source_file_date=None,
            code_check=report,
        )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Import a verified local OA-15576 full CSV export")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-year", required=True, type=int)
    parser.add_argument("--retrieved-at", required=True, type=datetime.fromisoformat)
    parser.add_argument("--code-check-boundary-version", required=True, type=UUID)
    parser.add_argument("--write", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = run_import(
            args.csv,
            args.expected_sha256,
            args.source_year,
            args.retrieved_at,
            args.code_check_boundary_version,
            write=args.write,
        )
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        reason = (
            str(error)
            if isinstance(error, ChangeImportError)
            else "market_changes:operation_failed"
        )
        print(json.dumps({"error": reason}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
