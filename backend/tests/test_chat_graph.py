from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.core.security import encrypt_secret, get_password_hash
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.llm_provider import LLMProvider
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.services.chat_calendar_actions import ParsedCalendarIntent


def _seed_and_login(client, db_session) -> str:
    tenant = Tenant(name="Graph Tenant", slug="graph-tenant")
    user = User(email="graph-admin@example.com", full_name="Graph Admin", hashed_password=get_password_hash("password123"))
    db_session.add_all([tenant, user])
    db_session.flush()
    db_session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="Owner", is_default=True))
    db_session.commit()

    response = client.post("/api/v1/auth/login", json={"email": "graph-admin@example.com", "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _seed_provider(
    db_session,
    *,
    tenant_id: str,
    name: str = "Mock Provider",
    model_name: str = "mock-model",
    is_default: bool = True,
) -> LLMProvider:
    provider = LLMProvider(
        tenant_id=tenant_id,
        name=name,
        provider_type="openai",
        base_url="https://mock-provider.local",
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


def _seed_google_account(db_session, *, tenant_id: str, user_id: str, email: str) -> GoogleUserConnector:
    account = GoogleUserConnector(
        tenant_id=tenant_id,
        user_id=user_id,
        label="Graph Gmail",
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


def test_chat_v2_complete_returns_graph_envelope(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)

    monkeypatch.setattr(
        "app.routers.chat_v2.run_chat_v2",
        lambda *args, **kwargs: SimpleNamespace(
            conversation_id="conv-1",
            assistant_message_id="msg-1",
            provider_id="provider-1",
            provider_name="Provider",
            model_name="model",
            answer="hello",
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
            cost_usd=0.0,
            blocked=False,
            safety_flags=[],
            citations=[],
            interaction_type="answer",
            action_context=None,
            options=[],
        ),
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == "conv-1"
    assert payload["interaction_type"] == "answer"


def test_chat_v2_confirm_and_select_endpoints(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)

    def fake_run_chat_v2(*args, **kwargs):
        content = kwargs["user_messages"][0]["content"]
        if content == "yes":
            return SimpleNamespace(
                conversation_id="conv-1",
                assistant_message_id="msg-confirm",
                provider_id="email-action",
                provider_name="Email Action Engine",
                model_name="email-action",
                answer="Confirmed",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=0.0,
                blocked=False,
                safety_flags=[],
                citations=[],
                interaction_type="execution_result",
                action_context=None,
                options=[],
            )
        return SimpleNamespace(
            conversation_id="conv-1",
            assistant_message_id="msg-select",
            provider_id="calendar-action",
            provider_name="Calendar Action Engine",
            model_name="calendar-action",
            answer="Selected",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
            blocked=False,
            safety_flags=[],
            citations=[],
            interaction_type="execution_result",
            action_context=None,
            options=[],
        )

    monkeypatch.setattr("app.routers.chat_v2.run_chat_v2", fake_run_chat_v2)

    confirmed = client.post(
        "/api/v2/chat/actions/confirm",
        json={"conversation_id": "conv-1", "confirm": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["assistant_message_id"] == "msg-confirm"

    selected = client.post(
        "/api/v2/chat/actions/select",
        json={"conversation_id": "conv-1", "selection": "1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert selected.status_code == 200
    assert selected.json()["assistant_message_id"] == "msg-select"


def test_chat_v2_complete_knowledge_path_no_recursion(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership_tenant = db_session.query(TenantMembership).first()
    provider = _seed_provider(db_session, tenant_id=membership_tenant.tenant_id)

    def fake_chat(self, **kwargs):  # noqa: ARG001
        return (
            provider,
            {
                "answer": "v2 knowledge answer",
                "prompt_tokens": 3,
                "completion_tokens": 5,
                "total_tokens": 8,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_runtime.hybrid_search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.chat_runtime.LLMRouter.chat", fake_chat)

    response = client.post(
        "/api/v2/chat/complete",
        json={"messages": [{"role": "user", "content": "hello knowledge"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "v2 knowledge answer"
    assert payload["interaction_type"] == "answer"
    assert payload["citations"] == []


def test_chat_v1_complete_knowledge_path_no_recursion(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership_tenant = db_session.query(TenantMembership).first()
    provider = _seed_provider(db_session, tenant_id=membership_tenant.tenant_id)

    def fake_chat(self, **kwargs):  # noqa: ARG001
        return (
            provider,
            {
                "answer": "v1 knowledge answer",
                "prompt_tokens": 2,
                "completion_tokens": 4,
                "total_tokens": 6,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_runtime.hybrid_search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.chat_runtime.LLMRouter.chat", fake_chat)

    response = client.post(
        "/api/v1/chat/complete",
        json={"messages": [{"role": "user", "content": "hello knowledge"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "v1 knowledge answer"
    assert payload["citations"] == []


def test_chat_v2_calendar_intent_persists_without_llm_provider_fk_violation(client, db_session):
    token = _seed_and_login(client, db_session)

    response = client.post(
        "/api/v2/chat/complete",
        json={"messages": [{"role": "user", "content": "how to add a meeting to my calendar?"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] in {"execution_result", "answer"}

    assistant = db_session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == payload["conversation_id"], ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
    ).scalars().first()
    assert assistant is not None
    assert assistant.llm_provider_id is None


def test_chat_v2_email_access_query_routes_to_email_action(client, db_session):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={"messages": [{"role": "user", "content": f"do you have access to my inbox on {user.email}"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] == "execution_result"
    assert payload["provider_name"] == "Email Action Engine"
    assert "Yes, I can access your inbox" in payload["answer"]


def test_chat_v2_summarise_routes_to_email_action_engine(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Digest",
                "from": "Digest <digest@example.com>",
                "sent_at": "2026-02-24T05:00:00+00:00",
                "snippet": "Your weekly digest.",
            }
        ],
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={"messages": [{"role": "user", "content": "summarise my last 1 emails"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] == "execution_result"
    assert payload["provider_name"] == "Email Action Engine"
    assert "sender groups" in payload["answer"]


def test_chat_v2_today_s_emails_routes_to_email_action_engine(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")
    monkeypatch.setattr("app.services.chat_email_actions._parse_email_intent_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Today note",
                "from": "ops@example.com",
                "sent_at": "2026-03-05T10:00:00+11:00",
                "snippet": "today",
            }
        ],
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "today's emails"}],
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-05T18:00:00+11:00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] == "execution_result"
    assert payload["provider_name"] == "Email Action Engine"
    assert "Here are the emails I found:" in payload["answer"]


def test_chat_v2_email_intent_uses_override_provider_without_fallback(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    override_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Override Provider",
        model_name="gemma3:4b",
        is_default=True,
    )
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")
    captured: dict = {}

    def fake_chat(self, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        return (
            override_provider,
            {
                "answer": (
                    '{"intent":"list","account_hint":null,"message_id":null,'
                    '"query":null,"limit":10,"time_scope":"today","days":null,'
                    '"confidence":0.9,"raw_reason":"test"}'
                ),
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_email_actions.LLMRouter.chat", fake_chat)
    monkeypatch.setattr(
        "app.services.chat_email_actions.list_gmail_messages",
        lambda *args, **kwargs: [
            {
                "id": "m-1",
                "subject": "Today note",
                "from": "ops@example.com",
                "sent_at": "2026-03-05T10:00:00+11:00",
                "snippet": "today",
            }
        ],
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "today's emails"}],
            "provider_id_override": override_provider.id,
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-05T18:00:00+11:00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert captured["provider_id_override"] == override_provider.id
    assert captured["allow_fallback"] is False


def test_chat_v2_send_email_natural_phrase_uses_cleaned_draft(client, db_session):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "send email to molaei.kourosh@gmail.com say let's have fun after work tomorrow",
                }
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] == "confirmation_required"
    assert payload["provider_name"] == "Email Action Engine"
    assert "body preview: let's have fun after work tomorrow" in payload["answer"].lower()
    assert "body preview: say let's have fun after work tomorrow" not in payload["answer"].lower()
    assert "Subject: (No subject)" not in payload["answer"]


def test_chat_v2_create_natural_phrase_returns_confirmation_required(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={"messages": [{"role": "user", "content": "create meeting tomorrow 5pm with molaei.kourosh@gmail.com about testing"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] == "confirmation_required"
    assert payload["provider_name"] == "Calendar Action Engine"
    assert "Please confirm creating this meeting" in payload["answer"]


def test_chat_v2_create_uses_client_now_iso_for_relative_dates(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    monkeypatch.setattr(
        "app.services.chat_calendar_actions._parse_calendar_intent_llm",
        lambda *args, **kwargs: ParsedCalendarIntent(
            action_type="calendar_create",
            target_query="renting gpu",
            target_datetime=datetime(2024, 7, 3, 4, 0, tzinfo=UTC),
            summary="renting GPU and local AI Model",
            attendees=["molaei.kourosh@gmail.com"],
        ),
    )

    captured: dict[str, str] = {}

    def fake_create_event(db, connector, *, client_id, client_secret, payload):  # noqa: ARG001
        captured["start_datetime"] = payload["start_datetime"]
        return {
            "id": "evt-v2",
            "calendar_id": payload["calendar_id"],
            "summary": payload["summary"],
            "start_datetime": payload["start_datetime"],
            "end_datetime": payload["end_datetime"],
        }

    monkeypatch.setattr("app.services.chat_calendar_actions.create_event", fake_create_event)

    first = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "create a meeting on life at tomorrow 3pm about renting GPU "
                        "and local AI Model with molaei.kourosh@gmail.com"
                    ),
                }
            ],
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-02T09:30:00+11:00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    assert first.json()["interaction_type"] == "confirmation_required"
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v2/chat/actions/confirm",
        json={
            "conversation_id": conversation_id,
            "confirm": True,
            "client_timezone": "Australia/Sydney",
            "client_now_iso": "2026-03-02T09:30:00+11:00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200

    created_start = datetime.fromisoformat(captured["start_datetime"])
    assert created_start.year == 2026


def test_chat_v2_calendar_parser_respects_provider_override(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None
    user = db_session.query(User).filter(User.id == membership.user_id).one()
    override_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Override Parser",
        model_name="gemma3:4b",
        is_default=True,
    )
    monkeypatch.setattr("app.core.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("app.core.config.settings.google_client_secret", "google-client-secret")
    _seed_google_account(
        db_session,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        email=user.email,
    )

    captured: dict = {}

    def fake_chat(self, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        return (
            SimpleNamespace(id="provider-4b", name="Parser", model_name="gemma3:4b"),
            {
                "answer": (
                    '{"action_type":"calendar_create","target_datetime":"2026-03-04T14:00:00+11:00",'
                    '"summary":"Override Test","attendees":[]}'
                ),
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_calendar_actions.LLMRouter.chat", fake_chat)

    response = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "add meeting tomorrow 2pm about override"}],
            "provider_id_override": override_provider.id,
            "client_timezone": "Australia/Sydney",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction_type"] == "confirmation_required"
    assert captured["provider_id_override"] == override_provider.id
    assert captured["allow_fallback"] is False


def test_unpinned_conversation_pins_to_request_override(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None

    _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Default Provider",
        model_name="gemma3:12b",
        is_default=True,
    )
    override_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Override Provider",
        model_name="gemma3:4b",
        is_default=False,
    )

    captured: list[dict] = []

    def fake_chat(self, **kwargs):  # noqa: ARG001
        captured.append(kwargs)
        return (
            override_provider,
            {
                "answer": "Pinned to override",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_runtime.hybrid_search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.chat_runtime.LLMRouter.chat", fake_chat)

    response = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "hello pin"}],
            "provider_id_override": override_provider.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Pinned to override"
    assert captured[-1]["provider_id_override"] == override_provider.id
    assert captured[-1]["allow_fallback"] is False

    convo = db_session.get(ChatConversation, payload["conversation_id"])
    assert convo is not None
    assert convo.pinned_provider_id == override_provider.id
    assert convo.pinned_model_name == "gemma3:4b"
    assert convo.pinned_provider_name == "Override Provider"


def test_pinned_conversation_ignores_new_override_and_uses_pinned_provider(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None

    default_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Default Provider",
        model_name="gemma3:12b",
        is_default=True,
    )
    override_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Override Provider",
        model_name="gemma3:4b",
        is_default=False,
    )

    captured: list[dict] = []

    def fake_chat(self, **kwargs):  # noqa: ARG001
        captured.append(kwargs)
        provider_id = kwargs.get("provider_id_override")
        provider = override_provider if provider_id == override_provider.id else default_provider
        return (
            provider,
            {
                "answer": "knowledge",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_runtime.hybrid_search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.chat_runtime.LLMRouter.chat", fake_chat)

    first = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "first"}],
            "provider_id_override": override_provider.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    assert captured[-1]["provider_id_override"] == override_provider.id

    second = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "second"}],
            "conversation_id": conversation_id,
            "provider_id_override": default_provider.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    assert captured[-1]["provider_id_override"] == override_provider.id
    assert captured[-1]["allow_fallback"] is False

    convo = db_session.get(ChatConversation, conversation_id)
    assert convo is not None
    assert convo.pinned_provider_id == override_provider.id


def test_pinned_provider_missing_returns_explicit_error_no_fallback(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None

    default_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Default Provider",
        model_name="gemma3:12b",
        is_default=True,
    )
    override_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Override Provider",
        model_name="gemma3:4b",
        is_default=False,
    )
    called = {"count": 0}

    def fake_chat(self, **kwargs):  # noqa: ARG001
        called["count"] += 1
        return (
            default_provider,
            {
                "answer": "knowledge",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        )

    monkeypatch.setattr("app.services.chat_runtime.hybrid_search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.chat_runtime.LLMRouter.chat", fake_chat)

    first = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "pin me"}],
            "provider_id_override": override_provider.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]

    db_session.delete(override_provider)
    db_session.commit()

    second = client.post(
        "/api/v2/chat/complete",
        json={
            "messages": [{"role": "user", "content": "again"}],
            "conversation_id": conversation_id,
            "provider_id_override": default_provider.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 400
    assert "pinned to a provider that is unavailable" in second.json()["detail"]
    assert called["count"] == 1


def test_existing_unpinned_conversation_gets_pinned_on_next_message(client, db_session, monkeypatch):
    token = _seed_and_login(client, db_session)
    membership = db_session.query(TenantMembership).first()
    assert membership is not None

    _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Default Provider",
        model_name="gemma3:12b",
        is_default=True,
    )
    override_provider = _seed_provider(
        db_session,
        tenant_id=membership.tenant_id,
        name="Override Provider",
        model_name="gemma3:4b",
        is_default=False,
    )

    conversation = ChatConversation(
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        title="Legacy Conversation",
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    assert conversation.pinned_provider_id is None

    monkeypatch.setattr("app.services.chat_runtime.hybrid_search_chunks", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.services.chat_runtime.LLMRouter.chat",
        lambda *args, **kwargs: (
            override_provider,
            {
                "answer": "legacy pinned",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "cost_usd": 0.0,
            },
        ),
    )

    response = client.post(
        "/api/v2/chat/complete",
        json={
            "conversation_id": conversation.id,
            "messages": [{"role": "user", "content": "pin this existing conversation"}],
            "provider_id_override": override_provider.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    db_session.refresh(conversation)
    assert conversation.pinned_provider_id == override_provider.id
