from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db
from app.core.security import encrypt_secret
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.email_user_connector import EmailUserConnector
from app.models.tenant_membership import TenantMembership
from app.schemas.connectors.common import ConnectionTestResult, ConnectorStatus, SyncResponse, SyncRunRead
from app.schemas.connectors.email import EmailAccountCreate, EmailAccountRead, EmailAccountUpdate
from app.services.audit import audit_event
from app.services.connectors.common import connector_status_payload
from app.services.connectors.email_user_service import disconnect_account, sync_connector, test_connection

router = APIRouter(prefix="/connectors/email", tags=["connectors-email"])


def _read_model(account: EmailUserConnector) -> EmailAccountRead:
    return EmailAccountRead(
        id=account.id,
        tenant_id=account.tenant_id,
        user_id=account.user_id,
        label=account.label,
        email_address=account.email_address,
        username=account.username,
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        use_ssl=account.use_ssl,
        smtp_host=account.smtp_host,
        smtp_port=account.smtp_port,
        smtp_use_starttls=account.smtp_use_starttls,
        folders=account.folders,
        is_primary=account.is_primary,
        status=ConnectorStatus(**connector_status_payload(account)),
    )


def _get_owned_account(db: Session, membership: TenantMembership, account_id: str) -> EmailUserConnector:
    account = db.execute(
        select(EmailUserConnector).where(
            EmailUserConnector.id == account_id,
            EmailUserConnector.tenant_id == membership.tenant_id,
            EmailUserConnector.user_id == membership.user_id,
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Email account not found")
    return account


@router.get("/config")
def legacy_email_config_get() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/email/accounts")


@router.put("/config")
def legacy_email_config_put() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/email/accounts")


@router.post("/test")
def legacy_email_test() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/email/accounts")


@router.post("/sync")
def legacy_email_sync() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/email/accounts")


@router.get("/status")
def legacy_email_status() -> None:
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /api/v1/connectors/email/accounts")


@router.get("/accounts", response_model=list[EmailAccountRead])
def list_email_accounts(
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[EmailAccountRead]:
    accounts = db.execute(
        select(EmailUserConnector)
        .where(
            EmailUserConnector.tenant_id == membership.tenant_id,
            EmailUserConnector.user_id == membership.user_id,
        )
        .order_by(EmailUserConnector.created_at.desc())
    ).scalars().all()
    return [_read_model(account) for account in accounts]


@router.post("/accounts", response_model=EmailAccountRead)
def create_email_account(
    payload: EmailAccountCreate,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> EmailAccountRead:
    existing_primary = db.execute(
        select(EmailUserConnector.id).where(
            EmailUserConnector.tenant_id == membership.tenant_id,
            EmailUserConnector.user_id == membership.user_id,
            EmailUserConnector.is_primary.is_(True),
        )
    ).scalar_one_or_none()

    account = EmailUserConnector(
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        label=payload.label,
        email_address=payload.email_address,
        username=payload.username,
        password_encrypted=encrypt_secret(payload.password),
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        use_ssl=payload.use_ssl,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_use_starttls=payload.smtp_use_starttls,
        folders=payload.folders,
        enabled=payload.enabled,
        is_primary=existing_primary is None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _read_model(account)


@router.patch("/accounts/{account_id}", response_model=EmailAccountRead)
def update_email_account(
    account_id: str,
    payload: EmailAccountUpdate,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> EmailAccountRead:
    account = _get_owned_account(db, membership, account_id)

    updates = payload.model_dump(exclude_unset=True)
    set_primary = updates.pop("is_primary", None)
    password = updates.pop("password", None)
    if password:
        account.password_encrypted = encrypt_secret(password)
    for key, value in updates.items():
        setattr(account, key, value)

    if set_primary is True:
        others = db.execute(
            select(EmailUserConnector).where(
                EmailUserConnector.tenant_id == membership.tenant_id,
                EmailUserConnector.user_id == membership.user_id,
                EmailUserConnector.id != account.id,
            )
        ).scalars().all()
        for other in others:
            other.is_primary = False
        account.is_primary = True
    elif set_primary is False and account.is_primary:
        replacement = db.execute(
            select(EmailUserConnector).where(
                EmailUserConnector.tenant_id == membership.tenant_id,
                EmailUserConnector.user_id == membership.user_id,
                EmailUserConnector.id != account.id,
            )
        ).scalars().first()
        if replacement is None:
            raise HTTPException(status_code=400, detail="At least one primary email account is required")
        account.is_primary = False
        replacement.is_primary = True

    db.commit()
    db.refresh(account)
    return _read_model(account)


@router.delete("/accounts/{account_id}")
def delete_email_account(
    account_id: str,
    request: Request,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> dict:
    account = _get_owned_account(db, membership, account_id)
    was_primary = account.is_primary
    deleted_docs_count = disconnect_account(db, account)

    if was_primary:
        replacement = db.execute(
            select(EmailUserConnector).where(
                EmailUserConnector.tenant_id == membership.tenant_id,
                EmailUserConnector.user_id == membership.user_id,
            ).order_by(EmailUserConnector.created_at.asc())
        ).scalars().first()
        if replacement and not replacement.is_primary:
            replacement.is_primary = True
            db.commit()

    audit_event(
        db,
        event_type="email.oauth.disconnect",
        resource_type="email_user_connector",
        action="disconnect",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=account_id,
        request_id=request.headers.get("X-Request-ID"),
        payload={"deleted_docs_count": deleted_docs_count},
    )
    return {"message": "Email account disconnected", "deleted_docs_count": deleted_docs_count}


@router.post("/accounts/{account_id}/test", response_model=ConnectionTestResult)
def test_email_account(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> ConnectionTestResult:
    account = _get_owned_account(db, membership, account_id)
    success, message = test_connection(account)
    return ConnectionTestResult(success=success, message=message)


@router.post("/accounts/{account_id}/sync", response_model=SyncResponse)
def sync_email_account(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> SyncResponse:
    account = _get_owned_account(db, membership, account_id)
    items = sync_connector(db, account)
    return SyncResponse(status="success", items_synced=items, message="Email sync completed")


@router.get("/accounts/{account_id}/status", response_model=list[SyncRunRead])
def email_account_status(
    account_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> list[SyncRunRead]:
    _get_owned_account(db, membership, account_id)
    runs = db.execute(
        select(ConnectorSyncRun)
        .where(
            ConnectorSyncRun.tenant_id == membership.tenant_id,
            ConnectorSyncRun.connector_type == "email_user",
            ConnectorSyncRun.connector_config_id == account_id,
        )
        .order_by(ConnectorSyncRun.started_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        SyncRunRead(
            id=run.id,
            connector_type=run.connector_type,
            connector_config_id=run.connector_config_id,
            status=run.status,
            items_synced=run.items_synced,
            error_message=run.error_message,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        for run in runs
    ]
