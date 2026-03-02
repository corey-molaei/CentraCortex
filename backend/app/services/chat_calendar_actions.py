from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from dateparser import parse as parse_date
except Exception:  # pragma: no cover - optional dependency fallback
    parse_date = None

try:
    from dateparser.search import search_dates
except Exception:  # pragma: no cover - optional dependency fallback
    search_dates = None

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_pending_action import ChatPendingAction
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.services.audit import audit_event
from app.services.connectors.google_service import (
    create_event,
    delete_event,
    get_primary_account,
    list_calendars,
    list_events,
    list_user_accounts,
    update_event,
)

CREATE_ACTION = "calendar_create"
UPDATE_ACTION = "calendar_update"
DELETE_ACTION = "calendar_delete"
LIST_ACTION = "calendar_list"
LIST_CONNECTED_ACTION = "calendar_list_connected"

PENDING_DISAMBIGUATION = "pending_disambiguation"
PENDING_CONFIRMATION = "pending_confirmation"
COMPLETED = "completed"
CANCELLED = "cancelled"
EXPIRED = "expired"

YES_TOKENS = {"yes", "y", "confirm", "confirmed", "okay", "ok"}
NO_TOKENS = {"no", "n", "cancel", "stop"}
YES_PHRASES = {"go ahead", "do it"}
NO_PHRASES = {"never mind", "nevermind"}

COMMON_TZ_ABBREVIATIONS = {
    "AEDT": "+11:00",
    "AEST": "+10:00",
    "UTC": "+00:00",
    "GMT": "+00:00",
}
EMAIL_PATTERN = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.IGNORECASE)

QUERY_STOPWORDS = {
    "on",
    "at",
    "from",
    "to",
    "between",
    "and",
    "for",
    "calendar",
    "meeting",
    "event",
    "delete",
    "remove",
    "cancel",
    "update",
    "change",
    "move",
    "upcoming",
    "next",
    "future",
}
ATTENDEE_SEGMENT_END = r"(?:\s+\b(?:for|from|at|on|about|called|named|titled|tomorrow|today|next)\b|$)"


@dataclass
class CalendarChatResult:
    handled: bool
    answer: str


def maybe_handle_calendar_chat_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    client_timezone: str | None,
) -> CalendarChatResult | None:
    now_utc = datetime.now(UTC)

    active_pending = _get_active_pending_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if active_pending:
        if _coerce_utc(active_pending.expires_at) < now_utc:
            active_pending.status = EXPIRED
            db.commit()
            audit_event(
                db,
                event_type="chat.calendar.expired",
                resource_type="chat_pending_action",
                action="expire",
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=active_pending.id,
                payload={
                    "conversation_id": conversation_id,
                    "account_id": active_pending.account_id,
                },
            )
            return CalendarChatResult(
                handled=True,
                answer="That pending calendar action expired. Please repeat your request so I can start again.",
            )
        return _handle_pending_followup(
            db,
            pending=active_pending,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            client_timezone=client_timezone,
        )

    action_type = _detect_action_type(message)
    if action_type is None:
        return None

    if action_type == LIST_CONNECTED_ACTION:
        return _handle_list_connected_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    if not settings.google_client_id or not settings.google_client_secret:
        return CalendarChatResult(
            handled=True,
            answer=(
                "Google actions are not available because OAuth credentials are not configured on the server. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend environment settings."
            ),
        )

    account = _resolve_account(db, tenant_id=tenant_id, user_id=user_id, message=message)
    if account is None:
        return CalendarChatResult(
            handled=True,
            answer=(
                "I could not find a connected Google account for this tenant user. "
                "Open /connectors/google, connect an account, and set one as primary."
            ),
        )

    if not account.access_token_encrypted:
        return CalendarChatResult(
            handled=True,
            answer="This Google account is not connected yet. Please click Connect/Reconnect in /connectors/google first.",
        )

    if action_type == CREATE_ACTION:
        return _handle_create_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account=account,
            message=message,
            client_timezone=client_timezone,
        )
    if action_type == LIST_ACTION:
        return _handle_list_action(
            db,
            account=account,
            message=message,
            client_timezone=client_timezone,
        )

    return _handle_update_or_delete_request(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        account=account,
        message=message,
        action_type=action_type,
        client_timezone=client_timezone,
    )


def _handle_list_connected_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
) -> CalendarChatResult:
    accounts = list_user_accounts(db, tenant_id=tenant_id, user_id=user_id)
    if not accounts:
        return CalendarChatResult(
            handled=True,
            answer="You do not have any Google accounts connected yet. Open /connectors/google to add one.",
        )

    lines = ["Here are your connected Google accounts and calendars:"]
    has_oauth_credentials = bool(settings.google_client_id and settings.google_client_secret)

    for idx, account in enumerate(accounts, start=1):
        account_name = account.label or account.google_account_email or f"Account {idx}"
        account_flags: list[str] = []
        if account.is_primary:
            account_flags.append("primary")
        if account.enabled is False:
            account_flags.append("disabled")
        status_label = "connected" if account.access_token_encrypted else "not connected"
        suffix = f" ({', '.join(account_flags)})" if account_flags else ""
        lines.append(f"{idx}. {account_name}{suffix} - {status_label}")
        if account.google_account_email:
            lines.append(f"   google account email: {account.google_account_email}")

        configured_ids = ", ".join(account.calendar_ids or ["primary"])
        lines.append(f"   configured calendar IDs: {configured_ids}")

        if not account.access_token_encrypted:
            continue
        if not has_oauth_credentials:
            lines.append("   available calendars: unavailable (server OAuth credentials are not configured)")
            continue

        try:
            calendars = list_calendars(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
        except ValueError as exc:
            lines.append(f"   available calendars error: {exc}")
            continue

        if not calendars:
            lines.append("   available calendars: none returned by Google")
            continue

        preview = ", ".join([f"{item['summary']} [{item['id']}]" for item in calendars[:5]])
        if len(calendars) > 5:
            preview += f", ... (+{len(calendars) - 5} more)"
        lines.append(f"   available calendars: {preview}")

    return CalendarChatResult(handled=True, answer="\n".join(lines))


def _handle_list_action(
    db: Session,
    *,
    account: GoogleUserConnector,
    message: str,
    client_timezone: str | None,
) -> CalendarChatResult:
    tz_name = _safe_timezone(client_timezone)
    parsed = _parse_list_request(message, timezone_name=tz_name)
    search_result = _find_event_candidates(
        db,
        account=account,
        target_query=parsed["target_query"],
        target_datetime=parsed.get("target_datetime"),
        target_start_datetime=parsed.get("target_start_datetime"),
        target_end_datetime=parsed.get("target_end_datetime"),
    )

    if search_result.error:
        return CalendarChatResult(
            handled=True,
            answer=f"Google calendar lookup failed: {search_result.error}",
        )

    candidates = search_result.candidates
    if not candidates:
        return CalendarChatResult(
            handled=True,
            answer="I could not find meetings matching that request.",
        )

    lines = ["Here are the closest meetings I found:"]
    for idx, item in enumerate(candidates[:5], start=1):
        start = item.get("start_datetime") or "unknown start"
        end = item.get("end_datetime") or "unknown end"
        lines.append(f"{idx}. {item.get('summary') or 'Untitled'} ({start} -> {end})")
    return CalendarChatResult(handled=True, answer="\n".join(lines))


def _handle_create_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account: GoogleUserConnector,
    message: str,
    client_timezone: str | None,
) -> CalendarChatResult:
    tz_name = _safe_timezone(client_timezone)
    start_dt = _parse_datetime_from_text(message, timezone_name=tz_name)
    if start_dt is None:
        return CalendarChatResult(
            handled=True,
            answer="I can create the meeting, but I still need a date/time. Example: 'add meeting tomorrow 2pm'.",
        )

    duration_minutes = _extract_duration_minutes(message) or 60
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    summary = _extract_meeting_title(message)
    attendees = _extract_attendees(message)

    payload = {
        "calendar_id": "primary",
        "summary": summary,
        "description": None,
        "location": None,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "timezone": tz_name,
        "attendees": attendees,
    }

    try:
        event = create_event(
            db,
            account,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            payload=payload,
        )
    except ValueError as exc:
        return CalendarChatResult(handled=True, answer=f"Google calendar create failed: {exc}")

    audit_event(
        db,
        event_type="chat.calendar.create",
        resource_type="google_calendar_event",
        action="create",
        tenant_id=tenant_id,
        user_id=user_id,
        resource_id=event.get("id") or None,
        payload={
            "account_id": account.id,
            "calendar_id": event.get("calendar_id") or "primary",
            "conversation_id": conversation_id,
            "summary": summary,
            "start_datetime": payload["start_datetime"],
            "end_datetime": payload["end_datetime"],
        },
    )

    return CalendarChatResult(
        handled=True,
        answer=(
            f"Meeting created on {account.google_account_email or account.label or 'your primary account'}: "
            f"'{summary}' from {_humanize_datetime(start_dt, tz_name)} to {_humanize_datetime(end_dt, tz_name)}"
            f"{_attendee_suffix(attendees)}."
        ),
    )


def _handle_update_or_delete_request(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account: GoogleUserConnector,
    message: str,
    action_type: str,
    client_timezone: str | None,
) -> CalendarChatResult:
    tz_name = _safe_timezone(client_timezone)
    parsed = _parse_update_delete_request(message, action_type=action_type, timezone_name=tz_name)

    if action_type == UPDATE_ACTION and parsed.get("new_start_datetime") is None:
        return CalendarChatResult(
            handled=True,
            answer="I can update that meeting, but I need the change details. Example: 'move my standup tomorrow to 3pm'.",
        )

    search_result = _find_event_candidates(
        db,
        account=account,
        target_query=parsed["target_query"],
        target_datetime=parsed.get("target_datetime"),
        target_start_datetime=parsed.get("target_start_datetime"),
        target_end_datetime=parsed.get("target_end_datetime"),
    )
    if search_result.error:
        return CalendarChatResult(
            handled=True,
            answer=f"Google calendar lookup failed: {search_result.error}",
        )

    candidates = search_result.candidates
    if not candidates:
        return CalendarChatResult(
            handled=True,
            answer="I could not find a matching calendar event. Please provide more specific title/date details.",
        )

    force_disambiguation = _is_ambiguous_update_delete(parsed)
    if len(candidates) > 1 or force_disambiguation:
        pending = _replace_pending_action(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            account_id=account.id,
            action_type=action_type,
            status=PENDING_DISAMBIGUATION,
            payload_json={
                "timezone": tz_name,
                "target_query": parsed["target_query"],
                "target_datetime": _to_iso(parsed.get("target_datetime")),
                "target_start_datetime": _to_iso(parsed.get("target_start_datetime")),
                "target_end_datetime": _to_iso(parsed.get("target_end_datetime")),
                "new_start_datetime": _to_iso(parsed.get("new_start_datetime")),
                "new_end_datetime": _to_iso(parsed.get("new_end_datetime")),
                "duration_minutes": parsed.get("duration_minutes"),
            },
            candidates_json=candidates[:5],
        )
        audit_event(
            db,
            event_type="chat.calendar.pending_disambiguation",
            resource_type="chat_pending_action",
            action="create",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=pending.id,
            payload={
                "account_id": account.id,
                "conversation_id": conversation_id,
                "action_type": action_type,
                "candidate_count": len(candidates[:5]),
            },
        )
        return CalendarChatResult(
            handled=True,
            answer=_build_candidate_prompt(action_type, candidates[:5]),
        )

    candidate = candidates[0]
    pending = _replace_pending_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        account_id=account.id,
        action_type=action_type,
        status=PENDING_CONFIRMATION,
        payload_json={
            "timezone": tz_name,
            "target_query": parsed["target_query"],
            "target_datetime": _to_iso(parsed.get("target_datetime")),
            "target_start_datetime": _to_iso(parsed.get("target_start_datetime")),
            "target_end_datetime": _to_iso(parsed.get("target_end_datetime")),
            "new_start_datetime": _to_iso(parsed.get("new_start_datetime")),
            "new_end_datetime": _to_iso(parsed.get("new_end_datetime")),
            "duration_minutes": parsed.get("duration_minutes"),
            "selected_event": candidate,
        },
        candidates_json=[],
    )
    audit_event(
        db,
        event_type="chat.calendar.pending_confirmation",
        resource_type="chat_pending_action",
        action="create",
        tenant_id=tenant_id,
        user_id=user_id,
        resource_id=pending.id,
        payload={
            "account_id": account.id,
            "conversation_id": conversation_id,
            "action_type": action_type,
            "event_id": candidate.get("id"),
        },
    )

    return CalendarChatResult(handled=True, answer=_build_confirmation_prompt(action_type, candidate))


def _handle_pending_followup(
    db: Session,
    *,
    pending: ChatPendingAction,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    client_timezone: str | None,
) -> CalendarChatResult:
    if pending.status == PENDING_DISAMBIGUATION:
        index = _parse_selection(message)
        if index is None or index < 1 or index > len(pending.candidates_json or []):
            return CalendarChatResult(handled=True, answer="Please select one candidate by number (for example: 1).")

        candidate = (pending.candidates_json or [])[index - 1]
        payload = dict(pending.payload_json or {})
        payload["selected_event"] = candidate

        pending.payload_json = payload
        pending.status = PENDING_CONFIRMATION
        pending.candidates_json = []
        pending.expires_at = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()

        audit_event(
            db,
            event_type="chat.calendar.pending_confirmation",
            resource_type="chat_pending_action",
            action="update",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=pending.id,
            payload={
                "account_id": pending.account_id,
                "conversation_id": conversation_id,
                "action_type": pending.action_type,
                "event_id": candidate.get("id"),
            },
        )
        return CalendarChatResult(handled=True, answer=_build_confirmation_prompt(pending.action_type, candidate))

    if pending.status != PENDING_CONFIRMATION:
        return CalendarChatResult(handled=True, answer="I could not continue that calendar action. Please retry your request.")

    decision = _parse_confirmation(message)
    if decision is False:
        pending.status = CANCELLED
        db.commit()
        audit_event(
            db,
            event_type="chat.calendar.cancelled",
            resource_type="chat_pending_action",
            action="cancel",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=pending.id,
            payload={"account_id": pending.account_id, "conversation_id": conversation_id},
        )
        return CalendarChatResult(handled=True, answer="Cancelled. I did not change your calendar.")

    if decision is None:
        return CalendarChatResult(handled=True, answer="Please confirm with 'yes' to proceed or 'no' to cancel.")

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
        return CalendarChatResult(handled=True, answer="That Google account is no longer available. Please reconnect and try again.")

    payload = dict(pending.payload_json or {})
    selected_event = dict(payload.get("selected_event") or {})
    tz_name = _safe_timezone(payload.get("timezone") or client_timezone)

    if pending.action_type == DELETE_ACTION:
        calendar_id = str(selected_event.get("calendar_id") or "primary")
        event_id = str(selected_event.get("id") or "")
        if not event_id:
            pending.status = CANCELLED
            db.commit()
            return CalendarChatResult(handled=True, answer="I could not resolve the event id to delete.")

        try:
            delete_event(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                calendar_id=calendar_id,
                event_id=event_id,
            )
        except ValueError as exc:
            return CalendarChatResult(handled=True, answer=f"Google calendar delete failed: {exc}")

        pending.status = COMPLETED
        db.commit()
        audit_event(
            db,
            event_type="chat.calendar.delete",
            resource_type="google_calendar_event",
            action="delete",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=event_id,
            payload={
                "account_id": account.id,
                "calendar_id": calendar_id,
                "conversation_id": conversation_id,
            },
        )
        return CalendarChatResult(
            handled=True,
            answer=f"Deleted '{selected_event.get('summary') or 'event'}' from your Google Calendar.",
        )

    if pending.action_type == UPDATE_ACTION:
        event_id = str(selected_event.get("id") or "")
        calendar_id = str(selected_event.get("calendar_id") or "primary")
        if not event_id:
            pending.status = CANCELLED
            db.commit()
            return CalendarChatResult(handled=True, answer="I could not resolve the event id to update.")

        new_start = _from_iso(payload.get("new_start_datetime"))
        new_end = _from_iso(payload.get("new_end_datetime"))
        if new_start is None:
            return CalendarChatResult(handled=True, answer="I still need the new meeting time to apply the update.")

        selected_start = _from_iso(selected_event.get("start_datetime"))
        selected_end = _from_iso(selected_event.get("end_datetime"))
        duration_minutes = payload.get("duration_minutes")
        if duration_minutes is None:
            if selected_start and selected_end and selected_end > selected_start:
                duration_minutes = int((selected_end - selected_start).total_seconds() // 60)
            else:
                duration_minutes = 60

        if new_end is None:
            new_end = new_start + timedelta(minutes=max(1, int(duration_minutes)))

        update_payload = {
            "calendar_id": calendar_id,
            "summary": selected_event.get("summary") or "Meeting",
            "description": selected_event.get("description"),
            "location": selected_event.get("location"),
            "start_datetime": new_start.isoformat(),
            "end_datetime": new_end.isoformat(),
            "timezone": tz_name,
            "attendees": [],
        }

        try:
            updated = update_event(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                event_id=event_id,
                payload=update_payload,
            )
        except ValueError as exc:
            return CalendarChatResult(handled=True, answer=f"Google calendar update failed: {exc}")

        pending.status = COMPLETED
        db.commit()
        audit_event(
            db,
            event_type="chat.calendar.update",
            resource_type="google_calendar_event",
            action="update",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=event_id,
            payload={
                "account_id": account.id,
                "calendar_id": calendar_id,
                "conversation_id": conversation_id,
                "start_datetime": update_payload["start_datetime"],
                "end_datetime": update_payload["end_datetime"],
            },
        )
        return CalendarChatResult(
            handled=True,
            answer=(
                f"Updated '{updated.get('summary') or selected_event.get('summary') or 'meeting'}' "
                f"to {_humanize_datetime(new_start, tz_name)}."
            ),
        )

    pending.status = CANCELLED
    db.commit()
    return CalendarChatResult(handled=True, answer="Unsupported pending calendar action type.")


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
            ChatPendingAction.status.in_([PENDING_DISAMBIGUATION, PENDING_CONFIRMATION]),
        )
        .order_by(ChatPendingAction.created_at.desc())
    ).scalars().first()


def _replace_pending_action(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    account_id: str,
    action_type: str,
    status: str,
    payload_json: dict,
    candidates_json: list[dict],
) -> ChatPendingAction:
    active = _get_active_pending_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if active:
        active.status = CANCELLED

    pending = ChatPendingAction(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        account_id=account_id,
        action_type=action_type,
        status=status,
        payload_json=payload_json,
        candidates_json=candidates_json,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    return pending


@dataclass
class EventSearchResult:
    candidates: list[dict]
    error: str | None = None


def _find_event_candidates(
    db: Session,
    *,
    account: GoogleUserConnector,
    target_query: str,
    target_datetime: datetime | None,
    target_start_datetime: datetime | None,
    target_end_datetime: datetime | None,
) -> EventSearchResult:
    windows: list[tuple[str, str, int]] = []
    if target_start_datetime:
        first_min = target_start_datetime - timedelta(hours=2)
        first_max = (target_end_datetime + timedelta(hours=2)) if target_end_datetime else (target_start_datetime + timedelta(hours=3))
        windows.append((first_min.isoformat(), first_max.isoformat(), 120))
        windows.append(((target_start_datetime - timedelta(days=1)).isoformat(), (first_max + timedelta(days=1)).isoformat(), 250))
    elif target_datetime:
        # First pass is narrow around requested time to avoid missing the target in busy calendars.
        windows.append(((target_datetime - timedelta(hours=12)).isoformat(), (target_datetime + timedelta(hours=12)).isoformat(), 120))
        # Fallback pass broadens range.
        windows.append(((target_datetime - timedelta(days=2)).isoformat(), (target_datetime + timedelta(days=4)).isoformat(), 250))
    else:
        now = datetime.now(UTC)
        windows.append(((now - timedelta(days=30)).isoformat(), (now + timedelta(days=90)).isoformat(), 250))

    query = target_query.strip()
    query = query if _is_useful_query(query) else None
    configured_calendar_ids = [str(item).strip() for item in (account.calendar_ids or ["primary"]) if str(item).strip()]
    calendar_ids: list[str] = []
    for calendar_id in configured_calendar_ids + ["primary"]:
        if calendar_id not in calendar_ids:
            calendar_ids.append(calendar_id)

    events: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []

    def _collect(query_value: str | None, *, time_min: str, time_max: str, limit: int) -> None:
        for calendar_id in calendar_ids:
            try:
                rows = list_events(
                    db,
                    account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    calendar_id=calendar_id,
                    query=query_value,
                    time_min=time_min,
                    time_max=time_max,
                    limit=limit,
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
            for item in rows:
                event_id = str(item.get("id") or "")
                item_calendar_id = str(item.get("calendar_id") or calendar_id)
                if not event_id:
                    continue
                # De-duplicate aliases of the same Google calendar (e.g. "primary" and account email)
                # where Google returns the same event id from both endpoints.
                key = event_id
                if key in seen:
                    continue
                seen.add(key)
                item["calendar_id"] = item_calendar_id
                events.append(item)

    for time_min, time_max, limit in windows:
        _collect(query, time_min=time_min, time_max=time_max, limit=limit)
        if query and not events:
            _collect(None, time_min=time_min, time_max=time_max, limit=limit)
        if events:
            break

    query_tokens = _tokenize(query or "")

    def _score(event: dict) -> float:
        score = 0.0

        summary = str(event.get("summary") or "")
        summary_tokens = _tokenize(summary)
        score += float(len(query_tokens.intersection(summary_tokens))) * 10.0

        if query and query.lower() in summary.lower():
            score += 8.0

        start = _from_iso(event.get("start_datetime"))
        end = _from_iso(event.get("end_datetime"))

        if target_datetime and start:
            diff_hours = abs((start - target_datetime).total_seconds()) / 3600.0
            score += max(0.0, 6.0 - min(diff_hours / 6.0, 6.0))

        if target_start_datetime and start:
            diff_minutes = abs((start - target_start_datetime).total_seconds()) / 60.0
            score += max(0.0, 16.0 - min(diff_minutes / 5.0, 16.0))

        if target_end_datetime and end:
            diff_minutes = abs((end - target_end_datetime).total_seconds()) / 60.0
            score += max(0.0, 12.0 - min(diff_minutes / 5.0, 12.0))

        return score

    ranked = sorted(events, key=_score, reverse=True)
    filtered = [event for event in ranked if event.get("id")]

    if query and filtered:
        strong = [event for event in filtered if _score(event) >= 5.0]
        if strong:
            return EventSearchResult(candidates=strong[:5])

    if filtered:
        return EventSearchResult(candidates=filtered[:5])

    if errors:
        return EventSearchResult(candidates=[], error=errors[-1])
    return EventSearchResult(candidates=[])


def _parse_update_delete_request(message: str, *, action_type: str, timezone_name: str) -> dict:
    cleaned = " ".join(message.strip().split())
    target_query = cleaned

    target_start_datetime, target_end_datetime = _extract_datetime_range(cleaned, timezone_name=timezone_name)
    target_datetime = target_start_datetime or _parse_datetime_from_text(cleaned, timezone_name=timezone_name)
    duration_minutes = _extract_duration_minutes(cleaned)

    new_start: datetime | None = None
    new_end: datetime | None = None

    if action_type == UPDATE_ACTION:
        to_match = re.search(r"\bto\b\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if to_match:
            to_phrase = to_match.group(1).strip()
            new_start = _parse_datetime_from_text(to_phrase, timezone_name=timezone_name)

            explicit_date = bool(
                re.search(r"\b(today|tomorrow|next|on|\d{4}-\d{2}-\d{2})\b", to_phrase, flags=re.IGNORECASE)
            )
            if new_start and not explicit_date and target_datetime:
                tz = ZoneInfo(timezone_name)
                anchor = target_datetime.astimezone(tz)
                candidate = new_start.astimezone(tz)
                new_start = candidate.replace(year=anchor.year, month=anchor.month, day=anchor.day)

            if new_start and duration_minutes:
                new_end = new_start + timedelta(minutes=duration_minutes)

            target_query = cleaned[: to_match.start()].strip()

    target_query = _sanitize_target_query(_strip_action_words(target_query, action_type=action_type))

    return {
        "original_message": message,
        "target_query": target_query,
        "target_datetime": target_datetime,
        "target_start_datetime": target_start_datetime,
        "target_end_datetime": target_end_datetime,
        "new_start_datetime": new_start,
        "new_end_datetime": new_end,
        "duration_minutes": duration_minutes,
    }


def _parse_list_request(message: str, *, timezone_name: str) -> dict:
    cleaned = " ".join(message.strip().split())
    target_start_datetime, target_end_datetime = _extract_datetime_range(cleaned, timezone_name=timezone_name)
    target_datetime = target_start_datetime or _parse_datetime_from_text(cleaned, timezone_name=timezone_name)
    target_query = _sanitize_target_query(_strip_action_words(cleaned, action_type=LIST_ACTION))
    return {
        "target_query": target_query,
        "target_datetime": target_datetime,
        "target_start_datetime": target_start_datetime,
        "target_end_datetime": target_end_datetime,
    }


def _resolve_account(db: Session, *, tenant_id: str, user_id: str, message: str) -> GoogleUserConnector | None:
    accounts = list_user_accounts(db, tenant_id=tenant_id, user_id=user_id)
    if not accounts:
        return None

    lowered = message.lower()
    for account in accounts:
        for value in [account.google_account_email or "", account.label or ""]:
            candidate = value.strip().lower()
            if candidate and candidate in lowered:
                return account

    message_tokens = _tokenize(lowered)
    best_match: GoogleUserConnector | None = None
    best_score = 0
    for account in accounts:
        label = (account.label or "").strip().lower()
        if not label:
            continue
        label_tokens = _tokenize(label)
        if not label_tokens:
            continue
        overlap = label_tokens.intersection(message_tokens)
        if not overlap:
            continue
        # Prefer the account with strongest token overlap when users reference partial labels.
        score = len(overlap)
        if score > best_score:
            best_match = account
            best_score = score
    if best_match is not None:
        return best_match

    primary = get_primary_account(db, tenant_id=tenant_id, user_id=user_id)
    return primary or accounts[0]


def _detect_action_type(message: str) -> str | None:
    lowered = message.lower()

    if re.search(r"\b(list|show|find|get|what)\b", lowered) and re.search(
        r"\b(connected|added|configured)\b", lowered
    ) and re.search(r"\b(google|calendar|calendars|account|accounts)\b", lowered):
        return LIST_CONNECTED_ACTION

    if re.search(r"\b(add|create|schedule|book|set up|setup)\b", lowered) and re.search(
        r"\b(meeting|event|calendar)\b", lowered
    ):
        return CREATE_ACTION

    if re.search(r"\b(update|change|move|reschedule|edit)\b", lowered) and re.search(
        r"\b(meeting|event|calendar|standup)\b", lowered
    ):
        return UPDATE_ACTION

    if re.search(r"\b(delete|remove|cancel)\b", lowered) and re.search(
        r"\b(meeting|event|calendar)\b", lowered
    ):
        return DELETE_ACTION
    if re.search(r"\b(upcoming|next|future)\b", lowered) and re.search(
        r"\b(meetings?|events?|calendar)\b", lowered
    ):
        return LIST_ACTION
    if re.search(r"\b(list|show|find|get|what)\b", lowered) and re.search(
        r"\b(meetings?|events?|calendars?)\b", lowered
    ):
        return LIST_ACTION

    return None


def _extract_duration_minutes(message: str) -> int | None:
    duration_match = re.search(r"\bfor\s+(\d{1,3})\s*(minutes?|mins?|hours?|hrs?)\b", message, flags=re.IGNORECASE)
    if not duration_match:
        return None

    value = int(duration_match.group(1))
    unit = duration_match.group(2).lower()
    if unit.startswith("hour") or unit.startswith("hr"):
        return value * 60
    return value


def _extract_meeting_title(message: str) -> str:
    normalized = " ".join(message.strip().split())

    named = re.search(
        r"\b(?:called|named|titled)\s+(.+?)(?:\s+(?:tomorrow|today|at|on|for|from)\b|$)",
        normalized,
        re.IGNORECASE,
    )
    if named:
        title = named.group(1).strip(" .,")
        if title:
            return title[:120]

    about = re.search(
        r"\babout\s+(.+?)(?:\s+(?:tomorrow|today|at|on|for|from)\b|$)",
        normalized,
        re.IGNORECASE,
    )
    if about:
        title = about.group(1).strip(" .,")
        if title:
            return title[:120]

    return "Meeting"


def _extract_attendees(message: str) -> list[str]:
    normalized = " ".join(message.strip().split())

    attendee_patterns = [
        rf"\battendees?\b\s*(?::|-)?\s*(.+?){ATTENDEE_SEGMENT_END}",
        rf"\bwith\b\s+(.+?){ATTENDEE_SEGMENT_END}",
        rf"\binvite\b\s+(.+?){ATTENDEE_SEGMENT_END}",
    ]
    attendee_fragments: list[str] = []
    for pattern in attendee_patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            attendee_fragments.append(match.group(1))

    raw_candidates: list[str] = []
    for fragment in attendee_fragments:
        raw_candidates.extend(EMAIL_PATTERN.findall(fragment))

    if not raw_candidates and re.search(r"\battendees?\b", normalized, flags=re.IGNORECASE):
        raw_candidates = EMAIL_PATTERN.findall(normalized)

    unique: list[str] = []
    seen: set[str] = set()
    for email in raw_candidates:
        lowered = email.strip().lower()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        unique.append(lowered)
    return unique


def _attendee_suffix(attendees: list[str]) -> str:
    if not attendees:
        return ""
    if len(attendees) == 1:
        return f" with attendee {attendees[0]}"
    return f" with attendees {', '.join(attendees)}"


def _parse_datetime_from_text(text: str, *, timezone_name: str) -> datetime | None:
    normalized_text = _normalize_datetime_text(text)
    sanitized_text = _sanitize_datetime_input(normalized_text)
    tz_name = _safe_timezone(timezone_name)
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    if search_dates is not None:
        parsed = search_dates(
            sanitized_text,
            settings={
                "TIMEZONE": tz_name,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now,
            },
            languages=["en"],
        )
        if parsed:
            best_value: datetime | None = None
            best_score = -10_000
            for fragment, value in parsed:
                if value is None:
                    continue
                score = _datetime_fragment_score(fragment, sanitized_text)
                if score > best_score:
                    best_value = value
                    best_score = score
            if best_value is not None:
                if (
                    ("tomorrow" in sanitized_text.lower() or "today" in sanitized_text.lower())
                    and best_value.year > now.year + 2
                ):
                    return _fallback_parse_datetime(sanitized_text, now=now)
                return _coerce_utc(best_value)

    if parse_date is not None:
        parsed_single = parse_date(
            sanitized_text,
            settings={
                "TIMEZONE": tz_name,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "RELATIVE_BASE": now,
            },
        )
        if parsed_single is not None:
            if (
                ("tomorrow" in sanitized_text.lower() or "today" in sanitized_text.lower())
                and parsed_single.year > now.year + 2
            ):
                return _fallback_parse_datetime(sanitized_text, now=now)
            return _coerce_utc(parsed_single)

    return _fallback_parse_datetime(sanitized_text, now=now)


def _fallback_parse_datetime(text: str, *, now: datetime) -> datetime | None:
    lowered = text.lower()
    explicit_date = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lowered)

    day_offset = 0
    if "tomorrow" in lowered:
        day_offset = 1
    elif "today" in lowered:
        day_offset = 0

    am_pm_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    twenty_four_match = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)

    if am_pm_match:
        hour = int(am_pm_match.group(1))
        minute = int(am_pm_match.group(2) or 0)
        meridiem = am_pm_match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
    elif twenty_four_match:
        hour = int(twenty_four_match.group(1))
        minute = int(twenty_four_match.group(2))
    else:
        return None

    base = now + timedelta(days=day_offset)
    if explicit_date:
        base = base.replace(
            year=int(explicit_date.group(1)),
            month=int(explicit_date.group(2)),
            day=int(explicit_date.group(3)),
        )

    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return _coerce_utc(candidate)


def _build_candidate_prompt(action_type: str, candidates: list[dict]) -> str:
    verb = "update" if action_type == UPDATE_ACTION else "delete"
    lines = [f"I found these nearest meetings. Reply with a number to choose which one to {verb}:"]
    for idx, item in enumerate(candidates, start=1):
        lines.append(f"{idx}. {item.get('summary') or 'Untitled'} ({item.get('start_datetime') or 'unknown start'})")
    return "\n".join(lines)


def _build_confirmation_prompt(action_type: str, candidate: dict) -> str:
    if action_type == UPDATE_ACTION:
        return (
            f"Confirm update for '{candidate.get('summary') or 'meeting'}' "
            f"at {candidate.get('start_datetime') or 'unknown start'}? Reply yes/no."
        )
    return (
        f"Confirm delete for '{candidate.get('summary') or 'meeting'}' "
        f"at {candidate.get('start_datetime') or 'unknown start'}? Reply yes/no."
    )


def _parse_selection(text: str) -> int | None:
    stripped = text.strip().lower()
    if stripped.isdigit():
        return int(stripped)

    return {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
    }.get(stripped)


def _parse_confirmation(text: str) -> bool | None:
    lowered = text.strip().lower()
    token_set = _tokenize(lowered)

    if token_set.intersection(YES_TOKENS) or any(phrase in lowered for phrase in YES_PHRASES):
        return True
    if token_set.intersection(NO_TOKENS) or any(phrase in lowered for phrase in NO_PHRASES):
        return False
    return None


def _strip_action_words(text: str, *, action_type: str) -> str:
    patterns = {
        CREATE_ACTION: r"\b(add|create|schedule|book|set up|setup|a|an|meeting|event|calendar)\b",
        UPDATE_ACTION: r"\b(update|change|move|reschedule|edit|my|the|meeting|event|calendar)\b",
        DELETE_ACTION: r"\b(delete|remove|cancel|my|the|meeting|event|calendar)\b",
        LIST_ACTION: r"\b(list|show|find|get|what|are|is|my|the|upcoming|next|future|meetings?|events?|calendars?)\b",
    }
    pattern = patterns.get(action_type)
    if not pattern:
        return text
    return re.sub(pattern, " ", text, flags=re.IGNORECASE)


def _sanitize_target_query(value: str) -> str:
    cleaned = value
    cleaned = EMAIL_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}\s*(am|pm)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(am|pm)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(aedt|aest|utc|gmt)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(today|tomorrow|next|from|to|on|at|between)\b", " ", cleaned, flags=re.IGNORECASE)

    tokens = [token for token in _tokenize(cleaned) if token not in QUERY_STOPWORDS and not token.isdigit()]
    if "about" in tokens:
        tokens = [t for t in tokens if t != "about"]
    return " ".join(tokens[:8])


def _is_useful_query(value: str | None) -> bool:
    if not value:
        return False
    tokens = [token for token in _tokenize(value) if token not in QUERY_STOPWORDS]
    return any(any(ch.isalpha() for ch in token) and len(token) >= 3 for token in tokens)


def _extract_datetime_range(text: str, *, timezone_name: str) -> tuple[datetime | None, datetime | None]:
    range_match = re.search(r"\bfrom\b(?P<start>.+?)\bto\b(?P<end>.+)$", text, flags=re.IGNORECASE)
    if not range_match:
        return None, None

    start_text = range_match.group("start").strip(" ,.")
    end_text = range_match.group("end").strip(" ,.")

    start_dt = _parse_datetime_from_text(start_text, timezone_name=timezone_name)
    end_dt = _parse_datetime_from_text(end_text, timezone_name=timezone_name)
    if start_dt and end_dt and end_dt <= start_dt:
        end_dt = end_dt + timedelta(days=1)

    return start_dt, end_dt


def _is_ambiguous_update_delete(parsed: dict) -> bool:
    query = str(parsed.get("target_query") or "").strip()
    tokens = [token for token in _tokenize(query) if token not in QUERY_STOPWORDS]
    has_time_constraint = parsed.get("target_datetime") is not None or parsed.get("target_start_datetime") is not None
    no_explicit_range = parsed.get("target_start_datetime") is None and parsed.get("target_end_datetime") is None
    has_explicit_title = bool(re.search(r"\b(called|named|titled)\b", str(parsed.get("original_message") or ""), flags=re.IGNORECASE))

    if has_explicit_title:
        return False
    if has_time_constraint and no_explicit_range and len(tokens) <= 2:
        return True
    return False


def _normalize_datetime_text(value: str) -> str:
    normalized = value
    for abbreviation, offset in COMMON_TZ_ABBREVIATIONS.items():
        normalized = re.sub(rf"\b{abbreviation}\b", offset, normalized, flags=re.IGNORECASE)
    return normalized


def _sanitize_datetime_input(value: str) -> str:
    cleaned = EMAIL_PATTERN.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _datetime_fragment_score(fragment: str, full_text: str) -> int:
    score = len(fragment.strip())
    lowered_fragment = fragment.lower()
    lowered_full = full_text.lower()
    if "tomorrow" in lowered_fragment or "today" in lowered_fragment:
        score += 200
    if "tomorrow" in lowered_full or "today" in lowered_full:
        if "tomorrow" not in lowered_fragment and "today" not in lowered_fragment:
            score -= 25
    if re.search(r"\b\d{1,2}:\d{2}\b", lowered_fragment) or re.search(r"\b\d{1,2}\s*(am|pm)\b", lowered_fragment):
        score += 80
    if any(token in lowered_fragment for token in ["from", "to"]):
        score -= 10
    return score


def _humanize_datetime(value: datetime, timezone_name: str) -> str:
    tz = ZoneInfo(_safe_timezone(timezone_name))
    local = value.astimezone(tz)
    return local.strftime("%Y-%m-%d %H:%M %Z")


def _tokenize(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", value.lower()) if len(token) >= 2}


def _safe_timezone(value: str | None) -> str:
    if not value:
        return "UTC"
    try:
        ZoneInfo(value)
        return value
    except Exception:
        return "UTC"


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _coerce_utc(parsed)
