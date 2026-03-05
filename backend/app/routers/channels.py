from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.core.security import decrypt_secret, encrypt_secret
from app.models.channel_facebook_connector import ChannelFacebookConnector
from app.models.channel_telegram_connector import ChannelTelegramConnector
from app.models.channel_whatsapp_connector import ChannelWhatsAppConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.channels import (
    ChannelConnectorRead,
    ChannelInboundEvent,
    ChannelTestResponse,
    FacebookConnectorUpdate,
    TelegramConnectorUpdate,
    WhatsAppConnectorUpdate,
)
from app.services.channel_dispatcher import resolve_contact, run_channel_message
from app.services.connectors.google_workspace_service import get_or_create_integration

router = APIRouter(prefix="/channels", tags=["channels"])


def _telegram(db: Session, tenant_id: str) -> ChannelTelegramConnector:
    row = db.execute(select(ChannelTelegramConnector).where(ChannelTelegramConnector.tenant_id == tenant_id)).scalar_one_or_none()
    if row:
        return row
    row = ChannelTelegramConnector(tenant_id=tenant_id, enabled=False, config_json={})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _whatsapp(db: Session, tenant_id: str) -> ChannelWhatsAppConnector:
    row = db.execute(select(ChannelWhatsAppConnector).where(ChannelWhatsAppConnector.tenant_id == tenant_id)).scalar_one_or_none()
    if row:
        return row
    row = ChannelWhatsAppConnector(tenant_id=tenant_id, enabled=False, config_json={})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _facebook(db: Session, tenant_id: str) -> ChannelFacebookConnector:
    row = db.execute(select(ChannelFacebookConnector).where(ChannelFacebookConnector.tenant_id == tenant_id)).scalar_one_or_none()
    if row:
        return row
    row = ChannelFacebookConnector(tenant_id=tenant_id, enabled=False, config_json={})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _read_channel(name: str, row) -> ChannelConnectorRead:
    configured = False
    if name == "telegram":
        configured = bool(row.bot_token_encrypted)
    elif name == "whatsapp":
        configured = bool(row.access_token_encrypted and row.phone_number_id)
    elif name == "facebook":
        configured = bool(row.page_access_token_encrypted and row.page_id)

    return ChannelConnectorRead(
        id=row.id,
        tenant_id=row.tenant_id,
        channel=name,
        enabled=row.enabled,
        configured=configured,
        last_error=row.last_error,
        config_json=row.config_json or {},
    )


@router.get("/status", response_model=list[ChannelConnectorRead])
def channel_status(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[ChannelConnectorRead]:
    return [
        _read_channel("telegram", _telegram(db, membership.tenant_id)),
        _read_channel("whatsapp", _whatsapp(db, membership.tenant_id)),
        _read_channel("facebook", _facebook(db, membership.tenant_id)),
    ]


@router.put("/telegram", response_model=ChannelConnectorRead)
def upsert_telegram(
    payload: TelegramConnectorUpdate,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ChannelConnectorRead:
    row = _telegram(db, admin.tenant_id)
    updates = payload.model_dump(exclude_unset=True)
    if "bot_token" in updates:
        row.bot_token_encrypted = encrypt_secret(updates.pop("bot_token")) if updates["bot_token"] else None
    for key, value in updates.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _read_channel("telegram", row)


@router.put("/whatsapp", response_model=ChannelConnectorRead)
def upsert_whatsapp(
    payload: WhatsAppConnectorUpdate,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ChannelConnectorRead:
    row = _whatsapp(db, admin.tenant_id)
    updates = payload.model_dump(exclude_unset=True)
    if "access_token" in updates:
        row.access_token_encrypted = encrypt_secret(updates.pop("access_token")) if updates["access_token"] else None
    for key, value in updates.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _read_channel("whatsapp", row)


@router.put("/facebook", response_model=ChannelConnectorRead)
def upsert_facebook(
    payload: FacebookConnectorUpdate,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ChannelConnectorRead:
    row = _facebook(db, admin.tenant_id)
    updates = payload.model_dump(exclude_unset=True)
    if "page_access_token" in updates:
        row.page_access_token_encrypted = encrypt_secret(updates.pop("page_access_token")) if updates["page_access_token"] else None
    if "app_secret" in updates:
        row.app_secret_encrypted = encrypt_secret(updates.pop("app_secret")) if updates["app_secret"] else None
    for key, value in updates.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _read_channel("facebook", row)


@router.post("/telegram/test", response_model=ChannelTestResponse)
def test_telegram(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChannelTestResponse:
    row = _telegram(db, membership.tenant_id)
    if not row.bot_token_encrypted:
        return ChannelTestResponse(success=False, message="Telegram bot token is not configured")
    _ = decrypt_secret(row.bot_token_encrypted)
    return ChannelTestResponse(success=True, message="Telegram connector looks configured")


@router.post("/whatsapp/test", response_model=ChannelTestResponse)
def test_whatsapp(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChannelTestResponse:
    row = _whatsapp(db, membership.tenant_id)
    if not row.access_token_encrypted or not row.phone_number_id:
        return ChannelTestResponse(success=False, message="WhatsApp credentials are incomplete")
    _ = decrypt_secret(row.access_token_encrypted)
    return ChannelTestResponse(success=True, message="WhatsApp connector looks configured")


@router.post("/facebook/test", response_model=ChannelTestResponse)
def test_facebook(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChannelTestResponse:
    row = _facebook(db, membership.tenant_id)
    if not row.page_access_token_encrypted or not row.page_id:
        return ChannelTestResponse(success=False, message="Facebook credentials are incomplete")
    _ = decrypt_secret(row.page_access_token_encrypted)
    return ChannelTestResponse(success=True, message="Facebook connector looks configured")


@router.post("/telegram/webhook")
def telegram_webhook(
    payload: ChannelInboundEvent,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID is required")

    row = _telegram(db, tenant_id)
    if not row.enabled:
        raise HTTPException(status_code=400, detail="Telegram connector is disabled")

    integration = get_or_create_integration(db, tenant_id=tenant_id)
    if not integration.access_token_encrypted:
        raise HTTPException(status_code=400, detail="Workspace Google integration is not connected")

    contact = resolve_contact(
        db,
        tenant_id=tenant_id,
        channel="telegram",
        external_user_id=payload.external_user_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
    )
    # use deterministic workspace admin actor; first owner/admin member
    actor = db.execute(
        select(TenantMembership)
        .where(TenantMembership.tenant_id == tenant_id)
        .order_by(TenantMembership.role.asc(), TenantMembership.created_at.asc())
    ).scalars().first()
    if actor is None:
        raise HTTPException(status_code=400, detail="No workspace member available for channel runtime")

    return run_channel_message(
        db,
        tenant_id=tenant_id,
        user_id=actor.user_id,
        channel="telegram",
        contact=contact,
        message=payload.text,
    )


@router.post("/whatsapp/webhook")
def whatsapp_webhook(
    payload: ChannelInboundEvent,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID is required")
    row = _whatsapp(db, tenant_id)
    if not row.enabled:
        raise HTTPException(status_code=400, detail="WhatsApp connector is disabled")
    actor = db.execute(
        select(TenantMembership)
        .where(TenantMembership.tenant_id == tenant_id)
        .order_by(TenantMembership.role.asc(), TenantMembership.created_at.asc())
    ).scalars().first()
    if actor is None:
        raise HTTPException(status_code=400, detail="No workspace member available for channel runtime")
    contact = resolve_contact(
        db,
        tenant_id=tenant_id,
        channel="whatsapp",
        external_user_id=payload.external_user_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
    )
    return run_channel_message(
        db,
        tenant_id=tenant_id,
        user_id=actor.user_id,
        channel="whatsapp",
        contact=contact,
        message=payload.text,
    )


@router.post("/facebook/webhook")
def facebook_webhook(
    payload: ChannelInboundEvent,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID is required")
    row = _facebook(db, tenant_id)
    if not row.enabled:
        raise HTTPException(status_code=400, detail="Facebook connector is disabled")
    actor = db.execute(
        select(TenantMembership)
        .where(TenantMembership.tenant_id == tenant_id)
        .order_by(TenantMembership.role.asc(), TenantMembership.created_at.asc())
    ).scalars().first()
    if actor is None:
        raise HTTPException(status_code=400, detail="No workspace member available for channel runtime")
    contact = resolve_contact(
        db,
        tenant_id=tenant_id,
        channel="facebook",
        external_user_id=payload.external_user_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
    )
    return run_channel_message(
        db,
        tenant_id=tenant_id,
        user_id=actor.user_id,
        channel="facebook",
        contact=contact,
        message=payload.text,
    )
