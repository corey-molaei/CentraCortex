from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import encrypt_secret, get_password_hash
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


@pytest.fixture(autouse=True)
def google_oauth_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")


def _seed_tenant_with_user(db_session, *, email: str) -> tuple[Tenant, User]:
    tenant = Tenant(name="Contacts Tenant", slug=f"contacts-{email.split('@')[0]}")
    user = User(email=email, full_name="Contacts User", hashed_password=get_password_hash("password123"))
    db_session.add_all([tenant, user])
    db_session.flush()
    db_session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="User", is_default=True))
    db_session.commit()
    return tenant, user


def _login(client, *, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str, tenant_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}


def _seed_google_account(
    db_session,
    *,
    tenant_id: str,
    user_id: str,
    email: str,
    contacts_enabled: bool = True,
    scopes: list[str] | None = None,
) -> GoogleUserConnector:
    account = GoogleUserConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        label="Contacts Account",
        google_account_email=email,
        google_account_sub=f"sub-{email}",
        access_token_encrypted=encrypt_secret("token"),
        refresh_token_encrypted=encrypt_secret("refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
        scopes=scopes or [
            "https://www.googleapis.com/auth/contacts.readonly",
            "https://www.googleapis.com/auth/contacts",
        ],
        gmail_enabled=False,
        calendar_enabled=False,
        contacts_enabled=contacts_enabled,
        enabled=True,
        is_primary=True,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def test_contacts_access_status_returns_connected(client, db_session):
    tenant, user = _seed_tenant_with_user(db_session, email="contacts-access@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email=user.email)

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "do you have access to my contacts"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Contacts Action Engine"
    assert "Yes. I can access and modify contacts" in body["answer"]


def test_contacts_list_and_read_actions(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="contacts-list@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email=user.email)

    monkeypatch.setattr(
        "app.services.chat_contacts_actions.list_contacts",
        lambda *args, **kwargs: [
            {
                "resource_name": "people/c1",
                "display_name": "John Doe",
                "primary_email": "john@example.com",
                "primary_phone": "+61 400 000 000",
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.chat_contacts_actions.get_contact",
        lambda *args, **kwargs: {
            "resource_name": "people/c1",
            "display_name": "John Doe",
            "given_name": "John",
            "family_name": "Doe",
            "emails": ["john@example.com"],
            "phones": ["+61 400 000 000"],
            "organizations": ["CentraCortex"],
            "biography": "Lead",
        },
    )

    listed = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "list my contacts"}]},
    )
    assert listed.status_code == 200
    assert listed.json()["provider_name"] == "Contacts Action Engine"
    assert "Here are the contacts I found:" in listed.json()["answer"]

    read = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "read contact people/c1"}]},
    )
    assert read.status_code == 200
    assert "Contact details:" in read.json()["answer"]
    assert "John Doe" in read.json()["answer"]


def test_contacts_create_requires_confirmation_and_executes_on_yes(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="contacts-create@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email=user.email)

    captured: dict = {"count": 0}

    def fake_create_contact(*args, **kwargs):
        captured["count"] += 1
        return {
            "resource_name": "people/new-1",
            "display_name": kwargs["payload"].get("display_name") or "Unnamed",
        }

    monkeypatch.setattr("app.services.chat_contacts_actions.create_contact", fake_create_contact)

    first = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "add contact John Doe email john@example.com"}]},
    )
    assert first.status_code == 200
    assert "Please confirm creating this contact" in first.json()["answer"]
    assert captured["count"] == 0
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"conversation_id": conversation_id, "messages": [{"role": "user", "content": "yes"}]},
    )
    assert second.status_code == 200
    assert "Contact created" in second.json()["answer"]
    assert captured["count"] == 1


def test_contacts_delete_cancel_does_not_execute(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="contacts-delete-cancel@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email=user.email)

    monkeypatch.setattr(
        "app.services.chat_contacts_actions.search_contacts",
        lambda *args, **kwargs: [
            {"resource_name": "people/a1", "display_name": "John Doe", "primary_email": "john@example.com"}
        ],
    )
    called = {"count": 0}

    def fake_delete_contact(*args, **kwargs):
        called["count"] += 1
        return {"resource_name": kwargs["resource_name"], "deleted": True}

    monkeypatch.setattr("app.services.chat_contacts_actions.delete_contact", fake_delete_contact)

    first = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "delete contact John Doe"}]},
    )
    assert first.status_code == 200
    assert "Please confirm deleting this contact" in first.json()["answer"]
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"conversation_id": conversation_id, "messages": [{"role": "user", "content": "no"}]},
    )
    assert second.status_code == 200
    assert "Cancelled. I did not change your contacts." in second.json()["answer"]
    assert called["count"] == 0


def test_contacts_update_uses_disambiguation_then_confirmation(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="contacts-update@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email=user.email)

    monkeypatch.setattr(
        "app.services.chat_contacts_actions.search_contacts",
        lambda *args, **kwargs: [
            {"resource_name": "people/a1", "display_name": "John Doe", "primary_email": "john1@example.com"},
            {"resource_name": "people/a2", "display_name": "John Doe", "primary_email": "john2@example.com"},
        ],
    )

    captured: dict = {}

    def fake_update_contact(*args, **kwargs):
        captured["resource_name"] = kwargs["resource_name"]
        captured["payload"] = kwargs["payload"]
        return {"resource_name": kwargs["resource_name"], "display_name": "John Doe"}

    monkeypatch.setattr("app.services.chat_contacts_actions.update_contact", fake_update_contact)

    first = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "update contact John Doe email john.new@example.com"}]},
    )
    assert first.status_code == 200
    assert "Please select one by number" in first.json()["answer"]
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"conversation_id": conversation_id, "messages": [{"role": "user", "content": "2"}]},
    )
    assert second.status_code == 200
    assert "Please confirm updating this contact" in second.json()["answer"]

    third = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"conversation_id": conversation_id, "messages": [{"role": "user", "content": "yes"}]},
    )
    assert third.status_code == 200
    assert "Contact updated" in third.json()["answer"]
    assert captured["resource_name"] == "people/a2"
    assert captured["payload"]["emails"] == ["john.new@example.com"]


def test_contacts_llm_parser_fallback_when_parser_fails(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="contacts-fallback@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email=user.email)

    monkeypatch.setattr("app.services.chat_contacts_actions._parse_contacts_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.chat_contacts_actions.list_contacts", lambda *args, **kwargs: [])

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "my contacts"}]},
    )
    assert response.status_code == 200
    assert response.json()["provider_name"] == "Contacts Action Engine"
    assert "I could not find contacts" in response.json()["answer"]
