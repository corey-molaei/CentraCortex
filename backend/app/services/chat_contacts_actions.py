from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_pending_action import ChatPendingAction
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.workspace_settings import WorkspaceSettings
from app.services.audit import audit_event
from app.services.connectors.google_service import (
    create_contact,
    delete_contact,
    get_contact,
    get_primary_account,
    list_contacts,
    list_user_accounts,
    search_contacts,
    update_contact,
)
from app.services.llm_router import LLMRouter

INTENT_ACCESS = "contacts_access"
INTENT_LIST = "contacts_list"
INTENT_READ = "contacts_read"
INTENT_CREATE = "contacts_create"
INTENT_UPDATE = "contacts_update"
INTENT_DELETE = "contacts_delete"

PENDING_DISAMBIGUATION = "pending_disambiguation"
PENDING_CONFIRMATION = "pending_confirmation"
COMPLETED = "completed"
CANCELLED = "cancelled"
EXPIRED = "expired"

YES_TOKENS = {"yes", "y", "confirm", "confirmed", "ok", "okay"}
NO_TOKENS = {"no", "n", "cancel", "stop"}
YES_PHRASES = {"go ahead", "do it"}
NO_PHRASES = {"never mind", "nevermind"}

EMAIL_REGEX = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.IGNORECASE)
PHONE_REGEX = re.compile(r"(?:\+?\d[\d\s().\-]{6,}\d)")
RESOURCE_NAME_REGEX = re.compile(r"\bpeople/[A-Za-z0-9_\-]+\b")
CONTACT_TOKENS = {
    "contact",
    "contacts",
    "people",
    "person",
    "addressbook",
    "address_book",
}
CONTACT_WRITE_SCOPE = "https://www.googleapis.com/auth/contacts"
CONTACT_READ_SCOPES = {
    CONTACT_WRITE_SCOPE,
    "https://www.googleapis.com/auth/contacts.readonly",
}

logger = structlog.get_logger(__name__)


@dataclass
class ContactsChatResult:
    handled: bool
    answer: str


@dataclass
class ParsedContactsIntent:
    intent: str
    account_hint: str | None = None
    contact_id: str | None = None
    target_query: str | None = None
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    emails: list[str] | None = None
    phones: list[str] | None = None
    organizations: list[str] | None = None
    biography: str | None = None
    confidence: float | None = None


def _workspace_action_enabled(db: Session, *, tenant_id: str, action_key: str, default: bool = True) -> bool:
    row = db.execute(
        select(WorkspaceSettings.allowed_actions_json).where(WorkspaceSettings.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not isinstance(row, dict):
        return default
    value = row.get(action_key)
    if value is None:
        return default
    return bool(value)


def maybe_handle_contacts_chat_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    provider_id_override: str | None = None,
) -> ContactsChatResult | None:
    now_utc = datetime.now(UTC)
    pending = _get_active_pending_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if pending:
        if _coerce_utc(pending.expires_at) < now_utc:
            pending.status = EXPIRED
            db.commit()
            return ContactsChatResult(
                handled=True,
                answer="That pending contacts action expired. Please repeat your request.",
            )
        return _handle_pending_followup(
            db,
            pending=pending,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
        )

    if not _looks_contacts_related(message):
        return None

    parsed = _parse_contacts_intent_llm(
        db,
        tenant_id=tenant_id,
        message=message,
        provider_id_override=provider_id_override,
    )
    fallback_used = False
    if parsed is None:
        parsed = _parse_contacts_intent_fallback(message)
        fallback_used = True
    parsed = _normalize_and_validate_contacts_intent(parsed, message=message)

    logger.debug(
        "contacts_intent_parse_result",
        tenant_id=tenant_id,
        user_id=user_id,
        intent=(parsed.intent if parsed else None),
        parser_fallback_used=fallback_used,
    )

    if parsed is None:
        return ContactsChatResult(handled=True, answer=_contacts_help_response())

    if parsed.intent not in {
        INTENT_ACCESS,
        INTENT_LIST,
        INTENT_READ,
        INTENT_CREATE,
        INTENT_UPDATE,
        INTENT_DELETE,
    }:
        return ContactsChatResult(handled=True, answer=_contacts_help_response())

    if not settings.google_client_id or not settings.google_client_secret:
        return ContactsChatResult(
            handled=True,
            answer=(
                "Google actions are not available because OAuth credentials are not configured on the server. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend environment settings."
            ),
        )

    account = _resolve_account(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        message=message,
        account_hint=parsed.account_hint,
    )
    if account is None:
        return ContactsChatResult(
            handled=True,
            answer=(
                "I could not find a connected Google account for this user. "
                "Open /connectors/google, connect an account, and set one as primary."
            ),
        )
    if not account.enabled:
        return ContactsChatResult(handled=True, answer="This Google account is disabled. Re-enable it in /connectors/google.")
    if not account.access_token_encrypted:
        return ContactsChatResult(
            handled=True,
            answer="This Google account is not connected yet. Click Connect/Reconnect in /connectors/google first.",
        )

    if parsed.intent == INTENT_ACCESS:
        return _handle_access_status(account=account)

    if not account.contacts_enabled:
        return ContactsChatResult(
            handled=True,
            answer=(
                "Contacts access is disabled for this account. Enable Contacts in /connectors/google and reconnect "
                "to grant the required permissions."
            ),
        )

    if parsed.intent in {INTENT_LIST, INTENT_READ} and not _has_contacts_read_scope(account):
        return ContactsChatResult(
            handled=True,
            answer=(
                "Contacts read scope is missing for this account. Reconnect in /connectors/google with Contacts enabled."
            ),
        )

    if parsed.intent in {INTENT_CREATE, INTENT_UPDATE, INTENT_DELETE}:
        action_key = parsed.intent.replace("contacts_", "contacts_")
        if not _workspace_action_enabled(db, tenant_id=tenant_id, action_key=action_key):
            return ContactsChatResult(
                handled=True,
                answer="This contacts action is disabled for this workspace by policy. Enable it in Workspace Settings.",
            )
        if not _has_contacts_write_scope(account):
            return ContactsChatResult(
                handled=True,
                answer=(
                    "Contacts write scope is missing for this account. Reconnect in /connectors/google with Contacts "
                    "enabled to grant write permissions."
                ),
            )

    if parsed.intent == INTENT_LIST:
        return _handle_list_action(db, account=account, parsed=parsed)
    if parsed.intent == INTENT_READ:
        return _handle_read_action(db, account=account, parsed=parsed)
    if parsed.intent == INTENT_CREATE:
        return _queue_create_confirmation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account=account,
            parsed=parsed,
        )
    if parsed.intent in {INTENT_UPDATE, INTENT_DELETE}:
        return _queue_update_or_delete(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account=account,
            parsed=parsed,
        )
    return ContactsChatResult(handled=True, answer=_contacts_help_response())


def _contacts_help_response() -> str:
    return (
        "I can help with Google Contacts actions, but I need a clearer command.\n"
        "Examples:\n"
        "- do you have access to my contacts\n"
        "- list my contacts\n"
        "- find contact john\n"
        "- read contact people/c123456\n"
        "- add contact John Doe email john@example.com phone +61 400 000 000\n"
        "- update contact John Doe email john.new@example.com\n"
        "- delete contact John Doe\n"
        "Note: create/update/delete always require your confirmation."
    )


def _looks_contacts_related(message: str) -> bool:
    if RESOURCE_NAME_REGEX.search(message):
        return True
    tokens = _tokenize(message)
    return bool(tokens.intersection(CONTACT_TOKENS))


def _handle_access_status(*, account: GoogleUserConnector) -> ContactsChatResult:
    if not account.enabled:
        return ContactsChatResult(handled=True, answer="No. Your Google account is currently disabled.")
    if not account.access_token_encrypted:
        return ContactsChatResult(handled=True, answer="No. Your Google account is not connected yet.")
    if not account.contacts_enabled:
        return ContactsChatResult(
            handled=True,
            answer="No. Contacts capability is disabled for this account. Enable Contacts in /connectors/google.",
        )
    if not _has_contacts_read_scope(account):
        return ContactsChatResult(
            handled=True,
            answer="No. Contacts permission is missing. Reconnect in /connectors/google with Contacts enabled.",
        )

    if _has_contacts_write_scope(account):
        return ContactsChatResult(
            handled=True,
            answer=f"Yes. I can access and modify contacts on {account.google_account_email or account.label or 'this account'}.",
        )
    return ContactsChatResult(
        handled=True,
        answer=(
            f"Yes. I can read contacts on {account.google_account_email or account.label or 'this account'}, "
            "but write permission is not granted."
        ),
    )


def _handle_list_action(
    db: Session,
    *,
    account: GoogleUserConnector,
    parsed: ParsedContactsIntent,
) -> ContactsChatResult:
    query = (parsed.target_query or "").strip()
    try:
        if query:
            contacts = search_contacts(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                query=query,
                limit=10,
            )
        else:
            contacts = list_contacts(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                limit=10,
            )
    except ValueError as exc:
        return ContactsChatResult(handled=True, answer=f"Google Contacts request failed: {exc}")

    if not contacts:
        return ContactsChatResult(
            handled=True,
            answer="I could not find any matching contacts." if query else "I could not find contacts in this account.",
        )

    lines = ["Here are the contacts I found:"]
    for idx, item in enumerate(contacts[:10], start=1):
        display = str(item.get("display_name") or "Unnamed")
        email = str(item.get("primary_email") or "-")
        phone = str(item.get("primary_phone") or "-")
        resource = str(item.get("resource_name") or "-")
        lines.append(f"{idx}. {display} | email: {email} | phone: {phone} | id: {resource}")
    return ContactsChatResult(handled=True, answer="\n".join(lines))


def _handle_read_action(
    db: Session,
    *,
    account: GoogleUserConnector,
    parsed: ParsedContactsIntent,
) -> ContactsChatResult:
    if parsed.contact_id:
        resource = parsed.contact_id
    else:
        query = (parsed.target_query or "").strip()
        if not query:
            return ContactsChatResult(handled=True, answer="Please specify which contact to read (name, email, or contact id).")
        candidates = _find_contact_candidates(db, account=account, query=query, limit=5)
        if not candidates:
            return ContactsChatResult(handled=True, answer=f"I could not find a contact matching '{query}'.")
        if len(candidates) > 1:
            lines = ["I found multiple contacts. Please specify one by contact id:"]
            for idx, item in enumerate(candidates, start=1):
                lines.append(
                    f"{idx}. {item.get('display_name') or 'Unnamed'} | "
                    f"{item.get('primary_email') or '-'} | id: {item.get('resource_name')}"
                )
            return ContactsChatResult(handled=True, answer="\n".join(lines))
        resource = str(candidates[0].get("resource_name") or "")

    if not resource:
        return ContactsChatResult(handled=True, answer="I could not resolve the contact id.")

    try:
        item = get_contact(
            db,
            account,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            resource_name=resource,
        )
    except ValueError as exc:
        return ContactsChatResult(handled=True, answer=f"Google Contacts read failed: {exc}")

    lines = [
        "Contact details:",
        f"Name: {item.get('display_name') or '-'}",
        f"Given name: {item.get('given_name') or '-'}",
        f"Family name: {item.get('family_name') or '-'}",
        f"Emails: {', '.join(item.get('emails') or []) or '-'}",
        f"Phones: {', '.join(item.get('phones') or []) or '-'}",
        f"Organizations: {', '.join(item.get('organizations') or []) or '-'}",
        f"Notes: {item.get('biography') or '-'}",
        f"ID: {item.get('resource_name') or '-'}",
    ]
    return ContactsChatResult(handled=True, answer="\n".join(lines))


def _queue_create_confirmation(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account: GoogleUserConnector,
    parsed: ParsedContactsIntent,
) -> ContactsChatResult:
    create_payload = _contact_payload_from_intent(parsed)
    if not _has_contact_create_fields(create_payload):
        return ContactsChatResult(
            handled=True,
            answer="I need at least a name, email, phone, organization, or note to create a contact.",
        )

    pending = ChatPendingAction(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        action_type=INTENT_CREATE,
        status=PENDING_CONFIRMATION,
        account_id=account.id,
        payload_json={"create_payload": create_payload},
        candidates_json=[],
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)

    return ContactsChatResult(
        handled=True,
        answer=_build_create_confirmation_prompt(account=account, payload=create_payload),
    )


def _queue_update_or_delete(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account: GoogleUserConnector,
    parsed: ParsedContactsIntent,
) -> ContactsChatResult:
    query = (parsed.target_query or "").strip()
    contact_id = (parsed.contact_id or "").strip()
    if not contact_id and not query:
        return ContactsChatResult(
            handled=True,
            answer="Please specify which contact to update/delete (name, email, or contact id).",
        )

    if parsed.intent == INTENT_UPDATE:
        update_payload = _contact_payload_from_intent(parsed)
        if not _has_contact_update_fields(update_payload):
            return ContactsChatResult(
                handled=True,
                answer="I need at least one updated field (name/email/phone/organization/note) for contact update.",
            )
    else:
        update_payload = {}

    if contact_id:
        candidates = [{"resource_name": contact_id}]
    else:
        candidates = _find_contact_candidates(db, account=account, query=query, limit=5)

    if not candidates:
        return ContactsChatResult(handled=True, answer=f"I could not find a contact matching '{query or contact_id}'.")

    action_payload = {
        "update_payload": update_payload,
        "query": query or None,
    }
    if len(candidates) > 1:
        pending = ChatPendingAction(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            action_type=parsed.intent,
            status=PENDING_DISAMBIGUATION,
            account_id=account.id,
            payload_json=action_payload,
            candidates_json=candidates,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        lines = ["I found multiple contacts. Please select one by number:"]
        for idx, item in enumerate(candidates, start=1):
            lines.append(
                f"{idx}. {item.get('display_name') or 'Unnamed'} | "
                f"{item.get('primary_email') or '-'} | id: {item.get('resource_name')}"
            )
        return ContactsChatResult(handled=True, answer="\n".join(lines))

    selected = candidates[0]
    pending = ChatPendingAction(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        action_type=parsed.intent,
        status=PENDING_CONFIRMATION,
        account_id=account.id,
        payload_json={**action_payload, "selected_contact": selected},
        candidates_json=[],
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)

    return ContactsChatResult(
        handled=True,
        answer=_build_mutation_confirmation_prompt(
            action_type=parsed.intent,
            account=account,
            selected_contact=selected,
            update_payload=update_payload,
        ),
    )


def _handle_pending_followup(
    db: Session,
    *,
    pending: ChatPendingAction,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
) -> ContactsChatResult:
    if pending.status == PENDING_DISAMBIGUATION:
        index = _parse_selection(message)
        candidates = pending.candidates_json or []
        if index is None or index < 1 or index > len(candidates):
            return ContactsChatResult(handled=True, answer="Please select one candidate by number (for example: 1).")

        selected = candidates[index - 1]
        payload = dict(pending.payload_json or {})
        payload["selected_contact"] = selected
        pending.payload_json = payload
        pending.status = PENDING_CONFIRMATION
        pending.candidates_json = []
        pending.expires_at = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()
        return ContactsChatResult(
            handled=True,
            answer=_build_mutation_confirmation_prompt(
                action_type=pending.action_type,
                account=_account_stub(selected_email=None),
                selected_contact=selected,
                update_payload=payload.get("update_payload") or {},
            ),
        )

    if pending.status != PENDING_CONFIRMATION:
        return ContactsChatResult(handled=True, answer="I could not continue that contacts action. Please retry.")

    decision = _parse_confirmation(message)
    if decision is None:
        return ContactsChatResult(handled=True, answer="Please confirm with 'yes' to proceed or 'no' to cancel.")
    if decision is False:
        pending.status = CANCELLED
        db.commit()
        return ContactsChatResult(handled=True, answer="Cancelled. I did not change your contacts.")

    account = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.id == pending.account_id,
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.user_id == user_id,
        )
    ).scalar_one_or_none()
    if account is None:
        pending.status = CANCELLED
        db.commit()
        return ContactsChatResult(handled=True, answer="That Google account is no longer available. Please reconnect and try again.")

    payload = dict(pending.payload_json or {})
    try:
        if pending.action_type == INTENT_CREATE:
            created = create_contact(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                payload=dict(payload.get("create_payload") or {}),
            )
            pending.status = COMPLETED
            db.commit()
            audit_event(
                db,
                event_type="chat.contacts.create",
                resource_type="google_contact",
                action="create",
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=created.get("resource_name") or None,
                payload={"conversation_id": conversation_id, "account_id": account.id},
            )
            return ContactsChatResult(
                handled=True,
                answer=f"Contact created: {created.get('display_name') or 'Unnamed'} ({created.get('resource_name')}).",
            )

        selected = dict(payload.get("selected_contact") or {})
        resource_name = str(selected.get("resource_name") or "")
        if not resource_name:
            return ContactsChatResult(handled=True, answer="I could not resolve the selected contact id.")

        if pending.action_type == INTENT_UPDATE:
            updated = update_contact(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                resource_name=resource_name,
                payload=dict(payload.get("update_payload") or {}),
            )
            pending.status = COMPLETED
            db.commit()
            audit_event(
                db,
                event_type="chat.contacts.update",
                resource_type="google_contact",
                action="update",
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=resource_name,
                payload={"conversation_id": conversation_id, "account_id": account.id},
            )
            return ContactsChatResult(
                handled=True,
                answer=f"Contact updated: {updated.get('display_name') or resource_name}.",
            )

        if pending.action_type == INTENT_DELETE:
            delete_contact(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                resource_name=resource_name,
            )
            pending.status = COMPLETED
            db.commit()
            audit_event(
                db,
                event_type="chat.contacts.delete",
                resource_type="google_contact",
                action="delete",
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=resource_name,
                payload={"conversation_id": conversation_id, "account_id": account.id},
            )
            return ContactsChatResult(
                handled=True,
                answer=f"Contact deleted: {selected.get('display_name') or resource_name}.",
            )
    except ValueError as exc:
        return ContactsChatResult(handled=True, answer=f"Google Contacts action failed: {exc}")

    pending.status = CANCELLED
    db.commit()
    return ContactsChatResult(handled=True, answer="Unsupported pending contacts action type.")


def _parse_contacts_intent_llm(
    db: Session,
    *,
    tenant_id: str,
    message: str,
    provider_id_override: str | None,
) -> ParsedContactsIntent | None:
    prompt = (
        "Extract a Google Contacts action from the user command and return ONLY JSON.\n"
        "Allowed intent values: contacts_access, contacts_list, contacts_read, contacts_create, contacts_update, contacts_delete.\n"
        "JSON keys: intent,account_hint,contact_id,target_query,display_name,given_name,family_name,"
        "emails,phones,organizations,biography,confidence.\n"
        "Rules:\n"
        "- Never invent contact ids, emails, or phone numbers.\n"
        "- contact_id must be a people/* resource only if explicitly present.\n"
        "- For list/search phrases default to contacts_list.\n"
        "- For access questions default to contacts_access.\n"
        "- If unknown field, return null or empty string/list.\n"
        f"- Command: {message}"
    )
    try:
        _, result = LLMRouter(db, tenant_id).chat(
            messages=[
                {"role": "system", "content": "You are a strict JSON extraction engine for Google Contacts actions."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            provider_id_override=provider_id_override,
            allow_fallback=False,
        )
    except Exception:
        return None

    parsed = _parse_json_object(str(result.get("answer") or ""))
    if not isinstance(parsed, dict):
        return None

    return ParsedContactsIntent(
        intent=_normalize_intent(str(parsed.get("intent") or "")),
        account_hint=_as_text(parsed.get("account_hint")),
        contact_id=_as_text(parsed.get("contact_id")),
        target_query=_as_text(parsed.get("target_query")),
        display_name=_as_text(parsed.get("display_name")),
        given_name=_as_text(parsed.get("given_name")),
        family_name=_as_text(parsed.get("family_name")),
        emails=_as_string_list(parsed.get("emails")),
        phones=_as_string_list(parsed.get("phones")),
        organizations=_as_string_list(parsed.get("organizations")),
        biography=_as_text(parsed.get("biography")),
        confidence=_coerce_optional_float(parsed.get("confidence")),
    )


def _parse_contacts_intent_fallback(message: str) -> ParsedContactsIntent:
    lowered = message.lower()
    intent = ""
    if re.search(r"\b(access|permission)\b", lowered) and re.search(r"\b(contact|contacts|people)\b", lowered):
        intent = INTENT_ACCESS
    elif re.search(r"\b(create|add)\b", lowered) and re.search(r"\b(contact|person)\b", lowered):
        intent = INTENT_CREATE
    elif re.search(r"\b(update|change|edit)\b", lowered) and re.search(r"\b(contact|person)\b", lowered):
        intent = INTENT_UPDATE
    elif re.search(r"\b(delete|remove)\b", lowered) and re.search(r"\b(contact|person)\b", lowered):
        intent = INTENT_DELETE
    elif re.search(r"\b(read|show|details)\b", lowered) and re.search(r"\b(contact|person)\b", lowered):
        intent = INTENT_READ
    elif re.search(r"\b(list|find|search|show|get)\b", lowered) and re.search(r"\b(contact|contacts|people)\b", lowered):
        intent = INTENT_LIST
    elif _looks_contacts_related(message):
        intent = INTENT_LIST

    resource_match = RESOURCE_NAME_REGEX.search(message)
    target_query = _extract_target_query(message)
    return ParsedContactsIntent(
        intent=intent,
        contact_id=resource_match.group(0) if resource_match else None,
        target_query=target_query,
        display_name=_extract_display_name(message),
        emails=[value.lower() for value in EMAIL_REGEX.findall(message)],
        phones=[_normalize_phone(value) for value in PHONE_REGEX.findall(message)],
    )


def _normalize_and_validate_contacts_intent(
    parsed: ParsedContactsIntent | None,
    *,
    message: str,
) -> ParsedContactsIntent | None:
    if parsed is None:
        return None

    intent = _normalize_intent(parsed.intent)
    if not intent:
        return None

    emails = _normalize_emails(parsed.emails or [])
    phones = _normalize_phones(parsed.phones or [])
    organizations = _normalize_string_list(parsed.organizations or [], max_len=120)

    display_name = _truncate(_strip_prefix(parsed.display_name or ""), 120) or None
    given_name = _truncate(parsed.given_name or "", 80) or None
    family_name = _truncate(parsed.family_name or "", 80) or None
    biography = _truncate(parsed.biography or "", 500) or None

    contact_id = _truncate((parsed.contact_id or "").strip(), 120) or None
    if contact_id and not contact_id.startswith("people/"):
        contact_id = None
    target_query = _truncate((parsed.target_query or "").strip(), 160) or None
    if target_query is None:
        target_query = _extract_target_query(message)

    if intent == INTENT_CREATE:
        if not any([display_name, given_name, family_name, emails, phones, organizations, biography]):
            return None
    if intent in {INTENT_READ, INTENT_UPDATE, INTENT_DELETE} and not contact_id and not target_query:
        return None
    if intent == INTENT_UPDATE and not any([display_name, given_name, family_name, emails, phones, organizations, biography]):
        return None

    return ParsedContactsIntent(
        intent=intent,
        account_hint=_truncate((parsed.account_hint or "").strip(), 160) or None,
        contact_id=contact_id,
        target_query=target_query,
        display_name=display_name,
        given_name=given_name,
        family_name=family_name,
        emails=emails,
        phones=phones,
        organizations=organizations,
        biography=biography,
        confidence=parsed.confidence,
    )


def _resolve_account(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    message: str,
    account_hint: str | None,
) -> GoogleUserConnector | None:
    accounts = [item for item in list_user_accounts(db, tenant_id=tenant_id, user_id=user_id) if item.enabled]
    if not accounts:
        return None

    hint = (account_hint or "").strip().lower()
    if hint:
        for account in accounts:
            label = (account.label or "").strip().lower()
            email = (account.google_account_email or "").strip().lower()
            if hint == label or hint == email:
                return account

    message_tokens = _tokenize(message)
    best: GoogleUserConnector | None = None
    best_score = 0
    for account in accounts:
        label_tokens = _tokenize((account.label or "") + " " + (account.google_account_email or ""))
        overlap = message_tokens.intersection(label_tokens)
        if len(overlap) > best_score:
            best = account
            best_score = len(overlap)
    if best is not None:
        return best

    primary = get_primary_account(db, tenant_id=tenant_id, user_id=user_id)
    if primary and primary.enabled:
        return primary
    return accounts[0]


def _find_contact_candidates(
    db: Session,
    *,
    account: GoogleUserConnector,
    query: str,
    limit: int,
) -> list[dict]:
    try:
        rows = search_contacts(
            db,
            account,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            query=query,
            limit=limit,
        )
    except ValueError:
        return []
    return [_sanitize_candidate(item) for item in rows if str(item.get("resource_name") or "").strip()]


def _sanitize_candidate(value: dict) -> dict:
    return {
        "resource_name": str(value.get("resource_name") or ""),
        "display_name": str(value.get("display_name") or "Unnamed"),
        "primary_email": value.get("primary_email"),
        "primary_phone": value.get("primary_phone"),
    }


def _parse_confirmation(message: str) -> bool | None:
    lowered = message.strip().lower()
    if not lowered:
        return None
    if lowered in YES_TOKENS or any(phrase in lowered for phrase in YES_PHRASES):
        return True
    if lowered in NO_TOKENS or any(phrase in lowered for phrase in NO_PHRASES):
        return False
    return None


def _parse_selection(message: str) -> int | None:
    match = re.search(r"\b(\d{1,2})\b", message)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_create_confirmation_prompt(*, account: GoogleUserConnector, payload: dict) -> str:
    return (
        "Please confirm creating this contact (yes/no):\n"
        f"Account: {account.google_account_email or account.label or account.id}\n"
        f"Name: {payload.get('display_name') or '-'}\n"
        f"Given: {payload.get('given_name') or '-'}\n"
        f"Family: {payload.get('family_name') or '-'}\n"
        f"Emails: {', '.join(payload.get('emails') or []) or '-'}\n"
        f"Phones: {', '.join(payload.get('phones') or []) or '-'}\n"
        f"Organizations: {', '.join(payload.get('organizations') or []) or '-'}\n"
        f"Notes: {payload.get('biography') or '-'}"
    )


def _account_stub(*, selected_email: str | None) -> GoogleUserConnector:
    return GoogleUserConnector(
        tenant_id="",
        user_id="",
        label=None,
        google_account_email=selected_email,
        enabled=True,
    )


def _build_mutation_confirmation_prompt(
    *,
    action_type: str,
    account: GoogleUserConnector,
    selected_contact: dict,
    update_payload: dict,
) -> str:
    display = str(selected_contact.get("display_name") or "Unnamed")
    resource = str(selected_contact.get("resource_name") or "-")
    account_label = account.google_account_email or account.label or "your account"
    if action_type == INTENT_DELETE:
        return (
            "Please confirm deleting this contact (yes/no):\n"
            f"Account: {account_label}\n"
            f"Contact: {display}\n"
            f"ID: {resource}"
        )
    return (
        "Please confirm updating this contact (yes/no):\n"
        f"Account: {account_label}\n"
        f"Contact: {display}\n"
        f"ID: {resource}\n"
        f"New name: {update_payload.get('display_name') or '-'}\n"
        f"New given: {update_payload.get('given_name') or '-'}\n"
        f"New family: {update_payload.get('family_name') or '-'}\n"
        f"New emails: {', '.join(update_payload.get('emails') or []) or '-'}\n"
        f"New phones: {', '.join(update_payload.get('phones') or []) or '-'}\n"
        f"New organizations: {', '.join(update_payload.get('organizations') or []) or '-'}\n"
        f"New notes: {update_payload.get('biography') or '-'}"
    )


def _get_active_pending_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
) -> ChatPendingAction | None:
    return db.execute(
        select(ChatPendingAction)
        .where(
            ChatPendingAction.tenant_id == tenant_id,
            ChatPendingAction.user_id == user_id,
            ChatPendingAction.conversation_id == conversation_id,
            ChatPendingAction.action_type.in_([INTENT_CREATE, INTENT_UPDATE, INTENT_DELETE]),
            ChatPendingAction.status.in_([PENDING_DISAMBIGUATION, PENDING_CONFIRMATION]),
        )
        .order_by(ChatPendingAction.updated_at.desc(), ChatPendingAction.created_at.desc())
    ).scalar_one_or_none()


def _normalize_intent(value: str) -> str:
    raw = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        INTENT_ACCESS: INTENT_ACCESS,
        "access": INTENT_ACCESS,
        INTENT_LIST: INTENT_LIST,
        "list": INTENT_LIST,
        "search": INTENT_LIST,
        "find": INTENT_LIST,
        INTENT_READ: INTENT_READ,
        "read": INTENT_READ,
        "show": INTENT_READ,
        "get": INTENT_READ,
        INTENT_CREATE: INTENT_CREATE,
        "create": INTENT_CREATE,
        "add": INTENT_CREATE,
        INTENT_UPDATE: INTENT_UPDATE,
        "update": INTENT_UPDATE,
        "edit": INTENT_UPDATE,
        "change": INTENT_UPDATE,
        INTENT_DELETE: INTENT_DELETE,
        "delete": INTENT_DELETE,
        "remove": INTENT_DELETE,
    }
    return aliases.get(raw, "")


def _parse_json_object(value: str) -> dict[str, Any] | None:
    text = value.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,\n]+", value) if part.strip()]
    return []


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", (value or "").lower()))


def _normalize_emails(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in values:
        candidate = str(item).strip().lower()
        if not candidate:
            continue
        if not EMAIL_REGEX.fullmatch(candidate):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        output.append(candidate)
    return output


def _normalize_phone(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _normalize_phones(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in values:
        candidate = _normalize_phone(item)
        if not candidate:
            continue
        if not PHONE_REGEX.fullmatch(candidate):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        output.append(candidate)
    return output


def _normalize_string_list(values: list[str], *, max_len: int) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in values:
        candidate = _truncate(str(item).strip(), max_len)
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output


def _extract_target_query(message: str) -> str | None:
    normalized = " ".join(message.split())
    patterns = [
        r"\b(?:find|search|read|show|get|delete|remove|update|change)\s+(?:contact|person|people)\s+(.+)$",
        r"\b(?:contact|person)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip(" .")
        if candidate:
            return _truncate(candidate, 160)
    return None


def _extract_display_name(message: str) -> str | None:
    normalized = " ".join(message.split())
    named = re.search(
        r"\b(?:named|name)\s+(.+?)(?:\s+(?:email|phone|organization|company|notes?)\b|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if named:
        candidate = named.group(1).strip(" .,")
        if candidate:
            return _truncate(candidate, 120)

    create = re.search(
        r"\b(?:add|create)\s+(?:contact|person)\s+(.+?)(?:\s+(?:email|phone|organization|company|notes?)\b|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if create:
        candidate = create.group(1).strip(" .,")
        if candidate:
            return _truncate(candidate, 120)
    return None


def _contact_payload_from_intent(parsed: ParsedContactsIntent) -> dict:
    return {
        "display_name": parsed.display_name,
        "given_name": parsed.given_name,
        "family_name": parsed.family_name,
        "emails": parsed.emails or [],
        "phones": parsed.phones or [],
        "organizations": parsed.organizations or [],
        "biography": parsed.biography,
    }


def _has_contact_create_fields(payload: dict) -> bool:
    return bool(
        payload.get("display_name")
        or payload.get("given_name")
        or payload.get("family_name")
        or payload.get("emails")
        or payload.get("phones")
        or payload.get("organizations")
        or payload.get("biography")
    )


def _has_contact_update_fields(payload: dict) -> bool:
    return _has_contact_create_fields(payload)


def _strip_prefix(value: str) -> str:
    cleaned = value
    patterns = [
        r"^\s*(?:please\s+)?(?:add|create|update|change|delete|remove|find|read|show)\s+",
        r"^\s*(?:contact|person|people)\s+",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _truncate(value: str, limit: int) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _has_contacts_read_scope(account: GoogleUserConnector) -> bool:
    scopes = {str(item).strip() for item in (account.scopes or []) if str(item).strip()}
    return bool(scopes.intersection(CONTACT_READ_SCOPES))


def _has_contacts_write_scope(account: GoogleUserConnector) -> bool:
    scopes = {str(item).strip() for item in (account.scopes or []) if str(item).strip()}
    return CONTACT_WRITE_SCOPE in scopes
