from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_pending_email_action import ChatPendingEmailAction
from app.models.connectors.email_user_connector import EmailUserConnector
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.services.audit import audit_event
from app.services.connectors.email_user_service import list_messages as list_imap_messages
from app.services.connectors.email_user_service import read_message as read_imap_message
from app.services.connectors.email_user_service import send_message as send_imap_message
from app.services.connectors.google_service import (
    get_primary_account,
    list_gmail_messages,
    read_gmail_message,
    send_gmail_message,
)
from app.services.connectors.google_service import (
    list_user_accounts as list_google_accounts,
)

AccountType = Literal["google_gmail", "imap"]
SEND_ACTION = "email_send"
PENDING_CONFIRMATION = "pending_confirmation"
COMPLETED = "completed"
CANCELLED = "cancelled"
EXPIRED = "expired"

EMAIL_REGEX = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.IGNORECASE)
YES_TOKENS = {"yes", "y", "confirm", "confirmed", "okay", "ok"}
NO_TOKENS = {"no", "n", "cancel", "stop"}


@dataclass
class EmailChatResult:
    handled: bool
    answer: str


def maybe_handle_email_chat_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
) -> EmailChatResult | None:
    pending = _get_active_pending_action(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)
    if pending:
        return _handle_pending_followup(
            db,
            pending=pending,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
        )

    intent = _detect_email_intent(message)
    if intent is None:
        return None

    resolved = _resolve_account(db, tenant_id=tenant_id, user_id=user_id, message=message)
    if resolved is None:
        if intent in {"list", "summarize"}:
            return None
        return EmailChatResult(
            handled=True,
            answer=(
                "I could not find a connected email account for your user. "
                "Open /connectors/google or /connectors/email and connect an account first."
            ),
        )

    account_type, account = resolved

    if intent == "list_accounts":
        return _handle_list_accounts(db, tenant_id=tenant_id, user_id=user_id)
    if intent == "send":
        return _handle_send_request(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_type=account_type,
            account=account,
            message=message,
        )
    if intent == "read":
        return _handle_read_request(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_type=account_type,
            account=account,
            message=message,
        )
    if intent in {"list", "summarize"}:
        return _handle_list_or_summarize(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_type=account_type,
            account=account,
            message=message,
            summarize=intent == "summarize",
        )
    return None


def _handle_list_accounts(db: Session, *, tenant_id: str, user_id: str) -> EmailChatResult:
    google_accounts = [
        account for account in list_google_accounts(db, tenant_id=tenant_id, user_id=user_id) if account.enabled
    ]
    imap_accounts = db.execute(
        select(EmailUserConnector)
        .where(
            EmailUserConnector.tenant_id == tenant_id,
            EmailUserConnector.user_id == user_id,
            EmailUserConnector.enabled.is_(True),
        )
        .order_by(EmailUserConnector.created_at.asc())
    ).scalars().all()

    if not google_accounts and not imap_accounts:
        return EmailChatResult(
            handled=True,
            answer="No email accounts are connected for your user yet.",
        )

    lines = ["Here are your connected email accounts:"]
    index = 1
    for account in google_accounts:
        label = account.label or account.google_account_email or "Google account"
        suffix = " (primary)" if account.is_primary else ""
        status = "connected" if account.access_token_encrypted else "not connected"
        lines.append(f"{index}. Gmail - {label}{suffix} - {status}")
        index += 1
    for account in imap_accounts:
        label = account.label or account.email_address
        suffix = " (primary)" if account.is_primary else ""
        lines.append(f"{index}. IMAP - {label}{suffix}")
        index += 1

    return EmailChatResult(handled=True, answer="\n".join(lines))


def _handle_list_or_summarize(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    message: str,
    summarize: bool,
) -> EmailChatResult:
    count = _extract_recent_count(message)
    query = _extract_query_phrase(message)
    try:
        messages = _list_account_messages(db, account_type=account_type, account=account, limit=count, query=query)
    except ValueError as exc:
        return EmailChatResult(handled=True, answer=f"Email lookup failed: {exc}")

    if not messages:
        return EmailChatResult(handled=True, answer="No matching emails were found.")

    audit_event(
        db,
        event_type="chat.email.summarize" if summarize else "chat.email.list",
        resource_type="email_account",
        action="read",
        tenant_id=tenant_id,
        user_id=user_id,
        payload={
            "account_type": account_type,
            "account_id": account.id,
            "conversation_id": conversation_id,
            "count": len(messages),
        },
    )

    if summarize:
        lines = [f"I found {len(messages)} recent emails:"]
        for idx, item in enumerate(messages, start=1):
            lines.append(
                f"{idx}. {item.get('subject') or '(No Subject)'} from {item.get('from') or 'unknown sender'} "
                f"at {item.get('sent_at') or 'unknown time'}"
            )
            snippet = str(item.get("snippet") or "").strip()
            if snippet:
                lines.append(f"   Summary: {snippet[:200]}")
        return EmailChatResult(handled=True, answer="\n".join(lines))

    lines = ["Here are the emails I found:"]
    for idx, item in enumerate(messages, start=1):
        lines.append(
            f"{idx}. [{item.get('id')}] {item.get('subject') or '(No Subject)'} "
            f"from {item.get('from') or 'unknown sender'} at {item.get('sent_at') or 'unknown time'}"
        )
    return EmailChatResult(handled=True, answer="\n".join(lines))


def _handle_read_request(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    message: str,
) -> EmailChatResult:
    message_id = _extract_message_id(message)
    if not message_id:
        return EmailChatResult(
            handled=True,
            answer="Please provide the email id to read. Example: 'read email id <id>'.",
        )

    try:
        row = _read_account_message(db, account_type=account_type, account=account, message_id=message_id)
    except ValueError as exc:
        return EmailChatResult(handled=True, answer=f"Email read failed: {exc}")

    if not row:
        return EmailChatResult(handled=True, answer="I could not find that email message id.")

    audit_event(
        db,
        event_type="chat.email.read",
        resource_type="email_account",
        action="read",
        tenant_id=tenant_id,
        user_id=user_id,
        payload={
            "account_type": account_type,
            "account_id": account.id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        },
    )

    lines = [
        f"Subject: {row.get('subject') or '(No Subject)'}",
        f"From: {row.get('from') or 'unknown'}",
        f"To: {row.get('to') or 'unknown'}",
        f"Date: {row.get('date') or row.get('sent_at') or 'unknown'}",
        "",
        str(row.get("body") or row.get("snippet") or "").strip()[:4000],
    ]
    return EmailChatResult(handled=True, answer="\n".join(lines).strip())


def _handle_send_request(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    message: str,
) -> EmailChatResult:
    parsed = _parse_send_request(message)
    missing: list[str] = []
    if not parsed["to"]:
        missing.append("recipient email")
    if not parsed["body"]:
        missing.append("email body")

    if missing:
        return EmailChatResult(
            handled=True,
            answer=f"I can send the email, but I still need: {', '.join(missing)}.",
        )

    pending = _replace_pending_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        account_type=account_type,
        account_id=account.id,
        payload_json=parsed,
    )

    audit_event(
        db,
        event_type="chat.email.send_pending",
        resource_type="chat_pending_email_action",
        action="create",
        tenant_id=tenant_id,
        user_id=user_id,
        resource_id=pending.id,
        payload={
            "account_type": account_type,
            "account_id": account.id,
            "conversation_id": conversation_id,
            "to_count": len(parsed["to"]),
            "cc_count": len(parsed["cc"]),
            "bcc_count": len(parsed["bcc"]),
        },
    )

    account_label = _account_display_label(account_type, account)
    return EmailChatResult(
        handled=True,
        answer=(
            "Please confirm sending this email (yes/no):\n"
            f"Account: {account_label}\n"
            f"To: {', '.join(parsed['to'])}\n"
            f"Cc: {', '.join(parsed['cc']) or '-'}\n"
            f"Bcc: {', '.join(parsed['bcc']) or '-'}\n"
            f"Subject: {parsed['subject']}\n"
            f"Body preview: {parsed['body'][:240]}"
        ),
    )


def _handle_pending_followup(
    db: Session,
    *,
    pending: ChatPendingEmailAction,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
) -> EmailChatResult:
    now = datetime.now(UTC)
    if _coerce_utc(pending.expires_at) < now:
        pending.status = EXPIRED
        db.commit()
        audit_event(
            db,
            event_type="chat.email.send_expired",
            resource_type="chat_pending_email_action",
            action="expire",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=pending.id,
            payload={"conversation_id": conversation_id},
        )
        return EmailChatResult(handled=True, answer="That pending email send request expired. Please compose it again.")

    decision = _parse_confirmation(message)
    if decision is None:
        return EmailChatResult(handled=True, answer="Please reply 'yes' to send or 'no' to cancel.")

    if decision is False:
        pending.status = CANCELLED
        db.commit()
        audit_event(
            db,
            event_type="chat.email.send_cancelled",
            resource_type="chat_pending_email_action",
            action="cancel",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=pending.id,
            payload={"conversation_id": conversation_id},
        )
        return EmailChatResult(handled=True, answer="Cancelled. I did not send the email.")

    parsed = dict(pending.payload_json or {})
    account_type = str(pending.account_type)
    try:
        account = _get_account_by_pending(db, tenant_id=tenant_id, user_id=user_id, pending=pending)
    except ValueError as exc:
        pending.status = CANCELLED
        db.commit()
        return EmailChatResult(handled=True, answer=str(exc))

    try:
        send_result = _send_with_account(
            db,
            account_type=account_type,  # type: ignore[arg-type]
            account=account,
            to=list(parsed.get("to") or []),
            cc=list(parsed.get("cc") or []),
            bcc=list(parsed.get("bcc") or []),
            subject=str(parsed.get("subject") or "(No subject)"),
            body=str(parsed.get("body") or ""),
        )
    except ValueError as exc:
        pending.status = CANCELLED
        db.commit()
        audit_event(
            db,
            event_type="chat.email.send_failed",
            resource_type="chat_pending_email_action",
            action="fail",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=pending.id,
            payload={"conversation_id": conversation_id, "error": str(exc)},
        )
        return EmailChatResult(handled=True, answer=f"Email send failed: {exc}")

    pending.status = COMPLETED
    db.commit()
    audit_event(
        db,
        event_type="chat.email.send",
        resource_type="email_account",
        action="send",
        tenant_id=tenant_id,
        user_id=user_id,
        payload={
            "account_type": account_type,
            "account_id": pending.account_id,
            "conversation_id": conversation_id,
            "to_count": len(parsed.get("to") or []),
            "provider_message_id": send_result.get("provider_message_id") or send_result.get("id"),
        },
    )
    return EmailChatResult(handled=True, answer="Email sent successfully.")


def _replace_pending_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_type: AccountType,
    account_id: str,
    payload_json: dict,
) -> ChatPendingEmailAction:
    active = _get_active_pending_action(db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)
    if active:
        active.status = CANCELLED

    pending = ChatPendingEmailAction(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        account_type=account_type,
        account_id=account_id,
        status=PENDING_CONFIRMATION,
        payload_json=payload_json,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    return pending


def _get_active_pending_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
) -> ChatPendingEmailAction | None:
    return db.execute(
        select(ChatPendingEmailAction)
        .where(
            ChatPendingEmailAction.tenant_id == tenant_id,
            ChatPendingEmailAction.user_id == user_id,
            ChatPendingEmailAction.conversation_id == conversation_id,
            ChatPendingEmailAction.status == PENDING_CONFIRMATION,
        )
        .order_by(ChatPendingEmailAction.created_at.desc())
    ).scalars().first()


def _resolve_account(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    message: str,
) -> tuple[AccountType, GoogleUserConnector | EmailUserConnector] | None:
    lowered = message.lower()
    google_accounts = [
        account
        for account in list_google_accounts(db, tenant_id=tenant_id, user_id=user_id)
        if account.enabled and account.access_token_encrypted
    ]
    imap_accounts = db.execute(
        select(EmailUserConnector)
        .where(
            EmailUserConnector.tenant_id == tenant_id,
            EmailUserConnector.user_id == user_id,
            EmailUserConnector.enabled.is_(True),
        )
        .order_by(EmailUserConnector.created_at.asc())
    ).scalars().all()

    for account in google_accounts:
        for value in [account.google_account_email or "", account.label or ""]:
            candidate = value.strip().lower()
            if candidate and candidate in lowered:
                return "google_gmail", account

    for account in imap_accounts:
        for value in [account.email_address, account.label or ""]:
            candidate = value.strip().lower()
            if candidate and candidate in lowered:
                return "imap", account

    if "gmail" in lowered or "google" in lowered:
        primary = get_primary_account(db, tenant_id=tenant_id, user_id=user_id)
        if primary and primary.enabled and primary.access_token_encrypted:
            return "google_gmail", primary
        if google_accounts:
            return "google_gmail", google_accounts[0]

    if "imap" in lowered or "smtp" in lowered:
        primary_imap = next((account for account in imap_accounts if account.is_primary), None)
        if primary_imap:
            return "imap", primary_imap
        if imap_accounts:
            return "imap", imap_accounts[0]

    primary_google = get_primary_account(db, tenant_id=tenant_id, user_id=user_id)
    if primary_google and primary_google.enabled and primary_google.access_token_encrypted:
        return "google_gmail", primary_google
    if google_accounts:
        return "google_gmail", google_accounts[0]

    primary_imap = next((account for account in imap_accounts if account.is_primary), None)
    if primary_imap:
        return "imap", primary_imap
    if imap_accounts:
        return "imap", imap_accounts[0]
    return None


def _list_account_messages(
    db: Session,
    *,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    limit: int,
    query: str | None,
) -> list[dict]:
    if account_type == "google_gmail":
        if not settings.google_client_id or not settings.google_client_secret:
            raise ValueError("Google OAuth credentials are not configured on the server")
        return list_gmail_messages(
            db,
            account,  # type: ignore[arg-type]
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            limit=limit,
            query=query,
        )
    return list_imap_messages(
        account,  # type: ignore[arg-type]
        limit=limit,
        query=query,
    )


def _read_account_message(
    db: Session,
    *,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    message_id: str,
) -> dict | None:
    if account_type == "google_gmail":
        if not settings.google_client_id or not settings.google_client_secret:
            raise ValueError("Google OAuth credentials are not configured on the server")
        return read_gmail_message(
            db,
            account,  # type: ignore[arg-type]
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            message_id=message_id,
        )
    return read_imap_message(
        account,  # type: ignore[arg-type]
        message_id=message_id,
    )


def _send_with_account(
    db: Session,
    *,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body: str,
) -> dict:
    if account_type == "google_gmail":
        if not settings.google_client_id or not settings.google_client_secret:
            raise ValueError("Google OAuth credentials are not configured on the server")
        return send_gmail_message(
            db,
            account,  # type: ignore[arg-type]
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            to=to,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body=body,
        )
    return send_imap_message(
        account,  # type: ignore[arg-type]
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
    )


def _detect_email_intent(message: str) -> Literal["list_accounts", "send", "list", "read", "summarize"] | None:
    lowered = message.lower()
    if re.search(r"\b(list|show|what)\b", lowered) and re.search(r"\bconnected\b", lowered) and re.search(
        r"\b(email accounts?|mail accounts?)\b", lowered
    ):
        return "list_accounts"
    if re.search(r"\b(send|email)\b", lowered) and EMAIL_REGEX.search(lowered):
        return "send"
    if re.search(r"\bread\b", lowered) and re.search(r"\bemail\b", lowered):
        return "read"
    if re.search(r"\bsummarize\b", lowered) and re.search(r"\bemails?\b", lowered):
        return "summarize"
    if re.search(r"\b(list|show|find|get)\b", lowered) and re.search(r"\bemails?\b", lowered):
        return "list"
    return None


def _extract_recent_count(message: str) -> int:
    match = re.search(r"\b(?:last|latest|recent)\s+(\d{1,2})\s+emails?\b", message.lower())
    if not match:
        return 10
    try:
        return max(1, min(int(match.group(1)), 50))
    except ValueError:
        return 10


def _extract_query_phrase(message: str) -> str | None:
    match = re.search(r"\babout\s+(.+)$", message, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _extract_message_id(message: str) -> str | None:
    match = re.search(r"\bid\s+([a-zA-Z0-9:_\-]+)\b", message)
    if match:
        return match.group(1)
    return None


def _parse_send_request(message: str) -> dict:
    recipients = sorted(set(EMAIL_REGEX.findall(message)))

    subject = "(No subject)"
    subject_match = re.search(r"\bsubject\s*[:=]\s*([^\n]+)", message, flags=re.IGNORECASE)
    if subject_match:
        subject = subject_match.group(1).strip()
    else:
        about_match = re.search(r"\babout\s+([^\n]+)", message, flags=re.IGNORECASE)
        if about_match:
            subject = about_match.group(1).strip()[:160]

    body_match = re.search(r"\bbody\s*[:=]\s*(.+)$", message, flags=re.IGNORECASE | re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()
    else:
        cleaned = EMAIL_REGEX.sub(" ", message)
        cleaned = re.sub(r"\b(send|email|to|cc|bcc|subject|about)\b", " ", cleaned, flags=re.IGNORECASE)
        body = " ".join(cleaned.split()).strip()

    return {
        "to": recipients,
        "cc": [],
        "bcc": [],
        "subject": subject[:240],
        "body": body,
    }


def _parse_confirmation(message: str) -> bool | None:
    tokens = {token for token in re.findall(r"[a-z0-9_]+", message.lower())}
    if tokens.intersection(YES_TOKENS):
        return True
    if tokens.intersection(NO_TOKENS):
        return False
    return None


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _get_account_by_pending(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    pending: ChatPendingEmailAction,
) -> GoogleUserConnector | EmailUserConnector:
    if pending.account_type == "google_gmail":
        account = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.id == pending.account_id,
                GoogleUserConnector.tenant_id == tenant_id,
                GoogleUserConnector.user_id == user_id,
            )
        ).scalar_one_or_none()
    else:
        account = db.execute(
            select(EmailUserConnector).where(
                EmailUserConnector.id == pending.account_id,
                EmailUserConnector.tenant_id == tenant_id,
                EmailUserConnector.user_id == user_id,
            )
        ).scalar_one_or_none()

    if account is None:
        raise ValueError("The selected email account is no longer available.")
    return account


def _account_display_label(account_type: AccountType, account: GoogleUserConnector | EmailUserConnector) -> str:
    if account_type == "google_gmail":
        return account.google_account_email or account.label or "Google account"  # type: ignore[attr-defined]
    return account.email_address or account.label or "IMAP account"  # type: ignore[attr-defined]
