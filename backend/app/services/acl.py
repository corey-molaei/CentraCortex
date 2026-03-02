from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.acl_policy import ACLPolicy
from app.models.document import Document
from app.models.group import Group
from app.models.group_membership import GroupMembership
from app.models.role import Role
from app.models.tenant_membership import TenantMembership
from app.models.user_role_assignment import UserRoleAssignment


def get_user_role_names(db: Session, tenant_id: str, user_id: str) -> set[str]:
    names: set[str] = set()

    membership = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if membership:
        names.add(membership.role)

    stmt = (
        select(Role.name)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
        .where(
            UserRoleAssignment.tenant_id == tenant_id,
            UserRoleAssignment.user_id == user_id,
        )
    )
    names.update(db.execute(stmt).scalars().all())
    return {name.lower() for name in names}


def get_user_group_ids(db: Session, tenant_id: str, user_id: str) -> set[str]:
    stmt = (
        select(GroupMembership.group_id)
        .join(Group, Group.id == GroupMembership.group_id)
        .where(
            Group.tenant_id == tenant_id,
            GroupMembership.user_id == user_id,
        )
    )
    return set(db.execute(stmt).scalars().all())


def is_allowed_for_resource(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    policy_type: str,
    resource_id: str,
    allow_wildcard: bool = True,
    default_allow_if_no_policy: bool = False,
) -> bool:
    role_names = get_user_role_names(db, tenant_id, user_id)
    group_ids = get_user_group_ids(db, tenant_id, user_id)

    resource_filter = ACLPolicy.resource_id == resource_id
    if allow_wildcard:
        resource_filter = or_(ACLPolicy.resource_id == resource_id, ACLPolicy.resource_id == "*")

    policies = db.execute(
        select(ACLPolicy).where(
            ACLPolicy.tenant_id == tenant_id,
            ACLPolicy.policy_type == policy_type,
            ACLPolicy.active.is_(True),
            resource_filter,
        )
    ).scalars().all()

    if not policies:
        return default_allow_if_no_policy

    for policy in policies:
        if _is_policy_allowed(policy, user_id=user_id, group_ids=group_ids, role_names=role_names):
            return True

    return False


def _is_policy_allowed(policy: ACLPolicy, *, user_id: str, group_ids: set[str], role_names: set[str]) -> bool:
    if policy.allow_all:
        return True

    allowed_users = set(policy.allowed_user_ids or [])
    allowed_groups = set(policy.allowed_group_ids or [])
    allowed_roles = {r.lower() for r in (policy.allowed_role_names or [])}

    if user_id in allowed_users:
        return True
    if group_ids.intersection(allowed_groups):
        return True
    if role_names.intersection(allowed_roles):
        return True
    return False


def _has_default_document_policy(db: Session, tenant_id: str) -> bool:
    count = db.execute(
        select(func.count(ACLPolicy.id)).where(
            ACLPolicy.tenant_id == tenant_id,
            ACLPolicy.policy_type == "document",
            ACLPolicy.resource_id == "*",
            ACLPolicy.active.is_(True),
        )
    ).scalar_one()
    return int(count) > 0


def can_access_document(db: Session, *, tenant_id: str, user_id: str, document: Document) -> bool:
    if document.acl_policy_id:
        policy = db.get(ACLPolicy, document.acl_policy_id)
        if not policy:
            return False
        if policy.tenant_id != tenant_id or policy.policy_type != "document" or not policy.active:
            return False
        role_names = get_user_role_names(db, tenant_id, user_id)
        group_ids = get_user_group_ids(db, tenant_id, user_id)
        return _is_policy_allowed(policy, user_id=user_id, group_ids=group_ids, role_names=role_names)

    if not _has_default_document_policy(db, tenant_id):
        return True

    return is_allowed_for_resource(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        policy_type="document",
        resource_id="*",
        allow_wildcard=True,
        default_allow_if_no_policy=False,
    )


def get_accessible_documents(db: Session, tenant_id: str, user_id: str) -> list[Document]:
    docs = db.execute(select(Document).where(Document.tenant_id == tenant_id, Document.deleted_at.is_(None))).scalars().all()

    allowed: list[Document] = []
    for doc in docs:
        if can_access_document(db, tenant_id=tenant_id, user_id=user_id, document=doc):
            allowed.append(doc)

    return allowed
