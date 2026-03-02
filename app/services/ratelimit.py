from __future__ import annotations

from collections import defaultdict


class InMemoryRateLimit:
    def __init__(self, max_per_actor_action: int = 100) -> None:
        self.max_per_actor_action = max_per_actor_action
        self._counter: dict[tuple[str, str], int] = defaultdict(int)

    def hit(self, actor: str, action: str) -> tuple[bool, int, int]:
        key = (actor, action)
        self._counter[key] += 1
        used = self._counter[key]
        allowed = used <= self.max_per_actor_action
        return allowed, used, self.max_per_actor_action
