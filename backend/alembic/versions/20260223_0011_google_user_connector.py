"""google user connector hard replace

Revision ID: 20260223_0011
Revises: 20260223_0010
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260223_0011"
down_revision = "20260223_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_user_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("google_account_email", sa.String(length=320), nullable=True),
        sa.Column("google_account_sub", sa.String(length=255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("gmail_labels", sa.JSON(), nullable=False),
        sa.Column("gmail_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("calendar_ids", sa.JSON(), nullable=False),
        sa.Column("calendar_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("private_acl_policy_id", sa.String(length=36), nullable=True),
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_items_synced", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["private_acl_policy_id"], ["acl_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "google_account_sub", name="uq_google_user_connector_user_sub"),
    )
    op.create_index(op.f("ix_google_user_connectors_tenant_id"), "google_user_connectors", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_google_user_connectors_user_id"), "google_user_connectors", ["user_id"], unique=False)
    op.create_index(op.f("ix_google_user_connectors_google_account_sub"), "google_user_connectors", ["google_account_sub"], unique=False)

    op.add_column("connector_oauth_states", sa.Column("user_id", sa.String(length=36), nullable=True))
    op.add_column("connector_oauth_states", sa.Column("connector_config_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_connector_oauth_states_user_id"), "connector_oauth_states", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_connector_oauth_states_connector_config_id"),
        "connector_oauth_states",
        ["connector_config_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_connector_oauth_states_user_id_users",
        "connector_oauth_states",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        sa.text(
            "UPDATE documents SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE source_type IN ('google_gmail', 'google_calendar') AND deleted_at IS NULL"
        )
    )

    op.drop_table("google_connectors")


def downgrade() -> None:
    op.create_table(
        "google_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("google_account_email", sa.String(length=320), nullable=True),
        sa.Column("access_token_encrypted", sa.String(length=4096), nullable=True),
        sa.Column("refresh_token_encrypted", sa.String(length=4096), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("gmail_labels", sa.JSON(), nullable=False),
        sa.Column("gmail_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("calendar_ids", sa.JSON(), nullable=False),
        sa.Column("calendar_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_items_synced", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.drop_constraint("fk_connector_oauth_states_user_id_users", "connector_oauth_states", type_="foreignkey")
    op.drop_index(op.f("ix_connector_oauth_states_connector_config_id"), table_name="connector_oauth_states")
    op.drop_index(op.f("ix_connector_oauth_states_user_id"), table_name="connector_oauth_states")
    op.drop_column("connector_oauth_states", "connector_config_id")
    op.drop_column("connector_oauth_states", "user_id")

    op.drop_index(op.f("ix_google_user_connectors_google_account_sub"), table_name="google_user_connectors")
    op.drop_index(op.f("ix_google_user_connectors_user_id"), table_name="google_user_connectors")
    op.drop_index(op.f("ix_google_user_connectors_tenant_id"), table_name="google_user_connectors")
    op.drop_table("google_user_connectors")
