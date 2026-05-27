import time
import threading


class SessionStore:
    """In-memory session store with TTL support.

    Same interface as upstash-redis for drop-in replacement in local dev.
    """

    def __init__(self):
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def setex(self, key: str, value: str, seconds: int) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + seconds)

    def cleanup(self) -> None:
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]


# Singleton instance
session_store = SessionStore()
