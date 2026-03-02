from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def audit_event(
    db: Session,
    *,
    event_type: str,
    resource_type: str,
    action: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            event_type=event_type,
            resource_type=resource_type,
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=resource_id,
            request_id=request_id,
            ip_address=ip_address,
            payload=payload,
        )
    )
    db.commit()
