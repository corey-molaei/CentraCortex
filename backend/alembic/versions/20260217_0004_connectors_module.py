"""connectors module

Revision ID: 20260217_0004
Revises: 20260217_0003
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260217_0004"
down_revision = "20260217_0003"
branch_labels = None
depends_on = None


def _connector_common_columns() -> list[sa.Column]:
    return [
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_items_synced", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("documents", sa.Column("url", sa.String(length=1024), nullable=True))
    op.add_column("documents", sa.Column("author", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column(
        "documents",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "connector_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connector_type", sa.String(length=50), nullable=False),
        sa.Column("connector_config_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("items_synced", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connector_sync_runs_tenant_id", "connector_sync_runs", ["tenant_id"])
    op.create_index("ix_connector_sync_runs_connector_type", "connector_sync_runs", ["connector_type"])
    op.create_index("ix_connector_sync_runs_status", "connector_sync_runs", ["status"])

    op.create_table(
        "connector_oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connector_type", sa.String(length=50), nullable=False),
        sa.Column("state_token", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_token"),
    )
    op.create_index("ix_connector_oauth_states_tenant_id", "connector_oauth_states", ["tenant_id"])
    op.create_index("ix_connector_oauth_states_connector_type", "connector_oauth_states", ["connector_type"])

    op.create_table(
        "jira_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("api_token_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("project_keys", sa.JSON(), nullable=False),
        sa.Column("issue_types", sa.JSON(), nullable=False),
        sa.Column("fields_mapping", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "slack_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_name", sa.String(length=255), nullable=True),
        sa.Column("bot_token_encrypted", sa.String(length=2048), nullable=True),
        sa.Column("team_id", sa.String(length=64), nullable=True),
        sa.Column("channel_ids", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "email_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False, server_default=sa.text("993")),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("password_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("use_ssl", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("folders", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "code_repo_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="github"),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("token_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("repositories", sa.JSON(), nullable=False),
        sa.Column("include_readme", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_issues", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_prs", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_wiki", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "confluence_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("api_token_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("space_keys", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "sharepoint_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("azure_tenant_id", sa.String(length=128), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("site_ids", sa.JSON(), nullable=False),
        sa.Column("drive_ids", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "db_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_uri_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("table_allowlist", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "logs_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("folder_path", sa.String(length=1024), nullable=False),
        sa.Column("file_glob", sa.String(length=255), nullable=False, server_default="*.log"),
        sa.Column("parser_type", sa.String(length=20), nullable=False, server_default="plain"),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    op.create_table(
        "file_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("allowed_extensions", sa.JSON(), nullable=False),
        *_connector_common_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("file_connectors")
    op.drop_table("logs_connectors")
    op.drop_table("db_connectors")
    op.drop_table("sharepoint_connectors")
    op.drop_table("confluence_connectors")
    op.drop_table("code_repo_connectors")
    op.drop_table("email_connectors")
    op.drop_table("slack_connectors")
    op.drop_table("jira_connectors")

    op.drop_index("ix_connector_oauth_states_connector_type", table_name="connector_oauth_states")
    op.drop_index("ix_connector_oauth_states_tenant_id", table_name="connector_oauth_states")
    op.drop_table("connector_oauth_states")

    op.drop_index("ix_connector_sync_runs_status", table_name="connector_sync_runs")
    op.drop_index("ix_connector_sync_runs_connector_type", table_name="connector_sync_runs")
    op.drop_index("ix_connector_sync_runs_tenant_id", table_name="connector_sync_runs")
    op.drop_table("connector_sync_runs")

    op.drop_column("documents", "updated_at")
    op.drop_column("documents", "metadata_json")
    op.drop_column("documents", "source_updated_at")
    op.drop_column("documents", "source_created_at")
    op.drop_column("documents", "author")
    op.drop_column("documents", "url")
