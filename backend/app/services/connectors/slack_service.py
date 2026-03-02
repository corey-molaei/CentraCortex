from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret, random_token
from app.models.connector_oauth_state import ConnectorOAuthState
from app.models.connectors.slack_connector import SlackConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def _ts_to_datetime(ts_value: str | None) -> datetime | None:
    if not ts_value:
        return None
    try:
        return datetime.fromtimestamp(float(ts_value), tz=timezone.utc)
    except ValueError:
        return None


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_oauth_url(db: Session, connector: SlackConnector, client_id: str, redirect_uri: str) -> tuple[str, str]:
    state = random_token(16)
    db.add(
        ConnectorOAuthState(
            tenant_id=connector.tenant_id,
            connector_type="slack",
            state_token=state,
            redirect_uri=redirect_uri,
            expires_at=datetime.now(timezone.utc).replace(microsecond=0),
        )
    )
    db.commit()

    params = urlencode(
        {
            "client_id": client_id,
            "scope": "channels:history,channels:read,groups:history,groups:read,im:history,mpim:history",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"https://slack.com/oauth/v2/authorize?{params}", state


def complete_oauth(db: Session, connector: SlackConnector, *, code: str, state: str, client_id: str, client_secret: str) -> None:
    state_row = db.execute(
        select(ConnectorOAuthState).where(
            ConnectorOAuthState.tenant_id == connector.tenant_id,
            ConnectorOAuthState.connector_type == "slack",
            ConnectorOAuthState.state_token == state,
        )
    ).scalar_one_or_none()
    if not state_row:
        raise ValueError("Invalid OAuth state")

    with httpx.Client(timeout=20) as client:
        response = client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": state_row.redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()

    if not payload.get("ok"):
        raise ValueError(f"Slack OAuth failed: {payload.get('error')}")

    connector.bot_token_encrypted = encrypt_secret(payload["access_token"])
    connector.team_id = (payload.get("team") or {}).get("id")
    connector.workspace_name = (payload.get("team") or {}).get("name")
    db.delete(state_row)
    db.commit()


def test_connection(connector: SlackConnector) -> tuple[bool, str]:
    if not connector.bot_token_encrypted:
        return False, "Slack bot token is not configured"

    token = decrypt_secret(connector.bot_token_encrypted)
    try:
        with httpx.Client(timeout=20) as client:
            response = client.get("https://slack.com/api/auth.test", headers=_auth_headers(token))
            response.raise_for_status()
            data = response.json()
        if not data.get("ok"):
            return False, f"Slack auth failed: {data.get('error')}"
        return True, "Connected to Slack successfully"
    except Exception as exc:
        return False, f"Slack connection failed: {exc}"


def sync_connector(db: Session, connector: SlackConnector) -> int:
    if not connector.bot_token_encrypted:
        raise ValueError("Slack token not configured")

    run = start_sync_run(db, connector.tenant_id, "slack", connector.id)
    token = decrypt_secret(connector.bot_token_encrypted)
    headers = _auth_headers(token)

    try:
        count = 0
        cursor = dict(connector.sync_cursor or {})

        with httpx.Client(timeout=30) as client:
            for channel_id in connector.channel_ids:
                oldest = cursor.get(channel_id)
                response = client.get(
                    "https://slack.com/api/conversations.history",
                    headers=headers,
                    params={"channel": channel_id, **({"oldest": oldest} if oldest else {})},
                )
                response.raise_for_status()
                history = response.json()

                if not history.get("ok"):
                    raise ValueError(f"Slack history failed: {history.get('error')}")

                max_ts = oldest
                for msg in history.get("messages", []):
                    ts = msg.get("ts")
                    if ts and (max_ts is None or float(ts) > float(max_ts)):
                        max_ts = ts

                    thread_text = ""
                    if msg.get("thread_ts") and int(msg.get("reply_count", 0)) > 0:
                        replies = client.get(
                            "https://slack.com/api/conversations.replies",
                            headers=headers,
                            params={"channel": channel_id, "ts": msg["thread_ts"]},
                        )
                        replies.raise_for_status()
                        replies_payload = replies.json()
                        thread_text = "\n".join(r.get("text", "") for r in replies_payload.get("messages", [])[1:])

                    raw_text = f"{msg.get('text', '')}\nThread:\n{thread_text}".strip()
                    source_id = f"{channel_id}:{ts}"
                    url = None
                    if ts:
                        url = f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="slack",
                        source_id=source_id,
                        url=url,
                        title=f"Slack message {source_id}",
                        author=msg.get("user"),
                        source_created_at=_ts_to_datetime(ts),
                        source_updated_at=_ts_to_datetime(ts),
                        raw_text=raw_text,
                        metadata_json={"channel_id": channel_id, "message": msg},
                    )
                    count += 1

                if max_ts:
                    cursor[channel_id] = max_ts

        connector.sync_cursor = cursor
        connector.last_items_synced = count
        connector.last_error = None
        connector.last_sync_at = datetime.now(timezone.utc)
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=count)
        return count
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise
