"""per-user email connector and chat pending email actions

Revision ID: 20260224_0013
Revises: 20260223_0012
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260224_0013"
down_revision = "20260223_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_user_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False, server_default=sa.text("993")),
        sa.Column("use_ssl", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_use_starttls", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("folders", sa.JSON(), nullable=False),
        sa.Column("private_acl_policy_id", sa.String(length=36), nullable=True),
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_items_synced", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["private_acl_policy_id"], ["acl_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "email_address", name="uq_email_user_connector_user_address"),
    )
    op.create_index(op.f("ix_email_user_connectors_tenant_id"), "email_user_connectors", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_email_user_connectors_user_id"), "email_user_connectors", ["user_id"], unique=False)
    op.create_index(op.f("ix_email_user_connectors_email_address"), "email_user_connectors", ["email_address"], unique=False)
    op.create_index(op.f("ix_email_user_connectors_is_primary"), "email_user_connectors", ["is_primary"], unique=False)

    op.create_table(
        "chat_pending_email_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_tenant_id"),
        "chat_pending_email_actions",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_user_id"),
        "chat_pending_email_actions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_conversation_id"),
        "chat_pending_email_actions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_account_type"),
        "chat_pending_email_actions",
        ["account_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_account_id"),
        "chat_pending_email_actions",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_status"),
        "chat_pending_email_actions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_pending_email_actions_expires_at"),
        "chat_pending_email_actions",
        ["expires_at"],
        unique=False,
    )

    op.execute(
        sa.text(
            "UPDATE documents SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE source_type = 'email' AND deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_pending_email_actions_expires_at"), table_name="chat_pending_email_actions")
    op.drop_index(op.f("ix_chat_pending_email_actions_status"), table_name="chat_pending_email_actions")
    op.drop_index(op.f("ix_chat_pending_email_actions_account_id"), table_name="chat_pending_email_actions")
    op.drop_index(op.f("ix_chat_pending_email_actions_account_type"), table_name="chat_pending_email_actions")
    op.drop_index(op.f("ix_chat_pending_email_actions_conversation_id"), table_name="chat_pending_email_actions")
    op.drop_index(op.f("ix_chat_pending_email_actions_user_id"), table_name="chat_pending_email_actions")
    op.drop_index(op.f("ix_chat_pending_email_actions_tenant_id"), table_name="chat_pending_email_actions")
    op.drop_table("chat_pending_email_actions")

    op.drop_index(op.f("ix_email_user_connectors_is_primary"), table_name="email_user_connectors")
    op.drop_index(op.f("ix_email_user_connectors_email_address"), table_name="email_user_connectors")
    op.drop_index(op.f("ix_email_user_connectors_user_id"), table_name="email_user_connectors")
    op.drop_index(op.f("ix_email_user_connectors_tenant_id"), table_name="email_user_connectors")
    op.drop_table("email_user_connectors")
