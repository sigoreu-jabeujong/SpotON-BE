"""Owned, bounded metadata file. No credentials, paths, or source events are stored."""

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from etl.operation_logs import archive, render

RULE = "render-log-job-v1"
APPLICATION_ID = 0x53504A43
WINDOW_NS = 300 * 10**9
LAG_NS = 300 * 10**9
OVERLAP_NS = 120 * 10**9
MAX_WINDOWS = 6
DAY_NS = 86400 * 10**9
TABLE = (
    "CREATE TABLE job_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "binding TEXT NOT NULL CHECK(length(binding)=64), "
    "initial_ns INTEGER NOT NULL CHECK(initial_ns>=0), "
    "cursor_ns INTEGER NOT NULL CHECK(cursor_ns>=initial_ns))"
)


class JobError(ValueError):
    """Static reason only."""


@dataclass(frozen=True, repr=False)
class State:
    binding: str
    initial_ns: int
    cursor_ns: int


def binding(path: Path, owner: str, service: str, initial_ns: int) -> str:
    archive.validate_target(path)
    info = path.stat()
    if info.st_nlink != 1:
        raise JobError("archive_links")
    value = {
        "domain": RULE,
        "path": os.path.normcase(str(path.resolve())),
        "identity": [info.st_dev, info.st_ino],
        "owner": owner,
        "service": service,
        "initial_ns": initial_ns,
        "window_ns": WINDOW_NS,
        "lag_ns": LAG_NS,
        "overlap_ns": OVERLAP_NS,
        "max_windows": MAX_WINDOWS,
        "archive_rule": archive.RULE_VERSION,
        "render_rule": render.RULE,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate(path: Path) -> tuple[int, int]:
    try:
        identity = archive.validate_file_path(path)
    except archive.ArchiveError as exc:
        if str(exc) == "database_busy":
            raise JobError("state_journal_present") from None
        raise
    if identity is None or path.stat().st_nlink != 1 or path.stat().st_size > 1024**2:
        raise JobError("state_file")
    archive._header(path, identity, application_id=APPLICATION_ID)
    return identity


def owned(c: sqlite3.Connection) -> None:
    objects = {
        (kind, name): sql
        for kind, name, sql in c.execute("SELECT type,name,sql FROM sqlite_master")
    }
    if (
        c.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
        or c.execute("PRAGMA user_version").fetchone()[0] != 1
        or c.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
        or objects != {("table", "job_state"): TABLE}
    ):
        raise JobError("state_ownership")


def load(c: sqlite3.Connection) -> State:
    row = c.execute(
        "SELECT binding,initial_ns,cursor_ns FROM job_state WHERE singleton=1"
    ).fetchone()
    if (
        row is None
        or type(row[0]) is not str
        or not re.fullmatch("[0-9a-f]{64}", row[0])
        or type(row[1]) is not int
        or type(row[2]) is not int
        or not 0 <= row[1] <= row[2] <= 2**63 - 1
    ):
        raise JobError("state_contents")
    return State(*row)


@contextmanager
def connect(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    identity = validate(path)
    c = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
        uri=True,
        isolation_level=None,
        timeout=1,
    )
    try:
        if archive._identity(path) != identity:
            raise JobError("state_changed")
        c.execute("PRAGMA trusted_schema=OFF")
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


def initialize(path: Path, value: State, *, execute: bool = False) -> None:
    archive.validate_file_path(path, exists=False)
    if not execute:
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    identity = os.fstat(fd).st_dev, os.fstat(fd).st_ino
    os.close(fd)
    c = None
    complete = False
    try:
        if archive._identity(path) != identity:
            raise JobError("state_changed")
        c = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=1)
        if archive._identity(path) != identity:
            raise JobError("state_changed")
        c.execute("PRAGMA trusted_schema=OFF")
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("PRAGMA secure_delete=ON")
        c.execute("BEGIN IMMEDIATE")
        c.execute(f"PRAGMA application_id={APPLICATION_ID}")
        c.execute("PRAGMA user_version=1")
        c.execute(TABLE)
        c.execute(
            "INSERT INTO job_state VALUES (1,?,?,?)",
            (value.binding, value.initial_ns, value.cursor_ns),
        )
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


def save(c: sqlite3.Connection, before: State, cursor: int) -> None:
    if cursor < before.cursor_ns:
        raise JobError("checkpoint_regression")
    count = c.execute(
        "UPDATE job_state SET cursor_ns=? WHERE singleton=1 AND binding=? AND cursor_ns=?",
        (cursor, before.binding, before.cursor_ns),
    ).rowcount
    if count != 1:
        raise JobError("state_changed")
