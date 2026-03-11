"""add active conversation pointer to workspace contacts

Revision ID: 20260311_0019
Revises: 20260309_0018
Create Date: 2026-03-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260311_0019"
down_revision = "20260309_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_contacts", sa.Column("active_conversation_id", sa.String(length=36), nullable=True))
    op.create_index(
        op.f("ix_workspace_contacts_active_conversation_id"),
        "workspace_contacts",
        ["active_conversation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_workspace_contacts_active_conversation_id_chat_conversations",
        "workspace_contacts",
        "chat_conversations",
        ["active_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_workspace_contacts_active_conversation_id_chat_conversations",
        "workspace_contacts",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_workspace_contacts_active_conversation_id"), table_name="workspace_contacts")
    op.drop_column("workspace_contacts", "active_conversation_id")
