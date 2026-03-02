"""agent builder versioning and style examples

Revision ID: 20260218_0008
Revises: 20260218_0007
Create Date: 2026-02-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260218_0008"
down_revision = "20260218_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_spec_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("source_prompt", sa.Text(), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("selected_tools_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("selected_data_sources_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tone_profile_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("generated_tests_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_note", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_definitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_agent_spec_versions_agent_version"),
    )
    op.create_index("ix_agent_spec_versions_tenant_id", "agent_spec_versions", ["tenant_id"])
    op.create_index("ix_agent_spec_versions_agent_id", "agent_spec_versions", ["agent_id"])
    op.create_index("ix_agent_spec_versions_status", "agent_spec_versions", ["status"])

    op.create_table(
        "agent_style_examples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_definitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["agent_spec_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_style_examples_tenant_id", "agent_style_examples", ["tenant_id"])
    op.create_index("ix_agent_style_examples_agent_id", "agent_style_examples", ["agent_id"])
    op.create_index("ix_agent_style_examples_version_id", "agent_style_examples", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_style_examples_version_id", table_name="agent_style_examples")
    op.drop_index("ix_agent_style_examples_agent_id", table_name="agent_style_examples")
    op.drop_index("ix_agent_style_examples_tenant_id", table_name="agent_style_examples")
    op.drop_table("agent_style_examples")

    op.drop_index("ix_agent_spec_versions_status", table_name="agent_spec_versions")
    op.drop_index("ix_agent_spec_versions_agent_id", table_name="agent_spec_versions")
    op.drop_index("ix_agent_spec_versions_tenant_id", table_name="agent_spec_versions")
    op.drop_table("agent_spec_versions")
