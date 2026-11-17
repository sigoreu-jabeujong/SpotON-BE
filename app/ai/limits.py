"""LLM 호출 시간 예산·재시도 대기·프로세스 내 요청 한도."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.ai.client import LlmError, LlmErrorKind
from app.core.config import Settings

# 공식 문서: 일일 요청 한도(RPD)는 태평양 시간 자정에 초기화된다.
QUOTA_DAY_ZONE = ZoneInfo("America/Los_Angeles")
MINUTE_WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RetryPolicy:
    """제한된 지수 백오프(full jitter)와 전체 시간 예산."""

    request_timeout: float
    time_budget: float
    max_retries: int
    base_delay: float
    max_delay: float

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        return cls(
            request_timeout=settings.llm_request_timeout,
            time_budget=settings.llm_time_budget,
            max_retries=settings.llm_max_retries,
            base_delay=settings.llm_backoff_base,
            max_delay=settings.llm_backoff_max,
        )

    def delay_cap(self, retry_index: int) -> float:
        """재시도 순번(0부터)의 최대 대기 시간: min(max, base × 2^순번)."""
        return min(self.max_delay, math.ldexp(self.base_delay, retry_index))

    def backoff(self, retry_index: int, rng: Callable[[], float]) -> float:
        """0 이상 delay_cap 이하의 무작위 대기 시간."""
        fraction = min(max(rng(), 0.0), 1.0)
        return fraction * self.delay_cap(retry_index)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RequestLimiter:
    """공급자 호출 시도마다 분당·일일 한도를 하나씩 소모한다.

    한 프로세스·한 이벤트 루프 기준이다. 여러 worker의 합계는 공급자 429로 방어한다.
    한도가 가득 차면 기다리지 않고 실패한다.
    """

    def __init__(
        self,
        *,
        per_minute: int | None,
        per_day: int | None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if per_minute is not None and per_minute < 1:
            raise ValueError("per_minute는 1 이상이어야 합니다")
        if per_day is not None and per_day < 1:
            raise ValueError("per_day는 1 이상이어야 합니다")
        self._per_minute = per_minute
        self._per_day = per_day
        self._monotonic = monotonic
        self._now = now
        self._recent: deque[float] = deque()
        self._day: date | None = None
        self._day_count = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> RequestLimiter:
        return cls(
            per_minute=settings.llm_requests_per_minute,
            per_day=settings.llm_requests_per_day,
        )

    def acquire(self) -> None:
        moment = self._monotonic()
        if self._per_day is not None:
            today = self._now().astimezone(QUOTA_DAY_ZONE).date()
            if today != self._day:
                self._day = today
                self._day_count = 0
            if self._day_count >= self._per_day:
                raise LlmError(LlmErrorKind.QUOTA_EXHAUSTED)
        if self._per_minute is not None:
            while self._recent and moment - self._recent[0] >= MINUTE_WINDOW_SECONDS:
                self._recent.popleft()
            if len(self._recent) >= self._per_minute:
                raise LlmError(LlmErrorKind.RATE_LIMITED)
            self._recent.append(moment)
        if self._per_day is not None:
            self._day_count += 1
