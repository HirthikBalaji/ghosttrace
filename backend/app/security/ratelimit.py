"""Rate limiting for expensive operations.

Primary: a fixed one-minute window counter in FalkorDB's own Redis keyspace (`INCR` + `EXPIRE`), shared by every
API replica. Fallback when that is unavailable: an in-process token bucket (per replica, reset on restart).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, per_minute: int, redis: Any | None = None):
        self.per_minute = per_minute
        self.rate = per_minute / 60.0
        self.cap = float(per_minute)
        self.redis = redis
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def _shared(self, key: str, cost: float) -> bool | None:
        if self.redis is None:
            return None
        try:
            window = int(time.time() // 60)
            k = f"gt:ratelimit:{key}:{window}"
            pipe = self.redis.pipeline()
            pipe.incrby(k, int(max(1, cost)))
            pipe.expire(k, 120)
            count = int(pipe.execute()[0])
            return count <= self.per_minute
        except Exception:
            return None  # degrade to the local bucket rather than failing open or closed on infra errors

    def check(self, key: str, cost: float = 1.0) -> None:
        shared = self._shared(key, cost)
        if shared is False:
            raise HTTPException(status_code=429, detail="rate limit exceeded for expensive operation")
        if shared is True:
            return
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens < cost:
                self.buckets[key] = (tokens, now)
                raise HTTPException(status_code=429, detail="rate limit exceeded for expensive operation")
            self.buckets[key] = (tokens - cost, now)
