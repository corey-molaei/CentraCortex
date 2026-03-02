import hashlib
import hmac
import json
import time

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def seed_tenant(db_session):
    tenant = Tenant(name="Governance Tenant", slug="governance-tenant")
    owner = User(
        email="governance-owner@example.com",
        full_name="Governance Owner",
        hashed_password=get_password_hash("password123"),
    )

    db_session.add_all([tenant, owner])
    db_session.flush()
    db_session.add(TenantMembership(user_id=owner.id, tenant_id=tenant.id, role="Owner", is_default=True))
    db_session.commit()
    return tenant, owner


def login(client, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def create_send_email_policy(client, token: str):
    response = client.post(
        "/api/v1/admin/policies",
        json={
            "name": "send-email-owner-only",
            "policy_type": "tool",
            "resource_id": "send_email",
            "allowed_role_names": ["Owner"],
            "allowed_user_ids": [],
            "allowed_group_ids": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_governance_audit_filters_export_and_approval_queue(client, db_session):
    _, _ = seed_tenant(db_session)
    token = login(client, "governance-owner@example.com")

    role_create = client.post(
        "/api/v1/admin/roles",
        json={"name": "Compliance", "description": "Compliance role"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert role_create.status_code == 200

    logs = client.get(
        "/api/v1/governance/audit-logs?event_type=rbac.role.create",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logs.status_code == 200
    logs_payload = logs.json()
    assert len(logs_payload) >= 1
    assert any(item["event_type"] == "rbac.role.create" for item in logs_payload)

    export_csv = client.get(
        "/api/v1/governance/audit-logs/export?event_type=rbac.role.create",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert export_csv.status_code == 200
    assert "text/csv" in export_csv.headers.get("content-type", "")
    assert "event_type" in export_csv.text
    assert "rbac.role.create" in export_csv.text

    create_send_email_policy(client, token)

    agent = client.post(
        "/api/v1/agents/catalog",
        json={
            "name": "Governance Comms",
            "description": "Comms agent",
            "system_prompt": "Route comms through email with approval.",
            "default_agent_type": "comms",
            "allowed_tools": ["send_email"],
            "enabled": True,
            "config_json": {"require_approval_for_risky_tools": True},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 200
    agent_id = agent.json()["id"]

    run = client.post(
        "/api/v1/agents/runs",
        json={
            "agent_id": agent_id,
            "input_text": "Send weekly email status",
            "tool_inputs": {
                "send_email": {
                    "to": "team@example.com",
                    "subject": "Weekly status",
                    "body": "All systems nominal"
                }
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "waiting_approval"
    run_id = run.json()["id"]

    queue = client.get("/api/v1/governance/approval-queue", headers={"Authorization": f"Bearer {token}"})
    assert queue.status_code == 200
    queue_payload = queue.json()
    assert len(queue_payload) >= 1
    approval = queue_payload[0]

    approved = client.post(
        f"/api/v1/governance/approval-queue/{approval['id']}/approve",
        json={"note": "governance approved"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    run_detail = client.get(f"/api/v1/agents/runs/{run_id}", headers={"Authorization": f"Bearer {token}"})
    assert run_detail.status_code == 200
    assert run_detail.json()["run"]["status"] == "completed"


def test_rate_limit_and_request_signing_enforcement(client, db_session, monkeypatch):
    _, _ = seed_tenant(db_session)
    token = login(client, "governance-owner@example.com")

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)

    r1 = client.get("/api/v1/tenants/current", headers={"Authorization": f"Bearer {token}"})
    r2 = client.get("/api/v1/tenants/current", headers={"Authorization": f"Bearer {token}"})
    r3 = client.get("/api/v1/tenants/current", headers={"Authorization": f"Bearer {token}"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429

    monkeypatch.setattr(settings, "rate_limit_per_minute", 240)
    monkeypatch.setattr(settings, "request_signing_enabled", True)
    monkeypatch.setattr(settings, "request_signing_secret", "module-9-signing-secret")
    monkeypatch.setattr(settings, "request_signing_max_age_seconds", 300)

    unsigned = client.post(
        "/api/v1/admin/roles",
        json={"name": "SignedOnly", "description": "requires signature"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unsigned.status_code == 401

    timestamp = str(int(time.time()))
    payload = {"name": "SignedRole", "description": "signed request"}
    raw = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        settings.request_signing_secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw,
        hashlib.sha256,
    ).hexdigest()

    signed = client.post(
        "/api/v1/admin/roles",
        content=raw,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Signature-Timestamp": timestamp,
        },
    )
    assert signed.status_code == 200
    assert signed.json()["name"] == "SignedRole"
