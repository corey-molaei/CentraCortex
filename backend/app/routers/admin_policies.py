from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.config import settings
from app.models.acl_policy import ACLPolicy
from app.models.tenant_membership import TenantMembership
from app.schemas.rbac import PolicyCreate, PolicyRead, PolicyUpdate
from app.services.audit import audit_event

router = APIRouter(prefix="/admin/policies", tags=["admin-policies"])


@router.get("", response_model=list[PolicyRead])
def list_policies(
    policy_type: str | None = None,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[PolicyRead]:
    stmt = select(ACLPolicy).where(ACLPolicy.tenant_id == admin.tenant_id)
    if policy_type:
        stmt = stmt.where(ACLPolicy.policy_type == policy_type)
    rows = db.execute(stmt.order_by(ACLPolicy.created_at.desc())).scalars().all()
    return [
        PolicyRead(
            id=p.id,
            tenant_id=p.tenant_id,
            name=p.name,
            policy_type=p.policy_type,
            resource_id=p.resource_id,
            allow_all=p.allow_all,
            allowed_user_ids=p.allowed_user_ids or [],
            allowed_group_ids=p.allowed_group_ids or [],
            allowed_role_names=p.allowed_role_names or [],
            active=p.active,
            created_at=p.created_at,
        )
        for p in rows
    ]


@router.post("", response_model=PolicyRead)
def create_policy(
    payload: PolicyCreate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> PolicyRead:
    policy = ACLPolicy(
        tenant_id=admin.tenant_id,
        name=payload.name,
        policy_type=payload.policy_type,
        resource_id=payload.resource_id,
        allow_all=payload.allow_all,
        allowed_user_ids=payload.allowed_user_ids,
        allowed_group_ids=payload.allowed_group_ids,
        allowed_role_names=payload.allowed_role_names,
        active=payload.active,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.policy.create",
        resource_type="acl_policy",
        resource_id=policy.id,
        action="create",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
        payload={"policy_type": policy.policy_type, "resource_id": policy.resource_id},
    )

    return PolicyRead(
        id=policy.id,
        tenant_id=policy.tenant_id,
        name=policy.name,
        policy_type=policy.policy_type,
        resource_id=policy.resource_id,
        allow_all=policy.allow_all,
        allowed_user_ids=policy.allowed_user_ids or [],
        allowed_group_ids=policy.allowed_group_ids or [],
        allowed_role_names=policy.allowed_role_names or [],
        active=policy.active,
        created_at=policy.created_at,
    )


@router.patch("/{policy_id}", response_model=PolicyRead)
def update_policy(
    policy_id: str,
    payload: PolicyUpdate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> PolicyRead:
    policy = db.execute(
        select(ACLPolicy).where(ACLPolicy.id == policy_id, ACLPolicy.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(policy, key, value)

    db.commit()
    db.refresh(policy)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.policy.update",
        resource_type="acl_policy",
        resource_id=policy.id,
        action="update",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return PolicyRead(
        id=policy.id,
        tenant_id=policy.tenant_id,
        name=policy.name,
        policy_type=policy.policy_type,
        resource_id=policy.resource_id,
        allow_all=policy.allow_all,
        allowed_user_ids=policy.allowed_user_ids or [],
        allowed_group_ids=policy.allowed_group_ids or [],
        allowed_role_names=policy.allowed_role_names or [],
        active=policy.active,
        created_at=policy.created_at,
    )


@router.delete("/{policy_id}")
def delete_policy(
    policy_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    policy = db.execute(
        select(ACLPolicy).where(ACLPolicy.id == policy_id, ACLPolicy.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")

    db.delete(policy)
    db.commit()

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.policy.delete",
        resource_type="acl_policy",
        resource_id=policy_id,
        action="delete",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Policy deleted"}
