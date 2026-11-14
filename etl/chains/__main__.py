import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.operations import etl_phase, logged_import
from etl.chains.common import ChainsError, digest, external_path, fail, save_new
from etl.chains.compare import compare_local
from etl.chains.registry import load_registry
from etl.chains.semas import MAX_BYTES, collect
from etl.chains.snapshot import load_snapshot, save_snapshot
from etl.localdata.runner import SafeParser


@logged_import("brands")
def run(
    *,
    collect_semas: bool = False,
    snapshot: Path | None = None,
    output: Path | None = None,
    registry: Path | None = None,
    plan_output: Path | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if collect_semas:
        if (
            output is None
            or snapshot is not None
            or plan_output is not None
            or registry is not None
        ):
            fail("arguments")
        target = external_path(output)
        if target.exists():
            fail("output_exists")
        cfg = settings if settings is not None else Settings()
        with etl_phase("collect"):
            collected = collect(cfg.data_go_kr_service_key)
        with etl_phase("save_snapshot"):
            save_snapshot(output, collected)
        return dict(
            mode="collect_semas",
            rows=len(collected.rows),
            snapshot_saved=True,
            reference_month=collected.reference_month,
            observed_at=collected.observed_at.isoformat(),
            content_sha256=collected.content_sha256,
            request_count=collected.request_count,
        )
    if output is not None:
        fail("arguments")
    if plan_output is not None:
        if external_path(plan_output).exists():
            fail("output_exists")
    with etl_phase("read_source"):
        brands = load_registry(registry)
        data = load_snapshot(snapshot) if snapshot is not None else None
    with etl_phase("prepare"):
        summary, plan = compare_local(
            settings if settings is not None else Settings(), brands, data
        )
    if plan_output is not None:
        save_new(
            plan_output,
            dict(
                schema="chain-evidence-plan-v1",
                summary=summary,
                rows=plan,
                content_sha256=digest(plan),
            ),
            MAX_BYTES,
        )
    return dict(mode="read_only_compare", plan_saved=plan_output is not None, **summary)


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Offline chain membership evidence; no legacy/DB writes")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect-semas", action="store_true")
    mode.add_argument("--compare-local", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--plan-output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(
            collect_semas=args.collect_semas,
            snapshot=args.snapshot,
            output=args.output,
            registry=args.registry,
            plan_output=args.plan_output,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except ChainsError as error:
        print(json.dumps(dict(error=str(error))), flush=True)
        return 1
    except KeyboardInterrupt:
        print(json.dumps(dict(error="chains:cancelled")), flush=True)
        return 130
    except Exception:
        print(json.dumps(dict(error="chains:operation_failed")), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
