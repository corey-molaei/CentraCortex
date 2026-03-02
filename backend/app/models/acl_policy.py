import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ACLPolicy(Base):
    __tablename__ = "acl_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(50), index=True)  # document/tool/data_source
    resource_id: Mapped[str] = mapped_column(String(255), index=True)  # explicit id or '*'
    allow_all: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_user_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_group_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_role_names: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
