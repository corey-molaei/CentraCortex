from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy import String, and_, cast, desc, or_, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def query_audit_logs(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    event_type: str | None,
    tool: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    limit: int,
    offset: int,
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)

    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if event_type:
        stmt = stmt.where(AuditLog.event_type.ilike(f"%{event_type}%"))
    if tool:
        stmt = stmt.where(
            or_(
                and_(AuditLog.resource_type == "tool", AuditLog.resource_id == tool),
                and_(AuditLog.resource_type == "tool_approval", AuditLog.resource_id == tool),
                cast(AuditLog.payload, String).ilike(f"%{tool}%"),
            )
        )
    if start_at:
        stmt = stmt.where(AuditLog.created_at >= start_at)
    if end_at:
        stmt = stmt.where(AuditLog.created_at <= end_at)

    stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
    return db.execute(stmt).scalars().all()


def serialize_audit_log(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "tenant_id": log.tenant_id,
        "user_id": log.user_id,
        "event_type": log.event_type,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "action": log.action,
        "request_id": log.request_id,
        "ip_address": log.ip_address,
        "payload": log.payload,
        "created_at": log.created_at,
    }


def audit_logs_to_csv(logs: list[AuditLog]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "tenant_id",
            "user_id",
            "event_type",
            "resource_type",
            "resource_id",
            "action",
            "request_id",
            "ip_address",
            "payload",
            "created_at",
        ]
    )

    for log in logs:
        writer.writerow(
            [
                log.id,
                log.tenant_id,
                log.user_id,
                log.event_type,
                log.resource_type,
                log.resource_id,
                log.action,
                log.request_id,
                log.ip_address,
                log.payload,
                log.created_at.isoformat() if log.created_at else "",
            ]
        )

    return buffer.getvalue()
