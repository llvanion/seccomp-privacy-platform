from __future__ import annotations

from collections import defaultdict
import time


class InMemoryRateLimit:
    def __init__(self, max_per_actor_action: int = 100, window_seconds: int = 3600) -> None:
        self.max_per_actor_action = max_per_actor_action
        self.window_seconds = window_seconds
        self._counter: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def hit(self, actor: str, action: str) -> tuple[bool, int, int]:
        key = (actor, action)
        count, window_start = self._counter[key]
        now = time.time()
        if now - window_start >= self.window_seconds:
            count = 0
            window_start = now
        count += 1
        self._counter[key] = (count, window_start)
        allowed = count <= self.max_per_actor_action
        return allowed, count, self.max_per_actor_action


class RedisRateLimit:
    def __init__(self, redis_url: str, max_per_actor_action: int = 100, window_seconds: int = 3600) -> None:
        import redis

        self.max_per_actor_action = max_per_actor_action
        self.window_seconds = window_seconds
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._redis.ping()

    def hit(self, actor: str, action: str) -> tuple[bool, int, int]:
        key = f"ratelimit:{actor}:{action}"
        pipe = self._redis.pipeline()
        pipe.incr(key, 1)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl is None or ttl < 0:
            self._redis.expire(key, self.window_seconds)
        used = int(count)
        allowed = used <= self.max_per_actor_action
        return allowed, used, self.max_per_actor_action


def build_rate_limiter(
    *,
    backend: str,
    redis_url: str,
    max_per_actor_action: int,
    window_seconds: int,
):
    if backend == "memory":
        return InMemoryRateLimit(
            max_per_actor_action=max_per_actor_action,
            window_seconds=window_seconds,
        )

    if backend == "redis":
        return RedisRateLimit(
            redis_url=redis_url,
            max_per_actor_action=max_per_actor_action,
            window_seconds=window_seconds,
        )

    try:
        return RedisRateLimit(
            redis_url=redis_url,
            max_per_actor_action=max_per_actor_action,
            window_seconds=window_seconds,
        )
    except Exception:
        return InMemoryRateLimit(
            max_per_actor_action=max_per_actor_action,
            window_seconds=window_seconds,
        )

