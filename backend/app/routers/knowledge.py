from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db
from app.models.tenant_membership import TenantMembership
from app.schemas.knowledge import KnowledgeHealthItem, KnowledgeHealthResponse
from app.services.knowledge_health import build_knowledge_health

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/health", response_model=KnowledgeHealthResponse)
def knowledge_health(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> KnowledgeHealthResponse:
    payload = build_knowledge_health(db, tenant_id=membership.tenant_id)
    return KnowledgeHealthResponse(
        tenant_id=payload["tenant_id"],
        total_documents=payload["total_documents"],
        total_chunks=payload["total_chunks"],
        latest_sync_at=payload["latest_sync_at"],
        sources=[KnowledgeHealthItem(**item) for item in payload["sources"]],
        recent_errors=payload["recent_errors"],
    )
