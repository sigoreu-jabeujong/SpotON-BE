"""One-shot scheduler entry point. Preview is local-only; execute is at-least-once."""

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from etl.operation_logs import archive, render
from etl.operation_logs import job_state as control
from etl.operation_logs.__main__ import ArgumentsError, SafeParser
from etl.operation_logs.validation import epoch_us


def stamp(ns: int) -> str:
    seconds, fraction = divmod(ns, 10**9)
    value = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    return value.isoformat(timespec="seconds").removesuffix("+00:00") + f".{fraction:09d}Z"


def ids(owner: str, service: str) -> None:
    if not render.OWNER.fullmatch(owner) or not render.SERVICE.fullmatch(service):
        raise ArgumentsError


def plan(value: control.State, safe_end: int) -> list[tuple[int, int]]:
    if value.cursor_ns > safe_end:
        raise control.JobError("clock_behind_checkpoint")
    cursor = value.cursor_ns
    windows: list[tuple[int, int]] = []
    while cursor < safe_end and len(windows) < control.MAX_WINDOWS:
        end = min(cursor + control.WINDOW_NS, safe_end)
        windows.append((max(value.initial_ns, cursor - control.OVERLAP_NS), end))
        cursor = end
    if not windows and cursor > value.initial_ns:
        windows.append((max(value.initial_ns, cursor - control.OVERLAP_NS), cursor))
    return windows


@dataclass
class Result:
    status: str = "ok"
    error: str | None = None
    phase: str = "state"
    failed_window_start: str | None = None
    job_rule_version: str = control.RULE
    coverage_verified: bool = False
    mode: str = "dry_run"
    created: int = 0
    would_create: int = 0
    cursor_before: str | None = None
    last_confirmed_until: str | None = None
    proposed_until: str | None = None
    planned_windows: int = 0
    successful_windows: int = 0
    collector_invocations: int = 0
    inserted: int = 0
    duplicate: int = 0
    api_rows: int = 0
    rejected_messages: int = 0
    prune_deleted: int = 0
    prune_would_delete: int = 0
    prune_completed: bool = False
    checkpoint_committed: bool = False
    lag_seconds_after: int | None = None
    remaining_windows: int | None = None
    effects_may_be_partial: bool = False


def _check(path: Path, owner: str, service: str, value: control.State) -> None:
    if control.binding(path, owner, service, value.initial_ns) != value.binding:
        raise control.JobError("binding_mismatch")


def _lag(result: Result, safe_end: int, cursor: int) -> None:
    difference = max(0, safe_end - cursor)
    result.lag_seconds_after = (difference + 10**9 - 1) // 10**9
    result.remaining_windows = (difference + control.WINDOW_NS - 1) // control.WINDOW_NS


def initialize(
    path: Path,
    state: Path,
    owner: str,
    service: str,
    start: str,
    now: datetime,
    *,
    execute: bool = False,
) -> Result:
    ids(owner, service)
    if path.resolve() == state.resolve():
        raise control.JobError("same_file")
    try:
        initial = render.nanoseconds(start)
    except render.RenderLogError:
        raise ArgumentsError from None
    now_ns = epoch_us(now) * 1000
    safe_end = (now_ns - control.LAG_NS) // control.WINDOW_NS * control.WINDOW_NS
    if not max(0, now_ns - 30 * control.DAY_NS) < initial <= safe_end:
        raise ArgumentsError
    value = control.State(control.binding(path, owner, service, initial), initial, initial)
    control.initialize(state, value, execute=execute)
    return Result(
        phase="completed",
        mode="execute" if execute else "dry_run",
        created=int(execute),
        would_create=1,
        cursor_before=stamp(initial),
        last_confirmed_until=stamp(initial),
        proposed_until=stamp(initial),
    )


def _collect_counts(result: Result, fetched: dict[str, Any]) -> None:
    if (
        fetched.get("api_window_complete") is not True
        or fetched.get("coverage_verified") is not False
    ):
        raise control.JobError("collector_contract")
    for target, source in [
        ("api_rows", fetched),
        ("rejected_messages", fetched),
        ("inserted", fetched.get("archive")),
        ("duplicate", fetched.get("archive")),
    ]:
        if type(source) is not dict or type(source.get(target)) is not int or source[target] < 0:
            raise control.JobError("collector_contract")
    result.api_rows += fetched["api_rows"]
    result.rejected_messages += fetched["rejected_messages"]
    result.inserted += fetched["archive"]["inserted"]
    result.duplicate += fetched["archive"]["duplicate"]
    result.successful_windows += 1


def _process(
    c: sqlite3.Connection | None,
    path: Path,
    owner: str,
    service: str,
    key: SecretStr,
    value: control.State,
    now: datetime,
    execute: bool,
    result: Result,
) -> None:
    result.phase = "validation"
    _check(path, owner, service, value)
    now_ns = epoch_us(now) * 1000
    safe_end = (now_ns - control.LAG_NS) // control.WINDOW_NS * control.WINDOW_NS
    windows = plan(value, safe_end)
    result.cursor_before = result.last_confirmed_until = stamp(value.cursor_ns)
    result.proposed_until = result.cursor_before
    _lag(result, safe_end, value.cursor_ns)
    result.phase = "prune"
    pruned = archive.prune(path, now, execute=execute)
    result.prune_deleted = pruned["deleted"]
    result.prune_would_delete = pruned["would_delete"]
    result.prune_completed = True
    if value.cursor_ns <= now_ns - 30 * control.DAY_NS:
        raise control.JobError("checkpoint_expired")
    result.planned_windows = len(windows)
    if not execute:
        result.proposed_until = stamp(windows[-1][1] if windows else value.cursor_ns)
        result.phase = "preview"
        return
    cursor = value.cursor_ns
    for start, end in windows:
        _check(path, owner, service, value)
        result.phase = "collect"
        result.failed_window_start = stamp(start)
        result.collector_invocations += 1
        try:
            fetched = render.run_window(
                path, owner, service, stamp(start), stamp(end), key, execute=True
            )
        except ArgumentsError:
            # Arguments were checked before prune. A later clock change is a runtime failure.
            raise control.JobError("collector_window") from None
        except render.RenderLogError as exc:
            result.status = "failed"
            result.error = str(exc)
            break
        except httpx.RequestError:
            result.status = "failed"
            result.error = "api_network"
            break
        except archive.ArchiveError as exc:
            if str(exc) != "database_busy":
                raise
            result.status = "failed"
            result.error = "archive_busy"
            break
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", 0) & 255 not in (5, 6):
                raise
            result.status = "failed"
            result.error = "archive_busy"
            break
        _collect_counts(result, fetched)
        result.failed_window_start = None
        cursor = max(cursor, end)
        result.proposed_until = stamp(cursor)
    _check(path, owner, service, value)
    if cursor > value.cursor_ns:
        if c is None:
            raise control.JobError("state_transaction")
        result.phase = "checkpoint"
        control.save(c, value, cursor)
        c.commit()
        result.checkpoint_committed = True
        result.last_confirmed_until = stamp(cursor)
        _lag(result, safe_end, cursor)
    result.phase = "completed" if result.status == "ok" else "collect"


def run_once(
    path: Path,
    state: Path,
    owner: str,
    service: str,
    key: SecretStr,
    now: datetime,
    *,
    execute: bool = False,
) -> Result:
    result = Result(mode="execute" if execute else "dry_run")
    try:
        ids(owner, service)
        if path.resolve() == state.resolve():
            raise control.JobError("same_file")
        if execute:
            with control.connect(state, write=True) as c:
                _process(c, path, owner, service, key, control.load(c), now, True, result)
        else:
            with control.connect(state) as c:
                value = control.load(c)
            _process(None, path, owner, service, key, value, now, False, result)
    except ArgumentsError:
        raise
    except (control.JobError, archive.ArchiveError, render.RenderLogError) as exc:
        result.status = "failed"
        result.error = str(exc)
    except sqlite3.Error as exc:
        result.status = "failed"
        result.error = "database"
        if getattr(exc, "sqlite_errorcode", 0) & 255 in (5, 6):
            result.error = (
                "state_busy" if result.phase in {"state", "checkpoint"} else "archive_busy"
            )
    except KeyboardInterrupt:
        result.status = "interrupted"
        result.error = "interrupted"
    except Exception:
        result.status = "failed"
        result.error = "operation_failed"
    result.effects_may_be_partial = (
        execute
        and result.status != "ok"
        and (result.prune_completed or result.collector_invocations > 0)
    )
    return result


def main(argv: list[str] | None = None) -> int:
    result = Result()
    code = 0
    try:
        parser = SafeParser(prog="python -m etl.operation_logs.job", allow_abbrev=False)
        commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
        for name in ("init", "run"):
            sub = commands.add_parser(name, allow_abbrev=False)
            for option in ("db", "state", "owner-id", "service-id"):
                sub.add_argument(
                    "--" + option, required=True, type=Path if option in ("db", "state") else str
                )
            if name == "init":
                sub.add_argument("--start", required=True)
            sub.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        result.mode = "execute" if args.execute else "dry_run"
        now = datetime.now(UTC)
        if args.command == "init":
            result = initialize(
                args.db,
                args.state,
                args.owner_id,
                args.service_id,
                args.start,
                now,
                execute=args.execute,
            )
        else:
            result = run_once(
                args.db,
                args.state,
                args.owner_id,
                args.service_id,
                SecretStr(os.environ.get("RENDER_API_KEY", "")),
                now,
                execute=args.execute,
            )
        code = 0 if result.status == "ok" else 130 if result.status == "interrupted" else 1
    except ArgumentsError:
        result.status = "failed"
        result.error = "arguments"
        code = 2
    except (control.JobError, archive.ArchiveError) as exc:
        result.status = "failed"
        result.error = str(exc)
        code = 1
    except KeyboardInterrupt:
        result.status = "interrupted"
        result.error = "interrupted"
        code = 130
    except Exception:
        result.status = "failed"
        result.error = "operation_failed"
        code = 1
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
