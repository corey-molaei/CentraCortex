from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret, random_token
from app.models.connector_oauth_state import ConnectorOAuthState
from app.models.workspace_google_integration import WorkspaceGoogleIntegration
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document

GOOGLE_OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_CALENDAR_BASE_URL = "https://www.googleapis.com/calendar/v3"
GOOGLE_DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"
GOOGLE_SHEETS_BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _configured_scopes() -> list[str]:
    raw_value = settings.google_oauth_scopes.strip()
    if not raw_value:
        return []
    scopes: list[str] = []
    for chunk in raw_value.replace(",", " ").split():
        if chunk and chunk not in scopes:
            scopes.append(chunk)
    return scopes


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


def _parse_email_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def get_or_create_integration(db: Session, *, tenant_id: str) -> WorkspaceGoogleIntegration:
    integration = db.execute(
        select(WorkspaceGoogleIntegration).where(WorkspaceGoogleIntegration.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if integration:
        return integration

    integration = WorkspaceGoogleIntegration(
        tenant_id=tenant_id,
        enabled=True,
        gmail_enabled=True,
        calendar_enabled=True,
        drive_enabled=False,
        sheets_enabled=False,
        gmail_labels=["INBOX", "SENT"],
        calendar_ids=["primary"],
        drive_folder_ids=[],
        sheets_targets=[],
        sync_cursor={},
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


def get_oauth_url(
    db: Session,
    integration: WorkspaceGoogleIntegration,
    *,
    client_id: str,
    redirect_uri: str,
    user_id: str,
) -> tuple[str, str]:
    state = random_token(16)
    db.add(
        ConnectorOAuthState(
            tenant_id=integration.tenant_id,
            user_id=user_id,
            connector_type="google_workspace",
            connector_config_id=integration.id,
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
    integration: WorkspaceGoogleIntegration,
    *,
    code: str,
    state: str,
    client_id: str,
    client_secret: str,
    user_id: str,
) -> None:
    state_row = db.execute(
        select(ConnectorOAuthState).where(
            ConnectorOAuthState.tenant_id == integration.tenant_id,
            ConnectorOAuthState.user_id == user_id,
            ConnectorOAuthState.connector_type == "google_workspace",
            ConnectorOAuthState.connector_config_id == integration.id,
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

    integration.access_token_encrypted = encrypt_secret(access_token)
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        integration.refresh_token_encrypted = encrypt_secret(refresh_token)
    integration.token_expires_at = _utcnow() + timedelta(seconds=int(token_payload.get("expires_in", 3600)))
    integration.scopes = str(token_payload.get("scope", "")).split() or _configured_scopes()
    integration.google_account_email = str(profile.get("email") or "") or None
    integration.google_account_sub = str(profile.get("id") or "") or None

    db.delete(state_row)
    db.commit()


def refresh_access_token(
    db: Session,
    integration: WorkspaceGoogleIntegration,
    *,
    client_id: str,
    client_secret: str,
) -> str:
    if not integration.refresh_token_encrypted:
        raise ValueError("Google refresh token is not configured")

    refresh_token = decrypt_secret(integration.refresh_token_encrypted)
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

    integration.access_token_encrypted = encrypt_secret(access_token)
    integration.token_expires_at = _utcnow() + timedelta(seconds=int(token_payload.get("expires_in", 3600)))
    if token_payload.get("scope"):
        integration.scopes = str(token_payload["scope"]).split()
    db.commit()
    return access_token


def get_valid_access_token(
    db: Session,
    integration: WorkspaceGoogleIntegration,
    *,
    client_id: str,
    client_secret: str,
) -> str:
    if not integration.access_token_encrypted:
        return refresh_access_token(db, integration, client_id=client_id, client_secret=client_secret)

    token_expires_at = _coerce_utc(integration.token_expires_at)
    if token_expires_at is not None and token_expires_at <= _utcnow() + timedelta(seconds=30):
        return refresh_access_token(db, integration, client_id=client_id, client_secret=client_secret)

    return decrypt_secret(integration.access_token_encrypted)


def test_connection(
    db: Session,
    integration: WorkspaceGoogleIntegration,
    *,
    client_id: str,
    client_secret: str,
) -> tuple[bool, str]:
    try:
        access_token = get_valid_access_token(db, integration, client_id=client_id, client_secret=client_secret)
        profile = _google_request(method="GET", access_token=access_token, url=GOOGLE_USERINFO_URL)
        if profile.get("email"):
            integration.google_account_email = profile["email"]
        if profile.get("id"):
            integration.google_account_sub = profile["id"]
        db.commit()
        return True, f"Connected to Google workspace successfully ({profile.get('email', 'unknown account')})"
    except Exception as exc:
        return False, f"Google workspace connection failed: {exc}"


def _sync_gmail(db: Session, integration: WorkspaceGoogleIntegration, *, access_token: str) -> int:
    cursor = dict(integration.sync_cursor or {})
    gmail_cursor = dict(cursor.get("gmail", {}))
    processed = 0

    for label in integration.gmail_labels:
        label_cursor = dict(gmail_cursor.get(label, {}))
        page_token = label_cursor.get("page_token")
        latest_internal = int(label_cursor.get("max_internal_ms") or 0)
        max_seen = latest_internal

        while True:
            payload = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_GMAIL_BASE_URL}/messages",
                params={
                    "maxResults": 100,
                    "labelIds": label,
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            for item in payload.get("messages", []):
                message_id = str(item.get("id") or "")
                if not message_id:
                    continue

                detail = _google_request(
                    method="GET",
                    access_token=access_token,
                    url=f"{GOOGLE_GMAIL_BASE_URL}/messages/{message_id}",
                    params={"format": "full"},
                )
                internal_ms = int(detail.get("internalDate") or 0)
                if internal_ms and internal_ms <= latest_internal:
                    continue

                payload_data = detail.get("payload") or {}
                headers = payload_data.get("headers") or []
                subject = _gmail_header(headers, "Subject") or f"Gmail message {message_id}"
                sender = _gmail_header(headers, "From")
                created_at = _parse_email_date(_gmail_header(headers, "Date"))
                if created_at is None and internal_ms > 0:
                    created_at = datetime.fromtimestamp(internal_ms / 1000, tz=UTC)

                raw_text = _gmail_body(payload_data)
                if not raw_text:
                    raw_text = str(detail.get("snippet") or "")

                upsert_document(
                    db,
                    tenant_id=integration.tenant_id,
                    source_type="google_gmail",
                    source_id=f"workspace:{integration.id}:gmail:{message_id}",
                    url=None,
                    title=subject,
                    author=sender,
                    source_created_at=created_at,
                    source_updated_at=created_at,
                    raw_text=raw_text,
                    metadata_json={
                        "source_type": "google_gmail",
                        "google_workspace_integration_id": integration.id,
                        "google_account_email": integration.google_account_email,
                        "gmail_label": label,
                        "thread_id": detail.get("threadId"),
                        "message_id": message_id,
                    },
                )
                processed += 1
                if internal_ms:
                    max_seen = max(max_seen, internal_ms)

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        gmail_cursor[label] = {"max_internal_ms": max_seen}

    cursor["gmail"] = gmail_cursor
    integration.sync_cursor = cursor
    db.commit()
    return processed


def _sync_calendar(db: Session, integration: WorkspaceGoogleIntegration, *, access_token: str) -> int:
    cursor = dict(integration.sync_cursor or {})
    calendar_cursor = dict(cursor.get("calendar", {}))
    processed = 0

    for calendar_id in integration.calendar_ids:
        max_updated = str(calendar_cursor.get(calendar_id) or "")
        page_token: str | None = None

        while True:
            params = {
                "singleEvents": "true",
                "maxResults": 250,
                **({"updatedMin": max_updated} if max_updated else {}),
                **({"pageToken": page_token} if page_token else {}),
            }
            payload = _google_request(
                method="GET",
                access_token=access_token,
                url=f"{GOOGLE_CALENDAR_BASE_URL}/calendars/{quote(calendar_id, safe='')}/events",
                params=params,
            )
            for event_item in payload.get("items", []):
                event_id = str(event_item.get("id") or "")
                if not event_id:
                    continue

                updated = str(event_item.get("updated") or "")
                if updated and updated > max_updated:
                    max_updated = updated

                start_dt = (event_item.get("start") or {}).get("dateTime") or (event_item.get("start") or {}).get("date")
                end_dt = (event_item.get("end") or {}).get("dateTime") or (event_item.get("end") or {}).get("date")
                details = [
                    str(event_item.get("summary") or ""),
                    str(event_item.get("description") or ""),
                    str(event_item.get("location") or ""),
                    f"Start: {start_dt}" if start_dt else "",
                    f"End: {end_dt}" if end_dt else "",
                ]
                raw_text = "\n".join([line for line in details if line]) or f"Calendar event {event_id}"

                upsert_document(
                    db,
                    tenant_id=integration.tenant_id,
                    source_type="google_calendar",
                    source_id=f"workspace:{integration.id}:calendar:{calendar_id}:{event_id}",
                    url=event_item.get("htmlLink"),
                    title=event_item.get("summary") or f"Calendar event {event_id}",
                    author=integration.google_account_email,
                    source_created_at=_coerce_utc(datetime.fromisoformat(updated.replace("Z", "+00:00"))) if updated else None,
                    source_updated_at=_coerce_utc(datetime.fromisoformat(updated.replace("Z", "+00:00"))) if updated else None,
                    raw_text=raw_text,
                    metadata_json={
                        "source_type": "google_calendar",
                        "google_workspace_integration_id": integration.id,
                        "google_account_email": integration.google_account_email,
                        "calendar_id": calendar_id,
                        "event_id": event_id,
                        "status": event_item.get("status"),
                    },
                )
                processed += 1

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        if max_updated:
            calendar_cursor[calendar_id] = max_updated

    cursor["calendar"] = calendar_cursor
    integration.sync_cursor = cursor
    db.commit()
    return processed


def _sync_drive(db: Session, integration: WorkspaceGoogleIntegration, *, access_token: str) -> int:
    if not integration.drive_folder_ids:
        return 0

    processed = 0
    for folder_id in integration.drive_folder_ids:
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
                    "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)",
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            for item in payload.get("files", []):
                file_id = str(item.get("id") or "")
                if not file_id:
                    continue
                name = str(item.get("name") or file_id)
                mime_type = str(item.get("mimeType") or "")
                modified_time = str(item.get("modifiedTime") or "")
                source_updated_at = None
                if modified_time:
                    try:
                        source_updated_at = datetime.fromisoformat(modified_time.replace("Z", "+00:00")).astimezone(UTC)
                    except ValueError:
                        source_updated_at = None

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

                upsert_document(
                    db,
                    tenant_id=integration.tenant_id,
                    source_type="google_drive",
                    source_id=f"workspace:{integration.id}:drive:{file_id}",
                    url=item.get("webViewLink"),
                    title=name,
                    author=integration.google_account_email,
                    source_created_at=source_updated_at,
                    source_updated_at=source_updated_at,
                    raw_text=raw_text,
                    metadata_json={
                        "source_type": "google_drive",
                        "google_workspace_integration_id": integration.id,
                        "folder_id": folder_id,
                        "file_id": file_id,
                        "mime_type": mime_type,
                    },
                )
                processed += 1

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

    return processed


def _sync_sheets(db: Session, integration: WorkspaceGoogleIntegration, *, access_token: str) -> int:
    processed = 0
    for target in integration.sheets_targets:
        spreadsheet_id = str(target.get("spreadsheet_id") or "").strip()
        if not spreadsheet_id:
            continue
        target_range = str(target.get("range") or "A:Z")
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

        lines = [", ".join([str(cell) for cell in row]) for row in values]
        raw_text = "\n".join(lines)

        upsert_document(
            db,
            tenant_id=integration.tenant_id,
            source_type="google_sheets",
            source_id=f"workspace:{integration.id}:sheets:{spreadsheet_id}:{tab_name or 'sheet'}:{target_range}",
            url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
            title=f"Sheet {spreadsheet_id} {tab_name or ''} {target_range}".strip(),
            author=integration.google_account_email,
            source_created_at=None,
            source_updated_at=_utcnow(),
            raw_text=raw_text,
            metadata_json={
                "source_type": "google_sheets",
                "google_workspace_integration_id": integration.id,
                "spreadsheet_id": spreadsheet_id,
                "tab": tab_name,
                "range": target_range,
            },
        )
        processed += 1

    return processed


def sync_connector(
    db: Session,
    integration: WorkspaceGoogleIntegration,
    *,
    client_id: str,
    client_secret: str,
) -> dict[str, int]:
    run = start_sync_run(db, integration.tenant_id, "google_workspace", integration.id)
    try:
        access_token = get_valid_access_token(db, integration, client_id=client_id, client_secret=client_secret)
        counts = {"gmail": 0, "calendar": 0, "drive": 0, "sheets": 0}

        if integration.enabled and integration.gmail_enabled:
            counts["gmail"] = _sync_gmail(db, integration, access_token=access_token)
        if integration.enabled and integration.calendar_enabled:
            counts["calendar"] = _sync_calendar(db, integration, access_token=access_token)
        if integration.enabled and integration.drive_enabled:
            counts["drive"] = _sync_drive(db, integration, access_token=access_token)
        if integration.enabled and integration.sheets_enabled:
            counts["sheets"] = _sync_sheets(db, integration, access_token=access_token)

        total = sum(counts.values())
        integration.last_sync_at = _utcnow()
        integration.last_items_synced = total
        integration.last_error = None
        db.commit()
        finish_sync_run(db, run, status="success", items_synced=total)
        return {"total": total, **counts}
    except Exception as exc:
        integration.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise


def append_crm_row(
    db: Session,
    integration: WorkspaceGoogleIntegration,
    *,
    client_id: str,
    client_secret: str,
    values: list[str],
) -> None:
    if not integration.crm_sheet_spreadsheet_id:
        raise ValueError("CRM sheet spreadsheet id is not configured")
    tab = integration.crm_sheet_tab_name or "Leads"
    access_token = get_valid_access_token(db, integration, client_id=client_id, client_secret=client_secret)
    _google_request(
        method="POST",
        access_token=access_token,
        url=(
            f"{GOOGLE_SHEETS_BASE_URL}/{quote(integration.crm_sheet_spreadsheet_id, safe='')}/values/"
            f"{quote(tab + '!A:Z', safe='!:$')}:append"
        ),
        params={"valueInputOption": "RAW"},
        json_body={"values": [values]},
    )
