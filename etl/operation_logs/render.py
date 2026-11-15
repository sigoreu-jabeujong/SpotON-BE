"""Bounded read-only Render window export into an existing operator archive."""

import io
import json
import logging
import math
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import httpx
from pydantic import SecretStr

from etl.operation_logs import archive
from etl.operation_logs.__main__ import ArgumentsError, SafeParser
from etl.operation_logs.validation import MAX_LINE_BYTES, Rejected, epoch_us, parse_record

BASE = "https://api.render.com/v1"
RULE = "render-log-window-v1"
MAX_PAGES, PAGE_ROWS, MAX_ROWS = 20, 100, 2000
MAX_BODY, MAX_TOTAL, SERVICE_BODY = 1024**2, 10 * 1024**2, 256 * 1024
NETWORK_SECONDS = 30
STAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|\+00:00)"
)
OWNER = re.compile(r"(?:tea|usr)-[a-z0-9]{10,40}")
SERVICE = re.compile(r"srv-[a-z0-9]{10,40}")


class RenderLogError(ValueError):
    """Fixed reason codes, never response text/URLs/authentication values."""


def nanoseconds(value: object) -> int:
    if type(value) is not str or len(value) > 40:
        raise RenderLogError("timestamp")
    match = STAMP.fullmatch(value)
    if match is None:
        raise RenderLogError("timestamp")
    try:
        seconds = datetime.fromisoformat(match[1] + "+00:00")
        return epoch_us(seconds) * 1000 + int((match[2] or "").ljust(9, "0"))
    except ValueError:
        raise RenderLogError("timestamp") from None


def validate_window(owner: str, service: str, start: str, end: str) -> tuple[int, int, bool]:
    if not OWNER.fullmatch(owner) or not SERVICE.fullmatch(service):
        raise ArgumentsError
    try:
        lo, hi = nanoseconds(start), nanoseconds(end)
    except RenderLogError:
        raise ArgumentsError from None
    now = epoch_us(datetime.now(UTC)) * 1000
    if not lo < hi <= now or hi - lo > 3600 * 10**9:
        raise ArgumentsError
    return lo, hi, now - hi < 300 * 10**9


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise RenderLogError("api_payload")
        result[key] = value
    return result


def _constant(value: str) -> NoReturn:
    raise RenderLogError("api_payload")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise RenderLogError("api_payload")
    return number


class Reader:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.deadline = time.monotonic() + NETWORK_SECONDS
        self.total = 0

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise RenderLogError("network_budget")

    def get(self, path: str, params: dict[str, str] | None = None, *, cap: int = MAX_BODY) -> Any:
        self.check()
        timeout = max(0.001, min(5, self.deadline - time.monotonic()))
        with self.client.stream("GET", BASE + path, params=params, timeout=timeout) as response:
            if response.status_code != 200:
                reason = (
                    "api_authentication"
                    if response.status_code in (401, 403)
                    else "api_rate_limit"
                    if response.status_code == 429
                    else "api_http"
                )
                raise RenderLogError(reason)
            if (
                response.headers.get("content-type", "").split(";", 1)[0].strip()
                != "application/json"
            ):
                raise RenderLogError("api_payload")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise RenderLogError("api_payload")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                self.check()
                self.total += len(chunk)
                if len(data) + len(chunk) > cap or self.total > MAX_TOTAL:
                    raise RenderLogError("response_limit")
                data.extend(chunk)
        self.check()
        try:
            return json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_pairs,
                parse_constant=_constant,
                parse_float=_float,
            )
        except (ValueError, UnicodeError, RecursionError):
            raise RenderLogError("api_payload") from None


def _message(row: object, service: str, lo: int, hi: int) -> tuple[int, str | None]:
    if type(row) is not dict or not {"id", "message", "timestamp", "labels"} <= row.keys():
        raise RenderLogError("api_payload")
    if type(row["id"]) is not str or not 0 < len(row["id"]) <= 256:
        raise RenderLogError("api_payload")
    timestamp = nanoseconds(row["timestamp"])
    if not lo <= timestamp <= hi:
        raise RenderLogError("timestamp_scope")
    labels = row["labels"]
    if type(labels) is not list or len(labels) > 64:
        raise RenderLogError("labels")
    values: dict[str, str] = {}
    for label in labels:
        if (
            type(label) is not dict
            or type(label.get("name")) is not str
            or type(label.get("value")) is not str
            or len(label["name"]) > 64
            or len(label["value"]) > 1024
            or label["name"] in values
        ):
            raise RenderLogError("labels")
        values[label["name"]] = label["value"]
    if values.get("resource") != service or values.get("type") != "app":
        raise RenderLogError("resource_scope")
    message = row["message"]
    if type(message) is not str or any(c in message for c in ("\r", "\n", "\0")):
        return timestamp, None
    try:
        raw = message.encode("utf-8")
        if len(raw) > MAX_LINE_BYTES:
            return timestamp, None
        return timestamp, parse_record(raw).record
    except (Rejected, UnicodeError):
        return timestamp, None


def collect(
    reader: Reader, owner: str, service: str, start: str, end: str
) -> tuple[bytes, dict[str, int]]:
    lo, hi = nanoseconds(start), nanoseconds(end)
    params = {
        "ownerId": owner,
        "resource": service,
        "type": "app",
        "direction": "forward",
        "startTime": start,
        "endTime": end,
        "limit": str(PAGE_ROWS),
    }
    rows = rejected = pages = 0
    previous = lo
    records: list[str] = []
    while pages < MAX_PAGES:
        data = reader.get("/logs", params)
        pages += 1
        if (
            type(data) is not dict
            or type(data.get("logs")) is not list
            or type(data.get("hasMore")) is not bool
            or any(type(data.get(k)) is not str for k in ("nextStartTime", "nextEndTime"))
            or len(data["logs"]) > PAGE_ROWS
        ):
            raise RenderLogError("api_payload")
        rows += len(data["logs"])
        if rows > MAX_ROWS:
            raise RenderLogError("row_limit")
        for row in data["logs"]:
            timestamp, record = _message(row, service, lo, hi)
            if timestamp < previous:
                raise RenderLogError("timestamp_order")
            previous = timestamp
            if record is None:
                rejected += 1
            else:
                records.append(record)
        if not data["hasMore"]:
            reader.check()
            return ("\n".join(records) + ("\n" if records else "")).encode("ascii"), {
                "pages": pages,
                "api_rows": rows,
                "rejected_messages": rejected,
                "forwarded": len(records),
            }
        nxt, next_end = nanoseconds(data["nextStartTime"]), nanoseconds(data["nextEndTime"])
        if not data["logs"] or nxt <= lo:
            raise RenderLogError("cursor_stalled")
        if next_end != hi or nxt > hi or nxt < previous:
            raise RenderLogError("cursor_scope")
        if nxt > previous + 1:
            raise RenderLogError("cursor_gap")
        lo = nxt
        params.update(startTime=data["nextStartTime"], endTime=data["nextEndTime"])
    raise RenderLogError("page_limit")


def run_window(
    path: Path,
    owner: str,
    service: str,
    start: str,
    end: str,
    key: SecretStr,
    *,
    execute: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    _, _, recent = validate_window(owner, service, start, end)
    secret = key.get_secret_value()
    if not 8 <= len(secret) <= 512 or any(not 33 <= ord(c) <= 126 for c in secret):
        raise RenderLogError("configuration")
    with archive.connect(path):
        pass
    with (
        quiet_http(),
        httpx.Client(
            headers={"Authorization": "Bearer " + secret, "Accept-Encoding": "identity"},
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        ) as client,
    ):
        reader = Reader(client)
        data = reader.get("/services/" + service, cap=SERVICE_BODY)
        if (
            type(data) is not dict
            or data.get("id") != service
            or data.get("ownerId") != owner
            or data.get("type") != "web_service"
        ):
            raise RenderLogError("service_scope")
        batch, counters = collect(reader, owner, service, start, end)
    preflight, _ = archive.read_input(io.BytesIO(batch))
    if preflight.rejected != 0 or preflight.lines != counters["forwarded"]:
        raise RenderLogError("archive_invariant")
    counts = archive.ingest(path, io.BytesIO(batch), execute=execute)
    return {
        "adapter_rule_version": RULE,
        "archive_rule_version": archive.RULE_VERSION,
        "api_window_complete": True,
        "coverage_verified": False,
        "provenance": "schema_match_only",
        "recent_window": recent,
        "start": start,
        "end": end,
        **counters,
        "archive": counts,
    }


@contextmanager
def quiet_http() -> Iterator[None]:
    # Standalone CLI: cover descendants with their own DEBUG level/handlers too.
    old = logging.root.manager.disable
    try:
        logging.disable(max(old, logging.CRITICAL))
        yield
    finally:
        logging.disable(old)


def main(argv: list[str] | None = None) -> int:
    result: dict[str, Any] = {
        "adapter_rule_version": RULE,
        "api_window_complete": False,
        "coverage_verified": False,
    }
    code = 0
    try:
        parser = SafeParser(prog="python -m etl.operation_logs.render", allow_abbrev=False)
        for name in ("db", "owner-id", "service-id", "start", "end"):
            parser.add_argument("--" + name, required=True, type=Path if name == "db" else str)
        parser.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        result["mode"] = "execute" if args.execute else "dry_run"
        with quiet_http():
            result.update(
                run_window(
                    args.db,
                    args.owner_id,
                    args.service_id,
                    args.start,
                    args.end,
                    SecretStr(os.environ.get("RENDER_API_KEY", "")),
                    execute=args.execute,
                )
            )
        result["status"] = "ok"
    except ArgumentsError:
        result.update(status="failed", error="arguments")
        code = 2
    except (RenderLogError, archive.ArchiveError) as exc:
        result.update(status="failed", error=str(exc))
        code = 1
    except httpx.RequestError:
        result.update(status="failed", error="api_network")
        code = 1
    except sqlite3.Error:
        result.update(status="failed", error="archive_database")
        code = 1
    except KeyboardInterrupt:
        result.update(status="failed", error="interrupted")
        code = 130
    except Exception:
        result.update(status="failed", error="operation_failed")
        code = 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
