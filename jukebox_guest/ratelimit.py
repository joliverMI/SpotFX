"""
Rate limits for the guest app: token buckets, one per (kind, key), in
memory. A bucket holds `burst` taps and refills at `rate` a second; a tap
on an empty bucket is refused with how long until the next one. Memory is
bounded: past MAX_KEYS buckets, the ones idle longest are dropped (a full
bucket costs nothing to forget).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

MAX_KEYS = 5000


@dataclass(frozen=True)
class Limit:
    rate: float          # taps a second, refilled
    burst: float         # the most held at once


class RateLimiter:
    def __init__(self, limits: dict[str, Limit], clock: Callable[[], float] = time.monotonic):
        self.limits = limits
        self.clock = clock
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}   # (tokens, at)

    def take(self, kind: str, key: str) -> float:
        """0.0 = allowed (one tap taken); otherwise the seconds to wait."""
        lim = self.limits[kind]
        now = self.clock()
        tokens, at = self._buckets.get((kind, key), (lim.burst, now))
        tokens = min(lim.burst, tokens + (now - at) * lim.rate)
        if tokens < 1.0:
            self._buckets[(kind, key)] = (tokens, now)
            return (1.0 - tokens) / lim.rate if lim.rate > 0 else 60.0
        self._buckets[(kind, key)] = (tokens - 1.0, now)
        if len(self._buckets) > MAX_KEYS:
            for k, _ in sorted(self._buckets.items(), key=lambda kv: kv[1][1])[: MAX_KEYS // 5]:
                self._buckets.pop(k, None)
        return 0.0
