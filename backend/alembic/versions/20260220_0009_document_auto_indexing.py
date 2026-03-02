"""document auto indexing state

Revision ID: 20260220_0009
Revises: 20260218_0008
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260220_0009"
down_revision = "20260218_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("index_status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
    )
    op.add_column("documents", sa.Column("index_error", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("index_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("documents", sa.Column("index_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("next_index_attempt_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_documents_index_status", "documents", ["index_status"])
    op.create_index("ix_documents_next_index_attempt_at", "documents", ["next_index_attempt_at"])

    op.execute(
        """
        UPDATE documents
        SET
            index_status = CASE
                WHEN COALESCE(current_chunk_version, 0) > 0 THEN 'indexed'
                ELSE 'pending'
            END,
            index_requested_at = CASE
                WHEN COALESCE(current_chunk_version, 0) > 0 THEN indexed_at
                ELSE created_at
            END,
            next_index_attempt_at = CASE
                WHEN COALESCE(current_chunk_version, 0) > 0 THEN NULL
                ELSE created_at
            END,
            index_attempts = 0,
            index_error = NULL
        """
    )

    op.alter_column("documents", "index_status", server_default=None)
    op.alter_column("documents", "index_attempts", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_documents_next_index_attempt_at", table_name="documents")
    op.drop_index("ix_documents_index_status", table_name="documents")

    op.drop_column("documents", "next_index_attempt_at")
    op.drop_column("documents", "index_requested_at")
    op.drop_column("documents", "index_attempts")
    op.drop_column("documents", "index_error")
    op.drop_column("documents", "index_status")
