"""
Simple in-memory rate limiter for authentication endpoints.

Prevents brute-force password attacks by limiting login/register attempts
per IP address. Uses a sliding window counter stored in memory.

Not a replacement for a proper WAF, but sufficient for a LAN/VPN-only app.
"""

import logging
import time
from collections import defaultdict
from typing import Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Rate-limited path prefixes and their limits: (max_requests, window_seconds)
_RATE_LIMITS: Dict[str, Tuple[int, int]] = {
    "/api/auth/login": (5, 60),            # 5 attempts per minute
    "/api/auth/register": (3, 300),        # 3 registrations per 5 minutes
    "/api/auth/reset-password": (3, 300),  # 3 reset attempts per 5 minutes
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter for sensitive endpoints.

    Tracks request counts per (client_ip, path_prefix) in a dict.
    Stale entries are cleaned up periodically.

    Attributes:
        _counters: Dict mapping (ip, path) to list of request timestamps.
    """

    def __init__(self, app):
        super().__init__(app)
        # (ip, path_prefix) -> list of timestamps
        self._counters: Dict[Tuple[str, str], list] = defaultdict(list)
        self._last_cleanup = time.time()
        logger.info("RateLimitMiddleware active for auth endpoints")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request, respecting X-Forwarded-For."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _cleanup_stale(self) -> None:
        """Remove expired timestamps older than the largest window."""
        now = time.time()
        # Only clean up every 60 seconds to avoid overhead
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now

        max_window = max(w for _, w in _RATE_LIMITS.values())
        cutoff = now - max_window
        stale_keys = []
        for key, timestamps in self._counters.items():
            self._counters[key] = [t for t in timestamps if t > cutoff]
            if not self._counters[key]:
                stale_keys.append(key)
        for key in stale_keys:
            del self._counters[key]

    async def dispatch(self, request: Request, call_next) -> dict:
        """Check rate limits for auth endpoints before processing.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            Response from next handler, or 429 if rate limited.
        """
        # Only rate-limit POST requests to auth endpoints
        if request.method != "POST":
            return await call_next(request)

        path = request.url.path
        matched_prefix = None
        for prefix in _RATE_LIMITS:
            if path.startswith(prefix):
                matched_prefix = prefix
                break

        if matched_prefix is None:
            return await call_next(request)

        max_requests, window_seconds = _RATE_LIMITS[matched_prefix]
        client_ip = self._get_client_ip(request)
        key = (client_ip, matched_prefix)
        now = time.time()

        # Clean stale entries periodically
        self._cleanup_stale()

        # Remove timestamps outside the window
        self._counters[key] = [
            t for t in self._counters[key] if t > now - window_seconds
        ]

        if len(self._counters[key]) >= max_requests:
            retry_after = int(window_seconds - (now - self._counters[key][0]))
            logger.warning(
                f"Rate limit hit: {client_ip} on {matched_prefix} "
                f"({len(self._counters[key])}/{max_requests} in {window_seconds}s)"
            )
            return JSONResponse(
                status_code=429,
                content={"detail": f"Too many attempts. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)},
            )

        # Record this request
        self._counters[key].append(now)
        return await call_next(request)
