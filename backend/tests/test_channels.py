from datetime import UTC, datetime, timedelta

from app.core.security import encrypt_secret, get_password_hash
from app.models.channel_telegram_connector import ChannelTelegramConnector
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def _seed_tenant_with_owner(db_session, *, email: str) -> tuple[Tenant, User]:
    tenant = Tenant(name="Channels Tenant", slug=f"channels-{email.split('@')[0]}")
    user = User(email=email, full_name="Channels Owner", hashed_password=get_password_hash("password123"))
    db_session.add_all([tenant, user])
    db_session.flush()
    db_session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="Owner", is_default=True))
    db_session.commit()
    return tenant, user


def _login(client, *, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str, tenant_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}


def _seed_workspace_google_default(db_session, *, tenant_id: str, user_id: str) -> GoogleUserConnector:
    row = GoogleUserConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        label="Workspace Default",
        google_account_email="owner@example.com",
        google_account_sub="sub-owner",
        access_token_encrypted=encrypt_secret("token"),
        refresh_token_encrypted=encrypt_secret("refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar",
        ],
        enabled=True,
        gmail_enabled=True,
        calendar_enabled=True,
        contacts_enabled=True,
        is_primary=True,
        is_workspace_default=True,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_telegram_test_registers_webhook(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_owner(db_session, email="channels-register@example.com")
    token = _login(client, email=user.email)

    updated = client.put(
        "/api/v1/channels/telegram",
        headers=_auth(token, tenant.id),
        json={"enabled": True, "bot_token": "bot-token-123", "webhook_secret": "secret-123"},
    )
    assert updated.status_code == 200
    connector_id = updated.json()["id"]

    captured: dict = {}

    def fake_register(*, bot_token, webhook_url, webhook_secret):  # noqa: ANN001
        captured["bot_token"] = bot_token
        captured["webhook_url"] = webhook_url
        captured["webhook_secret"] = webhook_secret

    monkeypatch.setattr("app.routers.channels._register_telegram_webhook", fake_register)

    tested = client.post("/api/v1/channels/telegram/test", headers=_auth(token, tenant.id))
    assert tested.status_code == 200
    payload = tested.json()
    assert payload["success"] is True
    assert connector_id in payload["message"]

    assert captured["bot_token"] == "bot-token-123"
    assert captured["webhook_secret"] == "secret-123"
    assert captured["webhook_url"].endswith(f"/api/v1/channels/telegram/webhook/{connector_id}")


def test_telegram_public_webhook_processes_and_sends_reply(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_owner(db_session, email="channels-telegram-webhook@example.com")
    _seed_workspace_google_default(db_session, tenant_id=tenant.id, user_id=user.id)

    connector = ChannelTelegramConnector(
        tenant_id=tenant.id,
        enabled=True,
        bot_token_encrypted=encrypt_secret("bot-token-xyz"),
        webhook_secret="hook-secret",
        config_json={},
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)

    monkeypatch.setattr(
        "app.routers.channels.run_channel_message",
        lambda *args, **kwargs: {
            "conversation_id": "conv-1",
            "assistant_message_id": "msg-1",
            "answer": "Hello from CentraCortex",
            "provider_name": "Tool Planner",
            "model_name": "tool-planner",
        },
    )

    captured_send: dict = {}

    def fake_send(*, bot_token, chat_id, text):  # noqa: ANN001
        captured_send["bot_token"] = bot_token
        captured_send["chat_id"] = chat_id
        captured_send["text"] = text

    monkeypatch.setattr("app.routers.channels._send_telegram_message", fake_send)

    response = client.post(
        f"/api/v1/channels/telegram/webhook/{connector.id}",
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
        json={
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 1001, "first_name": "Kourosh"},
                "chat": {"id": 2002, "type": "private"},
                "date": 1710000000,
                "text": "hello bot",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured_send["bot_token"] == "bot-token-xyz"
    assert captured_send["chat_id"] == "2002"
    assert "Hello from CentraCortex" in captured_send["text"]


def test_telegram_public_webhook_secret_mismatch_returns_403(client, db_session):
    tenant, user = _seed_tenant_with_owner(db_session, email="channels-secret-mismatch@example.com")
    _seed_workspace_google_default(db_session, tenant_id=tenant.id, user_id=user.id)

    connector = ChannelTelegramConnector(
        tenant_id=tenant.id,
        enabled=True,
        bot_token_encrypted=encrypt_secret("bot-token-xyz"),
        webhook_secret="right-secret",
        config_json={},
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)

    response = client.post(
        f"/api/v1/channels/telegram/webhook/{connector.id}",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        json={
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 1001, "first_name": "Kourosh"},
                "chat": {"id": 2002, "type": "private"},
                "date": 1710000000,
                "text": "hello bot",
            },
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid Telegram webhook secret"


def test_telegram_public_webhook_ignores_non_text_updates(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_owner(db_session, email="channels-ignore-non-text@example.com")
    _seed_workspace_google_default(db_session, tenant_id=tenant.id, user_id=user.id)

    connector = ChannelTelegramConnector(
        tenant_id=tenant.id,
        enabled=True,
        bot_token_encrypted=encrypt_secret("bot-token-xyz"),
        webhook_secret=None,
        config_json={},
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)

    monkeypatch.setattr(
        "app.routers.channels._send_telegram_message",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("send should not be called")),
    )

    response = client.post(
        f"/api/v1/channels/telegram/webhook/{connector.id}",
        json={
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 1001, "first_name": "Kourosh"},
                "chat": {"id": 2002, "type": "private"},
                "date": 1710000000,
                "text": "",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["ignored"] is True
