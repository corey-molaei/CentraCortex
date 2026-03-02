from types import SimpleNamespace

from app.core.security import get_password_hash
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


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
