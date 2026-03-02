from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.core.config import settings
from app.models.tenant_membership import TenantMembership
from app.models.tool_definition import ToolDefinition
from app.schemas.rbac import ToolExecutionRequest
from app.services.acl import is_allowed_for_resource
from app.services.audit import audit_event

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/catalog/{tool_name}")
def register_tool(
    tool_name: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    exists = db.execute(
        select(ToolDefinition).where(ToolDefinition.tenant_id == admin.tenant_id, ToolDefinition.tool_name == tool_name)
    ).scalar_one_or_none()
    if not exists:
        db.add(ToolDefinition(tenant_id=admin.tenant_id, tool_name=tool_name, description=f"Tool {tool_name}"))
        db.commit()

    audit_event(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        event_type="tool.register",
        resource_type="tool_definition",
        resource_id=tool_name,
        action="register",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Tool registered"}


@router.post("/{tool_name}/execute")
def execute_tool(
    tool_name: str,
    payload: ToolExecutionRequest,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> dict:
    allowed = is_allowed_for_resource(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        policy_type="tool",
        resource_id=tool_name,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Tool execution denied by ACL policy")

    result = {
        "tool": tool_name,
        "status": "executed",
        "payload": payload.payload,
    }

    audit_event(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        event_type="tool.execute",
        resource_type="tool",
        resource_id=tool_name,
        action="execute",
        request_id=request.headers.get(settings.request_id_header),
        ip_address=request.client.host if request.client else None,
        payload=payload.payload,
    )

    return result
