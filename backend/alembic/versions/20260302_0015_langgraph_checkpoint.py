"""langgraph checkpoint state tables

Revision ID: 20260302_0015
Revises: 20260224_0014
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260302_0015"
down_revision = "20260224_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "langgraph_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("graph_name", sa.String(length=100), nullable=False),
        sa.Column("node_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_langgraph_checkpoints_tenant_id"), "langgraph_checkpoints", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_langgraph_checkpoints_user_id"), "langgraph_checkpoints", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_langgraph_checkpoints_conversation_id"),
        "langgraph_checkpoints",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_langgraph_checkpoints_thread_id"), "langgraph_checkpoints", ["thread_id"], unique=False)
    op.create_index(op.f("ix_langgraph_checkpoints_graph_name"), "langgraph_checkpoints", ["graph_name"], unique=False)
    op.create_index(op.f("ix_langgraph_checkpoints_node_name"), "langgraph_checkpoints", ["node_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_langgraph_checkpoints_node_name"), table_name="langgraph_checkpoints")
    op.drop_index(op.f("ix_langgraph_checkpoints_graph_name"), table_name="langgraph_checkpoints")
    op.drop_index(op.f("ix_langgraph_checkpoints_thread_id"), table_name="langgraph_checkpoints")
    op.drop_index(op.f("ix_langgraph_checkpoints_conversation_id"), table_name="langgraph_checkpoints")
    op.drop_index(op.f("ix_langgraph_checkpoints_user_id"), table_name="langgraph_checkpoints")
    op.drop_index(op.f("ix_langgraph_checkpoints_tenant_id"), table_name="langgraph_checkpoints")
    op.drop_table("langgraph_checkpoints")
