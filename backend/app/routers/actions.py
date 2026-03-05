from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant_membership, get_db
from app.core.config import settings
from app.models.action_undo_log import ActionUndoLog
from app.models.tenant_membership import TenantMembership
from app.schemas.actions import UndoResponse
from app.services.audit import audit_event
from app.services.connectors.google_service import delete_event as google_delete_event
from app.services.connectors.google_service import get_primary_account

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/{action_id}/undo", response_model=UndoResponse)
def undo_action(
    action_id: str,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    db: Session = Depends(get_db),
) -> UndoResponse:
    action = db.execute(
        select(ActionUndoLog).where(
            ActionUndoLog.id == action_id,
            ActionUndoLog.tenant_id == membership.tenant_id,
        )
    ).scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=404, detail="Undo action not found")
    if action.undone:
        raise HTTPException(status_code=400, detail="Undo action already used")
    if action.expires_at and action.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Undo action has expired")

    payload = action.undo_payload_json or {}

    if action.action_type == "calendar_create":
        account = get_primary_account(db, tenant_id=membership.tenant_id, user_id=membership.user_id)
        if not account:
            raise HTTPException(status_code=400, detail="No connected Google account for undo")
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(status_code=400, detail="Google OAuth credentials are not configured")
        calendar_id = str(payload.get("calendar_id") or "primary")
        event_id = str(payload.get("event_id") or "")
        if not event_id:
            raise HTTPException(status_code=400, detail="Undo payload is missing event id")
        try:
            google_delete_event(
                db,
                account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                calendar_id=calendar_id,
                event_id=event_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Undo failed: {exc}") from exc
    else:
        raise HTTPException(status_code=400, detail="Undo is not supported for this action")

    action.undone = True
    db.commit()
    audit_event(
        db,
        event_type="action.undo",
        resource_type=action.resource_type,
        action="undo",
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        resource_id=action.resource_id,
        payload={"action_id": action.id, "action_type": action.action_type},
    )
    return UndoResponse(status="ok", message="Action has been undone")
