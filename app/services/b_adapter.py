from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass
class LocalIndex:
    values_by_key: dict[str, list[str]] = field(default_factory=dict)


class BAdapter:
    def __init__(self) -> None:
        self._indices: dict[str, LocalIndex] = {}

    def build_index(self, index_name: str, records: list[dict]) -> int:
        idx = LocalIndex()
        for item in records:
            keys = item.get("keys", [])
            values = item.get("values", [])
            for k in keys:
                idx.values_by_key.setdefault(k, []).extend(values)
        self._indices[index_name] = idx
        return sum(len(v) for v in idx.values_by_key.values())

    def search(self, index_name: str, keyword: str) -> tuple[list[str], float]:
        started = time.perf_counter()
        idx = self._indices.get(index_name, LocalIndex())
        results = idx.values_by_key.get(keyword, [])
        latency_ms = (time.perf_counter() - started) * 1000
        return results, latency_ms
