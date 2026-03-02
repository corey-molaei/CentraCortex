from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.security import encrypt_secret
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.jira_connector import JiraConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncResponse, SyncRunRead
from app.schemas.connectors.jira import JiraConnectorConfig, JiraConnectorRead
from app.services.connectors.common import connector_status_payload
from app.services.connectors.jira_service import sync_connector, test_connection

router = APIRouter(prefix="/connectors/jira", tags=["connectors-jira"])


@router.get("/config", response_model=JiraConnectorRead | None)
def get_jira_config(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(JiraConnector).where(JiraConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not connector:
        return None
    return JiraConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        base_url=connector.base_url,
        email=connector.email,
        project_keys=connector.project_keys,
        issue_types=connector.issue_types,
        fields_mapping=connector.fields_mapping,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=JiraConnectorRead)
def upsert_jira_config(
    payload: JiraConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(JiraConnector).where(JiraConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = JiraConnector(tenant_id=admin.tenant_id, base_url=payload.base_url, email=payload.email, api_token_encrypted="")
        db.add(connector)

    connector.base_url = payload.base_url
    connector.email = payload.email
    connector.api_token_encrypted = encrypt_secret(payload.api_token)
    connector.project_keys = payload.project_keys
    connector.issue_types = payload.issue_types
    connector.fields_mapping = payload.fields_mapping
    connector.enabled = payload.enabled
    db.commit()
    db.refresh(connector)

    return JiraConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        base_url=connector.base_url,
        email=connector.email,
        project_keys=connector.project_keys,
        issue_types=connector.issue_types,
        fields_mapping=connector.fields_mapping,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_jira(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(JiraConnector).where(JiraConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Jira connector not configured")
    success, message = test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_jira(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(JiraConnector).where(JiraConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Jira connector not configured")
    items = sync_connector(db, connector)
    return SyncResponse(status="success", items_synced=items, message="Jira sync completed")


@router.get("/status", response_model=list[SyncRunRead])
def jira_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "jira")
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
