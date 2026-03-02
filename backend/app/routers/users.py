from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_current_user, get_db
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.schemas.user import UserProfileUpdate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
def read_me(
    current_user: User = Depends(get_current_user),
    _: TenantMembership = Depends(get_current_tenant_membership),
) -> UserRead:
    return UserRead(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    _: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> UserRead:
    current_user.full_name = payload.full_name
    db.commit()
    db.refresh(current_user)
    return UserRead(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
