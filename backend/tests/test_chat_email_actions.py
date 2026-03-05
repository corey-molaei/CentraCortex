from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import encrypt_secret, get_password_hash
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.llm_provider import LLMProvider
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


def _seed_provider(
    db_session,
    *,
    tenant_id: str,
    name: str = "Parser Provider",
    model_name: str = "gemma3:4b",
    is_default: bool = False,
) -> LLMProvider:
    provider = LLMProvider(
        tenant_id=tenant_id,
        name=name,
        provider_type="ollama",
        base_url="http://localhost:11434",
        api_key_encrypted=None,
        model_name=model_name,
        is_default=is_default,
        is_fallback=False,
        rate_limit_rpm=1000,
        config_json={},
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)
    return provider


def test_chat_summarise_spelling_routes_to_summarize(client, db_session, monkeypatch):
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
        json={"messages": [{"role": "user", "content": "summarise my last 2 emails"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "I found 2 recent emails across" in body["answer"]
    assert "hr@example.com - 1 emails" in body["answer"]
    assert "pm@example.com - 1 emails" in body["answer"]


def test_chat_summarize_sender_group_includes_count_and_group_summary(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-summary-group@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="summary@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Payroll Reminder",
                "from": "HR <hr@example.com>",
                "sent_at": "2026-02-24T03:00:00+00:00",
                "snippet": "Please review your payroll details.",
            },
            {
                "id": "m-2",
                "subject": "Payroll Reminder",
                "from": "HR <hr@example.com>",
                "sent_at": "2026-02-23T03:00:00+00:00",
                "snippet": "Please review your payroll details.",
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
    assert "hr@example.com - 2 emails" in body["answer"]
    assert "Summary: Please review your payroll details." in body["answer"]


def test_chat_summarize_sender_group_with_multiple_topics_renders_topic_bullets(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-summary-topics@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="summary@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Offer One",
                "from": "Ads <ads@example.com>",
                "sent_at": "2026-02-24T05:00:00+00:00",
                "snippet": "Save 10 percent today.",
            },
            {
                "id": "m-2",
                "subject": "Offer One",
                "from": "Ads <ads@example.com>",
                "sent_at": "2026-02-24T04:00:00+00:00",
                "snippet": "Save 10 percent today.",
            },
            {
                "id": "m-3",
                "subject": "Offer Two",
                "from": "Ads <ads@example.com>",
                "sent_at": "2026-02-23T05:00:00+00:00",
                "snippet": "Spring sale starts now.",
            },
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "summarize my last 3 emails"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "ads@example.com - 3 emails" in body["answer"]
    assert "- Offer One (2): Save 10 percent today." in body["answer"]
    assert "- Offer Two (1): Spring sale starts now." in body["answer"]


def test_chat_summarize_single_topic_sender_has_no_topic_bullets(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-summary-single-topic@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="summary@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Newsletter",
                "from": "News <news@example.com>",
                "sent_at": "2026-02-24T02:00:00+00:00",
                "snippet": "Weekly digest updates.",
            },
            {
                "id": "m-2",
                "subject": "Newsletter",
                "from": "News <news@example.com>",
                "sent_at": "2026-02-23T02:00:00+00:00",
                "snippet": "Weekly digest updates.",
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
    assert "news@example.com - 2 emails" in body["answer"]
    assert "- Newsletter (" not in body["answer"]


def test_chat_list_remains_itemized_not_grouped(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-list-itemized@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="summary@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Subject 1",
                "from": "One <one@example.com>",
                "sent_at": "2026-02-24T02:00:00+00:00",
                "snippet": "one",
            },
            {
                "id": "m-2",
                "subject": "Subject 2",
                "from": "Two <two@example.com>",
                "sent_at": "2026-02-23T02:00:00+00:00",
                "snippet": "two",
            },
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "list my last 2 emails"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "Here are the emails I found:" in body["answer"]
    assert "[m-1]" in body["answer"]
    assert "[m-2]" in body["answer"]
    assert "sender groups" not in body["answer"]


def test_today_s_emails_routes_to_list(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-today@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="today@gmail.com")

    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Today Update",
                "from": "Ops <ops@example.com>",
                "sent_at": "2026-03-05T05:00:00+11:00",
                "snippet": "today update",
            }
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={
            "messages": [{"role": "user", "content": "today's emails"}],
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-05T18:00:00+11:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "Here are the emails I found:" in body["answer"]
    assert "[m-1]" in body["answer"]


def test_today_scope_uses_client_timezone_calendar_day(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-today-scope@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="today@gmail.com")

    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Today Morning",
                "from": "Ops <ops@example.com>",
                "sent_at": "2026-03-05T09:00:00+11:00",
                "snippet": "today morning",
            },
            {
                "id": "m-2",
                "subject": "Yesterday Late",
                "from": "Ops <ops@example.com>",
                "sent_at": "2026-03-04T23:30:00+11:00",
                "snippet": "yesterday",
            },
            {
                "id": "m-3",
                "subject": "Today Noon",
                "from": "Ops <ops@example.com>",
                "sent_at": "2026-03-05T12:00:00+11:00",
                "snippet": "today noon",
            },
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={
            "messages": [{"role": "user", "content": "today's emails"}],
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-05T18:00:00+11:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "[m-1]" in body["answer"]
    assert "[m-3]" in body["answer"]
    assert "[m-2]" not in body["answer"]


def test_email_llm_intent_parser_fallback_on_failure(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-intent-fallback@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="today@gmail.com")

    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Fallback Result",
                "from": "Ops <ops@example.com>",
                "sent_at": "2026-03-05T09:00:00+11:00",
                "snippet": "fallback",
            }
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={
            "messages": [{"role": "user", "content": "today's emails"}],
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-05T18:00:00+11:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "Here are the emails I found:" in body["answer"]


def test_ambiguous_inbox_phrase_defaults_to_list(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-inbox-default@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="today@gmail.com")

    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Inbox Result",
                "from": "Ops <ops@example.com>",
                "sent_at": "2026-03-05T09:00:00+11:00",
                "snippet": "inbox result",
            }
        ],
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={
            "messages": [{"role": "user", "content": "inbox today"}],
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-05T18:00:00+11:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "Here are the emails I found:" in body["answer"]


def test_read_requires_message_id_still_enforced(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-read-requires-id@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="reader@gmail.com")
    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "read email"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Please provide the email id to read." in body["answer"]


def test_chat_email_access_query_uses_email_action_engine(client, db_session):
    tenant, user = _seed_tenant_with_user(db_session, email="email-access@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="molaei.kourosh87@gmail.com")

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "do you have access to my inbox on molaei.kourosh87@gmail.com"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "Yes, I can access your inbox" in body["answer"]
    assert "Source: Gmail." in body["answer"]
    assert "Subject:" not in body["answer"]
    assert "Summary:" not in body["answer"]


def test_chat_email_access_query_no_account_returns_guidance(client, db_session):
    tenant, user = _seed_tenant_with_user(db_session, email="email-access-none@example.com")
    token = _login(client, email=user.email)

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "do you have access to my inbox on molaei.kourosh87@gmail.com"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "I could not find a connected email account" in body["answer"]
    assert "/connectors/google" in body["answer"]
    assert "/connectors/email" in body["answer"]


def test_chat_email_like_unmatched_prompt_returns_email_help_not_rag(client, db_session):
    tenant, user = _seed_tenant_with_user(db_session, email="email-help@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="helper@gmail.com")

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "can you use my inbox"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "I can help with email actions" in body["answer"]
    assert "summarize my last 5 emails" in body["answer"]


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
    assert sent["subject"] == "status"


def test_send_parser_strips_say_prefix_and_generates_subject(client, db_session):
    tenant, user = _seed_tenant_with_user(db_session, email="email-send-clean@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "send email to molaei.kourosh@gmail.com say let's have fun after work tomorrow",
                }
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "Email Action Engine"
    assert "Please confirm sending this email" in body["answer"]
    assert "To: molaei.kourosh@gmail.com" in body["answer"]
    assert "body preview: let's have fun after work tomorrow" in body["answer"].lower()
    assert "body preview: say let's have fun after work tomorrow" not in body["answer"].lower()
    assert "Subject: (No subject)" not in body["answer"]
    assert "Subject was auto-generated from your message." in body["answer"]


def test_send_parser_fallback_when_llm_parse_fails(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-send-fallback@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    monkeypatch.setattr("app.services.chat_email_actions._parse_send_request_llm", lambda *args, **kwargs: None)

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "send email to bob@example.com say hello from fallback"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Please confirm sending this email" in body["answer"]
    assert "To: bob@example.com" in body["answer"]
    assert "body preview: hello from fallback" in body["answer"].lower()


def test_send_parser_uses_provider_override_without_fallback(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-send-override@example.com")
    token = _login(client, email=user.email)
    override_provider = _seed_provider(db_session, tenant_id=tenant.id, is_default=True)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    captured: dict = {}

    def fake_chat(self, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        return (
            type("Provider", (), {"id": "provider-4b", "name": "Parser", "model_name": "gemma3:4b"})(),
            {
                "answer": (
                    '{"to":["molaei.kourosh@gmail.com"],"cc":[],"bcc":[],"subject":"Override Subject",'
                    '"body":"Override body","inferred_subject":false,"cleanup_notes":[]}'
                ),
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.chat_email_actions.LLMRouter.chat", fake_chat)

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={
            "messages": [{"role": "user", "content": "send email to molaei.kourosh@gmail.com about override body: hello"}],
            "provider_id_override": override_provider.id,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "Please confirm sending this email" in body["answer"]
    assert captured["provider_id_override"] == override_provider.id
    assert captured["allow_fallback"] is False


def test_send_parser_does_not_invent_recipients(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-send-recipient-guard@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions._parse_send_request_llm",
        lambda *args, **kwargs: {
            "to": ["molaei.kourosh@gmail.com", "invented@example.com"],
            "cc": [],
            "bcc": [],
            "subject": "Hi",
            "body": "say hello",
            "inferred_subject": False,
            "cleanup_notes": [],
        },
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "send email to molaei.kourosh@gmail.com say hello"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert "To: molaei.kourosh@gmail.com" in body["answer"]
    assert "invented@example.com" not in body["answer"]


def test_send_missing_body_still_requests_more_info(client, db_session, monkeypatch):
    tenant, user = _seed_tenant_with_user(db_session, email="email-send-missing-body@example.com")
    token = _login(client, email=user.email)
    _seed_google_account(db_session, tenant_id=tenant.id, user_id=user.id, email="sender@gmail.com")

    monkeypatch.setattr(
        "app.services.chat_email_actions._parse_send_request_llm",
        lambda *args, **kwargs: {
            "to": ["molaei.kourosh@gmail.com"],
            "cc": [],
            "bcc": [],
            "subject": "test",
            "body": "",
            "inferred_subject": False,
            "cleanup_notes": [],
        },
    )

    response = client.post(
        "/api/v1/chat/complete",
        headers=_auth(token, tenant.id),
        json={"messages": [{"role": "user", "content": "send email to molaei.kourosh@gmail.com"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert "I can send the email, but I still need: email body." in body["answer"]


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
