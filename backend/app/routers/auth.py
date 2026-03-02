import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    hash_token,
    random_token,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.schemas.auth import (
    AccessTokenOnly,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshRequest,
    SessionInfo,
    SwitchTenantRequest,
    TenantMembershipSummary,
    TokenResponse,
)
from app.services.audit import audit_event

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_expired(value: datetime) -> bool:
    candidate = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return candidate < datetime.now(timezone.utc)


def _list_memberships(db: Session, user_id: str) -> list[TenantMembershipSummary]:
    stmt = (
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == user_id, Tenant.is_active.is_(True))
    )
    rows = db.execute(stmt).all()
    return [
        TenantMembershipSummary(tenant_id=membership.tenant_id, tenant_name=tenant.name, role=membership.role)
        for membership, tenant in rows
    ]


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    memberships = _list_memberships(db, user.id)
    tenant_id = memberships[0].tenant_id if memberships else None

    jti = secrets.token_hex(24)
    refresh_token = create_refresh_token(user.id, jti=jti)
    access_token = create_access_token(user.id, tenant_id=tenant_id)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_jti=jti,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    db.commit()

    audit_event(
        db,
        event_type="auth.login",
        resource_type="user",
        resource_id=user.id,
        action="login",
        user_id=user.id,
        tenant_id=tenant_id,
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        memberships=memberships,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    token_payload = decode_token(payload.refresh_token)
    if token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = token_payload.get("sub")
    jti = token_payload.get("jti")
    if not user_id or not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed refresh token")

    refresh_record = db.execute(
        select(RefreshToken).where(
            and_(
                RefreshToken.token_jti == jti,
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if not refresh_record or _is_expired(refresh_record.expires_at):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired or revoked token")

    memberships = _list_memberships(db, user_id)
    tenant_id = memberships[0].tenant_id if memberships else None
    access_token = create_access_token(user_id, tenant_id=tenant_id)

    audit_event(
        db,
        event_type="auth.refresh",
        resource_type="user",
        resource_id=user_id,
        action="refresh",
        user_id=user_id,
        tenant_id=tenant_id,
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=payload.refresh_token,
        tenant_id=tenant_id,
        memberships=memberships,
    )


@router.post("/switch-tenant", response_model=AccessTokenOnly)
def switch_tenant(
    payload: SwitchTenantRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessTokenOnly:
    membership = db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == current_user.id,
            TenantMembership.tenant_id == payload.tenant_id,
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not assigned")

    access_token = create_access_token(current_user.id, tenant_id=payload.tenant_id)

    audit_event(
        db,
        event_type="auth.switch_tenant",
        resource_type="tenant_membership",
        resource_id=membership.id,
        action="switch_tenant",
        user_id=current_user.id,
        tenant_id=payload.tenant_id,
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return AccessTokenOnly(access_token=access_token, tenant_id=payload.tenant_id)


@router.get("/me", response_model=SessionInfo)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SessionInfo:
    memberships = _list_memberships(db, current_user.id)
    tenant_id = memberships[0].tenant_id if memberships else None
    return SessionInfo(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        tenant_id=tenant_id,
        memberships=memberships,
        issued_at=datetime.now(timezone.utc),
    )


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetRequestResponse:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user:
        return PasswordResetRequestResponse(message="If the account exists, reset instructions were sent")

    raw_token = random_token()
    token_hash = hash_token(raw_token)

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_token_expire_minutes),
        )
    )
    db.commit()

    audit_event(
        db,
        event_type="auth.password_reset_request",
        resource_type="user",
        resource_id=user.id,
        action="password_reset_request",
        user_id=user.id,
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    if settings.app_env == "development":
        return PasswordResetRequestResponse(
            message="Password reset token generated (development only)",
            token=raw_token,
        )
    return PasswordResetRequestResponse(message="If the account exists, reset instructions were sent")


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    token_hash = hash_token(payload.token)
    record = db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)).scalar_one_or_none()

    if not record or record.used_at is not None or _is_expired(record.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = get_password_hash(payload.new_password)
    record.used_at = datetime.now(timezone.utc)
    db.commit()

    audit_event(
        db,
        event_type="auth.password_reset_confirm",
        resource_type="user",
        resource_id=user.id,
        action="password_reset_confirm",
        user_id=user.id,
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Password updated successfully"}
