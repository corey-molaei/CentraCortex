from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.models.tenant_membership import TenantMembership
from app.schemas.agent_builder import (
    BuilderAgentCreate,
    DeploySpecResponse,
    GenerateSpecRequest,
    RollbackRequest,
    SpecVersionDetail,
    SpecVersionRead,
    UpdateSpecRequest,
    UploadStyleExamplesResponse,
)
from app.schemas.agents import AgentDefinitionRead
from app.services.agent_builder import (
    create_builder_agent,
    deploy_spec_version,
    generate_spec_version,
    get_spec_version,
    get_version_examples,
    list_agent_versions,
    rollback_to_version,
    serialize_style_example,
    serialize_version,
    update_spec_version,
    upload_style_examples,
)
from app.services.agent_runtime import list_agent_definitions, serialize_agent
from app.services.audit import audit_event

router = APIRouter(prefix="/agent-builder", tags=["agent-builder"])


@router.get("/agents", response_model=list[AgentDefinitionRead])
def list_builder_agents(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[AgentDefinitionRead]:
    agents = list_agent_definitions(db, tenant_id=membership.tenant_id)
    return [AgentDefinitionRead(**serialize_agent(agent)) for agent in agents]


@router.post("/agents", response_model=AgentDefinitionRead)
def create_builder_agent_endpoint(
    payload: BuilderAgentCreate,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> AgentDefinitionRead:
    agent = create_builder_agent(
        db,
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        name=payload.name,
        description=payload.description,
    )

    audit_event(
        db,
        event_type="agent_builder.agent.create",
        resource_type="agent_definition",
        action="create",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=agent.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"name": agent.name},
    )
    return AgentDefinitionRead(**serialize_agent(agent))


@router.post("/agents/{agent_id}/examples/upload", response_model=UploadStyleExamplesResponse)
async def upload_examples_endpoint(
    agent_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> UploadStyleExamplesResponse:
    decoded: list[tuple[str | None, str]] = []
    for item in files:
        content = await item.read()
        text = content.decode("utf-8", errors="ignore").strip()
        if text:
            decoded.append((item.filename, text))

    if not decoded:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No readable text examples were uploaded")

    try:
        uploaded = upload_style_examples(
            db,
            tenant_id=admin.tenant_id,
            agent_id=agent_id,
            user_id=admin.user_id,
            files=decoded,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent_builder.examples.upload",
        resource_type="agent_style_example",
        action="upload",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=agent_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"uploaded_count": uploaded},
    )
    return UploadStyleExamplesResponse(uploaded_count=uploaded, message="Examples uploaded")


@router.post("/agents/{agent_id}/generate", response_model=SpecVersionRead)
def generate_spec_endpoint(
    agent_id: str,
    payload: GenerateSpecRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> SpecVersionRead:
    try:
        version = generate_spec_version(
            db,
            tenant_id=admin.tenant_id,
            agent_id=agent_id,
            user_id=admin.user_id,
            prompt=payload.prompt,
            selected_tools=payload.selected_tools,
            selected_data_sources=payload.selected_data_sources,
            risk_level=payload.risk_level,
            example_texts=payload.example_texts,
            generate_tests_count=payload.generate_tests_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent_builder.spec.generate",
        resource_type="agent_spec_version",
        action="generate",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=version.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"agent_id": agent_id, "version_number": version.version_number},
    )
    return SpecVersionRead(**serialize_version(version))


@router.get("/agents/{agent_id}/versions", response_model=list[SpecVersionRead])
def list_versions_endpoint(
    agent_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[SpecVersionRead]:
    versions = list_agent_versions(db, tenant_id=membership.tenant_id, agent_id=agent_id)
    return [SpecVersionRead(**serialize_version(version)) for version in versions]


@router.get("/versions/{version_id}", response_model=SpecVersionDetail)
def get_version_endpoint(
    version_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> SpecVersionDetail:
    version = get_spec_version(db, tenant_id=membership.tenant_id, version_id=version_id)
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    examples = get_version_examples(
        db,
        tenant_id=membership.tenant_id,
        agent_id=version.agent_id,
        version_id=version.id,
    )
    return SpecVersionDetail(
        version=SpecVersionRead(**serialize_version(version)),
        style_examples=[serialize_style_example(item) for item in examples],
    )


@router.patch("/versions/{version_id}", response_model=SpecVersionRead)
def update_version_endpoint(
    version_id: str,
    payload: UpdateSpecRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> SpecVersionRead:
    try:
        version = update_spec_version(
            db,
            tenant_id=admin.tenant_id,
            version_id=version_id,
            spec_json=payload.spec_json.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent_builder.spec.update",
        resource_type="agent_spec_version",
        action="update",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=version.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
    )
    return SpecVersionRead(**serialize_version(version))


@router.post("/versions/{version_id}/deploy", response_model=DeploySpecResponse)
def deploy_version_endpoint(
    version_id: str,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> DeploySpecResponse:
    try:
        version = deploy_spec_version(db, tenant_id=admin.tenant_id, version_id=version_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent_builder.spec.deploy",
        resource_type="agent_spec_version",
        action="deploy",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=version.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"agent_id": version.agent_id, "version_number": version.version_number},
    )
    return DeploySpecResponse(status="deployed", version=SpecVersionRead(**serialize_version(version)))


@router.post("/agents/{agent_id}/rollback", response_model=DeploySpecResponse)
def rollback_endpoint(
    agent_id: str,
    payload: RollbackRequest,
    request: Request,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> DeploySpecResponse:
    try:
        version = rollback_to_version(
            db,
            tenant_id=admin.tenant_id,
            agent_id=agent_id,
            target_version_id=payload.target_version_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="agent_builder.spec.rollback",
        resource_type="agent_spec_version",
        action="rollback",
        tenant_id=admin.tenant_id,
        user_id=admin.user_id,
        resource_id=version.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        payload={"agent_id": agent_id, "target_version_id": payload.target_version_id},
    )
    return DeploySpecResponse(status="deployed", version=SpecVersionRead(**serialize_version(version)))
