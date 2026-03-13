from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.server.streamable_http import MCP_PROTOCOL_VERSION_HEADER, MCP_SESSION_ID_HEADER
from mcp.types import LATEST_PROTOCOL_VERSION

from app.core.security import create_access_token, encrypt_secret, get_password_hash
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def _jsonrpc_result(response) -> dict:
    content_type = str(response.headers.get("content-type") or "")
    if content_type.startswith("application/json"):
        return response.json()["result"]

    payload = response.text
    data_lines = [line[6:] for line in payload.splitlines() if line.startswith("data: ")]
    assert data_lines, payload
    return json.loads("\n".join(data_lines))["result"]


def _seed_user_and_tenant(db_session, *, email: str = "mcp@example.com"):
    tenant = Tenant(name="MCP Tenant", slug=f"mcp-{email.split('@')[0]}")
    user = User(email=email, full_name="MCP User", hashed_password=get_password_hash("password123"))
    db_session.add_all([tenant, user])
    db_session.flush()
    membership = TenantMembership(user_id=user.id, tenant_id=tenant.id, role="Owner", is_default=True)
    db_session.add(membership)
    db_session.commit()
    return tenant, user, membership


def _seed_google_account(
    db_session,
    *,
    tenant_id: str,
    user_id: str,
    email: str,
    scopes: list[str],
    gmail_enabled: bool = True,
    calendar_enabled: bool = True,
    contacts_enabled: bool = True,
):
    account = GoogleUserConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        label="Primary Google",
        google_account_email=email,
        google_account_sub=f"sub-{email}",
        access_token_encrypted=encrypt_secret("token"),
        refresh_token_encrypted=encrypt_secret("refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
        scopes=scopes,
        gmail_enabled=gmail_enabled,
        calendar_enabled=calendar_enabled,
        contacts_enabled=contacts_enabled,
        enabled=True,
        is_primary=True,
    )
    db_session.add(account)
    db_session.commit()
    return account


def _mcp_initialize(client, headers: dict[str, str]) -> str:
    return _mcp_initialize_at_path(client, headers, "/api/v1/mcp/")


def _mcp_initialize_at_path(client, headers: dict[str, str], path: str) -> str:
    response = client.post(
        path,
        headers={
            "Host": "localhost:8000",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
        json={
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0.0"},
            },
        },
    )
    assert response.status_code == 200
    session_id = response.headers[MCP_SESSION_ID_HEADER]
    initialized = client.post(
        "/api/v1/mcp/",
        headers={
            "Host": "localhost:8000",
            "Accept": "application/json, text/event-stream",
            MCP_PROTOCOL_VERSION_HEADER: LATEST_PROTOCOL_VERSION,
            **headers,
            MCP_SESSION_ID_HEADER: session_id,
        },
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert initialized.status_code == 202
    return session_id


def _mcp_list_tools(client, headers: dict[str, str], session_id: str) -> dict:
    response = client.post(
        "/api/v1/mcp/",
        headers={
            "Host": "localhost:8000",
            "Accept": "application/json, text/event-stream",
            MCP_PROTOCOL_VERSION_HEADER: LATEST_PROTOCOL_VERSION,
            **headers,
            MCP_SESSION_ID_HEADER: session_id,
        },
        json={"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"},
    )
    assert response.status_code == 200
    return _jsonrpc_result(response)


def _mcp_call_tool(client, headers: dict[str, str], session_id: str, name: str, arguments: dict) -> dict:
    response = client.post(
        "/api/v1/mcp/",
        headers={
            "Host": "localhost:8000",
            "Accept": "application/json, text/event-stream",
            MCP_PROTOCOL_VERSION_HEADER: LATEST_PROTOCOL_VERSION,
            **headers,
            MCP_SESSION_ID_HEADER: session_id,
        },
        json={
            "jsonrpc": "2.0",
            "id": f"call-{name}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return _jsonrpc_result(response)


@pytest.fixture(autouse=True)
def mcp_test_google_credentials(monkeypatch):
    monkeypatch.setattr("app.services.mcp_server.settings.google_client_id", "test-google-client")
    monkeypatch.setattr("app.services.mcp_server.settings.google_client_secret", "test-google-secret")

def test_mcp_requires_auth(client):
    response = client.post(
        "/api/v1/mcp/",
        headers={
            "Host": "localhost:8000",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0.0"},
            },
        },
    )
    assert response.status_code == 401


def test_mcp_initialize_accepts_url_without_trailing_slash(client, db_session):
    tenant, user, _ = _seed_user_and_tenant(db_session, email="noslash@example.com")
    token = create_access_token(user.id, tenant.id)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}
    session_id = _mcp_initialize_at_path(client, headers, "/api/v1/mcp")
    assert session_id


def test_mcp_lists_built_in_tools_for_authenticated_client(client, db_session):
    tenant, user, _ = _seed_user_and_tenant(db_session)
    token = create_access_token(user.id, tenant.id)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}
    session_id = _mcp_initialize(client, headers)
    tools = _mcp_list_tools(client, headers, session_id)

    tool_names = {tool["name"] for tool in tools["tools"]}
    assert "email.list" in tool_names
    assert "calendar.create" in tool_names
    assert "contacts.search" in tool_names
    assert "knowledge.search" in tool_names


def test_mcp_knowledge_search_is_tenant_scoped(client, db_session, monkeypatch):
    tenant_a, user_a, _ = _seed_user_and_tenant(db_session, email="a@example.com")
    tenant_b, user_b, _ = _seed_user_and_tenant(db_session, email="b@example.com")
    chunk = SimpleNamespace(
        document_id="doc-a",
        id="chunk-a",
        chunk_index=0,
        content="maryam asadi customer onboarding guide",
        metadata_json={"title": "Tenant A Guide", "source_type": "manual"},
    )
    hit = SimpleNamespace(chunk=chunk, score=0.9, ranker="hybrid")

    def _fake_hybrid_search_chunks(db, *, tenant_id, user_id, query, limit):  # noqa: ARG001
        return [hit] if tenant_id == tenant_a.id else []

    monkeypatch.setattr("app.services.mcp_server.hybrid_search_chunks", _fake_hybrid_search_chunks)

    headers_a = {"Authorization": f"Bearer {create_access_token(user_a.id, tenant_a.id)}", "X-Tenant-ID": tenant_a.id}
    headers_b = {"Authorization": f"Bearer {create_access_token(user_b.id, tenant_b.id)}", "X-Tenant-ID": tenant_b.id}
    session_a = _mcp_initialize(client, headers_a)
    session_b = _mcp_initialize(client, headers_b)
    payload_a = _mcp_call_tool(client, headers_a, session_a, "knowledge.search", {"query": "maryam asadi", "limit": 5})
    payload_b = _mcp_call_tool(client, headers_b, session_b, "knowledge.search", {"query": "maryam asadi", "limit": 5})

    payload_a = payload_a["structuredContent"]
    payload_b = payload_b["structuredContent"]
    assert payload_a["results"]
    assert payload_a["results"][0]["document_title"] == "Tenant A Guide"
    assert payload_b["results"] == []


def test_mcp_send_draft_requires_execute_flag(client, db_session, monkeypatch):
    tenant, user, _ = _seed_user_and_tenant(db_session)
    _seed_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        email="mcp@gmail.com",
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    token = create_access_token(user.id, tenant.id)

    called = {"count": 0}

    def _fake_send(*args, **kwargs):  # noqa: ARG001
        called["count"] += 1
        return {"id": "msg-1", "thread_id": "thread-1", "label_ids": ["SENT"]}

    monkeypatch.setattr("app.services.mcp_server.send_gmail_message", _fake_send)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}
    session_id = _mcp_initialize(client, headers)
    payload = _mcp_call_tool(
        client,
        headers,
        session_id,
        "email.send_draft",
        {"to": ["person@example.com"], "subject": "Test", "body": "Hello"},
    )["structuredContent"]
    assert payload["status"] == "confirmation_required"
    assert payload["tool"] == "email.send_draft"
    assert called["count"] == 0


def test_mcp_contacts_search_uses_google_service(client, db_session, monkeypatch):
    tenant, user, _ = _seed_user_and_tenant(db_session)
    _seed_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        email="contacts@gmail.com",
        scopes=["https://www.googleapis.com/auth/contacts.readonly"],
    )
    token = create_access_token(user.id, tenant.id)

    monkeypatch.setattr(
        "app.services.mcp_server.search_contacts",
        lambda *args, **kwargs: [
            {
                "resource_name": "people/123",
                "display_name": "Maryam Asadi",
                "emails": ["maryam@example.com"],
                "phones": [],
                "organizations": [],
                "biography": "",
                "primary_email": "maryam@example.com",
                "primary_phone": None,
                "etag": "etag-1",
            }
        ],
    )
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}
    session_id = _mcp_initialize(client, headers)
    payload = _mcp_call_tool(client, headers, session_id, "contacts.search", {"query": "Maryam Asadi"})[
        "structuredContent"
    ]
    assert payload["status"] == "ok"
    assert payload["contacts"][0]["display_name"] == "Maryam Asadi"
