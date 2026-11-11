import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.cache import ByteCache, CacheResources, Flights
from app.core.config import Settings
from app.services.risk_cache import load_risk, query_parts, risk_key, save_risk, snapshot_token
from tests.ai.context_helpers import query, response


def test_ttl_lru_byte_budget_and_close():
    clock = Mock(return_value=0.0)
    cache = ByteCache(ttl=10, entries=2, max_bytes=5, clock=clock)
    cache.put("a", b"aa")
    cache.put("b", b"bb")
    assert cache.get("a") == b"aa"
    cache.put("c", b"ccc")
    assert cache.get("b") is None
    assert cache.get("a") == b"aa"
    cache.put("huge", b"123456")
    assert cache.info()["entries"] == 2 and cache.info()["bytes"] == 5
    clock.return_value = 9.999
    assert cache.get("a") == b"aa"
    clock.return_value = 10.0
    assert cache.get("a") is None and cache.get("c") is None
    cache.put("x", b"x")
    cache.put("x", b"xx")
    assert cache.info()["bytes"] == 2
    cache.close()
    cache.put("later", b"secret")
    assert cache.info()["entries"] == cache.info()["bytes"] == 0
    assert cache.get("x") is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), RuntimeError("clock")])
def test_cache_clock_failure_is_miss(bad):
    clock = Mock(return_value=0.0)
    cache = ByteCache(ttl=1, entries=1, max_bytes=10, clock=clock)
    cache.put("key", b"safe")
    if isinstance(bad, Exception):
        clock.side_effect = bad
    else:
        clock.return_value = bad
    assert cache.get("key") is None
    cache.put("other", b"safe")
    assert cache.info()["entries"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_cache_ttl_seconds", 0),
        ("risk_cache_ttl_seconds", 604801),
        ("ai_cache_ttl_seconds", 0),
        ("ai_cache_ttl_seconds", 604801),
        ("cache_max_entries", 0),
        ("cache_max_entries", 4097),
        ("cache_max_bytes", 1023),
        ("cache_max_bytes", 67108865),
    ],
)
def test_invalid_settings_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_opaque_per_app_keys_failure_and_disable(monkeypatch):
    a, b = CacheResources(Settings(_env_file=None)), CacheResources(Settings(_env_file=None))
    key = a.key("risk", {"lat": 37.56789123, "secret": "private-canary"})
    assert len(key) == 64 and key != b.key("risk", {"lat": 37.56789123, "secret": "private-canary"})
    assert "private-canary" not in key + repr(a)
    assert a.key("risk", float("nan")) is None
    assert a.key("risk", object()) is None
    assert a.key("risk", 1) != a.key("ai", 1)
    assert a.key("risk", {"a": 1, "b": 2}) == a.key("risk", {"b": 2, "a": 1})
    a.close()
    assert not a.enabled and a.key("risk", 1) is None
    assert not CacheResources(Settings(_env_file=None, cache_enabled=False)).enabled
    monkeypatch.setattr("app.core.cache.secrets.token_bytes", Mock(side_effect=OSError))
    assert not CacheResources(Settings(_env_file=None)).enabled


@pytest.mark.parametrize(
    "changes",
    [
        {"lat": 37.56789124},
        {"lng": 126.98765433},
        {"radius": 300},
        {"category": "restaurant"},
        {"as_of": "2026-11"},
        {"area": "lt33"},
        {"franchise": "franchise"},
        {"include_unknown_area": False},
        {"include_unknown_franchise": False},
        {"include": "market_change"},
    ],
)
def test_each_query_dimension_separates_keys(changes):
    assert query_parts(query()) != query_parts(query(**changes))


def test_key_normalization_and_risk_codec_copy():
    config = Settings(_env_file=None)
    cache = CacheResources(config)
    first = query(category="restaurant", sub_category="korean,chinese")
    second = query(category="restaurant", sub_category="chinese,korean")
    key = risk_key(cache, "view", first, config, "rule")
    assert key == risk_key(cache, "view", second, config, "rule")
    assert key != risk_key(cache, "view2", first, config, "rule")
    assert key != risk_key(cache, "view", first, config, "rule2")
    assert query_parts(query()) == query_parts(query(sub_category="cafe"))
    assert query_parts(query(include_unknown=True)) == query_parts(
        query(include_unknown_area=True, include_unknown_franchise=True)
    )
    expected = response(first)
    save_risk(cache, key, expected)
    encoded = cache.risk.get(key)
    assert b"37.56789123" not in encoded and b'"query"' not in encoded
    result = load_risk(cache, key, second)
    assert result.model_dump() == response(second).model_dump()
    result.data.flags.missing.clear()
    assert load_risk(cache, key, first).model_dump() == expected.model_dump()
    cache.risk.put(key, b'{"broken":true}')
    assert load_risk(cache, key, first) is None
    assert cache.risk.info()["entries"] == 0


def test_snapshot_only_supported_session_and_sql_error_not_hidden():
    cache = CacheResources(Settings(_env_file=None))
    row = (
        True,
        True,
        True,
        "private-database-canary",
        "role",
        "boot",
        "public",
        "UTC",
        "ISO, MDY",
        "1",
        "1:2:",
    )
    session = Mock()
    session.execute.return_value.one.return_value = row
    token = snapshot_token(session, cache)
    assert len(token) == 64 and "private-database-canary" not in token
    for index in range(3):
        session.execute.return_value.one.return_value = (*row[:index], False, *row[index + 1 :])
        assert snapshot_token(session, cache) is None
    session.execute.side_effect = SQLAlchemyError("private-canary")
    with pytest.raises(SQLAlchemyError):
        snapshot_token(session, cache)
    disabled = CacheResources(Settings(_env_file=None, cache_enabled=False))
    assert snapshot_token(session, disabled) is None


def test_flights_waiter_and_owner_cancellation_cleanup():
    async def run():
        flights = Flights()
        entered, release = asyncio.Event(), asyncio.Event()

        async def owner():
            async with flights.hold("key") as waited:
                assert not waited
                entered.set()
                await release.wait()

        task = asyncio.create_task(owner())
        await entered.wait()

        async def waiter():
            async with flights.hold("key"):
                pytest.fail("cancelled waiter entered")

        waiting = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert len(flights._active) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert flights._active == {}
        async with flights.hold("key") as waited:
            assert not waited
        async with flights.hold(None) as waited:
            assert not waited
        assert flights._active == {}

    asyncio.run(run())


def test_prune_idle_expiry_boundary_and_lru_accounting():
    clock = Mock(return_value=0.0)
    cache = ByteCache(ttl=10, entries=2, max_bytes=5, clock=clock)
    cache.put("old", b"old")
    clock.return_value = 5.0
    cache.put("new", b"nn")
    assert cache.get("old") == b"old"
    clock.return_value = 9.999
    cache.prune()
    assert cache.info()["entries"] == 2
    clock.return_value = 10.0
    cache.prune()
    assert cache.info()["entries"] == 1 and cache.info()["bytes"] == 2
    assert cache.get("new") == b"nn" and cache.get("old") is None
    clock.return_value = 15.0
    cache.prune()
    assert cache.info()["entries"] == cache.info()["bytes"] == 0


def test_sweeper_runs_without_requests_and_isolates_cache_failure(monkeypatch):
    async def run():
        cache = CacheResources(Settings(_env_file=None))
        clock = Mock(return_value=0.0)
        cache.ai._clock = clock
        cache.ai.put("opaque", b"selection")
        clock.return_value = 300.0
        monkeypatch.setattr(cache.risk, "prune", Mock(side_effect=RuntimeError("private-canary")))
        slept = []

        async def tick(seconds):
            slept.append(seconds)
            if len(slept) == 2:
                assert cache.ai.info()["entries"] == 0
                cache.close()

        monkeypatch.setattr("app.core.cache.asyncio.sleep", tick)
        await cache._maintain()
        assert slept == [1, 1] and cache.risk.prune.call_count == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "enabled,fail,cancel",
    [(True, False, False), (False, False, False), (True, True, False), (True, False, True)],
)
def test_maintenance_lifecycle_closes_on_error_and_preserves_cancellation(enabled, fail, cancel):
    async def run():
        cache = CacheResources(Settings(_env_file=None, cache_enabled=enabled))

        async def lifespan():
            async with cache.maintenance():
                assert (cache._sweeper is not None) is enabled
                cache.ai.put("key", b"selection")
                if fail:
                    raise ValueError("synthetic-startup-failure")
                if cancel:
                    await asyncio.Event().wait()

        task = asyncio.create_task(lifespan())
        await asyncio.sleep(0)
        if cancel:
            task.cancel()
        if fail or cancel:
            with pytest.raises(asyncio.CancelledError if cancel else ValueError):
                await task
        else:
            await task
        assert cache._sweeper is None or cache._sweeper.done()
        assert not cache.enabled
        cache.close()
        cache.ai.put("late", b"late")
        assert cache.ai.info()["entries"] == 0

    asyncio.run(run())


def test_concurrent_prune_and_cache_accounting():
    cache = ByteCache(ttl=1, entries=8, max_bytes=32)

    def worker(n):
        for i in range(50):
            cache.put(str((n + i) % 20), b"abcd")
            cache.get(str(i % 20))
            cache.prune()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(worker, range(8)))
    info = cache.info()
    assert 0 <= info["entries"] <= 8 and info["bytes"] == info["entries"] * 4
