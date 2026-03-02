"""chat calendar pending actions and google primary account

Revision ID: 20260223_0012
Revises: 20260223_0011
Create Date: 2026-02-23
"""

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "20260223_0012"
down_revision = "20260223_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "google_user_connectors",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(op.f("ix_google_user_connectors_is_primary"), "google_user_connectors", ["is_primary"], unique=False)

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT id, tenant_id, user_id, google_account_sub, access_token_encrypted
            FROM google_user_connectors
            ORDER BY tenant_id, user_id, created_at ASC
            """
        )
    ).mappings().all()

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["tenant_id"], row["user_id"])].append(dict(row))

    primary_ids: list[str] = []
    for group_rows in grouped.values():
        connected = [
            row
            for row in group_rows
            if row.get("google_account_sub") and row.get("access_token_encrypted")
        ]
        selected = connected[0] if connected else group_rows[0]
        primary_ids.append(str(selected["id"]))

    for connector_id in primary_ids:
        conn.execute(
            sa.text("UPDATE google_user_connectors SET is_primary = true WHERE id = :connector_id"),
            {"connector_id": connector_id},
        )

    op.alter_column("google_user_connectors", "is_primary", server_default=None)

    op.create_table(
        "chat_pending_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["google_user_connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_pending_actions_tenant_id"), "chat_pending_actions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_chat_pending_actions_user_id"), "chat_pending_actions", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_chat_pending_actions_conversation_id"),
        "chat_pending_actions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_chat_pending_actions_action_type"), "chat_pending_actions", ["action_type"], unique=False)
    op.create_index(op.f("ix_chat_pending_actions_status"), "chat_pending_actions", ["status"], unique=False)
    op.create_index(op.f("ix_chat_pending_actions_account_id"), "chat_pending_actions", ["account_id"], unique=False)
    op.create_index(op.f("ix_chat_pending_actions_expires_at"), "chat_pending_actions", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_pending_actions_expires_at"), table_name="chat_pending_actions")
    op.drop_index(op.f("ix_chat_pending_actions_account_id"), table_name="chat_pending_actions")
    op.drop_index(op.f("ix_chat_pending_actions_status"), table_name="chat_pending_actions")
    op.drop_index(op.f("ix_chat_pending_actions_action_type"), table_name="chat_pending_actions")
    op.drop_index(op.f("ix_chat_pending_actions_conversation_id"), table_name="chat_pending_actions")
    op.drop_index(op.f("ix_chat_pending_actions_user_id"), table_name="chat_pending_actions")
    op.drop_index(op.f("ix_chat_pending_actions_tenant_id"), table_name="chat_pending_actions")
    op.drop_table("chat_pending_actions")

    op.drop_index(op.f("ix_google_user_connectors_is_primary"), table_name="google_user_connectors")
    op.drop_column("google_user_connectors", "is_primary")
