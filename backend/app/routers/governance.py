from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.models.tenant_membership import TenantMembership
from app.schemas.agents import ToolApprovalDecisionRequest, ToolApprovalRead
from app.schemas.governance import AuditLogRead
from app.services.agent_runtime import decide_tool_approval, list_tool_approvals, serialize_approval
from app.services.audit import audit_event
from app.services.governance import audit_logs_to_csv, query_audit_logs, serialize_audit_log

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    tenant_id: str | None = None,
    user_id: str | None = None,
    event_type: str | None = None,
    tool: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    scoped_tenant_id = admin.tenant_id
    if tenant_id and tenant_id != admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant governance access denied")

    logs = query_audit_logs(
        db,
        tenant_id=scoped_tenant_id,
        user_id=user_id,
        event_type=event_type,
        tool=tool,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    return [AuditLogRead(**serialize_audit_log(log)) for log in logs]


@router.get("/audit-logs/export")
def export_audit_logs_csv(
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    event_type: str | None = None,
    tool: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    if tenant_id and tenant_id != admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant governance access denied")

    logs = query_audit_logs(
        db,
        tenant_id=admin.tenant_id,
        user_id=user_id,
        event_type=event_type,
        tool=tool,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=0,
    )
    csv_payload = audit_logs_to_csv(logs)

    audit_event(
        db,
        event_type="governance.audit.export",
        resource_type="audit_log",
        action="export",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id="csv",
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"records": len(logs), "event_type": event_type, "tool": tool},
    )

    return StreamingResponse(
        iter([csv_payload]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


@router.get("/approval-queue", response_model=list[ToolApprovalRead])
def list_approval_queue(
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[ToolApprovalRead]:
    approvals = list_tool_approvals(db, tenant_id=admin.tenant_id, status=status_filter, limit=limit)
    return [ToolApprovalRead(**serialize_approval(approval)) for approval in approvals]


@router.post("/approval-queue/{approval_id}/approve", response_model=ToolApprovalRead)
def approve_queue_item(
    approval_id: str,
    payload: ToolApprovalDecisionRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ToolApprovalRead:
    try:
        approval, run = decide_tool_approval(
            db,
            tenant_id=admin.tenant_id,
            approval_id=approval_id,
            approver_user_id=admin.user_id,
            decision="approved",
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="governance.approval.approve",
        resource_type="tool_approval",
        action="approve",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=approval.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"run_id": run.id, "tool_name": approval.tool_name},
    )
    return ToolApprovalRead(**serialize_approval(approval))


@router.post("/approval-queue/{approval_id}/reject", response_model=ToolApprovalRead)
def reject_queue_item(
    approval_id: str,
    payload: ToolApprovalDecisionRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ToolApprovalRead:
    try:
        approval, run = decide_tool_approval(
            db,
            tenant_id=admin.tenant_id,
            approval_id=approval_id,
            approver_user_id=admin.user_id,
            decision="rejected",
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="governance.approval.reject",
        resource_type="tool_approval",
        action="reject",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=approval.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"run_id": run.id, "tool_name": approval.tool_name},
    )
    return ToolApprovalRead(**serialize_approval(approval))
