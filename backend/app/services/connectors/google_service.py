from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret, random_token
from app.models.acl_policy import ACLPolicy
from app.models.connector_oauth_state import ConnectorOAuthState
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.document import Document
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document
from app.services.document_indexing import soft_delete_document

GOOGLE_OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_CALENDAR_BASE_URL = "https://www.googleapis.com/calendar/v3"
GOOGLE_DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"
GOOGLE_SHEETS_BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"
GOOGLE_PEOPLE_BASE_URL = "https://people.googleapis.com/v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _configured_scopes() -> list[str]:
    raw_value = settings.google_oauth_scopes.strip()
    if not raw_value:
        return []
    scopes: list[str] = []
    for chunk in raw_value.replace(",", " ").split():
        if chunk and chunk not in scopes:
            scopes.append(chunk)
    return scopes


def _parse_google_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_email_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decode_base64url(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * ((4 - len(data) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
    except Exception:
        return ""
    return raw.decode("utf-8", errors="ignore")


def _gmail_header(headers: list[dict], name: str) -> str:
    lookup = name.lower()
    for item in headers:
        if str(item.get("name", "")).lower() == lookup:
            return str(item.get("value", ""))
    return ""


def _gmail_body(payload: dict) -> str:
    mime_type = str(payload.get("mimeType", "")).lower()
    body = payload.get("body") or {}
    if mime_type.startswith("text/plain"):
        decoded = _decode_base64url(body.get("data"))
        if decoded:
            return decoded

    parts = payload.get("parts") or []
    for part in parts:
        part_body = _gmail_body(part)
        if part_body:
            return part_body

    return _decode_base64url(body.get("data"))


def _google_request(
    *,
    method: str,
    access_token: str | None = None,
    url: str,
    params: dict | None = None,
    data: dict | None = None,
    json_body: dict | None = None,
) -> dict:
    headers: dict[str, str] = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    with httpx.Client(timeout=30) as client:
        response = client.request(method, url, headers=headers, params=params, data=data, json=json_body)

    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            detail = str(payload.get("error_description") or (payload.get("error") or {}).get("message") or payload)
        except Exception:
            pass
        raise ValueError(f"Google API request failed: {detail}")

    if response.status_code == 204 or not response.content:
        return {}

    try:
        return response.json()
    except Exception as exc:
        raise ValueError("Google API returned a non-JSON response") from exc


def _google_text_request(*, access_token: str, url: str, params: dict | None = None) -> str:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=headers, params=params)
    if response.status_code >= 400:
        raise ValueError(f"Google API text request failed: {response.text}")
    return response.text


def _exchange_token(data: dict[str, str]) -> dict:
    return _google_request(method="POST", url=GOOGLE_TOKEN_URL, data=data)


def _selector_key(parts: list[str]) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()  # noqa: S324
    return digest[:16]


def _account_resource_id(account_id: str) -> str:
    return f"google_account:{account_id}"


def ensure_private_acl_policy(db: Session, connector: GoogleUserConnector) -> str:
    if connector.private_acl_policy_id:
        existing = db.get(ACLPolicy, connector.private_acl_policy_id)
        if existing and existing.tenant_id == connector.tenant_id:
            return existing.id

    resource_id = _account_resource_id(connector.id)
    policy = db.execute(
        select(ACLPolicy).where(
            ACLPolicy.tenant_id == connector.tenant_id,
            ACLPolicy.policy_type == "document",
            ACLPolicy.resource_id == resource_id,
        )
    ).scalar_one_or_none()

    if policy is None:
        policy = ACLPolicy(
            tenant_id=connector.tenant_id,
            name=f"Google Account {connector.id}",
            policy_type="document",
            resource_id=resource_id,
            allow_all=False,
            allowed_user_ids=[connector.user_id],
            allowed_group_ids=[],
            allowed_role_names=[],
            active=True,
        )
        db.add(policy)
        db.flush()
    else:
        if connector.user_id not in (policy.allowed_user_ids or []):
            policy.allowed_user_ids = [connector.user_id]
        policy.allow_all = False
        policy.active = True

    connector.private_acl_policy_id = policy.id
    db.commit()
    return policy.id


def get_oauth_url(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    redirect_uri: str,
    user_id: str,
) -> tuple[str, str]:
    state = random_token(16)
    db.add(
        ConnectorOAuthState(
            tenant_id=connector.tenant_id,
            user_id=user_id,
            connector_type="google",
            connector_config_id=connector.id,
            state_token=state,
            redirect_uri=redirect_uri,
            expires_at=_utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()

    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(_configured_scopes()),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_OAUTH_URL}?{params}", state


def complete_oauth(
    db: Session,
    connector: GoogleUserConnector,
    *,
    code: str,
    state: str,
    client_id: str,
    client_secret: str,
    user_id: str,
) -> None:
    state_row = db.execute(
        select(ConnectorOAuthState).where(
            ConnectorOAuthState.tenant_id == connector.tenant_id,
            ConnectorOAuthState.user_id == user_id,
            ConnectorOAuthState.connector_type == "google",
            ConnectorOAuthState.connector_config_id == connector.id,
            ConnectorOAuthState.state_token == state,
        )
    ).scalar_one_or_none()
    if not state_row:
        raise ValueError("Invalid OAuth state")
    if (_coerce_utc(state_row.expires_at) or _utcnow()) < _utcnow():
        db.delete(state_row)
        db.commit()
        raise ValueError("OAuth state has expired")

    token_payload = _exchange_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": state_row.redirect_uri,
        }
    )

    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValueError("Google token exchange did not return an access token")

    profile = _google_request(method="GET", access_token=access_token, url=GOOGLE_USERINFO_URL)

    connector.access_token_encrypted = encrypt_secret(access_token)
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        connector.refresh_token_encrypted = encrypt_secret(refresh_token)
    connector.token_expires_at = _utcnow() + timedelta(seconds=int(token_payload.get("expires_in", 3600)))
    connector.scopes = str(token_payload.get("scope", "")).split() or _configured_scopes()
    connector.google_account_email = str(profile.get("email") or "") or None
    connector.google_account_sub = str(profile.get("id") or "") or None

    ensure_private_acl_policy(db, connector)

    db.delete(state_row)
    db.commit()


def refresh_access_token(db: Session, connector: GoogleUserConnector, *, client_id: str, client_secret: str) -> str:
    if not connector.refresh_token_encrypted:
        raise ValueError("Google refresh token is not configured")

    refresh_token = decrypt_secret(connector.refresh_token_encrypted)
    token_payload = _exchange_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )

    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValueError("Google refresh token flow did not return an access token")

    connector.access_token_encrypted = encrypt_secret(access_token)
    connector.token_expires_at = _utcnow() + timedelta(seconds=int(token_payload.get("expires_in", 3600)))
    if token_payload.get("scope"):
        connector.scopes = str(token_payload["scope"]).split()
    db.commit()
    return access_token


def get_valid_access_token(db: Session, connector: GoogleUserConnector, *, client_id: str, client_secret: str) -> str:
    if not connector.access_token_encrypted:
        return refresh_access_token(db, connector, client_id=client_id, client_secret=client_secret)

    needs_refresh = False
    token_expires_at = _coerce_utc(connector.token_expires_at)
    if token_expires_at is not None:
        needs_refresh = token_expires_at <= _utcnow() + timedelta(seconds=30)

    if needs_refresh:
        return refresh_access_token(db, connector, client_id=client_id, client_secret=client_secret)

    return decrypt_secret(connector.access_token_encrypted)


def test_connection(db: Session, connector: GoogleUserConnector, *, client_id: str, client_secret: str) -> tuple[bool, str]:
    try:
        access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
        profile = _google_request(method="GET", access_token=access_token, url=GOOGLE_USERINFO_URL)
        if profile.get("email"):
            connector.google_account_email = profile["email"]
        if profile.get("id"):
            connector.google_account_sub = profile["id"]
        db.commit()
        return True, f"Connected to Google successfully ({profile.get('email', 'unknown account')})"
    except Exception as exc:
        return False, f"Google connection failed: {exc}"


def get_primary_account(db: Session, *, tenant_id: str, user_id: str) -> GoogleUserConnector | None:
    account = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.user_id == user_id,
            GoogleUserConnector.is_primary.is_(True),
        )
    ).scalars().first()
    if account:
        return account
    return db.execute(
        select(GoogleUserConnector)
        .where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.user_id == user_id,
        )
        .order_by(GoogleUserConnector.created_at.asc())
    ).scalars().first()


def list_user_accounts(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    connected_only: bool = False,
) -> list[GoogleUserConnector]:
    query = (
        select(GoogleUserConnector)
        .where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.user_id == user_id,
        )
        .order_by(GoogleUserConnector.created_at.asc())
    )
    accounts = db.execute(query).scalars().all()
    if connected_only:
        return [acc for acc in accounts if acc.access_token_encrypted]
    return accounts


def get_workspace_default_account(db: Session, *, tenant_id: str) -> GoogleUserConnector | None:
    account = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.is_workspace_default.is_(True),
        )
    ).scalars().first()
    if account:
        return account
    return db.execute(
        select(GoogleUserConnector)
        .where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.access_token_encrypted.is_not(None),
            GoogleUserConnector.enabled.is_(True),
        )
        .order_by(GoogleUserConnector.is_primary.desc(), GoogleUserConnector.created_at.asc())
    ).scalars().first()


def set_workspace_default_account(db: Session, *, tenant_id: str, account_id: str) -> GoogleUserConnector:
    account = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.id == account_id,
            GoogleUserConnector.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if account is None:
        raise ValueError("Google account not found")

    others = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.tenant_id == tenant_id,
            GoogleUserConnector.id != account.id,
            GoogleUserConnector.is_workspace_default.is_(True),
        )
    ).scalars().all()
    for other in others:
        other.is_workspace_default = False
    account.is_workspace_default = True
    db.commit()
    db.refresh(account)
    return account


def list_gmail_messages(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    labels: list[str] | None = None,
    limit: int = 10,
    query: str | None = None,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    labels = labels or connector.gmail_labels or ["INBOX"]

    rows: list[dict] = []
    seen: set[str] = set()
    remaining = max(1, limit)

    for label in labels:
        if remaining <= 0:
            break
        payload = _google_request(
            method="GET",
            access_token=access_token,
            url=f"{GOOGLE_GMAIL_BASE_URL}/messages",
            params={
                "maxResults": min(100, max(remaining, 20)),
                "labelIds": label,
                **({"q": query} if query else {}),
            },
        )

        for item in payload.get("messages", []):
            message_id = str(item.get("id") or "")
            if not message_id or message_id in seen:
                continue
            detail = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_GMAIL_BASE_URL}/messages/{message_id}",
                params={"format": "metadata"},
            )
            meta_payload = detail.get("payload") or {}
            headers = meta_payload.get("headers") or []
            subject = _gmail_header(headers, "Subject") or f"Gmail message {message_id}"
            sender = _gmail_header(headers, "From")
            created_at = _parse_email_date(_gmail_header(headers, "Date"))
            internal_date_ms = int(detail.get("internalDate") or 0)
            if created_at is None and internal_date_ms > 0:
                created_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)

            rows.append(
                {
                    "id": message_id,
                    "label": label,
                    "thread_id": detail.get("threadId"),
                    "subject": subject,
                    "from": sender,
                    "sent_at": created_at.isoformat() if created_at else None,
                    "snippet": str(detail.get("snippet") or ""),
                }
            )
            seen.add(message_id)
            remaining -= 1
            if remaining <= 0:
                break

    rows.sort(key=lambda row: row.get("sent_at") or "", reverse=True)
    return rows[:limit]


def read_gmail_message(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    message_id: str,
) -> dict:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    detail = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_GMAIL_BASE_URL}/messages/{message_id}",
        params={"format": "full"},
    )
    payload = detail.get("payload") or {}
    headers = payload.get("headers") or []
    return {
        "id": message_id,
        "thread_id": detail.get("threadId"),
        "subject": _gmail_header(headers, "Subject"),
        "from": _gmail_header(headers, "From"),
        "to": _gmail_header(headers, "To"),
        "date": _gmail_header(headers, "Date"),
        "snippet": str(detail.get("snippet") or ""),
        "body": _gmail_body(payload),
    }


def send_gmail_message(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict:
    if not to:
        raise ValueError("At least one recipient is required")

    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    cc = cc or []
    bcc = bcc or []
    sender = connector.google_account_email or connector.label or "me"

    lines = [
        f"From: {sender}",
        f"To: {', '.join(to)}",
        f"Subject: {subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
    ]
    if cc:
        lines.append(f"Cc: {', '.join(cc)}")
    if bcc:
        lines.append(f"Bcc: {', '.join(bcc)}")
    lines.extend(["", body])
    raw_message = "\r\n".join(lines)
    encoded_message = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("utf-8")

    payload = _google_request(
        method="POST",
        access_token=access_token,
        url=f"{GOOGLE_GMAIL_BASE_URL}/messages/send",
        json_body={"raw": encoded_message},
    )
    return {
        "id": payload.get("id"),
        "thread_id": payload.get("threadId"),
        "label_ids": payload.get("labelIds") or [],
    }


def sync_gmail(db: Session, connector: GoogleUserConnector, *, access_token: str) -> int:
    cursor = dict(connector.sync_cursor or {})
    gmail_cursor = dict(cursor.get("gmail", {}))

    processed_message_ids: set[str] = set()
    total = 0

    acl_policy_id = ensure_private_acl_policy(db, connector)
    sync_mode = str(connector.gmail_sync_mode or "last_n_days").strip().lower()
    cursor_key = _selector_key(
        [
            sync_mode,
            ",".join(sorted(connector.gmail_labels or [])),
            str(connector.gmail_last_n_days or ""),
            str(connector.gmail_max_messages or ""),
            str(connector.gmail_query or ""),
        ]
    )
    selector_cursor = dict(gmail_cursor.get(cursor_key, {}))
    hard_cap = max(1, min(int(connector.gmail_max_messages or 5000), 5000))

    for label in connector.gmail_labels:
        label_cursor = dict(selector_cursor.get(label, {}))
        max_internal_ms = int(label_cursor.get("internal_ms", 0))
        page_token: str | None = None

        while True:
            params: dict[str, str | int] = {
                "maxResults": 100,
                "labelIds": label,
            }
            query_parts: list[str] = []
            if sync_mode == "last_n_days" and connector.gmail_last_n_days:
                query_parts.append(f"newer_than:{max(1, int(connector.gmail_last_n_days))}d")
            elif sync_mode == "query" and connector.gmail_query:
                query_parts.append(str(connector.gmail_query).strip())
            elif max_internal_ms > 0 and sync_mode == "all":
                query_parts.append(f"after:{max_internal_ms // 1000}")
            if query_parts:
                params["q"] = " ".join(query_parts)
            if page_token:
                params["pageToken"] = page_token

            page = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_GMAIL_BASE_URL}/messages",
                params=params,
            )

            for item in page.get("messages", []):
                message_id = str(item.get("id", ""))
                if not message_id or message_id in processed_message_ids:
                    continue

                detail = _google_request(
                    method="GET",
                    access_token=access_token,
                    url=f"{GOOGLE_GMAIL_BASE_URL}/messages/{message_id}",
                    params={"format": "full"},
                )

                payload = detail.get("payload") or {}
                headers = payload.get("headers") or []
                subject = _gmail_header(headers, "Subject") or f"Gmail message {message_id}"
                sender = _gmail_header(headers, "From")
                created_at = _parse_email_date(_gmail_header(headers, "Date"))

                internal_date_ms = int(detail.get("internalDate") or 0)
                if internal_date_ms > max_internal_ms:
                    max_internal_ms = internal_date_ms

                if created_at is None and internal_date_ms > 0:
                    created_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)

                raw_text = _gmail_body(payload)
                if not raw_text:
                    raw_text = str(detail.get("snippet") or "")

                upsert_document(
                    db,
                    tenant_id=connector.tenant_id,
                    source_type="google_gmail",
                    source_id=f"{connector.id}:gmail:{message_id}",
                    url=f"https://mail.google.com/mail/u/0/#all/{message_id}",
                    title=subject,
                    author=sender,
                    source_created_at=created_at,
                    source_updated_at=created_at,
                    raw_text=raw_text,
                    acl_policy_id=acl_policy_id,
                    metadata_json={
                        "google_connector_account_id": connector.id,
                        "google_account_email": connector.google_account_email,
                        "google_account_sub": connector.google_account_sub,
                        "label": label,
                        "label_ids": detail.get("labelIds") or [],
                        "thread_id": detail.get("threadId"),
                        "snippet": detail.get("snippet"),
                    },
                )
                processed_message_ids.add(message_id)
                total += 1
                if total >= hard_cap:
                    break

            if total >= hard_cap:
                break
            page_token = page.get("nextPageToken")
            if not page_token:
                break

        selector_cursor[label] = {
            "internal_ms": str(max_internal_ms),
        }
        if total >= hard_cap:
            break

    gmail_cursor[cursor_key] = selector_cursor
    cursor["gmail"] = gmail_cursor
    connector.sync_cursor = cursor
    return total


def sync_calendar(db: Session, connector: GoogleUserConnector, *, access_token: str) -> int:
    cursor = dict(connector.sync_cursor or {})
    calendar_cursor = dict(cursor.get("calendar", {}))
    total = 0

    acl_policy_id = ensure_private_acl_policy(db, connector)

    sync_mode = str(connector.calendar_sync_mode or "range_days").strip().lower()
    cursor_key = _selector_key(
        [
            sync_mode,
            ",".join(sorted(connector.calendar_ids or [])),
            str(connector.calendar_days_back or ""),
            str(connector.calendar_days_forward or ""),
            str(connector.calendar_max_events or ""),
        ]
    )
    scoped_cursor = dict(calendar_cursor.get(cursor_key, {}))
    max_events_cap = max(1, min(int(connector.calendar_max_events or 5000), 5000))
    now_utc = _utcnow()
    time_min_iso: str | None = None
    time_max_iso: str | None = None
    if sync_mode == "range_days":
        back = max(0, int(connector.calendar_days_back or 30))
        forward = max(1, int(connector.calendar_days_forward or 90))
        time_min_iso = (now_utc - timedelta(days=back)).isoformat()
        time_max_iso = (now_utc + timedelta(days=forward)).isoformat()
    elif sync_mode == "upcoming_count":
        time_min_iso = now_utc.isoformat()

    for calendar_id in connector.calendar_ids:
        max_updated = str(scoped_cursor.get(calendar_id) or "")
        page_token: str | None = None

        while True:
            params: dict[str, str | int] = {
                "maxResults": 250,
                "singleEvents": "true",
                "showDeleted": "true",
            }
            if max_updated and sync_mode == "all":
                params["updatedMin"] = max_updated
            if time_min_iso:
                params["timeMin"] = time_min_iso
            if time_max_iso:
                params["timeMax"] = time_max_iso
            if sync_mode == "upcoming_count":
                params["orderBy"] = "startTime"
                params["maxResults"] = min(max_events_cap, 250)
            if page_token:
                params["pageToken"] = page_token

            encoded_calendar_id = quote(calendar_id, safe="")
            payload = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_CALENDAR_BASE_URL}/calendars/{encoded_calendar_id}/events",
                params=params,
            )

            for event_item in payload.get("items", []):
                event_id = str(event_item.get("id") or "")
                if not event_id:
                    continue

                updated_text = str(event_item.get("updated") or "")
                if updated_text and updated_text > max_updated:
                    max_updated = updated_text

                created_at = _parse_google_datetime(event_item.get("created"))
                updated_at = _parse_google_datetime(updated_text) or created_at

                start_value = (event_item.get("start") or {}).get("dateTime") or (event_item.get("start") or {}).get("date")
                end_value = (event_item.get("end") or {}).get("dateTime") or (event_item.get("end") or {}).get("date")
                attendees = [
                    attendee.get("email")
                    for attendee in (event_item.get("attendees") or [])
                    if attendee.get("email")
                ]

                details = [
                    event_item.get("summary"),
                    event_item.get("description"),
                    f"Location: {event_item.get('location')}" if event_item.get("location") else None,
                    f"Start: {start_value}" if start_value else None,
                    f"End: {end_value}" if end_value else None,
                    f"Attendees: {', '.join(attendees)}" if attendees else None,
                ]
                raw_text = "\n".join([line for line in details if line]) or f"Calendar event {event_id}"

                upsert_document(
                    db,
                    tenant_id=connector.tenant_id,
                    source_type="google_calendar",
                    source_id=f"{connector.id}:calendar:{calendar_id}:{event_id}",
                    url=event_item.get("htmlLink"),
                    title=event_item.get("summary") or f"Calendar event {event_id}",
                    author=(event_item.get("creator") or {}).get("email"),
                    source_created_at=created_at,
                    source_updated_at=updated_at,
                    raw_text=raw_text,
                    acl_policy_id=acl_policy_id,
                    metadata_json={
                        "google_connector_account_id": connector.id,
                        "google_account_email": connector.google_account_email,
                        "google_account_sub": connector.google_account_sub,
                        "calendar_id": calendar_id,
                        "event_id": event_id,
                        "status": event_item.get("status"),
                        "start": event_item.get("start"),
                        "end": event_item.get("end"),
                        "attendees": attendees,
                    },
                )
                total += 1
                if total >= max_events_cap:
                    break

            if total >= max_events_cap:
                break
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        if max_updated:
            scoped_cursor[calendar_id] = max_updated
        if total >= max_events_cap:
            break

    calendar_cursor[cursor_key] = scoped_cursor
    cursor["calendar"] = calendar_cursor
    connector.sync_cursor = cursor
    return total


def sync_drive(db: Session, connector: GoogleUserConnector, *, access_token: str) -> int:
    if not connector.drive_enabled:
        return 0
    selected_folders = [str(item).strip() for item in (connector.drive_folder_ids or []) if str(item).strip()]
    selected_files = [str(item).strip() for item in (connector.drive_file_ids or []) if str(item).strip()]
    if not selected_folders and not selected_files:
        return 0

    acl_policy_id = ensure_private_acl_policy(db, connector)
    seen_file_ids: set[str] = set()
    total = 0

    for folder_id in selected_folders:
        query = f"'{folder_id}' in parents and trashed=false"
        page_token: str | None = None
        while True:
            payload = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_DRIVE_BASE_URL}/files",
                params={
                    "q": query,
                    "pageSize": 100,
                    "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,owners(emailAddress))",
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            for item in payload.get("files", []):
                file_id = str(item.get("id") or "")
                if not file_id or file_id in seen_file_ids:
                    continue
                seen_file_ids.add(file_id)
                total += _upsert_drive_document(
                    db,
                    connector=connector,
                    acl_policy_id=acl_policy_id,
                    access_token=access_token,
                    file_id=file_id,
                    item=item,
                )
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

    for file_id in selected_files:
        if file_id in seen_file_ids:
            continue
        item = _google_request(
            method="GET",
            access_token=access_token,
            url=f"{GOOGLE_DRIVE_BASE_URL}/files/{quote(file_id, safe='')}",
            params={"fields": "id,name,mimeType,modifiedTime,webViewLink,owners(emailAddress)"},
        )
        seen_file_ids.add(file_id)
        total += _upsert_drive_document(
            db,
            connector=connector,
            acl_policy_id=acl_policy_id,
            access_token=access_token,
            file_id=file_id,
            item=item,
        )

    return total


def _upsert_drive_document(
    db: Session,
    *,
    connector: GoogleUserConnector,
    acl_policy_id: str,
    access_token: str,
    file_id: str,
    item: dict,
) -> int:
    name = str(item.get("name") or file_id)
    mime_type = str(item.get("mimeType") or "")
    modified_time = str(item.get("modifiedTime") or "")
    source_updated_at = _parse_google_datetime(modified_time)

    raw_text = f"Drive file: {name}"
    if mime_type == "application/vnd.google-apps.document":
        try:
            raw_text = _google_text_request(
                access_token=access_token,
                url=f"{GOOGLE_DRIVE_BASE_URL}/files/{quote(file_id, safe='')}/export",
                params={"mimeType": "text/plain"},
            )
        except Exception:
            pass

    owner_email = None
    owners = item.get("owners") or []
    if owners:
        owner_email = (owners[0] or {}).get("emailAddress")
    upsert_document(
        db,
        tenant_id=connector.tenant_id,
        source_type="google_drive",
        source_id=f"{connector.id}:drive:{file_id}",
        url=item.get("webViewLink"),
        title=name,
        author=owner_email or connector.google_account_email,
        source_created_at=source_updated_at,
        source_updated_at=source_updated_at,
        raw_text=raw_text,
        acl_policy_id=acl_policy_id,
        metadata_json={
            "google_connector_account_id": connector.id,
            "google_account_email": connector.google_account_email,
            "google_account_sub": connector.google_account_sub,
            "file_id": file_id,
            "mime_type": mime_type,
        },
    )
    return 1


def sync_sheets(db: Session, connector: GoogleUserConnector, *, access_token: str) -> int:
    if not connector.sheets_enabled:
        return 0
    acl_policy_id = ensure_private_acl_policy(db, connector)
    total = 0
    for target in connector.sheets_targets or []:
        if not target or target.get("enabled") is False:
            continue
        spreadsheet_id = str(target.get("spreadsheet_id") or "").strip()
        if not spreadsheet_id:
            continue
        target_range = str(target.get("range") or "A:Z").strip() or "A:Z"
        tab_name = str(target.get("tab") or "").strip()
        read_range = f"{tab_name}!{target_range}" if tab_name else target_range
        payload = _google_request(
            method="GET",
            access_token=access_token,
            url=f"{GOOGLE_SHEETS_BASE_URL}/{quote(spreadsheet_id, safe='')}/values/{quote(read_range, safe='!:$')}",
        )
        values = payload.get("values") or []
        if not values:
            continue
        raw_text = "\n".join([", ".join([str(cell) for cell in row]) for row in values])
        upsert_document(
            db,
            tenant_id=connector.tenant_id,
            source_type="google_sheets",
            source_id=f"{connector.id}:sheets:{spreadsheet_id}:{tab_name or 'sheet'}:{target_range}",
            url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
            title=f"Sheet {spreadsheet_id} {tab_name or ''} {target_range}".strip(),
            author=connector.google_account_email,
            source_created_at=None,
            source_updated_at=_utcnow(),
            raw_text=raw_text,
            acl_policy_id=acl_policy_id,
            metadata_json={
                "google_connector_account_id": connector.id,
                "google_account_email": connector.google_account_email,
                "google_account_sub": connector.google_account_sub,
                "spreadsheet_id": spreadsheet_id,
                "tab": tab_name,
                "range": target_range,
            },
        )
        total += 1
    return total


def sync_contacts(db: Session, connector: GoogleUserConnector, *, access_token: str) -> int:
    if not connector.contacts_enabled:
        return 0
    acl_policy_id = ensure_private_acl_policy(db, connector)
    mode = str(connector.contacts_sync_mode or "all").strip().lower()
    cap = max(1, min(int(connector.contacts_max_count or 1000), 5000))
    group_ids = [str(group).strip() for group in (connector.contacts_group_ids or []) if str(group).strip()]
    if mode == "groups" and not group_ids:
        return 0

    all_people: list[dict] = []
    if mode == "groups":
        for group_id in group_ids:
            page_token: str | None = None
            while True:
                payload = _google_request(
                    method="GET",
                    access_token=access_token,
                    url=f"{GOOGLE_PEOPLE_BASE_URL}/{quote(group_id, safe='/')}/members",
                    params={
                        "maxMembers": min(cap, 1000),
                        **({"pageToken": page_token} if page_token else {}),
                    },
                )
                all_people.extend(payload.get("memberResourceNames") or [])
                if len(all_people) >= cap:
                    break
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
            if len(all_people) >= cap:
                break
        unique_resource_names = []
        seen: set[str] = set()
        for item in all_people:
            resource_name = str(item or "").strip()
            if resource_name and resource_name not in seen:
                seen.add(resource_name)
                unique_resource_names.append(resource_name)
        people_resource_names = unique_resource_names[:cap]
        people: list[dict] = []
        for resource_name in people_resource_names:
            detail = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_PEOPLE_BASE_URL}/{quote(resource_name, safe='/')}",
                params={"personFields": "names,emailAddresses,phoneNumbers,organizations,biographies,metadata"},
            )
            people.append(detail)
    else:
        people = []
        page_token: str | None = None
        while True:
            payload = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_PEOPLE_BASE_URL}/people/me/connections",
                params={
                    "personFields": "names,emailAddresses,phoneNumbers,organizations,biographies,metadata",
                    "pageSize": min(cap, 1000),
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            people.extend(payload.get("connections") or [])
            if len(people) >= cap:
                break
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        people = people[:cap]

    total = 0
    for person in people:
        resource_name = str(person.get("resourceName") or "")
        if not resource_name:
            continue
        names = person.get("names") or []
        emails = person.get("emailAddresses") or []
        phones = person.get("phoneNumbers") or []
        orgs = person.get("organizations") or []
        display_name = str((names[0] or {}).get("displayName") or resource_name)
        email_value = str((emails[0] or {}).get("value") or "")
        phone_value = str((phones[0] or {}).get("value") or "")
        org_value = str((orgs[0] or {}).get("name") or "")
        raw_text_lines = [
            display_name,
            f"Email: {email_value}" if email_value else "",
            f"Phone: {phone_value}" if phone_value else "",
            f"Organization: {org_value}" if org_value else "",
        ]
        raw_text = "\n".join([line for line in raw_text_lines if line])
        upsert_document(
            db,
            tenant_id=connector.tenant_id,
            source_type="google_contacts",
            source_id=f"{connector.id}:contacts:{resource_name}",
            url=None,
            title=display_name,
            author=connector.google_account_email,
            source_created_at=None,
            source_updated_at=_utcnow(),
            raw_text=raw_text,
            acl_policy_id=acl_policy_id,
            metadata_json={
                "google_connector_account_id": connector.id,
                "google_account_email": connector.google_account_email,
                "google_account_sub": connector.google_account_sub,
                "resource_name": resource_name,
                "email": email_value,
                "phone": phone_value,
                "organization": org_value,
            },
        )
        total += 1
    return total


def list_drive_folders(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    limit: int = 100,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    payload = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_DRIVE_BASE_URL}/files",
        params={
            "q": "mimeType='application/vnd.google-apps.folder' and trashed=false",
            "pageSize": max(1, min(limit, 200)),
            "fields": "files(id,name)",
        },
    )
    return [{"id": str(item.get("id") or ""), "name": str(item.get("name") or "")} for item in payload.get("files", [])]


def list_drive_files(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    folder_id: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    parts = ["trashed=false"]
    if folder_id:
        parts.append(f"'{folder_id}' in parents")
    if query:
        escaped = str(query).replace("'", "\\'")
        parts.append(f"name contains '{escaped}'")
    q = " and ".join(parts)
    payload = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_DRIVE_BASE_URL}/files",
        params={
            "q": q,
            "pageSize": max(1, min(limit, 200)),
            "fields": "files(id,name,mimeType)",
        },
    )
    return [
        {"id": str(item.get("id") or ""), "name": str(item.get("name") or ""), "mime_type": item.get("mimeType")}
        for item in payload.get("files", [])
    ]


def list_sheets_spreadsheets(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    query: str | None = None,
    limit: int = 100,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    parts = ["mimeType='application/vnd.google-apps.spreadsheet'", "trashed=false"]
    if query:
        escaped = str(query).replace("'", "\\'")
        parts.append(f"name contains '{escaped}'")
    payload = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_DRIVE_BASE_URL}/files",
        params={
            "q": " and ".join(parts),
            "pageSize": max(1, min(limit, 200)),
            "fields": "files(id,name)",
        },
    )
    return [{"spreadsheet_id": str(item.get("id") or ""), "title": str(item.get("name") or "")} for item in payload.get("files", [])]


def list_sheet_tabs(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    spreadsheet_id: str,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    payload = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_SHEETS_BASE_URL}/{quote(spreadsheet_id, safe='')}",
        params={"fields": "sheets(properties(sheetId,title))"},
    )
    tabs: list[dict] = []
    for item in payload.get("sheets", []):
        props = item.get("properties") or {}
        tabs.append({"title": str(props.get("title") or ""), "sheet_id": props.get("sheetId")})
    return tabs


def list_contact_groups(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    limit: int = 200,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    payload = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_PEOPLE_BASE_URL}/contactGroups",
        params={"pageSize": max(1, min(limit, 1000))},
    )
    rows: list[dict] = []
    for item in payload.get("contactGroups", []):
        rows.append(
            {
                "resource_name": str(item.get("resourceName") or ""),
                "name": str(item.get("name") or item.get("formattedName") or ""),
            }
        )
    return rows


def _calendar_event_payload(payload: dict) -> dict:
    timezone_name = payload.get("timezone") or "UTC"
    request_payload = {
        "summary": payload.get("summary"),
        "description": payload.get("description"),
        "location": payload.get("location"),
        "start": {"dateTime": payload.get("start_datetime"), "timeZone": timezone_name},
        "end": {"dateTime": payload.get("end_datetime"), "timeZone": timezone_name},
        "attendees": [{"email": email_value} for email_value in payload.get("attendees", []) if email_value],
    }
    return request_payload


def _to_calendar_event_read(calendar_id: str, payload: dict) -> dict:
    start_value = (payload.get("start") or {}).get("dateTime") or (payload.get("start") or {}).get("date")
    end_value = (payload.get("end") or {}).get("dateTime") or (payload.get("end") or {}).get("date")
    return {
        "id": str(payload.get("id", "")),
        "calendar_id": calendar_id,
        "status": str(payload.get("status", "confirmed")),
        "html_link": payload.get("htmlLink"),
        "summary": payload.get("summary"),
        "start_datetime": start_value,
        "end_datetime": end_value,
    }


def create_event(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    payload: dict,
) -> dict:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    calendar_id = str(payload.get("calendar_id") or "primary")
    body = _calendar_event_payload(payload)
    result = _google_request(
        method="POST",
        access_token=access_token,
        url=f"{GOOGLE_CALENDAR_BASE_URL}/calendars/{quote(calendar_id, safe='')}/events",
        json_body=body,
    )
    return _to_calendar_event_read(calendar_id, result)


def update_event(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    event_id: str,
    payload: dict,
) -> dict:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    calendar_id = str(payload.get("calendar_id") or "primary")
    body = _calendar_event_payload(payload)
    result = _google_request(
        method="PUT",
        access_token=access_token,
        url=f"{GOOGLE_CALENDAR_BASE_URL}/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
        json_body=body,
    )
    return _to_calendar_event_read(calendar_id, result)


def delete_event(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    calendar_id: str,
    event_id: str,
) -> None:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    _google_request(
        method="DELETE",
        access_token=access_token,
        url=f"{GOOGLE_CALENDAR_BASE_URL}/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
    )


def list_events(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    calendar_id: str = "primary",
    query: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    limit: int = 10,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    params: dict[str, str | int] = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max(1, min(limit, 50)),
    }
    if query:
        params["q"] = query
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max

    try:
        payload = _google_request(
            method="GET",
            access_token=access_token,
            url=f"{GOOGLE_CALENDAR_BASE_URL}/calendars/{quote(calendar_id, safe='')}/events",
            params=params,
        )
    except ValueError as exc:
        raise ValueError(f"calendar '{calendar_id}': {exc}") from exc

    items: list[dict] = []
    for event_item in payload.get("items", []):
        start_value = (event_item.get("start") or {}).get("dateTime") or (event_item.get("start") or {}).get("date")
        end_value = (event_item.get("end") or {}).get("dateTime") or (event_item.get("end") or {}).get("date")
        items.append(
            {
                "id": str(event_item.get("id", "")),
                "calendar_id": calendar_id,
                "summary": event_item.get("summary"),
                "description": event_item.get("description"),
                "location": event_item.get("location"),
                "status": event_item.get("status"),
                "start_datetime": start_value,
                "end_datetime": end_value,
                "html_link": event_item.get("htmlLink"),
            }
        )
    return items


def list_calendars(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    limit: int = 25,
) -> list[dict]:
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    payload = _google_request(
        method="GET",
        access_token=access_token,
        url=f"{GOOGLE_CALENDAR_BASE_URL}/users/me/calendarList",
        params={"maxResults": max(1, min(limit, 100))},
    )

    calendars: list[dict] = []
    for item in payload.get("items", []):
        calendars.append(
            {
                "id": str(item.get("id", "")),
                "summary": str(item.get("summary") or item.get("id") or "Untitled"),
                "primary": bool(item.get("primary", False)),
                "access_role": str(item.get("accessRole") or ""),
                "selected": bool(item.get("selected", False)),
            }
        )
    return calendars


def sync_connector(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
) -> dict[str, int]:
    run = start_sync_run(db, connector.tenant_id, "google", connector.id)

    try:
        if not connector.sync_scope_configured:
            raise ValueError("Sync scope is not configured. Save sync options before running sync.")
        access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)

        counts = {
            "gmail": 0,
            "calendar": 0,
            "drive": 0,
            "sheets": 0,
            "contacts": 0,
        }
        if connector.gmail_enabled:
            counts["gmail"] = sync_gmail(db, connector, access_token=access_token)
        if connector.calendar_enabled:
            counts["calendar"] = sync_calendar(db, connector, access_token=access_token)
        if connector.drive_enabled:
            counts["drive"] = sync_drive(db, connector, access_token=access_token)
        if connector.sheets_enabled:
            counts["sheets"] = sync_sheets(db, connector, access_token=access_token)
        if connector.contacts_enabled:
            counts["contacts"] = sync_contacts(db, connector, access_token=access_token)

        total = sum(counts.values())
        connector.last_items_synced = total
        connector.last_error = None
        connector.last_sync_at = _utcnow()
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=total)
        return {"total": total, **counts}
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise


def append_crm_row(
    db: Session,
    connector: GoogleUserConnector,
    *,
    client_id: str,
    client_secret: str,
    values: list[str],
) -> None:
    if not connector.crm_sheet_spreadsheet_id:
        raise ValueError("CRM sheet spreadsheet id is not configured")
    tab = connector.crm_sheet_tab_name or "Leads"
    access_token = get_valid_access_token(db, connector, client_id=client_id, client_secret=client_secret)
    _google_request(
        method="POST",
        access_token=access_token,
        url=(
            f"{GOOGLE_SHEETS_BASE_URL}/{quote(connector.crm_sheet_spreadsheet_id, safe='')}/values/"
            f"{quote(tab + '!A:Z', safe='!:$')}:append"
        ),
        params={"valueInputOption": "RAW"},
        json_body={"values": [values]},
    )


def disconnect_account(db: Session, connector: GoogleUserConnector) -> int:
    docs = db.execute(
        select(Document).where(
            Document.tenant_id == connector.tenant_id,
            Document.deleted_at.is_(None),
            Document.source_type.in_(["google_gmail", "google_calendar", "google_drive", "google_sheets", "google_contacts"]),
            Document.source_id.like(f"{connector.id}:%"),
        )
    ).scalars().all()

    deleted_docs_count = 0
    for doc in docs:
        soft_delete_document(db, tenant_id=connector.tenant_id, document=doc)
        deleted_docs_count += 1

    if connector.private_acl_policy_id:
        policy = db.get(ACLPolicy, connector.private_acl_policy_id)
        if policy and policy.tenant_id == connector.tenant_id:
            db.delete(policy)

    db.delete(connector)
    db.commit()
    return deleted_docs_count
