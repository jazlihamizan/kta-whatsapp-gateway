"""Shared middleware utilities: rate limiting (R6) and client IP extraction."""
import time
import logging
from collections import defaultdict
from threading import Lock
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.metrics import RATE_LIMITED

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# R6: Rate Limiting - In-memory, per-IP, sliding window
# NOTE: This is a simple in-memory rate limiter suitable for single-instance
# development/testing. For distributed/production use, replace with a
# Redis-backed sliding window rate limiter (e.g. using redis-py + Lua scripts).
# ---------------------------------------------------------------------------
class SlidingWindowRateLimiter:
    """In-memory sliding-window rate limiter (not distributed)."""

    def __init__(self, requests_per_minute: int = 60, burst: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.window_ms = 60_000
        self._store: dict = defaultdict(list)  # ip -> list of timestamps (ms)
        self._lock = Lock()

    def is_allowed(self, ip: str) -> bool:
        """Return True if request from ip is allowed."""
        now_ms = int(time.time() * 1000)
        window_start = now_ms - self.window_ms

        with self._lock:
            # Prune old entries
            self._store[ip] = [ts for ts in self._store[ip] if ts > window_start]

            count = len(self._store[ip])
            if count >= self.requests_per_minute:
                return False

            # Burst: first `burst` requests always allowed
            if count < self.burst:
                self._store[ip].append(now_ms)
                return True

            self._store[ip].append(now_ms)
            return True

    def reset(self, ip: str = None):
        """Reset rate limit state for a specific ip or all ips."""
        with self._lock:
            if ip:
                self._store.pop(ip, None)
            else:
                self._store.clear()


# Global rate limiter instance
_rate_limiter = SlidingWindowRateLimiter(
    requests_per_minute=settings.rate_limit_requests_per_minute,
    burst=settings.rate_limit_burst,
)


def get_client_ip(request: Request) -> str:
    """Extract client IP, checking X-Forwarded-For first."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> Optional[JSONResponse]:
    """
    Check rate limit for current request.

    Returns:
        None if allowed (request can proceed).
        JSONResponse(429) if rate limited.
    """
    if not settings.rate_limit_enabled:
        return None

    ip = get_client_ip(request)
    if not _rate_limiter.is_allowed(ip):
        logger.warning(f"Rate limit exceeded for IP: {ip}")
        # G5: Track rate limit hit (endpoint inferred from call site)
        RATE_LIMITED.labels(endpoint="webhook").inc()
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": "60"}
        )
    return None


def reset_rate_limiter(ip: str = None):
    """Reset rate limit state (for testing)."""
    _rate_limiter.reset(ip)