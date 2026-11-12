"""API v1.2 §6 / data specification retention policy: allowlisted JSON events only."""

import json
import math
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from threading import Lock
from typing import Any, Literal, ParamSpec
from uuid import UUID, uuid4

EtlSource = Literal[
    "localdata", "market_areas", "market_stores", "market_sales", "market_changes", "living_pop"
]
Stage = Literal["import", "read_source", "collect", "preflight", "transform", "prepare", "persist"]
Status = Literal["started", "completed", "failed"]
API_PATHS = frozenset(
    {
        "/api/health",
        "/api/geocode",
        "/api/stores/history",
        "/api/stores/nearby",
        "/api/stores/snapshot",
        "/api/meta/data-range",
        "/api/market/activity",
        "/api/risk",
        "/api/risk/interpret",
        "/api/support-links",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
    }
)
COUNTS = frozenset(
    {
        "fetched",
        "accepted",
        "rejected_missing_key",
        "rejected_non_seoul",
        "duplicates",
        "transformed",
        "affected",
        "request_count",
        "source_rows",
        "rows",
        "excluded_rows",
        "inserted",
        "repaired",
        "grid_rows",
        "inserted_grids",
    }
)
QUALITY_FLAGS = frozenset(
    {
        "open_date_invalid",
        "close_date_invalid",
        "open_before_1960",
        "open_date_future",
        "close_date_future",
        "close_before_open",
        "status_missing",
        "status_unknown",
        "status_mismatch",
        "status_date_inconsistent",
        "area_invalid",
    }
)
POPULATION_QUALITY_COUNTS = frozenset(
    {
        "suppressed_rows",
        "missing_value_rows",
        "observed_zero_rows",
        "unlocated_rows",
        "multi_admin_groups",
        "multi_admin_rows",
    }
)
_WRITE_LOCK = Lock()
P = ParamSpec("P")


def new_id() -> str | None:
    try:
        return str(uuid4())
    except Exception:
        return None


def elapsed_ms(start: float) -> float | None:
    value = (time.monotonic() - start) * 1000
    return round(value, 3) if math.isfinite(value) and value >= 0 else None


def _emit(event: dict[str, object]) -> None:
    try:
        event = {"time": datetime.now(UTC).isoformat(), **event}
        line = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        if len(line.encode("utf-8")) > 4096:
            return
        with _WRITE_LOCK:
            sys.stderr.write(line)
            sys.stderr.flush()
    except Exception:
        # Observability must not replace an operation's result, error, or cancellation.
        pass


def api_event(
    *, path: str, status: int | None, duration: float | None, request_id: str | None, complete: bool
) -> None:
    parsed = _uuid(request_id)
    if parsed is not None and type(complete) is bool:
        _emit(
            {
                "event": "api_request",
                "path": next((known for known in API_PATHS if path == known), "unmatched"),
                "status_code": status if type(status) is int and 100 <= status <= 599 else None,
                "duration_ms": duration
                if duration is not None
                and type(duration) in (int, float)
                and math.isfinite(duration)
                and duration >= 0
                else None,
                "request_id": parsed,
                "response_complete": complete,
            }
        )


def llm_attempt(*, success: bool) -> None:
    if type(success) is bool:
        _emit({"event": "llm_http_attempt", "count": 1, "success": success})


def _counts(value: object, allowed: frozenset[str]) -> dict[str, int]:
    if type(value) is not dict:
        return {}
    return {
        key: value[key]
        for key in sorted(allowed)
        if type(value.get(key)) is int and 0 <= value[key] <= 2**63 - 1
    }


def _uuid(value: object) -> str | None:
    if type(value) is str and len(value) == 36:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return None


@dataclass(frozen=True)
class _Run:
    source: EtlSource
    run_id: str | None


_RUN: ContextVar[_Run | None] = ContextVar("operation_run", default=None)


def population_quality(counts: object) -> None:
    """Count-only source-day diagnostic; never an aggregation or import success claim."""
    try:
        run = _RUN.get()
        if run is None or run.source != "living_pop":
            return
        run_id = _uuid(run.run_id)
        if run_id is None:
            return
        valid = _counts(counts, POPULATION_QUALITY_COUNTS)
        complete = len(valid) == len(POPULATION_QUALITY_COUNTS)
        event: dict[str, object] = {
            "event": "etl_quality",
            "source": "living_pop",
            "run_id": run_id,
            "stage": "read_source",
            "status": "completed" if complete else "failed",
            "scope": "source_day_all_sources",
            "spatial_compatibility": "unverified",
            "aggregation_status": "pending",
        }
        if complete:
            event["counts"] = valid
        else:
            event["reason"] = "quality_summary_unavailable"
        _emit(event)
    except Exception:
        pass


def _etl_event(
    run: _Run,
    stage: Stage,
    status: Status,
    duration: float | None,
    result: dict[str, Any] | None = None,
) -> None:
    try:
        _etl_record(run, stage, status, duration, result)
    except Exception:
        pass


def _etl_record(
    run: _Run,
    stage: Stage,
    status: Status,
    duration: float | None,
    result: dict[str, Any] | None,
) -> None:
    if (
        run.run_id is None
        or run.source
        not in {
            "localdata",
            "market_areas",
            "market_stores",
            "market_sales",
            "market_changes",
            "living_pop",
        }
        or stage
        not in {"import", "read_source", "collect", "preflight", "transform", "prepare", "persist"}
        or status not in {"started", "completed", "failed"}
    ):
        return
    event: dict[str, object] = {
        "event": "etl_run" if stage == "import" else "etl_stage",
        "source": run.source,
        "run_id": run.run_id,
        "stage": stage,
        "status": status,
        "duration_ms": duration,
    }
    if status == "failed":
        event["reason"] = "operation_failed"
    if type(result) is dict:
        event["counts"] = _counts(result, COUNTS)
        event["quality_flags"] = _counts(result.get("flags"), QUALITY_FLAGS)
        for key in ("batch_id", "version_id"):
            parsed = _uuid(result.get(key))
            if parsed is not None:
                event[key] = parsed
        if type(result.get("mode")) is str and result["mode"] in ("write", "dry_run"):
            event["mode"] = result["mode"]
    _emit(event)


def logged_import(
    source: EtlSource,
) -> Callable[[Callable[P, dict[str, Any]]], Callable[P, dict[str, Any]]]:
    def decorate(function: Callable[P, dict[str, Any]]) -> Callable[P, dict[str, Any]]:
        @wraps(function)
        def run(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
            context = _Run(source, new_id())
            token = _RUN.set(context)
            start = time.monotonic()
            result = None
            complete = False
            try:
                _etl_event(context, "import", "started", None)
                result = function(*args, **kwargs)
                complete = True
                return result
            finally:
                try:
                    _etl_event(
                        context,
                        "import",
                        "completed" if complete else "failed",
                        elapsed_ms(start),
                        result,
                    )
                finally:
                    _RUN.reset(token)

        return run

    return decorate


@contextmanager
def etl_phase(stage: Stage) -> Iterator[None]:
    run = _RUN.get()
    start = time.monotonic()
    complete = False
    try:
        if run is not None:
            _etl_event(run, stage, "started", None)
        yield
        complete = True
    finally:
        if run is not None:
            _etl_event(run, stage, "completed" if complete else "failed", elapsed_ms(start))
