"""Strict receiver for the six allowlisted operation event shapes."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID

from app.core.operations import (
    API_PATHS,
    COUNTS,
    POPULATION_QUALITY_COUNTS,
    QUALITY_FLAGS,
    READINESS_REASONS,
    EtlSource,
    Stage,
    Status,
)

MAX_LINE_BYTES = 4096
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?\+00:00")


class Rejected(ValueError):
    """No source value is attached to validation errors."""


@dataclass(frozen=True, repr=False)
class Record:
    event_hash: str
    event_us: int
    event: str
    record: str


def epoch_us(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("utc_required")
    delta = value - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Rejected
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise Rejected


def _uuid(value: object) -> bool:
    if type(value) is not str or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _duration(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0 and math.copysign(1, value) > 0
    except (OverflowError, TypeError):
        return False


def _counts(value: object, allowed: frozenset[str], *, complete: bool = False) -> bool:
    return (
        type(value) is dict
        and (set(value) == allowed if complete else set(value) <= allowed)
        and all(type(v) is int and 0 <= v <= 2**63 - 1 for v in value.values())
    )


def parse_record(raw: bytes) -> Record:
    try:
        if len(raw) > MAX_LINE_BYTES:
            raise Rejected
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(data) is not dict or type(data.get("event")) is not str:
            raise Rejected
        stamp = data.get("time")
        if type(stamp) is not str or not TIME.fullmatch(stamp):
            raise Rejected
        event_time = datetime.fromisoformat(stamp)
        event = data["event"]
        required = {"time", "event"}
        optional: set[str] = set()
        valid = False
        if event == "api_request":
            required |= {"path", "status_code", "duration_ms", "request_id", "response_complete"}
            status = data.get("status_code")
            valid = (
                type(data.get("path")) is str
                and data["path"] in API_PATHS | {"unmatched"}
                and (status is None or type(status) is int and 100 <= status <= 599)
                and _duration(data.get("duration_ms"))
                and _uuid(data.get("request_id"))
                and type(data.get("response_complete")) is bool
            )
        elif event == "llm_http_attempt":
            required |= {"count", "success"}
            valid = (
                type(data.get("count")) is int
                and data["count"] == 1
                and type(data.get("success")) is bool
            )
        elif event == "readiness_probe":
            required |= {"path", "reason", "success", "duration_ms"}
            valid = (
                data.get("path") == "/api/ready"
                and type(data.get("reason")) is str
                and data["reason"] in READINESS_REASONS
                and type(data.get("success")) is bool
                and data["success"] == (data["reason"] == "ok")
                and _duration(data.get("duration_ms"))
            )
        elif event in {"etl_run", "etl_stage"}:
            required |= {"source", "run_id", "stage", "status", "duration_ms"}
            optional = {"counts", "quality_flags", "batch_id", "version_id", "mode"}
            if data.get("status") == "failed":
                required.add("reason")
            valid = (
                data.get("source") in get_args(EtlSource)
                and _uuid(data.get("run_id"))
                and data.get("stage") in get_args(Stage)
                and (data.get("stage") == "import") == (event == "etl_run")
                and data.get("status") in get_args(Status)
                and _duration(data.get("duration_ms"))
                and ("reason" not in required or data.get("reason") == "operation_failed")
                and ("counts" in data) == ("quality_flags" in data)
                and ("counts" not in data or _counts(data["counts"], COUNTS))
                and ("quality_flags" not in data or _counts(data["quality_flags"], QUALITY_FLAGS))
                and all(_uuid(data[k]) for k in ("batch_id", "version_id") if k in data)
                and ("mode" not in data or data["mode"] in ("write", "dry_run"))
            )
        elif event == "etl_quality":
            required |= {
                "source",
                "run_id",
                "stage",
                "status",
                "scope",
                "spatial_compatibility",
                "aggregation_status",
            }
            if data.get("status") == "completed":
                required.add("counts")
                valid = _counts(data.get("counts"), POPULATION_QUALITY_COUNTS, complete=True)
            elif data.get("status") == "failed":
                required.add("reason")
                valid = data.get("reason") == "quality_summary_unavailable"
            valid = (
                valid
                and data.get("source") == "living_pop"
                and _uuid(data.get("run_id"))
                and data.get("stage") == "read_source"
                and data.get("scope") == "source_day_all_sources"
                and data.get("spatial_compatibility") == "unverified"
                and data.get("aggregation_status") == "pending"
            )
        if not valid or not required <= data.keys() or not data.keys() <= required | optional:
            raise Rejected
        data["time"] = event_time.isoformat(timespec="microseconds")
        canonical = json.dumps(
            data, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
        return Record(
            hashlib.sha256(canonical.encode("ascii")).hexdigest(),
            epoch_us(event_time),
            event,
            canonical,
        )
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise Rejected from None
