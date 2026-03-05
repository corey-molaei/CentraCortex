from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_pending_email_action import ChatPendingEmailAction
from app.models.connectors.email_user_connector import EmailUserConnector
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.workspace_settings import WorkspaceSettings
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
from app.services.llm_router import LLMRouter

AccountType = Literal["google_gmail", "imap"]
EmailIntent = Literal["list_accounts", "send", "list", "read", "summarize", "access", "help", "none"]
EmailTimeScope = Literal["today", "yesterday", "last_n_days", "none"]
SEND_ACTION = "email_send"
PENDING_CONFIRMATION = "pending_confirmation"
COMPLETED = "completed"
CANCELLED = "cancelled"
EXPIRED = "expired"

EMAIL_REGEX = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.IGNORECASE)
YES_TOKENS = {"yes", "y", "confirm", "confirmed", "okay", "ok"}
NO_TOKENS = {"no", "n", "cancel", "stop"}
MAX_SUMMARY_TOPICS = 5
EMAIL_VALUE_REGEX = re.compile(r"^[\w.\-+]+@[\w.\-]+\.\w+$", re.IGNORECASE)
COMMAND_PREFIX_PATTERNS = [
    r"^\s*(?:please\s+)?say\s+",
    r"^\s*(?:please\s+)?saying\s+",
    r"^\s*(?:please\s+)?tell(?:\s+them|\s+him|\s+her)?\s+",
    r"^\s*(?:please\s+)?send(?:\s+this)?\s+",
    r"^\s*(?:please\s+)?email(?:\s+them|\s+him|\s+her)?\s+",
]

logger = structlog.get_logger(__name__)


@dataclass
class EmailChatResult:
    handled: bool
    answer: str


@dataclass
class ParsedSendDraft:
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    body: str
    inferred_subject: bool
    cleanup_notes: list[str]


@dataclass
class ParsedEmailIntent:
    intent: EmailIntent
    account_hint: str | None = None
    message_id: str | None = None
    query: str | None = None
    limit: int | None = None
    time_scope: EmailTimeScope = "none"
    days: int | None = None
    confidence: float | None = None
    raw_reason: str | None = None


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


def maybe_handle_email_chat_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    client_timezone: str | None = None,
    client_now_iso: str | None = None,
    provider_id_override: str | None = None,
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

    if not _looks_email_related(message) and not _looks_connected_accounts_prompt(message):
        return None

    parsed_intent = _parse_email_intent_llm(
        db,
        tenant_id=tenant_id,
        message=message,
        client_timezone=client_timezone,
        client_now_iso=client_now_iso,
        provider_id_override=provider_id_override,
    )
    fallback_used = False
    if parsed_intent is None:
        parsed_intent = _parse_email_intent_fallback(message)
        fallback_used = True

    parsed_intent = _normalize_and_validate_email_intent(parsed_intent, message=message)

    logger.debug(
        "email_intent_parse_result",
        tenant_id=tenant_id,
        user_id=user_id,
        intent=(parsed_intent.intent if parsed_intent else None),
        time_scope=(parsed_intent.time_scope if parsed_intent else None),
        limit=(parsed_intent.limit if parsed_intent else None),
        account_hint=(parsed_intent.account_hint if parsed_intent else None),
        parser_fallback_used=fallback_used,
    )
    if fallback_used:
        logger.debug("email_intent_fallback_used", tenant_id=tenant_id, user_id=user_id)

    if parsed_intent is None:
        return EmailChatResult(handled=True, answer=_email_help_response())

    intent = parsed_intent.intent
    if intent in {"help", "none"}:
        return EmailChatResult(handled=True, answer=_email_help_response())
    if intent == "list_accounts":
        return _handle_list_accounts(db, tenant_id=tenant_id, user_id=user_id)

    resolved = _resolve_account(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        message=message,
        account_hint=parsed_intent.account_hint,
    )
    if resolved is None:
        return EmailChatResult(handled=True, answer=_missing_account_guidance())

    account_type, account = resolved

    if intent == "access":
        return _handle_access_status(account_type=account_type, account=account)
    if intent == "send":
        if not _workspace_action_enabled(db, tenant_id=tenant_id, action_key="email_send"):
            return EmailChatResult(
                handled=True,
                answer="Email sending is disabled for this workspace by policy. Enable it in Workspace Settings.",
            )
        return _handle_send_request(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_type=account_type,
            account=account,
            message=message,
            provider_id_override=provider_id_override,
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
            message_id_override=parsed_intent.message_id,
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
            parsed_intent=parsed_intent,
            client_timezone=client_timezone,
            client_now_iso=client_now_iso,
        )
    return None


def _missing_account_guidance() -> str:
    return (
        "I could not find a connected email account for your user. "
        "Open /connectors/google or /connectors/email to connect an account first."
    )


def _email_help_response() -> str:
    return (
        "I can help with email actions, but I need a clearer command.\n"
        "Examples:\n"
        "- today's emails\n"
        "- summarize my last 5 emails\n"
        "- summarise my last 5 emails\n"
        "- list my recent emails about payroll\n"
        "- read email id <message-id>\n"
        "- send email to bob@example.com about update body: done\n"
        "Note: sending always requires your confirmation."
    )


def _looks_email_related(message: str) -> bool:
    if EMAIL_REGEX.search(message):
        return True
    tokens = set(re.findall(r"[a-z0-9_]+", message.lower()))
    return bool(
        tokens.intersection(
            {
                "email",
                "emails",
                "mail",
                "mails",
                "inbox",
                "gmail",
                "imap",
                "smtp",
                "sent",
            }
        )
    )


def _looks_connected_accounts_prompt(message: str) -> bool:
    lowered = message.lower()
    return bool(
        re.search(r"\b(list|show|what)\b", lowered)
        and re.search(r"\bconnected\b", lowered)
        and re.search(r"\b(email accounts?|mail accounts?)\b", lowered)
    )


def _handle_access_status(
    *,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
) -> EmailChatResult:
    account_label = _account_display_label(account_type, account)
    if account_type == "google_gmail":
        enabled = bool(account.enabled)
        token_ready = bool(account.access_token_encrypted)
        gmail_enabled = bool(account.gmail_enabled)
        ready = enabled and token_ready and gmail_enabled

        if ready:
            return EmailChatResult(
                handled=True,
                answer=(
                    f"Yes, I can access your inbox for {account_label}.\n"
                    "Source: Gmail.\n"
                    "Status: connector enabled, OAuth connected, Gmail enabled.\n"
                    "Capabilities: list/read/summarize emails, and send emails with confirmation."
                ),
            )

        issues: list[str] = []
        if not enabled:
            issues.append("connector is disabled")
        if not token_ready:
            issues.append("OAuth token is not connected")
        if not gmail_enabled:
            issues.append("Gmail access is disabled")
        issue_text = ", ".join(issues) if issues else "connector is not ready"
        return EmailChatResult(
            handled=True,
            answer=(
                f"I found your Gmail account {account_label}, but inbox access is not ready: {issue_text}. "
                "Reconnect/enable it in /connectors/google."
            ),
        )

    enabled = bool(account.enabled)
    creds_ready = bool(account.username and account.password_encrypted and account.imap_host and account.imap_port)
    folder_ready = bool(account.folders)
    smtp_ready = bool(account.smtp_host and account.smtp_port)
    ready = enabled and creds_ready and folder_ready

    if ready:
        send_capability = "send enabled (confirmation required)" if smtp_ready else "send unavailable (SMTP not configured)"
        return EmailChatResult(
            handled=True,
            answer=(
                f"Yes, I can access your inbox for {account_label}.\n"
                "Source: IMAP.\n"
                "Status: connector enabled, IMAP credentials configured, folders configured.\n"
                f"Capabilities: list/read/summarize emails, {send_capability}."
            ),
        )

    issues = []
    if not enabled:
        issues.append("connector is disabled")
    if not creds_ready:
        issues.append("IMAP credentials are incomplete")
    if not folder_ready:
        issues.append("folders are not configured")
    issue_text = ", ".join(issues) if issues else "connector is not ready"
    return EmailChatResult(
        handled=True,
        answer=(
            f"I found your IMAP account {account_label}, but inbox access is not ready: {issue_text}. "
            "Update and enable it in /connectors/email."
        ),
    )


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
    parsed_intent: ParsedEmailIntent | None = None,
    client_timezone: str | None = None,
    client_now_iso: str | None = None,
) -> EmailChatResult:
    count = parsed_intent.limit if parsed_intent and parsed_intent.limit is not None else _extract_recent_count(message)
    query = parsed_intent.query if parsed_intent and parsed_intent.query is not None else _extract_query_phrase(message)
    time_scope = parsed_intent.time_scope if parsed_intent is not None else "none"
    time_scope_days = parsed_intent.days if parsed_intent is not None else None
    fetch_limit = count
    if time_scope != "none":
        fetch_limit = min(max(count * 5, 50), 200)
    try:
        messages = _list_account_messages(
            db,
            account_type=account_type,
            account=account,
            limit=fetch_limit,
            query=query,
        )
    except ValueError as exc:
        return EmailChatResult(handled=True, answer=f"Email lookup failed: {exc}")

    if time_scope != "none":
        messages = _apply_time_scope_filter(
            messages,
            time_scope=time_scope,
            days=time_scope_days,
            limit=count,
            timezone_name=_safe_timezone(client_timezone),
            client_now_iso=client_now_iso,
        )
    else:
        messages = messages[:count]

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
        return EmailChatResult(handled=True, answer=_render_sender_group_summary(messages))

    lines = ["Here are the emails I found:"]
    for idx, item in enumerate(messages, start=1):
        lines.append(
            f"{idx}. [{item.get('id')}] {item.get('subject') or '(No Subject)'} "
            f"from {item.get('from') or 'unknown sender'} at {item.get('sent_at') or 'unknown time'}"
        )
    return EmailChatResult(handled=True, answer="\n".join(lines))


def _render_sender_group_summary(messages: list[dict]) -> str:
    groups = _group_messages_by_sender(messages)
    lines = [f"I found {len(messages)} recent emails across {len(groups)} sender groups:"]
    for idx, group in enumerate(groups, start=1):
        lines.append(
            f"{idx}. {group['sender_label']} - {group['total_count']} emails - latest: {group['latest_sent_at']}"
        )
        lines.append(f"   Summary: {group['group_summary']}")
        topics = group["topics"]
        if len(topics) <= 1:
            continue
        for topic in topics[:MAX_SUMMARY_TOPICS]:
            lines.append(f"   - {topic['label']} ({topic['count']}): {topic['summary']}")
        remaining = len(topics) - MAX_SUMMARY_TOPICS
        if remaining > 0:
            lines.append(f"   - ... and {remaining} more topics")
    return "\n".join(lines)


def _group_messages_by_sender(messages: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for item in messages:
        sender_label = _normalize_sender_label(item.get("from"))
        sender_key = sender_label.lower()
        sender_group = grouped.get(sender_key)
        if sender_group is None:
            sender_group = {
                "sender_label": sender_label,
                "total_count": 0,
                "latest_sent_at": "unknown time",
                "latest_sort": datetime.min.replace(tzinfo=UTC),
                "topics": {},
            }
            grouped[sender_key] = sender_group

        sender_group["total_count"] += 1
        sent_at_text = _as_text(item.get("sent_at"), default="unknown time")
        sent_sort = _parse_sent_at(sent_at_text)
        if sent_sort > sender_group["latest_sort"]:
            sender_group["latest_sort"] = sent_sort
            sender_group["latest_sent_at"] = sent_at_text

        topic_key, topic_label, topic_summary = _topic_signature(item)
        topic = sender_group["topics"].get(topic_key)
        if topic is None:
            topic = {
                "label": topic_label,
                "summary": topic_summary,
                "count": 0,
                "latest_sort": datetime.min.replace(tzinfo=UTC),
            }
            sender_group["topics"][topic_key] = topic
        topic["count"] += 1
        if sent_sort > topic["latest_sort"]:
            topic["latest_sort"] = sent_sort
            if topic_summary != "(No preview)":
                topic["summary"] = topic_summary

    results: list[dict] = []
    for sender_group in grouped.values():
        sorted_topics = sorted(
            sender_group["topics"].values(),
            key=lambda item: (int(item["count"]), item["latest_sort"]),
            reverse=True,
        )
        unique_summaries: list[str] = []
        for topic in sorted_topics:
            summary = _as_text(topic.get("summary"), default="")
            if summary and summary != "(No preview)" and summary not in unique_summaries:
                unique_summaries.append(summary)
        group_summary = "; ".join(unique_summaries[:2]) if unique_summaries else "No preview available."
        results.append(
            {
                "sender_label": sender_group["sender_label"],
                "total_count": sender_group["total_count"],
                "latest_sent_at": sender_group["latest_sent_at"],
                "group_summary": group_summary,
                "topics": [
                    {
                        "label": _as_text(topic.get("label"), default="(No Subject)"),
                        "summary": _as_text(topic.get("summary"), default="(No preview)"),
                        "count": int(topic["count"]),
                    }
                    for topic in sorted_topics
                ],
                "latest_sort": sender_group["latest_sort"],
            }
        )

    results.sort(key=lambda item: item["latest_sort"], reverse=True)
    for item in results:
        item.pop("latest_sort", None)
    return results


def _topic_signature(item: dict) -> tuple[str, str, str]:
    subject_raw = _as_text(item.get("subject"), default="(No Subject)")
    snippet_raw = _as_text(item.get("snippet"), default="")
    if not snippet_raw:
        snippet_raw = _as_text(item.get("body"), default="")

    subject_norm = _normalize_topic_text(subject_raw)
    snippet_norm = _normalize_topic_text(snippet_raw)

    label = subject_raw if subject_raw else "(No Subject)"
    summary = _truncate(snippet_raw, 140) if snippet_raw else "(No preview)"

    if not subject_norm and not snippet_norm:
        fallback = _as_text(item.get("id"), default="unknown-id").lower()
        return f"id:{fallback}", label, summary

    signature = f"{subject_norm}|{snippet_norm[:120]}"
    return signature, label, summary


def _normalize_sender_label(value: object) -> str:
    raw = _as_text(value, default="unknown sender")
    match = EMAIL_REGEX.search(raw)
    if match:
        return match.group(0).lower()
    return raw.lower()


def _normalize_topic_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _truncate(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _parse_sent_at(value: str) -> datetime:
    text = value.strip()
    if not text:
        return datetime.min.replace(tzinfo=UTC)
    candidate = text
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_timezone(value: str | None) -> str:
    if not value:
        return "UTC"
    candidate = value.strip()
    if not candidate:
        return "UTC"
    try:
        ZoneInfo(candidate)
    except Exception:
        return "UTC"
    return candidate


def _resolve_time_anchor(*, timezone_name: str, client_now_iso: str | None) -> datetime:
    tz = ZoneInfo(timezone_name)
    if client_now_iso:
        normalized = client_now_iso.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return parsed.astimezone(tz)
        except ValueError:
            pass
    return datetime.now(tz)


def _apply_time_scope_filter(
    messages: list[dict],
    *,
    time_scope: EmailTimeScope,
    days: int | None,
    limit: int,
    timezone_name: str,
    client_now_iso: str | None,
) -> list[dict]:
    if time_scope == "none":
        return messages[:limit]

    anchor = _resolve_time_anchor(timezone_name=timezone_name, client_now_iso=client_now_iso)
    tz = ZoneInfo(timezone_name)
    anchor_local = anchor.astimezone(tz)
    start_of_today = anchor_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_scope == "today":
        start = start_of_today
        end = anchor_local
    elif time_scope == "yesterday":
        start = start_of_today - timedelta(days=1)
        end = start_of_today
    else:
        days_value = max(1, min(days or 7, 30))
        start = (start_of_today - timedelta(days=days_value - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = anchor_local

    filtered: list[dict] = []
    for item in messages:
        sent_at = _parse_sent_at(_as_text(item.get("sent_at"), default=""))
        local_sent = sent_at.astimezone(tz)
        if start <= local_sent <= end:
            filtered.append(item)

    logger.debug(
        "email_time_scope_applied",
        time_scope=time_scope,
        days=days,
        timezone=timezone_name,
        input_count=len(messages),
        output_count=len(filtered),
        start=start.isoformat(),
        end=end.isoformat(),
    )

    return filtered[:limit]


def _as_text(value: object, *, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _handle_read_request(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_type: AccountType,
    account: GoogleUserConnector | EmailUserConnector,
    message: str,
    message_id_override: str | None = None,
) -> EmailChatResult:
    message_id = message_id_override or _extract_message_id(message)
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
    provider_id_override: str | None = None,
) -> EmailChatResult:
    llm_draft = _parse_send_request_llm(
        db,
        tenant_id=tenant_id,
        message=message,
        provider_id_override=provider_id_override,
    )
    parsed = _normalize_and_validate_send_draft(
        llm_draft if llm_draft is not None else _parse_send_request(message),
        message=message,
    )
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
    inferred_subject_note = (
        "\nSubject was auto-generated from your message." if bool(parsed.get("inferred_subject")) else ""
    )
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
            f"{inferred_subject_note}"
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
    account_hint: str | None = None,
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

    hint = (account_hint or "").strip().lower()
    if hint:
        for account in google_accounts:
            for value in [account.google_account_email or "", account.label or ""]:
                candidate = value.strip().lower()
                if candidate and (hint == candidate or hint in candidate or candidate in hint):
                    return "google_gmail", account
        for account in imap_accounts:
            for value in [account.email_address, account.label or ""]:
                candidate = value.strip().lower()
                if candidate and (hint == candidate or hint in candidate or candidate in hint):
                    return "imap", account

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


def _parse_email_intent_llm(
    db: Session,
    *,
    tenant_id: str,
    message: str,
    client_timezone: str | None,
    client_now_iso: str | None,
    provider_id_override: str | None = None,
) -> ParsedEmailIntent | None:
    if not settings.email_tool_llm_intent_parser_enabled:
        return None

    timezone_name = _safe_timezone(client_timezone)
    anchor = _resolve_time_anchor(timezone_name=timezone_name, client_now_iso=client_now_iso)
    prompt = (
        "Extract email action intent from the user command.\n"
        "Return ONLY valid JSON with keys: intent, account_hint, message_id, query, limit, time_scope, days, "
        "confidence, raw_reason.\n"
        "Allowed intent values: list_accounts, access, list, summarize, read, send, help, none.\n"
        "Allowed time_scope values: today, yesterday, last_n_days, none.\n"
        "Rules:\n"
        "- Prefer intent=list for ambiguous mailbox requests.\n"
        "- Recognize natural phrases like 'today's emails' and map to list + time_scope=today.\n"
        "- Do not fabricate message IDs, account IDs, or addresses not present in user text.\n"
        "- Only set message_id for read intent when explicit.\n"
        f"- Current datetime anchor: {anchor.isoformat()} ({timezone_name}).\n"
        f"- Keep output concise (under about {settings.email_tool_llm_intent_parser_max_tokens} tokens).\n"
        f"User command: {message}"
    )

    try:
        _, result = LLMRouter(db, tenant_id).chat(
            messages=[
                {"role": "system", "content": "You are a strict JSON extraction engine."},
                {"role": "user", "content": prompt},
            ],
            temperature=settings.email_tool_llm_intent_parser_temperature,
            provider_id_override=provider_id_override,
            allow_fallback=False,
        )
    except Exception:
        return None

    parsed = _parse_json_object(result.get("answer", ""))
    if not isinstance(parsed, dict):
        return None

    intent_raw = parsed.get("intent")
    if intent_raw is None:
        return None
    intent_value = str(intent_raw).strip().lower()
    if not intent_value:
        return None
    return ParsedEmailIntent(
        intent=intent_value if intent_value else "none",  # type: ignore[arg-type]
        account_hint=_as_text(parsed.get("account_hint"), default="") or None,
        message_id=_as_text(parsed.get("message_id"), default="") or None,
        query=_as_text(parsed.get("query"), default="") or None,
        limit=_coerce_int(parsed.get("limit")),
        time_scope=str(parsed.get("time_scope") or "none").strip().lower(),  # type: ignore[arg-type]
        days=_coerce_int(parsed.get("days")),
        confidence=_coerce_float(parsed.get("confidence")),
        raw_reason=_as_text(parsed.get("raw_reason"), default="") or None,
    )


def _parse_email_intent_fallback(message: str) -> ParsedEmailIntent | None:
    intent = _detect_email_intent(message)
    time_scope, days = _extract_time_scope_from_message(message)
    query = _extract_query_phrase(message)
    limit = _extract_recent_count(message)
    message_id = _extract_message_id(message)
    account_hint = _extract_account_hint_from_message(message)

    if intent is None and _looks_email_related(message):
        lowered = message.lower()
        if time_scope != "none" or re.search(r"\b(list|show|find|get|recent|latest|last)\b", lowered):
            intent = "list"

    if intent is None:
        return None

    return ParsedEmailIntent(
        intent=intent,
        account_hint=account_hint,
        message_id=message_id,
        query=query,
        limit=limit,
        time_scope=time_scope,
        days=days,
        raw_reason="deterministic_fallback",
    )


def _normalize_and_validate_email_intent(
    parsed: ParsedEmailIntent | None,
    *,
    message: str,
) -> ParsedEmailIntent | None:
    if parsed is None:
        return None

    valid_intents: set[str] = {"list_accounts", "access", "list", "summarize", "read", "send", "help", "none"}
    intent = parsed.intent if parsed.intent in valid_intents else "none"

    account_hint = (parsed.account_hint or "").strip()[:160] or None
    message_id = (parsed.message_id or "").strip() or None
    query = (parsed.query or "").strip()[:240] or None

    limit = parsed.limit if parsed.limit is not None else _extract_recent_count(message)
    limit = max(1, min(int(limit), 50))

    time_scope: EmailTimeScope = parsed.time_scope if parsed.time_scope in {"today", "yesterday", "last_n_days"} else "none"  # type: ignore[assignment]
    days = parsed.days
    if time_scope == "last_n_days":
        if days is None:
            days = 7
        days = max(1, min(int(days), 30))
    else:
        days = None

    if intent == "read" and not message_id:
        query = None

    if intent == "none" and _looks_email_related(message):
        intent = "help"

    return ParsedEmailIntent(
        intent=intent,  # type: ignore[arg-type]
        account_hint=account_hint,
        message_id=message_id,
        query=query,
        limit=limit,
        time_scope=time_scope,
        days=days,
        confidence=parsed.confidence,
        raw_reason=parsed.raw_reason,
    )


def _detect_email_intent(message: str) -> EmailIntent | None:
    lowered = message.lower()
    if re.search(r"\b(list|show|what)\b", lowered) and re.search(r"\bconnected\b", lowered) and re.search(
        r"\b(email accounts?|mail accounts?)\b", lowered
    ):
        return "list_accounts"
    access_patterns = [
        r"\bdo you have access to my inbox\b",
        r"\bcan you access my inbox\b",
        r"\binbox access\b",
        r"\baccess to gmail\b",
        r"\bcan you read my emails?\b",
    ]
    if any(re.search(pattern, lowered) for pattern in access_patterns):
        return "access"
    if re.search(r"\baccess\b", lowered) and re.search(r"\b(inbox|gmail|emails?|mail)\b", lowered):
        return "access"
    if EMAIL_REGEX.search(lowered) and re.search(r"\b(access|inbox)\b", lowered):
        return "access"
    if re.search(r"\b(send|email)\b", lowered) and EMAIL_REGEX.search(lowered):
        return "send"
    if re.search(r"\bread\b", lowered) and re.search(r"\bemail\b", lowered):
        return "read"
    if re.search(r"\b(summarize|summarise)\b", lowered) and re.search(r"\b(emails?|inbox|mail)\b", lowered):
        return "summarize"
    if re.search(r"\bsummary\b", lowered) and re.search(r"\b(emails?|inbox|mail)\b", lowered):
        return "summarize"
    if re.search(r"\b(list|show|find|get)\b", lowered) and re.search(r"\b(emails?|messages?|inbox)\b", lowered):
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


def _extract_time_scope_from_message(message: str) -> tuple[EmailTimeScope, int | None]:
    lowered = message.lower()
    if re.search(r"\btoday('?s)?\b", lowered):
        return "today", None
    if re.search(r"\byesterday('?s)?\b", lowered):
        return "yesterday", None
    days_match = re.search(r"\blast\s+(\d{1,2})\s+days?\b", lowered)
    if days_match:
        try:
            days = int(days_match.group(1))
        except ValueError:
            days = 7
        return "last_n_days", max(1, min(days, 30))
    return "none", None


def _extract_account_hint_from_message(message: str) -> str | None:
    emails = EMAIL_REGEX.findall(message)
    if emails:
        return emails[0].lower()
    return None


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

    subject = ""
    subject_match = re.search(r"\bsubject\s*[:=]\s*([^\n]+)", message, flags=re.IGNORECASE)
    if subject_match:
        subject = subject_match.group(1).strip()
    else:
        about_match = re.search(r"\babout\s+(.+?)(?:\s+\bbody\s*[:=]|\s*$)", message, flags=re.IGNORECASE)
        if about_match:
            subject = about_match.group(1).strip()[:160]

    body_match = re.search(r"\bbody\s*[:=]\s*(.+)$", message, flags=re.IGNORECASE | re.DOTALL)
    if body_match:
        body = _strip_command_prefixes(body_match.group(1).strip())
    else:
        cleaned = EMAIL_REGEX.sub(" ", message)
        cleaned = re.sub(r"\b(send|email|to|cc|bcc|subject|about|body)\b", " ", cleaned, flags=re.IGNORECASE)
        body = _strip_command_prefixes(" ".join(cleaned.split()).strip())

    return {
        "to": recipients,
        "cc": [],
        "bcc": [],
        "subject": subject[:240],
        "body": body,
    }


def _parse_send_request_llm(
    db: Session,
    *,
    tenant_id: str,
    message: str,
    provider_id_override: str | None = None,
) -> ParsedSendDraft | None:
    if not settings.email_tool_llm_parser_enabled:
        return None

    explicit_recipients = sorted({email.lower() for email in EMAIL_REGEX.findall(message)})
    prompt = (
        "Extract email send fields from the user command.\n"
        "Return ONLY valid JSON with keys: to, cc, bcc, subject, body, inferred_subject, cleanup_notes.\n"
        "Rules:\n"
        "- Use only explicit emails present in the user command.\n"
        "- Remove command words from body (say/tell/send/email).\n"
        "- If subject is missing, infer one from the body and set inferred_subject=true.\n"
        "- cleanup_notes is a short list of transformations applied.\n"
        f"- Keep output concise (under about {settings.email_tool_llm_parser_max_tokens} tokens).\n"
        f"Explicit emails in command: {explicit_recipients}\n"
        f"User command: {message}"
    )

    try:
        _, result = LLMRouter(db, tenant_id).chat(
            messages=[
                {"role": "system", "content": "You are a strict JSON extraction engine."},
                {"role": "user", "content": prompt},
            ],
            temperature=settings.email_tool_llm_parser_temperature,
            provider_id_override=provider_id_override,
            allow_fallback=False,
        )
    except Exception:
        return None

    parsed = _parse_json_object(result.get("answer", ""))
    if not isinstance(parsed, dict):
        return None

    return ParsedSendDraft(
        to=_as_string_list(parsed.get("to")),
        cc=_as_string_list(parsed.get("cc")),
        bcc=_as_string_list(parsed.get("bcc")),
        subject=_as_text(parsed.get("subject"), default=""),
        body=_as_text(parsed.get("body"), default=""),
        inferred_subject=bool(parsed.get("inferred_subject")),
        cleanup_notes=_as_string_list(parsed.get("cleanup_notes")),
    )


def _normalize_and_validate_send_draft(
    draft: ParsedSendDraft | dict[str, Any],
    *,
    message: str,
) -> dict[str, Any]:
    if isinstance(draft, ParsedSendDraft):
        raw = {
            "to": list(draft.to),
            "cc": list(draft.cc),
            "bcc": list(draft.bcc),
            "subject": draft.subject,
            "body": draft.body,
            "inferred_subject": draft.inferred_subject,
            "cleanup_notes": list(draft.cleanup_notes),
        }
    else:
        raw = dict(draft)

    explicit_recipients = [email.lower() for email in EMAIL_REGEX.findall(message)]
    explicit_set = set(explicit_recipients)

    to = _normalize_recipients(raw.get("to"), explicit_set)
    cc = _normalize_recipients(raw.get("cc"), explicit_set)
    bcc = _normalize_recipients(raw.get("bcc"), explicit_set)

    if not to and explicit_recipients:
        to = list(dict.fromkeys(explicit_recipients))

    seen = set(to)
    cc = [email for email in cc if email not in seen]
    seen.update(cc)
    bcc = [email for email in bcc if email not in seen]

    body_raw = _as_text(raw.get("body"), default="")
    if not body_raw:
        body_raw = _fallback_body_from_message(message)
    body_clean = _strip_command_prefixes(body_raw)

    subject_raw = _as_text(raw.get("subject"), default="")
    inferred_subject = bool(raw.get("inferred_subject"))
    if not subject_raw or subject_raw.lower() in {"(no subject)", "no subject", "none"}:
        subject_clean = _generate_subject_from_body(body_clean)
        inferred_subject = True
    else:
        subject_clean = _truncate(subject_raw, settings.email_tool_subject_max_len)

    cleanup_notes = _as_string_list(raw.get("cleanup_notes"))
    if body_clean != body_raw:
        cleanup_notes.append("Removed command prefix from body")
    if inferred_subject:
        cleanup_notes.append("Generated subject from message body")

    return {
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": subject_clean,
        "body": body_clean,
        "inferred_subject": inferred_subject,
        "cleanup_notes": list(dict.fromkeys(cleanup_notes)),
    }


def _normalize_recipients(value: Any, explicit_set: set[str]) -> list[str]:
    recipients: list[str] = []
    for item in _as_string_list(value):
        for candidate in EMAIL_REGEX.findall(item):
            normalized = candidate.lower()
            if not EMAIL_VALUE_REGEX.fullmatch(normalized):
                continue
            if explicit_set and normalized not in explicit_set:
                continue
            recipients.append(normalized)
    return list(dict.fromkeys(recipients))


def _fallback_body_from_message(message: str) -> str:
    cleaned = EMAIL_REGEX.sub(" ", message)
    cleaned = re.sub(r"\b(send|email|to|cc|bcc|subject|about|body)\b", " ", cleaned, flags=re.IGNORECASE)
    return _strip_command_prefixes(" ".join(cleaned.split()).strip())


def _strip_command_prefixes(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    while True:
        prior = text
        for pattern in COMMAND_PREFIX_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        text = text.lstrip(":-,; ")
        if text == prior:
            break
    return text.strip()


def _generate_subject_from_body(body: str) -> str:
    content = _strip_command_prefixes(body)
    if not content:
        return "(No subject)"
    first_sentence = next((part.strip() for part in re.split(r"[.!?\n]+", content) if part.strip()), content.strip())
    words = re.findall(r"[a-z0-9']+", first_sentence, flags=re.IGNORECASE)
    if not words:
        return "(No subject)"
    subject = " ".join(words[:8])
    subject = subject[0].upper() + subject[1:] if subject else "(No subject)"
    return _truncate(subject, settings.email_tool_subject_max_len)


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


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,\n]+", value) if part.strip()]
    return []


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
