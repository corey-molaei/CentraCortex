import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChannelFacebookConnector(Base):
    __tablename__ = "channel_facebook_connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    page_access_token_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    page_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    app_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    app_secret_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    verify_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
