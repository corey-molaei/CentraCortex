from __future__ import annotations

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.acl_policy import ACLPolicy
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.document import Document
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def _seed_tenant(db_session, *, slug: str) -> Tenant:
    tenant = Tenant(name=f"Tenant {slug}", slug=slug)
    db_session.add(tenant)
    db_session.commit()
    return tenant


def _seed_user(db_session, *, tenant: Tenant, email: str, is_default: bool = False) -> User:
    user = User(email=email, full_name=email.split("@")[0], hashed_password=get_password_hash("password123"))
    db_session.add(user)
    db_session.flush()
    db_session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="User", is_default=is_default))
    db_session.commit()
    return user


def _login(client, *, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str, tenant_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}


def test_user_can_create_and_list_multiple_email_accounts(client, db_session):
    tenant = _seed_tenant(db_session, slug="email-user-multi")
    user = _seed_user(db_session, tenant=tenant, email="imap-multi@example.com", is_default=True)
    token = _login(client, email=user.email)

    payload = {
        "label": "Work",
        "email_address": "work@example.com",
        "username": "work@example.com",
        "password": "app-password",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "use_ssl": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_use_starttls": True,
        "folders": ["INBOX"],
        "enabled": True,
    }
    create_a = client.post("/api/v1/connectors/email/accounts", headers=_auth(token, tenant.id), json=payload)
    assert create_a.status_code == 200
    create_b = client.post(
        "/api/v1/connectors/email/accounts",
        headers=_auth(token, tenant.id),
        json={**payload, "label": "Personal", "email_address": "personal@example.com", "username": "personal@example.com"},
    )
    assert create_b.status_code == 200

    listed = client.get("/api/v1/connectors/email/accounts", headers=_auth(token, tenant.id))
    assert listed.status_code == 200
    assert {item["email_address"] for item in listed.json()} == {"work@example.com", "personal@example.com"}


def test_email_account_actions_are_user_scoped(client, db_session):
    tenant = _seed_tenant(db_session, slug="email-user-scope")
    user_a = _seed_user(db_session, tenant=tenant, email="scope-a@example.com", is_default=True)
    user_b = _seed_user(db_session, tenant=tenant, email="scope-b@example.com")
    token_a = _login(client, email=user_a.email)
    token_b = _login(client, email=user_b.email)

    created = client.post(
        "/api/v1/connectors/email/accounts",
        headers=_auth(token_a, tenant.id),
        json={
            "label": "Work",
            "email_address": "scope-a@example.com",
            "username": "scope-a@example.com",
            "password": "app-password",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "use_ssl": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_use_starttls": True,
            "folders": ["INBOX"],
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["id"]

    forbidden = client.post(f"/api/v1/connectors/email/accounts/{account_id}/test", headers=_auth(token_b, tenant.id))
    assert forbidden.status_code == 404


def test_email_sync_creates_private_imap_documents(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="email-user-sync")
    user = _seed_user(db_session, tenant=tenant, email="imap-sync@example.com", is_default=True)
    token = _login(client, email=user.email)

    created = client.post(
        "/api/v1/connectors/email/accounts",
        headers=_auth(token, tenant.id),
        json={
            "label": "Work",
            "email_address": "imap-sync@example.com",
            "username": "imap-sync@example.com",
            "password": "app-password",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "use_ssl": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_use_starttls": True,
            "folders": ["INBOX"],
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["id"]

    raw_email = (
        b"Subject: Private Email\r\n"
        b"From: Sender <sender@example.com>\r\n"
        b"To: imap-sync@example.com\r\n"
        b"\r\n"
        b"Private email body.\r\n"
    )

    class DummyConn:
        def select(self, folder):  # noqa: ARG002
            return ("OK", [b""])

        def uid(self, action, uid_bytes, params):  # noqa: ARG002
            if action == "search":
                return ("OK", [b"1"])
            if action == "fetch":
                return ("OK", [(b"1 (RFC822 {123})", raw_email)])
            return ("NO", [b"unsupported"])

        def logout(self):
            return ("BYE", [b""])

    monkeypatch.setattr("app.services.connectors.email_user_service._connect_imap", lambda account: DummyConn())

    synced = client.post(f"/api/v1/connectors/email/accounts/{account_id}/sync", headers=_auth(token, tenant.id))
    assert synced.status_code == 200
    assert synced.json()["items_synced"] == 1

    docs = db_session.execute(
        select(Document).where(Document.tenant_id == tenant.id, Document.source_type == "imap_email")
    ).scalars().all()
    assert len(docs) == 1
    assert docs[0].source_id.startswith(f"{account_id}:")
    assert docs[0].metadata_json.get("email_account_id") == account_id
    assert docs[0].acl_policy_id is not None

    policy = db_session.get(ACLPolicy, docs[0].acl_policy_id)
    assert policy is not None
    assert policy.allowed_user_ids == [user.id]

    runs = db_session.execute(
        select(ConnectorSyncRun).where(
            ConnectorSyncRun.tenant_id == tenant.id,
            ConnectorSyncRun.connector_type == "email_user",
            ConnectorSyncRun.connector_config_id == account_id,
        )
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "success"
