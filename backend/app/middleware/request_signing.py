from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings


class RequestSigningMiddleware(BaseHTTPMiddleware):
    def _should_skip(self, path: str) -> bool:
        if not path.startswith("/api/v1"):
            return True
        if path.startswith("/api/v1/auth/"):
            return True
        if path.startswith("/api/v1/health"):
            return True
        return False

    def _verify(self, *, timestamp: str, signature: str, body: bytes) -> bool:
        secret = settings.request_signing_secret.encode("utf-8")
        payload = timestamp.encode("utf-8") + b"." + body
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def dispatch(self, request: Request, call_next):
        if not settings.request_signing_enabled or self._should_skip(request.url.path):
            return await call_next(request)

        signature = request.headers.get("X-Signature")
        timestamp = request.headers.get("X-Signature-Timestamp")

        if not signature or not timestamp:
            return JSONResponse(status_code=401, content={"detail": "Missing request signature headers"})

        try:
            ts_int = int(timestamp)
        except ValueError:
            return JSONResponse(status_code=401, content={"detail": "Invalid signature timestamp"})

        now = int(time.time())
        if abs(now - ts_int) > settings.request_signing_max_age_seconds:
            return JSONResponse(status_code=401, content={"detail": "Expired signature timestamp"})

        body = await request.body()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive  # type: ignore[attr-defined]

        if not self._verify(timestamp=timestamp, signature=signature, body=body):
            return JSONResponse(status_code=401, content={"detail": "Invalid request signature"})

        request.state.signature_verified = True
        return await call_next(request)
