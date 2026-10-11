"""In-process token-bucket rate limiter for expensive operations (local equivalent of a gateway limit)."""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.cap = float(per_minute)
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str, cost: float = 1.0) -> None:
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens < cost:
                self.buckets[key] = (tokens, now)
                raise HTTPException(status_code=429, detail="rate limit exceeded for expensive operation")
            self.buckets[key] = (tokens - cost, now)
