from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.logs_connector import LogsConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncResponse, SyncRunRead
from app.schemas.connectors.logs import LogsConnectorConfig, LogsConnectorRead
from app.services.connectors.common import connector_status_payload
from app.services.connectors.logs_service import sync_connector, test_connection

router = APIRouter(prefix="/connectors/logs", tags=["connectors-logs"])


@router.get("/config", response_model=LogsConnectorRead | None)
def get_logs_config(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(LogsConnector).where(LogsConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not connector:
        return None
    return LogsConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        folder_path=connector.folder_path,
        file_glob=connector.file_glob,
        parser_type=connector.parser_type,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=LogsConnectorRead)
def upsert_logs_config(
    payload: LogsConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(LogsConnector).where(LogsConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = LogsConnector(tenant_id=admin.tenant_id, folder_path=payload.folder_path)
        db.add(connector)

    connector.folder_path = payload.folder_path
    connector.file_glob = payload.file_glob
    connector.parser_type = payload.parser_type
    connector.enabled = payload.enabled
    db.commit()
    db.refresh(connector)

    return LogsConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        folder_path=connector.folder_path,
        file_glob=connector.file_glob,
        parser_type=connector.parser_type,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_logs(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(LogsConnector).where(LogsConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Logs connector not configured")
    success, message = test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_logs(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(LogsConnector).where(LogsConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Logs connector not configured")
    items = sync_connector(db, connector)
    return SyncResponse(status="success", items_synced=items, message="Logs sync completed")


@router.get("/status", response_model=list[SyncRunRead])
def logs_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "logs")
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
