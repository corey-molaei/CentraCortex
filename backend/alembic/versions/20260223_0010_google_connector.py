"""google connector

Revision ID: 20260223_0010
Revises: 20260220_0009
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260223_0010"
down_revision = "20260220_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("google_connectors")
