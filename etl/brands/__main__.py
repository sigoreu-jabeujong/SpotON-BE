import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from app.core.config import Settings
from app.core.operations import Stage, etl_phase, logged_import
from etl.brands.catalog import BrandsError, fail
from etl.brands.client import collect
from etl.brands.compare import compare_local as compare_catalog
from etl.brands.snapshot import external_path, load_snapshot, save_snapshot


class RunFailure(BrandsError):
    def __init__(self, code: str, stage: Stage, saved: bool) -> None:
        super().__init__(code)
        self.stage = stage
        self.snapshot_saved = saved


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "invalid arguments\n")


@logged_import("brands")
def run_import(
    *,
    year: int | None = None,
    output: Path | None = None,
    snapshot: Path | None = None,
    compare_local: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    stage: Stage = "preflight"
    saved = False
    try:
        if (snapshot is None) == (year is None) or (year is None) != (output is None):
            fail("arguments")
        if output is not None:
            external_path(output)
            if output.exists():
                fail("output_exists")
        config = settings
        requests = 0
        if snapshot is not None:
            stage = "read_source"
            with etl_phase(stage):
                catalog = load_snapshot(snapshot)
        else:
            stage = "collect"
            with etl_phase(stage):
                config = config if config is not None else Settings()
                assert year is not None and output is not None
                catalog = collect(year, config.data_go_kr_service_key)
                requests = len(catalog.pages) + 1
            stage = "save_snapshot"
            with etl_phase(stage):
                save_snapshot(output, catalog)
                saved = True
        comparison = None
        if compare_local:
            stage = "prepare"
            with etl_phase(stage):
                config = config if config is not None else Settings()
                comparison = compare_catalog(catalog, config)
        return dict(
            mode="snapshot_replay" if snapshot else "collect_api",
            compare_local=compare_local,
            snapshot_saved=saved,
            request_count=requests,
            classification_status="pending",
            comparison=comparison,
            **catalog.summary(),
        )
    except Exception as error:
        code = str(error) if type(error) is BrandsError else "brands:operation_failed"
        raise RunFailure(code, stage, saved) from None


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Collect FTC brands or replay a verified local snapshot")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year", type=int)
    group.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-local", action="store_true")
    args = parser.parse_args(argv)
    if (args.year is None) != (args.output is None):
        parser.error("output mode")
    try:
        result = run_import(
            year=args.year,
            output=args.output,
            snapshot=args.snapshot,
            compare_local=args.compare_local,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except RunFailure as error:
        print(
            json.dumps(
                dict(error=str(error), stage=error.stage, snapshot_saved=error.snapshot_saved)
            ),
            flush=True,
        )
        return 1
    except KeyboardInterrupt:
        print(json.dumps(dict(error="brands:cancelled")), flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
