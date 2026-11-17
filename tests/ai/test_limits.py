from datetime import UTC, datetime, timedelta

import pytest

from app.ai.client import LlmError, LlmErrorKind
from app.ai.limits import RequestLimiter, RetryPolicy
from app.core.config import Settings


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.mono = 1000.0
        self.wall = start

    def monotonic(self) -> float:
        return self.mono

    def now(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


def policy(**overrides: float) -> RetryPolicy:
    values: dict[str, float] = {
        "request_timeout": 10,
        "time_budget": 20,
        "max_retries": 2,
        "base_delay": 1,
        "max_delay": 8,
    }
    values.update(overrides)
    return RetryPolicy(
        request_timeout=values["request_timeout"],
        time_budget=values["time_budget"],
        max_retries=int(values["max_retries"]),
        base_delay=values["base_delay"],
        max_delay=values["max_delay"],
    )


def limiter(
    clock: FakeClock, *, per_minute: int | None = None, per_day: int | None = None
) -> RequestLimiter:
    return RequestLimiter(
        per_minute=per_minute,
        per_day=per_day,
        monotonic=clock.monotonic,
        now=clock.now,
    )


def kind_of(target: RequestLimiter) -> LlmErrorKind:
    with pytest.raises(LlmError) as raised:
        target.acquire()
    return raised.value.kind


@pytest.mark.parametrize(
    ("retry_index", "cap"),
    [(0, 1.0), (1, 2.0), (2, 4.0), (3, 8.0), (4, 8.0), (10, 8.0)],
)
def test_delay_cap_grows_exponentially_up_to_max(retry_index: int, cap: float) -> None:
    assert policy().delay_cap(retry_index) == cap


def test_backoff_is_full_jitter_within_cap() -> None:
    target = policy()
    assert target.backoff(2, lambda: 0.0) == 0.0
    assert target.backoff(2, lambda: 0.5) == 2.0
    assert target.backoff(2, lambda: 1.0) == 4.0
    assert target.backoff(5, lambda: 2.0) == 8.0
    assert target.backoff(5, lambda: -1.0) == 0.0


def test_policy_and_limiter_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_request_timeout=5,
        llm_time_budget=9,
        llm_max_retries=1,
        llm_backoff_base=0.5,
        llm_backoff_max=2,
        llm_requests_per_minute=3,
    )
    assert RetryPolicy.from_settings(settings) == RetryPolicy(
        request_timeout=5, time_budget=9, max_retries=1, base_delay=0.5, max_delay=2
    )
    created = RequestLimiter.from_settings(settings)
    for _ in range(3):
        created.acquire()
    assert kind_of(created) is LlmErrorKind.RATE_LIMITED


def test_no_limits_means_unlimited() -> None:
    target = limiter(FakeClock(datetime(2026, 11, 11, tzinfo=UTC)))
    for _ in range(1000):
        target.acquire()


def test_per_minute_limit_uses_sliding_window() -> None:
    clock = FakeClock(datetime(2026, 11, 11, tzinfo=UTC))
    target = limiter(clock, per_minute=2)
    target.acquire()
    clock.advance(30)
    target.acquire()
    assert kind_of(target) is LlmErrorKind.RATE_LIMITED
    clock.advance(29.9)
    assert kind_of(target) is LlmErrorKind.RATE_LIMITED
    clock.advance(0.1)
    target.acquire()
    assert kind_of(target) is LlmErrorKind.RATE_LIMITED


def test_rejected_minute_request_does_not_consume_daily_quota() -> None:
    clock = FakeClock(datetime(2026, 11, 11, tzinfo=UTC))
    target = limiter(clock, per_minute=1, per_day=2)
    target.acquire()
    assert kind_of(target) is LlmErrorKind.RATE_LIMITED
    clock.advance(60)
    target.acquire()
    clock.advance(60)
    assert kind_of(target) is LlmErrorKind.QUOTA_EXHAUSTED


def test_daily_quota_resets_at_pacific_midnight() -> None:
    # 2026-11-11 07:59:59 UTC = 2026-11-10 23:59:59 PST (UTC-8)
    clock = FakeClock(datetime(2026, 11, 11, 7, 59, 58, tzinfo=UTC))
    target = limiter(clock, per_day=1)
    target.acquire()
    clock.advance(1)
    assert kind_of(target) is LlmErrorKind.QUOTA_EXHAUSTED
    clock.advance(1)
    target.acquire()
    assert kind_of(target) is LlmErrorKind.QUOTA_EXHAUSTED


def test_utc_midnight_does_not_reset_daily_quota() -> None:
    clock = FakeClock(datetime(2026, 11, 11, 23, 59, 59, tzinfo=UTC))
    target = limiter(clock, per_day=1)
    target.acquire()
    clock.advance(2)
    assert kind_of(target) is LlmErrorKind.QUOTA_EXHAUSTED


@pytest.mark.parametrize("field", ["per_minute", "per_day"])
def test_limiter_rejects_non_positive_limits(field: str) -> None:
    with pytest.raises(ValueError):
        RequestLimiter(**{"per_minute": None, "per_day": None, field: 0})
