from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.security import encrypt_secret
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.sharepoint_connector import SharePointConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncResponse, SyncRunRead
from app.schemas.connectors.sharepoint import SharePointConnectorConfig, SharePointConnectorRead
from app.services.connectors.common import connector_status_payload
from app.services.connectors.sharepoint_service import sync_connector, test_connection

router = APIRouter(prefix="/connectors/sharepoint", tags=["connectors-sharepoint"])


@router.get("/config", response_model=SharePointConnectorRead | None)
def get_sharepoint_config(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(
        select(SharePointConnector).where(SharePointConnector.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if not connector:
        return None
    return SharePointConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        azure_tenant_id=connector.azure_tenant_id,
        client_id=connector.client_id,
        site_ids=connector.site_ids,
        drive_ids=connector.drive_ids,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=SharePointConnectorRead)
def upsert_sharepoint_config(
    payload: SharePointConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(
        select(SharePointConnector).where(SharePointConnector.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if connector is None:
        connector = SharePointConnector(
            tenant_id=admin.tenant_id,
            azure_tenant_id=payload.azure_tenant_id,
            client_id=payload.client_id,
            client_secret_encrypted="",
        )
        db.add(connector)

    connector.azure_tenant_id = payload.azure_tenant_id
    connector.client_id = payload.client_id
    connector.client_secret_encrypted = encrypt_secret(payload.client_secret)
    connector.site_ids = payload.site_ids
    connector.drive_ids = payload.drive_ids
    connector.enabled = payload.enabled
    db.commit()
    db.refresh(connector)

    return SharePointConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        azure_tenant_id=connector.azure_tenant_id,
        client_id=connector.client_id,
        site_ids=connector.site_ids,
        drive_ids=connector.drive_ids,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_sharepoint(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(
        select(SharePointConnector).where(SharePointConnector.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="SharePoint connector not configured")
    success, message = test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_sharepoint(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(
        select(SharePointConnector).where(SharePointConnector.tenant_id == admin.tenant_id)
    ).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="SharePoint connector not configured")
    items = sync_connector(db, connector)
    return SyncResponse(status="success", items_synced=items, message="SharePoint sync completed")


@router.get("/status", response_model=list[SyncRunRead])
def sharepoint_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "sharepoint")
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
