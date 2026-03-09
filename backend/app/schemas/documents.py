from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentChunkRead(BaseModel):
    id: str
    chunk_index: int
    chunk_version: int
    content: str
    token_count: int
    acl_policy_id: str | None = None
    metadata_json: dict[str, Any]


class DocumentListItem(BaseModel):
    id: str
    source_type: str
    source_id: str
    title: str
    url: str | None = None
    author: str | None = None
    tags_json: list[str]
    acl_policy_id: str | None = None
    current_chunk_version: int
    indexed_at: datetime | None = None
    index_status: str
    index_error: str | None = None
    index_attempts: int
    index_requested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    chunk_count: int


class DocumentDetail(BaseModel):
    id: str
    tenant_id: str
    source_type: str
    source_id: str
    url: str | None = None
    title: str
    author: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    tags_json: list[str]
    metadata_json: dict[str, Any]
    acl_policy_id: str | None = None
    current_chunk_version: int
    indexed_at: datetime | None = None
    index_status: str
    index_error: str | None = None
    index_attempts: int
    index_requested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    chunks: list[DocumentChunkRead]


class ReindexRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    source_type: str | None = None
    acl_policy_id: str | None = None


class ReindexResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int


class ResetEmbeddingsResponse(BaseModel):
    reset_documents: int
    deleted_chunks: int
    status: str


class ForgetDocumentResponse(BaseModel):
    status: str
    document_id: str


class ChunkSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=8, ge=1, le=50)


class ChunkSearchResultItem(BaseModel):
    document_id: str
    document_title: str
    document_url: str | None = None
    source_type: str
    chunk_id: str
    chunk_index: int
    snippet: str
    score: float
    ranker: str


class ChunkSearchResponse(BaseModel):
    results: list[ChunkSearchResultItem]
