from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.security import decode_token


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _should_skip(self, path: str) -> bool:
        if not path.startswith("/api/"):
            return True
        for prefix in ["/api/v1/health", "/docs", "/redoc", "/openapi.json"]:
            if path.startswith(prefix):
                return True
        return False

    def _key_for(self, request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1].strip()
            try:
                payload = decode_token(token)
                user_id = str(payload.get("sub") or "")
                if user_id:
                    return f"user:{user_id}:{request.url.path}"
            except Exception:
                pass

        host = request.client.host if request.client else "unknown"
        return f"ip:{host}:{request.url.path}"

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or self._should_skip(request.url.path):
            return await call_next(request)

        now = time.time()
        window_seconds = 60
        limit = max(1, settings.rate_limit_per_minute)
        key = self._key_for(request)

        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = int(max(1, (bucket[0] + window_seconds) - now))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            bucket.append(now)
            remaining = max(0, limit - len(bucket))

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
