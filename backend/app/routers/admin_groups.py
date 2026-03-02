from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.config import settings
from app.models.group import Group
from app.models.group_membership import GroupMembership
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.schemas.rbac import GroupCreate, GroupRead, GroupUpdate, UserListItem
from app.services.audit import audit_event

router = APIRouter(prefix="/admin/groups", tags=["admin-groups"])


@router.get("", response_model=list[GroupRead])
def list_groups(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)) -> list[GroupRead]:
    groups = db.execute(select(Group).where(Group.tenant_id == admin.tenant_id).order_by(Group.name)).scalars().all()
    return [
        GroupRead(
            id=g.id,
            tenant_id=g.tenant_id,
            name=g.name,
            description=g.description,
            created_at=g.created_at,
        )
        for g in groups
    ]


@router.post("", response_model=GroupRead)
def create_group(
    payload: GroupCreate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> GroupRead:
    exists = db.execute(
        select(Group).where(Group.tenant_id == admin.tenant_id, Group.name.ilike(payload.name))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group already exists")

    group = Group(tenant_id=admin.tenant_id, name=payload.name, description=payload.description)
    db.add(group)
    db.commit()
    db.refresh(group)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.group.create",
        resource_type="group",
        resource_id=group.id,
        action="create",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return GroupRead(
        id=group.id,
        tenant_id=group.tenant_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
    )


@router.get("/{group_id}", response_model=GroupRead)
def get_group(group_id: str, admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)) -> GroupRead:
    group = db.execute(select(Group).where(Group.id == group_id, Group.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    return GroupRead(
        id=group.id,
        tenant_id=group.tenant_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
    )


@router.patch("/{group_id}", response_model=GroupRead)
def update_group(
    group_id: str,
    payload: GroupUpdate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> GroupRead:
    group = db.execute(select(Group).where(Group.id == group_id, Group.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description

    db.commit()
    db.refresh(group)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.group.update",
        resource_type="group",
        resource_id=group.id,
        action="update",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return GroupRead(
        id=group.id,
        tenant_id=group.tenant_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
    )


@router.delete("/{group_id}")
def delete_group(
    group_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    group = db.execute(select(Group).where(Group.id == group_id, Group.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    db.delete(group)
    db.commit()

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.group.delete",
        resource_type="group",
        resource_id=group_id,
        action="delete",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Group deleted"}


@router.get("/{group_id}/members", response_model=list[UserListItem])
def list_group_members(
    group_id: str,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[UserListItem]:
    group = db.execute(select(Group).where(Group.id == group_id, Group.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    rows = db.execute(
        select(User, GroupMembership)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group.id)
    ).all()

    return [UserListItem(id=u.id, email=u.email, full_name=u.full_name, role="member") for u, _ in rows]
