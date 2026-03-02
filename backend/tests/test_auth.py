from sqlalchemy import select

from app.core.security import get_password_hash, verify_password
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def seed_user(db_session):
    tenant_a = Tenant(name="Tenant A", slug="tenant-a")
    tenant_b = Tenant(name="Tenant B", slug="tenant-b")
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password=get_password_hash("password123"),
    )
    db_session.add_all([tenant_a, tenant_b, user])
    db_session.flush()

    db_session.add_all(
        [
            TenantMembership(user_id=user.id, tenant_id=tenant_a.id, role="Owner", is_default=True),
            TenantMembership(user_id=user.id, tenant_id=tenant_b.id, role="Admin", is_default=False),
        ]
    )
    db_session.commit()
    return user, tenant_a, tenant_b


def test_login_me_and_switch_tenant(client, db_session):
    _, tenant_a, tenant_b = seed_user(db_session)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    login_payload = login.json()
    assert login_payload["access_token"]
    assert login_payload["refresh_token"]
    assert len(login_payload["memberships"]) == 2

    access = login_payload["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"

    current_tenant = client.get("/api/v1/tenants/current", headers={"Authorization": f"Bearer {access}"})
    assert current_tenant.status_code == 200
    assert current_tenant.json()["id"] == tenant_a.id

    switch = client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": tenant_b.id},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert switch.status_code == 200
    switched_access = switch.json()["access_token"]

    current_tenant_after = client.get(
        "/api/v1/tenants/current",
        headers={"Authorization": f"Bearer {switched_access}"},
    )
    assert current_tenant_after.status_code == 200
    assert current_tenant_after.json()["id"] == tenant_b.id


def test_refresh_and_password_reset(client, db_session):
    user, _, _ = seed_user(db_session)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    ).json()

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    reset_request = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "admin@example.com"},
    )
    assert reset_request.status_code == 200
    token = reset_request.json()["token"]
    assert token

    reset_confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "newpass123"},
    )
    assert reset_confirm.status_code == 200

    updated_user = db_session.execute(select(User).where(User.id == user.id)).scalar_one()
    assert not verify_password("password123", updated_user.hashed_password)
    assert verify_password("newpass123", updated_user.hashed_password)
