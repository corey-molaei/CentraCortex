from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.security import encrypt_secret
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.code_repo_connector import CodeRepoConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.code_repo import CodeRepoConnectorConfig, CodeRepoConnectorRead
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncResponse, SyncRunRead
from app.services.connectors.code_repo_service import sync_connector, test_connection
from app.services.connectors.common import connector_status_payload

router = APIRouter(prefix="/connectors/code-repo", tags=["connectors-code-repo"])


@router.get("/config", response_model=CodeRepoConnectorRead | None)
def get_repo_config(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(CodeRepoConnector).where(CodeRepoConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not connector:
        return None
    return CodeRepoConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        provider=connector.provider,
        base_url=connector.base_url,
        repositories=connector.repositories,
        include_readme=connector.include_readme,
        include_issues=connector.include_issues,
        include_prs=connector.include_prs,
        include_wiki=connector.include_wiki,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=CodeRepoConnectorRead)
def upsert_repo_config(
    payload: CodeRepoConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(CodeRepoConnector).where(CodeRepoConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = CodeRepoConnector(tenant_id=admin.tenant_id, base_url=payload.base_url, token_encrypted="")
        db.add(connector)

    connector.provider = payload.provider
    connector.base_url = payload.base_url
    connector.token_encrypted = encrypt_secret(payload.token)
    connector.repositories = payload.repositories
    connector.include_readme = payload.include_readme
    connector.include_issues = payload.include_issues
    connector.include_prs = payload.include_prs
    connector.include_wiki = payload.include_wiki
    connector.enabled = payload.enabled
    db.commit()
    db.refresh(connector)

    return CodeRepoConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        provider=connector.provider,
        base_url=connector.base_url,
        repositories=connector.repositories,
        include_readme=connector.include_readme,
        include_issues=connector.include_issues,
        include_prs=connector.include_prs,
        include_wiki=connector.include_wiki,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_repo(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(CodeRepoConnector).where(CodeRepoConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Code repo connector not configured")
    success, message = test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_repo(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(CodeRepoConnector).where(CodeRepoConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Code repo connector not configured")
    items = sync_connector(db, connector)
    return SyncResponse(status="success", items_synced=items, message="Code repo sync completed")


@router.get("/status", response_model=list[SyncRunRead])
def repo_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "code_repo")
        .order_by(ConnectorSyncRun.started_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        SyncRunRead(
            id=r.id,
            connector_type=r.connector_type,
            connector_config_id=r.connector_config_id,
            status=r.status,
            items_synced=r.items_synced,
            error_message=r.error_message,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in runs
    ]
