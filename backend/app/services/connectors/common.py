from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.acl_policy import ACLPolicy
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.document import Document
from app.services.storage import ensure_raw_storage_ready
from app.services.storage import put_raw_document_blob as put_blob_object


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def put_raw_document_blob(tenant_id: str, source_type: str, source_id: str, payload: dict[str, Any]) -> str:
    object_name = f"{tenant_id}/{source_type}/{source_id}.json"
    return put_blob_object(object_name, payload)


def ensure_bucket() -> None:
    ensure_raw_storage_ready()


def resolve_default_document_acl(db: Session, tenant_id: str) -> str | None:
    policy = db.execute(
        select(ACLPolicy)
        .where(
            ACLPolicy.tenant_id == tenant_id,
            ACLPolicy.policy_type == "document",
            ACLPolicy.resource_id == "*",
            ACLPolicy.active.is_(True),
        )
        .order_by(ACLPolicy.created_at.desc())
    ).scalar_one_or_none()
    return policy.id if policy else None


def start_sync_run(db: Session, tenant_id: str, connector_type: str, connector_config_id: str) -> ConnectorSyncRun:
    run = ConnectorSyncRun(
        tenant_id=tenant_id,
        connector_type=connector_type,
        connector_config_id=connector_config_id,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_sync_run(
    db: Session,
    run: ConnectorSyncRun,
    *,
    status: str,
    items_synced: int,
    error_message: str | None = None,
) -> None:
    run.status = status
    run.items_synced = items_synced
    run.error_message = error_message
    run.finished_at = utcnow()
    db.commit()


def upsert_document(
    db: Session,
    *,
    tenant_id: str,
    source_type: str,
    source_id: str,
    url: str | None,
    title: str,
    author: str | None,
    raw_text: str,
    metadata_json: dict[str, Any],
    source_created_at: datetime | None = None,
    source_updated_at: datetime | None = None,
    acl_policy_id: str | None = None,
) -> Document:
    tags = metadata_json.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    raw_object_key = put_raw_document_blob(
        tenant_id,
        source_type,
        source_id,
        metadata_json | {"raw_text": raw_text, "title": title},
    )

    doc = db.execute(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_type == source_type,
            Document.source_id == source_id,
        )
    ).scalar_one_or_none()

    resolved_acl = acl_policy_id or resolve_default_document_acl(db, tenant_id)
    index_requested_at = utcnow()

    if doc is None:
        doc = Document(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            url=url,
            title=title,
            author=author,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            raw_text=raw_text,
            metadata_json=metadata_json,
            tags_json=tags,
            raw_object_key=raw_object_key,
            acl_policy_id=resolved_acl,
            index_status="pending",
            index_error=None,
            index_attempts=0,
            index_requested_at=index_requested_at,
            next_index_attempt_at=index_requested_at,
        )
        db.add(doc)
    else:
        doc.url = url
        doc.title = title
        doc.author = author
        doc.source_created_at = source_created_at
        doc.source_updated_at = source_updated_at
        doc.raw_text = raw_text
        doc.metadata_json = metadata_json
        doc.tags_json = tags
        doc.raw_object_key = raw_object_key
        if resolved_acl:
            doc.acl_policy_id = resolved_acl
        doc.index_status = "pending"
        doc.index_error = None
        doc.index_attempts = 0
        doc.index_requested_at = index_requested_at
        doc.next_index_attempt_at = index_requested_at

    db.commit()
    db.refresh(doc)
    return doc


def connector_status_payload(connector) -> dict[str, Any]:
    return {
        "enabled": connector.enabled,
        "last_sync_at": connector.last_sync_at,
        "last_items_synced": connector.last_items_synced,
        "last_error": connector.last_error,
    }
