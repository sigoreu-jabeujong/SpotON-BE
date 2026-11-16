"""Inspect already-downloaded official sources, without credentials or DB access."""

import argparse
import json
from datetime import date
from pathlib import Path

from etl.admin_population.source import inspect_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="행정동 인구·경계 ZIP 읽기 전용 대조")
    parser.add_argument("--population-zip", type=Path, required=True)
    parser.add_argument("--population-sha256", required=True)
    parser.add_argument("--boundary-zip", type=Path, required=True)
    parser.add_argument("--boundary-sha256", required=True)
    parser.add_argument("--observation-date", type=date.fromisoformat)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--quarantine", type=Path)
    args = parser.parse_args()
    try:
        if args.write and args.observation_date is None:
            raise ValueError("observation date required")
        if args.observation_date is not None:
            from etl.admin_population.runner import run_import

            report = run_import(
                args.population_zip,
                args.population_sha256,
                args.boundary_zip,
                args.boundary_sha256,
                args.observation_date,
                write=args.write,
                quarantine=args.quarantine,
            )
            print(json.dumps(report, ensure_ascii=True))
            return 0
        report = inspect_sources(
            args.population_zip,
            args.population_sha256,
            args.boundary_zip,
            args.boundary_sha256,
        )
    except Exception:
        print(
            json.dumps({"status": "failed", "reason": "invalid_source", "database_access": False})
        )
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
