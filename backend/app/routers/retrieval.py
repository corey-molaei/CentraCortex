from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.models.acl_policy import ACLPolicy
from app.models.document import Document
from app.models.tenant_membership import TenantMembership
from app.schemas.rbac import DocumentCreate, DocumentRead
from app.services.acl import get_accessible_documents

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/documents", response_model=DocumentRead)
def create_document(
    payload: DocumentCreate,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> DocumentRead:
    if payload.acl_policy_id:
        policy = db.execute(
            select(ACLPolicy).where(ACLPolicy.id == payload.acl_policy_id, ACLPolicy.tenant_id == admin.tenant_id)
        ).scalar_one_or_none()
        if not policy:
            raise HTTPException(status_code=404, detail="ACL policy not found")

    doc = Document(
        tenant_id=admin.tenant_id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        title=payload.title,
        raw_text=payload.raw_text,
        acl_policy_id=payload.acl_policy_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return DocumentRead(
        id=doc.id,
        source_type=doc.source_type,
        source_id=doc.source_id,
        title=doc.title,
        acl_policy_id=doc.acl_policy_id,
    )


@router.get("/documents", response_model=list[DocumentRead])
def list_accessible_documents(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[DocumentRead]:
    docs = get_accessible_documents(db, membership.tenant_id, membership.user_id)
    return [
        DocumentRead(
            id=d.id,
            source_type=d.source_type,
            source_id=d.source_id,
            title=d.title,
            acl_policy_id=d.acl_policy_id,
        )
        for d in docs
    ]
