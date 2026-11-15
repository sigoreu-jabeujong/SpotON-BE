"""Keyless logical SPBK export. No source writes, secrets, transport or encryption."""

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from etl.operation_logs import archive, backup, job
from etl.operation_logs import backup_store as store
from etl.operation_logs.__main__ import ArgumentsError, SafeParser
from etl.operation_logs.validation import epoch_us

RULE = "operation-log-export-v1"
CHUNK_BYTES = 64 * 1024
REASONS = frozenset(
    {
        "path",
        "missing",
        "exists",
        "ownership",
        "configuration",
        "database_busy",
        "backup_journal_present",
        "backup_file",
        "backup_ownership",
        "backup_integrity",
        "backup_changed",
        "backup_configuration",
        "target_mismatch",
        "clock_before_backup",
        "clock_behind_checkpoint",
        "checkpoint_expired",
        "capture_limit",
        "budget_exceeded",
        "generation_missing",
        "output_changed",
        "output_integrity",
        "output_limit",
    }
)


@dataclass
class Result:
    status: str = "ok"
    error: str | None = None
    mode: str = "dry_run"
    phase: str = "validation"
    rule_version: str = RULE
    snapshot_as_of: str | None = None
    captured_at: str | None = None
    last_confirmed_until: str | None = None
    sequence: int | None = None
    generations: int = 0
    source_rows: int = 0
    rows: int = 0
    rows_skipped_expired: int = 0
    next_expiry_at: str | None = None
    would_create: int = 0
    created: int = 0
    integrity_verified: bool = False
    output_verified: bool = False
    output_bytes: int | None = None
    output_sha256: str | None = None
    commit_outcome_unknown: bool = False
    created_files_removed: int = 0
    orphan_files: int = 0
    effects_may_be_partial: bool = False
    encrypted: bool = False
    remote_uploaded: bool = False
    coverage_verified: bool = False


@dataclass(repr=False)
class Created:
    identity: tuple[int, int] | None = None


def same_file(path: Path, identity: tuple[int, int]) -> os.stat_result:
    if archive.validate_file_path(path, syntax_only=True) != identity:
        raise store.BackupError("output_changed")
    info = path.stat()
    if (
        (info.st_dev, info.st_ino) != identity
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
    ):
        raise store.BackupError("output_changed")
    return info


def filtered(
    value: store.Snapshot, now_us: int, result: Result, budget: store.Budget
) -> store.Snapshot:
    if value.active is None or value.origin is None:
        raise store.BackupError("generation_missing")
    generations = {}
    records = {}
    first_expiry = None
    for slot, generation in value.generations.items():
        backup.validate_cursor(generation.initial_ns, generation.cursor_ns, now_us)
        eligible = []
        for item in value.records[slot]:
            budget.check()
            if item.event_us > now_us - archive.RETENTION_US:
                eligible.append(item)
                expiry = item.event_us + archive.RETENTION_US
                first_expiry = expiry if first_expiry is None else min(first_expiry, expiry)
        generations[slot] = replace(
            generation,
            row_count=len(eligible),
            digest=store.digest(value.target, value.origin, generation, eligible),
        )
        records[slot] = eligible
    result.integrity_verified = True
    result.generations = len(generations)
    result.source_rows = sum(len(rows) for rows in value.records.values())
    result.rows = sum(len(rows) for rows in records.values())
    result.rows_skipped_expired = result.source_rows - result.rows
    result.next_expiry_at = None if first_expiry is None else job.stamp(first_expiry * 1000)
    active = value.generations[value.active]
    result.sequence = active.sequence
    result.captured_at = job.stamp(active.captured_us * 1000)
    result.last_confirmed_until = job.stamp(active.cursor_ns)
    result.would_create = 1
    return store.Snapshot(value.target, value.origin, value.active, generations, records)


def create_file(path: Path, created: Created, result: Result) -> None:
    archive.validate_file_path(path, exists=False)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    result.created = 1
    try:
        info = os.fstat(fd)
        created.identity = info.st_dev, info.st_ino
        same_file(path, created.identity)
    finally:
        os.close(fd)


def commit(c: sqlite3.Connection, result: Result) -> None:
    result.commit_outcome_unknown = True
    c.commit()
    result.commit_outcome_unknown = False


def write_file(
    path: Path,
    identity: tuple[int, int],
    value: store.Snapshot,
    now_us: int,
    result: Result,
    budget: store.Budget,
) -> None:
    if same_file(path, identity).st_size != 0:
        raise store.BackupError("output_changed")
    c = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=1)
    try:
        same_file(path, identity)
        store.configure(c, budget, write=True)
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("BEGIN IMMEDIATE")
        c.execute(f"PRAGMA application_id={store.APPLICATION_ID}")
        c.execute("PRAGMA user_version=1")
        for sql in (store.ROOT_TABLE, store.GEN_TABLE, store.EVENT_TABLE, store.INDEX):
            c.execute(sql)
        c.execute(
            "INSERT INTO backup_root VALUES(1,?,?,?)", (value.target, value.origin, value.active)
        )
        for slot, generation in value.generations.items():
            budget.check()
            c.execute(
                "INSERT INTO backup_generations VALUES(?,?,?,?,?,?,?)",
                (
                    slot,
                    generation.sequence,
                    generation.captured_us,
                    generation.initial_ns,
                    generation.cursor_ns,
                    generation.row_count,
                    generation.digest,
                ),
            )
            for item in value.records[slot]:
                budget.check()
                c.execute(
                    "INSERT INTO backup_events VALUES(?,?,?,?,?)",
                    (slot, item.event_hash, item.event_us, item.event, item.record),
                )
        store.owned(c)
        if store.load(c, value.target, now_us, budget) != value:
            raise store.BackupError("output_integrity")
        same_file(path, identity)
        budget.check()
        commit(c, result)
    finally:
        try:
            if c.in_transaction:
                c.rollback()
        finally:
            c.close()


def fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def file_hash(path: Path, identity: tuple[int, int], budget: store.Budget) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            (info.st_dev, info.st_ino) != identity
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= store.MAX_FILE
        ):
            raise store.BackupError("output_changed")
        expected = fingerprint(info)
        h = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "rb", closefd=False) as stream:
            while True:
                budget.check()
                chunk = stream.read(min(CHUNK_BYTES, info.st_size - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > info.st_size:
                    raise store.BackupError("output_changed")
                h.update(chunk)
        if size != info.st_size or fingerprint(os.fstat(fd)) != expected:
            raise store.BackupError("output_changed")
        if fingerprint(same_file(path, identity)) != expected:
            raise store.BackupError("output_changed")
        return size, h.hexdigest()
    finally:
        os.close(fd)


def verify_file(
    path: Path,
    identity: tuple[int, int],
    value: store.Snapshot,
    now_us: int,
    budget: store.Budget,
) -> tuple[int, str]:
    before = fingerprint(same_file(path, identity))
    with store.connect(path, budget) as c:
        if store.load(c, value.target, now_us, budget) != value:
            raise store.BackupError("output_integrity")
    size, digest = file_hash(path, identity, budget)
    if before != fingerprint(same_file(path, identity)):
        raise store.BackupError("output_changed")
    budget.check()
    return size, digest


def cleanup(path: Path, created: Created, result: Result) -> None:
    # Never remove sidecars, replacement files or an unrecognizable nonempty file.
    try:
        if created.identity is not None:
            info = same_file(path, created.identity)
            for suffix in ("-journal", "-wal", "-shm"):
                side = Path(str(path) + suffix)
                if side.exists() or side.is_symlink():
                    raise store.BackupError("output_changed")
            if info.st_size:
                store.validate(path)
            same_file(path, created.identity)
            path.unlink()
            result.created_files_removed = 1
    except (OSError, ValueError, KeyboardInterrupt):
        pass
    for name in (path, *(Path(str(path) + s) for s in ("-journal", "-wal", "-shm"))):
        try:
            result.orphan_files += int(name.exists() or name.is_symlink())
        except OSError:
            # Failure to inspect is not proof that the file is absent.
            result.orphan_files += 1


def run(
    source: Path,
    output: Path,
    owner: str,
    service: str,
    now: datetime,
    *,
    execute: bool = False,
) -> Result:
    result = Result(mode="execute" if execute else "dry_run")
    created = Created()
    budget = store.Budget()
    try:
        target = store.target_hash(owner, service)
        try:
            now_us = epoch_us(now)
        except ValueError:
            raise ArgumentsError from None
        result.snapshot_as_of = job.stamp(now_us * 1000)
        if source == output:
            raise store.BackupError("output_changed")
        archive.validate_file_path(output, exists=False)
        result.phase = "source"
        identity = store.validate(source)
        with store.connect(source, budget) as c:
            value = filtered(store.load(c, target, now_us, budget), now_us, result, budget)
            same_file(source, identity)
        if execute:
            result.phase = "create"
            budget.check()
            create_file(output, created, result)
            if created.identity is None:
                raise store.BackupError("output_changed")
            result.phase = "write"
            write_file(output, created.identity, value, now_us, result, budget)
            result.phase = "verify"
            size, digest = verify_file(output, created.identity, value, now_us, budget)
            result.output_bytes, result.output_sha256 = size, digest
            result.output_verified = True
        result.phase = "completed" if execute else "preview"
    except ArgumentsError:
        result.status, result.error = "failed", "arguments"
    except (archive.ArchiveError, store.BackupError) as exc:
        reason = str(exc) if str(exc) in REASONS else "operation_failed"
        if result.phase == "source" and reason.startswith("backup_"):
            reason = "source_" + reason.removeprefix("backup_")
        elif result.phase == "source" and reason == "output_changed":
            reason = "source_changed"
        elif result.phase in {"write", "verify"} and reason.startswith("backup_"):
            reason = "output_" + reason.removeprefix("backup_")
        result.status, result.error = "failed", reason
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0) & 255
        prefix = "source" if result.phase == "source" else "output"
        reason = prefix + "_database"
        if code in (5, 6):
            reason = prefix + "_busy"
        elif code == 9:
            reason = "budget_exceeded"
        elif code == 13:
            reason = prefix + "_capacity"
        elif code == 10:
            reason = prefix + "_io"
        elif code in (11, 26):
            reason = prefix + "_integrity"
        result.status, result.error = "failed", reason
    except KeyboardInterrupt:
        result.status, result.error = "interrupted", "interrupted"
    except OSError:
        result.status, result.error = "failed", "filesystem"
    except Exception:
        result.status, result.error = "failed", "operation_failed"
    finally:
        if result.status != "ok" and result.created:
            cleanup(output, created, result)
            result.effects_may_be_partial = True
    return result


def main(argv: list[str] | None = None) -> int:
    result = Result()
    try:
        parser = SafeParser(prog="python -m etl.operation_logs.backup_export", allow_abbrev=False)
        for name in ("backup", "output", "owner-id", "service-id"):
            parser.add_argument(
                "--" + name, type=Path if name in {"backup", "output"} else str, required=True
            )
        parser.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        result = run(
            args.backup,
            args.output,
            args.owner_id,
            args.service_id,
            datetime.now(UTC),
            execute=args.execute,
        )
    except ArgumentsError:
        result.status, result.error = "failed", "arguments"
    except KeyboardInterrupt:
        result.status, result.error = "interrupted", "interrupted"
    except Exception:
        result.status, result.error = "failed", "operation_failed"
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return (
        0
        if result.status == "ok"
        else 130
        if result.status == "interrupted"
        else 2
        if (result.error == "arguments")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
