from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.connector_sync_run import ConnectorSyncRun
from app.models.document import Document
from app.models.document_chunk import DocumentChunk

INDEX_BUCKETS = {"indexed", "pending", "retry", "failed"}


def build_knowledge_health(db: Session, *, tenant_id: str) -> dict:
    docs = db.execute(
        select(
            Document.source_type,
            Document.index_status,
            func.count(Document.id),
            func.max(Document.source_updated_at),
        ).where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        ).group_by(Document.source_type, Document.index_status)
    ).all()

    by_source: dict[str, dict] = defaultdict(
        lambda: {
            "documents": 0,
            "indexed": 0,
            "pending": 0,
            "retry": 0,
            "failed": 0,
            "last_source_update_at": None,
        }
    )

    for source_type, index_status, count, last_update in docs:
        source = by_source[str(source_type)]
        source["documents"] += int(count or 0)
        status = str(index_status or "pending")
        if status in INDEX_BUCKETS:
            source[status] += int(count or 0)
        if isinstance(last_update, datetime):
            current = source["last_source_update_at"]
            if current is None or last_update > current:
                source["last_source_update_at"] = last_update

    total_documents = sum(item["documents"] for item in by_source.values())
    total_chunks = int(
        db.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.tenant_id == tenant_id)).scalar_one() or 0
    )
    latest_sync_at = db.execute(
        select(func.max(ConnectorSyncRun.finished_at)).where(ConnectorSyncRun.tenant_id == tenant_id)
    ).scalar_one_or_none()

    recent_errors = db.execute(
        select(ConnectorSyncRun.error_message)
        .where(
            ConnectorSyncRun.tenant_id == tenant_id,
            ConnectorSyncRun.status == "failed",
            ConnectorSyncRun.error_message.is_not(None),
        )
        .order_by(ConnectorSyncRun.started_at.desc())
        .limit(20)
    ).scalars().all()

    sources = [
        {"source_type": source_type, **payload}
        for source_type, payload in sorted(by_source.items(), key=lambda item: item[0])
    ]

    return {
        "tenant_id": tenant_id,
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "latest_sync_at": latest_sync_at,
        "sources": sources,
        "recent_errors": [str(item) for item in recent_errors if item],
    }
