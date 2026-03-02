from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.file_connector import FileConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncRunRead
from app.schemas.connectors.file_upload import FileConnectorConfig, FileConnectorRead
from app.services.connectors.common import connector_status_payload, finish_sync_run, start_sync_run
from app.services.connectors.file_service import ingest_file, test_connection

router = APIRouter(prefix="/connectors/file-upload", tags=["connectors-file-upload"])


@router.get("/config", response_model=FileConnectorRead | None)
def get_file_connector(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(FileConnector).where(FileConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not connector:
        return None
    return FileConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        allowed_extensions=connector.allowed_extensions,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=FileConnectorRead)
def upsert_file_connector(
    payload: FileConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(FileConnector).where(FileConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = FileConnector(tenant_id=admin.tenant_id)
        db.add(connector)

    connector.allowed_extensions = payload.allowed_extensions
    connector.enabled = payload.enabled
    db.commit()
    db.refresh(connector)

    return FileConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        allowed_extensions=connector.allowed_extensions,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_file_connector(_: TenantMembership = Depends(require_tenant_admin)):
    success, message = test_connection()
    return ConnectionTestResult(success=success, message=message)


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(FileConnector).where(FileConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=400,
            detail="File upload connector is not configured. Save connector settings first.",
        )

    run = start_sync_run(
        db,
        tenant_id=admin.tenant_id,
        connector_type="file_upload",
        connector_config_id=connector.id,
    )
    ingested_ids: list[str] = []
    try:
        for file in files:
            filename = file.filename or ""
            if not filename:
                raise ValueError("Uploaded file must have a filename")

            content = await file.read()
            doc_id = ingest_file(
                db,
                connector,
                filename=filename,
                content=content,
                content_type=file.content_type,
            )
            ingested_ids.append(doc_id)
    except ValueError as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(
            db,
            run,
            status="failed",
            items_synced=len(ingested_ids),
            error_message=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    finish_sync_run(
        db,
        run,
        status="success",
        items_synced=len(ingested_ids),
    )
    return {
        "status": "success",
        "items_synced": len(ingested_ids),
        "document_ids": ingested_ids,
        "indexing_queued": True,
    }


@router.get("/status", response_model=list[SyncRunRead])
def file_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "file_upload")
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
