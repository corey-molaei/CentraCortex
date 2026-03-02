import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CodeRepoConnector(Base):
    __tablename__ = "code_repo_connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(20), default="github", nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    token_encrypted: Mapped[str] = mapped_column(String(2048), nullable=False)
    repositories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    include_readme: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_issues: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_prs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_wiki: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_items_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
