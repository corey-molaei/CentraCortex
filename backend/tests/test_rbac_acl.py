from app.core.security import get_password_hash
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def seed_rbac(db_session):
    tenant = Tenant(name="Core Tenant", slug="core")

    admin = User(
        email="owner@example.com",
        full_name="Owner User",
        hashed_password=get_password_hash("password123"),
    )
    analyst = User(
        email="analyst@example.com",
        full_name="Analyst User",
        hashed_password=get_password_hash("password123"),
    )

    db_session.add_all([tenant, admin, analyst])
    db_session.flush()

    db_session.add_all(
        [
            TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="Owner", is_default=True),
            TenantMembership(user_id=analyst.id, tenant_id=tenant.id, role="User", is_default=True),
        ]
    )
    db_session.commit()

    return tenant, admin, analyst


def login(client, email: str):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_admin_crud_and_assignments(client, db_session):
    _, _, analyst = seed_rbac(db_session)
    admin_token = login(client, "owner@example.com")

    role = client.post(
        "/api/v1/admin/roles",
        json={"name": "Analyst", "description": "Can review documents"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert role.status_code == 200
    role_id = role.json()["id"]

    group = client.post(
        "/api/v1/admin/groups",
        json={"name": "Finance", "description": "Finance group"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert group.status_code == 200
    group_id = group.json()["id"]

    assign_group = client.post(
        f"/api/v1/admin/users/{analyst.id}/groups",
        json={"group_id": group_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert assign_group.status_code == 200

    assign_role = client.post(
        f"/api/v1/admin/users/{analyst.id}/roles",
        json={"role_id": role_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert assign_role.status_code == 200

    detail = client.get(
        f"/api/v1/admin/users/{analyst.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail.status_code == 200
    assert len(detail.json()["groups"]) == 1
    assert len(detail.json()["custom_roles"]) == 1


def test_acl_enforcement_for_retrieval_and_tool_execution(client, db_session):
    _, _, _ = seed_rbac(db_session)
    admin_token = login(client, "owner@example.com")
    user_token = login(client, "analyst@example.com")

    group = client.post(
        "/api/v1/admin/groups",
        json={"name": "Legal", "description": "Legal group"},
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()

    analyst_users = client.get(
        "/api/v1/admin/users?q=analyst@example.com",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    analyst_id = analyst_users[0]["id"]

    client.post(
        f"/api/v1/admin/users/{analyst_id}/groups",
        json={"group_id": group["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    doc_policy = client.post(
        "/api/v1/admin/policies",
        json={
            "name": "Legal Docs",
            "policy_type": "document",
            "resource_id": "*",
            "allowed_group_ids": [group["id"]],
            "allowed_user_ids": [],
            "allowed_role_names": []
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert doc_policy.status_code == 200

    create_doc = client.post(
        "/api/v1/retrieval/documents",
        json={
            "source_type": "manual",
            "source_id": "doc-1",
            "title": "Contract Notes",
            "raw_text": "Confidential legal notes"
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_doc.status_code == 200

    docs_visible_to_user = client.get(
        "/api/v1/retrieval/documents",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert docs_visible_to_user.status_code == 200
    assert len(docs_visible_to_user.json()) == 1

    tool_policy = client.post(
        "/api/v1/admin/policies",
        json={
            "name": "Owner Tool Access",
            "policy_type": "tool",
            "resource_id": "send_email",
            "allowed_role_names": ["Owner"],
            "allowed_user_ids": [],
            "allowed_group_ids": []
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert tool_policy.status_code == 200

    denied = client.post(
        "/api/v1/tools/send_email/execute",
        json={"payload": {"to": "a@example.com"}},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/api/v1/tools/send_email/execute",
        json={"payload": {"to": "a@example.com"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "executed"
