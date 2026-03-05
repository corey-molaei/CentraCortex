import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceSettings(Base):
    __tablename__ = "workspace_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(128), default="UTC", nullable=False)
    default_email_signature: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    fallback_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    escalation_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    working_hours_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    allowed_actions_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {
            "email_send": True,
            "email_reply": True,
            "calendar_create": True,
            "calendar_update": True,
            "calendar_delete": True,
        },
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
