import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db
from app.core.config import settings
from app.models.connector_oauth_state import ConnectorOAuthState
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, OAuthStartResponse, SyncResponse, SyncRunRead
from app.schemas.connectors.google import (
    GoogleAccountCreate,
    GoogleAccountRead,
    GoogleAccountUpdate,
    GoogleCalendarEventRead,
    GoogleCalendarEventUpsert,
    GoogleCalendarListItem,
    GoogleContactGroupItem,
    GoogleDriveFileItem,
    GoogleDriveFolderItem,
    GoogleSheetItem,
    GoogleSheetTabItem,
    GoogleSyncOptionsUpdate,
)
from app.services.audit import audit_event
from app.services.connectors.common import connector_status_payload
from app.services.connectors.google_service import (
    complete_oauth,
    create_event,
    delete_event,
    disconnect_account,
    get_oauth_url,
    list_calendars,
    list_contact_groups,
    list_drive_files,
    list_drive_folders,
    list_sheet_tabs,
    list_sheets_spreadsheets,
    set_workspace_default_account,
    sync_connector,
    test_connection,
    update_event,
)

router = APIRouter(prefix="/connectors/google", tags=["connectors-google"])
logger = structlog.get_logger(__name__)


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


def _read_model(connector: GoogleUserConnector) -> GoogleAccountRead:
    return GoogleAccountRead(
        id=connector.id,
        tenant_id=connector.tenant_id,
        user_id=connector.user_id,
        label=connector.label,
        google_account_email=connector.google_account_email,
        google_account_sub=connector.google_account_sub,
        is_oauth_connected=bool(connector.access_token_encrypted),
        is_primary=connector.is_primary,
        is_workspace_default=connector.is_workspace_default,
        scopes=connector.scopes,
        gmail_enabled=connector.gmail_enabled,
        gmail_labels=connector.gmail_labels,
        gmail_sync_mode=connector.gmail_sync_mode,
        gmail_last_n_days=connector.gmail_last_n_days,
        gmail_max_messages=connector.gmail_max_messages,
        gmail_query=connector.gmail_query,
        calendar_enabled=connector.calendar_enabled,
        calendar_ids=connector.calendar_ids,
        calendar_sync_mode=connector.calendar_sync_mode,
        calendar_days_back=connector.calendar_days_back,
        calendar_days_forward=connector.calendar_days_forward,
        calendar_max_events=connector.calendar_max_events,
        drive_enabled=connector.drive_enabled,
        drive_folder_ids=connector.drive_folder_ids,
        drive_file_ids=connector.drive_file_ids,
        sheets_enabled=connector.sheets_enabled,
        sheets_targets=connector.sheets_targets,
        contacts_enabled=connector.contacts_enabled,
        contacts_sync_mode=connector.contacts_sync_mode,
        contacts_group_ids=connector.contacts_group_ids,
        contacts_max_count=connector.contacts_max_count,
        meet_enabled=connector.meet_enabled,
        crm_sheet_spreadsheet_id=connector.crm_sheet_spreadsheet_id,
        crm_sheet_tab_name=connector.crm_sheet_tab_name,
        sync_scope_configured=connector.sync_scope_configured,
        status=ConnectorStatus(**connector_status_payload(connector)),
    )


def _get_owned_account(db: Session, membership: TenantMembership, account_id: str) -> GoogleUserConnector:
    connector = db.execute(
        select(GoogleUserConnector).where(
            GoogleUserConnector.id == account_id,
            GoogleUserConnector.tenant_id == membership.tenant_id,
            GoogleUserConnector.user_id == membership.user_id,
        )
    ).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Google account not found")
    return connector


def _validate_sync_options(payload: GoogleSyncOptionsUpdate) -> None:
    if payload.gmail_last_n_days is not None and not (1 <= payload.gmail_last_n_days <= 3650):
        raise HTTPException(status_code=400, detail="gmail_last_n_days must be between 1 and 3650")
    if payload.gmail_max_messages is not None and not (1 <= payload.gmail_max_messages <= 5000):
        raise HTTPException(status_code=400, detail="gmail_max_messages must be between 1 and 5000")
    if payload.calendar_days_back is not None and not (0 <= payload.calendar_days_back <= 3650):
        raise HTTPException(status_code=400, detail="calendar_days_back must be between 0 and 3650")
    if payload.calendar_days_forward is not None and not (1 <= payload.calendar_days_forward <= 3650):
        raise HTTPException(status_code=400, detail="calendar_days_forward must be between 1 and 3650")
    if payload.calendar_max_events is not None and not (1 <= payload.calendar_max_events <= 5000):
        raise HTTPException(status_code=400, detail="calendar_max_events must be between 1 and 5000")
    if payload.contacts_max_count is not None and not (1 <= payload.contacts_max_count <= 5000):
        raise HTTPException(status_code=400, detail="contacts_max_count must be between 1 and 5000")


@router.get("/config")
def legacy_google_config_get() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/google/accounts")


@router.put("/config")
def legacy_google_config_put() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/google/accounts")


@router.get("/accounts", response_model=list[GoogleAccountRead])
def list_google_accounts(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    accounts = db.execute(
        select(GoogleUserConnector)
        .where(
            GoogleUserConnector.tenant_id == membership.tenant_id,
            GoogleUserConnector.user_id == membership.user_id,
        )
        .order_by(GoogleUserConnector.created_at.desc())
    ).scalars().all()
    return [_read_model(account) for account in accounts]


@router.post("/accounts", response_model=GoogleAccountRead)
def create_google_account(
    payload: GoogleAccountCreate,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    normalized_email = payload.google_account_email.strip().lower() if payload.google_account_email else None
    if normalized_email:
        existing_by_email = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.tenant_id == membership.tenant_id,
                GoogleUserConnector.user_id == membership.user_id,
                func.lower(GoogleUserConnector.google_account_email) == normalized_email,
            )
        ).scalar_one_or_none()
        if existing_by_email is not None:
            if payload.label is not None:
                existing_by_email.label = payload.label
            existing_by_email.google_account_email = normalized_email
            existing_by_email.gmail_enabled = payload.gmail_enabled
            existing_by_email.calendar_enabled = payload.calendar_enabled
            existing_by_email.drive_enabled = payload.drive_enabled
            existing_by_email.sheets_enabled = payload.sheets_enabled
            existing_by_email.contacts_enabled = payload.contacts_enabled
            db.commit()
            db.refresh(existing_by_email)
            logger.info(
                "google_account_create_idempotent_hit",
                tenant_id=membership.tenant_id,
                user_id=membership.user_id,
                account_id=existing_by_email.id,
                google_account_email=normalized_email,
            )
            return _read_model(existing_by_email)

    existing_primary = db.execute(
        select(GoogleUserConnector.id).where(
            GoogleUserConnector.tenant_id == membership.tenant_id,
            GoogleUserConnector.user_id == membership.user_id,
            GoogleUserConnector.is_primary.is_(True),
        )
    ).scalar_one_or_none()

    existing_workspace_default = db.execute(
        select(GoogleUserConnector.id).where(
            GoogleUserConnector.tenant_id == membership.tenant_id,
            GoogleUserConnector.is_workspace_default.is_(True),
        )
    ).scalar_one_or_none()

    account = GoogleUserConnector(
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        label=payload.label,
        google_account_email=normalized_email,
        enabled=payload.enabled,
        is_primary=existing_primary is None,
        is_workspace_default=payload.is_workspace_default or existing_workspace_default is None,
        gmail_enabled=payload.gmail_enabled,
        gmail_labels=payload.gmail_labels,
        gmail_sync_mode=payload.gmail_sync_mode,
        gmail_last_n_days=payload.gmail_last_n_days,
        gmail_max_messages=payload.gmail_max_messages,
        gmail_query=payload.gmail_query,
        calendar_enabled=payload.calendar_enabled,
        calendar_ids=payload.calendar_ids,
        calendar_sync_mode=payload.calendar_sync_mode,
        calendar_days_back=payload.calendar_days_back,
        calendar_days_forward=payload.calendar_days_forward,
        calendar_max_events=payload.calendar_max_events,
        drive_enabled=payload.drive_enabled,
        drive_folder_ids=payload.drive_folder_ids,
        drive_file_ids=payload.drive_file_ids,
        sheets_enabled=payload.sheets_enabled,
        sheets_targets=payload.sheets_targets,
        contacts_enabled=payload.contacts_enabled,
        contacts_sync_mode=payload.contacts_sync_mode,
        contacts_group_ids=payload.contacts_group_ids,
        contacts_max_count=payload.contacts_max_count,
        meet_enabled=payload.meet_enabled,
        crm_sheet_spreadsheet_id=payload.crm_sheet_spreadsheet_id,
        crm_sheet_tab_name=payload.crm_sheet_tab_name,
        sync_scope_configured=payload.sync_scope_configured,
    )
    db.add(account)
    db.commit()
    if account.is_workspace_default:
        set_workspace_default_account(db, tenant_id=membership.tenant_id, account_id=account.id)
    db.refresh(account)
    return _read_model(account)


@router.patch("/accounts/{account_id}", response_model=GoogleAccountRead)
def update_google_account(
    account_id: str,
    payload: GoogleAccountUpdate,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    account = _get_owned_account(db, membership, account_id)

    updates = payload.model_dump(exclude_unset=True)
    set_primary = updates.pop("is_primary", None)
    set_workspace_default = updates.pop("is_workspace_default", None)
    for key, value in updates.items():
        setattr(account, key, value)

    if set_primary is True:
        others = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.tenant_id == membership.tenant_id,
                GoogleUserConnector.user_id == membership.user_id,
                GoogleUserConnector.id != account.id,
            )
        ).scalars().all()
        for other in others:
            other.is_primary = False
        account.is_primary = True
    elif set_primary is False and account.is_primary:
        replacement = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.tenant_id == membership.tenant_id,
                GoogleUserConnector.user_id == membership.user_id,
                GoogleUserConnector.id != account.id,
            )
        ).scalars().first()
        if replacement is None:
            raise HTTPException(status_code=400, detail="At least one primary Google account is required")
        account.is_primary = False
        replacement.is_primary = True

    db.commit()
    if set_workspace_default is True:
        set_workspace_default_account(db, tenant_id=membership.tenant_id, account_id=account.id)
    elif set_workspace_default is False and account.is_workspace_default:
        replacement = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.tenant_id == membership.tenant_id,
                GoogleUserConnector.id != account.id,
            )
        ).scalars().first()
        if replacement is None:
            raise HTTPException(status_code=400, detail="At least one workspace-default Google account is required")
        set_workspace_default_account(db, tenant_id=membership.tenant_id, account_id=replacement.id)
    db.refresh(account)
    return _read_model(account)


@router.delete("/accounts/{account_id}")
def delete_google_account(
    account_id: str,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    account = _get_owned_account(db, membership, account_id)
    was_primary = account.is_primary
    was_workspace_default = account.is_workspace_default
    deleted_docs_count = disconnect_account(db, account)

    if was_primary:
        replacement = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.tenant_id == membership.tenant_id,
                GoogleUserConnector.user_id == membership.user_id,
            ).order_by(GoogleUserConnector.created_at.asc())
        ).scalars().first()
        if replacement and not replacement.is_primary:
            replacement.is_primary = True
            db.commit()

    if was_workspace_default:
        replacement_workspace = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.tenant_id == membership.tenant_id,
            ).order_by(GoogleUserConnector.created_at.asc())
        ).scalars().first()
        if replacement_workspace:
            set_workspace_default_account(db, tenant_id=membership.tenant_id, account_id=replacement_workspace.id)

    audit_event(
        db,
        event_type="google.oauth.disconnect",
        resource_type="google_connector_account",
        action="disconnect",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account_id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"deleted_docs_count": deleted_docs_count},
    )
    return {"message": "Google account disconnected", "deleted_docs_count": deleted_docs_count}


@router.get("/accounts/{account_id}/oauth/start", response_model=OAuthStartResponse)
def google_oauth_start(
    account_id: str,
    redirect_uri: str = Query(...),
    login_hint: str | None = Query(default=None),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, _ = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    auth_url, state = get_oauth_url(
        db,
        account,
        client_id=client_id,
        redirect_uri=redirect_uri,
        user_id=membership.user_id,
        login_hint=login_hint,
    )
    return OAuthStartResponse(auth_url=auth_url, state=state)


@router.get("/oauth/callback")
def google_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()

    state_row = db.execute(
        select(ConnectorOAuthState).where(
            ConnectorOAuthState.connector_type == "google",
            ConnectorOAuthState.state_token == state,
        )
    ).scalar_one_or_none()
    if not state_row:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    if state_row.tenant_id != membership.tenant_id or state_row.user_id != membership.user_id:
        raise HTTPException(status_code=403, detail="OAuth state does not belong to current user")

    if not state_row.connector_config_id:
        raise HTTPException(status_code=400, detail="OAuth state is missing account context")

    account = _get_owned_account(db, membership, state_row.connector_config_id)

    try:
        effective_account = complete_oauth(
            db,
            account,
            code=code,
            state=state,
            client_id=client_id,
            client_secret=client_secret,
            user_id=membership.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="google.oauth.connect",
        resource_type="google_connector_account",
        action="connect",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=effective_account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={
            "account_id": effective_account.id,
            "google_account_email": effective_account.google_account_email,
        },
    )
    return {"message": "Google OAuth completed"}


@router.post("/accounts/{account_id}/test", response_model=ConnectionTestResult)
def test_google(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    success, message = test_connection(db, account, client_id=client_id, client_secret=client_secret)
    return ConnectionTestResult(success=success, message=message)


@router.post("/accounts/{account_id}/sync", response_model=SyncResponse)
def sync_google(
    account_id: str,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)

    try:
        counts = sync_connector(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="google.sync.gmail",
        resource_type="google_connector_account",
        action="sync",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={
            "account_id": account.id,
            "google_account_email": account.google_account_email,
            "items_synced": counts["gmail"],
        },
    )
    audit_event(
        db,
        event_type="google.sync.calendar",
        resource_type="google_connector_account",
        action="sync",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={
            "account_id": account.id,
            "google_account_email": account.google_account_email,
            "items_synced": counts["calendar"],
        },
    )
    audit_event(
        db,
        event_type="google.sync.drive",
        resource_type="google_connector_account",
        action="sync",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"account_id": account.id, "google_account_email": account.google_account_email, "items_synced": counts["drive"]},
    )
    audit_event(
        db,
        event_type="google.sync.sheets",
        resource_type="google_connector_account",
        action="sync",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"account_id": account.id, "google_account_email": account.google_account_email, "items_synced": counts["sheets"]},
    )
    audit_event(
        db,
        event_type="google.sync.contacts",
        resource_type="google_connector_account",
        action="sync",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"account_id": account.id, "google_account_email": account.google_account_email, "items_synced": counts["contacts"]},
    )

    return SyncResponse(status="success", items_synced=counts["total"], message="Google sync completed")


@router.get("/accounts/{account_id}/sync-options")
def get_google_sync_options(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    account = _get_owned_account(db, membership, account_id)
    return {
        "sync_scope_configured": account.sync_scope_configured,
        "gmail_sync_mode": account.gmail_sync_mode,
        "gmail_last_n_days": account.gmail_last_n_days,
        "gmail_max_messages": account.gmail_max_messages,
        "gmail_query": account.gmail_query,
        "calendar_sync_mode": account.calendar_sync_mode,
        "calendar_days_back": account.calendar_days_back,
        "calendar_days_forward": account.calendar_days_forward,
        "calendar_max_events": account.calendar_max_events,
        "drive_enabled": account.drive_enabled,
        "drive_folder_ids": account.drive_folder_ids,
        "drive_file_ids": account.drive_file_ids,
        "sheets_enabled": account.sheets_enabled,
        "sheets_targets": account.sheets_targets,
        "contacts_enabled": account.contacts_enabled,
        "contacts_sync_mode": account.contacts_sync_mode,
        "contacts_group_ids": account.contacts_group_ids,
        "contacts_max_count": account.contacts_max_count,
        "validation": {
            "gmail_last_n_days": {"min": 1, "max": 3650},
            "gmail_max_messages": {"min": 1, "max": 5000},
            "calendar_days_back": {"min": 0, "max": 3650},
            "calendar_days_forward": {"min": 1, "max": 3650},
            "calendar_max_events": {"min": 1, "max": 5000},
            "contacts_max_count": {"min": 1, "max": 5000},
        },
    }


@router.put("/accounts/{account_id}/sync-options", response_model=GoogleAccountRead)
def update_google_sync_options(
    account_id: str,
    payload: GoogleSyncOptionsUpdate,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    _validate_sync_options(payload)
    account = _get_owned_account(db, membership, account_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(account, key, value)
    account.sync_scope_configured = True
    db.commit()
    db.refresh(account)
    return _read_model(account)


@router.get("/accounts/{account_id}/status", response_model=list[SyncRunRead])
def google_status(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    account = _get_owned_account(db, membership, account_id)

    runs = db.execute(
        select(ConnectorSyncRun)
        .where(
            ConnectorSyncRun.tenant_id == membership.tenant_id,
            ConnectorSyncRun.connector_type == "google",
            ConnectorSyncRun.connector_config_id == account.id,
        )
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


@router.get("/accounts/{account_id}/calendars", response_model=list[GoogleCalendarListItem])
def google_list_calendars(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    if not account.access_token_encrypted:
        raise HTTPException(status_code=400, detail="Google account is not connected yet")

    try:
        calendars = list_calendars(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [GoogleCalendarListItem(**item) for item in calendars]


@router.get("/accounts/{account_id}/drive/folders", response_model=list[GoogleDriveFolderItem])
def google_list_drive_folders(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    try:
        rows = list_drive_folders(db, account, client_id=client_id, client_secret=client_secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GoogleDriveFolderItem(**item) for item in rows]


@router.get("/accounts/{account_id}/drive/files", response_model=list[GoogleDriveFileItem])
def google_list_drive_files(
    account_id: str,
    folder_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    try:
        rows = list_drive_files(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
            folder_id=folder_id,
            query=q,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GoogleDriveFileItem(**item) for item in rows]


@router.get("/accounts/{account_id}/sheets/spreadsheets", response_model=list[GoogleSheetItem])
def google_list_sheets_spreadsheets(
    account_id: str,
    q: str | None = Query(default=None),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    try:
        rows = list_sheets_spreadsheets(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
            query=q,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GoogleSheetItem(**item) for item in rows]


@router.get("/accounts/{account_id}/sheets/{spreadsheet_id}/tabs", response_model=list[GoogleSheetTabItem])
def google_list_sheet_tabs(
    account_id: str,
    spreadsheet_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    try:
        rows = list_sheet_tabs(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
            spreadsheet_id=spreadsheet_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GoogleSheetTabItem(**item) for item in rows]


@router.get("/accounts/{account_id}/contacts/groups", response_model=list[GoogleContactGroupItem])
def google_list_contacts_groups(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)
    try:
        rows = list_contact_groups(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GoogleContactGroupItem(**item) for item in rows]


@router.post("/accounts/{account_id}/calendar/events", response_model=GoogleCalendarEventRead)
def create_google_calendar_event(
    account_id: str,
    payload: GoogleCalendarEventUpsert,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)

    try:
        event = create_event(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="google.calendar.create",
        resource_type="google_calendar_event",
        action="create",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=event["id"],
        request_id=request.headers.get("X-Request-ID"),
        payload={"account_id": account.id, "calendar_id": event["calendar_id"]},
    )
    return GoogleCalendarEventRead(**event)


@router.put("/accounts/{account_id}/calendar/events/{event_id}", response_model=GoogleCalendarEventRead)
def update_google_calendar_event(
    account_id: str,
    event_id: str,
    payload: GoogleCalendarEventUpsert,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)

    try:
        event = update_event(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
            event_id=event_id,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="google.calendar.update",
        resource_type="google_calendar_event",
        action="update",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=event_id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"account_id": account.id, "calendar_id": event["calendar_id"]},
    )
    return GoogleCalendarEventRead(**event)


@router.delete("/accounts/{account_id}/calendar/events/{event_id}")
def delete_google_calendar_event(
    account_id: str,
    request: Request,
    event_id: str,
    calendar_id: str = Query("primary"),
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
):
    client_id, client_secret = _ensure_oauth_settings()
    account = _get_owned_account(db, membership, account_id)

    try:
        delete_event(
            db,
            account,
            client_id=client_id,
            client_secret=client_secret,
            calendar_id=calendar_id,
            event_id=event_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        event_type="google.calendar.delete",
        resource_type="google_calendar_event",
        action="delete",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=event_id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"account_id": account.id, "calendar_id": calendar_id},
    )
    return {"message": "Google calendar event deleted"}
