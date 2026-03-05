"""chat conversation provider pinning

Revision ID: 20260303_0016
Revises: 20260302_0015
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260303_0016"
down_revision = "20260302_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_conversations", sa.Column("pinned_provider_id", sa.String(length=36), nullable=True))
    op.add_column("chat_conversations", sa.Column("pinned_provider_name", sa.String(length=255), nullable=True))
    op.add_column("chat_conversations", sa.Column("pinned_model_name", sa.String(length=255), nullable=True))
    op.add_column("chat_conversations", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_chat_conversations_pinned_provider_id"),
        "chat_conversations",
        ["pinned_provider_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_conversations_pinned_provider_id"), table_name="chat_conversations")
    op.drop_column("chat_conversations", "pinned_at")
    op.drop_column("chat_conversations", "pinned_model_name")
    op.drop_column("chat_conversations", "pinned_provider_name")
    op.drop_column("chat_conversations", "pinned_provider_id")
