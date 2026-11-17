"""Explicit local maintenance after a committed import; dry-run is read only."""

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, NoReturn

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import DatabaseConfigurationError, create_db_engine
from app.services.store_cohort import current_provenance
from etl.localdata.runner import (
    ImportConfigurationError,
    check_local_database,
    validate_local_target,
)

VACUUM_SQL = "VACUUM (ANALYZE, TRUNCATE FALSE) public.stores"
MAINTENANCE_TIMEOUT = "60s"
LOCK_TIMEOUT = "5s"
Phase = Literal["arguments", "preflight", "vacuum", "provenance", "cleanup", "completed"]
Failure = Literal[
    "arguments",
    "configuration",
    "ownership",
    "database",
    "vacuum",
    "provenance",
    "cleanup",
    "interrupted",
    "operation_failed",
]


@dataclass
class MaintenanceResult:
    mode: Literal["dry_run", "execute"] = "dry_run"
    operation: Literal["vacuum_analyze_stores"] = "vacuum_analyze_stores"
    phase: Phase = "preflight"
    vacuum_completed: bool = False
    provenance_checked: bool = False
    batch_count: int | None = None
    reference_date: date | None = None
    error: Failure | None = None


class OwnershipError(ValueError):
    pass


class ArgumentsError(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ArgumentsError


@contextmanager
def _read_session(engine: Engine, timeout_ms: int) -> Iterator[Session]:
    # Preserve raw DB exceptions so a SQL failure is distinct from invalid provenance.
    with Session(engine) as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{timeout_ms}ms"},
        )
        yield session


def _check_target(connection: Connection) -> None:
    check_local_database(connection)
    owned = connection.scalar(
        text(
            "SELECT c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
            "AND 'stores'::regclass='public.stores'::regclass "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname='stores' AND c.relkind='r'"
        )
    )
    if owned is not True:
        raise OwnershipError


def _vacuum(engine: Engine) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(
            text("SELECT set_config('lock_timeout', :timeout, false)"), {"timeout": LOCK_TIMEOUT}
        )
        connection.execute(
            text("SELECT set_config('statement_timeout', :timeout, false)"),
            {"timeout": MAINTENANCE_TIMEOUT},
        )
        _check_target(connection)
        connection.execute(text(VACUUM_SQL))


def run_maintenance(
    *, execute: bool = False, settings: Settings | None = None
) -> MaintenanceResult:
    result = MaintenanceResult(mode="execute" if execute else "dry_run")
    engine: Engine | None = None
    try:
        if type(execute) is not bool:
            raise ArgumentsError
        config = settings if settings is not None else Settings()
        validate_local_target(config)
        engine = create_db_engine(config)
        with _read_session(engine, config.database_statement_timeout_ms) as session:
            _check_target(session.connection())
        if execute:
            result.phase = "vacuum"
            _vacuum(engine)
            result.vacuum_completed = True
            result.phase = "provenance"
            with _read_session(engine, config.database_statement_timeout_ms) as session:
                batches, reference = current_provenance(session)
                result.batch_count = len(batches)
                result.reference_date = reference
            result.provenance_checked = True
        result.phase = "completed"
    except ArgumentsError:
        result.error = "arguments"
    except (ImportConfigurationError, DatabaseConfigurationError, ValidationError):
        result.error = "configuration"
    except OwnershipError:
        result.error = "ownership"
    except AppError:
        result.error = "provenance" if result.phase == "provenance" else "operation_failed"
    except SQLAlchemyError:
        result.error = "vacuum" if result.phase == "vacuum" else "database"
    except KeyboardInterrupt:
        result.error = "interrupted"
    except Exception:
        result.error = "operation_failed"
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                if result.error is None:
                    result.phase = "cleanup"
                    result.error = "cleanup"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(
        description="Local stores maintenance; pause reads and writers first", allow_abbrev=False
    )
    parser.add_argument(
        "--execute", action="store_true", help="run maintenance; default only checks"
    )
    try:
        args = parser.parse_args(argv)
    except ArgumentsError:
        result = MaintenanceResult(phase="arguments", error="arguments")
    else:
        result = run_maintenance(execute=args.execute)
    payload = asdict(result)
    payload["reference_date"] = (
        result.reference_date.isoformat() if result.reference_date is not None else None
    )
    payload["error"] = "localdata_maintenance:" + result.error if result.error else None
    print(json.dumps(payload, allow_nan=False, separators=(",", ":")), flush=True)
    return 130 if result.error == "interrupted" else int(result.error is not None)


if __name__ == "__main__":
    sys.exit(main())
