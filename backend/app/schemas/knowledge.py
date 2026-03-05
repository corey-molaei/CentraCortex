from datetime import datetime

from pydantic import BaseModel


class KnowledgeHealthItem(BaseModel):
    source_type: str
    documents: int
    indexed: int
    pending: int
    retry: int
    failed: int
    last_source_update_at: datetime | None = None


class KnowledgeHealthResponse(BaseModel):
    tenant_id: str
    total_documents: int
    total_chunks: int
    latest_sync_at: datetime | None = None
    sources: list[KnowledgeHealthItem]
    recent_errors: list[str]
