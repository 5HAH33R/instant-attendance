import os
import time
import threading


class InMemorySessionStore:
    """In-memory session store with TTL support (for local dev)."""

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
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]


def _create_session_store():
    """Create session store - Redis if credentials exist, in-memory otherwise."""
    redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
    redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

    if redis_url and redis_token:
        try:
            import upstash_redis
            print(f"Using Upstash Redis at {redis_url[:30]}...")
            return upstash_redis.Redis(url=redis_url, token=redis_token)
        except ImportError:
            print("upstash-redis not installed, falling back to in-memory store")
            return InMemorySessionStore()
        except Exception as e:
            print(f"Redis connection failed: {e}, falling back to in-memory store")
            return InMemorySessionStore()
    else:
        print("No Redis credentials found, using in-memory session store")
        return InMemorySessionStore()


# Singleton instance
session_store = _create_session_store()
