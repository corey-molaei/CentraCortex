from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db, require_tenant_admin
from app.core.config import settings
from app.models.tenant_membership import TenantMembership
from app.models.workspace_google_integration import WorkspaceGoogleIntegration
from app.schemas.connectors.common import ConnectionTestResult, OAuthStartResponse, SyncResponse
from app.schemas.connectors.google_workspace import WorkspaceGoogleIntegrationRead, WorkspaceGoogleIntegrationUpdate
from app.services.connectors.common import connector_status_payload
from app.services.connectors.google_workspace_service import (
    complete_oauth,
    get_oauth_url,
    get_or_create_integration,
    sync_connector,
    test_connection,
)

router = APIRouter(prefix="/connectors/google-workspace", tags=["connectors-google-workspace"])


def _ensure_oauth_settings() -> tuple[str, str]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google OAuth credentials are not configured. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then restart api/worker/beat."
            ),
        )
    return settings.google_client_id, settings.google_client_secret


def _workspace_integration(db: Session, tenant_id: str) -> WorkspaceGoogleIntegration:
    return get_or_create_integration(db, tenant_id=tenant_id)


def _read_model(connector: WorkspaceGoogleIntegration) -> WorkspaceGoogleIntegrationRead:
    return WorkspaceGoogleIntegrationRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        google_account_email=connector.google_account_email,
        google_account_sub=connector.google_account_sub,
        is_oauth_connected=bool(connector.access_token_encrypted),
        scopes=connector.scopes,
        enabled=connector.enabled,
        gmail_enabled=connector.gmail_enabled,
        gmail_labels=connector.gmail_labels,
        calendar_enabled=connector.calendar_enabled,
        calendar_ids=connector.calendar_ids,
        drive_enabled=connector.drive_enabled,
        drive_folder_ids=connector.drive_folder_ids,
        sheets_enabled=connector.sheets_enabled,
        sheets_targets=connector.sheets_targets,
        crm_sheet_spreadsheet_id=connector.crm_sheet_spreadsheet_id,
        crm_sheet_tab_name=connector.crm_sheet_tab_name,
        status=connector_status_payload(connector),
    )


@router.get("/config", response_model=WorkspaceGoogleIntegrationRead)
def get_workspace_google_config(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    return _read_model(_workspace_integration(db, membership.tenant_id))


@router.put("/config", response_model=WorkspaceGoogleIntegrationRead)
def update_workspace_google_config(
    payload: WorkspaceGoogleIntegrationUpdate,
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    connector = _workspace_integration(db, admin.tenant_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(connector, key, value)
    db.commit()
    db.refresh(connector)
    return _read_model(connector)


@router.get("/oauth/start", response_model=OAuthStartResponse)
def start_workspace_google_oauth(
    redirect_uri: str = Query(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    client_id, _ = _ensure_oauth_settings()
    connector = _workspace_integration(db, admin.tenant_id)
    auth_url, state = get_oauth_url(
        db,
        connector,
        client_id=client_id,
        redirect_uri=redirect_uri,
        user_id=admin.user_id,
    )
    return OAuthStartResponse(auth_url=auth_url, state=state)


@router.get("/oauth/callback")
def complete_workspace_google_oauth(
    code: str = Query(...),
    state: str = Query(...),
    admin: TenantMembership = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    connector = _workspace_integration(db, admin.tenant_id)
    try:
        complete_oauth(
            db,
            connector,
            code=code,
            state=state,
            client_id=client_id,
            client_secret=client_secret,
            user_id=admin.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Google workspace OAuth completed"}


@router.post("/test", response_model=ConnectionTestResult)
def test_workspace_google(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    connector = _workspace_integration(db, membership.tenant_id)
    success, message = test_connection(db, connector, client_id=client_id, client_secret=client_secret)
    return ConnectionTestResult(success=success, message=message)


@router.post("/sync", response_model=SyncResponse)
def sync_workspace_google(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    connector = _workspace_integration(db, membership.tenant_id)
    try:
        counts = sync_connector(db, connector, client_id=client_id, client_secret=client_secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncResponse(status="success", items_synced=counts["total"], message="Workspace Google sync completed")


@router.get("/status")
def workspace_google_status(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    connector = _workspace_integration(db, membership.tenant_id)
    return connector_status_payload(connector)
