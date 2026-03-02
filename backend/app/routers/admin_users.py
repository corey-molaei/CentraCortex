from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.config import settings
from app.core.security import random_token
from app.models.group import Group
from app.models.group_membership import GroupMembership
from app.models.invitation import Invitation
from app.models.role import Role
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.models.user_role_assignment import UserRoleAssignment
from app.schemas.rbac import (
    AssignGroupRequest,
    AssignRoleRequest,
    GroupRead,
    InviteUserRequest,
    InviteUserResponse,
    RoleRead,
    UserDetail,
    UserListItem,
)
from app.services.audit import audit_event

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=list[UserListItem])
def list_users(
    q: str | None = Query(default=None, description="Search by email or name"),
    role: str | None = Query(default=None),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[UserListItem]:
    stmt = (
        select(User, TenantMembership)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(TenantMembership.tenant_id == admin.tenant_id)
    )

    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.email.ilike(like)) | (User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(TenantMembership.role.ilike(role))

    rows = db.execute(stmt).all()
    return [
        UserListItem(id=user.id, email=user.email, full_name=user.full_name, role=membership.role)
        for user, membership in rows
    ]


@router.post("/invite", response_model=InviteUserResponse)
def invite_user(
    payload: InviteUserRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> InviteUserResponse:
    invite_token = random_token(16)
    invite = Invitation(
        tenant_id=admin.tenant_id,
        invited_by_user_id=admin.user_id,
        email=payload.email,
        role=payload.role,
        status="pending",
        invite_token=invite_token,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.user.invite",
        resource_type="invitation",
        resource_id=invite.id,
        action="invite",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
        payload={"email": payload.email, "role": payload.role},
    )

    return InviteUserResponse(invitation_id=invite.id, invite_token=invite.invite_token, status=invite.status)


@router.get("/{user_id}", response_model=UserDetail)
def get_user_detail(
    user_id: str,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> UserDetail:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    membership = db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == admin.tenant_id, TenantMembership.user_id == user_id)
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in tenant")

    groups = db.execute(
        select(Group)
        .join(GroupMembership, GroupMembership.group_id == Group.id)
        .where(Group.tenant_id == admin.tenant_id, GroupMembership.user_id == user_id)
    ).scalars().all()

    roles = db.execute(
        select(Role)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
        .where(UserRoleAssignment.tenant_id == admin.tenant_id, UserRoleAssignment.user_id == user_id)
    ).scalars().all()

    return UserDetail(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        groups=[
            GroupRead(
                id=g.id,
                tenant_id=g.tenant_id,
                name=g.name,
                description=g.description,
                created_at=g.created_at,
            )
            for g in groups
        ],
        custom_roles=[
            RoleRead(
                id=r.id,
                tenant_id=r.tenant_id,
                name=r.name,
                description=r.description,
                is_system=r.is_system,
                created_at=r.created_at,
            )
            for r in roles
        ],
    )


@router.post("/{user_id}/groups")
def assign_group_to_user(
    user_id: str,
    payload: AssignGroupRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    group = db.execute(select(Group).where(Group.id == payload.group_id, Group.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    exists = db.execute(
        select(GroupMembership).where(GroupMembership.group_id == group.id, GroupMembership.user_id == user_id)
    ).scalar_one_or_none()
    if not exists:
        db.add(GroupMembership(group_id=group.id, user_id=user_id))
        db.commit()

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.user.group_assign",
        resource_type="group_membership",
        resource_id=f"{group.id}:{user_id}",
        action="assign",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Group assigned"}


@router.post("/{user_id}/roles")
def assign_role_to_user(
    user_id: str,
    payload: AssignRoleRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    role = db.execute(
        select(Role).where(Role.id == payload.role_id, (Role.tenant_id == admin.tenant_id) | (Role.tenant_id.is_(None)))
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    assignment = db.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.tenant_id == admin.tenant_id,
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role_id == role.id,
        )
    ).scalar_one_or_none()
    if not assignment:
        db.add(UserRoleAssignment(tenant_id=admin.tenant_id, user_id=user_id, role_id=role.id))
        db.commit()

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="rbac.user.role_assign",
        resource_type="user_role_assignment",
        resource_id=f"{role.id}:{user_id}",
        action="assign",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Role assigned"}
