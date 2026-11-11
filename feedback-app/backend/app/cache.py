"""Small, bounded read cache. Authentication is always checked before a hit."""
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from time import monotonic


@dataclass(frozen=True)
class CachedResponse:
    body: bytes
    media_type: str
    expires_at: float


class ReadCache:
    def __init__(self, max_entries: int = 256, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.entries: OrderedDict[tuple, CachedResponse] = OrderedDict()
        self.lock = RLock()
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.size = 0
        self.generation = 0

    def get(self, key: tuple) -> CachedResponse | None:
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= monotonic():
                self.size -= len(self.entries.pop(key).body)
                return None
            self.entries.move_to_end(key)
            return entry

    def put(self, key: tuple, body: bytes, media_type: str, ttl: int, generation: int) -> None:
        with self.lock:
            if ttl <= 0 or generation != self.generation or len(body) > self.max_bytes:
                return
            if key in self.entries:
                self.size -= len(self.entries.pop(key).body)
            self.entries[key] = CachedResponse(body, media_type, monotonic() + ttl)
            self.size += len(body)
            while len(self.entries) > self.max_entries or self.size > self.max_bytes:
                _, entry = self.entries.popitem(last=False)
                self.size -= len(entry.body)

    def invalidate(self) -> None:
        with self.lock:
            self.generation += 1
            self.entries.clear()
            self.size = 0


read_cache = ReadCache()
