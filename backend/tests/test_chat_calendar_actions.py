from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import encrypt_secret, get_password_hash
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.llm_provider import LLMProvider
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.services.llm_router import LLMRouter


def _seed_tenant_with_user(db_session, *, email: str) -> tuple[Tenant, User]:
    tenant = Tenant(name="Calendar Tenant", slug=f"calendar-{email.split('@')[0]}")
    user = User(email=email, full_name="Calendar User", hashed_password=get_password_hash("password123"))

    db_session.add_all([tenant, user])
    db_session.flush()
    db_session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="User", is_default=True))
    db_session.commit()
    return tenant, user


def _login(client, *, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str, tenant_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}


def _seed_connected_google_account(
    db_session,
    *,
    tenant_id: str,
    user_id: str,
    label: str,
    is_primary: bool,
    calendar_ids: list[str] | None = None,
) -> GoogleUserConnector:
    account = GoogleUserConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        label=label,
        google_account_email=f"{label.lower()}@example.com",
        google_account_sub=f"sub-{label.lower()}",
        access_token_encrypted=encrypt_secret("token"),
        refresh_token_encrypted=encrypt_secret("refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
        enabled=True,
        gmail_enabled=True,
        calendar_enabled=True,
        gmail_labels=["INBOX"],
        calendar_ids=calendar_ids or ["primary"],
        is_primary=is_primary,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


@pytest.fixture(autouse=True)
def google_oauth_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")


def test_chat_create_meeting_uses_primary_account_and_client_timezone(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-create@example.com")
    token = _login(client, email=user.email)

    non_primary = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Secondary",
        is_primary=False,
    )
    primary = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Primary",
        is_primary=True,
    )

    captured: dict = {}

    def fake_create_event(db, connector, *, client_id, client_secret, payload):  # noqa: ARG001
        captured["account_id"] = connector.id
        captured["payload"] = payload
        return {
            "id": "evt-created",
            "calendar_id": "primary",
            "summary": payload["summary"],
            "start_datetime": payload["start_datetime"],
            "end_datetime": payload["end_datetime"],
        }

    monkeypatch.setattr("app.services.chat_calendar_actions.create_event", fake_create_event)

    response = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "add a meeting tomorrow 2pm"}],
            "client_timezone": "America/Los_Angeles",
        },
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_name"] == "Calendar Action Engine"
    assert "Meeting created" in payload["answer"]

    assert captured["account_id"] != non_primary.id
    assert captured["account_id"] == primary.id
    assert captured["payload"]["timezone"] == "America/Los_Angeles"

    start_dt = datetime.fromisoformat(captured["payload"]["start_datetime"])
    end_dt = datetime.fromisoformat(captured["payload"]["end_datetime"])
    assert int((end_dt - start_dt).total_seconds()) == 3600


def test_chat_create_meeting_includes_attendees(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-create-attendees@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="life",
        is_primary=True,
    )

    captured: dict = {}

    def fake_create_event(db, connector, *, client_id, client_secret, payload):  # noqa: ARG001
        captured["account_id"] = connector.id
        captured["payload"] = payload
        return {
            "id": "evt-created-attendees",
            "calendar_id": "primary",
            "summary": payload["summary"],
            "start_datetime": payload["start_datetime"],
            "end_datetime": payload["end_datetime"],
        }

    monkeypatch.setattr("app.services.chat_calendar_actions.create_event", fake_create_event)

    response = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "create meeting on life attendee molaei.kourosh@gmail.com for tomorrow 5pm about testing",
                }
            ],
            "client_timezone": "Australia/Sydney",
        },
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert "with attendee molaei.kourosh@gmail.com" in payload["answer"]
    assert captured["payload"]["attendees"] == ["molaei.kourosh@gmail.com"]


def test_chat_update_meeting_requires_confirmation(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-update@example.com")
    token = _login(client, email=user.email)

    account = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Primary",
        is_primary=True,
    )

    monkeypatch.setattr(
        "app.services.chat_calendar_actions.list_events",
        lambda *args, **kwargs: [
            {
                "id": "evt-1",
                "calendar_id": "primary",
                "summary": "Daily Standup",
                "start_datetime": "2026-02-24T14:00:00+00:00",
                "end_datetime": "2026-02-24T15:00:00+00:00",
                "description": "daily",
                "location": "Room 1",
            }
        ],
    )

    updated_calls: dict = {}

    def fake_update_event(db, connector, *, client_id, client_secret, event_id, payload):  # noqa: ARG001
        updated_calls["account_id"] = connector.id
        updated_calls["event_id"] = event_id
        updated_calls["payload"] = payload
        return {
            "id": event_id,
            "calendar_id": payload["calendar_id"],
            "summary": payload["summary"],
            "start_datetime": payload["start_datetime"],
            "end_datetime": payload["end_datetime"],
        }

    monkeypatch.setattr("app.services.chat_calendar_actions.update_event", fake_update_event)

    first = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "move my standup tomorrow to 3pm"}],
            "client_timezone": "UTC",
        },
        headers=_auth(token, tenant.id),
    )
    assert first.status_code == 200
    first_body = first.json()
    assert "Reply with a number" in first_body["answer"]
    conversation_id = first_body["conversation_id"]

    select_candidate = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "1"}],
            "conversation_id": conversation_id,
            "client_timezone": "UTC",
        },
        headers=_auth(token, tenant.id),
    )
    assert select_candidate.status_code == 200
    assert "Reply yes/no" in select_candidate.json()["answer"]

    confirm = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "yes"}],
            "conversation_id": conversation_id,
            "client_timezone": "UTC",
        },
        headers=_auth(token, tenant.id),
    )
    assert confirm.status_code == 200
    assert "Updated" in confirm.json()["answer"]

    assert updated_calls["account_id"] == account.id
    assert updated_calls["event_id"] == "evt-1"


def test_chat_delete_meeting_disambiguation_and_confirmation(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-delete@example.com")
    token = _login(client, email=user.email)

    account = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Primary",
        is_primary=True,
    )

    monkeypatch.setattr(
        "app.services.chat_calendar_actions.list_events",
        lambda *args, **kwargs: [
            {
                "id": "evt-1",
                "calendar_id": "primary",
                "summary": "Team Sync",
                "start_datetime": "2026-02-24T14:00:00+00:00",
                "end_datetime": "2026-02-24T15:00:00+00:00",
            },
            {
                "id": "evt-2",
                "calendar_id": "primary",
                "summary": "Team Sync",
                "start_datetime": "2026-02-24T16:00:00+00:00",
                "end_datetime": "2026-02-24T17:00:00+00:00",
            },
        ],
    )

    deleted_calls: dict = {}

    def fake_delete_event(db, connector, *, client_id, client_secret, calendar_id, event_id):  # noqa: ARG001
        deleted_calls["account_id"] = connector.id
        deleted_calls["calendar_id"] = calendar_id
        deleted_calls["event_id"] = event_id

    monkeypatch.setattr("app.services.chat_calendar_actions.delete_event", fake_delete_event)

    first = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "delete my team sync meeting tomorrow"}]},
        headers=_auth(token, tenant.id),
    )
    assert first.status_code == 200
    assert "Reply with a number" in first.json()["answer"]
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "2"}], "conversation_id": conversation_id},
        headers=_auth(token, tenant.id),
    )
    assert second.status_code == 200
    assert "Reply yes/no" in second.json()["answer"]

    third = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "yes"}], "conversation_id": conversation_id},
        headers=_auth(token, tenant.id),
    )
    assert third.status_code == 200
    assert "Deleted" in third.json()["answer"]

    assert deleted_calls["account_id"] == account.id
    assert deleted_calls["event_id"] == "evt-2"


def test_chat_delete_by_time_range_without_title(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-delete-range@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="molaei.kourosh87@gmail.com",
        is_primary=True,
    )

    captured_queries: list[str | None] = []

    def fake_list_events(*args, **kwargs):
        query = kwargs.get("query")
        captured_queries.append(query)
        return [
            {
                "id": "evt-range-1",
                "calendar_id": "primary",
                "summary": "Meeting",
                "start_datetime": "2026-02-25T04:00:00+00:00",
                "end_datetime": "2026-02-25T05:00:00+00:00",
            }
        ]

    deleted_calls: dict = {}

    def fake_delete_event(db, connector, *, client_id, client_secret, calendar_id, event_id):  # noqa: ARG001
        deleted_calls["account_id"] = connector.id
        deleted_calls["calendar_id"] = calendar_id
        deleted_calls["event_id"] = event_id

    monkeypatch.setattr("app.services.chat_calendar_actions.list_events", fake_list_events)
    monkeypatch.setattr("app.services.chat_calendar_actions.delete_event", fake_delete_event)

    first = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "delete meeting on molaei.kourosh87@gmail.com "
                        "from 2026-02-25 15:00 AEDT to 2026-02-25 16:00 AEDT"
                    ),
                }
            ],
            "client_timezone": "Australia/Sydney",
        },
        headers=_auth(token, tenant.id),
    )
    assert first.status_code == 200
    assert "Reply yes/no" in first.json()["answer"]
    assert captured_queries and captured_queries[0] is None
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "yes"}], "conversation_id": conversation_id},
        headers=_auth(token, tenant.id),
    )
    assert second.status_code == 200
    assert "Deleted" in second.json()["answer"]
    assert deleted_calls["event_id"] == "evt-range-1"


def test_chat_delete_by_single_time_and_account_email(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-delete-single@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="molaei.kourosh87@gmail.com",
        is_primary=True,
    )

    captured_queries: list[str | None] = []

    def fake_list_events(*args, **kwargs):
        captured_queries.append(kwargs.get("query"))
        return [
            {
                "id": "evt-single-1",
                "calendar_id": "primary",
                "summary": "Meeting",
                "start_datetime": "2026-02-24T04:00:00+00:00",
                "end_datetime": "2026-02-24T05:00:00+00:00",
            }
        ]

    deleted_calls: dict = {}

    def fake_delete_event(db, connector, *, client_id, client_secret, calendar_id, event_id):  # noqa: ARG001
        deleted_calls["account_id"] = connector.id
        deleted_calls["calendar_id"] = calendar_id
        deleted_calls["event_id"] = event_id

    monkeypatch.setattr("app.services.chat_calendar_actions.list_events", fake_list_events)
    monkeypatch.setattr("app.services.chat_calendar_actions.delete_event", fake_delete_event)

    first = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "delete meeting on tomorrow 3pm on molaei.kourosh87@gmail.com",
                }
            ],
            "client_timezone": "Australia/Sydney",
        },
        headers=_auth(token, tenant.id),
    )
    assert first.status_code == 200
    assert "Reply with a number" in first.json()["answer"]
    assert captured_queries and captured_queries[0] is None
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "1"}], "conversation_id": conversation_id},
        headers=_auth(token, tenant.id),
    )
    assert second.status_code == 200
    assert "Reply yes/no" in second.json()["answer"]

    third = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "yes"}], "conversation_id": conversation_id},
        headers=_auth(token, tenant.id),
    )
    assert third.status_code == 200
    assert "Deleted" in third.json()["answer"]
    assert deleted_calls["event_id"] == "evt-single-1"


def test_chat_delete_single_time_uses_narrow_time_window_first(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-delete-window@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="molaei.kourosh87@gmail.com",
        is_primary=True,
    )

    call_params: list[dict] = []

    def fake_list_events(*args, **kwargs):
        call_params.append(kwargs)
        return [
            {
                "id": "evt-window-1",
                "calendar_id": "primary",
                "summary": "Meeting",
                "start_datetime": "2026-02-24T04:00:00+00:00",
                "end_datetime": "2026-02-24T05:00:00+00:00",
            }
        ]

    monkeypatch.setattr("app.services.chat_calendar_actions.list_events", fake_list_events)
    monkeypatch.setattr("app.services.chat_calendar_actions.delete_event", lambda *args, **kwargs: None)

    first = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "delete meeting tomorrow 3pm on molaei.kourosh87@gmail.com"}],
            "client_timezone": "Australia/Sydney",
        },
        headers=_auth(token, tenant.id),
    )
    assert first.status_code == 200
    assert "Reply with a number" in first.json()["answer"]
    assert call_params
    assert call_params[0]["query"] is None
    assert call_params[0]["limit"] >= 100


def test_chat_list_meetings_intent_returns_nearest_candidates(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-list@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Primary",
        is_primary=True,
    )

    monkeypatch.setattr(
        "app.services.chat_calendar_actions.list_events",
        lambda *args, **kwargs: [
            {
                "id": "evt-near",
                "calendar_id": "primary",
                "summary": "Salary Review",
                "start_datetime": "2026-02-25T15:02:00+11:00",
                "end_datetime": "2026-02-25T16:02:00+11:00",
            },
            {
                "id": "evt-far",
                "calendar_id": "primary",
                "summary": "Weekly Planning",
                "start_datetime": "2026-02-25T18:30:00+11:00",
                "end_datetime": "2026-02-25T19:00:00+11:00",
            },
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "find meetings on 2026-02-25 15:00 AEDT"}],
            "client_timezone": "Australia/Sydney",
        },
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "closest meetings" in answer.lower()
    assert "1. Salary Review" in answer


def test_chat_list_meetings_falls_back_to_primary_calendar_when_configured_id_missing(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-list-fallback@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Primary",
        is_primary=True,
        calendar_ids=["missing-calendar-id"],
    )

    seen_calendar_ids: list[str] = []

    def fake_list_events(*args, **kwargs):
        calendar_id = kwargs["calendar_id"]
        seen_calendar_ids.append(calendar_id)
        if calendar_id == "missing-calendar-id":
            raise ValueError("calendar 'missing-calendar-id': Google API request failed: Not Found")
        if calendar_id == "primary":
            return [
                {
                    "id": "evt-primary-1",
                    "calendar_id": "primary",
                    "summary": "Primary Calendar Event",
                    "start_datetime": "2026-02-25T15:00:00+11:00",
                    "end_datetime": "2026-02-25T16:00:00+11:00",
                }
            ]
        return []

    monkeypatch.setattr("app.services.chat_calendar_actions.list_events", fake_list_events)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "list meetings"}], "client_timezone": "Australia/Sydney"},
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "closest meetings" in answer.lower()
    assert "Primary Calendar Event" in answer
    assert seen_calendar_ids[:2] == ["missing-calendar-id", "primary"]


def test_chat_upcoming_meetings_phrase_routes_to_calendar_action(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-upcoming@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="life",
        is_primary=True,
    )

    monkeypatch.setattr(
        "app.services.chat_calendar_actions.list_events",
        lambda *args, **kwargs: [
            {
                "id": "evt-1",
                "calendar_id": "primary",
                "summary": "Life Planning",
                "start_datetime": "2026-02-25T13:00:00+11:00",
                "end_datetime": "2026-02-25T14:00:00+11:00",
            },
            {
                "id": "evt-2",
                "calendar_id": "primary",
                "summary": "Life Review",
                "start_datetime": "2026-02-25T18:00:00+11:00",
                "end_datetime": "2026-02-25T19:00:00+11:00",
            },
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "upcoming meetings on life"}]},
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_name"] == "Calendar Action Engine"
    assert "closest meetings" in payload["answer"].lower()
    assert "Life Planning" in payload["answer"]


def test_chat_list_meetings_dedupes_primary_and_email_calendar_alias(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-alias-dedupe@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="life",
        is_primary=True,
        calendar_ids=["molaei.kourosh87@gmail.com"],
    )

    def fake_list_events(*args, **kwargs):
        calendar_id = kwargs.get("calendar_id")
        if calendar_id in {"molaei.kourosh87@gmail.com", "primary"}:
            return [
                {
                    "id": "tblgnasksnfb1pq2d9d3kqcumg",
                    "calendar_id": calendar_id,
                    "summary": "salary",
                    "start_datetime": "2026-02-25T16:00:00+11:00",
                    "end_datetime": "2026-02-25T17:00:00+11:00",
                }
            ]
        return []

    monkeypatch.setattr("app.services.chat_calendar_actions.list_events", fake_list_events)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "upcoming meetings on life"}]},
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "1. salary" in answer
    assert "2. salary" not in answer


def test_chat_delete_surfaces_google_lookup_error_details(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-lookup-error@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Primary",
        is_primary=True,
    )

    def fake_list_events(*args, **kwargs):
        raise ValueError("token refresh failed: invalid_grant")

    monkeypatch.setattr("app.services.chat_calendar_actions.list_events", fake_list_events)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "delete meeting tomorrow 3pm"}], "client_timezone": "UTC"},
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    assert "Google calendar lookup failed: token refresh failed: invalid_grant" in response.json()["answer"]


def test_chat_list_connected_google_calendars(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-connected-list@example.com")
    token = _login(client, email=user.email)

    connected = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Work",
        is_primary=True,
        calendar_ids=["primary", "team@example.com"],
    )
    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Draft",
        is_primary=False,
    ).access_token_encrypted = None
    db_session.commit()

    def fake_list_calendars(db, connector, *, client_id, client_secret, limit=25):  # noqa: ARG001
        assert connector.id == connected.id
        return [
            {"id": "primary", "summary": "Personal", "primary": True, "access_role": "owner", "selected": True},
            {
                "id": "team@example.com",
                "summary": "Team Calendar",
                "primary": False,
                "access_role": "writer",
                "selected": True,
            },
        ]

    monkeypatch.setattr("app.services.chat_calendar_actions.list_calendars", fake_list_calendars)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "list google calendars that i have connected"}]},
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "connected Google accounts and calendars" in answer
    assert "Work (primary) - connected" in answer
    assert "google account email: work@example.com" in answer
    assert "Personal [primary]" in answer
    assert "Team Calendar [team@example.com]" in answer


def test_chat_selects_account_by_partial_label_match(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-label-match@example.com")
    token = _login(client, email=user.email)

    primary = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Work Main",
        is_primary=True,
    )
    secondary = _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Personal Finance",
        is_primary=False,
    )

    captured: dict = {}

    def fake_create_event(db, connector, *, client_id, client_secret, payload):  # noqa: ARG001
        captured["account_id"] = connector.id
        return {
            "id": "evt-created",
            "calendar_id": "primary",
            "summary": payload["summary"],
            "start_datetime": payload["start_datetime"],
            "end_datetime": payload["end_datetime"],
        }

    monkeypatch.setattr("app.services.chat_calendar_actions.create_event", fake_create_event)

    response = client.post(
        "/api/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "add a meeting tomorrow 2pm on personal account"}],
            "client_timezone": "UTC",
        },
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    assert "Meeting created" in response.json()["answer"]
    assert captured["account_id"] == secondary.id
    assert captured["account_id"] != primary.id


def test_chat_list_connected_google_calendars_surfaces_google_error(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-connected-list-error@example.com")
    token = _login(client, email=user.email)

    _seed_connected_google_account(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        label="Work",
        is_primary=True,
    )

    def fake_list_calendars(*args, **kwargs):
        raise ValueError("Google API request failed: Not Found")

    monkeypatch.setattr("app.services.chat_calendar_actions.list_calendars", fake_list_calendars)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "show my connected google calendars"}]},
        headers=_auth(token, tenant.id),
    )

    assert response.status_code == 200
    assert "available calendars error: Google API request failed: Not Found" in response.json()["answer"]


def test_non_calendar_chat_prompt_still_uses_llm(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="calendar-regression@example.com")
    token = _login(client, email=user.email)

    provider = LLMProvider(
        tenant_id=tenant.id,
        name="primary",
        provider_type="openai",
        base_url="https://api.openai.com",
        api_key_encrypted=None,
        model_name="gpt-primary",
        is_default=True,
        is_fallback=False,
        rate_limit_rpm=100,
        config_json={},
    )
    db_session.add(provider)
    db_session.commit()

    def fake_call(self, provider, messages, temperature):  # noqa: ARG001
        return {
            "answer": "normal llm answer",
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "total_tokens": 5,
            "cost_usd": 0.0,
        }

    monkeypatch.setattr(LLMRouter, "_call_provider", fake_call)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "What risks are open this week?"}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "normal llm answer"
    assert payload["provider_name"] == "primary"
