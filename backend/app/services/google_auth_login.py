from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash, random_token
from app.models.auth_oauth_state import AuthOAuthState
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.models.user_identity import UserIdentity

GOOGLE_OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "workspace"


def _google_auth_scopes() -> str:
    raw = (settings.google_auth_scopes or "openid profile email").strip()
    return " ".join([chunk for chunk in raw.replace(",", " ").split() if chunk])


def start_google_login(db: Session, *, redirect_uri: str) -> tuple[str, str]:
    if not settings.google_client_id:
        raise ValueError("Google OAuth is not configured. Set GOOGLE_CLIENT_ID.")

    state = random_token(16)
    row = AuthOAuthState(
        provider="google",
        state_token=state,
        redirect_uri=redirect_uri,
        expires_at=_utcnow() + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()

    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _google_auth_scopes(),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_OAUTH_URL}?{params}", state


def _exchange_code(*, code: str, redirect_uri: str) -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise ValueError("Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")

    with httpx.Client(timeout=30) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
            },
        )

    if response.status_code >= 400:
        raise ValueError(f"Google token exchange failed: {response.text}")
    return response.json()


def _fetch_userinfo(access_token: str) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        raise ValueError(f"Google userinfo request failed: {response.text}")
    return response.json()


def _find_or_create_user(db: Session, *, email: str, full_name: str | None, subject: str) -> User:
    identity = db.execute(
        select(UserIdentity).where(UserIdentity.provider == "google", UserIdentity.provider_subject == subject)
    ).scalar_one_or_none()
    if identity:
        user = db.get(User, identity.user_id)
        if not user:
            raise ValueError("Google identity is linked to a missing user")
        return user

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=get_password_hash(random_token(24)),
            is_active=True,
        )
        db.add(user)
        db.flush()

        # bootstrap workspace on first Google login when no account exists
        slug_base = _slugify(email.split("@", 1)[0])
        slug = slug_base
        idx = 1
        while db.execute(select(Tenant.id).where(Tenant.slug == slug)).scalar_one_or_none():
            idx += 1
            slug = f"{slug_base}-{idx}"

        tenant = Tenant(
            name=full_name or settings.google_auth_default_tenant_name,
            slug=slug,
            is_active=True,
        )
        db.add(tenant)
        db.flush()

        db.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                role="owner",
                is_default=True,
            )
        )

    db.add(
        UserIdentity(
            user_id=user.id,
            provider="google",
            provider_subject=subject,
            email=email,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def complete_google_login(db: Session, *, code: str, state: str) -> User:
    state_row = db.execute(
        select(AuthOAuthState).where(AuthOAuthState.provider == "google", AuthOAuthState.state_token == state)
    ).scalar_one_or_none()
    if not state_row:
        raise ValueError("Invalid OAuth state")

    if state_row.expires_at.replace(tzinfo=UTC) < _utcnow():
        db.delete(state_row)
        db.commit()
        raise ValueError("OAuth state has expired")

    token_payload = _exchange_code(code=code, redirect_uri=state_row.redirect_uri)
    access_token = str(token_payload.get("access_token") or "")
    if not access_token:
        raise ValueError("Google token exchange did not return an access token")

    userinfo = _fetch_userinfo(access_token)
    email = str(userinfo.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Google profile did not include an email")
    if userinfo.get("verified_email") is False:
        raise ValueError("Google email is not verified")

    allowed_domains = [item.strip().lower() for item in (settings.google_auth_allowed_domains or "").split(",") if item.strip()]
    if allowed_domains:
        domain = email.split("@", 1)[-1]
        if domain not in allowed_domains:
            raise ValueError("Google account domain is not allowed")

    subject = str(userinfo.get("id") or "")
    if not subject:
        raise ValueError("Google profile did not include subject id")

    user = _find_or_create_user(
        db,
        email=email,
        full_name=str(userinfo.get("name") or "").strip() or None,
        subject=subject,
    )

    db.delete(state_row)
    db.commit()
    return user
