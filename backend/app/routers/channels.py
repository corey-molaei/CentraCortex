from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models.channel_facebook_connector import ChannelFacebookConnector
from app.models.channel_telegram_connector import ChannelTelegramConnector
from app.models.channel_whatsapp_connector import ChannelWhatsAppConnector
from app.models.connectors.google_user_connector import GoogleUserConnector
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

router = APIRouter(prefix="/channels", tags=["channels"])
logger = structlog.get_logger(__name__)


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
    config_json = dict(row.config_json or {})
    if name == "telegram":
        configured = bool(row.bot_token_encrypted)
        config_json["webhook_path"] = f"/api/v1/channels/telegram/webhook/{row.id}"
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
        config_json=config_json,
    )


def _build_public_api_base(request: Request) -> str:
    configured = (settings.api_base_url or "").strip()
    if configured:
        parsed = urlparse(configured)
        host = (parsed.hostname or "").lower()
        is_local = host in {"localhost", "127.0.0.1", "0.0.0.0", "testserver"} or host.endswith(".local")
        if parsed.scheme == "https":
            return configured.rstrip("/")
        if parsed.scheme == "http" and is_local:
            return configured.rstrip("/")
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return configured.replace("http://", "https://", 1).rstrip("/")

    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    forwarded_host = request.headers.get("X-Forwarded-Host")
    if forwarded_proto and forwarded_host:
        scheme = "https" if forwarded_proto.lower() != "http" else "http"
        if forwarded_host.lower().startswith(("localhost", "127.0.0.1", "0.0.0.0", "testserver")):
            return f"{scheme}://{forwarded_host}".rstrip("/")
        return f"https://{forwarded_host}".rstrip("/")

    fallback = str(request.base_url).rstrip("/")
    parsed_fallback = urlparse(fallback)
    host = (parsed_fallback.hostname or "").lower()
    is_local = host in {"localhost", "127.0.0.1", "0.0.0.0", "testserver"} or host.endswith(".local")
    if fallback.startswith("http://") and not is_local:
        return fallback.replace("http://", "https://", 1)
    return fallback


def _telegram_webhook_url(*, connector_id: str, request: Request) -> str:
    return f"{_build_public_api_base(request)}/api/v1/channels/telegram/webhook/{connector_id}"


def _register_telegram_webhook(
    *,
    bot_token: str,
    webhook_url: str,
    webhook_secret: str | None,
) -> None:
    payload: dict[str, Any] = {
        "url": webhook_url,
        "drop_pending_updates": False,
        "allowed_updates": ["message", "edited_message"],
    }
    secret_value = (webhook_secret or "").strip()
    if secret_value:
        payload["secret_token"] = secret_value

    with httpx.Client(timeout=20) as client:
        response = client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json=payload,
        )
    if response.status_code >= 400:
        raise ValueError(f"Telegram setWebhook failed ({response.status_code}): {response.text[:400]}")
    data = response.json()
    if not data.get("ok"):
        raise ValueError(str(data.get("description") or "Telegram setWebhook failed"))


def _send_telegram_message(*, bot_token: str, chat_id: str, text: str) -> None:
    safe_text = (text or "").strip() or "Done."
    safe_text = safe_text[:3900]
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
        )
    if response.status_code >= 400:
        raise ValueError(f"Telegram sendMessage failed ({response.status_code}): {response.text[:400]}")
    data = response.json()
    if not data.get("ok"):
        raise ValueError(str(data.get("description") or "Telegram sendMessage failed"))


def _parse_telegram_update(update: dict[str, Any]) -> tuple[ChannelInboundEvent | None, str | None]:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None, None

    text = str(message.get("text") or "").strip()
    if not text:
        return None, None

    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat_id_raw = chat.get("id")
    sender_id_raw = sender.get("id")
    chat_id = str(chat_id_raw) if chat_id_raw is not None else ""
    external_user_id = str(sender_id_raw) if sender_id_raw is not None else chat_id
    if not external_user_id:
        return None, None

    first_name = str(sender.get("first_name") or "").strip()
    last_name = str(sender.get("last_name") or "").strip()
    username = str(sender.get("username") or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    display_name = full_name or (f"@{username}" if username else None)

    return (
        ChannelInboundEvent(
            external_user_id=external_user_id,
            text=text,
            name=display_name,
            phone=None,
            email=None,
        ),
        chat_id or external_user_id,
    )


def _workspace_actor(db: Session, *, tenant_id: str) -> TenantMembership:
    actor = db.execute(
        select(TenantMembership)
        .where(TenantMembership.tenant_id == tenant_id)
        .order_by(TenantMembership.role.asc(), TenantMembership.created_at.asc())
    ).scalars().first()
    if actor is None:
        raise HTTPException(status_code=400, detail="No workspace member available for channel runtime")
    return actor


def _ensure_workspace_google_default(db: Session, *, tenant_id: str) -> None:
    integration = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.is_workspace_default.is_(True),
            GoogleUserConnector.enabled.is_(True),
            GoogleUserConnector.access_token_encrypted.is_not(None),
        )
    ).scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=400,
            detail="Workspace default Google account is not connected. Configure /connectors/google first.",
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
    request: Request,
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
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChannelTestResponse:
    row = _telegram(db, membership.tenant_id)
    if not row.bot_token_encrypted:
        return ChannelTestResponse(success=False, message="Telegram bot token is not configured")
    bot_token = decrypt_secret(row.bot_token_encrypted)
    webhook_url = _telegram_webhook_url(connector_id=row.id, request=request)
    try:
        _register_telegram_webhook(
            bot_token=bot_token,
            webhook_url=webhook_url,
            webhook_secret=row.webhook_secret,
        )
    except Exception as exc:  # noqa: BLE001
        row.last_error = str(exc)[:1800]
        db.commit()
        logger.warning(
            "telegram_webhook_registration_failed",
            tenant_id=membership.tenant_id,
            connector_id=row.id,
            error=str(exc),
        )
        return ChannelTestResponse(success=False, message=f"Telegram webhook registration failed: {exc}")

    row.last_error = None
    row.config_json = {
        **(row.config_json or {}),
        "webhook_url": webhook_url,
    }
    db.commit()
    return ChannelTestResponse(success=True, message=f"Telegram connector looks configured. Webhook: {webhook_url}")


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

    _ensure_workspace_google_default(db, tenant_id=tenant_id)

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
    actor = _workspace_actor(db, tenant_id=tenant_id)

    return run_channel_message(
        db,
        tenant_id=tenant_id,
        user_id=actor.user_id,
        channel="telegram",
        contact=contact,
        message=payload.text,
    )


@router.post("/telegram/webhook/{connector_id}")
async def telegram_webhook_public(
    connector_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    row = db.execute(select(ChannelTelegramConnector).where(ChannelTelegramConnector.id == connector_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Telegram connector not found")
    if not row.enabled:
        raise HTTPException(status_code=400, detail="Telegram connector is disabled")
    if not row.bot_token_encrypted:
        raise HTTPException(status_code=400, detail="Telegram bot token is not configured")

    expected_secret = (row.webhook_secret or "").strip()
    if expected_secret:
        provided_secret = (request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").strip()
        if provided_secret != expected_secret:
            logger.warning(
                "telegram_webhook_secret_mismatch",
                tenant_id=row.tenant_id,
                connector_id=row.id,
            )
            raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    try:
        update = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid Telegram payload: {exc}") from exc

    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="Invalid Telegram payload")

    inbound, chat_id = _parse_telegram_update(update)
    if inbound is None or not chat_id:
        logger.debug(
            "telegram_webhook_ignored_non_text",
            tenant_id=row.tenant_id,
            connector_id=row.id,
        )
        return {"ok": True, "ignored": True}

    tenant_id = row.tenant_id
    _ensure_workspace_google_default(db, tenant_id=tenant_id)
    actor = _workspace_actor(db, tenant_id=tenant_id)
    contact = resolve_contact(
        db,
        tenant_id=tenant_id,
        channel="telegram",
        external_user_id=inbound.external_user_id,
        name=inbound.name,
        phone=inbound.phone,
        email=inbound.email,
    )
    result = run_channel_message(
        db,
        tenant_id=tenant_id,
        user_id=actor.user_id,
        channel="telegram",
        contact=contact,
        message=inbound.text,
    )

    bot_token = decrypt_secret(row.bot_token_encrypted)
    try:
        _send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=str(result.get("answer") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        row.last_error = str(exc)[:1800]
        db.commit()
        logger.exception(
            "telegram_send_failed",
            tenant_id=tenant_id,
            connector_id=row.id,
            chat_id=chat_id,
        )
        raise HTTPException(status_code=502, detail=f"Telegram send failed: {exc}") from exc

    row.last_error = None
    db.commit()
    return {"ok": True, "conversation_id": result.get("conversation_id")}


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
