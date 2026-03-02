from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.models.tenant_membership import TenantMembership
from app.schemas.agents import (
    AgentDefinitionCreate,
    AgentDefinitionRead,
    AgentDefinitionUpdate,
    AgentRunDetail,
    AgentRunRead,
    AgentRunRequest,
    AgentTraceStepRead,
    ToolApprovalDecisionRequest,
    ToolApprovalRead,
)
from app.services.agent_runtime import (
    create_agent_definition,
    decide_tool_approval,
    delete_agent_definition,
    get_agent_definition,
    get_agent_run_detail,
    list_agent_definitions,
    list_agent_runs,
    list_tool_approvals,
    run_agent,
    serialize_agent,
    serialize_approval,
    serialize_run,
    serialize_trace,
    update_agent_definition,
)
from app.services.audit import audit_event

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/catalog", response_model=list[AgentDefinitionRead])
def list_catalog(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[AgentDefinitionRead]:
    agents = list_agent_definitions(db, tenant_id=membership.tenant_id)
    return [AgentDefinitionRead(**serialize_agent(agent)) for agent in agents]


@router.post("/catalog", response_model=AgentDefinitionRead)
def create_catalog_item(
    payload: AgentDefinitionCreate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> AgentDefinitionRead:
    try:
        agent = create_agent_definition(
            db,
            tenant_id=admin.tenant_id,
            created_by_user_id=admin.user_id,
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            default_agent_type=payload.default_agent_type,
            allowed_tools=payload.allowed_tools,
            enabled=payload.enabled,
            config_json=payload.config_json,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent.catalog.create",
        resource_type="agent_definition",
        action="create",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=agent.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"name": agent.name, "default_agent_type": agent.default_agent_type},
    )
    return AgentDefinitionRead(**serialize_agent(agent))


@router.get("/catalog/{agent_id}", response_model=AgentDefinitionRead)
def get_catalog_item(
    agent_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> AgentDefinitionRead:
    agent = get_agent_definition(db, tenant_id=membership.tenant_id, agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return AgentDefinitionRead(**serialize_agent(agent))


@router.patch("/catalog/{agent_id}", response_model=AgentDefinitionRead)
def update_catalog_item(
    agent_id: str,
    payload: AgentDefinitionUpdate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> AgentDefinitionRead:
    try:
        agent = update_agent_definition(
            db,
            tenant_id=admin.tenant_id,
            agent_id=agent_id,
            updates=payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent.catalog.update",
        resource_type="agent_definition",
        action="update",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=agent.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"updated_fields": list(payload.model_dump(exclude_unset=True).keys())},
    )
    return AgentDefinitionRead(**serialize_agent(agent))


@router.delete("/catalog/{agent_id}")
def delete_catalog_item(
    agent_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        delete_agent_definition(db, tenant_id=admin.tenant_id, agent_id=agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent.catalog.delete",
        resource_type="agent_definition",
        action="delete",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=agent_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
    )
    return {"message": "Agent deleted"}


@router.post("/runs", response_model=AgentRunRead)
def run_agent_endpoint(
    payload: AgentRunRequest,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> AgentRunRead:
    try:
        run = run_agent(
            db,
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            agent_id=payload.agent_id,
            input_text=payload.input_text,
            tool_inputs=payload.tool_inputs,
            metadata_json=payload.metadata_json,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent.run.create",
        resource_type="agent_run",
        action="run",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=run.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"agent_id": payload.agent_id, "status": run.status, "routed_agent": run.routed_agent},
    )
    return AgentRunRead(**serialize_run(run))


@router.get("/runs", response_model=list[AgentRunRead])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[AgentRunRead]:
    runs = list_agent_runs(
        db,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        user_role=membership.role,
        limit=limit,
    )
    return [AgentRunRead(**serialize_run(run)) for run in runs]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_run(
    run_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> AgentRunDetail:
    try:
        run, traces, approvals = get_agent_run_detail(
            db,
            tenant_id=membership.tenant_id,
            run_id=run_id,
            user_id=membership.user_id,
            user_role=membership.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return AgentRunDetail(
        run=AgentRunRead(**serialize_run(run)),
        traces=[AgentTraceStepRead(**serialize_trace(trace)) for trace in traces],
        approvals=[ToolApprovalRead(**serialize_approval(approval)) for approval in approvals],
    )


@router.get("/approvals", response_model=list[ToolApprovalRead])
def list_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[ToolApprovalRead]:
    approvals = list_tool_approvals(db, tenant_id=admin.tenant_id, status=status_filter, limit=limit)
    return [ToolApprovalRead(**serialize_approval(approval)) for approval in approvals]


@router.post("/approvals/{approval_id}/approve", response_model=ToolApprovalRead)
def approve_approval(
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
        event_type="agent.approval.approve",
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


@router.post("/approvals/{approval_id}/reject", response_model=ToolApprovalRead)
def reject_approval(
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
        event_type="agent.approval.reject",
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
