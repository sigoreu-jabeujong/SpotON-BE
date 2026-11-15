"""Keyless logical backup/expiry/restore CLI. All writes require explicit execution."""

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etl.operation_logs import archive, job
from etl.operation_logs import backup_store as store
from etl.operation_logs import job_state as control
from etl.operation_logs.__main__ import ArgumentsError, SafeParser
from etl.operation_logs.validation import Rejected, _constant, _pairs, epoch_us


@dataclass
class Result:
    status: str = "ok"
    error: str | None = None
    command: str = ""
    phase: str = "validation"
    mode: str = "dry_run"
    rule_version: str = store.RULE
    coverage_verified: bool = False
    created: int = 0
    would_create: int = 0
    backup_prune_committed: bool = False
    prune_deleted: int = 0
    prune_would_delete: int = 0
    generation_committed: bool = False
    rows_captured: int = 0
    rows_would_capture: int = 0
    source_rows_current: int | None = None
    source_rows_skipped_expired: int = 0
    generations_after: int = 0
    rows: int = 0
    latest_rows: int = 0
    latest_bytes: int = 0
    near_capture_limit: bool = False
    expired: int = 0
    captured_at: str | None = None
    last_confirmed_until: str | None = None
    sequence: int | None = None
    generation: str = "latest"
    archive_created: int = 0
    state_created: int = 0
    rows_restored: int = 0
    rows_would_restore: int = 0
    rows_skipped_expired: int = 0
    created_files_removed: int = 0
    orphan_files: int = 0
    integrity_verified: bool = False
    effects_may_be_partial: bool = False
    commit_outcome_unknown: bool = False
    capture_limit_rows: int = field(default_factory=lambda: store.MAX_ROWS)
    capture_limit_bytes: int = field(default_factory=lambda: store.MAX_BYTES)


def distinct(paths: list[Path]) -> None:
    for path in paths:
        archive.validate_file_path(path, syntax_only=True)
    if len({p.resolve() for p in paths}) != len(paths):
        raise store.BackupError("same_file")
    identities = []
    for path in paths:
        if path.exists():
            identities.append(archive._identity(path))
    if len(set(identities)) != len(identities):
        raise store.BackupError("same_file")


def summarize(value: store.Snapshot, now_us: int, result: Result) -> None:
    result.integrity_verified = True
    result.generations_after = len(value.generations)
    result.rows = sum(len(rows) for rows in value.records.values())
    result.expired = sum(
        item.event_us <= now_us - archive.RETENTION_US
        for rows in value.records.values()
        for item in rows
    )
    if value.active is not None:
        active = value.generations[value.active]
        result.latest_rows = active.row_count
        result.latest_bytes = sum(
            len(r.record.encode("utf-8")) for r in value.records[value.active]
        )
        result.near_capture_limit = (
            result.latest_rows * 10 >= store.MAX_ROWS * 9
            or result.latest_bytes * 10 >= store.MAX_BYTES * 9
        )
        result.captured_at = job.stamp(active.captured_us * 1000)
        result.last_confirmed_until = job.stamp(active.cursor_ns)
        result.sequence = active.sequence


def commit(c: sqlite3.Connection, result: Result, field: str) -> None:
    result.commit_outcome_unknown = True
    c.commit()
    result.commit_outcome_unknown = False
    setattr(result, field, True)


def prune(
    path: Path, target: str, now_us: int, budget: store.Budget, execute: bool, result: Result
) -> None:
    with store.connect(path, budget, write=execute) as c:
        value = store.load(c, target, now_us, budget)
        summarize(value, now_us, result)
        result.prune_would_delete = result.expired
        if not execute:
            return
        for slot, generation in value.generations.items():
            current = [r for r in value.records[slot] if r.event_us > now_us - archive.RETENTION_US]
            if len(current) == len(value.records[slot]):
                continue
            if value.origin is None:
                raise store.BackupError("backup_integrity")
            c.execute(
                "DELETE FROM backup_events WHERE slot=? AND event_us<=?",
                (slot, now_us - archive.RETENTION_US),
            )
            c.execute(
                "UPDATE backup_generations SET row_count=?,digest=? WHERE slot=?",
                (len(current), store.digest(target, value.origin, generation, current), slot),
            )
        checked = store.load(c, target, now_us, budget)
        if sum(len(v) for v in checked.records.values()) != result.rows - result.prune_would_delete:
            raise store.BackupError("backup_integrity")
        commit(c, result, "backup_prune_committed")
        result.prune_deleted = result.prune_would_delete
        summarize(checked, now_us, result)


def validate_cursor(initial: int, cursor: int, now_us: int) -> None:
    if (
        not 0
        <= initial
        <= cursor
        <= (now_us * 1000 - control.LAG_NS) // control.WINDOW_NS * control.WINDOW_NS
    ):
        raise store.BackupError("clock_behind_checkpoint")
    if cursor <= (now_us - archive.RETENTION_US) * 1000:
        raise store.BackupError("checkpoint_expired")


def source_check(path: Path, owner: str, service: str, value: control.State) -> None:
    if control.binding(path, owner, service, value.initial_ns) != value.binding:
        raise store.BackupError("binding_mismatch")


def capture(
    db: Path,
    state: Path,
    backup: Path,
    owner: str,
    service: str,
    target: str,
    now_us: int,
    execute: bool,
    result: Result,
    budget: store.Budget,
) -> None:
    result.phase = "backup_prune"
    prune(backup, target, now_us, budget, execute, result)
    result.phase = "source"
    if not db.exists() or not state.exists():
        raise store.BackupError("source_missing")
    state_identity = control.validate(state)
    with control.connect(state, write=execute) as control_c:
        source = control.load(control_c)
        source_check(db, owner, service, source)
        validate_cursor(source.initial_ns, source.cursor_ns, now_us)
        with archive.connect(db) as source_c:
            budget.install(source_c)
            result.source_rows_skipped_expired = source_c.execute(
                "SELECT count(*) FROM operation_events WHERE event_us<=?",
                (now_us - archive.RETENTION_US,),
            ).fetchone()[0]
            result.source_rows_current = source_c.execute(
                "SELECT count(*) FROM operation_events WHERE event_us>?",
                (now_us - archive.RETENTION_US,),
            ).fetchone()[0]
            try:
                records = store.bounded_records(
                    source_c,
                    "operation_events",
                    "event_us>?",
                    (now_us - archive.RETENTION_US,),
                    budget,
                )
            except store.BackupError as exc:
                if str(exc) == "backup_integrity":
                    raise store.BackupError("source_integrity") from None
                raise
            if any(r.event_us > now_us for r in records):
                raise store.BackupError("source_future_rows")
        result.rows_would_capture = len(records)
        result.phase = "capture"
        with store.connect(backup, budget, write=execute) as c:
            old = store.load(c, target, now_us, budget)
            if old.origin not in (None, source.binding):
                raise store.BackupError("origin_changed")
            sequence = 1
            if old.active is not None:
                previous = old.generations[old.active]
                if source.cursor_ns < previous.cursor_ns:
                    raise store.BackupError("cursor_regression")
                if now_us < previous.captured_us:
                    raise store.BackupError("clock_before_backup")
                sequence = previous.sequence + 1
            if sequence > 2**63 - 1:
                raise store.BackupError("generation_limit")
            slot = 0 if old.active is None else 1 - old.active
            generation = store.Generation(
                slot, sequence, now_us, source.initial_ns, source.cursor_ns, len(records), ""
            )
            result.sequence = sequence
            source_check(db, owner, service, source)
            if archive._identity(state) != state_identity:
                raise store.BackupError("source_changed")
            budget.check()
            if not execute:
                return
            c.execute("DELETE FROM backup_events WHERE slot=?", (slot,))
            c.execute("DELETE FROM backup_generations WHERE slot=?", (slot,))
            checksum = store.digest(target, source.binding, generation, records)
            c.execute(
                "INSERT INTO backup_generations VALUES(?,?,?,?,?,?,?)",
                (
                    slot,
                    sequence,
                    now_us,
                    source.initial_ns,
                    source.cursor_ns,
                    len(records),
                    checksum,
                ),
            )
            for item in records:
                budget.check()
                c.execute(
                    "INSERT INTO backup_events VALUES(?,?,?,?,?)",
                    (slot, item.event_hash, item.event_us, item.event, item.record),
                )
            c.execute(
                "UPDATE backup_root SET origin=?,active=? WHERE singleton=1", (source.binding, slot)
            )
            checked = store.load(c, target, now_us, budget)
            source_check(db, owner, service, source)
            if archive._identity(state) != state_identity:
                raise store.BackupError("source_changed")
            commit(c, result, "generation_committed")
            result.rows_captured = len(records)
            summarize(checked, now_us, result)


def restore(
    db: Path,
    state: Path,
    backup: Path,
    owner: str,
    service: str,
    target: str,
    now_us: int,
    execute: bool,
    result: Result,
    budget: store.Budget,
) -> None:
    archive.validate_file_path(db, exists=False)
    archive.validate_file_path(state, exists=False)
    created: dict[Path, tuple[int, int]] = {}
    complete = False
    try:
        with store.connect(backup, budget) as c:
            value = store.load(c, target, now_us, budget)
            summarize(value, now_us, result)
            slot = value.active
            if result.generation == "previous" and slot is not None:
                slot = 1 - slot
            if slot is None or slot not in value.generations:
                raise store.BackupError("generation_missing")
            generation = value.generations[slot]
            validate_cursor(generation.initial_ns, generation.cursor_ns, now_us)
            eligible = [
                r for r in value.records[slot] if r.event_us > now_us - archive.RETENTION_US
            ]
            result.rows_would_restore = len(eligible)
            result.rows_skipped_expired = generation.row_count - len(eligible)
            result.sequence = generation.sequence
            if not execute:
                complete = True
                return
            result.phase = "restore_archive"
            budget.check()
            archive.initialize(db, execute=True)
            created[db] = archive._identity(db)
            result.archive_created = 1
            with archive.connect(db, write=True) as dest:
                budget.install(dest)
                for item in eligible:
                    budget.check()
                    dest.execute(
                        "INSERT INTO operation_events VALUES(?,?,?,?)",
                        (item.event_hash, item.event_us, item.event, item.record),
                    )
            result.rows_restored = len(eligible)
            result.phase = "restore_state"
            if archive._identity(db) != created[db]:
                raise store.BackupError("restore_changed")
            budget.check()
            control.initialize(
                state,
                control.State(
                    control.binding(db, owner, service, generation.initial_ns),
                    generation.initial_ns,
                    generation.cursor_ns,
                ),
                execute=True,
            )
            created[state] = archive._identity(state)
            result.state_created = 1
            complete = True
    finally:
        if execute and not complete:
            for path, identity in created.items():
                try:
                    if archive._identity(path) != identity:
                        continue
                    if path == db:
                        archive.validate_target(path)
                    else:
                        control.validate(path)
                    if path.stat().st_nlink == 1 and archive._identity(path) == identity:
                        path.unlink()
                        result.created_files_removed += 1
                except (OSError, ValueError):
                    pass
            result.orphan_files = sum(int(path.exists()) for path in (db, state))


def run(
    command: str,
    backup: Path,
    owner: str,
    service: str,
    now: datetime,
    *,
    execute: bool = False,
    db: Path | None = None,
    state: Path | None = None,
    generation: str = "latest",
) -> Result:
    result = Result(
        command=command, mode="execute" if execute else "dry_run", generation=generation
    )
    budget = store.Budget()
    try:
        target = store.target_hash(owner, service)
        now_us = epoch_us(now)
        if command not in {"init", "status", "prune", "capture", "restore"} or generation not in {
            "latest",
            "previous",
        }:
            raise ArgumentsError
        if command in {"capture", "restore"}:
            if db is None or state is None:
                raise ArgumentsError
            distinct([db, state, backup])
        if command == "init":
            store.initialize(backup, target, execute=execute)
            result.created, result.would_create = int(execute), 1
        elif command == "status":
            with store.connect(backup, budget) as c:
                summarize(store.load(c, target, now_us, budget), now_us, result)
        elif command == "prune":
            result.phase = "backup_prune"
            prune(backup, target, now_us, budget, execute, result)
        elif db is not None and state is not None:
            if command == "capture":
                capture(db, state, backup, owner, service, target, now_us, execute, result, budget)
            else:
                restore(db, state, backup, owner, service, target, now_us, execute, result, budget)
        result.phase = "completed" if execute else "preview"
    except ArgumentsError:
        raise
    except (store.BackupError, archive.ArchiveError, control.JobError) as exc:
        result.status, result.error = "failed", str(exc)
    except sqlite3.Error as exc:
        reason = "database"
        if getattr(exc, "sqlite_errorcode", 0) & 255 in (5, 6):
            reason = "source_busy" if result.phase == "source" else "backup_busy"
        elif getattr(exc, "sqlite_errorcode", 0) & 255 == 9:
            reason = "budget_exceeded"
        result.status, result.error = "failed", reason
    except KeyboardInterrupt:
        result.status, result.error = "interrupted", "interrupted"
    except Exception:
        result.status, result.error = "failed", "operation_failed"
    result.effects_may_be_partial = bool(
        execute
        and result.status != "ok"
        and (
            result.backup_prune_committed
            or result.commit_outcome_unknown
            or result.archive_created
            or result.state_created
            or result.orphan_files
        )
    )
    return result


def read_config(path: Path) -> dict[str, Any]:
    identity = archive.validate_file_path(path, suffix=".json")
    if path.stat().st_nlink != 1 or path.stat().st_size > 16384:
        raise ArgumentsError
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != identity:
            raise ArgumentsError
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(16385)
        if len(raw) > 16384 or archive._identity(path) != identity:
            raise ArgumentsError
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if (
            type(value) is not dict
            or set(value) != {"db", "state", "backup", "owner_id", "service_id"}
            or any(type(v) is not str for v in value.values())
        ):
            raise ArgumentsError
        return value
    except (UnicodeError, ValueError, Rejected):
        raise ArgumentsError from None
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    result = Result()
    code = 0
    try:
        parser = SafeParser(prog="python -m etl.operation_logs.backup", allow_abbrev=False)
        commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
        for name in ("init", "status", "prune", "capture", "restore"):
            sub = commands.add_parser(name, allow_abbrev=False)
            for option in ("backup", "owner-id", "service-id"):
                sub.add_argument(
                    "--" + option,
                    type=Path if option == "backup" else str,
                    required=name != "capture",
                )
            if name in {"capture", "restore"}:
                for option in ("db", "state"):
                    sub.add_argument("--" + option, type=Path, required=name == "restore")
            if name == "capture":
                sub.add_argument("--config", type=Path)
            if name == "restore":
                sub.add_argument("--generation", choices=("latest", "previous"), default="latest")
            if name != "status":
                sub.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        write = getattr(args, "execute", False)
        result.mode = "execute" if write else "dry_run"
        if args.command == "capture":
            values = [args.db, args.state, args.backup, args.owner_id, args.service_id]
            if args.config:
                if any(v is not None for v in values):
                    raise ArgumentsError
                config = read_config(args.config)
                args.db, args.state, args.backup = (
                    Path(config[n]) for n in ("db", "state", "backup")
                )
                args.owner_id, args.service_id = config["owner_id"], config["service_id"]
            elif any(v is None for v in values):
                raise ArgumentsError
        result = run(
            args.command,
            args.backup,
            args.owner_id,
            args.service_id,
            datetime.now(UTC),
            execute=write,
            db=getattr(args, "db", None),
            state=getattr(args, "state", None),
            generation=getattr(args, "generation", "latest"),
        )
        code = 0 if result.status == "ok" else 130 if result.status == "interrupted" else 1
    except ArgumentsError:
        result.status, result.error, code = "failed", "arguments", 2
    except KeyboardInterrupt:
        result.status, result.error, code = "interrupted", "interrupted", 130
    except (archive.ArchiveError, OSError):
        result.status, result.error, code = "failed", "configuration", 1
    except Exception:
        result.status, result.error, code = "failed", "operation_failed", 1
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
