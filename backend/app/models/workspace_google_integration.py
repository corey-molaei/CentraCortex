import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceGoogleIntegration(Base):
    __tablename__ = "workspace_google_integrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)

    google_account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    google_account_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    gmail_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    gmail_labels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["INBOX", "SENT"], nullable=False)

    calendar_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    calendar_ids: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["primary"], nullable=False)

    drive_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drive_folder_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    sheets_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sheets_targets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    crm_sheet_spreadsheet_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    crm_sheet_tab_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_items_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
