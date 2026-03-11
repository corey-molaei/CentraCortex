from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_conversation import ChatConversation
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.conversation_contact_link import ConversationContactLink
from app.models.workspace_contact import WorkspaceContact
from app.services.audit import audit_event
from app.services.chat_runtime import get_or_create_conversation, run_chat_v2
from app.services.connectors.google_service import append_crm_row

CHANNEL_HISTORY_TURN_LIMIT = 50
CHANNEL_NEW_COMMAND = "/new"


def resolve_contact(
    db: Session,
    *,
    tenant_id: str,
    channel: str,
    external_user_id: str,
    name: str | None,
    phone: str | None,
    email: str | None,
) -> WorkspaceContact:
    contact = db.execute(
        select(WorkspaceContact).where(
            WorkspaceContact.tenant_id == tenant_id,
            WorkspaceContact.channel == channel,
            WorkspaceContact.external_user_id == external_user_id,
        )
    ).scalar_one_or_none()
    if contact is None:
        contact = WorkspaceContact(
            tenant_id=tenant_id,
            channel=channel,
            external_user_id=external_user_id,
            name=name,
            phone=phone,
            email=email,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)
        return contact

    if name:
        contact.name = name
    if phone:
        contact.phone = phone
    if email:
        contact.email = email
    db.commit()
    return contact


def _load_valid_active_conversation_id(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    contact: WorkspaceContact,
) -> str | None:
    candidate = (contact.active_conversation_id or "").strip()
    if not candidate:
        return None
    valid = db.execute(
        select(ChatConversation.id).where(
            ChatConversation.id == candidate,
            ChatConversation.tenant_id == tenant_id,
            ChatConversation.user_id == user_id,
        )
    ).scalar_one_or_none()
    if valid:
        return candidate
    contact.active_conversation_id = None
    db.commit()
    return None


def _ensure_conversation_contact_link(
    db: Session,
    *,
    tenant_id: str,
    conversation_id: str,
    contact_id: str,
) -> None:
    link = db.execute(
        select(ConversationContactLink).where(
            ConversationContactLink.tenant_id == tenant_id,
            ConversationContactLink.conversation_id == conversation_id,
            ConversationContactLink.contact_id == contact_id,
        )
    ).scalar_one_or_none()
    if link is None:
        db.add(
            ConversationContactLink(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
            )
        )
        db.commit()


def _start_new_contact_conversation(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    contact: WorkspaceContact,
    seed_message: str,
) -> str:
    conversation = get_or_create_conversation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=None,
        seed_message=seed_message,
    )
    contact.active_conversation_id = conversation.id
    db.commit()
    _ensure_conversation_contact_link(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        contact_id=contact.id,
    )
    return conversation.id


def run_channel_message(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    channel: str,
    contact: WorkspaceContact,
    message: str,
) -> dict:
    normalized = (message or "").strip()
    active_conversation_id = _load_valid_active_conversation_id(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        contact=contact,
    )

    if normalized.lower() == CHANNEL_NEW_COMMAND:
        previous_conversation_id = active_conversation_id
        new_conversation_id = _start_new_contact_conversation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            contact=contact,
            seed_message=normalized or "New conversation",
        )
        reset_text = "Started a new conversation. You can continue with a fresh context."
        audit_event(
            db,
            event_type="channel.conversation.reset",
            resource_type="channel_contact",
            action="reset",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=contact.id,
            payload={
                "channel": channel,
                "previous_conversation_id": previous_conversation_id,
                "new_conversation_id": new_conversation_id,
            },
        )
        return {
            "conversation_id": new_conversation_id,
            "assistant_message_id": "",
            "answer": reset_text,
            "provider_name": "Channel Dispatcher",
            "model_name": "deterministic",
        }

    result = run_chat_v2(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        user_messages=[{"role": "user", "content": message}],
        temperature=0.2,
        provider_id_override=None,
        conversation_id=active_conversation_id,
        retrieval_limit=8,
        client_timezone="UTC",
        client_now_iso=None,
        history_turn_limit=CHANNEL_HISTORY_TURN_LIMIT,
    )

    if contact.active_conversation_id != result.conversation_id:
        contact.active_conversation_id = result.conversation_id
        db.commit()
    _ensure_conversation_contact_link(
        db,
        tenant_id=tenant_id,
        conversation_id=result.conversation_id,
        contact_id=contact.id,
    )

    audit_event(
        db,
        event_type="channel.message.processed",
        resource_type="channel_contact",
        action="message",
        tenant_id=tenant_id,
        user_id=user_id,
        resource_id=contact.id,
        payload={
            "channel": channel,
            "conversation_id": result.conversation_id,
            "assistant_message_id": result.assistant_message_id,
        },
    )

    integration = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.is_workspace_default.is_(True),
            GoogleUserConnector.enabled.is_(True),
            GoogleUserConnector.sheets_enabled.is_(True),
            GoogleUserConnector.crm_sheet_spreadsheet_id.is_not(None),
        )
    ).scalar_one_or_none()
    if integration and settings.google_client_id and settings.google_client_secret:
        try:
            append_crm_row(
                db,
                integration,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                values=[
                    contact.name or "",
                    contact.phone or "",
                    contact.email or "",
                    (result.answer or "")[:500],
                    "",
                    "",
                    datetime.now(UTC).isoformat(),
                    channel,
                    result.conversation_id,
                ],
            )
        except Exception as exc:  # noqa: BLE001
            audit_event(
                db,
                event_type="channel.crm_log_failed",
                resource_type="google_connector_account",
                action="append_row",
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=integration.id,
                payload={"error": str(exc), "conversation_id": result.conversation_id},
            )

    return {
        "conversation_id": result.conversation_id,
        "assistant_message_id": result.assistant_message_id,
        "answer": result.answer,
        "provider_name": result.provider_name,
        "model_name": result.model_name,
    }
