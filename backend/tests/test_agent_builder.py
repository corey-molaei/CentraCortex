from app.core.security import get_password_hash
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def seed_tenant(db_session):
    tenant = Tenant(name="Builder Tenant", slug="builder-tenant")
    owner = User(
        email="builder-owner@example.com",
        full_name="Builder Owner",
        hashed_password=get_password_hash("password123"),
    )
    user = User(
        email="builder-user@example.com",
        full_name="Builder User",
        hashed_password=get_password_hash("password123"),
    )

    db_session.add_all([tenant, owner, user])
    db_session.flush()
    db_session.add_all(
        [
            TenantMembership(user_id=owner.id, tenant_id=tenant.id, role="Owner", is_default=True),
            TenantMembership(user_id=user.id, tenant_id=tenant.id, role="User", is_default=True),
        ]
    )
    db_session.commit()
    return tenant, owner, user


def login(client, email: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_builder_generate_deploy_and_rollback(client, db_session):
    _, _, _ = seed_tenant(db_session)
    owner_token = login(client, "builder-owner@example.com")

    created_agent = client.post(
        "/api/v1/agent-builder/agents",
        json={"name": "Finance Builder", "description": "Builder managed finance agent"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created_agent.status_code == 200
    agent_id = created_agent.json()["id"]

    uploaded = client.post(
        f"/api/v1/agent-builder/agents/{agent_id}/examples/upload",
        headers={"Authorization": f"Bearer {owner_token}"},
        files=[("files", ("tone.txt", b"Use concise and formal language with clear action items.", "text/plain"))],
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["uploaded_count"] == 1

    generated_v1 = client.post(
        f"/api/v1/agent-builder/agents/{agent_id}/generate",
        json={
            "prompt": "Summarize Jira updates and highlight critical incidents.",
            "selected_tools": ["search_knowledge", "create_ticket"],
            "selected_data_sources": ["jira", "slack"],
            "risk_level": "high",
            "example_texts": ["Start with highest risk items and include owner names."],
            "generate_tests_count": 6,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert generated_v1.status_code == 200
    v1 = generated_v1.json()
    assert v1["version_number"] == 1
    assert v1["status"] == "draft"
    assert "tools" in v1["spec_json"]
    assert len(v1["generated_tests_json"]) == 6

    spec_v1 = v1["spec_json"]
    spec_v1["goal"] = "Summarize Jira updates, include SLA risk, and recommend next steps."
    updated_v1 = client.patch(
        f"/api/v1/agent-builder/versions/{v1['id']}",
        json={"spec_json": spec_v1},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert updated_v1.status_code == 200

    deployed_v1 = client.post(
        f"/api/v1/agent-builder/versions/{v1['id']}/deploy",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deployed_v1.status_code == 200
    assert deployed_v1.json()["status"] == "deployed"
    assert deployed_v1.json()["version"]["status"] == "deployed"

    generated_v2 = client.post(
        f"/api/v1/agent-builder/agents/{agent_id}/generate",
        json={
            "prompt": "Send executive summaries by email for unresolved incidents.",
            "selected_tools": ["search_knowledge", "send_email"],
            "selected_data_sources": ["jira", "email"],
            "risk_level": "medium",
            "example_texts": ["Keep summaries to 5 bullets and include severity trends."],
            "generate_tests_count": 6,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert generated_v2.status_code == 200
    v2 = generated_v2.json()
    assert v2["version_number"] == 2

    deployed_v2 = client.post(
        f"/api/v1/agent-builder/versions/{v2['id']}/deploy",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deployed_v2.status_code == 200
    assert deployed_v2.json()["version"]["status"] == "deployed"

    rollback = client.post(
        f"/api/v1/agent-builder/agents/{agent_id}/rollback",
        json={"target_version_id": v1["id"], "note": "v2 changed tone too aggressively"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["version"]["id"] == v1["id"]
    assert rollback.json()["version"]["status"] == "deployed"

    versions = client.get(
        f"/api/v1/agent-builder/agents/{agent_id}/versions",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert versions.status_code == 200
    payload = versions.json()
    assert any(item["id"] == v1["id"] and item["status"] == "deployed" for item in payload)
    assert any(item["id"] == v2["id"] and item["status"] in {"rolled_back", "archived"} for item in payload)


def test_builder_strict_spec_validation(client, db_session):
    _, _, _ = seed_tenant(db_session)
    owner_token = login(client, "builder-owner@example.com")

    created_agent = client.post(
        "/api/v1/agent-builder/agents",
        json={"name": "Strict Validator", "description": "validator"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created_agent.status_code == 200
    agent_id = created_agent.json()["id"]

    generated = client.post(
        f"/api/v1/agent-builder/agents/{agent_id}/generate",
        json={
            "prompt": "Generate a strict spec.",
            "selected_tools": ["search_knowledge"],
            "selected_data_sources": ["jira"],
            "risk_level": "low",
            "example_texts": [],
            "generate_tests_count": 6,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert generated.status_code == 200
    version_id = generated.json()["id"]

    invalid_update = client.patch(
        f"/api/v1/agent-builder/versions/{version_id}",
        json={"spec_json": {"name": "incomplete"}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert invalid_update.status_code == 422
