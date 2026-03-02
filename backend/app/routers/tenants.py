from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_current_user, get_db
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.schemas.tenant import TenantRead

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/mine", response_model=list[TenantRead])
def list_my_tenants(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TenantRead]:
    stmt = (
        select(Tenant)
        .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
        .where(TenantMembership.user_id == current_user.id)
    )
    tenants = db.execute(stmt).scalars().all()
    return [
        TenantRead(
            id=t.id,
            name=t.name,
            slug=t.slug,
            is_active=t.is_active,
            created_at=t.created_at,
        )
        for t in tenants
    ]


@router.get("/current", response_model=TenantRead)
def get_current_tenant(
    membership: TenantMembership = Depends(get_current_tenant_membership), db: Session = Depends(get_db)
) -> TenantRead:
    tenant = db.get(Tenant, membership.tenant_id)
    return TenantRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
    )
