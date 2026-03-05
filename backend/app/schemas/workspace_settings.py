from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkspaceAllowedActions(BaseModel):
    email_send: bool = True
    email_reply: bool = True
    calendar_create: bool = True
    calendar_update: bool = True
    calendar_delete: bool = True


class WorkspaceSettingsRead(BaseModel):
    tenant_id: str
    business_name: str | None = None
    timezone: str = "UTC"
    default_email_signature: str | None = None
    fallback_contact: str | None = None
    escalation_email: str | None = None
    working_hours_json: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: WorkspaceAllowedActions = Field(default_factory=WorkspaceAllowedActions)
    updated_at: datetime | None = None


class WorkspaceSettingsUpdate(BaseModel):
    business_name: str | None = None
    timezone: str | None = None
    default_email_signature: str | None = None
    fallback_contact: str | None = None
    escalation_email: str | None = None
    working_hours_json: dict[str, Any] | None = None
    allowed_actions: WorkspaceAllowedActions | None = None
