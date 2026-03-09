import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GoogleUserConnector(Base):
    __tablename__ = "google_user_connectors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "google_account_sub", name="uq_google_user_connector_user_sub"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)

    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    google_account_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    gmail_labels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["INBOX", "SENT"], nullable=False)
    gmail_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    gmail_sync_mode: Mapped[str] = mapped_column(String(32), default="last_n_days", nullable=False)
    gmail_last_n_days: Mapped[int | None] = mapped_column(Integer, default=30, nullable=True)
    gmail_max_messages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gmail_query: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    calendar_ids: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["primary"], nullable=False)
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    calendar_sync_mode: Mapped[str] = mapped_column(String(32), default="range_days", nullable=False)
    calendar_days_back: Mapped[int | None] = mapped_column(Integer, default=30, nullable=True)
    calendar_days_forward: Mapped[int | None] = mapped_column(Integer, default=90, nullable=True)
    calendar_max_events: Mapped[int | None] = mapped_column(Integer, nullable=True)

    drive_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drive_folder_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    drive_file_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    sheets_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sheets_targets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    contacts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contacts_sync_mode: Mapped[str] = mapped_column(String(32), default="all", nullable=False)
    contacts_group_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    contacts_max_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    meet_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    crm_sheet_spreadsheet_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    crm_sheet_tab_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sync_scope_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    private_acl_policy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("acl_policies.id", ondelete="SET NULL"), nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_workspace_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_items_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
