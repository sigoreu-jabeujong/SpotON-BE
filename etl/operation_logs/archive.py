"""Separate operator-owned SQLite archive; no application/ETL database access."""

import os
import sqlite3
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import BinaryIO

from etl.operation_logs.validation import MAX_LINE_BYTES, Record, Rejected, epoch_us, parse_record

RULE_VERSION = "operation-log-archive-v1"
RETENTION_DAYS = 30
RETENTION_US = RETENTION_DAYS * 86400 * 1_000_000
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_LINES = 10_000
LOCK_TIMEOUT = 1.0
APPLICATION_ID = 0x53504F4C
ROOT = Path(__file__).resolve().parents[2]
TABLE = (
    "CREATE TABLE operation_events (event_hash TEXT PRIMARY KEY CHECK(length(event_hash)=64), "
    "event_us INTEGER NOT NULL, event TEXT NOT NULL, record TEXT NOT NULL)"
)
INDEX = "CREATE INDEX ix_operation_events_time ON operation_events(event_us)"
SCHEMA = {
    ("table", "operation_events"): TABLE,
    ("index", "ix_operation_events_time"): INDEX,
    ("index", "sqlite_autoindex_operation_events_1"): None,
}


class ArchiveError(ValueError):
    """Fixed reason only; the CLI never prints exception messages."""


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ArchiveError("path")
    return info.st_dev, info.st_ino


def _remote_drive(anchor: str) -> bool:
    if os.name != "nt":
        return False
    import ctypes

    loader = getattr(ctypes, "windll", None)
    if loader is None:
        raise ArchiveError("configuration")
    get_type = loader.kernel32.GetDriveTypeW
    get_type.argtypes = [ctypes.c_wchar_p]
    get_type.restype = ctypes.c_uint
    return int(get_type(anchor)) == 4


def _header(path: Path, identity: tuple[int, int]) -> None:
    # Check ownership/rollback mode before SQLite can create WAL sidecars or recover.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity:
            raise ArchiveError("path")
        data = os.read(fd, 100)
    finally:
        os.close(fd)
    if (
        len(data) != 100
        or data[:16] != b"SQLite format 3\0"
        or data[18:20] != b"\1\1"
        or int.from_bytes(data[60:64], "big") != 1
        or int.from_bytes(data[68:72], "big") != APPLICATION_ID
    ):
        raise ArchiveError("ownership")


def validate_target(path: Path, *, exists: bool = True) -> tuple[int, int] | None:
    if (
        not path.is_absolute()
        or path.suffix != ".sqlite3"
        or str(path).startswith(("\\\\", "//"))
        or ".." in path.parts
        or any(p.endswith((" ", ".")) for p in path.parts)
        or any(":" in part for part in path.parts[1:])
        or PureWindowsPath(path.name).is_reserved()
        or _remote_drive(path.anchor)
    ):
        raise ArchiveError("path")
    for part in (*reversed(path.parents), path):
        if part.exists() or part.is_symlink():
            _identity(part)
        elif part != path:
            raise ArchiveError("path")
    resolved = path.resolve(strict=False)
    if os.path.normcase(str(path)) != os.path.normcase(str(resolved)) or resolved.is_relative_to(
        ROOT
    ):
        raise ArchiveError("path")
    if any((p / ".git").exists() for p in path.parents):
        raise ArchiveError("path")
    for suffix in ("-journal", "-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists() or side.is_symlink():
            try:
                _identity(side)
            except FileNotFoundError:
                # A concurrent writer can finish between the existence and identity checks.
                continue
            raise ArchiveError("database_busy" if suffix == "-journal" else "ownership")
    present = path.exists()
    if not present:
        if exists:
            raise ArchiveError("missing")
        return None
    if not exists:
        raise ArchiveError("exists")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size == 0:
        raise ArchiveError("ownership")
    identity = _identity(path)
    _header(path, identity)
    return identity


def _owned(connection: sqlite3.Connection) -> None:
    objects = {
        (kind, name): sql
        for kind, name, sql in connection.execute("SELECT type,name,sql FROM sqlite_master")
    }
    if (
        connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
        or connection.execute("PRAGMA user_version").fetchone()[0] != 1
        or objects != SCHEMA
        or connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
    ):
        raise ArchiveError("ownership")


def _configure(connection: sqlite3.Connection, *, write: bool) -> None:
    connection.execute("PRAGMA trusted_schema=OFF")
    if write:
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA temp_store=MEMORY")
        if connection.execute("PRAGMA secure_delete").fetchone()[0] != 1:
            raise ArchiveError("configuration")
    deadline = time.monotonic() + 10
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)


@contextmanager
def connect(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    identity = validate_target(path)
    c = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
        uri=True,
        isolation_level=None,
        timeout=LOCK_TIMEOUT,
    )
    try:
        if _identity(path) != identity:
            raise ArchiveError("path")
        c.execute("PRAGMA trusted_schema=OFF")
        _owned(c)
        _configure(c, write=write)
        c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        _owned(c)
        yield c
        if write:
            c.commit()
    finally:
        try:
            if c.in_transaction:
                c.rollback()
        finally:
            c.close()


def initialize(path: Path, *, execute: bool = False) -> dict[str, int]:
    validate_target(path, exists=False)
    if not execute:
        return {"created": 0, "would_create": 1}
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    identity = os.fstat(fd).st_dev, os.fstat(fd).st_ino
    os.close(fd)
    c: sqlite3.Connection | None = None
    complete = False
    try:
        if _identity(path) != identity:
            raise ArchiveError("path")
        c = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=LOCK_TIMEOUT
        )
        if _identity(path) != identity:
            raise ArchiveError("path")
        _configure(c, write=True)
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("BEGIN IMMEDIATE")
        c.execute(f"PRAGMA application_id={APPLICATION_ID}")
        c.execute("PRAGMA user_version=1")
        c.execute(TABLE)
        c.execute(INDEX)
        _owned(c)
        c.commit()
        complete = True
    finally:
        if c is not None:
            if c.in_transaction:
                c.rollback()
            c.close()
        if not complete and path.exists() and _identity(path) == identity:
            path.unlink()
    return {"created": 1, "would_create": 1}


@dataclass
class Counts:
    lines: int = 0
    rejected: int = 0
    future: int = 0
    expired: int = 0
    duplicate: int = 0
    inserted: int = 0
    would_insert: int = 0


def read_input(stream: BinaryIO, now: datetime | None = None) -> tuple[Counts, dict[str, Record]]:
    counts = Counts()
    records: dict[str, Record] = {}
    total = 0
    candidates: list[Record] = []
    while True:
        chunk = stream.readline(MAX_LINE_BYTES + 3)
        if not chunk:
            break
        counts.lines += 1
        oversized = False
        while True:
            total += len(chunk)
            if counts.lines > MAX_LINES or total > MAX_INPUT_BYTES:
                raise ArchiveError("input_limit")
            if chunk.endswith(b"\n") or len(chunk) < MAX_LINE_BYTES + 3:
                break
            oversized = True
            chunk = stream.readline(MAX_LINE_BYTES + 3)
            if not chunk:
                break
        raw = (
            chunk[:-2]
            if chunk.endswith(b"\r\n")
            else chunk[:-1]
            if chunk.endswith(b"\n")
            else chunk
        )
        if oversized or len(raw) > MAX_LINE_BYTES:
            counts.rejected += 1
            continue
        try:
            candidates.append(parse_record(raw))
        except Rejected:
            counts.rejected += 1
            continue
    # A finite batch is completely consumed before capturing its one reference clock.
    now_us = epoch_us(now if now is not None else datetime.now(UTC))
    for record in candidates:
        if record.event_us > now_us:
            counts.future += 1
        elif record.event_us <= now_us - RETENTION_US:
            counts.expired += 1
        elif record.event_hash in records:
            counts.duplicate += 1
        else:
            records[record.event_hash] = record
    return counts, records


def ingest(
    path: Path, stream: BinaryIO, now: datetime | None = None, *, execute: bool = False
) -> dict[str, int]:
    validate_target(path)
    counts, records = read_input(stream, now)
    with connect(path, write=execute) as c:
        for record in records.values():
            if execute:
                inserted = c.execute(
                    "INSERT OR IGNORE INTO operation_events VALUES (?,?,?,?)",
                    (record.event_hash, record.event_us, record.event, record.record),
                ).rowcount
            else:
                inserted = int(
                    c.execute(
                        "SELECT 1 FROM operation_events WHERE event_hash=?", (record.event_hash,)
                    ).fetchone()
                    is None
                )
            counts.would_insert += inserted
            counts.duplicate += 1 - inserted
        counts.inserted = counts.would_insert if execute else 0
        if (
            counts.lines
            != counts.rejected
            + counts.future
            + counts.expired
            + counts.duplicate
            + counts.would_insert
        ):
            raise ArchiveError("counts")
    return asdict(counts)


def _summary(c: sqlite3.Connection, cutoff: int) -> dict[str, int]:
    total, expired = c.execute(
        "SELECT count(*),coalesce(sum(event_us<=?),0) FROM operation_events", (cutoff,)
    ).fetchone()
    return {"rows": total, "expired": expired}


def status(path: Path, now: datetime) -> dict[str, int]:
    with connect(path) as c:
        return _summary(c, epoch_us(now) - RETENTION_US)


def prune(path: Path, now: datetime, *, execute: bool = False) -> dict[str, int]:
    cutoff = epoch_us(now) - RETENTION_US
    with connect(path, write=execute) as c:
        before = _summary(c, cutoff)
        deleted = 0
        if execute:
            deleted = c.execute(
                "DELETE FROM operation_events WHERE event_us<=?", (cutoff,)
            ).rowcount
            after = _summary(c, cutoff)
            if (
                deleted != before["expired"]
                or after["expired"] != 0
                or after["rows"] != before["rows"] - deleted
            ):
                raise ArchiveError("counts")
        else:
            after = before
        return {
            "would_delete": before["expired"],
            "deleted": deleted,
            "rows": after["rows"],
            "expired": after["expired"],
        }
