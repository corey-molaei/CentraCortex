from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.acl import get_accessible_documents
from app.services.storage import delete_raw_document_blob

logger = structlog.get_logger(__name__)
INDEX_STATUS_PENDING = "pending"
INDEX_STATUS_INDEXED = "indexed"
INDEX_STATUS_RETRY = "retry"
INDEX_STATUS_FAILED = "failed"


@dataclass
class ChunkSearchResult:
    chunk: DocumentChunk
    score: float
    ranker: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def tenant_collection_name(tenant_id: str) -> str:
    return f"tenant_{tenant_id}"


def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout_seconds)


def _ensure_tenant_collection(tenant_id: str) -> None:
    collection_name = tenant_collection_name(tenant_id)
    client = _qdrant_client()
    if client.collection_exists(collection_name):
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config=qmodels.VectorParams(
            size=settings.embedding_dimension,
            distance=qmodels.Distance.COSINE,
        ),
    )


def _split_text(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    max_chars = max(settings.chunk_size_chars, 200)
    overlap = min(max(settings.chunk_overlap_chars, 0), max_chars // 2)
    chunks: list[str] = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(start + max_chars, length)
        chunk = normalized[start:end]
        if end < length:
            last_space = chunk.rfind(" ")
            if last_space > max_chars // 2:
                end = start + last_space
                chunk = normalized[start:end]
        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def embed_text(text: str) -> list[float]:
    dim = settings.embedding_dimension
    vector = [0.0] * dim
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    if not tokens:
        vector[0] = 1.0
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        vector[0] = 1.0
        norm = 1.0
    return [v / norm for v in vector]


def _delete_qdrant_document_points(tenant_id: str, document_id: str) -> None:
    try:
        _ensure_tenant_collection(tenant_id)
        client = _qdrant_client()
        client.delete(
            collection_name=tenant_collection_name(tenant_id),
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
    except Exception as exc:  # pragma: no cover - network-dependent path
        logger.warning("qdrant_delete_failed", tenant_id=tenant_id, document_id=document_id, error=str(exc))


def _upsert_qdrant_chunks(tenant_id: str, document: Document, chunks: list[DocumentChunk]) -> None:
    try:
        _ensure_tenant_collection(tenant_id)
        client = _qdrant_client()
        points = [
            qmodels.PointStruct(
                id=chunk.id,
                vector=chunk.embedding_vector,
                payload={
                    "tenant_id": tenant_id,
                    "document_id": document.id,
                    "chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_version": chunk.chunk_version,
                    "acl_policy_id": chunk.acl_policy_id,
                    "source_type": document.source_type,
                    "source_id": document.source_id,
                    "title": document.title,
                    "url": document.url,
                },
            )
            for chunk in chunks
        ]
        if points:
            client.upsert(collection_name=tenant_collection_name(tenant_id), points=points, wait=True)
    except Exception as exc:  # pragma: no cover - network-dependent path
        logger.warning("qdrant_upsert_failed", tenant_id=tenant_id, document_id=document.id, error=str(exc))


def index_document(db: Session, *, tenant_id: str, document: Document) -> tuple[int, int]:
    if document.tenant_id != tenant_id:
        raise ValueError("Cross-tenant indexing is forbidden")
    if document.deleted_at is not None:
        raise ValueError("Document is deleted")

    text = document.raw_text or ""
    chunks_text = _split_text(text)
    next_version = document.current_chunk_version + 1

    db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.chunk_version == next_version,
        )
    )
    db.commit()

    chunks: list[DocumentChunk] = []
    for idx, chunk_text in enumerate(chunks_text):
        embedding = embed_text(chunk_text)
        chunk = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=idx,
            chunk_version=next_version,
            content=chunk_text,
            token_count=len(chunk_text.split()),
            embedding_model="hash-v1",
            embedding_vector=embedding,
            acl_policy_id=document.acl_policy_id,
            metadata_json={
                "source_type": document.source_type,
                "source_id": document.source_id,
                "title": document.title,
                "url": document.url,
            },
        )
        db.add(chunk)
        chunks.append(chunk)

    document.current_chunk_version = next_version
    document.indexed_at = utcnow()
    document.index_status = INDEX_STATUS_INDEXED
    document.index_error = None
    document.index_attempts = 0
    document.next_index_attempt_at = None
    db.commit()
    for chunk in chunks:
        db.refresh(chunk)

    _delete_qdrant_document_points(tenant_id, document.id)
    _upsert_qdrant_chunks(tenant_id, document, chunks)
    return next_version, len(chunks)


def index_pending_documents(
    db: Session,
    *,
    batch_size: int = 100,
    max_retries: int = 5,
    backoff_base_seconds: int = 15,
    max_backoff_seconds: int = 900,
) -> dict[str, int | list[str]]:
    now = utcnow()
    docs = (
        db.execute(
            select(Document)
            .where(
                Document.deleted_at.is_(None),
                Document.index_status.in_([INDEX_STATUS_PENDING, INDEX_STATUS_RETRY]),
                or_(
                    Document.next_index_attempt_at.is_(None),
                    Document.next_index_attempt_at <= now,
                ),
            )
            .order_by(func.coalesce(Document.index_requested_at, Document.updated_at).asc())
            .limit(max(1, batch_size))
        )
        .scalars()
        .all()
    )

    stats: dict[str, int | list[str]] = {
        "processed": 0,
        "indexed": 0,
        "retry": 0,
        "failed": 0,
        "indexed_document_ids": [],
        "retry_document_ids": [],
        "failed_document_ids": [],
    }
    for doc in docs:
        stats["processed"] = int(stats["processed"]) + 1
        try:
            index_document(db, tenant_id=doc.tenant_id, document=doc)
            stats["indexed"] = int(stats["indexed"]) + 1
            cast(list[str], stats["indexed_document_ids"]).append(doc.id)
        except Exception as exc:  # pragma: no cover - covered via tests with monkeypatch
            attempts = (doc.index_attempts or 0) + 1
            doc.index_attempts = attempts
            doc.index_error = str(exc)
            doc.index_requested_at = doc.index_requested_at or now
            if attempts >= max_retries:
                doc.index_status = INDEX_STATUS_FAILED
                doc.next_index_attempt_at = None
                stats["failed"] = int(stats["failed"]) + 1
                cast(list[str], stats["failed_document_ids"]).append(doc.id)
            else:
                doc.index_status = INDEX_STATUS_RETRY
                backoff = min((2**attempts) * backoff_base_seconds, max_backoff_seconds)
                doc.next_index_attempt_at = now + timedelta(seconds=backoff)
                stats["retry"] = int(stats["retry"]) + 1
                cast(list[str], stats["retry_document_ids"]).append(doc.id)
            db.commit()
            logger.warning(
                "document_auto_index_failed",
                document_id=doc.id,
                tenant_id=doc.tenant_id,
                attempts=attempts,
                status=doc.index_status,
                error=str(exc),
            )

    return stats


def get_document_chunks(db: Session, *, tenant_id: str, document_id: str, version: int | None = None) -> list[DocumentChunk]:
    doc = db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if not doc:
        return []

    chunk_version = version if version is not None else doc.current_chunk_version
    if chunk_version <= 0:
        return []

    return (
        db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_version == chunk_version,
            )
            .order_by(DocumentChunk.chunk_index.asc())
        )
        .scalars()
        .all()
    )


def list_accessible_documents(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    source_type: str | None = None,
    tag: str | None = None,
    acl_policy_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    q: str | None = None,
) -> list[Document]:
    docs = get_accessible_documents(db, tenant_id, user_id)
    query_lower = q.lower().strip() if q else None
    tag_lower = tag.lower().strip() if tag else None

    filtered: list[Document] = []
    for doc in docs:
        if doc.deleted_at is not None:
            continue
        if source_type and doc.source_type != source_type:
            continue
        if acl_policy_id and doc.acl_policy_id != acl_policy_id:
            continue
        if created_from and doc.created_at < created_from:
            continue
        if created_to and doc.created_at > created_to:
            continue
        if tag_lower:
            tags = [str(t).lower() for t in (doc.tags_json or [])]
            if tag_lower not in tags:
                continue
        if query_lower:
            title = (doc.title or "").lower()
            body = (doc.raw_text or "").lower()
            if query_lower not in title and query_lower not in body:
                continue
        filtered.append(doc)

    filtered.sort(key=lambda d: d.updated_at, reverse=True)
    return filtered


def forget_document(db: Session, *, tenant_id: str, document: Document) -> None:
    if document.tenant_id != tenant_id:
        raise ValueError("Cross-tenant delete is forbidden")

    _delete_qdrant_document_points(tenant_id, document.id)
    if document.raw_object_key:
        delete_raw_document_blob(document.raw_object_key)

    db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
        )
    )
    db.delete(document)
    db.commit()


def soft_delete_document(db: Session, *, tenant_id: str, document: Document) -> None:
    if document.tenant_id != tenant_id:
        raise ValueError("Cross-tenant delete is forbidden")

    _delete_qdrant_document_points(tenant_id, document.id)
    db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
        )
    )
    document.deleted_at = utcnow()
    db.commit()


def _bm25_chunks(
    db: Session,
    *,
    tenant_id: str,
    accessible_doc_ids: list[str],
    query: str,
    limit: int,
) -> list[ChunkSearchResult]:
    if not accessible_doc_ids:
        return []

    dialect = db.get_bind().dialect.name if db.get_bind() else "sqlite"
    if dialect == "postgresql":
        vector = func.to_tsvector("english", DocumentChunk.content)
        tokens = [token for token in re.findall(r"[a-z0-9_]+", query.lower()) if len(token) >= 2]
        if tokens:
            tsquery_text = " | ".join(tokens)
            ts_query = func.to_tsquery("english", tsquery_text)
        else:
            ts_query = func.plainto_tsquery("english", query)
        stmt = (
            select(DocumentChunk, func.ts_rank_cd(vector, ts_query).label("score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id.in_(accessible_doc_ids),
                Document.deleted_at.is_(None),
                DocumentChunk.chunk_version == Document.current_chunk_version,
                vector.op("@@")(ts_query),
            )
            .order_by(desc("score"))
            .limit(limit)
        )
        rows = db.execute(stmt).all()
        return [ChunkSearchResult(chunk=row[0], score=float(row[1]), ranker="bm25") for row in rows]

    tokens = [token for token in re.findall(r"[a-z0-9_]+", query.lower()) if len(token) >= 3]
    if not tokens:
        tokens = [query.lower().strip()]
    conditions = [func.lower(DocumentChunk.content).like(f"%{token}%") for token in tokens if token]
    if not conditions:
        return []
    rows = (
        db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id.in_(accessible_doc_ids),
                Document.deleted_at.is_(None),
                DocumentChunk.chunk_version == Document.current_chunk_version,
                or_(*conditions),
            )
            .limit(limit)
        )
        .all()
    )
    results: list[ChunkSearchResult] = []
    for chunk, _document in rows:
        score = float(sum(chunk.content.lower().count(token) for token in tokens))
        if score <= 0:
            score = 1.0
        results.append(ChunkSearchResult(chunk=chunk, score=score, ranker="like"))
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def _vector_chunks(
    db: Session,
    *,
    tenant_id: str,
    accessible_doc_ids: list[str],
    query: str,
    limit: int,
) -> list[ChunkSearchResult]:
    if not accessible_doc_ids:
        return []

    try:
        _ensure_tenant_collection(tenant_id)
        client = _qdrant_client()
        vector = embed_text(query)
        hits = client.search(
            collection_name=tenant_collection_name(tenant_id),
            query_vector=vector,
            limit=limit,
            with_payload=True,
        )
    except Exception as exc:  # pragma: no cover - network-dependent path
        logger.warning("qdrant_search_failed", tenant_id=tenant_id, error=str(exc))
        return []

    chunk_ids = [str(hit.id) for hit in hits]
    if not chunk_ids:
        return []

    chunks_by_id = {
        chunk.id: chunk
        for chunk in db.execute(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.document_id.in_(accessible_doc_ids),
                Document.deleted_at.is_(None),
                DocumentChunk.chunk_version == Document.current_chunk_version,
            )
        )
        .scalars()
        .all()
    }
    results: list[ChunkSearchResult] = []
    for hit in hits:
        chunk = chunks_by_id.get(str(hit.id))
        if not chunk:
            continue
        score = float(hit.score if hit.score is not None else 0.0)
        results.append(ChunkSearchResult(chunk=chunk, score=score, ranker="vector"))
    return results


def hybrid_search_chunks(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    query: str,
    limit: int,
) -> list[ChunkSearchResult]:
    accessible_docs = get_accessible_documents(db, tenant_id, user_id)
    accessible_doc_ids = [doc.id for doc in accessible_docs if doc.deleted_at is None]
    if not accessible_doc_ids:
        return []

    bm25 = _bm25_chunks(db, tenant_id=tenant_id, accessible_doc_ids=accessible_doc_ids, query=query, limit=limit * 3)
    vector = _vector_chunks(db, tenant_id=tenant_id, accessible_doc_ids=accessible_doc_ids, query=query, limit=limit * 3)

    combined: dict[str, ChunkSearchResult] = {}
    for item in bm25:
        combined[item.chunk.id] = ChunkSearchResult(chunk=item.chunk, score=item.score * 0.45, ranker=item.ranker)
    for item in vector:
        if item.chunk.id in combined:
            combined[item.chunk.id].score += item.score * 0.55
            combined[item.chunk.id].ranker = "hybrid"
        else:
            combined[item.chunk.id] = ChunkSearchResult(chunk=item.chunk, score=item.score * 0.55, ranker=item.ranker)

    ranked = sorted(combined.values(), key=lambda x: x.score, reverse=True)
    return ranked[:limit]


def reindex_documents(
    db: Session,
    *,
    tenant_id: str,
    document_ids: list[str] | None = None,
    source_type: str | None = None,
    acl_policy_id: str | None = None,
) -> tuple[int, int]:
    stmt = select(Document).where(Document.tenant_id == tenant_id, Document.deleted_at.is_(None))
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))
    if source_type:
        stmt = stmt.where(Document.source_type == source_type)
    if acl_policy_id:
        stmt = stmt.where(Document.acl_policy_id == acl_policy_id)

    docs = db.execute(stmt).scalars().all()
    indexed_docs = 0
    indexed_chunks = 0
    for doc in docs:
        _, chunks = index_document(db, tenant_id=tenant_id, document=doc)
        indexed_docs += 1
        indexed_chunks += chunks
    return indexed_docs, indexed_chunks
