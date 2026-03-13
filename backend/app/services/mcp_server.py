from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.config import settings
from app.db.session import SessionLocal
from app.middleware.mcp_auth import MCPAuthContext
from app.services.audit import audit_event
from app.services.connectors.google_service import (
    create_contact,
    create_event,
    delete_contact,
    delete_event,
    get_contact,
    get_primary_account,
    list_contacts,
    list_events,
    list_gmail_messages,
    list_user_accounts,
    read_gmail_message,
    search_contacts,
    send_gmail_message,
    update_contact,
    update_event,
)
from app.services.document_indexing import hybrid_search_chunks

logger = structlog.get_logger(__name__)

GMAIL_READ_SCOPES = {
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
}
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_WRITE_SCOPES = {
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
}
CONTACTS_READ_SCOPES = {
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts",
}
CONTACTS_WRITE_SCOPE = "https://www.googleapis.com/auth/contacts"

MUTATING_TOOLS = {
    "email.send_draft",
    "calendar.create",
    "calendar.update",
    "calendar.delete",
    "contacts.create",
    "contacts.update",
    "contacts.delete",
}


def _host_patterns_from_url(url: str | None) -> list[str]:
    if not url:
        return []
    parsed = urlparse(url)
    host = parsed.netloc.strip()
    if not host:
        return []
    if ":" in host:
        return [host]
    return [host, f"{host}:*"]


def _build_transport_security_settings() -> TransportSecuritySettings:
    allowed_hosts = [
        *_host_patterns_from_url(settings.api_base_url),
        *_host_patterns_from_url(settings.ui_base_url),
        "localhost:*",
        "127.0.0.1:*",
        "[::1]:*",
    ]
    allowed_origins = [
        settings.api_base_url,
        settings.ui_base_url,
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
        "https://localhost:*",
        "https://127.0.0.1:*",
        "https://[::1]:*",
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(filter(None, allowed_hosts))),
        allowed_origins=list(dict.fromkeys(filter(None, allowed_origins))),
    )


@dataclass(frozen=True)
class MCPGoogleAccountContext:
    id: str
    label: str | None
    email: str | None
    scopes: list[str]
    gmail_enabled: bool
    calendar_enabled: bool
    contacts_enabled: bool
    enabled: bool
    connected: bool
    connector: Any


@dataclass(frozen=True)
class MCPRequestContext:
    auth: MCPAuthContext
    request: Request


mcp_server = FastMCP(
    name="CentraCortex MCP",
    instructions=(
        "CentraCortex exposes tenant-scoped business tools for email, calendar, contacts, and knowledge retrieval. "
        "Mutating tools default to preview mode and require execute=true for real side effects."
    ),
    streamable_http_path="/",
    transport_security=_build_transport_security_settings(),
)


@contextmanager
def _db_session(request: Request) -> Session:
    db_factory = getattr(request.app.state, "db_session_factory", SessionLocal)
    db = db_factory()
    try:
        yield db
    finally:
        db.close()


def _create_session_manager() -> StreamableHTTPSessionManager:
    return StreamableHTTPSessionManager(
        app=mcp_server._mcp_server,  # noqa: SLF001 - SDK does not expose a public constructor for mounted lifespan control.
        event_store=None,
        retry_interval=None,
        json_response=mcp_server.settings.json_response,
        stateless=mcp_server.settings.stateless_http,
        security_settings=mcp_server.settings.transport_security,
    )


def _ensure_session_manager() -> StreamableHTTPSessionManager:
    manager = getattr(mcp_server, "_session_manager", None)
    if manager is None:
        manager = _create_session_manager()
        mcp_server._session_manager = manager  # noqa: SLF001 - see _create_session_manager note.
    return manager


class MountedMCPASGIApp:
    async def __call__(self, scope, receive, send) -> None:
        await StreamableHTTPASGIApp(_ensure_session_manager())(scope, receive, send)


def get_mcp_asgi_app() -> MountedMCPASGIApp:
    return MountedMCPASGIApp()


async def start_mcp_server() -> Any:
    manager = _create_session_manager()
    mcp_server._session_manager = manager  # noqa: SLF001 - see _create_session_manager note.
    cm = manager.run()
    await cm.__aenter__()
    return cm


async def stop_mcp_server(cm: Any | None) -> None:
    if cm is not None:
        await cm.__aexit__(None, None, None)
    mcp_server._session_manager = None  # noqa: SLF001 - reset between app lifecycles/tests.


def _request_context(ctx: Context) -> MCPRequestContext:
    request = ctx.request_context.request
    if request is None:
        raise ValueError("MCP request context is unavailable")

    auth = getattr(request.state, "mcp_auth", None)
    if not isinstance(auth, MCPAuthContext):
        raise ValueError("MCP request is not authenticated")

    return MCPRequestContext(auth=auth, request=request)


def _tool_error(message: str, *, status: str = "error") -> dict[str, Any]:
    return {"status": status, "message": message}


def _preview_response(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "confirmation_required",
        "tool": tool_name,
        "message": "Preview generated. Repeat this tool call with execute=true to perform the action.",
        "preview": payload,
    }


def _has_any_scope(account: MCPGoogleAccountContext, scopes: set[str]) -> bool:
    return bool(scopes.intersection(set(account.scopes or [])))


def _resolve_google_account(db: Session, auth: MCPAuthContext, account_hint: str | None) -> MCPGoogleAccountContext:
    hint = str(account_hint or "").strip().lower()
    accounts = list_user_accounts(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    if not accounts:
        raise ValueError("No connected Google account is available for this user")

    selected = None
    if hint:
        for account in accounts:
            candidates = {
                str(account.id or "").lower(),
                str(account.label or "").lower(),
                str(account.google_account_email or "").lower(),
                str(account.google_account_sub or "").lower(),
            }
            if hint in candidates:
                selected = account
                break

    if selected is None:
        selected = get_primary_account(db, tenant_id=auth.tenant_id, user_id=auth.user_id) or accounts[0]

    return MCPGoogleAccountContext(
        id=selected.id,
        label=selected.label,
        email=selected.google_account_email,
        scopes=list(selected.scopes or []),
        gmail_enabled=bool(selected.gmail_enabled),
        calendar_enabled=bool(selected.calendar_enabled),
        contacts_enabled=bool(selected.contacts_enabled),
        enabled=bool(selected.enabled),
        connected=bool(selected.access_token_encrypted),
        connector=selected,
    )


def _ensure_google_ready(account: MCPGoogleAccountContext) -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise ValueError("Google OAuth credentials are not configured on the server")
    if not account.enabled:
        raise ValueError("Selected Google account is disabled")
    if not account.connected:
        raise ValueError("Selected Google account is not connected")


def _audit_mcp_call(
    db: Session,
    *,
    request_ctx: MCPRequestContext,
    tool_name: str,
    payload: dict[str, Any],
    status: str,
) -> None:
    audit_event(
        db,
        tenant_id=request_ctx.auth.tenant_id,
        user_id=request_ctx.auth.user_id,
        event_type="mcp.tool.execute",
        resource_type="mcp_tool",
        resource_id=tool_name,
        action=status,
        request_id=request_ctx.request.headers.get(settings.request_id_header),
        ip_address=request_ctx.request.client.host if request_ctx.request.client else None,
        payload=payload,
    )


def _log_tool_call(
    *,
    request_ctx: MCPRequestContext,
    tool_name: str,
    started_at: float,
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "mcp_tool_executed",
        tenant_id=request_ctx.auth.tenant_id,
        user_id=request_ctx.auth.user_id,
        tool_name=tool_name,
        status=status,
        duration_ms=int((time.perf_counter() - started_at) * 1000),
        **(extra or {}),
    )


def _citation_from_hit(item: Any) -> dict[str, Any]:
    chunk = item.chunk
    meta = chunk.metadata_json or {}
    return {
        "document_id": chunk.document_id,
        "document_title": str(meta.get("title", "Untitled")),
        "document_url": meta.get("url"),
        "source_type": str(meta.get("source_type", "unknown")),
        "chunk_id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "snippet": chunk.content[:320],
        "score": item.score,
        "ranker": item.ranker,
    }


@mcp_server.tool(name="knowledge.search", description="Search indexed tenant knowledge and return cited results.")
def knowledge_search(query: str, limit: int = 5, ctx: Context | None = None) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    cap = max(1, min(int(limit), 10))
    with _db_session(request_ctx.request) as db:
        hits = hybrid_search_chunks(
            db,
            tenant_id=request_ctx.auth.tenant_id,
            user_id=request_ctx.auth.user_id,
            query=str(query or "").strip(),
            limit=cap,
        )
        result = {"status": "ok", "query": query, "results": [_citation_from_hit(item) for item in hits]}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="knowledge.search",
            payload={"query": query, "limit": cap, "result_count": len(hits)},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="knowledge.search", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="email.list", description="List Gmail messages for the authenticated user's connected account.")
def email_list(
    limit: int = 10,
    query: str | None = None,
    account_hint: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.gmail_enabled:
            raise ValueError("Gmail access is disabled for this account")
        if not _has_any_scope(account, GMAIL_READ_SCOPES):
            raise ValueError("Gmail read scope is missing for this account")
        rows = list_gmail_messages(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            limit=max(1, min(int(limit), 25)),
            query=(str(query).strip() if query else None),
        )
        result = {
            "status": "ok",
            "account": {"id": account.id, "label": account.label, "email": account.email},
            "messages": rows,
        }
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="email.list",
            payload={"account_id": account.id, "limit": limit, "query": query, "result_count": len(rows)},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="email.list", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="email.read", description="Read a Gmail message by its message_id.")
def email_read(message_id: str, account_hint: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.gmail_enabled:
            raise ValueError("Gmail access is disabled for this account")
        if not _has_any_scope(account, GMAIL_READ_SCOPES):
            raise ValueError("Gmail read scope is missing for this account")
        message = read_gmail_message(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            message_id=str(message_id or "").strip(),
        )
        result = {"status": "ok", "account": {"id": account.id, "email": account.email}, "message": message}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="email.read",
            payload={"account_id": account.id, "message_id": message_id},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="email.read", started_at=started_at, status="executed")
    return result


@mcp_server.tool(
    name="email.send_draft",
    description="Preview or send an email. Defaults to preview mode; set execute=true to send.",
)
def email_send_draft(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    preview = {
        "to": [str(value).strip() for value in to if str(value).strip()],
        "cc": [str(value).strip() for value in (cc or []) if str(value).strip()],
        "bcc": [str(value).strip() for value in (bcc or []) if str(value).strip()],
        "subject": str(subject or "").strip(),
        "body": str(body or ""),
    }
    if not preview["to"] or not preview["subject"] or not preview["body"]:
        raise ValueError("to, subject, and body are required")
    if not execute:
        _log_tool_call(
            request_ctx=request_ctx,
            tool_name="email.send_draft",
            started_at=started_at,
            status="preview",
            extra={"execute": False},
        )
        return _preview_response("email.send_draft", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.gmail_enabled:
            raise ValueError("Gmail access is disabled for this account")
        if GMAIL_SEND_SCOPE not in set(account.scopes or []):
            raise ValueError("Gmail send scope is missing for this account")
        payload = send_gmail_message(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            to=preview["to"],
            subject=preview["subject"],
            body=preview["body"],
            cc=preview["cc"],
            bcc=preview["bcc"],
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "result": payload}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="email.send_draft",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(
        request_ctx=request_ctx,
        tool_name="email.send_draft",
        started_at=started_at,
        status="executed",
        extra={"execute": True},
    )
    return result


@mcp_server.tool(name="calendar.list", description="List Google Calendar events.")
def calendar_list(
    calendar_id: str = "primary",
    query: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    limit: int = 10,
    account_hint: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.calendar_enabled:
            raise ValueError("Calendar access is disabled for this account")
        if not _has_any_scope(account, CALENDAR_WRITE_SCOPES):
            raise ValueError("Calendar scope is missing for this account")
        events = list_events(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            calendar_id=str(calendar_id or "primary"),
            query=(str(query).strip() if query else None),
            time_min=(str(time_min).strip() if time_min else None),
            time_max=(str(time_max).strip() if time_max else None),
            limit=max(1, min(int(limit), 25)),
        )
        result = {"status": "ok", "account": {"id": account.id, "email": account.email}, "events": events}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="calendar.list",
            payload={"account_id": account.id, "calendar_id": calendar_id, "result_count": len(events)},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="calendar.list", started_at=started_at, status="executed")
    return result


def _calendar_preview(
    *,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None,
    location: str | None,
    attendees: list[str] | None,
    calendar_id: str,
) -> dict[str, Any]:
    if not summary.strip():
        raise ValueError("summary is required")
    if not start_datetime.strip() or not end_datetime.strip():
        raise ValueError("start_datetime and end_datetime are required")
    return {
        "calendar_id": calendar_id,
        "summary": summary.strip(),
        "start_datetime": start_datetime.strip(),
        "end_datetime": end_datetime.strip(),
        "description": (description or "").strip() or None,
        "location": (location or "").strip() or None,
        "attendees": [str(value).strip() for value in (attendees or []) if str(value).strip()],
    }


@mcp_server.tool(name="calendar.create", description="Preview or create a calendar event.")
def calendar_create(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    preview = _calendar_preview(
        summary=summary,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        description=description,
        location=location,
        attendees=attendees,
        calendar_id=calendar_id,
    )
    if not execute:
        _log_tool_call(request_ctx=request_ctx, tool_name="calendar.create", started_at=started_at, status="preview")
        return _preview_response("calendar.create", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.calendar_enabled:
            raise ValueError("Calendar access is disabled for this account")
        if not _has_any_scope(account, CALENDAR_WRITE_SCOPES):
            raise ValueError("Calendar write scope is missing for this account")
        payload = create_event(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            payload=preview,
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "event": payload}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="calendar.create",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="calendar.create", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="calendar.update", description="Preview or update a calendar event.")
def calendar_update(
    event_id: str,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    if not str(event_id or "").strip():
        raise ValueError("event_id is required")
    preview = _calendar_preview(
        summary=summary,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        description=description,
        location=location,
        attendees=attendees,
        calendar_id=calendar_id,
    )
    preview["event_id"] = str(event_id).strip()
    if not execute:
        _log_tool_call(request_ctx=request_ctx, tool_name="calendar.update", started_at=started_at, status="preview")
        return _preview_response("calendar.update", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.calendar_enabled:
            raise ValueError("Calendar access is disabled for this account")
        if not _has_any_scope(account, CALENDAR_WRITE_SCOPES):
            raise ValueError("Calendar write scope is missing for this account")
        payload = update_event(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            event_id=preview["event_id"],
            payload=preview,
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "event": payload}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="calendar.update",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="calendar.update", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="calendar.delete", description="Preview or delete a calendar event.")
def calendar_delete(
    event_id: str,
    calendar_id: str = "primary",
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    preview = {"event_id": str(event_id or "").strip(), "calendar_id": str(calendar_id or "primary").strip()}
    if not preview["event_id"]:
        raise ValueError("event_id is required")
    if not execute:
        _log_tool_call(request_ctx=request_ctx, tool_name="calendar.delete", started_at=started_at, status="preview")
        return _preview_response("calendar.delete", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.calendar_enabled:
            raise ValueError("Calendar access is disabled for this account")
        if not _has_any_scope(account, CALENDAR_WRITE_SCOPES):
            raise ValueError("Calendar write scope is missing for this account")
        delete_event(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            calendar_id=preview["calendar_id"],
            event_id=preview["event_id"],
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "deleted": preview}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="calendar.delete",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="calendar.delete", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="contacts.list", description="List contacts from the authenticated user's Google People account.")
def contacts_list(limit: int = 20, account_hint: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.contacts_enabled:
            raise ValueError("Contacts access is disabled for this account")
        if not _has_any_scope(account, CONTACTS_READ_SCOPES):
            raise ValueError("Contacts read scope is missing for this account")
        rows = list_contacts(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            limit=max(1, min(int(limit), 50)),
        )
        result = {"status": "ok", "account": {"id": account.id, "email": account.email}, "contacts": rows}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="contacts.list",
            payload={"account_id": account.id, "limit": limit, "result_count": len(rows)},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="contacts.list", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="contacts.search", description="Search contacts by name, email, or phone.")
def contacts_search(
    query: str,
    limit: int = 20,
    account_hint: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.contacts_enabled:
            raise ValueError("Contacts access is disabled for this account")
        if not _has_any_scope(account, CONTACTS_READ_SCOPES):
            raise ValueError("Contacts read scope is missing for this account")
        rows = search_contacts(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            query=str(query or "").strip(),
            limit=max(1, min(int(limit), 50)),
        )
        result = {"status": "ok", "account": {"id": account.id, "email": account.email}, "contacts": rows}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="contacts.search",
            payload={"account_id": account.id, "query": query, "result_count": len(rows)},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="contacts.search", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="contacts.read", description="Read a contact by Google People resource_name.")
def contacts_read(resource_name: str, account_hint: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.contacts_enabled:
            raise ValueError("Contacts access is disabled for this account")
        if not _has_any_scope(account, CONTACTS_READ_SCOPES):
            raise ValueError("Contacts read scope is missing for this account")
        record = get_contact(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            resource_name=str(resource_name or "").strip(),
        )
        result = {"status": "ok", "account": {"id": account.id, "email": account.email}, "contact": record}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="contacts.read",
            payload={"account_id": account.id, "resource_name": resource_name},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="contacts.read", started_at=started_at, status="executed")
    return result


def _contact_preview(
    *,
    display_name: str | None,
    given_name: str | None,
    family_name: str | None,
    emails: list[str] | None,
    phones: list[str] | None,
    organizations: list[str] | None,
    biography: str | None,
) -> dict[str, Any]:
    payload = {
        "display_name": (display_name or "").strip() or None,
        "given_name": (given_name or "").strip() or None,
        "family_name": (family_name or "").strip() or None,
        "emails": [str(value).strip() for value in (emails or []) if str(value).strip()],
        "phones": [str(value).strip() for value in (phones or []) if str(value).strip()],
        "organizations": [str(value).strip() for value in (organizations or []) if str(value).strip()],
        "biography": (biography or "").strip() or None,
    }
    if not any(
        [
            payload["display_name"],
            payload["given_name"],
            payload["family_name"],
            payload["emails"],
            payload["phones"],
            payload["organizations"],
            payload["biography"],
        ]
    ):
        raise ValueError("At least one contact field is required")
    return payload


@mcp_server.tool(name="contacts.create", description="Preview or create a contact.")
def contacts_create(
    display_name: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    organizations: list[str] | None = None,
    biography: str | None = None,
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    preview = _contact_preview(
        display_name=display_name,
        given_name=given_name,
        family_name=family_name,
        emails=emails,
        phones=phones,
        organizations=organizations,
        biography=biography,
    )
    if not execute:
        _log_tool_call(request_ctx=request_ctx, tool_name="contacts.create", started_at=started_at, status="preview")
        return _preview_response("contacts.create", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.contacts_enabled:
            raise ValueError("Contacts access is disabled for this account")
        if CONTACTS_WRITE_SCOPE not in set(account.scopes or []):
            raise ValueError("Contacts write scope is missing for this account")
        record = create_contact(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            payload=preview,
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "contact": record}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="contacts.create",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="contacts.create", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="contacts.update", description="Preview or update a contact by resource_name.")
def contacts_update(
    resource_name: str,
    display_name: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    organizations: list[str] | None = None,
    biography: str | None = None,
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    if not str(resource_name or "").strip():
        raise ValueError("resource_name is required")
    preview = _contact_preview(
        display_name=display_name,
        given_name=given_name,
        family_name=family_name,
        emails=emails,
        phones=phones,
        organizations=organizations,
        biography=biography,
    )
    preview["resource_name"] = str(resource_name).strip()
    if not execute:
        _log_tool_call(request_ctx=request_ctx, tool_name="contacts.update", started_at=started_at, status="preview")
        return _preview_response("contacts.update", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.contacts_enabled:
            raise ValueError("Contacts access is disabled for this account")
        if CONTACTS_WRITE_SCOPE not in set(account.scopes or []):
            raise ValueError("Contacts write scope is missing for this account")
        record = update_contact(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            resource_name=preview["resource_name"],
            payload=preview,
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "contact": record}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="contacts.update",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="contacts.update", started_at=started_at, status="executed")
    return result


@mcp_server.tool(name="contacts.delete", description="Preview or delete a contact by resource_name.")
def contacts_delete(
    resource_name: str,
    account_hint: str | None = None,
    execute: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    assert ctx is not None
    request_ctx = _request_context(ctx)
    started_at = time.perf_counter()
    preview = {"resource_name": str(resource_name or "").strip()}
    if not preview["resource_name"]:
        raise ValueError("resource_name is required")
    if not execute:
        _log_tool_call(request_ctx=request_ctx, tool_name="contacts.delete", started_at=started_at, status="preview")
        return _preview_response("contacts.delete", preview)

    with _db_session(request_ctx.request) as db:
        account = _resolve_google_account(db, request_ctx.auth, account_hint)
        _ensure_google_ready(account)
        if not account.contacts_enabled:
            raise ValueError("Contacts access is disabled for this account")
        if CONTACTS_WRITE_SCOPE not in set(account.scopes or []):
            raise ValueError("Contacts write scope is missing for this account")
        deleted = delete_contact(
            db,
            account.connector,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            resource_name=preview["resource_name"],
        )
        result = {"status": "executed", "account": {"id": account.id, "email": account.email}, "contact": deleted}
        _audit_mcp_call(
            db,
            request_ctx=request_ctx,
            tool_name="contacts.delete",
            payload={"account_id": account.id, **preview},
            status="executed",
        )
    _log_tool_call(request_ctx=request_ctx, tool_name="contacts.delete", started_at=started_at, status="executed")
    return result
