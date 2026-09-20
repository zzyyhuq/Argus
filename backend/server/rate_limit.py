"""Per-client rate limiting for research requests.

This protects the *server's* search quota, not the visitor's. A visitor who
supplies their own Tavily key spends their own credits and is not limited;
everyone else shares the server's allowance, which is small -- Tavily's free
tier is 1000 searches/month and one research issues 4-8 of them, so a few dozen
visitors could exhaust it in an afternoon.

Deliberately in-memory and per-process: the app runs a single uvicorn worker
(`Dockerfile` WORKERS default 1, `main.py` plain `uvicorn.run`), so a shared
store would be premature. If that ever changes, this needs to move to Redis or
similar -- process-local counters would each enforce their own limit.
"""

import asyncio
import os
import time
from typing import Dict, List, Tuple


class RateLimiter:
    """Sliding-window request counter keyed by client identity."""

    def __init__(self, limit: int, window_seconds: int = 3600):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> Tuple[bool, int]:
        """Record a request for ``key``.

        Args:
            key: Client identity (see ``client_key``).

        Returns:
            ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is 0
            when the request is allowed.
        """
        if self.limit <= 0:  # 0 disables limiting entirely
            return True, 0

        now = time.monotonic()
        cutoff = now - self.window_seconds

        async with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False, int(hits[0] + self.window_seconds - now) + 1

            hits.append(now)
            self._hits[key] = hits

            # Drop keys with no live hits so the map does not grow without bound
            # as visitors come and go.
            if len(self._hits) > 1024:
                self._hits = {k: v for k, v in self._hits.items() if v}

            return True, 0


def client_key(websocket) -> str:
    """Identify the caller for rate-limiting purposes.

    NOTE: this is the *direct peer* address. Behind a reverse proxy (nginx,
    Cloudflare, ...) every visitor shares the proxy's IP and would be limited
    as one client -- at which point this must read a trusted X-Forwarded-For
    instead.
    """
    client = getattr(websocket, "client", None)
    return getattr(client, "host", None) or "unknown"


def build_limiter(env_var: str = "RATE_LIMIT_PER_HOUR", default: int = 3) -> RateLimiter:
    """Build a limiter from an environment variable.

    Args:
        env_var: Name of the environment variable holding the hourly limit.
        default: Used when the variable is unset or not an integer.

    Returns:
        A limiter with that limit, or an unlimited one when the value is <= 0.
    """
    raw = os.getenv(env_var, str(default)).strip()
    try:
        limit = int(raw)
    except ValueError:
        limit = default
    return RateLimiter(limit)
