from __future__ import annotations

import email
import imaplib
from datetime import datetime, timezone
from email.header import decode_header

from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.connectors.email_connector import EmailConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            decoded += chunk.decode(charset or "utf-8", errors="ignore")
        else:
            decoded += chunk
    return decoded


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
    return ""


def _connect(connector: EmailConnector):
    password = decrypt_secret(connector.password_encrypted)
    if connector.use_ssl:
        conn = imaplib.IMAP4_SSL(connector.imap_host, connector.imap_port)
    else:
        conn = imaplib.IMAP4(connector.imap_host, connector.imap_port)
    conn.login(connector.username, password)
    return conn


def test_connection(connector: EmailConnector) -> tuple[bool, str]:
    try:
        conn = _connect(connector)
        conn.noop()
        conn.logout()
        return True, "Connected to IMAP successfully"
    except Exception as exc:
        return False, f"Email connection failed: {exc}"


def sync_connector(db: Session, connector: EmailConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "email", connector.id)

    try:
        conn = _connect(connector)
        cursor = dict(connector.sync_cursor or {})
        total = 0

        for folder in connector.folders:
            conn.select(folder)
            since_uid = int(cursor.get(folder, 0))
            status, data = conn.uid("search", None, "ALL")
            if status != "OK":
                continue

            max_uid = since_uid
            for uid_bytes in data[0].split():
                uid = int(uid_bytes.decode("utf-8"))
                if uid <= since_uid:
                    continue

                fetch_status, msg_data = conn.uid("fetch", uid_bytes, "(RFC822)")
                if fetch_status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_value(msg.get("Subject")) or f"Email {uid}"
                sender = _decode_header_value(msg.get("From"))
                body = _extract_body(msg)

                upsert_document(
                    db,
                    tenant_id=connector.tenant_id,
                    source_type="email",
                    source_id=f"{folder}:{uid}",
                    url=None,
                    title=subject,
                    author=sender,
                    source_created_at=datetime.now(timezone.utc),
                    source_updated_at=datetime.now(timezone.utc),
                    raw_text=body,
                    metadata_json={"folder": folder, "uid": uid, "subject": subject, "from": sender},
                )
                total += 1
                max_uid = max(max_uid, uid)

            cursor[folder] = str(max_uid)

        conn.logout()

        connector.sync_cursor = cursor
        connector.last_items_synced = total
        connector.last_error = None
        connector.last_sync_at = datetime.now(timezone.utc)
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=total)
        return total
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise
