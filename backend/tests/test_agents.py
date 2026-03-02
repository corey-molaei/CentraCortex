from app.core.security import get_password_hash
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def seed_tenant(db_session):
    tenant = Tenant(name="Agents Tenant", slug="agents-tenant")
    owner = User(
        email="agent-owner@example.com",
        full_name="Agent Owner",
        hashed_password=get_password_hash("password123"),
    )
    analyst = User(
        email="agent-user@example.com",
        full_name="Agent User",
        hashed_password=get_password_hash("password123"),
    )

    db_session.add_all([tenant, owner, analyst])
    db_session.flush()
    db_session.add_all(
        [
            TenantMembership(user_id=owner.id, tenant_id=tenant.id, role="Owner", is_default=True),
            TenantMembership(user_id=analyst.id, tenant_id=tenant.id, role="User", is_default=True),
        ]
    )
    db_session.commit()
    return tenant, owner, analyst


def login(client, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def create_tool_policy(client, token: str, tool_name: str, allowed_roles: list[str]):
    response = client.post(
        "/api/v1/admin/policies",
        json={
            "name": f"{tool_name}-policy",
            "policy_type": "tool",
            "resource_id": tool_name,
            "allowed_role_names": allowed_roles,
            "allowed_user_ids": [],
            "allowed_group_ids": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_agent_catalog_and_knowledge_run(client, db_session):
    _, _, _ = seed_tenant(db_session)
    owner_token = login(client, "agent-owner@example.com")

    create_tool_policy(client, owner_token, "search_knowledge", ["Owner"])

    doc = client.post(
        "/api/v1/retrieval/documents",
        json={
            "source_type": "manual",
            "source_id": "agent-doc-1",
            "title": "Database Failover Guide",
            "raw_text": "Failover process: promote replica, verify writes, update routing.",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert doc.status_code == 200
    doc_id = doc.json()["id"]

    reindex = client.post(f"/api/v1/documents/{doc_id}/reindex", headers={"Authorization": f"Bearer {owner_token}"})
    assert reindex.status_code == 200

    created = client.post(
        "/api/v1/agents/catalog",
        json={
            "name": "Knowledge Agent",
            "description": "Knowledge retrieval with ACL",
            "system_prompt": "Use retrieval and return concise answers.",
            "default_agent_type": "knowledge",
            "allowed_tools": ["search_knowledge"],
            "enabled": True,
            "config_json": {"require_approval_for_risky_tools": True},
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]

    run = client.post(
        "/api/v1/agents/runs",
        json={
            "agent_id": agent_id,
            "input_text": "Find failover steps from docs",
            "tool_inputs": {"search_knowledge": {"query": "failover steps", "limit": 5}},
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["status"] == "completed"
    run_id = run_payload["id"]

    detail = client.get(f"/api/v1/agents/runs/{run_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert len(detail_payload["traces"]) >= 2
    assert any(step["step_type"] == "route" for step in detail_payload["traces"])
    assert any(step["step_type"] == "tool_result" for step in detail_payload["traces"])


def test_agent_risky_tool_approval_flow(client, db_session):
    _, _, _ = seed_tenant(db_session)
    owner_token = login(client, "agent-owner@example.com")
    user_token = login(client, "agent-user@example.com")

    create_tool_policy(client, owner_token, "send_email", ["Owner"])

    created = client.post(
        "/api/v1/agents/catalog",
        json={
            "name": "Comms Agent",
            "description": "Comms execution",
            "system_prompt": "Route comms actions to approved tools.",
            "default_agent_type": "comms",
            "allowed_tools": ["send_email"],
            "enabled": True,
            "config_json": {"require_approval_for_risky_tools": True},
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]

    run = client.post(
        "/api/v1/agents/runs",
        json={
            "agent_id": agent_id,
            "input_text": "Send an email update to finance",
            "tool_inputs": {
                "send_email": {
                    "to": "finance@example.com",
                    "subject": "Ops update",
                    "body": "Pipeline complete",
                }
            },
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "waiting_approval"
    run_id = run.json()["id"]

    detail = client.get(f"/api/v1/agents/runs/{run_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert detail.status_code == 200
    approvals = detail.json()["approvals"]
    assert len(approvals) == 1
    approval_id = approvals[0]["id"]
    assert approvals[0]["status"] == "pending"

    denied = client.post(
        f"/api/v1/agents/approvals/{approval_id}/approve",
        json={"note": "approve"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert denied.status_code == 403

    approved = client.post(
        f"/api/v1/agents/approvals/{approval_id}/approve",
        json={"note": "approved by owner"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    detail_after = client.get(f"/api/v1/agents/runs/{run_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert detail_after.status_code == 200
    assert detail_after.json()["run"]["status"] == "completed"
    assert any(step["step_type"] == "approval" for step in detail_after.json()["traces"])


def test_agent_tool_acl_denies_non_admin_user(client, db_session):
    _, _, _ = seed_tenant(db_session)
    owner_token = login(client, "agent-owner@example.com")
    user_token = login(client, "agent-user@example.com")

    create_tool_policy(client, owner_token, "send_email", ["Owner"])

    created = client.post(
        "/api/v1/agents/catalog",
        json={
            "name": "Restricted Comms",
            "description": "Comms for owner only",
            "system_prompt": "Use send_email with approvals.",
            "default_agent_type": "comms",
            "allowed_tools": ["send_email"],
            "enabled": True,
            "config_json": {"require_approval_for_risky_tools": True},
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 200

    run = client.post(
        "/api/v1/agents/runs",
        json={
            "agent_id": created.json()["id"],
            "input_text": "Send email to legal",
            "tool_inputs": {
                "send_email": {
                    "to": "legal@example.com",
                    "subject": "Notice",
                    "body": "Please review",
                }
            },
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "failed"
    assert "ACL" in (run.json()["error_message"] or "")
