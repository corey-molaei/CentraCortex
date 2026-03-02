from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_tenant_admin
from app.core.config import settings
from app.core.security import encrypt_secret
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.slack_connector import SlackConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, OAuthStartResponse, SyncResponse, SyncRunRead
from app.schemas.connectors.slack import SlackConnectorConfig, SlackConnectorRead
from app.services.connectors.common import connector_status_payload
from app.services.connectors.slack_service import complete_oauth, get_oauth_url, sync_connector, test_connection

router = APIRouter(prefix="/connectors/slack", tags=["connectors-slack"])


@router.get("/config", response_model=SlackConnectorRead | None)
def get_slack_config(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(SlackConnector).where(SlackConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if not connector:
        return None
    return SlackConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        workspace_name=connector.workspace_name,
        team_id=connector.team_id,
        channel_ids=connector.channel_ids,
        is_oauth_connected=bool(connector.bot_token_encrypted),
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.put("/config", response_model=SlackConnectorRead)
def upsert_slack_config(
    payload: SlackConnectorConfig,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(SlackConnector).where(SlackConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = SlackConnector(tenant_id=admin.tenant_id)
        db.add(connector)

    connector.workspace_name = payload.workspace_name
    connector.team_id = payload.team_id
    connector.channel_ids = payload.channel_ids
    connector.enabled = payload.enabled
    if payload.bot_token:
        connector.bot_token_encrypted = encrypt_secret(payload.bot_token)

    db.commit()
    db.refresh(connector)

    return SlackConnectorRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        workspace_name=connector.workspace_name,
        team_id=connector.team_id,
        channel_ids=connector.channel_ids,
        is_oauth_connected=bool(connector.bot_token_encrypted),
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


@router.get("/oauth/start", response_model=OAuthStartResponse)
def slack_oauth_start(
    redirect_uri: str = Query(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(SlackConnector).where(SlackConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        connector = SlackConnector(tenant_id=admin.tenant_id)
        db.add(connector)
        db.commit()
        db.refresh(connector)

    if not settings.slack_client_id:
        raise HTTPException(status_code=400, detail="SLACK_CLIENT_ID is not configured")

    auth_url, state = get_oauth_url(db, connector, settings.slack_client_id, redirect_uri)
    return OAuthStartResponse(auth_url=auth_url, state=state)


@router.get("/oauth/callback")
def slack_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = db.execute(select(SlackConnector).where(SlackConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Slack connector not configured")

    if not settings.slack_client_id or not settings.slack_client_secret:
        raise HTTPException(status_code=400, detail="Slack OAuth credentials are not configured")

    complete_oauth(
        db,
        connector,
        code=code,
        state=state,
        client_id=settings.slack_client_id,
        client_secret=settings.slack_client_secret,
    )
    return {"message": "Slack OAuth completed"}


@router.post("/test", response_model=ConnectionTestResult)
def test_slack(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(SlackConnector).where(SlackConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Slack connector not configured")
    success, message = test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_slack(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    connector = db.execute(select(SlackConnector).where(SlackConnector.tenant_id == admin.tenant_id)).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Slack connector not configured")
    items = sync_connector(db, connector)
    return SyncResponse(status="success", items_synced=items, message="Slack sync completed")


@router.get("/status", response_model=list[SyncRunRead])
def slack_status(admin: TenantMembership = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.tenant_id == admin.tenant_id, ConnectorSyncRun.connector_type == "slack")
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
