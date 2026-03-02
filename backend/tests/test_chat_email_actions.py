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
    tenant = Tenant(name="Email Chat Tenant", slug=f"email-chat-{email.split('@')[0]}")
    user = User(email=email, full_name="Email User", hashed_password=get_password_hash("password123"))
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


def _seed_google_account(db_session, *, tenant_id: str, user_id: str, email: str) -> GoogleUserConnector:
    account = GoogleUserConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        label="Work Gmail",
        google_account_email=email,
        google_account_sub=f"sub-{email}",
        access_token_encrypted=encrypt_secret("token"),
        refresh_token_encrypted=encrypt_secret("refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
        scopes=[],
        gmail_enabled=True,
        gmail_labels=["INBOX"],
        calendar_enabled=False,
        calendar_ids=["primary"],
        enabled=True,
        is_primary=True,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def test_chat_summarize_emails_uses_email_action_engine(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-summary@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="summary@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Salary Update",
                "from": "HR <hr@example.com>",
                "sent_at": "2026-02-24T01:00:00+00:00",
                "snippet": "Your salary update is attached.",
            },
            {
                "id": "m-2",
                "subject": "Project Kickoff",
                "from": "PM <pm@example.com>",
                "sent_at": "2026-02-23T11:00:00+00:00",
                "snippet": "Kickoff meeting details.",
            },
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "summarize my last 2 emails"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "I found 2 recent emails" in body["answer"]
    assert "Salary Update" in body["answer"]


def test_chat_send_email_requires_confirmation_then_sends(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-send@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    sent: dict = {}

    def fake_send(*args, **kwargs):
        sent["to"] = kwargs["to"]
        sent["subject"] = kwargs["subject"]
        sent["body"] = kwargs["body"]
        return {"id": "gmail-msg-1"}

    monkeypatch.setattr("app.services.chat_email_actions.send_gmail_message", fake_send)

    first = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "send email to bob@example.com about status body: completed"}]},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert "Please confirm sending this email" in first_body["answer"]
    conversation_id = first_body["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "yes"}], "conversation_id": conversation_id},
    )
    assert second.status_code == 200
    assert "Email sent successfully." in second.json()["answer"]
    assert sent["to"] == ["bob@example.com"]
    assert sent["subject"] == "status body: completed"


def test_chat_send_email_can_be_cancelled(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-cancel@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    called = {"count": 0}

    def fake_send(*args, **kwargs):
        called["count"] += 1
        return {"id": "gmail-msg-1"}

    monkeypatch.setattr("app.services.chat_email_actions.send_gmail_message", fake_send)

    first = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "send email to bob@example.com body: ignore this"}]},
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "no"}], "conversation_id": conversation_id},
    )
    assert second.status_code == 200
    assert "Cancelled" in second.json()["answer"]
    assert called["count"] == 0
