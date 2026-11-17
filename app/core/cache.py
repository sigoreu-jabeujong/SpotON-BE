"""Process-local caches. Keys are opaque HMACs; values contain no raw query echo."""

import asyncio
import hashlib
import hmac
import json
import math
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import Lock

from app.core.config import Settings

CACHE_VERSION = "risk-ai-cache-v1"


@dataclass(frozen=True)
class _Entry:
    value: bytes = field(repr=False)
    expires: float


class ByteCache:
    def __init__(
        self, *, ttl: int, entries: int, max_bytes: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if (
            type(ttl) is not int
            or not 1 <= ttl <= 604800
            or type(entries) is not int
            or not 1 <= entries <= 4096
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 67108864
        ):
            raise ValueError("invalid cache limits")
        self._ttl = ttl
        self._limit = entries
        self._max_bytes = max_bytes
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._closed = False
        self._lock = Lock()

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= len(entry.value)

    def _now(self) -> float:
        now = self._clock()
        if not math.isfinite(now):
            raise ValueError("invalid cache clock")
        return now

    def get(self, key: str | None) -> bytes | None:
        if key is None:
            return None
        try:
            with self._lock:
                if self._closed:
                    return None
                entry = self._entries.get(key)
                if entry is None or entry.expires <= self._now():
                    self._remove(key)
                    self._misses += 1
                    return None
                self._entries.move_to_end(key)
                self._hits += 1
                return entry.value
        except Exception:
            return None

    def put(self, key: str | None, value: bytes) -> None:
        if key is None:
            return
        try:
            if type(value) is not bytes or len(value) > self._max_bytes:
                return
            with self._lock:
                if self._closed:
                    return
                now = self._now()
                for expired in [k for k, v in self._entries.items() if v.expires <= now]:
                    self._remove(expired)
                self._remove(key)
                while self._entries and (
                    len(self._entries) >= self._limit or self._bytes + len(value) > self._max_bytes
                ):
                    self._remove(next(iter(self._entries)))
                self._entries[key] = _Entry(value, now + self._ttl)
                self._bytes += len(value)
        except Exception:
            pass

    def discard(self, key: str) -> None:
        with self._lock:
            self._remove(key)

    def prune(self) -> None:
        try:
            with self._lock:
                now = self._now()
                for key in [k for k, entry in self._entries.items() if entry.expires <= now]:
                    self._remove(key)
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._entries.clear()
            self._bytes = 0

    def info(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": self._bytes,
                "hits": self._hits,
                "misses": self._misses,
            }


class CacheResources:
    def __init__(self, settings: Settings):
        self._enabled = settings.cache_enabled
        try:
            self._secret = secrets.token_bytes(32)
        except Exception:
            self._secret = b""
        self._closed = False
        self._sweeper: asyncio.Task[None] | None = None
        self.risk = ByteCache(
            ttl=settings.risk_cache_ttl_seconds,
            entries=settings.cache_max_entries,
            max_bytes=settings.cache_max_bytes,
        )
        self.ai = ByteCache(
            ttl=settings.ai_cache_ttl_seconds,
            entries=settings.cache_max_entries,
            max_bytes=settings.cache_max_bytes,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._secret) and not self._closed

    def key(self, domain: str, *parts: object) -> str | None:
        if not self.enabled:
            return None
        try:
            encoded = json.dumps(
                [CACHE_VERSION, domain, *parts],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            return hmac.new(self._secret, encoded, hashlib.sha256).hexdigest()
        except Exception:
            return None

    def close(self) -> None:
        self._closed = True
        self.risk.close()
        self.ai.close()

    def prune(self) -> None:
        for cache in (self.risk, self.ai):
            try:
                cache.prune()
            except Exception:
                pass

    async def _maintain(self) -> None:
        while self.enabled:
            await asyncio.sleep(1)
            self.prune()

    @asynccontextmanager
    async def maintenance(self) -> AsyncIterator[None]:
        task = None
        try:
            if self.enabled:
                task = self._sweeper = asyncio.create_task(self._maintain(), name="cache-sweeper")
            yield
        finally:
            # Close first: late worker results must not repopulate a shutting-down cache.
            self.close()
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelling():
                        raise


@dataclass
class _Flight:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    users: int = 0


class Flights:
    """Used only on the owning ASGI event loop, never by preparation threads."""

    def __init__(self) -> None:
        self._active: dict[str, _Flight] = {}

    @asynccontextmanager
    async def hold(self, key: str | None) -> AsyncIterator[bool]:
        if key is None:
            yield False
            return
        entry = self._active.setdefault(key, _Flight())
        entry.users += 1
        waited = entry.lock.locked()
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield waited
        finally:
            if acquired:
                entry.lock.release()
            entry.users -= 1
            if not entry.users:
                self._active.pop(key, None)
