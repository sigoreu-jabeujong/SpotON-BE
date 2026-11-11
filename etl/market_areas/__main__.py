import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

from app.core.config import Settings
from app.core.operations import etl_phase, logged_import
from app.db.session import create_db_engine
from etl.localdata.runner import check_local_database, validate_local_target
from etl.market_areas.archive import MarketImportError, load_archive
from etl.market_areas.geometry import prepare
from etl.market_areas.repository import save


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise MarketImportError("market:arguments")


@logged_import("market_areas")
def run_import(
    path: Path,
    expected_sha256: str,
    source_file_date: date,
    *,
    write: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    with etl_phase("read_source"):
        archive = load_archive(path, expected_sha256, source_file_date)
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    engine = create_db_engine(config)
    try:
        with etl_phase("prepare"), engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            check_local_database(connection)
            prepared = prepare(connection, archive)
            connection.rollback()
        version = None
        reused = False
        if write:
            with etl_phase("persist"), engine.connect() as connection, connection.begin():
                check_local_database(connection)
                version, reused = save(connection, prepared)
        return {
            "mode": "write" if write else "dry_run",
            "rows": len(prepared.areas),
            "repaired": sum(a.geometry_repaired for a in prepared.areas),
            "input_sha256_prefix": archive.input_sha256[:12],
            "version_id": str(version) if version is not None else None,
            "reused": reused,
            "inserted": len(prepared.areas) if write and not reused else 0,
            "boundary_as_of": None,
        }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Import a verified local OA-15560 boundary ZIP")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-file-date", required=True, type=date.fromisoformat)
    parser.add_argument("--write", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = run_import(args.zip, args.expected_sha256, args.source_file_date, write=args.write)
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, MarketImportError) else "market:operation_failed"
        print(json.dumps({"error": reason}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
