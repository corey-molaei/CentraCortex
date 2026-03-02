from __future__ import annotations

import email
import imaplib
import smtplib
from datetime import UTC, datetime
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.acl_policy import ACLPolicy
from app.models.connectors.email_user_connector import EmailUserConnector
from app.models.document import Document
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document
from app.services.document_indexing import soft_delete_document


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
            disposition = str(part.get("Content-Disposition", "")).lower()
            if part.get_content_type() == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
    return ""


def _connect_imap(account: EmailUserConnector):
    password = decrypt_secret(account.password_encrypted)
    if account.use_ssl:
        conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
    else:
        conn = imaplib.IMAP4(account.imap_host, account.imap_port)
    conn.login(account.username, password)
    return conn


def _connect_smtp(account: EmailUserConnector):
    if not account.smtp_host or not account.smtp_port:
        return None

    password = decrypt_secret(account.password_encrypted)
    conn = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=30)
    conn.ehlo()
    if account.smtp_use_starttls:
        conn.starttls()
        conn.ehlo()
    conn.login(account.username, password)
    return conn


def _account_resource_id(account_id: str) -> str:
    return f"imap_account:{account_id}"


def ensure_private_acl_policy(db: Session, account: EmailUserConnector) -> str:
    if account.private_acl_policy_id:
        existing = db.get(ACLPolicy, account.private_acl_policy_id)
        if existing and existing.tenant_id == account.tenant_id:
            return existing.id

    resource_id = _account_resource_id(account.id)
    policy = db.execute(
        select(ACLPolicy).where(
            ACLPolicy.tenant_id == account.tenant_id,
            ACLPolicy.policy_type == "document",
            ACLPolicy.resource_id == resource_id,
        )
    ).scalar_one_or_none()

    if policy is None:
        policy = ACLPolicy(
            tenant_id=account.tenant_id,
            name=f"IMAP Account {account.id}",
            policy_type="document",
            resource_id=resource_id,
            allow_all=False,
            allowed_user_ids=[account.user_id],
            allowed_group_ids=[],
            allowed_role_names=[],
            active=True,
        )
        db.add(policy)
        db.flush()
    else:
        policy.allow_all = False
        policy.active = True
        if account.user_id not in (policy.allowed_user_ids or []):
            policy.allowed_user_ids = [account.user_id]

    account.private_acl_policy_id = policy.id
    db.commit()
    return policy.id


def test_connection(account: EmailUserConnector) -> tuple[bool, str]:
    try:
        conn = _connect_imap(account)
        conn.noop()
        conn.logout()

        smtp_conn = _connect_smtp(account)
        if smtp_conn is not None:
            smtp_conn.noop()
            smtp_conn.quit()
        return True, "Connected to IMAP successfully"
    except Exception as exc:
        return False, f"Email connection failed: {exc}"


def sync_connector(db: Session, account: EmailUserConnector) -> int:
    run = start_sync_run(db, account.tenant_id, "email_user", account.id)
    ensure_private_acl_policy(db, account)

    try:
        conn = _connect_imap(account)
        cursor = dict(account.sync_cursor or {})
        total = 0

        for folder in account.folders:
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
                sent_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(UTC)
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=UTC)
                sent_at = sent_at.astimezone(UTC)

                upsert_document(
                    db,
                    tenant_id=account.tenant_id,
                    source_type="imap_email",
                    source_id=f"{account.id}:{folder}:{uid}",
                    url=None,
                    title=subject,
                    author=sender,
                    source_created_at=sent_at,
                    source_updated_at=sent_at,
                    raw_text=body,
                    metadata_json={
                        "folder": folder,
                        "uid": uid,
                        "subject": subject,
                        "from": sender,
                        "email_account_id": account.id,
                        "email_address": account.email_address,
                    },
                    acl_policy_id=account.private_acl_policy_id,
                )
                total += 1
                max_uid = max(max_uid, uid)

            cursor[folder] = str(max_uid)

        conn.logout()

        account.sync_cursor = cursor
        account.last_items_synced = total
        account.last_error = None
        account.last_sync_at = datetime.now(UTC)
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=total)
        return total
    except Exception as exc:
        account.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise


def list_messages(
    account: EmailUserConnector,
    *,
    folder: str = "INBOX",
    limit: int = 10,
    query: str | None = None,
) -> list[dict]:
    conn = _connect_imap(account)
    try:
        conn.select(folder)
        status, data = conn.uid("search", None, "ALL")
        if status != "OK":
            return []

        all_uids = [uid.decode("utf-8") for uid in data[0].split()]
        all_uids = list(reversed(all_uids))

        results: list[dict] = []
        for uid in all_uids:
            uid_bytes = uid.encode("utf-8")
            fetch_status, msg_data = conn.uid("fetch", uid_bytes, "(RFC822)")
            if fetch_status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_header_value(msg.get("Subject")) or "(No Subject)"
            sender = _decode_header_value(msg.get("From"))
            body = _extract_body(msg)
            sent_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(UTC)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=UTC)
            sent_at = sent_at.astimezone(UTC)

            haystack = f"{subject}\n{sender}\n{body}".lower()
            if query and query.lower() not in haystack:
                continue

            results.append(
                {
                    "id": f"{folder}:{uid}",
                    "folder": folder,
                    "uid": uid,
                    "subject": subject,
                    "from": sender,
                    "sent_at": sent_at.isoformat(),
                    "snippet": body[:400],
                    "body": body,
                }
            )
            if len(results) >= limit:
                break
        return results
    finally:
        conn.logout()


def read_message(account: EmailUserConnector, *, message_id: str) -> dict | None:
    parts = message_id.split(":", 1)
    if len(parts) != 2:
        return None
    folder, uid = parts
    conn = _connect_imap(account)
    try:
        conn.select(folder)
        fetch_status, msg_data = conn.uid("fetch", uid.encode("utf-8"), "(RFC822)")
        if fetch_status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
            return None
        msg = email.message_from_bytes(msg_data[0][1])
        subject = _decode_header_value(msg.get("Subject")) or "(No Subject)"
        sender = _decode_header_value(msg.get("From"))
        sent_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(UTC)
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=UTC)
        sent_at = sent_at.astimezone(UTC)
        body = _extract_body(msg)
        return {
            "id": message_id,
            "folder": folder,
            "uid": uid,
            "subject": subject,
            "from": sender,
            "to": _decode_header_value(msg.get("To")),
            "date": _decode_header_value(msg.get("Date")),
            "sent_at": sent_at.isoformat(),
            "snippet": body[:400],
            "body": body,
        }
    finally:
        conn.logout()


def send_message(
    account: EmailUserConnector,
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict:
    if not account.smtp_host or not account.smtp_port:
        raise ValueError("SMTP is not configured for this account")

    cc = cc or []
    bcc = bcc or []
    recipients = [*to, *cc, *bcc]
    if not recipients:
        raise ValueError("At least one recipient is required")

    msg = EmailMessage()
    msg["From"] = account.email_address
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)

    smtp_conn = _connect_smtp(account)
    if smtp_conn is None:
        raise ValueError("SMTP is not configured for this account")
    try:
        response = smtp_conn.send_message(msg, from_addr=account.email_address, to_addrs=recipients)
    finally:
        smtp_conn.quit()

    return {
        "provider_message_id": msg.get("Message-ID"),
        "failed_recipients": list(response.keys()),
    }


def disconnect_account(db: Session, account: EmailUserConnector) -> int:
    docs = db.execute(
        select(Document).where(
            Document.tenant_id == account.tenant_id,
            Document.deleted_at.is_(None),
            Document.source_type == "imap_email",
            Document.source_id.like(f"{account.id}:%"),
        )
    ).scalars().all()

    deleted_docs_count = 0
    for doc in docs:
        soft_delete_document(db, tenant_id=account.tenant_id, document=doc)
        deleted_docs_count += 1

    if account.private_acl_policy_id:
        policy = db.get(ACLPolicy, account.private_acl_policy_id)
        if policy and policy.tenant_id == account.tenant_id:
            db.delete(policy)

    db.delete(account)
    db.commit()
    return deleted_docs_count
