"""
Discrete-event virtual clock for offline engine tests.

Unlike a naive "advance a counter" fake sleep, this handles CONCURRENT
sleepers correctly (asyncio.gather of staggered lanes): each sleeper parks on
a heap keyed by its absolute wake time; the driver advances the clock to the
earliest waiter only when the event loop has no runnable work left.

Usage:
    from scripts._virtual_clock import VirtualClock
    clock = VirtualClock()          # patches asyncio.sleep + time.monotonic
    await clock.run(coro)           # drive a coroutine on virtual time
    clock.now_ms                    # current virtual ms
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import time

_ORIG_SLEEP = asyncio.sleep


class VirtualClock:
    def __init__(self) -> None:
        self.t_ms: float = 0.0
        self._waiters: list = []  # (target_ms, seq, future)
        self._seq = itertools.count()
        asyncio.sleep = self._sleep          # type: ignore[assignment]
        time.monotonic = lambda: self.t_ms / 1000.0  # type: ignore[assignment]

    @property
    def now_ms(self) -> int:
        return int(self.t_ms)

    def reset(self) -> None:
        self.t_ms = 0.0
        self._waiters.clear()

    async def _sleep(self, seconds, *a, **k):
        if seconds is None or seconds <= 0:
            await _ORIG_SLEEP(0)
            return
        fut = asyncio.get_event_loop().create_future()
        heapq.heappush(self._waiters, (self.t_ms + seconds * 1000, next(self._seq), fut))
        await fut

    async def run(self, coro) -> None:
        """Drive `coro` (and everything it spawns) to completion on virtual time."""
        task = asyncio.ensure_future(coro)
        while not task.done():
            # Drain all currently-runnable work before advancing time.
            for _ in range(50):
                await _ORIG_SLEEP(0)
            if task.done():
                break
            if self._waiters:
                target, _, fut = heapq.heappop(self._waiters)
                self.t_ms = max(self.t_ms, target)
                if not fut.done():
                    fut.set_result(None)
            else:
                await _ORIG_SLEEP(0)
        await task
