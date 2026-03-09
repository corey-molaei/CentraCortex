from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import encrypt_secret, get_password_hash
from app.models.acl_policy import ACLPolicy
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.document import Document
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.tasks.celery_app import sync_google_connectors


@pytest.fixture(autouse=True)
def mock_raw_blob_storage(monkeypatch):
    def _stub_blob_store(tenant_id: str, source_type: str, source_id: str, payload: dict) -> str:  # noqa: ARG001
        return f"{tenant_id}/{source_type}/{source_id}.json"

    monkeypatch.setattr("app.services.connectors.common.put_raw_document_blob", _stub_blob_store)


@pytest.fixture(autouse=True)
def google_oauth_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")


def _seed_user(db_session, *, tenant: Tenant, email: str, is_default: bool = False) -> User:
    user = User(email=email, full_name=email.split("@")[0], hashed_password=get_password_hash("password123"))
    db_session.add(user)
    db_session.flush()
    db_session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="User", is_default=is_default))
    db_session.commit()
    return user


def _seed_tenant(db_session, *, slug: str) -> Tenant:
    tenant = Tenant(name=f"Tenant {slug}", slug=slug)
    db_session.add(tenant)
    db_session.commit()
    return tenant


def _login(client, *, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str, tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id,
    }


def _create_account(client, token: str, tenant_id: str, *, label: str = "Work") -> str:
    response = client.post(
        "/api/v1/connectors/google/accounts",
        headers=_auth(token, tenant_id),
        json={
            "label": label,
            "enabled": True,
            "gmail_enabled": True,
            "gmail_labels": ["INBOX", "SENT"],
            "calendar_enabled": True,
            "calendar_ids": ["primary"],
            "sync_scope_configured": True,
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_user_can_create_and_list_multiple_google_accounts(client, db_session):
    tenant = _seed_tenant(db_session, slug="google-multi")
    user = _seed_user(db_session, tenant=tenant, email="multi@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_a = _create_account(client, token, tenant.id, label="Work")
    account_b = _create_account(client, token, tenant.id, label="Personal")

    listed = client.get("/api/v1/connectors/google/accounts", headers=_auth(token, tenant.id))
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert ids == {account_a, account_b}


def test_primary_account_assignment_and_switch(client, db_session):
    tenant = _seed_tenant(db_session, slug="google-primary")
    user = _seed_user(db_session, tenant=tenant, email="primary@example.com", is_default=True)
    token = _login(client, email=user.email)

    first = client.post(
        "/api/v1/connectors/google/accounts",
        headers=_auth(token, tenant.id),
        json={
            "label": "Work",
            "enabled": True,
            "gmail_enabled": True,
            "gmail_labels": ["INBOX"],
            "calendar_enabled": True,
            "calendar_ids": ["primary"],
        },
    )
    assert first.status_code == 200
    first_id = first.json()["id"]
    assert first.json()["is_primary"] is True

    second = client.post(
        "/api/v1/connectors/google/accounts",
        headers=_auth(token, tenant.id),
        json={
            "label": "Personal",
            "enabled": True,
            "gmail_enabled": True,
            "gmail_labels": ["INBOX"],
            "calendar_enabled": True,
            "calendar_ids": ["primary"],
        },
    )
    assert second.status_code == 200
    second_id = second.json()["id"]
    assert second.json()["is_primary"] is False

    switched = client.patch(
        f"/api/v1/connectors/google/accounts/{second_id}",
        headers=_auth(token, tenant.id),
        json={"is_primary": True},
    )
    assert switched.status_code == 200
    assert switched.json()["is_primary"] is True

    listed = client.get("/api/v1/connectors/google/accounts", headers=_auth(token, tenant.id))
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()}
    assert by_id[first_id]["is_primary"] is False
    assert by_id[second_id]["is_primary"] is True


def test_google_oauth_callback_is_bound_to_user_and_account(client, db_session):
    tenant = _seed_tenant(db_session, slug="google-oauth-user-scope")
    user_a = _seed_user(db_session, tenant=tenant, email="user-a@example.com", is_default=True)
    user_b = _seed_user(db_session, tenant=tenant, email="user-b@example.com")
    token_a = _login(client, email=user_a.email)
    token_b = _login(client, email=user_b.email)

    account_id = _create_account(client, token_a, tenant.id, label="A")

    start = client.get(
        f"/api/v1/connectors/google/accounts/{account_id}/oauth/start",
        headers=_auth(token_a, tenant.id),
        params={"redirect_uri": "http://localhost:5173/connectors/google"},
    )
    assert start.status_code == 200
    state = start.json()["state"]

    forbidden = client.get(
        "/api/v1/connectors/google/oauth/callback",
        headers=_auth(token_b, tenant.id),
        params={"code": "oauth-code", "state": state},
    )
    assert forbidden.status_code == 403


def test_google_account_actions_are_user_scoped(client, db_session):
    tenant = _seed_tenant(db_session, slug="google-user-scope")
    user_a = _seed_user(db_session, tenant=tenant, email="scope-a@example.com", is_default=True)
    user_b = _seed_user(db_session, tenant=tenant, email="scope-b@example.com")
    token_a = _login(client, email=user_a.email)
    token_b = _login(client, email=user_b.email)

    account_id = _create_account(client, token_a, tenant.id)

    not_found = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/test",
        headers=_auth(token_b, tenant.id),
    )
    assert not_found.status_code == 404


def test_google_sync_writes_private_docs_with_account_prefixed_ids(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="google-sync-private")
    user = _seed_user(db_session, tenant=tenant, email="private@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)
    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None
    account.access_token_encrypted = encrypt_secret("token")
    account.refresh_token_encrypted = encrypt_secret("refresh")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    def fake_google_request(**kwargs):
        url = kwargs["url"]
        method = kwargs["method"]
        params = kwargs.get("params") or {}
        if method == "GET" and url.endswith("/messages"):
            label = params.get("labelIds")
            if label == "INBOX":
                return {"messages": [{"id": "m-1"}]}
            if label == "SENT":
                return {"messages": []}
            return {"messages": []}
        if method == "GET" and url.endswith("/messages/m-1"):
            return {
                "id": "m-1",
                "threadId": "t-1",
                "labelIds": ["INBOX"],
                "internalDate": "1707600000000",
                "snippet": "snippet inbox",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Inbox Subject"},
                        {"name": "From", "value": "Sender <sender@example.com>"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": "SW5ib3ggYm9keQ"},
                },
            }
        if method == "GET" and "/calendar/v3/calendars/primary/events" in url:
            return {
                "items": [
                    {
                        "id": "evt-1",
                        "status": "confirmed",
                        "summary": "Design Review",
                        "description": "Architecture",
                        "location": "Room A",
                        "htmlLink": "https://calendar.google.com/event?eid=evt-1",
                        "created": "2026-02-20T00:00:00Z",
                        "updated": "2026-02-20T01:00:00Z",
                        "creator": {"email": "owner@example.com"},
                        "start": {"dateTime": "2026-02-25T10:00:00Z"},
                        "end": {"dateTime": "2026-02-25T11:00:00Z"},
                        "attendees": [{"email": "a@example.com"}],
                    }
                ]
            }
        return {}

    monkeypatch.setattr("app.services.connectors.google_service._google_request", fake_google_request)

    synced = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/sync",
        headers=_auth(token, tenant.id),
    )
    assert synced.status_code == 200
    assert synced.json()["items_synced"] == 2

    docs = db_session.execute(
        select(Document).where(
            Document.tenant_id == tenant.id,
            Document.source_type.in_(["google_gmail", "google_calendar"]),
        )
    ).scalars().all()
    assert len(docs) == 2
    assert all(doc.source_id.startswith(f"{account_id}:") for doc in docs)

    acl_ids = {doc.acl_policy_id for doc in docs}
    assert None not in acl_ids
    policy_id = next(iter(acl_ids))
    policy = db_session.get(ACLPolicy, policy_id)
    assert policy is not None
    assert policy.allowed_user_ids == [user.id]


def test_new_account_requires_sync_scope_before_sync(client, db_session):
    tenant = _seed_tenant(db_session, slug="google-sync-scope-required")
    user = _seed_user(db_session, tenant=tenant, email="scope-required@example.com", is_default=True)
    token = _login(client, email=user.email)

    created = client.post(
        "/api/v1/connectors/google/accounts",
        headers=_auth(token, tenant.id),
        json={
            "label": "Work",
            "enabled": True,
            "gmail_enabled": True,
            "gmail_labels": ["INBOX"],
            "calendar_enabled": True,
            "calendar_ids": ["primary"],
            "sync_scope_configured": False,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["id"]

    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None
    account.access_token_encrypted = encrypt_secret("token")
    account.refresh_token_encrypted = encrypt_secret("refresh")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    response = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/sync",
        headers=_auth(token, tenant.id),
    )
    assert response.status_code == 400
    assert "Sync scope is not configured" in response.json()["detail"]


def test_gmail_sync_last_n_days_applies_query(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="google-sync-last-n-days")
    user = _seed_user(db_session, tenant=tenant, email="last-days@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)
    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None
    account.access_token_encrypted = encrypt_secret("token")
    account.refresh_token_encrypted = encrypt_secret("refresh")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    account.gmail_sync_mode = "last_n_days"
    account.gmail_last_n_days = 7
    db_session.commit()

    seen_queries: list[str] = []

    def fake_google_request(**kwargs):
        url = kwargs["url"]
        params = kwargs.get("params") or {}
        if kwargs["method"] == "GET" and url.endswith("/messages"):
            seen_queries.append(str(params.get("q") or ""))
            return {"messages": []}
        if kwargs["method"] == "GET" and "/calendar/v3/calendars/primary/events" in url:
            return {"items": []}
        return {}

    monkeypatch.setattr("app.services.connectors.google_service._google_request", fake_google_request)

    response = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/sync",
        headers=_auth(token, tenant.id),
    )
    assert response.status_code == 200
    assert any("newer_than:7d" in value for value in seen_queries)


def test_calendar_sync_range_days_applies_time_window(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="google-sync-calendar-range")
    user = _seed_user(db_session, tenant=tenant, email="calendar-range@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)
    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None
    account.access_token_encrypted = encrypt_secret("token")
    account.refresh_token_encrypted = encrypt_secret("refresh")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    account.calendar_sync_mode = "range_days"
    account.calendar_days_back = 3
    account.calendar_days_forward = 10
    db_session.commit()

    seen_time_min: list[str] = []
    seen_time_max: list[str] = []

    def fake_google_request(**kwargs):
        url = kwargs["url"]
        params = kwargs.get("params") or {}
        if kwargs["method"] == "GET" and url.endswith("/messages"):
            return {"messages": []}
        if kwargs["method"] == "GET" and "/calendar/v3/calendars/primary/events" in url:
            seen_time_min.append(str(params.get("timeMin") or ""))
            seen_time_max.append(str(params.get("timeMax") or ""))
            return {"items": []}
        return {}

    monkeypatch.setattr("app.services.connectors.google_service._google_request", fake_google_request)

    response = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/sync",
        headers=_auth(token, tenant.id),
    )
    assert response.status_code == 200
    assert any(value for value in seen_time_min)
    assert any(value for value in seen_time_max)


def test_disconnect_soft_deletes_google_documents(client, db_session):
    tenant = _seed_tenant(db_session, slug="google-disconnect")
    user = _seed_user(db_session, tenant=tenant, email="disconnect@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)
    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None

    doc = Document(
        tenant_id=tenant.id,
        source_type="google_gmail",
        source_id=f"{account_id}:gmail:m-1",
        title="Mail",
        raw_text="Body",
        metadata_json={"google_connector_account_id": account_id},
        tags_json=[],
    )
    db_session.add(doc)
    db_session.commit()

    deleted = client.delete(
        f"/api/v1/connectors/google/accounts/{account_id}",
        headers=_auth(token, tenant.id),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_docs_count"] == 1

    account_after = db_session.get(GoogleUserConnector, account_id)
    assert account_after is None

    doc_after = db_session.get(Document, doc.id)
    assert doc_after is not None
    assert doc_after.deleted_at is not None


def test_google_calendar_event_crud_scoped_by_account(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="google-calendar-crud")
    user = _seed_user(db_session, tenant=tenant, email="calendar@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)
    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None
    account.access_token_encrypted = encrypt_secret("token")
    account.refresh_token_encrypted = encrypt_secret("refresh")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    def fake_google_request(**kwargs):
        method = kwargs["method"]
        if method == "POST":
            return {
                "id": "evt-1",
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/event?eid=evt-1",
                "summary": "Kickoff",
                "start": {"dateTime": "2026-03-01T09:00:00Z"},
                "end": {"dateTime": "2026-03-01T10:00:00Z"},
            }
        if method == "PUT":
            return {
                "id": "evt-1",
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/event?eid=evt-1",
                "summary": "Kickoff Updated",
                "start": {"dateTime": "2026-03-01T09:00:00Z"},
                "end": {"dateTime": "2026-03-01T10:30:00Z"},
            }
        return {}

    monkeypatch.setattr("app.services.connectors.google_service._google_request", fake_google_request)

    created = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/calendar/events",
        headers=_auth(token, tenant.id),
        json={
            "calendar_id": "primary",
            "summary": "Kickoff",
            "description": "Initial meeting",
            "start_datetime": "2026-03-01T09:00:00Z",
            "end_datetime": "2026-03-01T10:00:00Z",
            "timezone": "UTC",
            "attendees": ["a@example.com"],
        },
    )
    assert created.status_code == 200
    assert created.json()["id"] == "evt-1"

    updated = client.put(
        f"/api/v1/connectors/google/accounts/{account_id}/calendar/events/evt-1",
        headers=_auth(token, tenant.id),
        json={
            "calendar_id": "primary",
            "summary": "Kickoff Updated",
            "description": "Updated",
            "start_datetime": "2026-03-01T09:00:00Z",
            "end_datetime": "2026-03-01T10:30:00Z",
            "timezone": "UTC",
            "attendees": ["a@example.com"],
        },
    )
    assert updated.status_code == 200

    deleted = client.delete(
        f"/api/v1/connectors/google/accounts/{account_id}/calendar/events/evt-1",
        headers=_auth(token, tenant.id),
        params={"calendar_id": "primary"},
    )
    assert deleted.status_code == 200


def test_google_list_calendars_for_account(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="google-calendar-list")
    user = _seed_user(db_session, tenant=tenant, email="calendar-list@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)
    account = db_session.get(GoogleUserConnector, account_id)
    assert account is not None
    account.access_token_encrypted = encrypt_secret("token")
    account.refresh_token_encrypted = encrypt_secret("refresh")
    account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    def fake_google_request(**kwargs):
        if kwargs["method"] == "GET" and kwargs["url"].endswith("/users/me/calendarList"):
            return {
                "items": [
                    {
                        "id": "primary",
                        "summary": "Personal",
                        "primary": True,
                        "accessRole": "owner",
                        "selected": True,
                    },
                    {
                        "id": "team@example.com",
                        "summary": "Team",
                        "primary": False,
                        "accessRole": "writer",
                        "selected": True,
                    },
                ]
            }
        return {}

    monkeypatch.setattr("app.services.connectors.google_service._google_request", fake_google_request)

    response = client.get(
        f"/api/v1/connectors/google/accounts/{account_id}/calendars",
        headers=_auth(token, tenant.id),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "primary"
    assert payload[1]["id"] == "team@example.com"


def test_worker_sync_processes_enabled_google_user_accounts(db_session, monkeypatch):
    tenant_a = _seed_tenant(db_session, slug="google-worker-a")
    tenant_b = _seed_tenant(db_session, slug="google-worker-b")
    user_a = _seed_user(db_session, tenant=tenant_a, email="worker-a@example.com", is_default=True)
    user_b = _seed_user(db_session, tenant=tenant_b, email="worker-b@example.com", is_default=True)

    db_session.add_all(
        [
            GoogleUserConnector(
                tenant_id=tenant_a.id,
                user_id=user_a.id,
                label="A",
                access_token_encrypted=encrypt_secret("token-a"),
                refresh_token_encrypted=encrypt_secret("refresh-a"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                gmail_enabled=True,
                calendar_enabled=False,
                gmail_labels=["INBOX"],
                calendar_ids=["primary"],
                enabled=True,
                sync_scope_configured=True,
            ),
            GoogleUserConnector(
                tenant_id=tenant_b.id,
                user_id=user_b.id,
                label="B",
                access_token_encrypted=encrypt_secret("token-b"),
                refresh_token_encrypted=encrypt_secret("refresh-b"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                gmail_enabled=False,
                calendar_enabled=True,
                gmail_labels=["INBOX"],
                calendar_ids=["primary"],
                enabled=True,
                sync_scope_configured=True,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")

    def fake_google_request(**kwargs):
        url = kwargs["url"]
        if url.endswith("/messages"):
            return {"messages": []}
        if "/calendar/v3/calendars/primary/events" in url:
            return {"items": []}
        if url.endswith("/userinfo"):
            return {"email": "owner@example.com", "id": "sub-1"}
        return {}

    monkeypatch.setattr("app.services.connectors.google_service._google_request", fake_google_request)
    monkeypatch.setattr("app.tasks.celery_app.SessionLocal", lambda: db_session)

    result = sync_google_connectors()
    assert result["success"] == 2
    assert result["failed"] == 0


def test_missing_google_credentials_returns_400(client, db_session, monkeypatch):
    tenant = _seed_tenant(db_session, slug="google-missing-creds")
    user = _seed_user(db_session, tenant=tenant, email="missing-creds@example.com", is_default=True)
    token = _login(client, email=user.email)

    account_id = _create_account(client, token, tenant.id)

    monkeypatch.setattr("app.core.config.settings.google_client_id", "")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "")

    response = client.post(
        f"/api/v1/connectors/google/accounts/{account_id}/test",
        headers=_auth(token, tenant.id),
    )
    assert response.status_code == 400
    assert "GOOGLE_CLIENT_ID" in response.json()["detail"]
