"""Explicit archive CLI. stdout is a count-only result; stderr remains empty."""

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, NoReturn

from etl.operation_logs.archive import (
    RETENTION_DAYS,
    RULE_VERSION,
    ArchiveError,
    ingest,
    initialize,
    prune,
    status,
)


class ArgumentsError(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ArgumentsError


def main(argv: list[str] | None = None, *, stdin: BinaryIO | None = None) -> int:
    result: dict[str, object] = {"rule_version": RULE_VERSION, "retention_days": RETENTION_DAYS}
    code = 0
    try:
        parser = SafeParser(prog="python -m etl.operation_logs", allow_abbrev=False)
        commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
        for name in ("init", "ingest", "status", "prune"):
            sub = commands.add_parser(name, allow_abbrev=False)
            sub.add_argument("--db", required=True, type=Path)
            if name != "status":
                sub.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        execute = getattr(args, "execute", False)
        result.update(command=args.command, mode="execute" if execute else "dry_run")
        now = datetime.now(UTC)
        if args.command == "init":
            result.update(initialize(args.db, execute=execute))
        elif args.command == "ingest":
            result.update(
                ingest(args.db, stdin if stdin is not None else sys.stdin.buffer, execute=execute)
            )
        elif args.command == "prune":
            result.update(prune(args.db, now, execute=execute))
        else:
            result.update(status(args.db, now))
        result["status"] = "ok"
    except ArgumentsError:
        result.update(status="failed", error="arguments")
        code = 2
    except ArchiveError as exc:
        result.update(status="failed", error=str(exc))
        code = 1
    except KeyboardInterrupt:
        result.update(status="failed", error="interrupted")
        code = 130
    except sqlite3.Error as exc:
        reason = (
            "database_busy"
            if getattr(exc, "sqlite_errorcode", 0) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            else "database"
        )
        result.update(status="failed", error=reason)
        code = 1
    except Exception:
        result.update(status="failed", error="operation_failed")
        code = 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
