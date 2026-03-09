from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.tenant_membership import TenantMembership
from app.schemas.documents import (
    ChunkSearchRequest,
    ChunkSearchResponse,
    ChunkSearchResultItem,
    DocumentChunkRead,
    DocumentDetail,
    DocumentListItem,
    ForgetDocumentResponse,
    ReindexRequest,
    ReindexResponse,
    ResetEmbeddingsResponse,
)
from app.services.acl import can_access_document
from app.services.audit import audit_event
from app.services.document_indexing import (
    forget_document,
    get_document_chunks,
    hybrid_search_chunks,
    index_document,
    list_accessible_documents,
    reindex_documents,
    reset_embedded_content,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _can_access_document(db: Session, membership: TenantMembership, document: Document) -> bool:
    return can_access_document(db, tenant_id=membership.tenant_id, user_id=membership.user_id, document=document)


def _chunk_counts(db: Session, doc_ids: list[str]) -> dict[str, int]:
    if not doc_ids:
        return {}
    rows = (
        db.execute(
            select(DocumentChunk.document_id, func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.document_id.in_(doc_ids),
                DocumentChunk.chunk_version == Document.current_chunk_version,
            )
            .group_by(DocumentChunk.document_id)
        )
        .all()
    )
    return {str(row[0]): int(row[1]) for row in rows}


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    source_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    acl_policy_id: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    q: str | None = Query(default=None),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[DocumentListItem]:
    docs = list_accessible_documents(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        source_type=source_type,
        tag=tag,
        acl_policy_id=acl_policy_id,
        created_from=created_from,
        created_to=created_to,
        q=q,
    )
    counts = _chunk_counts(db, [doc.id for doc in docs])
    return [
        DocumentListItem(
            id=doc.id,
            source_type=doc.source_type,
            source_id=doc.source_id,
            title=doc.title,
            url=doc.url,
            author=doc.author,
            tags_json=doc.tags_json,
            acl_policy_id=doc.acl_policy_id,
            current_chunk_version=doc.current_chunk_version,
            indexed_at=doc.indexed_at,
            index_status=doc.index_status,
            index_error=doc.index_error,
            index_attempts=doc.index_attempts,
            index_requested_at=doc.index_requested_at,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            chunk_count=counts.get(doc.id, 0),
        )
        for doc in docs
    ]


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    document = db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == membership.tenant_id,
            Document.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not _can_access_document(db, membership, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this document")

    chunks = get_document_chunks(
        db,
        tenant_id=membership.tenant_id,
        document_id=document.id,
        version=document.current_chunk_version,
    )
    return DocumentDetail(
        id=document.id,
        tenant_id=document.tenant_id,
        source_type=document.source_type,
        source_id=document.source_id,
        url=document.url,
        title=document.title,
        author=document.author,
        source_created_at=document.source_created_at,
        source_updated_at=document.source_updated_at,
        tags_json=document.tags_json,
        metadata_json=document.metadata_json,
        acl_policy_id=document.acl_policy_id,
        current_chunk_version=document.current_chunk_version,
        indexed_at=document.indexed_at,
        index_status=document.index_status,
        index_error=document.index_error,
        index_attempts=document.index_attempts,
        index_requested_at=document.index_requested_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        chunks=[
            DocumentChunkRead(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                chunk_version=chunk.chunk_version,
                content=chunk.content,
                token_count=chunk.token_count,
                acl_policy_id=chunk.acl_policy_id,
                metadata_json=chunk.metadata_json,
            )
            for chunk in chunks
        ],
    )


@router.post("/{document_id}/reindex", response_model=ReindexResponse)
def reindex_single_document(
    document_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ReindexResponse:
    document = db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == admin.tenant_id,
            Document.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    _, chunk_count = index_document(db, tenant_id=admin.tenant_id, document=document)
    audit_event(
        db,
        event_type="document.index.reindex_single",
        resource_type="document",
        action="reindex",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=document.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"chunk_count": chunk_count},
    )
    return ReindexResponse(indexed_documents=1, indexed_chunks=chunk_count)


@router.post("/reindex", response_model=ReindexResponse)
def reindex_many_documents(
    payload: ReindexRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ReindexResponse:
    indexed_documents, indexed_chunks = reindex_documents(
        db,
        tenant_id=admin.tenant_id,
        document_ids=payload.document_ids or None,
        source_type=payload.source_type,
        acl_policy_id=payload.acl_policy_id,
    )
    audit_event(
        db,
        event_type="document.index.reindex_many",
        resource_type="document",
        action="reindex_bulk",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={
            "indexed_documents": indexed_documents,
            "indexed_chunks": indexed_chunks,
            "source_type": payload.source_type,
            "acl_policy_id": payload.acl_policy_id,
        },
    )
    return ReindexResponse(indexed_documents=indexed_documents, indexed_chunks=indexed_chunks)


@router.post("/reset-embeddings", response_model=ResetEmbeddingsResponse)
def reset_embeddings_for_tenant(
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ResetEmbeddingsResponse:
    reset_documents, deleted_chunks = reset_embedded_content(db, tenant_id=admin.tenant_id)
    audit_event(
        db,
        event_type="document.embedding.reset",
        resource_type="document",
        action="reset_embeddings",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={
            "reset_documents": reset_documents,
            "deleted_chunks": deleted_chunks,
            "embedding_dimension": settings.embedding_dimension,
        },
    )
    return ResetEmbeddingsResponse(
        reset_documents=reset_documents,
        deleted_chunks=deleted_chunks,
        status="pending_reindex",
    )


@router.delete("/{document_id}", response_model=ForgetDocumentResponse)
def forget_document_endpoint(
    document_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ForgetDocumentResponse:
    document = db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == admin.tenant_id,
            Document.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    forget_document(db, tenant_id=admin.tenant_id, document=document)
    audit_event(
        db,
        event_type="document.delete.forget",
        resource_type="document",
        action="forget",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=document_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
    )
    return ForgetDocumentResponse(status="deleted", document_id=document_id)


@router.post("/search", response_model=ChunkSearchResponse)
def search_chunks(
    payload: ChunkSearchRequest,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ChunkSearchResponse:
    results = hybrid_search_chunks(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        query=payload.query,
        limit=payload.limit,
    )
    return ChunkSearchResponse(
        results=[
            ChunkSearchResultItem(
                document_id=item.chunk.document_id,
                document_title=item.chunk.metadata_json.get("title", "Untitled"),
                document_url=item.chunk.metadata_json.get("url"),
                source_type=item.chunk.metadata_json.get("source_type", "unknown"),
                chunk_id=item.chunk.id,
                chunk_index=item.chunk.chunk_index,
                snippet=item.chunk.content[:320],
                score=round(item.score, 6),
                ranker=item.ranker,
            )
            for item in results
        ]
    )
