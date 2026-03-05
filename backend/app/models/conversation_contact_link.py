import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationContactLink(Base):
    __tablename__ = "conversation_contact_links"
    __table_args__ = (
        UniqueConstraint("conversation_id", "contact_id", name="uq_conversation_contact"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace_contacts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
