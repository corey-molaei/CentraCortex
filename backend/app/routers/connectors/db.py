from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.security import encrypt_secret
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.db_connector import DBConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncResponse, SyncRunRead
from app.schemas.connectors.db import DBConnectorConfig, DBConnectorRead
from app.services.connectors.common import connector_status_payload
from app.services.connectors.db_service import sync_connector, test_connection

router = APIRouter(prefix="/connectors/db", tags=["connectors-db"])


@router.get("/config", response_model=DBConnectorRead | None)
def get_db_config(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(DBConnector).where(DBConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not connector:
        return None
    return DBConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        table_allowlist=connector.table_allowlist,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=DBConnectorRead)
def upsert_db_config(
    payload: DBConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(DBConnector).where(DBConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = DBConnector(tenant_id=admin.tenant_id, connection_uri_encrypted="")
        db.add(connector)

    connector.connection_uri_encrypted = encrypt_secret(payload.connection_uri)
    connector.table_allowlist = payload.table_allowlist
    connector.enabled = payload.enabled
    db.commit()
    db.refresh(connector)

    return DBConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        table_allowlist=connector.table_allowlist,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_db(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(DBConnector).where(DBConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="DB connector not configured")
    success, message = test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_db(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(DBConnector).where(DBConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="DB connector not configured")
    items = sync_connector(db, connector)
    return SyncResponse(status="success", items_synced=items, message="DB sync completed")


@router.get("/status", response_model=list[SyncRunRead])
def db_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "db")
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
