from __future__ import annotations

from dataclasses import dataclass

from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.tenant_membership import TenantMembership
from app.models.user import User


@dataclass(frozen=True)
class MCPAuthContext:
    tenant_id: str
    user_id: str
    role: str
    membership_id: str


class MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.scope.get("path", "")
        if path == "/api/v1/mcp":
            request.scope["path"] = "/api/v1/mcp/"
            request.scope["raw_path"] = b"/api/v1/mcp/"
            path = "/api/v1/mcp/"

        if not path.startswith("/api/v1/mcp"):
            return await call_next(request)

        auth_header = str(request.headers.get("Authorization") or "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token)
        except ValueError:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

        if payload.get("type") != "access":
            return JSONResponse(status_code=401, content={"detail": "Invalid access token"})

        user_id = str(payload.get("sub") or "").strip()
        tenant_id = str(request.headers.get("X-Tenant-ID") or payload.get("tenant_id") or "").strip()
        if not user_id or not tenant_id:
            return JSONResponse(status_code=400, content={"detail": "Tenant context is required"})

        db_factory = getattr(request.app.state, "db_session_factory", SessionLocal)
        db = db_factory()
        try:
            user = db.get(User, user_id)
            if not user or not user.is_active:
                return JSONResponse(status_code=401, content={"detail": "Inactive user"})

            membership = db.execute(
                select(TenantMembership).where(
                    TenantMembership.user_id == user_id,
                    TenantMembership.tenant_id == tenant_id,
                )
            ).scalar_one_or_none()
            if not membership:
                return JSONResponse(status_code=403, content={"detail": "No access to tenant"})

            request.state.mcp_auth = MCPAuthContext(
                tenant_id=tenant_id,
                user_id=user_id,
                role=membership.role,
                membership_id=membership.id,
            )
        finally:
            db.close()

        return await call_next(request)
