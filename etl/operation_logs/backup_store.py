"""Two logical snapshots, one owned file; credentials and raw source messages are excluded."""

import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from etl.operation_logs import archive, job, job_state, render
from etl.operation_logs.validation import MAX_LINE_BYTES, Record, Rejected, parse_record

RULE = "operation-log-backup-v1"
APPLICATION_ID = 0x5350424B
MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE = 256 * 1024 * 1024
HEX = re.compile("[0-9a-f]{64}")
ROOT_TABLE = (
    "CREATE TABLE backup_root (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "target TEXT NOT NULL CHECK(length(target)=64), origin TEXT CHECK(length(origin)=64), "
    "active INTEGER CHECK(active IN (0,1)))"
)
GEN_TABLE = (
    "CREATE TABLE backup_generations (slot INTEGER PRIMARY KEY CHECK(slot IN (0,1)), "
    "sequence INTEGER NOT NULL CHECK(sequence>0), "
    "captured_us INTEGER NOT NULL CHECK(captured_us>=0), "
    "initial_ns INTEGER NOT NULL CHECK(initial_ns>=0), "
    "cursor_ns INTEGER NOT NULL CHECK(cursor_ns>=initial_ns), "
    "row_count INTEGER NOT NULL CHECK(row_count>=0), digest TEXT NOT NULL CHECK(length(digest)=64))"
)
EVENT_TABLE = (
    "CREATE TABLE backup_events (slot INTEGER NOT NULL CHECK(slot IN (0,1)), "
    "event_hash TEXT NOT NULL CHECK(length(event_hash)=64), event_us INTEGER NOT NULL, "
    "event TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(slot,event_hash), "
    "FOREIGN KEY(slot) REFERENCES backup_generations(slot))"
)
INDEX = "CREATE INDEX ix_backup_event_time ON backup_events(event_us)"
SCHEMA = {
    ("table", "backup_root"): ROOT_TABLE,
    ("table", "backup_generations"): GEN_TABLE,
    ("table", "backup_events"): EVENT_TABLE,
    ("index", "sqlite_autoindex_backup_events_1"): None,
    ("index", "ix_backup_event_time"): INDEX,
}


class BackupError(ValueError):
    """Static reason only."""


@dataclass
class Budget:
    end: float = field(default_factory=lambda: time.monotonic() + 30)

    def check(self) -> None:
        if time.monotonic() > self.end:
            raise BackupError("budget_exceeded")

    def install(self, c: sqlite3.Connection) -> None:
        c.set_progress_handler(lambda: int(time.monotonic() > self.end), 1000)


@dataclass(frozen=True, repr=False)
class Generation:
    slot: int
    sequence: int
    captured_us: int
    initial_ns: int
    cursor_ns: int
    row_count: int
    digest: str


@dataclass(repr=False)
class Snapshot:
    target: str
    origin: str | None
    active: int | None
    generations: dict[int, Generation]
    records: dict[int, list[Record]]


def target_hash(owner: str, service: str) -> str:
    job.ids(owner, service)
    return hashlib.sha256(
        json.dumps(
            [
                RULE,
                archive.RULE_VERSION,
                job_state.RULE,
                render.RULE,
                owner,
                service,
                job_state.WINDOW_NS,
                job_state.LAG_NS,
                job_state.OVERLAP_NS,
                job_state.MAX_WINDOWS,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def validate(path: Path) -> tuple[int, int]:
    try:
        identity = archive.validate_file_path(path)
    except archive.ArchiveError as exc:
        if str(exc) == "database_busy":
            raise BackupError("backup_journal_present") from None
        raise
    if identity is None or path.stat().st_nlink != 1 or path.stat().st_size > MAX_FILE:
        raise BackupError("backup_file")
    archive._header(path, identity, application_id=APPLICATION_ID)
    return identity


def owned(c: sqlite3.Connection) -> None:
    objects = {
        (kind, name): sql
        for kind, name, sql in c.execute("SELECT type,name,sql FROM sqlite_master LIMIT 6")
    }
    if (
        objects != SCHEMA
        or c.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
        or c.execute("PRAGMA user_version").fetchone()[0] != 1
        or c.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
        or c.execute("PRAGMA page_count").fetchone()[0]
        * c.execute("PRAGMA page_size").fetchone()[0]
        > MAX_FILE
    ):
        raise BackupError("backup_ownership")


def configure(c: sqlite3.Connection, budget: Budget, *, write: bool) -> None:
    budget.check()
    c.execute("PRAGMA trusted_schema=OFF")
    c.execute("PRAGMA foreign_keys=ON")
    budget.install(c)
    if write:
        c.execute("PRAGMA secure_delete=ON")
        c.execute("PRAGMA temp_store=MEMORY")
        pages = MAX_FILE // c.execute("PRAGMA page_size").fetchone()[0]
        if c.execute(f"PRAGMA max_page_count={pages}").fetchone()[0] != pages or (
            c.execute("PRAGMA secure_delete").fetchone()[0] != 1
        ):
            raise BackupError("backup_configuration")


@contextmanager
def connect(path: Path, budget: Budget, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    identity = validate(path)
    c = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
        uri=True,
        isolation_level=None,
        timeout=1,
    )
    try:
        if archive._identity(path) != identity:
            raise BackupError("backup_changed")
        configure(c, budget, write=write)
        owned(c)
        c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        owned(c)
        yield c
    finally:
        try:
            if c.in_transaction:
                c.rollback()
        finally:
            c.close()


def initialize(path: Path, target: str, *, execute: bool = False) -> None:
    archive.validate_file_path(path, exists=False)
    if not execute:
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    info = os.fstat(fd)
    identity = info.st_dev, info.st_ino
    os.close(fd)
    c = None
    complete = False
    try:
        if archive._identity(path) != identity:
            raise BackupError("backup_changed")
        c = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=1)
        if archive._identity(path) != identity:
            raise BackupError("backup_changed")
        configure(c, Budget(), write=True)
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("BEGIN IMMEDIATE")
        c.execute(f"PRAGMA application_id={APPLICATION_ID}")
        c.execute("PRAGMA user_version=1")
        for sql in (ROOT_TABLE, GEN_TABLE, EVENT_TABLE, INDEX):
            c.execute(sql)
        c.execute("INSERT INTO backup_root VALUES(1,?,NULL,NULL)", (target,))
        owned(c)
        c.commit()
        complete = True
    finally:
        if c is not None:
            try:
                if c.in_transaction:
                    c.rollback()
            finally:
                c.close()
        if not complete:
            try:
                if path.exists() and archive._identity(path) == identity:
                    path.unlink()
            except (OSError, archive.ArchiveError):
                pass


def record(row: Sequence[object]) -> Record:
    if len(row) != 4 or any(type(row[n]) is not str for n in (0, 2, 3)) or type(row[1]) is not int:
        raise BackupError("backup_integrity")
    try:
        parsed = parse_record(str(row[3]).encode("utf-8"))
    except (Rejected, UnicodeError):
        raise BackupError("backup_integrity") from None
    if (parsed.event_hash, parsed.event_us, parsed.event, parsed.record) != tuple(row):
        raise BackupError("backup_integrity")
    return parsed


def digest(target: str, origin: str, value: Generation, records: list[Record]) -> str:
    h = hashlib.sha256(
        json.dumps(
            dict(
                domain=RULE,
                target=target,
                origin=origin,
                sequence=value.sequence,
                captured_us=value.captured_us,
                initial_ns=value.initial_ns,
                cursor_ns=value.cursor_ns,
                row_count=len(records),
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    for item in records:
        h.update(item.record.encode("utf-8") + b"\n")
    return h.hexdigest()


def bounded_records(
    c: sqlite3.Connection, table: str, where: str, args: tuple[object, ...], budget: Budget
) -> list[Record]:
    # All table/where fragments are internal constants, never operator input.
    if c.execute(f"SELECT count(*) FROM {table} WHERE {where}", args).fetchone()[0] > MAX_ROWS:
        raise BackupError("capture_limit")
    rows = c.execute(
        f"SELECT event_hash, CASE WHEN typeof(event_us)='integer' THEN event_us END, "
        f"CASE WHEN typeof(event)='text' AND length(event)<=64 THEN event END, "
        f"CASE WHEN typeof(record)='text' AND length(CAST(record AS BLOB))<={MAX_LINE_BYTES} "
        f"THEN record END FROM {table} WHERE {where} ORDER BY event_hash",
        args,
    )
    result: list[Record] = []
    size = 0
    for row in rows:
        budget.check()
        item = record(row)
        size += len(item.record.encode("utf-8"))
        if size > MAX_BYTES:
            raise BackupError("capture_limit")
        result.append(item)
    return result


def load(c: sqlite3.Connection, target: str, now_us: int, budget: Budget) -> Snapshot:
    roots = c.execute("SELECT target,origin,active FROM backup_root").fetchall()
    if len(roots) != 1:
        raise BackupError("backup_integrity")
    if roots[0][0] != target:
        raise BackupError("target_mismatch")
    _, origin, active = roots[0]
    if (origin is not None and (type(origin) is not str or not HEX.fullmatch(origin))) or (
        active is not None and (type(active) is not int or active not in (0, 1))
    ):
        raise BackupError("backup_integrity")
    gens: dict[int, Generation] = {}
    records: dict[int, list[Record]] = {}
    for row in c.execute("SELECT * FROM backup_generations"):
        if (
            any(type(v) is not int for v in row[:6])
            or row[0] not in (0, 1)
            or not 1 <= row[1] <= 2**63 - 1
            or not 0 <= row[3] <= row[4] <= 2**63 - 1
            or not 0 <= row[2] <= 2**63 - 1
            or not 0 <= row[5] <= MAX_ROWS
            or type(row[6]) is not str
            or not HEX.fullmatch(row[6])
        ):
            raise BackupError("backup_integrity")
        if row[2] > now_us:
            raise BackupError("clock_before_backup")
        value = Generation(*row)
        if value.cursor_ns > value.captured_us * 1000:
            raise BackupError("backup_integrity")
        gens[value.slot] = value
    if not gens:
        if (
            origin is not None
            or active is not None
            or c.execute("SELECT 1 FROM backup_events LIMIT 1").fetchone()
        ):
            raise BackupError("backup_integrity")
    else:
        if origin is None or active not in gens:
            raise BackupError("backup_integrity")
        ordered = sorted(gens.values(), key=lambda v: v.sequence)
        if (
            (len(ordered) == 1 and ordered[0].sequence != 1)
            or ordered[-1].slot != active
            or (
                len(ordered) == 2
                and (
                    ordered[1].sequence != ordered[0].sequence + 1
                    or ordered[1].initial_ns != ordered[0].initial_ns
                    or ordered[1].cursor_ns < ordered[0].cursor_ns
                    or ordered[1].captured_us < ordered[0].captured_us
                )
            )
        ):
            raise BackupError("backup_integrity")
        if c.execute(
            "SELECT 1 FROM backup_events WHERE slot NOT IN "
            "(SELECT slot FROM backup_generations) LIMIT 1"
        ).fetchone():
            raise BackupError("backup_integrity")
        for slot, value in gens.items():
            records[slot] = bounded_records(c, "backup_events", "slot=?", (slot,), budget)
            if (
                len(records[slot]) != value.row_count
                or any(r.event_us > value.captured_us for r in records[slot])
                or digest(target, origin, value, records[slot]) != value.digest
            ):
                raise BackupError("backup_integrity")
    return Snapshot(target, origin, active, gens, records)
