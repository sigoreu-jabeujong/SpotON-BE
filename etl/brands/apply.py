"""Apply immutable estimate evidence, never UPDATE stores. Default: read-only plan."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from sqlalchemy import text

from app.core.config import Settings
from app.core.operations import Stage, etl_phase, logged_import
from app.db.session import create_db_engine
from app.models.brand import MAPPING_RULE
from etl.brands.assignment import limits, plan, save
from etl.brands.catalog import BrandsError
from etl.brands.snapshot import read_snapshot
from etl.localdata.runner import check_local_database, validate_local_target


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "invalid arguments\n")


@logged_import("brands")
def run_apply(
    path: Path, *, write: bool = False, settings: Settings | None = None
) -> dict[str, Any]:
    with etl_phase("read_source"):
        catalog, input_hash = read_snapshot(path)
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    engine = create_db_engine(config)
    try:
        stage: Stage = "persist" if write else "prepare"
        with etl_phase(stage), engine.connect() as c, c.begin():
            if not write:
                c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            else:
                c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            limits(c)
            if write:
                c.execute(text("SELECT pg_advisory_xact_lock(1397772116,21)"))
            check_local_database(c)
            prepared = plan(c, catalog)
            result = save(c, catalog, input_hash, prepared) if write else {}
        return dict(
            mode="write" if write else "dry_run",
            reference_year=catalog.year,
            rule_version=MAPPING_RULE,
            catalog_content_sha256=catalog.content_sha256,
            store_input_sha256=prepared.input_sha256,
            rows=prepared.counts["total"],
            matched=len(prepared.targets),
            counts=prepared.counts,
            **result,
        )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Plan or apply versioned exact-name franchise estimates")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(run_apply(args.snapshot, write=args.write), ensure_ascii=False), flush=True
        )
        return 0
    except Exception as error:
        code = str(error) if type(error) is BrandsError else "brands:operation_failed"
        print(json.dumps({"error": code}), flush=True)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"error": "brands:cancelled"}), flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
