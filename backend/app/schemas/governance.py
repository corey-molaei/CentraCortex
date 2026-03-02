from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogRead(BaseModel):
    id: str
    tenant_id: str | None = None
    user_id: str | None = None
    event_type: str
    resource_type: str
    resource_id: str | None = None
    action: str
    request_id: str | None = None
    ip_address: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class AuditLogQuery(BaseModel):
    tenant_id: str | None = None
    user_id: str | None = None
    event_type: str | None = None
    tool: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
