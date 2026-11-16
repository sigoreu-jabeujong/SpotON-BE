"""ASGI-loop-owned capacity leases and result-sharing, never lock-only regeneration."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class CapacityPool:
    def __init__(self, capacity: int):
        self.available = capacity
        self.changed = asyncio.Condition()

    def try_reserve(self, amount: int) -> bool:
        if amount > self.available:
            return False
        self.available -= amount
        return True

    async def release(self, amount: int = 1) -> None:
        # Restore capacity before any cancellation point; notification must also survive it.
        self.available += amount

        async def notify() -> None:
            async with self.changed:
                self.changed.notify_all()

        task = asyncio.create_task(notify())
        task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        await asyncio.shield(task)

    async def __aenter__(self) -> None:
        async with self.changed:
            await self.changed.wait_for(lambda: self.available > 0)
            self.available -= 1

    async def __aexit__(self, *_args: object) -> None:
        await self.release()


class ReportFlights(Generic[T]):
    def __init__(self) -> None:
        self.active: dict[str, tuple[asyncio.Task[T], int]] = {}

    async def run(self, key: str, generate: Callable[[], Awaitable[T]]) -> T:
        entry = self.active.get(key)
        if entry is None:

            async def invoke() -> T:
                return await generate()

            task: asyncio.Task[T] = asyncio.create_task(invoke())
            # Retrieve exceptions even if every HTTP waiter disconnects.
            task.add_done_callback(lambda t: None if t.cancelled() else t.exception())

            def finished(done: asyncio.Task[T]) -> None:
                current = self.active.get(key)
                if current is not None and current[0] is done:
                    self.active.pop(key, None)

            task.add_done_callback(finished)
            entry = (task, 0)
        task, users = entry
        self.active[key] = (task, users + 1)
        try:
            return await asyncio.shield(task)
        finally:
            current = self.active.get(key)
            if current is not None and current[0] is task:
                remaining = current[1] - 1
                if remaining:
                    self.active[key] = (task, remaining)
                else:
                    self.active.pop(key, None)
                    if not task.done():
                        task.cancel()
