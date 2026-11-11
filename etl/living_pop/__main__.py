import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from app.core.config import Settings
from app.core.operations import etl_phase, logged_import
from app.db.session import create_db_engine
from etl.living_pop.data import PopulationImportError
from etl.living_pop.grid import prepare_grid
from etl.living_pop.input import load_input
from etl.living_pop.repository import inspect_import, limits, save
from etl.localdata.runner import check_local_database, validate_local_target


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise PopulationImportError("living_pop:arguments")


@logged_import("living_pop")
def run_import(
    path: Path, *, write: bool = False, settings: Settings | None = None
) -> dict[str, Any]:
    with etl_phase("read_source"):
        daily = load_input(path)
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    engine = create_db_engine(config)
    try:
        with etl_phase("prepare"), engine.connect() as c:
            c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            limits(c)
            check_local_database(c)
            grid = prepare_grid(c, daily.grid)
            _, existing = inspect_import(c, daily, grid)
            c.rollback()
        gid = None
        vid = None
        reused = False
        inserted_grids = 0
        if write:
            with etl_phase("persist"), engine.connect() as c, c.begin():
                check_local_database(c)
                gid, vid, reused, inserted_grids = save(c, daily, grid)
        return dict(
            mode="write" if write else "dry_run",
            observation_date=daily.manifest.day.isoformat(),
            grid_version_id=str(gid) if gid else None,
            version_id=str(vid) if vid else None,
            grid_rows=len(grid.rows),
            rows=len(daily.rows),
            inserted=len(daily.rows) if write and not reused else 0,
            inserted_grids=inserted_grids,
            reused=reused,
            would_reuse=existing is not None,
            grid_as_of=None,
            spatial_compatibility="unverified",
            unlocated_scope="source_date_all_admin_rows",
            sources={
                s: {k: m[k] for k in ("rows", "statuses", "unlocated_rows", "unlocated_grids")}
                for s, m in daily.sources.items()
            },
        )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    p = SafeParser(description="Import verified daily 250m population files")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--write", action="store_true")
    try:
        args = p.parse_args(argv)
        print(json.dumps(run_import(args.manifest, write=args.write)), flush=True)
        return 0
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, PopulationImportError)
            else "living_pop:operation_failed"
        )
        print(json.dumps({"error": code}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
