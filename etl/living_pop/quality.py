"""Explicit local, read-only stored-row diagnostic; no population values returned."""

import argparse
import json
import sys
from typing import NoReturn
from uuid import UUID

from pydantic import ValidationError

from app.analysis.population_quality import QualityError, QualityQuery, QualityReport, diagnose
from app.core.config import Settings
from app.core.errors import AppError
from app.db.dependencies import DatabaseResources, read_only_session
from etl.localdata.runner import (
    ImportConfigurationError,
    check_local_database,
    validate_local_target,
)


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise QualityError("arguments")


def run_diagnostic(query: QualityQuery, *, settings: Settings | None = None) -> QualityReport:
    config = settings if settings is not None else Settings()
    validate_local_target(config)
    resources = DatabaseResources(config)
    try:
        with read_only_session(resources) as session:
            check_local_database(session.connection())
            return diagnose(session, query)
    finally:
        resources.close()


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description="Count stored row states in an explicit observation version")
    parser.add_argument("--population-version", required=True, type=UUID)
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lng", required=True, type=float)
    parser.add_argument("--radius", type=int, choices=(300, 500, 1000), default=500)
    try:
        args = parser.parse_args(argv)
        query = QualityQuery(
            observation_version_id=args.population_version,
            lat=args.lat,
            lng=args.lng,
            radius=args.radius,
        )
        print(run_diagnostic(query).model_dump_json(), flush=True)
        return 0
    except (QualityError, ValidationError) as error:
        code = (
            str(error)
            if str(error)
            in {
                "living_pop_quality:version",
                "living_pop_quality:counts",
            }
            else "living_pop_quality:arguments"
        )
    except ImportConfigurationError:
        code = "living_pop_quality:configuration"
    except AppError:
        code = "living_pop_quality:database"
    except Exception:
        code = "living_pop_quality:operation_failed"
    print(json.dumps({"error": code}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
