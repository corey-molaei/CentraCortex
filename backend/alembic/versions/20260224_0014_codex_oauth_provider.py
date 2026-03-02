"""tenant codex oauth provider support

Revision ID: 20260224_0014
Revises: 20260224_0013
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260224_0014"
down_revision = "20260224_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_codex_oauth_apps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("client_secret_encrypted", sa.String(length=4096), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_index(op.f("ix_tenant_codex_oauth_apps_tenant_id"), "tenant_codex_oauth_apps", ["tenant_id"], unique=False)

    op.create_table(
        "tenant_codex_oauth_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("access_token_encrypted", sa.String(length=8192), nullable=False),
        sa.Column("refresh_token_encrypted", sa.String(length=8192), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("connected_email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_index(op.f("ix_tenant_codex_oauth_tokens_tenant_id"), "tenant_codex_oauth_tokens", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_codex_oauth_tokens_tenant_id"), table_name="tenant_codex_oauth_tokens")
    op.drop_table("tenant_codex_oauth_tokens")

    op.drop_index(op.f("ix_tenant_codex_oauth_apps_tenant_id"), table_name="tenant_codex_oauth_apps")
    op.drop_table("tenant_codex_oauth_apps")
