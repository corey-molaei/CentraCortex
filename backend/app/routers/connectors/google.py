from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
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
    sync_connector,
    test_connection,
    update_event,
)

router = APIRouter(prefix="/connectors/google", tags=["connectors-google"])


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
        scopes=connector.scopes,
        gmail_enabled=connector.gmail_enabled,
        gmail_labels=connector.gmail_labels,
        calendar_enabled=connector.calendar_enabled,
        calendar_ids=connector.calendar_ids,
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
    existing_primary = db.execute(
        select(GoogleUserConnector.id).where(
            GoogleUserConnector.tenant_id == membership.tenant_id,
            GoogleUserConnector.user_id == membership.user_id,
            GoogleUserConnector.is_primary.is_(True),
        )
    ).scalar_one_or_none()

    account = GoogleUserConnector(
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        label=payload.label,
        enabled=payload.enabled,
        is_primary=existing_primary is None,
        gmail_enabled=payload.gmail_enabled,
        gmail_labels=payload.gmail_labels,
        calendar_enabled=payload.calendar_enabled,
        calendar_ids=payload.calendar_ids,
    )
    db.add(account)
    db.commit()
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
        complete_oauth(
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
        resource_id=account.id,
        request_id=request.headers.get("X-Request-ID"),
        payload={
            "account_id": account.id,
            "google_account_email": account.google_account_email,
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
        total, gmail_count, calendar_count = sync_connector(
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
            "items_synced": gmail_count,
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
            "items_synced": calendar_count,
        },
    )

    return SyncResponse(status="success", items_synced=total, message="Google sync completed")


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
