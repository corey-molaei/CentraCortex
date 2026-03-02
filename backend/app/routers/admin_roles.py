from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.config import settings
from app.models.role import Role
from app.models.tenant_membership import TenantMembership
from app.schemas.rbac import RoleCreate, RoleRead
from app.services.audit import audit_event

router = APIRouter(prefix="/admin/roles", tags=["admin-roles"])


@router.get("", response_model=list[RoleRead])
def list_roles(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)) -> list[RoleRead]:
    roles = db.execute(
        select(Role).where(or_(Role.tenant_id == admin.tenant_id, Role.tenant_id.is_(None))).order_by(Role.name)
    ).scalars().all()
    return [
        RoleRead(
            id=r.id,
            tenant_id=r.tenant_id,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            created_at=r.created_at,
        )
        for r in roles
    ]


@router.post("", response_model=RoleRead)
def create_role(
    payload: RoleCreate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> RoleRead:
    exists = db.execute(
        select(Role).where(Role.tenant_id == admin.tenant_id, Role.name.ilike(payload.name))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role already exists")

    role = Role(tenant_id=admin.tenant_id, name=payload.name, description=payload.description, is_system=False)
    db.add(role)
    db.commit()
    db.refresh(role)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.role.create",
        resource_type="role",
        resource_id=role.id,
        action="create",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
        payload={"name": role.name},
    )

    return RoleRead(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        created_at=role.created_at,
    )
